"""The worker tools: every refusal, where a quote sits, and the rules for fetching a page.

Nothing here touches the network: pages come from a pretend web.
"""
import gzip
import io
import json
import re
import socket
import subprocess
import threading
import unittest
from unittest import mock

import helpers
from runner_support import (BLUEPRINT, BRIEF, DOCUMENT, PAGE, PLAN, PUBLIC, SCENARIO, YOODLI,
                            JobCase)

import checks
from runner import worker_tools
from workspace import WorkspaceError

DOCS = 'https://docs.example.com/restarts'
BLUEPRINTS = {'blueprint': {'kind': 'blueprint', 'findings': helpers.FINDINGS}}
PLANS = {'research-plan': {'kind': 'research-plan', 'scope': 'public-web'}}
QUOTE = 'Capacity holds only when more than one instance is running.'
COMPETITIVE = (helpers.EXAMPLES / 'competitive-brief.md').read_text(encoding='utf-8')
PROFILE = json.loads((helpers.SKILL / 'assets' / 'profiles' / 'yoodli.json').read_text())


class PrepareTests(JobCase):
    def test_a_prepared_folder_says_what_the_job_may_read_and_must_hand_back(self):
        worker_tools.prepare(self.job, inputs={'intake': 'For platform leads.\n'},
                             artifacts=BLUEPRINTS, fetch=False)
        job = json.loads((self.job / 'job.json').read_text())
        self.assertEqual(job['inputs'], [{'name': 'intake', 'file': 'inputs/1.txt',
                                          'chars': 20}])
        self.assertEqual((job['finding'], job['fetch'], job['ask']), (None, False, True))
        self.assertEqual((self.job / 'inputs' / '1.txt').read_text(), 'For platform leads.\n')

    def test_a_folder_is_prepared_once(self):
        worker_tools.prepare(self.job)
        with self.assertRaisesRegex(WorkspaceError, 'already holds a job'):
            worker_tools.prepare(self.job)

    def test_a_draft_needs_a_kind_that_can_be_checked(self):
        with self.assertRaisesRegex(WorkspaceError, 'research-plan, blueprint'):
            worker_tools.prepare(self.job, artifacts={'poem': {'kind': 'poem'}})
        with self.assertRaisesRegex(WorkspaceError, 'scope is one of'):
            worker_tools.prepare(self.job, artifacts={'p': {'kind': 'research-plan',
                                                            'scope': 'anything'}})
        with self.assertRaisesRegex(WorkspaceError, 'the kind of brief is one of product, '
                                    'competitive'):
            worker_tools.prepare(self.job, artifacts={'brief': {'kind': 'brief',
                                                                'brief_kind': 'sales'}})
        self.assertEqual(list(worker_tools.VALIDATORS), [
            'research-plan', 'blueprint', 'document', 'brief', 'scenario', 'yoodli', 'outline',
            'section'])

    def test_a_finding_needs_a_question_id(self):
        with self.assertRaisesRegex(WorkspaceError, 'not a research question ID'):
            worker_tools.prepare(self.job, finding='Instance Min')

    def test_an_offered_source_needs_its_details(self):
        with self.assertRaisesRegex(WorkspaceError, 'needs: origin, file'):
            worker_tools.prepare(self.job, sources=[{'title': 'Handbook', 'text': 'Words.'}])

    def test_tools_need_a_prepared_folder(self):
        with self.assertRaisesRegex(WorkspaceError, 'not a job folder'):
            worker_tools.WorkerTools(self.job)
        with self.assertRaisesRegex(WorkspaceError, 'not a job folder'):
            worker_tools.collect(self.job)

    def test_the_command_starts_this_server_for_that_folder(self):
        command = worker_tools.command(self.job)
        self.assertEqual(command[1], '-I')
        self.assertTrue(command[2].endswith('worker_tools.py'))
        self.assertEqual(command[3:], ['--job', str(self.job)])


class InputTests(JobCase):
    def test_inputs_are_listed_by_name_with_their_size(self):
        tools = self.tools(inputs={'intake': 'Short.\n', 'findings': 'x' * 50_000})
        listed = self.ok(tools.list_inputs())
        self.assertIn('- intake: 7 characters', listed)
        self.assertIn('- findings: 50,000 characters, in 3 parts', listed)

    def test_a_job_with_no_inputs_says_so(self):
        self.assertIn('no inputs', self.ok(self.tools().list_inputs()))

    def test_saved_sources_are_listed_too(self):
        tools = self.tools(finding='instance-min', sources=[
            {'title': 'Operations handbook', 'origin': 'Supplied by the team',
             'text': 'Restart one batch at a time.', 'file': 'sources/handbook.txt'}])
        listed = self.ok(tools.list_inputs())
        self.assertIn('- s1: "Operations handbook", 29 characters', listed)
        self.assertNotIn('read_input', listed)

    def test_a_short_input_is_read_whole(self):
        tools = self.tools(inputs={'intake': 'For platform leads.\n'})
        self.assertEqual(self.ok(tools.read_input('intake')), 'For platform leads.\n')

    def test_a_long_input_is_read_in_parts_that_end_at_line_ends(self):
        text = ''.join(f'Line {number} of the findings.\n' for number in range(2500))
        tools = self.tools(inputs={'findings': text})
        pieces = worker_tools.parts(text)
        self.assertGreater(len(pieces), 2)
        self.assertEqual(''.join(pieces), text)
        self.assertTrue(all(len(piece) <= worker_tools.PART and piece.endswith('\n')
                            for piece in pieces))
        first = self.ok(tools.read_input('findings'))
        self.assertTrue(first.startswith(f'[findings: part 1 of {len(pieces)}; ask for part '
                                         '2 for more]\n\nLine 0 of'))
        last = self.ok(tools.read_input('findings', str(len(pieces))))
        self.assertIn('this is the last part', last)
        self.assertTrue(last.endswith(pieces[-1]))

    def test_text_with_no_line_ends_is_still_cut(self):
        self.assertEqual([len(piece) for piece in worker_tools.parts('x' * 25, size=10)],
                         [10, 10, 5])

    def test_an_unknown_input_is_refused_with_the_names_there_are(self):
        tools = self.tools(inputs={'intake': 'Text.'})
        self.assertIn('This job\'s inputs: intake', self.refused(tools.read_input('notes')))

    def test_a_part_that_does_not_exist_is_refused(self):
        tools = self.tools(inputs={'intake': 'Text.'})
        self.assertIn('there is no part 2', self.refused(tools.read_input('intake', 2)))
        self.assertIn('must be a whole number', self.refused(tools.read_input('intake', 'two')))

    def test_wrong_arguments_are_refused_with_the_ones_it_takes(self):
        tools = self.tools(inputs={'intake': 'Text.'})
        said = self.refused(tools.call('read_input', {'title': 'intake'}))
        self.assertEqual(said, 'Wrong arguments for read_input: it takes name, part.')

    def test_a_tool_that_does_not_exist_is_refused(self):
        self.assertEqual(self.refused(self.tools().call('run_command', {'command': 'ls'})),
                         'There is no tool called run_command.')

    def test_every_call_is_logged(self):
        tools = self.tools(inputs={'intake': 'Text.'})
        tools.read_input('intake')
        tools.read_input('notes')
        tools.call('run_command', {})
        tools.call('read_input', {'title': 'x'})
        log = [json.loads(line) for line in (self.job / 'tools.log').read_text().splitlines()]
        self.assertEqual([(entry['tool'], entry['ok']) for entry in log],
                         [('read_input', True), ('read_input', False), ('run_command', False),
                          ('read_input', False)])
        self.assertEqual(log[0]['given'], {'name': 'intake'})
        self.assertEqual(log[0]['answer'], 'Text.')

    def test_a_tool_that_breaks_is_reported_and_logged(self):
        tools = self.tools(inputs={'intake': 'Text.'})
        with mock.patch.object(worker_tools, 'parts', side_effect=RuntimeError('boom')):
            said = self.refused(tools.call('read_input', {'name': 'intake'}))
        self.assertIn('The tool failed and nothing was kept (RuntimeError: boom)', said)
        self.assertEqual(self.ok(tools.read_input('intake')), 'Text.')


