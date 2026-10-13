"""Start an agent as a confined worker for one job, and say how it went.

What a caller needs to know
---------------------------
    folder = agents.staging() / 'rolling-restarts-blueprint-1'
    worker_tools.prepare(folder, inputs={...}, artifacts={...})
    job = Job(guidance=briefs.guidance('blueprint'), task='...', folder=folder,
              profile='write', tools=worker_tools.command(folder),
              limits=Limits(seconds=600, dollars=2.0))
    outcome = Claude().run(job, activity=print)
    handed_back = worker_tools.collect(folder)

- One interface, three adapters: `Claude`, `Codex`, and `Scripted` for tests. Each has
  `run(job, activity=None) -> Outcome` and `ready() -> Readiness`. AGENTS maps the names a
  run record uses to the two real ones.
- A worker has no built-in tools: no shell, no file tools, no fetching. It has the worker
  tools the job's `tools` command serves and, under the `research` profile only, the agent's
  own web search. What it hands back is in the job's folder, never in its final text.
- `Job.folder` is the job's own folder and belongs to the runner. The worker stands in
  `folder/stand`, which is empty, and is given `folder/tmp` as its temporary folder. The
  event stream is kept in `folder/events.jsonl`, and what the agent wrote to standard error
  in `folder/stderr.txt`. A folder under a shared temporary folder is refused, because an
  agent's own sandbox lets it write there: use `staging()`.
- `run` never raises for something the agent did. It returns an Outcome whose `reason` is
  `timeout`, `limit`, `failed` or `unavailable`, with a sentence in `detail`. It raises
  WorkspaceError only for a job that is wrong before it starts.
- `activity` is called with one short plain line each time the worker does something.
- `ready()` says whether the agent is installed, signed in and reachable from this network.
  It never starts an agent. Being signed in is not enough: a network can block one agent.
- A Claude worker is not passed any environment variable that belongs to another Claude
  session (names starting CLAUDE or ANTHROPIC). The account's email address still reaches
  every Claude worker, and a Codex worker still sees the list of the person's installed
  skills and their global instruction file; milestone 0 records both.
"""
from __future__ import annotations

import base64
import http.client
import json
import os
import shutil
import signal
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
import home
from workspace import WorkspaceError

from runner import worker_tools

PROFILES = ('write', 'research')
REASONS = ('timeout', 'limit', 'failed', 'unavailable')
SERVER = 'runner'           # the name the worker tools are served under
CLAUDE_SEARCH = 'WebSearch'
GUIDANCE_LIMIT = 60_000     # characters; an operating system limits one argument's length
SOMEONE_ELSES = ('CLAUDE', 'ANTHROPIC')
# Codex features a worker must not have. The last two are its shell.
CODEX_OFF = ('apps', 'plugins', 'remote_plugin', 'plugin_sharing', 'browser_use',
             'browser_use_external', 'browser_use_full_cdp_access', 'computer_use',
             'in_app_browser', 'image_generation', 'multi_agent', 'hooks', 'skill_search',
             'tool_suggest', 'skill_mcp_dependency_install', 'worktrees', 'goals',
             'shell_tool', 'unified_exec')
# Words in an agent's own account of a failure that mean it could not be reached or is not
# signed in, and words that mean an account limit. A best effort: ready() is the real check.
UNREACHABLE = ('error sending request', 'connection failed', 'not logged in', 'unauthorized',
               'please run /login', 'invalid api key', 'routing discovery failed')
LIMITED = ('usage limit', 'rate limit', 'quota')
# How Claude names an ending that is not a success, in plain words.
CLAUDE_ENDINGS = {'error_max_budget_usd': 'its spending limit was reached',
                  'error_max_turns': 'it took more turns than a job may',
                  'error_during_execution': 'it failed while it was working'}


@dataclass(frozen=True)
class Limits:
    """How long a job may run, and how much it may spend where the agent can be told."""
    seconds: int = 600
    dollars: float | None = None


