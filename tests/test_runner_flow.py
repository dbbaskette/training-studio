"""The engine after the blueprints: the guide, the brief, the practice scenarios, the Yoodli
scenarios, the copies, the deck that is not made, the index, and research from documents
the person supplies.

Scripted workers hand back the core's own examples. The person's documents, the copies and
the index are small stand-ins that follow the docstrings of the three modules. No agent is
started, nothing is converted and nothing touches the network.
"""
import re
import shutil
from pathlib import Path

import helpers  # noqa: F401
from runner_support import (BLUEPRINT, BRIEF, DOCUMENT, FORM, QUOTE, SCENARIO, YOODLI,
                            NO_BRAND_SKILL, NO_SLIDES, StudioCase, asks, left)

import assess
import desk
import home
import workspace
from runner import page, pipeline
from workspace import WorkspaceError

AVOIDED = re.compile(r'\b(artifacts?|stale|lineage)\b', re.IGNORECASE)
PLAIN = ['research-plan', 'research', 'blueprint', 'document', 'brief', 'scenario:main']
OWN = SCENARIO.replace('Priya Nair', 'Sam Okafor').replace(
    'The zero-downtime objection', 'A restart that dropped requests')
NOTES = ('A platform lead rings after a restart dropped requests.\n\n'
         'She was told rolling restarts mean zero downtime.\n\n'
         'The engineer should explain when capacity holds and agree what happens next.\n')


def other_blueprint() -> str:
    """The example blueprint with one line changed, as a revision would leave it."""
    return BLUEPRINT.replace('A three-instance web app', 'A four-instance web app')


class FlowCase(StudioCase):
    def kinds(self, since: int = 0) -> list[str]:
        """The kind of each job started, after the first `since`."""
        return [kind for kind, _, _ in self.workers.jobs[since:]]

    def review(self, root: Path, name: str) -> str:
        """The last thing written for the person about one file."""
        text = (root / workspace.review_file(name)).read_text()
        return text.rpartition('## Ready for your review')[2]

    def gate(self, root: Path, name: str) -> dict:
        return page.RunnerPage(8765, self.engine).gate(str(root), name)


class ToTheEndTests(FlowCase):
    def test_a_plain_training_goes_from_the_form_to_finished(self):
        self.engine = self.make(at_once=1)
        root = self.start()
        self.assertEqual(self.to_end(root), PLAIN)
        self.assertEqual(self.kinds(), [
            'research-plan', 'question:availability', 'question:instance-min',
            'question:health-checks', 'question:zero-downtime', 'blueprint', 'document',
            'brief', 'scenario'])
        view = self.view(root)
        self.assertEqual((view['state'], view['sentence']), (
            'done', 'This training is finished, with 1 thing left out or limited.'))
        self.assertEqual(view['finished'], {
            'ready': True, 'limitations': ['The deck stage was left out'], 'blocking': [],
            'index': 'README.md'})
        self.assertEqual((view['deck_left'], view['documents'], view['copies'], view['problem']),
                         (None, None, [], None))
        self.assertEqual({step['status'] for step in view['steps']}, {'done'})
        self.assertEqual([step['id'] for step in view['steps']][9:], [
            'document', 'gate:document', 'brief', 'gate:brief', 'scenario:main',
            'gate:scenario:main', 'package'])
        status = workspace.status(root)
        self.assertEqual((status['stage'], status['next_step'], status['gate']),
                         ('done', view['sentence'], None))
        self.assertEqual(set(status['artifacts'].values()), {'approved', 'skipped'})
        self.assertEqual((root / 'document.md').read_text(), DOCUMENT)
        self.assertEqual((root / 'product-brief.md').read_text(), BRIEF)
        self.assertEqual((root / 'scenario.md').read_text(), SCENARIO)
        self.assertTrue((root / 'README.md').read_text().startswith('# Rolling restarts\n'))
        self.assertNotIn('README.md', status['files'].values(), 'the index is never saved '
                         'through the core')
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_a_finished_training_is_filed_under_finished_by_the_desk(self):
        root = self.start()
        self.to_end(root)
        listed = page.RunnerPage(8765, self.engine).trainings()[0]
        self.assertEqual((listed['state'], listed['run']['state'], listed['ready']),
                         ('finished', 'done', True))
        self.assertEqual(self.engine.brief(root)['needs'], False)
        jobs = len(self.workers.jobs)
        self.engine.wake(root)
        self.assertEqual(len(self.workers.jobs), jobs, 'a finished run starts nothing')

    def test_it_says_at_least_how_often_it_will_ask(self):
        for levels, expect in (([], 5), (['101'], 5), (['101', '301'], 8)):
            form = pipeline.check_form({**FORM, 'levels': levels,
                                        'title': f'Restarts {len(levels)}'})
            made = self.engine.start(form)
            self.assertEqual(made['gates'], expect)
            self.assertGreaterEqual(len(self.to_end(Path(made['path']))), expect)

    def test_with_levels_everything_after_the_blueprints_is_done_one_level_at_a_time(self):
        root = self.start(levels=['201', '101'])
        self.assertEqual(self.to_end(root), [
            'research-plan', 'research', 'blueprint@101', 'blueprint@201', 'document@101',
            'brief@101', 'scenario:main@101', 'document@201', 'brief@201',
            'scenario:main@201'])
        self.assertEqual(self.kinds(5), ['blueprint', 'blueprint', 'document', 'brief',
                                         'scenario', 'document', 'brief', 'scenario'])
        first, second = self.workers.of('document')
        self.assertIn('Write the level 101 learner guide for this training.', first.task)
        self.assertIn('This guide is for level 101.', first.task)
        self.assertEqual(first.guidance, pipeline.briefs.guidance('document', level='101'))
        self.assertIn('Your inputs are "intake", "blueprint" and "research findings".',
                      first.task)
        self.assertIn('Your inputs are "intake", "blueprint", "research findings" and '
                      '"earlier levels".', second.task)
        self.assertEqual(self.workers.jobs[-3][2]['inputs'][3]['name'], 'earlier levels')
        self.assertEqual(self.workers.of('brief')[1].guidance,
                         pipeline.briefs.guidance('brief', level='201', kind='product'))
        for name in ('document.md', 'product-brief.md', 'scenario.md', 'blueprint.md'):
            self.assertTrue((root / '101' / name).is_file() and (root / '201' / name).is_file())
        view = self.view(root)
        self.assertEqual((view['state'], view['finished']['ready']), ('done', True))
        self.assertEqual(workspace.status(root)['level'], '201')

    def test_the_level_being_worked_on_is_recorded_through_the_core(self):
        root = self.start(levels=['101', '301'])
        self.to_gate(root, 'document@101')
        self.assertEqual(workspace.status(root)['level'], '101')
        self.to_gate(root, 'document@301')
        status = workspace.status(root)
        self.assertEqual((status['level'], status['stage']), ('301', 'document'))

    def test_earlier_levels_are_given_to_a_guide_as_what_to_assume(self):
        root = self.start(levels=['101', '201'])
        self.to_gate(root, 'document@201')
        found = pipeline.survey(root, self.record(root))
        step = next(step for step in found.steps if step.id == 'document@201')
        given = pipeline.document_work(root, found, step, None, None, []).prepared['inputs']
        self.assertEqual(given['earlier levels'], (
            '## Level 101\n\nAssume the reader can already:\n\n'
            '- Describe what a rolling restart does\n'
            '- Explain when a rolling restart keeps capacity\n'
            '- Handle the objection that rolling restarts guarantee zero downtime\n'))


