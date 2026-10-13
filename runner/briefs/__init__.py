"""What a worker is told for each kind of job.

What a caller needs to know
---------------------------
    briefs.guidance('research-plan')            drafting the research questions
    briefs.guidance('research-question')        researching one question
    briefs.guidance('blueprint')                drafting a blueprint for a plain training
    briefs.guidance('blueprint', level='301')   drafting one level's blueprint

- A brief says how to do a kind of job. It is the same for every training, so it goes to
  an agent as guidance. What one job is about goes in the task: the topic, the audience
  and purpose, the name to hand a draft back under, the question and its ID, the names of
  the inputs, and on a second attempt what went wrong or what the person asked for.
- A brief names only the worker tools. It never names a helper command or a file,
  because a worker has neither. Each one ends with how to hand back and when to stop.
- The blueprint brief ends with the core's own example blueprint, so the format is
  written down in one place.
"""
from __future__ import annotations

from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
import workspace
from workspace import WorkspaceError

HERE = Path(__file__).resolve().parent
JOBS = ('research-plan', 'research-question', 'blueprint')
EXAMPLE = Path('assets') / 'examples' / 'blueprint.md'
EXAMPLE_NOTE = ('## The example\n\nThis shows the shape to follow. Its subject is not '
                'yours: take nothing from it but the shape.\n\n```markdown\n{example}```\n')


def read(name: str) -> str:
    return (HERE / f'{name}.md').read_text(encoding='utf-8')


def guidance(job: str, level: str | None = None) -> str:
    """The guidance for one kind of job, whole."""
    if job not in JOBS:
        raise WorkspaceError('There is a brief for: ' + ', '.join(JOBS) + '.')
    if level is not None and (job != 'blueprint' or level not in workspace.LEVELS):
        raise WorkspaceError('Only a blueprint is written for a level, and the level is one '
                             'of: ' + ', '.join(workspace.LEVELS) + '.')
    text = read(job)
    if job != 'blueprint':
        return text
    if level is not None:
        text += '\n' + read('blueprint-level').replace('{level}', level)
    example = (workspace.GUIDANCE_DIR / EXAMPLE).read_text(encoding='utf-8')
    return text + '\n' + EXAMPLE_NOTE.replace('{example}', example.rstrip('\n') + '\n')
