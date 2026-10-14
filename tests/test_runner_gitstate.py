"""The workspace: one folder inside a repository that other tools and people also use.

Bare repositories in temporary folders stand in for a team's remote. No network.
"""
import contextlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers
import runner_support  # noqa: F401

import hub
from runner import gitstate
from workspace import WorkspaceError

VERSION = (helpers.SKILL / 'VERSION').read_text().strip()
THEIR_HUB = b'{\n  "name": "team",\n  "schema": 1\n}\n'
THEIR_README = b'# Team\n\nRebuilt by another tool.\n'
PATTERNS = ['work/', 'sources/', '**/.harness-research/guidance/',
            '**/.harness-slides/guidance/', '*.lock', '**/.training-studio/lock']


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(['git', '-c', 'user.name=Other Tool', '-c',
                           'user.email=tool@example.com', *args], cwd=repo,
                          capture_output=True, text=True, check=True)
    return done.stdout.strip()


class Held:
    """A lock that says whether it is held, for a test to look at."""

    def __init__(self):
        self.depth = 0

    def __enter__(self):
        self.depth += 1

    def __exit__(self, *failure):
        self.depth -= 1


@contextlib.contextmanager
def asked(held: Held | None = None):
    """Every git command the runner runs inside, by name, with whether `held` was held."""
    ran, real = [], hub.run

    def spy(repo, *args, **named):
        ran.append((hub.subcommand(args), bool(held and held.depth)))
        return real(repo, *args, **named)

    with mock.patch.object(hub, 'run', spy):
        yield ran


class WorkspaceCase(unittest.TestCase):
    """A bare repository standing in for the team's remote, and people who each have their
    own data folder and git identity."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.base = Path(holder.name).resolve()
        (self.base / 'no-templates').mkdir()
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE'):
            os.environ.pop(name, None)
        self.remote = self.base / 'team-repo.git'
        self.others = 0
        self.be('alex')

    def be(self, person: str) -> None:
        folder = self.base / person
        if not folder.is_dir():
            folder.mkdir()
            helpers.gitconfig(
                folder / 'gitconfig',
                f'[user]\n\tname = {person.title()}\n\temail = {person}@example.com\n'
                f"[init]\n\tdefaultBranch = main\n\ttemplateDir = {self.base / 'no-templates'}\n")
        os.environ.update({'TRAINING_STUDIO_DATA': str(folder / 'data'),
                           'GIT_CONFIG_GLOBAL': str(folder / 'gitconfig'),
                           'GIT_CONFIG_NOSYSTEM': '1'})

    def bare(self) -> Path:
        """An empty repository of the kind a host makes, with main as its branch."""
        self.remote.mkdir()
        git(self.remote, 'init', '--quiet', '--bare')
        git(self.remote, 'symbolic-ref', 'HEAD', 'refs/heads/main')
        return self.remote

    def other_tool(self, files: dict[str, bytes], message: str = 'Another tool') -> None:
        """Something else commits to the remote's main branch and pushes."""
        if not self.remote.exists():
            self.bare()
        self.others += 1
        clone = self.base / f'other-{self.others}'
        git(self.base, 'clone', '--quiet', str(self.remote), str(clone))
        for name, data in files.items():
            (clone / name).parent.mkdir(parents=True, exist_ok=True)
            (clone / name).write_bytes(data)
        git(clone, 'add', '-A')
        git(clone, 'commit', '--quiet', '-m', message)
        git(clone, 'push', '--quiet', 'origin', 'HEAD:main')

    def join(self, **named) -> gitstate.Workspace:
        if not self.remote.exists():
            self.bare()
        return gitstate.join(str(self.remote), **named)

    def write(self, workspace, relative: str, text: str = 'Text.\n') -> Path:
        path = workspace.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def committed(self, repo: Path, commit: str = 'HEAD') -> list[str]:
        return sorted(git(repo, 'show', '--name-only', '--format=', commit).splitlines())

    def remote_head(self, branch: str = 'main') -> str:
        return git(self.remote, 'rev-parse', f'refs/heads/{branch}')

    def nobody(self) -> None:
        """Become someone git has no name for."""
        os.environ['GIT_CONFIG_GLOBAL'] = str(helpers.gitconfig(
            self.base / 'nobody.gitconfig', '[user]\n\tuseConfigOnly = true\n'))

    def nothing_kept(self) -> None:
        """No clone and no remembered workspace were left behind."""
        self.assertIsNone(gitstate.current())
        self.assertFalse(gitstate.settings_path().exists())
        left = list(gitstate.clones().iterdir()) if gitstate.clones().exists() else []
        self.assertEqual(left, [])


