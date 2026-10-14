"""The pipelines as data, the form, and where a training is, worked out from its files.

Nothing here runs a worker: each test puts files in place through the core, as the engine
would, and asks what comes next.
"""
import json
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401
from runner_support import (BLUEPRINT, BRIEF, DOCUMENT, FORM, FOUR, SCENARIO, YOODLI,
                            StudioCase)

import workspace
from runner import pipeline, research
from workspace import WorkspaceError

SNAPSHOT = 'sources/docs-example-com-0123456789ab.txt'
QUOTE = 'Capacity holds only when more than one instance is running.'


class DefinitionTests(StudioCase):
    def test_the_training_pipeline_is_data_from_the_form_to_the_index(self):
        stages = list(dict.fromkeys(row[0] for row in pipeline.TRAINING))
        self.assertEqual(stages, ['intake', 'research-plan', 'research', 'blueprint',
                                  'document', 'brief', 'deck', 'scenario', 'yoodli',
                                  'package'])
        self.assertEqual([(row[1], row[2]) for row in pipeline.TRAINING], [
            ('intake', 'code'), ('documents', 'gate'), ('research-plan', 'agent'),
            ('gate:research-plan', 'gate'), ('research-start', 'code'), ('research', 'agent'),
            ('research-report', 'code'), ('gate:research', 'gate'), ('blueprint', 'agent'),
            ('gate:blueprint', 'gate'), ('document', 'agent'), ('gate:document', 'gate'),
            ('copies:document', 'code'), ('brief', 'agent'), ('gate:brief', 'gate'),
            ('copies:brief', 'code'), ('deck-handoff', 'code'), ('deck-brand', 'code'),
            ('deck-outline', 'agent'), ('gate:deck-outline', 'gate'), ('deck-start', 'code'),
            ('deck-sections', 'agent'), ('deck-whole', 'code'), ('deck-review', 'agent'),
            ('deck-repair', 'agent'), ('deck-save', 'code'), ('gate:deck', 'gate'),
            ('scenario', 'agent'), ('gate:scenario', 'gate'),
            ('yoodli', 'agent'), ('gate:yoodli', 'gate'), ('copies:yoodli', 'code'),
            ('deck', 'gate'), ('package', 'code')])
        self.assertEqual([name for name, _ in pipeline.RESEARCH],
                         ['research-start', 'research', 'research-report'])
        self.assertEqual(set(stages), set(workspace.STAGES) - {'done'})
        self.assertEqual(pipeline.TRAINING[-2][:3], ('deck', 'deck', 'gate'), 'on a computer '
                         'that cannot make a deck, a training is taken through every other '
                         'stage first')

    def test_a_trainings_steps_are_laid_out_in_the_order_they_are_walked(self):
        plain = pipeline.steps([])
        self.assertEqual([(step.id, step.kind, step.artifact) for step in plain][7:], [
            ('blueprint', 'agent', 'blueprint'), ('gate:blueprint', 'gate', 'blueprint'),
            ('document', 'agent', 'document'), ('gate:document', 'gate', 'document'),
            ('brief', 'agent', 'brief'), ('gate:brief', 'gate', 'brief'),
            ('deck', 'gate', None), ('package', 'code', None)])
        self.assertEqual([step.label for step in plain], [
            'Record your answers', 'Draft the research plan',
            'Your review of the research plan', 'Hand the approved questions to research',
            'Research each question', 'Write the research report',
            'Your review of the research report', 'Draft the blueprint',
            'Your review of the blueprint', 'Write the learner guide',
            'Your review of the learner guide', 'Write the brief', 'Your review of the brief',
            'The slide deck, made in a conversation or left out', 'Write the index'])
        self.assertEqual((plain[1].doing, plain[-1].doing, plain[-1].stage),
                         ('Drafting the research plan', 'Writing the index', 'package'))
        levelled = pipeline.steps(['101', '301'])
        self.assertEqual([(step.id, step.artifact, step.label) for step in levelled][7:11], [
            ('blueprint@101', 'blueprint@101', 'Draft the level 101 blueprint'),
            ('blueprint@301', 'blueprint@301', 'Draft the level 301 blueprint'),
            ('gate:blueprint@101', 'blueprint@101', 'Your review of the level 101 blueprint'),
            ('gate:blueprint@301', 'blueprint@301', 'Your review of the level 301 blueprint')])
        self.assertEqual([step.id for step in levelled][11:], [
            'document@101', 'gate:document@101', 'brief@101', 'gate:brief@101',
            'document@301', 'gate:document@301', 'brief@301', 'gate:brief@301', 'deck',
            'package'], 'after the blueprints, one level at a time, lowest first')

    def test_what_a_training_wants_decides_which_steps_it_has(self):
        whole = pipeline.steps(
            ['101'], stages=('document', 'brief', 'scenario', 'yoodli'),
            practice={'101': {'main': {}, 'objection': {}}}, documents=True,
            copies={'brief@101', 'yoodli:main@101'}, own={'scenario:objection@101'})
        self.assertEqual([step.id for step in whole], [
            'intake', 'documents', 'research-plan', 'gate:research-plan', 'research-start',
            'research', 'research-report', 'gate:research', 'blueprint@101',
            'gate:blueprint@101', 'document@101', 'gate:document@101', 'brief@101',
            'gate:brief@101', 'copies:brief@101', 'scenario:main@101',
            'scenario:objection@101', 'gate:scenario:main@101',
            'gate:scenario:objection@101', 'yoodli:main@101', 'yoodli:objection@101',
            'gate:yoodli:main@101', 'gate:yoodli:objection@101', 'copies:yoodli:main@101',
            'package'])
        by_id = {step.id: step for step in whole}
        self.assertEqual({(step.id, step.stage) for step in whole if '101' in step.id
                          and step.stage not in step.id}, set())
        self.assertEqual((by_id['documents'].kind, by_id['documents'].label,
                          by_id['documents'].artifact),
                         ('gate', 'Add your documents', None))
        self.assertEqual((by_id['scenario:main@101'].kind, by_id['scenario:main@101'].label),
                         ('agent', 'Draft the level 101 practice scenario'))
        theirs = by_id['scenario:objection@101']
        self.assertEqual((theirs.kind, theirs.label, theirs.artifact), (
            'code', 'Take in the level 101 practice scenario "objection", as you wrote it',
            'scenario:objection@101'))
        self.assertEqual(by_id['copies:yoodli:main@101'].label,
                         'Make the copies of the level 101 Yoodli scenario')
        self.assertEqual(by_id['yoodli:main@101'].doing,
                         'Laying out the level 101 Yoodli scenario')
        laid = pipeline.steps([], practice={None: {'main': {}}}, laid={'scenario:main'})
        self.assertEqual([(step.kind, step.label) for step in laid if step.id == 'scenario:main'],
                         [('agent', 'Lay out the practice scenario, in your own words')])
        bare = pipeline.steps([], stages=())
        self.assertEqual([step.id for step in bare][9:], ['package'],
                         'a stage that is left out has no steps')
        self.assertEqual(pipeline.gate_for('scenario:main@101'), by_id['gate:scenario:main@101'])

    def test_it_says_the_fewest_times_it_will_ask_for_a_decision(self):
        for levels, expect in (([], 5), (['101'], 5), (['101', '201'], 8),
                               (['101', '201', '301', '401'], 14)):
            form = pipeline.check_form({**FORM, 'levels': levels})
            self.assertEqual(pipeline.gates(form), expect)
            gates = [step for step in pipeline.steps(form['levels'])
                     if step.id.startswith('gate:')]
            self.assertEqual(len(gates), expect)


