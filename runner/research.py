"""The harness-research command line, called from Python.

What a caller needs to know
---------------------------
    research = Research()                     # finds the installed runtime, or refuses
    status = research.plan(training, training / '.training-studio' / 'research-plan.json')
    status = research.record(training, status['run'], 'instance-min', finding)
    status = research.status(training)

- Every call returns the command's own JSON: `run`, `status` (`not-started`,
  `in-progress`, `complete` or `stale`), `pending`, `unresolved`, `staleItems`,
  `completed`, `total`, `sourceGaps`, and where the record and the `report` are.
- A question with a finding of `insufficient` or `unavailable` counts as completed there.
  Whether that is enough is the caller's rule, not the command's.
- When the command says no, Refused is raised: a WorkspaceError that carries the one line
  it printed in `line`. `busy` is true when another save held its lock; record findings one
  at a time. A lock left by a process that died is cleared only by `unlock`, which is for a
  caller that knows nothing else can be saving: the engine, when the runner starts.
- `finding` is what worker_tools keeps for an accepted finding. Its `file` paths are read
  from the training's folder, so copy a job's sources into the training first.
- The runtime is the folder named by HARNESS_RESEARCH_RUNTIME when that is set, else the
  first usual install location that holds one. `Research(run=...)` replaces how the command
  is run. The tests' stand-in, in tests/stand_ins/research.py, behaves like the real command
  for plan, record and status and needs neither Node nor an installed skill.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
from workspace import WorkspaceError

from runner import companion

VARIABLE = 'HARNESS_RESEARCH_RUNTIME'
SCRIPT = Path('scripts') / 'harness-research.mjs'
LOCK = Path('.harness-research') / 'research.lock'
TIMEOUT = 120
BUSY = 'Research storage is busy'


class Refused(WorkspaceError):
    """harness-research said no. `line` is the one line it gave."""

    def __init__(self, line: str):
        super().__init__(f'harness-research refused: {line}')
        self.line = line

    @property
    def busy(self) -> bool:
        """True when another save was in progress, so trying again may work."""
        return self.line.startswith(BUSY)


def locations() -> list[Path]:
    """Where an installed harness-research may be. The override, when set, is the only
    place looked."""
    return companion.locations(VARIABLE, 'harness-research', 'Harness Research')


def find_runtime() -> Path:
    """The installed harness-research, with links followed so one version is used
    throughout. Refuses when there is none."""
    return companion.find_runtime(locations(), SCRIPT, VARIABLE, 'harness-research',
                                  'research cannot run')


def unlock(project: Path) -> bool:
    """Remove the lock a save left behind when its process died. True when there was one.
    Only for a caller that knows no save is in progress."""
    lock = Path(project) / LOCK
    found = lock.is_file()
    lock.unlink(missing_ok=True)
    return found


def run_command(command: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """Run the command line once: (exit code, standard output, standard error)."""
    return companion.run_command(command, cwd, TIMEOUT, 'harness-research')


class Research:
    """The plan, record and status commands of one installed harness-research."""

    def __init__(self, runtime: Path | None = None, run=None):
        self.run = run or run_command
        self.runtime = Path(runtime) if runtime else find_runtime()
        self.node = 'node' if run else shutil.which('node')
        if self.node is None:
            raise WorkspaceError('harness-research needs Node.js 20 or newer, which was not '
                                 'found on this computer. Install it, then try again.')

    def _call(self, *args: str) -> str:
        code, out, err = self.run([self.node, str(self.runtime / SCRIPT), *args])
        if code != 0:
            lines = [line.strip() for line in err.splitlines() if line.strip()]
            raise Refused(lines[-1] if lines else f'it ended with exit code {code}')
        return out

    def _json(self, *args: str) -> dict:
        try:
            found = json.loads(self._call(*args))
        except ValueError:
            found = None
        if not isinstance(found, dict):
            raise WorkspaceError('harness-research answered with something other than the '
                                 'JSON it should. Check that it is installed whole.')
        return found

    def version(self) -> str:
        """The runtime's version, as it states it."""
        return self._call('--version').strip().rpartition(' ')[2]

    def plan(self, project: Path, file: Path, allow_web: bool = False) -> dict:
        """Hand over an approved plan. The same plan again continues its run; a changed
        one starts a new run with no results. `allow_web` permits a plan that widens
        supplied-only research to the public web."""
        extra = ['--allow-web'] if allow_web else []
        return self._json('plan', '--project', str(project), '--file', str(file), *extra)

    def record(self, project: Path, run: str, item: str, finding: dict) -> dict:
        """Record one question's finding in a run."""
        wanted = {key: finding.get(key) for key in ('status', 'summary', 'limits', 'evidence')}
        handle, name = tempfile.mkstemp(suffix='.json', prefix='finding-')
        try:
            with os.fdopen(handle, 'w', encoding='utf-8') as stream:
                json.dump(wanted, stream)
            return self._json('record', '--project', str(project), '--file', name,
                              '--run', run, '--item', item)
        finally:
            Path(name).unlink(missing_ok=True)

    def status(self, project: Path) -> dict:
        """Where the research stands. The command rewrites its report when asked."""
        return self._json('status', '--project', str(project))
