"""What a worker is told for each kind of job.

What a caller needs to know
---------------------------
    briefs.guidance('research-plan')            drafting the research questions
    briefs.guidance('research-question')        researching one question
    briefs.guidance('blueprint')                drafting a blueprint for a plain training
    briefs.guidance('blueprint', level='301')   drafting one level's blueprint
    briefs.guidance('document', level='301')    writing a learner guide, here one level's
    briefs.guidance('brief', kind='product')    writing a brief of one kind
    briefs.guidance('scenario')                 drafting a practice scenario
    briefs.guidance('yoodli')                   laying a scenario out in Yoodli's fields
    briefs.guidance('deck-outline')             writing what a slide deck says
    briefs.guidance('deck-section')             drawing one section of a deck
    briefs.guidance('deck-section', repair=True)   drawing it again after a review
    briefs.guidance('deck-review')              reviewing a deck someone else drew
    briefs.guidance('document', naming=True)    for a training with a brand: with its names
    briefs.mode('roleplay')                     the core's own reference for one mode

- A brief says how to do a kind of job. It is the same for every training, so it goes to
  an agent as guidance. What one job is about goes in the task: the topic, the audience
  and purpose, the name to hand a draft back under, the question and its ID, the names of
  the inputs, and on a second attempt what went wrong or what the person asked for.
- A brief names only the worker tools. It never names a helper command or a file,
  because a worker has neither. Each one ends with how to hand back and when to stop.
- A brief for a draft ends with the core's own example of it, so the format is written
  down in one place. A brief's example is of its own kind.
- A blueprint, a guide and a brief can be written for a level, and then say what a level
  asks of them.
- A scenario's mode is not part of its brief. The mode's reference is the core's own, and
  goes to the worker as one of the job's inputs.
- A deck's briefs have no example. The format of an outline and of a section is the slides
  tool's own, and goes to the worker as an input, with the brand's limits in it.
- The writers of a guide, a brief and a scenario are told, when the training has a brand,
  that one of their inputs says how the organisation and its products are named, and that
  names are all it governs. What is added to a brief goes in before how to hand back.
"""
from __future__ import annotations

from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
import checks
import workspace
from workspace import WorkspaceError

HERE = Path(__file__).resolve().parent
JOBS = ('research-plan', 'research-question', 'blueprint', 'document', 'brief', 'scenario',
        'yoodli', 'deck-outline', 'deck-section', 'deck-review')
NAMED = ('document', 'brief', 'scenario')   # the writers a brand's naming rules are given to
HAND_BACK = '\n## Hand back\n'
EXAMPLES = Path('assets') / 'examples'
EXAMPLE = {'blueprint': 'blueprint.md', 'document': 'document.md', 'brief': '{kind}-brief.md',
           'scenario': 'scenario.md', 'yoodli': 'yoodli.md'}
LEVELLED = {'blueprint': 'blueprint-level', 'document': 'level', 'brief': 'level'}
MODES = Path('references') / 'modes'
EXAMPLE_NOTE = ('## The example\n\nThis shows the shape to follow. Its subject is not '
                'yours: take nothing from it but the shape.\n\n```markdown\n{example}```\n')


def read(name: str) -> str:
    return (HERE / f'{name}.md').read_text(encoding='utf-8')


def mode(name: str) -> str:
    """The core's reference for one practice mode, whole."""
    if name not in checks.MODES:
        raise WorkspaceError('A practice mode is one of: ' + ', '.join(checks.MODES) + '.')
    return (workspace.GUIDANCE_DIR / MODES / f'{name}.md').read_text(encoding='utf-8')


def guidance(job: str, level: str | None = None, kind: str | None = None,
             naming: bool = False, repair: bool = False) -> str:
    """The guidance for one kind of job, whole. `naming` says the job has the brand's
    naming rules among its inputs, and `repair` that a section is drawn again."""
    if job not in JOBS:
        raise WorkspaceError('There is a brief for: ' + ', '.join(JOBS) + '.')
    if level is not None and (job not in LEVELLED or level not in workspace.LEVELS):
        raise WorkspaceError('Only a blueprint, a guide and a brief are written for a level, '
                             'and the level is one of: ' + ', '.join(workspace.LEVELS) + '.')
    if (kind is not None) != (job == 'brief') or kind not in (None, *workspace.BRIEF_KINDS):
        raise WorkspaceError('A brief, and nothing else, is written as one of these kinds: '
                             + ', '.join(workspace.BRIEF_KINDS) + '.')
    if (naming and job not in NAMED) or (repair and job != 'deck-section'):
        raise WorkspaceError('Naming rules are given to the writers of a guide, a brief and '
                             'a scenario, and only a section of a deck is drawn again.')
    text = read(job)
    for added in (['naming'] if naming else []) + (['deck-repair'] if repair else []):
        text = text.replace(HAND_BACK, f'\n{read(added)}{HAND_BACK}', 1)
    if level is not None:
        text += '\n' + read(LEVELLED[job]).replace('{level}', level)
    if job not in EXAMPLE:
        return text
    name = EXAMPLE[job].replace('{kind}', kind or '')
    example = (workspace.GUIDANCE_DIR / EXAMPLES / name).read_text(encoding='utf-8')
    return text + '\n' + EXAMPLE_NOTE.replace('{example}', example.rstrip('\n') + '\n')
