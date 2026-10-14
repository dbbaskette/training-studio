"""What the runner looks after when it starts: the links the installer placed, the
companion skills against the pins this version was installed with, which releases exist,
and which guidance a new training gets.

Training Studio is installed by its own installer into a temporary home. The companions
are the installer tests' stand-ins, and each repository is a bare one made here, with its
release tags. Nothing real is read, and nothing is fetched from anywhere but there.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import helpers
import runner_support  # noqa: F401  puts the runner on the import path
import test_installer
from test_installer import NODE, StandIn, install, write_pins

import home
import sync_guidance
from workspace import WorkspaceError

from runner import settings, upkeep

VERSION = (helpers.SKILL / 'VERSION').read_text().strip()
_made = {}


def git(cwd: Path, *args: str) -> str:
    return test_installer.git(cwd, *args)


def tag(stand_in: StandIn, *versions: str) -> None:
    """Tag the stand-in's latest release, and send the tags to its bare repository."""
    for version in versions:
        git(stand_in.work, 'tag', version)
    git(stand_in.work, 'push', '-q', '--tags', str(stand_in.bare))


def settle(keep: upkeep.Upkeep) -> None:
    """Wait for what it does in the background, without ending anything."""
    for thread in list(keep._threads):
        thread.join(60)


def setUpModule():
    """Each companion's stand-in, pinned at its first release, as a maintainer pins it."""
    holder = tempfile.TemporaryDirectory()
    unittest.addModuleCleanup(holder.cleanup)
    base = Path(holder.name).resolve()
    pins = {}
    for name, version in (('harness-research', '0.8.0'), ('harness-slides', '0.13.1')):
        _made[name] = StandIn(base, name)
        commit = _made[name].release(version)
        tag(_made[name], f'v{version}')
        pins[name] = {'repository': str(_made[name].bare), 'version': '0.0.0',
                      'commit': '0' * 40, 'sha256': '0' * 64, 'stub': 'bootstrap/SKILL.md',
                      'installer': 'scripts/install.mjs'}
        write_pins(base / 'companions.json', pins)
        install.pin(base / 'companions.json', name, commit)
        pins = install.read_pins(base / 'companions.json')
    _made['pins'] = pins


class UpkeepCase(unittest.TestCase):
    """A temporary home, with its data folder where the installer keeps its record."""

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
        self.pins_file = self.base / 'companions.json'
        write_pins(self.pins_file, _made['pins'])
        self.source = self.base / 'training-studio.git'   # Training Studio's own repository
        git(self.base, 'init', '-q', '--bare', str(self.source))
        for patch in (mock.patch.dict(os.environ, {
                          'TRAINING_STUDIO_DATA': str(self.root),
                          'TRAINING_STUDIO_SOURCE': str(self.source)}),
                      mock.patch.object(install, 'PINS', self.pins_file),
                      mock.patch.object(install, 'PLATFORM', 'linux'),
                      # What else this computer has is the installer tests' business.
                      mock.patch.object(install, 'prerequisites',
                                        lambda *asked, **named: {'notes': []})):
            patch.start()
            self.addCleanup(patch.stop)

    def installed(self, *args: str) -> Path:
        """Install Training Studio into the temporary home; the installed version."""
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = install.main(['install', '--yes', '--companions', 'skip', '--json',
                                 '--home', str(self.home), *args])
        self.assertEqual(code, 0, printed.getvalue())
        result = json.loads(printed.getvalue())
        return self.root / 'versions' / result['version'] if result['mode'] == 'managed' \
            else helpers.REPO

    def keeper(self, staged: Path | None = None, after=None) -> upkeep.Upkeep:
        """What looks after the skills, as the runner of that version makes it."""
        staged = staged or self.installed()
        return upkeep.Upkeep(home_dir=self.home, root=self.root,
                             installer=staged / 'installer' / 'install.py', after=after)

    def companion(self, skills: Path, name: str, version: str | None) -> None:
        """A companion as its own installer leaves it, or one whose version cannot be read."""
        (skills / name).mkdir()
        (skills / name / 'SKILL.md').write_text('its entry\n')
        if version:
            (skills / name / 'package.json').write_text(json.dumps({'version': version}))

    def look_online(self, on: bool = True) -> None:
        settings.save(settings.Settings(look_for_updates=on))


