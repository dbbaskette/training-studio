"""The brand skill's own repository: which releases it has, and installing one with the
brand skill's own installer.

What a caller needs to know
---------------------------
    found = brand_source.check(address, release, place)   # refuses in a sentence
    found['chosen']                 # {'tag', 'version', 'commit'}: the one to install
    listed = brand_source.releases(address, place)        # {tag: {...}}, or a refusal
    folder, how = brand_source.fetch(address, tag, commit, into, stop)
    brings = brand_source.bootstraps(folder)              # {'harness-slides': '0.13.1'}
    code, late, said = brand_source.install(folder, home, seconds, stop)

- The repository is the person's choice, and is reached with their own git access, as the
  workspace is: through `hub.run`, which never asks on a terminal and gives ssh BatchMode.
  The guidance's isolated git, which ignores the person's settings, is never used here.
- A release is a tag such as `v1.4.0`. Releases are ordered as the brand skill's own
  updater orders them: a version whose first number is a year, 2000 to 2099, is from an
  older way of numbering and comes before every other (`order`).
- `check` reads the repository's tags with `git ls-remote` and nothing else. A repository
  that cannot be read is refused with a sentence that says whether git could not sign in,
  the repository was not found, or it could not be reached. One with no release, or
  without the release named, is refused too. `chosen` is the release named, else the
  newest.
- `fetch` puts the release in a new folder inside `into` and returns that folder and how
  it came (`zip` or `tag`):
  - With `gh` installed and signed in, and an address on github.com, the release's ZIP
    is downloaded: on a Mac the one named `-mac.zip` when there is one, otherwise the only
    other. A `.sha256` beside it is checked. It is unpacked with nothing outside its folder
    and no links.
  - Otherwise, or when the release has no ZIP, the tag is cloned at depth one, and its
    commit must be `commit`, the one the person was shown.
- `install` runs the release's own installer from that folder, under
  `companion.supervise`: `scripts/install-mac.mjs --yes --research skip` on a Mac, else
  `scripts/install-skill.mjs --research skip`. `--research skip` keeps it from touching
  harness-research. It has no such option for harness-slides, which it leaves alone only
  when one it can use is installed; `bootstraps` reads which version that is, from the
  release's own record of what it installs. `home`, when it is not the person's own, is
  given to it as HOME.
- Nothing here is run before the person's yes; the caller asks for that.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import runner  # noqa: F401  puts the core on the import path
import hub
from workspace import WorkspaceError

from runner import companion, settings

LOOK_SECONDS = 30          # for the repository to say which tags it has
FETCH_SECONDS = 600        # for a release to be downloaded or cloned
TAG = re.compile(r'^([0-9a-f]{40})\trefs/tags/(v?(\d+\.\d+\.\d+))(\^\{\})?$')
YEARS = range(2000, 2100)  # a first number in here is a year: the older way of numbering
GITHUB = re.compile(r'^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)'
                    r'([\w.-]+)/([\w.-]+?)(?:\.git)?/?$')
SOURCES = Path('scripts') / 'lib' / 'harness-install-sources.json'
SKIPPED = ('harness-research',)   # what `--research skip` keeps the installer from touching
MOST_FILES = 5000          # in a release ZIP
MOST_BYTES = 500_000_000   # unpacked, in a release ZIP
PLATFORM = sys.platform
SIGN_IN = ('terminal prompts disabled', 'could not read username', 'could not read password',
           'authentication failed', 'permission denied', 'host key verification failed',
           'invalid username or password')
NOT_FOUND = ('not found', 'does not appear to be a git repository', 'does not exist',
             'no such file')


def order(version) -> tuple:
    """How releases are ordered: one numbered from a year before every other, then by its
    numbers. Something that is not a version comes first of all."""
    try:
        parts = tuple(int(part) for part in str(version).split('.'))
    except ValueError:
        return ()
    return (0 if parts[0] in YEARS else 1, *parts)


def listed(text: str) -> dict:
    """Each release tag `git ls-remote --tags` printed: {tag: {'tag', 'version', 'commit'}}.
    An annotated tag's commit is the one it points at."""
    found = {}
    for line in text.splitlines():
        match = TAG.match(line.strip())
        if match:
            commit, name, version, peeled = match.groups()
            entry = found.setdefault(name, {'tag': name, 'version': version, 'commit': commit})
            if peeled:
                entry['commit'] = commit
    return found


