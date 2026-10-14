"""Guidance sync, against a local git repository standing in for the public one."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers
import sync_guidance
import workspace


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                           *args], cwd=repo, capture_output=True, text=True, check=True)
    return done.stdout.strip()


class SyncCase(unittest.TestCase):
    """A remote repository holding the skill, a private data folder, and a training folder."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        base = Path(holder.name).resolve()
        self.remote = base / 'remote'
        self.project = base / 'valkey-training'
        self.project.mkdir()
        shutil.copytree(helpers.SKILL, self.remote / 'skills' / 'training-studio',
                        ignore=shutil.ignore_patterns('__pycache__'))
        self.manifest(minimum_runtime='0.1.0')
        git(self.remote, 'init', '--quiet')
        git(self.remote, 'symbolic-ref', 'HEAD', 'refs/heads/main')
        self.first = self.commit('first')
        patcher = mock.patch.dict(os.environ, {'TRAINING_STUDIO_DATA': str(base / 'data'),
                                               'TRAINING_STUDIO_SOURCE': str(self.remote)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def manifest(self, **changes) -> None:
        content = {'schema': 1, 'content_root': 'skills/training-studio', **changes}
        (self.remote / 'guidance').mkdir(exist_ok=True)
        (self.remote / 'guidance' / 'manifest.json').write_text(json.dumps(content))

    def commit(self, message: str) -> str:
        git(self.remote, 'add', '-A')
        git(self.remote, 'commit', '--quiet', '-m', message)
        return git(self.remote, 'rev-parse', 'HEAD')

    def change_remote(self, text: str = 'A newer entry.') -> str:
        entry = self.remote / 'skills' / 'training-studio' / 'SKILL.md'
        entry.write_text(entry.read_text() + f'\n{text}\n')
        return self.commit('newer guidance')

    def train(self) -> None:
        """Start a training here the way the helper does: resolve guidance, init, pin."""
        sync_guidance.start(self.project)
        workspace.init(self.project, 'Valkey')
        sync_guidance.adopt(self.project)


class StartTests(SyncCase):
    def test_start_fetches_the_newest_guidance_and_names_the_helper(self):
        result = sync_guidance.start(self.project)
        self.assertEqual((result['commit'], result['freshness'], result['pinned']),
                         (self.first, 'fetched', False))
        entry = Path(result['entry'])
        self.assertEqual(entry.read_text(), (helpers.SKILL / 'SKILL.md').read_text())
        self.assertTrue((entry.parent / 'references' / 'gates.md').is_file())
        self.assertTrue((entry.parent / 'assets' / 'profiles' / 'yoodli.json').is_file())
        self.assertFalse((entry.parent / 'scripts').exists())
        self.assertEqual(Path(result['helper']), helpers.SCRIPTS / 'training.py')
        self.assertIsNone(result['notice'])

    def test_the_helper_is_the_command_that_ran_this_when_there_is_one(self):
        command = self.project.parent / 'training'
        command.write_text('#!/bin/sh\n')
        with mock.patch.dict(os.environ, {'TRAINING_STUDIO_HELPER': str(command)}):
            self.assertEqual(sync_guidance.start(self.project)['helper'], str(command))
        with mock.patch.dict(os.environ, {'TRAINING_STUDIO_HELPER': str(command) + '-gone'}):
            self.assertEqual(Path(sync_guidance.start(self.project)['helper']),
                             helpers.SCRIPTS / 'training.py')

    def test_start_writes_nothing_into_a_directory_that_has_no_training(self):
        sync_guidance.start(self.project)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_a_second_start_uses_the_cache(self):
        sync_guidance.start(self.project)
        self.assertEqual(sync_guidance.start(self.project)['freshness'], 'cached')

    def test_scripts_are_never_fetched(self):
        entry = Path(sync_guidance.start(self.project)['entry'])
        self.assertEqual(sorted(path.name for path in entry.parent.iterdir()),
                         ['SKILL.md', 'assets', 'references'])


class PinTests(SyncCase):
    def test_a_new_training_is_pinned_to_the_guidance_it_started_with(self):
        self.train()
        pin = json.loads((self.project / '.training-studio' / 'guidance.json').read_text())
        self.assertEqual(pin['commit'], self.first)
        self.assertIn('SKILL.md', pin['files'])
        result = sync_guidance.start(self.project)
        self.assertEqual((result['freshness'], result['pinned'], result['commit']),
                         ('pinned', True, self.first))

    def test_a_pinned_training_stays_put_when_guidance_moves_on(self):
        self.train()
        newer = self.change_remote()
        pinned = sync_guidance.start(self.project)
        self.assertEqual(pinned['commit'], self.first)
        self.assertNotIn('A newer entry.', Path(pinned['entry']).read_text())
        elsewhere = self.project.parent / 'another-training'
        elsewhere.mkdir()
        fresh = sync_guidance.start(elsewhere)
        self.assertEqual(fresh['commit'], newer)
        self.assertIn('A newer entry.', Path(fresh['entry']).read_text())

    def test_update_moves_a_training_to_the_newest_guidance(self):
        self.train()
        newer = self.change_remote()
        result = sync_guidance.update(self.project)
        self.assertEqual(result['commit'], newer)
        self.assertIn('Run the checks again', result['notice'])
        self.assertEqual(sync_guidance.start(self.project)['commit'], newer)
        self.assertIsNone(sync_guidance.update(self.project)['notice'])

    def test_update_needs_a_training(self):
        with self.assertRaisesRegex(sync_guidance.SyncError, 'No training'):
            sync_guidance.update(self.project)

    def test_a_training_started_without_a_pin_gets_one_on_the_next_start(self):
        workspace.init(self.project, 'Valkey')
        result = sync_guidance.start(self.project)
        self.assertTrue(result['pinned'])
        self.assertEqual(sync_guidance.summary(self.project)['commit'], self.first)

    def test_a_damaged_cache_is_rebuilt_from_what_was_fetched(self):
        self.train()
        entry = Path(sync_guidance.start(self.project)['entry'])
        entry.write_text('tampered')
        self.change_remote()
        result = sync_guidance.start(self.project)
        self.assertEqual(result['freshness'], 'pinned')
        self.assertEqual(Path(result['entry']).read_text(),
                         (helpers.SKILL / 'SKILL.md').read_text())

    def test_the_training_uses_the_profile_from_its_pinned_guidance(self):
        self.train()
        entry = Path(sync_guidance.start(self.project)['entry'])
        self.assertEqual(workspace.profile_for(self.project),
                         entry.parent / 'assets' / 'profiles' / 'yoodli.json')
        self.assertEqual(workspace.profile_for(self.project.parent), workspace.PROFILE)


class FallbackTests(SyncCase):
    def test_an_unreachable_source_falls_back_to_the_installed_guidance_and_says_so(self):
        with mock.patch.dict(os.environ, {'TRAINING_STUDIO_SOURCE': str(self.remote / 'gone')}):
            result = sync_guidance.start(self.project)
        self.assertEqual((result['freshness'], result['commit']), ('installed', None))
        self.assertEqual(Path(result['entry']), helpers.SKILL / 'SKILL.md')
        self.assertIn('Could not get the newest guidance', result['notice'])
        self.assertIn('may be older', result['notice'])

    def test_guidance_that_needs_newer_scripts_is_not_used(self):
        self.manifest(minimum_runtime='99.0.0')
        self.commit('needs a newer runtime')
        result = sync_guidance.start(self.project)
        self.assertEqual(result['freshness'], 'installed')
        self.assertIn('needs Training Studio 99.0.0 or later', result['notice'])

    def test_a_manifest_this_version_does_not_understand_is_not_used(self):
        self.manifest(schema=2)
        self.commit('a newer manifest')
        result = sync_guidance.start(self.project)
        self.assertEqual(result['freshness'], 'installed')
        self.assertIn('not one this version understands', result['notice'])

    def test_a_training_pinned_while_offline_keeps_using_the_installed_guidance(self):
        with mock.patch.dict(os.environ, {'TRAINING_STUDIO_SOURCE': str(self.remote / 'gone')}):
            self.train()
        result = sync_guidance.start(self.project)
        self.assertEqual((result['freshness'], result['pinned']), ('installed', True))
        self.assertIsNone(result['notice'])


class CommandLineTests(SyncCase):
    def run_sync(self, *args, expect=0) -> dict:
        done = subprocess.run([sys.executable, str(helpers.SCRIPTS / 'sync_guidance.py'), *args],
                              cwd=self.project, capture_output=True, text=True)
        self.assertEqual(done.returncode, expect, done.stdout + done.stderr)
        return json.loads(done.stdout)

    def test_start_prints_json_from_the_training_directory(self):
        result = self.run_sync('start')
        self.assertEqual(result['commit'], self.first)
        self.assertTrue(Path(result['entry']).is_file())

    def test_a_failure_is_a_json_error(self):
        self.assertEqual(self.run_sync('update', expect=2),
                         {'error': 'No training in this directory.'})


class TrustCase(SyncCase):
    """A training, a cache or an environment someone else set up, and a marker file that any
    command planted there would create."""

    def setUp(self):
        super().setUp()
        self.marker = self.project.parent / 'planted-code-ran'
        self.addCleanup(lambda: self.assertFalse(self.marker.exists(), 'planted code ran'))
        self.cache = Path(os.environ['TRAINING_STUDIO_DATA']) / 'guidance' / 'cache.git'
        self.trusted = (helpers.SKILL / 'SKILL.md').read_text()

    def touch_marker(self) -> str:
        return f'#!/bin/sh\ntouch "{self.marker}"\n'

    def elsewhere(self) -> Path:
        """Another repository, holding guidance nobody should get."""
        other = self.project.parent / 'elsewhere'
        shutil.copytree(self.remote, other, ignore=shutil.ignore_patterns('.git'))
        (other / 'skills' / 'training-studio' / 'SKILL.md').write_text('Planted guidance.\n')
        git(other, 'init', '--quiet')
        git(other, 'add', '-A')
        git(other, 'commit', '--quiet', '-m', 'planted')
        return other

    def fork(self) -> str:
        """A commit in the source repository that was never on main, as a fork's would be."""
        git(self.remote, 'checkout', '--quiet', '-b', 'fork')
        (self.remote / 'skills' / 'training-studio' / 'SKILL.md').write_text('Fork guidance.\n')
        commit = self.commit('a fork')
        git(self.remote, 'checkout', '--quiet', 'main')
        return commit

    def plant_pin(self, commit, folder: Path | None = None) -> None:
        """A training that arrived with its own pin, naming a folder it also brought."""
        if not (self.project / '.training-studio' / 'session.json').is_file():
            workspace.init(self.project, 'Valkey')
        if folder is None:
            folder = self.project / 'brought-guidance'
            (folder / 'assets' / 'profiles').mkdir(parents=True, exist_ok=True)
            (folder / 'SKILL.md').write_text('Planted guidance.\n')
            (folder / 'assets' / 'profiles' / 'yoodli.json').write_text('{}')
        pin = {'schema': 1, 'commit': commit, 'path': str(folder),
               'files': sync_guidance.hashes(folder), 'runtime': '0.1.0',
               'pinned_at': '2026-01-01T00:00:00Z'}
        (self.project / '.training-studio' / 'guidance.json').write_text(json.dumps(pin))

    def assertTrusted(self, result: dict, commit: str) -> None:
        entry = Path(result['entry'])
        self.assertEqual(result['commit'], commit)
        self.assertEqual(entry.parent, self.cache.parent / commit)
        self.assertEqual(entry.read_text(), self.trusted)


class BroughtPinTests(TrustCase):
    def test_a_training_that_brings_its_own_guidance_gets_the_guidance_of_main(self):
        self.plant_pin(self.first)
        result = sync_guidance.start(self.project)
        self.assertTrusted(result, self.first)
        self.assertEqual((result['freshness'], result['pinned']), ('pinned', True))
        self.assertEqual(workspace.profile_for(self.project),
                         self.cache.parent / self.first / 'assets' / 'profiles' / 'yoodli.json')

    def test_a_folder_that_matches_the_pin_but_not_the_commit_is_not_used(self):
        self.train()
        served = Path(sync_guidance.start(self.project)['entry']).parent
        (served / 'SKILL.md').write_text('Planted guidance.\n')
        self.plant_pin(self.first, served)          # the pin's hashes now agree with the folder
        self.assertTrusted(sync_guidance.resume(self.project), self.first)

    def test_a_pin_naming_a_commit_that_was_never_on_main_is_refused(self):
        fork = self.fork()
        self.plant_pin(fork)
        for action in (sync_guidance.start, sync_guidance.resume):
            with self.assertRaisesRegex(sync_guidance.SyncError, 'not on the main branch'):
                action(self.project)
        self.assertFalse((self.cache.parent / fork).exists())
        self.assertEqual(workspace.profile_for(self.project), workspace.PROFILE)

    def test_a_pin_whose_commit_is_not_a_commit_id_cannot_be_read(self):
        for commit in ('../../brought-guidance', self.first[:12], 42):
            self.plant_pin(commit)
            with self.assertRaisesRegex(sync_guidance.SyncError, 'cannot be read'):
                sync_guidance.start(self.project)
            self.assertEqual(workspace.profile_for(self.project), workspace.PROFILE)

    def test_a_pin_from_an_older_version_resumes_on_the_same_commit(self):
        # What an older version left: a shallow cache with git's default config, a folder named
        # by twelve digits of the commit, and a pin that names that folder.
        self.cache.mkdir(parents=True)
        git(self.cache, 'init', '--quiet', '--bare')
        git(self.cache, 'fetch', '--quiet', '--depth', '1', f'file://{self.remote}', 'main')
        old = self.cache.parent / self.first[:12]
        shutil.copytree(helpers.SKILL, old,
                        ignore=shutil.ignore_patterns('scripts', '__pycache__', 'VERSION'))
        self.plant_pin(self.first, old)
        self.change_remote()
        result = sync_guidance.start(self.project)
        self.assertTrusted(result, self.first)
        self.assertEqual(result['freshness'], 'pinned')

    def test_a_commit_an_older_version_fetched_by_id_is_refused(self):
        fork = self.fork()
        self.cache.mkdir(parents=True)
        git(self.cache, 'init', '--quiet', '--bare')
        git(self.cache, 'fetch', '--quiet', str(self.remote), fork)
        self.plant_pin(fork)
        with self.assertRaisesRegex(sync_guidance.SyncError, 'not on the main branch'):
            sync_guidance.start(self.project)

    def test_a_pinned_training_resumes_with_no_network(self):
        self.train()
        shutil.rmtree(self.cache.parent / self.first)
        with mock.patch.dict(os.environ, {'TRAINING_STUDIO_SOURCE': str(self.remote / 'gone')}):
            result = sync_guidance.start(self.project)
        self.assertTrusted(result, self.first)
        self.assertIsNone(result['notice'])

    def test_a_brought_pin_falls_back_to_the_installed_guidance_when_main_is_out_of_reach(self):
        self.plant_pin(self.fork())
        with mock.patch.dict(os.environ, {'TRAINING_STUDIO_SOURCE': str(self.remote / 'gone')}):
            result = sync_guidance.start(self.project)
        self.assertEqual((result['freshness'], result['commit']), ('installed', None))
        self.assertEqual(Path(result['entry']), helpers.SKILL / 'SKILL.md')
        self.assertIn('could not be fetched', result['notice'])

    def test_the_refusal_is_a_json_error_on_the_command_line(self):
        self.plant_pin(self.fork())
        done = subprocess.run([sys.executable, str(helpers.SCRIPTS / 'sync_guidance.py'),
                               'start'], cwd=self.project, capture_output=True, text=True)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn('not on the main branch', json.loads(done.stdout)['error'])


class PlantedCacheTests(TrustCase):
    """The cache is in the data folder, not in a training, but it is only ever used as this
    helper made it."""

    def configure(self, key: str, value: str) -> None:
        git(self.cache, 'config', '--file', str(self.cache / 'config'), key, value)

    def newest(self) -> str:
        newer = self.change_remote()
        self.trusted = (self.remote / 'skills' / 'training-studio' / 'SKILL.md').read_text()
        return newer

    def test_a_cache_that_sends_main_elsewhere_is_rebuilt(self):
        sync_guidance.start(self.project)
        self.configure(f'url.{self.elsewhere()}.insteadOf', str(self.remote))
        newer = self.newest()
        self.assertTrusted(sync_guidance.start(self.project), newer)

    def test_a_cache_that_runs_a_command_in_place_of_a_fetch_runs_nothing(self):
        sync_guidance.start(self.project)
        self.configure(f'url.ext::sh -c touch% {self.marker}.insteadOf', str(self.remote))
        self.configure('protocol.ext.allow', 'always')
        newer = self.newest()
        self.assertTrusted(sync_guidance.start(self.project), newer)

    def test_hooks_and_fsmonitor_in_the_cache_do_not_run(self):
        sync_guidance.start(self.project)
        hooks = self.cache / 'hooks'
        hooks.mkdir(exist_ok=True)
        for name in ('reference-transaction', 'post-checkout', 'pre-auto-gc', 'post-merge'):
            (hooks / name).write_text(self.touch_marker())
            (hooks / name).chmod(0o755)
        self.configure('core.hooksPath', str(hooks))
        self.configure('core.fsmonitor', str(hooks / 'reference-transaction'))
        newer = self.newest()
        self.assertTrusted(sync_guidance.start(self.project), newer)

    def test_a_replace_ref_does_not_swap_the_guidance(self):
        self.train()
        other = self.elsewhere()
        git(self.cache, 'fetch', '--quiet', str(other), '+HEAD:refs/heads/planted')
        git(self.cache, 'replace', self.first, git(self.cache, 'rev-parse', 'refs/heads/planted'))
        shutil.rmtree(self.cache.parent / self.first)
        self.assertTrusted(sync_guidance.start(self.project), self.first)

    def test_alternates_do_not_lend_the_cache_objects_from_elsewhere(self):
        self.train()
        other = self.elsewhere()
        alternates = self.cache / 'objects' / 'info' / 'alternates'
        alternates.write_text(str(other / '.git' / 'objects') + '\n')
        self.assertTrusted(sync_guidance.start(self.project), self.first)
        self.assertFalse(alternates.exists())

    def test_git_run_by_the_helper_ignores_hooks_and_fsmonitor_in_any_repository(self):
        planted = self.project.parent / 'planted.git'
        git(self.project.parent, 'init', '--quiet', '--bare', str(planted))
        hook = planted / 'hooks' / 'reference-transaction'
        hook.write_text(self.touch_marker())
        hook.chmod(0o755)
        git(planted, 'config', 'core.fsmonitor', str(hook))
        git(planted, 'fetch', '--quiet', str(self.remote), '+main:refs/heads/a')
        self.assertTrue(self.marker.exists(), 'plain git should run the hook')
        self.marker.unlink()
        sync_guidance.git('fetch', '--quiet', str(self.remote), '+main:refs/heads/b',
                          repo=planted)


class PlantedEnvironmentTests(TrustCase):
    def test_global_config_and_git_variables_are_ignored(self):
        other = self.elsewhere()
        home = self.project.parent / 'home'
        hooks = home / 'hooks'
        hooks.mkdir(parents=True)
        (hooks / 'reference-transaction').write_text(self.touch_marker())
        (hooks / 'reference-transaction').chmod(0o755)
        config = helpers.gitconfig(home / '.gitconfig',
                                   f'[url "{other}"]\n\tinsteadOf = {self.remote}\n'
                                   f'[core]\n\thooksPath = {hooks}\n')
        planted = {'HOME': str(home), 'XDG_CONFIG_HOME': str(home),
                   'GIT_CONFIG_GLOBAL': str(config), 'GIT_CONFIG_COUNT': '1',
                   'GIT_CONFIG_KEY_0': f'url.{other}.insteadOf',
                   'GIT_CONFIG_VALUE_0': str(self.remote),
                   'GIT_DIR': str(other / '.git'),
                   'GIT_ALTERNATE_OBJECT_DIRECTORIES': str(other / '.git' / 'objects')}
        with mock.patch.dict(os.environ, planted):
            self.assertTrusted(sync_guidance.start(self.project), self.first)

    def test_a_source_that_is_not_https_or_a_file_is_not_fetched(self):
        command = f'ext::sh -c touch% {self.marker}'
        with mock.patch.dict(os.environ, {'TRAINING_STUDIO_SOURCE': command}):
            result = sync_guidance.start(self.project)
        self.assertEqual(result['freshness'], 'installed')
