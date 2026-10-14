"""Whether Training Studio and the skills it uses are in place and current. The runner looks
when it starts and when the page checks this computer again.

What a caller needs to know
---------------------------
    keep = upkeep.Upkeep(after=engine.look_again)   # this computer's home and installation
    keep.start()                 # in the background: put back what is safe, then look online
    keep.again()                 # "Check again": the part on this computer now, online after
    keep.check(repair=False)     # the part on this computer only, changing nothing
    keep.report()                # what was found, for the page; never waits, starts nothing
    keep.update(working)         # bring the missing or older companions; refuses in a sentence
    keep.close()                 # end an update in hand

- It asks the installer beside the runner, `../installer/install.py`. That file is there in a
  checkout and in each installed version alike, with the pins the version was installed
  with. Nothing here is a second implementation of what the installer does.
- What is put back without asking, and only where the installer recorded placing it:
  - the skill link of an assistant Training Studio was installed for, when it is missing,
    the copy it points at is whole and the assistant's skill folder is still there;
  - the `current` link, when it is missing or points nowhere;
  - the `studio` and `training` commands, when they are missing.

  Anything else in the way, such as a link pointing elsewhere or a real folder, is left
  alone and said. A companion's links belong to its own installer, so a missing one is not
  put back here: it is shown, with Update.
- `update` runs `install.py companions` from the same copy, as a command of its own under
  `companion.supervise`, with UPDATE_SECONDS to finish; `close` ends it.
  - It is refused while a training on this computer is working, since a step in hand uses
    the companion it found when it started.
  - When it ends, `after` is called, so that the computer is looked at again.
- Online, at most once a day and only while the setting `look_for_updates` is on:
  - It runs `git ls-remote --tags` against Training Studio's repository and each
    companion's, through `hub.run`, with LOOK_SECONDS to answer.
  - Only the tags are kept, in `updates.json` in the data folder. Whether one is newer is
    worked out each time it is shown. Nothing is downloaded or run.
  - Training Studio is also compared with the version on `main` when guidance was last
    fetched. That is read from the guidance cache, which needs no network.
- The report says which guidance a new training is given: the revision the last guidance
  start resolved, or the copy installed with this version.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
import home
import hub
import sync_guidance
from workspace import WorkspaceError

from runner import companion, settings

INSTALLER = Path(__file__).resolve().parent.parent / 'installer' / 'install.py'
SAVED = 'updates.json'    # in the data folder: the releases last found online, and when
DAY = 24 * 3600           # seconds between looks online
LOOK_SECONDS = 15         # for one repository to answer
UPDATE_SECONDS = 2400     # for the companions to be fetched, checked and installed
SELF = 'training-studio'
TAG = re.compile(r'^[0-9a-f]+\trefs/tags/v?(\d+\.\d+\.\d+)$')
COMMANDS = {'command': 'The command that opens Training Studio',
            'helper': "The command the skill runs its helper with"}
NO_INSTALLER = ('This copy of the runner has no installer beside it, so the skills cannot be '
                'checked or updated from here. Run the installer again.')
WORKING = ('A training on this computer is working now, and a step in hand keeps using the '
           'skill it started with. Pause it, or wait until it stops for you, then update.')
UPDATING = 'The companion skills are being updated already.'
NOTHING = 'Every companion skill is already as new as this Training Studio was made with.'
STOPPED = 'The update was stopped when Training Studio closed. Nothing more was changed.'


def _now() -> str:
    return home.now()


def _age(stamp: str | None) -> float | None:
    """Seconds since a time this module wrote, or None when it cannot be read."""
    try:
        then = datetime.strptime(str(stamp), '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - then).total_seconds()


def _version(text: str) -> tuple:
    try:
        return tuple(int(part) for part in text.split('.'))
    except (AttributeError, ValueError):
        return ()


def newest(listed: str) -> str | None:
    """The newest release among the tags `git ls-remote --tags` printed, or None."""
    found = [match.group(1) for line in listed.splitlines()
             if (match := TAG.match(line.strip()))]
    return max(found, key=_version) if found else None


def install_root(runner_dir: Path | None = None) -> Path:
    """Where the installer keeps its record: the folder of `versions/` the runner was
    installed in, or else the data folder, where a linked checkout's record is."""
    here = (runner_dir or Path(__file__).resolve().parent).parent
    if here.parent.name == 'versions':
        return here.parent.parent
    return home.data_root()


