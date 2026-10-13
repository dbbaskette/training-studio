"""The tools a worker is given, and the server that offers them to an agent.

What a caller needs to know
---------------------------
A worker has no shell and no files. It can only call these tools, and what it hands back is
checked here before anything is kept. Each job has a folder that only the runner writes to:

    job.json      what the job may read and must hand back, written by prepare()
    inputs/       the job's inputs, one file each
    sources/      saved sources: index.json, a text snapshot of each, and its original
    accepted/     what the worker handed back and the checks let through
    state.json    how often each thing was handed back, and why the last one was refused
    tools.log     every call, one JSON object a line

    prepare(folder, inputs=, artifacts=, finding=, sources=, fetch=, ask=)   set a job up
    command(folder)        the command an agent starts the server with
    WorkerTools(folder)    the same tools in this process; every tool answers (ok, text)
    collect(folder)        what was handed back, for the engine to keep

- `artifacts` maps each draft the job hands back to {'kind': ...}. The kind chooses the
  validator (VALIDATORS), and each validator is the core's own check. A 'blueprint' also
  takes 'level' and 'findings' (finding ID to verdict). A 'research-plan' takes 'scope' and
  'sources': the worker supplies the topic and the questions, and the runner fills in the
  rest, so what is kept is the whole plan. A 'document' takes 'blueprint', its blueprint's
  text. A 'brief' takes 'brief_kind' and 'findings'. A 'scenario' takes 'label', its name
  in the core without a level, and 'mode', the mode the practice plan gives it. A 'yoodli'
  takes 'label', 'profile' (the Yoodli profile, parsed), 'scenario' (its scenario's text)
  and 'objectives' (the blueprint's objective IDs); the length each field states is put in
  for the worker, so nobody counts characters by eye.
- A check that cannot run for want of one of these is recorded as unavailable, for the gate.
  It is not held against the worker.
- `finding` is the ID of the one research question the job answers. An accepted finding is in
  the shape `harness-research record` takes, with each quote's place worked out here.
- `sources` are documents offered before the job starts: {'title', 'origin', 'text', 'file',
  'supplied'}, where `file` is the snapshot's path in the training and `supplied` is the
  document's ID in the research plan, if it has one.
- Saved sources are named after their content, under sources/, so the engine can copy a
  job's sources into a training's own sources/ and a finding's `file` stays true.
- `fetch` lets the job save pages. Only public http and https addresses are fetched: every
  address a name has must be public, each redirect is checked again, and the connection
  goes to the address that was checked. Where a computer reaches the web through a proxy,
  the proxy connects instead; if that computer cannot look names up itself, nothing is
  fetched.
- A draft or a finding can be handed back SUBMISSIONS times. After that, treat the job as
  failed: `collect(folder)['problems']` says why the last one was refused.
- A question (`ask_person`) ends the job: every later call is refused. Pass `ask=False`
  for a job nobody can answer, such as one research question among many.
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import html.parser
import http.client
import inspect
import ipaddress
import json
import re
import shutil
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

if not __package__:  # started as the server, by its path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import runner  # noqa: F401,E402  puts the core on the import path
import checks  # noqa: E402
import home  # noqa: E402
from workspace import BRIEF_KINDS, WorkspaceError  # noqa: E402

SCHEMA = 1
PART = 20_000           # characters of an input in one read
WINDOW = 12_000         # characters of a source in one read
MAX_BYTES = 8_000_000   # the largest page or PDF that is kept
MAX_SOURCES = 30        # the most sources one job may save
MAX_HOPS = 5            # redirects followed for one page
TIMEOUT = 40            # seconds for one request
SUBMISSIONS = 6         # times one draft or finding may be handed back
QUOTE = (20, 900)       # the shortest and longest quote, in characters
SUMMARY = 1500
NOTES = 4000
QUESTION = 1000
PASSAGES = 20
ADDRESS = 2000
STATUSES = ('supported', 'contradicted', 'insufficient', 'unavailable')
SCOPES = ('public-web', 'supplied-only')
QUESTION_ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
NOT_A_QUERY = re.compile(r'https?://|[/\\@]')
CHARSET = re.compile(r'charset\s*=\s*["\']?([\w.:-]+)', re.IGNORECASE)
META_CHARSET = re.compile(rb'<meta[^>]+charset\s*=\s*["\']?([\w.:-]+)', re.IGNORECASE)
REDIRECTS = (301, 302, 303, 307, 308)
TEXT_TYPES = ('application/xhtml+xml', 'application/xml', 'application/json')
# A person's browser sends these; some sites refuse a request without them.
HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
                   '(KHTML, like Gecko) Version/17.0 Safari/605.1.15'),
    'Accept': 'text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}
# Characters an agent may write one of in place of another when it copies a quote.
ALIKE = ("'‘’`", '"“”', '-‐‑–—')
ENDED = ('This job ended when you asked your question. Stop now: nothing more can be done '
         'until a person answers.')


class Refusal(WorkspaceError):
    """A tool's "no", in a sentence the worker can act on."""


# --- text ------------------------------------------------------------------------------

def parts(text: str, size: int = PART) -> list[str]:
    """A long text in pieces of at most `size`, each ending at a line end where it can."""
    pieces, start = [], 0
    while len(text) - start > size:
        cut = text.rfind('\n', start + size // 2, start + size) + 1 or start + size
        pieces.append(text[start:cut])
        start = cut
    pieces.append(text[start:])
    return pieces


def tidy(text: str) -> str:
    """Text as it is kept: one space between words, no more than one blank line, and none
    of the characters that would shift where a quote is counted from."""
    text = text.replace('\x00', '').replace('﻿', '')
    lines = [' '.join(line.split()) for line in text.splitlines()]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip() + '\n'


def whole(value, label: str) -> int:
    """A whole number an agent sent, which may have arrived as text."""
    try:
        return int(value)
    except (TypeError, ValueError):
        raise Refusal(f'{label} must be a whole number.')


def slug(text: str, length: int = 40) -> str:
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:length].strip('-') or 'x'


