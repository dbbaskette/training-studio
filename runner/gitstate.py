"""The workspace: one folder, inside a git repository, where trainings and their state live.

What a caller needs to know
---------------------------
    workspace = gitstate.join('https://example.com/team/team-repo.git')   # a team repository
    workspace = gitstate.local(Path.home() / 'my-trainings')              # no remote
    workspace = gitstate.current()               # the one remembered on this computer

    workspace.root                               # the folder the runner owns
    workspace.training('rolling-restarts')       # where one training lives: root/<id>/
    gitstate.commit(workspace, 'Approve the blueprint', ['rolling-restarts'])
    gitstate.commit(workspace, 'Keep the research plan')   # everything under the folder
    if workspace.share == 'decision':
        report = gitstate.sync(workspace)        # fetch, replay, push; never forced

- A workspace is a repository, a folder in it (`trainings` unless named or found) and a
  branch. `join` works in a clone the runner keeps for itself under the per-user data
  folder, never in one a person or another tool works in. `local` uses a folder with no
  remote as it is, and makes it a repository if it is not one.
- The repository is shared with other tools and people. The runner reads, writes, stages
  and commits only under its own folder. A commit takes the paths it is given and nothing
  else, whatever else is changed or staged in the repository.
- Setting up puts three files in the folder when they are missing, and commits them: a
  README, an ignore file, and `hub.json`, which says the folder is Training Studio's and
  which repository, branch and folder its work lives in. A `hub.json` already there is
  adopted: its folder and branch are used. One at the repository's root, or one written by
  another tool, is never read as ours and never written.
- Kept out of every commit by the ignore file: `work/`, `sources/`, the guidance caches
  the two harness skills keep, and lock files.
- Nothing is recorded without a git identity; the refusal says how to set one.
- `sync` never forces a push. When the same file changed on both sides it stops, puts
  things back as they were and reports. When the remote cannot be reached or refuses, the
  commits stay here and the report says the work is not shared yet. Do not call it while a
  step is writing files: it sets unfinished changes aside and puts them back.
- What belongs to this computer is kept in the per-user data folder, not in the
  repository: which clone is the workspace, and when to share. Sharing is `decision`,
  after each decision a person makes, unless they choose `asked`, only when they ask.
"""
from __future__ import annotations

import re
import secrets
import shutil
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

import runner  # noqa: F401  puts the core on the import path
import home
import hub
import sync_guidance
import workspace
from workspace import WorkspaceError

SCHEMA = 1
TOOL = 'training-studio'
MARKER = 'hub.json'
FOLDER = 'trainings'
SHARE = ('decision', 'asked')   # when to share; the first is the default
NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
IGNORED = ('work/', 'sources/', '**/.harness-research/guidance/',
           '**/.harness-slides/guidance/', '*.lock', '**/.training-studio/lock')
IGNORE_NOTE = '# Kept on each computer and never shared. Written by Training Studio.'
README = """# Trainings

This folder holds trainings made with Training Studio, one folder each. Each step that
was kept and each decision a person made is a commit, so the history says what happened.

- Open a training's folder to read its research, blueprint and other files.
- `hub.json` tells Training Studio that this folder is its own. Leave it where it is.
- Working files, saved sources and lock files stay on each person's computer. The ignore
  file here keeps them out.

Change a training through Training Studio, not by hand, so its record stays true.
"""


@dataclass(frozen=True)
class Workspace:
    """Where trainings are kept on this computer."""
    name: str
    repo: Path                  # the repository's working folder
    folder: str                 # the folder in it that the runner owns
    branch: str
    address: str | None = None  # the repository's address; None when it has no remote
    share: str = SHARE[0]       # when to share: after each decision, or when asked

    @property
    def root(self) -> Path:
        return self.repo / self.folder

    def training(self, ident: str) -> Path:
        return self.root / ident


# --- what this computer remembers --------------------------------------------------------

def settings_path() -> Path:
    return home.data_root() / 'workspace.json'


def clones() -> Path:
    """Where the runner keeps its own clones of team repositories."""
    return home.data_root() / 'workspaces'


def remember(workspace: Workspace) -> Workspace:
    """Make this the computer's workspace."""
    home.write_json(settings_path(), {
        'schema': SCHEMA, 'name': workspace.name, 'repo': str(workspace.repo),
        'folder': workspace.folder, 'branch': workspace.branch,
        'address': workspace.address, 'share': workspace.share})
    return workspace


