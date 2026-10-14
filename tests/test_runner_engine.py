"""The engine, from the form to gate 3, with scripted workers and the stand-in for
harness-research. No agent is started and nothing touches the network. What comes after
the blueprints is in test_runner_flow.py.

Most classes drive the engine in the test's own thread, so each step has finished when a
call returns. LiveTests lets it run on threads of its own, as the runner does.
"""
import json
import re
import threading
import time
from dataclasses import replace
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401
from runner_support import FORM, FOUR, QUESTIONS, StudioCase, asks, fails

import home
import workspace
from runner import agents, gitstate, pipeline, research, settings, worker_tools
from runner.agents import Outcome
from runner.engine import ACTIONS
from workspace import WorkspaceError

AVOIDED = re.compile(r'\b(artifacts?|stale|lineage)\b', re.IGNORECASE)
SLOW = 'It did not finish in 900 seconds, so it was stopped.'
STEPS = ['intake', 'research-plan', 'gate:research-plan', 'research-start', 'research',
         'research-report', 'gate:research', 'blueprint', 'gate:blueprint', 'document',
         'gate:document', 'brief', 'gate:brief', 'package']


class Crash(BaseException):
    """The runner's process ending in the middle of something."""


class FormToGateThreeTests(StudioCase):
    def test_the_form_becomes_a_training_made_through_the_core_in_page_mode(self):
        root = self.start()
        self.assertEqual(root, self.space.training('rolling-restarts'))
        status = workspace.status(root)
        self.assertEqual((status['approval'], status['artifacts']['intake'], status['title']),
                         ('page', 'approved', 'Rolling restarts'))
        session = workspace.load(root)
        self.assertEqual(session['artifacts']['intake']['approved']['by'], 'page')
        self.assertEqual((root / 'intake.md').read_text(), (
            '## Topic\n\nRolling restarts on the platform\n\n## Levels\n\nNone\n\n'
            '## Brief\n\nproduct\n\n## Audience\n\nSolutions engineers who deploy apps\n\n'
            '## Purpose\n\nField enablement\n\n## Source scope\n\nPublic web\n\n'
            '## Time limit\n\n25 minutes\n'))
        with self.assertRaisesRegex(WorkspaceError, 'decided on the page'):
            workspace.approve(root, 'research-plan')

    def test_it_stops_at_each_gate_and_a_decision_wakes_it(self):
        root = self.start()
        view = self.view(root)
        self.assertEqual((view['state'], view['sentence'], view['agent'], view['model']),
                         ('waiting', 'The research plan is waiting for your review.',
                          'claude', None))
        self.assertEqual([step['id'] for step in view['steps']], STEPS)
        self.assertEqual({step['id']: step['status'] for step in view['steps']}, {
            **dict.fromkeys(STEPS, 'to-do'), 'intake': 'done', 'research-plan': 'done',
            'gate:research-plan': 'waiting'})
        self.assertEqual((view['workers'], view['question'], view['problem']),
                         ([], None, None))
        status = workspace.status(root)
        self.assertEqual((status['gate'], status['pending_question'], status['stage']),
                         ('research-plan', 'Approve the research plan?', 'research-plan'))
        self.assertEqual(len(self.workers.jobs), 1)

        said = self.decide(root, 'research-plan')
        self.assertEqual(said['said'],
                         'Approved. The research report is waiting for your review.')
        self.assertEqual(said['next']['artifact'], 'research')
        self.assertEqual((self.state(root), workspace.status(root)['gate']),
                         ('waiting', 'research'))
        self.assertEqual(self.view(root)['sentence'],
                         'The research report is waiting for your review.')
        self.assertEqual(workspace.status(root)['research']['findings'],
                         {'supported': 3, 'contradicted': 1})
        self.assertEqual(len(self.workers.of('question')), 4)

        self.decide(root, 'research')
        self.assertEqual((self.state(root), workspace.status(root)['gate']),
                         ('waiting', 'blueprint'))
        self.assertEqual(len(self.workers.jobs), 6)

        said = self.decide(root, 'blueprint')
        self.assertEqual(said['said'], 'Approved. The learner guide is waiting for your review.')
        view, status = self.view(root), workspace.status(root)
        self.assertEqual((view['state'], status['stage'], status['gate']),
                         ('waiting', 'document', 'document'))
        self.assertEqual({status['artifacts'][name] for name in
                          ('intake', 'research-plan', 'research', 'blueprint')}, {'approved'})
        self.assertEqual([step['id'] for step in view['steps']],
                         STEPS[:-1] + ['scenario:main', 'gate:scenario:main', 'package'],
                         'the blueprint has named a practice scenario')
        self.assertEqual(len(self.workers.jobs), 7)

    def test_every_kept_step_and_every_decision_is_a_commit_that_says_what_happened(self):
        (self.space.repo / 'README.md').write_text('# Another tool keeps this\n')
        (self.space.repo / 'notes.txt').write_text('Staged by someone else.\n')
        self.git('add', 'notes.txt')
        self.engine = self.make(at_once=1)
        root = self.start()
        self.to_end(root)
        self.assertEqual(self.log(), ['Set up the Training Studio workspace in trainings/'] + [
            f'Rolling restarts: {what}' for what in (
                'start the training from the form',
                'keep the research plan',
                'ask for a review of the research plan',
                'The research plan was approved on the page.',
                'hand the approved questions to research',
                'keep the finding for availability',
                'keep the finding for instance-min',
                'keep the finding for health-checks',
                'keep the finding for zero-downtime',
                'keep the research report',
                'ask for a review of the research report',
                'The research report was approved on the page.',
                'keep the blueprint',
                'ask for a review of the blueprint',
                'The blueprint was approved on the page.',
                'keep the learner guide',
                'ask for a review of the learner guide',
                'The learner guide was approved on the page.',
                'keep the brief',
                'ask for a review of the brief',
                'The brief was approved on the page.',
                'keep the practice scenario',
                'ask for a review of the practice scenario',
                'The practice scenario was approved on the page.',
                'write the index; the training is finished')])
        self.assertEqual(self.git('status', '--porcelain'), 'A  notes.txt\n?? README.md'.strip())
        changed = self.git('log', '--format=', '--name-only').split()
        self.assertTrue(changed)
        self.assertEqual({name.split('/')[0] for name in changed}, {'trainings'})
        self.assertNotIn('sources', {part for name in changed for part in name.split('/')})
        self.assertTrue(list((root / 'sources').glob('docs-example-com-*.txt')))
        self.assertEqual(self.git('log', '-1', '--format=%an <%ae>'),
                         'Alex <alex@example.com>')

    def test_with_levels_every_blueprint_is_drafted_and_each_is_reviewed_in_turn(self):
        made = self.engine.start(pipeline.check_form({**FORM, 'levels': ['301', '101']}))
        root = Path(made['path'])
        self.assertEqual(made, {'path': str(root), 'id': 'rolling-restarts', 'gates': 8})
        self.assertEqual([step['id'] for step in self.view(root)['steps']][7:11],
                         ['blueprint@101', 'blueprint@301', 'gate:blueprint@101',
                          'gate:blueprint@301'])
        self.to_gate(root, 'blueprint@101')
        self.assertEqual([spec['artifacts']['blueprint']['level']
                          for _, _, spec in self.workers.jobs[-2:]], ['101', '301'])
        self.assertIn('This blueprint is for level 301.', self.workers.jobs[-1][1].task)
        self.assertIn('## This blueprint is for level 301', self.workers.jobs[-1][1].guidance)
        self.assertEqual(self.view(root)['sentence'],
                         'The level 101 blueprint is waiting for your review.')
        self.decide(root, 'blueprint@101')
        self.assertEqual((self.state(root), workspace.status(root)['gate']),
                         ('waiting', 'blueprint@301'))
        self.decide(root, 'blueprint@301')
        self.assertEqual((self.state(root), self.view(root)['sentence']), (
            'waiting', 'The level 101 learner guide is waiting for your review.'))
        self.assertIn('Level: 301', (root / '301' / 'blueprint.md').read_text())

    def test_the_run_record_holds_what_the_files_cannot_say_and_is_committed(self):
        settings.save(replace(settings.load(), model='a-model', step_seconds=300))
        self.workers.cost = 0.25
        root = self.start()
        record = self.record(root)
        self.assertEqual((record['agent'], record['model'], record['limits']),
                         ('claude', 'a-model',
                          {'step_seconds': 300, 'training_dollars': 20.0}))
        attempt = record['steps']['research-plan']['attempts'][0]
        self.assertEqual((attempt['outcome'], attempt['error'], attempt['dollars'],
                          attempt['tokens'], attempt['seconds']),
                         ('kept', None, 0.25, 1200, 1.5))
        self.assertRegex(attempt['started_at'] + attempt['ended_at'],
                         r'^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ){2}$')
        committed = self.git('show', 'HEAD:trainings/rolling-restarts/.training-studio/run.json')
        self.assertEqual(json.loads(committed), record)
        view = self.view(root)
        self.assertEqual((view['spent'], view['model']),
                         ({'dollars': 0.25, 'tokens': 1200}, 'a-model'))
        step = self.steps(root)['research-plan']
        self.assertEqual((step['attempts'], step['seconds'], step['dollars'], step['kind'],
                          step['label']), (1, 1.5, 0.25, 'agent', 'Draft the research plan'))
        self.assertEqual((self.steps(root)['gate:research-plan']['kind'],
                          self.steps(root)['intake']['kind']), ('gate', 'code'))

    def test_the_agent_is_chosen_when_the_training_starts_and_does_not_change(self):
        other = type(self.workers)()
        self.engine.adapters['codex'] = agents.Scripted(other)
        root = self.start(agent='codex', model='their-model')
        self.assertEqual((self.view(root)['agent'], self.view(root)['model']),
                         ('codex', 'their-model'))
        settings.save(replace(settings.load(), agent='claude', model='another'))
        self.to_gate(root, 'blueprint')
        self.assertEqual((len(other.jobs), len(self.workers.jobs)), (6, 0))
        self.assertEqual({job.model for _, job, _ in other.jobs}, {'their-model'})
        self.assertEqual(self.view(root)['agent'], 'codex')

    def test_an_agent_that_is_not_ready_starts_nothing(self):
        away = agents.Readiness('claude', True, True, False, '2.1', 'Claude Code is signed '
                                'in but cannot be used from this network. Try another.')
        with mock.patch.object(self.adapters['claude'], 'ready', return_value=away):
            with self.assertRaisesRegex(WorkspaceError, 'cannot be used from this network'):
                self.start()
        self.assertEqual((self.engine.trainings(), self.workers.jobs), ([], []))
        self.assertFalse(self.space.training('rolling-restarts').exists())

    def test_a_title_already_in_the_workspace_is_refused(self):
        self.start()
        with self.assertRaisesRegex(WorkspaceError, 'already has a training in trainings/'
                                    'rolling-restarts. Give this one a different title'):
            self.start(topic='Something else')
        self.assertEqual(len(self.engine.trainings()), 1)

    def test_without_a_workspace_nothing_starts(self):
        gitstate.settings_path().unlink()
        with self.assertRaisesRegex(WorkspaceError, 'No workspace is set up on this computer'):
            self.start()

    def test_nothing_a_person_reads_uses_the_words_the_page_avoids(self):
        self.workers.then('research-plan', asks('Which platform is this about?'))
        self.workers.then('question:health-checks', fails(SLOW, 'timeout'), fails(SLOW),
                          fails(SLOW))
        self.workers.then('blueprint', fails(), fails(), fails())
        root, said = self.start(), []

        def note() -> None:
            view = self.view(root)
            said.extend([view['sentence'], *(step['label'] for step in view['steps']),
                         *(step['error'] or '' for step in view['steps']),
                         *(view['question'] or {}).values(),
                         *((view['problem'] or {}).values())])

        note()
        self.engine.answer(root, self.view(root)['question']['id'], 'The public platform.')
        note()
        self.decide(root, 'research-plan')
        note()
        said.append(self.decide(root, 'research')['said'])
        note()
        self.assertEqual(self.state(root), 'failed')
        said += [(root / 'reviews' / f'{name}.md').read_text()
                 for name in ('research-plan', 'research')]
        said += self.log()
        for text in said:
            self.assertIsNone(AVOIDED.search(str(text or '')), text)