class WorkerTests(FlowCase):
    """What each of the new jobs is told and given, and that it is given nothing else."""

    def setUp(self):
        super().setUp()
        self.root = self.start(yoodli=True)
        self.to_end(self.root)
        self.jobs = {kind: (job, spec) for kind, job, spec in self.workers.jobs}

    def given(self, kind: str) -> list[str]:
        return [entry['name'] for entry in self.jobs[kind][1]['inputs']]

    def test_every_job_is_a_writer_with_no_web_and_only_the_worker_tools(self):
        for kind in ('document', 'brief', 'scenario', 'yoodli'):
            job, spec = self.jobs[kind]
            self.assertEqual((job.profile, spec['fetch'], spec['finding'], spec['ask']),
                             ('write', False, None, True), kind)
            self.assertEqual(list(spec['artifacts']), [kind])
            self.assertIn('Topic: Rolling restarts on the platform', job.task)
            self.assertIn(f'with submit_artifact under the name "{kind}".', job.task)
            self.assertNotIn(self.space.repo, job.folder.parents)

    def test_the_guide_is_written_from_the_blueprint_and_the_research(self):
        job, spec = self.jobs['document']
        self.assertEqual(self.given('document'), ['intake', 'blueprint', 'research findings'])
        self.assertEqual(spec['artifacts']['document'], {'kind': 'document',
                                                         'blueprint': BLUEPRINT})
        self.assertEqual(job.guidance, pipeline.briefs.guidance('document'))
        self.assertIn('Write the learner guide for this training.', job.task)

    def test_the_brief_is_written_as_the_kind_the_training_asked_for(self):
        job, spec = self.jobs['brief']
        self.assertEqual(self.given('brief'), ['intake', 'blueprint', 'research findings'])
        self.assertEqual(spec['artifacts']['brief'], {
            'kind': 'brief', 'brief_kind': 'product', 'findings': {
                'availability': 'supported', 'instance-min': 'supported',
                'health-checks': 'supported', 'zero-downtime': 'contradicted'}})
        self.assertEqual(job.guidance, pipeline.briefs.guidance('brief', kind='product'))
        self.assertIn('Write the brief for this training. It is a product brief.', job.task)

    def test_a_scenario_is_drafted_from_the_practice_plan_the_brief_and_its_mode(self):
        job, spec = self.jobs['scenario']
        self.assertEqual(self.given('scenario'), ['intake', 'blueprint', 'brief',
                                                  'mode reference'])
        self.assertEqual(spec['artifacts']['scenario'],
                         {'kind': 'scenario', 'label': 'scenario:main', 'mode': 'roleplay'})
        self.assertEqual(job.guidance, pipeline.briefs.guidance('scenario'))
        self.assertIn('Scenario ID: main\nMode: roleplay\nThe practice plan says of it: '
                      'roleplay. Objectives: O1, O2, O3. A sceptical platform lead', job.task)

    def test_a_yoodli_scenario_is_laid_out_from_the_approved_scenario_and_brief(self):
        job, spec = self.jobs['yoodli']
        self.assertEqual(self.given('yoodli'), ['scenario', 'brief', 'objectives',
                                                'Yoodli field data', 'mode reference'])
        about = spec['artifacts']['yoodli']
        self.assertEqual((about['kind'], about['label'], about['scenario'],
                          about['objectives']),
                         ('yoodli', 'yoodli:main', SCENARIO, ['O1', 'O2', 'O3']))
        self.assertEqual(about['profile']['limits']['context_chars']['value'], 10000)
        self.assertEqual(job.guidance, pipeline.briefs.guidance('yoodli'))
        self.assertIn('Lay the practice scenario out for Yoodli.', job.task)
        self.assertIn('Scenario ID: main\nMode: roleplay\nThe copy of the brief to upload is '
                      'its Word file, product-brief.docx.', job.task)

    def test_the_yoodli_facts_a_worker_reads_come_from_the_profile(self):
        profile = helpers.SKILL / 'assets' / 'profiles' / 'yoodli.json'
        facts = pipeline.yoodli_facts(home.read_json(profile, None))
        for said in ('Types: Custom, Tutor, Pitch, Objection Handling, Questionnaire, '
                     'Interview.', 'roleplay is Objection Handling',
                     'Persona fields: Name, Role, Demeanor, Background, Behaviors.',
                     'Types that need a persona: Objection Handling, Pitch.',
                     '- Context: 10,000 characters', '- Personas: 3',
                     "- A goal's Explanation: 2,500 characters",
                     'These limits and the field names are provisional.',
                     '- It takes up to 5 files and 1 public address.',
                     '- It cannot create new custom goals.',
                     '- It creates new roleplays only.',
                     '- Custom goals: An organisation on an Enterprise plan.',
                     "- Strict mode uses more of the roleplay's capacity.",
                     '- A PDF can also be shown to the learner.'):
            self.assertIn(said, facts)
        self.assertIn('# Yoodli field data', pipeline.yoodli_facts({}),
                      'a profile that cannot be read still gives the worker a page')


class ReviewTests(FlowCase):
    """What the review at each new gate carries."""

    def test_gate_4_says_what_was_checked_and_that_coverage_is_declared(self):
        root = self.start()
        self.to_gate(root, 'document')
        note = self.review(root, 'document')
        self.assertIn('> Checked for you: 1 check passed.\n> - Every objective and every '
                      'supported key point is named in a coverage comment, and no '
                      'unsupported one is.\n> Coverage is declared: each section says in a '
                      'comment what it teaches, and the check reads only those comments. '
                      'Whether the prose teaches it is for you to read.', note)
        self.assertIn("> The worker's own notes on its draft. They are its judgment, not a "
                      'check:\n>\n> Each section teaches what its comment says.', note)
        shown = self.gate(root, 'document')
        self.assertEqual((shown['waiting'], shown['checked']['passed'], shown['decisions']),
                         (True, 1, ['approve', 'revise', 'rebuild', 'skip']))
        self.assertNotIn('whose', shown)
        self.assertNotIn('beside', shown)

    def test_gate_5_carries_where_the_worker_thinks_the_brief_is_weakest(self):
        root = self.start()
        self.workers.then('brief', lambda tools, job: tools.submit_artifact('brief', BRIEF))
        self.to_gate(root, 'brief')
        self.assertIn('> The worker left no notes, so nothing here says where the brief is '
                      'weakest. Read its Limitations and its Unknowns with that in mind.',
                      self.review(root, 'brief'))
        self.decide(root, 'brief', 'rebuild')
        note = self.review(root, 'brief')
        self.assertIn('> Checked for you: 2 checks passed.\n> - The title and the eight '
                      'numbered sections are there, in order, and none is empty.\n> - Each '
                      'evidence section names findings that exist and have the verdict it '
                      'needs.', note)
        self.assertIn('> Where the worker thinks the brief is weakest, with its other notes. '
                      'They are its judgment, not a check:\n>\n> It is weakest on rollback',
                      note)

    def test_gate_7_says_whose_file_it_is(self):
        root = self.start()
        self.to_gate(root, 'scenario:main')
        note = self.review(root, 'scenario:main')
        self.assertIn('> The runner drafted this file, from the practice plan and the brief. '
                      'It is yours to change from here.\n> Mode: roleplay. Success '
                      'criteria: 4.', note)
        self.assertEqual(self.gate(root, 'scenario:main')['whose'], 'runner')
        self.assertEqual(self.record(root)['drafted'], ['scenario:main'])

    def test_gate_8_names_the_goals_the_counts_and_the_copy_to_upload(self):
        root = self.start(yoodli=True)
        self.to_gate(root, 'yoodli:main')
        note = self.review(root, 'yoodli:main')
        self.assertIn('> Checked for you: 3 checks passed.', note)
        self.assertIn('> Which goal carries each success criterion:\n'
                      '> - 1. Describes what a rolling restart does. Carried by: Goal 1 '
                      '(Describes the mechanism).\n', note)
        self.assertIn('> - 4. Leaves with an agreed next step. Carried by: Goal 3 (Handles '
                      'the objection).', note)
        self.assertIn("> Counts against Yoodli's limits, in characters:\n"
                      '> - Context: 666 of 10,000\n'
                      '> - Goal 1: explanation 65 of 2,500, achieved 57 of 1,000, missed 74 '
                      'of 1,000\n', note)
        self.assertIn('> - Personas: 1 of 3, counted in personas\n'
                      f'> {pipeline.PROVISIONAL}', note)
        self.assertIn('> The brief has a copy to upload: its Word file, product-brief.docx.',
                      note)
        self.assertEqual((root / 'yoodli' / 'main.md').read_text(), YOODLI,
                         'the counts the worker left at 0 are the real ones')
        shown = self.gate(root, 'yoodli:main')
        self.assertEqual(shown['beside'], {'artifact': 'scenario:main',
                                           'label': 'The practice scenario'})
        self.assertNotIn('whose', shown)

    def test_nothing_a_person_reads_about_the_later_stages_uses_the_words_the_page_avoids(self):
        self.copies.refuse['word'] = 'This computer has no converter for Word files.'
        root = self.start(yoodli=True, deck_target='pptx', copies=['word'])
        self.to_end(root)
        view = self.view(root)
        said = [view['sentence'], view['deck_left']['says'],
                *(step['label'] for step in view['steps']),
                *(entry['label'] + (entry['problem'] or '') for entry in view['copies'])]
        self.decide(root, 'deck', 'skip', 'No slides.')
        view = self.view(root)
        said += [view['sentence'], *view['finished']['limitations'],
                 *view['finished']['blocking'], *self.log()]
        said += [path.read_text() for path in (root / 'reviews').glob('*.md')]
        said += [job.task for _, job, _ in self.workers.jobs]
        self.assertGreater(len(said), 60)
        for text in said:
            self.assertIsNone(AVOIDED.search(text.replace('submit_artifact', '')), text)


