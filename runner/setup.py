"""Setting this computer up for the runner: the workspace, the agent, the limits and how a
deck's previews are rendered.

What a caller needs to know
---------------------------
    setup.describe(engine)        the workspace, the default agent and the limits, as saved,
                                  with what this computer has for previews and for a brand
    setup.check(sent)             whether a repository or a folder can be used; changes nothing
    setup.save_brand(engine, sent)   the brand skill's repository, once it can be read
    wanted = setup.read(sent)     what the set-up screen sent, once it all makes sense
    setup.apply(engine, wanted)   set the workspace up, save the settings, and describe them

- A workspace is given as a repository's address or as a folder on this computer, never
  both. A repository is cloned into a copy of the runner's own; a folder is used as it is.
- `check` looks before anything is written: the place can be reached and written to, git
  knows who the person is, and the folder for trainings is not another tool's. It reads a
  repository through a shallow copy that it removes again, and asks the remote whether it
  would take a push without sending one.
- `found` says what the place already holds. When a Training Studio `hub.json` is there,
  its name, folder and branch are the ones that will be used, and nothing it says is asked
  for again.
- When to share is written `each-decision` or `when-asked` here; `gitstate` calls them
  `decision` and `asked`.
- `previews` is the person's choice between LibreOffice on this computer (`local`) and
  Google Drive (`drive`), with which of the two this computer can use (`drive` is None
  once LibreOffice is chosen: Drive is not asked then), and the preview files the runner
  has left in Drive. It never deletes one, so it lists them. `brand` is the brand skill
  that was found and the brands it has, with every brand skill found under `skills` as
  {'name', 'path', 'chosen'}; `brand_skill` names one of those paths to use. Both are
  asked of the engine, which looks at this computer and reuses the look, so asking for
  this again starts nothing while nothing has changed. `brand` also has `repository` and
  `release`: where the brand skill is installed from, as kept by `save_brand`.
- `save_brand(engine, {"repository", "release"})` keeps the brand skill's repository once
  `brand_source.check` can read it with this person's git access, and refuses in a sentence
  otherwise. An empty repository forgets it. A brand skill installed by hand is used
  either way.
- `notify` is {'on', 'can', 'problem'}: whether the runner tells the person through the
  computer's own notifications when no page is open, whether this computer has a way to,
  and a sentence when it has none. It is sent as true or false, and cannot be turned on
  where there is no way.
- `updates` is {'look'}: whether the runner looks online, at most once a day, for newer
  releases. It is sent as `look_for_updates`, true or false. `upkeep` is what the runner
  found when it last looked at Training Studio and its skills on this computer, or None
  where it does not look (see `upkeep.Upkeep.report`).
- `shared` is what the studios config every *-studio reads holds that Training Studio can
  use, in the file's own shape: `team` {repository, branch}, `assistant` {agent, model,
  effort}, `brand` {brand, variant}, `output` and `share`. A value that would be refused
  here is left out, and so is anything Training Studio does not use. `shared_problem` is a
  sentence when the file could not be read, which is then as if there were none. The page
  fills in its set-up and a new training from `shared`; this computer's own settings win.
- `"for_all_studios": true`, sent with the set-up, also writes into that file the shared
  values this save changed: the team repository and its branch, when to share, and the
  agent, its model and its level. A value is written only when it differs from what this
  computer had before and from what the file says; a model or level left to the agent is
  written as null. The set-up is saved first, and the answer gains `for_all_studios`,
  {"written": [the keys written, such as "team.repository"], "problem": a sentence or null},
  so a file that cannot be written never undoes the set-up. See `studios_config`.
"""
from __future__ import annotations

import os
import re
import secrets
import shutil
from dataclasses import replace
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
import hub
import workspace
from workspace import WorkspaceError

from runner import brand_source, gitstate, settings, studios_config

WHEN = {'decision': 'each-decision', 'asked': 'when-asked'}
SHARE = {said: kept for kept, said in WHEN.items()}
PROBE = 'training-studio-write-check'   # a branch name that is asked about, never made
NOBODY = ('-c', 'user.name=Training Studio', '-c', 'user.email=check@example.invalid')
PLACE = 2000    # characters in an address or a path
WORD = 100      # characters in a brand's or a variant's name
BRANCH = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$')   # a branch a file may name
OUTPUTS = ('google', 'pptx')    # what a studio makes by default, as the shared file says


