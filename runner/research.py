"""The harness-research command line, called from Python.

What a caller needs to know
---------------------------
    research = Research()                     # finds the installed runtime, or refuses
    status = research.plan(training, training / '.training-studio' / 'research-plan.json')
    status = research.record(training, status['run'], 'instance-min', finding)
    status = research.status(training)

- Every call returns the command's own JSON: `run`, `status` (`not-started`,
  `in-progress`, `complete` or `stale`), `pending`, `unresolved`, `staleItems`,
  `completed`, `total`, `sourceGaps`, and where the record and the `report` are.
- A question with a finding of `insufficient` or `unavailable` counts as completed there.
  Whether that is enough is the caller's rule, not the command's.
- When the command says no, Refused is raised: a WorkspaceError that carries the one line
  it printed in `line`. `busy` is true when another save held its lock; record findings one
  at a time. A lock left by a process that died is not cleared here.
- `finding` is what worker_tools keeps for an accepted finding. Its `file` paths are read
  from the training's folder, so copy a job's sources into the training first.
- The runtime is the folder named by HARNESS_RESEARCH_RUNTIME when that is set, else the
  first usual install location that holds one. `Research(run=...)` replaces how the command
  is run; `stand_in()` gives a Research backed by StandIn, which behaves like the real
  command for plan, record and status and needs neither Node nor an installed skill.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
from workspace import WorkspaceError

VARIABLE = 'HARNESS_RESEARCH_RUNTIME'
SCRIPT = Path('scripts') / 'harness-research.mjs'
TIMEOUT = 120
BUSY = 'Research storage is busy'
VERDICTS = ('supported', 'contradicted', 'insufficient', 'unavailable')
SCOPES = {'supplied-only': 'Uploaded sources only',
          'public-web': 'Uploaded sources plus external research'}
IDENT = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
NOT_A_QUERY = re.compile(r'https?://|[/\\@]')


class Refused(WorkspaceError):
    """harness-research said no. `line` is the one line it gave."""

    def __init__(self, line: str):
        super().__init__(f'harness-research refused: {line}')
        self.line = line

    @property
    def busy(self) -> bool:
        """True when another save was in progress, so trying again may work."""
        return self.line.startswith(BUSY)


def locations() -> list[Path]:
    """Where an installed harness-research may be. The override, when set, is the only
    place looked."""
    override = os.environ.get(VARIABLE)
    if override:
        return [Path(override).expanduser()]
    user = Path.home()
    return [user / 'Library' / 'Application Support' / 'Harness Research' / 'current',
            user / '.local' / 'share' / 'harness-research' / 'current',
            user / '.claude' / 'skills' / 'harness-research',
            user / '.agents' / 'skills' / 'harness-research',
            user / '.cursor' / 'skills' / 'harness-research']


def find_runtime() -> Path:
    """The installed harness-research, with links followed so one version is used
    throughout. Refuses when there is none."""
    for place in locations():
        if (place / SCRIPT).is_file():
            return place.resolve()
    if os.environ.get(VARIABLE):
        raise WorkspaceError(f'{VARIABLE} names {os.environ[VARIABLE]}, which does not hold '
                             'harness-research. Point it at the installed skill, or unset it.')
    raise WorkspaceError('The harness-research skill is not installed on this computer, so '
                         'research cannot run. Install it, then try again.')


def run_command(command: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """Run the command line once: (exit code, standard output, standard error)."""
    try:
        done = subprocess.run(command, cwd=cwd, capture_output=True, timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL, encoding='utf-8', errors='replace')
    except subprocess.TimeoutExpired:
        raise WorkspaceError(f'harness-research did not answer in {TIMEOUT} seconds.')
    except OSError as failure:
        raise WorkspaceError(f'harness-research could not be started ({failure}).')
    return done.returncode, done.stdout, done.stderr


class Research:
    """The plan, record and status commands of one installed harness-research."""

    def __init__(self, runtime: Path | None = None, run=None):
        self.run = run or run_command
        self.runtime = Path(runtime) if runtime else find_runtime()
        self.node = 'node' if run else shutil.which('node')
        if self.node is None:
            raise WorkspaceError('harness-research needs Node.js 20 or newer, which was not '
                                 'found on this computer. Install it, then try again.')

    def _call(self, *args: str) -> str:
        code, out, err = self.run([self.node, str(self.runtime / SCRIPT), *args])
        if code != 0:
            lines = [line.strip() for line in err.splitlines() if line.strip()]
            raise Refused(lines[-1] if lines else f'it ended with exit code {code}')
        return out

    def _json(self, *args: str) -> dict:
        try:
            found = json.loads(self._call(*args))
        except ValueError:
            found = None
        if not isinstance(found, dict):
            raise WorkspaceError('harness-research answered with something other than the '
                                 'JSON it should. Check that it is installed whole.')
        return found

    def version(self) -> str:
        """The runtime's version, as it states it."""
        return self._call('--version').strip().rpartition(' ')[2]

    def plan(self, project: Path, file: Path, allow_web: bool = False) -> dict:
        """Hand over an approved plan. The same plan again continues its run; a changed
        one starts a new run with no results. `allow_web` permits a plan that widens
        supplied-only research to the public web."""
        extra = ['--allow-web'] if allow_web else []
        return self._json('plan', '--project', str(project), '--file', str(file), *extra)

    def record(self, project: Path, run: str, item: str, finding: dict) -> dict:
        """Record one question's finding in a run."""
        wanted = {key: finding.get(key) for key in ('status', 'summary', 'limits', 'evidence')}
        handle, name = tempfile.mkstemp(suffix='.json', prefix='finding-')
        try:
            with os.fdopen(handle, 'w', encoding='utf-8') as stream:
                json.dump(wanted, stream)
            return self._json('record', '--project', str(project), '--file', name,
                              '--run', run, '--item', item)
        finally:
            Path(name).unlink(missing_ok=True)

    def status(self, project: Path) -> dict:
        """Where the research stands. The command rewrites its report when asked."""
        return self._json('status', '--project', str(project))