class YoodliTests(FlowCase):
    def test_with_yoodli_each_approved_scenario_is_laid_out_and_put_to_the_person(self):
        root = self.start(yoodli=True)
        self.assertEqual(self.to_end(root), PLAIN + ['yoodli:main'])
        self.assertEqual(self.kinds(6), ['document', 'brief', 'scenario', 'yoodli'])
        ids = [step['id'] for step in self.view(root)['steps']]
        self.assertEqual(ids[9:], [
            'document', 'gate:document', 'brief', 'gate:brief', 'copies:brief',
            'scenario:main', 'gate:scenario:main', 'yoodli:main', 'gate:yoodli:main',
            'copies:yoodli:main', 'package'])
        view = self.view(root)
        self.assertEqual([(entry['artifact'], entry['kind'], entry['state'], entry['link'])
                          for entry in view['copies']], [
            ('brief', 'word', 'made', 'product-brief.docx'),
            ('yoodli:main', 'word', 'made', 'yoodli/main.docx')])
        self.assertEqual(view['finished'], {
            'ready': True, 'limitations': ['The deck stage was left out'], 'blocking': [],
            'index': 'README.md'})
        self.assertEqual(assess.run_checks(root)['practice']['basis'], 'Yoodli goals')

    def test_without_yoodli_no_scenario_is_laid_out(self):
        root = self.start()
        self.to_end(root)
        self.assertEqual(self.workers.of('yoodli'), [])
        self.assertNotIn('yoodli:main', workspace.status(root)['artifacts'])

    def test_with_no_copy_of_the_brief_gate_8_says_the_handoff_is_incomplete(self):
        self.copies.refuse['word'] = 'This computer has no converter for Word files.'
        root = self.start(yoodli=True)
        self.to_gate(root, 'yoodli:main')
        self.assertIn('No copy of the brief is ready to upload: This computer has no '
                      'converter for Word files. Name no file under AI assets.',
                      self.workers.of('yoodli')[0].task)
        self.assertIn('> The Yoodli handoff is incomplete: the brief has no copy to upload '
                      'yet (This computer has no converter for Word files.). Try the copies '
                      "again from this training's page, or save the brief as a PDF or a "
                      'Word file yourself and upload that.', self.review(root, 'yoodli:main'))
        self.decide(root, 'yoodli:main')
        view = self.view(root)
        self.assertEqual((view['state'], view['finished']['ready']), ('done', True))
        self.assertIn('The Yoodli handoff is incomplete: the brief has no Word copy',
                      view['finished']['limitations'])

    def test_with_only_a_google_doc_to_upload_it_is_not_ready_until_the_doc_is_made(self):
        self.copies.refuse['google'] = 'Google access is not set up on this computer.'
        root = self.start(yoodli=True, copies=['google'])
        self.to_end(root)
        view = self.view(root)
        self.assertEqual((view['state'], view['sentence']), (
            'done', 'Everything is made, but this training is not ready yet: 1 thing is in '
            'the way. Yoodli needs a copy of the brief to upload, and none is made. Try the '
            'copies again.'))
        self.assertEqual((view['finished']['ready'], view['finished']['blocking']), (
            False, ['The brief is not in a Google Doc, and the Yoodli scenario names it as '
                    'the file to upload']))
        self.assertEqual([(entry['artifact'], entry['state'], entry['problem'])
                          for entry in view['copies']], [
            (name, 'not-made', 'Google access is not set up on this computer.')
            for name in ('document', 'brief')], 'the copies to try again are shown with it')
        self.assertEqual(workspace.status(root)['next_step'], view['sentence'])
        listed = page.RunnerPage(8765, self.engine).trainings()[0]
        self.assertEqual((listed['state'], listed['sentence']),
                         ('in-progress', view['sentence']))
        self.copies.refuse.clear()
        after = self.engine.copies_again(root)
        self.assertEqual((after['state'], after['finished']['ready'], after['sentence']), (
            'done', True, 'This training is finished, with 1 thing left out or limited.'))
        self.assertEqual(page.RunnerPage(8765, self.engine).trainings()[0]['state'],
                         'finished')

    def test_leaving_the_brief_out_with_yoodli_on_is_refused_by_the_core(self):
        root = self.start(yoodli=True)
        self.to_gate(root, 'brief')
        self.assertNotIn('skip', self.gate(root, 'brief')['decisions'])
        with self.assertRaisesRegex(WorkspaceError, 'Turn Yoodli off before skipping the '
                                    'brief'):
            self.decide(root, 'brief', 'skip', 'No brief.')
        self.assertEqual(workspace.status(root)['gate'], 'brief')