class FormTests(StudioCase):
    def test_the_form_is_read_field_by_field(self):
        form = pipeline.check_form({
            'title': '  Rolling restarts ', 'topic': 'Rolling restarts on the platform',
            'audience': 'Operators', 'purpose': 'Technical upskilling',
            'levels': ['301', '101', '301'], 'copies': ['word', 'google'], 'unknown': 'left'})
        self.assertEqual(form, {
            'title': 'Rolling restarts', 'topic': 'Rolling restarts on the platform',
            'audience': 'Operators', 'purpose': 'Technical upskilling', 'time_limit': None,
            'brand': None, 'levels': ['101', '301'], 'copies': ['google', 'word'],
            'brief_kind': 'product', 'deck_target': None, 'source_scope': 'public-web',
            'yoodli': False, 'agent': None, 'model': None, 'effort': None})

    def test_research_may_look_at_the_web_the_persons_documents_or_both(self):
        self.assertEqual(pipeline.check_form({**FORM, 'source_scope': None})['source_scope'],
                         'public-web')
        for scope, words in (('public-web', 'Public web'),
                             ('supplied-only', 'Your documents only'),
                             ('both', 'The public web and your documents')):
            form = pipeline.check_form({**FORM, 'source_scope': scope})
            self.assertEqual(form['source_scope'], scope)
            self.assertIn(f'## Source scope\n\n{words}\n', pipeline.intake_text(form))
        with self.assertRaisesRegex(WorkspaceError, 'The source scope is one of: public-web, '
                                    'supplied-only, both'):
            pipeline.check_form({**FORM, 'source_scope': 'the-moon'})

    def test_a_form_that_says_no_deck_leaves_the_deck_out_as_the_persons_own_choice(self):
        without = pipeline.create(self.space, pipeline.check_form(FORM))
        session = workspace.load(without)
        self.assertEqual(session['settings']['stages'], ['document', 'brief', 'scenario'])
        self.assertEqual([(event['reason'], event['by']) for event in session['events']
                          if event['event'] == 'skip'], [(pipeline.NO_DECK, 'page')])
        self.assertFalse((without / 'reviews').exists())
        wanted = pipeline.create(self.space, pipeline.check_form(
            {**FORM, 'title': 'Health checks', 'deck_target': 'google'}))
        self.assertEqual(workspace.load(wanted)['settings']['stages'],
                         ['document', 'brief', 'deck', 'scenario'])

    def test_the_answers_become_intake_and_are_read_back_from_it(self):
        form = pipeline.check_form({**FORM, 'levels': ['101', '301'],
                                    'brief_kind': 'competitive', 'time_limit': None,
                                    'purpose': 'Technical upskilling'})
        root = pipeline.create(self.space, form)
        text = (root / 'intake.md').read_text()
        self.assertEqual([line[3:] for line in text.splitlines() if line.startswith('#')],
                         list(pipeline.HEADINGS))
        self.assertEqual(pipeline.answers(root), {
            'topic': 'Rolling restarts on the platform', 'levels': '101, 301',
            'brief': 'competitive', 'audience': 'Solutions engineers who deploy apps',
            'purpose': 'Technical upskilling', 'source scope': 'Public web',
            'time limit': 'None given'})
        self.assertEqual(pipeline.answers(self.base / 'nowhere'), {})

    def test_a_training_is_made_whole_or_not_at_all(self):
        form = pipeline.check_form(FORM)
        root = pipeline.create(self.space, form)
        session = workspace.load(root)
        self.assertEqual((session['settings']['approval'], session['stage'],
                          session['next_step']),
                         ('page', 'research-plan', 'Draft the research plan'))
        with self.assertRaisesRegex(WorkspaceError, 'Give this one a different title'):
            pipeline.create(self.space, form)
        self.assertTrue((root / 'intake.md').is_file(), 'the first one is left as it was')
        other = pipeline.check_form({**FORM, 'title': 'Health checks'})
        with mock.patch.object(workspace, 'approve', side_effect=WorkspaceError('No.')):
            with self.assertRaisesRegex(WorkspaceError, 'No.'):
                pipeline.create(self.space, other)
        self.assertFalse(self.space.training('health-checks').exists())
        self.assertEqual(pipeline.create(self.space, other).name, 'health-checks')


