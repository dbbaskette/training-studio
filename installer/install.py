#!/usr/bin/env python3
"""Install, check, roll back or remove the Training Studio skill."""
import sys

if sys.version_info < (3, 11):
    sys.exit('Training Studio setup needs Python 3.11 or newer; this is '
             + sys.version.split()[0] + '.')

import argparse
import hashlib
import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

NAME = 'training-studio'
REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / 'skills' / NAME
BOOTSTRAP = REPO / 'bootstrap' / NAME / 'SKILL.md'
GUIDANCE_SOURCE = {'repository': 'https://github.com/dbbaskette/training-studio.git',
                   'branch': 'main'}
GUIDANCE_PARTS = ('SKILL.md', 'references', 'assets')
SKILL_ROOTS = {'claude': ('.claude', 'skills'), 'codex': ('.agents', 'skills')}
HARNESS = {'claude': 'Claude Code', 'codex': 'Codex'}
COMPANIONS = {
    'harness-research': 'https://github.com/dbbaskette/harness-research-skill',
    'harness-slides': 'https://github.com/dbbaskette/harness-slides-skill',
}
IGNORED = ('__pycache__', '.DS_Store')


class InstallError(Exception):
    """A refusal to show the user as it is."""


def now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# --- the package ----------------------------------------------------------------

def package_files(source: Path) -> list[Path]:
    return sorted(path for path in source.rglob('*')
                  if path.is_file() and not any(part in IGNORED for part in path.parts))


def package_key(folder: Path) -> str:
    """The version and a hash of every file, naming one exact copy of the skill."""
    version = (folder / 'VERSION').read_text(encoding='utf-8').strip()
    digest = hashlib.sha256()
    for path in package_files(folder):
        digest.update(path.relative_to(folder).as_posix().encode() + b'\0')
        digest.update(path.read_bytes() + b'\0')
    return f'{version}-{digest.hexdigest()[:12]}'


def assemble(source: Path, bootstrap: Path, destination: Path) -> None:
    """Lay out an installed copy: a small entry, the scripts, and the guidance beside them.

    The entry fetches newer guidance when it can. The guidance copied here is what it falls
    back to when it cannot.
    """
    ignore = shutil.ignore_patterns(*IGNORED)
    destination.mkdir(parents=True)
    shutil.copy2(bootstrap, destination / 'SKILL.md')
    shutil.copy2(source / 'VERSION', destination / 'VERSION')
    (destination / 'source.json').write_text(
        json.dumps(GUIDANCE_SOURCE, indent=2) + '\n', encoding='utf-8')
    for folder in ('scripts', 'agents'):
        shutil.copytree(source / folder, destination / folder, ignore=ignore)
    for part in GUIDANCE_PARTS:
        target = destination / 'guidance' / part
        if (source / part).is_dir():
            shutil.copytree(source / part, target, ignore=ignore)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / part, target)


def verify(source: Path) -> None:
    """Refuse a source that is not a whole Training Studio package."""
    validator = source / 'scripts' / 'validate_package.py'
    if not (source / 'VERSION').is_file() or not validator.is_file():
        raise InstallError(f'{source} is not a Training Studio skill package.')
    spec = importlib.util.spec_from_file_location('training_studio_validator', validator)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    problems = module.problems(source)
    if problems:
        raise InstallError('The package is not whole:\n  ' + '\n  '.join(problems))


def smoke(skill: Path) -> None:
    """Confirm an installed copy runs: its guidance is whole and its helper answers."""
    # -B: checking the copy must not leave bytecode caches in it.
    checked = subprocess.run([sys.executable, '-B',
                              str(skill / 'scripts' / 'validate_package.py'),
                              '--guidance', str(skill / 'guidance')],
                             capture_output=True, text=True)
    if checked.returncode != 0:
        raise InstallError('The installed copy failed its own check:\n' + checked.stdout)
    with tempfile.TemporaryDirectory() as empty:
        asked = subprocess.run([sys.executable, '-B', str(skill / 'scripts' / 'training.py'),
                                '--dir', empty, 'status'], capture_output=True, text=True)
    if asked.returncode != 2 or 'No training in this directory' not in asked.stdout:
        raise InstallError('The installed helper did not answer as expected:\n'
                           + asked.stdout + asked.stderr)


