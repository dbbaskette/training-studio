"""Session record, artifacts, history, status, approval and exports for one training directory."""
from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 1
STATE_DIR = '.training-studio'
SKILL_DIR = Path(__file__).resolve().parent.parent
# In a checkout the guidance sits beside the scripts; an installed copy keeps it in guidance/.
GUIDANCE_DIR = SKILL_DIR if (SKILL_DIR / 'references').is_dir() else SKILL_DIR / 'guidance'
PROFILE = GUIDANCE_DIR / 'assets' / 'profiles' / 'yoodli.json'
# What only a copy of this repository has: the skill at the path it is kept in.
CHECKOUT_MARK = Path('skills') / 'training-studio' / 'SKILL.md'

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
COPIES = ('google', 'word')
APPROVAL = ('chat', 'page')
DECISIONS = ('approve', 'accept', 'revise', 'rebuild', 'skip', 'restore')
REQUESTS = ('revise', 'rebuild')
WHERE = {'chat': 'in the conversation', 'page': 'on the page'}
OPEN_THE_PAGE = ('The user opens the page by running `training.py desk` in a terminal of '
                 'their own.')
LABELS = {'intake': 'intake summary', 'research-plan': 'research plan',
          'research': 'research report', 'blueprint': 'blueprint', 'document': 'learner guide',
          'brief': 'brief', 'deck': 'slide deck', 'scenario': 'practice scenario',
          'yoodli': 'Yoodli scenario'}
STAGE_LABELS = {'document': 'the learner guide stage', 'brief': 'the brief stage',
                'deck': 'the deck stage', 'scenario': 'the practice stage',
                'yoodli': 'the Yoodli stage'}
