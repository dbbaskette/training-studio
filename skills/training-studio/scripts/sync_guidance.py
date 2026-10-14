#!/usr/bin/env python3
"""Fetch, pin and verify the guidance a training follows.

Guidance is the skill's SKILL.md, references and assets. It can be newer than the installed
scripts, so it is fetched from the skill's repository and pinned for each training. Scripts
are never fetched: every command runs from the installed copy.
"""
import sys

if sys.version_info < (3, 11):
    sys.exit('Training Studio needs Python 3.11 or newer; this is '
             + sys.version.split()[0] + '.')

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import home

RUNTIME = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = {'repository': 'https://github.com/dbbaskette/training-studio.git',
                  'branch': 'main'}
PARTS = ('SKILL.md', 'references', 'assets')
STATE_DIR = '.training-studio'


class SyncError(Exception):
    """A reason guidance could not be fetched or used, to show as it is."""


def runtime_version() -> str:
    return (RUNTIME / 'VERSION').read_text(encoding='utf-8').strip()


def source() -> dict:
    """Where guidance comes from: the installed source.json, or the public repository."""
    configured = home.read_json(RUNTIME / 'source.json', {})
    found = {**DEFAULT_SOURCE, **(configured if isinstance(configured, dict) else {})}
    if os.environ.get('TRAINING_STUDIO_SOURCE'):
        found['repository'] = os.environ['TRAINING_STUDIO_SOURCE']
    return found


def bundled() -> Path:
    """The guidance that came with the installed scripts, used when nothing newer can be had."""
    inside = RUNTIME / 'guidance'
    return inside if (inside / 'SKILL.md').is_file() else RUNTIME


def helper() -> str:
    """How to run the helper: the installer's `training` command when that is what ran this,
    since it finds a Python new enough; otherwise training.py itself."""
    command = os.environ.get('TRAINING_STUDIO_HELPER')
    if command and Path(command).is_file():
        return command
    return str(RUNTIME / 'scripts' / 'training.py')


def guidance_root() -> Path:
    return home.data_root() / 'guidance'


def git(*args: str, cwd: Path | None = None) -> bytes:
    try:
        done = subprocess.run(['git', *args], cwd=cwd, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as failure:
        raise SyncError(f'git could not run: {failure}')
    if done.returncode != 0:
        message = done.stderr.decode('utf-8', 'replace').strip().splitlines()
        raise SyncError(message[-1] if message else 'git failed')
    return done.stdout


def as_tuple(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in version.split('.'))
    except ValueError:
        raise SyncError(f'"{version}" is not a version number.')


def hashes(folder: Path) -> dict[str, str]:
    return {path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.rglob('*')) if path.is_file()}


def fetch(revision: str | None = None) -> str:
    """Fetch the source branch, or one commit, into the local cache; return the commit."""
    cache = guidance_root() / 'cache.git'
    if not (cache / 'HEAD').is_file():
        cache.parent.mkdir(parents=True, exist_ok=True)
        git('init', '--quiet', '--bare', str(cache))
    where = source()
    git('fetch', '--quiet', '--depth', '1', where['repository'], revision or where['branch'],
        cwd=cache)
    return git('rev-parse', 'FETCH_HEAD', cwd=cache).decode().strip()


def cached(commit: str) -> bool:
    """True when the local cache already holds a commit."""
    cache = guidance_root() / 'cache.git'
    if not (cache / 'HEAD').is_file():
        return False
    try:
        git('cat-file', '-e', f'{commit}^{{commit}}', cwd=cache)
    except SyncError:
        return False
    return True


def manifest(commit: str) -> dict:
    """The guidance manifest at a commit, checked against the installed scripts."""
    cache = guidance_root() / 'cache.git'
    try:
        found = json.loads(git('show', f'{commit}:guidance/manifest.json', cwd=cache))
    except ValueError:
        raise SyncError('The guidance manifest is not valid JSON.')
    if not isinstance(found, dict) or found.get('schema') != 1 \
            or not isinstance(found.get('content_root'), str):
        raise SyncError('The guidance manifest is not one this version understands.')
    needed = str(found.get('minimum_runtime', '0'))
    if as_tuple(needed) > as_tuple(runtime_version()):
        raise SyncError(f'The newest guidance needs Training Studio {needed} or later; '
                        f'{runtime_version()} is installed. Update the skill to use it.')
    return found


def materialize(commit: str) -> Path:
    """Put one commit's guidance files in the cache, and return the folder."""
    folder = guidance_root() / commit[:12]
    if (folder / 'SKILL.md').is_file():
        return folder
    root = manifest(commit)['content_root'].strip('/')
    cache = guidance_root() / 'cache.git'
    archive = git('archive', '--format=tar', commit, *(f'{root}/{part}' for part in PARTS),
                  cwd=cache)
    pending = folder.with_name(f'.{folder.name}.pending')
    shutil.rmtree(pending, ignore_errors=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        for member in bundle.getmembers():
            if not member.isfile() or not member.name.startswith(root + '/'):
                continue
            inside = Path(member.name).relative_to(root)
            if '..' in inside.parts:
                continue
            target = pending / inside
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.extractfile(member).read())
    if not (pending / 'SKILL.md').is_file():
        shutil.rmtree(pending, ignore_errors=True)
        raise SyncError('The fetched guidance has no SKILL.md.')
    shutil.rmtree(folder, ignore_errors=True)
    pending.replace(folder)
    return folder