def describe(engine) -> dict:
    """What is set up on this computer, in the shape the page reads."""
    space, chosen = engine.workspace, settings.load()
    found = None if space is None else {
        'name': space.name, 'repository': space.address, 'path': str(space.repo),
        'folder': space.folder, 'branch': space.branch, 'share_when': WHEN[space.share],
        **engine.shared()}
    needs = engine.deck_needs()
    can, problem = engine.notifier.can()
    values, unread = shared()
    return {'configured': space is not None, 'workspace': found,
            'shared': values, 'shared_problem': unread,
            'notify': {'on': chosen.notify, 'can': can, 'problem': problem},
            'updates': {'look': chosen.look_for_updates},
            'upkeep': keeping.report() if (keeping := getattr(engine, 'upkeep', None))
            else None,
            'agent': {'default': chosen.agent, 'model': chosen.model,
                      'effort': chosen.effort},
            'limits': chosen.limits,
            'previews': {'how': chosen.previews, 'drive': needs['drive'],
                         'local': needs['local'], 'left': engine.previews_left()},
            'brand': {**needs['brand'], 'skills': engine.brand_skills(),
                      'repository': chosen.brand_repository,
                      'release': chosen.brand_release}}


def save_brand(engine, sent: dict) -> dict:
    """Keep the brand skill's repository, and the release to install from it, once this
    person's own git access can read it and the release is one it has. An empty address
    forgets both. What the check found is kept for the versions, and the set-up described."""
    repository = _text(sent, 'repository')
    release = _text(sent, 'release')
    if repository is None and release is not None:
        raise WorkspaceError("A release is chosen from the brand skill's repository: give the "
                             'repository too.')
    kept = settings.load()
    if repository is None:
        settings.save(replace(kept, brand_repository=None, brand_release=None))
        return describe(engine)
    found = brand_source.check(repository, release, _anywhere())
    settings.save(replace(kept, brand_repository=found['repository'],
                          brand_release=found['release']))
    keeping = getattr(engine, 'upkeep', None)
    if keeping is not None:
        keeping.remember_brand(found['repository'], {entry['tag']: entry
                                                     for entry in found['releases']})
    return describe(engine)


# --- the studios config ------------------------------------------------------------------

def _group(found: dict, name: str) -> dict:
    value = found.get(name)
    return value if isinstance(value, dict) else {}


def _word(value, most: int = WORD) -> str | None:
    """A plain word from the file, or None for anything else."""
    if not isinstance(value, str) or not value.strip() or len(value) > most \
            or any(ord(mark) < 32 for mark in value):
        return None
    return value.strip()


def _passes(check, *args):
    """What a check of Settings makes of a value, or None where it refuses it."""
    try:
        return check(*args)
    except WorkspaceError:
        return None


def shared() -> tuple[dict, str | None]:
    """The studios config's values that Training Studio can use, in the file's own shape,
    and a sentence when the file could not be read. A value that would be refused here, such
    as an address that carries a password, is left out."""
    found, problem = studios_config.read()
    team, assistant, brand = (_group(found, name) for name in ('team', 'assistant', 'brand'))
    branch = _word(team.get('branch'), 200)
    named = assistant.get('agent')
    agent = None if named is None else _passes(settings.check_agent, named)
    # A model or a level named for an agent Training Studio does not have is not for it.
    usable = named is None or agent is not None
    model = _passes(settings.check_model, assistant.get('model')) if usable else None
    effort = _passes(settings.check_effort, assistant.get('effort'),
                     agent or settings.Settings().agent, model) if usable else None
    values = {
        'team': {'repository': _passes(settings.check_repository,
                                       _word(team.get('repository'), PLACE)),
                 'branch': branch if branch and BRANCH.match(branch) and '..' not in branch
                 and not branch.endswith(('/', '.', '.lock')) else None},
        'assistant': {'agent': agent, 'model': model, 'effort': effort},
        'brand': {'brand': _word(brand.get('brand')), 'variant': _word(brand.get('variant'))},
        'output': found.get('output') if found.get('output') in OUTPUTS else None,
        'share': found.get('share') if found.get('share') in gitstate.SHARE else None}
    kept = {}
    for key, value in values.items():
        if isinstance(value, dict):
            value = {name: inner for name, inner in value.items() if inner is not None}
        if value:
            kept[key] = value
    return kept, problem


MISSING = object()


def _values(space, chosen: settings.Settings | None) -> dict:
    """What this computer's set-up says of the values every studio may share."""
    said = {}
    if space is not None and space.address:
        said['team'] = {'repository': space.address, 'branch': space.branch}
        said['share'] = space.share
    if chosen is not None:
        said['assistant'] = {'agent': chosen.agent, 'model': chosen.model,
                             'effort': chosen.effort}
    return said


def _same(one, other) -> bool:
    return type(one) is type(other) and one == other


