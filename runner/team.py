"""What sharing a workspace with teammates needs: who drives a training, the computer's own
notifications, what the workspace has published, and a training's folder brought in.

What a caller needs to know
---------------------------
    team.computer()                          # this computer's identifier, made once
    team.claim(space)                        # the driver this person on this computer is
    team.driver(space, record)               # {'name', 'here', 'since'} or None
    team.ours(space, record)                 # may this computer change the training?
    team.elsewhere(space, record)            # why not, in a sentence; None when it may

    notifier = team.Notifier()               # the computer's own notifications
    notifier.can()                           # (True, None) or (False, a sentence)
    notifier.send('Rolling restarts')        # its title, and that it needs a decision

    team.publish(space, ident, title, ready, by)   # the next revision, as a tag; never moved
    team.published(space)                    # each training's latest revision
    team.revisions(space, ident)             # how many of one training's there are
    team.taken(folder)                       # who took a training from this computer
    team.fetch_tags(space); team.send_tags(space)  # with the shared repository

    team.unacceptable(folder)                # why a folder cannot be brought in, or None
    team.copy_in(folder, target)             # the copy; the folder itself is only read

- A driver is kept in a training's run record as {'name', 'computer', 'since'}: the git
  identity, this computer's identifier and when. The identifier is random, made once, and
  kept in the per-user data folder as `computer.json`. It says nothing about the person
  or the computer.
- A workspace that is a folder on one computer has no drivers: `driver` is None and `ours`
  is true for every training there. In a shared workspace a training is ours only while
  its record names this computer. One that names nobody is nobody's until it is taken.
- Notifications go through a command that can be replaced: `TRAINING_STUDIO_NOTIFY` names a
  program that is given the title and the sentence as two arguments. Without it, macOS's
  own `osascript` is used, or `notify-send` where that is installed. What is said is handed
  over as arguments, never written into a script. Where there is none, `can` says so.
- A published revision is an annotated tag, `training-studio/<folder>/<id>/<number>`, on
  the commit where the workspace stood. Its message says what the page lists. A tag is
  never made twice, never moved and never pushed with force.
- Bringing a folder in reads it and never writes to it. A symbolic link, a repository of
  its own below the top, or a file larger than LARGEST is refused, because the workspace
  would not take it. The top folder's own `.git`, lock files and the guidance caches are
  not copied.
"""
from __future__ import annotations

import json
import os
import platform
import re
import secrets
import shlex
import shutil
import subprocess
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
import home
import hub
import workspace
from workspace import WorkspaceError

from runner import gitstate

SCHEMA = 1
REPLACED = 'TRAINING_STUDIO_NOTIFY'
APP = 'Training Studio'
SAYS = '"{title}" needs a decision.'
NO_WAY = ('This computer has no way to show a notification that the runner knows of. The '
          'page still notifies through the browser while it is open.')
LARGEST = 50_000_000    # bytes in one file a workspace takes
SCRIPT = ('on run argv', 'display notification (item 2 of argv) with title (item 1 of argv)',
          'end run')
SKIPPED = ('.git',)     # at the top of a folder brought in
NOBODY = ('Nobody is running this training. Take it to carry on with it from this '
          'computer.')


# --- this computer -----------------------------------------------------------------------

def computer() -> str:
    """This computer's identifier: random, made once, and kept in the per-user data
    folder. It holds no personal data."""
    path = home.data_root() / 'computer.json'
    kept = home.read_json(path, None)
    if isinstance(kept, dict) and kept.get('schema') == SCHEMA \
            and re.fullmatch(r'[0-9a-f]{16}', str(kept.get('id'))):
        return kept['id']
    made = secrets.token_hex(8)
    home.write_json(path, {'schema': SCHEMA, 'id': made})
    return made


def kept(name: str) -> dict:
    """Something this computer remembers for the team, by the name of its file."""
    found = home.read_json(home.data_root() / f'{name}.json', None)
    return found if isinstance(found, dict) else {}


def keep(name: str, value: dict) -> None:
    home.write_json(home.data_root() / f'{name}.json', value)


def taken(root: Path) -> dict | None:
    """Who took a training this computer used to drive, as the page is told: {'by', 'at',
    'kept'}, where `kept` is the ref that keeps what this computer never shared, or None.
    None for a training nobody took from it."""
    lost = kept('taken').get(str(root))
    if not isinstance(lost, dict) or not lost.get('name'):
        return None
    return {'by': lost['name'], 'at': lost.get('at'), 'kept': lost.get('kept')}


# --- one driver for each training --------------------------------------------------------

def claim(space: gitstate.Workspace) -> dict | None:
    """The driver this person on this computer would be. None where there are no drivers."""
    if space.address is None:
        return None
    return {'name': gitstate.identity(space.repo), 'computer': computer(),
            'since': home.now()}


def _named(record: dict | None) -> dict | None:
    found = (record or {}).get('driver')
    if isinstance(found, dict) and isinstance(found.get('computer'), str):
        return found
    return None


