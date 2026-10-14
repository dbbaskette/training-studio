"""What this computer remembers for the runner: the agent to use by default, the limits, and
how a deck's previews are rendered.

What a caller needs to know
---------------------------
    chosen = settings.load()                      # the defaults when nothing is saved
    settings.save(replace(chosen, agent='codex', training_dollars=10))

- Kept in the per-user data folder as `runner.json`, beside the workspace `gitstate`
  remembers there. Nothing here is written into the repository: two people who share a
  workspace can use different agents and different limits.
- `step_seconds` is how long one worker may run. `training_dollars` is what one training
  may spend, where the agent reports spending, before it stops and asks. `parallel` is how
  many trainings work at once.
- `previews` is how a deck's slides are rendered to look at: `local`, with LibreOffice on
  this computer, or `drive`, through Google Drive. None until the person chooses.
- `brand_skill` is where the brand skill to use is, when the person named one of those
  found. None for the first that is found.
- `notify` is whether the runner tells the person, through the computer's own
  notifications, that a training needs a decision while no page is open. Off until they
  turn it on.
- A value that makes no sense is refused with a sentence, not corrected silently.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import runner  # noqa: F401  puts the core on the import path
import home
from workspace import WorkspaceError

SCHEMA = 1
AGENTS = ('claude', 'codex')
SECONDS = (60, 7200)        # the shortest and longest time one worker may be given
DOLLARS = 1000              # the most one training may be allowed to spend
PARALLEL = (1, 8)           # the fewest and most trainings that work at once
MODEL = 100                 # characters in a model's name
PREVIEWS = ('drive', 'local')   # how a deck's previews are rendered


@dataclass(frozen=True)
class Settings:
    """This computer's choices for the runner."""
    agent: str = 'claude'
    model: str | None = None
    step_seconds: int = 900
    training_dollars: float = 20.0
    parallel: int = 2
    previews: str | None = None
    brand_skill: str | None = None
    notify: bool = False

    @property
    def limits(self) -> dict:
        return {'step_seconds': self.step_seconds, 'training_dollars': self.training_dollars,
                'parallel': self.parallel}


def path():
    return home.data_root() / 'runner.json'


def check_agent(agent) -> str:
    if agent not in AGENTS:
        raise WorkspaceError('The agent is one of: ' + ', '.join(AGENTS) + '.')
    return agent


def check_model(model) -> str | None:
    """A model's name as an agent takes it, or None for the agent's own default."""
    if model is None or model == '':
        return None
    if not isinstance(model, str) or len(model) > MODEL or not model.strip() \
            or model.startswith('-') or any(mark.isspace() for mark in model):
        raise WorkspaceError('The model is the short name the agent knows it by, with no '
                             'spaces, or nothing for the agent\'s own choice.')
    return model


def check_previews(how) -> str | None:
    if how is not None and how not in PREVIEWS:
        raise WorkspaceError('Previews are rendered one of these ways: '
                             + ', '.join(PREVIEWS) + '.')
    return how


def check_place(place) -> str | None:
    if place is not None and (not isinstance(place, str) or not place.strip()
                              or len(place) > 2000 or '\0' in place):
        raise WorkspaceError('Give the brand skill as one of those found on this computer.')
    return place


def check_notify(wanted) -> bool:
    if not isinstance(wanted, bool):
        raise WorkspaceError('Notifications are on or off: give notify as true or false.')
    return wanted


def number(value, label: str, least: float, most: float, whole: bool):
    """A limit a person typed, which must be a number in a sensible range."""
    plain = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not plain or (whole and int(value) != value) or not least <= value <= most:
        kind = 'a whole number' if whole else 'a number'
        raise WorkspaceError(f'{label} is {kind} from {least:g} to {most:g}.')
    return int(value) if whole else float(value)


def check(chosen: Settings) -> Settings:
    """The same settings, once every one of them makes sense."""
    return Settings(
        check_agent(chosen.agent), check_model(chosen.model),
        number(chosen.step_seconds, 'The time for one step, in seconds,', *SECONDS, True),
        number(chosen.training_dollars, 'What a training may spend, in dollars,', 0.01,
               DOLLARS, False),
        number(chosen.parallel, 'How many trainings run at once', *PARALLEL, True),
        check_previews(chosen.previews), check_place(chosen.brand_skill),
        check_notify(chosen.notify))


def load() -> Settings:
    """What is saved on this computer. Anything missing or unusable is the default."""
    kept = home.read_json(path(), None)
    if not isinstance(kept, dict) or kept.get('schema') != SCHEMA:
        return Settings()
    known = {name: kept[name] for name in asdict(Settings()) if name in kept}
    try:
        return check(Settings(**known))
    except WorkspaceError:
        return Settings()


def save(chosen: Settings) -> Settings:
    """Remember these settings on this computer."""
    chosen = check(chosen)
    home.write_json(path(), {'schema': SCHEMA, **asdict(chosen)})
    return chosen
