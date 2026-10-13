"""The copies a training asked for: a Google Doc or a Word file of a guide, a brief or a
Yoodli scenario.

What a caller needs to know
---------------------------
    copies.wanted(root, problems=None)       # every copy the training asks for, as shown
    made, problems = copies.make(root, google=None, word=None)

- An entry is {'artifact', 'label', 'kind', 'state', 'link', 'problem'}. `kind` is 'google'
  or 'word'. `state` is 'made', 'out-of-date' or 'not-made'. `link` is the Doc's address,
  or the Word file's path from the training's folder, once there is one. `label` is the
  artifact's name as a person reads it.
- What is wanted is what the core says: `gdocs.copy_states` for Google Docs and
  `workspace.export_states` for Word. This module adds no rule of its own about which
  artifacts get a copy.
- `make` makes every wanted copy of an approved artifact that is not current, and leaves
  the rest alone. It never raises for a copy that cannot be made. A Word copy that cannot
  be made is recorded through the core as unavailable, with the reason. A Google Doc that
  cannot be made has nowhere in the core to say why, so `make` returns `problems`:
  {artifact: sentence}. The caller keeps them and passes them back to `wanted`.
- `google` is a `gdocs.Transport`; left out, it is `gdocs.GcloudTransport()`, which uses
  the Google access this computer already has. No credential is asked for, stored or
  printed here. `word` is a callable (source: Path, target: Path) -> None; left out, it
  runs `pandoc`, and a computer without it gets a sentence saying so.
- Nothing is approved, skipped or decided here.

`made` holds the entries of the copies this call made, as `wanted` would now give them.
A copy of something that is not approved yet is listed by `wanted` as not made, with no
problem: it is made when its file is approved.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
import gdocs
import workspace
from workspace import WorkspaceError

STATES = {'current': 'made', 'outdated': 'out-of-date', 'missing': 'not-made',
          'unavailable': 'not-made'}
TIMEOUT = 120           # seconds for one conversion
AGAIN = 'try the copies again'
NOT_SET_UP = ('Google access is not set up on this computer: the gcloud command was not '
              'found. Install the Google Cloud CLI, run `gcloud auth login '
              f'--enable-gdrive-access` in a terminal, then {AGAIN}.')
NO_PANDOC = ('Word copies are made with pandoc, which is not on this computer. Install it, '
             f'then {AGAIN}.')
# What the core says to an assistant, which has commands to run, said here for a person.
REWORDED = (
    ('changed since the last sync',
     'Someone has changed the Google Doc since it was last sent, so it was left as it is. '
     f'Ask your assistant to bring those changes into the training, then {AGAIN}.'),
    ('could not find the Doc',
     'Google could not find the Doc. It may have been deleted, or the signed-in account '
     f'cannot open it. Ask your assistant to unlink it from the training, then {AGAIN} to '
     'make a new one.'),
)
PICTURE = ('![', '<img')    # how a Markdown file names a picture for pandoc to fetch


# --- what is wanted ------------------------------------------------------------------------

def wanted(root: Path, problems: dict | None = None) -> list[dict]:
    """Every copy the training asks for, in the order of what each is a copy of."""
    root = Path(root)
    session = workspace.load(root)
    docs, files = gdocs.copy_states(root, session), workspace.export_states(root, session)
    links = gdocs.read_links(root)['docs'] if docs else {}
    listed = []
    for name in workspace.artifact_names(root, session):
        if name in docs:
            listed.append(_entry(name, 'google', STATES[docs[name]],
                                 links.get(name, {}).get('url'), (problems or {}).get(name)))
        if name in files:
            made = session['exports'].get(name) or {}
            state = STATES[files[name]]
            listed.append(_entry(name, 'word', state,
                                 None if state == 'not-made' else made.get('file'),
                                 made.get('unavailable')))
    return listed


def _entry(name: str, kind: str, state: str, link, problem) -> dict:
    return {'artifact': name, 'label': workspace.label(name), 'kind': kind, 'state': state,
            'link': link if isinstance(link, str) else None,
            'problem': problem if state != 'made' and isinstance(problem, str) else None}


# --- making them ---------------------------------------------------------------------------

def make(root: Path, google=None, word=None) -> tuple[list[dict], dict]:
    """Make every wanted copy of something approved that is not current. Returns the
    copies made and, for each Google Doc that could not be, why."""
    root = Path(root).resolve()
    approved = {name for name, status
                in workspace.statuses(root, workspace.load(root)).items()
                if status == 'approved'}
    tried, problems = [], {}
    for entry in wanted(root):
        name = entry['artifact']
        if entry['state'] == 'made' or name not in approved:
            continue
        tried.append((name, entry['kind']))
        if entry['kind'] == 'word':
            _word(root, name, word or pandoc)
        elif google is None and shutil.which('gcloud') is None:
            problems[name] = NOT_SET_UP
        else:
            google = google or gdocs.GcloudTransport()
            problem = _google(root, name, google)
            if problem:
                problems[name] = problem
    now = {(entry['artifact'], entry['kind']): entry for entry in wanted(root, problems)}
    return [now[key] for key in tried if key in now and now[key]['state'] == 'made'], problems


def _google(root: Path, name: str, transport) -> str | None:
    """Make one Google Doc, or bring it up to date. Returns why it could not be, else
    None. A Doc someone has edited is never written over."""
    try:
        gdocs.push(root, name, transport)
    except WorkspaceError as refusal:
        said = str(refusal)
        return next((ours for theirs, ours in REWORDED if theirs in said), said)
    except Exception as failure:  # a copy that cannot be made never stops a run
        # Only what kind of failure it was: its own words could hold anything.
        return ('Google Drive did not answer as it should have '
                f'({type(failure).__name__}), so the Google Doc was not made. Wait a '
                f'little, then {AGAIN}.')
    return None


def _word(root: Path, name: str, convert) -> None:
    """Make one Word copy beside its file and record it through the core, or record
    through the core why there is none."""
    spec = workspace.artifact(root, workspace.load(root), name)
    relative = Path(spec['file']).with_suffix('.docx').as_posix()
    reason = None
    try:
        source, target = workspace.managed(root, spec['file']), workspace.managed(root, relative)
        # Made outside the training first: a conversion that fails leaves nothing half
        # made where a copy belongs.
        with tempfile.TemporaryDirectory() as scratch:
            draft = Path(scratch) / target.name
            convert(source, draft)
            if not draft.is_file() or not draft.stat().st_size:
                raise WorkspaceError('The converter left no Word file. '
                                     f'{workspace.sentence(AGAIN)}.')
            workspace.write_atomic(target, draft.read_bytes())
    except WorkspaceError as refusal:
        reason = str(refusal)
    except Exception as failure:  # a copy that cannot be made never stops a run
        reason = (f'The Word copy could not be made ({type(failure).__name__}). '
                  f'{workspace.sentence(AGAIN)}.')
    try:
        workspace.export(root, name, **({'unavailable': reason} if reason
                                        else {'file': relative}))
    except WorkspaceError:
        pass  # the record could not be written now; the copy is tried again next time


def pandoc(source: Path, target: Path) -> None:
    """Convert a Markdown file to Word with pandoc. Refuses with a sentence when pandoc is
    not on this computer or does not finish.

    pandoc is kept to the one file it is given. A Markdown file can name a picture
    anywhere on this computer or on the web, and pandoc would fetch it into the copy. Where
    a pandoc cannot be kept so, it is used as it is only for a file that names no picture.
    """
    program = shutil.which('pandoc')
    if program is None:
        raise WorkspaceError(NO_PANDOC)
    command = [program, '--from', 'markdown-raw_attribute', '--to', 'docx',
               '--output', str(target), str(source)]
    done = _run([command[0], '--sandbox', *command[1:]])
    if done.returncode != 0:
        text = source.read_text(encoding='utf-8', errors='replace').lower()
        if not any(mark in text for mark in PICTURE):
            done = _run(command)
    if done.returncode != 0 or not target.is_file():
        # Its first line that is not a warning says what went wrong.
        lines = [line.strip() for line in (done.stderr or '').splitlines()
                 if line.strip() and not line.lstrip().startswith('[')]
        said = lines[0] if lines else f'it ended with exit code {done.returncode}'
        for folder in (str(source.parent), str(target.parent)):
            said = said.replace(folder, '')     # where this computer keeps things stays here
        raise WorkspaceError(f"pandoc could not make the Word copy ({said[:200].rstrip('.')}). "
                             f'Put that right, then {AGAIN}.')


def _run(command: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, capture_output=True, stdin=subprocess.DEVNULL,
                              timeout=TIMEOUT, encoding='utf-8', errors='replace')
    except subprocess.TimeoutExpired:
        raise WorkspaceError(f'pandoc did not finish in {TIMEOUT} seconds, so the Word copy '
                             f'was not made. {workspace.sentence(AGAIN)}.') from None
    except OSError as failure:
        raise WorkspaceError('pandoc could not be started '
                             f'({failure.strerror or type(failure).__name__}), so the Word '
                             f'copy was not made. {workspace.sentence(AGAIN)}.') from None