def pin_path(project: Path) -> Path:
    return project / STATE_DIR / 'guidance.json'


def write_pin(project: Path, commit: str | None, folder: Path) -> dict:
    pin = {'schema': 1, 'commit': commit, 'path': str(folder),
           'files': hashes(folder) if commit else {}, 'runtime': runtime_version(),
           'pinned_at': home.now()}
    home.write_json(pin_path(project), pin)
    return pin


def answer(folder: Path, commit: str | None, freshness: str, pinned: bool,
           notice: str | None = None) -> dict:
    return {'entry': str(folder / 'SKILL.md'), 'helper': helper(), 'commit': commit,
            'freshness': freshness, 'pinned': pinned, 'runtime': runtime_version(),
            'notice': notice}


def latest() -> tuple[Path, str | None, str, str | None]:
    """The newest usable guidance: folder, commit, freshness and a notice if it fell back."""
    try:
        commit = fetch()
        fresh = 'cached' if (guidance_root() / commit[:12] / 'SKILL.md').is_file() else 'fetched'
        return materialize(commit), commit, fresh, None
    except SyncError as failure:
        return bundled(), None, 'installed', (
            f'Could not get the newest guidance: {failure} Using the guidance installed '
            'with the skill, which may be older.')


def start(project: Path) -> dict:
    """The guidance to follow here: the pinned one for a training, else the newest."""
    if pin_path(project).is_file():
        return resume(project)
    folder, commit, freshness, notice = latest()
    home.write_json(guidance_root() / 'last.json', {'commit': commit, 'path': str(folder)})
    has_training = (project / STATE_DIR / 'session.json').is_file()
    if has_training:
        write_pin(project, commit, folder)
    return answer(folder, commit, freshness, has_training, notice)


def adopt(project: Path) -> dict | None:
    """Pin a new training to the guidance the last start resolved. Called by init."""
    last = home.read_json(guidance_root() / 'last.json', None)
    if not isinstance(last, dict) or not (Path(last.get('path', '')) / 'SKILL.md').is_file():
        return None
    return write_pin(project, last.get('commit'), Path(last['path']))


def resume(project: Path) -> dict:
    """The guidance a training is pinned to, verified against what was pinned."""
    pin = home.read_json(pin_path(project), None)
    if not isinstance(pin, dict) or pin.get('schema') != 1:
        raise SyncError('The guidance pin for this training cannot be read.')
    commit = pin.get('commit')
    if commit is None:
        return answer(bundled(), None, 'installed', True)
    folder = Path(pin['path'])
    intact = (folder / 'SKILL.md').is_file() and hashes(folder) == pin['files']
    if not intact:
        try:
            shutil.rmtree(guidance_root() / commit[:12], ignore_errors=True)
            if not cached(commit):
                fetch(commit)
            folder = materialize(commit)
        except SyncError as failure:
            return answer(bundled(), None, 'installed', True, (
                'The guidance this training was pinned to is not on this computer and '
                f'could not be fetched: {failure} Using the guidance installed with the skill.'))
        if hashes(folder) != pin['files']:
            raise SyncError('The pinned guidance does not match what was recorded for this '
                            'training. Run update to adopt the current guidance.')
        pin['path'] = str(folder)
        home.write_json(pin_path(project), pin)
    return answer(folder, commit, 'pinned', True)


def update(project: Path) -> dict:
    """Move a training to the newest guidance. Checks may give different results afterwards."""
    if not (project / STATE_DIR / 'session.json').is_file():
        raise SyncError('No training in this directory.')
    before = home.read_json(pin_path(project), {})
    commit = fetch()
    folder = materialize(commit)
    write_pin(project, commit, folder)
    changed = before.get('commit') != commit
    return answer(folder, commit, 'fetched', True, (
        f"Guidance moved from {(before.get('commit') or 'the installed copy')[:12]} to "
        f'{commit[:12]}. Run the checks again; results can differ.') if changed else None)


def summary(project: Path) -> dict | None:
    """What a training is pinned to, for status output."""
    pin = home.read_json(pin_path(project), None)
    if not isinstance(pin, dict):
        return None
    return {'commit': pin.get('commit'), 'pinned_at': pin.get('pinned_at'),
            'runtime': pin.get('runtime')}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('action', choices=('start', 'resume', 'update'))
    parser.add_argument('--project', default='.', help='the training directory')
    args = parser.parse_args(argv)
    project = Path(args.project).resolve()
    try:
        result = {'start': start, 'resume': resume, 'update': update}[args.action](project)
    except (SyncError, OSError) as failure:
        print(json.dumps({'error': str(failure)}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