class PlanTests(JobCase):
    def submit(self, plan, **spec):
        tools = self.tools() if (self.job / 'job.json').exists() else self.tools(
            artifacts={'research-plan': {'kind': 'research-plan', 'scope': 'public-web',
                                         **spec}})
        text = plan if isinstance(plan, str) else json.dumps(plan)
        return tools.submit_artifact('research-plan', text)

    def test_an_accepted_plan_is_kept_whole(self):
        self.assertEqual(self.ok(self.submit(PLAN)), 'Accepted: research-plan.')
        kept = worker_tools.collect(self.job)['artifacts']['research-plan']
        plan = json.loads(kept['text'])
        self.assertEqual(kept['kind'], 'research-plan')
        self.assertEqual(kept['path'], self.job / 'accepted' / 'research-plan.json')
        self.assertEqual((plan['topic'], plan['purpose'], plan['scope'], plan['sources']),
                         ('Rolling restarts', 'planning', 'public-web', []))
        self.assertEqual(plan['items'][0], {
            'id': 'instance-min', 'claim': None,
            'question': 'How many instances keep capacity during a restart?',
            'public_query': 'rolling restart minimum instances'})
        import checks
        self.assertEqual(checks.check_research_plan(plan)['status'], 'passed')
        self.assertEqual(kept['checks'][0]['status'], 'passed')

    def test_the_runner_sets_the_scope_the_sources_and_the_purpose(self):
        chosen = [{'id': 'handbook', 'title': 'Handbook', 'origin': 'Supplied',
                   'file': 'sources/handbook.txt'}]
        written = {**PLAN, 'scope': 'public-web', 'purpose': 'fact-check',
                   'sources': [{'id': 'made-up'}], 'input_files': ['intake.md']}
        self.ok(self.submit(written, scope='supplied-only', sources=chosen))
        plan = json.loads(worker_tools.collect(self.job)['artifacts']['research-plan']['text'])
        self.assertEqual((plan['purpose'], plan['scope'], plan['sources']),
                         ('planning', 'supplied-only', chosen))
        self.assertNotIn('input_files', plan)
        self.assertEqual([item['public_query'] for item in plan['items']], [None, None])

    def test_text_that_is_not_json_is_refused(self):
        self.assertIn('not valid JSON', self.refused(self.submit('Here are my questions:')))
        self.assertIn('must be a JSON object', self.refused(self.submit('["instance-min"]')))

    def test_the_cores_own_check_decides(self):
        twice = {**PLAN, 'items': [PLAN['items'][0], PLAN['items'][0]]}
        self.assertIn('Question ID instance-min is used more than once.',
                      self.refused(self.submit(twice)))
        self.assertIn('"items" must hold 1 to 30 questions.',
                      self.refused(self.submit({'topic': 'Rolling restarts', 'items': []})))
        self.assertIn('Question 1 has no question text.',
                      self.refused(self.submit({**PLAN, 'items': ['instance-min']})))

    def test_a_plan_needs_a_topic(self):
        self.assertIn('"topic" must say what the training is about',
                      self.refused(self.submit({'items': PLAN['items']})))

    def test_a_public_query_is_search_words_only(self):
        for query in ('https://example.com/restarts', 'restarts/rolling', 'ask someone@x', ''):
            with self.subTest(query):
                asked = {**PLAN, 'items': [{**PLAN['items'][0], 'public_query': query}]}
                self.assertIn('instance-min: "public_query" is a few public search words',
                              self.refused(self.submit(asked)))

    def test_a_question_asks_one_thing(self):
        rambling = {**PLAN, 'items': [{**PLAN['items'][0], 'question': 'Why? ' * 900}]}
        self.assertIn('instance-min: the question is too long; ask one thing.',
                      self.refused(self.submit(rambling)))

    def test_a_refused_plan_keeps_nothing_and_says_why_afterwards(self):
        self.refused(self.submit('nonsense'))
        found = worker_tools.collect(self.job)
        self.assertEqual(found['artifacts'], {})
        self.assertIn('not valid JSON', found['problems']['research-plan'][0])


class BlueprintTests(JobCase):
    def test_the_example_blueprint_is_accepted(self):
        tools = self.tools(artifacts=BLUEPRINTS)
        self.assertEqual(self.ok(tools.submit_artifact('blueprint', BLUEPRINT)),
                         'Accepted: blueprint.')
        kept = worker_tools.collect(self.job)['artifacts']['blueprint']
        self.assertEqual((kept['kind'], kept['text'], kept['warnings']),
                         ('blueprint', BLUEPRINT, []))
        self.assertEqual(kept['path'], self.job / 'accepted' / 'blueprint.md')
        self.assertEqual({check['status'] for check in kept['checks']}, {'passed'})

    def test_a_refused_blueprint_comes_back_with_the_lints_own_words_and_can_be_fixed(self):
        tools = self.tools(artifacts=BLUEPRINTS)
        said = self.refused(tools.submit_artifact('blueprint', '# Blueprint\n\nTo come.\n'))
        self.assertTrue(said.startswith('Not accepted. Fix these and hand it back again:\n- '))
        self.assertIn('- No objectives found under "## Objectives".', said)
        self.assertIn('- No modules found.', said)
        self.assertEqual(worker_tools.collect(self.job)['artifacts'], {})
        self.ok(tools.submit_artifact('blueprint', BLUEPRINT))
        found = worker_tools.collect(self.job)
        self.assertEqual((list(found['artifacts']), found['problems']), (['blueprint'], {}))

    def test_a_citation_of_a_finding_that_is_not_supported_is_refused(self):
        tools = self.tools(artifacts=BLUEPRINTS)
        wrong = BLUEPRINT.replace('[R:health-checks]', '[R:vendor-claim]')
        self.assertIn('K1.3 cites vendor-claim, which is insufficient, not supported.',
                      self.refused(tools.submit_artifact('blueprint', wrong)))

    def test_a_level_must_be_stated_in_the_frame(self):
        tools = self.tools(artifacts={'blueprint@301': {
            'kind': 'blueprint', 'level': '301', 'findings': helpers.FINDINGS}})
        self.assertIn('The frame must say "Level: 301"',
                      self.refused(tools.submit_artifact('blueprint@301', BLUEPRINT)))
        levelled = BLUEPRINT.replace('## Frame\n', '## Frame\nLevel: 301\n')
        self.ok(tools.submit_artifact('blueprint@301', levelled))
        kept = worker_tools.collect(self.job)['artifacts']['blueprint@301']
        self.assertEqual(kept['path'].name, 'blueprint-301.md')

    def test_warnings_are_noted_for_the_reviewer_and_do_not_refuse(self):
        tools = self.tools(artifacts=BLUEPRINTS)
        long = BLUEPRINT.replace('(25 min)', '(60 min)')
        said = self.ok(tools.submit_artifact('blueprint', long))
        self.assertIn('Noted for the person who reviews it:\n- A lesson usually runs 45', said)
        self.assertEqual(len(worker_tools.collect(self.job)['artifacts']['blueprint']
                             ['warnings']), 1)

    def test_a_check_that_cannot_run_is_recorded_and_not_held_against_the_worker(self):
        tools = self.tools(artifacts={'blueprint': {'kind': 'blueprint'}})
        self.ok(tools.submit_artifact('blueprint', BLUEPRINT))
        checks = worker_tools.collect(self.job)['artifacts']['blueprint']['checks']
        self.assertEqual({check['check']: check['status'] for check in checks}
                         ['blueprint.citations'], 'unavailable')

    def test_a_job_with_no_draft_refuses_one(self):
        said = self.refused(self.tools().submit_artifact('blueprint', BLUEPRINT))
        self.assertEqual(said, 'This job has no draft to hand back.')

    def test_a_draft_under_another_name_is_refused(self):
        said = self.refused(self.tools(artifacts=BLUEPRINTS).submit_artifact('document', 'x'))
        self.assertEqual(said, 'This job hands back blueprint, not "document". Use that name.')

    def test_an_empty_draft_is_refused(self):
        tools = self.tools(artifacts=BLUEPRINTS)
        self.assertIn('The text is empty', self.refused(tools.submit_artifact('blueprint', ' ')))
        self.assertIn('The text is empty',
                      self.refused(tools.call('submit_artifact', {'name': 'blueprint',
                                                                  'text': None})))

    def test_a_draft_can_be_handed_back_only_so_many_times(self):
        tools = self.tools(artifacts=BLUEPRINTS)
        for attempt in range(1, worker_tools.SUBMISSIONS + 1):
            said = self.refused(tools.submit_artifact('blueprint', f'# Attempt {attempt}\n'))
            left = worker_tools.SUBMISSIONS - attempt
            if left > 2:
                self.assertNotIn('more time', said)
            elif left:
                self.assertIn(f'It can be handed back {left} more time(s).', said)
            else:
                self.assertIn('it cannot be handed back again', said)
                self.assertIn('Stop now', said)
        said = self.refused(tools.submit_artifact('blueprint', BLUEPRINT))
        self.assertIn(f'has been handed back {worker_tools.SUBMISSIONS} times', said)
        found = worker_tools.collect(self.job)
        self.assertEqual(found['artifacts'], {})
        self.assertIn('No modules found.', found['problems']['blueprint'])


