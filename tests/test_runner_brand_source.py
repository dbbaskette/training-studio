"""The brand skill's own repository, and installing it from the page: which releases it has,
fetching one, and running its own installer without letting it move the companions.

The brand repository is a bare one made here, with its release tags. Its installer is a
stand-in that records how it was run, lays the brand skill out as a shared install with a
link for each assistant, and refuses when it is not told to leave harness-research alone.
`gh` is a stand-in too, which serves a ZIP the test made. Nothing real is read, and nothing
is fetched from anywhere but here.
"""
import dataclasses
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import helpers
import runner_support  # noqa: F401  puts the runner on the import path
import test_runner_upkeep
from test_installer import NODE
from test_runner_upkeep import UpkeepCase, git, settle

from workspace import WorkspaceError

from runner import brand_source, companion, settings, upkeep

GITHUB = 'https://github.com/acme/acme-brand.git'
# The brand skill's own command: it lists its brands and says its version, as a real one.
COMMAND = """const [asked] = process.argv.slice(2);
if (asked === 'brands') console.log(JSON.stringify([{ brand: 'acme', name: 'Acme Works',
  variants: ['light'] }]));
else if (asked === 'version') console.log('Acme Brand @VERSION@');
else { console.error('Unknown command'); process.exit(1); }
"""
# The brand skill's own installer, as small as it can be and still do what the real one
# does: one shared copy, `current` pointing at it, and a link for each assistant. It writes
# down how it was run, refuses unless told to leave harness-research alone, can be held
# until the test lets it go, and, when its package says so, meddles with harness-slides.
INSTALLER = """import { cpSync, mkdirSync, symlinkSync, readFileSync, rmSync, lstatSync,
  writeFileSync, existsSync, appendFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { homedir } from 'node:os';
import { fileURLToPath } from 'node:url';
const args = process.argv.slice(2);
const script = fileURLToPath(import.meta.url);
const source = join(dirname(script), '..');
const pkg = JSON.parse(readFileSync(join(source, 'package.json'), 'utf8'));
appendFileSync(process.env.BRAND_STAND_IN_RECORD, JSON.stringify({ script: script.split('/').pop(),
  args, home: homedir(), cwd: process.cwd() }) + '\\n');
if (process.env.BRAND_STAND_IN_HOLD) {
  writeFileSync(process.env.BRAND_STAND_IN_HOLD + '.running', 'yes');
  while (!existsSync(process.env.BRAND_STAND_IN_HOLD)) await new Promise(go => setTimeout(go, 20));
}
const at = args.indexOf('--research');
if (at < 0 || args[at + 1] !== 'skip') {
  console.error('Setup could not finish: it would install harness-research.');
  process.exit(1);
}
if (pkg.refuses) { console.error('Setup could not finish: ' + pkg.refuses); process.exit(1); }
if (pkg.meddles) {
  const slides = join(homedir(), '.agents', 'skills', 'harness-slides');
  rmSync(slides, { recursive: true, force: true });
  mkdirSync(slides, { recursive: true });
  writeFileSync(join(slides, 'package.json'), JSON.stringify({ version: '0.1.0' }));
}
const shared = join(homedir(), '.local', 'share', 'acme-brand');
const runtime = join(shared, 'versions', pkg.version);
mkdirSync(runtime, { recursive: true });
cpSync(source, runtime, { recursive: true, filter: path => !path.includes('/.git') });
rmSync(join(shared, 'current'), { force: true });
symlinkSync(join('versions', pkg.version), join(shared, 'current'));
for (const folder of ['.agents', '.claude']) {
  const target = join(homedir(), folder, 'skills', 'acme-brand');
  mkdirSync(dirname(target), { recursive: true });
  try { lstatSync(target); } catch { symlinkSync(join(shared, 'current'), target); }
}
console.log('Shared installation installed.');
"""