class WorkerTests(StudioCase):
    """What a worker is given, and that it is given nothing else."""

    def test_a_worker_has_only_the_worker_tools_and_a_folder_outside_the_workspace(self):
        seen = []

        def looking(act):
            def script(tools, job):
                seen.append((job.folder, sorted(path.name for path in job.folder.iterdir())))
                return act(tools, job)
            return script

        self.workers.then('research-plan', looking(self.workers.research_plan))
        self.workers.then('question', *[looking(self.workers.question)] * 4)
        self.workers.then('blueprint', looking(self.workers.blueprint))
        root = self.start()
        self.to_gate(root, 'blueprint')
        profiles = {kind.partition(':')[0]: (job.profile, spec['fetch'], spec['ask'])
                    for kind, job, spec in self.workers.jobs}
        self.assertEqual(profiles, {'research-plan': ('write', False, True),
                                    'question': ('research', True, False),
                                    'blueprint': ('write', False, True)})
        for kind, job, spec in self.workers.jobs:
            self.assertEqual(list(job.tools), worker_tools.command(job.folder))
            self.assertEqual(job.folder.parent, agents.staging())
            self.assertNotIn(self.space.repo, job.folder.parents)
            self.assertEqual((job.limits.seconds, job.limits.dollars), (900, 20.0))
        for folder, held in seen:
            self.assertIn(held, (['inputs', 'job.json', 'sources'], ['job.json', 'sources']))
            self.assertFalse(folder.exists(), 'a job folder is removed once its work is kept')
        self.assertEqual(len({folder for folder, _ in seen}), 6)

    def test_what_a_worker_is_told_says_what_the_training_is_about(self):
        root = self.start()
        self.to_gate(root, 'blueprint')
        plan, question, blueprint = (self.workers.of(kind)[0] for kind in
                                     ('research-plan', 'question:instance-min', 'blueprint'))
        for job in (plan, question, blueprint):
            self.assertIn('Topic: Rolling restarts on the platform', job.task)
            self.assertIn('Audience: Solutions engineers who deploy apps', job.task)
            self.assertIn('Purpose: Field enablement', job.task)
        self.assertEqual(plan.guidance, pipeline.briefs.guidance('research-plan'))
        self.assertIn('Hand the questions back with submit_artifact under the name '
                      '"research-plan".', plan.task)
        self.assertIn('Sources that may be used: the public web.', plan.task)
        self.assertEqual(question.guidance, pipeline.briefs.guidance('research-question'))
        self.assertIn('Question ID: instance-min\nQuestion: How many instances keep capacity '
                      'during a restart?\nSearch words to start from: rolling restart '
                      'instance-min', question.task)
        self.assertEqual(blueprint.guidance, pipeline.briefs.guidance('blueprint'))
        self.assertIn('Your inputs are "intake" and "research findings".', blueprint.task)
        self.assertIn('Practice scenarios are wanted: plan them.', blueprint.task)
        spec = self.workers.jobs[-1][2]
        self.assertEqual([entry['name'] for entry in spec['inputs']],
                         ['intake', 'research findings'])
        self.assertEqual(spec['artifacts']['blueprint']['findings'], {
            'availability': 'supported', 'instance-min': 'supported',
            'health-checks': 'supported', 'zero-downtime': 'contradicted'})
        findings = pipeline.findings_text(root)
        self.assertIn('## instance-min\n\nQuestion: How many instances keep capacity during a '
                      'restart?\nVerdict: supported\nSummary: What the page says about '
                      'instance-min.\nLimits: none\nQuoted from Rolling restarts '
                      '(https://docs.example.com/restarts): "Capacity holds only when more '
                      'than one instance is running."', findings)

    def test_the_review_at_a_gate_carries_the_checks_and_the_workers_own_notes(self):
        root = self.start()
        review = (root / 'reviews' / 'research-plan.md').read_text()
        self.assertRegex(review, r'## Ready for your review, \d{4}-')
        self.assertIn('> Checked for you: 1 check passed.', review)
        self.assertIn("> The worker's own notes on its draft. They are its judgment, not a "
                      'check:\n>\n> Four questions. I left rollback out: it is a topic of its '
                      'own.', review)
        self.to_gate(root, 'blueprint')
        self.assertIn('> 3 of 4 questions have an answer the sources support.\n> 1 more state '
                      'a claim that the sources contradict.\n> Every question was researched '
                      'and settled.', (root / 'reviews' / 'research.md').read_text())
        blueprint = (root / 'reviews' / 'blueprint.md').read_text()
        self.assertIn('> Checked for you: 4 checks passed.', blueprint)
        # Approving a blueprint commits the person to a decision on each scenario it plans.
        self.assertIn('> It plans 1 practice scenario: main. Each comes to you for review: 1 '
                      'more decision for this blueprint. To have fewer, ask for changes here.',
                      blueprint)