class DraftCase(JobCase):
    """A job that hands back one draft of one kind."""
    KIND = ''

    def drafting(self, **spec) -> worker_tools.WorkerTools:
        return self.tools(artifacts={self.KIND: {'kind': self.KIND, **spec}})

    def kept(self) -> dict:
        return worker_tools.collect(self.job)['artifacts'][self.KIND]

    def statuses(self) -> dict:
        return {check['check']: check['status'] for check in self.kept()['checks']}


class GuideTests(DraftCase):
    KIND = 'document'

    def test_the_example_guide_is_accepted_against_the_example_blueprint(self):
        tools = self.drafting(blueprint=BLUEPRINT)
        self.assertEqual(self.ok(tools.submit_artifact('document', DOCUMENT)),
                         'Accepted: document.')
        kept = self.kept()
        self.assertEqual((kept['text'], kept['warnings'], kept['path'].name),
                         (DOCUMENT, [], 'document.md'))
        self.assertEqual(self.statuses(), {'document.coverage': 'passed'})
        self.assertEqual(kept['checks'][0]['basis'], 'declared')

    def test_a_guide_that_leaves_something_out_comes_back_with_what_is_missing(self):
        tools = self.drafting(blueprint=BLUEPRINT)
        thin = DOCUMENT.replace('<!-- covers: O2 K1.2 -->', '<!-- covers: K1.2 -->')
        said = self.refused(tools.submit_artifact('document', thin))
        self.assertIn('- O2 is not covered by any section.', said)
        self.assertEqual(worker_tools.collect(self.job)['artifacts'], {})
        self.ok(tools.submit_artifact('document', DOCUMENT))

    def test_a_guide_may_not_teach_what_the_research_could_not_support(self):
        tools = self.drafting(blueprint=BLUEPRINT)
        wrong = DOCUMENT.replace('<!-- covers: O1 K1.1 K1.3 -->',
                                 '<!-- covers: O1 K1.1 K1.3 K1.4 K9.9 -->')
        said = self.refused(tools.submit_artifact('document', wrong))
        self.assertIn('- K1.4 is [unsupported] and must not be taught.', said)
        self.assertIn('- K9.9 is not in the blueprint.', said)

    def test_without_its_blueprint_the_check_cannot_run_which_is_not_held_against_it(self):
        self.ok(self.drafting().submit_artifact('document', '# A guide\n\nWords.\n'))
        check, = self.kept()['checks']
        self.assertEqual((check['check'], check['status'], check['problems']), (
            'document.coverage', 'unavailable',
            ['The blueprint was not given, so coverage could not be checked.']))


class BriefDraftTests(DraftCase):
    KIND = 'brief'

    def test_the_example_briefs_are_accepted_each_as_its_own_kind(self):
        for kind, text in (('product', BRIEF), ('competitive', COMPETITIVE)):
            with self.subTest(kind):
                self.job = self.base / kind
                tools = self.drafting(brief_kind=kind, findings=helpers.FINDINGS)
                self.ok(tools.submit_artifact('brief', text))
                self.assertEqual(self.statuses(), {'brief.sections': 'passed',
                                                   'brief.findings': 'passed'})
                self.assertEqual(self.kept()['text'], text)

    def test_a_brief_of_the_wrong_kind_or_shape_comes_back_with_the_checks_own_words(self):
        tools = self.drafting(brief_kind='competitive', findings=helpers.FINDINGS)
        said = self.refused(tools.submit_artifact('brief', BRIEF))
        self.assertIn('- The title must start with "# Competitive brief:".', said)
        self.assertIn('- Section "Comparison" is missing.', said)
        swapped = COMPETITIVE.replace('## 3. Differentiators', '## 3. Limitations', 1) \
            .replace('## 4. Limitations', '## 4. Differentiators', 1)
        self.assertIn('- Sections are out of order; expected: Executive summary, Comparison',
                      self.refused(tools.submit_artifact('brief', swapped)))

    def test_a_section_may_rest_only_on_findings_that_exist_and_are_supported(self):
        tools = self.drafting(brief_kind='product', findings=helpers.FINDINGS)
        for old, new, said in (
                ('<!-- findings: availability -->', '<!-- findings: made-up -->',
                 'Section "What it is and where it fits" names unknown finding made-up.'),
                ('<!-- findings: availability health-checks -->',
                 '<!-- findings: vendor-claim -->',
                 'Section "Capabilities" rests on vendor-claim, which is insufficient.'),
                ('<!-- findings: instance-min -->\n\n- A single', '- A single',
                 'Section "Limitations" names no findings.')):
            with self.subTest(said):
                self.assertIn(old, BRIEF)
                self.assertIn(f'- {said}', self.refused(tools.submit_artifact(
                    'brief', BRIEF.replace(old, new, 1))))
        self.ok(tools.submit_artifact('brief', BRIEF))

    def test_without_the_findings_that_check_cannot_run_and_the_brief_is_still_taken(self):
        self.ok(self.drafting(brief_kind='product').submit_artifact('brief', BRIEF))
        self.assertEqual(self.statuses(), {'brief.sections': 'passed',
                                           'brief.findings': 'unavailable'})
        self.job = self.base / 'unnamed'
        self.ok(self.drafting(findings=helpers.FINDINGS).submit_artifact('brief', BRIEF))
        self.assertEqual(self.statuses()['brief.sections'], 'passed',
                         'a brief with no kind named is a product brief')


class ScenarioDraftTests(DraftCase):
    KIND = 'scenario'

    def test_the_example_scenario_is_accepted(self):
        tools = self.drafting(label='scenario:main', mode='roleplay')
        self.assertEqual(self.ok(tools.submit_artifact('scenario', SCENARIO)),
                         'Accepted: scenario.')
        self.assertEqual((self.statuses(), self.kept()['warnings'], self.kept()['text']),
                         ({'scenario:main.sections': 'passed'}, [], SCENARIO))

    def test_a_scenario_that_is_not_in_shape_comes_back_with_what_it_lacks(self):
        tools = self.drafting(label='scenario:objection')
        said = self.refused(tools.submit_artifact('scenario', 'A lead rings after a restart '
                                                  'dropped requests.\n'))
        for problem in ('The file must start with "# Scenario: <name>".',
                        'Section "Opening" is missing or empty.',
                        'Section "Success criteria" is missing or empty.'):
            self.assertIn(f'- {problem}', said)
        prose = SCENARIO.replace('- Describes what a rolling restart does.\n- Explains that '
                                 'capacity holds only with more than one instance.\n- '
                                 'Corrects the zero-downtime belief without dismissing the '
                                 'customer.\n- Leaves with an agreed next step.',
                                 'The learner explains it well.')
        self.assertNotEqual(prose, SCENARIO)
        self.assertIn('- Success criteria must be a list, one criterion per item.',
                      self.refused(tools.submit_artifact('scenario', prose)))
        unknown = SCENARIO.replace('## Mode\n\nroleplay', '## Mode\n\ndebate')
        self.assertIn('- Mode "debate" is not one of: roleplay, pitch, tutor, questionnaire',
                      self.refused(tools.submit_artifact('scenario', unknown)))
        self.ok(tools.submit_artifact('scenario', SCENARIO))
        self.assertEqual(self.statuses(), {'scenario:objection.sections': 'passed'})

    def test_a_mode_other_than_the_practice_plans_is_noted_and_does_not_refuse(self):
        tools = self.drafting(label='scenario:main', mode='pitch')
        said = self.ok(tools.submit_artifact('scenario', SCENARIO))
        self.assertIn('Noted for the person who reviews it:\n- The practice plan lists this '
                      'scenario as pitch; the file says roleplay. The scenario file decides.',
                      said)
        self.assertEqual(len(self.kept()['warnings']), 1)