class BrandRepository:
    """A stand-in for the brand skill's repository: a bare one, with release tags."""

    def __init__(self, base: Path):
        self.bare, self.work = base / 'acme-brand.git', base / 'acme-brand-work'
        # Its releases are pushed to main, which is its HEAD whatever git's default is here.
        git(base, 'init', '-q', '--bare', '--initial-branch=main', str(self.bare))
        git(base, 'init', '-q', str(self.work))

    def release(self, version: str, slides: str | None = '0.13.1', tag: bool = True,
                **package) -> str:
        """Commit one release, tag it v<version>, and return its commit."""
        files = {
            'package.json': json.dumps({'name': 'acme-brand', 'version': version, **package}),
            'SKILL.md': '---\nname: acme-brand\n---\n\nThe Acme brands.\n',
            'scripts/acme-brand.mjs': COMMAND.replace('@VERSION@', version),
            'scripts/install-mac.mjs': INSTALLER,
            'scripts/install-skill.mjs': INSTALLER,
        }
        if slides:
            files['scripts/lib/harness-install-sources.json'] = json.dumps({
                'slides': {'package': 'harness-slides', 'version': slides},
                'research': {'package': 'harness-research-skill', 'version': '0.8.0'}})
        for name, text in files.items():
            (self.work / name).parent.mkdir(parents=True, exist_ok=True)
            (self.work / name).write_text(text, encoding='utf-8')
        if not slides:
            (self.work / 'scripts' / 'lib' / 'harness-install-sources.json').unlink(
                missing_ok=True)
        git(self.work, 'add', '-A')
        git(self.work, 'commit', '-q', '-m', f'Release {version}')
        if tag:
            git(self.work, 'tag', '-f', f'v{version}')
        git(self.work, 'push', '-q', '-f', '--tags', str(self.bare), 'HEAD:refs/heads/main')
        return git(self.work, 'rev-parse', 'HEAD')

    def archive(self, folder: Path, version: str, prefix: str = '') -> Path:
        """The working copy as a release ZIP, as the brand packs it."""
        path = folder / f'acme-brand-{version}{"-mac" if prefix else ""}.zip'
        with zipfile.ZipFile(path, 'w') as packed:
            for one in sorted(self.work.rglob('*')):
                if one.is_file() and '.git' not in one.relative_to(self.work).parts:
                    packed.write(one, prefix + one.relative_to(self.work).as_posix())
        return path


GH = """#!@PYTHON@
import json, os, shutil, sys
args = sys.argv[1:]
folder = os.environ['GH_STAND_IN']
with open(os.path.join(folder, 'asked.jsonl'), 'a') as kept:
    kept.write(json.dumps(args) + '\\n')
if args[:2] == ['auth', 'status']:
    sys.exit(0 if os.path.exists(os.path.join(folder, 'signed-in')) else 1)
tag = args[2]
release = os.path.join(folder, 'releases', tag)
if args[:2] == ['release', 'view']:
    if not os.path.isdir(release):
        print('release not found', file=sys.stderr)
        sys.exit(1)
    print(json.dumps({'assets': [{'name': name} for name in sorted(os.listdir(release))]}))
    sys.exit(0)
if args[:2] == ['release', 'download']:
    into = args[args.index('--dir') + 1]
    wanted = [args[at + 1] for at, word in enumerate(args) if word == '--pattern']
    for name in wanted:
        shutil.copy(os.path.join(release, name), os.path.join(into, name))
    sys.exit(0)
sys.exit(2)
"""


def setUpModule():
    """The companions' stand-ins, pinned, as the upkeep tests make them."""
    test_runner_upkeep.setUpModule()


