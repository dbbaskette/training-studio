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
- The values every studio shares are kept only in the studios config (`studios_config`),
  and saving one here writes it there: the agent, its model and its level and the brand
  skill's repository and release (see `settings`), when to share for a team workspace, and
  the team repository when set-up joins another one, with its branch where the file names
  no branch for that repository. A folder on this computer writes no `team` and no `share`.
  While the file cannot be read, a save that would change one of them is refused before
  anything changes, and one that changes none goes through. Every write that depends on
  what the file holds is worked out from it under the lock every studio takes to write it,
  so a value another studio writes meanwhile is kept, or the save is refused.
- `shared_seen`, sent with the set-up or with the brand skill's repository, is the `shared`
  the page's form was shown. Then only what the person changed from it is written: a value
  another studio changed while the form was open is kept, and a change to a value another
  studio changed too is refused, in a sentence, before anything changes: before the
  workspace is joined or moved, and before anything is written. Without it, a value is
  written where it differs from what the file holds now.
- `shared` is what the file holds that Training Studio can use, in the file's own shape:
  `team` {repository, branch}, `assistant` {agent, model, effort}, `brand` {repository,
  release, brand, variant}, `output` and `share`. A value that would be refused here is
  left out, and so is anything Training Studio does not use. `shared_problem` is a sentence
  when the file could not be read, which is then as if there were none. The page fills in
  a first set-up's team repository and a new training's deck from `shared`.
- `team_moved` is {"repository", "branch", "says"} when the file names a team repository
  that is not the one this computer's workspace is a copy of, which happens when it is
  changed in another studio, and None otherwise. The workspace is never moved by itself:
  `says` is one sentence for the page, which offers to join the new one through set-up. A
  folder on this computer is never compared, and only the repository is: a Training Studio
  folder in a repository keeps the branch its hub.json names.
- `migrate()`, when the runner starts, moves the shared values this computer kept as its
  own before they were shared (agent, model, level, the brand skill's repository and
  release in runner.json; when to share, and the team repository and branch it joined, in
  the workspace record) into the file where it has none, and takes them out of runner.json
  and the record. The record keeps its repository and branch, which say what the clone is.
  When to share moves from a record of a team repository even where its clone or marker is
  gone, and leaves the record only once the file holds it.
  A value the file holds already stays as it is. A model and a level go only beside the
  same agent, a release only beside the same repository, and a branch only beside the same
  team repository. Where a value differed, `shared_notice` is a sentence that says so, until
  `notice_read()`. While the file cannot be read nothing is moved. What moves is worked out
  again under the file's lock, so a value another studio writes meanwhile stays.
