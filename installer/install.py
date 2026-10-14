#!/usr/bin/env python3
"""Install, check, roll back or remove Training Studio: the skill, and the runner with it."""
import sys

if sys.version_info < (3, 11):
    sys.exit('Training Studio setup needs Python 3.11 or newer; this is '
             + sys.version.split()[0] + '.')

import argparse
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shlex
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
RUNNER = REPO / 'runner'
PINS = Path(__file__).resolve().parent / 'companions.json'   # the companions, each pinned
NEEDS = {'harness-research': 'research cannot run without it',
         'harness-slides': 'everything is built except the slide deck without it'}
IGNORED = ('__pycache__', '.DS_Store')
PLATFORM = sys.platform
OPENER = 'studio'                              # the one-line command, in the data folder
HELPER = 'training'                            # the helper's command, beside it
LAUNCHER = 'Open Training Studio.command'      # the double-click launcher, on macOS
OURS = '# Written by the Training Studio installer.'
# Where a Python new enough is looked for, in order. install.sh holds the same list, since it
# runs before any Python is found; a test keeps the two the same.
PYTHONS = ('python3', 'python3.14', 'python3.13', 'python3.12', 'python3.11',
           '/opt/homebrew/bin/python3', '/usr/local/bin/python3',
           '/Library/Frameworks/Python.framework/Versions/Current/bin/python3')
PYTHON_NEEDED = (3, 11)
NODE_NEEDED = 20
VERSION = re.compile(r'^\d+\.\d+\.\d+$')
HEX = {'commit': re.compile(r'^[0-9a-f]{40}$'), 'sha256': re.compile(r'^[0-9a-f]{64}$')}


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


def assemble(source: Path, bootstrap: Path, destination: Path, runner: Path = RUNNER,
             pins: Path | None = None) -> None:
    """Lay out an installed copy: a small entry, the scripts, the guidance beside them, and
    the runner beside the scripts, where it finds them.

    The entry fetches newer guidance when it can. The guidance copied here is what it falls
    back to when it cannot. This installer and the pins it installed with go beside the
    runner too, as they are beside it in a checkout: the runner asks them, when it starts,
    whether the skills are still in place, and brings a companion with them when asked.
    """
    ignore = shutil.ignore_patterns(*IGNORED)
    destination.mkdir(parents=True)
    shutil.copy2(bootstrap, destination / 'SKILL.md')
    shutil.copy2(source / 'VERSION', destination / 'VERSION')
    (destination / 'source.json').write_text(
        json.dumps(GUIDANCE_SOURCE, indent=2) + '\n', encoding='utf-8')
    for folder in ('scripts', 'agents'):
        shutil.copytree(source / folder, destination / folder, ignore=ignore)
    shutil.copytree(runner, destination / 'runner', ignore=ignore)
    (destination / 'installer').mkdir()
    shutil.copy2(Path(__file__).resolve(), destination / 'installer' / 'install.py')
    shutil.copy2(pins or PINS, destination / 'installer' / 'companions.json')
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
    if (skill / 'runner').is_dir():   # a version from before the runner has none
        # Asking for its usage loads every module of the runner, and so the helper's too.
        usage = subprocess.run([sys.executable, '-B', str(skill / 'runner' / 'studio.py'),
                                '--help'], capture_output=True, text=True)
        if usage.returncode != 0:
            raise InstallError('The installed runner did not start:\n'
                               + usage.stdout + usage.stderr)


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


# --- asking this computer --------------------------------------------------------------

def ask(command: tuple, cwd: Path | None = None, timeout: int = 20) -> tuple[int, str] | None:
    """Run one command that only reports: (its exit code, what it printed). None when the
    program is not on this computer."""
    try:
        done = subprocess.run(list(command), capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL, cwd=cwd)
    except FileNotFoundError:
        return None
    except (OSError, subprocess.TimeoutExpired):
        return 1, ''
    return done.returncode, (done.stdout or done.stderr).strip()


def node_version() -> str | None:
    found = ask(('node', '--version'))
    return found[1] if found and found[0] == 0 else None


def node_is_enough(node: str | None) -> bool:
    digits = (node or '').lstrip('v').split('.')[0]
    return digits.isdigit() and int(digits) >= NODE_NEEDED


def brand_skill(home: Path) -> bool | None:
    """Whether a brand skill is on this computer, found as the runner finds one. None when
    that could not be asked."""
    try:
        if str(RUNNER.parent) not in sys.path:
            sys.path.insert(0, str(RUNNER.parent))
        from runner import brand
        return bool(brand.found(home=home))
    except Exception:  # the report goes on without this line
        return None


# --- the runner -------------------------------------------------------------------------

def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def serving(home: Path) -> tuple[int, Path] | None:
    """The runner that is serving on this computer: (its process, the file that says so).
    The runner keeps that file in the per-user data folder for as long as it serves."""
    places = [home / '.local' / 'share' / NAME]
    override = os.environ.get('TRAINING_STUDIO_DATA')
    if override and home == Path.home().resolve():
        places.insert(0, Path(override).expanduser())
    for place in places:
        try:
            kept = (place / 'runner.pid').read_text(encoding='utf-8').strip()
        except OSError:
            continue
        if kept.isdigit() and alive(int(kept)):
            return int(kept), place / 'runner.pid'
    return None