class DeckTests(FlowCase):
    def test_no_deck_on_the_form_leaves_the_deck_out_through_the_core(self):
        root = self.start()
        session = workspace.load(root)
        self.assertNotIn('deck', session['settings']['stages'])
        skipped = [event for event in session['events'] if event['event'] == 'skip']
        self.assertEqual([(event['stage'], event['reason'], event['by']) for event in skipped],
                         [('deck', 'No deck was chosen when this training was started.',
                           'page')])
        self.assertEqual(workspace.status(root)['artifacts']['deck'], 'skipped')
        self.assertNotIn('deck', [step['id'] for step in self.view(root)['steps']])

    def test_a_training_that_wants_a_deck_stops_when_the_deck_is_all_that_is_left(self):
        root = self.start(deck_target='pptx')
        self.assertIn('deck', workspace.load(root)['settings']['stages'])
        self.assertEqual(self.to_end(root), PLAIN)
        view, status = self.view(root), workspace.status(root)
        self.assertEqual((view['state'], view['sentence'], view['finished']), (
            'done', 'Everything but the slide deck is made. A deck cannot be made on this '
            f'computer yet: {NO_SLIDES} {NO_BRAND_SKILL} Put that right and check this '
            'computer again, make the deck in a conversation with your assistant, or leave '
            'it out.', None))
        self.assertEqual(view['deck_left'], {'says': view['sentence'], 'artifact': 'deck'})
        steps = self.steps(root)
        self.assertEqual((steps['deck']['status'], steps['deck']['kind'],
                          steps['package']['status']), ('waiting', 'gate', 'to-do'))
        self.assertEqual((status['stage'], status['next_step'], status['gate']),
                         ('deck', view['sentence'], None))
        self.assertFalse((root / 'README.md').exists())
        self.assertEqual(self.log()[-1],
                         'Rolling restarts: everything but the slide deck is made')
        before, jobs = self.log(), len(self.workers.jobs)
        self.engine.wake(root)
        self.assertEqual((self.log(), len(self.workers.jobs)), (before, jobs))
        self.assertEqual(self.engine.brief(root)['needs'], False)

    def test_leaving_the_deck_out_at_the_end_finishes_the_training(self):
        root = self.start(deck_target='pptx')
        self.to_end(root)
        said = self.decide(root, self.view(root)['deck_left']['artifact'], 'skip',
                           'No slides for this one.')
        self.assertEqual(said['said'], 'This stage is left out. You can bring it back from '
                         'the training at any time. This training is finished, with 1 thing '
                         'left out or limited.')
        view = self.view(root)
        self.assertEqual((view['state'], view['deck_left'], view['finished']['ready'],
                          view['finished']['limitations']),
                         ('done', None, True, ['The deck stage was left out']))
        self.assertNotIn('deck', [step['id'] for step in view['steps']])
        self.assertEqual(self.log()[-2:], [
            'Rolling restarts: The deck stage was left out on the page: No slides for this '
            'one.', 'Rolling restarts: write the index; the training is finished'])

    def test_with_levels_one_decision_leaves_every_levels_deck_out(self):
        root = self.start(deck_target='google', levels=['101', '201'])
        self.to_end(root)
        self.assertEqual(self.view(root)['deck_left']['artifact'], 'deck')
        self.decide(root, 'deck', 'skip', 'No slides.')
        self.assertEqual(self.view(root)['finished']['ready'], True)

    def test_a_deck_approved_in_a_conversation_lets_the_index_be_written(self):
        root = self.start(deck_target='pptx')
        self.to_end(root)
        desk_page = page.RunnerPage(8765, self.engine)
        self.assertEqual(desk_page.move_approval(str(root), 'chat'), {'approval': 'chat'})
        self.assertEqual(self.view(root)['deck_left']['artifact'], 'deck')
        (root / 'deck.pptx').write_bytes(b'PK\x03\x04 a deck made in a conversation\n')
        workspace.save(root, 'deck', built=True,
                       coverage={'O1': [2], 'O2': [3], 'O3': [4, 5]})
        workspace.approve(root, 'deck')
        self.engine.wake(root)
        view = self.view(root)
        self.assertEqual((view['state'], view['deck_left'], view['finished']['ready'],
                          view['finished']['limitations']), ('done', None, True, []))
        self.assertEqual(view['sentence'],
                         'This training is finished. Nothing is left out or limited.')
        self.assertEqual(self.steps(root)['deck']['status'], 'done')
        self.assertTrue((root / 'README.md').is_file())

    def test_a_deck_that_is_there_but_not_approved_is_said_to_need_finishing(self):
        root = self.start(deck_target='pptx')
        self.to_end(root)
        (root / 'deck.pptx').write_bytes(b'PK\x03\x04 a deck made in a conversation\n')
        self.assertEqual(self.view(root)['deck_left']['says'], left(pipeline.DECK_AGAIN))
        self.assertIn('finish the deck in a conversation with your assistant, or leave it out',
                      left(pipeline.DECK_AGAIN))

    def test_bringing_the_deck_back_to_a_finished_training_waits_for_the_deck_again(self):
        root = self.start()
        self.to_end(root)
        self.decide(root, 'deck', 'restore')
        view = self.view(root)
        self.assertEqual((view['state'], view['finished'], view['deck_left']['artifact']),
                         ('done', None, 'deck'))
        self.assertEqual(workspace.status(root)['stage'], 'deck')


class LeftOutTests(FlowCase):
    def test_a_stage_the_person_left_out_is_passed_over(self):
        root = self.start()
        self.to_gate(root, 'document')
        said = self.decide(root, 'document', 'skip', 'The brief is all we need.')
        self.assertEqual(said['said'], 'This stage is left out. You can bring it back from '
                         'the training at any time. The brief is waiting for your review.')
        ids = [step['id'] for step in self.view(root)['steps']]
        self.assertNotIn('document', ids)
        self.assertNotIn('gate:document', ids)
        self.assertEqual(self.to_end(root), ['brief', 'scenario:main'])
        view = self.view(root)
        self.assertEqual((view['state'], view['finished']['ready']), ('done', True))
        self.assertEqual(view['finished']['limitations'],
                         ['The learner guide stage was left out', 'The deck stage was left '
                          'out'])

    def test_a_stage_left_out_before_it_is_reached_is_never_started(self):
        root = self.start()
        self.decide(root, 'brief', 'skip', 'No brief.')
        self.decide(root, 'scenario', 'skip', 'No practice.')
        self.assertEqual(self.to_end(root), ['research-plan', 'research', 'blueprint',
                                             'document'])
        self.assertEqual(self.kinds(5), ['blueprint', 'document'])
        self.assertIn('Practice scenarios are not wanted', self.workers.of('blueprint')[0].task)
        self.assertEqual(self.view(root)['finished']['ready'], True)

    def test_a_scenario_is_drafted_without_a_brief_when_the_brief_is_left_out(self):
        root = self.start()
        self.decide(root, 'brief', 'skip', 'No brief.')
        self.to_gate(root, 'scenario:main')
        job, spec = self.workers.jobs[-1][1:]
        self.assertEqual([entry['name'] for entry in spec['inputs']],
                         ['intake', 'blueprint', 'mode reference'])
        self.assertIn("This training has no brief. Keep product facts to what the "
                      "blueprint's key points say.", job.task)

    def test_a_stage_brought_back_is_made_and_put_to_the_person(self):
        root = self.start()
        self.decide(root, 'brief', 'skip', 'No brief.')
        self.to_end(root)
        self.assertEqual(self.workers.of('brief'), [])
        self.decide(root, 'brief', 'restore')
        self.assertEqual((workspace.status(root)['gate'], len(self.workers.of('brief'))),
                         ('brief', 1))
        self.decide(root, 'brief')
        self.assertEqual(self.view(root)['finished']['limitations'],
                         ['The deck stage was left out'])

    def test_a_training_whose_blueprint_plans_no_practice_is_not_ready_and_says_why(self):
        self.workers.blueprint_text = BLUEPRINT.partition('## Practice plan')[0] \
            + '## Open gaps' + BLUEPRINT.partition('## Open gaps')[2]
        root = self.start()
        self.assertEqual(self.to_end(root), PLAIN[:-1])
        view = self.view(root)
        self.assertEqual((view['state'], view['sentence']), (
            'done', 'Everything is made, but this training is not ready yet: 1 thing is in '
            'the way.'))
        self.assertEqual((view['finished']['ready'], view['finished']['blocking']),
                         (False, ['No scenario file found.']))
        self.assertEqual(self.workers.of('scenario'), [], 'only a scenario the practice '
                         'plan names is drafted')
        self.assertEqual(self.log()[-1],
                         'Rolling restarts: write the index; the training is not ready yet')