class LinkTests(UpkeepCase):
    def test_a_missing_link_to_a_whole_copy_is_put_back_and_said(self):
        keep = self.keeper()
        link = self.claude / 'training-studio'
        link.unlink()
        found = keep.check(repair=True)
        self.assertEqual(os.readlink(link), str(self.root / 'current'))
        self.assertTrue((link / 'SKILL.md').is_file())
        self.assertEqual(found['repaired'], [f'The link for Claude Code was missing, and was '
                                             f'put back: {link}.'])
        self.assertEqual([(entry['assistant'], entry['state']) for entry in found['links']],
                         [('Claude Code', 'repaired'), ('Codex', 'ok')])
        self.assertEqual(keep.check(repair=True)['repaired'], [], 'once put back, it is ok')

    def test_looking_without_repairing_changes_nothing(self):
        keep = self.keeper()
        (self.codex / 'training-studio').unlink()
        found = keep.check(repair=False)
        self.assertFalse(os.path.lexists(self.codex / 'training-studio'))
        self.assertEqual(found['repaired'], [])
        self.assertEqual(found['links'][1]['state'], 'missing')
        self.assertIn('It is put back when Training Studio starts.', found['links'][1]['says'])

    def test_only_what_the_installer_placed_is_ever_put_back(self):
        keep = self.keeper()
        claude, codex = self.claude / 'training-studio', self.codex / 'training-studio'
        claude.unlink()
        claude.mkdir()                               # a folder of someone's own
        (claude / 'SKILL.md').write_text('mine\n')
        codex.unlink()
        codex.symlink_to(self.base)                  # a link someone pointed elsewhere
        found = keep.check(repair=True)
        self.assertEqual(found['repaired'], [])
        self.assertEqual((claude / 'SKILL.md').read_text(), 'mine\n')
        self.assertEqual(os.readlink(codex), str(self.base))
        self.assertEqual([entry['state'] for entry in found['links']],
                         ['left alone', 'left alone'])
        self.assertIn('is not the link the installer placed, so it was left alone',
                      found['links'][0]['says'])

    def test_an_assistant_whose_skill_folder_is_gone_is_not_given_one_again(self):
        keep = self.keeper()
        shutil.rmtree(self.home / '.agents')
        found = keep.check(repair=True)
        self.assertFalse((self.home / '.agents').exists())
        self.assertEqual(found['links'][1]['state'], 'left alone')
        self.assertIn('is gone, so Training Studio was not linked into it again',
                      found['links'][1]['says'])

    def test_the_link_to_the_version_and_the_commands_are_put_back_when_missing(self):
        staged = self.installed()
        keep = self.keeper(staged)
        (self.root / 'current').unlink()
        (self.root / 'training').unlink()
        (self.root / 'studio').write_text('my own studio\n')   # not missing: left alone
        found = keep.check(repair=True)
        self.assertEqual(os.readlink(self.root / 'current'), str(staged))
        self.assertTrue(install.ours(self.root / 'training'))
        self.assertEqual((self.root / 'studio').read_text(), 'my own studio\n')
        self.assertEqual(found['repaired'], [
            f"The link to the installed version was missing, and was put back: "
            f"{self.root / 'current'}.",
            f"The command the skill runs its helper with was missing, and was written again: "
            f"{self.root / 'training'}."])
        self.assertEqual([entry['state'] for entry in found['links']], ['ok', 'ok'],
                         'the links work again once the version they point through is back')

    def test_a_link_whose_copy_is_gone_is_said_and_left(self):
        keep = self.keeper()
        (self.root / 'current').unlink()
        (self.root / 'current').symlink_to(self.base / 'gone')
        state = install.read_state(self.root)
        state['current'] = 'not-there'
        install.write_state(self.root, state)
        found = keep.check(repair=True)
        self.assertEqual(found['repaired'], [])
        self.assertEqual(found['links'][0]['state'], 'missing')
        self.assertIn('which is not there any more. Run the installer again.',
                      found['links'][0]['says'])

    def test_a_runner_with_no_installer_beside_it_says_so(self):
        keep = upkeep.Upkeep(home_dir=self.home, root=self.root,
                             installer=self.base / 'nowhere' / 'install.py')
        found = keep.check()
        self.assertEqual((found['installer'], found['problem']), (False, upkeep.NO_INSTALLER))
        self.assertFalse(keep.report()['update']['offered'])
        with self.assertRaises(WorkspaceError) as refused:
            keep.update(working=False)
        self.assertEqual(str(refused.exception), upkeep.NO_INSTALLER)

    def test_where_the_record_is_follows_where_the_runner_was_installed(self):
        version = self.root / 'versions' / '1.0.0-abc'
        self.assertEqual(upkeep.install_root(version / 'runner'), self.root)
        self.assertEqual(upkeep.install_root(helpers.REPO / 'runner'), home.data_root())