def not_while_serving(home: Path) -> None:
    """Refuse to change anything underneath a runner that is working."""
    found = serving(home)
    if found:
        raise InstallError(f'Training Studio is open on this computer (process {found[0]}), '
                           'and it is never changed while it is working. Close it first: '
                           'press Ctrl-C in its window, or close that window. Then run this '
                           f'again. If it is not open, remove {found[1]}.')


def python_search(run: str, pythons: tuple | None = None) -> str:
    """The loop both commands use: `run` with the first Python new enough. The Python that
    ran this installer is tried first, then the places install.sh tries."""
    names = ' '.join(shlex.quote(name) for name in (pythons or (sys.executable, *PYTHONS)))
    return f"""for candidate in {names}; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1; then
    {run}
  fi
done"""


def opener_text(studio: Path) -> str:
    """The one-line command: finds a Python new enough and starts the runner with it."""
    return f"""#!/bin/sh
# Opens Training Studio: starts the runner, which shows its page in your browser.
{OURS} Run the installer again to renew it.
runner={shlex.quote(str(studio))}
if [ ! -f "$runner" ]; then
  printf '%s\\n' 'Training Studio is not installed here any more. Run its installer again.' >&2
  exit 1
fi
[ "$#" -eq 0 ] && set -- serve --open
{python_search('exec "$candidate" "$runner" "$@"')}
printf '%s\\n' 'Training Studio needs Python 3.11 or newer.' \\
  'Install it from https://www.python.org/downloads/ and open Training Studio again.' >&2
exit 1
"""


def helper_text(scripts: Path, itself: Path, pythons: tuple | None = None) -> str:
    """The helper's command: training.py, or guidance sync after `guidance`, run with a
    Python new enough whatever python3 is. A failure is printed as JSON, as the helper prints
    one, since an assistant reads it."""
    return f"""#!/bin/sh
# Runs the Training Studio helper with a Python new enough, whatever python3 is.
# `training <command>` runs training.py; `training guidance start` runs guidance sync.
{OURS} Run the installer again to renew it.
scripts={shlex.quote(str(scripts))}
script=training.py
if [ "$1" = guidance ]; then script=sync_guidance.py; shift; fi
if [ ! -f "$scripts/$script" ]; then
  printf '%s\\n' '{{"error": "Training Studio is not installed here any more. Run its installer again."}}'
  exit 2
fi
TRAINING_STUDIO_HELPER={shlex.quote(str(itself))}
export TRAINING_STUDIO_HELPER
{python_search('exec "$candidate" "$scripts/$script" "$@"', pythons)}
printf '%s\\n' '{{"error": "Training Studio needs Python 3.11 or newer. Install it from https://www.python.org/downloads/ and try again."}}'
exit 2
"""


def launcher_text(opener: Path) -> str:
    """The double-click launcher: the same command, in a terminal window of the person's own."""
    return f"""#!/bin/sh
# Double-click to open Training Studio. It works for as long as this window is open:
# press Ctrl-C here, or close the window, to stop it. Nothing is lost by stopping.
{OURS} Run the installer again to renew it.
printf '\\n%s\\n%s\\n\\n' 'Training Studio is starting. Its page opens in your browser.' \\
  'Leave this window open while you work. Press Ctrl-C here to stop.'
/bin/sh {shlex.quote(str(opener))}
studio_exit=$?
if [ -t 0 ]; then
  printf '\\n%s' 'Training Studio has stopped. Press Return to close this window. '
  read -r studio_close
fi
exit "$studio_exit"
"""


def launcher_places(home: Path, root: Path) -> dict[str, Path]:
    places = {'command': root / OPENER}
    if PLATFORM == 'darwin':
        places['double_click'] = home / 'Applications' / LAUNCHER
    places['helper'] = root / HELPER
    return places


def ours(path: Path) -> bool:
    """True for a launcher this installer wrote."""
    try:
        return path.is_file() and not path.is_symlink() \
            and OURS in path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return False


def write_launchers(home: Path, root: Path, studio: Path, scripts: Path,
                    kinds: tuple | None = None) -> dict[str, str]:
    """Write the ways to open the runner, and the helper's command: every one, or only the
    `kinds` named. A file of someone's own in the way is left alone."""
    places = launcher_places(home, root)
    texts = {'command': lambda: opener_text(studio),
             'helper': lambda: helper_text(scripts, places['helper']),
             'double_click': lambda: launcher_text(places['command'])}
    written = {}
    for kind, path in places.items():
        if kinds is not None and kind not in kinds:
            continue
        if (path.exists() or path.is_symlink()) and not ours(path):
            continue
        text = texts[kind]()
        path.parent.mkdir(parents=True, exist_ok=True)
        pending = path.with_name(f'.{path.name}.pending-{secrets.token_hex(4)}')
        try:
            pending.write_text(text, encoding='utf-8')
            pending.chmod(0o755)
            os.replace(pending, path)
        finally:
            pending.unlink(missing_ok=True)
        written[kind] = str(path)
    return written


def runner_report(home: Path, root: Path, state: dict) -> dict:
    """Where the runner stands: whether it is installed, how to open it, whether it serves."""
    kept = state.get('launchers', {})
    opener = Path(kept['command']) if 'command' in kept else None
    target = Path(state['runner']) if state.get('runner') else None
    found = serving(home)
    return {'installed': bool(target and target.is_file()),
            'open_with': 'sh ' + shlex.quote(str(opener)) if opener and ours(opener) else None,
            'double_click': kept.get('double_click') if ours(Path(kept.get('double_click', '')))
            else None,
            'serving': found[0] if found else None}


