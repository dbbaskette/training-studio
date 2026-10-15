"""What the runner is set to: the agent to use by default, the limits, how a deck's previews
are rendered, and where the brand skill is installed from.

What a caller needs to know
---------------------------
    chosen = settings.load()                      # the defaults when nothing is saved
    settings.save(replace(chosen, agent='codex', training_dollars=10))

- Two places hold them. The values every studio on this computer shares are kept only in
  the studios config (`studios_config`), and read from it each time: the agent, its model
  and its level (`assistant.agent`, `.model`, `.effort`) and the brand skill's repository and
  release (`brand.repository`, `.release`). SHARED names them. A value there that would be
  refused here is the default, and so is every one of them while the file cannot be read.
  The rest belong to Training Studio on this computer alone, and are kept in the per-user
  data folder as `runner.json`, beside the workspace `gitstate` remembers there. Nothing
  here is written into the repository: two people who share a workspace can use different
  agents and different limits.
- `save` writes into the studios config only the shared values that differ from what
  `load` reads there now, then `runner.json`. Where a shared value changed and the file
  cannot be read or written, it refuses before anything is kept, and the file is left as it
  is. A value in the file that Training Studio cannot use is never written over by a save
  that did not change it.
- An agent and its model and level are written as one, and so are the brand skill's
  repository and its release: where a save writes a model or a level and the file names
  another agent than the one saved, the agent, its model and its level are all written, as
  the form showed them. A model is never left beside another studio's agent. `writes` says
  what a save would write, from what the file holds, and refuses as `save` would; set-up
  asks it before it changes anything else.
- `own()` is what `runner.json` still holds of the shared values from before they were
  shared, and `forget_own()` takes them out of it. See `setup.migrate`.
- `model` is the model the agent is asked for and `effort` how hard it reasons, its
  reasoning level; None for each is the agent's own choice. A level is one of the words an
  agent takes (EFFORTS): which of them a model takes is what the agent lists. Claude Code
  lists nothing, so its models and their levels are kept in `claude-code-models.json`
  beside this file, and a level its model does not take is refused (`takes`).
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
- `look_for_updates` is whether the runner asks, at most once a day, which releases of
  Training Studio, its companion skills and the brand skill exist. On until they turn it
  off. See `upkeep`.
- `brand_repository` is the address of the brand skill's own repository, https, ssh or a
  folder, from which the page installs and upgrades it; None until the person names one.
  `brand_release` is the release tag to install from it, None for the newest. Neither is
  needed to use a brand skill installed by hand. Whether the repository can be reached is
  `brand_source`'s to say; here only its shape is checked.
- A value that makes no sense is refused with a sentence, not corrected silently.
"""
from __future__ import annotations

import functools
import json
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
import home
import hub
from workspace import WorkspaceError

from runner import studios_config

SCHEMA = 1
AGENTS = ('claude', 'codex')
SECONDS = (60, 7200)        # the shortest and longest time one worker may be given
DOLLARS = 1000              # the most one training may be allowed to spend
PARALLEL = (1, 8)           # the fewest and most trainings that work at once
MODEL = 100                 # characters in a model's name
# The reasoning levels each agent takes: Claude Code's `--effort`, and the words Codex's
# catalog and its service use.
LEVELS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra')
EFFORTS = {'claude': ('low', 'medium', 'high', 'xhigh', 'max'), 'codex': LEVELS}
# Claude Code has no list of its models, so the runner keeps one, with its source and date.
CLAUDE_MODELS = Path(__file__).resolve().with_name('claude-code-models.json')
PREVIEWS = ('drive', 'local')   # how a deck's previews are rendered
ADDRESS = 2000                  # characters in a repository's address
RELEASE = re.compile(r'^[\w][\w.+-]{0,99}$')   # a release tag's name, as git takes it
# The settings every studio shares, each with where the studios config keeps it.
SHARED = {'agent': ('assistant', 'agent'), 'model': ('assistant', 'model'),
          'effort': ('assistant', 'effort'), 'brand_repository': ('brand', 'repository'),
          'brand_release': ('brand', 'release')}


