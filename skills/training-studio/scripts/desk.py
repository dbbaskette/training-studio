"""The page: every training on this computer, and the place a gate is decided.

The server answers on 127.0.0.1 only. It reads through the same functions the command line
uses, so the page shows what the assistant sees. Reading is GET. The few things that change
a training are POST with a JSON body, accepted only from the page itself, and they go through
the same function as the command line's `approve` and `skip`, recorded as made on the page.
"""
from __future__ import annotations

import codecs
import difflib
import json
import re
import secrets
import socketserver
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import checks
import computer
import home
import training
import workspace

HOST = '127.0.0.1'
TOKEN_HEADER = 'X-Training-Studio-Token'
PAGE_DIR = Path(__file__).resolve().parent / 'desk'
PAGE = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/index.html': ('index.html', 'text/html; charset=utf-8'),
    '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
    '/markdown.js': ('markdown.js', 'text/javascript; charset=utf-8'),
    '/style.css': ('style.css', 'text/css; charset=utf-8'),
}
JSON = 'application/json; charset=utf-8'
SECURITY_HEADERS = {
    'Content-Security-Policy': "default-src 'self'",
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer',
    'Cache-Control': 'no-store',
}
STATUSES = ('approved', 'draft', 'stale', 'not-started', 'skipped', 'unavailable')
TEXT_SUFFIXES = ('.md', '.json')
PREVIEW_LIMIT = 1_000_000
BODY_LIMIT = 64_000      # bytes a POST may carry
NOTE_LIMIT = 10_000      # characters in a note or a reason
CHANGE_LIMIT = 2_000     # lines of comparison sent to the page
COMPUTER_CACHE = 60      # seconds a look at this computer is reused
READS = ('/api/trainings', '/api/training', '/api/file', '/api/gate', '/api/computer')
WRITES = ('/api/decide', '/api/approval', '/api/computer')

# --- the page's words -----------------------------------------------------------
# Nothing on the page says "artifact", "stale" or "lineage". These are what it says instead.

WORDS = {'approved': 'approved', 'draft': 'not approved yet', 'stale': 'out of date',
         'not-started': 'not started', 'skipped': 'left out',
         'unavailable': 'could not be made'}
STAGE_NAMES = {'intake': 'Start', 'research-plan': 'Questions', 'research': 'Research',
               'blueprint': 'Blueprint', 'document': 'Guide', 'brief': 'Brief',
               'deck': 'Deck', 'scenario': 'Practice', 'yoodli': 'Yoodli',
               'package': 'Wrap-up'}
STAGE_STATES = {'done': 'done', 'current': 'in progress', 'review': 'yours to review',
                'not-started': 'not started', 'left-out': 'left out',
                'unavailable': 'could not be made'}
BACK_TO_CHAT = ('Your assistant picks this up when you go back to the conversation and tell '
                'it you have decided. You can close this page.')
SAID = {
    'approve': 'Approved.',
    'accept': 'Accepted as it is.',
    'revise': 'Your changes are noted. Once they are made, the new version comes back here '
              'for your review.',
    'rebuild': 'A rebuild is asked for. The new version comes back here for your review.',
    'skip': 'This stage is left out. You can bring it back from the training at any time.',
    'restore': 'This stage is back.',
}


class Refusal(Exception):
    """A request the page will not answer, with the HTTP status to refuse it with."""

    def __init__(self, status: int, message: str, allow: str | None = None):
        super().__init__(message)
        self.status = status
        self.allow = allow


def describe(failure: Exception) -> str:
    """An error in the words the command line would use for it."""
    if isinstance(failure, (workspace.WorkspaceError, Refusal)):
        return str(failure)
    return f'{type(failure).__name__}: {failure}'


def as_json(status: int, value) -> tuple[int, str, bytes]:
    # "<" never leaves as itself, so no reader can take an answer for markup.
    text = json.dumps(value, sort_keys=True).replace('<', '\\u003c')
    return status, JSON, text.encode('utf-8')


def named(name: str) -> str:
    """An artifact in the page's words, ready to start a sentence."""
    return workspace.sentence(workspace.label(name))


def _reword(pattern: str, build):
    return re.compile(pattern, re.DOTALL), build


