"""The agent adapters: the command and environment each builds, how each event stream is
read, time limits, and readiness. No test starts a real agent or touches the network: the
"agents" run here are small shell scripts that print events written by hand.
"""
import json
import os
import ssl
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401
from runner_support import BLUEPRINT, JobCase

from runner import agents, worker_tools
from runner.agents import Claude, Codex, Job, Limits, Outcome, Scripted
from workspace import WorkspaceError

SEARCH = 'rolling restart minimum instances'
PAGE = 'https://docs.example.com/restarts'


def use(ident: str, name: str, given: dict) -> dict:
    return {'type': 'assistant', 'message': {'role': 'assistant', 'content': [
        {'type': 'tool_use', 'id': ident, 'name': name, 'input': given}]}}


def result(ident: str, refused: bool = False) -> dict:
    block = {'type': 'tool_result', 'tool_use_id': ident,
             'content': [{'type': 'text', 'text': 'Answer.'}]}
    if refused:
        block['is_error'] = True
    return {'type': 'user', 'message': {'role': 'user', 'content': [block]}}


def call(ident: str, tool: str, given: dict, status: str | None = None) -> dict:
    item = {'id': ident, 'type': 'mcp_tool_call', 'server': 'runner', 'tool': tool,
            'arguments': given, 'result': None, 'error': None,
            'status': status or 'in_progress'}
    return {'type': 'item.completed' if status else 'item.started', 'item': item}


FINDING = {'item': 'instance-min', 'status': 'supported', 'summary': 'Two instances.'}
CLAUDE_STREAM = [
    {'type': 'system', 'subtype': 'init', 'model': 'claude-test-1',
     'tools': ['WebSearch', 'mcp__runner__save_source'],
     'mcp_servers': [{'name': 'runner', 'status': 'connected'}]},
    {'type': 'system', 'subtype': 'thinking_tokens', 'estimated_tokens': 50},
    {'type': 'system', 'subtype': 'thinking_tokens', 'estimated_tokens': 120},
    use('toolu_1', 'WebSearch', {'query': SEARCH}),
    result('toolu_1'),
    {'type': 'rate_limit_event', 'rate_limit_info': {'status': 'allowed'}},
    use('toolu_2', 'mcp__runner__save_source', {'url': PAGE}),
    result('toolu_2'),
    use('toolu_3', 'mcp__runner__submit_finding', FINDING),
    result('toolu_3', refused=True),
    use('toolu_4', 'mcp__runner__submit_finding', FINDING),
    result('toolu_4'),
    {'type': 'assistant', 'message': {'role': 'assistant', 'content': [
        {'type': 'text', 'text': 'The finding was accepted.'}]}},
    {'type': 'result', 'subtype': 'success', 'is_error': False, 'num_turns': 6,
     'result': 'The finding for instance-min was accepted.', 'total_cost_usd': 0.3197,
     'usage': {'input_tokens': 10, 'cache_creation_input_tokens': 31625,
               'cache_read_input_tokens': 90806, 'output_tokens': 2423}},
]
CLAUDE_LINES = ['Started on claude-test-1', 'Thinking', f'Searching the web: {SEARCH}',
                f'Saving a source: {PAGE}', 'Handing back the finding for instance-min',
                'The finding was sent back with problems to fix',
                'Handing back the finding for instance-min', 'The finding was accepted']
CODEX_STREAM = [
    {'type': 'thread.started', 'thread_id': 'thread-1'},
    {'type': 'turn.started'},
    {'type': 'item.completed', 'item': {'id': 'item_0', 'type': 'agent_message',
                                        'text': 'I will look for the documentation.'}},
    {'type': 'item.started', 'item': {'id': 'ws_1', 'type': 'web_search', 'query': '',
                                      'action': {'type': 'other'}}},
    {'type': 'item.completed', 'item': {'id': 'ws_1', 'type': 'web_search', 'query': SEARCH,
                                        'action': {'type': 'search', 'query': SEARCH}}},
    call('item_1', 'save_source', {'url': PAGE}),
    call('item_1', 'save_source', {'url': PAGE}, 'completed'),
    call('item_2', 'submit_finding', FINDING),
    call('item_2', 'submit_finding', FINDING, 'failed'),
    call('item_3', 'submit_finding', FINDING),
    call('item_3', 'submit_finding', FINDING, 'completed'),
    {'type': 'item.completed', 'item': {'id': 'item_4', 'type': 'agent_message',
                                        'text': 'The finding was accepted.'}},
    {'type': 'turn.completed', 'usage': {'input_tokens': 189411, 'cached_input_tokens': 151552,
                                         'output_tokens': 932, 'reasoning_output_tokens': 0}},
]
CODEX_LINES = ['Started', f'Searching the web: {SEARCH}', f'Saving a source: {PAGE}',
               'Handing back the finding for instance-min',
               'The finding was sent back with problems to fix',
               'Handing back the finding for instance-min', 'The finding was accepted']