def clip(value, length: int = 200) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= length else text[:length] + '…'


def _loose(character: str) -> str:
    for group in ALIKE:
        if character in group:
            return '[' + re.escape(group) + ']'
    return re.escape(character)


def place(text: str, quote: str) -> tuple[int, str] | None:
    """Where a quote sits in a source, and the source's own wording of it.

    A quote that differs only in spacing, line breaks or the style of its quotation marks
    and dashes is found too, and the wording returned is the source's, character for
    character. None when the quote is not there.
    """
    at = text.find(quote)
    if at >= 0 and quote:
        return at, quote
    pattern = r'\s+'.join(''.join(map(_loose, word)) for word in quote.split())
    found = re.search(pattern, text) if pattern else None
    return (found.start(), found.group(0)) if found else None


class _Page(html.parser.HTMLParser):
    """The readable text of a web page, and its title."""
    SKIP = {'script', 'style', 'noscript', 'svg', 'head', 'template'}
    BREAK = {'p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'section',
             'article', 'pre', 'table', 'blockquote', 'dt', 'dd'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.depth, self.title, self.in_title = [], 0, '', False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        if tag == 'title':
            self.in_title = True
        if tag in self.BREAK:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1
        if tag == 'title':
            self.in_title = False
        if tag in self.BREAK:
            self.parts.append('\n')

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if not self.depth:
            self.parts.append(data)


def decode(data: bytes, content_type: str) -> str:
    """A page's bytes as text, in the encoding it declares, or UTF-8."""
    declared = CHARSET.search(content_type)
    name = declared.group(1) if declared else None
    if name is None:
        found = META_CHARSET.search(data[:4096])
        name = found.group(1).decode('ascii', 'replace') if found else 'utf-8'
    try:
        return data.decode(name, 'replace')
    except LookupError:
        return data.decode('utf-8', 'replace')


def page_text(data: bytes, content_type: str) -> tuple[str, str]:
    """The text and title of a fetched page that is not a PDF."""
    text = decode(data, content_type)
    kind = content_type.partition(';')[0].strip().lower()
    if kind == 'application/json' or (kind.startswith('text/') and kind != 'text/html'):
        return tidy(text), ''
    parser = _Page()
    parser.feed(text)
    parser.close()
    return tidy(''.join(parser.parts)), ' '.join(parser.title.split())


def pdf_text(path: Path) -> str | None:
    """The text of a PDF, read with pdftotext. None when pdftotext is not installed."""
    program = shutil.which('pdftotext')
    if program is None:
        return None
    try:
        done = subprocess.run([program, '-layout', str(path), '-'], capture_output=True,
                              stdin=subprocess.DEVNULL, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        raise Refusal('That PDF could not be read. It was not saved.')
    if done.returncode != 0:
        raise Refusal('That PDF could not be read. It was not saved.')
    return done.stdout.decode('utf-8', 'replace')


# --- fetching --------------------------------------------------------------------------

def public(address: str) -> bool:
    """True for an address on the public internet: not private, loopback, link-local,
    shared, reserved or unspecified, in either address family."""
    try:
        found = ipaddress.ip_address(address.partition('%')[0])
    except ValueError:
        return False
    return (getattr(found, 'ipv4_mapped', None) or found).is_global


def resolve(host: str) -> list[str]:
    """Every address a host name has."""
    found = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in found))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects come back as answers, so each new address is checked before it is used."""

    def redirect_request(self, *args, **kwargs):
        return None


def _pinned(address: str) -> list:
    """Handlers that connect to one address, already checked, whatever the name resolves to
    by the time the connection is made."""
    context = ssl.create_default_context()
    context.set_alpn_protocols(['http/1.1'])

    class Plain(http.client.HTTPConnection):
        def connect(self):
            self.sock = socket.create_connection((address, self.port), self.timeout)

    class Secure(http.client.HTTPSConnection):
        def connect(self):
            plain = socket.create_connection((address, self.port), self.timeout)
            self.sock = context.wrap_socket(plain, server_hostname=self.host)

    class Http(urllib.request.HTTPHandler):
        def http_open(self, request):
            return self.do_open(Plain, request)

    class Https(urllib.request.HTTPSHandler):
        def https_open(self, request):
            return self.do_open(Secure, request)

    return [Http(), Https()]


def fetch_once(url: str, address: str, limit: int) -> tuple[int, dict, bytes]:
    """Ask for one address once, following nothing: (status, headers, at most limit + 1
    bytes of body). Connects to `address`, which the caller has checked, unless this
    computer reaches the web through a proxy, which then makes the connection itself."""
    target = urllib.parse.urlsplit(url)
    proxied = (target.scheme in urllib.request.getproxies()
               and not urllib.request.proxy_bypass(target.hostname))
    opener = urllib.request.build_opener(_NoRedirect(), *([] if proxied else _pinned(address)))
    try:
        reply = opener.open(urllib.request.Request(url, headers=HEADERS), timeout=TIMEOUT)
    except urllib.error.HTTPError as answered:
        reply = answered
    with reply:
        headers = {name.lower(): value for name, value in reply.headers.items()}
        return reply.code, headers, reply.read(limit + 1)


def unpacked(data: bytes, encoding: str) -> bytes:
    """A body as sent, or unpacked when the site compressed it without being asked to."""
    if encoding.strip().lower() in ('', 'identity'):
        return data
    try:
        return zlib.decompressobj(47).decompress(data, MAX_BYTES + 1)
    except zlib.error:
        raise Refusal('The site sent that page in a form that could not be read. It was '
                      'not saved.')


# --- validators ------------------------------------------------------------------------

def check_plan(text: str, spec: dict) -> tuple[list[str], list[dict], list[str], str]:
    """A research plan: the worker's topic and questions, with the rest filled in here.
    Returns problems, the checks that ran, warnings, and the plan as it will be kept."""
    try:
        given = json.loads(text)
    except ValueError as failure:
        return [f'The plan is not valid JSON ({failure}).'], [], [], text
    if not isinstance(given, dict):
        return ['The plan must be a JSON object with "topic" and "items".'], [], [], text
    scope = spec.get('scope') or given.get('scope')
    items, problems = given.get('items'), []
    if isinstance(items, list):
        items = [_question(item, scope, problems) for item in items]
    plan = {'topic': given.get('topic'), 'purpose': 'planning', 'scope': scope,
            'sources': spec.get('sources') or [], 'items': items}
    topic = plan['topic']
    if not isinstance(topic, str) or not topic.strip() or len(topic) > 4000:
        problems.insert(0, '"topic" must say what the training is about, in a line or two.')
    outcome = checks.check_research_plan(plan)
    return (outcome['problems'] + problems, [outcome], [],
            json.dumps(plan, indent=2, ensure_ascii=False) + '\n')


def _question(item, scope, problems: list[str]):
    """One question as harness-research takes it. Problems it would refuse are added."""
    if not isinstance(item, dict):
        return item
    query = item.get('public_query') if scope == 'public-web' else None
    label = item.get('id') or 'a question'
    if query is not None and (not isinstance(query, str) or not query.strip()
                              or len(query) > 500 or NOT_A_QUERY.search(query)):
        problems.append(f'{label}: "public_query" is a few public search words, at most 500 '
                        'characters, with no address, path or email address in it.')
    if isinstance(item.get('question'), str) and len(item['question']) > 4000:
        problems.append(f'{label}: the question is too long; ask one thing.')
    return {'id': item.get('id'), 'question': item.get('question'), 'public_query': query,
            'claim': None}


def held(outcomes: list[dict]) -> list[str]:
    """What the checks hold against a draft: the problems of each one that failed. A check
    that could not run holds nothing against it."""
    return [problem for outcome in outcomes if outcome['status'] == 'failed'
            for problem in outcome['problems']]


def as_kept(text: str) -> str:
    """A draft as it is kept: ending in one line end."""
    return text.rstrip('\n') + '\n'


def check_blueprint(text: str, spec: dict) -> tuple[list[str], list[dict], list[str], str]:
    """A blueprint, against the core's own lint. A check that could not run is recorded
    for the gate, not held against the worker."""
    report = checks.lint_blueprint(text, spec.get('findings'), spec.get('level'))
    return held(report['checks']), report['checks'], report['warnings'], as_kept(text)


def check_document(text: str, spec: dict) -> tuple[list[str], list[dict], list[str], str]:
    """A learner guide, against the core's coverage check and the blueprint it teaches.
    Without the blueprint the check cannot run, which is recorded for the gate."""
    if isinstance(spec.get('blueprint'), str):
        outcome = checks.document_coverage(checks.parse_blueprint(spec['blueprint']), text)
    else:
        outcome = checks.result('document.coverage', [], unavailable=(
            'The blueprint was not given, so coverage could not be checked.'))
    return held([outcome]), [outcome], [], as_kept(text)


def check_brief(text: str, spec: dict) -> tuple[list[str], list[dict], list[str], str]:
    """A brief, against the core's own check of its sections and the findings they name.
    Without the findings the second cannot run, which is recorded for the gate."""
    outcomes = checks.check_brief(text, spec.get('brief_kind') or BRIEF_KINDS[0],
                                  spec.get('findings'))
    return held(outcomes), outcomes, [], as_kept(text)


def check_scenario(text: str, spec: dict) -> tuple[list[str], list[dict], list[str], str]:
    """A practice scenario, against the core's own check of its shape. A mode other than
    the practice plan's is noted for the reviewer: the scenario file decides."""
    outcome = checks.check_scenario(text, spec.get('label') or 'scenario:main')
    stated, planned = checks.parse_scenario(text)['mode'], spec.get('mode')
    warnings = [] if not planned or stated == planned else [
        f'The practice plan lists this scenario as {planned}; the file says {stated}. The '
        'scenario file decides.']
    return held([outcome]), [outcome], warnings, as_kept(text)