REWORDED = (
    _reword(r'(\S+) is (draft|stale|not-started)',
            lambda m: f'{named(m[1])} is {WORDS[m[2]]}'),
    _reword(r'(\w+) was skipped',
            lambda m: f'{workspace.sentence(workspace.STAGE_LABELS.get(m[1], m[1]))} '
                      'was left out'),
    _reword(r'(\w+) unavailable: (.*)',
            lambda m: f'{workspace.sentence(workspace.STAGE_LABELS.get(m[1], m[1]))} '
                      f'could not be made: {m[2]}'),
    _reword(r'A question is waiting on the user: (.*)',
            lambda m: f'A question is waiting for you: {m[1]}'),
    _reword(r'The user asked for (changes|a rebuild) to (\S+), and that is still to do',
            lambda m: f'You asked for {m[1]} to {workspace.label(m[2])}, and that is still '
                      'to do'),
    _reword(r'(\S+) was accepted as it was after its inputs changed: (.*)',
            lambda m: f'{named(m[1])} was accepted as it was, after what it was built from '
                      f'changed: {m[2]}'),
    _reword(r'(\S+) has no export(.*)', lambda m: f'{named(m[1])} has no Word copy{m[2]}'),
    _reword(r'The export of (\S+) is out of date',
            lambda m: f'The Word copy of {workspace.label(m[1])} is out of date'),
    _reword(r'Yoodli handoff incomplete: no export of (\S+)',
            lambda m: f'The Yoodli handoff is incomplete: {workspace.label(m[1])} has no '
                      'Word copy'),
    _reword(r'The Google Doc of (\S+) is behind its file',
            lambda m: f'The Google Doc of {workspace.label(m[1])} is behind its file'),
    _reword(r'(\S+) is not in a Google Doc(.*)',
            lambda m: f'{named(m[1])} is not in a Google Doc{m[2]}'),
    _reword(r'(\S+\.\S+) failed', lambda m: f'A check failed: {m[1]}'),
    _reword(r'(\S+\.\S+) could not run: (.*)',
            lambda m: f'A check could not run ({m[1]}): {m[2]}'),
)


def plainly(reason: str) -> str:
    """One of the helper's reasons, in the page's words. Anything else is left as it is."""
    for pattern, build in REWORDED:
        found = pattern.fullmatch(reason)
        if found:
            return build(found)
    return reason


# --- what the page reads --------------------------------------------------------

def read(root: Path) -> tuple[dict, dict]:
    """A training's status report and check result, as the command line gives them.

    The same as `status` and `check`, except that reading here is not remembered in the
    registry: looking at a training writes nothing.
    """
    return training.describe(root), training.run_checks(root)


def touched(root: Path, seen: str) -> str:
    """When a training was last seen or its record last changed, whichever is later."""
    events = workspace.load(root)['events']
    stamps = [event['at'] for event in events
              if isinstance(event, dict) and isinstance(event.get('at'), str)]
    return max([seen, *stamps])


def known(entry: dict) -> dict:
    """What the registry says about a training, which is all there is if its record is broken."""
    seen = entry.get('seen_at')
    return {'path': entry['path'], 'title': entry.get('title'), 'levels': entry.get('levels'),
            'touched_at': seen if isinstance(seen, str) else ''}


def waiting(report: dict) -> dict | None:
    """What a training is waiting on its user for: something at a gate, a question, or nothing.

    The gate is the one the assistant recorded. Where it recorded only a question, the gate
    is taken to be the first file in pipeline order that is not approved yet or out of date.
    """
    state, question = report['artifacts'], report.get('pending_question')
    gate = report.get('gate')
    recorded = state.get(gate) in ('draft', 'stale')
    if not recorded:
        if not question:
            return None
        gate = next((name for name, status in state.items() if status in ('draft', 'stale')),
                    None)
    return {'artifact': gate, 'label': workspace.label(gate) if gate else None,
            'question': question, 'recorded': recorded}


def stage_row(report: dict, ready: bool, gate: str | None) -> list[dict]:
    """The row of stages, the same everywhere: each done, in progress, yours to review, not
    started, left out, or could not be made."""
    wanted, state = report['settings']['stages'], report['artifacts']
    by_stage: dict[str, list[str]] = {}
    for name, status in state.items():
        base = workspace.split(name)[0].partition(':')[0]
        by_stage.setdefault(base, []).append(status)
    review = workspace.split(gate)[0].partition(':')[0] if gate else None
    row = []
    for stage in workspace.STAGES[:-1]:
        found = by_stage.get(stage, [])
        if stage in workspace.OPTIONAL and stage not in wanted:
            continue
        if stage in workspace.SKIPPABLE and stage not in wanted:
            now = 'left-out'
        elif stage in report['unavailable_stages']:
            now = 'unavailable'
        elif stage == review:
            now = 'review'
        elif stage == 'package':
            now = ('done' if ready else
                   'current' if report['stage'] in ('package', 'done') else 'not-started')
        elif found and all(status == 'approved' for status in found):
            now = 'done'
        elif stage == report['stage'] or any(status != 'not-started' for status in found):
            now = 'current'
        else:
            now = 'not-started'
        row.append({'stage': stage, 'name': STAGE_NAMES[stage], 'state': now,
                    'words': STAGE_STATES[now]})
    return row


