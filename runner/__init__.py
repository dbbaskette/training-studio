"""The Studio Runner's foundations: confined workers, their tools, state in git, research.

    agents         start Claude or Codex as a worker for one job, or script one for tests
    worker_tools   the only tools a worker has, and the server that offers them to an agent
    gitstate       the workspace: one folder inside a git repository, committed and shared
    research       the harness-research command line, called from Python
    briefs         what a worker is told for each kind of job

Each module's own docstring says what a caller needs to know. Refusals meant for a person
are raised as the core's WorkspaceError, with a sentence to show as it is.

Importing this package puts the helper's own modules (the core, in
skills/training-studio/scripts) on the import path, so `import workspace`, `import checks`
and `import home` work anywhere in the runner.
"""
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / 'skills' / 'training-studio' / 'scripts'
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))