def counted(text: str) -> str:
    """A Yoodli scenario with the real length of each field put where the file states one,
    as in "666 of 10,000 characters". The limit beside it is left as the worker wrote it."""
    fields, _ = checks.fenced_fields(text)
    lines, path, inside = [], [], False
    for line in text.splitlines():
        if line.startswith('```'):
            inside = not inside
        elif not inside:
            head = checks.HEADING.match(line)
            if head:
                path = path[:len(head.group(1)) - 2] + [head.group(2)]
            elif tuple(path) in fields:
                size = f'{len(fields[tuple(path)]):,}'
                line = checks.STATED_COUNT.sub(
                    lambda stated: size + stated.group(0)[len(stated.group(1)):], line, count=1)
        lines.append(line)
    return '\n'.join(lines) + '\n'


def check_yoodli(text: str, spec: dict) -> tuple[list[str], list[dict], list[str], str]:
    """A Yoodli scenario, against the core's own check with the Yoodli profile: its fields,
    its goals, each count against its limit, and that every success criterion has a goal.
    What cannot be checked for want of the profile, the scenario or the objectives is
    recorded for the gate."""
    label, profile = spec.get('label') or 'yoodli:main', spec.get('profile')
    if not isinstance(profile, dict) or not isinstance(profile.get('limits'), dict):
        outcomes = [checks.result(f'{label}.{part}', [], unavailable=(
            'The Yoodli profile was not given, so this could not be checked.'))
            for part in ('fields', 'limits', 'mapping')]
        return [], outcomes, [], as_kept(text)
    text = counted(text)
    scenario = (checks.parse_scenario(spec['scenario'])
                if isinstance(spec.get('scenario'), str) else None)
    objectives = set(spec['objectives']) if isinstance(spec.get('objectives'), list) else None
    outcomes = checks.check_yoodli(text, profile, scenario, objectives, label)
    return held(outcomes), outcomes, [], as_kept(text)


