"""The training desk: what its read-only API returns, what it refuses, and the command."""
import contextlib
import io
import json
import os
import re
import signal
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode, urlsplit

import helpers
import test_cli
import desk
import training
import validate_package
import workspace

PAGE = helpers.SCRIPTS / 'desk'
PAGE_FILES = ('index.html', 'app.js', 'style.css')
SECURITY_HEADERS = {'Content-Security-Policy': "default-src 'self'",
                    'X-Content-Type-Options': 'nosniff',
                    'Cache-Control': 'no-store'}
# Straight to the socket: a proxy named in the environment must not sit in between.
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
MARKUP = '<script>alert(1)</script>\n<img src=x onerror=alert(2)>\n'


def ask(url: str, headers: dict | None = None, method: str = 'GET'):
    """One request. Returns the status, the headers and the body, refused or not."""
    request = urllib.request.Request(url, headers=headers or {}, method=method)
    try:
        with DIRECT.open(request, timeout=10) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as refused:
        with refused:
            return refused.code, refused.headers, refused.read()


class DeskCase(test_cli.Flow):
    """A registry of its own, and a desk serving on a port the system chose."""

    def setUp(self):
        super().setUp()
        data = self.root.parent / 'data'
        patcher = mock.patch.dict(os.environ, {'TRAINING_STUDIO_DATA': str(data)})
        patcher.start()
        self.addCleanup(patcher.stop)
        try:
            self.desk = desk.Desk()
        except PermissionError as refused:
            self.skipTest(f'This environment does not allow listening on a local port: {refused}')
        self.addCleanup(self.desk.stop)
        self.desk.start()

    def another(self, name: str, *init_args) -> Path:
        """A second training in its own folder, registered like the first."""
        root = self.root.parent / name
        root.mkdir()
        with contextlib.redirect_stdout(io.StringIO()):
            code = training.main(['--dir', str(root), 'init', '--title', name.title(),
                                  *init_args])
        self.assertEqual(code, 0)
        return root

    def fetch(self, target: str, token=True, host: str | None = None, method: str = 'GET'):
        """Ask the desk. `token` is True for the right one, False for none, or one to send."""
        headers = {}
        if token:
            headers[desk.TOKEN_HEADER] = self.desk.token if token is True else token
        if host:
            headers['Host'] = host
        return ask(f'http://127.0.0.1:{self.desk.port}{target}', headers, method)

    def api(self, endpoint: str, expect: int = 200, **params) -> dict:
        target = f'/api/{endpoint}' + (f'?{urlencode(params)}' if params else '')
        status, headers, body = self.fetch(target)
        self.assertEqual(status, expect, body)
        self.assertEqual(headers.get_content_type(), 'application/json')
        return json.loads(body)

    def listed(self) -> dict:
        return {item['path']: item for item in self.api('trainings')['trainings']}

    def seen(self, when: dict) -> None:
        """Rewrite when the registry last saw each training."""
        registry = Path(os.environ['TRAINING_STUDIO_DATA']) / 'registry.json'
        record = json.loads(registry.read_text(encoding='utf-8'))
        for root, stamp in when.items():
            record['trainings'][str(root)]['seen_at'] = stamp
        registry.write_text(json.dumps(record), encoding='utf-8')

    def on_disk(self) -> dict:
        base = self.root.parent
        return {path.relative_to(base).as_posix(): path.read_bytes()
                for path in sorted(base.rglob('*')) if path.is_file()}