def stand_in() -> Research:
    """A Research that needs nothing installed, for tests."""
    return Research(runtime=Path('stand-in'), run=StandIn())


# --- a stand-in for tests ----------------------------------------------------------------

class _Said(Exception):
    """A line the command would print before exiting with 1."""


def _text(value, label: str, most: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > most:
        raise _Said(f'{label} requires nonempty text (maximum {most} characters).')
    return value


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class StandIn:
    """Behaves like the real command line for plan, record and status, in Python.

    It keeps the same record and report, in the same places, returns the same JSON and
    says no with the same lines. It keeps no history of earlier runs and knows nothing of
    migration. `calls` lists the arguments of every call made.
    """

    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
        args = [str(part) for part in command[2:]]
        self.calls.append(args)
        try:
            result = self._act(args)
        except (_Said, KeyError, TypeError, AttributeError, ValueError) as said:
            return 1, '', f'{said}\n'  # as the real one does: one line, and exit code 1
        if isinstance(result, str):
            return 0, result + '\n', ''
        return 0, json.dumps(result, indent=2) + '\n', ''

    def _act(self, args: list[str]):
        if args == ['--version']:
            return 'harness-research 0.0.0-stand-in'
        action, options, rest = (args[0] if args else None), {}, args[1:]
        while rest:
            name = rest.pop(0)
            options[name] = True if name == '--allow-web' else rest.pop(0) if rest else None
        if action not in ('plan', 'record', 'status') or not options.get('--project'):
            raise _Said('Choose plan, record, status or migrate and supply --project.')
        project = Path(options['--project']).resolve()
        lock = project / '.harness-research' / 'research.lock'
        if lock.exists():
            raise _Said(f'{BUSY}; retry after the current save.')
        if action == 'status':
            return self._status(project)
        if not options.get('--file'):
            raise _Said('--file is required for plan or record.')
        supplied = json.loads(Path(options['--file']).read_text(encoding='utf-8'))
        if action == 'plan':
            return self._plan(project, supplied, bool(options.get('--allow-web')))
        if not options.get('--run') or not options.get('--item'):
            raise _Said('Recording requires --run and --item.')
        return self._record(project, options['--run'], options['--item'], supplied)

    # --- the record ---

    def _load(self, project: Path) -> dict | None:
        try:
            return json.loads((project / '.harness-research' / 'research.json').read_text(
                encoding='utf-8'))
        except (OSError, ValueError):
            return None

    def _file(self, project: Path, name) -> Path:
        parts = re.split(r'[\\/]', name) if isinstance(name, str) else ['']
        if not name or Path(name).is_absolute() or any(p in ('', '..') for p in parts):
            raise _Said('Research file paths must be relative to the project.')
        if not (project / name).is_file():
            raise _Said(f'Research source is missing: {name}')
        return project / name

    def _pins(self, project: Path, names) -> dict:
        return {name: _digest((project / name).read_bytes())
                if (project / name).is_file() else None for name in names}

    def _save(self, project: Path, value: dict) -> dict:
        folder = project / '.harness-research'
        folder.mkdir(exist_ok=True)
        status = self._inspect(project, value)
        (folder / 'research.json').write_text(json.dumps(value, indent=2) + '\n',
                                              encoding='utf-8')
        (folder / 'research-report.md').write_text(self._render(value, status),
                                                   encoding='utf-8')
        return status

    def _inspect(self, project: Path, value: dict) -> dict:
        stale = [ident for ident, result in value['results'].items()
                 if any(self._pins(project, [source['file']])[source['file']]
                        != source['sha256'] for source in result['evidence'])]
        changed = self._pins(project, value['inputs']) != value['inputs']
        pending = [item['id'] for item in value['items'] if item['id'] not in value['results']]
        unresolved = [ident for ident, result in value['results'].items()
                      if result['status'] in ('insufficient', 'unavailable')]
        folder = project / '.harness-research'
        return {'run': value['run'], 'scope': value['scope'],
                'sourceMode': SCOPES[value['scope']],
                'sourceGaps': [{'id': source['id'], 'title': source['title'],
                                'limits': source['limits']}
                               for source in value.get('sources') or []
                               if not source.get('file') or source['limits'] != 'none'],
                'status': ('stale' if stale or changed else 'in-progress' if pending
                           else 'complete'),
                'pending': pending, 'unresolved': unresolved, 'staleItems': stale,
                'completed': len(value['results']), 'total': len(value['items']),
                'file': str(folder / 'research.json'),
                'report': str(folder / 'research-report.md'),
                'assessment': 'Research coverage; does not certify a factual or downstream '
                              'review.'}

    def _render(self, value: dict, status: dict) -> str:
        lines = ['# Research brief', '', f"Topic: {value['topic']}",
                 f"Purpose: {value['purpose']}; scope: {SCOPES[value['scope']]} "
                 f"({value['scope']}).",
                 f"Status: {status['status']}. Completed: {status['completed']}/"
                 f"{status['total']}.",
                 f"Pending: {', '.join(status['pending']) or 'none'}.",
                 f"Unresolved: {', '.join(status['unresolved']) or 'none'}.", '']
        for item in value['items']:
            finding = value['results'].get(item['id'])
            lines += [f"## {item['id']}", '', item['question'], '',
                      f"Status: {finding['status'] if finding else 'pending'}.", '']
            if finding:
                lines += [finding['summary'], '',
                          f"Limits/open questions: {finding['limits']}", '']
                for source in finding['evidence']:
                    quote = source['quote'].replace('\n', '\n> ')
                    lines += [f"Source: {source['title']}", f"Origin: {source['origin']}",
                              f"Snapshot: {source['file']}; SHA256: {source['sha256']}",
                              f"Location: {source['locator']}", '', f'> {quote}', '']
        return '\n'.join(lines) + '\n'

    # --- the commands ---

    def _status(self, project: Path) -> dict:
        value = self._load(project)
        folder = project / '.harness-research'
        if value is None:
            return {'status': 'not-started', 'file': str(folder / 'research.json'),
                    'report': str(folder / 'research-report.md')}
        return self._save(project, value)

    def _plan(self, project: Path, supplied: dict, allow_web: bool) -> dict:
        _text(supplied.get('topic'), 'Topic')
        if supplied.get('purpose') not in ('planning', 'fact-check') \
                or supplied.get('scope') not in SCOPES:
            raise _Said('Choose planning/fact-check and supplied-only/public-web.')
        items = supplied.get('items')
        if not isinstance(items, list) or not 1 <= len(items) <= 30:
            raise _Said('Plan 1–30 focused research questions.')
        seen = set()
        for item in items:
            if not IDENT.match(str(item.get('id'))) or item['id'] in seen:
                raise _Said('Research question IDs must be unique, lowercase identifiers.')
            seen.add(item['id'])
            _text(item.get('question'), 'Question')
            query = item.get('public_query')
            if query is not None:
                _text(query, 'Public query', 500)
                if supplied['scope'] != 'public-web' or NOT_A_QUERY.search(query):
                    raise _Said('Public queries require public-web scope and cannot contain '
                                'URLs, paths or emails.')
        sources = [{**source, 'limits': source.get('limits') or 'none'}
                   for source in supplied.get('sources') or []]
        files = sorted({name for source in sources
                        for name in (source.get('file'), source.get('original_file')) if name})
        for name in files:
            self._file(project, name)
        plan = {'topic': supplied['topic'], 'purpose': supplied['purpose'],
                'scope': supplied['scope'], 'input_files': files, 'items': items}
        if 'sources' in supplied:
            plan['sources'] = sources
        pins = self._pins(project, files)
        run = _digest(json.dumps([plan, pins], sort_keys=True).encode())[:24]
        old = self._load(project)
        if old and old['scope'] == 'supplied-only' and plan['scope'] == 'public-web' \
                and not allow_web:
            raise _Said('Supplied-only research requires explicit permission before changing '
                        'to public-web scope.')
        if old and old['run'] == run:
            return self._status(project)
        return self._save(project, {
            'schema': 1, 'owner': 'harness-research', 'run': run, **plan, 'inputs': pins,
            'results': {}, 'created_at': _now()})

    def _record(self, project: Path, run: str, ident: str, supplied: dict) -> dict:
        value = self._load(project)
        if value is None:
            raise _Said('No valid Harness research record; plan research first.')
        if value['run'] != run or self._pins(project, value['inputs']) != value['inputs']:
            raise _Said('Research run or content changed; refresh the plan before recording '
                        'results.')
        if not any(item['id'] == ident for item in value['items']):
            raise _Said('Unknown research question.')
        passages = supplied.get('evidence')
        if supplied.get('status') not in VERDICTS or not isinstance(passages, list) \
                or len(passages) > 20:
            raise _Said('Result requires a supported/contradicted/insufficient/unavailable '
                        'status and up to 20 evidence passages.')
        _text(supplied.get('summary'), 'Summary', 12000)
        _text(supplied.get('limits'), 'Coverage limits')
        evidence = [self._evidence(project, value, source) for source in passages]
        if supplied['status'] in ('supported', 'contradicted') and not evidence:
            raise _Said('Supported or contradicted findings require an inspected source '
                        'passage.')
        value['results'][ident] = {
            'status': supplied['status'], 'summary': supplied['summary'],
            'limits': supplied['limits'], 'evidence': evidence, 'checked_at': _now()}
        return self._save(project, value)

    def _evidence(self, project: Path, value: dict, source: dict) -> dict:
        for key, label in (('title', 'Source title'), ('origin', 'Source origin'),
                           ('locator', 'Source location')):
            _text(source.get(key), label)
        _text(source.get('quote'), 'Evidence quote', 12000)
        chosen = next((document for document in value.get('sources') or []
                       if document.get('file') and document['file'] == source.get('file')),
                      None)
        if source.get('source_id') is not None and (chosen or {}).get('id') != \
                source['source_id']:
            raise _Said('Evidence must match its selected supplied document.')
        if 'sources' in value and value['scope'] == 'supplied-only' and not chosen:
            raise _Said('Uploaded-sources-only evidence must come from a selected readable '
                        'document.')
        data = self._file(project, source.get('file')).read_bytes()
        try:
            content = data.decode('utf-8')
        except UnicodeDecodeError:
            content = '\0'
        if '\0' in content or content.startswith('%PDF-'):
            raise _Said('Research evidence needs a readable UTF-8 extraction.')
        content, start, quote = content.removeprefix('﻿'), source.get('start'), \
            source['quote']
        if type(start) is not int or start < 0 or content[start:start + len(quote)] != quote:
            raise _Said('Evidence must quote the inspected source snapshot exactly.')
        return {**source, **({'source_id': chosen['id']} if chosen else {}),
                'sha256': _digest(data)}


def _now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