class RetryTests(StudioCase):
    def test_a_draft_the_checks_refuse_is_fixed_by_the_worker_and_then_kept(self):
        def careless(tools, job):
            first = tools.submit_artifact('research-plan', json.dumps(
                {'topic': 'Rolling restarts', 'items': [{'id': 'Not An ID', 'question': ''}]}))
            assert not first[0] and 'needs an "id"' in first[1], first
            self.workers.research_plan(tools, job)

        self.workers.then('research-plan', careless)
        root = self.start()
        step = self.steps(root)['research-plan']
        self.assertEqual((self.state(root), step['status'], step['attempts'], step['error']),
                         ('waiting', 'done', 1, None))
        kept = json.loads((root / pipeline.PLAN).read_text())
        self.assertEqual(([item['id'] for item in kept['items']], kept['scope'],
                          kept['purpose']), (list(QUESTIONS), 'public-web', 'planning'))

    def test_a_try_that_hands_nothing_back_is_made_again_with_the_reason(self):
        def never_right(tools, job):
            tools.submit_artifact('research-plan', '{"topic": "Rolling restarts"}')

        self.workers.then('research-plan', fails(SLOW, 'timeout'), never_right)
        root = self.start()
        first, second, third = self.workers.of('research-plan')
        self.assertNotIn('An earlier try', first.task)
        self.assertIn(f'An earlier try at this job did not work: {SLOW}', second.task)
        self.assertIn('An earlier try at this job did not work: What it handed back did not '
                      'pass the checks: "items" must hold 1 to 30 questions.', third.task)
        self.assertEqual(len({first.folder, second.folder, third.folder}), 3)
        step, entry = self.steps(root)['research-plan'], self.record(root)['steps'][
            'research-plan']
        self.assertEqual((self.state(root), step['status'], step['attempts'], step['error']),
                         ('waiting', 'done', 3, None))
        self.assertEqual(([attempt['outcome'] for attempt in entry['attempts']],
                          entry['failed'], entry['attempts'][0]['error']),
                         (['failed', 'failed', 'kept'], 0, SLOW))
        self.assertIn('Rolling restarts: a try at this step did not work: Draft the research '
                      'plan', self.log())

    def test_a_step_that_fails_three_times_stops_the_training_and_says_what_went_wrong(self):
        self.workers.then('research-plan', fails(SLOW, 'timeout'), fails(), fails(
            'It stopped without finishing: its spending limit was reached', 'limit'))
        root = self.start()
        view = self.view(root)
        self.assertEqual((view['state'], len(self.workers.jobs)), ('failed', 3))
        self.assertEqual(view['problem'], {
            'what': 'This step did not work in 3 tries: Draft the research plan. The last '
                    'one: It stopped without finishing: its spending limit was reached',
            'kept': 'Everything kept before this step is still here. Nothing from the tries '
                    'that failed was kept.',
            'action': 'retry', 'label': 'Try again'})
        self.assertEqual(view['sentence'], view['problem']['what'])
        step = self.steps(root)['research-plan']
        self.assertEqual((step['status'], step['attempts']), ('failed', 3))
        self.assertIn('its spending limit was reached', step['error'])
        self.assertFalse((root / pipeline.PLAN).exists())
        self.assertEqual(workspace.status(root)['artifacts']['research-plan'], 'not-started')
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertTrue(self.log()[-1].startswith('Rolling restarts: stop. This step did not'))

        self.engine.wake(root)
        self.assertEqual(len(self.workers.jobs), 3, 'a failed run starts nothing by itself')
        after = self.engine.act(root, 'retry')
        self.assertEqual((after['state'], after['problem'], len(self.workers.jobs)),
                         ('waiting', None, 4))
        self.assertEqual(self.steps(root)['research-plan']['status'], 'done')

    def test_an_agent_that_cannot_be_used_is_not_tried_again_until_asked(self):
        self.workers.then('research-plan', fails('Claude Code is not installed on this '
                                                 'computer.', 'unavailable'))
        root = self.start()
        view = self.view(root)
        self.assertEqual((view['state'], len(self.workers.jobs)), ('failed', 1))
        self.assertEqual(view['problem']['what'], 'scripted could not be used. Claude Code is '
                         'not installed on this computer.')
        self.assertEqual(self.engine.act(root, 'retry')['state'], 'waiting')

    def test_a_worker_that_runs_out_of_time_is_tried_again(self):
        self.workers.then('blueprint', fails(SLOW, 'timeout'))
        root = self.start()
        self.to_gate(root, 'blueprint')
        self.assertEqual(self.steps(root)['blueprint']['attempts'], 2)
        self.assertIn(SLOW, self.workers.of('blueprint')[1].task)

    def test_something_the_runner_did_not_expect_stops_one_training_and_says_so(self):
        def broken(tools, job):
            raise RuntimeError('the adapter broke')

        self.workers.then('research-plan', broken)
        root = self.start()
        view = self.view(root)
        self.assertEqual((view['state'], view['problem']['what'], view['problem']['action']),
                         ('failed', 'The runner could not go on: RuntimeError: the adapter '
                          'broke', 'retry'))
        self.assertEqual(self.engine.act(root, 'retry')['state'], 'waiting')