VALIDATORS = {'research-plan': check_plan, 'blueprint': check_blueprint,
              'document': check_document, 'brief': check_brief, 'scenario': check_scenario,
              'yoodli': check_yoodli}
EXTENSIONS = {'research-plan': '.json'}


# --- a job's folder --------------------------------------------------------------------

def prepare(folder: Path, inputs: dict[str, str] | None = None,
            artifacts: dict[str, dict] | None = None, finding: str | None = None,
            sources=(), fetch: bool = False, ask: bool = True) -> Path:
    """Set a job's folder up: what the worker may read, and what it must hand back."""
    folder = Path(folder)
    if (folder / 'job.json').exists():
        raise WorkspaceError(f'{folder} already holds a job. Give each job, and each new '
                             'attempt at one, a folder of its own.')
    for name, spec in (artifacts or {}).items():
        if not isinstance(spec, dict) or spec.get('kind') not in VALIDATORS:
            raise WorkspaceError(f'{name} needs a kind that can be checked: one of '
                                 + ', '.join(VALIDATORS) + '.')
        if spec.get('scope') not in (None, *SCOPES):
            raise WorkspaceError(f"{name}: the scope is one of {', '.join(SCOPES)}.")
        if spec.get('brief_kind') not in (None, *BRIEF_KINDS):
            raise WorkspaceError(f"{name}: the kind of brief is one of "
                                 f"{', '.join(BRIEF_KINDS)}.")
    if finding is not None and not QUESTION_ID.match(finding):
        raise WorkspaceError(f'"{finding}" is not a research question ID.')
    listed = []
    for number, (name, text) in enumerate((inputs or {}).items(), start=1):
        _write(folder / 'inputs' / f'{number}.txt', text)
        listed.append({'name': name, 'file': f'inputs/{number}.txt', 'chars': len(text)})
    index = [_offered(folder, number, source)
             for number, source in enumerate(sources, start=1)]
    home.write_json(folder / 'sources' / 'index.json', index)
    home.write_json(folder / 'job.json', {
        'schema': SCHEMA, 'inputs': listed, 'artifacts': artifacts or {}, 'finding': finding,
        'fetch': bool(fetch), 'ask': bool(ask), 'prepared_at': home.now()})
    return folder


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode('utf-8'))


def _offered(folder: Path, number: int, source: dict) -> dict:
    """Keep a document the runner offers, and describe it as a saved source."""
    missing = [key for key in ('title', 'origin', 'text', 'file') if not source.get(key)]
    if missing:
        raise WorkspaceError('An offered source needs: ' + ', '.join(missing) + '.')
    text, local = tidy(source['text']), f'sources/offered-{number}.txt'
    _write(folder / local, text)
    return {'id': f's{number}', 'url': source['origin'], 'title': source['title'],
            'chars': len(text), 'file': source['file'], 'local': local, 'original': None,
            'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(), 'offered': True,
            'supplied': source.get('supplied')}


def command(folder: Path) -> list[str]:
    """The command that starts the tools server for one job. It runs apart from whatever
    Python settings the agent's environment carries."""
    return [sys.executable, '-I', str(Path(__file__).resolve()), '--job',
            str(Path(folder).resolve())]


def _job(folder: Path) -> dict:
    job = home.read_json(Path(folder) / 'job.json', None)
    if not isinstance(job, dict) or job.get('schema') != SCHEMA:
        raise WorkspaceError(f'{folder} is not a job folder this version can use. Set one up '
                             'with prepare first.')
    return job


def collect(folder: Path) -> dict:
    """What a job handed back and the checks let through, read from its folder.

    `artifacts` maps each accepted draft to its kind, text, checks and warnings. `sources`
    lists every source with `path`, where its snapshot is in the job's folder, and `file`,
    where a finding says it is in the training. `problems` holds why the last hand-back of
    anything not accepted was refused.
    """
    folder = Path(folder)
    _job(folder)
    kept = folder / 'accepted'
    artifacts = {}
    for name, entry in home.read_json(kept / 'artifacts.json', {}).items():
        path = folder / entry['file']
        artifacts[name] = {**entry, 'path': path, 'text': path.read_text(encoding='utf-8')}
    review, asked = kept / 'review.md', home.read_json(kept / 'question.json', None)
    sources = []
    for entry in home.read_json(folder / 'sources' / 'index.json', []):
        original = entry.get('original')
        sources.append({**entry, 'path': folder / entry['local'],
                        'original_path': folder / original if original else None})
    state = home.read_json(folder / 'state.json', {})
    return {'artifacts': artifacts,
            'review': review.read_text(encoding='utf-8') if review.is_file() else None,
            'finding': home.read_json(kept / 'finding.json', None),
            'question': asked.get('question') if isinstance(asked, dict) else None,
            'sources': sources,
            'problems': {name: found for name, found
                         in state.get('problems', {}).items() if found}}


# --- the tools -------------------------------------------------------------------------

def tool(method):
    """Make a method a worker tool: fit the arguments an agent sent, refuse once the job
    has ended, turn a refusal into an answer, and log the call."""
    signature = inspect.signature(method)
    takes = ', '.join(list(signature.parameters)[1:]) or 'nothing'

    @functools.wraps(method)
    def called(self, *args, **given):
        shown = given
        try:
            bound = signature.bind(self, *args, **given)
        except TypeError:
            outcome = (False, f'Wrong arguments for {method.__name__}: it takes {takes}.')
        else:
            shown = dict(list(bound.arguments.items())[1:])
            try:
                if self._state().get('ended'):
                    raise Refusal(ENDED)
                outcome = method(*bound.args, **bound.kwargs)
            except (WorkspaceError, OSError) as refused:
                outcome = (False, str(refused))
        self._log(method.__name__, shown, outcome)
        return outcome
    called.is_tool = True
    return called