class SetUpTests(WorkspaceCase):
    def test_a_first_set_up_creates_and_commits_the_folder_and_its_three_files(self):
        workspace = self.join()
        self.assertEqual(workspace, gitstate.Workspace(
            'team-repo', gitstate.clones() / 'team-repo', 'trainings', 'main',
            str(self.remote), 'decision'))
        self.assertEqual(workspace.root, workspace.repo / 'trainings')
        self.assertEqual(workspace.training('rolling-restarts'),
                         workspace.repo / 'trainings' / 'rolling-restarts')
        self.assertEqual(json.loads((workspace.root / 'hub.json').read_text()), {
            'tool': 'training-studio', 'schema': 1, 'name': 'team-repo',
            'repository': str(self.remote), 'branch': 'main', 'folder': 'trainings',
            'minimum_runtime': VERSION})
        self.assertEqual(self.committed(workspace.repo),
                         ['trainings/.gitignore', 'trainings/README.md', 'trainings/hub.json'])
        self.assertEqual(git(workspace.repo, 'log', '--format=%an: %s'),
                         'Alex: Set up the Training Studio workspace in trainings/')
        self.assertEqual(sorted(path.name for path in workspace.repo.iterdir()),
                         ['.git', 'trainings'])
        self.assertEqual(git(workspace.repo, 'status', '--porcelain'), '')
        ignored = (workspace.root / '.gitignore').read_text().splitlines()
        self.assertEqual(ignored[1:], PATTERNS)
        self.assertIn('one folder each', (workspace.root / 'README.md').read_text())

    def test_set_up_pushes_nothing(self):
        self.join()
        self.assertEqual(git(self.remote, 'for-each-ref'), '')

    def test_the_workspace_is_remembered_on_this_computer_and_not_in_the_repository(self):
        workspace = self.join(share='asked')
        kept = json.loads(gitstate.settings_path().read_text())
        self.assertEqual(kept, {'schema': 1, 'name': 'team-repo', 'repo': str(workspace.repo),
                                'folder': 'trainings', 'branch': 'main',
                                'address': str(self.remote), 'share': 'asked'})
        self.assertEqual(gitstate.settings_path().parent, Path(os.environ['TRAINING_STUDIO_DATA']))
        self.assertEqual(gitstate.current(), workspace)
        marker = json.loads((workspace.root / 'hub.json').read_text())
        self.assertNotIn('share', marker)
        self.assertNotIn(str(workspace.repo), json.dumps(marker))

    def test_work_is_shared_after_each_decision_unless_the_person_chooses_to_be_asked(self):
        self.assertEqual(self.join().share, 'decision')
        self.assertEqual(gitstate.share_when('asked').share, 'asked')
        self.assertEqual(gitstate.current().share, 'asked')
        self.assertEqual(self.join().share, 'asked')
        self.assertEqual(self.join(share='decision').share, 'decision')
        with self.assertRaisesRegex(WorkspaceError, 'Sharing is one of: decision, asked'):
            gitstate.share_when('hourly')
        with self.assertRaisesRegex(WorkspaceError, 'Sharing is one of: decision, asked'):
            self.join(share='hourly')

    def test_there_is_no_workspace_until_one_is_set_up(self):
        self.assertIsNone(gitstate.current())
        with self.assertRaisesRegex(WorkspaceError, 'No workspace is set up'):
            gitstate.share_when('decision')
        workspace = self.join()
        shutil.rmtree(workspace.repo)
        self.assertIsNone(gitstate.current())

    def test_a_second_person_adopts_the_folder_without_being_asked(self):
        first = self.join(folder='enablement')
        self.assertTrue(gitstate.sync(first)['shared'])
        self.be('blake')
        second = self.join()
        self.assertEqual((second.folder, second.branch, second.name),
                         ('enablement', 'main', 'team-repo'))
        self.assertNotEqual(second.repo, first.repo)
        self.assertEqual(git(second.repo, 'rev-parse', 'HEAD'), self.remote_head())
        self.assertEqual(git(second.repo, 'status', '--porcelain'), '')
        self.assertFalse((second.repo / 'trainings').exists())

    def test_the_branch_the_file_names_is_adopted_too(self):
        first = self.join(branch='studio')
        self.assertEqual(json.loads((first.root / 'hub.json').read_text())['branch'], 'studio')
        self.assertTrue(gitstate.sync(first)['shared'])
        git(first.repo, 'push', '--quiet', 'origin', 'studio:main')
        self.be('blake')
        second = self.join()
        self.assertEqual((second.branch, gitstate.on_branch(second.repo)), ('studio', 'studio'))
        self.assertEqual(git(second.repo, 'rev-parse', 'HEAD'), self.remote_head('studio'))
        self.be('casey')
        with self.assertRaisesRegex(WorkspaceError, 'on the branch studio, not main. Leave'):
            self.join(branch='main')
        self.nothing_kept()

    def test_a_named_branch_that_exists_on_the_remote_is_followed(self):
        first = self.join(branch='studio')
        gitstate.sync(first)
        self.be('blake')
        second = self.join(branch='studio')
        self.assertEqual((second.branch, second.folder), ('studio', 'trainings'))
        self.assertEqual(git(second.repo, 'rev-parse', 'HEAD'), self.remote_head('studio'))
        with self.assertRaisesRegex(WorkspaceError, 'cannot be the name of a branch'):
            self.join(branch='not a branch')

    def test_another_tools_hub_json_at_the_root_is_left_exactly_as_it_is(self):
        self.other_tool({'hub.json': THEIR_HUB, 'README.md': THEIR_README})
        workspace = self.join()
        self.assertEqual(workspace.folder, 'trainings')
        self.write(workspace, 'rolling-restarts/intake.md')
        gitstate.commit(workspace, 'Keep the intake of rolling-restarts')
        self.assertTrue(gitstate.sync(workspace)['shared'])
        for name, theirs in (('hub.json', THEIR_HUB), ('README.md', THEIR_README)):
            self.assertEqual((workspace.repo / name).read_bytes(), theirs)
            shown = subprocess.run(['git', 'show', f'main:{name}'], cwd=self.remote,
                                   capture_output=True, check=True).stdout
            self.assertEqual(shown, theirs)
        ours = [name for commit in git(workspace.repo, 'rev-list', '--author=Alex', 'HEAD'
                                       ).splitlines() for name in self.committed(workspace.repo,
                                                                                 commit)]
        self.assertTrue(ours and all(name.startswith('trainings/') for name in ours), ours)

    def test_a_root_hub_json_is_never_read_as_ours_whatever_it_says(self):
        claims = json.dumps({'tool': 'training-studio', 'schema': 9, 'folder': '.',
                             'branch': 'elsewhere', 'minimum_runtime': '99.0.0'}).encode()
        self.other_tool({'hub.json': claims})
        workspace = self.join()
        self.assertEqual((workspace.folder, workspace.branch), ('trainings', 'main'))
        self.assertEqual((workspace.repo / 'hub.json').read_bytes(), claims)

    def test_a_folder_that_belongs_to_another_tool_is_not_mistaken_for_ours(self):
        theirs = json.dumps({'tool': 'deck-builder', 'schema': 1, 'folder': 'decks'}).encode()
        self.other_tool({'decks/hub.json': theirs})
        self.assertEqual(self.join().folder, 'trainings')
        self.be('blake')
        with self.assertRaisesRegex(WorkspaceError, 'decks/hub.json belongs to another tool'):
            self.join(folder='decks')
        self.nothing_kept()

    def test_a_layout_this_version_does_not_know_is_refused(self):
        self.other_tool({'trainings/hub.json': json.dumps({
            'tool': 'training-studio', 'schema': 2, 'name': 'team', 'folder': 'trainings',
            'branch': 'main', 'minimum_runtime': VERSION}).encode()})
        with self.assertRaisesRegex(WorkspaceError, 'trainings/hub.json uses layout 2, which '
                                    'this version of Training Studio does not understand'):
            self.join()
        self.nothing_kept()

    def test_a_workspace_that_needs_a_newer_helper_is_refused(self):
        self.other_tool({'trainings/hub.json': json.dumps({
            'tool': 'training-studio', 'schema': 1, 'name': 'team', 'folder': 'trainings',
            'branch': 'main', 'minimum_runtime': '99.0.0'}).encode()})
        with self.assertRaisesRegex(WorkspaceError, 'needs Training Studio 99.0.0 or newer, '
                                    f'and this computer has {VERSION}. Update'):
            self.join()
        self.nothing_kept()

    def test_a_file_that_cannot_be_read_or_is_in_the_wrong_place_is_refused(self):
        good = {'tool': 'training-studio', 'schema': 1, 'name': 'team', 'folder': 'trainings',
                'branch': 'main', 'minimum_runtime': VERSION}
        self.other_tool({'broken/hub.json': b'{not json', 'moved/hub.json':
                         json.dumps(good).encode(), 'nameless/hub.json':
                         json.dumps({**good, 'folder': 'nameless', 'name': None}).encode(),
                         'odd/hub.json':
                         json.dumps({**good, 'folder': 'odd',
                                     'minimum_runtime': 'soon'}).encode()})
        for folder, said in (('broken', 'broken/hub.json cannot be read'),
                             ('moved', 'does not describe the folder it is in'),
                             ('odd', 'odd/hub.json cannot be read'),
                             ('nameless', 'nameless/hub.json cannot be read')):
            with self.subTest(folder), self.assertRaisesRegex(WorkspaceError, said):
                self.join(folder=folder)

    def test_two_training_studio_folders_need_one_to_be_named(self):
        def marker(folder):
            return json.dumps({'tool': 'training-studio', 'schema': 1, 'name': folder,
                               'folder': folder, 'branch': 'main',
                               'minimum_runtime': VERSION}).encode()

        self.other_tool({'sales/hub.json': marker('sales'), 'support/hub.json':
                         marker('support')})
        with self.assertRaisesRegex(WorkspaceError, 'more than one Training Studio folder: '
                                    'sales, support. Name the one to use'):
            self.join()
        workspace = self.join(folder='support')
        self.assertEqual((workspace.folder, workspace.name), ('support', 'support'))
        self.assertFalse((workspace.repo / 'sales' / 'README.md').exists())

    def test_an_address_with_a_password_or_token_is_refused_before_anything_is_written(self):
        for address in ('https://alex:secret@example.com/team/team-repo.git',
                        'https://' + 'x' * 24 + '@example.com/team/team-repo.git'):
            with self.subTest(address), self.assertRaisesRegex(
                    WorkspaceError, 'carries a password or token'):
                gitstate.join(address)
        self.nothing_kept()
        self.assertFalse(gitstate.clones().exists())

    def test_a_repository_that_cannot_be_cloned_leaves_nothing(self):
        with self.assertRaisesRegex(WorkspaceError, 'Could not clone .*missing.git'):
            gitstate.join(str(self.base / 'missing.git'))
        self.nothing_kept()

    def test_the_runners_own_clone_is_used_again(self):
        first = self.join()
        self.write(first, 'rolling-restarts/intake.md')
        again = self.join()
        self.assertEqual(again, first)
        self.assertEqual(git(first.repo, 'rev-list', '--count', 'HEAD'), '1')
        self.assertTrue((first.root / 'rolling-restarts' / 'intake.md').is_file())
        other = self.base / 'another.git'
        git(self.base, 'init', '--quiet', '--bare', str(other))
        with self.assertRaisesRegex(WorkspaceError, 'already kept on this computer for a '
                                    'different repository'):
            gitstate.join(str(other), name='team-repo')
        self.assertEqual(gitstate.join(str(other)).name, 'another')

    def test_a_folder_that_is_already_there_gains_only_what_it_lacks(self):
        self.other_tool({'trainings/README.md': b'# Ours already\n',
                         'trainings/.gitignore': b'drafts/\nsources/\n',
                         'trainings/old/intake.md': b'Kept.\n'})
        workspace = self.join()
        self.assertEqual((workspace.root / 'README.md').read_bytes(), b'# Ours already\n')
        self.assertEqual((workspace.root / '.gitignore').read_text().splitlines(),
                         ['drafts/', 'sources/', '', gitstate.IGNORE_NOTE,
                          *[pattern for pattern in PATTERNS if pattern != 'sources/']])
        self.assertEqual(self.committed(workspace.repo),
                         ['trainings/.gitignore', 'trainings/hub.json'])

    def test_a_folder_name_is_one_plain_name(self):
        for folder in ('../elsewhere', 'a/b', '.git', '', '-rf'):
            with self.subTest(folder), self.assertRaisesRegex(WorkspaceError,
                                                              'A workspace folder is'):
                self.join(folder=folder)
        with self.assertRaisesRegex(WorkspaceError, 'A workspace name is'):
            self.join(name='team repo')
        self.nothing_kept()

    def test_a_workspace_needs_git(self):
        with mock.patch.object(gitstate.shutil, 'which', return_value=None):
            for set_up in (lambda: gitstate.join('https://example.com/team/team-repo.git'),
                           lambda: gitstate.local(self.base / 'solo')):
                with self.assertRaisesRegex(WorkspaceError, 'needs git, which is not installed'):
                    set_up()
        self.assertFalse((self.base / 'solo').exists())

    def test_set_up_needs_a_git_identity_and_says_how_to_give_one(self):
        self.bare()
        self.nobody()
        with self.assertRaises(WorkspaceError) as refused:
            self.join()
        said = str(refused.exception)
        self.assertIn('git does not know who you are', said)
        self.assertIn('git config --global user.name "Your Name"', said)
        self.assertIn('git config --global user.email', said)
        self.nothing_kept()