class SourceCase(unittest.TestCase):
    """A brand repository with releases, and a folder to run git in."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.base = Path(holder.name).resolve()
        self.place = self.base / 'git-runs-here'
        self.place.mkdir()
        self.brand = BrandRepository(self.base)
        self.address = str(self.brand.bare)


class ReleaseTests(SourceCase):
    def test_a_year_first_version_comes_before_every_other(self):
        for version in ('2026.5.0', '2026.6.0', '2099.0.0'):
            self.assertLess(brand_source.order(version), brand_source.order('0.8.0'))
        self.assertLess(brand_source.order('2026.5.7'), brand_source.order('2026.6.0'))
        self.assertLess(brand_source.order('0.10.2'), brand_source.order('0.13.1'))
        self.assertGreater(brand_source.order('1999.1.0'), brand_source.order('2026.1.0'),
                           'a number before 2000 is a version, not a year')
        self.assertEqual(brand_source.order('not.a.version'), ())

    def test_the_newest_release_is_the_newest_version_and_not_the_newest_year(self):
        first = self.brand.release('2026.6.0')
        newer = self.brand.release('0.13.1')
        git(self.brand.work, 'tag', '-a', '-m', 'Older', 'v0.10.2', first)
        git(self.brand.work, 'tag', 'not-a-release')
        git(self.brand.work, 'push', '-q', '--tags', str(self.brand.bare))
        found = brand_source.check(self.address, None, self.place)
        self.assertEqual(found['chosen'], {'tag': 'v0.13.1', 'version': '0.13.1',
                                           'commit': newer})
        self.assertEqual([entry['tag'] for entry in found['releases']],
                         ['v0.13.1', 'v0.10.2', 'v2026.6.0'])
        self.assertEqual(found['releases'][1]['commit'], first,
                         'an annotated tag is the commit it points at')
        self.assertIsNone(found['release'])

    def test_a_release_can_be_chosen_by_its_tag_or_its_version(self):
        older = self.brand.release('0.10.2')
        self.brand.release('0.13.1')
        for asked in ('v0.10.2', '0.10.2'):
            found = brand_source.check(self.address, asked, self.place)
            self.assertEqual((found['release'], found['chosen']['commit']), ('v0.10.2', older))
        with self.assertRaises(WorkspaceError) as refused:
            brand_source.check(self.address, 'v9.9.9', self.place)
        self.assertEqual(str(refused.exception), f'{self.address} has no release v9.9.9. Its '
                         'newest is v0.13.1. Leave the release empty for the newest.')

    def test_a_repository_that_cannot_be_used_is_refused_in_a_plain_sentence(self):
        with self.assertRaises(WorkspaceError) as refused:
            brand_source.check(self.address, None, self.place)
        self.assertEqual(str(refused.exception), f'{self.address} has no releases: no tag '
                         'such as v1.0.0. Check the address, or ask whoever keeps it to tag '
                         'a release.')
        with self.assertRaises(WorkspaceError) as refused:
            brand_source.check(str(self.base / 'nowhere.git'), None, self.place)
        self.assertTrue(str(refused.exception).startswith(
            "The brand skill's repository could not be read. It was not found ("),
            str(refused.exception))
        for address, says in (
                ('https://pat:secret@example.com/brand.git', 'carries a password or token'),
                ('relative/brand.git', "or a folder's whole path"),
                ('--upload-pack=touch', 'as one address'),
                ('', "Give the brand skill's repository address.")):
            with self.subTest(address=address), self.assertRaises(WorkspaceError) as refused:
                brand_source.check(address, None, self.place)
            self.assertIn(says, str(refused.exception))

    def test_why_git_failed_is_said_as_what_to_do(self):
        self.assertIn('Sign git in with an account that may read it', brand_source.plain(
            "could not read Username for 'https://github.com': terminal prompts disabled"))
        self.assertIn('Sign git in', brand_source.plain(
            'git@github.com: Permission denied (publickey)'))
        self.assertIn('A private repository is not found by someone who may not read it',
                      brand_source.plain('Repository not found'))
        self.assertIn('Check the address and that this computer is online',
                      brand_source.plain("unable to access 'https://example.com/': Could not "
                                         'resolve host: example.com'))


class FetchTests(SourceCase):
    def test_a_tag_is_cloned_with_its_commit_checked(self):
        commit = self.brand.release('0.13.1')
        into = self.base / 'into'
        into.mkdir()
        folder, how = brand_source.fetch(self.address, 'v0.13.1', commit, into)
        self.assertEqual(how, 'tag')
        self.assertEqual(json.loads((folder / 'package.json').read_text())['version'], '0.13.1')
        self.assertTrue((folder / '.git').is_dir(), 'its installer may ask git which commit')
        again = self.base / 'again'
        again.mkdir()
        with self.assertRaises(WorkspaceError) as refused:
            brand_source.fetch(self.address, 'v0.13.1', '0' * 40, again)
        self.assertIn('was fetched at another commit than the 000000000000 you were shown',
                      str(refused.exception))

    def test_with_gh_signed_in_the_release_zip_is_fetched_and_checked(self):
        commit = self.brand.release('0.13.1')
        stand_in = self.gh()
        release = stand_in / 'releases' / 'v0.13.1'
        release.mkdir(parents=True)
        mac = self.brand.archive(release, '0.13.1', prefix='acme-brand/')
        plain = self.brand.archive(release, '0.13.1')
        for archive in (mac, plain):
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            (release / f'{archive.name}.sha256').write_text(f'{digest}  {archive.name}\n')
        for platform, chosen in (('darwin', mac.name), ('linux', plain.name)):
            into = self.base / f'into-{platform}'
            into.mkdir()
            with mock.patch.object(brand_source, 'PLATFORM', platform):
                folder, how = brand_source.fetch(GITHUB, 'v0.13.1', commit, into)
            self.assertEqual(how, 'zip')
            self.assertTrue((folder / 'scripts' / 'install-mac.mjs').is_file())
            self.assertEqual(json.loads((folder / 'package.json').read_text())['version'],
                             '0.13.1')
            self.assertIn(['release', 'download', 'v0.13.1', '--repo', 'acme/acme-brand',
                           '--dir', str(into / 'download'), '--pattern', chosen,
                           '--pattern', f'{chosen}.sha256'], self.asked(stand_in))

        (release / f'{plain.name}.sha256').write_text(f'{"0" * 64}  {plain.name}\n')
        into = self.base / 'into-wrong'
        into.mkdir()
        with mock.patch.object(brand_source, 'PLATFORM', 'linux'), \
                self.assertRaises(WorkspaceError) as refused:
            brand_source.fetch(GITHUB, 'v0.13.1', commit, into)
        self.assertIn('does not match the checksum published beside it',
                      str(refused.exception))

    def test_without_gh_signed_in_the_tag_is_cloned_with_the_persons_own_git(self):
        commit = self.brand.release('0.13.1')
        stand_in = self.gh(signed_in=False)
        config = helpers.gitconfig(self.base / 'gitconfig',
                                   f'[url "{self.address}"]\n\tinsteadOf = {GITHUB}\n')
        into = self.base / 'into'
        into.mkdir()
        with mock.patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': str(config)}):
            folder, how = brand_source.fetch(GITHUB, 'v0.13.1', commit, into)
        self.assertEqual(how, 'tag')
        self.assertTrue((folder / 'scripts' / 'install-skill.mjs').is_file())
        self.assertEqual(self.asked(stand_in), [['auth', 'status', '--hostname', 'github.com']])

    def test_a_zip_with_a_link_or_a_path_outside_it_is_refused(self):
        for name, entry in (('outside.zip', ('../outside.txt', 0o100644)),
                            ('linked.zip', ('skill/SKILL.md', 0o120777))):
            archive = self.base / name
            with zipfile.ZipFile(archive, 'w') as packed:
                info = zipfile.ZipInfo(entry[0])
                info.external_attr = entry[1] << 16
                packed.writestr(info, '/etc/passwd')
            into = self.base / f'into-{name}'
            into.mkdir()
            with self.subTest(name=name), self.assertRaises(WorkspaceError):
                brand_source.unpack(archive, into)
            self.assertFalse((self.base / 'outside.txt').exists())

    def gh(self, signed_in: bool = True) -> Path:
        """A stand-in gh, first on PATH for this test."""
        folder = self.base / 'gh'
        (folder / 'bin').mkdir(parents=True)
        command = folder / 'bin' / 'gh'
        command.write_text(GH.replace('@PYTHON@', sys.executable))
        command.chmod(0o755)
        if signed_in:
            (folder / 'signed-in').write_text('yes\n')
        patch = mock.patch.dict(os.environ, {
            'GH_STAND_IN': str(folder),
            'PATH': f"{folder / 'bin'}{os.pathsep}{os.environ['PATH']}"})
        patch.start()
        self.addCleanup(patch.stop)
        return folder

    @staticmethod
    def asked(folder: Path) -> list:
        kept = folder / 'asked.jsonl'
        return [json.loads(line) for line in kept.read_text().splitlines()] \
            if kept.is_file() else []


class InstallerTests(SourceCase):
    def test_its_own_installer_is_told_to_leave_harness_research_alone(self):
        folder = self.base / 'release'
        (folder / 'scripts').mkdir(parents=True)
        for name in ('install-mac.mjs', 'install-skill.mjs'):
            (folder / 'scripts' / name).write_text('// its installer\n')
        with mock.patch.object(brand_source, 'PLATFORM', 'darwin'):
            self.assertEqual(brand_source.installer(folder, 'node'), [
                'node', str(folder / 'scripts' / 'install-mac.mjs'), '--yes', '--research',
                'skip'])
        with mock.patch.object(brand_source, 'PLATFORM', 'linux'):
            self.assertEqual(brand_source.installer(folder, 'node'), [
                'node', str(folder / 'scripts' / 'install-skill.mjs'), '--research', 'skip'])
        (folder / 'scripts' / 'install-skill.mjs').unlink()
        with mock.patch.object(brand_source, 'PLATFORM', 'linux'), \
                self.assertRaises(WorkspaceError) as refused:
            brand_source.installer(folder, 'node')
        self.assertIn('no installer Training Studio knows how to run', str(refused.exception))

    def test_what_it_brings_when_it_finds_none_is_read_from_its_own_record(self):
        folder = self.base / 'release'
        (folder / 'scripts' / 'lib').mkdir(parents=True)
        self.assertEqual(brand_source.bootstraps(folder), {})
        (folder / brand_source.SOURCES).write_text(json.dumps({
            'slides': {'version': '0.13.1'}, 'research': {'version': '0.8.0'},
            '../odd': {'version': '1.0.0'}, 'other': {'version': 'soon'}}))
        self.assertEqual(brand_source.bootstraps(folder),
                         {'harness-slides': '0.13.1', 'harness-research': '0.8.0'})


@unittest.skipUnless(NODE, 'the brand skill and its installer run on Node')
class BrandInstallCase(UpkeepCase):
    """Training Studio installed in a temporary home, with both companions at their pins
    for both assistants, and a brand repository with releases."""

    def setUp(self):
        super().setUp()
        self.brand = BrandRepository(self.base)
        self.address = str(self.brand.bare)
        self.record = self.base / 'brand-installer.jsonl'
        patch = mock.patch.dict(os.environ, {'BRAND_STAND_IN_RECORD': str(self.record)})
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop('BRAND_SKILL_RUNTIME', None)   # within the patch, so put back after
        self.staged = self.installed()
        for skills in (self.claude, self.codex):
            self.companion(skills, 'harness-research', '0.8.0')
            self.companion(skills, 'harness-slides', '0.13.1')
        self.after = []
        self.keep = upkeep.Upkeep(home_dir=self.home, root=self.root,
                                  installer=self.staged / 'installer' / 'install.py',
                                  after=lambda: self.after.append('looked'))
        self.addCleanup(self.keep.close)

    def choose(self, release: str | None = None) -> dict:
        """Name the brand repository in Settings, as the page's save does."""
        found = brand_source.check(self.address, release, self.base)
        settings.save(settings.Settings(brand_repository=found['repository'],
                                        brand_release=found['release']))
        self.keep.remember_brand(found['repository'],
                                 {entry['tag']: entry for entry in found['releases']})
        return found

    def row(self, report: dict | None = None) -> dict:
        report = report or self.keep.report()
        return report['versions']['rows'][-1]

    def ran(self) -> list:
        return [json.loads(line) for line in self.record.read_text().splitlines()] \
            if self.record.is_file() else []

    def install(self, release: str) -> dict:
        shown = self.keep.install_brand(False, release)
        settle(self.keep)
        return shown