def summary(report: dict, result: dict) -> dict:
    """Where a training is, for the home and status screens: whether it needs its user, one
    sentence saying what is happening, and its row of stages."""
    needs, requests = waiting(report), report['requests']
    if needs:
        now = 'needs-you'
        if needs['artifact'] is None:
            says = f"A question is waiting for you: {needs['question']}"
        elif report['artifacts'][needs['artifact']] == 'stale':
            says = f"{named(needs['artifact'])} is out of date and waiting for your decision."
        else:
            says = f"{named(needs['artifact'])} is waiting for your review."
    elif result['ready']:
        now = 'finished'
        left = len(result['limitations'])
        says = ('Finished. Everything is approved.' if not left else
                f'Finished, with {left} thing{"" if left == 1 else "s"} left out or limited.')
    else:
        now = 'in-progress'
        if requests:
            latest = requests[-1]
            asked = 'a rebuild of' if latest.get('kind') == 'rebuild' else 'changes to'
            says = (f"You asked for {asked} {workspace.label(str(latest.get('artifact')))}. "
                    'Your assistant does that when you go back to the conversation.')
        else:
            says = (report.get('next_step')
                    or f"At the {STAGE_NAMES.get(report['stage'], 'last')} stage.")
    return {'state': now, 'sentence': says, 'waiting': needs,
            'approval': report['approval'], 'requests': len(requests),
            'stage_name': STAGE_NAMES.get(report['stage'], 'Finished'),
            'stages': stage_row(report, result['ready'], needs and needs['artifact'])}


def trainings() -> list[dict]:
    """Every training in the registry, most recently touched first."""
    listed = []
    for entry in home.trainings():
        item = known(entry)
        root = Path(entry['path'])
        try:
            report, result = read(root)
            counts = dict.fromkeys(STATUSES, 0)
            for state in report['artifacts'].values():
                counts[state] = counts.get(state, 0) + 1
            item.update(title=report['title'], levels=report['levels'], stage=report['stage'],
                        touched_at=touched(root, item['touched_at']), counts=counts,
                        ready=result['ready'], blocking=len(result['blocking']),
                        **summary(report, result))
        except Exception as failure:  # one record that cannot be read must not hide the rest
            item['error'] = describe(failure)
        listed.append(item)
    return sorted(listed, key=lambda item: item['touched_at'], reverse=True)


def registered(path: str) -> dict:
    """The registry's entry for `path`. Any other folder is refused, whatever it holds."""
    for entry in home.trainings():
        if entry['path'] == path:
            return entry
    raise Refusal(HTTPStatus.FORBIDDEN, 'That folder is not a training this computer knows.')


def files(report: dict, needs: dict | None) -> list[dict]:
    """Every file of a training in pipeline order, in the page's words."""
    exports, docs = report['exports'], report.get('google_docs') or {}
    return [{'artifact': name, 'label': named(name), 'level': workspace.split(name)[1],
             'status': status, 'words': WORDS[status], 'file': report['files'][name],
             'waiting': bool(needs) and needs['artifact'] == name,
             'asked': any(request.get('artifact') == name for request in report['requests']),
             'word_copy': exports.get(name), 'google_doc': docs.get(name)}
            for name, status in report['artifacts'].items()]


def left_out(report: dict) -> list[dict]:
    """The stages a training leaves out, each of which the page can bring back."""
    wanted = report['settings']['stages']
    return [{'stage': stage, 'name': workspace.sentence(workspace.STAGE_LABELS[stage]),
             'optional': stage in workspace.OPTIONAL}
            for stage in workspace.SKIPPABLE if stage not in wanted]


def detail(path: str) -> dict:
    """One registered training: its status report, its check result, and both in plain words."""
    item = known(registered(path))
    root = Path(path)
    try:
        report, result = read(root)
        about = summary(report, result)
        item.update(title=report['title'], levels=report['levels'],
                    touched_at=touched(root, item['touched_at']), status=report, check=result,
                    **about,
                    view={'files': files(report, about['waiting']),
                          'left_out': left_out(report),
                          'blocking': [plainly(reason) for reason in result['blocking']],
                          'limitations': [plainly(reason) for reason in result['limitations']],
                          'warnings': result['warnings']})
    except Exception as failure:  # shown on the page, like the same training in the list
        item['error'] = describe(failure)
    return item