class LocalTests(WorkspaceCase):
    def test_a_folder_with_no_repository_is_made_one(self):
        place = self.base / 'my trainings'
        workspace = gitstate.local(place)
        self.assertEqual(workspace, gitstate.Workspace('my-trainings', place, 'trainings',
                                                       'main', None, 'decision'))
        self.assertEqual(json.loads((workspace.root / 'hub.json').read_text())['repository'],
                         None)
        self.assertEqual(self.committed(place),
                         ['trainings/.gitignore', 'trainings/README.md', 'trainings/hub.json'])
        self.assertEqual(gitstate.current(), workspace)

    def test_an_existing_repository_with_no_remote_is_used_as_it_is(self):
        place = self.base / 'notes'
        place.mkdir()
        git(place, 'init', '--quiet')
        (place / 'README.md').write_bytes(THEIR_README)
        git(place, 'add', '-A')
        git(place, 'commit', '--quiet', '-m', 'Mine')
        workspace = gitstate.local(place, folder='courses', name='Field-Team')
        self.assertEqual((workspace.folder, workspace.name), ('courses', 'Field-Team'))
        self.assertEqual(git(place, 'rev-list', '--count', 'HEAD'), '2')
        self.assertEqual((place / 'README.md').read_bytes(), THEIR_README)
        self.assertEqual(gitstate.local(place), workspace)
        self.assertEqual(git(place, 'rev-list', '--count', 'HEAD'), '2')

    def test_a_copy_of_a_shared_repository_that_someone_works_in_is_refused(self):
        self.bare()
        mine = self.base / 'my-clone'
        git(self.base, 'clone', '--quiet', str(self.remote), str(mine))
        with self.assertRaisesRegex(WorkspaceError, "from the repository's address instead"):
            gitstate.local(mine)
        self.assertEqual(sorted(path.name for path in mine.iterdir()), ['.git'])
        self.assertIsNone(gitstate.current())

    def test_a_folder_that_is_a_link_or_a_file_cannot_hold_trainings(self):
        place = self.base / 'notes'
        place.mkdir()
        (place / 'trainings').write_text('A file, not a folder.\n')
        with self.assertRaisesRegex(WorkspaceError, 'trainings in this repository is not a '
                                    'plain folder'):
            gitstate.local(place)
        (place / 'courses').mkdir()
        (place / 'elsewhere.json').write_text('{"tool": "training-studio"}')
        (place / 'courses' / 'hub.json').symlink_to(place / 'elsewhere.json')
        with self.assertRaisesRegex(WorkspaceError, 'courses/hub.json is a symbolic link'):
            gitstate.local(place, folder='courses')
        self.assertIsNone(gitstate.current())

    def test_a_file_is_not_a_place_for_a_workspace(self):
        (self.base / 'notes.txt').write_text('x')
        with self.assertRaisesRegex(WorkspaceError, 'is a file'):
            gitstate.local(self.base / 'notes.txt')

    def test_training_studios_own_repository_is_not_a_place_for_trainings(self):
        for place in (helpers.REPO, helpers.SKILL, helpers.REPO.parent,
                      helpers.SKILL / 'scripts'):
            with self.subTest(place), self.assertRaisesRegex(
                    WorkspaceError, 'holds Training Studio itself'):
                gitstate.local(place)
        self.assertFalse((helpers.REPO / 'trainings').exists())

    def test_a_local_workspace_has_nowhere_to_share_to(self):
        report = gitstate.sync(gitstate.local(self.base / 'solo'))
        self.assertEqual((report['shared'], report['reached']), (False, None))
        self.assertIn('no shared repository, so there is nowhere to share it', report['notice'])