class CompanionTests(UpkeepCase):
    def test_each_companion_is_compared_with_the_pins_this_version_shipped_with(self):
        keep = self.keeper()
        self.companion(self.claude, 'harness-research', '0.8.0')
        self.companion(self.codex, 'harness-research', '0.7.0')
        self.companion(self.claude, 'harness-slides', None)
        found = keep.check()
        research, slides = found['companions']
        self.assertEqual((research['state'], research['found']),
                         ('older', {'Claude Code': '0.8.0', 'Codex': '0.7.0'}))
        self.assertEqual(research['says'], 'harness-research for Codex is older than the '
                         '0.8.0 this Training Studio was made with.')
        self.assertEqual((slides['state'], slides['found']),
                         ('missing', {'Claude Code': '', 'Codex': None}))
        self.assertIn('harness-slides is not installed for Codex, and everything is built '
                      'except the slide deck without it.', slides['says'])
        self.assertEqual((slides['repository'], slides['commit']),
                         (str(_made['harness-slides'].bare.with_suffix('')),
                          _made['pins']['harness-slides']['commit'][:12]))
        self.assertTrue(keep.report()['update']['offered'])
        self.assertTrue((self.claude / 'harness-slides' / 'SKILL.md').is_file(),
                        "a companion's own links are never touched here")

    def test_companions_as_new_as_their_pins_offer_nothing(self):
        keep = self.keeper()
        for skills in (self.claude, self.codex):
            self.companion(skills, 'harness-research', '0.8.0')
            self.companion(skills, 'harness-slides', '0.14.0')
        found = keep.check()
        self.assertEqual([entry['state'] for entry in found['companions']], ['ok', 'ok'])
        self.assertEqual(found['companions'][1]['says'],
                         'harness-slides 0.14.0, for Claude Code and Codex.')
        self.assertFalse(keep.report()['update']['offered'])
        with self.assertRaises(WorkspaceError) as refused:
            keep.update(working=False)
        self.assertEqual(str(refused.exception), upkeep.NOTHING)

    def test_an_update_is_refused_while_a_training_is_working(self):
        keep = self.keeper()
        keep.check()
        with mock.patch.object(upkeep.companion, 'supervise') as ran:
            with self.assertRaises(WorkspaceError) as refused:
                keep.update(working=True)
        self.assertEqual(str(refused.exception), upkeep.WORKING)
        ran.assert_not_called()
        self.assertIsNone(keep.report()['update']['state'])

    def test_an_update_runs_the_installer_of_this_version_in_the_background(self):
        staged = self.installed()
        going, told = threading.Event(), []
        asked = []

        def supervise(command, cwd, env, stdin, seconds, errors, each, stop):
            asked.append((command, seconds))
            going.wait(30)
            each(json.dumps({'action': 'companions', 'companions': {
                'harness-research': {'state': 'installed', 'wanted': '0.8.0'},
                'harness-slides': {'state': 'failed', 'wanted': '0.13.1',
                                   'detail': 'its installer needs Node 20 or newer.'}}})
                 .encode())
            return 0, False

        keep = self.keeper(staged, after=lambda: told.append('looked again'))
        keep.check()
        with mock.patch.object(upkeep.companion, 'supervise', supervise):
            shown = keep.update(working=False)
            self.assertEqual(shown['update']['state'], 'running')
            self.assertFalse(shown['update']['offered'], 'one update at a time')
            with self.assertRaises(WorkspaceError) as refused:
                keep.update(working=False)
            self.assertEqual(str(refused.exception), upkeep.UPDATING)
            going.set()
            settle(keep)
        (command, seconds), = asked
        self.assertEqual(command[2:], [
            str(staged / 'installer' / 'install.py'), 'companions', '--companions', 'install',
            '--while-open', '--json', '--home', str(self.home), '--root', str(self.root)])
        self.assertEqual(seconds, upkeep.UPDATE_SECONDS)
        done = keep.report()['update']
        self.assertEqual(done['state'], 'failed')
        self.assertEqual(done['says'], 'harness-research 0.8.0 was installed by its own '
                         'installer. harness-slides 0.13.1 was not installed: its installer '
                         'needs Node 20 or newer.')
        self.assertEqual(told, ['looked again'])

    def test_an_update_that_takes_too_long_or_is_stopped_says_so(self):
        keep = self.keeper()
        keep.check()
        with mock.patch.object(upkeep.companion, 'supervise',
                               lambda *asked: (0, True)):
            keep.update(working=False)
            settle(keep)
        self.assertIn('did not finish in 40 minutes, so it was ended',
                      keep.report()['update']['says'])

        keep = self.keeper(self.root / 'current')
        keep.check()

        def held(command, cwd, env, stdin, seconds, errors, each, stop):
            self.assertTrue(stop.wait(30))
            return -9, False

        with mock.patch.object(upkeep.companion, 'supervise', held):
            keep.update(working=False)
            keep.close()
        self.assertEqual((keep.report()['update']['state'], keep.report()['update']['says']),
                         ('failed', upkeep.STOPPED))

    @unittest.skipUnless(NODE, 'a companion installs itself with Node')
    def test_an_update_brings_each_companion_through_its_own_checked_install(self):
        staged = self.installed('--target', 'claude')
        keep = self.keeper(staged)
        self.assertEqual([entry['state'] for entry in keep.check()['companions']],
                         ['missing', 'missing'])
        keep.update(working=False)
        settle(keep)
        done = keep.report()
        self.assertEqual(done['update']['state'], 'done', done['update']['says'])
        self.assertEqual(done['update']['says'], 'harness-research 0.8.0 was installed by its '
                         'own installer. harness-slides 0.13.1 was installed by its own '
                         'installer.')
        self.assertEqual([entry['found'] for entry in done['companions']],
                         [{'Claude Code': '0.8.0'}, {'Claude Code': '0.13.1'}])
        state = install.read_state(self.root)
        self.assertEqual(sorted(state['companions']), ['harness-research', 'harness-slides'])