def _load(path: Path):
    """The installer at `path`, as a module, or None when it is not there or cannot load."""
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location('training_studio_installer', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:  # an installer that cannot be loaded is said, not raised
        return None
    return module


def _who(names: list[str]) -> str:
    return ' and '.join(names)


class Upkeep:
    """What the runner knows about the skills on this computer, and the one update in hand."""

    def __init__(self, home_dir: Path | None = None, root: Path | None = None,
                 installer: Path | None = None, after=None):
        self.home = Path(home_dir or Path.home())
        self.root = Path(root or install_root())
        self.installer = Path(installer or INSTALLER)
        self.after = after
        self._module = None
        self._lock = threading.Lock()
        self._found: dict | None = None      # the last look on this computer
        self._update: dict | None = None     # the update in hand, or the last one
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()

    # --- in the background ---------------------------------------------------------------

    def start(self) -> None:
        """Look on this computer, putting back what is safe, then online when that is due.
        All of it in the background: the page answers meanwhile."""
        self._background(self._first, 'looking at the skills')

    def again(self) -> None:
        """The page's "Check again": the part on this computer now, online in the
        background when that is due."""
        self.check(repair=True)
        self._background(self.look, 'looking for releases')

    def _first(self) -> None:
        self.check(repair=True)
        self.look()

    def _background(self, work, name: str) -> None:
        thread = threading.Thread(target=work, daemon=True, name=name)
        self._threads.append(thread)
        thread.start()

    def close(self) -> None:
        """End an update in hand. What was looked at is kept."""
        self._stop.set()
        for thread in self._threads:
            if thread is not threading.current_thread():
                thread.join(timeout=10)

    # --- on this computer ----------------------------------------------------------------

    def module(self):
        if self._module is None:
            self._module = _load(self.installer)
        return self._module

    def check(self, repair: bool = True) -> dict:
        """Look at the links, the commands and the companions on this computer, putting back
        what is safe when `repair`. Never raises: what went wrong is said in the report."""
        try:
            found = self._local(repair)
        except Exception as failure:  # the runner keeps serving, and says so
            found = self._blank(f'Looking at the skills on this computer did not work '
                                f'({type(failure).__name__}: {failure}).')
        with self._lock:
            self._found = found
        return found

    def _blank(self, problem: str | None) -> dict:
        return {'at': _now(), 'installer': False, 'mode': None, 'links': [], 'repaired': [],
                'companions': [], 'problem': problem, 'main': None}

    def _local(self, repair: bool) -> dict:
        install = self.module()
        if install is None:
            return {**self._blank(NO_INSTALLER), 'main': self._main_version()}
        problem = None
        try:
            state = install.read_state(self.root)
        except install.InstallError as refusal:
            state, problem = None, str(refusal)
        repaired = self._current(install, state) if state and repair else []
        chosen = list(state.get('links', {})) if state else install.found_harnesses(self.home)
        links = [self._link(install, state, harness, repair) for harness in chosen]
        repaired += [link['says'] for link in links if link['state'] == 'repaired']
        if state and repair:
            repaired += self._commands(install, state)
        try:
            pins = install.read_pins(self.installer.parent / 'companions.json')
        except install.InstallError as refusal:
            pins, problem = {}, problem or str(refusal)
        return {'at': _now(), 'installer': True, 'mode': (state or {}).get('mode'),
                'links': links, 'repaired': repaired, 'problem': problem,
                'companions': [self._companion(install, name, pin, chosen)
                               for name, pin in pins.items()],
                'main': self._main_version()}

    def _current(self, install, state: dict) -> list[str]:
        """Put back the link to the installed version when it is missing or points nowhere."""
        current = self.root / 'current'
        kept = state.get('current')
        staged = self.root / 'versions' / str(kept)
        if state.get('mode') != 'managed' or not kept or current.exists() \
                or not staged.is_dir():
            return []
        install.replace_link(current, staged)
        return [f'The link to the installed version was missing, and was put back: {current}.']

    def _link(self, install, state: dict | None, harness: str, repair: bool) -> dict:
        """The Training Studio link of one assistant: as it is, or put back."""
        name = install.HARNESS[harness]
        entry = (state or {}).get('links', {}).get(harness)
        shown = {'assistant': name, 'name': install.NAME}
        if entry is None:   # not installed for it, as with a checkout that was never linked
            link = install.skill_link(self.home, harness)
            here = (link / 'SKILL.md').is_file()
            return {**shown, 'path': str(link), 'state': 'ok' if here else 'missing',
                    'says': None if here else f'Training Studio is not installed for {name}. '
                    'Run the installer to install it.'}
        link, target = Path(entry['path']), str(entry['target'])
        shown['path'] = str(link)
        if link.is_symlink() and os.readlink(link) == target:
            if (link / 'SKILL.md').is_file():
                return {**shown, 'state': 'ok', 'says': None}
            return {**shown, 'state': 'missing', 'says': f'The link for {name} points at '
                    f'{target}, which is not there any more. Run the installer again.'}
        if link.exists() or link.is_symlink():
            return {**shown, 'state': 'left alone', 'says': f'{link} is not the link the '
                    'installer placed, so it was left alone. Run the installer again to '
                    'link Training Studio there.'}
        if not link.parent.is_dir():
            return {**shown, 'state': 'left alone', 'says': f"{name}'s skill folder, "
                    f'{link.parent}, is gone, so Training Studio was not linked into it again.'}
        if not (Path(target) / 'SKILL.md').is_file():
            return {**shown, 'state': 'missing', 'says': f'The link for {name} is missing, and '
                    f'the copy it pointed at, {target}, is not there either. Run the installer '
                    'again.'}
        if not repair:
            return {**shown, 'state': 'missing', 'says': f'The link for {name} is missing. It '
                    'is put back when Training Studio starts.'}
        install.replace_link(link, Path(target))
        return {**shown, 'state': 'repaired', 'says': f'The link for {name} was missing, and '
                f'was put back: {link}.'}

    def _commands(self, install, state: dict) -> list[str]:
        """Write again the commands the installer wrote, where one is missing. A file of
        someone's own in their place is left alone by the installer itself."""
        kept = state.get('launchers', {})
        missing = tuple(kind for kind in COMMANDS if kind in kept
                        and not os.path.lexists(kept[kind]))
        studio = Path(str(state.get('runner', '')))
        scripts = (Path(str(state.get('source', ''))) if state.get('mode') == 'link'
                   else self.root / 'current') / 'scripts'
        if not missing or not studio.is_file() or not scripts.is_dir():
            return []
        written = install.write_launchers(self.home, self.root, studio, scripts, missing)
        return [f'{COMMANDS[kind]} was missing, and was written again: {path}.'
                for kind, path in written.items()]

    def _companion(self, install, name: str, pin: dict, chosen: list[str]) -> dict:
        """One companion, for each assistant Training Studio is installed for."""
        found = install.companion_found(self.home, chosen, name)
        short = install.wanting(found, pin['version'])
        unread = [install.HARNESS[harness] for harness, version in found.items()
                  if version == '']
        wanted, need = pin['version'], install.NEEDS.get(
            name, 'part of a training cannot be made without it')
        who = _who([install.HARNESS[harness] for harness in short])
        if short and all(found[harness] is None for harness in short):
            state, says = 'missing', (f'{name} is not installed for {who}, and {need}. This '
                                      f'Training Studio was made with {wanted}.')
        elif short:
            state, says = 'older', (f'{name} for {who} is older than the {wanted} this '
                                    f'Training Studio was made with.')
        elif unread:
            state, says = 'unread', (f'{name} is there for {_who(unread)}, but not as its '
                                     'own installer leaves it, so its version could not be '
                                     'read. It was left alone.')
        elif not chosen:
            state, says = 'missing', f'{name} cannot be looked for: no assistant was found.'
        else:
            having = sorted({version for version in found.values() if version}, key=_version)
            state, says = 'ok', f"{name} {', '.join(having)}, for " + _who(
                [install.HARNESS[harness] for harness in found]) + '.'
        return {'name': name, 'wanted': wanted, 'state': state, 'says': says,
                'found': {install.HARNESS[harness]: version
                          for harness, version in found.items()},
                'repository': pin['repository'].removesuffix('.git'),
                'commit': pin['commit'][:12], 'note': pin.get('note')}

    @staticmethod
    def _main_version() -> str | None:
        """Training Studio's version on the source branch when guidance was last fetched,
        read from the helper's guidance cache with its own isolated git. Nothing is fetched,
        and a cache the helper would not use is not read: it is the helper's to rebuild."""
        cache = sync_guidance.guidance_root() / 'cache.git'
        if not sync_guidance.ours(cache):
            return None
        try:
            commit = sync_guidance.git('rev-parse', '--verify',
                                       f'{sync_guidance.MAIN}^{{commit}}',
                                       repo=cache).decode().strip()
            # Not `manifest()`: that refuses guidance a newer version needs, which is just
            # what is looked for here.
            kept = json.loads(sync_guidance.git(
                'cat-file', 'blob', f'{commit}:guidance/manifest.json', repo=cache))
            root = str(kept['content_root']).strip('/')
            found = sync_guidance.git('cat-file', 'blob', f'{commit}:{root}/VERSION',
                                      repo=cache).decode().strip()
        except (sync_guidance.SyncError, ValueError, KeyError, TypeError, AttributeError,
                UnicodeDecodeError):
            return None
        return found if _version(found) else None

    # --- online --------------------------------------------------------------------------

    @staticmethod
    def saved_path() -> Path:
        return home.data_root() / SAVED

    def due(self) -> bool:
        """Whether looking online is on, and a day has passed since it last looked."""
        if not settings.load().look_for_updates:
            return False
        kept = home.read_json(self.saved_path(), None)
        age = _age(kept.get('at')) if isinstance(kept, dict) else None
        return age is None or age >= DAY or age < 0

    def repositories(self) -> dict:
        """Where each release is looked for: Training Studio's repository and each
        companion's, as its pin names it."""
        found = {SELF: sync_guidance.source()['repository']}
        install = self.module()
        if install is not None:
            try:
                pins = install.read_pins(self.installer.parent / 'companions.json')
            except install.InstallError:
                pins = {}
            found.update({name: pin['repository'] for name, pin in pins.items()})
        return found

    def look(self) -> bool:
        """Ask each repository which releases it has, when that is due. Only the tags are
        read: nothing is downloaded or run. True when it looked."""
        if not self.due():
            return False
        place = home.data_root()
        place.mkdir(parents=True, exist_ok=True)
        found = {}
        for name, repository in self.repositories().items():
            entry = {'repository': repository, 'latest': None, 'problem': None}
            try:
                done = hub.run(place, 'ls-remote', '--tags', '--refs', '--', repository,
                               timeout=LOOK_SECONDS)
            except WorkspaceError as refusal:
                entry['problem'] = str(refusal).rstrip('.')
            else:
                if done.returncode == 0:
                    entry['latest'] = newest(done.stdout)
                else:
                    entry['problem'] = hub.reason(done)
            found[name] = entry
        home.write_json(self.saved_path(), {'schema': 1, 'at': _now(), 'found': found})
        return True

    # --- the update ----------------------------------------------------------------------

    def update(self, working: bool) -> dict:
        """Bring each companion that is missing or older than its pin, through the
        installer's own checked install, in the background. Refused, in a sentence, while a
        training is working, while an update is in hand, and when there is nothing to do."""
        with self._lock:
            found = self._found
            if self._update and self._update['state'] == 'running':
                raise WorkspaceError(UPDATING)
        if found is None:
            found = self.check(repair=False)
        if not found['installer']:
            raise WorkspaceError(NO_INSTALLER)
        names = [entry['name'] for entry in found['companions']
                 if entry['state'] in ('missing', 'older')]
        if not names:
            raise WorkspaceError(NOTHING)
        if working:
            raise WorkspaceError(WORKING)
        with self._lock:
            if self._update and self._update['state'] == 'running':
                raise WorkspaceError(UPDATING)
            self._update = {'state': 'running', 'since': _now(), 'names': names,
                            'says': f'Bringing {_who(names)}. This can take a few minutes.'}
        self._background(lambda: self._bring(names), 'updating the skills')
        return self.report()

    def _bring(self, names: list[str]) -> None:
        command = [sys.executable, '-B', str(self.installer), 'companions', '--companions',
                   'install', '--while-open', '--json', '--home', str(self.home), '--root',
                   str(self.root)]
        printed: list[bytes] = []
        state, says = 'failed', None
        try:
            with tempfile.TemporaryFile() as errors:
                code, late = companion.supervise(command, None, None, '', UPDATE_SECONDS,
                                                 errors, printed.append, self._stop)
                errors.seek(0)
                complaint = errors.read().decode('utf-8', 'replace').strip()
            if self._stop.is_set():
                says = STOPPED
            elif late:
                says = (f'The update did not finish in {UPDATE_SECONDS // 60} minutes, so it '
                        'was ended. Try again, or run the installer.')
            else:
                state, says = self._said(code, b''.join(printed), complaint)
        except Exception as failure:  # said on the page; the runner keeps serving
            says = f'The update could not be run ({type(failure).__name__}: {failure}).'
        with self._lock:
            self._update = {**(self._update or {}), 'state': state, 'says': says,
                            'ended': _now()}
        self.check(repair=False)
        if self.after is not None:
            try:
                self.after()
            except Exception:  # a look that fails is the next look's to say
                pass

    @staticmethod
    def _said(code: int, printed: bytes, complaint: str) -> tuple[str, str]:
        """What the installer said it did, in sentences: ('done' or 'failed', says)."""
        try:
            result = json.loads(printed.decode('utf-8', 'replace'))
        except ValueError:
            result = None
        if not isinstance(result, dict):
            line = (complaint.splitlines() or ['it said nothing'])[-1][:300]
            return 'failed', f'The installer did not answer as expected: {line}'
        if 'error' in result or code != 0:
            return 'failed', f"Nothing was updated: {result.get('error', 'the installer failed')}"
        lines, whole = [], True
        for name, outcome in (result.get('companions') or {}).items():
            if outcome.get('state') == 'installed':
                lines.append(f"{name} {outcome.get('wanted')} was installed by its own "
                             'installer.')
            elif outcome.get('state') in ('failed', 'refused'):
                whole = False
                lines.append(f"{name} {outcome.get('wanted')} was not installed: "
                             f"{outcome.get('detail')}")
        return ('done' if whole else 'failed'), ' '.join(lines) or 'Nothing needed bringing.'

    # --- what is said ----------------------------------------------------------------------

    def command(self) -> str | None:
        """The command that installs a newer Training Studio, from the checkout it was
        installed from, when that is still there."""
        install = self.module()
        try:
            state = install.read_state(self.root) if install else None
        except install.InstallError:
            state = None
        source = Path(str((state or {}).get('source') or Path(__file__).resolve().parent.parent
                          / 'skills' / SELF))
        repo = source.parent.parent
        if not (repo / 'installer' / 'install.sh').is_file():
            return None
        pull = 'git pull && ' if (repo / '.git').exists() else ''
        return f'cd {shlex.quote(str(repo))} && {pull}sh installer/install.sh'

    def releases(self, found: dict | None) -> dict:
        """What was last found online, and what of it is newer than what is here."""
        kept = home.read_json(self.saved_path(), None)
        kept = kept if isinstance(kept, dict) and isinstance(kept.get('found'), dict) else {}
        online = kept.get('found', {})
        have, newer = sync_guidance.runtime_version(), []
        latest = [version for version in ((online.get(SELF) or {}).get('latest'),
                                          (found or {}).get('main')) if version]
        if latest and _version(max(latest, key=_version)) > _version(have):
            version, command = max(latest, key=_version), self.command()
            newer.append({'name': SELF, 'version': version, 'have': have, 'command': command,
                          'link': None, 'says': (
                              f'Training Studio {version} is out, and this is {have}. Close '
                              'Training Studio, then ' + (
                                  'run this in a terminal:' if command else
                                  'get the newer version of its repository and run '
                                  'sh installer/install.sh in it.'))})
        for entry in (found or {}).get('companions', []):
            out = (online.get(entry['name']) or {}).get('latest')
            if out and _version(out) > _version(entry['wanted']):
                newer.append({'name': entry['name'], 'version': out, 'have': entry['wanted'],
                              'command': None, 'link': entry['repository'], 'says': (
                                  f"{entry['name']} {out} is out, and this Training Studio "
                                  f"was made with {entry['wanted']}. It comes with Update "
                                  'once a Training Studio made with it is installed.')})
        missed = [name for name, entry in online.items()
                  if isinstance(entry, dict) and entry.get('problem')]
        problem = None
        if missed:
            first = online[missed[0]]['problem']
            problem = (f'The last look for newer releases did not reach {_who(missed)} '
                       f'({first}). It is tried again in a day.')
        return {'on': settings.load().look_for_updates, 'at': kept.get('at'),
                'problem': problem, 'newer': newer}

    @staticmethod
    def guidance() -> dict:
        """Which guidance a new training is given."""
        path = sync_guidance.guidance_root() / 'last.json'
        last = home.read_json(path, None)
        commit = last.get('commit') if isinstance(last, dict) else None
        have = sync_guidance.runtime_version()
        try:
            at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime(
                '%Y-%m-%dT%H:%M:%SZ') if last is not None else None
        except OSError:
            at = None
        # The guidance `adopt` pins a new training to: a whole commit whose folder is there.
        if isinstance(commit, str) and sync_guidance.COMMIT.fullmatch(commit) \
                and (sync_guidance.folder_for(commit) / 'SKILL.md').is_file():
            branch = sync_guidance.source().get('branch', 'main')
            return {'commit': commit[:12], 'at': at, 'says': (
                f'New trainings follow the guidance from revision {commit[:12]} of {branch}, '
                'the newest when guidance was last fetched.')}
        return {'commit': None, 'at': at, 'says': (
            f'New trainings follow the guidance installed with Training Studio {have}. '
            + ('The newest could not be fetched when it was last asked for.'
               if last is not None else 'None has been fetched on this computer yet.'))}

    def report(self) -> dict:
        """Everything found, in the shape the page reads. Starts nothing and never waits."""
        with self._lock:
            found = self._found
            update = dict(self._update) if self._update else None
        wanted = [entry for entry in (found or {}).get('companions', [])
                  if entry['state'] in ('missing', 'older')]
        running = bool(update and update['state'] == 'running')
        return {'checking': found is None, 'checked_at': found and found['at'],
                'version': sync_guidance.runtime_version(),
                'mode': found and found['mode'],
                'problem': found and found['problem'],
                'links': list((found or {}).get('links', [])),
                'repaired': list((found or {}).get('repaired', [])),
                'companions': list((found or {}).get('companions', [])),
                'update': {'offered': bool(wanted and found['installer'] and not running),
                           'state': update and update['state'],
                           'since': update and update['since'],
                           'says': update and update['says']},
                'guidance': self.guidance(), 'releases': self.releases(found)}