class RequestTests(FlowCase):
    """Asking for changes or a rebuild at the new gates works as it does at gates 1 to 3."""

    def test_a_change_asked_for_at_each_new_gate_has_the_step_done_again(self):
        root = self.start(yoodli=True)
        for name, kind, thing in (('document', 'document', 'the guide'),
                                  ('brief', 'brief', 'the brief'),
                                  ('scenario:main', 'scenario', 'the scenario'),
                                  ('yoodli:main', 'yoodli', 'the layout')):
            with self.subTest(name):
                self.to_gate(root, name)
                before = (root / workspace.status(root)['files'][name]).read_text()
                said = self.decide(root, name, 'revise', f'Make {thing} shorter.')
                self.assertIn('Your changes are noted.', said['said'])
                first, second = self.workers.of(kind)
                self.assertNotIn('revising', first.task)
                self.assertIn('You are revising an earlier draft. What the person asked for:'
                              f'\n\nMake {thing} shorter.', second.task)
                self.assertIn(f'The earlier draft:\n\n{before}', second.task)
                status = workspace.status(root)
                self.assertEqual((status['gate'], status['requests'], self.state(root)),
                                 (name, [], 'waiting'))
                self.assertIn(f'> This version was made because you asked for changes: Make '
                              f'{thing} shorter.', self.review(root, name))
                self.assertEqual(self.steps(root)[name]['attempts'], 2)
        self.assertEqual(self.record(root)['drafted'], ['scenario:main'])

    def test_a_rebuild_asked_for_at_a_new_gate_starts_the_step_again(self):
        root = self.start()
        self.to_gate(root, 'document')
        self.decide(root, 'document', 'rebuild')
        self.assertIn('The person asked for the guide to be made again from the start.',
                      self.workers.of('document')[1].task)
        self.assertIn('> This version was made because you asked for a new draft.',
                      self.review(root, 'document'))
        self.assertEqual(workspace.status(root)['gate'], 'document')

    def test_a_worker_on_a_later_stage_can_ask_the_person_a_question(self):
        root = self.start()
        self.workers.then('brief', asks('Which product is the brief about?'))
        self.to_gate(root, 'document')
        self.decide(root, 'document')
        asked = self.view(root)['question']
        self.assertEqual(asked['from'], 'The worker writing the brief')
        self.engine.answer(root, asked['id'], 'The platform itself.')
        self.assertEqual(workspace.status(root)['gate'], 'brief')
        self.assertIn('Answer: The platform itself.', self.workers.of('brief')[1].task)

    def test_changes_asked_of_a_finished_training_are_made_and_it_finishes_again(self):
        root = self.start()
        self.to_end(root)
        index = (root / 'README.md').stat().st_mtime_ns
        self.workers.then('document', lambda tools, job: tools.submit_artifact(
            'document', DOCUMENT + '\nRollback is not covered here.\n'))
        self.decide(root, 'document', 'revise', 'Add a line on rollback.')
        view, status = self.view(root), workspace.status(root)
        self.assertEqual((view['state'], view['finished'], status['gate'], status['stage']),
                         ('waiting', None, 'document', 'document'))
        self.assertEqual(self.steps(root)['package']['status'], 'to-do')
        self.decide(root, 'document')
        view = self.view(root)
        self.assertEqual((view['state'], view['finished']['ready']), ('done', True))
        self.assertGreater((root / 'README.md').stat().st_mtime_ns, index)
        self.assertEqual(self.log()[-1],
                         'Rolling restarts: write the index; the training is finished')


class LaterChangeTests(FlowCase):
    """An earlier approval that changes, and what is done again because of it."""

    def test_a_blueprint_changed_and_approved_again_has_what_it_built_done_again(self):
        root = self.start(yoodli=True)
        self.to_end(root)
        jobs = len(self.workers.jobs)
        self.workers.blueprint_text = other_blueprint()
        self.decide(root, 'blueprint', 'revise', 'Use four instances in the example.')
        status = workspace.status(root)
        self.assertEqual((status['gate'], status['artifacts']['document'],
                          status['artifacts']['brief'], status['artifacts']['scenario:main'],
                          status['artifacts']['yoodli:main']),
                         ('blueprint', 'stale', 'stale', 'approved', 'stale'))
        self.assertEqual(self.kinds(jobs), ['blueprint'],
                         'nothing below is made again until the change is approved')
        self.assertEqual(self.to_end(root), ['blueprint', 'document', 'brief', 'yoodli:main'])
        self.assertEqual(self.kinds(jobs), ['blueprint', 'document', 'brief', 'yoodli'])
        again = self.workers.of('document')[1]
        self.assertIn('What the guide was made from has changed since the earlier draft, and '
                      'the person approved the change, so it is being made again. Keep what '
                      'still fits what your inputs say now, and change what does not.\n\nThe '
                      f'earlier draft:\n\n{DOCUMENT}', again.task)
        self.assertEqual(self.workers.jobs[jobs + 1][2]['artifacts']['document']['blueprint'],
                         other_blueprint())
        self.assertIn('> This version was made because what the earlier one was made from '
                      'changed, and you approved the change.', self.review(root, 'document'))
        session = workspace.load(root)
        self.assertEqual([decision for decision in session['decisions']
                          if decision.get('decision') == 'accepted-stale'], [],
                         'nothing is accepted as it is without the person')
        view = self.view(root)
        self.assertEqual((view['state'], view['finished']['ready']), ('done', True))
        self.assertEqual(self.record(root)['drafted'], ['scenario:main'])

    def test_accepting_as_it_is_stays_the_persons_decision(self):
        root = self.start()
        self.to_gate(root, 'brief')
        self.engine.act(root, 'stop')
        self.workers.blueprint_text = other_blueprint()
        self.decide(root, 'blueprint', 'revise', 'Use four instances in the example.')
        self.engine.act(root, 'resume')
        self.engine.act(root, 'stop')
        self.decide(root, 'blueprint')
        self.assertEqual(workspace.status(root)['artifacts']['document'], 'stale')
        self.assertIn('accept', self.gate(root, 'document')['decisions'])
        self.decide(root, 'document', 'accept', 'The example is not in the guide.')
        self.engine.act(root, 'resume')
        self.assertEqual((len(self.workers.of('document')), workspace.status(root)['gate']),
                         (1, 'brief'), 'what the person accepted is not made again')

    def test_research_changed_and_approved_again_reaches_every_level(self):
        def again(tools, job):
            tools.save_source('https://docs.example.com/restarts')
            tools.submit_finding('health-checks', 'supported', 'Readiness is checked too.',
                                 evidence=[{'source_id': 's1', 'quote': QUOTE}])

        root = self.start(levels=['101', '201'])
        self.to_gate(root, 'brief@101')
        jobs = len(self.workers.jobs)
        self.workers.then('question:health-checks', again)
        self.decide(root, 'research', 'revise', 'Look again at health-checks.')
        self.decide(root, 'research')
        self.assertEqual(self.kinds(jobs), ['question:health-checks', 'blueprint',
                                            'blueprint'])
        self.assertEqual(workspace.status(root)['gate'], 'blueprint@101')

    def test_a_setting_that_changes_has_what_uses_it_made_again(self):
        root = self.start()
        self.to_end(root)
        workspace.checkpoint(root, brief_kind='competitive')
        self.assertEqual(workspace.status(root)['artifacts']['brief'], 'not-started')
        self.workers.then('brief', asks('Which two platforms does it compare?'))
        self.engine.wake(root)
        self.assertEqual(self.workers.of('brief')[1].guidance,
                         pipeline.briefs.guidance('brief', kind='competitive'))
        self.assertEqual(self.view(root)['question']['text'],
                         'Which two platforms does it compare?')