def newest(found: dict) -> dict | None:
    """The newest of the releases `listed` found, or None."""
    return max(found.values(), key=lambda entry: order(entry['version'])) if found else None


def plain(reason: str) -> str:
    """Why a repository could not be read, as a sentence a person can act on."""
    said = reason.lower()
    if any(words in said for words in SIGN_IN):
        return (f'git could not sign in to it without asking ({reason}). Sign git in with an '
                'account that may read it, through its credential helper for an https '
                'address or an ssh key for an ssh one, then try again.')
    if any(words in said for words in NOT_FOUND):
        return (f'It was not found ({reason}). Check the address. A private repository is '
                'not found by someone who may not read it, either.')
    return (f'It could not be reached ({reason}). Check the address and that this computer '
            'is online, then try again.')


def releases(address: str, place: Path, seconds: float = LOOK_SECONDS) -> dict:
    """The repository's release tags, as `listed` gives them. Refuses in a sentence when it
    cannot be read with this person's own git access."""
    done = hub.run(place, 'ls-remote', '--tags', '--', address, timeout=seconds)
    if done.returncode != 0:
        raise WorkspaceError(f"The brand skill's repository could not be read. "
                             f'{plain(hub.reason(done))}')
    return listed(done.stdout)


def _address(address: str) -> str:
    """An address, or a folder's whole path. A folder must say where it is."""
    if '://' in address or re.match(r'^[\w.-]+@[\w.-]+:', address):
        return address
    folder = Path(address).expanduser()
    if not folder.is_absolute():
        raise WorkspaceError("Give the brand skill's repository as an https or ssh address, "
                             'or a folder\'s whole path, starting from / or from ~.')
    return str(folder)


def check(address, release, place: Path) -> dict:
    """Whether the brand skill can be installed from this repository, by this person:
    {'repository', 'release', 'releases', 'newest', 'chosen'}. `release` is the tag kept,
    or None for the newest; `releases` is every release, newest first."""
    address = settings.check_repository(address)
    if address is None:
        raise WorkspaceError("Give the brand skill's repository address.")
    address = _address(address)
    release = settings.check_release(release, address)
    found = releases(address, place)
    if not found:
        raise WorkspaceError(f'{address} has no releases: no tag such as v1.0.0. Check the '
                             'address, or ask whoever keeps it to tag a release.')
    latest = newest(found)
    chosen = latest
    if release is not None:
        chosen = found.get(release) or found.get(f'v{release}')
        if chosen is None:
            raise WorkspaceError(f"{address} has no release {release}. Its newest is "
                                 f"{latest['tag']}. Leave the release empty for the newest.")
    return {'repository': address, 'release': release and chosen['tag'],
            'releases': sorted(found.values(), key=lambda entry: order(entry['version']),
                               reverse=True),
            'newest': latest, 'chosen': chosen}


# --- fetching a release --------------------------------------------------------------------

def _text(data: bytes) -> str:
    return data.decode('utf-8', 'replace').replace('\r\n', '\n')


def _run(command: list[str], seconds: float, stop, env: dict | None = None,
         cwd: Path | None = None) -> tuple[int, bool, str, str]:
    """Run a command once under `companion.supervise`: (exit code, whether it ran out of
    time, output, complaint). One that cannot start has failed. Stopped is raised on
    `stop`."""
    printed: list[bytes] = []
    with tempfile.TemporaryFile() as errors:
        try:
            code, late = companion.supervise(command, cwd, env, '', seconds, errors,
                                             printed.append, stop)
        except OSError as failure:
            return 127, False, '', str(failure)
        errors.seek(0)
        complaint = _text(errors.read())
    if stop is not None and stop.is_set():
        raise companion.Stopped('It was stopped before it finished.')
    if late:
        return code, True, '', f'it did not finish in {seconds:g} seconds'
    return code, False, _text(b''.join(printed)), complaint


