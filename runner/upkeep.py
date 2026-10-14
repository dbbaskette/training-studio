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
    keep.upgrade(working, '0.22.0')   # install that newer Training Studio beside this one
    keep.restart(working)        # after an upgrade: stop, so that `studio` starts the new one
    keep.dismiss(key)            # Home stops showing the versions until a newer one is out
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
  - Only the tags are kept, in `updates.json` in the data folder, each newest with its
    commit. Whether one is newer is worked out each time it is shown. Nothing is
    downloaded or run.
- The newest Training Studio is its newest release tag once there is one, and until then
  the version on `main` when guidance was last fetched. Which companion versions that
  newest one is pinned to is read from its `installer/companions.json` in the guidance
  cache, which holds `main` with its history; a tag is read there only when its commit is
  on `main`. All of that is local. When it cannot be read, it is not guessed.
- `report()['versions']` has a row for Training Studio and one for each companion: what is
  installed, the newest, what this version is pinned to and the newest one's pin, a state
  (`current`, `update`, `missing` or `unknown`) and a sentence. A companion released
  beyond the newest Training Studio's pin is said, and never offered: the pin is the line.
  Where a companion's tool is found, what it says of itself is said too.
- `upgrade` installs the newest Training Studio, the one the person confirmed:
  - the revision, a tag or `main`, is fetched by name into a temporary folder with the
    guidance's own isolated git, and only its plain files are written out;
  - its `VERSION` must be the one shown, and then its own installer runs `install
    --while-open`, which checks it, lays it beside this version and moves `current`;
  - all of it under `companion.supervise`, with UPGRADE_SECONDS to finish.
  This version's folder is left as it is, so the runner keeps running from it. It is
  refused from a checkout, which is upgraded with `git pull`, while a training is working,
  while anything else is in hand, and when the newest is no longer the one confirmed.
- `restart` is offered once an upgrade is installed. It sets `restarting` to the command
  that opens Training Studio, the one the installer wrote, and calls `leave`; `studio
  serve` then stops and runs that command in its place. Without that command, the person
  is told to open Training Studio again.
- The report says which guidance a new training is given: the revision the last guidance
  start resolved, or the copy installed with this version.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import runner  # noqa: F401  puts the core on the import path
import home
import hub
import sync_guidance
from workspace import WorkspaceError

from runner import companion, settings
from runner import research as research_tool, slides as slides_tool

INSTALLER = Path(__file__).resolve().parent.parent / 'installer' / 'install.py'
SAVED = 'updates.json'    # in the data folder: the releases last found online, and when
DAY = 24 * 3600           # seconds between looks online
LOOK_SECONDS = 15         # for one repository to answer
UPDATE_SECONDS = 2400     # for the companions to be fetched, checked and installed
UPGRADE_SECONDS = 900     # for a newer Training Studio to be checked and installed
SELF = 'training-studio'
TAG = re.compile(r'^([0-9a-f]{40})\trefs/tags/(v?(\d+\.\d+\.\d+))(\^\{\})?$')
TOOLS = {'harness-research': (research_tool, 'Harness Research'),
         'harness-slides': (slides_tool, 'Harness Slides')}
COMMANDS = {'command': 'The command that opens Training Studio',
            'helper': "The command the skill runs its helper with"}
NO_INSTALLER = ('This copy of the runner has no installer beside it, so the skills cannot be '
                'checked or updated from here. Run the installer again.')
WORKING = ('A training on this computer is working now, and a step in hand keeps using the '
           'skill it started with. Pause it, or wait until it stops for you, then update.')
UPDATING = 'The companion skills are being updated already.'
NOTHING = 'Every companion skill is already as new as this Training Studio was made with.'
STOPPED = 'The update was stopped when Training Studio closed. Nothing more was changed.'
UPGRADING = 'Training Studio is being upgraded already.'
UPGRADE_WORKING = ('A training on this computer is working now. Pause it, or wait until it '
                   'stops for you, then upgrade.')
FROM_CHECKOUT = ('This Training Studio runs from a copy of its repository, so it is upgraded '
                 'there, with git pull, and not from here.')