class WorkerTools:
    """One job's tools. `opener`, `resolver` and `pdf` are replaceable, so tests never
    touch the network or need a PDF reader."""

    def __init__(self, folder: Path, opener=None, resolver=None, pdf=None):
        self.folder = Path(folder)
        self.job = _job(self.folder)
        self.opener = opener or fetch_once
        self.resolver = resolver or resolve
        self.pdf = pdf or pdf_text

    # --- bookkeeping ---

    def _state(self) -> dict:
        state = home.read_json(self.folder / 'state.json', {})
        return {'submissions': {}, 'problems': {}, 'ended': None, **state}

    def _count(self, name: str, problems: list[str]) -> int:
        """Note one more hand-back of `name` and how it went. Returns how many remain."""
        state = self._state()
        state['submissions'][name] = state['submissions'].get(name, 0) + 1
        state['problems'][name] = problems
        home.write_json(self.folder / 'state.json', state)
        return SUBMISSIONS - state['submissions'][name]

    def _allowed(self, name: str, what: str) -> None:
        if self._state()['submissions'].get(name, 0) >= SUBMISSIONS:
            raise Refusal(f'{what} has been handed back {SUBMISSIONS} times, which is the '
                          'most a job may. Stop now, and say in your last message what you '
                          'could not put right.')

    def _log(self, name: str, given: dict, outcome: tuple[bool, str]) -> None:
        entry = {'at': home.now(), 'tool': name, 'ok': outcome[0],
                 'given': {key: clip(value) for key, value in given.items()},
                 'answer': clip(outcome[1], 300)}
        with open(self.folder / 'tools.log', 'a', encoding='utf-8') as stream:
            stream.write(json.dumps(entry) + '\n')

    def _index(self) -> list[dict]:
        return home.read_json(self.folder / 'sources' / 'index.json', [])

    def _source(self, source_id) -> tuple[dict, str]:
        """A saved source's entry and its text."""
        index = self._index()
        entry = next((item for item in index if item['id'] == str(source_id).strip()), None)
        if entry is None:
            known = ', '.join(item['id'] for item in index) or 'none yet'
            raise Refusal(f'There is no source {source_id}. Saved sources: {known}.')
        return entry, (self.folder / entry['local']).read_text(encoding='utf-8')

    def _refused(self, problems: list[str], left: int) -> tuple[bool, str]:
        """The answer to a hand-back the checks did not let through."""
        listed = '\n- '.join(problems)
        if left <= 0:
            return False, ('Not accepted, and it cannot be handed back again:\n- ' + listed
                           + '\n\nStop now, and say in your last message what you could '
                           'not put right.')
        more = f'\n\nIt can be handed back {left} more time(s).' if left <= 2 else ''
        return False, f'Not accepted. Fix these and hand it back again:\n- {listed}{more}'

    def offered(self) -> list[dict]:
        """The tools this job has a use for, as an agent is told about them."""
        job, names = self.job, ['list_inputs', 'read_input']
        if job['artifacts']:
            names += ['submit_artifact', 'submit_review']
        if job['fetch']:
            names.append('save_source')
        if job['fetch'] or self._index():
            names += ['read_source', 'search_source']
        if job['finding']:
            names.append('submit_finding')
        if job['ask']:
            names.append('ask_person')
        return [entry for entry in TOOLS if entry['name'] in names]

    def call(self, name: str, given) -> tuple[bool, str]:
        """Run one tool by name with the arguments an agent sent. Never raises."""
        given = given if isinstance(given, dict) else {}
        if name not in NAMES:
            outcome = (False, f'There is no tool called {name}.')
        else:
            try:
                return getattr(self, name)(**given)
            except Exception as failure:  # the worker is told; the server keeps running
                outcome = (False, 'The tool failed and nothing was kept '
                           f'({type(failure).__name__}: {failure}).')
        self._log(str(name), given, outcome)
        return outcome

    # --- inputs ---

    @tool
    def list_inputs(self):
        """What the job was given to read."""
        lines = []
        for entry in self.job['inputs']:
            count = len(parts(self._input(entry)))
            lines.append(f"- {entry['name']}: {entry['chars']:,} characters"
                         + (f', in {count} parts' if count > 1 else ''))
        saved = [f"- {entry['id']}: \"{entry['title']}\", {entry['chars']:,} characters"
                 for entry in self._index()]
        if not lines and not saved:
            return True, 'This job has no inputs. Everything you need is in your task.'
        text = 'Inputs, read with read_input:\n' + '\n'.join(lines) if lines else ''
        if saved:
            text += ('\n\n' if text else '') + ('Saved sources, read with read_source and '
                                               'search_source:\n' + '\n'.join(saved))
        return True, text

    def _input(self, entry: dict) -> str:
        return (self.folder / entry['file']).read_text(encoding='utf-8')

    @tool
    def read_input(self, name, part=1):
        """One input, or one part of a long one."""
        wanted = str(name).strip()
        entry = next((item for item in self.job['inputs'] if item['name'] == wanted), None)
        if entry is None:
            known = ', '.join(item['name'] for item in self.job['inputs']) or 'none'
            raise Refusal(f'There is no input called "{wanted}". This job\'s inputs: '
                          f'{known}.')
        pieces, number = parts(self._input(entry)), whole(part, 'part')
        if not 1 <= number <= len(pieces):
            raise Refusal(f'"{wanted}" has {len(pieces)} part(s); there is no part '
                          f'{number}.')
        if len(pieces) == 1:
            return True, pieces[0]
        rest = (f'; ask for part {number + 1} for more' if number < len(pieces)
                else '; this is the last part')
        return True, f'[{wanted}: part {number} of {len(pieces)}{rest}]\n\n{pieces[number - 1]}'

    # --- drafts ---

    @tool
    def submit_artifact(self, name, text):
        """Hand back a draft. It is checked; what is wrong with it comes back to fix."""
        wanted = self.job['artifacts']
        if not wanted:
            raise Refusal('This job has no draft to hand back.')
        name = str(name).strip()
        if name not in wanted:
            raise Refusal(f'This job hands back {", ".join(wanted)}, not "{name}". Use '
                          'that name.')
        if not isinstance(text, str) or not text.strip():
            raise Refusal('The text is empty. Hand back the whole draft.')
        self._allowed(name, name)
        spec = wanted[name]
        problems, ran, warnings, kept = VALIDATORS[spec['kind']](text, spec)
        left = self._count(name, problems)
        if problems:
            return self._refused(problems, left)
        file = f"accepted/{slug(name)}{EXTENSIONS.get(spec['kind'], '.md')}"
        _write(self.folder / file, kept)
        index = home.read_json(self.folder / 'accepted' / 'artifacts.json', {})
        index[name] = {'kind': spec['kind'], 'file': file, 'checks': ran,
                       'warnings': warnings, 'at': home.now()}
        home.write_json(self.folder / 'accepted' / 'artifacts.json', index)
        noted = ('' if not warnings else ' Noted for the person who reviews it:\n- '
                 + '\n- '.join(warnings) + '\nHand it back again only if one of these is '
                 'a mistake you can put right.')
        return True, f'Accepted: {name}.{noted}'

    @tool
    def submit_review(self, text):
        """The worker's own notes on its draft, shown at the gate as its judgment."""
        if not self.job['artifacts']:
            raise Refusal('This job has no draft, so there is nothing to write notes on.')
        if not home.read_json(self.folder / 'accepted' / 'artifacts.json', {}):
            raise Refusal('Hand the draft back first. Write your notes once it has been '
                          'accepted.')
        if not isinstance(text, str) or not text.strip():
            raise Refusal('Your notes are empty.')
        if len(text) > NOTES:
            raise Refusal(f'Your notes are {len(text):,} characters. Keep them under '
                          f'{NOTES:,}.')
        _write(self.folder / 'accepted' / 'review.md', text.strip() + '\n')
        return True, ('Your notes were kept. The person who reviews the draft will see them '
                      'as your judgment.')

    # --- sources ---

    @tool
    def save_source(self, url):
        """Fetch a public page or PDF, keep it, and return the start of its text."""
        if not self.job['fetch']:
            raise Refusal('This job cannot fetch pages. Work from what you were given.')
        url, index = str(url).strip(), self._index()
        known = next((item for item in index if url in (item['url'], item.get('asked'))), None)
        if known:
            return True, self._shown(known, 'Already saved')
        if len(index) >= MAX_SOURCES:
            raise Refusal(f'This job has saved {MAX_SOURCES} sources, which is the most it '
                          'may. Work from those.')
        final, headers, data = self._fetch(url)
        entry = self._keep(url, final, headers, data, len(index) + 1)
        home.write_json(self.folder / 'sources' / 'index.json', [*index, entry])
        return True, self._shown(entry, 'Saved')

    def _shown(self, entry: dict, verb: str) -> str:
        text = (self.folder / entry['local']).read_text(encoding='utf-8')
        more = '' if len(text) <= WINDOW else (
            f'\n\n[{len(text) - WINDOW:,} more characters. Use search_source to find a '
            'passage and read_source to read around it.]')
        return (f"{verb} as {entry['id']}: \"{entry['title']}\", {len(text):,} "
                f'characters.\n\n{text[:WINDOW]}{more}')

    def _checked(self, url: str) -> list[str]:
        """The public addresses a web address leads to. Refuses any other kind."""
        try:
            target = urllib.parse.urlsplit(url)
            host, signed = target.hostname, target.username or target.password
        except ValueError:
            raise Refusal('That is not a web address.')
        if len(url) > ADDRESS:
            raise Refusal(f'That address is longer than {ADDRESS:,} characters, so it was not '
                          'fetched.')
        if target.scheme not in ('http', 'https') or not host:
            raise Refusal('Only http and https addresses can be saved.')
        if signed:
            raise Refusal('That address carries a name or password. Give it without them.')
        try:
            addresses = self.resolver(host)
        except (OSError, UnicodeError) as failure:
            raise Refusal(f'Could not look up {host} ({failure}).')
        if not addresses or not all(public(address) for address in addresses):
            raise Refusal('That address is not on the public internet, so it was not '
                          'fetched.')
        return addresses

    def _fetch(self, url: str) -> tuple[str, dict, bytes]:
        """A page's final address, headers and body, with every hop on the way checked."""
        for _ in range(MAX_HOPS + 1):
            status, headers, data = self._ask(url, self._checked(url))
            if status in REDIRECTS and headers.get('location'):
                url = urllib.parse.urljoin(url, headers['location'])
                continue
            if not 200 <= status < 300:
                said = http.client.responses.get(status, '')
                raise Refusal(f'The site answered {status} {said}'.rstrip()
                              + '. The page was not saved.')
            data = unpacked(data, headers.get('content-encoding', ''))
            if len(data) > MAX_BYTES:
                raise Refusal(f'That is larger than {MAX_BYTES // 1_000_000} MB, so it was '
                              'not saved. Look for a smaller page that says the same.')
            return url, headers, data
        raise Refusal('That address redirected too many times. It was not saved.')

    def _ask(self, url: str, addresses: list[str]) -> tuple[int, dict, bytes]:
        """One request, trying each of the host's addresses until one connects."""
        failure = None
        for address in addresses:
            try:
                return self.opener(url, address, MAX_BYTES)
            except (OSError, http.client.HTTPException) as failed:
                failure = getattr(failed, 'reason', None) or failed
        raise Refusal(f'Could not fetch the page ({failure}). It was not saved.')

    def _keep(self, asked: str, url: str, headers: dict, data: bytes, number: int) -> dict:
        """Store a fetched page and its text snapshot, and describe them."""
        kind = headers.get('content-type', 'text/html')
        base = kind.partition(';')[0].strip().lower()
        target = urllib.parse.urlsplit(url)
        digest = hashlib.sha256(data).hexdigest()
        stem = f'sources/{slug(target.hostname)}-{digest[:12]}'
        pdf = data[:5] == b'%PDF-' or base == 'application/pdf'
        if not pdf and not base.startswith('text/') and base not in TEXT_TYPES:
            raise Refusal(f'That address holds {base}, not a page or a PDF. It was not '
                          'saved.')
        original = stem + ('.pdf' if pdf else '.html' if 'html' in base else '.raw')
        (self.folder / 'sources').mkdir(exist_ok=True)
        (self.folder / original).write_bytes(data)
        try:
            text, title = (self._pdf(self.folder / original, target) if pdf
                           else page_text(data, kind))
            if not text.strip():
                raise Refusal('That page has no readable text; it may need a browser to '
                              'show it. It was not saved. Look for the same content '
                              'elsewhere.')
        except Refusal:
            (self.folder / original).unlink(missing_ok=True)
            raise
        _write(self.folder / (stem + '.txt'), text)
        return {'id': f's{number}', 'url': url, 'asked': asked,
                'title': clip(title or target.hostname, 300), 'chars': len(text),
                'file': stem + '.txt',
                'local': stem + '.txt', 'original': original, 'sha256': digest,
                'offered': False, 'supplied': None, 'saved_at': home.now()}

    def _pdf(self, path: Path, target) -> tuple[str, str]:
        """The text of a saved PDF, and the file name it goes by."""
        text = self.pdf(path)
        if text is None:
            raise Refusal('That is a PDF, and this computer has no PDF reader (pdftotext). '
                          'Look for the same content as a web page.')
        return tidy(text), urllib.parse.unquote(target.path.rsplit('/', 1)[-1])

    @tool
    def read_source(self, source_id, offset=0, length=WINDOW):
        """Part of a saved source, from a character offset."""
        entry, text = self._source(source_id)
        start = max(0, whole(offset, 'offset'))
        size = min(max(1, whole(length, 'length')), WINDOW)
        if start >= len(text):
            raise Refusal(f"{entry['id']} has {len(text):,} characters; there is nothing "
                          f'at {start:,}.')
        end = min(len(text), start + size)
        return True, (f"[{entry['id']}: characters {start:,} to {end:,} of {len(text):,}]"
                      f'\n\n{text[start:end]}')

    @tool
    def search_source(self, source_id, query):
        """Where a word or phrase appears in a saved source."""
        entry, text = self._source(source_id)
        wanted = ' '.join(str(query).lower().split())
        if not wanted:
            raise Refusal('Say what to look for.')
        found, low, start = [], text.lower(), 0
        while len(found) < 8:
            at = low.find(wanted, start)
            if at < 0:
                break
            found.append(f'[offset {at}] …{text[max(0, at - 250):at + 450]}…')
            start = at + len(wanted)
        if not found:
            return True, f"No match in {entry['id']}. Try fewer or different words."
        return True, '\n\n'.join(found)

    # --- findings ---

    @tool
    def submit_finding(self, item, status, summary, limits='', evidence=None):
        """Hand back the finding for the job's question, with exact quotes."""
        wanted = self.job['finding']
        if not wanted:
            raise Refusal('This job does not answer a research question.')
        if str(item).strip() != wanted:
            raise Refusal(f'This job answers {wanted}, not "{item}".')
        self._allowed('finding', 'This finding')
        passages = self._passages(evidence)
        problems, kept = [], []
        if status not in STATUSES:
            problems.append('status must be one of: ' + ', '.join(STATUSES) + '.')
        if not isinstance(summary, str) or not summary.strip():
            problems.append('The summary is empty.')
        elif len(summary) > SUMMARY:
            problems.append(f'The summary is {len(summary):,} characters. Keep it under '
                            f'{SUMMARY:,}, and to what the quotes support.')
        limits = str(limits or '').strip() or 'none'
        if len(limits) > 4000:
            problems.append('The limits are too long. Keep them under 4,000 characters.')
        if status in ('supported', 'contradicted') and not passages:
            problems.append(f'A {status} finding needs at least one quoted passage.')
        if len(passages) > PASSAGES:
            problems.append(f'Give at most {PASSAGES} passages; choose the ones that carry '
                            'the point.')
        for number, passage in enumerate(passages[:PASSAGES], start=1):
            placed = self._placed(number, passage, problems)
            if placed:
                kept.append(placed)
        left = self._count('finding', problems)
        if problems:
            return self._refused(problems, left)
        home.write_json(self.folder / 'accepted' / 'finding.json', {
            'item': wanted, 'status': status, 'summary': summary.strip(), 'limits': limits,
            'evidence': kept})
        return True, (f'Accepted: the finding for {wanted}, with {len(kept)} quoted '
                      'passage(s).')

    def _passages(self, evidence) -> list:
        """The passages an agent sent, which may have arrived as JSON text."""
        if isinstance(evidence, str) and evidence.strip():
            try:
                evidence = json.loads(evidence)
            except ValueError:
                raise Refusal('evidence must be a list of passages, each with source_id and '
                              'quote.')
        if evidence is None or evidence == '':
            return []
        if not isinstance(evidence, list):
            raise Refusal('evidence must be a list of passages, each with source_id and '
                          'quote.')
        return evidence

    def _placed(self, number: int, passage, problems: list[str]) -> dict | None:
        """One passage with its place in its source, or None with the problem added."""
        if not isinstance(passage, dict):
            problems.append(f'Passage {number} needs a source_id and a quote.')
            return None
        try:
            entry, text = self._source(passage.get('source_id'))
        except Refusal as missing:
            problems.append(f'Passage {number}: {missing}')
            return None
        quote = passage.get('quote') if isinstance(passage.get('quote'), str) else ''
        found = place(text, quote.strip())
        if found is None:
            problems.append(f"Passage {number}: the quote is not in {entry['id']} as "
                            'written. Copy it from the saved text with nothing left out '
                            'or added, and no "..." in it.')
            return None
        start, exact = found
        if not QUOTE[0] <= len(exact) <= QUOTE[1]:
            problems.append(f'Passage {number}: the quote is {len(exact)} characters. '
                            f'Quote the whole sentence that makes the point, between '
                            f'{QUOTE[0]} and {QUOTE[1]} characters.')
            return None
        placed = {'file': entry['file'], 'title': entry['title'] or entry['url'],
                  'origin': entry['url'], 'quote': exact, 'start': start,
                  'locator': f'characters {start} to {start + len(exact)}'}
        if entry.get('supplied'):
            placed['source_id'] = entry['supplied']
        return placed

    # --- questions ---

    @tool
    def ask_person(self, question):
        """End the job with a question for the person."""
        if not self.job['ask']:
            raise Refusal('Nobody can answer questions in this job. Do what you can, and '
                          'say what is missing when you hand back.')
        if not isinstance(question, str) or not question.strip():
            raise Refusal('The question is empty.')
        if len(question) > QUESTION:
            raise Refusal(f'The question is {len(question):,} characters. Ask one thing, in '
                          f'under {QUESTION:,}.')
        home.write_json(self.folder / 'accepted' / 'question.json',
                        {'question': question.strip(), 'at': home.now()})
        home.write_json(self.folder / 'state.json', {**self._state(), 'ended': 'question'})
        return True, ('Your question was recorded, and this job is over. Stop now and call '
                      'no other tool. The answer will be there when the work is started '
                      'again.')