class SurveyTests(StudioCase):
    """Each test moves a training along by hand, through the core, and asks what is next."""

    def setUp(self):
        super().setUp()
        self.root = pipeline.create(self.space, pipeline.check_form(FORM))
        self.run = {'steps': {}, 'research': None}

    def next(self) -> pipeline.Next:
        return pipeline.survey(self.root, self.run).next

    def kept(self, name: str, text: str) -> None:
        draft = self.base / 'draft'
        draft.write_text(text)
        workspace.save(self.root, name, source=draft)

    def plan(self) -> dict:
        return {**FOUR, 'purpose': 'planning', 'scope': 'public-web', 'sources': [],
                'items': [{**item, 'claim': None} for item in FOUR['items']]}

    def gate(self, name: str) -> None:
        workspace.checkpoint(self.root, gate=name, question=f'Approve {name}?')

    def approve(self, name: str) -> None:
        workspace.approve(self.root, name, by='page')

    def planned(self) -> None:
        """The plan approved and handed to the stand-in for harness-research."""
        self.kept('research-plan', json.dumps(self.plan()))
        self.approve('research-plan')
        status = self.research.plan(self.root, self.root / pipeline.PLAN)
        self.run['research'] = {'run': status['run'],
                                'plan': workspace.sha256_file(self.root / pipeline.PLAN)}

    def found(self, ident: str, verdict: str = 'supported') -> None:
        path = self.root / SNAPSHOT
        path.parent.mkdir(exist_ok=True)
        path.write_text(f'Rolling restarts\n\n{QUOTE}\n')
        start = path.read_text().index(QUOTE)
        evidence = [] if verdict in pipeline.UNRESOLVED else [{
            'file': SNAPSHOT, 'title': 'Rolling restarts', 'origin': 'https://example.com/',
            'quote': QUOTE, 'start': start, 'locator': 'the second paragraph'}]
        self.research.record(self.root, self.run['research']['run'], ident, {
            'status': verdict, 'summary': 'What the page says.', 'limits': 'none',
            'evidence': evidence})

    def researched(self) -> None:
        self.planned()
        for ident in pipeline.survey(self.root, self.run).research.questions:
            self.found(ident)
        workspace.save(self.root, 'research', built=True)
        self.approve('research')

    def test_a_new_training_needs_its_research_plan_drafted(self):
        found = pipeline.survey(self.root, self.run)
        self.assertEqual((found.next.kind, found.next.step.id, found.next.request),
                         ('agent', 'research-plan', None))
        self.assertEqual(found.done, {'intake'})

    def test_a_draft_is_put_to_the_person_and_then_waited_on(self):
        self.kept('research-plan', json.dumps(self.plan()))
        self.assertEqual((self.next().kind, self.next().step.id),
                         ('gate', 'gate:research-plan'))
        self.gate('research-plan')
        self.assertEqual((self.next().kind, self.next().step.artifact),
                         ('wait', 'research-plan'))
        workspace.checkpoint(self.root, clear_question=True)
        self.assertEqual(self.next().kind, 'gate', 'a gate that was cleared is set again')

    def test_a_request_sends_the_step_round_again_with_what_was_asked(self):
        self.kept('research-plan', json.dumps(self.plan()))
        self.gate('research-plan')
        workspace.decide(self.root, 'research-plan', 'revise', 'Fewer questions.', by='page')
        step = self.next()
        self.assertEqual((step.kind, step.step.id, step.request['kind'],
                          step.request['note']),
                         ('agent', 'research-plan', 'revise', 'Fewer questions.'))
        self.kept('research-plan', json.dumps(self.plan()))
        self.assertEqual(self.next().kind, 'gate', 'saving the new draft closes the request')

    def test_an_approved_plan_is_handed_to_research_once(self):
        self.kept('research-plan', json.dumps(self.plan()))
        self.approve('research-plan')
        self.assertEqual((self.next().kind, self.next().step.id), ('code', 'research-start'))
        status = self.research.plan(self.root, self.root / pipeline.PLAN)
        self.assertEqual(self.next().step.id, 'research-start',
                         'until the run record says which run it was handed to')
        self.run['research'] = {'run': status['run'],
                                'plan': workspace.sha256_file(self.root / pipeline.PLAN)}
        step = self.next()
        self.assertEqual((step.kind, step.step.id, step.questions),
                         ('agent', 'research', tuple(item['id'] for item in FOUR['items'])))
        self.run['research']['run'] = 'another-run'
        self.assertEqual(self.next().step.id, 'research-start')

    def test_research_goes_on_until_every_question_has_a_finding_or_has_failed_for_good(self):
        self.planned()
        self.found('availability')
        self.found('instance-min', 'insufficient')
        self.assertEqual(self.next().questions, ('health-checks', 'zero-downtime'))
        self.run['steps']['research:health-checks'] = {'failed': 2, 'attempts': []}
        self.assertEqual(self.next().questions, ('health-checks', 'zero-downtime'))
        self.run['steps']['research:health-checks']['failed'] = 3
        self.assertEqual(self.next().questions, ('zero-downtime',))
        self.found('zero-downtime', 'contradicted')
        found = pipeline.survey(self.root, self.run)
        self.assertEqual((found.next.kind, found.next.step.id), ('code', 'research-report'))
        self.assertEqual((found.research.unread, found.research.unresolved),
                         (['health-checks'], ['instance-min']))
        self.assertEqual(found.research.verdicts, {
            'availability': 'supported', 'instance-min': 'insufficient',
            'health-checks': 'pending', 'zero-downtime': 'contradicted'})
        workspace.save(self.root, 'research', built=True)
        self.assertEqual(self.next().step.id, 'gate:research')
        self.research.status(self.root)
        self.assertEqual(self.next().step.id, 'gate:research',
                         'asking again changes nothing while the report is the same')

    def test_a_request_about_the_research_names_the_questions_to_do_again(self):
        self.planned()
        for ident, verdict in (('availability', 'supported'), ('instance-min', 'insufficient'),
                               ('health-checks', 'supported')):
            self.found(ident, verdict)
        workspace.save(self.root, 'research', built=True)
        self.gate('research')
        for note, expect in (
                (None, ['instance-min', 'zero-downtime']),
                ('Look again at health-checks.', ['instance-min', 'health-checks',
                                                  'zero-downtime']),
                ('The checks on health need work.', ['instance-min', 'zero-downtime'])):
            self.assertEqual(pipeline.again(self.root, self.run, {'note': note}), expect)
        self.found('instance-min')
        self.found('zero-downtime', 'contradicted')
        self.assertEqual(pipeline.again(self.root, self.run, {'note': 'All of it, please.'}),
                         list(pipeline.survey(self.root, self.run).research.questions))
        workspace.decide(self.root, 'research', 'rebuild', by='page')
        request = workspace.load(self.root)['requests'][0]
        self.run['research']['again'] = {'at': request['at'], 'left': ['availability']}
        step = self.next()
        self.assertEqual((step.step.id, step.questions, step.request['kind']),
                         ('research', ('availability',), 'rebuild'))
        self.run['research']['again']['left'] = []
        self.assertEqual(self.next().step.id, 'research-report')

    def test_each_blueprint_is_drafted_and_then_each_is_put_to_the_person(self):
        self.researched()
        self.assertEqual((self.next().kind, self.next().step.id), ('agent', 'blueprint'))
        self.kept('blueprint', BLUEPRINT)
        self.assertEqual(self.next().step.id, 'gate:blueprint')
        self.approve('blueprint')
        found = pipeline.survey(self.root, self.run)
        self.assertEqual((found.next.kind, found.next.step.id), ('agent', 'document'))
        self.assertEqual([step.id for step in found.steps if step.id not in found.done], [
            'document', 'gate:document', 'brief', 'gate:brief', 'scenario:main',
            'gate:scenario:main', 'package'])

    def to_blueprint(self, text: str = BLUEPRINT) -> None:
        self.researched()
        self.kept('blueprint', text)
        self.approve('blueprint')

    def made(self, *names: str) -> None:
        """Keep and approve the example of each named file, as the engine and page would."""
        texts = {'document': DOCUMENT, 'brief': BRIEF, 'scenario:main': SCENARIO,
                 'yoodli:main': YOODLI}
        for name in names:
            self.kept(name, texts[name])
            self.approve(name)

    def test_after_the_blueprint_each_file_is_written_and_put_to_the_person_in_turn(self):
        self.to_blueprint()
        for name, kind in (('document', 'document'), ('brief', 'brief'),
                           ('scenario:main', 'scenario')):
            self.assertEqual((self.next().kind, self.next().step.id), ('agent', name))
            self.assertEqual(self.next().step.stage, kind)
            self.kept(name, {'document': DOCUMENT, 'brief': BRIEF}.get(name, SCENARIO))
            self.assertEqual((self.next().kind, self.next().step.id), ('gate', f'gate:{name}'))
            self.gate(name)
            self.assertEqual(self.next().kind, 'wait')
            self.approve(name)
        self.assertEqual((self.next().kind, self.next().step.id), ('code', 'package'))

    def test_the_index_is_written_once_and_again_when_the_training_moves_on(self):
        self.to_blueprint()
        self.made('document', 'brief', 'scenario:main')
        workspace.checkpoint(self.root, stage='done', clear_question=True)
        self.assertEqual(self.next().step.id, 'package', 'the stage alone does not say so')
        (self.root / pipeline.INDEX).write_text('# Rolling restarts\n')
        found = pipeline.survey(self.root, self.run)
        self.assertEqual((found.next.kind, found.next.step), ('done', None))
        self.assertEqual(found.done, {step.id for step in found.steps})
        workspace.checkpoint(self.root, stage='document')
        self.assertEqual(self.next().step.id, 'package')

    def test_what_was_made_from_something_that_changed_is_made_again(self):
        self.to_blueprint()
        self.made('document', 'brief', 'scenario:main')
        self.kept('blueprint', BLUEPRINT.replace('three-instance', 'four-instance'))
        found = pipeline.survey(self.root, self.run)
        self.assertEqual((found.state['document'], found.state['brief'],
                          found.state['scenario:main']), ('stale', 'stale', 'approved'))
        self.assertEqual(found.next.step.id, 'gate:blueprint',
                         'nothing is made again until the change is approved')
        self.approve('blueprint')
        step = self.next()
        self.assertEqual((step.kind, step.step.id, step.request), ('agent', 'document', None))
        self.kept('document', DOCUMENT)
        self.assertEqual(self.next().step.id, 'gate:document')
        self.approve('document')
        self.assertEqual((self.next().kind, self.next().step.id), ('agent', 'brief'))

    def test_a_request_about_something_approved_sends_its_step_round_again(self):
        self.to_blueprint()
        self.made('document', 'brief')
        workspace.decide(self.root, 'document', 'revise', 'Shorter.', by='page')
        step = self.next()
        self.assertEqual((step.kind, step.step.id, step.request['note']),
                         ('agent', 'document', 'Shorter.'))

    def test_a_stage_that_is_left_out_or_cannot_be_made_is_passed_over(self):
        self.to_blueprint()
        workspace.decide(self.root, 'document', 'skip', 'No guide.', by='page')
        self.assertEqual(self.next().step.id, 'brief')
        workspace.skip(self.root, 'brief', 'No evidence to write one from.', unavailable=True)
        found = pipeline.survey(self.root, self.run)
        self.assertEqual((found.next.step.id, pipeline.wanted(found.session)),
                         ('scenario:main', ['scenario']))
        workspace.decide(self.root, 'scenario', 'skip', 'No practice.', by='page')
        found = pipeline.survey(self.root, self.run)
        self.assertEqual((found.next.step.id, found.practice, found.own),
                         ('package', {}, frozenset()))

    def test_the_practice_plan_names_the_scenarios_and_a_persons_files_join_them(self):
        self.to_blueprint()
        found = pipeline.survey(self.root, self.run)
        self.assertEqual(found.practice, {None: {'main': {
            'mode': 'roleplay', 'objectives': ['O1', 'O2', 'O3'],
            'plan': 'roleplay. Objectives: O1, O2, O3. A sceptical platform lead who saw '
                    'dropped requests last week and was told that could not happen.'}}})
        (self.root / 'scenarios').mkdir()
        (self.root / 'scenarios' / 'objection.md').write_text(SCENARIO)
        found = pipeline.survey(self.root, self.run)
        self.assertEqual((list(found.practice[None]), found.practice[None]['objection']),
                         (['main', 'objection'], {'mode': None, 'objectives': [],
                                                  'plan': None}))
        self.assertEqual(found.own, {'scenario:objection'})
        self.assertEqual(pipeline.planned(BLUEPRINT, 'missing'), None)

    def test_a_scenario_is_the_persons_unless_the_run_record_says_the_runner_drafted_it(self):
        self.to_blueprint()
        self.made('document', 'brief')
        (self.root / 'scenario.md').write_text(SCENARIO)
        step = self.next()
        self.assertEqual((step.kind, step.step.id, step.step.label),
                         ('code', 'scenario:main', 'Take in the practice scenario, as you '
                          'wrote it'))
        workspace.save(self.root, 'scenario:main')
        self.assertEqual(self.next().step.id, 'gate:scenario:main', 'it is taken in as it is')
        (self.root / 'scenario.md').write_text(SCENARIO + '\nA line added later.\n')
        self.assertEqual(self.next().step.id, 'scenario:main', 'and again when it changes')
        workspace.save(self.root, 'scenario:main')
        workspace.decide(self.root, 'scenario:main', 'revise', 'Lay it out.', by='page')
        step = self.next()
        self.assertEqual((step.kind, step.step.label, step.request['note']),
                         ('agent', 'Lay out the practice scenario, in your own words',
                          'Lay it out.'))
        self.run['drafted'] = ['scenario:main']
        found = pipeline.survey(self.root, self.run)
        self.assertEqual((found.own, found.next.kind, found.next.step.label),
                         (frozenset(), 'agent', 'Draft the practice scenario'))

    def test_copies_are_made_after_an_approval_and_one_that_was_tried_holds_nothing_up(self):
        self.to_blueprint()
        wanted = [{'artifact': 'document', 'kind': 'word', 'state': 'not-made',
                   'label': 'the learner guide', 'link': None, 'problem': None}]

        def next_with(copies) -> pipeline.Next:
            return pipeline.survey(self.root, self.run, copies).next

        self.assertEqual(next_with(wanted).step.id, 'document')
        self.made('document')
        found = pipeline.survey(self.root, self.run, wanted)
        self.assertEqual((found.next.kind, found.next.step.id, found.copies),
                         ('code', 'copies:document', tuple(wanted)))
        self.assertNotIn('copies:brief', [step.id for step in found.steps])
        self.assertEqual(next_with([{**wanted[0], 'state': 'made'}]).step.id, 'brief')
        self.assertEqual(next_with([{**wanted[0], 'state': 'out-of-date'}]).step.id,
                         'copies:document')
        approved = workspace.load(self.root)['artifacts']['document']['approved']['sha256']
        self.run['copies'] = {'problems': {}, 'tried': {'document': approved}}
        self.assertEqual(next_with(wanted).step.id, 'brief', 'it was tried for this version')
        self.kept('document', DOCUMENT + '\nOne more line.\n')
        self.approve('document')
        self.assertEqual(next_with(wanted).step.id, 'copies:document',
                         'a copy is made again when its document is approved again')
        self.assertEqual(next_with([]).step.id, 'brief')

    def test_a_deck_that_is_wanted_is_all_that_is_left_before_the_index(self):
        workspace.decide(self.root, 'deck', 'restore', by='page')
        self.to_blueprint()
        self.made('document', 'brief', 'scenario:main')
        found = pipeline.survey(self.root, self.run)
        self.assertEqual((found.next.kind, found.next.step.id, found.next.step.stage),
                         ('deck', 'deck', 'deck'))
        self.assertEqual(pipeline.deck_says(found),
                         pipeline.DECK_LEFT.format(why=pipeline.NOT_LOOKED))
        (self.root / 'deck.pptx').write_bytes(b'PK\x03\x04 a deck\n')
        found = pipeline.survey(self.root, self.run)
        self.assertEqual((found.next.kind, pipeline.deck_says(found)),
                         ('deck', pipeline.DECK_AGAIN.format(why=pipeline.NOT_LOOKED)))
        workspace.decide(self.root, 'deck', 'skip', 'No slides.', by='page')
        self.assertEqual(self.next().step.id, 'package')

    def test_a_yoodli_scenario_follows_each_approved_scenario(self):
        workspace.decide(self.root, 'yoodli', 'restore', by='page')
        self.to_blueprint()
        self.made('document', 'brief')
        self.assertEqual([step.id for step in pipeline.survey(self.root, self.run).steps][13:], [
            'scenario:main', 'gate:scenario:main', 'yoodli:main', 'gate:yoodli:main',
            'package'])
        self.made('scenario:main')
        self.assertEqual((self.next().kind, self.next().step.id), ('agent', 'yoodli:main'))
        self.made('yoodli:main')
        self.assertEqual(self.next().step.id, 'package')
        self.kept('brief', BRIEF + '\nOne more unknown.\n')
        self.approve('brief')
        self.assertEqual((self.next().kind, self.next().step.id), ('agent', 'yoodli:main'))

    def test_a_training_from_the_persons_documents_waits_until_they_are_all_added(self):
        self.run['documents'] = {'scope': 'supplied-only', 'done': None, 'count': 0}
        readable = [{'name': 'handbook.txt', 'readable': True}]
        found = pipeline.survey(self.root, self.run, supplied=readable)
        self.assertEqual((found.next.kind, found.next.step.id, found.scope,
                          [step.id for step in found.steps][:3]),
                         ('documents', 'documents', 'supplied-only',
                          ['intake', 'documents', 'research-plan']))
        self.run['documents'].update(done='2026-10-13T10:00:00Z', count=1)
        self.assertEqual(pipeline.survey(self.root, self.run, supplied=readable).next.kind,
                         'documents', 'this computer has not been told that is all of them')
        (self.root / pipeline.ADDED).parent.mkdir()
        (self.root / pipeline.ADDED).write_text('2026-10-13T10:00:00Z\n')
        self.assertEqual(pipeline.survey(self.root, self.run, supplied=readable).next.step.id,
                         'research-plan')
        self.assertEqual(pipeline.survey(self.root, self.run, supplied=[]).next.kind,
                         'documents', 'the documents are not on this computer')
        self.run['documents']['count'] = 0
        self.assertEqual(pipeline.survey(self.root, self.run).next.step.id, 'research-plan')
        self.run['documents']['count'] = 1
        self.researched()
        self.assertEqual(pipeline.survey(self.root, self.run).next.step.id, 'blueprint',
                         'once the research is approved nothing needs them')
        self.assertEqual(pipeline.survey(self.root, {'steps': {}}).scope, 'public-web')

    def test_answers_changed_by_hand_are_put_to_the_person_and_so_is_what_they_date(self):
        self.researched()
        self.kept('blueprint', BLUEPRINT)
        intake = self.root / 'intake.md'
        intake.write_text(intake.read_text().replace('Field enablement', 'Upskilling'))
        found = pipeline.survey(self.root, self.run)
        self.assertEqual(found.state['intake'], 'draft')
        self.assertEqual((found.next.kind, found.next.step.id, found.next.step.artifact),
                         ('gate', 'gate:intake', 'intake'))
        self.approve('intake')
        found = pipeline.survey(self.root, self.run)
        self.assertEqual((found.state['research-plan'], found.next.step.id),
                         ('stale', 'gate:research-plan'))

    def test_a_training_whose_answers_are_gone_is_stuck_and_says_so(self):
        (self.root / 'intake.md').unlink()
        step = self.next()
        self.assertEqual(step.kind, 'stuck')
        self.assertIn('The answers this training was started from are missing', step.why)

    def test_the_run_record_says_how_often_a_step_has_failed(self):
        self.assertEqual(pipeline.tries(None, 'research-plan'),
                         {'failed': 0, 'attempts': []})
        run = {'steps': {'research-plan': {'failed': 3, 'attempts': [{}, {}, {}]}}}
        self.assertEqual((pipeline.spent(run, 'research-plan'), pipeline.spent(run, 'blueprint'),
                          pipeline.ATTEMPTS), (True, False, 3))