@dataclass(frozen=True)
class Settings:
    """This computer's choices for the runner."""
    agent: str = 'claude'
    model: str | None = None
    effort: str | None = None
    step_seconds: int = 900
    training_dollars: float = 20.0
    parallel: int = 2
    previews: str | None = None
    brand_skill: str | None = None
    notify: bool = False
    look_for_updates: bool = True
    brand_repository: str | None = None
    brand_release: str | None = None

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


def check_effort(effort, agent: str | None = None, model: str | None = None) -> str | None:
    """A reasoning level the agent and its model take, or None for the agent's own. With
    no agent, any level one of them takes."""
    if effort is None or effort == '':
        return None
    known = takes(agent, model)
    if not isinstance(effort, str) or effort not in known:
        named = claude_models()['named'].get(model) if agent == 'claude' else None
        if named and not known:
            raise WorkspaceError(f'{named} takes no reasoning level: leave it to the agent.')
        raise WorkspaceError((f'{named} takes one of these reasoning levels: ' if named
                              else 'The reasoning level is one of: ') + ', '.join(known)
                             + ', or nothing for the agent\'s own choice.')
    return effort


def takes(agent: str | None, model: str | None = None) -> tuple:
    """The reasoning levels a model takes: those the list of Claude Code's models gives
    it, or for a model that is not listed, every level its agent takes."""
    if agent == 'claude' and model:
        for listed in claude_models()['models']:
            if listed['name'] == model:
                return tuple(listed['levels'])
    return EFFORTS.get(agent, LEVELS)


@functools.lru_cache(maxsize=None)
def claude_models() -> dict:
    """Claude Code's models, read once from the file beside this one. See read_models."""
    return read_models(CLAUDE_MODELS)


def read_models(path: Path) -> dict:
    """A list of Claude Code's models: {'source', 'date', 'models', 'named'}. Each model is
    {'name', 'label', 'family', 'about', 'levels', 'default_level'}, in the file's order,
    and `named` gives each model's short name ("Opus 4.6") by its ID. An alias takes its
    label and its levels from the model it names. A list that is not whole is refused."""
    try:
        kept = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise WorkspaceError(f'The list of Claude Code\'s models in {path} cannot be read.')
    entries = kept.get('models') if isinstance(kept, dict) else None
    if not isinstance(entries, list):
        raise WorkspaceError(f'{path} has no list of models.')
    found: dict[str, dict] = {}
    for entry in entries:
        entry = entry if isinstance(entry, dict) else {}
        name = entry.get('id')
        try:
            check_model(name)
        except WorkspaceError:
            name = None
        if not name:
            raise WorkspaceError(f'{entry.get("id")} is not a model\'s name, in {path}.')
        if name in found:
            raise WorkspaceError(f'{name} is listed twice, in {path}.')
        for part in ('family',) if 'alias' in entry else ('family', 'label'):
            if not isinstance(entry.get(part), str) or not entry[part].strip():
                raise WorkspaceError(f'{name} has no {part}, in {path}.')
        levels = entry.get('levels', [])
        if 'alias' not in entry and (not isinstance(levels, list) or any(
                level not in EFFORTS['claude'] for level in levels)):
            raise WorkspaceError(f'{name} takes a level Claude Code does not, in {path}.')
        found[name] = entry
    models, named = [], {}
    for name, entry in found.items():
        meant = found.get(entry.get('alias')) if 'alias' in entry else entry
        if meant is None or 'alias' in meant:
            raise WorkspaceError(f'{name} names {entry.get("alias")}, which is not a version '
                                 f'listed in {path}.')
        named[name] = meant['label']
        label = (f'{entry["family"]}, always the newest (now {meant["label"]})'
                 if meant is not entry else f'{entry["label"]} ({name})')
        models.append({'name': name, 'label': label, 'family': entry['family'],
                       'about': None, 'levels': list(meant['levels']), 'default_level': None})
    return {'source': kept.get('source'), 'date': kept.get('date'), 'models': models,
            'named': named}


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


def check_look(wanted) -> bool:
    if not isinstance(wanted, bool):
        raise WorkspaceError('Looking for updates is on or off: give look_for_updates as true '
                             'or false.')
    return wanted