def share_all(before: dict, after: dict) -> dict:
    """Write into the studios config each shared value this save changed, where the file
    says otherwise. Answers {"written": [keys], "problem": a sentence or None}."""
    found, problem = studios_config.read()
    if problem:
        return {'written': [], 'problem': problem}
    changes, written = {}, []
    for key, value in after.items():
        was, held = before.get(key, MISSING), found.get(key)
        if not isinstance(value, dict):
            if not _same(value, was) and not _same(value, held):
                changes[key] = value
                written.append(key)
            continue
        was = was if isinstance(was, dict) else {}
        held = held if isinstance(held, dict) else {}
        for name, inner in value.items():
            if _same(inner, was.get(name, MISSING)) or _same(inner, held.get(name)):
                continue
            changes.setdefault(key, {})[name] = inner
            written.append(f'{key}.{name}')
    if changes:
        try:
            studios_config.update(changes)
        except WorkspaceError as refusal:
            return {'written': [], 'problem': str(refusal)}
    return {'written': written, 'problem': None}


# --- what was sent -----------------------------------------------------------------------

def _text(sent: dict, name: str) -> str | None:
    value = sent.get(name)
    if value is None or value == '':
        return None
    if not isinstance(value, str) or len(value) > PLACE or '\0' in value:
        raise WorkspaceError(f'Give the {name} as text.')
    return value.strip() or None


def place(sent: dict) -> tuple[str | None, str | None]:
    """The repository's address or the folder's path, whichever was given."""
    repository, path = _text(sent, 'repository'), _text(sent, 'path')
    if repository and path:
        raise WorkspaceError('Give the repository\'s address or a folder on this computer, '
                             'not both.')
    return repository, path


def whole(path: str) -> Path:
    """A folder's path, which must say where it is whatever folder the runner was started
    in."""
    folder = Path(path).expanduser()
    if not folder.is_absolute():
        raise WorkspaceError('Give the folder\'s whole path, starting from / or from ~.')
    return folder


def names(sent: dict) -> tuple[str | None, str | None]:
    """The folder and the branch that were asked for, when they were."""
    folder, branch = _text(sent, 'folder'), _text(sent, 'branch')
    if folder is not None:
        gitstate.check_name(folder, 'A workspace folder')
    if branch is not None and (branch.startswith('-') or not hub.passes(
            _anywhere(), 'check-ref-format', '--branch', branch)):
        raise WorkspaceError(f'"{branch}" cannot be the name of a branch.')
    return folder, branch


def _anywhere() -> Path:
    """A folder to run git in when no repository is involved yet."""
    base = gitstate.clones()
    base.mkdir(parents=True, exist_ok=True)
    return base


# --- looking before anything is written --------------------------------------------------

def _check(what: str, problem: str | None) -> dict:
    return {'what': what, 'ok': problem is None, 'fix': problem}


def _identity() -> str | None:
    """Why git cannot record anything for this person, or None when it can."""
    try:
        gitstate.identity(_anywhere())
    except WorkspaceError as refusal:
        return str(refusal)
    return None


def _marked(repo: Path, folder: str | None, branch: str | None, name: str,
            on: str) -> tuple[dict, str | None]:
    """What a repository's folder for trainings holds, and why it cannot be used if it
    cannot."""
    found = {'name': name, 'folder': folder or gitstate.FOLDER, 'branch': branch or on,
             'existing': False}
    try:
        where = gitstate.find_folder(repo, folder)
        marker = gitstate.marker(repo, where)
        gitstate.check_name(name, 'A workspace name')
    except WorkspaceError as refusal:
        return found, str(refusal)
    found['folder'] = where
    if marker is None:
        slot = repo / where
        if slot.is_symlink() or (slot.exists() and not slot.is_dir()):
            return found, (f'{where} in this repository is not a plain folder, so it cannot '
                           'hold trainings. Name a different folder.')
        return found, None
    found.update(name=marker['name'], branch=marker['branch'], existing=True)
    if branch is not None and branch != marker['branch']:
        return found, (f"{where}/{gitstate.MARKER} says this workspace's work is on the "
                       f"branch {marker['branch']}, not {branch}. Leave the branch out to "
                       'use it.')
    return found, None