class ListTests(DeskCase):
    def test_no_trainings_is_an_empty_list(self):
        self.assertEqual(self.api('trainings'), {'trainings': []})

    def test_each_training_has_its_title_levels_stage_counts_and_readiness(self):
        self.research()
        self.complete()
        self.cli('checkpoint', '--stage', 'package')
        other = self.another('second', '--levels', '101,301')
        listed = self.listed()
        first = listed[str(self.root)]
        self.assertEqual((first['title'], first['levels'], first['stage']),
                         ('Rolling restarts', [], 'package'))
        self.assertEqual(first['counts'], {'approved': 9, 'draft': 0, 'stale': 0,
                                           'not-started': 0, 'skipped': 0, 'unavailable': 0})
        self.assertEqual((first['ready'], first['blocking']), (True, 0))
        second = listed[str(other)]
        self.assertEqual((second['title'], second['levels'], second['stage']),
                         ('Second', ['101', '301'], 'intake'))
        self.assertEqual(second['counts']['not-started'], 11)
        self.assertEqual((second['ready'], second['blocking']),
                         (False, len(training.run_checks(other)['blocking'])))

    def test_counts_follow_what_is_on_disk_now(self):
        self.research()
        self.content()
        self.cli('skip', 'deck', '--reason', 'Not needed')
        self.write('blueprint.md', test_cli.example('blueprint.md') + '\nA late edit.\n')
        counts = self.listed()[str(self.root)]['counts']
        self.assertEqual(counts, {'approved': 3, 'draft': 1, 'stale': 2, 'not-started': 0,
                                  'skipped': 1, 'unavailable': 0})

    def test_the_most_recently_touched_training_comes_first(self):
        self.cli('init', '--title', 'First')
        other = self.another('second')
        self.seen({self.root: '2990-01-01T00:00:00Z', other: '2991-01-01T00:00:00Z'})
        listed = self.api('trainings')['trainings']
        self.assertEqual([item['path'] for item in listed], [str(other), str(self.root)])
        self.assertEqual(listed[0]['touched_at'], '2991-01-01T00:00:00Z')
        # A recorded change counts as a touch, even though the registry was not told.
        with mock.patch.object(workspace, 'now', return_value='2995-01-01T00:00:00Z'):
            self.cli('checkpoint', '--next', 'Draft the blueprint')
        listed = self.api('trainings')['trainings']
        self.assertEqual([item['path'] for item in listed], [str(self.root), str(other)])
        self.assertEqual(listed[0]['touched_at'], '2995-01-01T00:00:00Z')

    def test_an_unreadable_record_is_listed_with_its_error_and_hides_nothing(self):
        self.cli('init', '--title', 'Broken')
        other = self.another('whole')
        (self.root / '.training-studio' / 'session.json').write_text('{not json')
        listed = self.listed()
        broken = listed[str(self.root)]
        self.assertIn('not valid JSON', broken['error'])
        self.assertEqual(broken['title'], 'Broken')
        self.assertFalse({'ready', 'counts', 'stage'} & set(broken))
        self.assertEqual(listed[str(other)]['title'], 'Whole')
        self.assertNotIn('error', listed[str(other)])

    def test_a_record_that_fails_in_an_unexpected_way_is_listed_too(self):
        self.cli('init', '--title', 'Odd')
        other = self.another('whole')
        self.write('intake.md', 'v1\n')
        record = self.root / '.training-studio' / 'session.json'
        session = json.loads(record.read_text(encoding='utf-8'))
        session['artifacts'] = {'intake': {}}
        record.write_text(json.dumps(session), encoding='utf-8')
        listed = self.listed()
        self.assertIn('KeyError', listed[str(self.root)]['error'])
        self.assertIn('counts', listed[str(other)])