def helper_command(state: dict) -> str | None:
    """The helper's command, when this installer wrote it and it is still there."""
    kept = state.get('launchers', {}).get('helper')
    return kept if kept and ours(Path(kept)) else None


# --- the companion skills ---------------------------------------------------------------
#
# Each companion is installed by its own installer, from its own repository, at the one
# revision companions.json names. Nothing of a companion is kept in this repository.

def read_pins(path: Path) -> dict:
    """The pinned companions: {name: {repository, version, commit, sha256, stub, installer}}."""
    try:
        kept = json.loads(path.read_text(encoding='utf-8'))
        pins = kept['companions']
        if kept['schema'] != 1 or not isinstance(pins, dict):
            raise ValueError
        for name, pin in pins.items():
            for key in ('repository', 'version', 'commit', 'sha256', 'stub', 'installer'):
                if not isinstance(pin[key], str) or not pin[key]:
                    raise ValueError
            inside = [Path(pin[key]) for key in ('stub', 'installer')]
            if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', name) \
                    or not VERSION.match(pin['version']) \
                    or any(not pattern.match(pin[key]) for key, pattern in HEX.items()) \
                    or any(part.is_absolute() or '..' in part.parts for part in inside):
                raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        raise InstallError(f'{path} does not say which companion skills to install, or says '
                           'it in a way this installer does not read. Get this repository '
                           'again.')
    return pins


def as_tuple(version: str) -> tuple:
    return tuple(int(part) for part in version.split('.'))


def tree_digest(folder: Path) -> str:
    """One SHA-256 for every file under a folder: each file's path and its own SHA-256, in
    order. A link, or anything that is not a plain file, is refused."""
    lines = []
    for path in sorted(folder.rglob('*')):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise InstallError(f'{path.relative_to(folder)} is a link or a special file, '
                               'which a companion skill never holds.')
        if path.is_file():
            lines.append(hashlib.sha256(path.read_bytes()).hexdigest() + '  '
                         + path.relative_to(folder).as_posix() + '\n')
    return hashlib.sha256(''.join(lines).encode()).hexdigest()