def _remote(address: str, folder: str | None, branch: str | None) -> tuple[dict, list]:
    """Look at a repository by its address, through a shallow copy that is then removed."""
    name = hub.name_from(address)
    found = {'name': name, 'folder': folder or gitstate.FOLDER, 'branch': branch or 'main',
             'existing': False}
    reach, write, slot = 'The repository can be reached', 'The repository can be written to', \
        'The folder for trainings can be used'
    later = 'This is looked at once the repository can be reached.'
    if hub.ADDRESS_WITH_SECRET.match(address):
        return found, [_check(reach, 'That address carries a password or token. Give the '
                              'address without it; git signs in with your own credentials.'),
                       _check(write, later), _check(slot, later)]
    base = _anywhere()
    listed = hub.run(base, 'ls-remote', '--symref', '--', address, 'HEAD', 'refs/heads/*')
    if listed.returncode != 0:
        return found, [_check(reach, f'The repository could not be reached '
                              f'({hub.reason(listed)}). Check the address, and that git can '
                              'sign in to it without asking.'),
                       _check(write, later), _check(slot, later)]
    heads = {line.split('\t')[1].removeprefix('refs/heads/')
             for line in listed.stdout.splitlines()
             if '\t' in line and line.split('\t')[1].startswith('refs/heads/')}
    probe = base / f'.checking-{secrets.token_hex(4)}'
    try:
        wanted = ['--branch', branch] if branch in heads else []
        cloned = hub.run(base, 'clone', '--quiet', '--depth', '1', '--no-tags', *wanted,
                         *hub.COPY_AS_IS, '--', address, str(probe))
        if cloned.returncode != 0:
            return found, [_check(reach, f'The repository could not be read '
                                  f'({hub.reason(cloned)}).'),
                           _check(write, later), _check(slot, later)]
        found, unusable = _marked(probe, folder, branch, name, gitstate.on_branch(probe))
        return found, [_check(reach, None), _check(write, _unwritable(probe, address)),
                       _check(slot, unusable)]
    finally:
        shutil.rmtree(probe, ignore_errors=True)


def _unwritable(probe: Path, address: str) -> str | None:
    """Why this computer may not push to a repository, or None when the remote says it
    would take a push. Nothing is sent."""
    if Path(address).is_dir() and not os.access(address, os.W_OK):
        return ('This computer may read that repository but not write to it. Ask for write '
                'access, then check again.')
    if not hub.passes(probe, 'rev-parse', '--verify', '--quiet', 'HEAD'):
        hub.run(probe, *NOBODY, 'commit', '--quiet', '--allow-empty', '-m', 'check')
    sent = hub.run(probe, 'push', '--dry-run', '--quiet', 'origin',
                   f'HEAD:refs/heads/{PROBE}')
    if sent.returncode == 0:
        return None
    return (f'This computer may read the repository but not write to it ({hub.reason(sent)}). '
            'Ask for write access, or sign git in as someone who has it, then check again.')


def _local(path: str, folder: str | None, branch: str | None) -> tuple[dict, list]:
    """Look at a folder on this computer that is, or will be, a repository with no remote."""
    reach, write, slot = 'The folder can be reached', 'The folder can be written to', \
        'The folder for trainings can be used'
    repo = whole(path).resolve()
    name = hub.name_from(repo.name)
    found = {'name': name, 'folder': folder or gitstate.FOLDER, 'branch': branch or 'main',
             'existing': False}
    later = 'This is looked at once the folder can be reached.'
    skill, unreachable = workspace.SKILL_DIR, None
    if repo == skill or repo in skill.parents or skill in repo.parents:
        unreachable = (f'{repo} holds Training Studio itself. Choose a folder made for '
                       'trainings.')
    elif repo.exists() and not repo.is_dir():
        unreachable = f'{repo} is a file. Name a folder for the workspace.'
    elif (repo / '.git').exists() and hub.run(repo, 'remote').stdout.strip():
        unreachable = (f'{repo} is a copy of a shared repository that someone works in. '
                       "Give the repository's address instead: the runner keeps a copy "
                       'of its own, so it never changes yours.')
    if unreachable:
        return found, [_check(reach, unreachable), _check(write, later), _check(slot, later)]
    nearest = next(parent for parent in (repo, *repo.parents) if parent.exists())
    unwritable = None if os.access(nearest, os.W_OK | os.X_OK) else (
        f'{nearest} cannot be written to by you. Choose a folder that can.')
    on = gitstate.on_branch(repo) if (repo / '.git').exists() else _first_branch()
    found, unusable = _marked(repo, folder, branch, name, on)
    return found, [_check(reach, None), _check(write, unwritable), _check(slot, unusable)]


def _first_branch() -> str:
    """The branch git gives a repository it has just made on this computer."""
    probe = _anywhere() / f'.checking-{secrets.token_hex(4)}'
    try:
        probe.mkdir()
        hub.run(probe, 'init', '--quiet')
        return gitstate.on_branch(probe)
    except WorkspaceError:
        return 'main'
    finally:
        shutil.rmtree(probe, ignore_errors=True)


