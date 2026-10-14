"""The Studio Runner: a program that takes a training from a form to its index, stopping
at every gate for a decision on the page, the slide deck included.

    studio         the command line: `studio serve` and `studio status`
    page           the runner's server: the desk's page, with the runner behind it
    setup          this computer's set-up: the workspace, the agent and the limits
    engine         walks each training's pipeline, hands jobs to workers, stops at gates
    pipeline       the training and research pipelines, and where a training is in them
    settings       what this computer remembers: the default agent and the limits
    agents         start Claude or Codex as a worker for one job, or script one for tests
    worker_tools   the only tools a worker has, and the server that offers them to an agent
    gitstate       the workspace: one folder inside a git repository, committed and shared
    research       the harness-research command line, called from Python
    briefs         what a worker is told for each kind of job
    documents      the documents a person supplies for a training's research
    copies         the Google Docs and Word files a training asked for
    index          readiness, and README.md written from a training's record
    deck           the runner's own rules for a slide deck, and what its workers are told
    slides         the slides tool's command line, called from Python
    brand          a brand skill on this computer, called from Python

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
