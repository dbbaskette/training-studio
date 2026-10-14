"""The runner's command line: `studio serve` and `studio status`.

`serve` is tested with a server that binds no port, and once as a real process on a local
port, which is skipped where a port cannot be opened. No agent is started.
"""
import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

import helpers
from runner_support import StudioCase, fails

import cmd_desk
from runner import gitstate, page, studio

VERSION = (helpers.SKILL / 'VERSION').read_text().strip()
STUDIO = helpers.REPO / 'runner' / 'studio.py'
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Terminal(io.StringIO):
    """Standard output that is, or is not, a person's terminal."""

    def __init__(self, person: bool):
        super().__init__()
        self.person = person

    def isatty(self) -> bool:
        return self.person


class Server:
    """A stand-in for the runner's server that opens no port."""
    made = []

    def __init__(self, engine, port: int = 0):
        self.engine, self.port, self.did = engine, port or 8765, []
        self.token = 'the-key'
        self.address = f'http://127.0.0.1:{self.port}/'
        self.url = f'{self.address}#token={self.token}'
        Server.made.append(self)

    def serve(self) -> None:
        self.did.append('serve')

    def stop(self) -> None:
        self.did.append('stop')


class ServeTests(StudioCase):
    def setUp(self):
        super().setUp()
        Server.made = []
        patcher = mock.patch.object(page, 'Studio', Server)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.opened = []

    def serve(self, person: bool, *args: str, opens: bool = True) -> dict:
        out = Terminal(person)

        def opener(url: str) -> bool:
            self.opened.append(url)
            return opens

        chosen = studio.parser().parse_args(['serve', *args])
        self.assertEqual(studio.serve(chosen, make=lambda: self.engine, out=out,
                                      opener=opener), 0)
        printed = out.getvalue()
        self.assertEqual(printed.count('\n'), 1, 'one line, so a script can read it')
        return json.loads(printed)

    def test_to_a_terminal_it_prints_the_link_whole_and_opens_nothing(self):
        printed = self.serve(True)
        self.assertEqual(printed, {'url': 'http://127.0.0.1:8765/#token=the-key'})
        self.assertEqual((self.opened, Server.made[0].did), ([], ['serve', 'stop']))

    def test_asked_to_open_it_shows_a_person_the_page_as_well_as_the_link(self):
        printed = self.serve(True, '--open')
        self.assertEqual(printed, {'url': 'http://127.0.0.1:8765/#token=the-key'})
        self.assertEqual(self.opened, ['http://127.0.0.1:8765/#token=the-key'])
        self.assertEqual(self.serve(False, '--open')['opened'], True)
        self.assertEqual(len(self.opened), 2, 'opened once, not twice, for anything else')

    def test_to_anything_else_it_prints_no_key_and_opens_the_page_itself(self):
        printed = self.serve(False, '--port', '9000')
        self.assertEqual(printed, {'address': 'http://127.0.0.1:9000/', 'opened': True,
                                   'note': cmd_desk.NOT_A_PERSON})
        self.assertNotIn('the-key', json.dumps(printed))
        self.assertEqual(self.opened, ['http://127.0.0.1:9000/#token=the-key'])
        self.assertEqual(self.serve(False, opens=False)['opened'], False)

    def test_starting_picks_every_training_up_where_its_files_say_it_is(self):
        self.workers.then('research-plan', fails())
        root = self.start()
        self.assertEqual(len(self.workers.jobs), 2)
        (root / 'blueprint.md').write_text('# Left by a step that never finished\n')
        self.workers.then('research-plan', fails(), fails(), fails())
        failing = self.start(title='Health checks')
        self.engine.close()
        self.engine = self.make()
        self.serve(True)
        self.assertEqual([self.state(found) for found in (root, failing)],
                         ['waiting', 'failed'])
        self.assertTrue((root / 'blueprint.md').exists(), 'a training at a gate is left be')
        self.assertEqual(len(self.workers.jobs), 5, 'nothing is done twice')

    def test_it_refuses_to_start_without_a_git_identity_and_says_the_fix(self):
        (self.base / 'nobody.gitconfig').write_text('[user]\n\tuseConfigOnly = true\n')
        out = io.StringIO()
        with mock.patch.dict(os.environ, {'GIT_CONFIG_GLOBAL':
                                          str(self.base / 'nobody.gitconfig')}):
            with contextlib.redirect_stdout(out):
                code = studio.main(['serve'])
        said = json.loads(out.getvalue())['error']
        self.assertEqual((code, Server.made), (2, []))
        self.assertIn('git does not know who you are', said)
        self.assertIn('git config --global user.name "Your Name"', said)

    def test_only_one_runner_serves_on_a_computer_at_a_time(self):
        import home
        marker = home.data_root() / 'runner.pid'
        another = subprocess.Popen([sys.executable, '-c', 'import time\ntime.sleep(60)'])
        self.addCleanup(another.wait)
        self.addCleanup(another.kill)
        marker.write_text(f'{another.pid}\n')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = studio.main(['serve'])
        said = json.loads(out.getvalue())['error']
        self.assertEqual((code, Server.made), (2, []))
        self.assertIn(f'A runner is already serving on this computer (process {another.pid})',
                      said)
        self.assertEqual(marker.read_text(), f'{another.pid}\n')
        another.kill()
        another.wait()
        self.assertEqual(sorted(self.serve(True)), ['url'], 'one that ended is not counted')
        self.assertFalse(marker.exists(), 'and this one says when it has ended')

    def test_before_anything_is_set_up_it_still_serves_so_the_page_can_set_it_up(self):
        gitstate.settings_path().unlink()
        self.assertEqual(sorted(self.serve(True)), ['url'])

    def test_a_port_that_is_not_one_is_a_usage_error(self):
        for port in ('http', '70000', '-1'):
            with self.subTest(port), self.assertRaises(SystemExit) as stopped:
                with contextlib.redirect_stderr(io.StringIO()):
                    studio.parser().parse_args(['serve', '--port', port])
            self.assertEqual(stopped.exception.code, 2)