def current() -> Workspace | None:
    """The workspace remembered on this computer, or None when there is none to use."""
    kept = home.read_json(settings_path(), None)
    if not isinstance(kept, dict) or kept.get('schema') != SCHEMA:
        return None
    try:
        found = Workspace(str(kept['name']), Path(kept['repo']), str(kept['folder']),
                          str(kept['branch']), kept.get('address'),
                          kept['share'] if kept.get('share') in SHARE else SHARE[0])
    except (KeyError, TypeError):
        return None
    return found if (found.root / MARKER).is_file() else None


def share_when(when: str) -> Workspace:
    """Choose when work is shared: after each decision, or only when asked."""
    if when not in SHARE:
        raise WorkspaceError('Sharing is one of: ' + ', '.join(SHARE) + '.')
    workspace = current()
    if workspace is None:
        raise WorkspaceError('No workspace is set up on this computer yet.')
    return remember(replace(workspace, share=when))


# --- git ---------------------------------------------------------------------------------

def need_git() -> None:
    if shutil.which('git') is None:
        raise WorkspaceError('A workspace needs git, which is not installed. Install it and '
                             'try again.')


def identity(repo: Path) -> str:
    """The name git will put on a commit. Refuses, with the fix, when git has none."""
    done = hub.run(repo, 'var', 'GIT_AUTHOR_IDENT')
    name = done.stdout.rpartition(' <')[0].strip() if done.returncode == 0 else ''
    if not name:
        raise WorkspaceError(
            'git does not know who you are, so your work cannot be recorded. Tell it once '
            'with git config --global user.name "Your Name" and git config --global '
            'user.email "you@example.com", then try again.')
    return name


def on_branch(repo: Path) -> str:
    done = hub.run(repo, 'symbolic-ref', '--quiet', '--short', 'HEAD')
    if done.returncode != 0 or not done.stdout.strip():
        raise WorkspaceError(f'The repository in {repo} is not on a branch. Check a branch '
                             'out there with git, then try again.')
    return done.stdout.strip()


def switch(repo: Path, branch: str) -> None:
    """Be on a branch: one that exists here, one the remote has, or a new one."""
    if not hub.passes(repo, 'check-ref-format', '--branch', branch):
        raise WorkspaceError(f'"{branch}" cannot be the name of a branch.')
    if on_branch(repo) == branch:
        return
    if hub.passes(repo, 'rev-parse', '--verify', '--quiet', f'refs/heads/{branch}'):
        hub.git(repo, 'checkout', '--quiet', branch)
    elif hub.passes(repo, 'rev-parse', '--verify', '--quiet',
                    f'refs/remotes/origin/{branch}'):
        hub.git(repo, 'checkout', '--quiet', '-b', branch, '--track', f'origin/{branch}')
    else:
        hub.git(repo, 'checkout', '--quiet', '-b', branch)


# --- the folder and its hub.json ---------------------------------------------------------

def check_name(value: str, label: str) -> str:
    if not NAME.match(value) or value == '.git':
        raise WorkspaceError(f'{label} is letters, digits, dots, hyphens and underscores, at '
                             f'most 64, starting with a letter or digit; "{value}" is not.')
    return value


def installed() -> str:
    """The helper's version on this computer."""
    return sync_guidance.runtime_version()


def marker(repo: Path, folder: str) -> dict | None:
    """The folder's hub.json when it is one this version can work with; None when the
    folder has none. Refuses any other."""
    path, where = repo / folder / MARKER, f'{folder}/{MARKER}'
    if path.is_symlink():
        raise WorkspaceError(f'{where} is a symbolic link, so it is not used.')
    if not path.is_file():
        return None
    found = home.read_json(path, None)
    unreadable = WorkspaceError(f'{where} cannot be read, so {folder}/ cannot be used as a '
                                'workspace.')
    if not isinstance(found, dict):
        raise unreadable
    if found.get('tool') != TOOL:
        raise WorkspaceError(f'{where} belongs to another tool, so {folder}/ is not a '
                             'Training Studio folder. Name a different folder.')
    if found.get('schema') != SCHEMA:
        raise WorkspaceError(f"{where} uses layout {found.get('schema')!r}, which this "
                             'version of Training Studio does not understand. Update '
                             'Training Studio to use it.')
    try:
        needed = sync_guidance.as_tuple(str(found.get('minimum_runtime')))
        behind = needed > sync_guidance.as_tuple(installed())
    except sync_guidance.SyncError:
        raise unreadable
    if not isinstance(found.get('name'), str) or not isinstance(found.get('branch'), str):
        raise unreadable
    if behind:
        raise WorkspaceError(f"This workspace needs Training Studio {found['minimum_runtime']}"
                             f' or newer, and this computer has {installed()}. Update '
                             'Training Studio, then try again.')
    if found.get('folder') != folder:
        raise WorkspaceError(f'{where} does not describe the folder it is in, so it is not '
                             'used. Ask whoever looks after the repository to put it right.')
    return found