class YoodliDraftTests(DraftCase):
    KIND = 'yoodli'
    SPEC = {'label': 'yoodli:main', 'profile': PROFILE, 'scenario': SCENARIO,
            'objectives': ['O1', 'O2', 'O3']}

    def test_the_example_yoodli_scenario_is_accepted(self):
        tools = self.drafting(**self.SPEC)
        self.assertEqual(self.ok(tools.submit_artifact('yoodli', YOODLI)), 'Accepted: yoodli.')
        self.assertEqual(self.statuses(), {'yoodli:main.fields': 'passed',
                                           'yoodli:main.limits': 'passed',
                                           'yoodli:main.mapping': 'passed'})
        limits = self.kept()['checks'][1]
        self.assertEqual((limits['counts']['Context'], limits['provisional'],
                          self.kept()['text']), (666, True, YOODLI))

    def test_the_real_length_of_each_field_is_put_in_for_the_worker(self):
        zeroed = re.sub(r'\b[\d,]+ of ', '0 of ', YOODLI)
        self.assertEqual((zeroed.count('0 of '), worker_tools.counted(zeroed)), (10, YOODLI))
        self.assertEqual(worker_tools.counted(YOODLI), YOODLI)
        guessed = YOODLI.replace('666 of 10,000 characters', '1,234 of 10,000 characters')
        tools = self.drafting(**self.SPEC)
        self.ok(tools.submit_artifact('yoodli', guessed))
        self.assertEqual(self.kept()['text'], YOODLI)
        self.assertEqual(checks.stated_counts(self.kept()['text'])[('Context',)], 666)
        block = '```text\n12 of 99 characters\n```\n'
        self.assertEqual(worker_tools.counted(f'## Context\n\n{block}'),
                         f'## Context\n\n{block}', 'what is to be pasted is never changed')

    def test_a_field_over_its_limit_is_refused_and_nothing_is_cut(self):
        tools = self.drafting(**self.SPEC)
        long = YOODLI.replace('You are Priya Nair, the platform lead',
                              'You are Priya Nair, the platform lead' + ' and so on' * 1000)
        said = self.refused(tools.submit_artifact('yoodli', long))
        self.assertIn('- Context is 10666 characters; the limit is 10000.', said)
        self.assertEqual(worker_tools.collect(self.job)['artifacts'], {})

    def test_a_layout_that_does_not_fit_yoodli_or_its_scenario_comes_back(self):
        tools = self.drafting(**self.SPEC)
        for old, new, said in (
                ('```text\nObjection Handling\n```', '```text\nPitch\n```',
                 'Type "Pitch" does not match the scenario mode roleplay; expected '
                 '"Objection Handling".'),
                ('<!-- criterion: 3 4 -->', '<!-- criterion: 3 -->',
                 'Success criterion 4 is not carried by any goal: "Leaves with an agreed '
                 'next step."'),
                ('<!-- assesses: O3 -->', '<!-- assesses: O7 -->',
                 'Goal 3 assesses unknown objective O7.'),
                ('<!-- scenario: main -->', '<!-- scenario: other -->',
                 'The file must name its scenario with <!-- scenario: main -->.'),
                ('#### Role\n\n```text\nPlatform lead\n```\n', '',
                 'Persona 1: field "Role" is missing or empty.'),
                ('```text\nBinary\n```', '```text\nPass or fail\n```',
                 'Goal 1: type "Pass or fail" is not one of: Binary, Rated')):
            with self.subTest(said):
                self.assertIn(old, YOODLI)
                self.assertIn(f'- {said}', self.refused(tools.submit_artifact(
                    'yoodli', YOODLI.replace(old, new, 1))))

    def test_what_cannot_be_checked_is_recorded_and_not_held_against_the_worker(self):
        self.ok(self.drafting(label='yoodli:main', profile=PROFILE)
                .submit_artifact('yoodli', YOODLI))
        self.assertEqual(self.statuses(), {'yoodli:main.fields': 'passed',
                                           'yoodli:main.limits': 'passed',
                                           'yoodli:main.mapping': 'unavailable'})
        self.assertEqual(self.kept()['checks'][2]['problems'],
                         ['The scenario file is missing.'])
        self.job = self.base / 'no-profile'
        self.ok(self.drafting(label='yoodli:main').submit_artifact('yoodli', YOODLI))
        self.assertEqual(set(self.statuses().values()), {'unavailable'})
        self.assertEqual(self.kept()['checks'][0]['problems'],
                         ['The Yoodli profile was not given, so this could not be checked.'])


class ReviewTests(JobCase):
    def test_notes_are_kept_once_the_draft_is_accepted(self):
        tools = self.tools(artifacts=BLUEPRINTS)
        said = self.refused(tools.submit_review('It is fine.'))
        self.assertIn('Hand the draft back first', said)
        tools.submit_artifact('blueprint', BLUEPRINT)
        self.ok(tools.submit_review('  The third objective is the weakest.  '))
        self.assertEqual(worker_tools.collect(self.job)['review'],
                         'The third objective is the weakest.\n')

    def test_notes_that_cannot_be_written_are_refused_not_lost_silently(self):
        tools = self.tools(artifacts=BLUEPRINTS)
        tools.submit_artifact('blueprint', BLUEPRINT)
        with mock.patch.object(worker_tools, '_write', side_effect=OSError('No space left')):
            self.assertEqual(self.refused(tools.submit_review('Notes.')), 'No space left')
        self.assertIsNone(worker_tools.collect(self.job)['review'])

    def test_a_job_with_no_draft_has_nothing_to_review(self):
        self.assertIn('nothing to write notes on',
                      self.refused(self.tools(finding='instance-min').submit_review('Notes.')))

    def test_empty_and_overlong_notes_are_refused(self):
        tools = self.tools(artifacts=BLUEPRINTS)
        tools.submit_artifact('blueprint', BLUEPRINT)
        self.assertEqual(self.refused(tools.submit_review('  ')), 'Your notes are empty.')
        self.assertIn('Keep them under 4,000',
                      self.refused(tools.submit_review('x' * 4001)))
        self.assertIsNone(worker_tools.collect(self.job)['review'])