# --- links and state ----------------------------------------------------------------

def replace_link(link: Path, target: Path) -> None:
    """Point a symbolic link at a target, replacing an existing link in one step."""
    link.parent.mkdir(parents=True, exist_ok=True)
    pending = link.with_name(f'.{link.name}.pending-{secrets.token_hex(4)}')
    os.symlink(target, pending)
    os.replace(pending, link)


def skill_link(home: Path, harness: str) -> Path:
    return home.joinpath(*SKILL_ROOTS[harness]) / NAME


def found_harnesses(home: Path) -> list[str]:
    return [harness for harness in SKILL_ROOTS if skill_link(home, harness).parent.is_dir()]


def chosen_harnesses(home: Path, target: str | None) -> list[str]:
    """The assistants to install for: the one named, or every one whose skill folder exists."""
    if target in SKILL_ROOTS:
        return [target]
    if target == 'both':
        return list(SKILL_ROOTS)
    found = found_harnesses(home)
    if not found:
        raise InstallError('No skill folder was found for Claude Code (~/.claude/skills) or '
                           'Codex (~/.agents/skills). Name one with --target claude or '
                           '--target codex and it will be created.')
    return found


def read_state(root: Path) -> dict | None:
    path = root / 'installation.json'
    if not path.is_file():
        return None
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
    except ValueError:
        raise InstallError(f'{path} is not valid JSON; remove it and install again.')
    if not isinstance(state, dict) or state.get('schema') != 1:
        raise InstallError(f'{path} was written by something else; refusing to change it.')
    return state


