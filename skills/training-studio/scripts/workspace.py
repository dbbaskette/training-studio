"""Session record, artifacts, history, status, approval and exports for one training directory."""
from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 1
STATE_DIR = '.training-studio'
SKILL_DIR = Path(__file__).resolve().parent.parent
# In a checkout the guidance sits beside the scripts; an installed copy keeps it in guidance/.
GUIDANCE_DIR = SKILL_DIR if (SKILL_DIR / 'references').is_dir() else SKILL_DIR / 'guidance'
PROFILE = GUIDANCE_DIR / 'assets' / 'profiles' / 'yoodli.json'

STAGES = ('intake', 'research-plan', 'research', 'blueprint', 'document', 'brief',
          'deck', 'scenario', 'yoodli', 'package', 'done')
SKIPPABLE = ('document', 'brief', 'deck', 'scenario', 'yoodli')
OPTIONAL = ('yoodli',)
LEVELS = ('101', '201', '301', '401')
DECK_TARGETS = ('pptx', 'google')
BRIEF_KINDS = ('product', 'competitive')
PINNABLE = ('harness-research', 'harness-slides')

SHARED = {
    'intake': ('intake.md', (), 'intake'),
    'research-plan': (f'{STATE_DIR}/research-plan.json', ('intake',), 'research-plan'),
    'research': ('.harness-research/research-report.md', ('research-plan',), 'research'),
}
PER_LEVEL = ('blueprint', 'document', 'brief', 'deck')
RESEARCH_RECORD = '.harness-research/research.json'
PPTX_SIGNATURE = b'PK\x03\x04'
RESEARCH_COPY = 'research-report.md'
SHARED_DELIVERABLES = ('README.md', 'intake.md', RESEARCH_COPY)
LEVEL_DELIVERABLES = ('blueprint.md', 'document.md', 'document.docx', 'competitive-brief.md',
                      'competitive-brief.docx', 'product-brief.md', 'product-brief.docx',
                      'deck-handoff.md', 'deck.pptx', 'deck-link.md', 'yoodli')

SCENARIO_ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
MODULE_HEADING = re.compile(r'^## (M[1-9][0-9]?)\b', re.MULTILINE)
OBJECTIVE_HEADING = re.compile(r'^### (O[1-9][0-9]*)\b', re.MULTILINE)
SHAPE = {'schema': int, 'id': str, 'title': str, 'levels': list, 'sizing': dict, 'stage': str,
         'settings': dict, 'unavailable': dict, 'pins': dict, 'artifacts': dict,
         'exports': dict, 'decisions': list, 'events': list}
SETTINGS = ('deck_target', 'brand', 'brief_kind', 'stages')


class WorkspaceError(Exception):
    """A refusal to show the user as it is."""


# --- files and the session record -------------------------------------------

def now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f'.{path.name}.pending-{secrets.token_hex(6)}')
    try:
        with open(pending, 'xb') as stream:
            stream.write(data)
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)


def managed(root: Path, relative: str) -> Path:
    """The path of a file the helper manages; a symbolic link is refused."""
    path = root / relative
    if path.is_symlink():
        raise WorkspaceError(f'{relative} is a symbolic link; managed files must be real '
                             'files in the training directory.')
    return path


def session_path(root: Path) -> Path:
    return root / STATE_DIR / 'session.json'


def load(root: Path) -> dict:
    path = session_path(root)
    if not path.is_file():
        raise WorkspaceError('No training in this directory. Run init first.')
    try:
        session = json.loads(path.read_text(encoding='utf-8'))
    except ValueError:
        raise WorkspaceError('The session record is not valid JSON; refusing to change it.')
    if not isinstance(session, dict) or session.get('schema') != SCHEMA:
        found = session.get('schema') if isinstance(session, dict) else None
        raise WorkspaceError(f'Unrecognised session schema {found!r}; refusing to change it.')
    for key, kind in SHAPE.items():
        if not isinstance(session.get(key), kind):
            raise WorkspaceError(f'The session record has no usable "{key}"; '
                                 'refusing to change it.')
    for key in SETTINGS:
        if key not in session['settings']:
            raise WorkspaceError(f'The session record has no usable "settings.{key}"; '
                                 'refusing to change it.')
    return session