class DetailTests(DeskCase):
    def test_a_training_is_shown_exactly_as_the_assistant_sees_it(self):
        self.research('--levels', '101,301')
        self.complete('101')
        shown = self.api('training', path=str(self.root))
        self.assertEqual(shown['status'], self.cli('status'))
        self.assertEqual(shown['check'], self.cli('check'))
        self.assertEqual((shown['path'], shown['title']), (str(self.root), 'Rolling restarts'))
        self.assertIn('blueprint@301 is not-started', shown['check']['blocking'])
        self.assertEqual(shown['check']['limitations'], ['yoodli:main@101 has no export'])
        self.assertEqual(shown['check']['practice']['101']['exercised'], ['O1', 'O2', 'O3'])
        self.assertTrue(shown['check']['warnings'])
        self.assertEqual(shown['status']['research']['run'], 'run-1')
        self.assertIn('guidance', shown['status'])

    def test_a_failed_check_comes_with_its_problems(self):
        self.research()
        self.write('blueprint.md',
                   test_cli.example('blueprint.md').replace('[R:health-checks]', '[R:made-up]'))
        self.cli('save', 'blueprint', '--built')
        shown = self.api('training', path=str(self.root))
        failed = {item['check']: item for item in shown['check']['checks']}
        self.assertEqual(failed['blueprint.citations']['status'], 'failed')
        self.assertTrue(failed['blueprint.citations']['problems'])

    def test_an_unreadable_record_is_answered_with_its_error(self):
        self.cli('init', '--title', 'Broken')
        (self.root / '.training-studio' / 'session.json').write_text('{not json')
        shown = self.api('training', path=str(self.root))
        self.assertIn('not valid JSON', shown['error'])
        self.assertEqual((shown['path'], shown['title']), (str(self.root), 'Broken'))
        self.assertFalse({'status', 'check'} & set(shown))

    def test_reading_changes_nothing_on_disk(self):
        self.research()
        self.complete()
        self.another('second', '--levels', '101')
        before = self.on_disk()
        self.api('trainings')
        self.api('training', path=str(self.root))
        for artifact in ('document', 'deck', 'research-plan'):
            self.api('file', path=str(self.root), artifact=artifact)
        self.assertEqual(self.on_disk(), before)


class FileTests(DeskCase):
    def test_a_markdown_artifact_comes_back_as_its_text(self):
        self.research('--levels', '101')
        self.content('101')
        document = test_cli.example('document.md')
        self.assertEqual(
            self.api('file', path=str(self.root), artifact='document@101'),
            {'artifact': 'document@101', 'file': '101/document.md', 'binary': False,
             'size': len(document.encode()), 'text': document, 'truncated': False})
        brief = self.api('file', path=str(self.root), artifact='brief@101')
        self.assertEqual(brief['file'], '101/product-brief.md')

    def test_the_file_served_is_the_one_the_workspace_names(self):
        self.cli('init', '--title', 'Topic')
        self.write('scenarios/main.md', 'In the folder.\n')
        shown = self.api('file', path=str(self.root), artifact='scenario:main')
        self.assertEqual((shown['file'], shown['text']), ('scenarios/main.md', 'In the folder.\n'))

    def test_the_deck_comes_back_as_a_name_and_a_size_not_its_bytes(self):
        self.research()
        self.complete()
        self.assertEqual(self.api('file', path=str(self.root), artifact='deck'),
                         {'artifact': 'deck', 'file': 'deck.pptx', 'binary': True,
                          'size': len(helpers.DECK.encode())})

    def test_a_text_file_that_is_not_text_is_not_sent(self):
        self.cli('init', '--title', 'Topic')
        content = b'\xff\xfe\x00 not utf-8'
        (self.root / 'intake.md').write_bytes(content)
        shown = self.api('file', path=str(self.root), artifact='intake')
        self.assertEqual((shown['binary'], shown['size']), (True, len(content)))
        self.assertNotIn('text', shown)

    def test_an_artifact_with_no_file_yet_is_not_found(self):
        self.cli('init', '--title', 'Topic')
        missing = self.api('file', expect=404, path=str(self.root), artifact='blueprint')
        self.assertEqual(missing, {'error': 'blueprint.md does not exist yet.'})

    def test_a_long_file_is_cut_short_and_says_so(self):
        self.cli('init', '--title', 'Topic')
        self.write('intake.md', 'abcdefghé and the rest')
        with mock.patch.object(desk, 'PREVIEW_LIMIT', 9):
            shown = self.api('file', path=str(self.root), artifact='intake')
        # The cut fell inside a two-byte character, which is left out rather than garbled.
        self.assertEqual((shown['text'], shown['truncated'], shown['size']),
                         ('abcdefgh', True, 23))

    def test_markup_in_a_file_comes_back_as_data_never_as_a_page(self):
        self.cli('init', '--title', '<script>alert(0)</script>')
        self.write('intake.md', MARKUP)
        query = urlencode({'path': str(self.root), 'artifact': 'intake'})
        for target in (f'/api/file?{query}', '/api/trainings',
                       f'/api/training?{urlencode({"path": str(self.root)})}'):
            status, headers, body = self.fetch(target)
            self.assertEqual(status, 200)
            self.assertEqual(headers.get_content_type(), 'application/json')
            self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
            self.assertNotIn(b'<', body)
        self.assertEqual(self.api('file', path=str(self.root), artifact='intake')['text'], MARKUP)
        self.assertEqual(self.listed()[str(self.root)]['title'], '<script>alert(0)</script>')

    def test_a_record_that_cannot_be_read_has_no_files_to_show(self):
        self.cli('init', '--title', 'Broken')
        self.write('intake.md', 'v1\n')
        (self.root / '.training-studio' / 'session.json').write_text('{not json')
        refused = self.api('file', expect=409, path=str(self.root), artifact='intake')
        self.assertIn('not valid JSON', refused['error'])