def last_line(*said: str) -> str:
    """The last thing said, in one short line."""
    for text in said:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            return lines[-1][:300].rstrip('.')
    return 'it said nothing'


def _zip_name(names: list[str]) -> str | None:
    """The release's ZIP to install: the Mac one on a Mac, otherwise the only other."""
    zips = [name for name in names if name.endswith('.zip')]
    mac = [name for name in zips if name.endswith('-mac.zip')]
    other = [name for name in zips if not name.endswith('-mac.zip')]
    if PLATFORM == 'darwin' and len(mac) == 1:
        return mac[0]
    if len(other) == 1:
        return other[0]
    return zips[0] if len(zips) == 1 else None


def unpack(archive: Path, into: Path) -> Path:
    """A release ZIP's files, written into an empty folder; the folder of the skill in it.
    A path outside the folder, a link, or more than a release holds, is refused."""
    try:
        with zipfile.ZipFile(archive) as packed:
            members = packed.infolist()
            if len(members) > MOST_FILES or sum(one.file_size for one in members) > MOST_BYTES:
                raise WorkspaceError('The release ZIP holds more than a skill does.')
            for one in members:
                inside = PurePosixPath(one.filename)
                mode = one.external_attr >> 16
                if inside.is_absolute() or '\\' in one.filename or any(
                        part in ('.', '..') for part in inside.parts):
                    raise WorkspaceError('The release ZIP has a file that cannot be placed.')
                if stat.S_ISLNK(mode):
                    raise WorkspaceError('The release ZIP holds a link, which a skill never '
                                         'does.')
                target = into / inside
                if one.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with packed.open(one) as source, open(target, 'xb') as written:
                    shutil.copyfileobj(source, written)
                if mode & 0o111:
                    target.chmod(0o755)
    except (zipfile.BadZipFile, OSError, ValueError) as failure:
        raise WorkspaceError(f'The release ZIP could not be unpacked ({failure}).')
    if (into / 'SKILL.md').is_file():
        return into
    held = [folder for folder in into.iterdir() if (folder / 'SKILL.md').is_file()]
    if len(held) != 1:
        raise WorkspaceError('The release ZIP does not hold a skill.')
    return held[0]


def _gh_env() -> dict:
    return {**os.environ, 'GH_PROMPT_DISABLED': '1', 'GH_NO_UPDATE_NOTIFIER': '1',
            'NO_COLOR': '1'}


def _by_gh(gh: str, slug: str, tag: str, into: Path, stop) -> Path | None:
    """The release's ZIP, downloaded with gh, checked and unpacked; None when gh is not
    signed in or the release has no ZIP to install."""
    env = _gh_env()
    code, late, _, _ = _run([gh, 'auth', 'status', '--hostname', 'github.com'],
                            LOOK_SECONDS, stop, env)
    if code != 0 or late:
        return None
    code, late, out, _ = _run([gh, 'release', 'view', tag, '--repo', slug, '--json',
                               'assets'], LOOK_SECONDS, stop, env)
    code = 1 if late else code
    try:
        names = [str(asset.get('name')) for asset in json.loads(out).get('assets') or []
                 if isinstance(asset, dict)] if code == 0 else []
    except (ValueError, AttributeError):
        names = []
    name = _zip_name(names)
    if name is None:
        return None
    sums = f'{name}.sha256' if f'{name}.sha256' in names else None
    download = into / 'download'
    download.mkdir()
    code, late, out, err = _run([gh, 'release', 'download', tag, '--repo', slug, '--dir',
                                 str(download), '--pattern', name,
                                 *(['--pattern', sums] if sums else [])],
                                FETCH_SECONDS, stop, env)
    archive = download / name
    if code != 0 or late or not archive.is_file():
        raise WorkspaceError(f'Its ZIP could not be downloaded with gh ({last_line(err, out)})')
    if sums:
        kept = (download / sums).read_text(encoding='utf-8', errors='replace').split()
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if len(kept) != 2 or kept[1] != name or kept[0] != digest:
            raise WorkspaceError(f'Its ZIP does not match the checksum published beside it, '
                                 f'{sums}')
    folder = into / 'unpacked'
    folder.mkdir()
    return unpack(archive, folder)