LEVEL_STAGES = ('document', 'brief', 'deck', 'scenario', 'yoodli')
AHEAD = {'intake': 'Complete intake', 'research-plan': 'Draft the research questions',
         'research': 'Run the research', 'blueprint': 'Draft the blueprint',
         'document': 'Write {the} learner guide', 'brief': 'Write {the} brief',
         'deck': 'Hand {the} deck to harness-slides', 'scenario': 'Prepare {the} scenarios',
         'yoodli': 'Build {the} Yoodli scenarios', 'package': 'Write the index',
         'done': 'Nothing pending'}


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
    # A training started before copies were a choice asked for none.
    if not isinstance(session['settings'].setdefault('copies', []), list):
        raise WorkspaceError('The session record has no usable "settings.copies"; '
                             'refusing to change it.')
    # One started before approval could move to the page is approved in the conversation.
    if session['settings'].setdefault('approval', 'chat') not in APPROVAL:
        raise WorkspaceError('The session record has no usable "settings.approval"; '
                             'refusing to change it.')
    requests = session.setdefault('requests', [])
    if not isinstance(requests, list) or not all(isinstance(item, dict) for item in requests):
        raise WorkspaceError('The session record has no usable "requests"; '
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


def check_copies(copies) -> list[str]:
    """The kinds of copy to keep of each document and brief. None is a valid answer."""
    chosen = sorted(set(copies or ()))
    if any(kind not in COPIES for kind in chosen):
        raise WorkspaceError('Copies are any of: ' + ', '.join(COPIES) + '; or none.')
    return chosen


def prefix(level: str | None) -> str:
    return '' if level is None else f'{level}/'


def home_folder() -> Path | None:
    try:
        return Path.home().resolve()
    except (RuntimeError, KeyError):  # no home folder can be found
        return None


def refuse_the_wrong_place(root: Path) -> None:
    """Refuse a folder no training is started in: the home folder, the skill the helper runs
    from or a folder holding it, and a copy of this repository or any folder inside one."""
    root = root.resolve()
    if root == home_folder():
        raise WorkspaceError('This is your home folder. A training needs a folder of its own: '
                             'make a folder for this training, and start it there.')
    if root == SKILL_DIR or root in SKILL_DIR.parents:
        raise WorkspaceError('This directory holds the Training Studio skill itself. '
                             'Launch in a directory made for the training.')
    if any((folder / CHECKOUT_MARK).is_file() for folder in (root, *root.parents)):
        raise WorkspaceError('This directory is in a copy of the Training Studio repository. '
                             'Make a folder for this training outside it, and start it there.')


def init(root: Path, title: str, levels=(), brief_kind: str = 'product',
         deck_target: str | None = None, brand: str | None = None,
         yoodli: bool = False, copies=(), approval: str = 'chat') -> dict:
    if not title.strip():
        raise WorkspaceError('A training needs a title.')
    levels = check_levels(levels)
    copies = check_copies(copies)
    check_choice(approval, APPROVAL, 'Approval')
    check_choice(brief_kind, BRIEF_KINDS, 'The brief kind')
    check_choice(deck_target, DECK_TARGETS, 'The deck target')
    refuse_the_wrong_place(root)
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
        'gate': None,
        'requests': [],
        'settings': {'deck_target': deck_target, 'brand': brand, 'brief_kind': brief_kind,
                     'copies': copies, 'approval': approval,
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


def label(name: str) -> str:
    """An artifact in plain words: "the level 101 blueprint"."""
    base, level = split(name)
    kind, _, ident = base.partition(':')
    words = LABELS.get(kind, base)
    if ident and ident != 'main':
        words += f' "{ident}"'
    return f'the {words}' if level is None else f'the level {level} {words}'


def sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


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

def history_file(root: Path, name: str, digest: str, suffix: str) -> Path:
    """Where the kept copy of one version of an artifact is, or would be."""
    folder = re.sub(r'[:@]', '-', name)
    return root / STATE_DIR / 'history' / folder / f'{digest}{suffix}'


def snapshot(root: Path, name: str, path: Path) -> str | None:
    """Keep a content-addressed copy of a file and return its hash."""
    digest = sha256_file(path)
    if digest is None:
        return None
    kept = history_file(root, name, digest, path.suffix)
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
         coverage: dict | None = None, edit: bool = False) -> dict:
    """Record an artifact. `source` replaces the file first; `built` marks a rebuild.

    `edit` says the text from `source` is someone's edit, not a rebuild: the old version
    still goes to history, but what the artifact was built from is left as it was, so an
    edit can never clear staleness.
    """
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
    rebuilt = built or (source is not None and not edit)
    entry = record(root, session, name, built=rebuilt)
    if rebuilt:
        close_requests(session, name)
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


def export_wanted(session: dict, name: str) -> bool:
    """Whether an artifact needs a Word copy: the user asked for them, or Yoodli takes it
    as an upload and no Google Doc stands in for it."""
    settings = session['settings']
    if 'word' in settings['copies']:
        return exportable(name)
    if 'google' in settings['copies'] or 'yoodli' not in settings['stages']:
        return False
    base = split(name)[0]
    return base == 'brief' or base.startswith('yoodli:')


def export_states(root: Path, session: dict) -> dict[str, str]:
    """Whether each wanted export is current, outdated, missing or unavailable."""
    states = {}
    for name in artifact_names(root, session):
        if not export_wanted(session, name):
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


def findings_index(record: dict) -> dict[str, str]:
    """The status of every research question in a harness-research record."""
    return {item['id']: record['results'].get(item['id'], {}).get('status', 'pending')
            for item in record['items']}


def research_summary(root: Path, session: dict, approved: bool) -> dict | None:
    """The research run and how many findings have each status.

    Approved research is summarised as it was approved. Before that, or once it has changed,
    the summary is of the record as it stands, with no approval date.
    """
    entry = session['artifacts'].get('research', {}).get('approved')
    if approved and entry and session.get('research'):
        index, run, at = session.get('findings') or {}, session['research']['run'], entry['at']
    else:
        found = research_record(root)
        if found is None:
            return None
        index, run, at = findings_index(found), found.get('run'), None
    counts: dict[str, int] = {}
    for value in index.values():
        counts[value] = counts.get(value, 0) + 1
    return {'approved_at': at, 'run': run, 'findings': counts}


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
        'gate': session.get('gate'),
        'approval': session['settings']['approval'],
        'requests': session['requests'],
        'settings': session['settings'],
        'unavailable_stages': session['unavailable'],
        'pins': session['pins'],
        'research': research_summary(root, session, state.get('research') == 'approved'),
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


def on_the_page_only(session: dict, by: str, what: str) -> None:
    """Refuse a decision that did not come from the page, once approval has moved there."""
    if session['settings']['approval'] == 'page' and by != 'page':
        raise WorkspaceError(f'{sentence(what)} is decided on the page for this training, not '
                             f'on the command line. {OPEN_THE_PAGE}')


def input_label(key: str) -> str:
    """One of the things an artifact is built from, in plain words: "the blueprint"."""
    if key.startswith('setting:'):
        return f"the {key.partition(':')[2].replace('_', ' ')} setting"
    return 'the Yoodli profile' if key == 'profile' else label(key)


def give_a_reason(by: str, what: str = '') -> str:
    """The refusal for a missing reason, naming the flag on the command line."""
    return (f'Give a reason{what}.' if by == 'page'
            else f'Give a reason{what}: add `--reason "<the reason>"`.')


def close_requests(session: dict, name: str) -> None:
    session['requests'] = [request for request in session['requests']
                           if request.get('artifact') != name]


def _approve(root: Path, session: dict, name: str, accept_stale: str | None,
             by: str) -> dict:
    """Approve what is on disk in a loaded record. The caller stores it."""
    spec = artifact(root, session, name)
    check_choice(by, tuple(WHERE), 'Who decided')
    if name != 'intake':  # intake records the user's own answers, given in the conversation
        on_the_page_only(session, by, f'approval of {label(name)}')
    path = managed(root, spec['file'])
    state = statuses(root, session)
    if state[name] in ('skipped', 'unavailable'):
        raise WorkspaceError(f'Cannot approve {name}: it is {state[name]}.')
    if sha256_file(path) is None:
        raise WorkspaceError(f"Cannot approve {name}: {spec['file']} does not exist.")
    for upstream in spec['upstream']:
        if state[upstream] not in ('approved', 'skipped'):
            raise WorkspaceError(f'Cannot approve {name}: {upstream} is {state[upstream]}. '
                                 + (f'Rebuild {upstream}, or accept it as it is, first.'
                                    if state[upstream] == 'stale'
                                    else f'Approve {upstream} first.'))
    entry = record(root, session, name, built=False)
    current = pinned_inputs(root, session, name)
    if entry['built_from'] != current:
        if not accept_stale:
            changed = [input_label(key) for key in dict.fromkeys([*entry['built_from'], *current])
                       if entry['built_from'].get(key) != current.get(key)]
            fix = ('accept it as it is with a reason.' if by == 'page' else
                   'if the user accepts it as it is, run `approve '
                   f'{name} --accept-stale --reason "<their reason>"`.')
            raise WorkspaceError(f'{name} was built from an older version of '
                                 f'{" and ".join(changed)}. Rebuild it, or {fix}')
        session['decisions'].append({'at': now(), 'artifact': name,
                                     'decision': 'accepted-stale', 'from': entry['built_from'],
                                     'to': current, 'reason': accept_stale, 'by': by})
        entry['built_from'] = current
    entry['approved'] = {'sha256': entry['sha256'], 'inputs': dict(entry['built_from']),
                         'at': now(), 'by': by}
    close_requests(session, name)
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
            session['findings'] = findings_index(found)
            pending = sorted(key for key, value in session['findings'].items()
                             if value == 'pending')
            if pending:
                warnings.append('Research questions still pending: ' + ', '.join(pending))
    log(session, 'approve', artifact=name, sha256=entry['sha256'], by=by)
    return {'artifact': name, 'approved': entry['approved'], 'warnings': warnings}


@mutating
def approve(root: Path, name: str, accept_stale: str | None = None,
            by: str = 'chat') -> dict:
    """Record the user's approval of what is on disk, against what it was built from."""
    session = load(root)
    outcome = _approve(root, session, name, accept_stale, by)
    store(root, session)
    return outcome


# --- where the training is ------------------------------------------------------

def steps(session: dict) -> list[tuple[str, str | None]]:
    """The training's steps in order, as (stage, level): the shared stages, every level's
    blueprint together, then each level's own stages, lowest level first, then the package."""
    found = [(stage, None) for stage in ('intake', 'research-plan', 'research', 'blueprint')]
    for level in session['levels'] or [None]:
        found += [(stage, level) for stage in LEVEL_STAGES]
    return found + [('package', None), ('done', None)]


def step_of(session: dict, stage: str, level: str | None) -> int:
    """Where a stage, at a level, comes in the training's steps."""
    if stage not in LEVEL_STAGES:
        level = None
    elif session['levels'] and level not in session['levels']:
        level = session['levels'][0]
    return steps(session).index((stage, level))


def ahead(session: dict, stage: str, level: str | None) -> str:
    """What to do at a step, as the next step."""
    if stage == 'blueprint' and session['levels']:
        return 'Draft the blueprint for each level'
    return AHEAD[stage].format(the='the' if level is None else f'the {level}')


def left_at(root: Path, session: dict, state: dict, stage: str,
            level: str | None) -> list[str] | None:
    """What is still to approve at a step: empty when it is finished or left out, None when
    it has nothing to approve yet, as with no scenario files, or the package."""
    if stage in ('package', 'done'):
        return None
    if stage in SKIPPABLE and (stage not in session['settings']['stages']
                               or stage in session['unavailable']):
        return []
    names = [name for name in state if artifact(root, session, name)['stage'] == stage
             and (stage == 'blueprint' or split(name)[1] == level)]
    if not names:
        return None
    return [name for name in names if state[name] not in ('approved', 'skipped', 'unavailable')]


def move_on(root: Path, session: dict, after: int) -> str:
    """Move the training to the first step after `after` that still has work in it, and
    return what to do there."""
    state = statuses(root, session)
    for stage, level in steps(session)[after + 1:]:
        if left_at(root, session, state, stage, level) != []:
            break
    session['stage'] = stage
    if level is not None:
        session['level'] = level
    return ahead(session, stage, level)


def after_approval(root: Path, session: dict, name: str, said: str) -> str:
    """The next step once an artifact is approved, moving the training on if its stage is
    finished. An artifact from a stage already behind the training moves nothing."""
    spec, level = artifact(root, session, name), split(name)[1]
    here = step_of(session, session['stage'], session.get('level'))
    step = step_of(session, spec['stage'], level)
    if step < here:
        next_step = ahead(session, session['stage'], session.get('level'))
        return f'{said} Next: {next_step[:1].lower()}{next_step[1:]}.'
    left = left_at(root, session, statuses(root, session), spec['stage'], level)
    if left:
        return f'{said} Still to do at this stage: ' + ', '.join(map(label, left)) + '.'
    return move_on(root, session, step)


# --- decisions ------------------------------------------------------------------

def review_file(name: str) -> str:
    """Where the reviews of an artifact are kept, with `:` and `@` written as `-`."""
    return 'reviews/' + re.sub(r'[:@]', '-', name) + '.md'


def review_path(root: Path, name: str) -> Path:
    """An artifact's review file, refused if writing it would leave the training directory."""
    path = managed(root, review_file(name))
    if path.parent.is_symlink() or root.resolve() not in path.resolve().parents:
        raise WorkspaceError('The reviews folder must be a real folder in the training '
                             'directory.')
    return path


def append_review(root: Path, name: str, heading: str, note: str | None) -> None:
    """Add a dated entry to an artifact's review file, making the file if it is missing."""
    path = review_path(root, name)
    text = path.read_text(encoding='utf-8') if path.is_file() else f'# Reviews of {name}\n'
    entry = f'\n## {heading}\n'
    if note:
        # Quoted, so nothing in a note can pass for a heading or another entry.
        entry += '\n' + '\n'.join(f'> {line}'.rstrip() for line in note.splitlines()) + '\n'
    write_atomic(path, (text.rstrip('\n') + '\n' + entry).encode('utf-8'))


def shortened(note: str, limit: int = 200) -> str:
    """A note as one line of a sentence; `requests` and the review keep it whole."""
    line = ' '.join(note.split())
    return line if len(line) <= limit else line[:limit - 1].rstrip() + '…'


DECIDED = {'approve': 'approved', 'accept': 'accepted as it is',
           'revise': 'changes asked for', 'rebuild': 'a rebuild asked for',
           'skip': 'its stage left out', 'restore': 'its stage brought back'}


@mutating
def decide(root: Path, target: str, decision: str, note: str | None = None,
           by: str = 'chat', seen: str | None = None) -> dict:
    """Record what the user decided about an artifact, at a gate or after it.

    `approve`, `accept`, `revise` and `rebuild` are about one artifact. `skip` and `restore`
    are about a stage, named itself or by one of its artifacts. `seen` is the hash of the
    version the user was shown: an approval of anything else is refused.
    """
    session = load(root)
    check_choice(decision, DECISIONS, 'A decision')
    check_choice(by, tuple(WHERE), 'Who decided')
    note = (note or '').strip() or None
    where, brief = WHERE[by], shortened(note or '')
    names = artifact_names(root, session)
    outcome: dict = {}
    next_step = None
    if decision in ('skip', 'restore'):
        if target in SKIPPABLE:
            stage = target
        elif target in names:
            stage = artifact(root, session, target)['stage']
        else:
            raise WorkspaceError(f'{target} is not a stage or an artifact of this training.')
        outcome = _skip(session, stage, note, clear=decision == 'restore', by=by)
        names = list(dict.fromkeys(names + artifact_names(root, session)))
        about = [name for name in names if artifact(root, session, name)['stage'] == stage]
        for name in about:
            review_path(root, name)
        subject = STAGE_LABELS[stage]
        said = (f'{subject} was brought back {where}.' if decision == 'restore'
                else f'{subject} was left out {where}: {brief}')
        outcome['stage'] = stage
        if decision == 'skip' and stage == session['stage']:
            next_step = move_on(root, session,
                                step_of(session, stage, session.get('level')))
    else:
        if target not in names:
            raise WorkspaceError(f'{target} is not an artifact of this training.')
        about, subject = [target], label(target)
        review_path(root, target)  # before anything is decided: the decision is written there
        outcome['artifact'] = target
        if decision in ('approve', 'accept'):
            if decision == 'accept' and not note:
                raise WorkspaceError(give_a_reason(by, ' for accepting it as it is'))
            file = managed(root, artifact(root, session, target)['file'])
            if seen is not None and seen != sha256_file(file):
                raise WorkspaceError(f'{sentence(subject)} has changed since it was opened. '
                                     'Read the new version before deciding.')
            outcome.update(_approve(root, session, target,
                                    note if decision == 'accept' else None, by))
            said = (f'{subject} was approved {where}.' if decision == 'approve'
                    else f'{subject} was accepted as it is {where}: {brief}')
            next_step = after_approval(root, session, target, sentence(said))
        else:
            on_the_page_only(session, by, f'a request about {subject}')
            state = statuses(root, session)[target]
            if state in ('not-started', 'skipped', 'unavailable'):
                raise WorkspaceError(f'Nothing to change in {target}: it is {state}.')
            if decision == 'revise' and not note:
                raise WorkspaceError('Say what should change.')
            request = {'artifact': target, 'kind': decision, 'note': note, 'at': now()}
            session['requests'].append(request)
            log(session, 'request', artifact=target, kind=decision, by=by)
            outcome['request'] = request
            said = (f'Changes to {subject} were asked for {where}: {brief}'
                    if decision == 'revise'
                    else f'A rebuild of {subject} was asked for {where}'
                    + (f': {brief}' if note else '.'))
    session['pending_question'] = None
    session['gate'] = None
    session['next_step'] = next_step or sentence(said)
    store(root, session)
    for name in about:
        append_review(root, name, f'Decision: {DECIDED[decision]} {where}, {now()}', note)
    return {**outcome, 'decision': decision, 'by': by, 'said': sentence(said),
            'next_step': session['next_step'], 'requests': session['requests']}


# --- exports --------------------------------------------------------------------

PANDOC_TIMEOUT = 120  # seconds for one conversion
NO_PANDOC = ('pandoc, which makes Word copies, is not installed on this computer. Install it '
             'from pandoc.org, then make the copy again.')
PICTURE = ('![', '<img')  # how a Markdown file names a picture for pandoc to fetch


def export_spec(root: Path, session: dict, name: str) -> dict:
    """The artifact an export is of, once it is one this training keeps a Word copy of."""
    spec = artifact(root, session, name)
    if not exportable(name):
        raise WorkspaceError(f'{name} is not exported; only the document, the brief and '
                             'Yoodli scenarios are.')
    if not export_wanted(session, name):
        raise WorkspaceError(
            f'Word copies are off for this training, so no export of {name} is kept. To '
            'turn them on: checkpoint --copies '
            + ' '.join(sorted({*session['settings']['copies'], 'word'})) + '.')
    return spec


def export(root: Path, name: str, file: str | None = None, unavailable: str | None = None,
           convert=None) -> dict:
    """Record a converted copy of an artifact, or that one could not be produced.

    `convert`, a callable (source, target) such as `pandoc`, makes the copy first, beside
    its source, unless a file or a reason is given. It runs outside the lock, into a
    scratch folder, so a slow or failed conversion holds up nothing and leaves nothing
    behind. A conversion that fails is recorded as unavailable, with its reason, unless a
    copy made another way is already there.
    """
    if convert is None or file is not None or unavailable:
        return _export(root, name, file, unavailable)
    spec = export_spec(root, load(root), name)
    source = managed(root, spec['file'])
    digest = sha256_file(source)
    if digest is None:
        raise WorkspaceError(f"Cannot export {name}: {spec['file']} does not exist.")
    with tempfile.TemporaryDirectory() as scratch:
        draft = Path(scratch) / Path(spec['file']).with_suffix('.docx').name
        try:
            convert(source, draft)
            if not draft.is_file() or not draft.stat().st_size:
                raise WorkspaceError('The converter made no Word file.')
            made, reason = draft.read_bytes(), None
        except WorkspaceError as failure:
            made, reason = None, str(failure)
    return _export(root, name, made=made, made_from=digest, failed=reason)


@mutating
def _export(root: Path, name: str, file: str | None = None, unavailable: str | None = None,
            made: bytes | None = None, made_from: str | None = None,
            failed: str | None = None) -> dict:
    """Record an export: the file named, the copy just `made` from the source whose hash is
    `made_from`, or that none could be. `failed` says why a conversion made nothing."""
    session = load(root)
    spec = export_spec(root, session, name)
    if not unavailable:
        relative = file or str(Path(spec['file']).with_suffix('.docx'))
        path = (root / relative).resolve()
        if root not in path.parents:
            raise WorkspaceError('An export must be inside the training directory.')
        source = sha256_file(managed(root, spec['file']))
        if source is None:
            raise WorkspaceError(f"Cannot export {name}: {spec['file']} does not exist.")
        if made is not None:
            write_atomic(managed(root, relative), made)
            source = made_from
        elif failed is not None:
            # A copy made another way still counts, but not one already recorded against
            # an older version of the source.
            before = session['exports'].get(name) or {}
            old = (before.get('sha256') == sha256_file(path)
                   and before.get('source_sha256') != source)
            if not path.is_file() or old:
                unavailable = failed
        elif not path.is_file():
            raise WorkspaceError(f'{relative} does not exist.')
    if unavailable:
        record = {'unavailable': unavailable, 'at': now()}
    else:
        record = {'file': path.relative_to(root).as_posix(), 'source_sha256': source,
                  'sha256': sha256_file(path), 'at': now()}
    session['exports'][name] = record
    log(session, 'export', artifact=name)
    store(root, session)
    return record


def pandoc(source: Path, target: Path) -> None:
    """Convert a Markdown file to Word with pandoc, or refuse with a plain reason.

    pandoc is kept to the one file it is given: `--sandbox` stops it reading any other file
    or fetching anything from the web. A pandoc too old for `--sandbox` is used without it
    only for a file that names no picture, since a picture is what it would fetch.
    """
    program = shutil.which('pandoc')
    if program is None:
        raise WorkspaceError(NO_PANDOC)
    command = [program, '--from', 'markdown-raw_attribute', '--to', 'docx',
               '--output', str(target), str(source)]
    done = _pandoc([program, '--sandbox', *command[1:]])
    if done.returncode != 0:
        text = source.read_text(encoding='utf-8', errors='replace').lower()
        if not any(mark in text for mark in PICTURE):
            done = _pandoc(command)
    if done.returncode != 0 or not target.is_file():
        # Its first line that is not a warning says what went wrong.
        lines = [line.strip() for line in (done.stderr or '').splitlines()
                 if line.strip() and not line.lstrip().startswith('[')]
        said = lines[0] if lines else f'it ended with exit code {done.returncode}'
        for folder in (str(source.parent), str(target.parent)):
            said = said.replace(folder + os.sep, '').replace(folder, '')
        raise WorkspaceError(f"pandoc could not make the Word copy ({said[:200].rstrip('.')}).")


def _pandoc(command: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, capture_output=True, stdin=subprocess.DEVNULL,
                              timeout=PANDOC_TIMEOUT, encoding='utf-8', errors='replace')
    except subprocess.TimeoutExpired:
        raise WorkspaceError(f'pandoc did not finish in {PANDOC_TIMEOUT} seconds, so no Word '
                             'copy was made.') from None
    except OSError as failure:
        raise WorkspaceError('pandoc could not be started '
                             f'({failure.strerror or type(failure).__name__}), so no Word '
                             'copy was made.') from None


# --- skip, checkpoint, pin --------------------------------------------------------

def _skip(session: dict, stage: str, reason: str | None = None, unavailable: bool = False,
          clear: bool = False, by: str = 'chat') -> dict:
    """Skip a stage, mark it unavailable, or clear either mark, in a loaded record."""
    if stage not in SKIPPABLE:
        raise WorkspaceError('Only these stages can be skipped: ' + ', '.join(SKIPPABLE))
    check_choice(by, tuple(WHERE), 'Who decided')
    wanted = session['settings']['stages']
    # Saying a stage could not run, or that it now can, reports a fact. The rest are decisions.
    if not (clear and stage in wanted) and not (unavailable and not clear):
        on_the_page_only(session, by, f'leaving out or bringing back {STAGE_LABELS[stage]}')
    if clear:
        if stage == 'yoodli' and not {'brief', 'scenario'} <= set(wanted):
            raise WorkspaceError('Restore the brief and the scenarios first; a Yoodli '
                                 'scenario is built from both.')
        if stage not in wanted:
            wanted.append(stage)
            wanted.sort(key=SKIPPABLE.index)
        session['unavailable'].pop(stage, None)
        log(session, 'restore', stage=stage, by=by)
    elif not reason:
        raise WorkspaceError(give_a_reason(by))
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
        log(session, 'skip', stage=stage, reason=reason, by=by)
    return {'stages': wanted, 'unavailable': session['unavailable']}


@mutating
def skip(root: Path, stage: str, reason: str | None = None, unavailable: bool = False,
         clear: bool = False, by: str = 'chat') -> dict:
    """Skip a stage, mark it unavailable, or clear either mark."""
    session = load(root)
    outcome = _skip(session, stage, reason, unavailable, clear, by)
    store(root, session)
    return outcome


@mutating
def checkpoint(root: Path, stage: str | None = None, next_step: str | None = None,
               question: str | None = None, clear_question: bool = False,
               deck_target: str | None = None, brand: str | None = None,
               brief_kind: str | None = None, level: str | None = None,
               levels=None, copies=None, approval: str | None = None,
               gate: str | None = None, by: str = 'chat', add_levels=None) -> dict:
    """Record where the run is and change settings.

    `levels` sets the levels and never drops one with work in it; `add_levels` adds to them.
    """
    session = load(root)
    check_choice(stage, STAGES, 'The stage')
    check_choice(deck_target, DECK_TARGETS, 'The deck target')
    check_choice(brief_kind, BRIEF_KINDS, 'The brief kind')
    check_choice(approval, APPROVAL, 'Approval')
    check_choice(by, tuple(WHERE), 'Who decided')
    if approval is not None and approval != session['settings']['approval']:
        if approval == 'chat' and by != 'page':
            raise WorkspaceError('Approval was moved to the page for this training, and only '
                                 f'the page can move it back. {OPEN_THE_PAGE}')
        session['settings']['approval'] = approval
        log(session, 'approval', mode=approval, by=by)
    if levels is not None and add_levels is not None:
        raise WorkspaceError('Give the levels or a level to add, not both.')
    if levels is not None or add_levels is not None:
        if not session['levels']:
            raise WorkspaceError('A plain training cannot be given levels; start a levelled '
                                 'training in a new directory.')
        chosen = check_levels(levels if levels is not None
                              else [*session['levels'], *add_levels])
        if not chosen:
            raise WorkspaceError('A levelled training keeps at least one level.')
        for dropped in (level for level in session['levels'] if level not in chosen):
            work = level_work(root, dropped)
            if work:
                shown = ', '.join(work[:3]) + (f' and {len(work) - 3} more'
                                                if len(work) > 3 else '')
                raise WorkspaceError(
                    f'Level {dropped} has work in it ({shown}), so it cannot be dropped. To '
                    'add a level, use `checkpoint --add-level <level>`. To drop '
                    f'{dropped}, first move its folder {dropped}/ out of this training.')
        added = [level for level in chosen if level not in session['levels']]
        session['levels'] = chosen
        if session.get('level') not in chosen:
            session['level'] = None
        if added and STAGES.index(session['stage']) > STAGES.index('blueprint'):
            # A new level starts at its blueprint, whatever the others have reached.
            session['stage'], session['level'] = 'blueprint', added[0]
            session['next_step'] = (f"Draft the {' and '.join(added)} blueprint"
                                    + ('s' if len(added) > 1 else ''))
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
        session['gate'] = None
    if question is not None:
        session['pending_question'] = question
    if gate is not None:
        if gate not in artifact_names(root, session):
            raise WorkspaceError(f'{gate} is not an artifact of this training, so it cannot '
                                 'be at the gate.')
        session['gate'] = gate
    if deck_target is not None:
        session['settings']['deck_target'] = deck_target
    if brand is not None:
        session['settings']['brand'] = brand or None
    if brief_kind is not None:
        session['settings']['brief_kind'] = brief_kind
    if copies is not None:
        session['settings']['copies'] = check_copies(copies)
    log(session, 'checkpoint', stage=session['stage'])
    store(root, session)
    return {'stage': session['stage'], 'level': session.get('level'),
            'levels': session['levels'], 'next_step': session.get('next_step'),
            'pending_question': session.get('pending_question'),
            'gate': session.get('gate'),
            'review': review_file(session['gate']) if session.get('gate') else None,
            'settings': session['settings']}


def level_work(root: Path, level: str) -> list[str]:
    """Every file in a level's folder: the work that keeps the level from being dropped."""
    folder = root / level
    if not folder.is_dir():
        return []
    return sorted(path.relative_to(root).as_posix() for path in folder.rglob('*')
                  if path.is_file() or path.is_symlink())


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