def artifact_of(path: str, name: str) -> tuple[Path, dict]:
    """A registered training and its record, once `name` is known to be one of its artifacts."""
    registered(path)
    root = Path(path)
    session = workspace.load(root)
    if name not in workspace.artifact_names(root, session):
        raise Refusal(HTTPStatus.FORBIDDEN, f'{name} is not an artifact of this training.')
    return root, session


def inside(root: Path, relative: str) -> Path:
    """A file of a training, refused if it leads out of the training's folder."""
    file = (root / relative).resolve()
    if root.resolve() not in file.parents:
        raise Refusal(HTTPStatus.FORBIDDEN, f'{relative} leads outside the training folder.')
    return file


def text_of(file: Path) -> tuple[str, bool] | None:
    """The start of a file as text and whether it was cut short, or None if it is not text."""
    if file.suffix not in TEXT_SUFFIXES:
        return None
    with open(file, 'rb') as stream:
        data = stream.read(PREVIEW_LIMIT)
    truncated = file.stat().st_size > len(data)
    try:
        # A cut can fall inside a character; the decoder holds the loose bytes back.
        text = codecs.getincrementaldecoder('utf-8')().decode(data, final=not truncated)
    except UnicodeDecodeError:
        return None
    return None if '\0' in text else (text, truncated)


def preview(path: str, name: str) -> dict:
    """The text of one artifact's file, or just its name and size if it is not text."""
    root, session = artifact_of(path, name)
    relative = workspace.artifact(root, session, name)['file']
    file = inside(root, relative)
    if not file.is_file():
        raise Refusal(HTTPStatus.NOT_FOUND, f'{relative} does not exist yet.')
    shown = {'artifact': name, 'file': relative, 'size': file.stat().st_size, 'binary': True}
    found = text_of(file)
    if found is None:
        return shown
    return {**shown, 'binary': False, 'text': found[0], 'truncated': found[1]}


# --- a gate ---------------------------------------------------------------------

def questions(text: str) -> dict | None:
    """A research plan as its questions, or None if it cannot be read as one."""
    try:
        plan = json.loads(text)
        listed = [{'id': str(item['id']), 'question': str(item['question'])}
                  for item in plan['items']]
    except (ValueError, KeyError, TypeError):
        return None
    return {'topic': str(plan.get('topic') or ''), 'scope': str(plan.get('scope') or ''),
            'questions': listed}


def document(root: Path, session: dict, name: str) -> dict:
    """What a gate shows for an artifact: a document to read, a list of questions, or, for
    a deck, its name and size."""
    relative = workspace.artifact(root, session, name)['file']
    file = inside(root, relative)
    if not file.is_file():
        return {'kind': 'missing', 'file': relative}
    shown = {'file': relative, 'size': file.stat().st_size}
    found = text_of(file)
    if found is None:
        return {**shown, 'kind': 'file'}
    text, truncated = found
    plan = questions(text) if name == 'research-plan' and not truncated else None
    if plan is not None:
        return {**shown, 'kind': 'questions', **plan}
    kind = 'link' if workspace.split(name)[0] == 'deck' else 'markdown'
    return {**shown, 'kind': kind, 'text': text, 'truncated': truncated}


def lines_of(name: str, text: str) -> list[str]:
    """A file as the lines to compare: a research plan is compared question by question."""
    plan = questions(text) if name == 'research-plan' else None
    if plan is None:
        return text.splitlines()
    return [f"{item['id']}: {item['question']}" for item in plan['questions']]


def changes(root: Path, session: dict, name: str) -> dict:
    """A line comparison with the version last approved, when there is one."""
    approved = (session['artifacts'].get(name) or {}).get('approved')
    file = inside(root, workspace.artifact(root, session, name)['file'])
    current = workspace.sha256_file(file)
    if not approved or current is None:
        return {'available': False}
    shown = {'available': True, 'approved_at': approved.get('at'), 'rows': [],
             'same': approved['sha256'] == current, 'comparable': True, 'truncated': False}
    if shown['same']:
        return shown
    kept = workspace.history_file(root, name, approved['sha256'], file.suffix)
    before = text_of(kept) if kept.is_file() else None
    after = text_of(file)
    if before is None or after is None or before[1] or after[1]:
        return {**shown, 'comparable': False}
    rows = []
    for line in difflib.unified_diff(lines_of(name, before[0]), lines_of(name, after[0]),
                                     lineterm='', n=2):
        if line.startswith(('---', '+++')) and not rows:
            continue
        kind = {'@': 'gap', '+': 'added', '-': 'removed'}.get(line[:1], 'same')
        rows.append({'kind': kind, 'text': '' if kind == 'gap' else line[1:]})
    return {**shown, 'rows': rows[:CHANGE_LIMIT], 'truncated': len(rows) > CHANGE_LIMIT}