class OwnScenarioTests(FlowCase):
    """A scenario file the person wrote: used as it is, and laid out only on request."""

    def own(self, root: Path, text: str = OWN, name: str = 'scenario.md') -> Path:
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
        return file

    def test_a_scenario_the_person_wrote_is_put_to_them_as_it_is(self):
        root = self.start()
        self.to_gate(root, 'blueprint')
        file = self.own(root)
        self.to_gate(root, 'scenario:main')
        self.assertEqual((file.read_text(), self.workers.of('scenario')), (OWN, []))
        step = self.steps(root)['scenario:main']
        self.assertEqual((step['kind'], step['label'], step['status']),
                         ('code', 'Take in the practice scenario, as you wrote it', 'done'))
        self.assertEqual((self.gate(root, 'scenario:main')['whose'],
                          self.record(root)['drafted']), ('you', []))
        note = self.review(root, 'scenario:main')
        self.assertIn('> This is your own file, put to you as you wrote it. The runner '
                      'changed nothing in it.\n> Mode: roleplay. Success criteria: 4.\n> '
                      'Checked for you: 1 check passed.', note)
        self.assertIn('Rolling restarts: take in the practice scenario, as its person wrote '
                      'it', self.log())
        self.decide(root, 'scenario:main')
        self.assertEqual((self.view(root)['finished']['ready'], file.read_text()),
                         (True, OWN))
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_a_file_that_is_not_in_shape_is_put_to_them_with_what_the_check_found(self):
        root = self.start()
        file = self.own(root, NOTES)
        self.to_gate(root, 'scenario:main')
        self.assertEqual((file.read_text(), self.workers.of('scenario')), (NOTES, []))
        note = self.review(root, 'scenario:main')
        self.assertIn('> Checked for you: 0 checks passed.\n> Did not pass (scenario:main.'
                      'sections):\n> - The file must start with "# Scenario: <name>".\n> - '
                      'Section "Situation" is missing or empty.', note)
        self.assertIn('> Ask for changes, and a worker will lay your own wording out under '
                      'the headings a scenario needs. It asks you for anything that is '
                      'missing; it makes nothing up.', note)
        self.assertEqual(self.gate(root, 'scenario:main')['checked']['problems'][0]['check'],
                         'scenario:main.sections')

    def test_their_own_wording_is_laid_out_only_when_they_ask(self):
        root = self.start()
        file = self.own(root, NOTES)
        self.to_gate(root, 'scenario:main')
        self.workers.then('scenario', asks('What does the platform lead say first?'))
        self.decide(root, 'scenario:main', 'revise', 'Lay it out for me.')
        first = self.workers.of('scenario')[0]
        self.assertIn('Lay out a practice scenario the person wrote themselves.', first.task)
        self.assertIn('Keep their wording, as your guidance says under "When the scenario is '
                      'the person\'s own".', first.task)
        self.assertIn('What they asked for:\n\nLay it out for me.', first.task)
        self.assertIn(f'Their scenario, as they wrote it:\n\n{NOTES}', first.task)
        self.assertNotIn('revising an earlier draft', first.task)
        self.assertEqual(file.read_text(), NOTES, 'nothing is rewritten while it asks')
        step = self.steps(root)['scenario:main']
        self.assertEqual((step['kind'], step['label']),
                         ('agent', 'Lay out the practice scenario, in your own words'))
        asked = self.view(root)['question']
        self.assertEqual(asked['from'],
                         'The worker laying out the practice scenario, in your own words')
        self.engine.answer(root, asked['id'], '"Why did we drop requests last week?"')
        self.assertIn('Answer: "Why did we drop requests last week?"',
                      self.workers.of('scenario')[1].task)
        self.assertEqual((file.read_text(), workspace.status(root)['gate']),
                         (SCENARIO, 'scenario:main'))
        self.assertIn('> This is your own file, laid out under the headings a scenario needs '
                      'because you asked for that.', self.review(root, 'scenario:main'))
        self.assertEqual((self.gate(root, 'scenario:main')['whose'],
                          self.record(root)['drafted']), ('you', []),
                         'it is still their file')
        kept = list((root / '.training-studio' / 'history' / 'scenario-main').glob('*.md'))
        self.assertIn(NOTES, [path.read_text() for path in kept],
                      'what they wrote is kept')

    def test_a_scenario_of_theirs_beside_the_one_the_plan_names_gets_a_gate_of_its_own(self):
        root = self.start()
        self.to_gate(root, 'blueprint')
        self.own(root, OWN, 'scenarios/dropped-requests.md')
        approved = self.to_end(root)
        self.assertEqual(approved[-2:], ['scenario:main', 'scenario:dropped-requests'])
        self.assertEqual((len(self.workers.of('scenario')), self.record(root)['drafted']),
                         (1, ['scenario:main']))
        self.assertEqual([self.gate(root, name)['whose']
                          for name in ('scenario:main', 'scenario:dropped-requests')],
                         ['runner', 'you'])
        ids = [step['id'] for step in self.view(root)['steps']]
        self.assertEqual(ids[13:17], ['scenario:main', 'scenario:dropped-requests',
                                      'gate:scenario:main', 'gate:scenario:dropped-requests'])
        self.assertEqual((root / 'scenarios' / 'dropped-requests.md').read_text(), OWN)

    def test_a_file_of_theirs_changed_after_it_was_taken_in_is_taken_in_again(self):
        root = self.start()
        file = self.own(root)
        self.to_gate(root, 'scenario:main')
        file.write_text(OWN.replace('10 minutes', '15 minutes'))
        self.engine.wake(root)
        self.assertEqual(self.steps(root)['scenario:main']['attempts'], 2)
        self.assertIn('15 minutes', file.read_text())
        self.decide(root, 'scenario:main')
        self.assertEqual(self.view(root)['finished']['ready'], True)

    def test_a_mode_other_than_the_practice_plans_is_noted_and_their_file_decides(self):
        root = self.start()
        self.own(root, OWN.replace('## Mode\n\nroleplay', '## Mode\n\npitch'))
        self.to_gate(root, 'scenario:main')
        self.assertIn('> Worth a look: the practice plan lists this scenario as roleplay; '
                      'your file says pitch. Your file decides.',
                      self.review(root, 'scenario:main'))

    def test_a_training_with_no_run_cannot_say_whose_a_scenario_is(self):
        self.assertIsNone(self.engine.whose(self.base / 'elsewhere', 'scenario:main'))