@dataclass(frozen=True)
class Job:
    """One bounded piece of work for one worker."""
    guidance: str               # how to do this kind of job: a brief
    task: str                   # this job in particular
    folder: Path                # the job's own folder; see the module docstring
    profile: str                # 'write', or 'research' which adds the agent's web search
    tools: Sequence[str]        # the command that starts the worker tools server
    limits: Limits = field(default_factory=Limits)
    model: str | None = None


@dataclass(frozen=True)
class Outcome:
    """How a job ended."""
    finished: bool
    reason: str | None = None   # one of REASONS when it did not finish
    detail: str = ''            # a sentence for a person when it did not finish
    text: str = ''              # the worker's last message
    cost: float | None = None   # dollars, where the agent reports it
    tokens: dict | None = None  # {'input', 'cached', 'output'}, where reported
    seconds: float = 0.0
    events: Path | None = None  # where the raw event stream was saved


@dataclass(frozen=True)
class Readiness:
    """Whether an agent can be used from this computer and this network, now."""
    agent: str
    installed: bool
    signed_in: bool | None = None   # None when it could not be asked
    reachable: bool | None = None   # None when it was not tried
    version: str | None = None
    problem: str | None = None      # what to put right; None when ready

    @property
    def ready(self) -> bool:
        return self.problem is None


# --- where a job may be ----------------------------------------------------------------

def staging() -> Path:
    """Where job folders go: in the per-user data folder, outside every workspace and
    every shared temporary folder."""
    return home.data_root() / 'jobs'


def shared_temporary() -> list[Path]:
    """Temporary folders other programs also write to. An agent's sandbox lets a worker
    write to them, so nothing the runner relies on may sit under one."""
    named = ['/tmp', '/var/tmp', '/dev/shm', tempfile.gettempdir(), os.environ.get('TMPDIR')]
    return list(dict.fromkeys(Path(name).resolve() for name in named if name))


def check_folder(folder: Path) -> Path:
    """A job's folder, resolved. Refuses one under a shared temporary folder."""
    resolved = Path(folder).resolve()
    for shared in shared_temporary():
        if resolved == shared or shared in resolved.parents:
            raise WorkspaceError(
                f'{folder} is under {shared}, a temporary folder other programs share, so a '
                'worker could write to it. Keep job folders under agents.staging().')
    return resolved


def check(job: Job) -> Path:
    """Refuse a job that is wrong before it starts. Returns its folder, resolved."""
    if job.profile not in PROFILES:
        raise WorkspaceError('A job\'s profile is one of: ' + ', '.join(PROFILES) + '.')
    if not job.tools:
        raise WorkspaceError('A job needs the command that starts its worker tools.')
    if len(job.guidance) > GUIDANCE_LIMIT:
        raise WorkspaceError(f'The guidance is {len(job.guidance):,} characters; the most is '
                             f'{GUIDANCE_LIMIT:,}. Offer long material as an input instead.')
    folder = check_folder(job.folder)
    stand = folder / 'stand'
    if stand.is_dir() and any(stand.iterdir()):
        raise WorkspaceError(f'{stand} is not empty. A worker starts in an empty folder; give '
                             'each attempt a job folder of its own.')
    return folder


# --- plain words for what a worker is doing --------------------------------------------

def clip(text, length: int = 140) -> str:
    text = ' '.join(str(text).split())
    return text if len(text) <= length else text[:length - 1] + '…'


def describe(tool: str, given: dict) -> str:
    """One plain line for a call to a worker tool or to the agent's web search."""
    given = given if isinstance(given, dict) else {}
    lines = {
        'list_inputs': 'Looking at what it was given',
        'read_input': f"Reading {given.get('name', 'an input')}",
        'submit_artifact': f"Handing back {given.get('name', 'a draft')}",
        'submit_review': 'Writing its own notes on the draft',
        'save_source': f"Saving a source: {given.get('url', '')}",
        'read_source': f"Reading saved source {given.get('source_id', '')}",
        'search_source': (f"Searching {given.get('source_id', 'a source')} for "
                          f"\"{given.get('query', '')}\""),
        'submit_finding': f"Handing back the finding for {given.get('item', 'its question')}",
        'ask_person': 'Asking a question',
        'web_search': f"Searching the web: {given.get('query', '')}",
    }
    return clip(lines.get(tool, f'Using {tool}')).rstrip(': ')