class StatusTests(StudioCase):
    def status(self) -> dict:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(studio.main(['status']), 0)
        return json.loads(out.getvalue())

    def test_status_is_json_for_a_script(self):
        self.workers.then('research-plan', fails(), fails(), fails())
        failing = self.start()
        waiting = self.start(title='Health checks')
        found = self.status()
        self.assertEqual(sorted(found), ['agent', 'brand', 'configured', 'limits', 'notify',
                                         'previews', 'trainings', 'version', 'workspace'])
        self.assertEqual((found['version'], found['configured'], found['agent']),
                         (VERSION, True, {'default': 'claude', 'model': None}))
        self.assertEqual((found['workspace']['path'], found['workspace']['folder']),
                         (str(self.space.repo), 'trainings'))
        self.assertEqual(found['trainings'], [
            {'path': str(waiting), 'id': 'health-checks', 'state': 'waiting',
             'sentence': 'The research plan is waiting for your review.'},
            {'path': str(failing), 'id': 'rolling-restarts', 'state': 'failed',
             'sentence': self.view(failing)['sentence']}])
        self.assertEqual(len(self.workers.jobs), 4, 'asking starts nothing')

    def test_status_before_anything_is_set_up(self):
        gitstate.settings_path().unlink()
        found = self.status()
        self.assertEqual((found['configured'], found['workspace'], found['trainings']),
                         (False, None, []))


class ProcessTests(StudioCase):
    """`studio serve` as a person starts it: a process of its own, on a local port."""

    def launch(self, opened: Path):
        recorder = self.base / 'recorder.py'
        recorder.write_text('import sys\nopen(sys.argv[1], "w").write(sys.argv[2])\n')
        environment = {**os.environ, 'BROWSER': f'{sys.executable} {recorder} {opened} %s'}
        process = subprocess.Popen(
            [sys.executable, str(STUDIO), 'serve'], cwd=self.base, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True, env=environment)
        guard = threading.Timer(60, process.kill)
        guard.start()

        def finish():
            guard.cancel()
            if process.poll() is None:
                process.kill()
                process.wait()
            for stream in (process.stdout, process.stderr):
                stream.close()
        self.addCleanup(finish)
        return process

    @unittest.skipIf(os.name == 'nt', 'signals are delivered differently on Windows')
    def test_it_serves_the_page_and_the_runner_until_it_is_interrupted(self):
        opened = self.base / 'opened.txt'
        process = self.launch(opened)
        line = process.stdout.readline()
        printed = json.loads(line)
        if 'error' in printed:
            self.skipTest(f"This environment does not allow listening on a local port: "
                          f"{printed['error']}")
        self.assertEqual(set(printed), {'address', 'opened', 'note'})
        self.assertNotIn('token', line)
        url = opened.read_text()
        address, _, fragment = url.partition('#')
        self.assertEqual(address, printed['address'])
        request = urllib.request.Request(f'{address}api/capabilities', headers={
            'X-Training-Studio-Token': fragment.removeprefix('token=')})
        with DIRECT.open(request, timeout=20) as response:
            self.assertEqual(json.loads(response.read()), {'runner': True, 'version': VERSION})
        self.assertIsNone(process.poll())
        process.send_signal(signal.SIGTERM)
        rest, errors = process.communicate(timeout=30)
        self.assertEqual((process.returncode, rest, errors), (0, '', ''))


if __name__ == '__main__':
    unittest.main()