class RequestTests(StudioCase):
    def test_asking_for_changes_runs_the_step_again_with_the_note(self):
        root = self.start()
        shorter = {**FOUR, 'items': FOUR['items'][:3]}

        def revised(tools, job):
            tools.submit_artifact('research-plan', json.dumps(shorter))
            tools.submit_review('I dropped the zero-downtime question, as asked.')

        self.workers.then('research-plan', revised)
        said = self.decide(root, 'research-plan', 'revise',
                           'Drop the zero-downtime question.')
        self.assertIn('Your changes are noted.', said['said'])
        task = self.workers.of('research-plan')[1].task
        self.assertIn('You are revising an earlier draft. What the person asked for:\n\n'
                      'Drop the zero-downtime question.', task)
        self.assertIn('The earlier draft:\n\n- availability: When does a rolling restart '
                      'keep capacity?\n', task)
        status = workspace.status(root)
        self.assertEqual((status['requests'], status['gate'], self.state(root)),
                         ([], 'research-plan', 'waiting'))
        self.assertEqual(len(json.loads((root / pipeline.PLAN).read_text())['items']), 3)
        review = (root / 'reviews' / 'research-plan.md').read_text()
        self.assertIn('> This version was made because you asked for changes: Drop the '
                      'zero-downtime question.', review)
        self.assertEqual(self.log()[-3:], [
            'Rolling restarts: Changes to the research plan were asked for on the page: Drop '
            'the zero-downtime question.',
            'Rolling restarts: keep the research plan',
            'Rolling restarts: ask for a review of the research plan'])
        self.assertEqual(self.steps(root)['research-plan']['attempts'], 2)

    def test_asking_for_a_rebuild_runs_the_step_again_from_the_start(self):
        root = self.start()
        self.to_gate(root, 'blueprint')
        self.decide(root, 'blueprint', 'rebuild')
        task = self.workers.of('blueprint')[1].task
        self.assertIn('The person asked for the blueprint to be made again from the start.',
                      task)
        self.assertEqual((workspace.status(root)['requests'], workspace.status(root)['gate']),
                         ([], 'blueprint'))
        self.assertIn('> This version was made because you asked for a new draft.',
                      (root / 'reviews' / 'blueprint.md').read_text())

    def test_a_request_gives_a_step_that_had_failed_a_fresh_start(self):
        root = self.start()
        self.workers.then('research-plan', fails(), fails(), fails())
        self.decide(root, 'research-plan', 'revise', 'Ask about rollback too.')
        self.assertEqual((self.state(root), len(self.workers.jobs)), ('failed', 4))
        self.assertEqual(workspace.status(root)['artifacts']['research-plan'], 'draft',
                         'the earlier draft is kept')
        self.decide(root, 'research-plan', 'revise', 'Ask about rollback, briefly.')
        self.assertEqual((self.state(root), len(self.workers.jobs)), ('waiting', 5))
        self.assertIn('Ask about rollback, briefly.', self.workers.jobs[-1][1].task)

    def test_leaving_a_stage_out_is_committed_and_the_run_carries_on_where_it_was(self):
        root = self.start(deck_target='pptx')
        said = self.decide(root, 'deck', 'skip', 'No slides for this one.')
        self.assertIn('This stage is left out.', said['said'])
        status = workspace.status(root)
        self.assertNotIn('deck', status['settings']['stages'])
        self.assertEqual((status['gate'], status['pending_question'], self.state(root)),
                         ('research-plan', 'Approve the research plan?', 'waiting'))
        self.assertEqual(self.log()[-2:], [
            'Rolling restarts: The deck stage was left out on the page: No slides for this '
            'one.', 'Rolling restarts: ask for a review of the research plan'])
        self.assertEqual(len(self.workers.jobs), 1)
        self.decide(root, 'research-plan')
        self.assertEqual(workspace.status(root)['gate'], 'research')

    def test_changing_the_approved_plan_later_has_the_research_done_again(self):
        root = self.start()
        self.to_gate(root, 'blueprint')
        wider = {**FOUR, 'items': FOUR['items'] + [
            {'id': 'rollback', 'question': 'How is a failed restart rolled back?',
             'public_query': 'rolling restart rollback'}]}
        self.workers.plan = wider
        self.decide(root, 'research-plan', 'revise', 'Add a question about rollback.')
        self.assertEqual(workspace.status(root)['gate'], 'research-plan')
        before = len(self.workers.of('question'))
        self.decide(root, 'research-plan')
        self.assertEqual(len(self.workers.of('question')) - before, 5)
        self.assertEqual(workspace.status(root)['gate'], 'research')
        self.decide(root, 'research')
        status = workspace.status(root)
        self.assertEqual((status['gate'], status['artifacts']['blueprint'], self.state(root)),
                         ('blueprint', 'draft', 'waiting'))
        again = self.workers.of('blueprint')
        self.assertEqual(len(again), 2, 'the blueprint is drafted again from the new research')
        self.assertIn('What the blueprint was made from has changed since the earlier draft, '
                      'and the person approved the change, so it is being made again.',
                      again[1].task)
        self.assertIn('The earlier draft:\n\n# Blueprint: Rolling restarts', again[1].task)
        self.assertIn('> This version was made because what the earlier one was made from '
                      'changed, and you approved the change.',
                      (root / 'reviews' / 'blueprint.md').read_text())
        self.assertIn('## rollback', pipeline.findings_text(root))


class QuestionTests(StudioCase):
    def test_a_workers_question_waits_for_an_answer_which_goes_into_the_brief(self):
        self.workers.then('research-plan', asks('Which of the two platforms is this about?'))
        root = self.start()
        view = self.view(root)
        asked = view['question']
        self.assertEqual((view['state'], view['sentence']), (
            'waiting', 'A question is waiting for you: Which of the two platforms is this '
            'about?'))
        self.assertEqual((sorted(asked), asked['text'], asked['from']), (
            ['from', 'id', 'text'], 'Which of the two platforms is this about?',
            'The worker drafting the research plan'))
        self.assertEqual((self.steps(root)['research-plan']['status'], view['problem']),
                         ('waiting', None))
        self.assertEqual(self.log()[-1],
                         'Rolling restarts: a worker asks a question: Draft the research plan')
        self.engine.wake(root)
        self.assertEqual(len(self.workers.jobs), 1, 'nothing runs until it is answered')

        with self.assertRaisesRegex(WorkspaceError, 'not waiting for an answer any more'):
            self.engine.answer(root, 'another-question', 'The first.')
        after = self.engine.answer(root, asked['id'], ' The newer one.\n')
        self.assertEqual((after['state'], after['question']), ('waiting', None))
        self.assertEqual(workspace.status(root)['gate'], 'research-plan')
        task = self.workers.of('research-plan')[1].task
        self.assertIn('A worker on this job asked the person before. Do not ask these again:'
                      '\n\nQuestion: Which of the two platforms is this about?\nAnswer: The '
                      'newer one.', task)
        with self.assertRaisesRegex(WorkspaceError, 'not waiting for an answer any more'):
            self.engine.answer(root, asked['id'], 'Again.')
        entry = self.record(root)['steps']['research-plan']
        self.assertEqual(([attempt['outcome'] for attempt in entry['attempts']],
                          entry['failed']), (['question', 'kept'], 0))
        self.assertIn("Rolling restarts: a worker's question was answered on the page",
                      self.log())

    def test_a_step_may_ask_only_so_many_questions(self):
        self.workers.then('research-plan', asks('One?'), asks('Two?'), asks('Three?'))
        root = self.start()
        for _ in range(3):
            self.assertTrue(self.workers.jobs[-1][2]['ask'])
            self.engine.answer(root, self.view(root)['question']['id'], 'Yes.')
        self.assertFalse(self.workers.jobs[-1][2]['ask'])
        self.assertEqual((self.state(root), len(self.workers.jobs)), ('waiting', 4))
        self.assertIsNone(self.view(root)['question'])