def settled(tool: str | None, refused: bool) -> str | None:
    """One plain line for how a call came out, when that is worth saying."""
    if tool in ('submit_artifact', 'submit_finding'):
        thing = 'draft' if tool == 'submit_artifact' else 'finding'
        return (f'The {thing} was sent back with problems to fix' if refused
                else f'The {thing} was accepted')
    if tool == 'save_source' and refused:
        return 'That source could not be saved'
    return f'{tool} was refused' if refused and tool else None


def classify(said: str) -> str:
    """Why an agent stopped, from its own account: unavailable, limit or failed."""
    low = said.lower()
    if any(mark in low for mark in UNREACHABLE):
        return 'unavailable'
    return 'limit' if any(mark in low for mark in LIMITED) else 'failed'


class ClaudeEvents:
    """Reads Claude's event stream: lines to show as they happen, and how it ended."""

    def __init__(self):
        self.calls: dict[str, str] = {}
        self.text, self.cost, self.tokens = '', None, None
        self.ended, self.reason, self.detail = False, None, ''

    def feed(self, event: dict) -> list[str]:
        kind, lines = event.get('type'), []
        if kind == 'system':
            lines += self._system(event)
        elif kind in ('assistant', 'user'):
            content = (event.get('message') or {}).get('content')
            for block in content if isinstance(content, list) else ():
                lines += self._block(block) if isinstance(block, dict) else []
        elif kind == 'rate_limit_event':
            status = str((event.get('rate_limit_info') or {}).get('status', 'allowed'))
            if not status.startswith('allowed'):
                lines.append(f'The account\'s usage limit: {status}')
        elif kind == 'result':
            self._result(event)
        return [line for line in lines if line]

    def _system(self, event: dict) -> list[str]:
        subtype = event.get('subtype')
        if subtype == 'init':
            model = event.get('model')
            return ['Started' + (f' on {model}' if model else '')]
        if subtype == 'thinking_tokens':
            return ['Thinking']
        if subtype == 'permission_denied':
            return [f"Was refused the use of {event.get('tool_name', 'a tool')}"]
        return []

    def _block(self, block: dict) -> list[str]:
        if block.get('type') == 'tool_use':
            name = str(block.get('name', ''))
            tool = ('web_search' if name == CLAUDE_SEARCH
                    else name.removeprefix(f'mcp__{SERVER}__'))
            self.calls[block.get('id')] = tool
            return [describe(tool, block.get('input'))]
        if block.get('type') == 'tool_result':
            return [settled(self.calls.get(block.get('tool_use_id')),
                            bool(block.get('is_error')))]
        return []

    def _result(self, event: dict) -> None:
        self.ended = True
        self.text = event.get('result') if isinstance(event.get('result'), str) else ''
        cost, usage = event.get('total_cost_usd'), event.get('usage')
        self.cost = float(cost) if isinstance(cost, (int, float)) else None
        if isinstance(usage, dict):
            cached = usage.get('cache_read_input_tokens') or 0
            self.tokens = {
                'input': ((usage.get('input_tokens') or 0) + cached
                          + (usage.get('cache_creation_input_tokens') or 0)),
                'cached': cached, 'output': usage.get('output_tokens') or 0}
        subtype, status = str(event.get('subtype')), event.get('api_error_status')
        if subtype == 'success' and not event.get('is_error'):
            return
        said = clip(self.text or CLAUDE_ENDINGS.get(subtype, subtype), 300)
        if subtype in ('error_max_budget_usd', 'error_max_turns') or status == 429:
            self.reason = 'limit'
        elif status in (401, 403):
            self.reason = 'unavailable'
        else:
            self.reason = classify(said)
        self.detail = said