def ours(path: Path) -> bool:
    """True for a hub.json that says its folder is Training Studio's."""
    found = home.read_json(path, None) if path.is_file() and not path.is_symlink() else None
    return isinstance(found, dict) and found.get('tool') == TOOL


def find_folder(repo: Path, named: str | None) -> str:
    """The folder to use: the one named, else the one a hub.json one level down says is
    Training Studio's, else `trainings`. A hub.json at the root is not looked at."""
    if named is not None:
        return check_name(named, 'A workspace folder')
    found = sorted(path.parent.name for path in repo.glob(f'*/{MARKER}')
                   if not path.parent.name.startswith('.') and ours(path))
    if len(found) > 1:
        raise WorkspaceError('This repository has more than one Training Studio folder: '
                             + ', '.join(found) + '. Name the one to use.')
    return found[0] if found else FOLDER


def lay_out(repo: Path, folder: str, described: dict | None) -> list[str]:
    """Make the folder and the files it needs, where they are missing. Returns the paths
    written, from the repository's root. Nothing outside the folder is touched."""
    root = repo / folder
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise WorkspaceError(f'{folder} in this repository is not a plain folder, so it '
                             'cannot hold trainings. Name a different folder.')
    root.mkdir(exist_ok=True)
    written = []
    if described is not None:
        home.write_json(root / MARKER, described)
        written.append(MARKER)
    if not (root / 'README.md').exists():
        (root / 'README.md').write_text(README, encoding='utf-8')
        written.append('README.md')
    ignore = root / '.gitignore'
    had = ignore.read_text(encoding='utf-8').splitlines() if ignore.is_file() else []
    missing = [pattern for pattern in IGNORED if pattern not in had]
    if missing:
        lines = [*had, *([''] if had else []), IGNORE_NOTE, *missing]
        ignore.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        written.append('.gitignore')
    return [f'{folder}/{name}' for name in written]


def set_up(repo: Path, label: str, address: str | None, folder: str | None,
           branch: str | None, share: str | None) -> Workspace:
    """Adopt or lay out the runner's folder in a repository, and remember the workspace."""
    if share not in (None, *SHARE):
        raise WorkspaceError('Sharing is one of: ' + ', '.join(SHARE) + '.')
    identity(repo)
    if branch is not None:
        switch(repo, branch)
    where = find_folder(repo, folder)
    found = marker(repo, where)
    if found and found['branch'] != on_branch(repo):
        if branch is not None:
            raise WorkspaceError(f"{where}/{MARKER} says this workspace's work is on the "
                                 f"branch {found['branch']}, not {branch}. Leave the branch "
                                 'out to use it.')
        switch(repo, found['branch'])
        label, found = found['name'], marker(repo, where)
    described = None if found else {
        'tool': TOOL, 'schema': SCHEMA, 'name': label, 'repository': address,
        'branch': on_branch(repo), 'folder': where, 'minimum_runtime': installed()}
    written = lay_out(repo, where, described)
    if written:
        _commit(repo, f'Set up the Training Studio workspace in {where}/', written)
    before = current()
    kept = before.share if before and before.repo == repo else SHARE[0]
    return remember(Workspace(str((found or described)['name']), repo, where,
                              on_branch(repo), address, share or kept))