class ResearchTests(StudioCase):
    def test_a_question_that_fails_three_times_is_named_at_the_gate(self):
        self.workers.then('question:health-checks', fails(SLOW, 'timeout'),
                          fails(SLOW, 'timeout'), fails(SLOW, 'timeout'))
        root = self.start()
        self.decide(root, 'research-plan')
        self.assertEqual((self.state(root), workspace.status(root)['gate']),
                         ('waiting', 'research'))
        tried = self.workers.of('question:health-checks')
        self.assertEqual((len(tried), len(self.workers.of('question'))), (3, 6))
        self.assertIn(f'An earlier try at this job did not work: {SLOW}', tried[2].task)
        review = (root / 'reviews' / 'research.md').read_text()
        self.assertIn('> 2 of 4 questions have an answer the sources support.', review)
        self.assertIn(f'> Not researched (1):\n> - health-checks: What starts the next batch? '
                      f'({SLOW})', review)
        step = self.steps(root)['research']
        self.assertEqual((step['status'], step['attempts'], step['error']), (
            'done', 6, f'1 question could not be answered. The last reason: {SLOW}'))
        self.assertEqual(workspace.status(root)['research']['findings'],
                         {'supported': 2, 'contradicted': 1, 'pending': 1})

        self.decide(root, 'research', 'rebuild')
        self.assertEqual(len(self.workers.of('question:health-checks')), 4)
        self.assertEqual(len(self.workers.of('question')), 7, 'only that question is redone')
        self.assertIn('> Every question was researched and settled.',
                      (root / 'reviews' / 'research.md').read_text().rpartition('## Ready')[2])
        self.assertEqual((workspace.status(root)['gate'], workspace.status(root)['requests'],
                          self.steps(root)['research']['error']), ('research', [], None))

    def test_a_finding_the_sources_do_not_settle_is_named_at_the_gate(self):
        def unsure(tools, job):
            tools.submit_finding('instance-min', 'insufficient', 'The page does not say.',
                                 limits='Only one page was found.')

        self.workers.then('question:instance-min', unsure)
        root = self.start()
        self.decide(root, 'research-plan')
        self.assertIn('> Not settled (1):\n> - instance-min: How many instances keep capacity '
                      'during a restart? (insufficient)',
                      (root / 'reviews' / 'research.md').read_text())
        self.decide(root, 'research', 'revise', 'Look at the scaling guide for this.')
        self.assertEqual((len(self.workers.of('question:instance-min')),
                          len(self.workers.of('question'))), (2, 5))
        self.assertIn('The person looked at the research and asked for this, which may or may '
                      'not be about your question:\n\nLook at the scaling guide for this.',
                      self.workers.of('question:instance-min')[1].task)
        self.assertEqual(workspace.status(root)['research']['findings'],
                         {'supported': 3, 'contradicted': 1})

    def test_a_note_that_names_a_question_has_that_one_researched_again(self):
        root = self.start()
        self.to_gate(root, 'research')
        self.decide(root, 'research', 'revise',
                    'The answer for health-checks misses readiness probes.')
        self.assertEqual((len(self.workers.of('question:health-checks')),
                          len(self.workers.of('question'))), (2, 5))
        self.assertEqual(workspace.status(root)['gate'], 'research')
        self.decide(root, 'research', 'rebuild')
        self.assertEqual(len(self.workers.of('question')), 9,
                         'with nothing named and nothing open, every question is redone')

    def test_research_that_answers_nothing_stops_the_training(self):
        self.workers.then('question', *[fails(SLOW, 'timeout')] * 12)
        root = self.start()
        self.decide(root, 'research-plan')
        view = self.view(root)
        self.assertEqual((view['state'], len(self.workers.of('question'))), ('failed', 12))
        self.assertEqual(view['problem'], {
            'what': f'None of the 4 research questions could be answered. {SLOW}',
            'kept': 'The research plan you approved is kept.', 'action': 'retry',
            'label': 'Try again'})
        self.assertEqual(self.steps(root)['research']['status'], 'failed')
        self.assertEqual(workspace.status(root)['artifacts']['research'], 'draft')
        self.assertIsNone(workspace.status(root)['gate'])
        self.assertEqual(self.engine.act(root, 'retry')['state'], 'waiting')
        self.assertEqual(workspace.status(root)['gate'], 'research')

    def test_an_agent_that_cannot_be_used_stops_the_research_at_once(self):
        self.engine = self.make(at_once=1)
        self.workers.then('question:instance-min', fails('Not signed in.', 'unavailable'))
        root = self.start()
        self.decide(root, 'research-plan')
        view = self.view(root)
        self.assertEqual((view['state'], view['problem']['what'],
                          len(self.workers.of('question'))),
                         ('failed', 'scripted could not be used. Not signed in.', 2))
        self.assertEqual(self.engine.act(root, 'retry')['state'], 'waiting')
        self.assertEqual(len(self.workers.of('question')), 5)

    def test_without_harness_research_the_training_stops_before_research_and_says_so(self):
        with mock.patch.object(research, 'locations', return_value=[self.base / 'nowhere']):
            self.engine = self.make(research=research.Research)
            root = self.start()
            self.decide(root, 'research-plan')
        view = self.view(root)
        self.assertEqual((view['state'], view['sentence']), (
            'stopped', 'The harness-research skill is not installed on this computer, so '
            'research cannot run. Install it, then try again.'))
        self.assertEqual((view['problem']['kept'], view['problem']['action'],
                          view['problem']['label']),
                         ('The research plan you approved is kept.', 'retry', 'Try again'))
        self.assertEqual((self.steps(root)['research-start']['status'],
                          self.workers.of('question')), ('failed', []))
        self.assertFalse((root / '.harness-research').exists())
        self.engine.research = lambda: self.research
        self.assertEqual(self.engine.act(root, 'retry')['state'], 'waiting')
        self.assertEqual(workspace.status(root)['gate'], 'research')

    def test_the_stand_in_is_called_as_the_research_pipeline_lays_it_out(self):
        self.engine = self.make(at_once=1)
        root = self.start()
        self.decide(root, 'research-plan')
        calls = [call[0] for call in self.research.run.calls]
        self.assertEqual(calls, ['plan', 'record', 'record', 'record', 'record', 'status'])
        self.assertEqual(self.research.run.calls[0][1:], [
            '--project', str(root), '--file', str(root / pipeline.PLAN)])
        self.assertEqual(self.record(root)['research']['run'],
                         workspace.research_record(root)['run'])


class LimitTests(StudioCase):
    def test_a_training_that_has_spent_what_it_may_stops_and_asks(self):
        settings.save(replace(settings.load(), training_dollars=1.0))
        self.workers.cost = 0.6
        self.engine = self.make(at_once=1)
        root = self.start()
        self.assertEqual(self.workers.jobs[0][1].limits.dollars, 1.0)
        self.decide(root, 'research-plan')
        view = self.view(root)
        self.assertEqual((view['state'], view['sentence'], view['spent']['dollars']), (
            'stopped', 'This training has spent $1.20. It stops and asks each time it has '
            'spent another $1.00.', 1.2))
        self.assertEqual(view['problem'], {
            'what': view['sentence'], 'kept': 'Everything made so far is kept.',
            'action': 'resume', 'label': 'Carry on'})
        self.assertEqual(([job.limits.dollars for job in self.workers.of('question')],
                          self.steps(root)['research']['status']), ([0.4], 'to-do'))
        self.assertEqual(workspace.status(root)['research']['findings'],
                         {'supported': 1, 'pending': 3})

        self.assertEqual(self.engine.act(root, 'resume')['state'], 'stopped')
        self.assertEqual(self.view(root)['spent'], {'dollars': 2.4, 'tokens': 4800})
        after = self.engine.act(root, 'resume')
        self.assertEqual((after['state'], after['problem'], after['spent']['dollars']),
                         ('waiting', None, 3.0))
        self.assertEqual(workspace.status(root)['gate'], 'research')

    def test_a_step_is_given_its_time_and_what_the_training_may_still_spend(self):
        settings.save(replace(settings.load(), step_seconds=120, training_dollars=5.0))
        self.workers.cost = 1.5
        root = self.start()
        self.decide(root, 'research-plan')
        limits = [(job.limits.seconds, job.limits.dollars) for _, job, _ in self.workers.jobs]
        self.assertEqual(limits[0], (120, 5.0))
        self.assertEqual({seconds for seconds, _ in limits}, {120})
        self.assertLessEqual(max(dollars for _, dollars in limits[1:]), 3.5)

    def test_carrying_on_or_trying_again_takes_up_the_limits_this_computer_has_now(self):
        self.workers.then('research-plan', fails(), fails(), fails())
        root = self.start()
        settings.save(replace(settings.load(), step_seconds=1200, training_dollars=50.0))
        self.engine.act(root, 'retry')
        self.assertEqual(self.record(root)['limits'],
                         {'step_seconds': 1200, 'training_dollars': 50.0})
        self.assertEqual(self.workers.jobs[-1][1].limits.seconds, 1200)