class CodexEvents:
    """Reads Codex's event stream: lines to show as they happen, and how it ended."""

    def __init__(self):
        self.text, self.cost, self.tokens = '', None, None
        self.turns, self.failure, self.said = 0, None, ''

    def feed(self, event: dict) -> list[str]:
        kind, item = event.get('type'), event.get('item')
        item = item if isinstance(item, dict) else {}
        if kind == 'thread.started':
            return ['Started']
        if kind == 'item.started' and item.get('type') == 'mcp_tool_call':
            return [describe(str(item.get('tool')), item.get('arguments'))]
        if kind == 'item.completed':
            return [line for line in self._item(item) if line]
        if kind == 'turn.completed':
            self._usage(event.get('usage'))
        elif kind == 'turn.failed':
            self.failure = clip((event.get('error') or {}).get('message', 'no reason given'),
                                300)
        elif kind == 'error':
            self.said = clip(event.get('message', ''), 300)
            return ['Reconnecting' if self.said.startswith('Reconnecting')
                    else f'Codex said: {clip(self.said)}']
        return []

    def _item(self, item: dict) -> list:
        kind = item.get('type')
        if kind == 'mcp_tool_call':
            return [settled(str(item.get('tool')), item.get('status') == 'failed')]
        if kind == 'web_search':
            return [describe('web_search', item)]
        if kind == 'agent_message':
            self.text = item.get('text') if isinstance(item.get('text'), str) else self.text
        elif kind == 'reasoning':
            return ['Thinking']
        elif kind == 'command_execution':
            return ['Ran a command, which a worker should not be able to do']
        elif kind == 'error':
            self.said = clip(item.get('message', ''), 300)
            return [f'Codex said: {clip(self.said)}']
        return []

    def _usage(self, usage) -> None:
        self.turns += 1
        if not isinstance(usage, dict):
            return
        tokens = self.tokens or {'input': 0, 'cached': 0, 'output': 0}
        for ours, theirs in (('input', 'input_tokens'), ('cached', 'cached_input_tokens'),
                             ('output', 'output_tokens')):
            tokens[ours] += usage.get(theirs) or 0
        self.tokens = tokens


# --- running a command under a time limit ----------------------------------------------

def supervise(command: list[str], cwd: Path, env: dict, stdin: str, seconds: float,
              errors: Path, each) -> tuple[int, bool]:
    """Run a command to its end or to its time limit, passing each line it prints to
    `each` as bytes. Returns its exit code and whether it was stopped for taking too long.

    The command gets a process group of its own, and the whole group is killed when time
    runs out or the caller fails, so nothing it started is left running.
    """
    with open(errors, 'wb') as complaints:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=complaints,
                                   start_new_session=True)
    late = threading.Event()

    def kill() -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def out_of_time() -> None:
        if process.poll() is None:
            late.set()
            kill()

    def feed() -> None:
        for step in (lambda: process.stdin.write(stdin.encode('utf-8')), process.stdin.close):
            try:
                step()
            except OSError:
                pass  # it stopped reading; how it ended says why

    timer = threading.Timer(seconds, out_of_time)
    timer.daemon = True
    writer = threading.Thread(target=feed, daemon=True)
    timer.start()
    writer.start()
    try:
        for line in process.stdout:
            each(line)
        process.wait()
    finally:
        timer.cancel()
        if process.poll() is None:
            kill()
            process.wait()
        writer.join(timeout=10)
        process.stdout.close()
    return process.returncode, late.is_set()


def tail(path: Path, length: int = 300) -> str:
    """The last thing a command wrote to standard error, on one line."""
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').strip().splitlines()
    except OSError:
        return ''
    return clip(lines[-1], length) if lines else ''


# --- whether an agent can be used now --------------------------------------------------