def _by_tag(address: str, tag: str, commit: str, into: Path) -> Path:
    """The tag, cloned at depth one with the person's own git access. Its commit must be
    the one that was shown."""
    tree = into / 'tree'
    done = hub.run(into, 'clone', '--quiet', '--depth', '1', '--branch', tag,
                   *hub.COPY_AS_IS, '--', address, str(tree), timeout=FETCH_SECONDS)
    if done.returncode != 0:
        raise WorkspaceError(f'{tag} could not be fetched. {plain(hub.reason(done))}')
    head = hub.run(tree, 'rev-parse', 'HEAD')
    if head.returncode != 0 or head.stdout.strip() != commit:
        raise WorkspaceError(f'{tag} was fetched at another commit than the {commit[:12]} you '
                             'were shown. Look at it again before you install')
    return tree


def fetch(address: str, tag: str, commit: str, into: Path, stop=None) -> tuple[Path, str]:
    """The release, in a new folder inside the empty folder `into`: (its folder, 'zip' or
    'tag')."""
    match, gh = GITHUB.match(address), shutil.which('gh')
    if match and gh:
        folder = _by_gh(gh, f'{match[1]}/{match[2]}', tag, into, stop)
        if folder is not None:
            return folder, 'zip'
    return _by_tag(address, tag, commit, into), 'tag'


# --- its own installer ---------------------------------------------------------------------

def bootstraps(folder: Path) -> dict:
    """The companion versions a release's installer brings when it finds none it can use,
    as the release records them: {'harness-slides': '0.13.1', ...}. Empty when it records
    none."""
    try:
        kept = json.loads((folder / SOURCES).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return {f'harness-{kind}': entry['version'] for kind, entry in
            (kept.items() if isinstance(kept, dict) else ())
            if re.fullmatch(r'[a-z]{1,40}', str(kind)) and isinstance(entry, dict)
            and isinstance(entry.get('version'), str) and order(entry['version'])}


def installer(folder: Path, node: str) -> list[str]:
    """How the release's own installer is run: the Mac one on a Mac, else the other."""
    mac, other = folder / 'scripts' / 'install-mac.mjs', folder / 'scripts' / 'install-skill.mjs'
    if PLATFORM == 'darwin' and mac.is_file():
        return [node, str(mac), '--yes', '--research', 'skip']
    if other.is_file():
        return [node, str(other), '--research', 'skip']
    raise WorkspaceError('The release has no installer Training Studio knows how to run: '
                         'scripts/install-mac.mjs on a Mac, or scripts/install-skill.mjs. '
                         'Nothing was run')


def install(folder: Path, home: Path, seconds: float, stop=None) -> tuple[int, bool, str]:
    """Run the release's own installer: (its exit code, whether it ran out of time, the
    last thing it said)."""
    node = shutil.which('node')
    if node is None:
        raise WorkspaceError('Its installer needs Node.js 20 or newer, which was not found '
                             'on this computer. Nothing was run')
    command = installer(folder, node)
    env = dict(os.environ)
    if Path(home).resolve() != Path.home().resolve():
        env.update({'HOME': str(home), 'USERPROFILE': str(home)})
        env.pop('CLAUDE_CONFIG_DIR', None)
    code, late, out, err = _run(command, seconds, stop, env, folder)
    return code, late, last_line(err, out) if code else last_line(out)