class CommitTests(WorkspaceCase):
    def test_everything_that_changed_in_the_folder_is_committed_with_its_message(self):
        workspace = self.join()
        self.write(workspace, 'rolling-restarts/intake.md')
        self.write(workspace, 'rolling-restarts/.training-studio/session.json', '{}\n')
        self.assertEqual(gitstate.changed(workspace),
                         ['trainings/rolling-restarts/.training-studio/session.json',
                          'trainings/rolling-restarts/intake.md'])
        self.assertTrue(gitstate.commit(workspace, '  Keep the intake of rolling-restarts  '))
        self.assertEqual(git(workspace.repo, 'log', '-1', '--format=%an <%ae>: %s'),
                         'Alex <alex@example.com>: Keep the intake of rolling-restarts')
        self.assertEqual(self.committed(workspace.repo),
                         ['trainings/rolling-restarts/.training-studio/session.json',
                          'trainings/rolling-restarts/intake.md'])
        self.assertEqual(gitstate.changed(workspace), [])
        self.assertFalse(gitstate.commit(workspace, 'Nothing new'))
        self.assertEqual(git(workspace.repo, 'rev-list', '--count', 'HEAD'), '2')
        self.assertEqual(git(self.remote, 'for-each-ref'), '')

    def test_a_commit_is_two_git_commands_and_asks_more_only_when_nothing_changed(self):
        workspace = self.join()
        self.write(workspace, 'rolling-restarts/intake.md')
        with asked() as ran:
            self.assertTrue(gitstate.commit(workspace, 'Keep the intake'))
        self.assertEqual([name for name, _ in ran], ['add', 'commit'])
        with asked() as ran:
            self.assertFalse(gitstate.commit(workspace, 'Nothing new'))
        self.assertEqual([name for name, _ in ran], ['add', 'commit', 'diff'])

    def test_a_change_outside_the_folder_is_never_part_of_a_commit(self):
        self.other_tool({'hub.json': THEIR_HUB, 'README.md': THEIR_README,
                         'decks/outline.md': b'One.\n'})
        workspace = self.join()
        repo = workspace.repo
        (repo / 'README.md').write_text('# Changed by hand, not staged\n')
        (repo / 'decks' / 'outline.md').write_text('Two.\n')
        git(repo, 'add', 'decks/outline.md')
        (repo / 'staged-by-another-tool.txt').write_text('Staged.\n')
        git(repo, 'add', 'staged-by-another-tool.txt')
        (repo / 'scratch.txt').write_text('Untracked.\n')
        outside = '\n' + git(repo, 'status', '--porcelain')
        self.write(workspace, 'rolling-restarts/intake.md')
        self.assertTrue(gitstate.commit(workspace, 'Keep the intake of rolling-restarts'))
        self.assertEqual(self.committed(repo), ['trainings/rolling-restarts/intake.md'])
        self.assertEqual('\n' + git(repo, 'status', '--porcelain'), outside)
        self.assertEqual(outside.split('\n')[1:], ['M README.md', 'M  decks/outline.md',
                                                   'A  staged-by-another-tool.txt',
                                                   '?? scratch.txt'])
        self.write(workspace, 'rolling-restarts/blueprint.md')
        self.assertTrue(gitstate.commit(workspace, 'Keep the blueprint',
                                        ['rolling-restarts/blueprint.md']))
        self.assertEqual(self.committed(repo), ['trainings/rolling-restarts/blueprint.md'])
        self.assertEqual('\n' + git(repo, 'status', '--porcelain'), outside)
        self.assertEqual(git(repo, 'diff', '--name-only'), 'README.md')
        self.assertEqual(git(repo, 'diff', '--cached', '--name-only').splitlines(),
                         ['decks/outline.md', 'staged-by-another-tool.txt'])
        self.assertEqual(git(repo, 'show', 'HEAD:README.md').encode() + b'\n', THEIR_README)

    def test_named_paths_are_committed_and_the_rest_is_left(self):
        workspace = self.join()
        intake = self.write(workspace, 'rolling-restarts/intake.md')
        self.write(workspace, 'rolling-restarts/blueprint.md')
        self.write(workspace, 'blue-green/intake.md')
        self.assertTrue(gitstate.commit(workspace, 'Keep the intake', [intake]))
        self.assertEqual(self.committed(workspace.repo), ['trainings/rolling-restarts/intake.md'])
        self.assertEqual(gitstate.changed(workspace), ['trainings/blue-green/intake.md',
                                                       'trainings/rolling-restarts/blueprint.md'])
        self.assertTrue(gitstate.commit(workspace, 'Start blue-green', ['blue-green']))
        self.assertEqual(self.committed(workspace.repo), ['trainings/blue-green/intake.md'])
        self.assertFalse(gitstate.commit(workspace, 'Again', ['blue-green', intake]))

    def test_a_deleted_file_is_committed_as_gone(self):
        workspace = self.join()
        draft = self.write(workspace, 'rolling-restarts/draft.md')
        gitstate.commit(workspace, 'Keep a draft')
        draft.unlink()
        self.assertTrue(gitstate.commit(workspace, 'Discard the draft', [draft]))
        self.assertEqual(git(workspace.repo, 'ls-files', 'trainings/rolling-restarts'), '')

    def test_a_path_outside_the_folder_is_refused(self):
        self.other_tool({'README.md': THEIR_README})
        workspace = self.join()
        (workspace.repo / 'README.md').write_text('Changed.\n')
        self.write(workspace, 'rolling-restarts/intake.md')
        for path in ('../README.md', workspace.repo / 'README.md', workspace.repo,
                     'rolling-restarts/../../README.md', '/etc/hosts'):
            with self.subTest(path), self.assertRaisesRegex(
                    WorkspaceError, 'outside trainings/, the only folder the runner records'):
                gitstate.commit(workspace, 'Sneak', ['rolling-restarts/intake.md', path])
        self.assertEqual(git(workspace.repo, 'diff', '--cached', '--name-only'), '')
        self.assertEqual(git(workspace.repo, 'rev-list', '--count', 'HEAD'), '2')

    def test_working_files_sources_caches_and_locks_are_never_committed(self):
        workspace = self.join()
        kept = ['rolling-restarts/intake.md', 'rolling-restarts/.harness-research/research.json',
                'rolling-restarts/.training-studio/session.json', 'rolling-restarts/301/deck.pptx']
        left = ['rolling-restarts/work/attempt-1/draft.md', 'rolling-restarts/sources/page.txt',
                'rolling-restarts/sources/handbook.pdf', 'work/notes.md',
                'rolling-restarts/.harness-research/guidance/repository.git/HEAD',
                'rolling-restarts/301/.harness-slides/guidance/tasks/t1/SKILL.md',
                'rolling-restarts/.harness-research/research.lock',
                'rolling-restarts/.training-studio/lock']
        for name in kept + left:
            self.write(workspace, name)
        self.assertTrue(gitstate.commit(workspace, 'Keep what should be kept'))
        self.assertEqual(self.committed(workspace.repo),
                         sorted(f'trainings/{name}' for name in kept))
        self.assertEqual(gitstate.changed(workspace), [])
        with self.assertRaises(WorkspaceError):
            gitstate.commit(workspace, 'Force it', ['rolling-restarts/sources/page.txt'])
        self.assertTrue(all((workspace.root / name).is_file() for name in left))

    def test_a_commit_needs_a_message(self):
        workspace = self.join()
        self.write(workspace, 'rolling-restarts/intake.md')
        with self.assertRaisesRegex(WorkspaceError, 'needs a message'):
            gitstate.commit(workspace, '  ')

    def test_a_commit_without_a_git_identity_is_refused_with_the_fix(self):
        workspace = self.join()
        self.write(workspace, 'rolling-restarts/intake.md')
        self.nobody()
        with self.assertRaisesRegex(WorkspaceError, 'git does not know who you are.*git config '
                                    '--global user.name'):
            gitstate.commit(workspace, 'Keep the intake')
        self.assertEqual(git(workspace.repo, 'rev-list', '--count', 'HEAD'), '1')