def store(root: Path, session: dict) -> None:
    text = json.dumps(session, indent=2, sort_keys=True) + '\n'
    write_atomic(session_path(root), text.encode('utf-8'))


def log(session: dict, event: str, **details) -> None:
    session['events'].append({'at': now(), 'event': event, **details})


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextmanager
def locked(root: Path):
    """Hold the workspace lock so two commands cannot overwrite each other's changes."""
    path = root / STATE_DIR / 'lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            text = path.read_text(encoding='utf-8').strip() if path.is_file() else ''
            if text.isdigit() and _alive(int(text)):
                raise WorkspaceError('Another Training Studio command is running in this '
                                     f'directory (process {text}). Try again when it finishes.')
            path.unlink(missing_ok=True)
            continue
        os.write(handle, str(os.getpid()).encode())
        os.close(handle)
        break
    else:
        raise WorkspaceError('Could not take the workspace lock.')
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def mutating(function):
    """Run a state-changing command under the lock, in a directory that has a training."""
    @functools.wraps(function)
    def wrapper(root: Path, *args, **kwargs):
        if not session_path(root).is_file():
            raise WorkspaceError('No training in this directory. Run init first.')
        with locked(root):
            return function(root, *args, **kwargs)
    return wrapper


# --- init ---------------------------------------------------------------------