class FetchRuleTests(JobCase):
    def research(self, **extra):
        return self.tools(finding='instance-min', fetch=True, ask=False, **extra)

    def test_a_job_that_may_not_fetch_refuses(self):
        self.web.page(DOCS, PAGE)
        said = self.refused(self.tools(finding='instance-min').save_source(DOCS))
        self.assertIn('This job cannot fetch pages', said)
        self.assertEqual(self.web.asked, [])

    def test_only_http_and_https_addresses_are_fetched(self):
        tools = self.research()
        for address in ('ftp://docs.example.com/file', 'file:///etc/hosts', 'docs.example.com',
                        'https:///restarts', 'javascript:alert(1)'):
            with self.subTest(address):
                self.assertEqual(self.refused(tools.save_source(address)),
                                 'Only http and https addresses can be saved.')
        self.assertEqual(self.refused(tools.save_source('http://[::1/admin')),
                         'That is not a web address.')
        self.assertIn('longer than 2,000 characters',
                      self.refused(tools.save_source('https://docs.example.com/' + 'x' * 2000)))
        self.assertEqual(self.web.asked, [])

    def test_an_address_with_a_password_is_refused(self):
        self.web.page('https://docs.example.com/x', PAGE)
        said = self.refused(self.research().save_source('https://me:secret@docs.example.com/x'))
        self.assertIn('carries a name or password', said)
        self.assertEqual(self.web.asked, [])

    def test_private_loopback_and_link_local_addresses_are_refused(self):
        tools = self.research()
        for number, address in enumerate((
                '127.0.0.1', '10.0.0.5', '172.16.4.1', '192.168.1.10', '169.254.169.254',
                '100.64.0.1', '0.0.0.0', '::1', 'fe80::1', 'fc00::1', '::ffff:127.0.0.1',
                '::ffff:10.0.0.5', 'fe80::1%en0', 'not-an-address')):
            with self.subTest(address):
                url = self.web.page(f'http://host{number}.example.com/', PAGE,
                                    addresses=[address])
                self.assertEqual(self.refused(tools.save_source(url)),
                                 'That address is not on the public internet, so it was not '
                                 'fetched.')
        self.assertEqual(self.web.asked, [])
        self.assertEqual(worker_tools.collect(self.job)['sources'], [])

    def test_a_name_with_one_private_address_among_public_ones_is_refused(self):
        url = self.web.page('https://mixed.example.com/', PAGE, addresses=[PUBLIC, '10.0.0.5'])
        self.assertIn('not on the public internet', self.refused(self.research().save_source(url)))
        self.assertEqual(self.web.asked, [])

    def test_a_literal_private_address_is_refused_by_the_real_lookup(self):
        tools = worker_tools.WorkerTools(
            worker_tools.prepare(self.job, finding='instance-min', fetch=True),
            opener=self.web.opener)
        for url in ('http://127.0.0.1:8080/admin', 'http://169.254.169.254/latest/'):
            with self.subTest(url):
                self.assertIn('not on the public internet', self.refused(tools.save_source(url)))
        self.refused(tools.save_source('http://[::1]/'))
        self.assertEqual(self.web.asked, [])

    def test_public_addresses_are_told_from_the_rest(self):
        self.assertTrue(worker_tools.public(PUBLIC))
        self.assertTrue(worker_tools.public('2606:2800:220:1:248:1893:25c8:1946'))
        self.assertFalse(worker_tools.public('192.168.0.1'))
        self.assertFalse(worker_tools.public('::ffff:192.168.0.1'))

    def test_a_name_that_cannot_be_looked_up_is_refused(self):
        said = self.refused(self.research().save_source('https://nowhere.example.com/'))
        self.assertIn('Could not look up nowhere.example.com', said)

    def test_a_redirect_to_a_private_address_is_refused(self):
        self.web.page('http://internal.example.com/admin', 'secret', addresses=['10.0.0.5'])
        url = self.web.page('https://docs.example.com/go', '', status=302,
                            headers={'location': 'http://internal.example.com/admin'})
        said = self.refused(self.research().save_source(url))
        self.assertIn('not on the public internet', said)
        self.assertEqual(self.web.asked, [(url, PUBLIC)])
        self.assertEqual(worker_tools.collect(self.job)['sources'], [])

    def test_a_redirect_to_a_public_page_is_followed_and_the_final_address_kept(self):
        self.web.page('https://docs.example.com/restarts/', PAGE)
        url = self.web.page('https://docs.example.com/old', '', status=301,
                            headers={'location': '/restarts/'})
        tools = self.research()
        self.assertTrue(self.ok(tools.save_source(url)).startswith('Saved as s1'))
        source = worker_tools.collect(self.job)['sources'][0]
        self.assertEqual((source['url'], source['asked']),
                         ('https://docs.example.com/restarts/', url))
        self.assertTrue(self.ok(tools.save_source(url)).startswith('Already saved as s1'))

    def test_endless_redirects_are_given_up_on(self):
        url = self.web.page('https://docs.example.com/loop', '', status=302,
                            headers={'location': '/loop'})
        self.assertIn('redirected too many times', self.refused(self.research().save_source(url)))
        self.assertEqual(len(self.web.asked), worker_tools.MAX_HOPS + 1)

    def test_a_site_that_says_no_is_reported_as_it_answered(self):
        url = self.web.page('https://docs.example.com/private', 'Go away', status=403)
        self.assertEqual(self.refused(self.research().save_source(url)),
                         'The site answered 403 Forbidden. The page was not saved.')

    def test_a_page_over_the_size_limit_is_refused(self):
        url = self.web.page(DOCS, PAGE)
        with mock.patch.object(worker_tools, 'MAX_BYTES', 100):
            said = self.refused(self.research().save_source(url))
        self.assertIn('so it was not saved', said)
        self.assertEqual(worker_tools.collect(self.job)['sources'], [])

    def test_something_that_is_not_a_page_or_a_pdf_is_refused(self):
        url = self.web.page('https://docs.example.com/logo.png', b'\x89PNG\r\n', 'image/png')
        self.assertEqual(self.refused(self.research().save_source(url)),
                         'That address holds image/png, not a page or a PDF. It was not saved.')

    def test_a_page_with_no_readable_text_is_refused_and_nothing_is_kept(self):
        url = self.web.page(DOCS, '<html><body><script>render()</script></body></html>')
        said = self.refused(self.research().save_source(url))
        self.assertIn('has no readable text; it may need a browser', said)
        self.assertEqual([path.name for path in (self.job / 'sources').iterdir()],
                         ['index.json'])

    def test_a_connection_that_fails_tries_the_next_address_then_gives_up(self):
        url = self.web.page(DOCS, PAGE, addresses=[PUBLIC, '93.184.216.35'])
        tried = []

        def opener(asked, address, limit):
            tried.append(address)
            if address == PUBLIC:
                raise OSError('connection refused')
            return self.web.opener(asked, address, limit)

        tools = self.research()
        tools.opener = opener
        self.ok(tools.save_source(url))
        self.assertEqual(tried, [PUBLIC, '93.184.216.35'])
        self.web.pages['https://docs.example.com/down'] = OSError('timed out')
        said = self.refused(tools.save_source('https://docs.example.com/down'))
        self.assertEqual(said, 'Could not fetch the page (timed out). It was not saved.')

    def test_only_so_many_sources_are_saved(self):
        tools = self.research()
        with mock.patch.object(worker_tools, 'MAX_SOURCES', 2):
            for number in range(2):
                self.ok(tools.save_source(self.web.page(f'{DOCS}/{number}', PAGE + str(number))))
            said = self.refused(tools.save_source(self.web.page(f'{DOCS}/2', PAGE)))
        self.assertIn('has saved 2 sources, which is the most it may', said)

    def test_a_compressed_body_is_unpacked_and_a_garbled_one_refused(self):
        tools = self.research()
        url = self.web.page(DOCS, gzip.compress(PAGE.encode()),
                            headers={'content-encoding': 'gzip'})
        self.assertIn('Capacity holds only when', self.ok(tools.save_source(url)))
        bad = self.web.page(f'{DOCS}/bad', b'not gzip', headers={'content-encoding': 'br'})
        self.assertIn('could not be read', self.refused(tools.save_source(bad)))

    def test_requests_look_like_a_browsers(self):
        self.assertTrue(worker_tools.HEADERS['User-Agent'].startswith('Mozilla/5.0 '))
        self.assertIn('text/html', worker_tools.HEADERS['Accept'])
        self.assertIn('Accept-Language', worker_tools.HEADERS)