def write_state(root: Path, state: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    pending = root / f'.installation.json.pending-{secrets.token_hex(4)}'
    pending.write_text(json.dumps(state, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(pending, root / 'installation.json')


def blocked_links(home: Path, harnesses: list[str]) -> list[Path]:
    """Skill links that cannot be placed because something real is already there."""
    return [link for link in (skill_link(home, harness) for harness in harnesses)
            if link.exists() and not link.is_symlink()]


# --- actions ----------------------------------------------------------------------

def install(source: Path, home: Path, root: Path, harnesses: list[str], link_only: bool,
            replace: bool, bootstrap: Path = BOOTSTRAP) -> dict:
    """Install the skill and link it into each assistant's skill folder."""
    verify(source)
    if not link_only and not bootstrap.is_file():
        raise InstallError(f'The installer entry file is missing: {bootstrap}')
    blocked = blocked_links(home, harnesses)
    if blocked and not replace:
        raise InstallError('These exist and are not links, so they were left alone:\n  '
                           + '\n  '.join(str(path) for path in blocked)
                           + '\nMove them away, or add --replace to have them moved to '
                           + str(root / 'backups') + '.')
    state = read_state(root) or {'schema': 1, 'history': []}
    if link_only:
        key = package_key(source)
        destination = source
    else:
        pending = root / 'versions' / f'.pending-{secrets.token_hex(4)}'
        pending.parent.mkdir(parents=True, exist_ok=True)
        try:
            assemble(source, bootstrap, pending)
            key = package_key(pending)
            staged = root / 'versions' / key
            if not staged.exists():
                os.replace(pending, staged)
        finally:
            shutil.rmtree(pending, ignore_errors=True)
        if package_key(staged) != key:
            raise InstallError(f'{staged} exists but its files have changed. '
                               'Remove that folder and install again.')
        smoke(staged)
        replace_link(root / 'current', staged)
        destination = root / 'current'
        if not state['history'] or state['history'][-1] != key:
            state['history'].append(key)

    links = {}
    for harness in harnesses:
        link = skill_link(home, harness)
        entry = {'path': str(link), 'target': str(destination)}
        if link.is_symlink():
            entry['previous'] = os.readlink(link)
        elif link.exists():
            backup = root / 'backups' / f'{now().replace(":", "")}-{harness}-{NAME}'
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(link), str(backup))
            entry['backup'] = str(backup)
        replace_link(link, destination)
        links[harness] = entry
    state.update({'mode': 'link' if link_only else 'managed', 'current': key,
                  'source': str(source), 'installed_at': now(),
                  'links': {**state.get('links', {}), **links}})
    write_state(root, state)
    return {'action': 'install', 'mode': state['mode'], 'version': key, 'links': links,
            **prerequisites(home, harnesses)}


def rollback(root: Path) -> dict:
    """Go back to the version installed before the current one."""
    state = read_state(root)
    if state is None or state.get('mode') != 'managed':
        raise InstallError('Nothing to roll back: there is no managed installation here.')
    if len(state['history']) < 2:
        raise InstallError('Nothing to roll back to: only one version has been installed.')
    previous = state['history'][-2]
    staged = root / 'versions' / previous
    if not staged.is_dir():
        raise InstallError(f'The earlier version is no longer on disk: {staged}')
    smoke(staged)
    replace_link(root / 'current', staged)
    left = state['history'].pop()
    state.update({'current': previous, 'installed_at': now()})
    write_state(root, state)
    return {'action': 'rollback', 'version': previous, 'left': left}


def uninstall(root: Path) -> dict:
    """Remove the links this installer placed. Installed versions are left on disk."""
    state = read_state(root)
    if state is None:
        raise InstallError('Nothing to remove: Training Studio is not installed here.')
    removed, kept = [], []
    for entry in state.get('links', {}).values():
        link = Path(entry['path'])
        if link.is_symlink() and os.readlink(link) == entry['target']:
            link.unlink()
            removed.append(entry['path'])
        elif link.exists() or link.is_symlink():
            kept.append(entry['path'])
    if (root / 'current').is_symlink():
        (root / 'current').unlink()
    (root / 'installation.json').unlink()
    versions = root / 'versions'
    return {'action': 'uninstall', 'removed': removed, 'left_alone': kept,
            'versions_kept_in': str(versions) if versions.is_dir() else None}


def node_version() -> str | None:
    try:
        found = subprocess.run(['node', '--version'], capture_output=True, text=True)
    except OSError:
        return None
    return found.stdout.strip() if found.returncode == 0 else None


def prerequisites(home: Path, harnesses: list[str]) -> dict:
    """What Training Studio needs beside itself, and what is missing."""
    node = node_version()
    digits = (node or '').lstrip('v').split('.')[0]
    companions = {harness: {name: (skill_link(home, harness).parent / name).exists()
                            for name in COMPANIONS} for harness in harnesses}
    notes = []
    if not digits.isdigit() or int(digits) < 20:
        notes.append('Node 20 or newer is needed by the companion skills'
                     + (f'; found {node}.' if node else '; none was found.'))
    for harness, found in companions.items():
        for name, present in found.items():
            if not present:
                need = ('research cannot run without it' if name == 'harness-research'
                        else 'the deck will be reported as unavailable without it')
                notes.append(f'{name} is not installed for {HARNESS[harness]}: {need}. '
                             f'Get it from {COMPANIONS[name]}')
    pandoc = bool(shutil.which('pandoc'))
    if not pandoc:
        notes.append('pandoc was not found. It matters only if you ask for Word copies, which '
                     'will then rely on your assistant or be reported as unavailable: '
                     'https://pandoc.org')
    return {'python': sys.version.split()[0], 'node': node, 'pandoc': pandoc,
            'companions': companions, 'notes': notes}


def check(home: Path, root: Path, harnesses: list[str]) -> dict:
    """Report what is installed and whether its links still point where they should."""
    state = read_state(root) or {}
    links = {}
    for harness in harnesses:
        link = skill_link(home, harness)
        entry = state.get('links', {}).get(harness)
        if not link.is_symlink() and not link.exists():
            links[harness] = 'not linked'
        elif entry and link.is_symlink() and os.readlink(link) == entry['target'] \
                and (link / 'SKILL.md').is_file():
            links[harness] = 'ok'
        else:
            links[harness] = 'points somewhere this installer did not put it'
    return {'action': 'check', 'installed': bool(state), 'mode': state.get('mode'),
            'version': state.get('current'),
            'earlier_versions': state.get('history', [])[:-1], 'links': links,
            **prerequisites(home, harnesses)}


# --- command line -------------------------------------------------------------------

def describe(result: dict) -> str:
    """A plain-language account of what happened, for a person."""
    action = result['action']
    lines = []
    if action == 'install':
        how = 'linked to this checkout' if result['mode'] == 'link' else 'installed'
        lines.append(f"Training Studio {result['version']} is {how}.")
        for harness, entry in result['links'].items():
            lines.append(f"  {HARNESS[harness]}: {entry['path']}")
            if 'backup' in entry:
                lines.append(f"    What was there before was moved to {entry['backup']}")
    elif action == 'rollback':
        lines.append(f"Rolled back to {result['version']} (from {result['left']}).")
    elif action == 'uninstall':
        lines.append('Training Studio was removed from: '
                     + (', '.join(result['removed']) or 'nowhere; no links were found'))
        lines += [f'  Left alone, not ours: {path}' for path in result['left_alone']]
        if result['versions_kept_in']:
            lines.append(f"  Installed versions are still in {result['versions_kept_in']}; "
                         'delete that folder if you no longer want them.')
    elif action == 'check':
        if result['installed']:
            lines.append(f"Training Studio {result['version']} is installed "
                         f"({result['mode']}).")
        else:
            lines.append('Training Studio is not installed.')
        lines += [f'  {HARNESS[harness]}: {state}' for harness, state in result['links'].items()]
    elif action == 'plan':
        lines.append(f"Would install Training Studio {result['version']} ({result['mode']}) for: "
                     + ', '.join(HARNESS[harness] for harness in result['harnesses']))
        lines += [f'  {path}' for path in result['links']]
        lines += [f'  In the way, and not a link: {path}' for path in result['blocked']]
    notes = result.get('notes', [])
    if notes:
        lines += ['', 'Worth knowing:'] + [f'  - {note}' for note in notes]
    elif action in ('install', 'check'):
        lines += ['', 'Everything Training Studio needs is in place.']
    if action == 'install':
        lines += ['', 'Next: make a folder for a topic, start your assistant in it, and ask '
                      'for a training.']
    return '\n'.join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='install',
                        choices=('install', 'check', 'rollback', 'uninstall'))
    parser.add_argument('--target', choices=('claude', 'codex', 'both'),
                        help='which assistant to install for (default: every one found)')
    parser.add_argument('--link', action='store_true',
                        help='link to this checkout and copy nothing; for development')
    parser.add_argument('--replace', action='store_true',
                        help='move aside a real folder that is in the way of a link')
    parser.add_argument('--yes', action='store_true', help='do not ask before making changes')
    parser.add_argument('--dry-run', action='store_true',
                        help='say what an install would do; change nothing')
    parser.add_argument('--json', action='store_true', help='print the result as JSON')
    parser.add_argument('--home', type=Path, default=Path.home(), help=argparse.SUPPRESS)
    parser.add_argument('--root', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--source', type=Path, default=SOURCE, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    home = args.home.expanduser().resolve()
    root = (args.root or home / '.local' / 'share' / NAME).expanduser().resolve()
    source = args.source.expanduser().resolve()
    try:
        if args.action == 'check':
            named = [args.target] if args.target in SKILL_ROOTS else None
            result = check(home, root, named or found_harnesses(home) or list(SKILL_ROOTS))
        elif args.dry_run:
            if args.action != 'install':
                raise InstallError('--dry-run applies to install only.')
            verify(source)
            harnesses = chosen_harnesses(home, args.target)
            result = {'action': 'plan',
                      'version': (source / 'VERSION').read_text(encoding='utf-8').strip(),
                      'mode': 'link' if args.link else 'managed', 'harnesses': harnesses,
                      'links': [str(skill_link(home, harness)) for harness in harnesses],
                      'blocked': [str(path) for path in blocked_links(home, harnesses)]}
        else:
            if not args.yes:
                if not sys.stdin.isatty():
                    raise InstallError('Add --yes to make changes without being asked.')
                answer = input(f'Proceed with {args.action}? [y/N]: ').strip().lower()
                if answer not in ('y', 'yes'):
                    print('Nothing was changed.')
                    return 0
            if args.action == 'install':
                result = install(source, home, root, chosen_harnesses(home, args.target),
                                 args.link, args.replace)
            elif args.action == 'rollback':
                result = rollback(root)
            else:
                result = uninstall(root)
    except InstallError as refusal:
        print(json.dumps({'error': str(refusal)}) if args.json else f'Not done: {refusal}')
        return 1
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else describe(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
