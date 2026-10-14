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