class RefusalTests(DeskCase):
    """Everything the desk will not do. Each refusal is JSON and reveals nothing."""

    def setUp(self):
        super().setUp()
        self.cli('init', '--title', 'Topic')
        self.write('intake.md', 'The intake.\n')
        self.targets = ('/api/trainings',
                        '/api/training?' + urlencode({'path': str(self.root)}),
                        '/api/file?' + urlencode({'path': str(self.root),
                                                  'artifact': 'intake'}))

    def unregistered(self) -> Path:
        """A real training that this computer's registry was never told about."""
        root = self.root.parent / 'unregistered'
        root.mkdir()
        workspace.init(root, 'Unregistered')
        (root / 'intake.md').write_text('Private.\n', encoding='utf-8')
        return root

    def assert_refused(self, reply, status: int = 403) -> dict:
        code, headers, body = reply
        self.assertEqual(code, status, body)
        self.assertEqual(headers.get_content_type(), 'application/json')
        self.assertNotIn(b'Private', body)
        self.assertNotIn(b'The intake', body)
        return json.loads(body)

    def test_the_right_token_and_address_are_answered(self):
        for target in self.targets:
            self.assertEqual(self.fetch(target)[0], 200, target)
            self.assertEqual(self.fetch(target, host=f'localhost:{self.desk.port}')[0], 200)
            self.assertEqual(self.fetch(target, host=f'LOCALHOST:{self.desk.port}')[0], 200)

    def test_an_api_call_without_the_token_is_refused(self):
        for target in self.targets:
            with self.subTest(target):
                self.assert_refused(self.fetch(target, token=False))

    def test_an_api_call_with_a_wrong_token_is_refused(self):
        for token in ('wrong', self.desk.token[:-1], self.desk.token + 'x',
                      self.desk.token.swapcase(), 'café'):
            with self.subTest(token):
                self.assert_refused(self.fetch(self.targets[1], token=token))

    def test_the_token_is_taken_from_the_header_only(self):
        query = urlencode({'token': self.desk.token, desk.TOKEN_HEADER: self.desk.token})
        self.assert_refused(self.fetch(f'/api/trainings?{query}', token=False))

    def test_a_wrong_host_header_is_refused(self):
        port = self.desk.port
        hosts = ('example.com', f'example.com:{port}', '127.0.0.1', 'localhost',
                 f'127.0.0.1:{port + 1}', f'127.0.0.1.example.com:{port}',
                 f'localhost.example.com:{port}', f'[::1]:{port}', f'0.0.0.0:{port}')
        for host in hosts:
            for target in ('/', '/app.js', *self.targets):
                with self.subTest(host=host, target=target):
                    self.assert_refused(self.fetch(target, host=host))

    def test_a_path_that_is_not_in_the_registry_is_refused(self):
        nowhere = self.root.parent / 'nowhere'
        elsewhere = self.unregistered()
        for path in (str(nowhere), str(elsewhere), str(self.root.parent), '/', '.', '',
                     str(Path.home())):
            with self.subTest(path):
                query = urlencode({'path': path})
                self.assert_refused(self.fetch(f'/api/training?{query}'),
                                    403 if path else 400)
                query = urlencode({'path': path, 'artifact': 'intake'})
                self.assert_refused(self.fetch(f'/api/file?{query}'), 403 if path else 400)

    def test_path_traversal_in_the_path_is_refused(self):
        elsewhere = self.unregistered()
        for path in (f'{self.root}/../{elsewhere.name}', f'{self.root}/', f'{self.root}/.',
                     f'{self.root}/../{self.root.name}', f'{self.root}\0',
                     str(self.root).upper()):
            with self.subTest(path):
                query = urlencode({'path': path, 'artifact': 'intake'})
                self.assert_refused(self.fetch(f'/api/file?{query}'))
                self.assert_refused(self.fetch('/api/training?' + urlencode({'path': path})))

    def test_an_artifact_that_is_not_one_of_the_trainings_is_refused(self):
        for artifact in ('nonsense', 'intake.md', 'intake@101', 'scenario:missing',
                         'yoodli:main', 'session', '.training-studio/session.json'):
            with self.subTest(artifact):
                refused = self.api('file', expect=403, path=str(self.root), artifact=artifact)
                self.assertIn('is not an artifact of this training', refused['error'])

    def test_path_traversal_in_the_artifact_is_refused(self):
        self.unregistered()
        for artifact in ('../unregistered/intake', 'scenario:../../unregistered/intake',
                         '../../../../etc/passwd', 'scenario:..', '/etc/passwd',
                         'intake/../intake', 'intake\0'):
            with self.subTest(artifact):
                query = urlencode({'path': str(self.root), 'artifact': artifact})
                self.assert_refused(self.fetch(f'/api/file?{query}'))

    @unittest.skipUnless(hasattr(os, 'symlink'), 'needs symbolic links')
    def test_an_artifact_file_that_links_out_of_the_folder_is_refused(self):
        elsewhere = self.unregistered()
        (self.root / 'intake.md').unlink()
        (self.root / 'intake.md').symlink_to(elsewhere / 'intake.md')
        refused = self.assert_refused(self.fetch(self.targets[2]))
        self.assertIn('outside the training folder', refused['error'])

    def test_a_parameter_given_twice_or_not_at_all_is_refused(self):
        twice = urlencode([('path', str(self.root)), ('path', str(self.unregistered()))])
        for target in ('/api/training', '/api/file', f'/api/training?{twice}',
                       f'/api/file?{twice}&artifact=intake',
                       '/api/file?' + urlencode({'path': str(self.root)})):
            with self.subTest(target):
                self.assert_refused(self.fetch(target), 400)

    def test_only_get_is_answered(self):
        before = self.on_disk()
        for method in ('POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD', 'TRACE', 'BREW'):
            for target in ('/', *self.targets):
                with self.subTest(method=method, target=target):
                    status, headers, body = self.fetch(target, method=method)
                    self.assertIn(status, (405, 501))
                    self.assertNotIn(b'The intake', body)
                    if status == 405:
                        self.assertEqual(headers['Allow'], 'GET')
        self.assertEqual(self.on_disk(), before)

    def test_another_site_is_given_no_way_to_read_an_answer(self):
        self.assertEqual(self.fetch(self.targets[0], method='OPTIONS')[0], 405)
        for target in ('/', *self.targets):
            names = [name.lower() for name in self.fetch(target)[1]]
            self.assertFalse([name for name in names if name.startswith('access-control')])

    def test_the_security_headers_are_on_every_response(self):
        replies = {
            'the page': self.fetch('/', token=False),
            'the script': self.fetch('/app.js', token=False),
            'the styles': self.fetch('/style.css', token=False),
            'the icon': self.fetch('/favicon.ico', token=False),
            'the list': self.fetch(self.targets[0]),
            'a training': self.fetch(self.targets[1]),
            'a file': self.fetch(self.targets[2]),
            'no token': self.fetch(self.targets[0], token=False),
            'wrong host': self.fetch('/', host='example.com'),
            'not found': self.fetch('/nothing'),
            'no such endpoint': self.fetch('/api/nothing'),
            'no such file': self.fetch('/api/file?' + urlencode({'path': str(self.root),
                                                                 'artifact': 'blueprint'})),
            'missing parameter': self.fetch('/api/training'),
            'unregistered': self.fetch('/api/training?path=%2Ftmp'),
            'post': self.fetch(self.targets[0], method='POST'),
            'head': self.fetch('/', method='HEAD'),
            'unknown method': self.fetch('/', method='BREW'),
        }
        expected = {'the page': 200, 'the script': 200, 'the styles': 200, 'the icon': 204,
                    'the list': 200, 'a training': 200, 'a file': 200, 'no token': 403,
                    'wrong host': 403, 'not found': 404, 'no such endpoint': 404,
                    'no such file': 404, 'missing parameter': 400, 'unregistered': 403,
                    'post': 405, 'head': 405, 'unknown method': 501}
        for label, (status, headers, _) in replies.items():
            with self.subTest(label):
                self.assertEqual(status, expected[label])
                for name, value in SECURITY_HEADERS.items():
                    self.assertEqual(headers.get_all(name), [value])
                self.assertNotIn('Python', headers.get('Server', ''))

    def test_a_failure_inside_the_desk_is_answered_as_json_with_the_headers(self):
        with mock.patch.object(desk, 'trainings', side_effect=RuntimeError('<b>boom</b>')):
            status, headers, body = self.fetch('/api/trainings')
        self.assertEqual((status, headers.get_content_type()), (500, 'application/json'))
        self.assertEqual(json.loads(body), {'error': 'RuntimeError: <b>boom</b>'})
        self.assertNotIn(b'<', body)
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')