class HaltTests(StudioCase):
    """What a person may ask of a run, which depends on the state it is in."""

    def refused(self, root: Path, action: str, said: str) -> None:
        before = self.record(root)
        with self.assertRaisesRegex(WorkspaceError, said):
            self.engine.act(root, action)
        self.assertEqual(self.record(root), before)

    def test_pausing_lets_the_step_in_hand_finish_and_starts_nothing_new(self):
        paused = []

        def pauses(tools, job):
            paused.append(self.engine.act(self.space.training('rolling-restarts'), 'pause'))
            self.workers.question(tools, job)

        self.engine = self.make(at_once=1)
        root = self.start()
        self.workers.then('question:availability', pauses)
        self.decide(root, 'research-plan')
        self.assertEqual((paused[0]['state'], paused[0]['sentence']),
                         ('paused', 'Pausing. The step in hand finishes first.'))
        view = self.view(root)
        self.assertEqual((view['state'], view['sentence'], len(self.workers.of('question'))),
                         ('paused', 'Paused. Nothing new starts until you resume.', 1))
        self.assertEqual(workspace.status(root)['research']['findings'],
                         {'supported': 1, 'pending': 3})
        self.refused(root, 'pause', 'Only a training that is working can be paused. This one '
                     'is paused.')
        resumed = self.engine.act(root, 'resume')
        self.assertEqual((resumed['state'], len(self.workers.of('question'))), ('waiting', 4))
        self.assertIn('Rolling restarts: paused on the page', self.log())
        self.assertIn('Rolling restarts: resumed on the page', self.log())

    def test_a_stopped_training_stays_stopped_until_it_is_resumed(self):
        root = self.start()
        stopped = self.engine.act(root, 'stop')
        self.assertEqual((stopped['state'], stopped['sentence']),
                         ('stopped', 'Stopped. Everything kept so far is still here.'))
        said = self.decide(root, 'research-plan')
        self.assertEqual(said['said'], 'Approved. This training is not running, so nothing '
                         'more happens until you resume it or try again.')
        self.assertEqual((self.state(root), self.workers.of('question')), ('stopped', []))
        self.assertEqual(workspace.status(root)['artifacts']['research-plan'], 'approved')
        self.refused(root, 'stop', 'This training is stopped, so there is nothing to stop.')
        self.assertEqual(self.engine.act(root, 'resume')['state'], 'waiting')
        self.assertEqual(workspace.status(root)['gate'], 'research')

    def test_a_paused_training_can_be_stopped(self):
        def pauses(tools, job):
            self.engine.act(self.space.training('rolling-restarts'), 'pause')
            self.workers.research_plan(tools, job)

        self.workers.then('research-plan', pauses)
        root = self.start()
        self.assertEqual(self.state(root), 'paused')
        self.assertEqual(self.engine.act(root, 'stop')['state'], 'stopped')
        self.assertEqual(self.engine.act(root, 'resume')['state'], 'waiting')

    def test_a_run_stopped_on_a_problem_can_be_resumed_as_well_as_tried_again(self):
        with mock.patch.object(research, 'locations', return_value=[self.base / 'nowhere']):
            self.engine = self.make(research=research.Research)
            root = self.start()
            self.decide(root, 'research-plan')
        view = self.view(root)
        self.assertEqual((view['state'], view['problem']['action']), ('stopped', 'retry'))
        self.engine.research = lambda: self.research
        after = self.engine.act(root, 'resume')
        self.assertEqual((after['state'], after['problem']), ('waiting', None))
        self.assertEqual(workspace.status(root)['gate'], 'research')

    def test_what_cannot_be_done_as_things_stand_is_refused_in_a_sentence(self):
        root = self.start()
        self.assertEqual(self.state(root), 'waiting')
        self.refused(root, 'pause', 'Only a training that is working can be paused. This one '
                     'is waiting for you.')
        self.refused(root, 'resume', 'This training is not paused or stopped, so there is '
                     'nothing to resume.')
        self.refused(root, 'retry', 'Nothing here failed, so there is nothing to try again.')
        self.refused(root, 'restart', 'A run can be asked to: pause, resume, stop, retry.')

        self.workers.then('research-plan', fails(), fails(), fails())
        failed = self.start(title='Health checks')
        self.assertEqual(self.state(failed), 'failed')
        self.refused(failed, 'pause', 'This one is stopped on a problem.')
        self.refused(failed, 'stop', 'This training is stopped on a problem, so there is '
                     'nothing to stop.')
        self.refused(failed, 'resume', 'not paused or stopped')

        self.to_end(root)
        self.assertEqual(self.state(root), 'done')
        for action in ACTIONS:
            with self.subTest(action):
                self.refused(root, action, 'finished as far as the runner takes it|not paused '
                             'or stopped|Nothing here failed')
        elsewhere = self.base / 'elsewhere'
        with self.assertRaisesRegex(WorkspaceError, 'No run is driving this training'):
            self.engine.act(elsewhere, 'pause')
        self.assertIsNone(self.engine.view(elsewhere))
        self.assertIsNone(self.engine.brief(elsewhere))