class DiscardTests(WorkspaceCase):
    """Putting one training back as its last commit had it."""

    def test_what_a_step_left_half_made_is_put_back_and_the_rest_is_left(self):
        workspace = self.join()
        self.write(workspace, 'rolling-restarts/intake.md', 'As committed.\n')
        self.write(workspace, 'rolling-restarts/301/blueprint.md', 'As committed.\n')
        self.write(workspace, 'health-checks/intake.md', 'As committed.\n')
        gitstate.commit(workspace, 'Keep two trainings')
        self.write(workspace, 'rolling-restarts/intake.md', 'Half written.\n')
        (workspace.root / 'rolling-restarts' / '301' / 'blueprint.md').unlink()
        self.write(workspace, 'rolling-restarts/document.md', 'Never committed.\n')
        self.write(workspace, 'rolling-restarts/reviews/blueprint.md', 'Never committed.\n')
        git(workspace.repo, 'add', 'trainings/rolling-restarts/document.md')
        self.write(workspace, 'rolling-restarts/sources/page.txt', 'A saved page.\n')
        self.write(workspace, 'health-checks/intake.md', 'Someone is editing this.\n')
        (workspace.repo / 'README.md').write_text('# Another tool\n')
        lost = gitstate.discard(workspace, 'rolling-restarts')
        self.assertEqual(lost, [f'trainings/rolling-restarts/{name}' for name in (
            '301/blueprint.md', 'document.md', 'intake.md', 'reviews/blueprint.md')])
        root = workspace.training('rolling-restarts')
        self.assertEqual(((root / 'intake.md').read_text(),
                          (root / '301' / 'blueprint.md').read_text()),
                         ('As committed.\n', 'As committed.\n'))
        self.assertFalse((root / 'document.md').exists())
        self.assertFalse((root / 'reviews').exists())
        self.assertEqual((root / 'sources' / 'page.txt').read_text(), 'A saved page.\n',
                         'ignored files are left')
        self.assertEqual(gitstate.changed(workspace), ['trainings/health-checks/intake.md'])
        self.assertEqual((workspace.repo / 'README.md').read_text(), '# Another tool\n')
        self.assertEqual(gitstate.discard(workspace, 'rolling-restarts'), [])

    def test_a_training_that_was_never_committed_is_removed_whole(self):
        workspace = self.join()
        self.write(workspace, 'rolling-restarts/intake.md')
        self.write(workspace, 'rolling-restarts/.training-studio/session.json', '{}\n')
        git(workspace.repo, 'add', '-A', '--', 'trainings/rolling-restarts')
        self.assertEqual(len(gitstate.discard(workspace, workspace.training(
            'rolling-restarts'))), 2)
        self.assertFalse(workspace.training('rolling-restarts').exists())
        self.assertEqual(git(workspace.repo, 'status', '--porcelain'), '')

    def test_nothing_outside_the_folder_can_be_discarded(self):
        workspace = self.join()
        (workspace.repo / 'README.md').write_text('# Another tool\n')
        for path in ('../README.md', workspace.repo / 'README.md'):
            with self.subTest(path=path), self.assertRaisesRegex(
                    WorkspaceError, 'outside trainings/'):
                gitstate.discard(workspace, path)
        self.assertTrue((workspace.repo / 'README.md').exists())