def git(args: list[str], cwd: Path) -> tuple[int, str]:
    """Run git without anyone's sign-in being asked for: (exit code, what it said)."""
    env = {key: value for key, value in os.environ.items()
           if not key.startswith('GIT_') or key.startswith('GIT_CONFIG_')}
    env['GIT_TERMINAL_PROMPT'] = '0'
    try:
        done = subprocess.run(['git', *args], cwd=cwd, env=env, capture_output=True, text=True,
                              timeout=300, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise InstallError('git is needed to fetch a companion skill, and was not found.')
    except (OSError, subprocess.TimeoutExpired) as failure:
        return 1, type(failure).__name__
    return done.returncode, (done.stdout if done.returncode == 0 else done.stderr).strip()


def fetch_revision(repository: str, revision: str, into: Path) -> str:
    """Put one revision of a repository into an empty folder as plain files, with nothing of
    git left in it. Returns the commit that was fetched."""
    for step in (['init', '-q'],
                 ['fetch', '-q', '--depth', '1', '--no-tags', repository, revision],
                 ['-c', 'core.autocrlf=false', '-c', 'advice.detachedHead=false', 'checkout',
                  '-q', '--detach', 'FETCH_HEAD']):
        code, said = git(step, into)
        if code != 0:
            why = said.splitlines()[-1] if said else 'git gave no reason'
            raise InstallError(f'{revision} could not be fetched from {repository}: {why}')
    code, commit = git(['rev-parse', 'HEAD'], into)
    if code != 0 or not HEX['commit'].match(commit):
        raise InstallError(f'What was fetched from {repository} could not be read.')
    shutil.rmtree(into / '.git')
    return commit


def fetch_companion(name: str, pin: dict, root: Path) -> Path:
    """The companion's repository at its pinned revision, checked, in this installer's own
    folder. Refuses anything that is not exactly what companions.json names."""
    kept = root / 'companions' / name / pin['commit'][:12]
    if kept.is_dir():
        if tree_digest(kept) != pin['sha256']:
            raise InstallError(f'{kept} has changed since it was fetched. Remove that folder '
                               'and run this again.')
        return kept
    kept.parent.mkdir(parents=True, exist_ok=True)
    pending = Path(tempfile.mkdtemp(prefix='.pending-', dir=kept.parent))
    try:
        commit = fetch_revision(pin['repository'], pin['commit'], pending)
        if commit != pin['commit'] or tree_digest(pending) != pin['sha256']:
            raise InstallError(f"What {pin['repository']} gave for {name} {pin['version']} "
                               'is not what this installer expects, file for file. None of '
                               'it was kept and none of it was run.')
        stub = pending / pin['stub']
        named = re.search(r'^name: *(\S+) *$', stub.read_text(encoding='utf-8'), re.MULTILINE) \
            if stub.is_file() else None
        if not named or named.group(1) != name or not (pending / pin['installer']).is_file():
            raise InstallError(f'{name} at its pinned revision does not hold the entry and '
                               'the installer this installer expects. None of it was run.')
        os.replace(pending, kept)
    finally:
        shutil.rmtree(pending, ignore_errors=True)
    return kept


def companion_found(home: Path, harnesses: list[str], name: str) -> dict:
    """The version of a companion each assistant has: None when it has none, '' when one is
    there whose version cannot be read."""
    found = {}
    for harness in harnesses:
        skill = skill_link(home, harness).parent / name
        if not skill.exists() and not skill.is_symlink():
            found[harness] = None
            continue
        try:
            version = json.loads((skill / 'package.json').read_text(encoding='utf-8'))['version']
        except (OSError, ValueError, KeyError, TypeError):
            version = ''
        found[harness] = version if isinstance(version, str) and VERSION.match(version) else ''
    return found


def wanting(found: dict, wanted: str) -> list[str]:
    """The assistants that have no copy of a companion, or an older one than is pinned."""
    return [harness for harness, version in found.items()
            if version is None or (version and as_tuple(version) < as_tuple(wanted))]


def companion_command(node: str, checkout: Path, pin: dict, home: Path) -> list[str]:
    """How a companion's own installer is run. Only a home that is not the person's own is
    named to it; otherwise it is left to its own defaults."""
    command = [node, str(checkout / pin['installer'])]
    return command if home == Path.home().resolve() else [*command, '--home', str(home)]


def run_companion(name: str, pin: dict, checkout: Path, home: Path,
                  harnesses: list[str]) -> dict:
    """Run a companion's own installer from its checked copy, then look at what it left."""
    node = shutil.which('node')
    if not node:
        return {'state': 'failed', 'detail': 'Node was not found, and its installer runs on '
                                             'Node.'}
    env = dict(os.environ)
    if home != Path.home().resolve():
        env.update({'HOME': str(home), 'USERPROFILE': str(home)})
        env.pop('CLAUDE_CONFIG_DIR', None)
    try:
        done = subprocess.run(companion_command(node, checkout, pin, home), env=env,
                              capture_output=True, text=True, timeout=900,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as failure:
        return {'state': 'failed', 'detail': f'its installer did not finish '
                                             f'({type(failure).__name__}).'}
    if done.returncode != 0:
        said = (done.stderr or done.stdout).strip().splitlines()
        return {'state': 'failed', 'detail': 'its installer said: '
                + (said[-1][:300] if said else 'nothing, and stopped.')}
    try:
        said = json.loads(done.stdout)
    except ValueError:
        said = {}
    outcome = {'state': 'installed'}
    if isinstance(said, dict) and isinstance(said.get('next'), str):
        outcome['next'] = said['next'][:300]   # what its installer says is still to do
    stub = (checkout / pin['stub']).read_bytes()
    found = companion_found(home, harnesses, name)
    for harness in harnesses:
        entry = skill_link(home, harness).parent / name / 'SKILL.md'
        if wanting({harness: found[harness]}, pin['version']) or not entry.is_file() \
                or entry.read_bytes() != stub:
            return {'state': 'failed', 'detail': 'its installer finished, but did not leave '
                    f'the entry this installer checked for {HARNESS[harness]}.'}
    return outcome


def bring_companions(home: Path, root: Path, harnesses: list[str], pins: dict, agree,
                     state: dict, declined: str | None = None) -> dict:
    """Bring each companion that is missing or older than its pin, when the person agrees.
    One that is as new or newer is left alone. Nothing here undoes Training Studio's own
    installation: what goes wrong is reported. `declined` says why one was not agreed to."""
    outcomes = {}
    for name, pin in pins.items():
        found = companion_found(home, harnesses, name)
        outcome = {'wanted': pin['version'], 'found': found, 'state': 'left alone'}
        if wanting(found, pin['version']):
            if not node_is_enough(node_version()):
                outcome.update({'state': 'failed', 'detail': f'its installer needs Node '
                                f'{NODE_NEEDED} or newer.'})
            elif not agree(name, pin, found):
                outcome['state'] = 'waiting'
                if declined:
                    outcome['why'] = declined
            else:
                try:
                    checkout = fetch_companion(name, pin, root)
                    outcome.update(run_companion(name, pin, checkout, home, harnesses))
                except InstallError as refusal:
                    outcome.update({'state': 'refused', 'detail': str(refusal)})
                outcome['found'] = companion_found(home, harnesses, name)
                if outcome['state'] == 'installed':
                    state.setdefault('companions', {})[name] = {
                        'version': pin['version'], 'commit': pin['commit'],
                        'installed_at': now()}
        outcomes[name] = outcome
    return outcomes


def companions(home: Path, root: Path, target: str | None, pins: dict, agree,
               declined: str | None = None) -> dict:
    """Bring each companion skill that is missing or older than its pin, and nothing else.
    It is brought for the assistants named, else those Training Studio was installed for,
    else every one found. What was brought is recorded with the installation, when there is
    one. The runner's Update asks for this."""
    state = read_state(root)
    named = list(SKILL_ROOTS) if target == 'both' else [target] if target else None
    harnesses = named or list((state or {}).get('links', {})) or chosen_harnesses(home, None)
    outcomes = bring_companions(home, root, harnesses, pins, agree,
                                state if state is not None else {}, declined)
    if state is not None:
        write_state(root, state)
    notes = [said_of(name, pins[name], outcome, harnesses) for name, outcome in outcomes.items()]
    return {'action': 'companions', 'harnesses': harnesses, 'companions': outcomes,
            'notes': [note for note in notes if note]}


def pin(path: Path, name: str, revision: str) -> dict:
    """For whoever keeps this repository: pin a companion to a tag or commit of its own
    repository, and write what that revision holds into companions.json."""
    pins = read_pins(path)
    if name not in pins:
        raise InstallError(f'{name} is not a companion skill. Those are: '
                           + ', '.join(pins) + '.')
    entry = pins[name]
    with tempfile.TemporaryDirectory() as holder:
        commit = fetch_revision(entry['repository'], revision, Path(holder))
        try:
            version = json.loads((Path(holder) / 'package.json').read_text(
                encoding='utf-8'))['version']
        except (OSError, ValueError, KeyError, TypeError):
            version = None
        if not isinstance(version, str) or not VERSION.match(version) \
                or not all((Path(holder) / entry[key]).is_file()
                           for key in ('stub', 'installer')):
            raise InstallError(f'{revision} of {name} does not hold a version, its entry '
                               f"({entry['stub']}) and its installer ({entry['installer']}).")
        was = (entry['version'], entry['commit'])
        entry.update({'version': version, 'commit': commit,
                      'sha256': tree_digest(Path(holder))})
    pending = path.with_name(f'.{path.name}.pending-{secrets.token_hex(4)}')
    try:
        pending.write_text(json.dumps({'schema': 1, 'companions': pins}, indent=2) + '\n',
                           encoding='utf-8')
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)
    return {'action': 'pin', 'companion': name, 'version': version, 'commit': commit,
            'was': {'version': was[0], 'commit': was[1]}, 'written': str(path)}


# --- actions ----------------------------------------------------------------------

def install(source: Path, home: Path, root: Path, harnesses: list[str], link_only: bool,
            replace: bool, bootstrap: Path = BOOTSTRAP, runner: Path = RUNNER,
            pins: dict | None = None, agree=None, declined: str | None = None,
            pins_file: Path | None = None, while_open: bool = False) -> dict:
    """Install the skill and the runner, link the skill into each assistant's skill folder,
    write the ways to open the runner, and bring the companion skills the person agrees to.
    `pins_file` is where `pins` were read from, which the installed copy keeps.

    `while_open` is for the runner's own upgrade: a new version is laid beside the one it
    runs from, which is left whole, and `current` moves. A link to a checkout is never made
    while it is open."""
    verify(source)
    if not (runner / 'studio.py').is_file():
        raise InstallError(f'The runner is missing: {runner}')
    if not link_only and not bootstrap.is_file():
        raise InstallError(f'The installer entry file is missing: {bootstrap}')
    if link_only or not while_open:
        not_while_serving(home)
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
            assemble(source, bootstrap, pending, runner, pins_file)
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
    studio = (runner if link_only else root / 'current' / 'runner') / 'studio.py'
    scripts = (source if link_only else root / 'current') / 'scripts'
    state.update({'mode': 'link' if link_only else 'managed', 'current': key,
                  'source': str(source), 'installed_at': now(), 'runner': str(studio),
                  'launchers': write_launchers(home, root, studio, scripts),
                  'links': {**state.get('links', {}), **links}})
    write_state(root, state)
    outcomes = bring_companions(home, root, harnesses, pins or {},
                                agree or (lambda *asked: False), state, declined)
    write_state(root, state)
    return {'action': 'install', 'mode': state['mode'], 'version': key, 'links': links,
            'runner': runner_report(home, root, state), 'helper': helper_command(state),
            **prerequisites(home, root, harnesses, pins, outcomes)}


def rollback(root: Path, home: Path) -> dict:
    """Go back to the version installed before the current one, the runner with it."""
    state = read_state(root)
    if state is None or state.get('mode') != 'managed':
        raise InstallError('Nothing to roll back: there is no managed installation here.')
    if len(state['history']) < 2:
        raise InstallError('Nothing to roll back to: only one version has been installed.')
    not_while_serving(home)
    previous = state['history'][-2]
    staged = root / 'versions' / previous
    if not staged.is_dir():
        raise InstallError(f'The earlier version is no longer on disk: {staged}')
    smoke(staged)
    replace_link(root / 'current', staged)
    left = state['history'].pop()
    state.update({'current': previous, 'installed_at': now()})
    write_state(root, state)
    return {'action': 'rollback', 'version': previous, 'left': left,
            'runner': runner_report(home, root, state)}


def uninstall(root: Path, home: Path) -> dict:
    """Remove the links and launchers this installer placed. Installed versions are left on
    disk, and so are the companion skills, which belong to their own installers."""
    state = read_state(root)
    if state is None:
        raise InstallError('Nothing to remove: Training Studio is not installed here.')
    not_while_serving(home)
    removed, kept = [], []
    for entry in state.get('links', {}).values():
        link = Path(entry['path'])
        if link.is_symlink() and os.readlink(link) == entry['target']:
            link.unlink()
            removed.append(entry['path'])
        elif link.exists() or link.is_symlink():
            kept.append(entry['path'])
    launchers = []
    for path in map(Path, state.get('launchers', {}).values()):
        if ours(path):
            path.unlink()
            launchers.append(str(path))
    if (root / 'current').is_symlink():
        (root / 'current').unlink()
    (root / 'installation.json').unlink()
    versions = root / 'versions'
    return {'action': 'uninstall', 'removed': removed, 'left_alone': kept,
            'launchers_removed': launchers,
            'companions_left': sorted(state.get('companions', {})),
            'versions_kept_in': str(versions) if versions.is_dir() else None}


def again(*args: str) -> str:
    """The command that runs this installer again with these arguments, as it would be typed
    in the folder the person is in."""
    script = REPO / 'installer' / 'install.sh'
    try:
        script = script.relative_to(Path.cwd().resolve())
    except (OSError, ValueError):
        pass
    return shlex.join(['sh', str(script), *args])


# Why a companion that was wanted was not fetched, for the note that says so.
WHY = {'skipped': 'It was not fetched, because --companions skip was given.',
       'declined': 'It was not fetched, because you answered no.',
       'nobody to ask': 'It was not fetched, because no one was there to answer.'}
# What the notes are about, most important first: what stops everything, then what stops
# research, and so on down to what matters only when it is asked for.
IMPACT = ('assistant', 'git', 'harness-research', 'node', 'harness-slides', 'companion',
          'identity', 'python3', 'brand', 'pandoc')


def said_of(name: str, pin: dict, outcome: dict, harnesses: list[str]) -> str | None:
    """What is worth knowing about one companion, or None when it is as it should be."""
    found, wanted = outcome['found'], pin['version']
    need = NEEDS.get(name, 'part of a training cannot be made without it')
    source = pin['repository'].removesuffix('.git')
    command = again('--companions', 'install')
    if outcome['state'] in ('refused', 'failed'):
        return (f"{name} {wanted} was not installed, and {need}: {outcome['detail']} When that "
                f'is put right, run: {command}')
    short = wanting(found, wanted)
    if short:
        who = ' and '.join(HARNESS[harness] for harness in short)
        what = 'is not installed' if all(found[harness] is None for harness in short) \
            else f'is older than the {wanted} Training Studio was made with'
        why = WHY.get(outcome.get('why'))
        return ' '.join(filter(None, (f'{name} {what} for {who}: {need}.', why,
                                      f'To fetch it from {source} and install it, run: '
                                      f'{command}')))
    unread = [HARNESS[harness] for harness in harnesses if found[harness] == '']
    if unread:
        return (f"{name} is there for {' and '.join(unread)}, but not as its own installer "
                f'leaves it, so its version could not be read. It was left alone. If {need}, '
                f'move it away and run this again. It comes from {source}')
    return outcome.get('next') and f"{name} says there is more to do: {outcome['next']}"


def path_python() -> str | None:
    """The version of the python3 on PATH, which is what a bare `python3` runs."""
    found = ask(('python3', '--version'))
    named = re.search(r'Python (\d+\.\d+(?:\.\d+)?)', found[1]) \
        if found and found[0] == 0 else None
    return named.group(1) if named else None


def prerequisites(home: Path, root: Path, harnesses: list[str], pins: dict | None = None,
                  outcomes: dict | None = None) -> dict:
    """What Training Studio and its runner need beside themselves, and what is missing, each
    with how to get it, the most important first."""
    pins = pins or {}
    node = node_version()
    companions = {name: (outcomes or {}).get(name) or {
        'wanted': pin['version'], 'found': companion_found(home, harnesses, name),
        'state': 'not asked'} for name, pin in pins.items()}
    git_found = ask(('git', '--version')) is not None
    known = {key: bool(git_found and (ask(('git', 'config', '--get', f'user.{key}'),
                                          home if home.is_dir() else None)
                                      or (1, ''))[0] == 0) for key in ('name', 'email')}
    claude, codex = ask(('claude', '--version')), ask(('codex', '--version'))
    signed = ask(('codex', 'login', 'status')) if codex else None
    agents = {'claude': {'installed': claude is not None, 'signed_in': None},
              'codex': {'installed': codex is not None,
                        'signed_in': bool(signed and signed[0] == 0
                                          and 'not logged in' not in signed[1].lower())
                        if codex else None}}
    brand = brand_skill(home)
    python3 = path_python()
    notes = []   # (what it is about, the note)
    if not git_found:
        notes.append(('git', 'git was not found. The runner keeps every training in a git '
                      'repository. Install it from https://git-scm.com, then tell it your '
                      'name and email.'))
    elif not all(known.values()):
        notes.append(('identity', 'git does not know who you are, and the runner records who '
                      'decided what. Run: git config --global user.name "Your Name"  and  '
                      'git config --global user.email "you@example.com"'))
    if not agents['claude']['installed'] and not agents['codex']['installed']:
        notes.append(('assistant', 'No assistant was found. Install Claude Code or Codex and '
                      'sign in: the runner works with your own sign-in and has no key of its '
                      'own.'))
    elif not agents['claude']['installed'] and not agents['codex']['signed_in']:
        notes.append(('assistant', 'Codex is installed but not signed in. Run: codex login'))
    if not node_is_enough(node):
        notes.append(('node', f'Node {NODE_NEEDED} or newer is needed by the companion skills'
                      + (f'; found {node}.' if node else '; none was found.')
                      + ' Get it from https://nodejs.org'))
    for name, outcome in companions.items():
        note = said_of(name, pins[name], outcome, harnesses)
        if note:
            notes.append((name if name in IMPACT else 'companion', note))
    if python3 and as_tuple(python3)[:2] < PYTHON_NEEDED:
        notes.append(('python3', f'python3 on your PATH is {python3}, older than the 3.11 '
                      'Training Studio needs. Nothing needs changing: the commands this '
                      f'installer wrote, {root / HELPER} and {root / OPENER}, find a newer '
                      'Python themselves. Run the helper with the first of them, not with '
                      'python3.'))
    if brand is False:
        notes.append(('brand', 'No brand skill was found. A slide deck is always made in a '
                      'brand, so without one everything is made except the deck. A brand '
                      "skill is your organisation's own and is not installed from here: ask "
                      'whoever keeps yours.'))
    pandoc = bool(shutil.which('pandoc'))
    if not pandoc:
        notes.append(('pandoc', 'pandoc was not found. It matters only if you ask for Word '
                      'copies, which will then rely on your assistant or be reported as '
                      'unavailable: https://pandoc.org'))
    notes.sort(key=lambda note: IMPACT.index(note[0]))   # stable: ties keep their order
    return {'python': sys.version.split()[0], 'python3_on_path': python3, 'node': node,
            'pandoc': pandoc, 'git': {'installed': git_found, **known}, 'agents': agents,
            'brand_skill': brand, 'companions': companions,
            'notes': [note for _, note in notes]}


def check(home: Path, root: Path, harnesses: list[str], pins: dict | None = None) -> dict:
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
            'runner': runner_report(home, root, state), 'helper': helper_command(state),
            **prerequisites(home, root, harnesses, pins)}