class RestartTests(StudioCase):
    """The runner ending and starting again: the next step comes from the files."""

    def restart(self, **options):
        self.engine.close()
        self.engine = self.make(**options)
        self.engine.resume()

    def test_a_restart_in_the_middle_of_research_does_only_what_is_left(self):
        def dies(tools, job):
            raise Crash()

        self.engine = self.make(at_once=1)
        root = self.start()
        self.workers.then('question:health-checks', dies)
        with self.assertRaises(Crash):
            self.decide(root, 'research-plan')
        self.assertEqual(workspace.status(root)['research']['findings'],
                         {'supported': 2, 'pending': 2})
        (root / 'blueprint.md').write_text('# Half made\n')
        (root / research.LOCK).write_text('12345\n')  # a save that never finished
        self.restart(at_once=1)
        self.assertFalse((root / 'blueprint.md').exists(), 'what was half-made is discarded')
        self.assertFalse((root / research.LOCK).exists())
        asked = [kind for kind, _, _ in self.workers.jobs if kind.startswith('question')]
        self.assertEqual(asked, ['question:availability', 'question:instance-min',
                                 'question:health-checks', 'question:health-checks',
                                 'question:zero-downtime'])
        self.assertEqual((self.state(root), workspace.status(root)['gate']),
                         ('waiting', 'research'))
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_a_finding_that_was_not_committed_is_researched_again(self):
        real = gitstate.commit

        def dying(space, message, paths=None):
            if message.endswith('keep the finding for instance-min'):
                raise Crash()
            return real(space, message, paths)

        self.engine = self.make(at_once=1)
        root = self.start()
        with mock.patch.object(gitstate, 'commit', dying):
            with self.assertRaises(Crash):
                self.decide(root, 'research-plan')
        self.assertEqual(workspace.status(root)['research']['findings'],
                         {'supported': 2, 'pending': 2})
        self.assertNotEqual(self.git('status', '--porcelain'), '')
        self.restart(at_once=1)
        self.assertEqual((len(self.workers.of('question:availability')),
                          len(self.workers.of('question:instance-min'))), (1, 2))
        self.assertEqual((self.state(root), workspace.status(root)['gate']),
                         ('waiting', 'research'))
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertEqual(self.log().count('Rolling restarts: keep the finding for '
                                          'instance-min'), 1)

    def test_a_restart_at_a_gate_waits_there_and_leaves_what_a_person_changed(self):
        root = self.start()
        plan = root / pipeline.PLAN
        plan.write_text(plan.read_text().replace('What starts the next batch?',
                                                 'What decides when the next batch starts?'))
        self.restart()
        self.assertIn('What decides when the next batch starts?', plan.read_text())
        self.assertEqual((self.state(root), len(self.workers.jobs)), ('waiting', 1))
        self.decide(root, 'research-plan')
        self.assertEqual(workspace.status(root)['gate'], 'research')

    def test_a_restart_respects_a_pause_a_question_and_a_failure(self):
        self.workers.then('research-plan', asks('Which platform?'))
        asking = self.start()
        failing = self.start(title='Health checks')
        self.workers.then('blueprint', fails(), fails(), fails())
        self.to_gate(failing, 'research')
        self.decide(failing, 'research')
        def pauses(tools, job):
            self.engine.act(self.space.training('blue-green-deploys'), 'pause')
            self.workers.research_plan(tools, job)

        self.workers.then('research-plan', pauses)
        paused = self.start(title='Blue green deploys')
        stopped = self.start(title='Canary releases')
        self.engine.act(stopped, 'stop')
        self.decide(stopped, 'research-plan')
        jobs = len(self.workers.jobs)
        self.restart()
        self.assertEqual([self.state(root) for root in (asking, failing, paused, stopped)],
                         ['waiting', 'failed', 'paused', 'stopped'])
        self.assertEqual(len(self.workers.jobs), jobs)
        self.assertEqual(self.view(asking)['question']['text'], 'Which platform?')

    def test_a_training_someone_else_added_to_the_workspace_becomes_known_here(self):
        root = self.start()
        home.registry_path().unlink()
        self.restart()
        self.assertEqual([entry['path'] for entry in home.trainings()], [str(root)])

    def test_a_run_that_is_done_is_left_alone(self):
        root = self.start()
        self.to_end(root)
        (root / 'notes.md').write_text('# Notes someone keeps beside the training\n')
        jobs = len(self.workers.jobs)
        self.restart()
        self.assertTrue((root / 'notes.md').exists())
        self.assertEqual((self.state(root), len(self.workers.jobs)), ('done', jobs))

    def test_what_a_person_changed_while_no_step_was_in_hand_is_never_discarded(self):
        root = self.start()
        self.to_end(root)
        guide = root / 'document.md'
        guide.write_text(guide.read_text() + '\nA line its person added by hand.\n')
        self.assertFalse((root / self.engines.IN_HAND).exists())
        self.restart()
        self.assertIn('A line its person added by hand.', guide.read_text())
        self.assertEqual((self.state(root), workspace.status(root)['gate']),
                         ('waiting', 'document'), 'their change is put to them')

    def test_only_a_step_the_runner_ended_in_the_middle_of_is_discarded(self):
        seen = []

        def dies(tools, job):
            seen.append((root / self.engines.IN_HAND).read_text())
            raise Crash()

        root = self.start()
        self.to_gate(root, 'blueprint')
        self.workers.then('document', dies)
        with self.assertRaises(Crash):
            self.decide(root, 'blueprint')
        self.assertEqual(seen, ['document\n'])
        (root / 'document.md').write_text('# Half made\n')
        self.assertEqual(self.git('status', '--porcelain', '--', str(root)),
                         '?? trainings/rolling-restarts/document.md',
                         'the note that a step is in hand is never shared')
        self.restart()
        self.assertFalse((root / self.engines.IN_HAND).exists())
        self.assertEqual((workspace.status(root)['gate'], len(self.workers.of('document'))),
                         ('document', 2))
        self.assertNotIn('Half made', (root / 'document.md').read_text())


class SharingTests(StudioCase):
    """A workspace whose repository is shared: a bare repository stands in for the team's."""

    def set_up(self):
        self.remote = self.base / 'team-repo.git'
        self.remote.mkdir()
        self.git('init', '--quiet', '--bare', repo=self.remote)
        self.git('symbolic-ref', 'HEAD', 'refs/heads/main', repo=self.remote)
        return self.gitstate.join(str(self.remote))

    def shared(self) -> list[str]:
        """What the team's repository has been sent, newest first."""
        if not self.git('for-each-ref', 'refs/heads/main', repo=self.remote):
            return []
        return self.git('log', '--format=%s', 'main', repo=self.remote).splitlines()

    def test_work_is_shared_after_each_decision(self):
        root = self.start()
        self.assertEqual(self.shared()[0], 'Rolling restarts: start the training from the form',
                         'who drives a training is shared before any work is done for it')
        self.decide(root, 'research-plan')
        self.assertEqual(self.shared()[0],
                         'Rolling restarts: The research plan was approved on the page.')
        self.assertEqual(workspace.status(root)['gate'], 'research')
        self.assertEqual(self.engine.shared(), {'shared': False, 'notice': None},
                         'what the run did after the decision waits for the next one')
        self.assertEqual(self.engine.share(), {'shared': True, 'notice': None})
        self.assertEqual(self.shared()[0],
                         'Rolling restarts: ask for a review of the research report')
        self.assertEqual(self.engine.shared(), {'shared': True, 'notice': None})

    def test_the_last_thing_the_runner_does_is_shared_without_another_decision(self):
        root = self.start()
        self.to_end(root)
        self.assertEqual(self.state(root), 'done')
        self.assertEqual(self.shared()[0],
                         'Rolling restarts: write the index; the training is finished')
        self.assertEqual(self.engine.shared(), {'shared': True, 'notice': None})

    def test_a_repository_that_cannot_be_reached_never_holds_a_run_up(self):
        root = self.start()
        self.remote.rename(self.base / 'moved-away.git')
        self.decide(root, 'research-plan')
        self.assertEqual((self.state(root), workspace.status(root)['gate']),
                         ('waiting', 'research'))
        found = self.engine.shared()
        self.assertFalse(found['shared'])
        self.assertIn('could not be reached', found['notice'])
        self.assertIn('is not shared yet', found['notice'])
        self.assertEqual(self.engine.share()['shared'], False)

    def test_sharing_only_when_asked(self):
        self.gitstate.share_when('asked')
        root = self.start()
        self.decide(root, 'research-plan')
        self.assertEqual(self.shared()[0], 'Rolling restarts: start the training from the form',
                         'only the claim that starts a training is sent without being asked')
        self.assertEqual(self.engine.shared(), {'shared': False, 'notice': None})
        self.assertEqual(self.engine.share(), {'shared': True, 'notice': None})
        self.assertIn('Rolling restarts: The research plan was approved on the page.',
                      self.shared())
        self.assertEqual(self.engine.shared(), {'shared': True, 'notice': None})

    def test_a_workspace_with_no_remote_has_nowhere_to_share_to(self):
        self.gitstate.local(self.base / 'alone')
        self.assertEqual(self.engine.shared(), {'shared': False, 'notice': None})
        found = self.engine.share()
        self.assertEqual(found['shared'], False)
        self.assertIn('no shared repository', found['notice'])