def ask(command: list[str], env: dict | None = None, seconds: float = 20) -> tuple:
    """Run a short command that only reports. Returns (exit code, output), or (None, '')
    when it could not be run or did not answer in time."""
    try:
        done = subprocess.run(command, env=env, capture_output=True, timeout=seconds,
                              stdin=subprocess.DEVNULL, encoding='utf-8', errors='replace')
    except (OSError, subprocess.TimeoutExpired):
        return None, ''
    return done.returncode, (done.stdout + done.stderr).strip()


def reachable(host: str, seconds: float = 8) -> str | None:
    """Why a service cannot be reached over TLS from this network, or None when it can.

    It connects and checks the service's certificate, through this computer's proxy when
    it has one, and sends no request. A network that intercepts the connection fails here
    even though the agent is signed in.
    """
    context = ssl.create_default_context()
    proxy = urllib.request.getproxies().get('https')
    try:
        if proxy and not urllib.request.proxy_bypass(host):
            via = urllib.parse.urlsplit(proxy if '//' in proxy else f'//{proxy}')
            headers = {}
            if via.username:
                secret = f'{via.username}:{via.password or ""}'.encode()
                headers['Proxy-Authorization'] = 'Basic ' + base64.b64encode(secret).decode()
            link = http.client.HTTPSConnection(via.hostname, via.port or 80,
                                               timeout=seconds, context=context)
            link.set_tunnel(host, 443, headers=headers)
            try:
                link.connect()
            finally:
                link.close()
        else:
            with socket.create_connection((host, 443), timeout=seconds) as plain:
                context.wrap_socket(plain, server_hostname=host).close()
    except ssl.SSLCertVerificationError as failure:
        return (f'the connection to {host} is being intercepted on this network, or its '
                f'certificate is not trusted here ({failure.verify_message})')
    except (OSError, http.client.HTTPException) as failure:
        return f'{host} cannot be reached from this network ({failure})'
    return None


# --- the adapters ----------------------------------------------------------------------

class _Agent:
    """What the two real adapters share: checking the job, running the command under its
    time limit, keeping the event stream, and reporting how it went."""
    name = title = program = host = sign_in = ''

    def __init__(self, program: str | None = None):
        self.program = program or self.program

    def environment(self, job: Job) -> dict:
        """The worker's environment: this one, with a temporary folder of its own."""
        return {**os.environ, 'TMPDIR': str(Path(job.folder).resolve() / 'tmp')}

    def run(self, job: Job, activity=None) -> Outcome:
        folder = check(job)
        if shutil.which(self.program) is None:
            return Outcome(False, 'unavailable', f'{self.title} is not installed on this '
                           'computer.')
        for name in ('stand', 'tmp'):
            (folder / name).mkdir(parents=True, exist_ok=True)
        reader, events = self.reader(), folder / 'events.jsonl'
        said: list[str] = []

        def each(line: bytes) -> None:
            kept.write(line)
            kept.flush()
            try:
                event = json.loads(line)
            except ValueError:
                return
            for text in reader.feed(event) if isinstance(event, dict) else ():
                if activity and text != (said[-1] if said else None):
                    activity(text)
                said.append(text)

        started = time.monotonic()
        with open(events, 'wb') as kept:
            try:
                code, late = supervise(self.command(job), folder / 'stand',
                                       self.environment(job), self.said_to(job),
                                       job.limits.seconds, folder / 'stderr.txt', each)
            except OSError as failure:
                return Outcome(False, 'unavailable', f'{self.title} could not be started '
                               f'({failure}).', events=events)
        seconds = round(time.monotonic() - started, 1)
        if late:
            return Outcome(False, 'timeout', f'It did not finish in {job.limits.seconds} '
                           'seconds, so it was stopped.', reader.text, reader.cost,
                           reader.tokens, seconds, events)
        reason, detail = self.verdict(job, reader, code, tail(folder / 'stderr.txt'))
        return Outcome(reason is None, reason, detail, self.last(job, reader), reader.cost,
                       reader.tokens, seconds, events)

    def last(self, job: Job, reader) -> str:
        return reader.text

    def ready(self, which=shutil.which, run=ask, reach=reachable) -> Readiness:
        """Whether this agent is installed, signed in and reachable now. Starts no agent."""
        if which(self.program) is None:
            return Readiness(self.name, False, problem=f'{self.title} is not installed. '
                             'Install it and sign in, then try again.')
        version = (run([self.program, '--version'])[1].splitlines() or [''])[-1].strip()
        signed, host = self.signed_in(run)
        blocked = reach(host)
        problem = None
        if signed is False:
            problem = (f'{self.title} is not signed in. Run {self.sign_in} in a terminal, '
                       'then try again.')
        elif blocked:
            problem = (f'{self.title} is signed in but cannot be used from this network: '
                       f'{blocked}. Try another network.')
        return Readiness(self.name, True, signed, blocked is None, version or None, problem)