class SourceTests(JobCase):
    def saved(self, body=PAGE, **page):
        tools = self.tools(finding='instance-min', fetch=True)
        said = self.ok(tools.save_source(self.web.page(DOCS, body, **page)))
        return tools, said, worker_tools.collect(self.job)['sources'][0]

    def test_a_page_is_kept_with_its_text_its_original_and_its_hash(self):
        import hashlib
        tools, said, source = self.saved()
        digest = hashlib.sha256(PAGE.encode()).hexdigest()
        self.assertEqual((source['id'], source['title'], source['url'], source['sha256']),
                         ('s1', 'Rolling restarts', DOCS, digest))
        self.assertEqual(source['file'], f'sources/docs-example-com-{digest[:12]}.txt')
        self.assertEqual(source['original'], f'sources/docs-example-com-{digest[:12]}.html')
        self.assertEqual(source['path'], self.job / source['file'])
        self.assertEqual(source['original_path'].read_bytes(), PAGE.encode())
        text = source['path'].read_text(encoding='utf-8')
        self.assertTrue(text.startswith('Rolling restarts\n\nA rolling restart replaces'))
        self.assertNotIn('hidden', text)
        self.assertNotIn('color', text)
        self.assertEqual(source['chars'], len(text))
        self.assertTrue(said.startswith(f'Saved as s1: "Rolling restarts", {len(text)} '
                                        'characters.\n\nRolling restarts'))
        self.assertEqual(self.web.asked, [(DOCS, PUBLIC)])

    def test_the_same_content_is_named_the_same_whichever_job_saved_it(self):
        _, _, first = self.saved()
        other = self.base / 'another-job'
        worker_tools.prepare(other, finding='health-checks', fetch=True)
        tools = worker_tools.WorkerTools(other, opener=self.web.opener,
                                         resolver=self.web.resolver)
        tools.save_source(DOCS)
        self.assertEqual(worker_tools.collect(other)['sources'][0]['file'], first['file'])

    def test_a_long_page_says_how_to_read_the_rest(self):
        body = '<p>' + 'word ' * 4000 + '</p>'
        _, said, source = self.saved(body)
        self.assertIn(f"[{source['chars'] - worker_tools.WINDOW:,} more characters. Use "
                      'search_source', said)

    def test_a_page_is_read_in_the_encoding_it_declares(self):
        _, said, _ = self.saved('<p>Café capacity</p>'.encode('latin-1'),
                                kind='text/html; charset=ISO-8859-1')
        self.assertIn('Café capacity', said)
        self.job.joinpath('job.json').unlink()
        body = b'<meta charset="windows-1252"><p>Caf\xe9 again</p>'
        self.assertIn('Café again', self.saved(body, kind='text/html')[1])

    def test_characters_that_would_shift_a_quote_are_dropped(self):
        _, _, source = self.saved('﻿<p>Batch\x00 size is two.</p>')
        self.assertEqual(source['path'].read_text(encoding='utf-8'), 'Batch size is two.\n')

    def test_an_endless_title_is_cut_short(self):
        _, _, source = self.saved(f"<title>{'Restarts ' * 100}</title><p>Body text.</p>")
        self.assertEqual(len(source['title']), 301)

    def test_plain_text_is_kept_as_it_is(self):
        _, said, source = self.saved('Line one.\n<not a tag>\n', kind='text/plain')
        self.assertIn('Line one.\n<not a tag>', said)
        self.assertTrue(source['original'].endswith('.raw'))
        self.assertEqual(source['title'], 'docs.example.com')

    def test_a_pdf_is_read_with_the_pdf_reader(self):
        tools = self.tools(finding='instance-min', fetch=True)
        url = self.web.page('https://docs.example.com/files/Restart%20guide.pdf',
                            b'%PDF-1.7 ...', 'application/octet-stream')
        self.assertIn('Text of the PDF.', self.ok(tools.save_source(url)))
        source = worker_tools.collect(self.job)['sources'][0]
        self.assertEqual(source['title'], 'Restart guide.pdf')
        self.assertTrue(source['original'].endswith('.pdf'))
        self.assertEqual(source['original_path'].read_bytes(), b'%PDF-1.7 ...')

    def test_a_pdf_is_refused_when_this_computer_cannot_read_one(self):
        tools = self.tools(finding='instance-min', fetch=True)
        tools.pdf = worker_tools.pdf_text
        url = self.web.page('https://docs.example.com/guide.pdf', b'%PDF-1.7 ...',
                            'application/pdf')
        with mock.patch.object(worker_tools.shutil, 'which', return_value=None):
            said = self.refused(tools.save_source(url))
        self.assertIn('this computer has no PDF reader (pdftotext)', said)
        self.assertEqual([path.name for path in (self.job / 'sources').iterdir()],
                         ['index.json'])

    def test_a_pdf_that_cannot_be_read_is_refused(self):
        done = subprocess.CompletedProcess([], 1, b'', b'Syntax Error')
        with mock.patch.object(worker_tools.shutil, 'which', return_value='/bin/pdftotext'), \
                mock.patch.object(worker_tools.subprocess, 'run', return_value=done):
            with self.assertRaisesRegex(worker_tools.Refusal, 'could not be read'):
                worker_tools.pdf_text(self.job / 'x.pdf')

    def test_a_source_is_read_from_an_offset(self):
        tools, _, source = self.saved()
        text = source['path'].read_text(encoding='utf-8')
        said = self.ok(tools.read_source('s1', '18', 30))
        self.assertEqual(said, f'[s1: characters 18 to 48 of {len(text)}]\n\n{text[18:48]}')
        whole = self.ok(tools.read_source('s1', 0, 10 ** 9))
        self.assertTrue(whole.endswith(text))

    def test_reading_past_the_end_or_an_unknown_source_is_refused(self):
        tools, _, source = self.saved()
        self.assertIn(f"s1 has {source['chars']} characters; there is nothing at 5,000",
                      self.refused(tools.read_source('s1', 5000)))
        self.assertEqual(self.refused(tools.read_source('s9')),
                         'There is no source s9. Saved sources: s1.')
        self.assertIn('offset must be a whole number',
                      self.refused(tools.read_source('s1', 'start')))

    def test_a_source_is_searched_without_regard_to_case(self):
        tools, _, source = self.saved()
        text = source['path'].read_text(encoding='utf-8')
        said = self.ok(tools.search_source('s1', 'CAPACITY  holds'))
        self.assertTrue(said.startswith(f"[offset {text.index('Capacity holds')}] …"))
        self.assertIn('more than one instance', said)
        self.assertEqual(self.ok(tools.search_source('s1', 'rollback')),
                         'No match in s1. Try fewer or different words.')
        self.assertEqual(self.refused(tools.search_source('s1', '  ')), 'Say what to look for.')
        self.assertIn('There is no source s2', self.refused(tools.search_source('s2', 'x')))

    def test_a_source_with_nothing_saved_says_so(self):
        tools = self.tools(finding='instance-min', fetch=True)
        self.assertEqual(self.refused(tools.read_source('s1')),
                         'There is no source s1. Saved sources: none yet.')


class PinnedFetchTests(unittest.TestCase):
    """The real request, over a socket pair in place of the network."""

    def fetch(self, url: str, answer: bytes):
        ours, theirs = socket.socketpair()
        seen = {}

        def serve():
            seen['request'] = theirs.recv(65536).decode('latin-1')
            theirs.sendall(answer)
            theirs.close()

        def connect(address, *args, **kwargs):
            seen['address'] = address
            return ours

        thread = threading.Thread(target=serve)
        thread.start()
        with mock.patch.object(socket, 'create_connection', side_effect=connect), \
                mock.patch.object(worker_tools.urllib.request, 'getproxies', return_value={}):
            found = worker_tools.fetch_once(url, PUBLIC, 1000)
        thread.join()
        return found, seen

    def test_it_connects_to_the_checked_address_and_asks_as_a_browser_would(self):
        answer = b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 5\r\n\r\nhello'
        (status, headers, body), seen = self.fetch('http://docs.example.com/restarts', answer)
        self.assertEqual((status, headers['content-type'], body), (200, 'text/html', b'hello'))
        self.assertEqual(seen['address'], (PUBLIC, 80))
        self.assertIn('GET /restarts HTTP/1.1', seen['request'])
        self.assertIn('Host: docs.example.com', seen['request'])
        self.assertIn('User-Agent: Mozilla/5.0', seen['request'])

    def test_an_https_request_goes_to_the_checked_address_under_the_hosts_own_name(self):
        ours, theirs = socket.socketpair()
        plain, context, seen = object(), mock.Mock(), {}
        context.wrap_socket.return_value = ours

        def serve():
            seen['request'] = theirs.recv(65536).decode('latin-1')
            theirs.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok')
            theirs.close()

        def connect(address, *args, **kwargs):
            seen['address'] = address
            return plain

        thread = threading.Thread(target=serve)
        thread.start()
        with mock.patch.object(socket, 'create_connection', side_effect=connect), \
                mock.patch.object(worker_tools.ssl, 'create_default_context',
                                  return_value=context), \
                mock.patch.object(worker_tools.urllib.request, 'getproxies', return_value={}):
            status, _, body = worker_tools.fetch_once('https://docs.example.com:8443/restarts',
                                                      PUBLIC, 1000)
        thread.join()
        self.assertEqual((status, body, seen['address']), (200, b'ok', (PUBLIC, 8443)))
        context.wrap_socket.assert_called_once_with(plain, server_hostname='docs.example.com')
        self.assertIn('Host: docs.example.com:8443', seen['request'])

    def test_a_redirect_comes_back_as_an_answer_and_is_not_followed(self):
        answer = (b'HTTP/1.1 302 Found\r\nLocation: http://169.254.169.254/\r\n'
                  b'Content-Length: 0\r\n\r\n')
        (status, headers, body), seen = self.fetch('http://docs.example.com/go', answer)
        self.assertEqual((status, headers['location'], body),
                         (302, 'http://169.254.169.254/', b''))
        self.assertEqual(seen['address'], (PUBLIC, 80))

    def test_an_error_answer_is_returned_not_raised(self):
        answer = b'HTTP/1.1 404 Not Found\r\nContent-Length: 4\r\n\r\ngone'
        (status, _, body), _ = self.fetch('http://docs.example.com/missing', answer)
        self.assertEqual((status, body), (404, b'gone'))

    def test_no_more_than_the_limit_and_one_byte_is_read(self):
        answer = b'HTTP/1.1 200 OK\r\nContent-Length: 5000\r\n\r\n' + b'x' * 5000
        (_, _, body), _ = self.fetch('http://docs.example.com/big', answer)
        self.assertEqual(len(body), 1001)


