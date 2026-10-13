"""The harness-research wrapper, against a stand-in for the command line. Neither Node nor
the installed skill is needed, and nothing touches the network.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers
from runner_support import PAGE, Web

import workspace
from runner import research, worker_tools
from workspace import WorkspaceError

SCRIPT = Path('scripts') / 'harness-research.mjs'
PLAN = {'topic': 'Rolling restarts', 'purpose': 'planning', 'scope': 'public-web',
        'sources': [], 'items': [
            {'id': 'instance-min', 'question': 'How many instances keep capacity?',
             'public_query': 'rolling restart minimum instances', 'claim': None},
            {'id': 'health-checks', 'question': 'What starts the next batch?',
             'public_query': None, 'claim': None}]}
SNAPSHOT = 'Rolling restarts\n\nCapacity holds only when more than one instance is running.\n'
QUOTE = 'Capacity holds only when more than one instance is running.'


def installed(folder: Path) -> Path:
    """A folder that looks like an installed harness-research."""
    (folder / 'scripts').mkdir(parents=True)
    (folder / SCRIPT).write_text('// the command line\n')
    return folder


class FindingTheRuntimeTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.home = Path(holder.name).resolve()
        patches = (mock.patch.dict(os.environ), mock.patch.object(Path, 'home',
                                                                  return_value=self.home))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        os.environ.pop(research.VARIABLE, None)

    def test_the_override_is_the_only_place_looked(self):
        installed(self.home / '.claude' / 'skills' / 'harness-research')
        chosen = installed(self.home / 'elsewhere')
        os.environ[research.VARIABLE] = str(chosen)
        self.assertEqual(research.find_runtime(), chosen)
        os.environ[research.VARIABLE] = str(self.home / 'nowhere')
        with self.assertRaisesRegex(WorkspaceError, 'HARNESS_RESEARCH_RUNTIME names .*nowhere, '
                                    'which does not hold harness-research'):
            research.find_runtime()

    def test_the_usual_install_locations_are_tried_in_turn(self):
        with self.assertRaisesRegex(WorkspaceError, 'The harness-research skill is not '
                                    'installed on this computer, so research cannot run'):
            research.find_runtime()
        linked = installed(self.home / '.agents' / 'skills' / 'harness-research')
        self.assertEqual(research.find_runtime(), linked)
        shared = installed(self.home / '.local' / 'share' / 'harness-research' / 'current')
        self.assertEqual(research.find_runtime(), shared)

    def test_links_are_followed_so_one_version_is_used_throughout(self):
        version = installed(self.home / 'Library' / 'Application Support' / 'Harness Research'
                            / 'versions' / '0.8.0')
        (version.parent.parent / 'current').symlink_to(Path('versions') / '0.8.0')
        skill = self.home / '.claude' / 'skills'
        skill.mkdir(parents=True)
        (skill / 'harness-research').symlink_to(version.parent.parent / 'current')
        self.assertEqual(research.find_runtime(), version)
        self.assertEqual(research.Research(run=lambda command, cwd=None: (0, '{}', '')).runtime,
                         version)

    def test_the_real_command_needs_node(self):
        os.environ[research.VARIABLE] = str(installed(self.home / 'runtime'))
        with mock.patch.object(research.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(WorkspaceError, 'needs Node.js 20 or newer'):
                research.Research()
        with mock.patch.object(research.shutil, 'which', return_value='/usr/bin/node'):
            self.assertEqual(research.Research().node, '/usr/bin/node')


class CommandTests(unittest.TestCase):
    """What is run, and how its answers and refusals are read."""

    def setUp(self):
        self.ran, self.answers, self.files = [], [], []
        self.research = research.Research(runtime=Path('/opt/harness-research'),
                                          run=self.pretend)

    def pretend(self, command, cwd=None):
        self.ran.append(command)
        if '--file' in command:
            path = Path(command[command.index('--file') + 1])
            self.files.append((path, path.read_text() if path.is_file() else None))
        return self.answers.pop(0) if self.answers else (0, '{"status": "in-progress"}\n', '')

    def test_plan_record_and_status_are_run_as_the_command_line_takes_them(self):
        script = '/opt/harness-research/scripts/harness-research.mjs'
        self.assertEqual(self.research.plan(Path('/t/rolling'), Path('/t/rolling/plan.json')),
                         {'status': 'in-progress'})
        self.research.plan(Path('/t/rolling'), Path('/t/rolling/plan.json'), allow_web=True)
        self.research.status(Path('/t/rolling'))
        self.assertEqual(self.ran, [
            ['node', script, 'plan', '--project', '/t/rolling', '--file', '/t/rolling/plan.json'],
            ['node', script, 'plan', '--project', '/t/rolling', '--file', '/t/rolling/plan.json',
             '--allow-web'],
            ['node', script, 'status', '--project', '/t/rolling']])

    def test_a_finding_is_handed_over_in_a_file_that_is_then_removed(self):
        finding = {'item': 'instance-min', 'status': 'insufficient', 'summary': 'Not said.',
                   'limits': 'One page.', 'evidence': [], 'extra': 'dropped'}
        self.research.record(Path('/t/rolling'), 'run-1', 'instance-min', finding)
        command = self.ran[0]
        path, text = self.files[0]
        self.assertEqual(command[2:], ['record', '--project', '/t/rolling', '--file', str(path),
                                       '--run', 'run-1', '--item', 'instance-min'])
        self.assertEqual(json.loads(text), {'status': 'insufficient', 'summary': 'Not said.',
                                            'limits': 'One page.', 'evidence': []})
        self.assertFalse(path.exists())

    def test_a_refusal_carries_the_one_line_the_command_gave(self):
        self.answers = [(1, '', 'Unknown research question.\n'),
                        (1, '', '\n(node:1) Warning: something\nResearch storage is busy; retry '
                         'after the current save.\n\n'), (1, '', '')]
        with self.assertRaises(research.Refused) as refused:
            self.research.status(Path('/t/rolling'))
        self.assertEqual(refused.exception.line, 'Unknown research question.')
        self.assertEqual(str(refused.exception),
                         'harness-research refused: Unknown research question.')
        self.assertFalse(refused.exception.busy)
        self.assertIsInstance(refused.exception, WorkspaceError)
        with self.assertRaises(research.Refused) as refused:
            self.research.status(Path('/t/rolling'))
        self.assertEqual(refused.exception.line,
                         'Research storage is busy; retry after the current save.')
        self.assertTrue(refused.exception.busy)
        with self.assertRaisesRegex(research.Refused, 'it ended with exit code 1'):
            self.research.status(Path('/t/rolling'))

    def test_a_finding_file_is_removed_even_when_the_command_refuses(self):
        self.answers = [(1, '', 'Unknown research question.\n')]
        with self.assertRaises(research.Refused):
            self.research.record(Path('/t'), 'run-1', 'nothing', {'status': 'supported'})
        self.assertFalse(self.files[0][0].exists())

    def test_an_answer_that_is_not_json_is_not_trusted(self):
        for answer in ('Usage: node scripts/harness-research.mjs ...', '[1, 2]', ''):
            self.answers = [(0, answer, '')]
            with self.assertRaisesRegex(WorkspaceError, 'something other than the JSON'):
                self.research.status(Path('/t/rolling'))

    def test_the_version_is_read_from_what_the_command_prints(self):
        self.answers = [(0, 'harness-research 0.8.0\n', '')]
        self.assertEqual(self.research.version(), '0.8.0')
        self.assertEqual(self.ran[0][2:], ['--version'])

    def test_a_command_that_hangs_or_cannot_start_is_a_refusal(self):
        self.assertEqual(research.run_command([sys.executable, '-c', 'print("ok")']),
                         (0, 'ok\n', ''))
        slow = subprocess.TimeoutExpired(['node'], research.TIMEOUT)
        with mock.patch.object(research.subprocess, 'run', side_effect=slow):
            with self.assertRaisesRegex(WorkspaceError, 'did not answer in 120 seconds'):
                research.run_command(['node'])
        with self.assertRaisesRegex(WorkspaceError, 'could not be started'):
            research.run_command(['no-such-program-anywhere'])


class StandInTests(helpers.TrainingCase):
    """The stand-in behaves as the real command line does for plan, record and status."""

    def setUp(self):
        super().setUp()
        self.research = research.stand_in()
        self.plan_file = self.write('.training-studio/research-plan.json', json.dumps(PLAN))
        self.write('sources/docs-example-com-0123456789ab.txt', SNAPSHOT)

    def finding(self, **changes) -> dict:
        start = SNAPSHOT.index(QUOTE)
        return {'status': 'supported', 'summary': 'Two instances keep capacity.',
                'limits': 'none', 'evidence': [{
                    'file': 'sources/docs-example-com-0123456789ab.txt',
                    'title': 'Rolling restarts', 'origin': 'https://docs.example.com/restarts',
                    'quote': QUOTE, 'start': start,
                    'locator': f'characters {start} to {start + len(QUOTE)}'}], **changes}

    def planned(self) -> str:
        return self.research.plan(self.root, self.plan_file)['run']

    def refusal(self, call, *args, **named) -> str:
        with self.assertRaises(research.Refused) as refused:
            call(*args, **named)
        return refused.exception.line

    def test_nothing_is_started_until_there_is_a_plan(self):
        status = self.research.status(self.root)
        self.assertEqual(status['status'], 'not-started')
        self.assertTrue(status['report'].endswith('.harness-research/research-report.md'))
        self.assertFalse((self.root / '.harness-research').exists())
        self.assertEqual(self.refusal(self.research.record, self.root, 'run', 'instance-min',
                                      self.finding()),
                         'No valid Harness research record; plan research first.')

    def test_a_plan_starts_a_run_with_every_question_pending(self):
        status = self.research.plan(self.root, self.plan_file)
        self.assertEqual((status['status'], status['pending'], status['completed'],
                          status['total'], status['unresolved'], status['staleItems']),
                         ('in-progress', ['instance-min', 'health-checks'], 0, 2, [], []))
        self.assertEqual(len(status['run']), 24)
        self.assertEqual((status['scope'], status['sourceGaps']), ('public-web', []))
        record = workspace.research_record(self.root)
        self.assertEqual((record['run'], record['owner'], record['results']),
                         (status['run'], 'harness-research', {}))
        self.assertEqual(workspace.findings_index(record),
                         {'instance-min': 'pending', 'health-checks': 'pending'})
        self.assertIn('Status: pending.', Path(status['report']).read_text())

    def test_the_same_plan_continues_its_run_and_a_changed_one_starts_another(self):
        run = self.planned()
        self.research.record(self.root, run, 'instance-min', self.finding())
        again = self.research.plan(self.root, self.plan_file)
        self.assertEqual((again['run'], again['completed']), (run, 1))
        longer = {**PLAN, 'items': PLAN['items'] + [{'id': 'rollback', 'question': 'How is a '
                                                     'failed restart rolled back?'}]}
        self.plan_file.write_text(json.dumps(longer))
        changed = self.research.plan(self.root, self.plan_file)
        self.assertNotEqual(changed['run'], run)
        self.assertEqual((changed['completed'], changed['total']), (0, 3))

    def test_findings_are_recorded_one_at_a_time_until_the_run_is_complete(self):
        run = self.planned()
        first = self.research.record(self.root, run, 'instance-min', self.finding())
        self.assertEqual((first['status'], first['completed'], first['pending']),
                         ('in-progress', 1, ['health-checks']))
        second = self.research.record(self.root, run, 'health-checks', self.finding(
            status='insufficient', summary='The page does not say.', evidence=[]))
        self.assertEqual((second['status'], second['completed'], second['pending'],
                          second['unresolved']), ('complete', 2, [], ['health-checks']))
        record = workspace.research_record(self.root)
        self.assertEqual(workspace.findings_index(record),
                         {'instance-min': 'supported', 'health-checks': 'insufficient'})
        kept = record['results']['instance-min']['evidence'][0]
        self.assertEqual(len(kept['sha256']), 64)
        report = Path(second['report']).read_text()
        self.assertIn(f'> {QUOTE}', report)
        self.assertIn('Unresolved: health-checks.', report)
        self.assertEqual(self.research.status(self.root), second)

    def test_the_core_keeps_and_approves_what_the_stand_in_wrote(self):
        workspace.init(self.root, 'Rolling restarts')
        self.write('intake.md', '# Intake\n')
        workspace.save(self.root, 'intake', built=True)
        workspace.approve(self.root, 'intake')
        workspace.save(self.root, 'research-plan', built=True)
        workspace.approve(self.root, 'research-plan')
        run = self.planned()
        self.research.record(self.root, run, 'instance-min', self.finding())
        workspace.save(self.root, 'research', built=True)
        approved = workspace.approve(self.root, 'research')
        self.assertEqual(approved['warnings'], ['Research questions still pending: '
                                                'health-checks'])
        summary = workspace.status(self.root)['research']
        self.assertEqual((summary['run'], summary['findings']),
                         (run, {'supported': 1, 'pending': 1}))

    def test_a_finding_for_the_wrong_run_or_question_is_refused(self):
        run = self.planned()
        self.assertEqual(self.refusal(self.research.record, self.root, 'another-run',
                                      'instance-min', self.finding()),
                         'Research run or content changed; refresh the plan before recording '
                         'results.')
        self.assertEqual(self.refusal(self.research.record, self.root, run, 'rollback',
                                      self.finding()), 'Unknown research question.')

    def test_a_finding_must_be_whole_and_quote_its_source_exactly(self):
        run = self.planned()
        passage = self.finding()['evidence'][0]
        for changes, line in (
                ({'status': 'proven'}, 'Result requires a supported/contradicted/insufficient/'
                 'unavailable status and up to 20 evidence passages.'),
                ({'evidence': [passage] * 21}, 'Result requires a supported/contradicted/'
                 'insufficient/unavailable status and up to 20 evidence passages.'),
                ({'summary': ' '}, 'Summary requires nonempty text (maximum 12000 characters).'),
                ({'limits': ''}, 'Coverage limits requires nonempty text (maximum 4000 '
                 'characters).'),
                ({'evidence': []}, 'Supported or contradicted findings require an inspected '
                 'source passage.'),
                ({'evidence': [{**passage, 'start': passage['start'] + 1}]},
                 'Evidence must quote the inspected source snapshot exactly.'),
                ({'evidence': [{**passage, 'start': '18'}]},
                 'Evidence must quote the inspected source snapshot exactly.'),
                ({'evidence': [{**passage, 'file': 'sources/missing.txt'}]},
                 'Research source is missing: sources/missing.txt'),
                ({'evidence': [{**passage, 'file': '../outside.txt'}]},
                 'Research file paths must be relative to the project.'),
                ({'evidence': [{**passage, 'title': ''}]},
                 'Source title requires nonempty text (maximum 4000 characters).'),
                ({'evidence': [{**passage, 'source_id': 'handbook'}]},
                 'Evidence must match its selected supplied document.')):
            with self.subTest(line):
                self.assertEqual(self.refusal(self.research.record, self.root, run,
                                              'instance-min', self.finding(**changes)), line)
        self.assertEqual(self.research.status(self.root)['completed'], 0)

    def test_a_source_that_changes_after_it_was_quoted_makes_the_research_stale(self):
        run = self.planned()
        self.research.record(self.root, run, 'instance-min', self.finding())
        self.write('sources/docs-example-com-0123456789ab.txt', SNAPSHOT + 'Edited later.\n')
        status = self.research.status(self.root)
        self.assertEqual((status['status'], status['staleItems']), ('stale', ['instance-min']))

    def test_a_save_in_progress_makes_the_command_busy(self):
        self.planned()
        lock = self.write('.harness-research/research.lock', '12345')
        with self.assertRaises(research.Refused) as refused:
            self.research.status(self.root)
        self.assertTrue(refused.exception.busy)
        lock.unlink()
        self.assertEqual(self.research.status(self.root)['status'], 'in-progress')

    def test_a_plan_the_command_would_not_take_is_refused_in_its_words(self):
        item = PLAN['items'][0]
        for changes, line in (
                ({'topic': ''}, 'Topic requires nonempty text (maximum 4000 characters).'),
                ({'scope': 'everything'}, 'Choose planning/fact-check and supplied-only/'
                 'public-web.'),
                ({'items': []}, 'Plan 1–30 focused research questions.'),
                ({'items': [item, item]}, 'Research question IDs must be unique, lowercase '
                 'identifiers.'),
                ({'items': [{**item, 'question': ''}]}, 'Question requires nonempty text '
                 '(maximum 4000 characters).'),
                ({'items': [{**item, 'public_query': 'see https://example.com'}]},
                 'Public queries require public-web scope and cannot contain URLs, paths or '
                 'emails.'),
                ({'scope': 'supplied-only'}, 'Public queries require public-web scope and '
                 'cannot contain URLs, paths or emails.')):
            with self.subTest(line):
                self.plan_file.write_text(json.dumps({**PLAN, **changes}))
                self.assertEqual(self.refusal(self.research.plan, self.root, self.plan_file),
                                 line)
        self.assertEqual(self.research.status(self.root)['status'], 'not-started')

    def test_supplied_only_research_quotes_only_the_chosen_documents(self):
        self.write('sources/handbook.txt', 'Keep two instances running throughout.\n')
        supplied = {**PLAN, 'scope': 'supplied-only', 'sources': [
            {'id': 'handbook', 'title': 'Operations handbook', 'origin': 'Supplied by the team',
             'file': 'sources/handbook.txt'},
            {'id': 'slides', 'title': 'Old slides', 'origin': 'Supplied by the team',
             'original_file': 'sources/handbook.txt', 'limits': 'Could not be read.'}],
            'items': [{**item, 'public_query': None} for item in PLAN['items']]}
        self.plan_file.write_text(json.dumps(supplied))
        status = self.research.plan(self.root, self.plan_file)
        self.assertEqual(status['sourceGaps'], [{'id': 'slides', 'title': 'Old slides',
                                                 'limits': 'Could not be read.'}])
        self.assertEqual(self.refusal(self.research.record, self.root, status['run'],
                                      'instance-min', self.finding()),
                         'Uploaded-sources-only evidence must come from a selected readable '
                         'document.')
        quote = 'Keep two instances running throughout.'
        own = {'file': 'sources/handbook.txt', 'title': 'Operations handbook',
               'origin': 'Supplied by the team', 'quote': quote, 'start': 0,
               'locator': 'characters 0 to 38', 'source_id': 'handbook'}
        done = self.research.record(self.root, status['run'], 'instance-min',
                                    self.finding(evidence=[own]))
        self.assertEqual(done['completed'], 1)
        self.plan_file.write_text(json.dumps(PLAN))
        self.assertEqual(self.refusal(self.research.plan, self.root, self.plan_file),
                         'Supplied-only research requires explicit permission before changing '
                         'to public-web scope.')
        self.assertEqual(self.research.plan(self.root, self.plan_file, allow_web=True)['scope'],
                         'public-web')

    def test_it_says_which_version_it_is_and_lists_its_calls(self):
        self.assertEqual(self.research.version(), '0.0.0-stand-in')
        self.research.status(self.root)
        self.assertEqual(self.research.run.calls, [['--version'],
                                                   ['status', '--project', str(self.root)]])
        self.assertEqual(self.research.run(['node', 'script', 'migrate'])[0], 1)
        self.plan_file.write_text('["not", "a", "plan"]')
        self.assertIn('list', self.refusal(self.research.plan, self.root, self.plan_file))

    def test_what_the_worker_tools_accept_the_command_records(self):
        """One question from end to end: a worker saves a page and hands back a finding,
        the sources are copied into the training, and the finding is recorded."""
        web, job = Web(), self.root.parent / 'job'
        url = web.page('https://docs.example.com/restarts', PAGE)
        worker_tools.prepare(job, finding='instance-min', fetch=True, ask=False)
        tools = worker_tools.WorkerTools(job, opener=web.opener, resolver=web.resolver)
        tools.save_source(url)
        typed = "more than one instance is running. The platform's health check decides"
        accepted = tools.submit_finding(
            'instance-min', 'supported', 'An app keeps capacity with two or more instances.',
            evidence=[{'source_id': 's1', 'quote': QUOTE}, {'source_id': 's1', 'quote': typed}])
        self.assertTrue(accepted[0], accepted[1])
        handed_back = worker_tools.collect(job)
        for source in handed_back['sources']:
            (self.root / source['file']).parent.mkdir(exist_ok=True)
            shutil.copyfile(source['path'], self.root / source['file'])
        status = self.research.record(self.root, self.planned(), 'instance-min',
                                      handed_back['finding'])
        self.assertEqual((status['completed'], status['unresolved']), (1, []))
        kept = workspace.research_record(self.root)['results']['instance-min']
        self.assertEqual((kept['status'], kept['limits'], len(kept['evidence'])),
                         ('supported', 'none', 2))
        self.assertIn('platform’s health\ncheck', kept['evidence'][1]['quote'])


if __name__ == '__main__':
    unittest.main()