class Claude(_Agent):
    """Claude Code as a worker: `claude -p --restricted`, with no built-in tools."""
    name, title, program = 'claude', 'Claude Code', 'claude'
    host, sign_in = 'api.anthropic.com', 'claude auth login'
    reader = ClaudeEvents

    def environment(self, job: Job | None = None) -> dict:
        """Nothing that belongs to another Claude session is passed on."""
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(SOMEONE_ELSES)}
        if job is not None:
            env['TMPDIR'] = str(Path(job.folder).resolve() / 'tmp')
        return env

    def command(self, job: Job) -> list[str]:
        """The exact command. It also writes the one file the command names: the list of
        MCP servers, which holds the worker tools and nothing else.

        `--tools ""` leaves no built-in tool at all, and a research job gets the search tool
        alone. The permission mode is the one milestone 0 ran with; with no file tools
        there is nothing for it to accept.
        """
        research = job.profile == 'research'
        config = Path(job.folder).resolve() / 'mcp.json'
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({'mcpServers': {SERVER: {
            'command': job.tools[0], 'args': list(job.tools[1:])}}}), encoding='utf-8')
        allowed = [f'mcp__{SERVER}'] + ([CLAUDE_SEARCH] if research else [])
        command = [self.program, '-p', '--output-format', 'stream-json', '--verbose',
                   '--restricted', '--strict-mcp-config', '--mcp-config', str(config),
                   '--permission-prompts', 'none', '--permission-mode', 'acceptEdits',
                   '--tools', CLAUDE_SEARCH if research else '',
                   '--allowedTools', ','.join(allowed), '--no-session-persistence',
                   '--append-system-prompt', job.guidance]
        if job.limits.dollars is not None:
            command += ['--max-budget-usd', f'{job.limits.dollars:g}']
        if job.model:
            command += ['--model', job.model]
        return command

    def said_to(self, job: Job) -> str:
        """What goes to standard input: the job. The guidance is in the command."""
        return job.task

    def verdict(self, job: Job, reader: ClaudeEvents, code: int, complaint: str) -> tuple:
        if reader.ended and reader.reason is None:
            return None, ''
        if reader.ended:
            return reader.reason, f'It stopped without finishing: {reader.detail}'
        said = complaint or f'it ended with exit code {code} and no result'
        return classify(said), f'It stopped without finishing: {said}'

    def signed_in(self, run) -> tuple[bool | None, str]:
        """Whether Claude Code says it is signed in, asked as a worker would be started."""
        code, said = run([self.program, 'auth', 'status', '--json'], self.environment())
        try:
            found = json.loads(said).get('loggedIn')
        except (ValueError, AttributeError):
            found = None
        return (found if isinstance(found, bool) else None if code is None else code == 0,
                self.host)