class FindingTests(JobCase):
    def research(self, **extra):
        tools = self.tools(finding='instance-min', fetch=True, ask=False, **extra)
        self.ok(tools.save_source(self.web.page(DOCS, PAGE)))
        self.text = worker_tools.collect(self.job)['sources'][-1]['path'].read_text('utf-8')
        return tools

    def submit(self, tools, quote=QUOTE, **changes):
        given = {'item': 'instance-min', 'status': 'supported',
                 'summary': 'An app keeps capacity when it runs more than one instance.',
                 'limits': 'One page from the platform\'s own documentation.',
                 'evidence': [{'source_id': 's1', 'quote': quote}], **changes}
        return tools.submit_finding(**given)

    def test_an_accepted_finding_has_each_quote_placed(self):
        tools = self.research()
        self.assertEqual(self.ok(self.submit(tools)),
                         'Accepted: the finding for instance-min, with 1 quoted passage(s).')
        finding = worker_tools.collect(self.job)['finding']
        self.assertEqual((finding['item'], finding['status']), ('instance-min', 'supported'))
        passage, source = finding['evidence'][0], worker_tools.collect(self.job)['sources'][0]
        start = self.text.index(QUOTE)
        self.assertEqual(passage, {
            'file': source['file'], 'title': 'Rolling restarts', 'origin': DOCS, 'quote': QUOTE,
            'start': start, 'locator': f'characters {start} to {start + len(QUOTE)}'})
        self.assertEqual(self.text[start:start + len(QUOTE)], QUOTE)

    def test_a_quote_that_is_not_there_is_refused(self):
        tools = self.research()
        said = self.refused(self.submit(tools, 'Capacity always holds during a restart.'))
        self.assertIn('Passage 1: the quote is not in s1 as written.', said)
        self.assertIsNone(worker_tools.collect(self.job)['finding'])
        self.assertIn('Passage 1', worker_tools.collect(self.job)['problems']['finding'][0])

    def test_a_quote_with_words_left_out_is_refused(self):
        tools = self.research()
        said = self.refused(self.submit(tools, 'A rolling restart replaces instances ... so '
                                        'the app keeps serving traffic'))
        self.assertIn('no "..." in it', said)

    def test_a_quote_across_a_line_break_is_found_and_kept_in_the_sources_wording(self):
        tools = self.research()
        typed = 'so the app keeps   serving traffic while it restarts.'
        self.assertNotIn(typed, self.text)
        self.ok(self.submit(tools, typed))
        passage = worker_tools.collect(self.job)['finding']['evidence'][0]
        self.assertEqual(passage['quote'], 'so the app keeps serving\ntraffic while it restarts.')
        self.assertEqual(self.text[passage['start']:passage['start'] + len(passage['quote'])],
                         passage['quote'])

    def test_a_quote_with_plain_marks_matches_the_sources_curly_ones(self):
        tools = self.research()
        self.ok(self.submit(tools, "The platform's health check decides when the next batch "
                                   'starts.'))
        passage = worker_tools.collect(self.job)['finding']['evidence'][0]
        self.assertIn('platform’s health\ncheck', passage['quote'])

    def test_where_a_quote_sits_is_counted_in_characters_not_bytes(self):
        text = 'Café \U0001f600 capacity holds with two instances.\n'
        self.assertEqual(worker_tools.place(text, 'capacity holds with two instances.'),
                         (7, 'capacity holds with two instances.'))
        self.assertEqual(worker_tools.place(text, 'two — instances'), None)
        self.assertEqual(worker_tools.place('up - or down', 'up – or down'),
                         (0, 'up - or down'))
        self.assertIsNone(worker_tools.place(text, ''))
        self.assertIsNone(worker_tools.place(text, '   '))

    def test_a_quote_must_be_a_passage_not_a_fragment_or_a_page(self):
        tools = self.research()
        self.assertIn('Passage 1: the quote is 14 characters. Quote the whole sentence',
                      self.refused(self.submit(tools, 'Capacity holds')))
        with mock.patch.object(worker_tools, 'QUOTE', (20, 40)):
            self.assertIn('between 20 and 40 characters', self.refused(self.submit(tools)))

    def test_a_passage_from_a_source_that_was_not_saved_is_refused(self):
        tools = self.research()
        said = self.refused(self.submit(tools, evidence=[{'source_id': 's4', 'quote': QUOTE}]))
        self.assertIn('Passage 1: There is no source s4. Saved sources: s1.', said)
        said = self.refused(self.submit(tools, evidence=['s1']))
        self.assertIn('Passage 1 needs a source_id and a quote.', said)

    def test_a_verdict_that_claims_something_needs_a_quote(self):
        tools = self.research()
        for status in ('supported', 'contradicted'):
            said = self.refused(self.submit(tools, status=status, evidence=[]))
            self.assertIn(f'A {status} finding needs at least one quoted passage.', said)
        self.ok(self.submit(tools, status='insufficient', evidence=None, limits=''))
        finding = worker_tools.collect(self.job)['finding']
        self.assertEqual((finding['evidence'], finding['limits']), ([], 'none'))

    def test_the_verdict_summary_limits_and_number_of_passages_are_checked(self):
        tools = self.research()
        self.assertIn('status must be one of: supported, contradicted, insufficient, '
                      'unavailable.', self.refused(self.submit(tools, status='proven')))
        self.assertIn('The summary is empty.', self.refused(self.submit(tools, summary=' ')))
        self.assertIn('The summary is 1,501 characters',
                      self.refused(self.submit(tools, summary='x' * 1501)))
        self.assertIn('The limits are too long',
                      self.refused(self.submit(tools, limits='x' * 4001)))
        many = [{'source_id': 's1', 'quote': QUOTE}] * 21
        with mock.patch.object(worker_tools, 'SUBMISSIONS', 99):
            self.assertIn('Give at most 20 passages',
                          self.refused(self.submit(tools, evidence=many)))

    def test_evidence_may_arrive_as_json_text_but_must_be_a_list(self):
        tools = self.research()
        self.assertIn('evidence must be a list of passages',
                      self.refused(self.submit(tools, evidence='s1 says so')))
        self.assertIn('evidence must be a list of passages',
                      self.refused(self.submit(tools, evidence={'source_id': 's1'})))
        self.ok(self.submit(tools, evidence=json.dumps([{'source_id': 's1', 'quote': QUOTE}])))

    def test_a_job_answers_its_own_question_and_no_other(self):
        tools = self.research()
        self.assertEqual(self.refused(self.submit(tools, item='health-checks')),
                         'This job answers instance-min, not "health-checks".')
        writer = worker_tools.WorkerTools(worker_tools.prepare(self.base / 'w',
                                                               artifacts=BLUEPRINTS))
        self.assertEqual(self.refused(self.submit(writer)),
                         'This job does not answer a research question.')

    def test_a_finding_can_be_handed_back_only_so_many_times(self):
        tools = self.research()
        for _ in range(worker_tools.SUBMISSIONS):
            self.refused(self.submit(tools, 'This sentence is not in the page at all.'))
        self.assertIn('This finding has been handed back', self.refused(self.submit(tools)))

    def test_a_supplied_document_is_quoted_under_its_own_id_and_path(self):
        tools = self.tools(finding='instance-min', ask=False, sources=[{
            'title': 'Operations handbook', 'origin': 'Supplied by the team',
            'text': 'Restart   one batch at a time.\nKeep two instances running throughout.',
            'file': 'sources/handbook.txt', 'supplied': 'handbook'}])
        self.assertIn('This job cannot fetch pages', self.refused(tools.save_source(DOCS)))
        self.ok(tools.submit_finding('instance-min', 'supported', 'Two instances are kept.',
                                     evidence=[{'source_id': 's1', 'quote': 'Keep two '
                                                'instances running throughout.'}]))
        passage = worker_tools.collect(self.job)['finding']['evidence'][0]
        self.assertEqual((passage['file'], passage['source_id'], passage['origin'],
                          passage['start']),
                         ('sources/handbook.txt', 'handbook', 'Supplied by the team', 29))
        source = worker_tools.collect(self.job)['sources'][0]
        self.assertTrue(source['offered'])
        self.assertEqual(source['path'].read_text(),
                         'Restart one batch at a time.\nKeep two instances running throughout.\n')