def driver(space: gitstate.Workspace | None, record: dict | None) -> dict | None:
    """Who drives a training, as the page is told: {'name', 'here', 'since'}. None for a
    training nobody drives, and for every training in a workspace with no remote."""
    found = _named(record)
    if space is None or space.address is None or found is None:
        return None
    return {'name': str(found.get('name') or 'Someone'),
            'here': found['computer'] == computer(), 'since': found.get('since')}


def ours(space: gitstate.Workspace | None, record: dict | None) -> bool:
    """True when this computer may change a training: always where there are no drivers,
    else only while its record names this computer."""
    if space is None or space.address is None:
        return True
    found = _named(record)
    return found is not None and found['computer'] == computer()


def day(stamp) -> str:
    """A time as a person reads it in a sentence."""
    text = str(stamp or '')
    return f'{text[:10]} at {text[11:16]} UTC' if len(text) >= 16 else 'an unknown time'


def elsewhere(space: gitstate.Workspace | None, record: dict | None) -> str | None:
    """Why this computer may not change a training, in a sentence. None when it may."""
    if ours(space, record):
        return None
    found = driver(space, record)
    if found is None:
        return NOBODY
    return (f"{found['name']} has been running this training from another computer since "
            f"{day(found['since'])}. It can be read here. Take it over to change it.")


# --- the computer's own notifications ----------------------------------------------------