RECORDS = """pwd > "$FAKE_OUT/cwd"
printf '%s\\n' "$@" > "$FAKE_OUT/args"
echo "$TMPDIR" > "$FAKE_OUT/tmpdir"
env > "$FAKE_OUT/env"
cat > "$FAKE_OUT/stdin"
"""


def gone(pid: int) -> bool:
    """True when a process has ended, whether or not anything has collected it yet."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    try:
        state = Path(f'/proc/{pid}/stat').read_text().rpartition(')')[2].split()[0]
    except (OSError, IndexError):
        return False
    return state == 'Z'


def lines(reader, stream) -> list[str]:
    return [line for event in stream for line in reader.feed(event)]


class AgentCase(JobCase):
    """A job in a temporary folder, with the rule against shared temporary folders lifted
    so that a pretend agent can be run there."""

    def setUp(self):
        super().setUp()
        self.out = self.base / 'out'
        self.out.mkdir()
        patcher = mock.patch.dict(os.environ, {'FAKE_OUT': str(self.out)})
        patcher.start()
        self.addCleanup(patcher.stop)
        allowed = mock.patch.object(agents, 'shared_temporary', return_value=[])
        allowed.start()
        self.addCleanup(allowed.stop)

    def make(self, profile: str = 'write', **changes) -> Job:
        self.job.mkdir(exist_ok=True)
        given = {'guidance': '# How to do the job\n', 'task': 'Draft the blueprint.\n',
                 'folder': self.job, 'profile': profile,
                 'tools': ('/usr/bin/python3', '-I', '/opt/runner/worker_tools.py', '--job',
                           str(self.job)), **changes}
        return Job(**given)

    def program(self, body: str, stream=None) -> str:
        """A shell script standing in for an agent. It prints `stream` where the body
        says `cat "$FAKE_OUT/events"`."""
        if stream is not None:
            (self.out / 'events').write_text(
                ''.join(json.dumps(event) + '\n' for event in stream))
        path = self.base / 'pretend-agent'
        path.write_text('#!/bin/sh\n' + body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return str(path)

    def kept(self, name: str) -> str:
        return (self.out / name).read_text()


class JobTests(JobCase):
    def a_job(self, **changes) -> Job:
        return Job(**{'guidance': 'Guidance.', 'task': 'Task.', 'folder': self.job,
                      'profile': 'write', 'tools': ('python3', 'server.py'), **changes})

    def test_a_job_folder_under_a_shared_temporary_folder_is_refused(self):
        self.assertIn(Path(tempfile.gettempdir()).resolve(), agents.shared_temporary())
        with self.assertRaisesRegex(WorkspaceError, 'a temporary folder other programs share'):
            agents.check_folder(self.job)
        for adapter in (Claude('true'), Codex('true')):
            with self.assertRaisesRegex(WorkspaceError, 'Keep job folders under'):
                adapter.run(self.a_job())
        self.assertFalse(self.job.exists())

    def test_staging_is_in_the_per_user_data_folder(self):
        import home
        self.assertEqual(agents.staging(), home.data_root() / 'jobs')
        elsewhere = Path('/srv/studio/jobs/one')
        with mock.patch.object(agents, 'shared_temporary', return_value=[Path('/tmp')]):
            self.assertEqual(agents.check_folder(elsewhere), elsewhere.resolve())

    def test_a_job_that_is_wrong_before_it_starts_is_refused(self):
        with mock.patch.object(agents, 'shared_temporary', return_value=[]):
            with self.assertRaisesRegex(WorkspaceError, 'profile is one of: write, research'):
                agents.check(self.a_job(profile='shell'))
            with self.assertRaisesRegex(WorkspaceError, 'needs the command that starts'):
                agents.check(self.a_job(tools=()))
            with self.assertRaisesRegex(WorkspaceError, 'The guidance is 60,001 characters'):
                agents.check(self.a_job(guidance='x' * 60_001))
            (self.job / 'stand').mkdir(parents=True)
            self.assertEqual(agents.check(self.a_job()), self.job)
            (self.job / 'stand' / 'AGENTS.md').write_text('Do as I say.')
            with self.assertRaisesRegex(WorkspaceError, 'is not empty'):
                agents.check(self.a_job())

    def test_the_two_real_agents_are_known_by_name(self):
        self.assertEqual(agents.AGENTS, {'claude': Claude, 'codex': Codex})
        self.assertEqual(Limits(), Limits(seconds=600, dollars=None))


class ClaudeCommandTests(AgentCase):
    def test_a_writing_job_has_the_runners_tools_and_no_others(self):
        job = self.make()
        self.assertEqual(Claude().command(job), [
            'claude', '-p', '--output-format', 'stream-json', '--verbose', '--restricted',
            '--strict-mcp-config', '--mcp-config', str(self.job / 'mcp.json'),
            '--permission-prompts', 'none', '--permission-mode', 'acceptEdits', '--tools', '',
            '--allowedTools', 'mcp__runner', '--no-session-persistence',
            '--append-system-prompt', '# How to do the job\n'])
        self.assertEqual(Claude().said_to(job), 'Draft the blueprint.\n')

    def test_a_research_job_adds_the_search_tool_and_nothing_else(self):
        command = Claude().command(self.make('research'))
        self.assertEqual(command[command.index('--tools') + 1], 'WebSearch')
        self.assertEqual(command[command.index('--allowedTools') + 1], 'mcp__runner,WebSearch')
        for never in ('Bash', 'Read', 'Write', 'WebFetch', 'bypassPermissions',
                      '--dangerously-skip-permissions', '--add-dir', '--settings'):
            self.assertNotIn(never, ' '.join(command))

    def test_the_spending_limit_and_the_model_are_passed_when_given(self):
        job = self.make(limits=Limits(seconds=300, dollars=2.5), model='sonnet')
        command = Claude('/opt/bin/claude').command(job)
        self.assertEqual(command[0], '/opt/bin/claude')
        self.assertEqual(command[-4:], ['--max-budget-usd', '2.5', '--model', 'sonnet'])

    def test_the_only_mcp_server_is_the_jobs_own_tools(self):
        job = self.make()
        Claude().command(job)
        self.assertEqual(json.loads((self.job / 'mcp.json').read_text()), {'mcpServers': {
            'runner': {'command': '/usr/bin/python3',
                       'args': ['-I', '/opt/runner/worker_tools.py', '--job', str(self.job)]}}})

    def test_nothing_from_another_claude_session_is_passed_on(self):
        mine = {'CLAUDECODE': '1', 'CLAUDE_CODE_ENTRYPOINT': 'cli', 'ANTHROPIC_API_KEY': 'k',
                'CLAUDE_CONFIG_DIR': '/somewhere', 'ANTHROPIC_BASE_URL': 'https://example.com',
                'EDITOR': 'vi', 'TMPDIR': '/tmp/shared'}
        with mock.patch.dict(os.environ, mine):
            env = Claude().environment(self.make())
            passed = Codex().environment(self.make())
        self.assertEqual([name for name in env if name.startswith(('CLAUDE', 'ANTHROPIC'))], [])
        self.assertEqual((env['EDITOR'], env['PATH']), ('vi', os.environ['PATH']))
        self.assertEqual(env['TMPDIR'], str(self.job / 'tmp'))
        self.assertEqual((passed['TMPDIR'], passed['EDITOR']), (str(self.job / 'tmp'), 'vi'))


class CodexCommandTests(AgentCase):
    def test_a_writing_job_has_everything_switched_off_but_the_runners_tools(self):
        job = self.make()
        off = [part for feature in agents.CODEX_OFF for part in ('--disable', feature)]
        self.assertEqual(Codex().command(job), [
            'codex', 'exec', '--json', '--cd', str(self.job / 'stand'),
            '--sandbox', 'workspace-write', '--ignore-user-config', '--ignore-rules',
            '--skip-git-repo-check', '--ephemeral', '-o', str(self.job / 'last-message.txt'),
            *off,
            '-c', 'project_doc_max_bytes=0',
            '-c', 'web_search="disabled"',
            '-c', 'mcp_servers.runner.command="/usr/bin/python3"',
            '-c', 'mcp_servers.runner.args=["-I", "/opt/runner/worker_tools.py", "--job", '
                  f'"{self.job}"]',
            '-c', 'mcp_servers.runner.default_tools_approval_mode="approve"',
            '-'])
        for feature in ('shell_tool', 'unified_exec', 'apps', 'plugins', 'browser_use',
                        'computer_use', 'image_generation', 'multi_agent', 'hooks',
                        'skill_search'):
            self.assertIn(feature, agents.CODEX_OFF)

    def test_a_research_job_turns_the_web_search_on(self):
        command = Codex().command(self.make('research', model='gpt-test'))
        self.assertIn('web_search="live"', command)
        self.assertNotIn('web_search="disabled"', command)
        self.assertEqual(command[-3:], ['-m', 'gpt-test', '-'])
        for never in ('--dangerously-bypass-approvals-and-sandbox', 'danger-full-access',
                      '--enable', '--add-dir'):
            self.assertNotIn(never, command)

    def test_the_guidance_and_the_job_go_in_as_one_prompt(self):
        self.assertEqual(Codex().said_to(self.make()),
                         'Instructions for this job:\n\n# How to do the job\n\n\nThe job:\n\n'
                         'Draft the blueprint.\n')

    def test_a_path_with_awkward_characters_is_still_valid_toml(self):
        self.assertEqual(agents._toml('C:\\Program Files\\py "3"\\caf\u00e9'),
                         '"C:\\\\Program Files\\\\py \\"3\\"\\\\caf\u00e9"')


class ClaudeEventTests(unittest.TestCase):
    def read(self, *events):
        reader = agents.ClaudeEvents()
        return reader, lines(reader, events)

    def test_a_whole_run_is_told_in_plain_lines(self):
        reader, said = self.read(*CLAUDE_STREAM)
        self.assertEqual(said, CLAUDE_LINES[:2] + ['Thinking'] + CLAUDE_LINES[2:])
        self.assertEqual((reader.ended, reader.reason), (True, None))
        self.assertEqual(reader.text, 'The finding for instance-min was accepted.')
        self.assertEqual(reader.cost, 0.3197)
        self.assertEqual(reader.tokens, {'input': 122441, 'cached': 90806, 'output': 2423})

    def test_each_worker_tool_has_its_own_line(self):
        said = self.read(
            use('1', 'mcp__runner__list_inputs', {}),
            use('2', 'mcp__runner__read_input', {'name': 'intake', 'part': 2}),
            use('3', 'mcp__runner__submit_artifact', {'name': 'blueprint@301', 'text': '…'}),
            result('3', refused=True), use('4', 'mcp__runner__submit_artifact', {'name': 'x'}),
            result('4'), use('5', 'mcp__runner__submit_review', {'text': 'Notes.'}),
            use('6', 'mcp__runner__read_source', {'source_id': 's2', 'offset': 100}),
            use('7', 'mcp__runner__search_source', {'source_id': 's2', 'query': 'batch'}),
            use('8', 'mcp__runner__save_source', {'url': PAGE}), result('8', refused=True),
            use('9', 'mcp__runner__ask_person', {'question': 'Which product?'}),
            use('10', 'mcp__other__thing', {}), result('10', refused=True))[1]
        self.assertEqual(said, [
            'Looking at what it was given', 'Reading intake', 'Handing back blueprint@301',
            'The draft was sent back with problems to fix', 'Handing back x',
            'The draft was accepted', 'Writing its own notes on the draft',
            'Reading saved source s2', 'Searching s2 for "batch"', f'Saving a source: {PAGE}',
            'That source could not be saved', 'Asking a question', 'Using mcp__other__thing',
            'mcp__other__thing was refused'])

    def test_a_long_line_is_cut_short(self):
        said = self.read(use('1', 'WebSearch', {'query': 'rolling restart ' * 40}))[1][0]
        self.assertEqual(len(said), 140)
        self.assertTrue(said.endswith('…'))

    def test_a_refused_built_in_tool_and_a_usage_limit_are_said(self):
        said = self.read(
            {'type': 'system', 'subtype': 'permission_denied', 'tool_name': 'Bash'},
            {'type': 'rate_limit_event', 'rate_limit_info': {'status': 'rejected'}},
            {'type': 'rate_limit_event', 'rate_limit_info': {'status': 'allowed_warning'}},
            {'type': 'user', 'message': {'role': 'user', 'content': 'plain text'}},
            {'type': 'something_new', 'detail': 1})[1]
        self.assertEqual(said, ['Was refused the use of Bash',
                                "The account's usage limit: rejected"])

    def ending(self, **fields):
        return self.read({'type': 'result', 'is_error': True, 'result': '', **fields})[0]

    def test_reaching_the_spending_limit_is_a_limit(self):
        reader = self.ending(subtype='error_max_budget_usd', total_cost_usd=2.01)
        self.assertEqual((reader.reason, reader.detail, reader.cost),
                         ('limit', 'its spending limit was reached', 2.01))
        self.assertEqual(self.ending(subtype='error_max_turns').reason, 'limit')
        self.assertEqual(self.ending(subtype='success', api_error_status=429,
                                     result='Usage limit reached').reason, 'limit')

    def test_not_being_signed_in_is_unavailable(self):
        reader = self.ending(subtype='success', api_error_status=401,
                             result='Invalid API key · Please run /login')
        self.assertEqual((reader.reason, reader.detail),
                         ('unavailable', 'Invalid API key · Please run /login'))
        self.assertEqual(self.ending(subtype='success', result='Not logged in').reason,
                         'unavailable')

    def test_any_other_error_is_a_failure(self):
        reader = self.ending(subtype='error_during_execution')
        self.assertEqual((reader.reason, reader.detail),
                         ('failed', 'it failed while it was working'))
        self.assertEqual(self.ending(subtype='success', api_error_status=500,
                                     result='API Error: 500').reason, 'failed')


class CodexEventTests(unittest.TestCase):
    def read(self, *events):
        reader = agents.CodexEvents()
        return reader, lines(reader, events)

    def test_a_whole_run_is_told_in_plain_lines(self):
        reader, said = self.read(*CODEX_STREAM)
        self.assertEqual(said, CODEX_LINES)
        self.assertEqual((reader.turns, reader.failure), (1, None))
        self.assertEqual(reader.text, 'The finding was accepted.')
        self.assertEqual(reader.tokens, {'input': 189411, 'cached': 151552, 'output': 932})
        self.assertIsNone(reader.cost)

    def test_a_service_that_cannot_be_reached_is_told_as_it_happens(self):
        reader, said = self.read(
            {'type': 'thread.started', 'thread_id': 't'}, {'type': 'turn.started'},
            {'type': 'error', 'message': 'Reconnecting... 2/5 (workspace routing discovery '
                                         'failed)'},
            {'type': 'item.completed', 'item': {'id': 'item_0', 'type': 'error', 'message':
                                                'Falling back from WebSockets to HTTPS.'}},
            {'type': 'error', 'message': 'workspace routing discovery failed'},
            {'type': 'turn.failed', 'error': {'message': 'workspace routing discovery failed'}})
        self.assertEqual(said, ['Started', 'Reconnecting',
                                'Codex said: Falling back from WebSockets to HTTPS.',
                                'Codex said: workspace routing discovery failed'])
        self.assertEqual((reader.turns, reader.failure),
                         (0, 'workspace routing discovery failed'))
        self.assertEqual(agents.classify(reader.failure), 'unavailable')

    def test_other_items_are_told_or_passed_over(self):
        said = self.read(
            {'type': 'item.completed', 'item': {'type': 'reasoning', 'text': 'Hm.'}},
            {'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'ls'}},
            {'type': 'item.started', 'item': {'type': 'mcp_tool_call', 'server': 'codex',
                                              'tool': 'list_mcp_resources', 'arguments': {}}},
            {'type': 'item.completed', 'item': {'type': 'file_change'}},
            {'type': 'item.completed', 'item': None}, {'type': 'something.new'})[1]
        self.assertEqual(said, ['Thinking', 'Ran a command, which a worker should not be able '
                                'to do', 'Using list_mcp_resources'])

    def test_usage_adds_up_over_turns(self):
        usage = {'input_tokens': 100, 'cached_input_tokens': 40, 'output_tokens': 7}
        reader = self.read({'type': 'turn.completed', 'usage': usage},
                           {'type': 'turn.completed', 'usage': usage},
                           {'type': 'turn.completed'})[0]
        self.assertEqual((reader.turns, reader.tokens),
                         (3, {'input': 200, 'cached': 80, 'output': 14}))

    def test_why_an_agent_stopped_is_read_from_its_own_words(self):
        for said, reason in (('stream error: error sending request for url', 'unavailable'),
                             ('401 Unauthorized', 'unavailable'),
                             ("You've hit your usage limit.", 'limit'),
                             ('Rate limit reached for requests', 'limit'),
                             ('the model returned an empty response', 'failed')):
            self.assertEqual(agents.classify(said), reason, said)


class RunTests(AgentCase):
    def test_a_claude_run_is_started_as_built_and_its_stream_is_kept_and_told(self):
        program = self.program(RECORDS + 'cat "$FAKE_OUT/events"\necho "a note" >&2\n',
                               CLAUDE_STREAM)
        said = []
        with mock.patch.dict(os.environ, {'CLAUDE_CODE_ENTRYPOINT': 'cli',
                                          'ANTHROPIC_API_KEY': 'not-passed-on'}):
            outcome = Claude(program).run(self.make('research'), said.append)
        self.assertEqual((outcome.finished, outcome.reason, outcome.detail), (True, None, ''))
        self.assertEqual(outcome.text, 'The finding for instance-min was accepted.')
        self.assertEqual((outcome.cost, outcome.tokens['output']), (0.3197, 2423))
        self.assertEqual(said, CLAUDE_LINES)
        self.assertEqual(outcome.events, self.job / 'events.jsonl')
        self.assertEqual([json.loads(line) for line in outcome.events.read_text().splitlines()],
                         CLAUDE_STREAM)
        self.assertEqual((self.job / 'stderr.txt').read_text(), 'a note\n')
        self.assertEqual(Path(self.kept('cwd').strip()).resolve(), self.job / 'stand')
        self.assertEqual(self.kept('tmpdir').strip(), str(self.job / 'tmp'))
        self.assertTrue((self.job / 'tmp').is_dir())
        self.assertEqual(list((self.job / 'stand').iterdir()), [])
        self.assertEqual(self.kept('stdin'), 'Draft the blueprint.\n')
        passed = self.kept('env')
        self.assertNotIn('CLAUDE_CODE_ENTRYPOINT', passed)
        self.assertNotIn('not-passed-on', passed)
        self.assertEqual(self.kept('args').split('\n')[:3], ['-p', '--output-format',
                                                             'stream-json'])
        self.assertGreaterEqual(outcome.seconds, 0)

    def test_a_codex_run_takes_its_last_message_from_the_file_it_writes(self):
        body = ('out=""\nfor arg in "$@"; do\n  if [ "$previous" = "-o" ]; then out="$arg"; fi\n'
                '  previous="$arg"\ndone\n' + RECORDS + 'cat "$FAKE_OUT/events"\n'
                'printf "Accepted: one supported finding." > "$out"\n')
        said = []
        outcome = Codex(self.program(body, CODEX_STREAM)).run(self.make('research'),
                                                              said.append)
        self.assertEqual((outcome.finished, outcome.reason), (True, None))
        self.assertEqual(outcome.text, 'Accepted: one supported finding.')
        self.assertEqual((outcome.cost, outcome.tokens),
                         (None, {'input': 189411, 'cached': 151552, 'output': 932}))
        self.assertEqual(said, CODEX_LINES)
        self.assertTrue(self.kept('stdin').startswith('Instructions for this job:\n\n# How'))
        self.assertEqual(Path(self.kept('cwd').strip()).resolve(), self.job / 'stand')
        self.assertEqual(self.kept('args').split('\n')[:2], ['exec', '--json'])

    def test_a_run_over_its_time_limit_is_stopped_with_everything_it_started(self):
        body = ('sleep 60 &\necho $! > "$FAKE_OUT/child"\n'
                'echo \'{"type":"system","subtype":"init","model":"m"}\'\nsleep 60\n')
        said = []
        started = time.monotonic()
        outcome = Claude(self.program(body)).run(self.make(limits=Limits(seconds=1)),
                                                 said.append)
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual((outcome.finished, outcome.reason), (False, 'timeout'))
        self.assertEqual(outcome.detail, 'It did not finish in 1 seconds, so it was stopped.')
        self.assertEqual(said, ['Started on m'])
        self.assertIn('"init"', outcome.events.read_text())
        child = int(self.kept('child'))
        for _ in range(100):
            if gone(child):
                break
            time.sleep(0.05)
        else:
            self.fail('What the worker started was left running.')

    def test_an_agent_that_is_not_installed_is_unavailable(self):
        outcome = Claude('no-such-agent-anywhere').run(self.make())
        self.assertEqual((outcome.finished, outcome.reason), (False, 'unavailable'))
        self.assertEqual(outcome.detail, 'Claude Code is not installed on this computer.')
        self.assertFalse((self.job / 'stand').exists())

    def test_an_agent_that_exits_without_a_result_has_failed(self):
        outcome = Claude(self.program('cat > /dev/null\necho "fatal: it broke" >&2\nexit 3\n')
                         ).run(self.make())
        self.assertEqual((outcome.finished, outcome.reason), (False, 'failed'))
        self.assertEqual(outcome.detail, 'It stopped without finishing: fatal: it broke')
        silent = self.base / 'second'
        outcome = Claude(self.program('cat > /dev/null\nexit 0\n')).run(self.make(folder=silent))
        self.assertEqual(outcome.detail, 'It stopped without finishing: it ended with exit '
                         'code 0 and no result')

    def test_a_claude_run_that_ends_in_an_error_says_which(self):
        stream = [CLAUDE_STREAM[0], {'type': 'result', 'subtype': 'error_max_budget_usd',
                                     'is_error': True, 'total_cost_usd': 1.02}]
        program = self.program('cat > /dev/null\ncat "$FAKE_OUT/events"\nexit 1\n', stream)
        outcome = Claude(program).run(self.make(limits=Limits(dollars=1.0)))
        self.assertEqual((outcome.finished, outcome.reason, outcome.cost), (False, 'limit', 1.02))
        self.assertEqual(outcome.detail, 'It stopped without finishing: its spending limit '
                         'was reached')

    def test_a_codex_run_that_cannot_reach_its_service_is_unavailable(self):
        stream = [{'type': 'thread.started', 'thread_id': 't'}, {'type': 'turn.started'},
                  {'type': 'turn.failed', 'error': {'message': 'stream disconnected'}}]
        body = ('cat > /dev/null\ncat "$FAKE_OUT/events"\n'
                'echo "ERROR: Connection failed: error sending request" >&2\nexit 1\n')
        outcome = Codex(self.program(body, stream)).run(self.make())
        self.assertEqual((outcome.finished, outcome.reason), (False, 'unavailable'))
        self.assertEqual(outcome.detail, 'It stopped without finishing: stream disconnected')
        self.assertEqual(outcome.text, '')

    def test_a_codex_run_that_never_finishes_a_turn_has_failed(self):
        outcome = Codex(self.program('cat > /dev/null\n', [CODEX_STREAM[0]])).run(self.make())
        self.assertEqual((outcome.finished, outcome.reason), (False, 'failed'))
        self.assertIn('exit code 0 before finishing a turn', outcome.detail)

    def test_output_that_is_not_json_is_kept_but_not_read(self):
        program = self.program('cat > /dev/null\necho "warming up"\ncat "$FAKE_OUT/events"\n',
                               CLAUDE_STREAM[-1:])
        outcome = Claude(program).run(self.make())
        self.assertTrue(outcome.finished)
        self.assertTrue(outcome.events.read_text().startswith('warming up\n'))


class SuperviseTests(JobCase):
    def run_python(self, code: str, stdin: str = '', seconds: float = 30):
        printed = []
        found = agents.supervise([sys.executable, '-c', code], self.base, dict(os.environ),
                                 stdin, seconds, self.base / 'errors.txt', printed.append)
        return found, printed

    def test_each_line_is_passed_on_and_the_exit_code_returned(self):
        found, printed = self.run_python(
            'import sys\nprint(sys.stdin.read().upper())\nprint("two")\n'
            'print("oops", file=sys.stderr)\nsys.exit(4)', 'one')
        self.assertEqual((found, printed), ((4, False), [b'ONE\n', b'two\n']))
        self.assertEqual((self.base / 'errors.txt').read_text(), 'oops\n')

    def test_a_long_task_does_not_block_a_command_that_is_slow_to_read(self):
        found, printed = self.run_python(
            'import sys, time\ntime.sleep(0.3)\nprint(len(sys.stdin.read()))', 'x' * 2_000_000)
        self.assertEqual((found, printed), ((0, False), [b'2000000\n']))

    def test_a_command_that_never_reads_its_task_still_ends(self):
        found, _ = self.run_python('print("done")', 'x' * 2_000_000)
        self.assertEqual(found, (0, False))

    def test_a_command_past_its_limit_is_killed(self):
        started = time.monotonic()
        (code, late), printed = self.run_python(
            'import time\nprint("started", flush=True)\ntime.sleep(60)', seconds=0.5)
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual((late, printed), (True, [b'started\n']))
        self.assertLess(code, 0)

    def test_a_caller_that_fails_does_not_leave_the_command_running(self):
        def broken(line):
            raise RuntimeError('the caller broke')

        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, 'the caller broke'):
            agents.supervise([sys.executable, '-c',
                              'import time\nprint("x", flush=True)\ntime.sleep(60)'],
                             self.base, dict(os.environ), '', 60, self.base / 'e.txt', broken)
        self.assertLess(time.monotonic() - started, 20)


class ScriptedTests(JobCase):
    def job_for(self, **prepared) -> Job:
        worker_tools.prepare(self.job, **prepared)
        return Job('Guidance.', 'Task.', self.job, 'write',
                   tuple(worker_tools.command(self.job)))

    def test_a_script_uses_the_jobs_tools_as_an_agent_would(self):
        def script(tools, job):
            text = tools.read_input('example')[1]
            first = tools.submit_artifact('blueprint', '# Not yet\n')
            second = tools.submit_artifact('blueprint', text)
            tools.submit_review('It follows the example closely.')
            return f'{first[0]} then {second[0]}, for a job called {job.task}'

        job = self.job_for(inputs={'example': BLUEPRINT},
                           artifacts={'blueprint': {'kind': 'blueprint',
                                                    'findings': helpers.FINDINGS}})
        said = []
        outcome = Scripted(script).run(job, said.append)
        self.assertEqual((outcome.finished, outcome.reason, outcome.events), (True, None, None))
        self.assertEqual(outcome.text, 'False then True, for a job called Task.')
        self.assertEqual(said, ['Reading example', 'Handing back blueprint',
                                'The draft was sent back with problems to fix',
                                'Handing back blueprint', 'The draft was accepted',
                                'Writing its own notes on the draft'])
        found = worker_tools.collect(self.job)
        self.assertEqual(found['artifacts']['blueprint']['text'], BLUEPRINT)
        self.assertEqual(found['review'], 'It follows the example closely.\n')
        self.assertEqual(len((self.job / 'tools.log').read_text().splitlines()), 4)

    def test_a_script_can_play_a_run_that_did_not_finish(self):
        late = Outcome(False, 'timeout', 'It did not finish in 600 seconds.', cost=0.4)
        self.assertIs(Scripted(lambda tools, job: late).run(self.job_for()), late)

    def test_a_script_that_returns_nothing_finished_with_nothing_to_say(self):
        def script(tools, job):
            tools.ask_person('Which of the two products is this about?')

        outcome = Scripted(script).run(self.job_for())
        self.assertEqual((outcome.finished, outcome.text), (True, ''))
        self.assertEqual(worker_tools.collect(self.job)['question'],
                         'Which of the two products is this about?')

    def test_it_is_always_ready_and_checks_the_profile(self):
        self.assertTrue(Scripted(None).ready().ready)
        job = self.job_for()
        with self.assertRaisesRegex(WorkspaceError, 'profile is one of'):
            Scripted(lambda tools, job: None).run(Job('g', 't', self.job, 'shell', job.tools))


class ReadinessTests(unittest.TestCase):
    def probe(self, adapter, answers: dict, installed: bool = True, blocked: str | None = None):
        """Ask an adapter whether it is ready, with every outside call pretended."""
        self.ran, self.reached = [], []

        def run(command, env=None, seconds=20):
            self.ran.append((command, env))
            return answers.get(' '.join(command[1:]), (None, ''))

        def reach(host):
            self.reached.append(host)
            return blocked

        which = (lambda program: f'/usr/local/bin/{program}') if installed else (lambda p: None)
        return adapter.ready(which=which, run=run, reach=reach)

    def test_an_agent_that_is_not_installed_is_not_asked_anything(self):
        found = self.probe(Claude(), {}, installed=False)
        self.assertEqual((found.ready, found.installed, found.signed_in, found.reachable),
                         (False, False, None, None))
        self.assertEqual(found.problem, 'Claude Code is not installed. Install it and sign '
                         'in, then try again.')
        self.assertEqual((self.ran, self.reached), ([], []))

    def test_claude_ready(self):
        found = self.probe(Claude(), {
            '--version': (0, '2.1.287 (Claude Code)'),
            'auth status --json': (0, json.dumps({'loggedIn': True, 'authMethod': 'x'}))})
        self.assertEqual(found, agents.Readiness('claude', True, True, True,
                                                 '2.1.287 (Claude Code)', None))
        self.assertTrue(found.ready)
        self.assertEqual(self.reached, ['api.anthropic.com'])

    def test_the_probe_never_starts_an_agent(self):
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'k', 'CLAUDECODE': '1'}):
            self.probe(Claude(), {})
            asked = self.ran
            self.probe(Codex(), {})
        self.assertEqual([command for command, _ in asked],
                         [['claude', '--version'], ['claude', 'auth', 'status', '--json']])
        self.assertEqual([command for command, _ in self.ran],
                         [['codex', '--version'], ['codex', 'login', 'status']])
        status_env = asked[1][1]
        self.assertEqual([name for name in status_env
                          if name.startswith(('CLAUDE', 'ANTHROPIC'))], [])

    def test_claude_signed_out(self):
        found = self.probe(Claude(), {'auth status --json': (1, '{"loggedIn": false}')})
        self.assertEqual((found.ready, found.signed_in, found.reachable), (False, False, True))
        self.assertEqual(found.problem, 'Claude Code is not signed in. Run claude auth login '
                         'in a terminal, then try again.')

    def test_signed_in_is_not_enough_when_the_network_blocks_the_agent(self):
        found = self.probe(Codex(), {'--version': (0, 'warning\ncodex-cli 0.162.1'),
                                     'login status': (0, 'Logged in using ChatGPT')},
                           blocked='chatgpt.com cannot be reached from this network (timed out)')
        self.assertEqual((found.ready, found.signed_in, found.reachable, found.version),
                         (False, True, False, 'codex-cli 0.162.1'))
        self.assertEqual(found.problem, 'Codex is signed in but cannot be used from this '
                         'network: chatgpt.com cannot be reached from this network (timed '
                         'out). Try another network.')
        self.assertEqual(self.reached, ['chatgpt.com'])

    def test_codex_signed_in_with_a_key_is_checked_against_the_other_service(self):
        found = self.probe(Codex(), {'login status': (0, 'Logged in using an API key - sk***')})
        self.assertTrue(found.ready)
        self.assertEqual(self.reached, ['api.openai.com'])

    def test_codex_signed_out(self):
        found = self.probe(Codex(), {'login status': (1, 'Not logged in')})
        self.assertEqual((found.ready, found.signed_in), (False, False))
        self.assertIn('Run codex login in a terminal', found.problem)

    def test_an_agent_that_cannot_be_asked_is_judged_by_whether_it_can_be_reached(self):
        found = self.probe(Claude(), {})
        self.assertEqual((found.ready, found.signed_in, found.reachable, found.version),
                         (True, None, True, None))
        found = self.probe(Claude(), {'auth status --json': (0, 'not json')})
        self.assertEqual((found.ready, found.signed_in), (True, True))

    def test_a_short_command_that_cannot_run_gives_no_answer(self):
        self.assertEqual(agents.ask(['no-such-agent-anywhere', '--version']), (None, ''))
        self.assertEqual(agents.ask([sys.executable, '-c', 'print("1.2.3")']), (0, '1.2.3'))


class ReachableTests(unittest.TestCase):
    def reach(self, connect=None, wrap=None):
        context = mock.Mock()
        if wrap:
            context.wrap_socket.side_effect = wrap
        with mock.patch.object(agents.urllib.request, 'getproxies', return_value={}), \
                mock.patch.object(agents.socket, 'create_connection',
                                  side_effect=connect) as made, \
                mock.patch.object(agents.ssl, 'create_default_context', return_value=context):
            return agents.reachable('service.example.com'), made, context

    def test_a_service_that_answers_with_a_good_certificate_is_reachable(self):
        found, made, context = self.reach()
        self.assertIsNone(found)
        self.assertEqual(made.call_args.args[0], ('service.example.com', 443))
        self.assertEqual(context.wrap_socket.call_args.kwargs,
                         {'server_hostname': 'service.example.com'})

    def test_a_connection_that_fails_says_so(self):
        found, _, _ = self.reach(connect=OSError('Network is unreachable'))
        self.assertEqual(found, 'service.example.com cannot be reached from this network '
                         '(Network is unreachable)')

    def test_an_intercepted_connection_is_told_apart(self):
        failure = ssl.SSLCertVerificationError('certificate verify failed')
        failure.verify_message = 'self-signed certificate in certificate chain'
        found, _, _ = self.reach(wrap=failure)
        self.assertEqual(found, 'the connection to service.example.com is being intercepted '
                         'on this network, or its certificate is not trusted here '
                         '(self-signed certificate in certificate chain)')


if __name__ == '__main__':
    unittest.main()