class LiveTests(StudioCase):
    """The engine on threads of its own, as the runner serves it."""

    BACKGROUND = True

    def until(self, check, seconds: float = 30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            found = check()
            if found:
                return found
            time.sleep(0.02)
        self.fail('It did not happen in time.')

    def held(self, act):
        """A worker that does its work, then waits to be let go."""
        entered, go = threading.Event(), threading.Event()
        self.addCleanup(go.set)

        def script(tools, job):
            returned = act(tools, job)
            entered.set()
            go.wait(30)
            return returned
        return script, entered, go

    def test_what_a_worker_is_doing_is_shown_while_it_works(self):
        script, entered, go = self.held(self.workers.research_plan)
        self.workers.then('research-plan', script)
        root = self.start()
        self.assertTrue(entered.wait(30))
        view = self.view(root)
        self.assertEqual((view['state'], view['sentence']),
                         ('working', 'Drafting the research plan.'))
        worker, = view['workers']
        self.assertEqual((worker['id'], worker['label']),
                         ('research-plan', 'Drafting the research plan'))
        self.assertRegex(worker['started_at'], r'^\d{4}-\d\d-\d\dT')
        self.assertEqual(worker['lines'], ['Handing back research-plan',
                                           'The draft was accepted',
                                           'Writing its own notes on the draft'])
        self.assertEqual(self.steps(root)['research-plan']['status'], 'working')
        self.assertEqual(self.engine.brief(root)['needs'], False)
        go.set()
        self.until(lambda: self.state(root) == 'waiting')
        self.assertEqual(self.view(root)['workers'], [])

    def test_only_so_many_trainings_work_at_once(self):
        settings.save(replace(settings.load(), parallel=1))
        script, entered, go = self.held(self.workers.research_plan)
        self.workers.then('research-plan', script)
        first = self.start()
        self.assertTrue(entered.wait(30))
        second = self.start(title='Health checks')
        self.until(lambda: self.view(second)['sentence'].startswith('Waiting for its turn'))
        time.sleep(0.3)
        view = self.view(second)
        self.assertEqual((view['state'], view['sentence'], view['workers'],
                          len(self.workers.jobs)),
                         ('working', 'Waiting for its turn. It is next.',
                          [], 1))
        go.set()
        self.until(lambda: self.state(first) == self.state(second) == 'waiting')
        self.assertEqual(len(self.workers.jobs), 2)

    def test_research_questions_are_worked_on_several_at_a_time(self):
        self.engine = self.make(at_once=2)
        lock, live, most = threading.Lock(), [0], [0]

        def counted(tools, job):
            with lock:
                live[0] += 1
                most[0] = max(most[0], live[0])
            time.sleep(0.2)
            self.workers.question(tools, job)
            with lock:
                live[0] -= 1

        self.workers.then('question', *[counted] * 4)
        root = self.start()
        self.until(lambda: self.state(root) == 'waiting')
        self.decide(root, 'research-plan')
        self.until(lambda: workspace.status(root)['gate'] == 'research')
        self.assertEqual((most[0], len(self.workers.of('question'))), (2, 4))
        self.assertEqual(workspace.status(root)['research']['findings'],
                         {'supported': 3, 'contradicted': 1})

    def test_after_a_decision_the_page_is_told_what_the_runner_does_next(self):
        root = self.start()
        self.until(lambda: self.state(root) == 'waiting')
        script, entered, go = self.held(self.workers.question)
        self.workers.then('question', script)
        said = self.decide(root, 'research-plan')
        self.assertEqual(said['said'], 'Approved. Researching the questions now. You can '
                         'close this page; it says when it needs you again.')
        self.assertTrue(entered.wait(30))
        go.set()
        self.until(lambda: workspace.status(root)['gate'] == 'research')
        script, entered, go = self.held(self.workers.blueprint)
        self.workers.then('blueprint', script)
        said = self.decide(root, 'research')
        self.assertEqual(said['said'], 'Approved. Drafting the blueprint now. You can close '
                         'this page; it says when it needs you again.')
        go.set()
        self.until(lambda: workspace.status(root)['gate'] == 'blueprint')
        script, entered, go = self.held(self.workers.blueprint)
        self.workers.then('blueprint', script)
        said = self.decide(root, 'blueprint', 'revise', 'Make the example a database.')
        self.assertEqual(said['said'], 'Your changes are noted. Once they are made, the new '
                         'version comes back here for your review. Drafting the blueprint now. '
                         'You can close this page; it says when it needs you again.')
        go.set()
        self.until(lambda: workspace.status(root)['gate'] == 'blueprint')

    def test_stopping_ends_the_step_in_hand_and_keeps_nothing_from_it(self):
        script, entered, go = self.held(self.workers.research_plan)
        self.workers.then('research-plan', script)
        root = self.start()
        self.assertTrue(entered.wait(30))
        self.assertFalse(self.engine._run(root).stop.is_set())
        stopped = self.engine.act(root, 'stop')
        self.assertEqual(stopped['state'], 'stopped')
        self.assertTrue(self.engine._run(root).stop.is_set())
        go.set()
        self.until(lambda: self.record(root)['steps'].get('research-plan'))
        self.until(lambda: self.engine._run(root).thread is None)
        self.assertEqual(self.record(root)['steps']['research-plan']['attempts'][0]['outcome'],
                         'stopped')
        self.assertFalse((root / pipeline.PLAN).exists())
        self.assertEqual((self.state(root), self.git('status', '--porcelain')),
                         ('stopped', ''))
        self.engine.act(root, 'resume')
        self.until(lambda: self.state(root) == 'waiting')
        self.assertEqual(workspace.status(root)['gate'], 'research-plan')

    def test_pausing_lets_the_step_in_hand_finish_and_keeps_it(self):
        script, entered, go = self.held(self.workers.research_plan)
        self.workers.then('research-plan', script)
        root = self.start()
        self.assertTrue(entered.wait(30))
        paused = self.engine.act(root, 'pause')
        self.assertEqual((paused['state'], paused['sentence']),
                         ('paused', 'Pausing. The step in hand finishes first.'))
        go.set()
        self.until(lambda: self.engine._run(root).thread is None)
        self.assertEqual(workspace.status(root)['artifacts']['research-plan'], 'draft')
        self.assertIsNone(workspace.status(root)['gate'], 'no gate is set while it is paused')
        self.engine.act(root, 'resume')
        self.until(lambda: workspace.status(root)['gate'] == 'research-plan')

    def test_closing_the_runner_ends_its_workers(self):
        script, entered, go = self.held(lambda tools, job: None)
        self.workers.then('research-plan', script)
        root = self.start()
        self.assertTrue(entered.wait(30))
        closing = threading.Thread(target=self.engine.close)
        closing.start()
        self.until(lambda: self.engine._run(root).stop.is_set())
        go.set()
        closing.join(30)
        self.assertFalse(closing.is_alive())
        self.assertIsNone(self.engine._run(root).thread)
        self.engine.wake(root)
        self.assertIsNone(self.engine._run(root).thread, 'a closed engine starts nothing')


class OutcomeTests(StudioCase):
    def test_a_draft_accepted_before_the_agent_gave_out_is_still_kept(self):
        def gives_out(tools, job):
            self.workers.research_plan(tools, job)
            return Outcome(False, 'timeout', SLOW, cost=0.1)

        self.workers.then('research-plan', gives_out)
        root = self.start()
        self.assertEqual((self.state(root), self.steps(root)['research-plan']['attempts']),
                         ('waiting', 1))
        self.assertEqual(self.view(root)['spent']['dollars'], 0.1)


if __name__ == '__main__':
    import unittest
    unittest.main()