class BrandRowTests(BrandInstallCase):
    def test_a_brand_skill_installed_by_hand_is_shown_and_nothing_is_offered(self):
        self.keep.check(repair=False)
        row = self.row()
        self.assertEqual((row['name'], row['kind'], row['state'], row['installed']),
                         ('brand skill', 'brand', 'unknown', None))
        self.assertEqual(row['says'], 'No brand skill is installed, so no deck is offered. '
                         'Name its repository in Settings to install and upgrade it from here.')
        self.brand.release('0.13.1')
        folder = self.base / 'by-hand'
        # By its tag: the bare repository's HEAD is whatever branch git makes by default here.
        # By its tag, so the branch git makes by default on this computer does not matter.
        git(self.base, 'clone', '-q', '--branch', 'v0.13.1', self.address, str(folder))
        (self.claude / 'acme-brand').symlink_to(folder)
        self.keep.check(repair=False)
        shown = self.keep.report()['versions']
        self.assertEqual((self.row()['installed'], self.row()['state']), ('0.13.1', 'unknown'))
        self.assertEqual(self.row()['says'], 'Acme Brand 0.13.1 is installed. Name its '
                         'repository in Settings to install and upgrade it from here.')
        self.assertFalse(shown['brand']['offered'])
        self.assertIsNone(shown['key'], 'Home says nothing of it')

    def test_with_a_repository_named_home_tells_of_a_missing_or_newer_brand_skill(self):
        self.brand.release('2026.6.0')
        commit = self.brand.release('0.13.1')
        self.choose()
        self.keep.check(repair=False)
        shown = self.keep.report()['versions']
        row = shown['rows'][-1]
        self.assertEqual((row['state'], row['newest'], row['target'], row['release'],
                          row['commit']), ('missing', '0.13.1', '0.13.1', 'v0.13.1',
                                           commit[:12]))
        self.assertEqual(row['says'], 'No brand skill is installed, so no deck is offered. '
                         f'v0.13.1 can be installed from {self.address}.')
        self.assertEqual(shown['key'], 'brand skill 0.13.1')
        self.assertEqual(shown['brand'], {
            'offered': True, 'action': 'Install', 'repository': self.address,
            'release': 'v0.13.1', 'version': '0.13.1', 'commit': commit[:12],
            'installed': None, 'state': None, 'since': None, 'says': None})

        self.install('v0.13.1')
        newer = self.brand.release('0.14.0')
        with mock.patch.object(upkeep.Upkeep, 'due', return_value=True):
            self.keep.look()
        self.keep.check(repair=False)
        shown = self.keep.report()['versions']
        row = shown['rows'][-1]
        self.assertEqual((row['state'], row['installed'], row['target'], row['commit']),
                         ('update', '0.13.1', '0.14.0', newer[:12]))
        self.assertEqual(row['says'], 'Acme Brand 0.14.0 is out, and this computer has 0.13.1.')
        self.assertEqual((shown['brand']['action'], shown['key']),
                         ('Upgrade', 'brand skill 0.14.0'))

    def test_a_release_chosen_in_settings_is_the_one_offered(self):
        older = self.brand.release('0.10.2')
        self.brand.release('0.13.1')
        self.choose('0.10.2')
        self.keep.check(repair=False)
        shown = self.keep.report()['versions']
        self.assertEqual((shown['brand']['release'], shown['brand']['commit']),
                         ('v0.10.2', older[:12]))
        self.install('v0.10.2')
        self.assertEqual(self.row()['says'], 'Acme Brand 0.10.2 is the release chosen in '
                         'Settings.')
        self.assertFalse(self.keep.report()['versions']['brand']['offered'])