def plan(source: Path, home: Path, root: Path, harnesses: list[str], link_only: bool,
         pins: dict) -> dict:
    """What an install would do. Changes nothing and fetches nothing."""
    companions = {}
    for name, pin in pins.items():
        found = companion_found(home, harnesses, name)
        companions[name] = {'wanted': pin['version'], 'found': found,
                            'would_offer': bool(wanting(found, pin['version'])),
                            'from': pin['repository'], 'commit': pin['commit']}
    return {'action': 'plan',
            'version': (source / 'VERSION').read_text(encoding='utf-8').strip(),
            'mode': 'link' if link_only else 'managed', 'harnesses': harnesses,
            'links': [str(skill_link(home, harness)) for harness in harnesses],
            'blocked': [str(path) for path in blocked_links(home, harnesses)],
            'launchers': {kind: str(path)
                          for kind, path in launcher_places(home, root).items()},
            'companions': companions}


# --- command line -------------------------------------------------------------------

def how_to_open(runner: dict) -> list[str]:
    lines = []
    if runner.get('double_click'):
        lines.append(f"  Double-click: {runner['double_click']}")
    if runner.get('open_with'):
        lines.append(f"  {'Or run' if lines else 'Run'}: {runner['open_with']}")
    return lines


def describe(result: dict) -> str:
    """A plain-language account of what happened, for a person."""
    action = result['action']
    lines = []
    if action == 'install':
        how = 'linked to this checkout' if result['mode'] == 'link' else 'installed'
        lines.append(f"Training Studio {result['version']} is {how}, the runner with it.")
        for harness, entry in result['links'].items():
            lines.append(f"  {HARNESS[harness]}: {entry['path']}")
            if 'backup' in entry:
                lines.append(f"    What was there before was moved to {entry['backup']}")
        for name, outcome in result['companions'].items():
            if outcome['state'] == 'installed':
                lines.append(f"  {name} {outcome['wanted']} was installed by its own "
                             'installer.')
            elif outcome['state'] == 'left alone' and not wanting(outcome['found'],
                                                                 outcome['wanted']):
                lines.append(f'  {name} was already there, and was left alone.')
    elif action == 'rollback':
        lines.append(f"Rolled back to {result['version']} (from {result['left']}).")
        if not result['runner']['installed']:
            lines.append('  That version came before the runner, so there is none to open.')
    elif action == 'uninstall':
        lines.append('Training Studio was removed from: '
                     + (', '.join(result['removed']) or 'nowhere; no links were found'))
        lines += [f'  Left alone, not ours: {path}' for path in result['left_alone']]
        lines += [f'  Launcher removed: {path}' for path in result['launchers_removed']]
        if result['companions_left']:
            lines.append('  Left in place, for anything else that uses them: '
                         + ', '.join(result['companions_left']))
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
        if result['installed']:
            lines.append('  The runner: ' + (
                f"open now (process {result['runner']['serving']})"
                if result['runner']['serving'] else 'installed'
                if result['runner']['installed'] else 'not in this version'))
    elif action == 'plan':
        lines.append(f"Would install Training Studio {result['version']} ({result['mode']}), "
                     'the runner with it, for: '
                     + ', '.join(HARNESS[harness] for harness in result['harnesses']))
        lines += [f'  {path}' for path in result['links']]
        lines += [f'  In the way, and not a link: {path}' for path in result['blocked']]
        lines += [f"  {'The helper' if kind == 'helper' else 'A way to open it'}: {path}"
                  for kind, path in result['launchers'].items()]
        for name, companion in result['companions'].items():
            lines.append(f"  {name} {companion['wanted']}: " + (
                f"would be offered, from {companion['from']} at revision "
                f"{companion['commit'][:12]}" if companion['would_offer']
                else 'already there; would be left alone'))
    elif action == 'companions':
        for name, outcome in result['companions'].items():
            if outcome['state'] == 'installed':
                lines.append(f"{name} {outcome['wanted']} was installed by its own installer.")
            elif outcome['state'] == 'left alone' and not wanting(outcome['found'],
                                                                 outcome['wanted']):
                lines.append(f"{name} is already as new as {outcome['wanted']}, and was left "
                             'alone.')
        lines = lines or ['No companion skill was brought.']
    elif action == 'pin':
        lines.append(f"{result['companion']} is now pinned to {result['version']} "
                     f"({result['commit'][:12]}); it was {result['was']['version']} "
                     f"({result['was']['commit'][:12]}).")
        lines.append(f"  Written to {result['written']}. Read what changed between the two "
                     'revisions before you commit it.')
    if action in ('install', 'check', 'rollback') and how_to_open(result['runner']):
        lines += ['', 'To open Training Studio:'] + how_to_open(result['runner'])
    notes = result.get('notes', [])
    if notes:
        lines += ['', 'Worth knowing:'] + [f'  - {note}' for note in notes]
    elif action in ('install', 'check'):
        lines += ['', 'Everything Training Studio needs is in place.']
    if action in ('install', 'check') and result['agents']['claude']['installed']:
        lines += ['', 'Claude Code cannot be asked whether it is signed in without starting '
                      'it. If you have not used it on this computer, run `claude` once.']
    if action == 'install':
        lines += ['', 'Next: open Training Studio and press "New training". Or make a folder '
                      'for a topic, start your assistant in it, and ask for a training.']
    return '\n'.join(lines)