def join(address: str, folder: str | None = None, branch: str | None = None,
         name: str | None = None, share: str | None = None) -> Workspace:
    """Set the workspace up from a repository's address, in a clone of the runner's own."""
    need_git()
    if hub.ADDRESS_WITH_SECRET.match(address):
        raise WorkspaceError('That address carries a password or token. Give the address '
                             'without it; git signs in with your own credentials.')
    label = check_name(name or hub.name_from(address), 'A workspace name')
    repo = clones() / label
    fresh = not (repo / '.git').exists()
    if fresh:
        _clone(address, repo)
    elif hub.run(repo, 'remote', 'get-url', 'origin').stdout.strip() != address:
        raise WorkspaceError(f'A workspace called "{label}" is already kept on this computer '
                             'for a different repository. Give this one another name.')
    try:
        return set_up(repo, label, address, folder, branch, share)
    except WorkspaceError:
        if fresh:  # a first set-up that was refused leaves nothing behind
            shutil.rmtree(repo, ignore_errors=True)
        raise


def _clone(address: str, repo: Path) -> None:
    """Clone a repository into place, or leave nothing when it cannot be cloned."""
    clones().mkdir(parents=True, exist_ok=True)
    pending = clones() / f'.joining-{secrets.token_hex(4)}'
    try:
        cloned = hub.run(clones(), 'clone', '--quiet', *hub.COPY_AS_IS, '--', address,
                         str(pending))
        if cloned.returncode != 0:
            raise WorkspaceError(f'Could not clone {address}: {hub.reason(cloned)}. Check the '
                                 'address, and that git can sign in to it without asking.')
        pending.replace(repo)
    finally:
        shutil.rmtree(pending, ignore_errors=True)


def local(path: Path, folder: str | None = None, branch: str | None = None,
          name: str | None = None, share: str | None = None) -> Workspace:
    """Set the workspace up in a folder on this computer that has no remote. The folder is
    made a repository if it is not one."""
    need_git()
    repo = Path(path).expanduser().resolve()
    skill = workspace.SKILL_DIR
    if repo == skill or repo in skill.parents or skill in repo.parents:
        raise WorkspaceError(f'{repo} holds Training Studio itself. Choose a folder made for '
                             'trainings.')
    if repo.exists() and not repo.is_dir():
        raise WorkspaceError(f'{repo} is a file. Name a folder for the workspace.')
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / '.git').exists():
        hub.git(repo, 'init', '--quiet')
    elif hub.git(repo, 'remote'):
        raise WorkspaceError(
            f'{repo} is a copy of a shared repository that someone works in. Set the '
            "workspace up from the repository's address instead: the runner keeps a copy of "
            'its own, so it never changes yours.')
    label = check_name(name or hub.name_from(repo.name), 'A workspace name')
    return set_up(repo, label, None, folder, branch, share)


# --- committing --------------------------------------------------------------------------

def inside(workspace: Workspace, path) -> str:
    """A path under the workspace's folder, from the repository's root. A relative path is
    taken from the folder. Refuses anything that leaves it."""
    given = Path(path)
    target = given if given.is_absolute() else workspace.root / given
    root = workspace.root.resolve()
    resolved = target.parent.resolve() / target.name
    if '..' in given.parts or (resolved != root and root not in resolved.parents):
        raise WorkspaceError(f'{path} is outside {workspace.folder}/, the only folder the '
                             'runner records.')
    return PurePosixPath(workspace.folder, *resolved.relative_to(root).parts).as_posix()


def _commit(repo: Path, message: str, scope: list[str]) -> bool:
    """Commit what changed in `scope` and nothing else. False when nothing did."""
    hub.git(repo, 'add', '-A', '--', *scope)
    if hub.passes(repo, 'diff', '--cached', '--quiet', '--', *scope):
        return False
    done = hub.run(repo, 'commit', '--quiet', '--only', '-m', message, '--', *scope)
    if done.returncode != 0:
        identity(repo)
        raise hub.GitError(hub.reason(done))
    return True


def commit(workspace: Workspace, message: str, paths=None) -> bool:
    """Commit the named paths, or everything that changed in the workspace's folder.

    Returns False when nothing had changed. Only paths under the folder are staged and
    committed: a change anywhere else in the repository, staged or not, is left as it is.
    Nothing is pushed.
    """
    if not message.strip():
        raise WorkspaceError('A commit needs a message that says what happened.')
    scope = [inside(workspace, path) for path in paths] if paths else [workspace.folder]
    return _commit(workspace.repo, message.strip(), scope)