class SyncTests(WorkspaceCase):
    def two_people(self):
        """Alex and Blake share a workspace; each has a clone of their own."""
        alex = self.join()
        self.assertTrue(gitstate.sync(alex)['shared'])
        self.be('blake')
        blake = self.join()
        self.be('alex')
        return alex, blake

    def test_sharing_pushes_what_was_committed_here(self):
        workspace = self.join()
        self.write(workspace, 'rolling-restarts/intake.md')
        gitstate.commit(workspace, 'Keep the intake of rolling-restarts')
        report = gitstate.sync(workspace)
        self.assertEqual(report, {'shared': True, 'reached': True, 'received': 0, 'unshared': 0,
                                  'conflict': [], 'notice': None})
        self.assertEqual(self.remote_head(), git(workspace.repo, 'rev-parse', 'HEAD'))
        self.assertEqual(gitstate.sync(workspace)['shared'], True)

    def test_two_peoples_work_on_different_trainings_is_replayed_not_merged(self):
        alex, blake = self.two_people()
        self.write(alex, 'rolling-restarts/intake.md')
        gitstate.commit(alex, 'Alex: keep the intake of rolling-restarts')
        self.assertTrue(gitstate.sync(alex)['shared'])
        self.be('blake')
        self.write(blake, 'blue-green/intake.md')
        gitstate.commit(blake, 'Blake: keep the intake of blue-green')
        report = gitstate.sync(blake)
        self.assertEqual((report['shared'], report['received'], report['unshared'],
                          report['notice']), (True, 1, 0, None))
        self.assertEqual(git(self.remote, 'log', '--format=%an', 'main').splitlines(),
                         ['Blake', 'Alex', 'Alex'])
        self.assertEqual(git(self.remote, 'rev-list', '--merges', 'main'), '')
        self.be('alex')
        self.assertEqual(gitstate.sync(alex)['received'], 1)
        self.assertTrue((alex.root / 'blue-green' / 'intake.md').is_file())

    def test_what_other_tools_push_comes_in_and_is_left_alone(self):
        workspace = self.join()
        gitstate.sync(workspace)
        self.other_tool({'hub.json': THEIR_HUB, 'decks/outline.md': b'One.\n'})
        self.write(workspace, 'rolling-restarts/intake.md')
        gitstate.commit(workspace, 'Keep the intake')
        report = gitstate.sync(workspace)
        self.assertEqual((report['shared'], report['received']), (True, 1))
        self.assertEqual((workspace.repo / 'hub.json').read_bytes(), THEIR_HUB)
        self.assertEqual(self.committed(workspace.repo), ['trainings/rolling-restarts/intake.md'])

    def test_a_conflict_is_undone_and_reported_and_nothing_is_forced(self):
        alex, blake = self.two_people()
        self.write(alex, 'rolling-restarts/intake.md', 'Alex wrote this.\n')
        gitstate.commit(alex, 'Alex: keep the intake')
        gitstate.sync(alex)
        theirs = self.remote_head()
        self.be('blake')
        self.write(blake, 'rolling-restarts/intake.md', 'Blake wrote this.\n')
        gitstate.commit(blake, 'Blake: keep the intake')
        mine = git(blake.repo, 'rev-parse', 'HEAD')
        report = gitstate.sync(blake)
        self.assertEqual((report['shared'], report['reached'], report['unshared']),
                         (False, True, 1))
        self.assertEqual(report['conflict'], ['trainings/rolling-restarts/intake.md'])
        self.assertIn('The same files were changed here and in the shared repository '
                      '(trainings/rolling-restarts/intake.md), and the runner will not choose',
                      report['notice'])
        self.assertIn('is not shared yet', report['notice'])
        self.assertEqual(self.remote_head(), theirs)
        self.assertEqual(git(blake.repo, 'rev-parse', 'HEAD'), mine)
        self.assertEqual((blake.root / 'rolling-restarts' / 'intake.md').read_text(),
                         'Blake wrote this.\n')
        self.assertEqual(git(blake.repo, 'status', '--porcelain'), '')
        self.assertFalse((blake.repo / '.git' / 'rebase-merge').exists())

    def test_a_remote_that_cannot_be_reached_keeps_the_work_here_and_says_so(self):
        workspace = self.join()
        self.write(workspace, 'rolling-restarts/intake.md')
        gitstate.commit(workspace, 'Keep the intake')
        self.remote.rename(self.base / 'unplugged.git')
        report = gitstate.sync(workspace)
        self.assertEqual((report['shared'], report['reached'], report['unshared']),
                         (False, False, 2))
        self.assertIn('The shared repository could not be reached (', report['notice'])
        self.assertIn('Your work is kept on this computer and is not shared yet. Share again '
                      'when it can be reached.', report['notice'])
        self.assertEqual(git(workspace.repo, 'rev-list', '--count', 'HEAD'), '2')
        (self.base / 'unplugged.git').rename(self.remote)
        self.assertTrue(gitstate.sync(workspace)['shared'])

    @unittest.skipIf(os.name == 'nt', 'an ssh on PATH is POSIX here')
    def test_a_host_ssh_does_not_know_yet_says_how_to_trust_it(self):
        workspace = self.join()
        tools = self.base / 'bin'
        tools.mkdir()
        ssh = tools / 'ssh'
        ssh.write_text('#!/bin/sh\necho "Host key verification failed." >&2\nexit 255\n')
        ssh.chmod(0o755)
        os.environ['PATH'] = f"{tools}{os.pathsep}{os.environ['PATH']}"
        for name in ('GIT_SSH_COMMAND', 'GIT_SSH'):
            os.environ.pop(name, None)
        git(workspace.repo, 'remote', 'set-url', 'origin', 'ssh://example.invalid/team.git')
        report = gitstate.sync(workspace)
        self.assertEqual((report['shared'], report['reached']), (False, False))
        self.assertIn('could not be reached', report['notice'])
        self.assertTrue(report['notice'].endswith(gitstate.TRUST), report['notice'])

    def test_a_remote_that_refuses_keeps_the_work_here_and_says_so(self):
        workspace = self.join()
        hook = self.remote / 'hooks' / 'pre-receive'
        hook.parent.mkdir(exist_ok=True)
        hook.write_text('#!/bin/sh\necho "pushes are closed today" >&2\nexit 1\n')
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
        report = gitstate.sync(workspace)
        self.assertEqual((report['shared'], report['reached'], report['unshared']),
                         (False, True, 1))
        self.assertIn('The shared repository did not accept the changes (', report['notice'])
        self.assertIn('are not shared yet. Check that you may push to it', report['notice'])
        self.assertEqual(git(self.remote, 'for-each-ref'), '')
        hook.unlink()
        self.assertTrue(gitstate.sync(workspace)['shared'])

    def test_unfinished_work_in_the_folder_is_still_there_after_sharing(self):
        alex, blake = self.two_people()
        self.write(alex, 'rolling-restarts/intake.md')
        gitstate.commit(alex, 'Alex: keep the intake')
        gitstate.sync(alex)
        self.be('blake')
        self.write(blake, 'blue-green/intake.md')
        gitstate.commit(blake, 'Blake: keep the intake')
        self.write(blake, 'blue-green/intake.md', 'Half-way through a change.\n')
        self.write(blake, 'blue-green/blueprint.md', 'Not kept yet.\n')
        self.assertTrue(gitstate.sync(blake)['shared'])
        self.assertEqual((blake.root / 'blue-green' / 'intake.md').read_text(),
                         'Half-way through a change.\n')
        self.assertEqual(gitstate.changed(blake), ['trainings/blue-green/blueprint.md',
                                                   'trainings/blue-green/intake.md'])
        self.assertEqual(git(blake.repo, 'stash', 'list'), '')

    def test_the_lock_is_held_for_this_copy_and_never_while_the_remote_is_asked(self):
        alex, blake = self.two_people()
        self.be('blake')
        self.write(blake, 'blue-green/intake.md')
        gitstate.commit(blake, 'Blake: keep the intake')
        gitstate.sync(blake)
        self.be('alex')
        self.write(alex, 'rolling-restarts/intake.md')
        gitstate.commit(alex, 'Alex: keep the intake')
        held, learned = Held(), []
        with asked(held) as ran:
            report = gitstate.sync(alex, before=lambda at: learned.append(held.depth), held=held)
        self.assertEqual((report['shared'], report['received']), (True, 1))
        self.assertEqual(learned, [1], 'what came in is learned while the lock is held')
        holding = {}
        for name, was in ran:
            holding.setdefault(name, set()).add(was)
        self.assertEqual({name: holding[name] for name in ('fetch', 'push', 'rebase')},
                         {'fetch': {False}, 'push': {False}, 'rebase': {True}})
        self.assertEqual(holding['rev-list'], {True})
        self.assertEqual(held.depth, 0)

    def test_what_is_replayed_on_is_what_was_learned_from_whatever_fetch_comes_between(self):
        """Another share's fetch can move the remote's ref while this one holds the lock.
        The replay stays on the commit `before` was shown, so nothing comes in unlearned."""
        workspace = self.join()
        gitstate.sync(workspace)
        self.other_tool({'first.md': b'First.\n'}, 'First')
        first = self.remote_head()
        self.write(workspace, 'rolling-restarts/intake.md')
        gitstate.commit(workspace, 'Keep the intake')
        shown, second = [], []

        def before(*at):
            shown.append(at[0] if at else None)
            if len(shown) == 1:   # meanwhile a teammate pushes, and another share fetches it
                self.other_tool({'second.md': b'Second.\n'}, 'Second')
                second.append(self.remote_head())
                git(workspace.repo, 'fetch', '--quiet', 'origin')

        report = gitstate.sync(workspace, before=before)
        self.assertEqual((report['shared'], report['received']), (True, 2))
        self.assertEqual(shown, [first, *second],
                         'the second commit was learned from before it was replayed on')
        self.assertEqual(git(workspace.repo, 'log', '-1', '--format=%s'), 'Keep the intake')

    def test_a_share_counts_the_commits_once_and_learns_only_when_something_came_in(self):
        workspace = self.join()
        gitstate.sync(workspace)
        self.write(workspace, 'rolling-restarts/intake.md')
        gitstate.commit(workspace, 'Keep the intake')
        learned = []
        with asked() as ran:
            report = gitstate.sync(workspace, before=lambda at: learned.append(True))
        self.assertEqual((report['shared'], report['unshared']), (True, 0))
        names = [name for name, _ in ran]
        self.assertEqual((names.count('rev-list'), names.count('push')), (1, 1))
        self.assertEqual(learned, [], 'nothing came in, so there was nothing to learn')
        with asked() as ran:
            self.assertTrue(gitstate.sync(workspace)['shared'])
        names = [name for name, _ in ran]
        self.assertEqual((names.count('rev-list'), names.count('push')), (1, 0))
        self.other_tool({'notes.md': b'Theirs.\n'})
        self.assertEqual(gitstate.sync(workspace, before=lambda at: learned.append(True))
                         ['received'], 1)
        self.assertEqual(learned, [True])

    def test_what_the_remote_changed_since_parting_is_found_in_two_commands(self):
        alex, blake = self.two_people()
        self.be('blake')
        self.write(blake, 'blue-green/intake.md')
        self.write(blake, 'blue-green/blueprint.md')
        gitstate.commit(blake, 'Blake: keep the intake')
        gitstate.sync(blake)
        self.be('alex')
        self.write(alex, 'rolling-restarts/intake.md')
        gitstate.commit(alex, 'Alex: keep the intake')
        self.assertEqual(gitstate.arrived(alex), set(), 'nothing is fetched to find it')
        git(alex.repo, 'fetch', '--quiet', 'origin')
        with asked() as ran:
            arrived = gitstate.arrived(alex)
        self.assertEqual(arrived, {'trainings/blue-green/blueprint.md',
                                   'trainings/blue-green/intake.md'})
        self.assertEqual([name for name, _ in ran], ['merge-base', 'diff'])
        self.assertTrue(gitstate.moved(alex, 'blue-green/intake.md'))
        self.assertFalse(gitstate.moved(alex, 'rolling-restarts/intake.md'))

    def test_sharing_from_the_wrong_branch_is_refused(self):
        workspace = self.join()
        git(workspace.repo, 'checkout', '--quiet', '-b', 'experiment')
        with self.assertRaisesRegex(WorkspaceError, 'is on the branch experiment, not main'):
            gitstate.sync(workspace)
        git(workspace.repo, 'checkout', '--quiet', '--detach')
        with self.assertRaisesRegex(WorkspaceError, 'is not on a branch'):
            gitstate.sync(workspace)

    def test_no_command_here_ever_forces_a_push(self):
        source = Path(gitstate.__file__).read_text()
        for never in ('--force', "'-f'", '+HEAD', '--mirror', 'reset', "'clean'"):
            self.assertNotIn(never, source.split('"""', 2)[2], never)


if __name__ == '__main__':
    unittest.main()