def check_repository(address) -> str | None:
    """The brand skill's repository as an address git takes, or None for none."""
    if address is None or address == '':
        return None
    if not isinstance(address, str) or not address.strip() or len(address) > ADDRESS \
            or any(mark.isspace() or ord(mark) < 32 for mark in address.strip()) \
            or address.strip().startswith('-'):
        raise WorkspaceError("Give the brand skill's repository as one address, such as "
                             'https://github.com/your-org/your-brand.git.')
    if hub.ADDRESS_WITH_SECRET.match(address.strip()):
        raise WorkspaceError('That address carries a password or token. Give the address '
                             'without it; git signs in with your own credentials.')
    return address.strip()


def check_release(release, repository: str | None = None) -> str | None:
    """A release tag's name, or None for the newest. A release needs a repository."""
    if release is None or release == '':
        return None
    if not isinstance(release, str) or not RELEASE.match(release) or '..' in release:
        raise WorkspaceError('Give the release as its tag, such as v1.4.0, or nothing for '
                             'the newest.')
    if repository is None:
        raise WorkspaceError("A release is chosen from the brand skill's repository: give "
                             'the repository too.')
    return release


def number(value, label: str, least: float, most: float, whole: bool):
    """A limit a person typed, which must be a number in a sensible range."""
    plain = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not plain or (whole and int(value) != value) or not least <= value <= most:
        kind = 'a whole number' if whole else 'a number'
        raise WorkspaceError(f'{label} is {kind} from {least:g} to {most:g}.')
    return int(value) if whole else float(value)


def check(chosen: Settings) -> Settings:
    """The same settings, once every one of them makes sense."""
    agent = check_agent(chosen.agent)
    repository = check_repository(chosen.brand_repository)
    return Settings(
        agent=agent, model=check_model(chosen.model),
        effort=check_effort(chosen.effort, agent, chosen.model),
        step_seconds=number(chosen.step_seconds, 'The time for one step, in seconds,',
                            *SECONDS, True),
        training_dollars=number(chosen.training_dollars,
                                'What a training may spend, in dollars,', 0.01, DOLLARS, False),
        parallel=number(chosen.parallel, 'How many trainings run at once', *PARALLEL, True),
        previews=check_previews(chosen.previews), brand_skill=check_place(chosen.brand_skill),
        notify=check_notify(chosen.notify),
        look_for_updates=check_look(chosen.look_for_updates),
        brand_repository=repository,
        brand_release=check_release(chosen.brand_release, repository))


def passes(check, *args):
    """What a check makes of a value, or None where it refuses it."""
    try:
        return check(*args)
    except WorkspaceError:
        return None


def from_shared(found: dict) -> dict:
    """The shared settings the studios config holds, by name, each as Training Studio can
    use it and None where it cannot. A model or a level named for an agent Training Studio
    does not have is not for it."""
    assistant, brand = (found.get(name) if isinstance(found.get(name), dict) else {}
                        for name in ('assistant', 'brand'))
    named = assistant.get('agent')
    agent = None if named is None else passes(check_agent, named)
    usable = named is None or agent is not None
    model = passes(check_model, assistant.get('model')) if usable else None
    effort = passes(check_effort, assistant.get('effort'), agent or Settings().agent,
                     model) if usable else None
    repository = brand.get('repository')
    repository = passes(check_repository, repository) if isinstance(repository, str) else None
    release = brand.get('release')
    release = passes(check_release, release, repository) \
        if isinstance(release, str) and repository else None
    return {'agent': agent, 'model': model, 'effort': effort,
            'brand_repository': repository, 'brand_release': release}


def _kept() -> dict:
    """What runner.json holds, or nothing when it cannot be used."""
    kept = home.read_json(path(), None)
    return kept if isinstance(kept, dict) and kept.get('schema') == SCHEMA else {}


def load() -> Settings:
    """The settings now: the shared ones from the studios config, the rest from this
    computer. Anything missing or unusable is the default."""
    kept = _kept()
    known = {name: kept[name] for name in asdict(Settings())
             if name in kept and name not in SHARED}
    try:
        mine = check(Settings(**known))
    except WorkspaceError:
        mine = Settings()
    return replace(mine, **shared_now(studios_config.read()[0]))