class QuestionTests(JobCase):
    def test_a_question_ends_the_job(self):
        tools = self.tools(inputs={'intake': 'Text.'}, artifacts=BLUEPRINTS)
        said = self.ok(tools.ask_person('  Which of the two products is this about?  '))
        self.assertIn('this job is over. Stop now', said)
        self.assertEqual(worker_tools.collect(self.job)['question'],
                         'Which of the two products is this about?')
        for outcome in (tools.read_input('intake'), tools.list_inputs(),
                        tools.submit_artifact('blueprint', BLUEPRINT),
                        tools.ask_person('And another thing?'),
                        tools.call('submit_review', {'text': 'Notes.'})):
            self.assertEqual(self.refused(outcome), worker_tools.ENDED)
        self.assertEqual(worker_tools.collect(self.job)['artifacts'], {})
        again = worker_tools.WorkerTools(self.job)
        self.assertEqual(self.refused(again.list_inputs()), worker_tools.ENDED)

    def test_a_job_that_nobody_can_answer_refuses_questions(self):
        said = self.refused(self.tools(finding='instance-min', ask=False).ask_person('Why?'))
        self.assertIn('Nobody can answer questions in this job', said)
        self.assertIsNone(worker_tools.collect(self.job)['question'])

    def test_an_empty_or_rambling_question_is_refused(self):
        tools = self.tools()
        self.assertEqual(self.refused(tools.ask_person(' ')), 'The question is empty.')
        self.assertIn('Ask one thing, in under 1,000', self.refused(tools.ask_person('x' * 1001)))
        self.assertEqual(self.ok(tools.list_inputs())[:8], 'This job')


class ServerTests(JobCase):
    def names(self, tools) -> list[str]:
        return [entry['name'] for entry in tools.offered()]

    def test_a_job_is_offered_only_the_tools_it_has_a_use_for(self):
        self.assertEqual(self.names(self.tools(artifacts=BLUEPRINTS)),
                         ['list_inputs', 'read_input', 'submit_artifact', 'submit_review',
                          'ask_person'])
        (self.job / 'job.json').unlink()
        self.assertEqual(self.names(self.tools(finding='instance-min', fetch=True, ask=False)),
                         ['list_inputs', 'read_input', 'save_source', 'read_source',
                          'search_source', 'submit_finding'])
        (self.job / 'job.json').unlink()
        supplied = self.tools(finding='instance-min', ask=False, sources=[
            {'title': 'Handbook', 'origin': 'Supplied', 'text': 'Words.', 'file': 'sources/h'}])
        self.assertEqual(self.names(supplied), ['list_inputs', 'read_input', 'read_source',
                                                'search_source', 'submit_finding'])

    def test_every_tool_is_described_and_is_a_method(self):
        tools = self.tools()
        for entry in worker_tools.TOOLS:
            self.assertTrue(getattr(getattr(tools, entry['name']), 'is_tool', False))
            self.assertTrue(entry['description'])
            self.assertLessEqual(set(entry['inputSchema']['required']),
                                 set(entry['inputSchema']['properties']))
        self.assertEqual(len(worker_tools.NAMES), 18)

    def answer(self, tools, method, params=None, ident=1):
        message = {'jsonrpc': '2.0', 'method': method, 'params': params or {}}
        if ident is not None:
            message['id'] = ident
        return worker_tools.answer(tools, message)

    def test_the_server_speaks_the_protocol_an_agent_expects(self):
        tools = self.tools(inputs={'intake': 'Text.'}, artifacts=BLUEPRINTS)
        hello = self.answer(tools, 'initialize', {'protocolVersion': '2025-06-18'})
        self.assertEqual(hello['result']['protocolVersion'], '2025-06-18')
        self.assertEqual(hello['result']['serverInfo']['name'], 'runner')
        self.assertEqual(hello['result']['capabilities'], {'tools': {}})
        self.assertIsNone(self.answer(tools, 'notifications/initialized', ident=None))
        listed = self.answer(tools, 'tools/list', ident='a')
        self.assertEqual(listed['id'], 'a')
        self.assertEqual([entry['name'] for entry in listed['result']['tools']],
                         self.names(tools))
        self.assertEqual(self.answer(tools, 'ping')['result'], {})
        self.assertEqual(self.answer(tools, 'resources/list')['result'], {'resources': []})
        self.assertEqual(self.answer(tools, 'sampling/createMessage')['error']['code'], -32601)
        self.assertIsNone(worker_tools.answer(tools, ['not', 'a', 'message']))

    def test_a_call_answers_with_text_and_says_when_it_was_refused(self):
        tools = self.tools(inputs={'intake': 'Text.'})
        read = self.answer(tools, 'tools/call', {'name': 'read_input',
                                                 'arguments': {'name': 'intake'}})
        self.assertEqual(read['result'], {'content': [{'type': 'text', 'text': 'Text.'}],
                                          'isError': False})
        missing = self.answer(tools, 'tools/call', {'name': 'read_input',
                                                    'arguments': {'name': 'notes'}})
        self.assertTrue(missing['result']['isError'])
        bare = self.answer(tools, 'tools/call', {'name': 'list_inputs'})
        self.assertFalse(bare['result']['isError'])

    def test_the_loop_skips_what_it_cannot_read_and_answers_the_rest(self):
        tools = self.tools()
        lines = ['not json\n', '\n', json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}),
                 json.dumps({'jsonrpc': '2.0', 'method': 'notifications/cancelled'}),
                 json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})]
        out = io.StringIO()
        worker_tools.serve(tools, lines, out)
        replies = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([reply['id'] for reply in replies], [1, 2])

    def test_the_command_really_starts_a_server_that_answers(self):
        worker_tools.prepare(self.job, inputs={'intake': 'Café owners.\n'})
        asked = '\n'.join(json.dumps(message) for message in (
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
             'params': {'name': 'read_input', 'arguments': {'name': 'intake'}}})) + '\n'
        done = subprocess.run(worker_tools.command(self.job), input=asked.encode('utf-8'),
                              capture_output=True, cwd=self.base, timeout=60,
                              env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
        self.assertEqual((done.returncode, done.stderr), (0, b''))
        replies = [json.loads(line) for line in done.stdout.decode('utf-8').splitlines()]
        self.assertEqual([reply['id'] for reply in replies], [1, 2])
        self.assertEqual(replies[1]['result']['content'][0]['text'], 'Café owners.\n')

    def test_the_server_will_not_start_for_a_folder_that_is_not_a_job(self):
        done = subprocess.run(worker_tools.command(self.job), input=b'', capture_output=True,
                              timeout=60)
        self.assertEqual(done.returncode, 2)
        self.assertIn(b'not a job folder', done.stderr)


if __name__ == '__main__':
    unittest.main()