class WorkTests(StudioCase):
    def setUp(self):
        super().setUp()
        self.root = pipeline.create(self.space, pipeline.check_form(
            {**FORM, 'levels': ['101', '301'], 'brief_kind': 'competitive'}))

    def test_a_drafting_job_is_told_why_it_is_being_done_again(self):
        found = pipeline.survey(self.root)
        step = found.next.step
        first = pipeline.work(self.root, found, step, None, None, [])
        self.assertNotIn('again', first.task)
        self.assertIn('Levels: 101, 301', first.task)
        self.assertIn('Kind of brief: competitive; the topic names the two sides compared',
                      first.task)
        self.assertEqual((first.profile, first.name, first.prepared['ask'],
                          first.prepared['artifacts']), ('write', 'research-plan', True, {
                              'research-plan': {'kind': 'research-plan', 'scope': 'public-web',
                                                'sources': []}}))
        again = pipeline.work(
            self.root, found, step, {'kind': 'rebuild', 'note': 'Start from the basics.'},
            'It did not finish in 900 seconds, so it was stopped.',
            [{'question': 'Which platform?', 'answer': 'The public one.'}] * 3)
        self.assertIn('The person asked for the questions to be made again from the start. '
                      'They added:\n\nStart from the basics.', again.task)
        self.assertIn('Question: Which platform?\nAnswer: The public one.', again.task)
        self.assertIn('An earlier try at this job did not work: It did not finish in 900 '
                      'seconds, so it was stopped.', again.task)
        self.assertFalse(again.prepared['ask'], 'a step may ask only so many questions')

    def test_a_blueprint_job_is_for_one_level_and_says_whether_practice_is_wanted(self):
        found = pipeline.survey(self.root)
        step = next(step for step in found.steps if step.id == 'blueprint@301')
        wanted = pipeline.blueprint_work(self.root, found, step, None, None, [])
        self.assertIn('Draft the level 301 blueprint for this training.', wanted.task)
        self.assertIn('This blueprint is for level 301.', wanted.task)
        self.assertIn('Practice scenarios are wanted: plan them.', wanted.task)
        self.assertEqual(wanted.prepared['artifacts']['blueprint']['level'], '301')
        self.assertEqual(wanted.guidance, pipeline.briefs.guidance('blueprint', level='301'))
        (self.root / '301' / 'scenarios').mkdir(parents=True)
        (self.root / '301' / 'scenarios' / 'objection.md').write_text('# Scenario: x\n')
        own = pipeline.blueprint_work(self.root, pipeline.survey(self.root), step, None, None,
                                      [])
        self.assertIn('The person already has these practice scenarios: objection. List them '
                      'in the practice plan.', own.task)
        workspace.decide(self.root, 'scenario', 'skip', 'No practice.', by='page')
        skipped = pipeline.blueprint_work(self.root, pipeline.survey(self.root), step, None,
                                          None, [])
        self.assertIn('Practice scenarios are not wanted: leave the practice plan out.',
                      skipped.task)

    def test_why_a_job_handed_nothing_back_is_said_in_a_sentence(self):
        nothing = {'problems': {}}
        self.assertEqual(pipeline.why_not(nothing, ''),
                         'It ended without handing anything back.')
        self.assertEqual(pipeline.why_not(nothing, 'It ran out of time.'),
                         'It ran out of time.')
        refused = {'problems': {'blueprint': ['One.', 'Two.', 'Three.', 'Four.'], 'x': []}}
        self.assertEqual(pipeline.why_not(refused, 'It ran out of time.'), 'What it handed '
                         'back did not pass the checks: One. Two. Three. And more.')

    def test_the_research_wrapper_is_the_one_the_foundations_built(self):
        self.assertIs(type(self.research), research.Research)
        self.assertEqual(Path(pipeline.PLAN), Path('.training-studio/research-plan.json'))
        self.assertEqual(Path(pipeline.REPORT), Path('.harness-research/research-report.md'))


if __name__ == '__main__':
    import unittest
    unittest.main()