class PageTests(DeskCase):
    def test_the_page_and_its_two_files_are_served_without_a_token(self):
        for target, name, kind in (('/', 'index.html', 'text/html'),
                                   ('/index.html', 'index.html', 'text/html'),
                                   ('/app.js', 'app.js', 'text/javascript'),
                                   ('/style.css', 'style.css', 'text/css')):
            with self.subTest(target):
                status, headers, body = self.fetch(target, token=False)
                self.assertEqual((status, headers.get_content_type()), (200, kind))
                self.assertEqual(headers.get_content_charset(), 'utf-8')
                self.assertEqual(body, (PAGE / name).read_bytes())

    def test_nothing_else_beside_the_page_is_served(self):
        for target in ('/desk.py', '/training.py', '/../desk.py', '/desk/../desk.py',
                       '/%2e%2e/desk.py', '/..%2fdesk.py', '/index.html/../../desk.py',
                       '/desk/index.html', '/app.js/', '/api', '/api/',
                       '/api/trainings/', '/api/../desk.py'):
            with self.subTest(target):
                status, headers, body = self.fetch(target)
                self.assertEqual(status, 404, body)
                self.assertEqual(json.loads(body), {'error': 'Nothing is served here.'})

    def test_the_link_carries_the_token_in_its_fragment_only(self):
        url = urlsplit(self.desk.url)
        self.assertEqual((url.scheme, url.hostname, url.port, url.path, url.query),
                         ('http', '127.0.0.1', self.desk.port, '/', ''))
        self.assertEqual(url.fragment, f'token={self.desk.token}')
        self.assertRegex(self.desk.token, r'^[A-Za-z0-9_-]{32,}$')

    def test_each_desk_makes_its_own_token(self):
        other = desk.Desk()
        self.addCleanup(other.stop)
        self.assertNotEqual(other.token, self.desk.token)
        self.assertNotEqual(other.port, self.desk.port)

    def test_it_listens_on_this_computer_only(self):
        self.assertEqual(self.desk.server.server_address[0], '127.0.0.1')

    def test_a_stopped_desk_no_longer_answers(self):
        self.desk.stop()
        with self.assertRaises(urllib.error.URLError):
            self.fetch('/')


