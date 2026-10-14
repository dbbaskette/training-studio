"""A companion skill's command line on this computer, and the one way the runner runs a
command it may have to end.

What a caller needs to know
---------------------------
    VARIABLE, SCRIPT = 'HARNESS_SLIDES_RUNTIME', Path('scripts') / 'harness-slides.mjs'
    places = companion.locations(VARIABLE, 'harness-slides', 'Harness Slides')
    runtime = companion.find_runtime(places, SCRIPT, VARIABLE, 'harness-slides',
                                     'a deck cannot be made')
    code, out, err = companion.run_command(command, cwd, 300, 'The slides tool')
    with companion.stopping(run.stop):
        ...                                   # every command run here ends on Stop
    code, late = companion.supervise(command, cwd, env, stdin, seconds, errors, each, stop)

- `locations` lists where a companion may be installed: the folder its variable names,
  when that is set, and nothing else; otherwise the folder its own installer uses and each
  assistant's skills folder. With no name, every folder in those places is listed, which
  is how a brand skill, whose name is not known, is looked for. `home` stands in for the
  person's home folder.
- `find_runtime` is the first of those places that holds the script, with links followed
  so that one version is used throughout. It refuses in a sentence when there is none.
- `run_command` runs a command once and returns (exit code, standard output, standard
  error) as text. A command that takes longer than its seconds, or cannot be started, is a
  WorkspaceError whose sentence begins with `said`. Within `stopping(stop)`, a command
  still running when `stop` is set is ended and Stopped is raised. Stopped is not a
  WorkspaceError: a step ended on purpose has nothing to say to a person.
- `stopping` holds for the thread it is entered in. A thread started inside it, such as
  one of a pool, needs `contextvars.copy_context().run` to carry it.
- `supervise` is what both an agent and a companion command run under. The command gets a
  process group of its own, and the whole group is killed as soon as the command ends,
  when time runs out, when `stop` is set or when the caller fails. So nothing it started
  is left running, and a process it left behind cannot keep the caller reading. A small
  watcher leads the group from before the command starts, and kills it if the caller is
  itself killed, however soon. That is how a preview the worker tools' server started
  inside an agent ends when that agent is stopped. A process
  that started a session of its own is out of reach, so reading stops GRACE seconds after
  the rest has been ended. The command is always waited for. Where there are no process
  groups, only the command itself is ended.
"""
from __future__ import annotations

import contextlib
import contextvars
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
from workspace import WorkspaceError

SHARED = (('Library', 'Application Support'), ('.local', 'share'))  # an installer's folder
SKILLS = (('.claude', 'skills'), ('.agents', 'skills'), ('.cursor', 'skills'))
GROUPS = hasattr(os, 'killpg')   # elsewhere only the command itself can be ended
TICK = 0.05     # seconds between looks at whether a command should be ended
GRACE = 2       # seconds to read what is left once a command has been ended
# The watcher leads the process group a command joins. It kills its own group when the
# pipe from the caller closes, which happens only when the caller is killed: a caller that
# ends a command itself kills the group first.
WATCHER = ('import os, signal, sys\n'
           'sys.stdin.buffer.read()\n'
           'os.killpg(0, signal.SIGKILL)\n')
STOP: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar(
    'stop', default=None)


class Stopped(Exception):
    """A command was ended because the run it was part of was stopped."""


# --- where a companion is --------------------------------------------------------------

def locations(variable: str, name: str | None = None, title: str | None = None,
              home: Path | None = None) -> list[Path]:
    """Every folder that may be an installed companion. The folder `variable` names, when
    set, is the only place looked. `title` is the name its installer gives its folder on a
    Mac. With no name, every folder in each place is listed."""
    override = os.environ.get(variable)
    if override:
        return [Path(override).expanduser()]

    def inside(folder: Path, named: str | None) -> list[Path]:
        if named:
            return [folder / named]
        try:
            return sorted(folder.iterdir())
        except OSError:
            return []

    user = home or Path.home()
    return [place / 'current' for parts, named in zip(SHARED, (title, name))
            for place in inside(user.joinpath(*parts), named)] \
        + [place for parts in SKILLS for place in inside(user.joinpath(*parts), name)]


def find_runtime(places: list[Path], script: Path, variable: str, name: str,
                 unable: str) -> Path:
    """The first place that holds `script`, with links followed so one version is used
    throughout. Refuses when there is none; `unable` says what cannot be done then."""
    for place in places:
        if (place / script).is_file():
            return place.resolve()
    if os.environ.get(variable):
        raise WorkspaceError(f'{variable} names {os.environ[variable]}, which does not hold '
                             f'{name}. Point it at the installed skill, or unset it.')
    raise WorkspaceError(f'The {name} skill is not installed on this computer, so {unable}. '
                         'Install it, then try again.')