def latest_review(root: Path, name: str) -> str | None:
    """The latest entry in an artifact's review file: everything from its last `## ` heading."""
    relative = workspace.review_file(name)
    try:
        file = inside(root, relative)
    except Refusal:
        return None
    found = text_of(file) if file.is_file() else None
    if found is None:
        return None
    lines = found[0].splitlines()
    starts = [index for index, line in enumerate(lines) if line.startswith('## ')]
    entry = '\n'.join(lines[starts[-1]:] if starts else lines).strip()
    return entry or None


def out_of_date(root: Path, session: dict, name: str, state: dict) -> list[str]:
    """Why an artifact is out of date: what it was built from that has changed since."""
    spec = workspace.artifact(root, session, name)
    reasons = [f'{named(upstream)} is itself out of date.'
               for upstream in spec['upstream'] if state[upstream] == 'stale']
    built = (session['artifacts'].get(name) or {}).get('built_from') or {}
    now = workspace.inputs(root, session, name)
    for key in dict.fromkeys([*built, *now]):
        if built.get(key) == now.get(key):
            continue
        if key.startswith('setting:'):
            setting = key.partition(':')[2].replace('_', ' ')
            reasons.append(f'The {setting} setting has changed since this was made.')
        elif key == 'profile':
            reasons.append('The Yoodli field data has changed since this was made.')
        else:
            reasons.append(f'{named(key)} has changed since this was made.')
    return reasons


def offered(session: dict, spec: dict, name: str, state: dict) -> tuple[list[str], list[dict]]:
    """The decisions a gate offers for an artifact, and what has to be settled first."""
    status, wanted = state[name], session['settings']['stages']
    first = [{'artifact': upstream, 'label': workspace.label(upstream)}
             for upstream in spec['upstream'] if state[upstream] not in ('approved', 'skipped')]
    offers = []
    if status == 'draft' and not first:
        offers.append('approve')
    if status in ('draft', 'stale', 'approved'):
        offers += ['revise', 'rebuild']
    if status == 'stale' and not first:
        offers.append('accept')
    if status in ('skipped', 'unavailable'):
        offers.append('restore')
    elif spec['stage'] in workspace.SKIPPABLE and not (
            spec['stage'] in ('brief', 'scenario') and 'yoodli' in wanted):
        offers.append('skip')
    return offers, first


def gate(path: str, name: str) -> dict:
    """Everything the gate screen shows for one artifact of one training."""
    root, session = artifact_of(path, name)
    report, result = training.describe(root), training.run_checks(root, show_all=True)
    state, spec = report['artifacts'], workspace.artifact(root, session, name)
    about = summary(report, result)
    needs = about['waiting']
    here = bool(needs) and needs['artifact'] == name
    own = [outcome for outcome in result['checks']
           if checks.artifact_of(outcome['check']) == name]
    offers, first = offered(session, spec, name, state)
    approved = (session['artifacts'].get(name) or {}).get('approved') or {}
    return {
        'path': path, 'title': report['title'], 'levels': report['levels'],
        'approval': report['approval'], 'stages': about['stages'],
        'artifact': name, 'label': named(name), 'stage': spec['stage'],
        'stage_name': STAGE_NAMES[spec['stage']],
        'status': state[name], 'words': WORDS[state[name]], 'waiting': here,
        'question': report.get('pending_question') if here else None,
        'sha256': workspace.sha256_file(inside(root, spec['file'])),
        'document': document(root, session, name),
        'changes': changes(root, session, name),
        'checked': {'passed': sum(outcome['status'] == 'passed' for outcome in own),
                    'problems': [{'check': outcome['check'], 'problems': outcome['problems'],
                                  'words': ('could not run' if outcome['status'] == 'unavailable'
                                            else 'failed')}
                                 for outcome in own if outcome['status'] != 'passed']},
        'out_of_date': (out_of_date(root, session, name, state)
                        if state[name] == 'stale' else []),
        'unavailable': report['unavailable_stages'].get(spec['stage']),
        'review': latest_review(root, name),
        'asked': [request for request in report['requests'] if request.get('artifact') == name],
        'approved': ({'at': approved.get('at'), 'by': approved.get('by', 'chat')}
                     if state[name] == 'approved' else None),
        'decisions': offers, 'first': first,
    }


