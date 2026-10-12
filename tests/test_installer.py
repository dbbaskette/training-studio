"""The installer, run against a temporary home directory. Nothing real is touched."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import helpers

sys.path.insert(0, str(helpers.REPO / 'installer'))
import install  # noqa: E402


class InstallerCase(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.base = Path(holder.name).resolve()
        self.home = self.base / 'home'
        self.root = self.home / '.local' / 'share' / 'training-studio'
        self.claude = self.home / '.claude' / 'skills'
        self.codex = self.home / '.agents' / 'skills'
        self.claude.mkdir(parents=True)
        self.codex.mkdir(parents=True)

    def run_installer(self, *args, expect=0) -> dict:
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = install.main([*args, '--home', str(self.home), '--json'])
        self.assertEqual(code, expect, printed.getvalue())
        return json.loads(printed.getvalue())

    def copy_of_the_skill(self, version: str) -> Path:
        """A changed copy of the skill, standing in for a later release."""
        source = self.base / f'source-{version}'
        shutil.copytree(helpers.SKILL, source, ignore=shutil.ignore_patterns('__pycache__'))
        (source / 'VERSION').write_text(version + '\n', encoding='utf-8')
        return source


class InstallTests(InstallerCase):
    def test_install_copies_the_skill_and_links_every_assistant_found(self):
        result = self.run_installer('install', '--yes')
        self.assertEqual(result['mode'], 'managed')
        staged = self.root / 'versions' / result['version']
        self.assertTrue((staged / 'SKILL.md').is_file())
        self.assertEqual(os.readlink(self.root / 'current'), str(staged))
        for link in (self.claude / 'training-studio', self.codex / 'training-studio'):
            self.assertEqual(os.readlink(link), str(self.root / 'current'))
            self.assertTrue((link / 'scripts' / 'training.py').is_file())
        self.assertFalse(list(staged.rglob('__pycache__')))
        state = json.loads((self.root / 'installation.json').read_text())
        self.assertEqual(state['history'], [result['version']])

    def test_the_version_names_the_exact_files(self):
        result = self.run_installer('install', '--yes')
        version = (helpers.SKILL / 'VERSION').read_text().strip()
        self.assertTrue(result['version'].startswith(version + '-'))
        self.assertEqual(result['version'], install.package_key(helpers.SKILL))

    def test_only_assistants_with_a_skill_folder_are_linked_by_default(self):
        shutil.rmtree(self.codex)
        result = self.run_installer('install', '--yes')
        self.assertEqual(list(result['links']), ['claude'])
        self.assertFalse(self.codex.exists())

    def test_a_named_assistant_gets_its_folder_created(self):
        shutil.rmtree(self.codex)
        shutil.rmtree(self.claude)
        refusal = self.run_installer('install', '--yes', expect=1)
        self.assertIn('No skill folder was found', refusal['error'])
        self.run_installer('install', '--yes', '--target', 'codex')
        self.assertTrue((self.codex / 'training-studio' / 'SKILL.md').is_file())
        self.assertFalse(self.claude.exists())

    def test_installing_again_changes_nothing(self):
        first = self.run_installer('install', '--yes')
        second = self.run_installer('install', '--yes')
        self.assertEqual(first['version'], second['version'])
        state = json.loads((self.root / 'installation.json').read_text())
        self.assertEqual(state['history'], [first['version']])
        self.assertEqual(len(list((self.root / 'versions').iterdir())), 1)

    def test_changes_need_yes_when_nobody_can_be_asked(self):
        refusal = self.run_installer('install', expect=1)
        self.assertEqual(refusal['error'], 'Add --yes to make changes without being asked.')
        self.assertFalse(self.root.exists())

    def test_a_dry_run_changes_nothing(self):
        plan = self.run_installer('install', '--dry-run')
        self.assertEqual(plan['action'], 'plan')
        self.assertEqual(plan['harnesses'], ['claude', 'codex'])
        self.assertFalse(self.root.exists())
        self.assertEqual(list(self.claude.iterdir()), [])

    def test_a_broken_package_is_refused_before_anything_changes(self):
        source = self.copy_of_the_skill('9.9.9')
        (source / 'references' / 'gates.md').unlink()
        refusal = self.run_installer('install', '--yes', '--source', str(source), expect=1)
        self.assertIn('The package is not whole', refusal['error'])
        self.assertFalse(self.root.exists())

    def test_a_folder_that_is_not_a_package_is_refused(self):
        refusal = self.run_installer('install', '--yes', '--source', str(self.base), expect=1)
        self.assertIn('is not a Training Studio skill package', refusal['error'])


class ExistingLinkTests(InstallerCase):
    def test_an_existing_link_is_replaced_and_remembered(self):
        elsewhere = self.base / 'checkout'
        elsewhere.mkdir()
        (self.claude / 'training-studio').symlink_to(elsewhere)
        result = self.run_installer('install', '--yes')
        self.assertEqual(result['links']['claude']['previous'], str(elsewhere))
        self.assertEqual(os.readlink(self.claude / 'training-studio'), str(self.root / 'current'))

    def test_a_real_folder_in_the_way_is_left_alone(self):
        mine = self.claude / 'training-studio'
        mine.mkdir()
        (mine / 'notes.txt').write_text('mine')
        refusal = self.run_installer('install', '--yes', expect=1)
        self.assertIn('exist and are not links', refusal['error'])
        self.assertEqual((mine / 'notes.txt').read_text(), 'mine')
        self.assertFalse((self.root / 'current').exists())
        self.assertFalse((self.codex / 'training-studio').exists())

    def test_replace_moves_a_real_folder_aside_and_never_deletes_it(self):
        mine = self.claude / 'training-studio'
        mine.mkdir()
        (mine / 'notes.txt').write_text('mine')
        result = self.run_installer('install', '--yes', '--replace')
        backup = Path(result['links']['claude']['backup'])
        self.assertEqual((backup / 'notes.txt').read_text(), 'mine')
        self.assertTrue(mine.is_symlink())


class LinkModeTests(InstallerCase):
    def test_link_mode_points_at_the_checkout_and_copies_nothing(self):
        result = self.run_installer('install', '--yes', '--link')
        self.assertEqual(result['mode'], 'link')
        self.assertEqual(os.readlink(self.claude / 'training-studio'), str(helpers.SKILL))
        self.assertFalse((self.root / 'versions').exists())

    def test_link_mode_has_nothing_to_roll_back(self):
        self.run_installer('install', '--yes', '--link')
        refusal = self.run_installer('rollback', '--yes', expect=1)
        self.assertIn('no managed installation', refusal['error'])


class RollbackTests(InstallerCase):
    def test_rollback_returns_to_the_version_before(self):
        first = self.run_installer('install', '--yes')
        second = self.run_installer('install', '--yes', '--source',
                                    str(self.copy_of_the_skill('9.9.9')))
        self.assertTrue(second['version'].startswith('9.9.9-'))
        self.assertEqual((self.claude / 'training-studio' / 'VERSION').read_text(), '9.9.9\n')
        back = self.run_installer('rollback', '--yes')
        self.assertEqual((back['version'], back['left']), (first['version'], second['version']))
        self.assertEqual(os.readlink(self.root / 'current'),
                         str(self.root / 'versions' / first['version']))
        self.assertTrue((self.root / 'versions' / second['version']).is_dir())

    def test_rollback_needs_an_earlier_version(self):
        self.run_installer('install', '--yes')
        refusal = self.run_installer('rollback', '--yes', expect=1)
        self.assertIn('only one version has been installed', refusal['error'])


class UninstallTests(InstallerCase):
    def test_uninstall_removes_its_links_and_keeps_the_versions(self):
        self.run_installer('install', '--yes')
        result = self.run_installer('uninstall', '--yes')
        self.assertEqual(len(result['removed']), 2)
        self.assertFalse((self.claude / 'training-studio').is_symlink())
        self.assertFalse((self.root / 'current').is_symlink())
        self.assertFalse((self.root / 'installation.json').exists())
        self.assertTrue(Path(result['versions_kept_in']).is_dir())

    def test_uninstall_leaves_a_link_someone_else_changed(self):
        self.run_installer('install', '--yes')
        link = self.claude / 'training-studio'
        link.unlink()
        link.symlink_to(self.base)
        result = self.run_installer('uninstall', '--yes')
        self.assertEqual(result['left_alone'], [str(link)])
        self.assertTrue(link.is_symlink())

    def test_uninstall_with_nothing_installed_says_so(self):
        refusal = self.run_installer('uninstall', '--yes', expect=1)
        self.assertIn('is not installed here', refusal['error'])


class CheckTests(InstallerCase):
    def test_check_before_and_after_install(self):
        before = self.run_installer('check')
        self.assertEqual((before['installed'], before['links']),
                         (False, {'claude': 'not linked', 'codex': 'not linked'}))
        installed = self.run_installer('install', '--yes')
        after = self.run_installer('check')
        self.assertEqual((after['installed'], after['version'], after['links']),
                         (True, installed['version'], {'claude': 'ok', 'codex': 'ok'}))

    def test_check_notices_a_link_that_was_moved(self):
        self.run_installer('install', '--yes')
        link = self.codex / 'training-studio'
        link.unlink()
        link.symlink_to(self.base)
        self.assertEqual(self.run_installer('check')['links']['codex'],
                         'points somewhere this installer did not put it')

    def test_missing_companion_skills_are_named_with_where_to_get_them(self):
        (self.claude / 'harness-research').mkdir()
        result = self.run_installer('install', '--yes', '--target', 'claude')
        self.assertEqual(result['companions'],
                         {'claude': {'harness-research': True, 'harness-slides': False}})
        slides = [note for note in result['notes'] if note.startswith('harness-slides')]
        self.assertEqual(len(slides), 1)
        self.assertIn('https://github.com/dbbaskette/harness-slides-skill', slides[0])
        self.assertFalse(any(note.startswith('harness-research') for note in result['notes']))

    def test_the_plain_report_is_for_a_person(self):
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            install.main(['install', '--yes', '--home', str(self.home)])
        text = printed.getvalue()
        self.assertIn('is installed.', text)
        self.assertIn('Claude Code:', text)
        self.assertIn('Next: make a folder for a topic', text)


class InstalledCopyTests(InstallerCase):
    def test_the_installed_helper_refuses_to_start_a_training_above_itself(self):
        self.run_installer('install', '--yes')
        helper = self.claude / 'training-studio' / 'scripts' / 'training.py'
        import subprocess
        asked = subprocess.run([sys.executable, str(helper), '--dir', str(self.home), 'init',
                                '--title', 'Topic'], capture_output=True, text=True)
        self.assertEqual(asked.returncode, 2)
        self.assertIn('holds the Training Studio skill', asked.stdout)
        elsewhere = self.base / 'valkey-training'
        elsewhere.mkdir()
        made = subprocess.run([sys.executable, str(helper), '--dir', str(elsewhere), 'init',
                               '--title', 'Topic'], capture_output=True, text=True)
        self.assertEqual(made.returncode, 0, made.stdout)