def shared_now(found: dict) -> dict:
    """The shared settings as Training Studio uses them, from what the studios config holds:
    those it can use, and the default for the rest."""
    shared = from_shared(found)
    return {**shared, 'agent': shared['agent'] or Settings().agent}


def seen(found: dict) -> Settings:
    """The settings a form was shown, from the shared values it was given, in the shape of
    the studios config. Only the shared ones mean anything."""
    return replace(Settings(), **shared_now(found if isinstance(found, dict) else {}))


def _same(one, other) -> bool:
    return type(one) is type(other) and one == other


def changes(before: Settings, after: Settings) -> dict:
    """The shared settings `after` changes from `before`, shaped as the studios config is."""
    found = {}
    for name, (group, key) in SHARED.items():
        if not _same(getattr(before, name), getattr(after, name)):
            found.setdefault(group, {})[key] = getattr(after, name)
    return found


# The shared settings that belong to another, which they are written beside.
OWNS = {'agent': ('model', 'effort'), 'brand_repository': ('brand_release',)}
# Each shared setting as a sentence names it.
NAMED = {'agent': 'The agent', 'model': 'The model', 'effort': 'The reasoning level',
         'brand_repository': "The brand skill's repository",
         'brand_release': "The brand skill's release"}
STALE = ('{} was changed in another studio while this was open, so nothing was saved. Look '
         'again, then save.')


def writes(chosen: Settings, before: Settings, found: dict) -> dict:
    """What saving `chosen` writes into the studios config while it holds `found`, shaped
    as the file is, when the form was shown `before`: each shared setting the person
    changed, with the agent beside its model and level, and the repository beside its
    release, where the file names another. Refuses, in a sentence, a change to a value
    another studio changed too."""
    changed = changes(before, chosen)
    for owner, owned in OWNS.items():
        group, key = SHARED[owner]
        held = found.get(group) if isinstance(found.get(group), dict) else {}
        if changed.get(group) and held.get(key) is not None \
                and not _same(held[key], getattr(chosen, owner)):
            for name in (owner, *owned):
                value = getattr(chosen, name)
                if value is not None or SHARED[name][1] in held:
                    changed[group][SHARED[name][1]] = value
    now = shared_now(found)
    for name, (group, key) in SHARED.items():
        if key in changed.get(group, {}) and not _same(now[name], getattr(before, name)) \
                and not _same(now[name], getattr(chosen, name)):
            raise WorkspaceError(STALE.format(NAMED[name]))
    return changed


def save(chosen: Settings, shown: Settings | None = None) -> Settings:
    """Keep these settings: each shared one that changed in the studios config, the rest on
    this computer. A shared one that cannot be written is refused before anything is kept.

    `shown` is what the form that sent them was shown, where it says. Then only what the
    person changed from that is written, so a value another studio changed meanwhile is
    kept, and a change to a value that another studio changed too is refused. What is
    written is worked out from the file under its lock (see `writes`)."""
    chosen = check(chosen)
    before = shown if shown is not None else load()
    if changes(before, chosen):
        studios_config.update(lambda found: writes(chosen, before, found))
    home.write_json(path(), {'schema': SCHEMA, **{
        name: value for name, value in asdict(chosen).items() if name not in SHARED}})
    return chosen


def own() -> dict:
    """The shared settings runner.json still holds from before they were shared, by name,
    each that can be used. Nothing when it holds none."""
    kept = _kept()
    found = from_shared({
        'assistant': {'agent': kept.get('agent'), 'model': kept.get('model'),
                      'effort': kept.get('effort')},
        'brand': {'repository': kept.get('brand_repository'),
                  'release': kept.get('brand_release')}})
    return {name: value for name, value in found.items() if value is not None}


def forget_own() -> None:
    """Take the shared settings out of runner.json, and leave the rest as it is."""
    kept = _kept()
    if any(name in kept for name in SHARED):
        home.write_json(path(), {name: value for name, value in kept.items()
                                 if name not in SHARED})
