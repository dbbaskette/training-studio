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
from runner import engine as engines
from runner import gitstate, page, settings, studio, upkeep

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

    def __init__(self, engine, port: int = 0, token: str | None = None):
        self.engine, self.port, self.did = engine, port or 8765, []
        self.token = token or 'the-key'
        self.address = f'http://127.0.0.1:{self.port}/'
        self.url = f'{self.address}#token={self.token}'
        Server.made.append(self)

    def serve(self) -> None:
        self.did.append('serve')

    def stop(self) -> None:
        self.did.append('stop')

    def leave(self) -> None:
        self.did.append('leave')


class Keeper:
    """A stand-in for what looks after the skills on this computer: it records what it is
    asked, and looks at nothing."""
    made = []

    def __init__(self, after=None):
        self.after, self.did = after, []
        Keeper.made.append(self)

    def start(self):
        self.did.append('start')

    def check(self, repair=True):
        self.did.append(('check', repair))
        return {}

    def report(self):
        return {'stand_in': True}

    def close(self):
        self.did.append('close')


class ServeTests(StudioCase):
    def setUp(self):
        super().setUp()
        Server.made, Keeper.made = [], []
        for patcher in (mock.patch.object(page, 'Studio', Server),
                        mock.patch.object(upkeep, 'Upkeep', Keeper)):
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
        # To anything that is not a person's terminal, asking changes nothing: the address
        # goes out without its key, and only the browser is handed the key.
        piped = self.serve(False, '--open')
        self.assertEqual(piped, {'address': 'http://127.0.0.1:8765/', 'opened': True,
                                 'note': cmd_desk.NOT_A_PERSON})
        self.assertNotIn('the-key', json.dumps(piped))
        self.assertEqual(len(self.opened), 2, 'opened once, not twice, for anything else')
        self.assertEqual(self.serve(False, '--open', opens=False)['opened'], False,
                         'with no browser to open, the key goes nowhere at all')

    def test_to_anything_else_it_prints_no_key_and_opens_the_page_itself(self):
        printed = self.serve(False, '--port', '9000')
        self.assertEqual(printed, {'address': 'http://127.0.0.1:9000/', 'opened': True,
                                   'note': cmd_desk.NOT_A_PERSON})
        self.assertNotIn('the-key', json.dumps(printed))
        self.assertEqual(self.opened, ['http://127.0.0.1:9000/#token=the-key'])
        self.assertEqual(self.serve(False, opens=False)['opened'], False)

    def test_once_it_answers_the_skills_are_looked_after_in_the_background(self):
        seen = []

        def answering(server):
            seen.append(list(Keeper.made[0].did))
            server.did.append('serve')

        with mock.patch.object(Server, 'serve', answering):
            self.serve(True)
        (keeper,) = Keeper.made
        self.assertEqual(seen, [['start']], 'started before serving, and never waited for')
        self.assertIs(self.engine.upkeep, keeper)
        self.assertEqual(keeper.after, self.engine.look_again,
                         'once it changes the skills, the computer is looked at again')
        self.engine.close()
        self.assertEqual(keeper.did, ['start', 'close'], 'closing ends an update in hand')

    def test_after_an_upgrade_it_opens_the_newer_version_in_its_own_place(self):
        ran, key = [], 'k' * 43

        def restarted(server):
            server.did.append('serve')
            keeper = Keeper.made[-1]
            self.assertEqual(keeper.leave, server.leave, 'the keeper can stop it')
            keeper.restarting = ['/bin/sh', '/home/pat/studio', 'serve']

        def execv(path, argv):
            ran.append((path, argv, os.environ.get(studio.RESTART)))

        with mock.patch.object(Server, 'serve', restarted), \
                mock.patch.dict(os.environ, {}):
            out = Terminal(False)
            chosen = studio.parser().parse_args(['serve', '--port', '9001'])
            self.assertEqual(studio.serve(chosen, make=lambda: self.engine, out=out,
                                          opener=self.opened.append, execv=execv), 0)
            self.assertEqual(ran, [('/bin/sh', ['/bin/sh', '/home/pat/studio', 'serve',
                                                '--port', '9001'],
                                    json.dumps({'token': 'the-key'}))])
            self.assertEqual(Server.made[-1].did, ['serve', 'stop'],
                             'stopped whole before the newer one is opened')
            self.assertFalse((self.base / 'data' / 'runner.pid').exists())

        # The newer one takes the key from the environment, once, and opens no page.
        with mock.patch.dict(os.environ, {}):
            self.opened.clear()
            os.environ[studio.RESTART] = json.dumps({'token': key})
            printed = self.serve(False, '--port', '9001')
            self.assertNotIn(studio.RESTART, os.environ, 'nothing it starts is given the key')
            self.assertEqual((Server.made[-1].token, printed['opened'], self.opened),
                             (key, False, []))
            os.environ[studio.RESTART] = json.dumps({'token': 'short'})
            self.serve(False)
            self.assertEqual(Server.made[-1].token, 'the-key', 'a key of the wrong shape')

    def test_when_the_newer_version_cannot_be_opened_it_says_so(self):
        def restarted(server):
            Keeper.made[-1].restarting = ['/bin/sh', '/gone/studio', 'serve']

        def execv(path, argv):
            raise FileNotFoundError(2, 'No such file or directory')

        with mock.patch.object(Server, 'serve', restarted), mock.patch.dict(os.environ, {}):
            out = Terminal(True)
            chosen = studio.parser().parse_args(['serve'])
            self.assertEqual(studio.serve(chosen, make=lambda: self.engine, out=out,
                                          execv=execv), 2)
            self.assertNotIn(studio.RESTART, os.environ)
        said = json.loads(out.getvalue().splitlines()[-1])['error']
        self.assertIn('Training Studio could not open again by itself', said)

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

    def test_the_page_answers_while_the_workspace_is_still_fetched(self):
        root = self.start()
        (root / engines.IN_HAND).write_text('research-plan\n')
        self.engine.close()
        self.engine = self.make(background=True)
        fetching, go, fetched, woken = (threading.Event(), threading.Event(),
                                        threading.Event(), [])

        def slow():
            fetching.set()
            go.wait(30)
            fetched.set()
            return {'reached': None, 'received': 0, 'notice': None}

        def answering(server):
            server.did.append('serve while fetching' if fetching.wait(10)
                              and not fetched.is_set() else 'serve after fetching')

        with mock.patch.object(self.engine, 'fetch', slow), \
                mock.patch.object(self.engine, 'wake', woken.append), \
                mock.patch.object(Server, 'serve', answering):
            self.serve(True)
            self.assertEqual(Server.made[0].did, ['serve while fetching', 'stop'])
            self.assertEqual(woken, [], 'nothing carries on before the fetch')
            self.assertFalse((root / engines.IN_HAND).exists(),
                             'what a step left behind was tidied before the page answered')
            go.set()
            for thread in threading.enumerate():
                if thread.name == 'resuming':
                    thread.join(30)
        self.assertEqual(woken, [root], 'picked up once the fetch is done')

    def test_what_goes_wrong_picking_trainings_up_is_said_and_the_rest_still_carry_on(self):
        first, second = self.start(), self.start(title='Health checks')
        self.engine.close()
        self.engine = self.make(background=True)
        woken = []

        def broken():
            raise RuntimeError('the fetch broke')

        def wake(root):
            if root == first:
                raise RuntimeError('the run would not start')
            woken.append(root)

        with mock.patch.object(self.engine, 'fetch', broken), \
                mock.patch.object(self.engine, 'wake', wake):
            self.engine.resume(wait=False)
            for thread in threading.enumerate():
                if thread.name == 'resuming':
                    thread.join(30)
        self.assertEqual(woken, [second], 'the others are still picked up')
        self.assertIn('Something went wrong while the runner picked its trainings up (the '
                      'run would not start)', self.view(first)['notice'])
        self.assertEqual(self.view(second)['notice'], self.view(first)['notice'])

    def test_it_refuses_to_start_without_a_git_identity_and_says_the_fix(self):
        helpers.gitconfig(self.base / 'nobody.gitconfig', '[user]\n\tuseConfigOnly = true\n')
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
    def setUp(self):
        super().setUp()
        Keeper.made = []
        patcher = mock.patch.object(upkeep, 'Upkeep', Keeper)
        patcher.start()
        self.addCleanup(patcher.stop)

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
                                         'previews', 'shared', 'shared_problem', 'trainings',
                                         'updates', 'upkeep', 'version', 'workspace'])
        # What was found of the skills, looked at as they are: nothing is put back, and
        # nothing is asked online.
        self.assertEqual((found['upkeep'], found['updates']),
                         ({'stand_in': True}, {'look': True}))
        self.assertEqual(Keeper.made[0].did, [('check', False)])
        self.assertEqual((found['version'], found['configured'], found['agent']),
                         (VERSION, True,
                          {'default': 'claude', 'model': None, 'effort': None}))
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

    def launch(self, opened: Path, programs: Path | None = None):
        recorder = self.base / 'recorder.py'
        recorder.write_text('import sys\nopen(sys.argv[1], "w").write(sys.argv[2])\n')
        # A home of its own, and no look online: nothing real is read and nothing is asked.
        (self.base / 'home').mkdir(exist_ok=True)
        settings.save(settings.Settings(look_for_updates=False))
        environment = {**os.environ, 'BROWSER': f'{sys.executable} {recorder} {opened} %s',
                       'HOME': str(self.base / 'home')}
        if programs:
            environment['PATH'] = f'{programs}{os.pathsep}{environment["PATH"]}'
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

    @unittest.skipIf(os.name == 'nt', 'the stand-in for Codex is a shell script')
    def test_each_agents_models_are_listed_by_the_running_server(self):
        programs = self.base / 'programs'
        programs.mkdir()
        catalog = {'models': [
            {'slug': 'gpt-6-sol', 'display_name': 'GPT-6-Sol', 'visibility': 'list',
             'default_reasoning_level': 'medium',
             'supported_reasoning_levels': [{'effort': 'low'}, 'medium']},
            {'slug': 'gpt-hidden', 'visibility': 'hide'}]}
        codex = programs / 'codex'
        codex.write_text(f"#!/bin/sh\necho '{json.dumps(catalog)}'\n")
        codex.chmod(0o755)
        opened = self.base / 'opened.txt'
        process = self.launch(opened, programs)
        printed = json.loads(process.stdout.readline())
        if 'error' in printed:
            self.skipTest(f"This environment does not allow listening on a local port: "
                          f"{printed['error']}")
        address, _, fragment = opened.read_text().partition('#')
        key = {'X-Training-Studio-Token': fragment.removeprefix('token=')}

        def models(agent: str) -> dict:
            request = urllib.request.Request(f'{address}api/models?agent={agent}', headers=key)
            with DIRECT.open(request, timeout=30) as response:
                return json.loads(response.read())

        self.assertEqual(models('codex'), {'agent': 'codex', 'problem': None, 'levels': [
            'low', 'medium'], 'source': None, 'models': [
                {'name': 'gpt-6-sol', 'label': 'GPT-6-Sol (gpt-6-sol)', 'family': None,
                 'about': None, 'default_level': 'medium', 'levels': ['low', 'medium']}]})
        claude = models('claude')
        self.assertEqual(claude['source'], 'Anthropic model reference, cached 2026-10-06')
        self.assertEqual([model['name'] for model in claude['models']][:4],
                         ['fable', 'claude-fable-5-1', 'claude-fable-5', 'opus'])
        self.assertEqual(claude['models'][-1]['levels'], [])
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=30)


if __name__ == '__main__':
    unittest.main()