"""
from __future__ import annotations

import os
import re
import secrets
import shutil
from dataclasses import replace
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
import home
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
            'team_moved': moved(space, values), 'shared_notice': notice(),
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
    told = seen(sent)
    shown = None if told is None else settings.seen(told)
    kept = settings.load()
    if repository is None:
        settings.save(replace(kept, brand_repository=None, brand_release=None), shown)
        return describe(engine)
    studios_config.writable()   # before git is asked anything
    found = brand_source.check(repository, release, _anywhere())
    settings.save(replace(kept, brand_repository=found['repository'],
                          brand_release=found['release']), shown)
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


def shared() -> tuple[dict, str | None]:
    """The studios config's values that Training Studio can use, in the file's own shape,
    and a sentence when the file could not be read. A value that would be refused here, such
    as an address that carries a password, is left out."""
    found, problem = studios_config.read()
    team, brand = (_group(found, name) for name in ('team', 'brand'))
    branch = _word(team.get('branch'), 200)
    usable = settings.from_shared(found)
    values = {
        'team': {'repository': settings.passes(settings.check_repository,
                                                _word(team.get('repository'), PLACE)),
                 'branch': branch if branch and BRANCH.match(branch) and '..' not in branch
                 and not branch.endswith(('/', '.', '.lock')) else None},
        'assistant': {name: usable[name] for name in ('agent', 'model', 'effort')},
        'brand': {'repository': usable['brand_repository'],
                  'release': usable['brand_release'],
                  'brand': _word(brand.get('brand')), 'variant': _word(brand.get('variant'))},
        'output': found.get('output') if found.get('output') in OUTPUTS else None,
        'share': found.get('share') if found.get('share') in gitstate.SHARE else None}
    kept = {}
    for key, value in values.items():
        if isinstance(value, dict):
            value = {name: inner for name, inner in value.items() if inner is not None}
        if value:
            kept[key] = value
    return kept, problem


def _same(one, other) -> bool:
    return type(one) is type(other) and one == other


def same_address(one: str | None, other: str | None) -> bool:
    """Whether two addresses name one repository, as a person would write it either way."""
    def plain(address: str) -> str:
        return address.strip().rstrip('/').removesuffix('.git')
    return bool(one and other) and plain(one) == plain(other)


def moved(space, values: dict) -> dict | None:
    """The team repository every studio shares, when this computer's workspace is a copy of
    another one, with a sentence that says so. None when they are one, and for a folder."""
    team = values.get('team') or {}
    wanted = team.get('repository')
    if space is None or space.address is None or not wanted \
            or same_address(wanted, space.address):
        return None
    return {'repository': wanted, 'branch': team.get('branch'),
            'says': f'The team repository your studios share is now {wanted}, and Training '
                    f'Studio still works in its copy of {space.address} until you join the '
                    'new one.'}


# What the person is told of a value the file held already, when this computer had another.
LABELS = {'agent': 'the agent', 'model': 'the model', 'effort': 'the reasoning level',
          'brand_repository': "the brand skill's repository",
          'brand_release': "the brand skill's release", 'share': 'when to share'}


def notice_path() -> Path:
    return home.data_root() / 'studios-notice.json'


def notice() -> str | None:
    """What the person is told, once, of what moving to the studios config left alone."""
    kept = home.read_json(notice_path(), None)
    says = kept.get('says') if isinstance(kept, dict) else None
    return says if isinstance(says, str) and says else None


def notice_read() -> None:
    """The person has read the notice: it is not shown again."""
    notice_path().unlink(missing_ok=True)


def _words(labels: list[str]) -> str:
    return labels[0] if len(labels) == 1 else ', '.join(labels[:-1]) + ' and ' + labels[-1]


def migrate() -> list[str]:
    """Move the shared values this computer kept as its own into the studios config, where it
    has none of them, and take them out of this computer's files. A value the file holds
    already is left as it is, and the notice says so. Answers what was written, as the keys
    of the file, such as "assistant.agent". Nothing moves while the file cannot be read or
    written: this computer's own copies then wait for the next start."""
    found, problem = studios_config.read()
    if problem:
        return []
    kept, share, record = settings.own(), gitstate.own_share(), gitstate.current()
    moving = {}

    def wanted(held: dict) -> dict:
        moving['changes'], moving['differed'] = _moving(held, kept, share, record)
        return moving['changes']

    # Worked out again under the lock, from what the file holds then.
    if wanted(found):
        try:
            studios_config.update(wanted)
        except WorkspaceError:
            return []
    settings.forget_own()
    gitstate.forget_own_share()
    differed = moving['differed']
    if differed:
        home.write_json(notice_path(), {'says': (
            f'Training Studio now keeps the values every studio shares only in '
            f'{studios_config.shown(studios_config.path())}, which said otherwise for '
            f'{_words(differed)}, so what this computer had chosen for those is no longer '
            'used.')})
    return [f'{key}.{name}' if isinstance(value, dict) else key
            for key, value in moving['changes'].items()
            for name in (value if isinstance(value, dict) else [None])]


def _moving(found: dict, kept: dict, share: str | None, record) -> tuple[dict, list]:
    """What moves into the studios config while it holds `found`, and what it said otherwise
    for, as the notice names them."""
    mine = [(*settings.SHARED[name], name, value) for name, value in kept.items()]
    if share:
        mine.append((None, 'share', 'share', share))
    if record is not None and record.address:
        team = _group(found, 'team')
        mine.append(('team', 'repository', None, record.address))
        if team.get('repository') is None or same_address(team['repository'], record.address):
            mine.append(('team', 'branch', None, record.branch))
    # A model and a level are for their agent, and a release for its repository: beside
    # another agent or another repository in the file, this computer's are not used.
    owns = {'model': 'agent', 'effort': 'agent', 'brand_release': 'brand_repository'}
    others = {name for name in ('agent', 'brand_repository') if name in kept
              and _group(found, settings.SHARED[name][0]).get(settings.SHARED[name][1])
              not in (None, kept[name])}
    changes, differed = {}, []
    for group, key, name, value in mine:
        if group is not None and found.get(group) is not None \
                and not isinstance(found[group], dict):
            continue    # a value of the file's own that is not an object is not replaced
        held = _group(found, group).get(key) if group else found.get(key)
        if owns.get(name) in others:
            if not _same(held, value):
                differed.append(LABELS[name])
        elif held is None:
            (changes.setdefault(group, {}) if group else changes)[key] = value
        elif not _same(held, value) and name is not None:
            differed.append(LABELS[name])
    return changes, differed


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
    return {'repository': repository, 'path': whole(path) if path else None,
            'brand_skill': sent.get('brand_skill'),
            'folder': folder, 'branch': branch, 'name': name,
            'share': SHARE[when] if when else None, 'settings': chosen(sent),
            'seen': seen(sent)}