class ReleaseCase(UpkeepCase):
    """An installed version, and Training Studio's repository with releases to tag."""

    def setUp(self):
        super().setUp()
        self.keep = self.keeper()
        self.keep.check()
        self.work = self.base / 'training-studio-work'
        git(self.base, 'init', '-q', str(self.work))
        (self.work / 'VERSION').write_text('1\n')
        git(self.work, 'add', '-A')
        git(self.work, 'commit', '-q', '-m', 'one')

    def release(self, *versions: str) -> None:
        for version in versions:
            git(self.work, 'tag', version)
        git(self.work, 'push', '-q', '--tags', str(self.source))

    def rows(self, keep: upkeep.Upkeep | None = None) -> dict:
        return {row['name']: row for row in (keep or self.keep).report()['versions']['rows']}


class ReleaseTests(ReleaseCase):
    def test_a_newer_training_studio_is_said_and_offered_from_the_page(self):
        self.release('v0.1.0', 'v99.0.0', 'not-a-release', 'v99.0.0-rc1')
        self.assertTrue(self.keep.look())
        shown = self.keep.report()
        own = self.rows()['training-studio']
        self.assertEqual((own['installed'], own['newest'], own['state'], own['target']),
                         (VERSION, '99.0.0', 'update', '99.0.0'))
        self.assertEqual(own['says'], f'Training Studio 99.0.0 is out, and this is {VERSION}.')
        versions = shown['versions']
        self.assertEqual((versions['checkout'], versions['command']), (False, None))
        self.assertEqual(versions['upgrade'], {
            'offered': True, 'version': '99.0.0', 'from': 'tag', 'state': None, 'since': None,
            'says': None, 'restart': False})
        self.assertEqual((shown['releases']['on'], shown['releases']['problem']), (True, None))
        kept = json.loads((self.root / upkeep.SAVED).read_text())
        commit = git(self.work, 'rev-parse', 'HEAD')
        self.assertEqual({key: kept['found']['training-studio'][key]
                          for key in ('latest', 'tag', 'commit')},
                         {'latest': '99.0.0', 'tag': 'v99.0.0', 'commit': commit})
        self.assertEqual(set(kept['found']), {'training-studio', 'harness-research',
                                              'harness-slides'})

    def test_an_annotated_release_is_known_by_the_commit_it_points_at(self):
        git(self.work, 'tag', '-a', '-m', 'A release', 'v99.0.1')
        git(self.work, 'push', '-q', '--tags', str(self.source))
        self.keep.look()
        kept = json.loads((self.root / upkeep.SAVED).read_text())
        self.assertEqual(kept['found']['training-studio']['commit'],
                         git(self.work, 'rev-parse', 'HEAD'))

    def test_a_companion_released_beyond_the_pin_is_said_and_never_offered(self):
        tag(_made['harness-slides'], 'v0.14.0')
        self.addCleanup(git, _made['harness-slides'].bare, 'tag', '-d', 'v0.14.0')
        for skills in (self.claude, self.codex):
            self.companion(skills, 'harness-research', '0.8.0')
            self.companion(skills, 'harness-slides', '0.13.1')
        self.keep.check()
        self.release('v0.1.0')
        self.keep.look()
        rows = self.rows()
        slides = rows['harness-slides']
        self.assertEqual((slides['installed'], slides['newest'], slides['pinned'],
                          slides['state'], slides['target']),
                         ('0.13.1', '0.14.0', '0.13.1', 'current', None))
        self.assertEqual(slides['beyond'], 'harness-slides 0.14.0 is out, newer than Training '
                         'Studio supports yet. It is offered once a Training Studio made with '
                         'it is out.')
        self.assertIsNone(rows['harness-research']['beyond'])
        self.assertEqual(rows['training-studio']['state'], 'current')
        shown = self.keep.report()
        self.assertFalse(shown['update']['offered'])
        self.assertFalse(shown['versions']['upgrade']['offered'])
        self.assertIsNone(shown['versions']['key'], 'nothing for Home to say')

    def test_it_looks_at_most_once_a_day_and_never_when_turned_off(self):
        self.release('v99.0.0')
        self.assertTrue(self.keep.look())
        known = self.rows()['training-studio']['known_at']
        shutil.rmtree(self.source)
        self.assertFalse(self.keep.look(), 'within a day it is not asked again')
        self.assertEqual(self.rows()['training-studio']['newest'], '99.0.0')
        kept = json.loads((self.root / upkeep.SAVED).read_text())
        kept['at'] = '2020-01-01T00:00:00Z'
        (self.root / upkeep.SAVED).write_text(json.dumps(kept))
        self.look_online(False)
        self.assertFalse(self.keep.look())
        self.assertFalse(self.keep.report()['releases']['on'])
        self.look_online(True)
        self.assertTrue(self.keep.look(), 'a day later it asks again')
        found = self.keep.report()['releases']
        self.assertIn('The last look for newer releases did not reach training-studio (',
                      found['problem'])
        self.assertTrue(found['problem'].endswith('It is tried again in a day.'))
        # Offline, what was last known is still shown, with when it was known.
        own = self.rows()['training-studio']
        self.assertEqual((own['newest'], own['state'], own['known_at']),
                         ('99.0.0', 'update', known))

    def test_before_anything_is_known_the_newest_is_unknown(self):
        own = self.rows()['training-studio']
        self.assertEqual((own['newest'], own['state']), (None, 'unknown'))
        self.assertIn('Whether a newer Training Studio is out is not known yet', own['says'])
        self.assertFalse(self.keep.report()['versions']['upgrade']['offered'])

    def test_once_installed_a_release_is_no_longer_newer(self):
        self.release(f'v{VERSION}')
        self.keep.look()
        own = self.rows()['training-studio']
        self.assertEqual((own['state'], own['says']),
                         ('current', f'Training Studio {VERSION} is the newest.'))

    def test_git_is_asked_without_a_terminal_and_with_a_short_time_limit(self):
        asked = []

        def run(repo, *args, input=None, timeout=None):
            asked.append((args, timeout))
            return subprocess.CompletedProcess(args, 0, '', '')

        with mock.patch.object(upkeep.hub, 'run', run):
            self.keep.look()
        self.assertEqual([args[:3] for args, _ in asked], [('ls-remote', '--tags', '--')] * 3)
        self.assertEqual({timeout for _, timeout in asked}, {upkeep.LOOK_SECONDS})

    def test_starting_looks_on_this_computer_then_online_in_the_background(self):
        self.release('v99.0.0')
        (self.claude / 'training-studio').unlink()
        let, order = threading.Event(), []
        local = upkeep.Upkeep._local

        def slow(keep, repair):
            order.append(repair)
            let.wait(30)
            return local(keep, repair)

        fresh = upkeep.Upkeep(home_dir=self.home, root=self.root,
                              installer=self.keep.installer)
        with mock.patch.object(upkeep.Upkeep, '_local', slow):
            begun = time.monotonic()
            fresh.start()
            self.assertLess(time.monotonic() - begun, 5, 'it answers at once')
            self.assertTrue(fresh.report()['checking'])
            self.assertFalse(os.path.lexists(self.claude / 'training-studio'))
            let.set()
            settle(fresh)
        self.assertEqual(order, [True])
        shown = fresh.report()
        self.assertFalse(shown['checking'])
        self.assertEqual(len(shown['repaired']), 1)
        self.assertEqual(shown['versions']['rows'][0]['newest'], '99.0.0')