def offer(name: str, pin: dict, found: dict) -> bool:
    """Ask the person whether to fetch a companion and run its installer."""
    source = pin['repository'].removesuffix('.git')
    having = sorted({version for version in found.values() if version})
    print(f"\n{name} {pin['version']} "
          + (f'is newer than the {having[0]} on this computer' if having
             else 'is not on this computer')
          + f": {NEEDS.get(name, 'part of a training cannot be made without it')}.")
    print(f"  It would be fetched from {source} at revision {pin['commit'][:12]} and checked, "
          'file for file,\n  against what this installer expects. Then its own installer '
          'would be run with Node.\n  That installer registers the skill for every assistant '
          'it knows, not only those above.')
    if pin.get('note'):
        print(f"  {pin['note']}")
    return input(f'Fetch {name} and run its installer? [y/N]: ').strip().lower() in ('y', 'yes')


def agreement(choice: str) -> tuple:
    """How each companion is agreed to for --companions, and why one is not."""
    return {'install': (lambda *asked: True, None),
            'skip': (lambda *asked: False, 'skipped'),
            'ask': (offer, 'declined') if sys.stdin.isatty()
            else (lambda *asked: False, 'nobody to ask')}[choice]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='install',
                        choices=('install', 'check', 'rollback', 'uninstall', 'companions',
                                 'pin'))
    parser.add_argument('companion', nargs='?', help=argparse.SUPPRESS)
    parser.add_argument('--target', choices=('claude', 'codex', 'both'),
                        help='which assistant to install for (default: every one found)')
    parser.add_argument('--link', action='store_true',
                        help='link to this checkout and copy nothing; for development')
    parser.add_argument('--replace', action='store_true',
                        help='move aside a real folder that is in the way of a link')
    parser.add_argument('--companions', choices=('ask', 'install', 'skip'), default='ask',
                        help='the companion skills: ask about each (the default; with no '
                             'one to ask, none is brought), install them, or skip them')
    parser.add_argument('--yes', action='store_true', help='do not ask before making changes')
    parser.add_argument('--dry-run', action='store_true',
                        help='say what an install would do; change nothing')
    parser.add_argument('--json', action='store_true', help='print the result as JSON')
    parser.add_argument('--revision', help=argparse.SUPPRESS)   # with pin: a tag or commit
    # With companions, or install of a new version: the runner asks, while it is open,
    # having seen no training working.
    parser.add_argument('--while-open', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--home', type=Path, default=Path.home(), help=argparse.SUPPRESS)
    parser.add_argument('--root', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--source', type=Path, default=SOURCE, help=argparse.SUPPRESS)
    parser.add_argument('--pins', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    home = args.home.expanduser().resolve()
    root = (args.root or home / '.local' / 'share' / NAME).expanduser().resolve()
    source = args.source.expanduser().resolve()
    pins_path = (args.pins or PINS).expanduser().resolve()
    try:
        if args.action == 'pin' and not (args.companion and args.revision):
            raise InstallError('Name the companion and its revision: '
                               'pin harness-slides --revision v0.14.1')
        if args.action != 'pin' and args.companion:
            raise InstallError(f'{args.companion} is one word too many.')
        pins = read_pins(pins_path)
        if args.action == 'check':
            named = [args.target] if args.target in SKILL_ROOTS else None
            result = check(home, root, named or found_harnesses(home) or list(SKILL_ROOTS),
                           pins)
        elif args.dry_run:
            if args.action != 'install':
                raise InstallError('--dry-run applies to install only.')
            verify(source)
            result = plan(source, home, root, chosen_harnesses(home, args.target), args.link,
                          pins)
        elif args.action == 'companions':
            # Each companion is its own question, so there is no question before them.
            if not args.while_open:
                not_while_serving(home)
            result = companions(home, root, args.target, pins, *agreement(args.companions))
        else:
            harnesses = chosen_harnesses(home, args.target) if args.action == 'install' else []
            if not args.yes:
                if not sys.stdin.isatty():
                    raise InstallError('Add --yes to make changes without being asked.')
                if args.action == 'install':
                    print(describe(plan(source, home, root, harnesses, args.link, pins)) + '\n')
                answer = input(f'Proceed with {args.action}? [y/N]: ').strip().lower()
                if answer not in ('y', 'yes'):
                    print('Nothing was changed.')
                    return 0
            if args.action == 'install':
                agree, declined = agreement(args.companions)
                result = install(source, home, root, harnesses, args.link, args.replace,
                                 pins=pins, agree=agree, declined=declined,
                                 pins_file=pins_path, while_open=args.while_open)
            elif args.action == 'rollback':
                result = rollback(root, home)
            elif args.action == 'pin':
                result = pin(pins_path, args.companion, args.revision)
            else:
                result = uninstall(root, home)
    except InstallError as refusal:
        print(json.dumps({'error': str(refusal)}) if args.json else f'Not done: {refusal}')
        return 1
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else describe(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