class PageFileTests(unittest.TestCase):
    """What can be said about the page without a browser."""

    def read(self, name: str) -> str:
        return (PAGE / name).read_text(encoding='utf-8')

    def test_the_page_loads_nothing_from_anywhere_else(self):
        for name in PAGE_FILES:
            with self.subTest(name):
                self.assertNotRegex(self.read(name), r'(?i)\b(?:https?|wss?|ftp|data|blob):')
        page = self.read('index.html')
        self.assertEqual(sorted(re.findall(r'(?:src|href)="([^"]*)"', page)),
                         ['#main', 'app.js', 'style.css'])
        styles = self.read('style.css')
        self.assertNotIn('url(', styles)
        self.assertNotIn('@import', styles)
        self.assertNotIn('@font-face', styles)
        script = self.read('app.js')
        self.assertEqual(set(re.findall(r"fetch\(\s*([^,)]+)", script)), {"'/api/' + endpoint"})
        for elsewhere in ('XMLHttpRequest', 'WebSocket', 'EventSource', 'sendBeacon', 'import('):
            self.assertNotIn(elsewhere, script)

    def test_the_page_has_nothing_its_own_policy_would_block(self):
        page = self.read('index.html')
        self.assertNotRegex(page, r'<style\b')
        self.assertNotRegex(page, r'\sstyle\s*=')
        self.assertNotRegex(page, r'\son[a-z]+\s*=')
        self.assertEqual(re.findall(r'<script\b[^>]*>(.*?)</script>', page, re.DOTALL), [''])

    def test_the_script_never_treats_a_value_as_markup(self):
        script = self.read('app.js')
        for risky in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write',
                      'createContextualFragment', 'DOMParser', 'srcdoc', 'eval(',
                      'Function(', "setAttribute('style'", "setAttribute('href'",
                      "setAttribute('src'"):
            with self.subTest(risky):
                self.assertNotIn(risky, script)
        self.assertIn('textContent', script)

    def test_the_page_names_every_status_and_draws_each_a_shape(self):
        page, styles = self.read('index.html'), self.read('style.css')
        for status in desk.STATUSES:
            with self.subTest(status):
                self.assertIn(f'data-status="{status}"', page)
                self.assertIn(f'[data-status="{status}"]', styles)
                self.assertRegex(page, rf'>\s*{status}\b')

    def test_both_colour_schemes_and_a_narrow_layout_are_styled(self):
        styles = self.read('style.css')
        self.assertIn('prefers-color-scheme: dark', styles)
        self.assertRegex(styles, r'@media[^{]*\b(?:min|max)-width')
        self.assertIn('width=device-width', self.read('index.html'))