class UpgradeTests(ReleaseCase):
    """Upgrading Training Studio itself: refused where it must be, and what it runs. The
    whole upgrade, from an older install to a newer one, is the page tests'."""

    def test_a_checkout_shows_the_versions_and_says_it_is_upgraded_with_git_pull(self):
        keep = upkeep.Upkeep(home_dir=self.home, root=self.base / 'nothing-installed',
                             installer=helpers.REPO / 'installer' / 'install.py')
        keep.check()
        self.release('v99.0.0')
        keep.look()
        versions = keep.report()['versions']
        self.assertEqual((versions['checkout'], versions['command']),
                         (True, f'cd {helpers.REPO} && git pull'))
        own = versions['rows'][0]
        self.assertEqual((own['installed'], own['newest'], own['state']),
                         (VERSION, '99.0.0', 'update'))
        self.assertIn('upgraded there with git pull, not from here', own['says'])
        self.assertFalse(versions['upgrade']['offered'])
        with self.assertRaises(WorkspaceError) as refused:
            keep.upgrade(False, '99.0.0')
        self.assertEqual(str(refused.exception), upkeep.FROM_CHECKOUT)

    def test_an_upgrade_is_refused_while_working_and_unless_it_is_the_newest(self):
        self.release('v99.0.0')
        self.keep.look()
        with mock.patch.object(upkeep.companion, 'supervise') as ran:
            for working, version, said in (
                    (True, '99.0.0', upkeep.UPGRADE_WORKING),
                    (False, '98.0.0', 'The newest Training Studio is now 99.0.0, not 98.0.0. '
                                      'Look at it again before you upgrade.')):
                with self.assertRaises(WorkspaceError) as refused:
                    self.keep.upgrade(working, version)
                self.assertEqual(str(refused.exception), said)
        ran.assert_not_called()
        self.assertIsNone(self.keep.report()['versions']['upgrade']['state'])
        with self.assertRaises(WorkspaceError) as refused:
            upkeep.Upkeep(home_dir=self.home, root=self.root,
                          installer=self.base / 'gone' / 'install.py').upgrade(False, '99.0.0')
        self.assertEqual(str(refused.exception), upkeep.NO_INSTALLER)

    def test_the_upgrade_runs_the_fetched_versions_own_installer_beside_this_one(self):
        self.release('v99.0.0')
        self.keep.look()
        asked, fetched = [], []

        def fetch(repository, ref, into):
            fetched.append((repository, ref))
            tree = into / 'tree'
            (tree / 'skills' / 'training-studio').mkdir(parents=True)
            (tree / 'skills' / 'training-studio' / 'VERSION').write_text('99.0.0\n')
            return tree, 'c' * 40

        def supervise(command, cwd, env, stdin, seconds, errors, each, stop):
            asked.append((command, seconds))
            staged = self.root / 'versions' / '99.0.0-abcdef012345'
            staged.mkdir(parents=True)
            install.replace_link(self.root / 'current', staged)
            each(json.dumps({'action': 'install', 'mode': 'managed',
                             'version': '99.0.0-abcdef012345'}).encode())
            return 0, False

        with mock.patch.object(upkeep, 'fetch_tree', fetch), \
                mock.patch.object(upkeep.companion, 'supervise', supervise):
            shown = self.keep.upgrade(False, '99.0.0')
            self.assertEqual(shown['versions']['upgrade']['state'], 'running')
            self.assertFalse(shown['versions']['upgrade']['offered'])
            settle(self.keep)
        self.assertEqual(fetched, [(str(self.source), 'refs/tags/v99.0.0')])
        (command, seconds), = asked
        self.assertEqual(command[3:], [
            'install', '--yes', '--json', '--companions', 'skip', '--while-open',
            '--home', str(self.home), '--root', str(self.root), '--target', 'both'])
        self.assertTrue(command[2].endswith('/tree/installer/install.py'))
        self.assertEqual(seconds, upkeep.UPGRADE_SECONDS)
        versions = self.keep.report()['versions']
        self.assertEqual((versions['upgrade']['state'], versions['upgrade']['restart']),
                         ('restart', True))
        self.assertEqual(versions['upgrade']['says'], 'Training Studio 99.0.0 is installed, '
                         'checked and in place. Restart to use it. This page comes back by '
                         'itself.')
        self.assertEqual(versions['rows'][0]['says'],
                         'Training Studio 99.0.0 is installed. Restart to use it.')
        with self.assertRaises(WorkspaceError) as refused:
            self.keep.update(False)
        self.assertIn('waits for a restart', str(refused.exception))

        # Restarting: refused while a training works, then the runner is asked to leave.
        left = []
        self.keep.leave = lambda: left.append('left')
        with self.assertRaises(WorkspaceError) as refused:
            self.keep.restart(True)
        self.assertEqual(str(refused.exception), upkeep.RESTART_WORKING)
        self.assertEqual(self.keep.restart(False)['versions']['upgrade']['state'],
                         'restarting')
        self.assertEqual((self.keep.restarting, left),
                         (['/bin/sh', str(self.root / 'studio'), 'serve'], ['left']))

    def test_a_version_that_is_not_the_one_shown_is_not_installed(self):
        self.release('v99.0.0')
        self.keep.look()

        def fetch(repository, ref, into):
            (into / 'tree' / 'skills' / 'training-studio').mkdir(parents=True)
            (into / 'tree' / 'skills' / 'training-studio' / 'VERSION').write_text('1.0.0\n')
            return into / 'tree', 'c' * 40

        with mock.patch.object(upkeep, 'fetch_tree', fetch), \
                mock.patch.object(upkeep.companion, 'supervise') as ran:
            self.keep.upgrade(False, '99.0.0')
            settle(self.keep)
        ran.assert_not_called()
        upgrade = self.keep.report()['versions']['upgrade']
        self.assertEqual(upgrade['state'], 'failed')
        self.assertEqual(upgrade['says'], f'Training Studio 99.0.0 was not installed: '
                         f'{self.source} has version 1.0.0 at refs/tags/v99.0.0.')
        with self.assertRaises(WorkspaceError) as refused:
            self.keep.restart(False)
        self.assertEqual(str(refused.exception), upkeep.NO_RESTART)

    def test_a_revision_is_fetched_by_name_as_plain_files_only(self):
        (self.work / 'run.sh').write_text('#!/bin/sh\n')
        (self.work / 'run.sh').chmod(0o755)
        (self.work / 'link').symlink_to('/etc/passwd')
        git(self.work, 'add', '-A')
        git(self.work, 'commit', '-q', '-m', 'two')
        self.release('v99.0.0')
        into = self.base / 'fetched'
        into.mkdir()
        tree, commit = upkeep.fetch_tree(str(self.source), 'refs/tags/v99.0.0', into)
        self.assertEqual(commit, git(self.work, 'rev-parse', 'HEAD'))
        self.assertEqual(sorted(path.name for path in tree.iterdir()), ['VERSION', 'run.sh'])
        self.assertTrue(os.access(tree / 'run.sh', os.X_OK))
        self.assertEqual(sorted(path.name for path in into.iterdir()), ['tree'])
        for wrong in ('HEAD', 'refs/tags/../x', '--upload-pack=x'):
            with self.assertRaises(sync_guidance.SyncError):
                upkeep.fetch_tree(str(self.source), wrong, self.base)