def next_up(listed: list[dict] | None = None) -> dict | None:
    """The next thing that needs the user, across every training, or None."""
    for item in trainings() if listed is None else listed:
        if item.get('state') == 'needs-you':
            return {'path': item['path'], 'title': item['title'],
                    'artifact': item['waiting']['artifact'], 'sentence': item['sentence']}
    return None


# --- what the page changes ------------------------------------------------------

def decide(path: str, target: str, decision: str, note: str | None, seen: str | None) -> dict:
    """Record a decision made on the page, through the function the command line uses."""
    registered(path)
    root = Path(path)
    session = workspace.load(root)
    if decision not in workspace.DECISIONS:
        raise Refusal(HTTPStatus.BAD_REQUEST, 'A decision is one of: '
                      + ', '.join(workspace.DECISIONS) + '.')
    stage = decision in ('skip', 'restore') and target in workspace.SKIPPABLE
    if not stage and target not in workspace.artifact_names(root, session):
        raise Refusal(HTTPStatus.FORBIDDEN, f'{target} is not an artifact of this training.')
    if session['settings']['approval'] != 'page':
        raise Refusal(HTTPStatus.CONFLICT, 'Decisions for this training are made in the '
                      'conversation. Move them to the page first.')
    if decision in ('approve', 'accept') and not seen:
        raise Refusal(HTTPStatus.BAD_REQUEST, 'Say which version was read, as `seen`.')
    outcome = training.decide(root, target, decision, note, by='page', seen=seen)
    return {'decided': outcome, 'said': f'{SAID[decision]} {BACK_TO_CHAT}', 'next': next_up()}


def move_approval(path: str, mode: str) -> dict:
    """Move a training's approval to the page, or back to the conversation."""
    registered(path)
    if mode not in workspace.APPROVAL:
        raise Refusal(HTTPStatus.BAD_REQUEST, 'Approval is one of: '
                      + ', '.join(workspace.APPROVAL) + '.')
    outcome = workspace.checkpoint(Path(path), approval=mode, by='page')
    return {'approval': outcome['settings']['approval']}


def uses_google() -> bool:
    """Whether any training here keeps a Google Doc or builds Google Slides."""
    for entry in home.trainings():
        try:
            settings = workspace.load(Path(entry['path']))['settings']
        except (workspace.WorkspaceError, OSError):
            continue
        if settings['deck_target'] == 'google' or 'google' in settings['copies']:
            return True
    return False


# --- the server -----------------------------------------------------------------

def allowed(target: str, reads=READS, writes=WRITES) -> str:
    """The methods an address answers, for the `Allow` header of a refusal."""
    path = target.partition('?')[0]
    methods = [method for method, paths in (('GET', (*PAGE, *reads)), ('POST', writes))
               if path in paths]
    return ', '.join(methods) or 'GET'