# --- what an agent is told about the tools -----------------------------------------------

def _described(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {'name': name, 'description': description,
            'inputSchema': {'type': 'object', 'properties': properties,
                            'required': required}}


TEXT, NUMBER = {'type': 'string'}, {'type': 'integer'}
TOOLS = [
    _described('list_inputs', 'List what this job was given to read: its inputs by name, '
               'and any sources already saved.', {}, []),
    _described('read_input', 'Read one input by name. A long input comes in parts: ask for '
               'part 2, 3 and so on.', {'name': TEXT, 'part': NUMBER}, ['name']),
    _described('submit_artifact', 'Hand back a finished draft under the name your task '
               'gives. It is checked: if anything is wrong you are told what, to fix it '
               'and hand it back again.', {'name': TEXT, 'text': TEXT}, ['name', 'text']),
    _described('submit_review', 'After your draft is accepted, give your own honest notes '
               'on it for the person who will review it: where it is weakest, what is '
               'missing, what to look at.', {'text': TEXT}, ['text']),
    _described('save_source', 'Fetch a public web page or PDF, keep it, and return the '
               'start of its text. Only sources saved this way count as evidence.',
               {'url': TEXT}, ['url']),
    _described('read_source', 'Read part of a saved source, from a character offset.',
               {'source_id': TEXT, 'offset': NUMBER, 'length': NUMBER}, ['source_id']),
    _described('search_source', 'Find a word or phrase in a saved source. Each match comes '
               'with its offset and the text around it.',
               {'source_id': TEXT, 'query': TEXT}, ['source_id', 'query']),
    _described('submit_finding', 'Hand back the finding for your research question. Each '
               'quote must be copied exactly from a saved source; its place is worked out '
               'for you.',
               {'item': TEXT, 'status': {'type': 'string', 'enum': list(STATUSES)},
                'summary': TEXT, 'limits': TEXT,
                'evidence': {'type': 'array', 'items': {
                    'type': 'object', 'properties': {'source_id': TEXT, 'quote': TEXT},
                    'required': ['source_id', 'quote']}}},
               ['item', 'status', 'summary']),
    _described('ask_person', 'Ask the person one question you cannot work without an '
               'answer to. This ends your job: stop as soon as you have asked.',
               {'question': TEXT}, ['question']),
]
NAMES = tuple(entry['name'] for entry in TOOLS)


# --- the server ------------------------------------------------------------------------

EMPTY = {'resources/list': {'resources': []}, 'prompts/list': {'prompts': []},
         'resources/templates/list': {'resourceTemplates': []}, 'ping': {}}


def answer(tools: WorkerTools, message) -> dict | None:
    """The reply to one message from an agent, or None when it expects none."""
    if not isinstance(message, dict) or message.get('id') is None:
        return None  # a notification, or nothing this server understands
    method, params = message.get('method'), message.get('params')
    params = params if isinstance(params, dict) else {}
    if method == 'initialize':
        result = {'protocolVersion': params.get('protocolVersion') or '2024-11-05',
                  'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'runner', 'version': str(SCHEMA)}}
    elif method == 'tools/list':
        result = {'tools': tools.offered()}
    elif method == 'tools/call':
        ok, text = tools.call(params.get('name'), params.get('arguments'))
        result = {'content': [{'type': 'text', 'text': text}], 'isError': not ok}
    elif method in EMPTY:
        result = EMPTY[method]
    else:
        return {'jsonrpc': '2.0', 'id': message['id'],
                'error': {'code': -32601, 'message': f'No such method: {method}'}}
    return {'jsonrpc': '2.0', 'id': message['id'], 'result': result}


def serve(tools: WorkerTools, lines, out) -> None:
    """Answer an agent over standard input and output until it closes the connection."""
    for line in lines:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        reply = answer(tools, message)
        if reply is not None:
            out.write(json.dumps(reply) + '\n')
            out.flush()


def main(argv: list[str] | None = None) -> int:
    options = argparse.ArgumentParser(description='Serve one job\'s worker tools.')
    options.add_argument('--job', required=True)
    args = options.parse_args(argv)
    try:
        tools = WorkerTools(Path(args.job))
    except WorkspaceError as refusal:
        print(refusal, file=sys.stderr)
        return 2
    sys.stdin.reconfigure(encoding='utf-8', errors='replace')
    sys.stdout.reconfigure(encoding='utf-8', newline='\n')
    serve(tools, sys.stdin, sys.stdout)
    return 0


if __name__ == '__main__':
    sys.exit(main())