class Codex(_Agent):
    """Codex as a worker: `codex exec`, with its shell and every extra switched off."""
    name, title, program = 'codex', 'Codex', 'codex'
    host, sign_in = 'chatgpt.com', 'codex login'
    reader = CodexEvents

    def command(self, job: Job) -> list[str]:
        """The exact command. Codex has no spending limit to set; only time bounds it."""
        folder = Path(job.folder).resolve()
        command = [self.program, 'exec', '--json', '--cd', str(folder / 'stand'),
                   '--sandbox', 'workspace-write', '--ignore-user-config', '--ignore-rules',
                   '--skip-git-repo-check', '--ephemeral',
                   '-o', str(folder / 'last-message.txt')]
        for feature in CODEX_OFF:
            command += ['--disable', feature]
        search = 'live' if job.profile == 'research' else 'disabled'
        for setting in ('project_doc_max_bytes=0', f'web_search="{search}"',
                        f'mcp_servers.{SERVER}.command=' + _toml(job.tools[0]),
                        f'mcp_servers.{SERVER}.args=' + _toml(list(job.tools[1:])),
                        f'mcp_servers.{SERVER}.default_tools_approval_mode="approve"'):
            command += ['-c', setting]
        if job.model:
            command += ['-m', job.model]
        return command + ['-']

    def said_to(self, job: Job) -> str:
        """Codex takes one prompt, so the guidance and the job go in together."""
        return f'Instructions for this job:\n\n{job.guidance}\n\nThe job:\n\n{job.task}'

    def verdict(self, job: Job, reader: CodexEvents, code: int, complaint: str) -> tuple:
        if reader.failure is None and code == 0 and reader.turns:
            return None, ''
        said = reader.failure or reader.said or complaint or (
            f'it ended with exit code {code} before finishing a turn')
        return classify(f'{said} {complaint}'), f'It stopped without finishing: {said}'

    def last(self, job: Job, reader: CodexEvents) -> str:
        """Codex writes its last message to a file; the stream's copy is the fallback."""
        try:
            return (Path(job.folder) / 'last-message.txt').read_text(encoding='utf-8')
        except OSError:
            return reader.text

    def signed_in(self, run) -> tuple[bool | None, str]:
        """Whether Codex says it is signed in, and which service that sign-in uses."""
        code, said = run([self.program, 'login', 'status'])
        host = 'api.openai.com' if 'api key' in said.lower() else self.host
        return (None if code is None else code == 0), host


def _toml(value) -> str:
    """A string or a list of strings as TOML, which a JSON spelling of them is."""
    return json.dumps(value, ensure_ascii=False)


class Scripted:
    """A worker played by a Python function, for tests.

    The function is called as `script(tools, job)` with the job's WorkerTools, and uses
    them as an agent would. What it returns becomes the outcome: text or None for a job
    that finished, or an Outcome to play a timeout, a limit or a failure. It starts
    nothing, so it does not mind where the job's folder is.
    """
    name = title = 'scripted'

    def __init__(self, script):
        self.script = script

    def run(self, job: Job, activity=None) -> Outcome:
        if job.profile not in PROFILES:
            raise WorkspaceError('A job\'s profile is one of: ' + ', '.join(PROFILES) + '.')
        started = time.monotonic()
        tools = worker_tools.WorkerTools(job.folder)
        returned = self.script(_Narrated(tools, activity) if activity else tools, job)
        seconds = round(time.monotonic() - started, 1)
        if isinstance(returned, Outcome):
            return returned
        return Outcome(True, text=returned or '', seconds=seconds)

    def ready(self, *unused, **ignored) -> Readiness:
        return Readiness(self.name, True, True, True, version='scripted')


class _Narrated:
    """Worker tools that say what is being done with them, as a real agent's stream does."""

    def __init__(self, tools, activity):
        self._tools, self._activity = tools, activity

    def __getattr__(self, name):
        found = getattr(self._tools, name)
        if name not in worker_tools.NAMES:
            return found

        def called(*args, **given):
            names = list(worker_tools.TOOLS[worker_tools.NAMES.index(name)]
                         ['inputSchema']['properties'])
            self._activity(describe(name, {**dict(zip(names, args)), **given}))
            outcome = found(*args, **given)
            line = settled(name, not outcome[0])
            if line:
                self._activity(line)
            return outcome
        return called


AGENTS = {'claude': Claude, 'codex': Codex}