def text(sent: dict, name: str, needed: bool = True) -> str | None:
    """One field of a change, which must be text of a sensible length."""
    value = sent.get(name)
    if value is None and not needed:
        return None
    if not isinstance(value, str) or (needed and not value) or len(value) > NOTE_LIMIT:
        raise Refusal(HTTPStatus.BAD_REQUEST, f'Give {name} as text.')
    return value


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        """A reader that hangs up early gets no traceback: the command's output stays one line."""

    def server_bind(self):
        # The base class looks its own name up, which can ask the network. Nothing here does.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class Handler(BaseHTTPRequestHandler):
    timeout = 30  # seconds a connection may sit idle before it is dropped

    def version_string(self):
        return 'TrainingStudioDesk'

    def respond(self, body: bytes | None = None):
        allow = None
        try:
            reply = self.server.desk.answer(self.path, self.headers, self.command, body)
        except Refusal as refusal:
            reply, allow = as_json(refusal.status, {'error': str(refusal)}), refusal.allow
        except workspace.WorkspaceError as refusal:
            reply = as_json(HTTPStatus.CONFLICT, {'error': str(refusal)})
        except Exception as failure:  # answered like any other, never a dropped connection
            reply = as_json(HTTPStatus.INTERNAL_SERVER_ERROR, {'error': describe(failure)})
        self.reply(*reply, allow=allow)

    def do_GET(self):
        self.respond()

    def do_POST(self):
        """Read the body, up to the limit, and hand it over. A body that is too long, or
        whose length is not stated, is never read: the request is refused and the line closed."""
        length = self.headers.get('Content-Length', '')
        limit = self.server.desk.page.body_limit(self.path, self.headers)
        if not length.isdigit() or int(length) > limit:
            self.close_connection = True
            return self.respond(None)
        self.respond(self.rfile.read(int(length)))

    def refuse_method(self):
        allow = self.server.desk.page.allowed(self.path)
        self.close_connection = True
        self.reply(*as_json(HTTPStatus.METHOD_NOT_ALLOWED,
                            {'error': 'The page reads with GET and sends a decision with POST. '
                                      'Nothing else is answered.'}), allow=allow)

    do_HEAD = do_PUT = do_PATCH = do_DELETE = refuse_method
    do_OPTIONS = do_TRACE = do_CONNECT = refuse_method

    def reply(self, status: int, kind: str | None, body: bytes, allow: str | None = None):
        self.send_response(status)
        if kind:
            self.send_header('Content-Type', kind)
        if allow:
            self.send_header('Allow', allow)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def end_headers(self):
        """Every response leaves through here, so every response carries these."""
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    def send_error(self, code, message=None, explain=None):
        """The base class's own refusals, as JSON like the rest rather than as a page."""
        self.close_connection = True
        self.reply(*as_json(code, {'error': message or HTTPStatus(code).phrase}))

    def log_message(self, format, *args):
        """Nothing is logged: the command's output is one line, and stays one line."""