def check(sent: dict) -> dict:
    """Whether a repository or a folder can be the workspace. It changes nothing."""
    repository, path = place(sent)
    if not repository and not path:
        raise WorkspaceError('Give the repository\'s address, or a folder on this computer.')
    folder, branch = names(sent)
    found, checks = (_remote(repository, folder, branch) if repository
                     else _local(path, folder, branch))
    checks.insert(2, _check('git knows who you are', _identity()))
    return {'ok': all(item['ok'] for item in checks), 'found': found, 'checks': checks}


# --- setting it up -----------------------------------------------------------------------

def chosen(sent: dict) -> settings.Settings:
    """This computer's settings, with what was sent in place of what was saved."""
    kept = settings.load()
    limits = sent.get('limits')
    if limits is not None and not isinstance(limits, dict):
        raise WorkspaceError('Give the limits as step_seconds, training_dollars and parallel.')
    agent = sent.get('agent') or kept.agent
    same = agent == kept.agent
    model = sent['model'] if 'model' in sent else (kept.model if same else None)
    effort = sent['effort'] if 'effort' in sent else (kept.effort if same else None)
    wanted = {name: (limits or {}).get(name, getattr(kept, name))
              for name in ('step_seconds', 'training_dollars', 'parallel')}
    previews = sent['previews'] if sent.get('previews') is not None else kept.previews
    skill = sent['brand_skill'] if sent.get('brand_skill') is not None else kept.brand_skill
    notify = sent['notify'] if sent.get('notify') is not None else kept.notify
    look = sent['look_for_updates'] if sent.get('look_for_updates') is not None \
        else kept.look_for_updates
    return settings.check(replace(kept, agent=agent, model=model, effort=effort,
                                  previews=previews, brand_skill=skill, notify=notify,
                                  look_for_updates=look, **wanted))


def read(sent: dict) -> dict:
    """What the set-up screen sent, once every part of it makes sense. Refuses, with a
    sentence, before anything is changed."""
    repository, path = place(sent)
    if not repository and not path and gitstate.current() is None:
        raise WorkspaceError('Give the repository\'s address, or a folder on this computer.')
    folder, branch = names(sent)
    name, when = _text(sent, 'name'), sent.get('share_when')
    if name is not None:
        gitstate.check_name(name, 'A workspace name')
    if when is not None and when not in SHARE:
        raise WorkspaceError('Sharing is one of: ' + ', '.join(SHARE) + '.')
    every = sent.get('for_all_studios', False)
    if not isinstance(every, bool):
        raise WorkspaceError('Say whether this is for all your studios as true or false.')
    return {'repository': repository, 'path': whole(path) if path else None,
            'for_all_studios': every,
            'brand_skill': sent.get('brand_skill'),
            'folder': folder, 'branch': branch, 'name': name,
            'share': SHARE[when] if when else None, 'settings': chosen(sent)}


def apply(engine, wanted: dict) -> dict:
    """Set the workspace up, save this computer's settings, and describe both.

    Without a repository or a folder, the workspace stays as it is and only the settings
    and when to share change.
    """
    repository, path, share = wanted['repository'], wanted['path'], wanted['share']
    named = wanted.get('brand_skill')
    if named is not None and named not in [skill['path'] for skill in engine.brand_skills()]:
        raise WorkspaceError('Choose the brand skill from those found on this computer.')
    can, problem = engine.notifier.can()
    if wanted['settings'].notify and not can:
        raise WorkspaceError(problem)
    before = engine.workspace
    was = _values(before, settings.load() if settings.path().is_file() else None)
    if not repository and not path:
        if share:
            gitstate.share_when(share)
    else:
        moving = before is not None and (
            before.address != repository if repository
            else before.address is not None or before.repo != path.resolve())
        if moving and any((engine.brief(root) or {}).get('state') == 'working'
                          for root in engine.trainings()):
            raise WorkspaceError('Trainings are working in the workspace this computer uses '
                                 'now. Pause or stop them before moving to another.')
        with engine.files:
            if repository:
                gitstate.join(repository, wanted['folder'], wanted['branch'],
                              wanted['name'], share)
            else:
                gitstate.local(path, wanted['folder'], wanted['branch'], wanted['name'],
                               share)
    chosen = settings.save(wanted['settings'])
    engine.saved()
    engine.resume()
    if not wanted.get('for_all_studios'):
        return describe(engine)
    report = share_all(was, _values(gitstate.current(), chosen))
    return {**describe(engine), 'for_all_studios': report}