class BrandInstallTests(BrandInstallCase):
    def test_the_release_is_fetched_and_its_own_installer_run_then_the_computer_looked_at(self):
        commit = self.brand.release('0.13.1')
        self.choose()
        self.keep.check(repair=False)
        going = self.base / 'go'
        with mock.patch.dict(os.environ, {'BRAND_STAND_IN_HOLD': str(going)}):
            shown = self.keep.install_brand(False, 'v0.13.1')
            brand = shown['versions']['brand']
            self.assertEqual((brand['state'], brand['offered']), ('running', False))
            self.assertEqual(brand['says'], f'Fetching v0.13.1 from {self.address} and running '
                             'its own installer. This can take a few minutes.')
            self.wait_for(going.with_name('go.running'))
            for refused, says in ((lambda: self.keep.install_brand(False, 'v0.13.1'),
                                   upkeep.BRAND_INSTALLING),
                                  (lambda: self.keep.update(False), upkeep.BRAND_INSTALLING)):
                with self.assertRaises(WorkspaceError) as caught:
                    refused()
                self.assertEqual(str(caught.exception), says)
            self.assertFalse(self.keep.report()['update']['offered'])
            going.write_text('go\n')
            settle(self.keep)
        (asked,) = self.ran()
        script = 'install-mac.mjs' if sys.platform == 'darwin' else 'install-skill.mjs'
        self.assertEqual(asked['script'], script)
        self.assertEqual(asked['args'], ['--yes', '--research', 'skip']
                         if sys.platform == 'darwin' else ['--research', 'skip'])
        self.assertEqual(Path(asked['home']).resolve(), self.home)
        brand = self.keep.report()['versions']['brand']
        self.assertEqual(brand['state'], 'done')
        self.assertEqual(brand['says'], f'Acme Brand 0.13.1 is installed, from {self.address} '
                         f'at v0.13.1 (revision {commit[:12]}). New decks can use it.')
        self.assertEqual(self.after, ['looked'], 'the computer is looked at again')
        self.assertEqual((self.row()['state'], self.row()['installed']), ('current', '0.13.1'))
        self.assertTrue((self.claude / 'acme-brand' / 'SKILL.md').is_file())
        for skills in (self.claude, self.codex):
            self.assertEqual(json.loads((skills / 'harness-slides' / 'package.json')
                                        .read_text())['version'], '0.13.1')

    def test_it_is_refused_before_anything_is_fetched_or_run(self):
        self.brand.release('0.13.1')
        self.keep.check(repair=False)
        cases = [(lambda: self.keep.install_brand(False, 'v0.13.1'),
                  upkeep.NO_BRAND_REPOSITORY)]
        for refused, says in cases:
            with self.assertRaises(WorkspaceError) as caught:
                refused()
            self.assertEqual(str(caught.exception), says)
        self.choose()
        for release, working, says in (
                ('v0.10.0', False, 'The release to install is now v0.13.1, not v0.10.0. Look '
                                   'at it again before you install.'),
                ('v0.13.1', True, upkeep.BRAND_WORKING)):
            with self.assertRaises(WorkspaceError) as caught:
                self.keep.install_brand(working, release)
            self.assertEqual(str(caught.exception), says)
        shutil.rmtree(self.codex / 'harness-slides')
        self.keep.check(repair=False)
        with self.assertRaises(WorkspaceError) as caught:
            self.keep.install_brand(False, 'v0.13.1')
        self.assertEqual(str(caught.exception), 'Update the companion skills first '
                         "(harness-slides). The brand skill's installer brings its own "
                         "harness-slides when it finds none it can use, and Training Studio's "
                         'are the ones to keep.')
        self.assertEqual(self.ran(), [])

    def test_a_release_that_would_replace_harness_slides_is_not_run(self):
        self.brand.release('0.13.1', slides='0.14.0')
        self.choose()
        self.keep.check(repair=False)
        self.install('v0.13.1')
        brand = self.keep.report()['versions']['brand']
        self.assertEqual(brand['state'], 'failed')
        self.assertEqual(brand['says'], 'The brand skill v0.13.1 was not installed: its '
                         'installer would replace harness-slides 0.13.1 with its own 0.14.0 for '
                         'Claude Code and Codex, in place of the one Training Studio is made '
                         'with. Choose an older release in Settings, or upgrade Training '
                         'Studio first. Nothing was run.')
        self.assertEqual(self.ran(), [], 'its installer was never run')
        self.assertFalse(os.path.lexists(self.claude / 'acme-brand'))

    def test_a_change_its_installer_made_to_a_companion_is_said(self):
        self.brand.release('0.13.1', meddles=True)
        self.choose()
        self.keep.check(repair=False)
        self.install('v0.13.1')
        brand = self.keep.report()['versions']['brand']
        self.assertEqual(brand['state'], 'changed')
        self.assertIn('Its installer also changed harness-slides at '
                      f"{self.codex / 'harness-slides'}, from 0.13.1 to 0.1.0. Training "
                      "Studio's pins are the ones to use: Update the skills puts back any that "
                      'is now older.', brand['says'])
        self.assertTrue(self.keep.report()['update']['offered'], 'Update puts it back')

    def test_what_its_installer_says_when_it_fails_is_shown(self):
        self.brand.release('0.13.1', refuses='Existing skill folders need migration.')
        self.choose()
        self.keep.check(repair=False)
        self.install('v0.13.1')
        brand = self.keep.report()['versions']['brand']
        self.assertEqual((brand['state'], brand['says']), (
            'failed', 'The brand skill v0.13.1 was not installed: Setup could not finish: '
                      'Existing skill folders need migration.'))
        self.assertEqual(self.after, ['looked'])

    def test_a_tag_moved_since_it_was_shown_is_not_installed(self):
        self.brand.release('0.13.1')
        self.choose()
        self.keep.check(repair=False)
        moved = self.brand.release('0.13.1', note='moved')   # the tag is moved on
        self.install('v0.13.1')
        brand = self.keep.report()['versions']['brand']
        self.assertEqual(brand['state'], 'failed')
        self.assertIn(f'v0.13.1 now points at {moved[:12]}, not the', brand['says'])
        self.assertEqual(self.ran(), [])

    def test_an_upgrade_moves_a_chosen_brand_skill_to_its_new_version(self):
        self.brand.release('0.13.1')
        self.choose()
        self.keep.check(repair=False)
        self.install('v0.13.1')
        installed = self.keep.check(repair=False)['brands'][0]['runtime']
        self.brand.release('0.14.0')
        self.choose()
        settings.save(dataclasses.replace(settings.load(), brand_skill=installed))
        self.keep.check(repair=False)
        self.install('v0.14.0')
        now = settings.load().brand_skill
        self.assertNotEqual(now, installed)
        self.assertTrue(now.endswith('0.14.0'), now)
        self.assertEqual(self.row()['installed'], '0.14.0')

    def test_closing_ends_an_install_in_hand(self):
        self.brand.release('0.13.1')
        self.choose()
        self.keep.check(repair=False)
        going = self.base / 'go'
        with mock.patch.dict(os.environ, {'BRAND_STAND_IN_HOLD': str(going)}):
            self.keep.install_brand(False, 'v0.13.1')
            self.wait_for(going.with_name('go.running'))
            self.keep.close()
        brand = self.keep.report()['versions']['brand']
        self.assertEqual((brand['state'], brand['says']), ('failed', upkeep.BRAND_STOPPED))

    def wait_for(self, path: Path) -> None:
        """Until the stand-in says it is running: it then waits to be let go."""
        clock = time.monotonic() + 60
        while not path.exists():
            self.assertLess(time.monotonic(), clock, 'the installer never started')
            time.sleep(0.02)


if __name__ == '__main__':
    unittest.main()