def slugify(title: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
    return slug[:64].strip('-') or 'training'


def check_choice(value: str | None, choices: tuple, label: str) -> None:
    if value is not None and value not in choices:
        raise WorkspaceError(f'{label} is one of: ' + ', '.join(choices))


def check_levels(levels) -> list[str]:
    chosen = sorted(set(levels))
    unknown = [level for level in chosen if level not in LEVELS]
    if unknown:
        raise WorkspaceError('Levels are chosen from: ' + ', '.join(LEVELS))
    return chosen


def prefix(level: str | None) -> str:
    return '' if level is None else f'{level}/'


def init(root: Path, title: str, levels=(), brief_kind: str = 'product',
         deck_target: str | None = None, brand: str | None = None,
         yoodli: bool = False) -> dict:
    if not title.strip():
        raise WorkspaceError('A training needs a title.')
    levels = check_levels(levels)
    check_choice(brief_kind, BRIEF_KINDS, 'The brief kind')
    check_choice(deck_target, DECK_TARGETS, 'The deck target')
    if root == SKILL_DIR or root in SKILL_DIR.parents:
        raise WorkspaceError('This directory holds the Training Studio skill itself. '
                             'Launch in a directory made for the training.')
    if session_path(root).exists():
        raise WorkspaceError('A training already exists in this directory.')
    names = list(SHARED_DELIVERABLES)
    for level in levels or [None]:
        names += [prefix(level) + name for name in LEVEL_DELIVERABLES]
    taken = sorted(name for name in names if (root / name).exists())
    if taken:
        raise WorkspaceError('These names are already in use here: ' + ', '.join(taken))
    session = {
        'schema': SCHEMA,
        'id': slugify(title),
        'title': title.strip(),
        'levels': levels,
        'level': None,
        'sizing': {},
        'stage': 'intake',
        'next_step': 'Complete intake',
        'pending_question': None,
        'settings': {'deck_target': deck_target, 'brand': brand, 'brief_kind': brief_kind,
                     'stages': [stage for stage in SKIPPABLE
                                if stage not in OPTIONAL or (stage == 'yoodli' and yoodli)]},
        'unavailable': {},
        'pins': {},
        'research': None,
        'findings': None,
        'artifacts': {},
        'exports': {},
        'decisions': [],
        'events': [],
    }
    log(session, 'init')
    with locked(root):
        store(root, session)
    return session


# --- artifacts ----------------------------------------------------------------

def split(name: str) -> tuple[str, str | None]:
    base, separator, level = name.partition('@')
    return base, (level if separator else None)


def qualify(base: str, level: str | None) -> str:
    return base if level is None else f'{base}@{level}'


def scenario_file(root: Path, level: str | None, ident: str) -> str:
    folder = prefix(level)
    if ident != 'main':
        return f'{folder}scenarios/{ident}.md'
    in_folder = f'{folder}scenarios/main.md'
    if (root / in_folder).is_file() and not (root / f'{folder}scenario.md').is_file():
        return in_folder
    return f'{folder}scenario.md'


def artifact(root: Path, session: dict, name: str) -> dict:
    """File, upstream artifacts, stage and other inputs for a named artifact."""
    base, level = split(name)
    if base in SHARED and level is None:
        file, upstream, stage = SHARED[base]
        return {'file': file, 'upstream': upstream, 'stage': stage, 'extras': ()}
    levels = session['levels']
    if level is not None and not levels:
        raise WorkspaceError(f'{name}: this training has no levels.')
    if levels and level not in levels:
        raise WorkspaceError(f'{name}: name the level, one of ' + ', '.join(levels) + '.')
    folder = prefix(level)
    settings = session['settings']

    def same(other: str) -> str:
        return qualify(other, level)

    if base == 'blueprint':
        return {'file': f'{folder}blueprint.md', 'upstream': ('intake', 'research'),
                'stage': 'blueprint', 'extras': ()}
    if base == 'document':
        return {'file': f'{folder}document.md', 'upstream': (same('blueprint'),),
                'stage': 'document', 'extras': ()}
    if base == 'brief':
        return {'file': f"{folder}{settings['brief_kind']}-brief.md",
                'upstream': (same('blueprint'), 'research'), 'stage': 'brief',
                'extras': ('setting:brief_kind',)}
    if base == 'deck':
        file = 'deck-link.md' if settings['deck_target'] == 'google' else 'deck.pptx'
        reference = same('document') if 'document' in settings['stages'] else 'research'
        return {'file': folder + file, 'upstream': (same('blueprint'), reference),
                'stage': 'deck', 'extras': ('setting:deck_target', 'setting:brand')}
    kind, _, ident = base.partition(':')
    if kind == 'scenario' and SCENARIO_ID.match(ident):
        return {'file': scenario_file(root, level, ident), 'upstream': (),
                'stage': 'scenario', 'extras': ()}
    if kind == 'yoodli' and SCENARIO_ID.match(ident):
        return {'file': f'{folder}yoodli/{ident}.md',
                'upstream': (same('blueprint'), same('brief'), same(f'scenario:{ident}')),
                'stage': 'yoodli', 'extras': ('profile',)}
    raise WorkspaceError(f'Unknown artifact {name!r}.')


def scenarios(root: Path, session: dict) -> dict:
    """Scenario files found, keyed by artifact name, and files that were passed over."""
    found, ignored = {}, []
    levels = session['levels']
    if levels:
        if (root / 'scenario.md').is_file():
            ignored.append('scenario.md')
        if (root / 'scenarios').is_dir():
            ignored += sorted(f'scenarios/{path.name}' for path in (root / 'scenarios').iterdir()
                              if path.is_file())
    for level in levels or [None]:
        folder = prefix(level)
        if (root / f'{folder}scenario.md').is_file():
            found[qualify('scenario:main', level)] = f'{folder}scenario.md'
        directory = root / f'{folder}scenarios'
        for path in sorted(directory.iterdir()) if directory.is_dir() else ():
            if not path.is_file():
                continue
            relative = f'{folder}scenarios/{path.name}'
            if path.suffix != '.md' or not SCENARIO_ID.match(path.stem):
                ignored.append(relative)
                continue
            name = qualify(f'scenario:{path.stem}', level)
            if name in found:
                raise WorkspaceError(f'{folder}scenario.md and {relative} are both the main '
                                     'scenario, which is ambiguous. Keep one.')
            found[name] = relative
    return {'found': dict(sorted(found.items())), 'ignored': ignored}


def artifact_names(root: Path, session: dict) -> list[str]:
    """Every artifact of this training, upstream before downstream."""
    names = list(SHARED)
    yoodli = 'yoodli' in session['settings']['stages']
    kinds = ('scenario:', 'yoodli:') if yoodli else ('scenario:',)
    known = set(scenarios(root, session)['found'])
    known |= {name.replace('yoodli:', 'scenario:', 1) for name in session['artifacts']
              if name.startswith(kinds)}
    for level in session['levels'] or [None]:
        names += [qualify(base, level) for base in PER_LEVEL]
        for name in sorted(name for name in known if split(name)[1] == level):
            names.append(name)
            if yoodli:
                names.append(name.replace('scenario:', 'yoodli:', 1))
    return names


def research_fingerprint(root: Path) -> str | None:
    """One hash for the research bundle: the live report, the record and the approved copy."""
    report = sha256_file(root / SHARED['research'][0])
    if report is None:
        return None
    parts = [report, sha256_file(root / RESEARCH_RECORD), sha256_file(root / RESEARCH_COPY)]
    return hashlib.sha256('\n'.join(part or '-' for part in parts).encode()).hexdigest()


def profile_for(root: Path) -> Path:
    """The Yoodli profile a training uses: its pinned guidance's, else the installed one."""
    try:
        pin = json.loads((root / STATE_DIR / 'guidance.json').read_text(encoding='utf-8'))
        pinned = Path(pin['path']) / 'assets' / 'profiles' / 'yoodli.json'
    except (OSError, ValueError, KeyError, TypeError):
        return PROFILE
    return pinned if pin.get('commit') and pinned.is_file() else PROFILE


def inputs(root: Path, session: dict, name: str) -> dict:
    """What an artifact is built from: upstream content, and the settings that affect it."""
    spec = artifact(root, session, name)
    found = {}
    for upstream in spec['upstream']:
        if upstream == 'research':
            found[upstream] = research_fingerprint(root)
        else:
            found[upstream] = sha256_file(root / artifact(root, session, upstream)['file'])
    for extra in spec['extras']:
        if extra == 'profile':
            found[extra] = sha256_file(profile_for(root))
        else:
            found[extra] = session['settings'][extra.partition(':')[2]]
    return found


# --- saving and history ---------------------------------------------------------

def snapshot(root: Path, name: str, path: Path) -> str | None:
    """Keep a content-addressed copy of a file and return its hash."""
    digest = sha256_file(path)
    if digest is None:
        return None
    folder = re.sub(r'[:@]', '-', name)
    kept = root / STATE_DIR / 'history' / folder / f'{digest}{path.suffix}'
    if not kept.exists():
        write_atomic(kept, path.read_bytes())
    return digest


def pinned_inputs(root: Path, session: dict, name: str) -> dict:
    found = inputs(root, session, name)
    for upstream in artifact(root, session, name)['upstream']:
        if found[upstream] is None:
            raise WorkspaceError(f'Cannot record {name} before {upstream} exists.')
    return found


def record(root: Path, session: dict, name: str, built: bool) -> dict:
    """Record what is on disk. `built` re-pins what the artifact was built from."""
    spec = artifact(root, session, name)
    path = managed(root, spec['file'])
    if sha256_file(path) is None:
        raise WorkspaceError(f"Nothing to record: {spec['file']} does not exist.")
    if spec['file'].endswith('.pptx') and path.read_bytes()[:4] != PPTX_SIGNATURE:
        raise WorkspaceError(f"{spec['file']} is not a PowerPoint file. A placeholder cannot "
                             'stand in for the deck; if it could not be built, mark the deck '
                             'unavailable.')
    known = session['artifacts'].get(name, {})
    pins = pinned_inputs(root, session, name) if built or 'built_from' not in known else None
    entry = session['artifacts'].setdefault(name, {})
    if pins is not None:
        entry['built_from'] = pins
    entry['file'] = spec['file']
    entry['sha256'] = snapshot(root, name, path)
    base, level = split(name)
    if base == 'blueprint':
        found = MODULE_HEADING.findall(path.read_text(encoding='utf-8'))
        modules = list(dict.fromkeys(module.lower() for module in found))
        size = None if not modules else 'lesson' if len(modules) == 1 else 'course'
        session['sizing'][level or ''] = {'size': size, 'modules': modules}
    return entry


def check_coverage(root: Path, session: dict, name: str, coverage) -> None:
    blueprint = root / artifact(root, session, qualify('blueprint', split(name)[1]))['file']
    text = blueprint.read_text(encoding='utf-8') if blueprint.is_file() else ''
    objectives = set(OBJECTIVE_HEADING.findall(text))
    if not isinstance(coverage, dict):
        raise WorkspaceError('Coverage maps each objective to a list of slide numbers.')
    for objective, slides in coverage.items():
        if objective not in objectives:
            raise WorkspaceError(f'{objective} is not an objective in the blueprint.')
        if not isinstance(slides, list) or any(
                type(slide) is not int or slide < 1 for slide in slides):
            raise WorkspaceError(f'Slides for {objective} must be a list of '
                                 'positive whole numbers.')


@mutating
def save(root: Path, name: str, source: Path | None = None, built: bool = False,
         coverage: dict | None = None) -> dict:
    """Record an artifact. `source` replaces the file first; `built` marks a rebuild."""
    session = load(root)
    spec = artifact(root, session, name)
    path = managed(root, spec['file'])
    if coverage is not None:
        if split(name)[0] != 'deck':
            raise WorkspaceError('Only the deck takes a reviewed coverage record.')
        check_coverage(root, session, name, coverage)
    if source is not None:
        if name == 'research':
            raise WorkspaceError(
                'The research report is written by harness-research; record it with --built.')
        if not source.is_file():
            raise WorkspaceError(f'{source} does not exist.')
        pinned_inputs(root, session, name)
        snapshot(root, name, path)
        write_atomic(path, source.read_bytes())
    entry = record(root, session, name, built=built or source is not None)
    if coverage is not None:
        blueprint = artifact(root, session, qualify('blueprint', split(name)[1]))['file']
        entry['reviewed_coverage'] = {'deck_sha256': entry['sha256'],
                                      'blueprint_sha256': sha256_file(root / blueprint),
                                      'at': now(), 'objectives': coverage}
    log(session, 'save', artifact=name, sha256=entry['sha256'])
    store(root, session)
    return entry


# --- status ---------------------------------------------------------------------

def research_intact(root: Path, session: dict) -> bool:
    """True while the record and the approved copy are what was approved."""
    bundle = session.get('research')
    return bool(bundle
                and sha256_file(root / RESEARCH_RECORD) == bundle['record_sha256']
                and sha256_file(root / RESEARCH_COPY) == bundle['report_sha256'])


def statuses(root: Path, session: dict) -> dict[str, str]:
    """Status of every artifact, computed from what is on disk now."""
    known: dict[str, str] = {}
    for name in artifact_names(root, session):
        known[name] = _status(root, session, name, known)
    return known


def _status(root: Path, session: dict, name: str, known: dict[str, str]) -> str:
    spec = artifact(root, session, name)
    if spec['stage'] in SKIPPABLE and spec['stage'] not in session['settings']['stages']:
        return 'skipped'
    if spec['stage'] in session['unavailable']:
        return 'unavailable'
    current = sha256_file(root / spec['file'])
    if current is None:
        return 'not-started'
    entry = session['artifacts'].get(name)
    if entry is None:
        return 'draft'
    if any(known[upstream] == 'stale' for upstream in spec['upstream']):
        return 'stale'
    if entry['built_from'] != inputs(root, session, name):
        return 'stale'
    approved = entry.get('approved')
    if (approved and approved['sha256'] == current
            and approved['inputs'] == entry['built_from']
            and (name != 'research' or research_intact(root, session))):
        return 'approved'
    return 'draft'


def exportable(name: str) -> bool:
    base = split(name)[0]
    return base in ('document', 'brief') or base.startswith('yoodli:')


def export_states(root: Path, session: dict) -> dict[str, str]:
    """Whether each export is current, outdated, missing or unavailable."""
    states = {}
    for name in artifact_names(root, session):
        if not exportable(name):
            continue
        made = session['exports'].get(name)
        if made is None:
            states[name] = 'missing'
        elif 'unavailable' in made:
            states[name] = 'unavailable'
        elif sha256_file(root / made['file']) is None:
            states[name] = 'missing'
        else:
            source = sha256_file(root / artifact(root, session, name)['file'])
            fresh = (made['source_sha256'] == source
                     and made['sha256'] == sha256_file(root / made['file']))
            states[name] = 'current' if fresh else 'outdated'
    return states


def research_summary(session: dict) -> dict | None:
    """When research was approved, its run, and how many findings have each status."""
    approved = session['artifacts'].get('research', {}).get('approved')
    if not approved or not session.get('research'):
        return None
    counts: dict[str, int] = {}
    for value in (session.get('findings') or {}).values():
        counts[value] = counts.get(value, 0) + 1
    return {'approved_at': approved['at'], 'run': session['research']['run'],
            'findings': counts}


def status(root: Path) -> dict:
    session = load(root)
    state = statuses(root, session)
    return {
        'id': session['id'],
        'title': session['title'],
        'levels': session['levels'],
        'level': session.get('level'),
        'sizing': session['sizing'],
        'stage': session['stage'],
        'next_step': session.get('next_step'),
        'pending_question': session.get('pending_question'),
        'settings': session['settings'],
        'unavailable_stages': session['unavailable'],
        'pins': session['pins'],
        'research': research_summary(session),
        'artifacts': state,
        'files': {name: artifact(root, session, name)['file'] for name in state},
        'exports': export_states(root, session),
        'stale': [name for name, value in state.items() if value == 'stale'],
        'scenarios': scenarios(root, session),
    }


# --- approval -------------------------------------------------------------------

def research_record(root: Path) -> dict | None:
    """The harness-research record, or None if it is missing or not one we recognise."""
    try:
        value = json.loads((root / RESEARCH_RECORD).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    recognised = (isinstance(value, dict) and value.get('schema') == 1
                  and value.get('owner') == 'harness-research'
                  and isinstance(value.get('items'), list)
                  and isinstance(value.get('results'), dict))
    return value if recognised else None


@mutating
def approve(root: Path, name: str, accept_stale: str | None = None) -> dict:
    """Record the user's approval of what is on disk, against what it was built from."""
    session = load(root)
    spec = artifact(root, session, name)
    path = managed(root, spec['file'])
    state = statuses(root, session)
    if state[name] in ('skipped', 'unavailable'):
        raise WorkspaceError(f'Cannot approve {name}: it is {state[name]}.')
    if sha256_file(path) is None:
        raise WorkspaceError(f"Cannot approve {name}: {spec['file']} does not exist.")
    for upstream in spec['upstream']:
        if state[upstream] not in ('approved', 'skipped'):
            raise WorkspaceError(f'Cannot approve {name}: {upstream} is {state[upstream]}.')
    entry = record(root, session, name, built=False)
    current = pinned_inputs(root, session, name)
    if entry['built_from'] != current:
        if not accept_stale:
            raise WorkspaceError(
                f'{name} was built from an older version of what it depends on. '
                'Rebuild it, or approve with a reason to accept it as it is.')
        session['decisions'].append({'at': now(), 'artifact': name,
                                     'decision': 'accepted-stale', 'from': entry['built_from'],
                                     'to': current, 'reason': accept_stale})
        entry['built_from'] = current
    entry['approved'] = {'sha256': entry['sha256'], 'inputs': dict(entry['built_from']),
                         'at': now()}
    warnings = []
    if name == 'research':
        write_atomic(root / RESEARCH_COPY, path.read_bytes())
        found = research_record(root)
        session['research'] = {'report_sha256': entry['sha256'],
                               'record_sha256': sha256_file(root / RESEARCH_RECORD),
                               'run': found.get('run') if found else None}
        if found is None:
            session['findings'] = None
            warnings.append('Could not read the findings index; '
                            'citation checks will report unavailable.')
        else:
            session['findings'] = {
                item['id']: found['results'].get(item['id'], {}).get('status', 'pending')
                for item in found['items']}
            pending = sorted(key for key, value in session['findings'].items()
                             if value == 'pending')
            if pending:
                warnings.append('Research questions still pending: ' + ', '.join(pending))
    log(session, 'approve', artifact=name, sha256=entry['sha256'])
    store(root, session)
    return {'artifact': name, 'approved': entry['approved'], 'warnings': warnings}


# --- exports --------------------------------------------------------------------

@mutating
def export(root: Path, name: str, file: str | None = None,
           unavailable: str | None = None) -> dict:
    """Record a converted copy of an artifact, or that one could not be produced."""
    session = load(root)
    spec = artifact(root, session, name)
    if not exportable(name):
        raise WorkspaceError(f'{name} is not exported; only the document, the brief and '
                             'Yoodli scenarios are.')
    if unavailable:
        made = {'unavailable': unavailable, 'at': now()}
    else:
        relative = file or str(Path(spec['file']).with_suffix('.docx'))
        path = (root / relative).resolve()
        if root not in path.parents:
            raise WorkspaceError('An export must be inside the training directory.')
        if not path.is_file():
            raise WorkspaceError(f'{relative} does not exist.')
        source = sha256_file(managed(root, spec['file']))
        if source is None:
            raise WorkspaceError(f"Cannot export {name}: {spec['file']} does not exist.")
        made = {'file': path.relative_to(root).as_posix(), 'source_sha256': source,
                'sha256': sha256_file(path), 'at': now()}
    session['exports'][name] = made
    log(session, 'export', artifact=name)
    store(root, session)
    return made


# --- skip, checkpoint, pin --------------------------------------------------------

@mutating
def skip(root: Path, stage: str, reason: str | None = None, unavailable: bool = False,
         clear: bool = False) -> dict:
    """Skip a stage, mark it unavailable, or clear either mark."""
    session = load(root)
    if stage not in SKIPPABLE:
        raise WorkspaceError('Only these stages can be skipped: ' + ', '.join(SKIPPABLE))
    wanted = session['settings']['stages']
    if clear:
        if stage == 'yoodli' and not {'brief', 'scenario'} <= set(wanted):
            raise WorkspaceError('Restore the brief and the scenarios first; a Yoodli '
                                 'scenario is built from both.')
        if stage not in wanted:
            wanted.append(stage)
            wanted.sort(key=SKIPPABLE.index)
        session['unavailable'].pop(stage, None)
        log(session, 'restore', stage=stage)
    elif not reason:
        raise WorkspaceError('Give a reason.')
    elif unavailable:
        session['unavailable'][stage] = reason
        log(session, 'unavailable', stage=stage, reason=reason)
    else:
        if stage in ('brief', 'scenario') and 'yoodli' in wanted:
            raise WorkspaceError(f'Turn Yoodli off before skipping the {stage}: a Yoodli '
                                 'scenario is built from the scenario file and uses the '
                                 'brief as its knowledge source.')
        if stage in wanted:
            wanted.remove(stage)
        log(session, 'skip', stage=stage, reason=reason)
    store(root, session)
    return {'stages': wanted, 'unavailable': session['unavailable']}


@mutating
def checkpoint(root: Path, stage: str | None = None, next_step: str | None = None,
               question: str | None = None, clear_question: bool = False,
               deck_target: str | None = None, brand: str | None = None,
               brief_kind: str | None = None, level: str | None = None,
               levels=None) -> dict:
    """Record where the run is and change settings."""
    session = load(root)
    check_choice(stage, STAGES, 'The stage')
    check_choice(deck_target, DECK_TARGETS, 'The deck target')
    check_choice(brief_kind, BRIEF_KINDS, 'The brief kind')
    if levels is not None:
        if not session['levels']:
            raise WorkspaceError('A plain training cannot be given levels; start a levelled '
                                 'training in a new directory.')
        chosen = check_levels(levels)
        if not chosen:
            raise WorkspaceError('A levelled training keeps at least one level.')
        session['levels'] = chosen
        if session.get('level') not in chosen:
            session['level'] = None
    if level is not None:
        if level not in session['levels']:
            raise WorkspaceError('The level is one of: ' + (', '.join(session['levels'])
                                                            or 'none; this is a plain training'))
        session['level'] = level
    if stage is not None:
        session['stage'] = stage
    if next_step is not None:
        session['next_step'] = next_step
    if clear_question:
        session['pending_question'] = None
    if question is not None:
        session['pending_question'] = question
    if deck_target is not None:
        session['settings']['deck_target'] = deck_target
    if brand is not None:
        session['settings']['brand'] = brand or None
    if brief_kind is not None:
        session['settings']['brief_kind'] = brief_kind
    log(session, 'checkpoint', stage=session['stage'])
    store(root, session)
    return {'stage': session['stage'], 'level': session.get('level'),
            'levels': session['levels'], 'next_step': session.get('next_step'),
            'pending_question': session.get('pending_question'),
            'settings': session['settings']}


@mutating
def pin(root: Path, skill: str, task: str, runtime: str, run: str | None = None,
        level: str | None = None) -> dict:
    """Record the harness skill task this training, or one of its levels, resumes with."""
    session = load(root)
    check_choice(skill, PINNABLE, 'A pinned skill')
    if level is not None and level not in session['levels']:
        raise WorkspaceError('The level is one of: ' + (', '.join(session['levels'])
                                                        or 'none; this is a plain training'))
    key = qualify(skill, level)
    session['pins'][key] = {'task': task, 'runtime': runtime}
    if run:
        session['pins'][key]['run'] = run
    log(session, 'pin', skill=skill, task=task)
    store(root, session)
    return session['pins']