NOTHING_NEWER = 'No newer Training Studio is known. Check this computer again to look.'
NO_RESTART = 'There is no upgrade waiting for a restart.'
RESTART_WORKING = ('A training on this computer is working now, and restarting would stop '
                   'its step. Pause it, or wait until it stops for you, then restart.')
UPGRADE_STOPPED = ('The upgrade was stopped when Training Studio closed. The version you '
                   'have is still the one in use.')


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


def newest(listed: str) -> dict | None:
    """The newest release among the tags `git ls-remote --tags` printed, as {'version',
    'tag', 'commit'}, or None. An annotated tag's commit is the one it points at."""
    found = {}
    for line in listed.splitlines():
        match = TAG.match(line.strip())
        if match:
            commit, name, version, peeled = match.groups()
            entry = found.setdefault(name, {'version': version, 'tag': name, 'commit': commit})
            if peeled:
                entry['commit'] = commit
    return max(found.values(), key=lambda entry: _version(entry['version'])) if found \
        else None


def fetch_tree(repository: str, ref: str, into: Path) -> tuple[Path, str]:
    """One revision of a repository, fetched by the name of its ref with the guidance's own
    isolated git, written into `into` as plain files: (the folder, its commit). Links and
    anything else that is not a plain file are left out."""
    if str(repository).startswith('-') or not re.fullmatch(r'refs/(heads|tags)/[\w.\-/]+',
                                                          ref) or '..' in ref:
        raise sync_guidance.SyncError('That is not a revision this version can fetch.')
    bare, tree = into / 'fetched.git', into / 'tree'
    sync_guidance.git('init', '--quiet', '--bare', '--template=', str(bare))
    (bare / 'config').write_bytes(sync_guidance.CACHE_CONFIG)
    sync_guidance.git('fetch', '--quiet', '--no-tags', '--depth', '1', str(repository),
                      f'+{ref}:refs/fetched', repo=bare)
    commit = sync_guidance.git('rev-parse', '--verify', 'refs/fetched^{commit}',
                               repo=bare).decode().strip()
    files = {}
    for line in filter(None, sync_guidance.git('ls-tree', '-r', '-z', '--full-tree', commit,
                                               repo=bare).split(b'\0')):
        meta, _, name = line.partition(b'\t')
        mode, kind, ident = meta.split()
        if kind != b'blob' or mode not in (b'100644', b'100755'):
            continue
        inside = PurePosixPath(name.decode('utf-8', 'replace'))
        if inside.is_absolute() or any(part in ('', '.', '..') for part in inside.parts):
            raise sync_guidance.SyncError('What was fetched has a file that cannot be placed.')
        files[inside.as_posix()] = (ident.decode(), mode == b'100755')
    content = sync_guidance.blobs(sorted({ident for ident, _ in files.values()}), bare)
    for name, (ident, runs) in files.items():
        target = tree / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content[ident])
        if runs:
            target.chmod(0o755)
    shutil.rmtree(bare, ignore_errors=True)
    return tree, commit


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
        self._upgrade: dict | None = None    # the upgrade in hand, or the one installed
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self.restarting: list[str] | None = None   # what `studio serve` runs once it stops
        self.leave = None                    # stops the runner; `studio serve` sets it

    @property
    def folder(self) -> Path:
        """The copy this runner and its installer belong to: a version folder, or a checkout."""
        return self.installer.resolve().parent.parent

    def checkout(self) -> bool:
        """Whether this runner runs from a copy of the repository, upgraded with git pull."""
        return self.folder.parent.name != 'versions'

    def version(self) -> str:
        """The version of the copy this runner belongs to."""
        for path in (self.folder / 'VERSION', self.folder / 'skills' / SELF / 'VERSION'):
            try:
                found = path.read_text(encoding='utf-8').strip()
            except OSError:
                continue
            if _version(found):
                return found
        return sync_guidance.runtime_version()

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
                'companions': [], 'problem': problem, 'main': None, 'newest': None,
                'tools': {}}

    def _local(self, repair: bool) -> dict:
        install = self.module()
        if install is None:
            return {**self._blank(NO_INSTALLER), 'main': self._main_version(),
                    'newest': self._newest(None)}
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
                'main': self._main_version(), 'newest': self._newest(install),
                'tools': self._tools(), 'target': self._target(state)}

    @staticmethod
    def _target(state: dict | None) -> str | None:
        """The assistants Training Studio was installed for, as the installer names them."""
        chosen = sorted((state or {}).get('links', {}))
        return 'both' if len(chosen) > 1 else chosen[0] if chosen else None

    def _tools(self) -> dict:
        """What each companion's own tool says of itself, where one is found in this home:
        {name: a sentence}. Asked on this computer only."""
        said = {}
        for name, (module, title) in TOOLS.items():
            places = companion.locations(module.VARIABLE, name, title, home=self.home)
            if not any((place / module.SCRIPT).is_file() for place in places):
                continue
            try:
                runtime = companion.find_runtime(places, module.SCRIPT, module.VARIABLE, name,
                                                 'it cannot be asked')
                if module is slides_tool:
                    tool = slides_tool.Slides(runtime)
                    listed = tool.capabilities()
                    said[name] = f'The tool in use says it is {tool.version()}' + (
                        f", and that it can do: {', '.join(sorted(listed))}." if listed
                        else '.')
                else:
                    said[name] = (f'The tool in use says it is '
                                  f'{research_tool.Research(runtime).version()}.')
            except (WorkspaceError, OSError) as refusal:
                said[name] = str(refusal)
        return said

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

    @classmethod
    def _main_version(cls) -> str | None:
        main = cls._main()
        return main and main['version']

    @staticmethod
    def _main() -> dict | None:
        """Training Studio's version on the source branch when guidance was last fetched,
        with its commit, read from the helper's guidance cache with its own isolated git.
        Nothing is fetched, and a cache the helper would not use is not read: it is the
        helper's to rebuild."""
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
        return {'version': found, 'commit': commit} if _version(found) else None

    def _newest(self, install) -> dict | None:
        """The newest Training Studio known here, as {'version', 'ref', 'from', 'pins'}: its
        newest release tag once it has one, else the version on the source branch when
        guidance was last fetched. `pins` are the companion versions it is pinned to, or
        None when they cannot be read here."""
        online = (self._saved().get('found') or {}).get(SELF) or {}
        branch = str(sync_guidance.source().get('branch', 'main'))
        if online.get('latest'):
            found = {'version': online['latest'], 'from': 'tag',
                     'ref': f"refs/tags/{online.get('tag') or 'v' + online['latest']}",
                     'commit': online.get('commit')}
        elif (main := self._main()) is not None:
            found = {'version': main['version'], 'from': branch,
                     'ref': f'refs/heads/{branch}', 'commit': main['commit']}
        else:
            return None
        found['pins'] = self._pins_at(install, found.pop('commit'))
        return found

    @staticmethod
    def _pins_at(install, commit: str | None) -> dict | None:
        """The companion versions Training Studio was pinned to at a commit, {name:
        version}, read from the guidance cache when that commit is on the source branch
        there. None when it cannot be read here: nothing is fetched for it."""
        cache = sync_guidance.guidance_root() / 'cache.git'
        if install is None or not isinstance(commit, str) \
                or not sync_guidance.COMMIT.fullmatch(commit) or not sync_guidance.ours(cache) \
                or not sync_guidance.on_main(commit, cache):
            return None
        try:
            text = sync_guidance.git('cat-file', 'blob', f'{commit}:installer/companions.json',
                                     repo=cache)
            with tempfile.TemporaryDirectory() as holder:
                kept = Path(holder) / 'companions.json'
                kept.write_bytes(text)
                pins = install.read_pins(kept)
        except (sync_guidance.SyncError, install.InstallError, OSError):
            return None
        return {name: pin['version'] for name, pin in pins.items()}

    # --- online --------------------------------------------------------------------------

    @staticmethod
    def saved_path() -> Path:
        return home.data_root() / SAVED

    @classmethod
    def _saved(cls) -> dict:
        """What was last found online, as `look` keeps it; empty when nothing was."""
        kept = home.read_json(cls.saved_path(), None)
        return kept if isinstance(kept, dict) and isinstance(kept.get('found', {}), dict) \
            else {}

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
        found, before = {}, self._saved().get('found') or {}
        for name, repository in self.repositories().items():
            # What was known last is kept when it cannot be asked now, with when it was.
            known = before.get(name) if isinstance(before.get(name), dict) \
                and before[name].get('repository') == repository else {}
            entry = {'repository': repository, 'problem': None,
                     **{key: known.get(key) for key in ('latest', 'tag', 'commit', 'known_at')}}
            try:
                done = hub.run(place, 'ls-remote', '--tags', '--', repository,
                               timeout=LOOK_SECONDS)
            except WorkspaceError as refusal:
                entry['problem'] = str(refusal).rstrip('.')
            else:
                if done.returncode == 0:
                    latest = newest(done.stdout) or {}
                    entry.update(latest=latest.get('version'), tag=latest.get('tag'),
                                 commit=latest.get('commit'), known_at=_now())
                else:
                    entry['problem'] = hub.reason(done)
            found[name] = entry
        home.write_json(self.saved_path(), {'schema': 1, 'at': _now(), 'found': found,
                                            'dismissed': self._saved().get('dismissed')})
        fresh = self._newest(self.module())
        with self._lock:
            if self._found is not None:
                self._found = {**self._found, 'newest': fresh}
        return True

    # --- the update ----------------------------------------------------------------------

    def update(self, working: bool) -> dict:
        """Bring each companion that is missing or older than its pin, through the
        installer's own checked install, in the background. Refused, in a sentence, while a
        training is working, while an update is in hand, and when there is nothing to do."""
        with self._lock:
            found = self._found
            self._refuse_busy()
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
            self._refuse_busy()
            self._update = {'state': 'running', 'since': _now(), 'names': names,
                            'says': f'Bringing {_who(names)}. This can take a few minutes.'}
        self._background(lambda: self._bring(names), 'updating the skills')
        return self.report()

    def _refuse_busy(self) -> None:
        """Refuse a change while another is in hand, or while a newer Training Studio waits
        for a restart: that one brings the companions it was made with. Under the lock."""
        if self._update and self._update['state'] == 'running':
            raise WorkspaceError(UPDATING)
        if self._upgrade and self._upgrade['state'] == 'running':
            raise WorkspaceError(UPGRADING)
        if self._upgrade and self._upgrade['state'] in ('restart', 'restarting'):
            raise WorkspaceError(f"Training Studio {self._upgrade['version']} is installed "
                                 'and waits for a restart. Restart first: it brings the '
                                 'companion skills it was made with.')

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

    # --- the upgrade ---------------------------------------------------------------------

    def upgrade(self, working: bool, version: str) -> dict:
        """Install the newest Training Studio, `version`, beside this one, in the background.
        Refused, in a sentence, from a checkout, while a training is working, while anything
        else is in hand, and when the newest known is not `version` or not newer."""
        with self._lock:
            found = self._found
            self._refuse_busy()
        if found is None:
            found = self.check(repair=False)
        if not found['installer']:
            raise WorkspaceError(NO_INSTALLER)
        if self.checkout() or found['mode'] != 'managed':
            raise WorkspaceError(FROM_CHECKOUT)
        newest, have = found.get('newest'), self.version()
        if not newest or _version(newest['version']) <= _version(have):
            raise WorkspaceError(NOTHING_NEWER)
        if newest['version'] != str(version):
            raise WorkspaceError(f"The newest Training Studio is now {newest['version']}, not "
                                 f'{version}. Look at it again before you upgrade.')
        if working:
            raise WorkspaceError(UPGRADE_WORKING)
        with self._lock:
            self._refuse_busy()
            self._upgrade = {'state': 'running', 'since': _now(), 'version': newest['version'],
                             'says': f"Fetching Training Studio {newest['version']}, checking "
                                     'it and installing it beside this one. This can take a '
                                     'few minutes.'}
        target = found.get('target')
        self._background(lambda: self._install(newest, target), 'upgrading Training Studio')
        return self.report()

    def _install(self, newest: dict, target: str | None) -> None:
        """Fetch the newest revision and run its own installer, beside this version."""
        version, state, says, commit = newest['version'], 'failed', None, None
        holder = Path(tempfile.mkdtemp(prefix='training-studio-upgrade-'))
        try:
            repository = str(sync_guidance.source()['repository'])
            tree, commit = fetch_tree(repository, newest['ref'], holder)
            found = (tree / 'skills' / SELF / 'VERSION').read_text(encoding='utf-8').strip() \
                if (tree / 'skills' / SELF / 'VERSION').is_file() else None
            if found != version:
                raise WorkspaceError(f"{repository} has version {found or 'unknown'} at "
                                     f"{newest['ref']}")
            state, says = self._run_installer(tree, version, target)
        except (sync_guidance.SyncError, WorkspaceError, OSError) as refusal:
            says = f'Training Studio {version} was not installed: {str(refusal).rstrip(".")}.'
        except Exception as failure:  # said on the page; the runner keeps serving
            says = f'The upgrade could not be run ({type(failure).__name__}: {failure}).'
        finally:
            shutil.rmtree(holder, ignore_errors=True)
        if self._stop.is_set() and state != 'restart':
            says = UPGRADE_STOPPED
        with self._lock:
            self._upgrade = {**(self._upgrade or {}), 'state': state, 'says': says,
                             'ended': _now(), 'commit': commit and commit[:12]}

    def _run_installer(self, tree: Path, version: str, target: str | None) -> tuple[str, str]:
        """Run the fetched version's own installer, which checks it, lays it beside this one
        and moves `current`: ('restart' or 'failed', what is said)."""
        command = [sys.executable, '-B', str(tree / 'installer' / 'install.py'), 'install',
                   '--yes', '--json', '--companions', 'skip', '--while-open',
                   '--home', str(self.home), '--root', str(self.root),
                   *(['--target', target] if target else [])]
        printed: list[bytes] = []
        with tempfile.TemporaryFile() as errors:
            code, late = companion.supervise(command, None, None, '', UPGRADE_SECONDS, errors,
                                             printed.append, self._stop)
            errors.seek(0)
            complaint = errors.read().decode('utf-8', 'replace').strip()
        if self._stop.is_set():
            return 'failed', UPGRADE_STOPPED
        if late:
            return 'failed', (f'The upgrade did not finish in {UPGRADE_SECONDS // 60} minutes, '
                              'so it was ended. The version you have is still the one in use.')
        try:
            result = json.loads(b''.join(printed).decode('utf-8', 'replace'))
        except ValueError:
            result = None
        if not isinstance(result, dict):
            line = (complaint.splitlines() or ['it said nothing'])[-1][:300]
            return 'failed', f'Its installer did not answer as expected: {line}'
        if 'error' in result or code != 0:
            return 'failed', (f'Training Studio {version} was not installed: '
                              f"{result.get('error', 'its installer failed')}")
        key = str(result.get('version', ''))
        current = self.root / 'current'
        if result.get('mode') != 'managed' or not key.startswith(f'{version}-') \
                or not os.path.islink(current) \
                or Path(os.readlink(current)) != self.root / 'versions' / key:
            return 'failed', (f'Its installer finished, but Training Studio {version} is not '
                              'the version in use. Run the installer again.')
        return 'restart', (f'Training Studio {version} is installed, checked and in place. '
                           'Restart to use it. This page comes back by itself.'
                           if self._opener() else
                           f'Training Studio {version} is installed, checked and in place. '
                           'Close Training Studio and open it again to use it.')

    def _opener(self) -> Path | None:
        """The command the installer wrote that opens Training Studio, when it is there."""
        install = self.module()
        try:
            state = install.read_state(self.root) if install else None
        except install.InstallError:
            state = None
        kept = (state or {}).get('launchers', {}).get('command')
        return Path(kept) if kept and install.ours(Path(kept)) else None

    def restart(self, working: bool) -> dict:
        """Once a newer version is installed: stop, so that `studio serve` runs the command
        that opens Training Studio, which opens the newer one. Refused while a training
        works, and when there is no such command: then the person opens it again."""
        with self._lock:
            upgrade = dict(self._upgrade) if self._upgrade else None
        if not upgrade or upgrade['state'] != 'restart':
            raise WorkspaceError(NO_RESTART)
        if working:
            raise WorkspaceError(RESTART_WORKING)
        opener = self._opener()
        if opener is None:
            raise WorkspaceError('Training Studio cannot open itself again here. Close it and '
                                 'open it again.')
        with self._lock:
            self._upgrade = {**self._upgrade, 'state': 'restarting',
                             'says': f"Restarting with Training Studio {upgrade['version']}."}
            self.restarting = ['/bin/sh', str(opener), 'serve']
        if self.leave is not None:
            self.leave()
        return self.report()

    def dismiss(self, key: str) -> dict:
        """Stop showing the versions on Home until a newer one is out than `key` names."""
        if not isinstance(key, str) or not key or len(key) > 500:
            raise WorkspaceError('Name what is dismissed as the key the page was given.')
        kept = self._saved()
        home.write_json(self.saved_path(), {'schema': 1, **kept, 'dismissed': key})
        return self.report()

    # --- what is said ----------------------------------------------------------------------

    def command(self) -> str | None:
        """The command that brings a newer Training Studio to a checkout this runner runs
        from, when it is a git checkout: Training Studio is then upgraded there."""
        if not self.checkout() or not (self.folder / '.git').exists():
            return None
        return f'cd {shlex.quote(str(self.folder))} && git pull'

    def releases(self) -> dict:
        """Whether looking online is on, when it last looked, and what it did not reach."""
        kept = self._saved()
        online = kept.get('found') or {}
        missed = [name for name, entry in online.items()
                  if isinstance(entry, dict) and entry.get('problem')]
        problem = None
        if missed:
            first = online[missed[0]]['problem']
            problem = (f'The last look for newer releases did not reach {_who(missed)} '
                       f'({first}). It is tried again in a day.')
        return {'on': settings.load().look_for_updates, 'at': kept.get('at'),
                'problem': problem}

    def versions(self, found: dict | None, upgrade: dict | None, busy: bool) -> dict:
        """A row each for Training Studio and its companions, what an upgrade would do, and
        the key Home is dismissed with. Worked out from what was last found; asks nothing."""
        kept = self._saved()
        online = kept.get('found') or {}
        have, newest = self.version(), (found or {}).get('newest')
        checkout = self.checkout() or (found or {}).get('mode') == 'link'
        ahead = bool(newest and _version(newest['version']) > _version(have))
        waiting = bool(upgrade and upgrade['state'] in ('restart', 'restarting'))
        rows = [{**self._own_row(have, newest, ahead, checkout, upgrade),
                 'known_at': (online.get(SELF) or {}).get('known_at')}]
        pins = (newest or {}).get('pins') if ahead else None
        for entry in (found or {}).get('companions', []):
            rows.append(self._companion_row(entry, online.get(entry['name']) or {},
                                            newest if ahead else None, pins,
                                            (found.get('tools') or {}).get(entry['name'])))
        wanted = [row for row in rows if row['state'] in ('update', 'missing')]
        key = ', '.join(f"{row['name']} {row['target'] or row['state']}" for row in wanted)
        offered = bool(ahead and not checkout and found and found['installer']
                       and found['mode'] == 'managed' and not busy and not waiting)
        return {'rows': rows, 'at': kept.get('at'), 'checkout': checkout,
                'command': self.command(),
                'key': key or None, 'dismissed': bool(key) and kept.get('dismissed') == key,
                'upgrade': {'offered': offered, 'version': newest['version'] if ahead else None,
                            'from': newest['from'] if ahead else None,
                            'state': upgrade and upgrade['state'],
                            'since': upgrade and upgrade['since'],
                            'says': upgrade and upgrade['says'],
                            'restart': bool(upgrade and upgrade['state'] == 'restart'
                                            and self._opener())}}

    def _own_row(self, have: str, newest: dict | None, ahead: bool, checkout: bool,
                 upgrade: dict | None) -> dict:
        """Training Studio's row."""
        row = {'name': SELF, 'installed': have, 'newest': newest and newest['version'],
               'pinned': None, 'next': None, 'target': None, 'beyond': None, 'reports': None}
        if newest is None:
            return {**row, 'state': 'unknown', 'says': (
                'Whether a newer Training Studio is out is not known yet. It is looked for '
                'once a day, and when you check this computer again.')}
        if not ahead:
            return {**row, 'state': 'current', 'says': f'Training Studio {have} is the newest.'}
        version = newest['version']
        if upgrade and upgrade['state'] in ('restart', 'restarting') \
                and upgrade.get('version') == version:
            says = f'Training Studio {version} is installed. Restart to use it.'
        elif checkout:
            says = (f'Training Studio {version} is out, and this is {have}. This one runs '
                    'from a copy of its repository, so it is upgraded there with git pull, '
                    'not from here.')
        else:
            says = f'Training Studio {version} is out, and this is {have}.'
        return {**row, 'state': 'update', 'target': version, 'says': says}

    @staticmethod
    def _companion_row(entry: dict, online: dict, newest: dict | None, pins: dict | None,
                       reports: str | None) -> dict:
        """One companion's row. `newest` is the newer Training Studio, when there is one,
        and `pins` what it is pinned to, when that could be read."""
        name, pinned = entry['name'], entry['wanted']
        having = sorted((version for version in entry['found'].values() if version),
                        key=_version)
        installed = having[0] if having else None
        following = (pins or {}).get(name)
        latest = online.get('latest')
        line = max((version for version in (pinned, following) if version), key=_version)
        row = {'name': name, 'installed': installed, 'newest': latest, 'pinned': pinned,
               'next': following, 'target': None, 'reports': reports,
               'known_at': online.get('known_at'),
               'beyond': (f'{name} {latest} is out, newer than Training Studio supports yet. '
                          'It is offered once a Training Studio made with it is out.')
               if latest and _version(latest) > _version(line) else None}
        if entry['state'] in ('missing', 'older'):
            return {**row, 'state': 'missing' if entry['state'] == 'missing' else 'update',
                    'target': pinned, 'says': entry['says']}
        if entry['state'] == 'unread' or installed is None:
            return {**row, 'state': 'unknown', 'says': entry['says']}
        if following and _version(installed) < _version(following):
            return {**row, 'state': 'update', 'target': following, 'says': (
                f"{name} {following} comes with Training Studio {newest['version']}, which "
                f'is made with it. This computer has {installed}.')}
        if newest and pins is None:
            return {**row, 'state': 'current', 'says': (
                f'{name} {installed} is what this Training Studio is made with. Which version '
                f"Training Studio {newest['version']} is made with is not known here yet.")}
        return {**row, 'state': 'current', 'says': (
            f'{name} {installed} is what this Training Studio is made with.'
            if installed == pinned else
            f'{name} {installed}, newer than the {pinned} this Training Studio is made with.')}

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
            upgrade = dict(self._upgrade) if self._upgrade else None
        wanted = [entry for entry in (found or {}).get('companions', [])
                  if entry['state'] in ('missing', 'older')]
        busy = bool(update and update['state'] == 'running') \
            or bool(upgrade and upgrade['state'] in ('running', 'restart', 'restarting'))
        return {'checking': found is None, 'checked_at': found and found['at'],
                'version': self.version(),
                'mode': found and found['mode'],
                'problem': found and found['problem'],
                'links': list((found or {}).get('links', [])),
                'repaired': list((found or {}).get('repaired', [])),
                'companions': list((found or {}).get('companions', [])),
                'update': {'offered': bool(wanted and found['installer'] and not busy),
                           'state': update and update['state'],
                           'since': update and update['since'],
                           'says': update and update['says']},
                'guidance': self.guidance(), 'releases': self.releases(),
                'versions': self.versions(found, upgrade, busy)}
