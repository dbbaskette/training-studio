"""The installer, run against a temporary home directory. Nothing real is touched, and
nothing is fetched from anywhere but a repository a test made."""
import contextlib
import io
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

sys.path.insert(0, str(helpers.REPO / 'installer'))
import install  # noqa: E402

NODE = shutil.which('node')
COMPANIONS = ('harness-research', 'harness-slides')
# A companion's own installer, as small as it can be and still do what a real one does: a
# shared copy whose entry is the stub, and a link to it for every assistant it knows. Like a
# real one it reads the home folder from the environment as well as from --home, so it
# refuses when the two differ rather than write anywhere a test did not name.
INSTALLER = """import { cpSync, mkdirSync, copyFileSync, symlinkSync, readFileSync, rmSync, lstatSync }
  from 'node:fs';
import { join, dirname } from 'node:path';
import { homedir } from 'node:os';
import { fileURLToPath } from 'node:url';
const at = process.argv.indexOf('--home');
const home = at > 0 ? process.argv[at + 1] : null;
if (home !== homedir()) { console.error('The home given is not the home in use.'); process.exit(1); }
const source = join(dirname(fileURLToPath(import.meta.url)), '..');
const pkg = JSON.parse(readFileSync(join(source, 'package.json'), 'utf8'));
if (pkg.refuses) { console.error('Existing unrelated skill: stand-in'); process.exit(1); }
const shared = join(homedir(), '.local', 'share', pkg.name);
const runtime = join(shared, 'versions', pkg.version);
mkdirSync(runtime, { recursive: true });
cpSync(source, runtime, { recursive: true });
copyFileSync(join(source, 'bootstrap', 'SKILL.md'), join(runtime, 'SKILL.md'));
rmSync(join(shared, 'current'), { force: true });
symlinkSync(join('versions', pkg.version), join(shared, 'current'));
for (const folder of ['.agents', '.claude', '.cursor']) {
  const target = join(home, folder, 'skills', pkg.name);
  mkdirSync(dirname(target), { recursive: true });
  try { lstatSync(target); } catch { symlinkSync(join(shared, 'current'), target); }
}
console.log(JSON.stringify({ status: 'installed', runtimeVersion: pkg.version }));
"""
_made = {}


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(['git', '-c', 'user.name=A Test', '-c', 'user.email=test@example.com',
                           *args], cwd=cwd, check=True, capture_output=True, text=True)
    return done.stdout.strip()


class StandIn:
    """A local stand-in for a companion's repository: a bare repository a test made."""

    def __init__(self, base: Path, name: str):
        self.name, self.bare, self.work = name, base / f'{name}.git', base / f'{name}-work'
        git(base, 'init', '-q', '--bare', str(self.bare))
        git(base, 'init', '-q', str(self.work))

    def release(self, version: str, stub_names: str | None = None, **package) -> str:
        """Commit one release and return its commit."""
        files = {
            'package.json': json.dumps({'name': self.name, 'version': version, **package}),
            'SKILL.md': f'---\nname: {self.name}\n---\n\nThe whole skill, {version}.\n',
            'bootstrap/SKILL.md': f'---\nname: {stub_names or self.name}\n---\n\n'
                                  f'The small entry of {version}.\n',
            'scripts/install.mjs': INSTALLER,
            f'scripts/{self.name}.mjs': '// the command of the skill\n',
        }
        for name, text in files.items():
            (self.work / name).parent.mkdir(parents=True, exist_ok=True)
            (self.work / name).write_text(text, encoding='utf-8')
        git(self.work, 'add', '-A')
        git(self.work, 'commit', '-q', '-m', f'Release {version}')
        git(self.work, 'push', '-q', str(self.bare), 'HEAD:refs/heads/main')
        return git(self.work, 'rev-parse', 'HEAD')


def write_pins(path: Path, pins: dict) -> None:
    path.write_text(json.dumps({'schema': 1, 'companions': pins}, indent=2), encoding='utf-8')


def setUpModule():
    """Make each companion's stand-in repository once, and pin it as a maintainer would."""
    holder = tempfile.TemporaryDirectory()
    unittest.addModuleCleanup(holder.cleanup)
    base = Path(holder.name).resolve()
    pins = {}
    for name, version in zip(COMPANIONS, ('0.8.0', '0.13.1')):
        _made[name] = StandIn(base, name)
        commit = _made[name].release(version)
        pins[name] = {'repository': str(_made[name].bare), 'version': '0.0.0',
                      'commit': '0' * 40, 'sha256': '0' * 64, 'stub': 'bootstrap/SKILL.md',
                      'installer': 'scripts/install.mjs'}
        write_pins(base / 'companions.json', pins)
        install.pin(base / 'companions.json', name, commit)
        pins = install.read_pins(base / 'companions.json')
    _made['pins'] = pins