class Page:
    """What the page may ask for and what it is refused. It holds the key; it has no socket.

    A program that serves the same page with more behind it, as the runner does, makes a
    subclass: it adds addresses to `reads` and `writes`, answers them in `read` and `write`,
    and may add to what `trainings`, `detail`, `decide` and `move_approval` return. Every
    rule about who may ask stays here, in `answer` and `change`.
    """
    reads, writes = READS, WRITES

    def __init__(self, port: int):
        self.token = secrets.token_urlsafe(32)
        self.port = port
        self.hosts = {f'{name}:{port}' for name in (HOST, 'localhost')}
        self._looking = threading.Lock()
        self._looked: tuple[float, dict] | None = None

    def computer(self, look: bool) -> dict | None:
        """The last look at this computer. `look` takes a new one unless one was just taken."""
        if look:
            with self._looking:
                seen = self._looked
                if not seen or time.monotonic() - seen[0] >= COMPUTER_CACHE:
                    self._looked = (time.monotonic(), computer.check(google=uses_google()))
        return self._looked[1] if self._looked else None

    def answer(self, target: str, headers, method: str = 'GET',
               body: bytes | None = None) -> tuple[int, str | None, bytes]:
        """Answer one request, or raise the refusal."""
        hosts = headers.get_all('Host') or []
        if len(hosts) != 1 or hosts[0].strip().lower() not in self.hosts:
            raise Refusal(HTTPStatus.FORBIDDEN, 'The page answers only at its own local address.')
        try:
            url = urlsplit(target)
        except ValueError:
            raise Refusal(HTTPStatus.BAD_REQUEST, 'That address cannot be read.')
        if method == 'POST':
            return self.change(url, hosts[0].strip().lower(), headers, body)
        if method != 'GET':
            raise Refusal(HTTPStatus.METHOD_NOT_ALLOWED, 'Nothing else is answered.',
                          self.allowed(url.path))
        if url.path in PAGE:
            name, kind = PAGE[url.path]
            return HTTPStatus.OK, kind, (PAGE_DIR / name).read_bytes()
        if url.path == '/favicon.ico':
            return HTTPStatus.NO_CONTENT, None, b''
        if url.path not in self.reads:
            if url.path in self.writes:
                raise Refusal(HTTPStatus.METHOD_NOT_ALLOWED,
                              'This is sent with POST, from the page.', self.allowed(url.path))
            raise Refusal(HTTPStatus.NOT_FOUND, 'Nothing is served here.')
        self.check_token(headers)
        query = parse_qs(url.query, keep_blank_values=True)

        def one(name: str) -> str:
            values = query.get(name, [])
            if len(values) != 1 or not values[0]:
                raise Refusal(HTTPStatus.BAD_REQUEST, f'Give one {name}.')
            return values[0]

        return self.read(url.path, one)

    def allowed(self, target: str) -> str:
        return allowed(target, self.reads, self.writes)

    def body_limit(self, target: str, headers) -> int:
        """The most bytes a POST to this address may carry. A subclass may let one address
        of its own carry more; nothing else about a request depends on this."""
        return BODY_LIMIT

    def trainings(self) -> list[dict]:
        return trainings()

    def detail(self, path: str) -> dict:
        return detail(path)

    def decide(self, path: str, target: str, decision: str, note: str | None,
               seen: str | None) -> dict:
        return decide(path, target, decision, note, seen)

    def move_approval(self, path: str, mode: str) -> dict:
        return move_approval(path, mode)

    def read(self, path: str, one) -> tuple[int, str, bytes]:
        """Answer one GET that passed every rule. `one(name)` is a query value."""
        if path == '/api/trainings':
            listed = self.trainings()
            return as_json(HTTPStatus.OK, {
                'trainings': listed,
                'needs': sum(item.get('state') == 'needs-you' for item in listed)})
        if path == '/api/training':
            return as_json(HTTPStatus.OK, self.detail(one('path')))
        if path == '/api/file':
            return as_json(HTTPStatus.OK, preview(one('path'), one('artifact')))
        if path == '/api/gate':
            return as_json(HTTPStatus.OK, gate(one('path'), one('artifact')))
        return as_json(HTTPStatus.OK, {'computer': self.computer(look=False)})

    def check_token(self, headers) -> None:
        supplied = headers.get(TOKEN_HEADER, '')
        if not secrets.compare_digest(supplied.encode('utf-8'), self.token.encode('utf-8')):
            raise Refusal(HTTPStatus.FORBIDDEN, 'This needs the key from the link the page '
                                                'was opened with.')

    def change(self, url, host: str, headers, body: bytes | None) -> tuple[int, str, bytes]:
        """Answer one POST: a decision, a move of approval, or a look at this computer."""
        if url.path not in self.writes:
            raise Refusal(HTTPStatus.METHOD_NOT_ALLOWED, 'This is read with GET.',
                          self.allowed(url.path))
        self.check_token(headers)
        origins = headers.get_all('Origin') or []
        if len(origins) != 1 or origins[0].strip().lower() != f'http://{host}':
            raise Refusal(HTTPStatus.FORBIDDEN, 'A change is accepted only from the page itself.')
        if url.query:
            raise Refusal(HTTPStatus.BAD_REQUEST, 'Send what is to change in the body.')
        if headers.get_content_type() != 'application/json':
            raise Refusal(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, 'Send the change as JSON.')
        if body is None:
            limit = self.body_limit(url.path, headers)
            raise Refusal(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                          f'A change is at most {limit:,} bytes, with its length stated.')
        try:
            sent = json.loads(body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            sent = None
        if not isinstance(sent, dict):
            raise Refusal(HTTPStatus.BAD_REQUEST, 'Send the change as one JSON object.')
        return self.write(url.path, sent)

    def write(self, path: str, sent: dict) -> tuple[int, str, bytes]:
        """Answer one POST that passed every rule. `sent` is its JSON object."""
        if path == '/api/decide':
            return as_json(HTTPStatus.OK, self.decide(
                text(sent, 'path'), text(sent, 'artifact'), text(sent, 'decision'),
                text(sent, 'note', False), text(sent, 'seen', False)))
        if path == '/api/approval':
            return as_json(HTTPStatus.OK, self.move_approval(text(sent, 'path'),
                                                             text(sent, 'mode')))
        return as_json(HTTPStatus.OK, {'computer': self.computer(look=True)})


class Desk:
    """The page's server. `start` serves on a thread, `serve` blocks, `stop` ends either.

    `page` makes what answers: Page here, or a subclass of it given the port.
    """

    def __init__(self, port: int = 0, page=Page):
        self.server = Server((HOST, port), Handler)
        self.server.desk = self
        self.port = self.server.server_address[1]
        self.page = page(self.port)
        self.token, self.hosts, self.answer = self.page.token, self.page.hosts, self.page.answer
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> str:
        """Where the page is, without its key."""
        return f'http://{HOST}:{self.port}/'

    @property
    def url(self) -> str:
        """The link for the user. The key rides in the fragment, which is never sent."""
        return f'{self.address}#token={self.token}'

    def serve(self) -> None:
        self.server.serve_forever()

    def start(self) -> None:
        self._thread = threading.Thread(target=self.server.serve_forever, args=(0.05,),
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is not None:
            self.server.shutdown()
            self._thread.join()
            self._thread = None
        self.server.server_close()