class CopiesTests(FlowCase):
    def shown(self, root: Path) -> dict:
        return {(entry['artifact'], entry['kind']): entry
                for entry in self.view(root)['copies']}

    def test_the_copies_a_training_asked_for_are_made_after_each_approval(self):
        root = self.start(copies=['google', 'word'])
        self.to_gate(root, 'document')
        self.assertEqual(len(self.copies.wanted(root)), 4)
        self.assertEqual((self.view(root)['copies'], self.copies.calls), ([], 0),
                         'no copy is made, or shown, of what is not approved yet')
        self.assertEqual([step for step in self.steps(root) if step.startswith('copies:')],
                         ['copies:document', 'copies:brief'])
        self.decide(root, 'document')
        made = self.shown(root)
        self.assertEqual([sorted(entry) for entry in made.values()],
                         [['artifact', 'kind', 'label', 'link', 'problem', 'state']] * 2)
        self.assertEqual((made['document', 'google']['state'],
                          made['document', 'google']['link'],
                          made['document', 'word']['state'], made['document', 'word']['link'],
                          made['document', 'word']['label']),
                         ('made', 'https://docs.example.com/d/doc1/edit', 'made',
                          'document.docx', 'the learner guide'))
        self.assertNotIn(('brief', 'word'), made)
        step = self.steps(root)['copies:document']
        self.assertEqual((step['kind'], step['status'], step['label']),
                         ('code', 'done', 'Make the copies of the learner guide'))
        self.assertIn('Rolling restarts: make the copies of the learner guide', self.log())
        self.assertTrue((root / 'document.docx').is_file())
        self.to_end(root)
        self.assertEqual({entry['state'] for entry in self.view(root)['copies']}, {'made'})
        self.assertEqual(self.view(root)['finished']['limitations'],
                         ['The deck stage was left out'])
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_a_training_that_asked_for_no_copies_has_no_copies_steps(self):
        root = self.start()
        self.to_end(root)
        self.assertEqual((self.view(root)['copies'], self.copies.calls), ([], 0))
        self.assertEqual([step for step in self.steps(root) if step.startswith('copies:')],
                         [])

    def test_a_copy_that_cannot_be_made_says_why_and_never_holds_the_run_up(self):
        self.copies.refuse.update(
            google='Google access is not set up on this computer.',
            word='This computer has no converter for Word files.')
        root = self.start(copies=['google', 'word'])
        self.to_gate(root, 'brief')
        made = self.shown(root)
        self.assertEqual((made['document', 'google']['state'],
                          made['document', 'google']['problem'],
                          made['document', 'word']['state'],
                          made['document', 'word']['problem']),
                         ('not-made', 'Google access is not set up on this computer.',
                          'not-made', 'This computer has no converter for Word files.'))
        self.assertEqual(self.steps(root)['copies:document']['status'], 'done')
        self.assertEqual(self.record(root)['copies']['problems'],
                         {'document': 'Google access is not set up on this computer.'})
        self.assertEqual((self.state(root), self.view(root)['problem']), ('waiting', None))
        calls = self.copies.calls
        self.engine.wake(root)
        self.assertEqual(self.copies.calls, calls, 'it is not tried again until asked')
        self.to_end(root)
        view = self.view(root)
        self.assertEqual((view['state'], view['finished']['ready']), ('done', True))
        self.assertIn('The learner guide is not in a Google Doc',
                      view['finished']['limitations'])

    def test_trying_the_copies_again_makes_those_that_were_not_made(self):
        self.copies.refuse['google'] = 'Google access is not set up on this computer.'
        root = self.start(copies=['google'])
        self.to_end(root)
        self.assertEqual({entry['state'] for entry in self.view(root)['copies']},
                         {'not-made'})
        self.assertNotIn('docs.example.com', (root / 'README.md').read_text())
        self.copies.refuse.clear()
        after = self.engine.copies_again(root)
        self.assertEqual([(entry['state'], entry['problem']) for entry in after['copies']],
                         [('made', None), ('made', None)])
        self.assertEqual(after['finished']['limitations'], ['The deck stage was left out'])
        self.assertEqual(after['sentence'],
                         'This training is finished, with 1 thing left out or limited.')
        self.assertIn('docs.example.com', (root / 'README.md').read_text(),
                      'the index lists the copies, so it is written again')
        self.assertEqual(self.log()[-1],
                         'Rolling restarts: make the copies again, as asked on the page')
        self.assertEqual(self.git('status', '--porcelain'), '')
        with self.assertRaisesRegex(WorkspaceError, 'No run is driving this training'):
            self.engine.copies_again(self.base / 'elsewhere')

    def test_a_copy_is_made_again_when_its_document_is_approved_again(self):
        root = self.start(copies=['word'])
        self.to_gate(root, 'brief')
        first = (root / 'document.docx').read_bytes()
        self.workers.then('document', lambda tools, job: tools.submit_artifact(
            'document', DOCUMENT.replace('25 minutes', '20 minutes')))
        self.decide(root, 'document', 'revise', 'Twenty minutes, not twenty-five.')
        self.assertEqual(self.shown(root)['document', 'word']['state'], 'out-of-date',
                         'a copy that is behind its file is shown, approved or not')
        self.assertEqual(self.steps(root)['copies:document']['status'], 'to-do')
        self.decide(root, 'document')
        self.assertEqual(self.shown(root)['document', 'word']['state'], 'made')
        self.assertNotEqual((root / 'document.docx').read_bytes(), first)
        self.assertEqual(workspace.status(root)['gate'], 'brief')