class Notifier:
    """Tells the person something through the computer's own notifications."""

    def __init__(self, command=None, which=shutil.which, run=subprocess.run,
                 system=platform.system, environ=None):
        self.given, self.which, self.run, self.system = command, which, run, system
        self.environ = os.environ if environ is None else environ

    def command(self) -> list[str] | None:
        """The command the title and the sentence are added to, or None when this
        computer has none."""
        if self.given:
            return list(self.given)
        replaced = (self.environ.get(REPLACED) or '').strip()
        if replaced:
            return shlex.split(replaced)
        if self.system() == 'Darwin' and self.which('osascript'):
            script = [part for line in SCRIPT for part in ('-e', line)]
            return ['osascript', *script, '--']
        if self.which('notify-send'):
            return ['notify-send', '--']
        return None

    def can(self) -> tuple[bool, str | None]:
        return (True, None) if self.command() else (False, NO_WAY)

    def send(self, title: str) -> bool:
        """Say that a training needs a decision: its title and nothing else of it. False
        when it could not be said."""
        command = self.command()
        if command is None:
            return False
        try:
            done = self.run([*command, APP, SAYS.format(title=title)], capture_output=True,
                            stdin=subprocess.DEVNULL, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return False
        return getattr(done, 'returncode', 1) == 0


# --- publishing inside the workspace -----------------------------------------------------

def _prefix(space: gitstate.Workspace) -> str:
    return f'{gitstate.TOOL}/{space.folder}'


def _tags(space: gitstate.Workspace) -> list[dict]:
    """Every published revision this copy knows, as its tag says."""
    done = hub.run(space.repo, 'for-each-ref', '--format=%(refname:short)%1f%(contents)%1e',
                   f'refs/tags/{_prefix(space)}/')
    listed = []
    for entry in done.stdout.split('\x1e') if done.returncode == 0 else ():
        name, _, said = entry.strip('\n').partition('\x1f')
        parts = name.split('/')
        try:
            about = json.loads(said.strip().rpartition('\n\n')[2])
            revision = int(parts[-1])
        except ValueError:
            continue
        if not isinstance(about, dict) or len(parts) != 4 or about.get('id') != parts[2] \
                or revision < 1:
            continue
        listed.append({'tag': name, 'id': parts[2], 'title': str(about.get('title') or ''),
                       'revision': revision, 'at': about.get('at'), 'by': about.get('by'),
                       'ready': about.get('ready') is True})
    return listed


def published(space: gitstate.Workspace) -> list[dict]:
    """Each training's latest published revision, newest first: {'path', 'id', 'title',
    'revision', 'at', 'by', 'ready', 'current'}. `current` is false when the training's
    folder here has changed since that revision."""
    latest: dict[str, dict] = {}
    for entry in _tags(space):
        if entry['revision'] > latest.get(entry['id'], {'revision': 0})['revision']:
            latest[entry['id']] = entry
    same = _unchanged(space, list(latest.values()))
    return sorted(({'path': str(space.training(entry['id'])),
                    **{key: entry[key] for key in ('id', 'title', 'revision', 'at', 'by',
                                                   'ready')},
                    'current': entry['tag'] in same}
                   for entry in latest.values()),
                  key=lambda entry: str(entry['at']), reverse=True)


def revisions(space: gitstate.Workspace, ident: str) -> int:
    """How many revisions of one training this copy knows were published."""
    return sum(entry['id'] == ident for entry in _tags(space))


def _unchanged(space: gitstate.Workspace, entries: list[dict]) -> set[str]:
    """The tags whose training's folder is the same at the tag and at HEAD. One git
    command for them all: a folder is the same where git names the same tree for it."""
    if not entries:
        return set()
    asked = ''.join(f"refs/tags/{entry['tag']}:{space.folder}/{entry['id']}\n"
                    f"HEAD:{space.folder}/{entry['id']}\n" for entry in entries)
    done = hub.run(space.repo, 'cat-file', '--batch-check', input=asked)
    found = done.stdout.splitlines() if done.returncode == 0 else []
    if len(found) != 2 * len(entries):
        return set()
    return {entry['tag'] for entry, tagged, now in zip(entries, found[::2], found[1::2])
            if tagged == now}   # a missing one is named as it was asked, so never matches


def fetch_tags(space: gitstate.Workspace) -> bool:
    """Bring in the revisions teammates published. One this copy already has is never
    replaced. False when the shared repository could not be asked."""
    if space.address is None:
        return False
    spec = f'refs/tags/{_prefix(space)}/*'
    with gitstate.ASKING:
        return hub.passes(space.repo, 'fetch', '--quiet', '--no-tags', 'origin',
                          f'{spec}:{spec}')


def send_tags(space: gitstate.Workspace, only: str | None = None) -> str | None:
    """Push published revisions, never with force. Why the shared repository did not take
    them, or None when it did."""
    if space.address is None:
        return 'this workspace has no shared repository'
    spec = f'refs/tags/{only}' if only else f'refs/tags/{_prefix(space)}/*'
    with gitstate.ASKING:
        sent = hub.run(space.repo, 'push', '--quiet', 'origin', f'{spec}:{spec}')
    return None if sent.returncode == 0 else hub.reason(sent)


def publish(space: gitstate.Workspace, ident: str, title: str, ready: bool,
            by: str) -> dict:
    """Mark where the workspace stands as the next revision of one training, and push the
    mark when there is somewhere to push it. Returns {'revision', 'tag', 'shared', 'why'}.

    The number is one more than the highest this copy and the shared repository have.
    When someone else published that number in the same moment, theirs stands and this
    one takes the next. A revision that exists is never moved.
    """
    repo, reached = space.repo, fetch_tags(space)
    for _ in range(hub.ATTEMPTS):
        taken = [entry['revision'] for entry in _tags(space) if entry['id'] == ident]
        revision = max(taken, default=0) + 1
        name = f'{_prefix(space)}/{ident}/{revision}'
        about = {'id': ident, 'title': title, 'revision': revision, 'ready': bool(ready),
                 'at': home.now(), 'by': by}
        hub.git(repo, 'tag', '--annotate', '-m', f'Publish {title}, revision {revision}',
                '-m', json.dumps(about, sort_keys=True), name, 'HEAD')
        why = send_tags(space, name)
        if why is None or space.address is None or not reached:
            return {'revision': revision, 'tag': name, 'shared': why is None, 'why': why}
        hub.git(repo, 'tag', '--delete', name)  # never shared, so nothing is moved
        fetch_tags(space)
        if not any(entry['revision'] == revision and entry['id'] == ident
                   for entry in _tags(space)):
            break  # it was not the number: the shared repository refused for its own reason
    raise WorkspaceError(f'The shared repository did not take the revision ({why}). Nothing '
                         'was published. Check that you may push to it, then try again.')


# --- bringing a training in --------------------------------------------------------------

def _left_out(top: Path, path: Path) -> bool:
    """True for what is never copied: the top folder's own repository, lock files, and the
    guidance caches the two harness skills keep."""
    parts = path.relative_to(top).parts
    return (parts[0] in SKIPPED or path.name.endswith('.lock')
            or parts[-2:] == (workspace.STATE_DIR, 'lock')
            or (len(parts) >= 2 and parts[-1] == 'guidance'
                and parts[-2] in ('.harness-research', '.harness-slides')))


def _walk(top: Path):
    """Every path under a folder that would be copied, without following a link."""
    pending = [top]
    while pending:
        for path in sorted(pending.pop().iterdir()):
            if _left_out(top, path):
                continue
            yield path
            if path.is_dir() and not path.is_symlink():
                pending.append(path)


def unacceptable(top: Path) -> str | None:
    """Why a folder cannot be copied into a workspace, in a sentence, or None when it
    can. The folder is only read."""
    for path in _walk(top):
        name = path.relative_to(top).as_posix()
        if path.is_symlink():
            return f'{name} is a symbolic link, which a workspace does not take.'
        if path.is_dir() and path.name == '.git':
            return (f'{path.parent.relative_to(top).as_posix()} holds a repository of its '
                    'own, which a workspace does not take.')
        if path.is_file() and path.stat().st_size > LARGEST:
            return (f'{name} is larger than {LARGEST // 1_000_000} MB, which a workspace '
                    'does not take.')
        if not path.is_dir() and not path.is_file():
            return f'{name} is not a plain file, so a workspace does not take it.'
    return None


def copy_in(top: Path, target: Path) -> None:
    """Copy a folder into place whole, or leave nothing. The folder is only read."""
    def ignore(folder: str, names: list[str]) -> list[str]:
        return [name for name in names if _left_out(top, Path(folder) / name)]

    pending = target.with_name(f'.bringing-{secrets.token_hex(4)}')
    try:
        shutil.copytree(top, pending, ignore=ignore)
        pending.replace(target)
    finally:
        shutil.rmtree(pending, ignore_errors=True)