class GuidanceTests(UpkeepCase):
    def test_which_guidance_a_new_training_gets_is_said(self):
        keep = self.keeper()
        self.assertEqual(keep.report()['guidance'], {
            'commit': None, 'at': None, 'says': f'New trainings follow the guidance installed '
            f'with Training Studio {VERSION}. None has been fetched on this computer yet.'})
        remote, commit = self.main_at('99.1.0')
        found = keep.report()['guidance']
        self.assertEqual(found['commit'], commit[:12])
        self.assertEqual(found['says'], f'New trainings follow the guidance from revision '
                         f'{commit[:12]} of main, the newest when guidance was last fetched.')
        # The version on main then is known without asking anything online.
        self.look_online(False)
        keep.check()
        own = keep.report()['versions']['rows'][0]
        self.assertEqual((own['name'], own['newest'], own['state']),
                         ('training-studio', '99.1.0', 'update'))
        self.assertEqual(keep.report()['versions']['upgrade']['from'], 'main')
        # A cache the helper would rebuild is not read, and nothing here rebuilds it.
        cache = sync_guidance.guidance_root() / 'cache.git'
        git(cache, 'update-ref', 'refs/heads/planted', commit)
        keep.check()
        self.assertEqual(keep.report()['versions']['rows'][0]['state'], 'unknown')
        self.assertTrue((cache / 'refs' / 'heads' / 'planted').is_file())

    def main_at(self, version: str, slides: str | None = None) -> tuple[Path, str]:
        """Training Studio's repository with `version` on main, pinning harness-slides at
        `slides`, and guidance fetched from it as a training's start fetches it."""
        remote = self.base / 'remote'
        if not remote.exists():
            shutil.copytree(helpers.SKILL, remote / 'skills' / 'training-studio',
                            ignore=shutil.ignore_patterns('__pycache__'))
            (remote / 'guidance').mkdir()
            (remote / 'guidance' / 'manifest.json').write_text(json.dumps(
                {'schema': 1, 'content_root': 'skills/training-studio',
                 'minimum_runtime': '0.1.0'}))
            git(self.base, 'init', '-q', str(remote))
            git(remote, 'symbolic-ref', 'HEAD', 'refs/heads/main')
        (remote / 'skills' / 'training-studio' / 'VERSION').write_text(f'{version}\n')
        if slides:
            pins = json.loads(json.dumps(_made['pins']))
            pins['harness-slides'].update(version=slides, commit='a' * 40, sha256='b' * 64)
            (remote / 'installer').mkdir(exist_ok=True)
            write_pins(remote / 'installer' / 'companions.json', pins)
        git(remote, 'add', '-A')
        git(remote, 'commit', '-q', '-m', f'Version {version}')
        project = self.base / 'a-training'
        project.mkdir(exist_ok=True)
        with mock.patch.dict(os.environ, {'TRAINING_STUDIO_SOURCE': str(remote)}):
            sync_guidance.start(project)
        return remote, git(remote, 'rev-parse', 'HEAD')

    def test_what_the_newest_is_pinned_to_is_read_where_guidance_is_kept(self):
        keep = self.keeper()
        for skills in (self.claude, self.codex):
            self.companion(skills, 'harness-research', '0.8.0')
            self.companion(skills, 'harness-slides', '0.13.1')
        remote, commit = self.main_at('99.1.0', slides='0.14.0')
        self.look_online(False)
        keep.check()
        rows = {row['name']: row for row in keep.report()['versions']['rows']}
        slides = rows['harness-slides']
        self.assertEqual((slides['installed'], slides['pinned'], slides['next'],
                          slides['state'], slides['target']),
                         ('0.13.1', '0.13.1', '0.14.0', 'update', '0.14.0'))
        self.assertEqual(slides['says'], 'harness-slides 0.14.0 comes with Training Studio '
                         '99.1.0, which is made with it. This computer has 0.13.1.')
        self.assertEqual((rows['harness-research']['next'], rows['harness-research']['state']),
                         ('0.8.0', 'current'))
        self.assertEqual(keep.report()['versions']['key'],
                         'training-studio 99.1.0, harness-slides 0.14.0')
        self.assertFalse(keep.report()['update']['offered'],
                         'nothing unpinned: it comes with the newer Training Studio')

        # Online: a release of the companion beyond even the newest pin, and a release of
        # Training Studio at the commit main has, whose pins are read the same way.
        tag(_made['harness-slides'], 'v0.15.0')
        self.addCleanup(git, _made['harness-slides'].bare, 'tag', '-d', 'v0.15.0')
        git(remote, 'tag', 'v99.1.0')
        self.look_online(True)
        with mock.patch.dict(os.environ, {'TRAINING_STUDIO_SOURCE': str(remote)}):
            self.assertTrue(keep.look())
        rows = {row['name']: row for row in keep.report()['versions']['rows']}
        self.assertEqual((rows['harness-slides']['next'], rows['harness-slides']['newest']),
                         ('0.14.0', '0.15.0'))
        self.assertIn('harness-slides 0.15.0 is out, newer than Training Studio supports yet',
                      rows['harness-slides']['beyond'])
        self.assertEqual(keep.report()['versions']['upgrade']['from'], 'tag')

        # A release whose commit was never fetched with main: its pins are not guessed.
        (remote / 'elsewhere').write_text('not on main\n')
        git(remote, 'checkout', '-q', '-b', 'side')
        git(remote, 'add', '-A')
        git(remote, 'commit', '-q', '-m', 'Off main')
        git(remote, 'tag', 'v99.2.0')
        saved = json.loads((self.root / upkeep.SAVED).read_text())
        saved['at'] = '2020-01-01T00:00:00Z'
        (self.root / upkeep.SAVED).write_text(json.dumps(saved))
        with mock.patch.dict(os.environ, {'TRAINING_STUDIO_SOURCE': str(remote)}):
            self.assertTrue(keep.look())
        rows = {row['name']: row for row in keep.report()['versions']['rows']}
        self.assertEqual((rows['training-studio']['newest'], rows['harness-slides']['next'],
                          rows['harness-slides']['state']), ('99.2.0', None, 'current'))
        self.assertIn('Which version Training Studio 99.2.0 is made with is not known here yet',
                      rows['harness-slides']['says'])


if __name__ == '__main__':
    unittest.main()