class DocumentTests(FlowCase):
    """Research from documents the person supplies."""

    def test_a_training_from_the_persons_documents_waits_for_them_first(self):
        root = self.start(source_scope='supplied-only')
        view = self.view(root)
        self.assertEqual((view['state'], view['sentence'], self.workers.jobs), (
            'waiting', 'Add your documents, then say that is all of them. Nothing is '
            'researched until you do. This training is researched from them alone.', []))
        self.assertEqual(view['documents'], {
            'waiting': True, 'added': [],
            'types': ['.txt', '.md', '.html', '.htm', '.docx'],
            'limits': {'bytes': 8_000_000, 'files': 40},
            # Where documents are kept is the page's to say; this is only what it cannot know.
            'note': 'This computer cannot read a PDF: save it as text or as a Word file '
                    'first.'})
        step = view['steps'][1]
        self.assertEqual((step['id'], step['kind'], step['status'], step['label']),
                         ('documents', 'gate', 'waiting', 'Add your documents'))
        self.assertEqual(self.engine.brief(root)['needs'], True)
        self.assertIn('## Source scope\n\nYour documents only\n',
                      (root / 'intake.md').read_text())
        self.assertEqual(self.record(root)['documents'],
                         {'scope': 'supplied-only', 'done': None, 'count': 0})
        self.engine.wake(root)
        self.assertEqual(self.workers.jobs, [])

    def test_a_training_from_the_public_web_takes_no_documents(self):
        root = self.start()
        self.assertIsNone(self.view(root)['documents'])
        self.assertIsNone(self.record(root)['documents'])
        with self.assertRaisesRegex(WorkspaceError, 'researched from the public web, so it '
                                    'takes no documents'):
            self.send(root, 'handbook.txt')
        with self.assertRaisesRegex(WorkspaceError, 'A document can be: add, remove, done'):
            self.engine.supply(root, 'replace', 'handbook.txt')
        with self.assertRaisesRegex(WorkspaceError, 'No run is driving this training'):
            self.engine.supply(self.base / 'elsewhere', 'done')

    def test_documents_are_added_shown_and_removed_until_the_person_says_that_is_all(self):
        root = self.start(source_scope='supplied-only')
        after = self.send(root, 'handbook.txt')
        self.assertEqual(after['documents']['added'], [
            {'name': 'handbook.txt', 'bytes': 60, 'readable': True, 'problem': None}])
        after = self.send(root, 'slides.docx')
        self.assertEqual(after['documents']['added'][1], {
            'name': 'slides.docx', 'bytes': 60, 'readable': False,
            'problem': 'slides.docx could not be read. Save it as text and add it again.'})
        for name, said in (('handbook.txt', 'was already added'),
                           ('notes.pdf', 'not a kind of document that can be read here'),
                           ('../outside.txt', 'a plain file name')):
            with self.assertRaisesRegex(WorkspaceError, said):
                self.send(root, name)
        self.assertEqual(self.git('status', '--porcelain'), '',
                         'the documents themselves are never shared')
        after = self.engine.supply(root, 'remove', 'slides.docx')
        self.assertEqual([entry['name'] for entry in after['documents']['added']],
                         ['handbook.txt'])
        self.assertEqual((after['documents']['waiting'], after['state'], self.workers.jobs),
                         (True, 'waiting', []))

        done = self.engine.supply(root, 'done')
        self.assertEqual((done['documents']['waiting'], done['state'], done['sentence']),
                         (False, 'waiting', 'The research plan is waiting for your review.'))
        self.assertEqual(self.steps(root)['documents']['status'], 'done')
        self.assertEqual(self.log()[-3],
                         'Rolling restarts: the documents are all added: 1 to research from')
        for action, name in (('add', 'more.txt'), ('remove', 'handbook.txt'), ('done', None)):
            with self.assertRaisesRegex(WorkspaceError, 'cannot be changed now'):
                self.engine.supply(root, action, name, b'More words.\n')

    def test_the_questions_are_drafted_for_what_the_documents_can_answer(self):
        root = self.start(source_scope='supplied-only')
        self.send(root, 'handbook.txt')
        self.send(root, 'runbook.md')
        self.engine.supply(root, 'done')
        job, spec = self.workers.jobs[0][1:]
        self.assertIn('Sources that may be used: only the documents the person supplied. Ask '
                      'what these can answer, and give no question any search words:\n- '
                      'handbook\n- runbook\n', job.task)
        about = spec['artifacts']['research-plan']
        self.assertEqual((about['scope'], [source['id'] for source in about['sources']]),
                         ('supplied-only', ['handbook', 'runbook']))
        plan = home.read_json(root / pipeline.PLAN, None)
        self.assertEqual((plan['scope'], {item['public_query'] for item in plan['items']}),
                         ('supplied-only', {None}))
        self.assertEqual(plan['sources'], [
            {'id': 'handbook', 'title': 'handbook', 'file': 'sources/supplied/handbook.text',
             'original_file': 'sources/supplied/handbook.txt', 'limits': 'none'},
            {'id': 'runbook', 'title': 'runbook', 'file': 'sources/supplied/runbook.text',
             'original_file': 'sources/supplied/runbook.md', 'limits': 'none'}])

    def test_a_worker_on_documents_only_cannot_reach_the_web(self):
        root = self.start(source_scope='supplied-only')
        self.send(root, 'handbook.txt')
        self.engine.supply(root, 'done')
        self.decide(root, 'research-plan')
        asked = self.workers.of('question')
        self.assertEqual(len(asked), 4)
        for kind, job, spec in self.workers.jobs[1:]:
            self.assertEqual((job.profile, spec['fetch'], spec['ask']),
                             ('write', False, False), kind)
        self.assertIn('Work only from the documents the person supplied, which are saved for '
                      'you already.', asked[0].task)
        self.assertNotIn('Search words to start from', asked[0].task)
        self.assertEqual(self.web.asked, [], 'no page was fetched')
        record = workspace.research_record(root)
        self.assertEqual((record['scope'], workspace.status(root)['gate']),
                         ('supplied-only', 'research'))
        passage = record['results']['availability']['evidence'][0]
        self.assertEqual((passage['file'], passage['source_id'], passage['quote']),
                         ('sources/supplied/handbook.text', 'handbook', QUOTE))
        self.assertEqual(self.to_end(root), PLAIN[1:])
        self.assertEqual(self.view(root)['finished']['ready'], True)

    def test_a_job_that_may_not_fetch_is_refused_a_page_by_its_own_tools(self):
        root = self.start(source_scope='supplied-only')
        self.send(root, 'handbook.txt')
        self.engine.supply(root, 'done')
        seen = []

        def tries(tools, job):
            seen.append(tools.save_source('https://docs.example.com/restarts'))
            seen.append([entry['name'] for entry in tools.offered()])
            self.workers.question(tools, job)

        self.workers.then('question:availability', tries)
        self.decide(root, 'research-plan')
        self.assertEqual(seen[0], (False, 'This job cannot fetch pages. Work from what you '
                                   'were given.'))
        self.assertNotIn('save_source', seen[1])
        self.assertIn('read_source', seen[1])

    def test_with_the_web_and_documents_a_worker_has_both(self):
        root = self.start(source_scope='both')
        self.assertIn('## Source scope\n\nThe public web and your documents\n',
                      (root / 'intake.md').read_text())
        self.assertNotIn('researched from them alone', self.view(root)['sentence'])
        self.send(root, 'handbook.txt')
        self.engine.supply(root, 'done')
        job, spec = self.workers.jobs[0][1:]
        self.assertIn('Sources that may be used: the public web, and these documents the '
                      'person supplied. Ask what the documents can answer as well as what '
                      'the web can:\n- handbook\n', job.task)
        plan = home.read_json(root / pipeline.PLAN, None)
        self.assertEqual((plan['scope'], [source['id'] for source in plan['sources']],
                          plan['items'][0]['public_query']),
                         ('public-web', ['handbook'], 'rolling restart availability'))
        self.decide(root, 'research-plan')
        kind, job, spec = self.workers.jobs[1]
        self.assertEqual((job.profile, spec['fetch']), ('research', True))
        self.assertIn('The documents the person supplied are saved for you already. Read '
                      'them as well as the web.', job.task)
        self.assertIn('Search words to start from: rolling restart', job.task)
        self.assertEqual(workspace.status(root)['gate'], 'research')

    def test_research_from_documents_alone_needs_one_that_can_be_read(self):
        root = self.start(source_scope='supplied-only')
        self.send(root, 'slides.docx')
        with self.assertRaisesRegex(WorkspaceError, 'Add at least one document that can be '
                                    'read first. This training is researched from your '
                                    'documents only.'):
            self.engine.supply(root, 'done')
        self.assertEqual((self.view(root)['documents']['waiting'], self.workers.jobs),
                         (True, []))

    def test_with_the_web_as_well_no_document_at_all_is_an_answer(self):
        root = self.start(source_scope='both')
        done = self.engine.supply(root, 'done')
        self.assertEqual((done['documents']['waiting'], workspace.status(root)['gate']),
                         (False, 'research-plan'))
        self.assertIn('Sources that may be used: the public web.\n',
                      self.workers.jobs[0][1].task)
        self.assertIn('Rolling restarts: no documents were added; research uses the public '
                      'web', self.log())

    def test_a_computer_that_can_read_a_pdf_takes_one(self):
        self.documents.pdf = True
        root = self.start(source_scope='both')
        shown = self.view(root)['documents']
        self.assertIn('.pdf', shown['types'])
        self.assertNotIn('PDF', shown['note'])

    def test_on_another_computer_research_waits_for_the_documents_again(self):
        root = self.start(source_scope='supplied-only')
        self.send(root, 'handbook.txt')
        self.engine.supply(root, 'done')
        self.to_gate(root, 'blueprint')
        shutil.rmtree(root / 'sources')  # never shared, so another computer has none of it
        shown = self.view(root)
        self.assertEqual((shown['state'], shown['documents']['waiting'],
                          shown['documents']['added']), ('waiting', False, []))
        self.assertTrue(shown['documents']['note'].endswith(
            'The documents this training was researched from are on another computer. '
            'Research cannot be run again here until they are added again.'))
        jobs = len(self.workers.jobs)
        self.decide(root, 'research', 'rebuild')
        shown = self.view(root)
        self.assertEqual((shown['state'], shown['documents']['waiting'], len(self.workers.jobs),
                          self.steps(root)['documents']['status']),
                         ('waiting', True, jobs, 'waiting'))
        again = self.send(root, 'handbook.txt')
        self.assertEqual((again['documents']['waiting'], len(self.workers.jobs)),
                         (True, jobs), 'this computer has not been told that is all of them')
        done = self.engine.supply(root, 'done')
        self.assertEqual((done['documents']['waiting'], done['state'], len(self.workers.jobs)),
                         (False, 'waiting', jobs + 4), 'the research is run again')
        self.assertNotIn('another computer', done['documents']['note'])


class AwayTests(FlowCase):
    """A training whose decisions were moved to a conversation."""

    def test_it_is_left_alone_until_its_decisions_come_back_to_the_page(self):
        root = self.start(deck_target='pptx')
        self.to_end(root)
        desk_page = page.RunnerPage(8765, self.engine)
        desk_page.move_approval(str(root), 'chat')
        guide = root / 'document.md'
        guide.write_text(guide.read_text() + '\nA line added in the conversation.\n')
        self.engine.wake(root)
        view, status = self.view(root), workspace.status(root)
        self.assertEqual((view['state'], view['sentence'], view['deck_left'], view['finished']), (
            'done', "This training's decisions are made in the conversation now, so the "
            'runner is leaving it alone. Move them back to the page to have the runner '
            'carry on.', None, None))
        self.assertEqual((status['gate'], status['artifacts']['document']), (None, 'draft'))
        self.engine.close()
        self.engine = self.make()
        self.engine.resume()
        self.assertIn('A line added in the conversation.', guide.read_text())
        self.assertIsNone(workspace.status(root)['gate'])

        page.RunnerPage(8765, self.engine).move_approval(str(root), 'page')
        self.assertEqual((self.state(root), workspace.status(root)['gate']),
                         ('waiting', 'document'))

    def test_decisions_cannot_move_to_a_conversation_while_the_run_has_work_to_do(self):
        root = self.start()
        self.to_gate(root, 'document')
        with self.assertRaisesRegex(desk.Refusal, 'The runner is driving this training'):
            page.RunnerPage(8765, self.engine).move_approval(str(root), 'chat')


if __name__ == '__main__':
    import unittest
    unittest.main()