# --- running a command -----------------------------------------------------------------

@contextlib.contextmanager
def stopping(stop: threading.Event | None):
    """Within this, a command `run_command` runs ends when `stop` is set."""
    token = STOP.set(stop)
    try:
        yield
    finally:
        STOP.reset(token)


def _text(data: bytes) -> str:
    """Output as text, with its line endings made plain as text mode would."""
    return data.decode('utf-8', 'replace').replace('\r\n', '\n').replace('\r', '\n')


def run_command(command: list[str], cwd: Path | None, seconds: float,
                said: str) -> tuple[int, str, str]:
    """Run a command line once: (exit code, standard output, standard error)."""
    stop, printed = STOP.get(), []
    with tempfile.TemporaryFile() as errors:
        try:
            code, late = supervise(command, cwd, None, '', seconds, errors, printed.append,
                                   stop)
        except OSError as failure:
            raise WorkspaceError(f'{said} could not be started ({failure}).')
        errors.seek(0)
        complaint = errors.read()
    if stop is not None and stop.is_set():
        raise Stopped(f'{said} was stopped before it finished.')
    if late:
        raise WorkspaceError(f'{said} did not answer in {seconds:g} seconds.')
    return code, _text(b''.join(printed)), _text(complaint)


def _watcher() -> subprocess.Popen | None:
    """Start a watcher at the head of a process group of its own, outside the caller's
    group so that killing that group does not kill it too. The command joins its group,
    so the group is known before the command runs. None when it cannot be started."""
    try:
        return subprocess.Popen([sys.executable, '-I', '-S', '-c', WATCHER],
                                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, process_group=0)
    except (OSError, ValueError):
        return None


def _dismiss(watcher: subprocess.Popen | None) -> None:
    """End a watcher that is no longer needed, without waiting for it to have started."""
    if watcher is not None:
        watcher.kill()
        watcher.wait()
        with contextlib.suppress(OSError):
            watcher.stdin.close()


def supervise(command: list[str], cwd: Path | None, env: dict | None, stdin: str,
              seconds: float, errors, each, stop: threading.Event | None = None
              ) -> tuple[int, bool]:
    """Run a command to its end or to its time limit, passing each line it prints to
    `each` as bytes. Returns its exit code and whether it was stopped for taking too long.
    `errors` is a file, or the path of one, that standard error is written to.

    The whole process group is killed once the command ends, when time runs out, when
    `stop` is set or when the caller fails; see the module docstring.
    """
    if isinstance(errors, (str, os.PathLike)):
        with open(errors, 'wb') as complaints:
            return supervise(command, cwd, env, stdin, seconds, complaints, each, stop)
    watcher = _watcher() if GROUPS else None
    grouped = ({'process_group': watcher.pid} if watcher is not None
               else {'start_new_session': GROUPS})
    try:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=errors, **grouped)
    except BaseException:
        _dismiss(watcher)
        raise
    group = watcher.pid if watcher is not None else process.pid
    over, failed = threading.Event(), []

    def kill() -> None:
        try:
            if GROUPS:
                os.killpg(group, signal.SIGKILL)
            else:
                process.kill()
        except (ProcessLookupError, PermissionError):
            pass

    def feed() -> None:
        for step in (lambda: process.stdin.write(stdin.encode('utf-8')), process.stdin.close):
            try:
                step()
            except OSError:
                pass  # it stopped reading; how it ended says why

    def read() -> None:
        try:
            for line in process.stdout:
                if over.is_set():
                    break
                each(line)
        except BaseException as failure:  # the caller's own failure, raised again below
            failed.append(failure)
        finally:
            process.stdout.close()

    writer = threading.Thread(target=feed, daemon=True)
    reader = threading.Thread(target=read, daemon=True)
    writer.start()
    reader.start()
    limit, late = time.monotonic() + seconds, False
    try:
        while process.poll() is None and not failed:
            if stop is not None and stop.is_set():
                break
            if time.monotonic() >= limit:
                late = True
                break
            if reader.is_alive():
                reader.join(TICK)
            else:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(TICK)
    finally:
        kill()
        reader.join(GRACE)   # a process that left the group may still hold the output
        over.set()
        writer.join(GRACE)
        _dismiss(watcher)
        process.wait()
    if failed:
        raise failed[0]
    return process.returncode, late