def changed(workspace: Workspace) -> list[str]:
    """Paths under the folder that differ from the last commit, from the repository's
    root. Ignored files are not listed."""
    done = hub.run(workspace.repo, 'status', '--porcelain', '--no-renames', '-z',
                   '--untracked-files=all', '--', workspace.folder)
    if done.returncode != 0:
        raise hub.GitError(hub.reason(done))
    return sorted(entry[3:] for entry in hub.names(done.stdout))


# --- sharing -----------------------------------------------------------------------------

def sync(workspace: Workspace) -> dict:
    """Share the workspace: fetch, replay local commits on the remote's, and push.

    Never raises for the remote's sake and never forces a push. The report says whether
    everything here is now shared (`shared`), whether the remote was reached, how many
    commits came in, how many local commits are still waiting (`unshared`), any files in
    conflict, and in `notice` a sentence for the person when the work is not shared.
    """
    repo, branch = workspace.repo, workspace.branch
    report = {'shared': False, 'reached': True, 'received': 0, 'unshared': 0, 'conflict': [],
              'notice': None}
    if workspace.address is None:
        return {**report, 'reached': None, 'notice': (
            'This workspace has no shared repository, so there is nowhere to share it. Your '
            'work is kept on this computer.')}
    if on_branch(repo) != branch:
        raise WorkspaceError(f"The workspace's repository in {repo} is on the branch "
                             f'{on_branch(repo)}, not {branch}. Check {branch} out there with '
                             'git, then try again.')
    tracking = f'refs/remotes/origin/{branch}'
    refused = stuck = None
    for _ in range(hub.ATTEMPTS):
        fetched = hub.run(repo, 'fetch', '--quiet', 'origin')
        if fetched.returncode != 0:
            report['reached'] = False
            break
        theirs = (hub.apart(repo, tracking) or (0, 0))[1]
        if refused and not theirs:
            break  # nobody pushed in between: the remote refused for a reason of its own
        if theirs:
            report['received'] += theirs
            stuck = _replay(repo, tracking, report)
            if stuck:
                break
        if not hub.ahead(repo, tracking):
            refused = None
            break
        sent = hub.run(repo, 'push', '--quiet', 'origin', f'HEAD:refs/heads/{branch}')
        refused = None if sent.returncode == 0 else hub.reason(sent)
        if refused is None:
            break
    report['unshared'] = hub.ahead(repo, tracking)
    report['shared'] = bool(report['reached']) and not stuck and not report['unshared']
    report['notice'] = _notice(repo, report, fetched, stuck, refused)
    return report


def _replay(repo: Path, tracking: str, report: dict) -> str | None:
    """Replay local commits on top of the remote's. On failure put everything back as it
    was and return why; the files in conflict go in the report."""
    done = hub.run(repo, 'rebase', '--autostash', tracking)
    if done.returncode == 0:
        return None
    report['conflict'] = hub.names(
        hub.run(repo, 'diff', '-z', '--name-only', '--diff-filter=U').stdout)
    hub.run(repo, 'rebase', '--abort')
    return hub.reason(done)


def _notice(repo: Path, report: dict, fetched, stuck: str | None,
            refused: str | None) -> str | None:
    """What to tell the person when the work is not shared, or None when it is."""
    waiting = ('Your work is kept on this computer and is not shared yet.'
               if report['unshared'] else 'Nothing here is waiting to be shared, but this '
               'copy may be out of date.')
    if not report['reached']:
        return (f'The shared repository could not be reached ({hub.reason(fetched)}). '
                f'{waiting} Share again when it can be reached.')
    if report['conflict']:
        return ('The same files were changed here and in the shared repository ('
                + ', '.join(report['conflict']) + '), and the runner will not choose between '
                'them. Nothing was pushed: your work is kept on this computer and is not '
                f'shared yet. Settle it with git in {repo}, then share again.')
    if stuck:
        return (f'The changes made here could not be put on top of the shared ones ({stuck}). '
                'Nothing was pushed: your work is kept on this computer and is not shared '
                f'yet. Look at {repo} with git, then share again.')
    if refused or report['unshared']:
        why = refused or 'it gave no reason'
        return (f'The shared repository did not accept the changes ({why}). They are kept on '
                'this computer and are not shared yet. Check that you may push to it, then '
                'share again.')
    return None