def seen(sent: dict) -> dict | None:
    """The shared values the form that sent this was shown, as `shared` gave them, or None
    where it does not say."""
    found = sent.get('shared_seen')
    if found is not None and not isinstance(found, dict):
        raise WorkspaceError('Give shared_seen as the shared values the page was shown.')
    return found


def stale(what: str) -> WorkspaceError:
    return WorkspaceError(settings.STALE.format(what))


def _address(found: dict) -> str | None:
    """The team repository the studios config names, as it is written there."""
    named = _group(found, 'team').get('repository')
    return named if isinstance(named, str) else None


def _team(joined: gitstate.Workspace, was: str | None) -> None:
    """Make the team repository just joined the one every studio shares, with its branch
    where the file names no branch for that repository. The file is read under its lock: a
    team repository another studio wrote there since set-up read `was` is kept, and
    `team_moved` says so, and a branch it names for this one stays."""
    def wanted(found: dict) -> dict:
        held, named = _group(found, 'team'), _address(found)
        if named is not None and named != was and not same_address(named, was) \
                and not same_address(named, joined.address):
            return {}
        team = {'repository': joined.address}
        if held.get('branch') is None or not same_address(named, joined.address):
            team['branch'] = joined.branch
        return {'team': team}
    studios_config.update(wanted)


def apply(engine, wanted: dict) -> dict:
    """Set the workspace up, save the settings, and describe both.

    Without a repository or a folder, the workspace stays as it is and only the settings
    and when to share change. A save that changes a value every studio shares is refused
    before anything changes while the studios config cannot be read.
    """
    repository, path, share = wanted['repository'], wanted['path'], wanted['share']
    named = wanted.get('brand_skill')
    if named is not None and named not in [skill['path'] for skill in engine.brand_skills()]:
        raise WorkspaceError('Choose the brand skill from those found on this computer.')
    can, problem = engine.notifier.can()
    if wanted['settings'].notify and not can:
        raise WorkspaceError(problem)
    before = engine.workspace
    # What the form was shown: only what the person changed from it is written, and a
    # change to a value another studio changed meanwhile is refused.
    told = wanted.get('seen')
    shown = None if told is None else settings.seen(told)
    holds = studios_config.read()[0]
    now = shared()[0]
    team = bool(repository) and (before is None or not same_address(before.address,
                                                                     repository))
    if team and told is not None:
        was, held = (_group(found, 'team').get('repository') for found in (told, now))
        if held and not same_address(held, was) and not same_address(held, repository):
            raise stale('The team repository')
    # When to share belongs to a team workspace: a folder on this computer never sets it.
    was = gitstate.shared_share() if told is None else (
        told.get('share') if told.get('share') in gitstate.SHARE else gitstate.SHARE[0])
    if not (repository or (not path and before is not None and before.address)) \
            or share == was:
        share = None
    elif gitstate.shared_share() not in (was, share):
        raise stale('When to share')
    # A change to a value another studio changed too is refused here, before the workspace
    # is joined or moved and before anything is written.
    settings.writes(wanted['settings'], shown or settings.load(), holds)
    if team or share or settings.changes(shown or settings.load(), wanted['settings']):
        studios_config.writable()
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
                gitstate.local(path, wanted['folder'], wanted['branch'], wanted['name'])
        if team:
            _team(gitstate.current(), _address(holds))
    settings.save(wanted['settings'], shown)
    engine.saved()
    engine.resume()
    return describe(engine)
