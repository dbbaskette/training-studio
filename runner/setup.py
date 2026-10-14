"""Setting this computer up for the runner: the workspace, the agent, the limits and how a
deck's previews are rendered.

What a caller needs to know
---------------------------
    setup.describe(engine)        the workspace, the default agent and the limits, as saved,
                                  with what this computer has for previews and for a brand
    setup.check(sent)             whether a repository or a folder can be used; changes nothing
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
  Google Drive (`drive`), with which of the two this computer can use, and the preview
  files the runner has left in Drive. It never deletes one, so it lists them. `brand` is
  the brand skill that was found and the brands it has, with every brand skill found
  under `skills` as {'name', 'path', 'chosen'}; `brand_skill` names one of those paths to
  use. Both are asked of the engine, which looks at this computer and reuses the look.
"""
from __future__ import annotations

import os
import secrets
import shutil
from dataclasses import replace
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
import hub
import workspace
from workspace import WorkspaceError

from runner import gitstate, settings

WHEN = {'decision': 'each-decision', 'asked': 'when-asked'}
SHARE = {said: kept for kept, said in WHEN.items()}
PROBE = 'training-studio-write-check'   # a branch name that is asked about, never made
NOBODY = ('-c', 'user.name=Training Studio', '-c', 'user.email=check@example.invalid')
PLACE = 2000    # characters in an address or a path


def describe(engine) -> dict:
    """What is set up on this computer, in the shape the page reads."""
    space, chosen = engine.workspace, settings.load()
    found = None if space is None else {
        'name': space.name, 'repository': space.address, 'path': str(space.repo),
        'folder': space.folder, 'branch': space.branch, 'share_when': WHEN[space.share],
        **engine.shared()}
    needs = engine.deck_needs()
    return {'configured': space is not None, 'workspace': found,
            'agent': {'default': chosen.agent, 'model': chosen.model},
            'limits': chosen.limits,
            'previews': {'how': chosen.previews, 'drive': needs['drive'],
                         'local': needs['local'], 'left': engine.previews_left()},
            'brand': {**needs['brand'], 'skills': engine.brand_skills()}}


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
    model = sent['model'] if 'model' in sent else (kept.model if agent == kept.agent else None)
    wanted = {name: (limits or {}).get(name, getattr(kept, name))
              for name in ('step_seconds', 'training_dollars', 'parallel')}
    previews = sent['previews'] if sent.get('previews') is not None else kept.previews
    skill = sent['brand_skill'] if sent.get('brand_skill') is not None else kept.brand_skill
    return settings.check(replace(kept, agent=agent, model=model, previews=previews,
                                  brand_skill=skill, **wanted))


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
    before = engine.workspace
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
    settings.save(wanted['settings'])
    engine.deck_needs(fresh=True)
    engine.resume()
    return describe(engine)