class CommandTests(DeskCase):
    """`training.py desk`, run as the assistant runs it."""

    def launch(self, *args) -> subprocess.Popen:
        process = subprocess.Popen(
            [sys.executable, str(test_cli.CLI), 'desk', *args], cwd=self.root,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        guard = threading.Timer(30, process.kill)
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

    def usable_signals(self) -> list:
        """SIGINT is ignored in a process started in the background by some shells."""
        ignored = signal.getsignal(signal.SIGINT) == signal.SIG_IGN
        return [signal.SIGTERM] if ignored else [signal.SIGINT, signal.SIGTERM]

    @unittest.skipIf(os.name == 'nt', 'signals are delivered differently on Windows')
    def test_it_prints_one_line_with_the_link_then_serves_until_stopped(self):
        self.cli('init', '--title', 'Topic')
        for how in self.usable_signals():
            with self.subTest(signal.Signals(how).name):
                process = self.launch()
                line = process.stdout.readline()
                url = json.loads(line)['url']
                self.assertRegex(url, r'^http://127\.0\.0\.1:\d+/#token=[A-Za-z0-9_-]{32,}$')
                address, _, fragment = url.partition('#')
                token = fragment.removeprefix('token=')
                self.assertEqual(ask(address)[0], 200)
                status, _, body = ask(f'{address}api/trainings', {desk.TOKEN_HEADER: token})
                self.assertEqual(status, 200)
                self.assertEqual([item['path'] for item in json.loads(body)['trainings']],
                                 [str(self.root)])
                self.assertEqual(ask(f'{address}api/trainings')[0], 403)
                self.assertIsNone(process.poll())
                process.send_signal(how)
                rest, errors = process.communicate(timeout=20)
                self.assertEqual((process.returncode, rest, errors), (0, '', ''))

    def test_a_port_can_be_asked_for_and_one_in_use_is_a_json_refusal(self):
        taken = subprocess.run(
            [sys.executable, str(test_cli.CLI), 'desk', '--port', str(self.desk.port)],
            cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertEqual(taken.returncode, 2, taken.stdout + taken.stderr)
        self.assertIn('OSError', json.loads(taken.stdout)['error'])

    def test_a_port_that_is_not_a_number_is_a_usage_error(self):
        for port in ('http', '70000', '-1'):
            with self.subTest(port):
                wrong = subprocess.run(
                    [sys.executable, str(test_cli.CLI), 'desk', '--port', port],
                    cwd=self.root, capture_output=True, text=True, timeout=30)
                self.assertEqual(wrong.returncode, 2, wrong.stderr)
                self.assertIn('--port', json.loads(wrong.stdout)['error'])

    def test_the_desk_can_be_given_a_port(self):
        self.desk.stop()
        again = desk.Desk(self.desk.port)
        self.addCleanup(again.stop)
        self.assertEqual(again.port, self.desk.port)
        self.assertIn(f':{self.desk.port}/#token=', again.url)


class PackageTests(unittest.TestCase):
    def test_the_guidance_fits_in_500_estimated_tokens(self):
        guidance = (helpers.SKILL / 'references' / 'desk.md').read_text(encoding='utf-8')
        self.assertLessEqual(validate_package.estimate(guidance), 500)

    def test_the_desk_is_part_of_the_package(self):
        for name in ('references/desk.md', 'scripts/desk.py', 'scripts/cmd_desk.py',
                     *(f'scripts/desk/{name}' for name in PAGE_FILES)):
            self.assertIn(name, validate_package.REQUIRED)
        files, budget = validate_package.loading_sets()['desk']
        self.assertEqual((files, budget), (['SKILL.md', 'references/desk.md'], 2000))

    def test_the_guidance_names_no_assistant_and_none_of_its_tools(self):
        guidance = (helpers.SKILL / 'references' / 'desk.md').read_text(encoding='utf-8')
        for word in ('Claude', 'Codex', 'Bash', 'run_in_background', 'BashOutput', 'KillShell'):
            self.assertNotIn(word, guidance)
        for needed in ('training.py desk', 'background', 'read-only', '`url`', 'stop'):
            self.assertIn(needed, guidance.lower())


if __name__ == '__main__':
    unittest.main()