class InstallerCase(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.base = Path(holder.name).resolve()
        self.home = self.base / 'home'
        self.root = self.home / '.local' / 'share' / 'training-studio'
        self.addCleanup(os.chdir, os.getcwd())
        self.claude = self.home / '.claude' / 'skills'
        self.codex = self.home / '.agents' / 'skills'
        self.claude.mkdir(parents=True)
        self.codex.mkdir(parents=True)
        self.pins_file = self.base / 'companions.json'
        self.pins = json.loads(json.dumps(_made['pins']))
        write_pins(self.pins_file, self.pins)
        # What this computer answers when asked: everything in place, until a test says not.
        self.answers = {('git', '--version'): (0, 'git version 2.50.0'),
                        ('git', 'config', '--get', 'user.name'): (0, 'A Test'),
                        ('git', 'config', '--get', 'user.email'): (0, 'test@example.com'),
                        ('claude', '--version'): (0, '2.1.0 (Claude Code)'),
                        ('node', '--version'): (0, 'v22.1.0')}
        self.brand, self.asks_the_runner = True, install.brand_skill
        for patch in (mock.patch.object(install, 'PINS', self.pins_file),
                      mock.patch.object(install, 'PLATFORM', 'linux'),
                      mock.patch.object(install, 'ask', lambda command, cwd=None, timeout=20:
                                        self.answers.get(tuple(command))),
                      mock.patch.object(install, 'brand_skill', lambda home: self.brand),
                      mock.patch.dict(os.environ)):
            patch.start()
            self.addCleanup(patch.stop)
        os.environ.pop('BRAND_SKILL_RUNTIME', None)

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

    def repin(self, name: str, commit: str) -> None:
        install.pin(self.pins_file, name, commit)
        self.pins = install.read_pins(self.pins_file)

    def a_stopped_process(self) -> int:
        done = subprocess.Popen([sys.executable, '-c', 'pass'])
        done.wait()
        return done.pid


class InstallTests(InstallerCase):
    def test_install_copies_the_skill_and_links_every_assistant_found(self):
        result = self.run_installer('install', '--yes')
        self.assertEqual(result['mode'], 'managed')
        staged = self.root / 'versions' / result['version']
        self.assertIn('training-studio/training guidance start',
                      (staged / 'SKILL.md').read_text())
        self.assertTrue((staged / 'guidance' / 'references' / 'gates.md').is_file())
        self.assertTrue((staged / 'guidance' / 'assets' / 'profiles' / 'yoodli.json').is_file())
        self.assertFalse((staged / 'references').exists())
        self.assertIn('github.com', (staged / 'source.json').read_text())
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
        staged = self.root / 'versions' / result['version']
        self.assertEqual(result['version'], install.package_key(staged))

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

    def test_the_plain_report_is_for_a_person(self):
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            install.main(['install', '--yes', '--home', str(self.home)])
        text = printed.getvalue()
        self.assertIn('is installed, the runner with it.', text)
        self.assertIn('Claude Code:', text)
        self.assertIn('To open Training Studio:\n  Run: sh ', text)
        self.assertIn('Next: open Training Studio and press "New training".', text)


class InstalledCopyTests(InstallerCase):
    def test_the_installed_helper_refuses_to_start_a_training_above_itself(self):
        self.run_installer('install', '--yes')
        helper = self.claude / 'training-studio' / 'scripts' / 'training.py'
        asked = subprocess.run([sys.executable, str(helper), '--dir', str(self.home), 'init',
                                '--title', 'Topic'], capture_output=True, text=True)
        self.assertEqual(asked.returncode, 2)
        self.assertIn('holds the Training Studio skill', asked.stdout)
        elsewhere = self.base / 'valkey-training'
        elsewhere.mkdir()
        made = subprocess.run([sys.executable, str(helper), '--dir', str(elsewhere), 'init',
                               '--title', 'Topic', '--yoodli'], capture_output=True, text=True)
        self.assertEqual(made.returncode, 0, made.stdout)

    def test_the_installed_helper_finds_the_profile_in_its_guidance_folder(self):
        self.run_installer('install', '--yes')
        scripts = self.claude / 'training-studio' / 'scripts'
        found = subprocess.run([sys.executable, '-c',
                                'import workspace; print(workspace.PROFILE.is_file())'],
                               cwd=scripts, capture_output=True, text=True)
        self.assertEqual(found.stdout.strip(), 'True', found.stderr)


class RunnerTests(InstallerCase):
    def core_found_from(self, folder: Path) -> Path:
        """Where the runner in a folder finds the helper's modules, asked of the runner."""
        asked = subprocess.run([sys.executable, '-B', '-c',
                                'import runner, workspace; print(runner.CORE)'],
                               cwd=folder, capture_output=True, text=True)
        self.assertEqual(asked.returncode, 0, asked.stderr)
        return Path(asked.stdout.strip())

    def test_the_runner_is_installed_with_the_version_beside_the_helper(self):
        result = self.run_installer('install', '--yes')
        staged = self.root / 'versions' / result['version']
        for name in ('studio.py', '__init__.py', 'engine.py', 'briefs',
                     'claude-code-models.json'):
            self.assertTrue((staged / 'runner' / name).exists(), name)
        self.assertTrue((staged / 'scripts' / 'workspace.py').is_file())
        self.assertFalse(list((staged / 'runner').rglob('__pycache__')))
        self.assertEqual(result['runner']['installed'], True)
        state = json.loads((self.root / 'installation.json').read_text())
        self.assertEqual(state['runner'], str(self.root / 'current' / 'runner' / 'studio.py'))

    def test_each_version_keeps_this_installer_and_the_pins_it_was_installed_with(self):
        result = self.run_installer('install', '--yes')
        staged = self.root / 'versions' / result['version']
        # Beside the runner, where they are in a checkout too: the runner asks them when it
        # starts whether the skills are in place, and brings a companion with them.
        self.assertEqual((staged / 'installer' / 'install.py').read_bytes(),
                         (helpers.REPO / 'installer' / 'install.py').read_bytes())
        self.assertEqual(install.read_pins(staged / 'installer' / 'companions.json'),
                         self.pins)
        self.assertEqual(set(path.name for path in (staged / 'installer').iterdir()),
                         {'install.py', 'companions.json'})

    def test_the_runner_finds_the_helper_in_a_checkout_and_in_an_installed_version(self):
        result = self.run_installer('install', '--yes')
        staged = self.root / 'versions' / result['version']
        self.assertEqual(self.core_found_from(staged), staged / 'scripts')
        self.assertEqual(self.core_found_from(helpers.REPO), helpers.SCRIPTS)

    @unittest.skipUnless(NODE, 'a companion installs itself with Node')
    def test_the_installed_runner_finds_the_helper_the_companions_and_where_a_brand_is(self):
        self.run_installer('install', '--yes', '--companions', 'install')
        installed = self.root / 'current'
        self.assertFalse((installed / 'skills').exists(), 'the installed layout, not a checkout')
        brand = self.claude / 'example-brand'
        brand.mkdir()
        env = {name: value for name, value in os.environ.items()
               if not name.endswith('_RUNTIME')}
        asked = subprocess.run(
            [sys.executable, '-B', '-c', (
                'import json, runner\n'
                'from runner import brand, research, slides, studio\n'
                'print(json.dumps({"core": str(runner.CORE),'
                ' "research": str(research.find_runtime()),'
                ' "slides": str(slides.find_runtime()),'
                ' "brand": [str(place) for place in brand.locations()],'
                ' "opens": studio.parser().parse_args(["serve", "--open"]).open}))')],
            cwd=installed, capture_output=True, text=True,
            env={**env, 'HOME': str(self.home), 'USERPROFILE': str(self.home)})
        self.assertEqual(asked.returncode, 0, asked.stderr)
        found = json.loads(asked.stdout)
        shared = self.home / '.local' / 'share'
        self.assertEqual(found['core'], str(installed.resolve() / 'scripts'))
        for name, version in zip(COMPANIONS, ('0.8.0', '0.13.1')):
            self.assertEqual(found[name.removeprefix('harness-')],
                             str(shared / name / 'versions' / version), name)
        # A brand skill is looked for among the skills each assistant has, where the
        # companions were just registered and where an organisation's own would be.
        self.assertIn(str(brand), found['brand'])
        self.assertIs(found['opens'], True)

    def test_a_runner_that_does_not_start_is_never_made_current(self):
        first = self.run_installer('install', '--yes')
        broken = self.base / 'runner'
        shutil.copytree(install.RUNNER, broken, ignore=shutil.ignore_patterns('__pycache__'))
        (broken / 'studio.py').write_text('raise SystemExit("broken")\n')
        with self.assertRaises(install.InstallError) as refused:
            install.install(helpers.SKILL, self.home, self.root, ['claude'], False, False,
                            runner=broken)
        self.assertIn('The installed runner did not start', str(refused.exception))
        self.assertEqual(os.readlink(self.root / 'current'),
                         str(self.root / 'versions' / first['version']))

    def test_the_one_line_command_opens_the_runner_that_was_installed(self):
        result = self.run_installer('install', '--yes')
        opener = self.root / 'studio'
        self.assertEqual(result['runner']['open_with'], f'sh {opener}')
        self.assertIsNone(result['runner']['double_click'])
        self.assertTrue(os.access(opener, os.X_OK))
        text = opener.read_text()
        self.assertIn(str(self.root / 'current' / 'runner' / 'studio.py'), text)
        self.assertIn('set -- serve --open', text)
        asked = subprocess.run(['sh', str(opener), 'serve', '--help'], capture_output=True,
                               text=True)
        self.assertEqual(asked.returncode, 0, asked.stderr)
        self.assertIn('usage: studio serve', asked.stdout)

    def test_on_a_mac_a_launcher_to_double_click_is_written_too(self):
        with mock.patch.object(install, 'PLATFORM', 'darwin'):
            result = self.run_installer('install', '--yes')
            launcher = self.home / 'Applications' / 'Open Training Studio.command'
            self.assertEqual(result['runner']['double_click'], str(launcher))
            self.assertTrue(os.access(launcher, os.X_OK))
            self.assertIn(f"/bin/sh {self.root / 'studio'}", launcher.read_text())
            self.assertNotIn('token', launcher.read_text(), 'no key is ever written down')
            gone = self.run_installer('uninstall', '--yes')
        self.assertEqual(sorted(gone['launchers_removed']),
                         sorted([str(launcher), str(self.root / 'studio'),
                                 str(self.root / 'training')]))
        self.assertFalse(launcher.exists())
        self.assertTrue(launcher.parent.is_dir())

    def test_a_file_of_the_persons_own_where_a_launcher_goes_is_left_alone(self):
        mine = self.home / 'Applications' / 'Open Training Studio.command'
        mine.parent.mkdir()
        mine.write_text('#!/bin/sh\necho mine\n')
        with mock.patch.object(install, 'PLATFORM', 'darwin'):
            result = self.run_installer('install', '--yes')
            self.assertIsNone(result['runner']['double_click'])
            self.run_installer('uninstall', '--yes')
        self.assertEqual(mine.read_text(), '#!/bin/sh\necho mine\n')

    def test_link_mode_opens_the_runner_of_the_checkout(self):
        self.run_installer('install', '--yes', '--link')
        self.assertIn(str(helpers.REPO / 'runner' / 'studio.py'),
                      (self.root / 'studio').read_text())

    def test_an_update_and_a_rollback_take_the_runner_with_them(self):
        first = self.run_installer('install', '--yes')
        opener = (self.root / 'studio').read_text()
        second = self.run_installer('install', '--yes', '--source',
                                    str(self.copy_of_the_skill('9.9.9')))
        running = self.root / 'current' / 'runner' / 'studio.py'
        self.assertEqual(running.resolve().parts[-3], second['version'])
        self.assertEqual((self.root / 'studio').read_text(), opener, 'it follows the version')
        back = self.run_installer('rollback', '--yes')
        self.assertEqual(running.resolve().parts[-3], first['version'])
        self.assertEqual(back['runner']['installed'], True)
        self.assertEqual(self.run_installer('check')['runner']['open_with'],
                         f"sh {self.root / 'studio'}")

    def test_nothing_is_changed_underneath_a_runner_that_is_serving(self):
        first = self.run_installer('install', '--yes')
        self.run_installer('install', '--yes', '--source', str(self.copy_of_the_skill('9.9.8')))
        before = os.readlink(self.root / 'current')
        (self.root / 'runner.pid').write_text(f'{os.getpid()}\n')   # this test is "serving"
        later = self.copy_of_the_skill('9.9.9')
        for action in (['install', '--source', str(later)], ['install', '--link'],
                       ['rollback'], ['uninstall']):
            refusal = self.run_installer(*action, '--yes', expect=1)['error']
            self.assertIn(f'Training Studio is open on this computer (process {os.getpid()})',
                          refusal)
            self.assertIn('Close it first', refusal)
        self.assertEqual(os.readlink(self.root / 'current'), before)
        self.assertEqual(len(list((self.root / 'versions').iterdir())), 2)
        self.assertTrue((self.claude / 'training-studio').is_symlink())
        self.assertEqual(self.run_installer('check')['runner']['serving'], os.getpid())
        self.assertNotEqual(first['version'], Path(before).name)

    def test_the_runner_may_ask_for_a_new_version_beside_the_one_it_runs(self):
        first = self.run_installer('install', '--yes')
        (self.root / 'runner.pid').write_text(f'{os.getpid()}\n')   # this test is "serving"
        running = self.root / 'versions' / first['version']
        later = self.copy_of_the_skill('9.9.9')
        second = self.run_installer('install', '--yes', '--while-open', '--source', str(later))
        for refused in (['rollback'], ['uninstall'], ['install', '--link', '--source', str(later)]):
            said = self.run_installer(*refused, '--yes', '--while-open', expect=1)['error']
            self.assertIn('Training Studio is open on this computer', said)
        self.assertEqual(os.readlink(self.root / 'current'),
                         str(self.root / 'versions' / second['version']))
        self.assertTrue((running / 'runner' / 'studio.py').is_file(),
                        'the version the runner runs from is still whole')
        self.assertEqual(install.read_state(self.root)['history'],
                         [first['version'], second['version']])

    def test_a_runner_that_ended_without_saying_so_is_not_counted(self):
        self.run_installer('install', '--yes')
        (self.root / 'runner.pid').write_text(f'{self.a_stopped_process()}\n')
        self.assertIsNone(self.run_installer('check')['runner']['serving'])
        self.run_installer('install', '--yes', '--source', str(self.copy_of_the_skill('9.9.9')))

    def test_a_dry_run_says_how_it_would_be_opened_and_what_would_be_offered(self):
        plan = self.run_installer('install', '--dry-run')
        self.assertEqual(plan['launchers'], {'command': str(self.root / 'studio'),
                                             'helper': str(self.root / 'training')})
        self.assertEqual({name: (one['wanted'], one['would_offer'])
                          for name, one in plan['companions'].items()},
                         {'harness-research': ('0.8.0', True), 'harness-slides': ('0.13.1', True)})
        self.assertFalse(self.root.exists())


class HelperTests(InstallerCase):
    """The helper's command: the helper run with a Python new enough, whatever python3 is."""

    def env(self, **more) -> dict:
        """A home, a data folder and a guidance source of the test's own: nothing real is read
        and nothing is fetched."""
        return {**os.environ, 'HOME': str(self.home), 'USERPROFILE': str(self.home),
                'TRAINING_STUDIO_DATA': str(self.base / 'data'),
                'TRAINING_STUDIO_SOURCE': str(self.base / 'nowhere'), **more}

    def ask_helper_text(self, *args, expect=0) -> str:
        folder = self.base / 'valkey-training'
        folder.mkdir(exist_ok=True)
        done = subprocess.run([str(self.root / 'training'), *args], cwd=folder,
                              capture_output=True, text=True, env=self.env())
        self.assertEqual(done.returncode, expect, done.stdout + done.stderr)
        return done.stdout

    def ask_helper(self, *args, expect=0) -> dict:
        return json.loads(self.ask_helper_text(*args, expect=expect))

    def old_python(self) -> Path:
        """A folder whose python3 is too old: it fails the version check, and says so if it is
        ever asked to run anything."""
        folder = self.base / 'old-bin'
        folder.mkdir(exist_ok=True)
        fake = folder / 'python3'
        fake.write_text('#!/bin/sh\n[ "$1" = -c ] && exit 1\necho \'{"ran": "python3"}\'\n')
        fake.chmod(0o755)
        return folder

    def test_the_helpers_command_is_written_beside_the_runners_and_runs_the_helper(self):
        result = self.run_installer('install', '--yes')
        command = self.root / 'training'
        self.assertEqual(result['helper'], str(command))
        self.assertTrue(os.access(command, os.X_OK))
        self.assertIn(str(self.root / 'current' / 'scripts'), command.read_text())
        self.assertIn('No training in this directory',
                      self.ask_helper('status', expect=2)['error'])
        self.assertIn('usage: training.py', self.ask_helper_text('--help'))

    def test_it_runs_guidance_sync_and_names_itself_as_the_helper(self):
        self.run_installer('install', '--yes')
        found = self.ask_helper('guidance', 'start')
        self.assertEqual(found['helper'], str(self.root / 'training'))
        self.assertEqual(Path(found['entry']).resolve(),
                         (self.root / 'current' / 'guidance' / 'SKILL.md').resolve())
        self.assertIn('Could not get the newest guidance', found['notice'])

    def test_a_python3_older_than_3_11_is_passed_over(self):
        self.run_installer('install', '--yes')
        newer = self.base / 'new-bin'
        newer.mkdir()
        (newer / 'python3.12').symlink_to(sys.executable)
        command = self.base / 'training'
        command.write_text(install.helper_text(self.root / 'current' / 'scripts', command,
                                               pythons=('python3', 'python3.12')))
        path = f'{self.old_python()}{os.pathsep}{newer}{os.pathsep}/usr/bin{os.pathsep}/bin'
        done = subprocess.run(['sh', str(command), 'status'], cwd=self.base, capture_output=True,
                              text=True, env=self.env(PATH=path))
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn('No training in this directory', json.loads(done.stdout)['error'])

    def test_with_no_python_new_enough_it_says_so_as_json(self):
        command = self.base / 'training'
        command.write_text(install.helper_text(helpers.SCRIPTS, command, pythons=('python3',)))
        done = subprocess.run(['sh', str(command), 'status'], capture_output=True, text=True,
                              env=self.env(PATH=f'{self.old_python()}{os.pathsep}/usr/bin'
                                                f'{os.pathsep}/bin'))
        self.assertEqual(done.returncode, 2)
        self.assertIn('needs Python 3.11 or newer', json.loads(done.stdout)['error'])

    def test_a_linked_checkout_gets_the_same_command_for_its_own_helper(self):
        self.run_installer('install', '--yes', '--link')
        self.assertIn(str(helpers.SCRIPTS), (self.root / 'training').read_text())
        self.assertIn('No training in this directory',
                      self.ask_helper('status', expect=2)['error'])

    def test_it_is_removed_with_the_others_and_never_written_over_a_file_of_ones_own(self):
        self.run_installer('install', '--yes')
        gone = self.run_installer('uninstall', '--yes')
        self.assertIn(str(self.root / 'training'), gone['launchers_removed'])
        self.assertFalse((self.root / 'training').exists())
        (self.root / 'training').write_text('#!/bin/sh\necho mine\n')
        self.assertIsNone(self.run_installer('install', '--yes')['helper'])
        self.assertEqual((self.root / 'training').read_text(), '#!/bin/sh\necho mine\n')

    def test_the_two_installers_look_for_python_in_the_same_places(self):
        script = (helpers.REPO / 'installer' / 'install.sh').read_text()
        listed = script.split('for candidate in', 1)[1].split('; do', 1)[0]
        self.assertEqual(tuple(listed.replace('\\\n', ' ').split()), install.PYTHONS)
        self.assertIn('/Library/Frameworks/Python.framework/Versions/Current/bin/python3',
                      install.PYTHONS)


class CompanionTests(InstallerCase):
    def fetched(self, name: str) -> list[Path]:
        folder = self.root / 'companions' / name
        return sorted(folder.iterdir()) if folder.is_dir() else []

    def test_nobody_to_ask_means_nothing_is_fetched_and_the_report_says_how(self):
        os.chdir(helpers.REPO)   # the installer's folder, as when it is run as the docs say
        why = {(): 'because no one was there to answer',
               ('--companions', 'skip'): 'because --companions skip was given'}
        for extra, reason in why.items():
            result = self.run_installer('install', '--yes', *extra)
            for name in COMPANIONS:
                self.assertEqual(result['companions'][name]['state'], 'waiting')
                self.assertEqual(result['companions'][name]['found'],
                                 {'claude': None, 'codex': None})
                self.assertEqual(self.fetched(name), [])
                self.assertFalse((self.claude / name).exists())
            notes = [note for note in result['notes'] if note.startswith('harness-slides')]
            self.assertEqual(len(notes), 1)
            self.assertIn('is not installed for Claude Code and Codex', notes[0])
            self.assertIn(reason, notes[0])
            self.assertIn('run: sh installer/install.sh --companions install', notes[0])
            self.assertNotIn('say yes', notes[0])
            self.assertIn(str(_made['harness-slides'].bare.with_suffix('')), notes[0])

    def test_the_command_in_a_note_works_from_wherever_it_is_read(self):
        os.chdir(self.base)
        (note,) = [note for note in self.run_installer('check')['notes']
                   if note.startswith('harness-research')]
        script = helpers.REPO / 'installer' / 'install.sh'
        self.assertTrue(note.endswith(f'run: sh {script} --companions install'), note)
        self.assertNotIn('because', note, 'check offered nothing, so it gives no reason')

    def test_a_person_who_said_no_is_told_how_to_change_their_mind(self):
        printed = io.StringIO()
        with mock.patch.object(install.sys, 'stdin', mock.Mock(isatty=lambda: True)), \
                mock.patch('builtins.input', lambda question: 'n'), \
                contextlib.redirect_stdout(printed):
            install.main(['install', '--yes', '--home', str(self.home)])
        (note,) = [line for line in printed.getvalue().splitlines()
                   if line.startswith('  - harness-research')]
        self.assertIn('because you answered no', note)
        self.assertIn('--companions install', note)

    def test_a_person_is_asked_about_each_companion_and_yes_to_the_rest_does_not_cover_it(self):
        asked, printed = [], io.StringIO()

        def answer(question: str) -> str:
            asked.append(question)
            return 'n'

        with mock.patch.object(install.sys, 'stdin', mock.Mock(isatty=lambda: True)), \
                mock.patch('builtins.input', answer), contextlib.redirect_stdout(printed):
            code = install.main(['install', '--yes', '--home', str(self.home)])
        self.assertEqual(code, 0, printed.getvalue())
        self.assertEqual(asked, ['Fetch harness-research and run its installer? [y/N]: ',
                                 'Fetch harness-slides and run its installer? [y/N]: '])
        said = printed.getvalue()
        self.assertIn(f"at revision {self.pins['harness-slides']['commit'][:12]} and checked",
                      said)
        self.assertIn('Then its own installer would be run with Node.', said)
        self.assertEqual(self.fetched('harness-research') + self.fetched('harness-slides'), [])
        self.assertTrue((self.claude / 'training-studio' / 'SKILL.md').is_file())

    def test_before_anything_a_person_is_told_what_would_be_done(self):
        printed = io.StringIO()
        with mock.patch.object(install.sys, 'stdin', mock.Mock(isatty=lambda: True)), \
                mock.patch('builtins.input', lambda question: 'n'), \
                contextlib.redirect_stdout(printed):
            install.main(['install', '--home', str(self.home)])
        said = printed.getvalue()
        self.assertIn('Would install Training Studio', said)
        self.assertIn(f"A way to open it: {self.root / 'studio'}", said)
        self.assertIn('harness-research 0.8.0: would be offered, from', said)
        self.assertIn('Nothing was changed.', said)
        self.assertFalse(self.root.exists())

    @unittest.skipUnless(NODE, 'a companion installs itself with Node')
    def test_each_companion_is_installed_by_its_own_installer_from_its_pinned_revision(self):
        result = self.run_installer('install', '--yes', '--companions', 'install')
        for name, version in zip(COMPANIONS, ('0.8.0', '0.13.1')):
            self.assertEqual(result['companions'][name]['state'], 'installed', result['notes'])
            self.assertEqual(result['companions'][name]['found'],
                             {'claude': version, 'codex': version})
            (kept,) = self.fetched(name)
            self.assertEqual(kept.name, self.pins[name]['commit'][:12])
            self.assertFalse((kept / '.git').exists())
            self.assertEqual(install.tree_digest(kept), self.pins[name]['sha256'])
            for skills in (self.claude, self.codex):
                self.assertEqual((skills / name / 'SKILL.md').read_text(),
                                 f'---\nname: {name}\n---\n\nThe small entry of {version}.\n')
                self.assertTrue((skills / name / 'scripts' / f'{name}.mjs').is_file())
        self.assertFalse(any(note.startswith('harness-') for note in result['notes']))
        state = json.loads((self.root / 'installation.json').read_text())
        self.assertEqual({name: one['commit'] for name, one in state['companions'].items()},
                         {name: self.pins[name]['commit'] for name in COMPANIONS})
        again = self.run_installer('install', '--yes', '--companions', 'install')
        self.assertEqual([one['state'] for one in again['companions'].values()],
                         ['left alone', 'left alone'])
        gone = self.run_installer('uninstall', '--yes')
        self.assertEqual(gone['companions_left'], list(COMPANIONS))
        self.assertTrue((self.claude / 'harness-research' / 'SKILL.md').is_file())

    @unittest.skipUnless(NODE, 'a companion installs itself with Node')
    def test_an_older_companion_is_brought_up_to_the_pin(self):
        self.run_installer('install', '--yes', '--companions', 'install', '--target', 'claude')
        self.repin('harness-slides', _made['harness-slides'].release('0.14.0'))
        result = self.run_installer('install', '--yes', '--companions', 'install',
                                    '--target', 'claude')
        self.assertEqual(result['companions']['harness-slides']['state'], 'installed')
        self.assertEqual(result['companions']['harness-slides']['found'], {'claude': '0.14.0'})
        self.assertEqual(result['companions']['harness-research']['state'], 'left alone')
        self.assertEqual(len(self.fetched('harness-slides')), 2)

    def test_a_companion_as_new_or_newer_is_left_alone(self):
        for name, version in (('harness-research', '0.8.0'), ('harness-slides', '1.2.0')):
            (self.claude / name).mkdir()
            (self.claude / name / 'package.json').write_text(json.dumps({'version': version}))
            (self.claude / name / 'SKILL.md').write_text('mine\n')
        result = self.run_installer('install', '--yes', '--companions', 'install',
                                    '--target', 'claude')
        for name, version in (('harness-research', '0.8.0'), ('harness-slides', '1.2.0')):
            self.assertEqual(result['companions'][name]['state'], 'left alone')
            self.assertEqual(result['companions'][name]['found'], {'claude': version})
            self.assertEqual(self.fetched(name), [])
            self.assertEqual((self.claude / name / 'SKILL.md').read_text(), 'mine\n')
        self.assertFalse(any(note.startswith('harness-') for note in result['notes']))

    def test_a_companion_whose_version_cannot_be_read_is_left_alone_and_named(self):
        (self.claude / 'harness-research').mkdir()
        result = self.run_installer('install', '--yes', '--companions', 'install',
                                    '--target', 'claude')
        self.assertEqual(result['companions']['harness-research']['state'], 'left alone')
        self.assertEqual(self.fetched('harness-research'), [])
        (note,) = [note for note in result['notes'] if note.startswith('harness-research')]
        self.assertIn('its version could not be read. It was left alone', note)

    def refused(self, name: str = 'harness-research') -> str:
        """Install with the pins as they stand, and return why the companion was refused."""
        write_pins(self.pins_file, self.pins)
        result = self.run_installer('install', '--yes', '--companions', 'install')
        outcome = result['companions'][name]
        self.assertEqual(outcome['state'], 'refused', outcome)
        self.assertEqual(outcome['found'], {'claude': None, 'codex': None})
        self.assertEqual(self.fetched(name), [], 'nothing of it is kept')
        self.assertFalse((self.home / '.local' / 'share' / name).exists(), 'and nothing ran')
        self.assertTrue((self.claude / 'training-studio' / 'SKILL.md').is_file())
        (note,) = [note for note in result['notes'] if note.startswith(name)]
        self.assertIn('was not installed', note)
        return outcome['detail']

    def test_a_companion_that_is_not_file_for_file_what_was_pinned_is_refused(self):
        self.pins['harness-research']['sha256'] = 'ab' * 32
        self.assertIn('is not what this installer expects, file for file', self.refused())

    def test_a_revision_other_than_the_pinned_one_is_refused(self):
        expected = self.pins['harness-research']['sha256']
        self.repin('harness-research', _made['harness-research'].release('0.8.1'))
        self.pins['harness-research']['sha256'] = expected
        self.assertIn('is not what this installer expects', self.refused())

    def test_a_revision_the_repository_does_not_have_is_refused(self):
        self.pins['harness-research']['commit'] = 'c' * 40
        self.assertIn('could not be fetched from', self.refused())

    def test_an_entry_that_names_another_skill_is_refused(self):
        self.repin('harness-research',
                   _made['harness-research'].release('0.8.2', stub_names='something-else'))
        self.assertIn('does not hold the entry and the installer', self.refused())

    @unittest.skipUnless(NODE, 'a companion installs itself with Node')
    def test_a_kept_copy_that_was_changed_is_never_run(self):
        self.repin('harness-slides', _made['harness-slides'].release('0.13.2', refuses=True))
        first = self.run_installer('install', '--yes', '--companions', 'install')
        self.assertEqual(first['companions']['harness-slides']['state'], 'failed')
        self.assertIn('its installer said: Existing unrelated skill',
                      first['companions']['harness-slides']['detail'])
        (kept,) = self.fetched('harness-slides')
        (kept / 'package.json').write_text(json.dumps({'name': 'harness-slides',
                                                       'version': '0.13.2'}))
        second = self.run_installer('install', '--yes', '--companions', 'install')
        self.assertEqual(second['companions']['harness-slides']['state'], 'refused')
        self.assertIn('has changed since it was fetched',
                      second['companions']['harness-slides']['detail'])
        self.assertFalse((self.claude / 'harness-slides').exists())

    def test_without_node_a_companion_is_not_fetched(self):
        self.answers[('node', '--version')] = (0, 'v18.19.0')
        result = self.run_installer('install', '--yes', '--companions', 'install')
        self.assertEqual(result['companions']['harness-slides']['state'], 'failed')
        self.assertEqual(self.fetched('harness-slides'), [])
        self.assertTrue(any('Node 20 or newer is needed by the companion skills; found '
                            'v18.19.0' in note for note in result['notes']))

    @unittest.skipUnless(NODE, 'a companion installs itself with Node')
    def test_companions_brings_only_the_companions_for_the_assistants_installed_for(self):
        self.run_installer('install', '--yes', '--target', 'claude')
        before = (os.readlink(self.root / 'current'),
                  (self.root / 'installation.json').read_text())
        result = self.run_installer('companions', '--companions', 'install')
        self.assertEqual(result['harnesses'], ['claude'])
        for name, version in zip(COMPANIONS, ('0.8.0', '0.13.1')):
            self.assertEqual(result['companions'][name]['state'], 'installed', result['notes'])
            self.assertEqual(result['companions'][name]['found'], {'claude': version})
        state = json.loads((self.root / 'installation.json').read_text())
        self.assertEqual({name: one['commit'] for name, one in state['companions'].items()},
                         {name: self.pins[name]['commit'] for name in COMPANIONS})
        self.assertEqual(os.readlink(self.root / 'current'), before[0])
        self.assertEqual({key: value for key, value in state.items() if key != 'companions'},
                         json.loads(before[1]))
        again = self.run_installer('companions', '--companions', 'install')
        self.assertEqual([one['state'] for one in again['companions'].values()],
                         ['left alone', 'left alone'])

    def test_companions_asks_about_each_and_refuses_underneath_a_runner_unless_it_asks(self):
        self.run_installer('install', '--yes')
        nobody = self.run_installer('companions')
        self.assertEqual([one['state'] for one in nobody['companions'].values()],
                         ['waiting', 'waiting'])
        self.assertTrue(any('because no one was there to answer' in note
                            for note in nobody['notes']))
        self.assertEqual(self.fetched('harness-slides'), [])
        (self.root / 'runner.pid').write_text(f'{os.getpid()}\n')   # this test is "serving"
        refusal = self.run_installer('companions', '--companions', 'install', expect=1)
        self.assertIn('Training Studio is open on this computer', refusal['error'])
        asked = self.run_installer('companions', '--companions', 'skip', '--while-open')
        self.assertEqual(asked['harnesses'], ['claude', 'codex'])
        self.assertEqual([one['state'] for one in asked['companions'].values()],
                         ['waiting', 'waiting'])

    def test_a_companions_installer_is_only_told_of_a_home_that_is_not_the_persons_own(self):
        pin, checkout = self.pins['harness-slides'], self.base / 'kept'
        self.assertEqual(install.companion_command('node', checkout, pin, self.home),
                         ['node', str(checkout / 'scripts' / 'install.mjs'), '--home',
                          str(self.home)])
        self.assertEqual(install.companion_command('node', checkout, pin,
                                                   Path.home().resolve()),
                         ['node', str(checkout / 'scripts' / 'install.mjs')])

    def test_pinning_records_the_revision_and_every_file_of_it(self):
        commit = _made['harness-slides'].release('0.15.0')
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = install.main(['pin', 'harness-slides', '--revision', 'main', '--yes',
                                 '--json', '--pins', str(self.pins_file)])
        self.assertEqual(code, 0, printed.getvalue())
        result = json.loads(printed.getvalue())
        self.assertEqual((result['version'], result['commit'], result['was']['version']),
                         ('0.15.0', commit, '0.13.1'))
        kept = install.read_pins(self.pins_file)['harness-slides']
        self.assertEqual((kept['version'], kept['commit']), ('0.15.0', commit))
        self.assertNotEqual(kept['sha256'], self.pins['harness-slides']['sha256'])
        self.assertEqual(install.read_pins(self.pins_file)['harness-research'],
                         self.pins['harness-research'])

    def test_pins_this_installer_cannot_read_are_refused(self):
        self.pins['harness-slides']['installer'] = '../elsewhere/install.mjs'
        write_pins(self.pins_file, self.pins)
        refusal = self.run_installer('install', '--yes', expect=1)
        self.assertIn('does not say which companion skills to install', refusal['error'])
        self.assertFalse(self.root.exists())

    def test_the_pins_that_ship_name_a_whole_commit_and_nothing_of_a_companion_is_here(self):
        pins = install.read_pins(helpers.REPO / 'installer' / 'companions.json')
        self.assertEqual(sorted(pins), sorted(COMPANIONS))
        for name, pin in pins.items():
            self.assertTrue(pin['repository'].startswith('https://github.com/'), name)
            self.assertFalse((helpers.REPO / 'bootstrap' / name).exists(), name)


class NeedsTests(InstallerCase):
    def test_with_everything_there_nothing_is_worth_knowing_but_pandoc(self):
        for name, version in zip(COMPANIONS, ('0.8.0', '0.13.1')):
            (self.claude / name).mkdir()
            (self.claude / name / 'package.json').write_text(json.dumps({'version': version}))
        result = self.run_installer('check', '--target', 'claude')
        self.assertEqual([note for note in result['notes'] if not note.startswith('pandoc')], [])
        self.assertEqual(result['git'], {'installed': True, 'name': True, 'email': True})
        self.assertEqual(result['agents']['claude'], {'installed': True, 'signed_in': None})
        self.assertEqual(result['brand_skill'], True)

    def test_each_thing_the_runner_needs_and_does_not_have_is_named_with_how_to_get_it(self):
        self.answers.clear()
        self.brand = False
        notes = self.run_installer('install', '--yes')['notes']
        for said in ('git was not found. The runner keeps every training in a git repository. '
                     'Install it from https://git-scm.com',
                     'No assistant was found. Install Claude Code or Codex and sign in',
                     'Node 20 or newer is needed by the companion skills; none was found. Get '
                     'it from https://nodejs.org',
                     'harness-research 0.8.0 was not installed',
                     'harness-slides 0.13.1 was not installed',
                     'No brand skill was found. A slide deck is always made in a brand'):
            self.assertEqual(len([note for note in notes if said in note]), 1, said)

    def test_what_stops_the_most_comes_first(self):
        self.answers = {('python3', '--version'): (0, 'Python 3.9.6'),
                        ('git', '--version'): (0, 'git version 2.50.0')}
        self.brand = False
        with mock.patch.object(install.shutil, 'which', lambda name: None):
            notes = self.run_installer('check')['notes']
            self.assertEqual([note.split(' ', 1)[0] for note in notes],
                             ['No', 'harness-research', 'Node', 'harness-slides', 'git',
                              'python3', 'No', 'pandoc'])
            self.assertTrue(notes[0].startswith('No assistant was found'))
            self.assertTrue(notes[6].startswith('No brand skill was found'))
            self.answers.pop(('git', '--version'))
            notes = self.run_installer('check')['notes']
        self.assertTrue(notes[1].startswith('git was not found'), notes)

    def test_a_python3_too_old_is_named_and_needs_nothing_done(self):
        self.answers[('python3', '--version')] = (0, 'Python 3.9.6')
        result = self.run_installer('install', '--yes')
        self.assertEqual(result['python3_on_path'], '3.9.6')
        (note,) = [note for note in result['notes'] if note.startswith('python3')]
        self.assertIn('python3 on your PATH is 3.9.6, older than the 3.11', note)
        self.assertIn(str(self.root / 'training'), note)
        for fine in ('Python 3.11.0', 'Python 3.13.2'):
            self.answers[('python3', '--version')] = (0, fine)
            self.assertFalse(any(note.startswith('python3')
                                 for note in self.run_installer('check')['notes']))

    def test_git_that_does_not_know_who_you_are_is_named_with_the_commands(self):
        del self.answers[('git', 'config', '--get', 'user.email')]
        result = self.run_installer('check')
        self.assertEqual(result['git'], {'installed': True, 'name': True, 'email': False})
        (note,) = [note for note in result['notes'] if note.startswith('git ')]
        self.assertIn('git config --global user.email "you@example.com"', note)

    def test_an_assistant_that_is_not_signed_in_is_named(self):
        del self.answers[('claude', '--version')]
        self.answers[('codex', '--version')] = (0, 'codex-cli 1.0.0')
        self.answers[('codex', 'login', 'status')] = (1, 'Not logged in')
        result = self.run_installer('check')
        self.assertEqual(result['agents']['codex'], {'installed': True, 'signed_in': False})
        self.assertIn('Codex is installed but not signed in. Run: codex login', result['notes'])
        self.answers[('codex', 'login', 'status')] = (0, 'Logged in using ChatGPT')
        result = self.run_installer('check')
        self.assertEqual(result['agents']['codex']['signed_in'], True)
        self.assertFalse(any('signed in' in note for note in result['notes']))

    def test_no_brand_skill_is_found_in_a_home_that_has_none(self):
        self.assertIs(self.asks_the_runner(self.home), False)

    def test_a_brand_skill_is_never_named(self):
        self.brand = False
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            install.main(['check', '--home', str(self.home)])
        self.assertIn("A brand skill is your organisation's own and is not installed from here",
                      printed.getvalue())
