"""The pipelines as data, the form, and where a training is, worked out from its files.

Nothing here runs a worker: each test puts files in place through the core, as the engine
would, and asks what comes next.
"""
import json
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401
from runner_support import BLUEPRINT, FORM, FOUR, StudioCase

import workspace
from runner import pipeline, research
from workspace import WorkspaceError

SNAPSHOT = 'sources/docs-example-com-0123456789ab.txt'
QUOTE = 'Capacity holds only when more than one instance is running.'


class DefinitionTests(StudioCase):
    def test_the_training_pipeline_is_data_as_far_as_the_blueprint(self):
        stages = list(dict.fromkeys(row[0] for row in pipeline.TRAINING))
        self.assertEqual(stages, ['intake', 'research-plan', 'research', 'blueprint'])
        self.assertEqual([(row[1], row[2]) for row in pipeline.TRAINING], [
            ('intake', 'code'), ('research-plan', 'agent'), ('gate:research-plan', 'gate'),
            ('research-start', 'code'), ('research', 'agent'), ('research-report', 'code'),
            ('gate:research', 'gate'), ('blueprint', 'agent'), ('gate:blueprint', 'gate')])
        self.assertEqual([name for name, _ in pipeline.RESEARCH],
                         ['research-start', 'research', 'research-report'])
        self.assertEqual({stage for stage in stages} - set(workspace.STAGES), set())

    def test_a_trainings_steps_are_laid_out_in_the_order_they_are_walked(self):
        plain = pipeline.steps([])
        self.assertEqual([(step.id, step.kind, step.artifact) for step in plain][-2:],
                         [('blueprint', 'agent', 'blueprint'),
                          ('gate:blueprint', 'gate', 'blueprint')])
        self.assertEqual([step.label for step in plain], [
            'Record your answers', 'Draft the research plan',
            'Your review of the research plan', 'Hand the approved questions to research',
            'Research each question', 'Write the research report',
            'Your review of the research report', 'Draft the blueprint',
            'Your review of the blueprint'])
        self.assertEqual(plain[1].doing, 'Drafting the research plan')
        levelled = pipeline.steps(['101', '301'])
        self.assertEqual([(step.id, step.artifact, step.label) for step in levelled][-4:], [
            ('blueprint@101', 'blueprint@101', 'Draft the level 101 blueprint'),
            ('blueprint@301', 'blueprint@301', 'Draft the level 301 blueprint'),
            ('gate:blueprint@101', 'blueprint@101', 'Your review of the level 101 blueprint'),
            ('gate:blueprint@301', 'blueprint@301', 'Your review of the level 301 blueprint')])
        self.assertEqual({step.stage for step in levelled[-4:]}, {'blueprint'})

    def test_it_asks_for_a_decision_twice_and_once_more_for_each_blueprint(self):
        for levels, expect in (([], 3), (['101'], 3), (['101', '201'], 4),
                               (['101', '201', '301', '401'], 6)):
            form = pipeline.check_form({**FORM, 'levels': levels})
            self.assertEqual(pipeline.gates(form), expect)
            gates = [step for step in pipeline.steps(form['levels']) if step.kind == 'gate']
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
            'yoodli': False, 'agent': None, 'model': None})

    def test_only_the_public_web_is_taken_as_the_source_scope(self):
        self.assertEqual(pipeline.check_form(FORM)['source_scope'], 'public-web')
        for scope in ('supplied-only', 'both'):
            with self.assertRaises(WorkspaceError) as refused:
                pipeline.check_form({**FORM, 'source_scope': scope})
            self.assertEqual(str(refused.exception), pipeline.NOT_YET)
        with self.assertRaisesRegex(WorkspaceError, 'The source scope is one of'):
            pipeline.check_form({**FORM, 'source_scope': 'the-moon'})

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
        self.assertEqual((found.next.kind, found.next.step), ('done', None))
        self.assertEqual(found.done, {step.id for step in found.steps})

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
