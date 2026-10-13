"""The page: what it reads, what it changes, everything it refuses, and the command.

Classes built on DeskCase talk to a real server on a local port and are skipped where a port
cannot be opened. Classes built on PageCase ask the same questions without a socket, so the
rules for decisions are tested everywhere.
"""
import base64
import contextlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode, urlsplit

import helpers
import test_cli
import cmd_desk
import computer
import desk
import training
import validate_package
import workspace

PAGE = helpers.SCRIPTS / 'desk'
PAGE_FILES = ('index.html', 'app.js', 'markdown.js', 'style.css')
HARNESS = Path(__file__).resolve().parent / 'page_harness.js'
NODE = shutil.which('node')
SECURITY_HEADERS = {'Content-Security-Policy': "default-src 'self'",
                    'X-Content-Type-Options': 'nosniff',
                    'X-Frame-Options': 'DENY',
                    'Referrer-Policy': 'no-referrer',
                    'Cache-Control': 'no-store'}
FORBIDDEN_WORDS = re.compile(r'\b(artifacts?|stale|lineage)\b', re.IGNORECASE)
# Straight to the socket: a proxy named in the environment must not sit in between.
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
MARKUP = '<script>alert(1)</script>\n<img src=x onerror=alert(2)>\n'


def ask(url: str, headers: dict | None = None, method: str = 'GET', body: bytes | None = None):
    """One request. Returns the status, the headers and the body, refused or not."""
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with DIRECT.open(request, timeout=10) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as refused:
        with refused:
            return refused.code, refused.headers, refused.read()


def never(*args, **kwargs):
    raise AssertionError('A test must never look at the real computer.')


class Registry(test_cli.Flow):
    """A registry of its own, and a readiness check that can never reach the real computer."""

    def setUp(self):
        super().setUp()
        data = self.root.parent / 'data'
        for patcher in (mock.patch.dict(os.environ, {'TRAINING_STUDIO_DATA': str(data)}),
                        mock.patch.object(computer, 'run', never),
                        mock.patch.object(computer, 'reach', never)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def another(self, name: str, *init_args) -> Path:
        """A second training in its own folder, registered like the first."""
        root = self.root.parent / name
        root.mkdir()
        with contextlib.redirect_stdout(io.StringIO()):
            code = training.main(['--dir', str(root), 'init', '--title', name.title(),
                                  *init_args])
        self.assertEqual(code, 0)
        return root

    def on_disk(self) -> dict:
        base = self.root.parent
        return {path.relative_to(base).as_posix(): path.read_bytes()
                for path in sorted(base.rglob('*')) if path.is_file()}

    def at_the_blueprint_gate(self, approval: str = 'page') -> None:
        """Research approved, a blueprint built and waiting at its gate."""
        self.research()
        self.write('blueprint.md', test_cli.example('blueprint.md'))
        self.cli('save', 'blueprint', '--built')
        self.cli('checkpoint', '--approval', approval, '--gate', 'blueprint', '--stage',
                 'blueprint', '--question', 'Approve the blueprint?',
                 '--next', 'Waiting for approval of blueprint')

    def sha(self, relative: str) -> str:
        return workspace.sha256_file(self.root / relative)


class DeskCase(Registry):
    """A page serving on a port the system chose."""

    def setUp(self):
        super().setUp()
        try:
            self.desk = desk.Desk()
        except PermissionError as refused:
            self.skipTest(f'This environment does not allow listening on a local port: {refused}')
        self.addCleanup(self.desk.stop)
        self.desk.start()

    def fetch(self, target: str, token=True, host: str | None = None, method: str = 'GET',
              body: bytes | None = None, headers: dict | None = None):
        """Ask the page. `token` is True for the right one, False for none, or one to send."""
        headers = dict(headers or {})
        if token:
            headers[desk.TOKEN_HEADER] = self.desk.token if token is True else token
        if host:
            headers['Host'] = host
        return ask(f'http://127.0.0.1:{self.desk.port}{target}', headers, method, body)

    def send(self, endpoint: str, sent, expect: int = 200, **headers) -> dict:
        """POST JSON as the page does: with the key, its own origin and a JSON body."""
        wanted = {'Origin': f'http://127.0.0.1:{self.desk.port}',
                  'Content-Type': 'application/json', **headers}
        wanted = {name: value for name, value in wanted.items() if value is not None}
        body = sent if isinstance(sent, bytes) else json.dumps(sent).encode()
        status, replied, data = self.fetch(f'/api/{endpoint}', method='POST', body=body,
                                           headers=wanted)
        self.assertEqual(status, expect, data)
        self.assertEqual(replied.get_content_type(), 'application/json')
        return json.loads(data)

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



class ListTests(DeskCase):
    def test_no_trainings_is_an_empty_list(self):
        self.assertEqual(self.api('trainings'), {'trainings': [], 'needs': 0})

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

    def test_the_google_docs_a_training_keeps_are_shown_with_their_state(self):
        self.research(yoodli=False, copies=('google',))
        for name, file in (('blueprint', 'blueprint.md'), ('document', 'document.md'),
                           ('brief', 'product-brief.md')):
            self.make(name, file, test_cli.example(file))
        shown = self.api('training', path=str(self.root))
        self.assertEqual(shown['status']['google_docs'],
                         {'brief': 'missing', 'document': 'missing'})
        self.assertEqual(shown['status']['exports'], {})
        self.assertIn('document is not in a Google Doc', shown['check']['limitations'])

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

    def test_what_is_read_answers_get_only(self):
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
    def test_the_page_and_its_files_are_served_without_a_token(self):
        for target, name, kind in (('/', 'index.html', 'text/html'),
                                   ('/index.html', 'index.html', 'text/html'),
                                   ('/app.js', 'app.js', 'text/javascript'),
                                   ('/markdown.js', 'markdown.js', 'text/javascript'),
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


class PageCase(Registry):
    """The page's answers with no socket, so these run where a port cannot be opened."""

    PORT = 8765

    def setUp(self):
        super().setUp()
        self.page = desk.Page(self.PORT)
        self.origin = f'http://127.0.0.1:{self.PORT}'

    def headers(self, token=True, host=None, origin=None, kind=None) -> Message:
        made = Message()
        made['Host'] = host or f'127.0.0.1:{self.PORT}'
        if token:
            made[desk.TOKEN_HEADER] = self.page.token if token is True else token
        for name, values in (('Origin', origin), ('Content-Type', kind)):
            for value in [values] if isinstance(values, str) else values or []:
                made[name] = value
        return made

    def answer(self, method: str, target: str, body: bytes | None = None, **options):
        """One request, answered as the server would: the status, the JSON, and `Allow`."""
        try:
            status, _, data = self.page.answer(target, self.headers(**options), method, body)
        except desk.Refusal as refusal:
            return int(refusal.status), {'error': str(refusal)}, refusal.allow
        except workspace.WorkspaceError as refusal:
            return 409, {'error': str(refusal)}, None
        self.assertNotIn(b'<', data)
        return int(status), json.loads(data) if data else None, None

    def get(self, endpoint: str, expect: int = 200, **params) -> dict:
        target = f'/api/{endpoint}' + (f'?{urlencode(params)}' if params else '')
        status, reply, _ = self.answer('GET', target)
        self.assertEqual(status, expect, reply)
        return reply

    def post(self, endpoint: str, sent, expect: int = 200, **options) -> dict:
        """POST as the page does, unless `options` say otherwise."""
        options.setdefault('origin', self.origin)
        options.setdefault('kind', 'application/json')
        body = sent if isinstance(sent, (bytes, type(None))) else json.dumps(sent).encode()
        status, reply, _ = self.answer('POST', f'/api/{endpoint}', body, **options)
        self.assertEqual(status, expect, reply)
        return reply

    def decide(self, decision: str, artifact: str = 'blueprint', expect: int = 200,
               **more) -> dict:
        return self.post('decide', {'path': str(self.root), 'artifact': artifact,
                                    'decision': decision, **more}, expect)

    def gate(self, artifact: str = 'blueprint', root: Path | None = None) -> dict:
        return self.get('gate', path=str(root or self.root), artifact=artifact)

    def listed(self) -> dict:
        return {item['path']: item for item in self.get('trainings')['trainings']}


class WriteRuleTests(PageCase):
    """What a change must carry before the page will make it (specification, section 4)."""

    def setUp(self):
        super().setUp()
        self.at_the_blueprint_gate()
        self.approve = {'path': str(self.root), 'artifact': 'blueprint', 'decision': 'approve',
                        'seen': self.sha('blueprint.md')}
        self.before = self.on_disk()

    def refused(self, expect: int, sent=None, **options) -> dict:
        reply = self.post('decide', self.approve if sent is None else sent, expect, **options)
        self.assertEqual(self.on_disk(), self.before)
        return reply

    def test_the_page_itself_is_answered(self):
        outcome = self.post('decide', self.approve)
        self.assertEqual(outcome['decided']['by'], 'page')
        self.assertEqual(self.cli('status')['artifacts']['blueprint'], 'approved')

    def test_the_page_is_answered_at_localhost_too(self):
        host = f'localhost:{self.PORT}'
        self.post('decide', self.approve, host=host, origin=f'http://{host}')
        self.assertEqual(self.cli('status')['artifacts']['blueprint'], 'approved')

    def test_a_change_needs_the_key(self):
        for token in (False, 'wrong', self.page.token[:-1], self.page.token + 'x'):
            with self.subTest(token):
                self.assertIn('needs the key', self.refused(403, token=token)['error'])

    def test_a_change_needs_the_pages_own_origin(self):
        other_port = f'http://127.0.0.1:{self.PORT + 1}'
        for origin in (None, 'null', 'http://example.com', other_port,
                       f'https://127.0.0.1:{self.PORT}', f'http://localhost:{self.PORT}',
                       f'{self.origin}.example.com', f'{self.origin}/', 'http://127.0.0.1',
                       [self.origin, 'http://example.com'], [self.origin, self.origin]):
            with self.subTest(origin):
                refusal = self.refused(403, origin=origin)
                self.assertEqual(refusal, {'error': 'A change is accepted only from the '
                                                    'page itself.'})

    def test_a_change_is_refused_at_any_other_address(self):
        for host in ('example.com', f'example.com:{self.PORT}', '127.0.0.1',
                     f'127.0.0.1.example.com:{self.PORT}', f'[::1]:{self.PORT}'):
            with self.subTest(host):
                refusal = self.refused(403, host=host, origin=f'http://{host}')
                self.assertIn('only at its own local address', refusal['error'])

    def test_a_change_is_json_in_the_body(self):
        for kind in (None, 'text/plain', 'application/x-www-form-urlencoded',
                     'multipart/form-data'):
            with self.subTest(kind):
                self.assertEqual(self.refused(415, kind=kind),
                                 {'error': 'Send the change as JSON.'})
        for body in (b'', b'{not json', b'[]', b'"approve"', b'null', b'\xff\xfe',
                     urlencode(self.approve).encode()):
            with self.subTest(body):
                self.assertIn('one JSON object', self.refused(400, body)['error'])

    def test_every_field_is_text(self):
        for field, value in (('path', None), ('path', 7), ('path', ''), ('artifact', None),
                             ('artifact', ['blueprint']), ('decision', True),
                             ('decision', ''), ('note', 3), ('note', {'a': 1}),
                             ('seen', 12), ('note', 'x' * (desk.NOTE_LIMIT + 1))):
            with self.subTest(field=field, value=str(value)[:20]):
                sent = {**self.approve, field: value}
                if value is None:
                    del sent[field]
                self.assertEqual(self.refused(400, sent), {'error': f'Give {field} as text.'})

    def test_a_body_that_is_too_long_or_has_no_length_is_never_read(self):
        refusal = self.post('decide', None, 413)
        self.assertIn('64,000 bytes', refusal['error'])
        self.assertEqual(self.on_disk(), self.before)

    def test_what_changes_is_never_named_in_the_address(self):
        query = urlencode(self.approve)
        status, reply, _ = self.answer('POST', f'/api/decide?{query}', b'{}',
                                       origin=self.origin, kind='application/json')
        self.assertEqual((status, reply), (400, {'error': 'Send what is to change in the '
                                                          'body.'}))
        self.assertEqual(self.on_disk(), self.before)

    def test_a_change_is_never_made_with_get_and_a_read_never_with_post(self):
        query = urlencode(self.approve)
        for target in ('/api/decide', f'/api/decide?{query}', '/api/approval'):
            with self.subTest(target):
                status, _, allow = self.answer('GET', target)
                self.assertEqual((status, allow), (405, 'POST'))
        for target in ('/', '/app.js', '/api/trainings', '/api/gate', '/api/file',
                       '/api/training', '/api/nothing', '/api/decide/'):
            with self.subTest(target):
                status, _, allow = self.answer('POST', target, json.dumps(self.approve).encode(),
                                               origin=self.origin, kind='application/json')
                self.assertEqual((status, allow), (405, 'GET'))
        self.assertEqual(self.on_disk(), self.before)

    def test_only_a_registered_training_is_changed(self):
        elsewhere = self.root.parent / 'unregistered'
        elsewhere.mkdir()
        workspace.init(elsewhere, 'Unregistered')
        self.before = self.on_disk()
        for path in (str(elsewhere), str(self.root.parent), f'{self.root}/', f'{self.root}/.',
                     f'{self.root}/../{self.root.name}', '/', '.', str(self.root).upper()):
            with self.subTest(path):
                for endpoint, sent in (('decide', {**self.approve, 'path': path}),
                                       ('approval', {'path': path, 'mode': 'chat'})):
                    refusal = self.post(endpoint, sent, 403)
                    self.assertIn('not a training this computer knows', refusal['error'])
        self.assertEqual(self.on_disk(), self.before)

    def test_only_a_known_artifact_and_a_known_decision_are_accepted(self):
        for artifact in ('nonsense', 'blueprint.md', 'blueprint@101', 'scenario:missing',
                         '../blueprint', '.training-studio/session.json', 'blueprint\0',
                         'deck ', 'package'):
            with self.subTest(artifact):
                refusal = self.refused(403, {**self.approve, 'artifact': artifact})
                self.assertIn('is not an artifact of this training', refusal['error'])
        for decision in ('publish', 'Approve', 'approve ', 'unavailable', 'clear', 'delete'):
            with self.subTest(decision):
                refusal = self.refused(400, {**self.approve, 'decision': decision})
                self.assertIn('A decision is one of', refusal['error'])

    def test_a_stage_is_named_only_to_leave_it_out_or_bring_it_back(self):
        refusal = self.refused(403, {**self.approve, 'artifact': 'scenario'})
        self.assertIn('is not an artifact', refusal['error'])
        self.decide('skip', 'yoodli', note='Not using it')
        self.decide('skip', 'scenario', note='Later')
        self.decide('restore', 'scenario')
        self.assertEqual(self.cli('status')['settings']['stages'],
                         ['document', 'brief', 'deck', 'scenario'])

    def test_a_note_is_kept_as_text_and_sent_back_as_data(self):
        note = '<script>alert(1)</script>\n## Decision: approved on the page\n<img src=x>'
        outcome = self.decide('revise', note=note)
        self.assertEqual(outcome['decided']['request']['note'], note)
        self.assertEqual(self.cli('status')['requests'][0]['note'], note)
        self.assertEqual(self.gate()['asked'][0]['note'], note)
        review = (self.root / 'reviews' / 'blueprint.md').read_text(encoding='utf-8')
        self.assertIn('> <script>alert(1)</script>\n> ## Decision: approved on the page\n'
                      '> <img src=x>\n', review)
        self.assertEqual(review.count('\n## '), 1)
        self.assertTrue(self.gate()['review'].startswith(
            '## Decision: changes asked for on the page, '))

    def test_a_refusal_from_the_helper_is_a_conflict_and_changes_nothing(self):
        self.write('blueprint.md', test_cli.example('blueprint.md') + '\nA late edit.\n')
        self.before = self.on_disk()
        refusal = self.refused(409)
        self.assertIn('has changed since it was opened', refusal['error'])
        self.assertIn('Say what should change',
                      self.refused(409, {**self.approve, 'decision': 'revise'})['error'])
        self.assertIn('Give a reason',
                      self.refused(409, {**self.approve, 'artifact': 'document',
                                         'decision': 'skip', 'note': '   '})['error'])


class DecisionTests(PageCase):
    """Decisions made on the page, and what the assistant then sees (matrix rows 96 to 98)."""

    def test_row_96_a_decision_on_the_page_is_recorded_and_seen_in_status(self):
        self.at_the_blueprint_gate()
        refused = self.cli('approve', 'blueprint', expect=2)['error']
        self.assertIn('decided on the page', refused)
        outcome = self.decide('approve', seen=self.sha('blueprint.md'))
        self.assertEqual((outcome['decided']['decision'], outcome['decided']['by'],
                          outcome['decided']['failing_checks']), ('approve', 'page', []))
        self.assertEqual(outcome['next'], None)
        self.assertTrue(outcome['said'].startswith('Approved. '))
        self.assertIn('You can close this page.', outcome['said'])
        report = self.cli('status')
        self.assertEqual((report['artifacts']['blueprint'], report['gate'],
                          report['pending_question'], report['next_step']),
                         ('approved', None, None, 'The blueprint was approved on the page.'))
        record = json.loads((self.root / '.training-studio' / 'session.json').read_text())
        self.assertEqual(record['artifacts']['blueprint']['approved']['by'], 'page')
        self.assertEqual((record['events'][-1]['event'], record['events'][-1]['by']),
                         ('approve', 'page'))
        review = (self.root / 'reviews' / 'blueprint.md').read_text(encoding='utf-8')
        self.assertIn('## Decision: approved on the page, ', review)

    def test_an_approval_names_the_version_that_was_read(self):
        self.at_the_blueprint_gate()
        self.assertIn('which version was read', self.decide('approve', expect=400)['error'])
        self.assertIn('which version was read',
                      self.decide('approve', expect=400, seen='')['error'])
        read = self.gate()['sha256']
        self.write('blueprint.md', test_cli.example('blueprint.md') + '\nRewritten.\n')
        self.assertIn('has changed since it was opened',
                      self.decide('approve', expect=409, seen=read)['error'])
        self.assertEqual(self.cli('status')['artifacts']['blueprint'], 'draft')
        self.decide('approve', seen=self.gate()['sha256'])
        self.assertEqual(self.cli('status')['artifacts']['blueprint'], 'approved')

    def test_row_97_the_page_decides_only_once_approval_has_moved_to_it(self):
        self.at_the_blueprint_gate(approval='chat')
        before = self.on_disk()
        for decision, more in (('approve', {'seen': self.sha('blueprint.md')}),
                               ('revise', {'note': 'Shorter'}), ('rebuild', {}),
                               ('skip', {'note': 'No', 'artifact': 'document'})):
            with self.subTest(decision):
                refusal = self.decide(decision, expect=409, **more)
                self.assertIn('made in the conversation', refusal['error'])
        self.assertEqual(self.on_disk(), before)
        self.assertEqual(self.gate()['approval'], 'chat')
        self.assertEqual(self.post('approval', {'path': str(self.root), 'mode': 'page'}),
                         {'approval': 'page'})
        self.assertEqual(self.gate()['approval'], 'page')
        self.decide('approve', seen=self.sha('blueprint.md'))
        self.assertEqual(self.cli('status')['artifacts']['blueprint'], 'approved')

    def test_only_the_page_moves_approval_back_to_the_conversation(self):
        self.at_the_blueprint_gate()
        self.assertIn('only the page can move it back',
                      self.cli('checkpoint', '--approval', 'chat', expect=2)['error'])
        self.assertEqual(self.post('approval', {'path': str(self.root), 'mode': 'chat'}),
                         {'approval': 'chat'})
        self.assertEqual(self.cli('status')['approval'], 'chat')
        self.cli('approve', 'blueprint')
        for mode in ('email', '', 'Page'):
            self.post('approval', {'path': str(self.root), 'mode': mode}, 400)
        self.post('approval', {'path': str(self.root)}, 400)

    def test_a_request_opens_on_the_page_and_closes_when_the_work_is_done(self):
        self.at_the_blueprint_gate()
        outcome = self.decide('revise', note='Add a second example')
        self.assertTrue(outcome['said'].startswith('Your changes are noted.'))
        shown = self.listed()[str(self.root)]
        self.assertEqual((shown['state'], shown['requests'], shown['waiting']),
                         ('in-progress', 1, None))
        self.assertEqual(shown['sentence'], 'You asked for changes to the blueprint. Your '
                         'assistant does that when you go back to the conversation.')
        gate = self.gate()
        self.assertEqual([(item['kind'], item['note']) for item in gate['asked']],
                         [('revise', 'Add a second example')])
        self.assertEqual((gate['waiting'], gate['question']), (False, None))
        detail = self.get('training', path=str(self.root))
        self.assertIn('You asked for changes to the blueprint, and that is still to do',
                      detail['view']['blocking'])
        self.assertTrue(detail['view']['files'][3]['asked'])
        revised = self.root.parent / 'revised.md'
        revised.write_text(test_cli.example('blueprint.md') + '\nA second example.\n')
        self.cli('save', 'blueprint', '--from', str(revised))
        self.assertEqual(self.gate()['asked'], [])
        self.assertEqual(self.cli('status')['requests'], [])
        self.decide('rebuild')
        self.assertEqual(self.listed()[str(self.root)]['sentence'],
                         'You asked for a rebuild of the blueprint. Your assistant does '
                         'that when you go back to the conversation.')
        self.decide('approve', seen=self.sha('blueprint.md'))
        self.assertEqual(self.cli('status')['requests'], [])

    def test_a_stage_is_left_out_and_brought_back_on_the_page(self):
        self.at_the_blueprint_gate()
        self.assertIn('Turn Yoodli off', self.decide('skip', 'brief', expect=409,
                                                     note='Deck only')['error'])
        outcome = self.decide('skip', 'deck', note='Not needed')
        self.assertEqual(outcome['decided']['stage'], 'deck')
        gate = self.gate('deck')
        self.assertEqual((gate['status'], gate['words'], gate['decisions']),
                         ('skipped', 'left out', ['restore']))
        detail = self.get('training', path=str(self.root))
        self.assertEqual(detail['view']['left_out'],
                         [{'stage': 'deck', 'name': 'The deck stage', 'optional': False}])
        self.assertIn('The deck stage was left out', detail['view']['limitations'])
        self.assertIn('decided on the page',
                      self.cli('skip', 'deck', '--clear', expect=2)['error'])
        self.decide('restore', 'deck')
        self.assertEqual(self.gate('deck')['status'], 'not-started')
        self.assertEqual(self.get('training', path=str(self.root))['view']['left_out'], [])

    def test_the_reply_names_the_next_thing_that_needs_the_user(self):
        self.at_the_blueprint_gate()
        other = self.another('second')
        (other / 'intake.md').write_text('# Intake\n', encoding='utf-8')
        workspace.checkpoint(other, question='Which audience?', gate='intake')
        outcome = self.decide('approve', seen=self.sha('blueprint.md'))
        self.assertEqual(outcome['next'], {
            'path': str(other), 'title': 'Second', 'artifact': 'intake',
            'sentence': 'The intake summary is waiting for your review.'})


class GateTests(PageCase):
    """What a gate shows: the document, what changed, what was checked, what is worth a look."""

    def test_row_98_without_a_recorded_gate_the_first_unapproved_file_is_at_the_gate(self):
        self.research()
        self.content()
        self.assertEqual(self.listed()[str(self.root)]['waiting'], None)
        self.write('blueprint.md', test_cli.example('blueprint.md') + '\nA late edit.\n')
        self.write('product-brief.md', test_cli.example('product-brief.md') + '\nAn edit.\n')
        state = self.cli('status')['artifacts']
        self.assertEqual((state['blueprint'], state['document'], state['brief']),
                         ('draft', 'stale', 'stale'))
        self.assertEqual(self.listed()[str(self.root)]['state'], 'in-progress')
        self.cli('checkpoint', '--question', 'Approve the brief?')
        shown = self.listed()[str(self.root)]
        self.assertEqual(shown['waiting'], {'artifact': 'blueprint', 'label': 'the blueprint',
                                            'question': 'Approve the brief?',
                                            'recorded': False})
        self.assertEqual((shown['state'], shown['sentence']),
                         ('needs-you', 'The blueprint is waiting for your review.'))
        self.assertTrue(self.gate('blueprint')['waiting'])
        self.cli('checkpoint', '--gate', 'brief')
        shown = self.listed()[str(self.root)]
        self.assertEqual((shown['waiting']['artifact'], shown['waiting']['recorded']),
                         ('brief', True))
        self.assertEqual(shown['sentence'],
                         'The brief is out of date and waiting for your decision.')
        self.assertEqual(self.get('trainings')['needs'], 1)
        self.assertEqual((self.gate('brief')['waiting'], self.gate('blueprint')['waiting']),
                         (True, False))

    def test_a_question_with_nothing_to_review_still_needs_the_user(self):
        self.cli('init', '--title', 'Rolling restarts')
        self.cli('checkpoint', '--question', 'Who is this for?')
        shown = self.listed()[str(self.root)]
        self.assertEqual(shown['waiting'], {'artifact': None, 'label': None,
                                            'question': 'Who is this for?', 'recorded': False})
        self.assertEqual(shown['sentence'], 'A question is waiting for you: Who is this for?')
        self.assertEqual(desk.next_up()['artifact'], None)

    def test_a_gate_shows_the_document_what_was_checked_and_the_latest_review(self):
        self.at_the_blueprint_gate()
        self.write('reviews/blueprint.md', '# Reviews of blueprint\n\n## Review 1\n\nFirst.\n\n'
                   '## Review 2\n\nThe sizing is my judgment.\n')
        gate = self.gate()
        self.assertEqual((gate['title'], gate['label'], gate['artifact'], gate['stage_name']),
                         ('Rolling restarts', 'The blueprint', 'blueprint', 'Blueprint'))
        self.assertEqual((gate['status'], gate['words'], gate['waiting'], gate['question']),
                         ('draft', 'not approved yet', True, 'Approve the blueprint?'))
        self.assertEqual(gate['document'], {
            'kind': 'markdown', 'file': 'blueprint.md', 'truncated': False,
            'size': len(test_cli.example('blueprint.md').encode()),
            'text': test_cli.example('blueprint.md')})
        self.assertEqual(gate['sha256'], self.sha('blueprint.md'))
        self.assertEqual(gate['checked'], {'passed': 4, 'problems': []})
        self.assertEqual(gate['review'], '## Review 2\n\nThe sizing is my judgment.')
        self.assertEqual((gate['decisions'], gate['first'], gate['out_of_date']),
                         (['approve', 'revise', 'rebuild'], [], []))
        self.assertEqual(gate['changes'], {'available': False})
        self.assertEqual([stage['state'] for stage in gate['stages']],
                         ['done', 'done', 'done', 'review'] + ['not-started'] * 6)

    def test_a_failed_check_is_named_with_its_reasons(self):
        self.research()
        self.write('blueprint.md',
                   test_cli.example('blueprint.md').replace('[R:health-checks]', '[R:made-up]'))
        self.cli('save', 'blueprint', '--built')
        checked = self.gate()['checked']
        self.assertEqual(checked['passed'], 3)
        self.assertEqual([(item['check'], item['words']) for item in checked['problems']],
                         [('blueprint.citations', 'failed')])
        self.assertTrue(checked['problems'][0]['problems'])
        self.assertEqual(self.gate('research')['checked'], {'passed': 0, 'problems': []})

    def test_checks_are_counted_for_the_level_they_belong_to(self):
        self.research('--levels', '101,301')
        self.content('101')
        self.assertEqual(self.gate('blueprint@101')['checked']['passed'], 4)
        self.assertEqual(self.gate('document@101')['checked']['passed'], 1)
        self.assertEqual(self.gate('blueprint@301')['checked'], {'passed': 0, 'problems': []})
        self.assertEqual(self.gate('blueprint@301')['document'],
                         {'kind': 'missing', 'file': '301/blueprint.md'})
        self.assertEqual(self.gate('blueprint@301')['label'], 'The level 301 blueprint')

    def test_the_research_plan_is_shown_as_its_questions(self):
        self.research()
        shown = self.gate('research-plan')['document']
        self.assertEqual((shown['kind'], shown['topic'], shown['scope']),
                         ('questions', 'Rolling restarts', 'public-web'))
        self.assertEqual(shown['questions'][0], {
            'id': 'availability', 'question': 'When does a rolling restart keep capacity?'})
        self.assertEqual(len(shown['questions']), 8)
        self.assertNotIn('text', shown)
        self.write('.training-studio/research-plan.json', '{not json')
        self.assertEqual(self.gate('research-plan')['document']['kind'], 'markdown')

    def test_a_deck_is_shown_as_its_name_and_size_and_a_link_as_its_text(self):
        self.research()
        self.complete()
        self.assertEqual(self.gate('deck')['document'],
                         {'kind': 'file', 'file': 'deck.pptx', 'size': len(helpers.DECK)})
        self.cli('checkpoint', '--deck-target', 'google')
        link = '# Deck\n\n[Rolling restarts](https://example.com/slides/1)\n'
        self.write('deck-link.md', link)
        self.assertEqual(self.gate('deck')['document'],
                         {'kind': 'link', 'file': 'deck-link.md', 'size': len(link),
                          'text': link, 'truncated': False})

    def test_what_changed_is_a_comparison_with_the_version_last_approved(self):
        self.research()
        self.content()
        self.assertEqual(self.gate('document')['changes']['same'], True)
        self.assertEqual(self.gate('document')['changes']['rows'], [])
        revised = self.root.parent / 'revised.md'
        revised.write_text(test_cli.example('document.md').replace('**Time:** 25 minutes.',
                                                                    '**Time:** 30 minutes.')
                           + '\nA closing line.\n')
        self.cli('save', 'document', '--from', str(revised))
        changed = self.gate('document')['changes']
        self.assertEqual((changed['available'], changed['same'], changed['comparable'],
                          changed['truncated']), (True, False, True, False))
        self.assertTrue(changed['approved_at'])
        rows = [(row['kind'], row['text']) for row in changed['rows']]
        self.assertIn(('removed', '**Time:** 25 minutes.'), rows)
        self.assertIn(('added', '**Time:** 30 minutes.'), rows)
        self.assertIn(('added', 'A closing line.'), rows)
        self.assertEqual(rows[0], ('gap', ''))
        self.assertNotIn(('same', '# Rolling restarts'), rows)
        self.assertEqual(sum(kind == 'removed' for kind, _ in rows), 1)
        with mock.patch.object(desk, 'CHANGE_LIMIT', 3):
            cut = self.gate('document')['changes']
        self.assertEqual((len(cut['rows']), cut['truncated']), (3, True))

    def test_a_research_plan_is_compared_question_by_question(self):
        self.research()
        plan = json.loads(json.dumps(helpers.PLAN))
        plan['items'][0]['question'] = 'When is capacity kept?'
        self.write('.training-studio/research-plan.json', json.dumps(plan))
        rows = [(row['kind'], row['text']) for row in self.gate('research-plan')['changes']['rows']]
        self.assertIn(('removed', 'availability: When does a rolling restart keep capacity?'),
                      rows)
        self.assertIn(('added', 'availability: When is capacity kept?'), rows)

    def test_what_is_not_text_is_said_to_have_changed_and_is_not_compared(self):
        self.research()
        self.complete()
        self.write('deck.pptx', helpers.DECK + 'a different deck')
        changed = self.gate('deck')['changes']
        self.assertEqual((changed['same'], changed['comparable'], changed['rows']),
                         (False, False, []))

    def test_an_out_of_date_file_says_why_and_offers_to_accept_it(self):
        self.research()
        self.content()
        self.write('blueprint.md', test_cli.example('blueprint.md') + '\nA late edit.\n')
        gate = self.gate('document')
        self.assertEqual((gate['status'], gate['words']), ('stale', 'out of date'))
        self.assertEqual(gate['out_of_date'], ['The blueprint has changed since this was made.'])
        self.assertEqual(gate['first'], [{'artifact': 'blueprint', 'label': 'the blueprint'}])
        self.assertEqual(gate['decisions'], ['revise', 'rebuild', 'skip'])
        self.cli('approve', 'blueprint')
        gate = self.gate('document')
        self.assertEqual((gate['first'], gate['decisions']),
                         ([], ['revise', 'rebuild', 'accept', 'skip']))
        self.cli('checkpoint', '--approval', 'page')
        self.decide('accept', 'document', note='Wording only', seen=gate['sha256'])
        gate = self.gate('document')
        self.assertEqual((gate['status'], gate['approved']['by'], gate['out_of_date']),
                         ('approved', 'page', []))

    def test_a_changed_setting_is_named_as_the_reason(self):
        self.research()
        self.content()
        self.deck()
        self.cli('checkpoint', '--brand', 'Another')
        gate = self.gate('deck')
        self.assertEqual((gate['status'], gate['out_of_date']),
                         ('stale', ['The brand setting has changed since this was made.']))

    def test_what_a_gate_offers_follows_where_the_file_stands(self):
        self.research()
        self.content()
        self.assertEqual(self.gate('document')['decisions'], ['revise', 'rebuild', 'skip'])
        self.assertEqual(self.gate('document')['approved']['by'], 'chat')
        self.assertEqual(self.gate('brief')['decisions'], ['revise', 'rebuild'])
        self.assertEqual(self.gate('blueprint')['decisions'], ['revise', 'rebuild'])
        self.assertEqual(self.gate('deck')['decisions'], ['skip'])
        self.cli('skip', 'deck', '--unavailable', '--reason', 'No slide skill here')
        gate = self.gate('deck')
        self.assertEqual((gate['words'], gate['unavailable'], gate['decisions']),
                         ('could not be made', 'No slide skill here', ['restore']))

    def test_a_gate_is_of_a_registered_training_and_a_known_artifact(self):
        self.at_the_blueprint_gate()
        self.assertIn('not a training this computer knows',
                      self.get('gate', 403, path=str(self.root.parent),
                               artifact='blueprint')['error'])
        self.assertIn('is not an artifact',
                      self.get('gate', 403, path=str(self.root), artifact='../blueprint')['error'])
        self.get('gate', 400, path=str(self.root))
        status, reply, _ = self.answer('GET', '/api/gate?' + urlencode(
            {'path': str(self.root), 'artifact': 'blueprint'}), token=False)
        self.assertEqual(status, 403)

    def test_reading_a_gate_changes_nothing(self):
        self.at_the_blueprint_gate()
        before = self.on_disk()
        self.gate()
        self.gate('deck')
        self.get('training', path=str(self.root))
        self.get('trainings')
        self.get('computer')
        self.assertEqual(self.on_disk(), before)


class PlainWordsTests(PageCase):
    """Where a training is, in the page's own words."""

    def shown(self) -> dict:
        return self.listed()[str(self.root)]

    def test_a_training_is_in_progress_then_waiting_then_finished(self):
        self.cli('init', '--title', 'Rolling restarts')
        first = self.shown()
        self.assertEqual((first['state'], first['sentence'], first['stage_name'],
                          first['approval']), ('in-progress', 'Complete intake', 'Start', 'chat'))
        self.assertEqual([(stage['name'], stage['state']) for stage in first['stages']],
                         [('Start', 'current'), ('Questions', 'not-started'),
                          ('Research', 'not-started'), ('Blueprint', 'not-started'),
                          ('Guide', 'not-started'), ('Brief', 'not-started'),
                          ('Deck', 'not-started'), ('Practice', 'not-started'),
                          ('Wrap-up', 'not-started')])
        self.cli('checkpoint', '--next', '')
        self.assertEqual(self.shown()['sentence'], 'At the Start stage.')

    def test_the_row_of_stages_says_done_left_out_and_could_not_be_made(self):
        self.research(yoodli=False, copies=())
        self.cli('skip', 'brief', '--reason', 'Later')
        self.cli('skip', 'deck', '--unavailable', '--reason', 'No slide skill here')
        for name, file in (('blueprint', 'blueprint.md'), ('document', 'document.md')):
            self.make(name, file, test_cli.example(file))
        self.scenario(yoodli=False)
        self.cli('checkpoint', '--stage', 'package')
        shown = self.shown()
        self.assertEqual([(stage['name'], stage['words']) for stage in shown['stages']],
                         [('Start', 'done'), ('Questions', 'done'), ('Research', 'done'),
                          ('Blueprint', 'done'), ('Guide', 'done'), ('Brief', 'left out'),
                          ('Deck', 'could not be made'), ('Practice', 'done'),
                          ('Wrap-up', 'done')])
        self.assertEqual((shown['state'], shown['sentence']),
                         ('finished', 'Finished, with 2 things left out or limited.'))

    def test_a_finished_training_with_nothing_left_out_says_so(self):
        self.research(yoodli=False, copies=())
        for name, file in (('blueprint', 'blueprint.md'), ('document', 'document.md'),
                           ('brief', 'product-brief.md')):
            self.make(name, file, test_cli.example(file))
        self.deck()
        self.scenario(yoodli=False)
        self.assertEqual(self.shown()['sentence'], 'Finished. Everything is approved.')
        self.assertEqual(self.get('trainings')['needs'], 0)

    def test_yoodli_is_in_the_row_only_when_it_is_wanted(self):
        self.cli('init', '--title', 'Rolling restarts', '--yoodli')
        self.assertIn('Yoodli', [stage['name'] for stage in self.shown()['stages']])
        detail = self.get('training', path=str(self.root))
        self.assertEqual(detail['view']['left_out'], [])
        self.cli('skip', 'yoodli', '--reason', 'Not using it')
        self.assertNotIn('Yoodli', [stage['name'] for stage in self.shown()['stages']])
        self.assertEqual(self.get('training', path=str(self.root))['view']['left_out'],
                         [{'stage': 'yoodli', 'name': 'The Yoodli stage', 'optional': True}])

    def test_the_helpers_reasons_are_put_in_plain_words(self):
        for said, plain in (
                ('document is draft', 'The learner guide is not approved yet'),
                ('yoodli:main@301 is stale', 'The level 301 Yoodli scenario is out of date'),
                ('scenario:exec-cost is not-started',
                 'The practice scenario "exec-cost" is not started'),
                ('deck was skipped', 'The deck stage was left out'),
                ('deck unavailable: No slide skill', 'The deck stage could not be made: '
                                                     'No slide skill'),
                ('A question is waiting on the user: Ready?',
                 'A question is waiting for you: Ready?'),
                ('The user asked for a rebuild to deck@101, and that is still to do',
                 'You asked for a rebuild to the level 101 slide deck, and that is still to do'),
                ('brief was accepted as it was after its inputs changed: Fine',
                 'The brief was accepted as it was, after what it was built from changed: '
                 'Fine'),
                ('brief has no export, and the Yoodli scenario names it as the file to upload',
                 'The brief has no Word copy, and the Yoodli scenario names it as the file to '
                 'upload'),
                ('The export of document is out of date',
                 'The Word copy of the learner guide is out of date'),
                ('Yoodli handoff incomplete: no export of brief',
                 'The Yoodli handoff is incomplete: the brief has no Word copy'),
                ('The Google Doc of document is behind its file',
                 'The Google Doc of the learner guide is behind its file'),
                ('document is not in a Google Doc', 'The learner guide is not in a Google Doc'),
                ('blueprint.citations failed', 'A check failed: blueprint.citations'),
                ('blueprint.citations@301 could not run: The research is not approved.',
                 'A check could not run (blueprint.citations@301): The research is not '
                 'approved.'),
                ('No scenario file found for level 301.',
                 'No scenario file found for level 301.')):
            with self.subTest(said):
                self.assertEqual(desk.plainly(said), plain)

    def test_nothing_the_page_composes_says_artifact_stale_or_lineage(self):
        self.research('--levels', '101,301')
        self.complete('101')
        self.write('101/blueprint.md', test_cli.levelled(test_cli.example('blueprint.md'), '101')
                   + '\nA late edit.\n')
        self.cli('skip', 'yoodli', '--reason', 'Not now')
        self.cli('skip', 'deck', '--reason', 'Not now')
        self.cli('checkpoint', '--approval', 'page', '--gate', 'document@101',
                 '--question', 'Rebuild the guide?')
        self.decide('rebuild', 'brief@101')
        composed = []
        for item in self.get('trainings')['trainings']:
            composed += [item['sentence'], *(stage['words'] for stage in item['stages'])]
        detail = self.get('training', path=str(self.root))
        composed += [detail['sentence'], *detail['view']['blocking'],
                     *detail['view']['limitations'],
                     *(stage['name'] for stage in detail['view']['left_out'])]
        for file in detail['view']['files']:
            composed += [file['label'], file['words']]
            gate = self.gate(file['artifact'])
            composed += [gate['label'], gate['words'], *gate['out_of_date'],
                         *(first['label'] for first in gate['first'])]
        composed += list(desk.SAID.values()) + [desk.BACK_TO_CHAT]
        self.assertGreater(len(composed), 60)
        for text in composed:
            self.assertNotRegex(text, FORBIDDEN_WORDS)
        self.assertIn('The level 101 learner guide is out of date', detail['view']['blocking'])


class ComputerTests(PageCase):
    """The look at this computer. Every command and connection here is a stand-in."""

    FOUND = {'claude': '2.1.0 (Claude Code)', 'codex': 'codex-cli 0.48.0',
             'codex-sign-in': 'Logged in using ChatGPT', 'node': 'v22.3.0',
             'gcloud': 'Google Cloud SDK 501.0.0\nbq 2.1.9', 'pandoc': 'pandoc 3.5'}

    def looked(self, found: dict | None = None, unreachable: dict | None = None,
               skills=('harness-research', 'harness-slides'), google: bool = False) -> dict:
        """Look at a computer that has `found`, cannot reach `unreachable`, and keeps `skills`."""
        found = self.FOUND if found is None else found
        self.ran, self.reached = [], []
        names = {command: key for key, command in computer.COMMANDS.items()}

        def run(command):
            self.ran.append(command)
            said = found.get(names[command])
            if said is None:
                return {'found': False, 'ok': False, 'output': ''}
            return {'found': True, 'ok': not said.startswith('!'), 'output': said.lstrip('!')}

        def reach(host):
            self.reached.append(host)
            return (unreachable or {}).get(host)

        home = self.root.parent / 'home'
        for skill in skills:
            (home / '.claude' / 'skills' / skill).mkdir(parents=True, exist_ok=True)
        with mock.patch.object(computer, 'run', run), mock.patch.object(computer, 'reach', reach):
            return computer.check(home, google)

    def by_id(self, result: dict) -> dict:
        return {item['id']: item for item in result['items']}

    def test_a_computer_with_everything_is_ready(self):
        result = self.looked()
        self.assertEqual((result['ready'], result['wrong'], result['assistants']),
                         (True, [], ['Claude Code', 'Codex']))
        self.assertRegex(result['checked_at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')
        items = self.by_id(result)
        self.assertEqual(list(items), ['claude', 'codex', 'node', 'harness-research',
                                       'harness-slides', 'gcloud', 'pandoc'])
        self.assertEqual({item['state'] for item in items.values()}, {'ok'})
        self.assertEqual(items['claude']['facts'], [
            computer.fact('Installed', 'ok', '2.1.0'),
            computer.fact('Signed in', 'unknown', 'cannot be asked without starting it; it '
                          'says so itself when used'),
            computer.fact('Reachable from this network', 'ok', 'api.anthropic.com')])
        self.assertEqual(items['codex']['facts'][1], computer.fact('Signed in', 'ok'))
        self.assertEqual(items['harness-slides']['facts'],
                         [computer.fact('Installed', 'ok', 'for Claude Code')])
        self.assertTrue(items['pandoc']['optional'] and items['gcloud']['optional'])

    def test_it_runs_only_the_listed_commands_and_never_an_agent(self):
        self.looked()
        self.assertEqual(sorted(self.ran), sorted([
            ('claude', '--version'), ('codex', '--version'), ('codex', 'login', 'status'),
            ('node', '--version'), ('gcloud', '--version'), ('pandoc', '--version')]))
        self.assertEqual(sorted(self.reached),
                         ['api.anthropic.com', 'api.openai.com', 'chatgpt.com'])
        for command in computer.COMMANDS.values():
            self.assertFalse({'-p', 'exec', 'run', 'chat', '--print'} & set(command), command)

    def test_the_real_runner_refuses_any_other_command(self):
        for command in (('claude', '-p', 'hello'), ('codex', 'exec', 'hello'), ('claude',),
                        ('claude', '--version', '-p'), ('sh', '-c', 'true')):
            with self.subTest(command):
                with mock.patch.object(computer.subprocess, 'run', never):
                    with self.assertRaisesRegex(ValueError, 'not a command the readiness'):
                        REAL_RUN(command)

    def test_the_real_runner_reports_a_command_that_is_missing_or_fails(self):
        class Done:
            returncode, stdout, stderr = 1, '', 'Not logged in\n'

        with mock.patch.object(computer.subprocess, 'run', side_effect=FileNotFoundError):
            self.assertEqual(REAL_RUN(('pandoc', '--version')),
                             {'found': False, 'ok': False, 'output': ''})
        with mock.patch.object(computer.subprocess, 'run', return_value=Done) as ran:
            self.assertEqual(REAL_RUN(('codex', 'login', 'status')),
                             {'found': True, 'ok': False, 'output': 'Not logged in'})
        self.assertEqual(ran.call_args.args[0], ['codex', 'login', 'status'])
        self.assertEqual(ran.call_args.kwargs['timeout'], computer.TIMEOUT)

    def test_no_assistant_means_not_ready_and_says_how_to_put_it_right(self):
        result = self.looked({key: value for key, value in self.FOUND.items()
                              if key not in ('claude', 'codex', 'codex-sign-in')})
        self.assertEqual((result['ready'], result['wrong'], result['assistants']),
                         (False, ['an assistant'], []))
        items = self.by_id(result)
        self.assertEqual((items['claude']['state'], items['codex']['state']),
                         ('missing', 'missing'))
        self.assertIn('Install Claude Code', items['claude']['fix'])
        self.assertIn('codex login', items['codex']['fix'])
        self.assertEqual(len(items['codex']['facts']), 1)

    def test_one_usable_assistant_is_enough(self):
        result = self.looked(unreachable={'chatgpt.com': 'it did not answer in time'})
        self.assertEqual((result['ready'], result['assistants']), (True, ['Claude Code']))
        codex = self.by_id(result)['codex']
        self.assertEqual(codex['state'], 'problem')
        self.assertEqual(codex['facts'][2], computer.fact(
            'Reachable from this network', 'problem', 'chatgpt.com: it did not answer in time'))
        self.assertIn('Try another network', codex['fix'])

    def test_an_assistant_that_is_signed_out_is_not_usable(self):
        result = self.looked({**self.FOUND, 'codex-sign-in': '!Not logged in'},
                             unreachable={'api.anthropic.com': 'the connection failed (OSError)'})
        self.assertEqual((result['ready'], result['wrong']), (False, ['an assistant']))
        codex = self.by_id(result)['codex']
        self.assertEqual(codex['facts'][1], computer.fact('Signed in', 'problem',
                                                          'not signed in'))
        self.assertIn('To sign in, run `codex login`', codex['fix'])

    def test_nothing_a_sign_in_prints_is_repeated(self):
        said = 'Logged in using an API key - sk-secret-0123456789'
        result = self.looked({**self.FOUND, 'codex-sign-in': said},
                             unreachable={'chatgpt.com': 'it did not answer in time'})
        self.assertNotIn('sk-secret', json.dumps(result))
        codex = self.by_id(result)['codex']
        self.assertEqual((codex['state'], codex['facts'][2]['detail']),
                         ('ok', 'api.openai.com'))

    def test_what_else_is_missing_is_named_with_its_remedy(self):
        result = self.looked({'claude': '2.1.0', 'node': 'v18.20.0'}, skills=('harness-research',))
        self.assertEqual((result['ready'], result['wrong']),
                         (False, ['Node', 'harness-slides']))
        items = self.by_id(result)
        self.assertEqual((items['node']['state'], items['node']['fix']),
                         ('problem', 'Install Node 20 or newer. The research and slide skills '
                                     'run on it.'))
        self.assertEqual(items['harness-slides']['state'], 'missing')
        self.assertIn('everything is built except the slide deck', items['harness-slides']['fix'])
        self.assertEqual((items['gcloud']['state'], items['gcloud']['optional']),
                         ('missing', True))
        self.assertEqual((items['pandoc']['state'], items['pandoc']['optional']),
                         ('missing', True))
        for item in result['items']:
            self.assertEqual(bool(item['fix']), item['state'] != 'ok', item['id'])

    def test_google_is_needed_only_by_a_training_that_keeps_something_there(self):
        missing = {key: value for key, value in self.FOUND.items() if key != 'gcloud'}
        self.assertTrue(self.looked(missing)['ready'])
        result = self.looked(missing, google=True)
        self.assertEqual((result['ready'], result['wrong']), (False, ['Google Cloud CLI']))
        self.assertFalse(desk.uses_google())
        self.cli('init', '--title', 'Rolling restarts', '--copies', 'google')
        self.assertTrue(desk.uses_google())

    def test_the_page_looks_only_when_asked_and_keeps_the_answer_briefly(self):
        looks = []

        def check(google=False):
            looks.append(google)
            return {'ready': True, 'looked': len(looks)}

        self.assertEqual(self.get('computer'), {'computer': None})
        with mock.patch.object(computer, 'check', check):
            self.get('trainings')
            self.assertEqual(looks, [])
            self.assertEqual(self.post('computer', {})['computer']['looked'], 1)
            self.assertEqual(self.post('computer', {})['computer']['looked'], 1)
            self.assertEqual(self.get('computer')['computer']['looked'], 1)
            with mock.patch.object(desk, 'COMPUTER_CACHE', 0):
                self.assertEqual(self.post('computer', {})['computer']['looked'], 2)
        self.assertEqual(looks, [False, False])

    def test_a_look_is_asked_for_as_any_other_change_is(self):
        with mock.patch.object(computer, 'check', never):
            self.post('computer', {}, 403, token=False)
            self.post('computer', {}, 403, origin='http://example.com')
            self.post('computer', {}, 415, kind='text/plain')
            self.assertEqual(self.answer('GET', '/api/computer', token=False)[0], 403)


REAL_RUN = computer.run


class PageFileTests(unittest.TestCase):
    """What can be said about the page without a browser."""

    SVG = 'http://www.w3.org/2000/svg'

    def read(self, name: str) -> str:
        return (PAGE / name).read_text(encoding='utf-8')

    def test_the_page_loads_nothing_from_anywhere_else(self):
        script = self.read('app.js')
        # The name of the SVG language is how an icon is drawn in script. It is never fetched.
        self.assertEqual(script.count(self.SVG), 1)
        for name in PAGE_FILES:
            with self.subTest(name):
                self.assertNotRegex(self.read(name).replace(f"'{self.SVG}'", "''"),
                                    r'(?i)\b(?:https?|wss?|ftp|data|blob):')
        page = self.read('index.html')
        self.assertEqual(sorted(re.findall(r'(?:src|href)="([^"]*)"', page)),
                         ['#main', 'app.js', 'markdown.js', 'style.css'])
        styles = self.read('style.css')
        self.assertNotIn('url(', styles)
        self.assertNotIn('@import', styles)
        self.assertNotIn('@font-face', styles)
        self.assertEqual(set(re.findall(r"fetch\(\s*([^,)]+)", script)), {"'/api/' + endpoint"})
        self.assertNotIn('fetch(', self.read('markdown.js'))
        for elsewhere in ('XMLHttpRequest', 'WebSocket', 'EventSource', 'sendBeacon', 'import(',
                          'localStorage', 'sessionStorage', 'document.cookie'):
            for name in ('app.js', 'markdown.js'):
                self.assertNotIn(elsewhere, self.read(name))

    def test_the_page_has_nothing_its_own_policy_would_block(self):
        page = self.read('index.html')
        self.assertNotRegex(page, r'<style\b')
        self.assertNotRegex(page, r'\sstyle\s*=')
        self.assertNotRegex(page, r'\son[a-z]+\s*=')
        self.assertNotRegex(page, r'<svg\b')
        self.assertEqual(re.findall(r'<script\b[^>]*>(.*?)</script>', page, re.DOTALL),
                         ['', ''])

    def test_the_scripts_never_treat_a_value_as_markup(self):
        for name in ('app.js', 'markdown.js'):
            script = self.read(name)
            for risky in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write',
                          'createContextualFragment', 'DOMParser', 'srcdoc', 'eval(',
                          'Function(', "setAttribute('style'", "setAttribute('href'",
                          "setAttribute('src'", 'cssText'):
                with self.subTest(name=name, risky=risky):
                    self.assertNotIn(risky, script)
            self.assertIn('textContent', script)
        # A link in a document is followed only to a web address, and never hands the page over.
        renderer = self.read('markdown.js')
        self.assertIn("node.rel = 'noopener noreferrer'", renderer)
        self.assertIn('SAFE_LINK.test(target)', renderer)

    def test_the_shell_names_its_controls_and_its_regions(self):
        page = self.read('index.html')
        self.assertIn('<html lang="en">', page)
        self.assertIn('width=device-width', page)
        for label in ('Home', 'Trainings', 'Status', 'Settings'):
            self.assertRegex(page, rf'<button type="button" id="go-\w+" class="nav-item"[^>]*>'
                                   rf'<span class="nav-label">{label}</span>')
        self.assertIn('<nav id="sidebar" class="sidebar glass" aria-label="Screens">', page)
        self.assertIn('id="notice" class="notice" role="alert"', page)
        self.assertIn('id="toasts" class="toasts" role="status" aria-live="polite"', page)
        self.assertIn('id="sheet" class="sheet glass" role="dialog" '
                      'aria-labelledby="sheet-title"', page)
        self.assertEqual(len(re.findall(r'<h1\b', page)), 1)
        self.assertNotRegex(page, r'tabindex="[1-9]')
        self.assertNotRegex(self.read('app.js'), r'tabIndex = [1-9]')

    def test_every_state_has_a_shape_of_its_own(self):
        script, styles = self.read('app.js'), self.read('style.css')
        drawn = dict(re.findall(r"(\w+): '(\w+)'", re.search(
            r'const BEAD_ICONS = \{(.*?)\};', script, re.DOTALL)[1]))
        self.assertEqual(drawn, {'done': 'check', 'review': 'eye', 'late': 'warn',
                                 'out': 'minus', 'off': 'slash'})
        self.assertEqual(len(set(drawn.values())), len(drawn))
        for icon in drawn.values():
            self.assertRegex(script, rf'\n  {icon}: \[')
        # In progress is a bead half full; not started is an empty one.
        self.assertIn('.bead[data-state="current"]::before', styles)
        self.assertNotIn('.bead[data-state="none"]', styles)

    def tokens(self) -> tuple[dict, dict]:
        """The colour tokens of the light and the dark appearance."""
        styles = self.read('style.css')

        def block(text: str, start: str) -> str:
            at = text.index('{', text.index(start))
            depth, end = 1, at + 1
            while depth:
                depth += {'{': 1, '}': -1}.get(text[end], 0)
                end += 1
            return text[at + 1:end - 1]

        def colours(body: str) -> dict:
            found = {}
            for name, value in re.findall(r'--([\w-]+):\s*([^;]+);', body):
                solid = re.fullmatch(r'#([0-9a-f]{6})', value.strip())
                mixed = re.fullmatch(r'rgb\((\d+) (\d+) (\d+)(?: / ([\d.]+))?\)', value.strip())
                if solid:
                    found[name] = (*(int(solid[1][at:at + 2], 16) for at in (0, 2, 4)), 1.0)
                elif mixed:
                    found[name] = (int(mixed[1]), int(mixed[2]), int(mixed[3]),
                                   float(mixed[4] or 1))
            return found

        light = colours(block(styles, ':root'))
        dark = colours(block(block(styles, '@media (prefers-color-scheme: dark)'), ':root'))
        self.assertEqual(set(light), set(dark), 'each appearance defines every colour')
        return light, dark

    @staticmethod
    def over(top: tuple, under: tuple) -> tuple:
        return (*(top[at] * top[3] + under[at] * (1 - top[3]) for at in range(3)), 1.0)

    @staticmethod
    def contrast(first: tuple, second: tuple) -> float:
        def luminance(colour: tuple) -> float:
            parts = [value / 255 for value in colour[:3]]
            parts = [part / 12.92 if part <= 0.03928 else ((part + 0.055) / 1.055) ** 2.4
                     for part in parts]
            return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2]

        lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
        return (lighter + 0.05) / (darker + 0.05)

    def test_text_stays_readable_on_glass_whatever_is_behind_it(self):
        for name, colour in zip(('light', 'dark'), self.tokens()):
            behind = [colour['ground'], colour['paper'],
                      *(self.over(colour[f'wash-{at}'], colour['ground']) for at in range(1, 6))]
            surfaces = {'paper': [colour['paper']], 'solid': [colour['solid']]}
            for glass in ('glass', 'card', 'sheet-fill'):
                surfaces[glass] = [self.over(colour[glass], under) for under in behind]
            for text in ('ink', 'quiet', 'link', 'yours', 'late', 'done'):
                for surface, shades in surfaces.items():
                    with self.subTest(appearance=name, text=text, on=surface):
                        worst = min(self.contrast(colour[text], shade) for shade in shades)
                        self.assertGreaterEqual(worst, 4.5)
            every = [shade for shades in surfaces.values() for shade in shades]
            pairs = {
                'a filled button': (colour['on-accent'], [colour['accent']], 4.5),
                'what is yours, on its wash': (colour['yours'], [colour['yours-wash']], 4.5),
                'what is late, on its wash': (colour['late'], [colour['late-wash']], 4.5),
                'quiet words on a wash': (colour['quiet'], [colour['yours-wash'],
                                                            colour['late-wash']], 4.5),
                'a chosen item': (colour['ink'], [self.over(colour['thumb'], shade)
                                                  for shade in every], 4.5),
                'a quiet option in its well': (colour['quiet'], [
                    self.over(colour['well'], shade) for shade in every], 4.5),
                'the focus ring': (colour['focus'], every, 3),
                'the tick on a done bead': ((255, 255, 255, 1.0), [colour['done-fill']], 3),
                'the mark on a late bead': (colour['paper'], [colour['late']], 3),
                'the badge': ((0x2b, 0x18, 0, 1.0), [colour['yours-fill']], 4.5),
            }
            for what, (text, shades, least) in pairs.items():
                with self.subTest(appearance=name, what=what):
                    self.assertGreaterEqual(min(self.contrast(text, shade) for shade in shades),
                                            least)

    def test_the_two_appearances_are_not_one_inverted(self):
        light, dark = self.tokens()
        self.assertGreater(self.contrast(light['ground'], (0, 0, 0, 1)), 15)
        self.assertGreater(self.contrast(dark['ground'], (255, 255, 255, 1)), 15)
        for name in ('wash-1', 'wash-2', 'wash-3', 'accent', 'glass', 'card', 'paper'):
            inverted = (*(255 - value for value in light[name][:3]), light[name][3])
            self.assertNotEqual(dark[name], inverted, name)

    def test_only_a_few_layers_blur_what_is_behind_them(self):
        styles, page, script = self.read('style.css'), self.read('index.html'), self.read('app.js')
        rules = re.sub(r'/\*.*?\*/', '', styles, flags=re.DOTALL)
        blurred = re.findall(r'([^{}]+)\{[^{}]*[^-]backdrop-filter: blur', rules)
        self.assertEqual([selector.strip() for selector in blurred], ['.glass'])
        self.assertEqual(len(re.findall(r'class="[^"]*\bglass\b', page)), 3)
        self.assertEqual(re.findall(r"'([\w -]*\bglass\b[\w -]*)'", script), ['toast glass'])

    def test_the_glass_has_every_fallback(self):
        styles = self.read('style.css')
        without = styles[styles.index('@supports not ((backdrop-filter: blur(1px))'):]
        self.assertIn('--glass: var(--solid);', without)
        calmer = styles[styles.index('@media (prefers-reduced-transparency: reduce), '
                                     '(prefers-contrast: more)'):]
        for swapped in ('--glass: var(--solid);', '--card: var(--solid);',
                        '--sheet-fill: var(--solid);', '--glass-line: var(--quiet);',
                        'backdrop-filter: none;', '.backdrop {\n    display: none;'):
            self.assertIn(swapped, calmer)
        still = styles[styles.index('@media (prefers-reduced-motion: reduce)'):]
        self.assertIn('animation: none !important;', still)
        self.assertIn('transition: none !important;', still)
        self.assertIn('::view-transition-group(*)', still)
        script = self.read('app.js')
        self.assertIn('if (document.startViewTransition && !calm())', script)
        self.assertRegex(script, r'function followPointer\(\) \{\n  if \(calm\(\)\) return;')
        self.assertIn("(prefers-reduced-motion: reduce)", script)

    def test_the_system_colour_and_the_system_type_are_used(self):
        styles = self.read('style.css')
        self.assertIn('@supports (color: AccentColor)', styles)
        self.assertIn('--accent: AccentColor;', styles)
        self.assertIn('--plain: -apple-system, BlinkMacSystemFont, "SF Pro Text", '
                      '"Helvetica Neue", sans-serif;', styles)
        self.assertIn('--typed: ui-monospace, "SF Mono", monospace;', styles)

    def test_focus_is_always_shown_where_the_keyboard_put_it(self):
        styles = self.read('style.css')
        self.assertRegex(styles, r':focus-visible \{\n  outline: 3px solid var\(--focus\);')
        rules = re.sub(r'/\*.*?\*/', '', styles, flags=re.DOTALL)
        hidden = re.findall(r'([^{}]+)\{[^{}]*outline: none', rules)
        # Only what the page itself moves focus to, never a control, goes without a ring.
        self.assertEqual(sorted(selector.strip() for selector in hidden),
                         ['.page:focus', '.sheet:focus', '.title:focus'])

    def test_both_appearances_and_a_narrow_layout_are_styled(self):
        styles = self.read('style.css')
        self.assertIn('prefers-color-scheme: dark', styles)
        self.assertRegex(styles, r'@media \(max-width: 52rem\)')
        self.assertRegex(styles, r'@media \(min-width: 70rem\)')


def tags(tree, found=None) -> list[str]:
    """Every element in a rendered tree, in order."""
    found = [] if found is None else found
    if isinstance(tree, dict):
        found.append(tree['tag'])
        for child in tree.get('children', []):
            tags(child, found)
    return found


def text_of(tree) -> str:
    if isinstance(tree, str):
        return tree
    return ''.join(text_of(child) for child in tree.get('children', []))


def first(tree, tag: str):
    if isinstance(tree, dict):
        if tree['tag'] == tag:
            return tree
        for child in tree.get('children', []):
            found = first(child, tag)
            if found:
                return found
    return None


@unittest.skipUnless(NODE, 'Node is needed to run the page scripts without a browser')
class MarkdownTests(unittest.TestCase):
    """markdown.js, run for real against a document that has no HTML parser."""

    def render(self, text: str, files: bool = False) -> dict:
        done = subprocess.run([NODE, str(HARNESS), 'markdown', *(['files'] if files else [])],
                              input=text, text=True, capture_output=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_a_training_document_is_drawn_as_a_document(self):
        tree = self.render(test_cli.example('document.md'))
        drawn = tags(tree)
        self.assertEqual(drawn[:2], ['div', 'h2'])
        for expected in ('h3', 'h4', 'p', 'ul', 'li', 'strong', 'blockquote', 'ol', 'code', 'br'):
            self.assertIn(expected, drawn)
        self.assertEqual(text_of(first(tree, 'h2')), 'Rolling restarts')
        self.assertNotIn('covers:', text_of(tree))
        self.assertNotIn('<!--', text_of(tree))
        self.assertIn('Capacity holds only when more than one instance is running',
                      text_of(tree))

    def test_every_example_and_format_draws_without_markup_or_comments(self):
        allowed = {'div', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'ul', 'ol', 'li', 'strong', 'em',
                   'code', 'pre', 'blockquote', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
                   'a', 'br', 'hr'}
        for path in sorted(helpers.EXAMPLES.glob('*.md')):
            with self.subTest(path.name):
                tree = self.render(path.read_text(encoding='utf-8'))
                self.assertLessEqual(set(tags(tree)), allowed)
                self.assertNotRegex(text_of(tree), r'<!--|-->')

    def test_markup_in_a_document_is_shown_as_the_text_it_is(self):
        tree = self.render(MARKUP + '\n<b onclick="x()">bold</b> and <iframe src="//example.com">'
                           '\n\n[a link](javascript:alert(3)) [another](data:text/html,x) '
                           '[relative](/api/trainings) <javascript:alert(4)>\n')
        self.assertLessEqual(set(tags(tree)), {'div', 'p', 'br'})
        shown = text_of(tree)
        for kept in ('<script>alert(1)</script>', '<img src=x onerror=alert(2)>',
                     '<b onclick="x()">bold</b>', '<iframe src="//example.com">',
                     '[a link](javascript:alert(3))', '[another](data:text/html,x)',
                     '[relative](/api/trainings)', '<javascript:alert(4)>'):
            self.assertIn(kept, shown)

    def test_an_index_names_its_trainings_files_plainly_and_never_links_them(self):
        text = ('[intake.md](intake.md) and [its review](reviews/research-plan.md), but '
                '[up](../secret.md), [root](/api/trainings), [odd](javascript:alert(1)) and '
                '[the docs](https://example.com/docs).\n')
        tree = self.render(text, files=True)
        shown = text_of(tree)
        for kept in ('intake.md and its review (reviews/research-plan.md)',
                     '[up](../secret.md)', '[root](/api/trainings)',
                     '[odd](javascript:alert(1))'):
            self.assertIn(kept, shown)
        self.assertNotIn('[intake.md]', shown)
        # Only the web address became a link.
        links = [child for child in first(tree, 'p')['children'] if isinstance(child, dict)]
        self.assertEqual([link['href'] for link in links], ['https://example.com/docs'])
        # Any other document shows such a link exactly as it was written.
        self.assertIn('[intake.md](intake.md)', text_of(self.render(text)))

    def test_a_link_goes_only_to_a_web_address_and_never_hands_the_page_over(self):
        tree = self.render('See [the docs](https://example.com/docs "Title"), '
                           '<http://example.com/plain> and [**bold** text](https://example.com).')
        links = [child for child in first(tree, 'p')['children'] if isinstance(child, dict)]
        self.assertEqual([(link['href'], link['rel'], link['target']) for link in links],
                         [('https://example.com/docs', 'noopener noreferrer', '_blank'),
                          ('http://example.com/plain', 'noopener noreferrer', '_blank'),
                          ('https://example.com', 'noopener noreferrer', '_blank')])
        self.assertEqual([text_of(link) for link in links],
                         ['the docs', 'http://example.com/plain', 'bold text'])
        self.assertEqual(tags(links[2]), ['a', 'strong'])

    def test_comments_are_left_out_wherever_they_fall(self):
        tree = self.render('Before <!-- covers: O1 --> after.\n\n<!-- a\ncomment over\nlines -->\n'
                           '\nKept.\n\n```\n<!-- shown in code -->\n```\n\n<!-- unfinished\n')
        self.assertEqual([text_of(child) for child in tree['children']],
                         ['Before  after.', 'Kept.', '<!-- shown in code -->'])

    def test_lists_tables_code_and_quotes(self):
        tree = self.render(
            '1. First\n2. Second\n   - nested `code`\n   - more\n3. Third\n\n'
            '5) starts at five\n\n'
            '| Instances | Serving |\n| --- | :-: |\n| 1 | none |\n| 3 | **two** |\n\n'
            '> A quote\n> over two lines.\n>\n> - with a list\n\n'
            '```text\ncf restart app\n  indented *not emphasis*\n```\n\n---\n\nAfter.\n')
        kinds = [child['tag'] for child in tree['children']]
        self.assertEqual(kinds, ['ol', 'ol', 'div', 'blockquote', 'pre', 'hr', 'p'])
        numbered = tree['children'][0]
        self.assertEqual([text_of(item) for item in numbered['children']],
                         ['First', 'Secondnested codemore', 'Third'])
        self.assertEqual(tags(numbered['children'][1]), ['li', 'ul', 'li', 'code', 'li'])
        self.assertEqual(tree['children'][1]['start'], 5)
        table = tree['children'][2]
        self.assertEqual(table['class'], 'md-table')
        self.assertEqual(tags(table), ['div', 'table', 'thead', 'tr', 'th', 'th', 'tbody',
                                       'tr', 'td', 'td', 'tr', 'td', 'td', 'strong'])
        self.assertEqual(first(table, 'th')['scope'], 'col')
        self.assertEqual(tags(tree['children'][3]), ['blockquote', 'p', 'br', 'ul', 'li'])
        self.assertEqual(text_of(tree['children'][4]),
                         'cf restart app\n  indented *not emphasis*')

    def test_emphasis_escapes_and_names_with_underscores(self):
        tree = self.render('*one* _two_ **three** __four__ a_b_c 2 * 3 * 4 \\*not\\* '
                           '`x_y_z` snake_case_name\n')
        paragraph = first(tree, 'p')
        self.assertEqual(tags(paragraph), ['p', 'em', 'em', 'strong', 'strong', 'code'])
        self.assertEqual(text_of(paragraph), 'one two three four a_b_c 2 * 3 * 4 *not* '
                                             'x_y_z snake_case_name')

    def test_lines_of_a_paragraph_keep_their_breaks_and_a_list_ends_at_plain_text(self):
        tree = self.render('Audience: engineers\nTime: 25 min\n- K1.1: a point\n'
                           'Example: an app.\n')
        self.assertEqual([child['tag'] for child in tree['children']], ['p', 'ul', 'p'])
        self.assertEqual(tags(tree['children'][0]), ['p', 'br'])
        self.assertEqual(text_of(tree['children'][2]), 'Example: an app.')


class ScriptedPage:
    """Runs app.js in the harness, and checks what every screen it shows must hold."""

    def captured(self, method: str, target: str, sent=None) -> dict:
        body = None if sent is None else json.dumps(sent).encode()
        status, reply, _ = self.answer(method, target, body, origin=self.origin,
                                       kind='application/json' if sent is not None else None)
        return {'status': status, 'body': reply}

    def read(self, endpoint: str, **params) -> dict:
        return self.captured('GET', f'/api/{endpoint}' + (f'?{urlencode(params)}'
                                                          if params else ''))

    def run_page(self, answers: dict, steps: list, **plan) -> dict:
        file = self.root.parent / 'plan.json'
        file.write_text(json.dumps({'answers': answers, 'steps': steps, **plan}),
                        encoding='utf-8')
        done = subprocess.run([NODE, str(HARNESS), 'app', str(file)], text=True,
                              capture_output=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        result = json.loads(done.stdout)
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['strayListeners'], [],
                         'only a real control may answer a click, so the keyboard reaches it')
        for name, shot in result['snapshots'].items():
            with self.subTest(screen=name):
                self.assertEqual(shot['unnamed'], [], 'every control has a name')
                self.assertEqual(shot['foreign'], 0, 'nothing from a file became an element')
                self.assertEqual(shot['bareBeads'], 0, 'every bead has words beside it')
                self.assertLessEqual(len(shot['filled']), 1, 'one filled button on a screen')
                self.assertNotRegex(shot['text'].replace(MARKUP_TITLE, ''), FORBIDDEN_WORDS)
        return result


@unittest.skipUnless(NODE, 'Node is needed to run the page scripts without a browser')
class PageScriptTests(ScriptedPage, PageCase):
    """app.js, run for real against the server's own answers, in a document with no parser.

    Each step presses a control the way Enter or Space would. A script that wrote markup,
    left a control without a name, or put a click on something that is not a control fails.
    """

    def a_gate_with_history(self) -> None:
        """The learner guide at its gate on the page, changed since it was last approved."""
        self.research()
        self.content()
        revised = self.root.parent / 'revised.md'
        revised.write_text(test_cli.example('document.md').replace('25 minutes', '30 minutes')
                           + '\n| Instances | Serving |\n| --- | --- |\n| 3 | two |\n')
        self.cli('save', 'document', '--from', str(revised))
        self.write('reviews/document.md', '## Review\n\n- The table is new. *My judgment.*\n')
        self.cli('checkpoint', '--approval', 'page', '--gate', 'document', '--stage',
                 'document', '--question', 'Is the guide ready?')

    def test_a_change_is_asked_for_from_home_to_done(self):
        self.a_gate_with_history()
        other = self.another('second')
        (other / '.training-studio' / 'session.json').write_text('{not json')
        gate = {'path': str(self.root), 'artifact': 'document'}
        answers = {'GET /api/trainings': [self.read('trainings')],
                   'GET /api/computer': [self.read('computer')],
                   'GET /api/gate': [self.read('gate', **gate)]}
        answers['POST /api/decide'] = [self.captured('POST', '/api/decide', {
            **gate, 'decision': 'revise', 'note': 'Shorten the opening.'})]
        answers['GET /api/trainings'].append(self.read('trainings'))
        answers['GET /api/gate'].append(self.read('gate', **gate))
        answers['GET /api/training'] = [self.read('training', path=str(self.root))]
        result = self.run_page(answers, [
            {'snapshot': 'home'},
            {'click': 'Review the learner guide'}, {'snapshot': 'gate'},
            {'click': 'What changed'}, {'snapshot': 'changes'},
            {'click': 'Ask for changes'}, {'snapshot': 'form'},
            {'click': 'Send for changes'}, {'snapshot': 'refused'},
            {'type': '  Shorten the opening.  '}, {'click': 'Send for changes'},
            {'snapshot': 'done'},
            {'click': 'Stay here'}, {'snapshot': 'after'},
            {'click': 'Rolling restarts'}, {'snapshot': 'training'},
            {'click': 'Trainings'}, {'snapshot': 'trainings'},
        ])
        shots = result['snapshots']

        home = shots['home']
        self.assertEqual((home['title'], home['heading'], home['badge']),
                         ('(1) Training Studio', 'Home', '1 thing needs you'))
        self.assertRegex(home['text'], r'Good (morning|afternoon|evening)\. One thing needs you\.')
        self.assertLess(home['text'].index('Needs you'), home['text'].index('Cannot be read'))
        self.assertIn('The learner guide is waiting for your review.', home['text'])
        self.assertIn('Your assistant asks: Is the guide ready?', home['text'])
        self.assertIn('This computer has not been checked yet.', home['text'])
        self.assertEqual(home['filled'], ['Review the learner guide'])
        self.assertEqual(home['focus'], 'title')
        self.assertEqual(home['current'], ['Home1 thing needs you'])
        self.assertEqual(home['buttons'][0], 'Home1 thing needs you')

        gate_shot = shots['gate']
        self.assertEqual(gate_shot['title'],
                         '(1) The learner guide · Rolling restarts · Training Studio')
        self.assertEqual((gate_shot['heading'], gate_shot['filled'], gate_shot['pressed']),
                         ('The learner guide', ['Approve'], ['The document']))
        for shown in ('Waiting for your review', 'Guide: yours to review',
                      'Your assistant asks: Is the guide ready?', 'Checked for you',
                      '1 check passed', 'Worth a look', 'The latest review note',
                      'The table is new. My judgment.', 'What changed',
                      "A rolling restart replaces an app's instances one batch at a time"):
            self.assertIn(shown, gate_shot['text'])
        self.assertNotIn('covers: O1', gate_shot['text'])
        self.assertEqual(gate_shot['buttons'][1:6], ['Trainings', 'Status', 'Settings', 'Back',
                                                     'Rolling restarts'])
        self.assertEqual(gate_shot['buttons'][6:9], ['Ask for changes', 'More', 'Approve'])
        self.assertEqual(gate_shot['posts'], 0)
        self.assertEqual(gate_shot['current'], ['Trainings'])
        self.assertEqual(set(gate_shot['beads']), {'done', 'review', 'none'})

        changes = shots['changes']
        self.assertEqual(changes['pressed'], ['What changed'])
        self.assertIn('−**Time:** 25 minutes. (removed)', changes['text'])
        self.assertIn('+**Time:** 30 minutes. (added)', changes['text'])

        self.assertEqual(shots['form']['focus'], 'note-text')
        self.assertEqual(shots['form']['filled'], ['Send for changes'])
        self.assertIn('What should change?', shots['form']['sheet'])
        self.assertNotIn('Approve', shots['form']['buttons'])
        self.assertNotIn('Say what should change first.', shots['form']['sheet'])

        # A missing note is refused beside the control, and nothing is sent.
        self.assertIn('Say what should change first.', shots['refused']['sheet'])
        self.assertEqual(shots['refused']['focus'], 'note-text')
        posts = [request for request in result['requests'] if request['method'] == 'POST']
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]['address'], '/api/decide')
        self.assertEqual(posts[0]['body'], {**gate, 'decision': 'revise',
                                            'note': 'Shorten the opening.',
                                            'seen': self.sha('document.md')})
        self.assertEqual(posts[0]['headers'], {desk.TOKEN_HEADER: 'the-test-key',
                                               'Content-Type': 'application/json'})

        done = shots['done']
        self.assertIn('Your changes are noted.', done['sheet'])
        self.assertIn('You can close this page.', done['sheet'])
        self.assertIn('Nothing else needs you right now.', done['sheet'])
        self.assertEqual((done['filled'], done['focus'], done['badge']),
                         (['Back to home'], 'sheet', ''))
        self.assertEqual(done['title'], 'The learner guide · Rolling restarts · Training Studio')
        self.assertIn('You asked for changes', done['text'])
        self.assertNotIn('Waiting for your review', done['text'])

        self.assertEqual((shots['after']['sheet'], shots['after']['filled']),
                         ('', ['Approve']))
        self.assertEqual(shots['after']['focus'], 'Ask for changes')

        one = shots['training']
        self.assertEqual((one['heading'], one['current'], one['filled']),
                         ('Rolling restarts', ['Trainings'], []))
        for shown in ('In progress', 'You asked for changes to the learner guide.', 'Files',
                      'not approved yet, changes asked for', 'In the way', 'Checks',
                      'Left out or limited', 'Practice', 'Research', 'Guidance',
                      'How this training is decided', 'Carry on with your assistant',
                      'Use training-studio to resume the training in'):
            self.assertIn(shown, one['text'])
        self.assertEqual(one['pressed'], ['On this page'])

        every = shots['trainings']
        self.assertEqual((every['heading'], every['filled']), ('Trainings', []))
        self.assertIn('2 trainings on this computer', every['text'])
        self.assertIn('Cannot be read', every['text'])
        self.assertIn('not valid JSON', every['text'])

    def test_an_approval_is_confirmed_in_the_sheet_and_names_what_was_read(self):
        self.at_the_blueprint_gate()
        other = self.root.parent / 'markup'
        other.mkdir()
        with contextlib.redirect_stdout(io.StringIO()):
            training.main(['--dir', str(other), 'init', '--title', MARKUP_TITLE])
        workspace.checkpoint(other, question='Who is it for?')
        gate = {'path': str(self.root), 'artifact': 'blueprint'}
        answers = {'GET /api/trainings': [self.read('trainings')],
                   'GET /api/computer': [self.read('computer')],
                   'GET /api/gate': [self.read('gate', **gate)]}
        seen = answers['GET /api/gate'][0]['body']['sha256']
        answers['POST /api/decide'] = [self.captured('POST', '/api/decide', {
            **gate, 'decision': 'approve', 'seen': seen})]
        answers['GET /api/trainings'].append(self.read('trainings'))
        answers['GET /api/gate'].append(self.read('gate', **gate))
        result = self.run_page(answers, [
            {'snapshot': 'home'},
            {'click': 'Review: Rolling restarts'}, {'snapshot': 'gate'},
            {'click': 'Approve'}, {'snapshot': 'confirm'},
            {'key': 'Escape'}, {'snapshot': 'put away'},
            {'click': 'Approve'}, {'click': 'Approve'}, {'snapshot': 'done'},
        ], notifications='granted')
        shots = result['snapshots']
        # A title that is markup is shown as the text it is.
        self.assertIn(MARKUP_TITLE, shots['home']['text'])
        self.assertIn('Two things need you.', shots['home']['text'])
        self.assertEqual(shots['home']['title'], '(2) Training Studio')
        self.assertEqual(shots['gate']['pressed'], [])
        self.assertIn('You have not approved a version of this before', shots['gate']['text'])
        confirm = shots['confirm']
        self.assertIn('Approve the blueprint?', confirm['sheet'])
        self.assertEqual((confirm['filled'], confirm['focus'], confirm['posts']),
                         (['Approve'], 'sheet', 0))
        self.assertEqual((shots['put away']['sheet'], shots['put away']['filled']),
                         ('', ['Approve']))
        self.assertEqual(shots['put away']['focus'], 'Approve')
        posts = [request for request in result['requests'] if request['method'] == 'POST']
        self.assertEqual([post['body'] for post in posts],
                         [{**gate, 'decision': 'approve', 'seen': seen}])
        done = shots['done']
        self.assertIn('Approved.', done['sheet'])
        self.assertIn('A question is waiting for you: Who is it for?', done['sheet'])
        self.assertEqual(done['filled'], ['Open the next one'])
        self.assertIn('You approved this on this page', done['text'])
        self.assertEqual(done['title'], '(1) The blueprint · Rolling restarts · Training Studio')

    def test_in_the_conversation_the_gate_says_so_and_offers_one_control(self):
        self.at_the_blueprint_gate(approval='chat')
        gate = {'path': str(self.root), 'artifact': 'blueprint'}
        answers = {'GET /api/trainings': [self.read('trainings')],
                   'GET /api/computer': [self.read('computer')],
                   'GET /api/gate': [self.read('gate', **gate)]}
        answers['POST /api/approval'] = [self.captured('POST', '/api/approval', {
            'path': str(self.root), 'mode': 'page'})]
        answers['GET /api/gate'].append(self.read('gate', **gate))
        result = self.run_page(answers, [
            {'click': 'Review the blueprint'}, {'snapshot': 'chat'},
            {'click': 'Decide on this page instead'}, {'snapshot': 'page'},
        ])
        chat = result['snapshots']['chat']
        self.assertIn('approving happens in your conversation with your assistant', chat['text'])
        self.assertEqual(chat['filled'], [])
        for absent in ('Approve', 'Ask for changes', 'More'):
            self.assertNotIn(absent, chat['buttons'])
        page = result['snapshots']['page']
        self.assertEqual((page['filled'], page['focus']), (['Approve'], 'Approve'))
        self.assertEqual(page['toasts'], ['Decisions for this training are now made on this '
                                          'page.'])
        self.assertNotIn('Decide on this page instead', page['buttons'])

    def test_status_and_settings_and_a_new_thing_that_needs_the_user(self):
        self.at_the_blueprint_gate()
        quiet = self.read('trainings')
        quiet['body']['trainings'][0].update(state='in-progress', waiting=None,
                                             sentence='Drafting the blueprint.')
        quiet['body']['needs'] = 0
        result_of_check = self.ComputerLook.result
        answers = {'GET /api/trainings': [quiet, self.read('trainings')],
                   'GET /api/computer': [self.read('computer')],
                   'POST /api/computer': [{'status': 200, 'body': {'computer': result_of_check}}],
                   'POST /api/approval': [{'status': 409, 'body': {'error': 'Not now.'}}]}
        result = self.run_page(answers, [
            {'snapshot': 'quiet'}, {'poll': True}, {'snapshot': 'needed'},
            {'click': 'Status'}, {'snapshot': 'status'},
            {'click': 'Check this computer'}, {'snapshot': 'checked'},
            {'click': 'Settings'}, {'snapshot': 'settings'},
            {'click': 'In the conversation'}, {'snapshot': 'refused'},
        ], notifications='granted')
        shots = result['snapshots']
        self.assertIn('Nothing needs you right now.', shots['quiet']['text'])
        self.assertEqual((shots['quiet']['title'], shots['quiet']['filled'],
                          shots['quiet']['badge']), ('Training Studio', [], ''))
        self.assertEqual((shots['needed']['title'], shots['needed']['badge']),
                         ('(1) Training Studio', '1 thing needs you'))
        said = 'Rolling restarts: The blueprint is waiting for your review.'
        self.assertEqual(result['notifications'],
                         [{'title': 'Training Studio needs you', 'body': said}])
        self.assertEqual(shots['needed']['toasts'], [said])

        status = shots['status']
        self.assertEqual((status['heading'], status['filled'], status['current']),
                         ('Status', ['Check this computer'], ['Status']))
        for shown in ('Rolling restarts', 'Blueprint', 'Waiting for you', 'This computer',
                      'It asks each one for its version and nothing more.'):
            self.assertIn(shown, status['text'])
        checked = shots['checked']
        for shown in ('Not ready yet. To put right: harness-slides.', 'Claude Code', 'Ready',
                      'Signed in: cannot be asked', 'Needs attention', 'Try another network',
                      'Not installed', 'Not installed (optional)'):
            self.assertIn(shown, checked['text'])
        self.assertEqual(checked['filled'], ['Check this computer again'])
        self.assertIn('This computer needs something put right.', checked['toasts'])

        settings = shots['settings']
        self.assertEqual((settings['heading'], settings['pressed']),
                         ('Settings', ['On this page']))
        for shown in ('Notifications', 'On. This browser tells you when something needs you',
                      'Where each training is decided', 'Nothing you read or decide here is '
                      'sent anywhere else.'):
            self.assertIn(shown, settings['text'])
        # The thumb slides back when the answer is no, and the reason is said.
        self.assertEqual(shots['refused']['pressed'], ['On this page'])
        self.assertIn('Not now.', shots['refused']['toasts'])

    class ComputerLook:
        result = {'checked_at': '2030-01-02T03:04:05Z', 'ready': False,
                  'assistants': ['Claude Code'], 'wrong': ['harness-slides'], 'items': [
                      computer.item('claude', 'Claude Code', 'ok', [
                          computer.fact('Installed', 'ok', '2.1.0'),
                          computer.fact('Signed in', 'unknown', 'cannot be asked'),
                          computer.fact('Reachable from this network', 'ok', 'a.example')]),
                      computer.item('codex', 'Codex', 'problem', [
                          computer.fact('Installed', 'ok', '0.48.0'),
                          computer.fact('Reachable from this network', 'problem', 'no')],
                          'Try another network.'),
                      computer.item('harness-slides', 'harness-slides', 'missing', [
                          computer.fact('Installed', 'problem', 'not found')], 'Get it.'),
                      computer.item('pandoc', 'pandoc', 'missing', [
                          computer.fact('Installed', 'problem', 'not found')], 'Optional.',
                          optional=True)]}

    def test_no_trainings_is_an_invitation_and_a_link_without_its_key_says_so(self):
        answers = {'GET /api/trainings': [self.read('trainings')],
                   'GET /api/computer': [self.read('computer')]}
        result = self.run_page(answers, [{'snapshot': 'empty'}, {'click': 'Trainings'},
                                         {'snapshot': 'none'}])
        empty = result['snapshots']['empty']
        self.assertIn('Start your first training', empty['text'])
        self.assertIn('Use training-studio to build a 101 training on rolling restarts.',
                      empty['text'])
        self.assertIn('Start your first training', result['snapshots']['none']['text'])
        result = self.run_page(answers, [{'snapshot': 'no key'}], hash='')
        self.assertIn('Run the desk command again in your terminal',
                      result['snapshots']['no key']['notice'])
        self.assertEqual(result['requests'], [])

    def test_a_link_with_the_wrong_key_is_explained(self):
        refused = {'status': 403, 'body': {'error': 'This needs the key.'}}
        result = self.run_page({'GET /api/trainings': [refused]}, [{'snapshot': 'refused'}])
        self.assertIn('This link does not match the page that is running.',
                      result['snapshots']['refused']['notice'])


def ok(body) -> dict:
    return {'status': 200, 'body': body}


# The runner's answers, written out field for field from the appendices of the milestone 2
# and milestone 3 specifications ("What the page asks the runner"). Its server is built apart
# from the page.
RUNNER = ok({'runner': True, 'version': '0.9.0'})
LIMITS = {'step_seconds': 900, 'training_dollars': 20, 'parallel': 2}
NOT_SET_UP = {'configured': False, 'workspace': None,
              'agent': {'default': 'claude', 'model': None}, 'limits': LIMITS}
WORKSPACE = {'name': 'Field enablement', 'repository': 'git@example.com:team/tools.git',
             'path': '/Users/pat/Library/Training Studio/workspace', 'folder': 'trainings',
             'branch': 'main', 'share_when': 'each-decision', 'shared': True, 'notice': None}
SET_UP = {'configured': True, 'workspace': WORKSPACE,
          'agent': {'default': 'claude', 'model': None}, 'limits': LIMITS}
AGENTS_FOUND = {'agents': [
    {'agent': 'claude', 'installed': True, 'signed_in': None, 'reachable': True,
     'version': '2.1.0', 'problem': None},
    {'agent': 'codex', 'installed': True, 'signed_in': False, 'reachable': None,
     'version': '0.48.0',
     'problem': 'Codex is not signed in. Run codex login in a terminal, then look again.'}]}
RUN_FIELDS = {'state', 'sentence', 'agent', 'model', 'steps', 'workers', 'spent', 'question',
              'problem', 'documents', 'copies', 'deck', 'finished'}
STEP_FIELDS = {'id', 'label', 'kind', 'status', 'attempts', 'seconds', 'dollars', 'error'}
DOCUMENT_FIELDS = {'name', 'bytes', 'readable', 'problem'}
COPY_FIELDS = {'artifact', 'label', 'kind', 'state', 'link', 'problem'}
TYPES = ['.txt', '.md', '.html', '.htm', '.docx']
NO_PDF = 'A PDF cannot be read on this computer. Save it as text or Word first.'
KEPT_HERE = ('Your documents stay on this computer and are never shared with your team. '
             'Passages quoted from them appear in the research report, which is shared.')
DECK_LEFT = ('Everything but the slide deck is made: make the deck with your assistant, or '
             'leave it out.')


def a_step(name: str, label: str, kind: str, status: str, **more) -> dict:
    step = {'id': name, 'label': label, 'kind': kind, 'status': status,
            'attempts': 0 if status == 'to-do' else 1, 'seconds': None, 'dollars': None,
            'error': None, **more}
    assert set(step) == STEP_FIELDS, step
    return step


def a_run(state: str, sentence: str, **more) -> dict:
    run = {'state': state, 'sentence': sentence, 'agent': 'claude', 'model': None,
           'steps': [], 'workers': [], 'spent': {'dollars': None, 'tokens': None},
           'question': None, 'problem': None, 'documents': None, 'copies': [], 'deck': None,
           'finished': None, **more}
    assert set(run) == RUN_FIELDS, run
    return ok(run)


def supplied(*added: dict, waiting: bool = True, files: int = 40) -> dict:
    """What a run says about the documents a person supplies."""
    for entry in added:
        assert set(entry) == DOCUMENT_FIELDS, entry
    return {'waiting': waiting, 'added': list(added), 'types': TYPES,
            'limits': {'bytes': 8_000_000, 'files': files}, 'note': NO_PDF}


def a_document(name: str, size: int, problem: str | None = None) -> dict:
    return {'name': name, 'bytes': size, 'readable': problem is None, 'problem': problem}


def a_copy(artifact: str, label: str, kind: str, state: str, link: str | None = None,
           problem: str | None = None) -> dict:
    copy = {'artifact': artifact, 'label': label, 'kind': kind, 'state': state, 'link': link,
            'problem': problem}
    assert set(copy) == COPY_FIELDS, copy
    return copy


def steps(*statuses: str) -> list:
    """The steps of a training up to its blueprint, each where `statuses` puts it."""
    named = (('intake', 'Your answers', 'code'),
             ('research-plan', 'Draft the research questions', 'agent'),
             ('gate:research-plan', 'Your review of the research questions', 'gate'),
             ('research', 'Do the research', 'agent'),
             ('gate:research', 'Your review of the research', 'gate'),
             ('blueprint', 'Draft the blueprint', 'agent'),
             ('gate:blueprint', 'Your review of the blueprint', 'gate'))
    return [a_step(name, label, kind, status)
            for (name, label, kind), status in zip(named, statuses + ('to-do',) * 7)]


@unittest.skipUnless(NODE, 'Node is needed to run the page scripts without a browser')
class RunnerScreenTests(ScriptedPage, PageCase):
    """What the runner adds to the page: set-up, a new training, a run, and running work in
    every list. Each screen is driven through its own controls."""

    def answers(self, setup=SET_UP, **more) -> dict:
        return {'GET /api/capabilities': [RUNNER], 'GET /api/setup': [ok(setup)],
                'GET /api/trainings': [self.read('trainings')],
                'GET /api/computer': [self.read('computer')],
                'GET /api/agents': [ok(AGENTS_FOUND)], **more}

    def posts(self, result: dict) -> list:
        """Every change the page asked for, each sent as milestone 1 says a change is."""
        made = [request for request in result['requests'] if request['method'] == 'POST']
        for post in made:
            self.assertEqual(post['headers'], {desk.TOKEN_HEADER: 'the-test-key',
                                               'Content-Type': 'application/json'})
        return [(post['address'], post['body']) for post in made]

    def asked(self, result: dict, endpoint: str) -> list:
        return [request['address'] for request in result['requests']
                if request['address'].split('?')[0] == f'/api/{endpoint}']

    def started(self, *init) -> None:
        """A training as the runner leaves it once the form is in: its start approved."""
        self.cli('init', '--title', 'Rolling restarts', *init)
        self.make('intake', 'intake.md', '# Intake\n\n## Topic\nRolling restarts\n')
        self.cli('checkpoint', '--approval', 'page', '--stage', 'research-plan',
                 '--next', 'Draft the research questions')

    def at_the_questions_gate(self) -> None:
        self.write('.training-studio/research-plan.json', json.dumps(helpers.PLAN))
        self.cli('save', 'research-plan', '--built')
        self.cli('checkpoint', '--gate', 'research-plan', '--stage', 'research-plan',
                 '--question', 'Are these the right questions?')

    def listed(self, state: str | None, sentence: str = '', needs: bool = False) -> dict:
        """The list as the runner gives it: every item has `run`, and this training's is
        `state`. `needs` is what the runner does when a run has a question or a problem."""
        found = self.read('trainings')
        for item in found['body']['trainings']:
            item['run'] = None
            if item['path'] == str(self.root) and state:
                item['run'] = {'state': state, 'sentence': sentence}
                if needs and item['state'] != 'needs-you':
                    item['state'] = 'needs-you'
                    found['body']['needs'] += 1
        return found

    def detail(self, state: str, sentence: str) -> dict:
        found = self.read('training', path=str(self.root))
        found['body']['run'] = {'state': state, 'sentence': sentence}
        return found

    def test_set_up_comes_first_and_each_answer_is_checked_as_it_is_given(self):
        first, second = 'git@example.com:team/enablement.git', 'git@example.com:team/tools.git'
        passed = [{'what': 'The repository can be reached', 'ok': True, 'fix': None},
                  {'what': 'You can write to it', 'ok': True, 'fix': None},
                  {'what': 'Git knows who you are', 'ok': True, 'fix': None}]
        refused = {'ok': False, 'checks': [passed[0], {
            'what': 'You can write to it', 'ok': False,
            'fix': 'Ask its owner for write access, then check again.'}, passed[2]],
            'found': {'name': 'enablement', 'folder': 'trainings', 'branch': 'main',
                      'existing': False}}
        found = {'ok': True, 'checks': passed,
                 'found': {'name': 'Field enablement', 'folder': 'tools/trainings',
                           'branch': 'trainings', 'existing': True}}
        saved = {'configured': True, 'agent': {'default': 'codex', 'model': 'gpt-5'},
                 'limits': {'step_seconds': 600, 'training_dollars': 15, 'parallel': 1},
                 'workspace': {**WORKSPACE, 'folder': 'tools/trainings', 'branch': 'trainings',
                               'share_when': 'when-asked', 'shared': False}}
        answers = self.answers(**{'GET /api/setup': [ok(NOT_SET_UP), ok(saved)],
                                  'POST /api/setup/check': [ok(refused), ok(found)],
                                  'POST /api/setup': [ok(saved)]})
        address, parallel = 'The repository’s address', 'How many trainings may run at once'
        result = self.run_page(answers, [
            {'snapshot': 'first'},
            {'click': 'Save and go on'}, {'snapshot': 'empty'},
            {'fill': address, 'value': first}, {'snapshot': 'failed'},
            {'click': 'Save and go on'}, {'snapshot': 'not yet'},
            {'fill': address, 'value': second}, {'snapshot': 'found'},
            {'click': 'Only when I ask'}, {'click': 'Codex'},
            {'fill': 'Its model', 'value': ' gpt-5 '},
            {'fill': 'The longest a step may take', 'value': '10'},
            {'fill': 'The most a training may spend', 'value': '15'},
            {'fill': parallel, 'value': '0'},
            {'click': 'Save and go on'}, {'snapshot': 'limit'},
            {'fill': parallel, 'value': '1'},
            {'click': 'Save and go on'}, {'snapshot': 'saved'},
        ])
        shots = result['snapshots']

        # Until the workspace is set, set-up is the only screen and there is no way off it.
        start = shots['first']
        self.assertEqual((start['heading'], start['title'], start['sidebar']),
                         ('Set up Training Studio', 'Set-up · Training Studio', False))
        self.assertEqual(start['filled'], ['Save and go on'])
        for absent in ('Home', 'Trainings', 'Status', 'Settings', 'Back', 'New training'):
            self.assertNotIn(absent, start['buttons'])
        for shown in ('Welcome.', 'nothing is changed until you save',
                      'Then you can start your first training.',
                      'It is checked as soon as you give the address.',
                      'After each decision: your team sees the drafts',
                      'Only when I ask: everything stays on this computer',
                      'Claude Code', 'Installed: 2.1.0', 'Signed in: cannot be asked', 'Codex',
                      'Needs attention', 'Signed in: no',
                      'Codex is not signed in. Run codex login in a terminal'):
            self.assertIn(shown, start['text'])
        self.assertEqual(start['pressed'], ['A team repository', 'After each decision',
                                            'Claude Code'])
        self.assertEqual(start['fields'], {
            address: '', 'The folder inside it': '', 'The branch': '',
            'A name for this workspace': '', 'Its model (optional)': '',
            'The longest a step may take, in minutes': '15',
            'The most a training may spend, in dollars': '20', parallel: '2'})
        self.assertEqual(self.asked(result, 'capabilities'), ['/api/capabilities'])

        # Nothing to save yet: refused beside the box, and nothing is sent.
        empty = shots['empty']
        self.assertEqual((empty['invalid'], empty['focus'], empty['posts']),
                         ([address], 'setup-repository', 0))
        self.assertIn('Give the repository’s address first.', empty['text'])
        self.assertIn('Nothing was saved.', empty['text'])

        # A check that fails says which, in plain words, with how to put it right.
        failed = shots['failed']
        for shown in ('The repository can be reached: yes', 'You can write to it: no',
                      'Ask its owner for write access, then check again.',
                      '1 thing needs putting right before this can be saved.'):
            self.assertIn(shown, failed['text'])
        self.assertEqual((failed['fields']['The folder inside it'], failed['fields']['The branch'],
                          failed['fields']['A name for this workspace'], failed['locked']),
                         ('trainings', 'main', 'enablement', []))
        self.assertNotIn('already set up', failed['text'])
        self.assertIn('needs putting right first', shots['not yet']['text'])
        self.assertEqual(shots['not yet']['posts'], 1)

        # The team's own hub.json is found: the page says so and takes its folder and branch.
        here = shots['found']
        self.assertIn('Training Studio is already set up in this repository, as “Field '
                      'enablement”.', here['text'])
        self.assertIn('This is ready to use.', here['text'])
        self.assertEqual((here['fields']['The folder inside it'], here['fields']['The branch'],
                          here['fields']['A name for this workspace']),
                         ('tools/trainings', 'trainings', 'Field enablement'))
        self.assertEqual(here['locked'], ['The folder inside it', 'The branch',
                                          'A name for this workspace'])

        # A limit that cannot be used is refused beside its box.
        self.assertEqual(shots['limit']['invalid'], [parallel])
        self.assertIn('Give a whole number, 1 or more.', shots['limit']['text'])

        nothing = {'path': None, 'folder': None, 'branch': None}
        self.assertEqual(self.posts(result), [
            ('/api/setup/check', {'repository': first, **nothing}),
            ('/api/setup/check', {'repository': second, **nothing}),
            ('/api/setup', {'repository': second, 'folder': 'tools/trainings',
                            'branch': 'trainings', 'name': 'Field enablement',
                            'share_when': 'when-asked', 'agent': 'codex', 'model': 'gpt-5',
                            'limits': {'step_seconds': 600, 'training_dollars': 15,
                                       'parallel': 1}})])

        # Then "Start your first training", and the rest of the page is there.
        done = shots['saved']
        self.assertEqual((done['heading'], done['sidebar'], done['filled']),
                         ('Home', True, ['New training']))
        self.assertIn('Start your first training', done['text'])
        self.assertIn('You are set up. Now start your first training.', done['toasts'])
        self.assertIn('Trainings', done['buttons'])

    def test_set_up_is_reached_from_settings_and_the_work_is_shared_when_asked(self):
        notice = 'The repository could not be reached when you last decided.'
        behind = {**SET_UP, 'workspace': {**WORKSPACE, 'shared': False, 'notice': notice}}
        dearer = {**SET_UP, 'limits': {**LIMITS, 'training_dollars': 30}}
        check = {'ok': True, 'found': {'name': 'Field enablement', 'folder': 'trainings',
                                       'branch': 'main', 'existing': True},
                 'checks': [{'what': 'The repository can be reached', 'ok': True, 'fix': None}]}
        answers = self.answers(behind, **{
            'POST /api/share': [ok({'shared': True, 'notice': None})],
            'POST /api/setup/check': [ok(check)], 'POST /api/setup': [ok(dearer)]})
        result = self.run_page(answers, [
            {'snapshot': 'home'},
            {'click': 'Settings'}, {'snapshot': 'settings'},
            {'click': 'Share now'}, {'snapshot': 'shared'},
            {'click': 'Change the set-up'}, {'snapshot': 'set-up'},
            {'fill': 'The most a training may spend', 'value': '30'},
            {'click': 'Save'}, {'snapshot': 'saved'},
        ])
        shots = result['snapshots']
        said = f'Not shared with your team yet. {notice} The work is kept on this computer'
        self.assertIn(said, shots['home']['text'])
        self.assertIn('Share now', shots['home']['buttons'])

        settings = shots['settings']
        for shown in ('Workspace', 'Field enablement', 'git@example.com:team/tools.git',
                      '/Users/pat/Library/Training Studio/workspace', 'trainings', 'main',
                      'after each decision: your team sees the drafts', said,
                      'Claude Code, with the model it chooses itself',
                      'A step may take up to 15 minutes.',
                      'A training stops and asks you once it has spent $20.00.',
                      'Up to 2 trainings run at once.'):
            self.assertIn(shown, settings['text'])
        self.assertEqual(settings['heading'], 'Settings')

        shared = shots['shared']
        self.assertIn('Shared: your team can see everything decided so far.', shared['text'])
        self.assertNotIn('Share now', shared['buttons'])
        self.assertIn('Shared. Your team can see it now.', shared['toasts'])
        self.assertEqual(shared['focus'], 'title')

        again = shots['set-up']
        self.assertEqual((again['heading'], again['current'], again['sidebar']),
                         ('Set-up', ['Settings'], True))
        self.assertEqual((again['filled'], again['buttons'].count('Back')), (['Save'], 1))
        self.assertEqual(again['fields']['The repository’s address'],
                         'git@example.com:team/tools.git')
        self.assertEqual(again['pressed'], ['A team repository', 'After each decision',
                                            'Claude Code'])
        self.assertIn('Training Studio is already set up in this repository', again['text'])

        self.assertEqual(self.posts(result), [
            ('/api/share', {}),
            ('/api/setup/check', {'repository': 'git@example.com:team/tools.git', 'path': None,
                                  'folder': 'trainings', 'branch': 'main'}),
            ('/api/setup', {'repository': 'git@example.com:team/tools.git',
                            'folder': 'trainings', 'branch': 'main',
                            'name': 'Field enablement', 'share_when': 'each-decision',
                            'agent': 'claude', 'model': None,
                            'limits': {'step_seconds': 900, 'training_dollars': 30,
                                       'parallel': 2}})])
        saved = shots['saved']
        self.assertEqual((saved['heading'], saved['current']), ('Settings', ['Settings']))
        self.assertIn('The set-up is saved.', saved['toasts'])
        self.assertIn('once it has spent $30.00', saved['text'])

    def test_a_folder_on_this_computer_is_set_up_without_anyone_to_share_with(self):
        check = {'ok': True, 'found': {'name': 'try-out', 'folder': 'trainings',
                                       'branch': 'main', 'existing': False},
                 'checks': [{'what': 'The folder can be written to', 'ok': True, 'fix': None}]}
        local = {**SET_UP, 'workspace': {**WORKSPACE, 'repository': None, 'name': 'try-out',
                                         'path': '/Users/pat/try-out', 'shared': False}}
        answers = self.answers(NOT_SET_UP, **{
            'GET /api/setup': [ok(NOT_SET_UP), ok(local)],
            'POST /api/setup/check': [ok(check)], 'POST /api/setup': [ok(local)]})
        result = self.run_page(answers, [
            {'click': 'A folder on this computer'}, {'snapshot': 'local'},
            {'fill': 'The folder', 'value': '/Users/pat/try-out'},
            {'fill': 'The folder inside it', 'value': 'courses'}, {'snapshot': 'checked'},
            {'click': 'Save and go on'}, {'snapshot': 'saved'},
        ])
        shots = result['snapshots']
        self.assertEqual(shots['local']['pressed'], ['A folder on this computer',
                                                     'Claude Code'])
        self.assertEqual(shots['local']['focus'], 'A folder on this computer')
        self.assertNotIn('When your team sees the work', shots['local']['text'])
        self.assertIn('It is checked as soon as you say which folder.', shots['local']['text'])
        self.assertEqual(shots['checked']['fields']['The folder inside it'], 'courses')
        place = {'repository': None, 'path': '/Users/pat/try-out', 'branch': None}
        self.assertEqual(self.posts(result), [
            ('/api/setup/check', {**place, 'folder': None}),
            ('/api/setup/check', {**place, 'folder': 'courses'}),
            ('/api/setup', {'path': '/Users/pat/try-out', 'folder': 'courses', 'branch': 'main',
                            'name': 'try-out', 'share_when': 'when-asked', 'agent': 'claude',
                            'model': None, 'limits': LIMITS})])
        self.assertIn('Your trainings are kept in a folder on this computer, and are not '
                      'shared with anyone.', shots['saved']['text'])
        self.assertNotIn('Share now', shots['saved']['buttons'])

    def test_a_name_that_cannot_be_used_is_refused_beside_its_box_before_it_is_sent(self):
        address, name = 'git@example.com:team/enablement.git', 'A name for this workspace'
        check = {'ok': True, 'found': {'name': 'enablement', 'folder': 'trainings',
                                       'branch': 'main', 'existing': False},
                 'checks': [{'what': 'The repository can be reached', 'ok': True,
                             'fix': None}]}
        saved = {**SET_UP, 'workspace': {**WORKSPACE, 'name': 'field-training'}}
        answers = self.answers(NOT_SET_UP, **{
            'GET /api/setup': [ok(NOT_SET_UP), ok(saved)],
            'POST /api/setup/check': [ok(check)], 'POST /api/setup': [ok(saved)]})
        result = self.run_page(answers, [
            {'fill': 'The repository’s address', 'value': address}, {'snapshot': 'checked'},
            {'fill': name, 'value': 'Field training'},
            {'click': 'Save and go on'}, {'snapshot': 'refused'},
            {'fill': name, 'value': 'field-training'}, {'snapshot': 'put right'},
            {'click': 'Save and go on'}, {'snapshot': 'saved'},
        ])
        shots = result['snapshots']
        # A box that is being put right no longer says it is wrong.
        self.assertEqual(shots['put right']['invalid'], [])
        self.assertNotIn('with no spaces, starting', shots['put right']['text'])

        # The rule is said before anyone breaks it.
        self.assertIn('a short name with no spaces, such as field-training',
                      shots['checked']['text'])
        refused = shots['refused']
        self.assertEqual((refused['invalid'], refused['focus']), ([name], 'setup-name'))
        self.assertIn('with no spaces', refused['text'])
        self.assertIn('Nothing was saved.', refused['text'])
        self.assertEqual([address for address, _ in self.posts(result)],
                         ['/api/setup/check', '/api/setup'])
        self.assertEqual(self.posts(result)[1][1]['name'], 'field-training')
        self.assertEqual(shots['saved']['heading'], 'Home')

    def test_a_new_training_takes_three_steps_and_lands_on_its_run(self):
        self.started('--levels', '101,301')
        sentence = 'Drafting the research questions.'
        working = a_run('working', sentence, steps=steps('done', 'working'),
                        workers=[{'id': 'w1', 'label': 'The research questions',
                                  'started_at': '2030-01-02T03:04:05Z',
                                  'lines': ['Read your answers', 'Drafting question 4']}])
        answers = self.answers(**{
            'GET /api/trainings': [ok({'trainings': [], 'needs': 0}),
                                   self.listed('working', sentence)],
            'POST /api/trainings': [ok({'path': str(self.root), 'id': 'rolling-restarts',
                                        'gates': 8})],
            'GET /api/run': [working], 'GET /api/training': [self.detail('working', sentence)]})
        result = self.run_page(answers, [
            {'snapshot': 'home'},
            {'click': 'New training'}, {'snapshot': 'one'},
            {'click': 'Continue'}, {'snapshot': 'missing'},
            {'fill': 'A short title', 'value': 'Rolling restarts'},
            {'fill': 'What should it teach?', 'value': 'How a rolling restart works.'},
            {'fill': 'Who is it for?', 'value': 'Platform engineers new to it.'},
            {'click': 'Technical upskilling'},
            {'click': 'Continue'}, {'snapshot': 'two'},
            {'click': '301'}, {'click': 'A comparison'}, {'click': 'Google Slides'},
            {'fill': 'A brand for the deck', 'value': 'Example Co'}, {'click': 'Google Docs'},
            {'fill': 'How long it should take', 'value': '30 minutes'},
            {'click': 'Continue'}, {'snapshot': 'three'},
            {'click': 'Back a step'}, {'snapshot': 'kept'},
            {'click': 'Continue'}, {'click': 'Start the training'}, {'snapshot': 'run'},
        ])
        shots = result['snapshots']
        self.assertEqual(shots['home']['filled'], ['New training'])
        self.assertIn('Start your first training', shots['home']['text'])

        one = shots['one']
        self.assertEqual((one['heading'], one['title'], one['filled'], one['current']),
                         ('The topic and who it is for', 'New training · Training Studio',
                          ['Continue'], ['Trainings']))
        self.assertIn('New training · Step 1 of 3', one['text'])
        self.assertEqual(one['pressed'], ['Field enablement'])
        missing = shots['missing']
        self.assertEqual(missing['invalid'], ['A short title', 'What should it teach?',
                                              'Who is it for?'])
        self.assertEqual((missing['focus'], missing['posts'], missing['heading']),
                         ('new-title', 0, 'The topic and who it is for'))
        self.assertIn('Give it a title first.', missing['text'])

        # Every choice about its shape has an answer already.
        two = shots['two']
        self.assertEqual((two['heading'], two['focus']), ('Its shape', 'title'))
        self.assertIn('New training · Step 2 of 3', two['text'])
        self.assertEqual((two['chosen'], two['pressed']),
                         (['101'], ['One product or technology', 'PowerPoint']))
        self.assertEqual(two['fields'], {'How long it should take (optional)': '',
                                         'A brand for the deck (optional)': ''})

        # Before it starts: how many times it will ask, and what it may spend.
        three = shots['three']
        self.assertEqual((three['heading'], three['filled']),
                         ('The sources, the agent and the limits', ['Start the training']))
        for shown in ('The public web: it searches for pages anyone can read', 'Claude Code',
                      'A step may take up to 15 minutes.',
                      'It starts at once and works on its own. It stops and asks for your '
                      'decision at least 8 times: at the research questions, at the research, '
                      'and at the blueprint, the learner guide and the brief of each of the 2 '
                      'levels.',
                      'It asks once more for each practice scenario. How many there are is not '
                      'known until a blueprint names them.',
                      'In between, you can close it.'):
            self.assertIn(shown, three['text'])
        self.assertNotIn('not offered yet', three['text'])
        self.assertEqual((three['pressed'], three['posts']),
                         (['The public web', 'Claude Code'], 0))
        self.assertEqual(self.asked(result, 'agents'), ['/api/agents'] * 2)

        # Going back a step loses nothing.
        kept = shots['kept']
        self.assertEqual((kept['chosen'], kept['pressed']),
                         (['101', '301', 'Google Docs'], ['A comparison', 'Google Slides']))
        self.assertEqual(kept['fields'], {'How long it should take (optional)': '30 minutes',
                                          'A brand for the deck (optional)': 'Example Co'})

        self.assertEqual(self.posts(result), [('/api/trainings', {
            'title': 'Rolling restarts', 'topic': 'How a rolling restart works.',
            'audience': 'Platform engineers new to it.', 'purpose': 'Technical upskilling',
            'levels': ['101', '301'], 'brief_kind': 'competitive', 'time_limit': '30 minutes',
            'source_scope': 'public-web', 'deck_target': 'google', 'brand': 'Example Co',
            'copies': ['google'], 'yoodli': False, 'agent': 'claude', 'model': None})])

        run = shots['run']
        self.assertEqual((run['heading'], run['title']),
                         ('Rolling restarts', 'Rolling restarts · Training Studio'))
        self.assertIn(sentence, run['text'])
        self.assertIn('In all, it stops and asks for your decision at least 8 times.',
                      run['text'])
        self.assertIn('Started. It is working on its own now.', run['toasts'])
        # Nothing reported yet is not the same as an agent that never says.
        self.assertIn('Nothing has been reported yet.', run['text'])
        self.assertIn('It stops and asks you at $20.00.', run['text'])
        self.assertNotIn('not what they cost', run['text'])
        # Read once on arriving, and once more with the list that now holds it.
        self.assertEqual(self.asked(result, 'run'),
                         [f'/api/run?{urlencode({"path": self.root})}'] * 2)

    def test_a_run_is_watched_from_working_to_a_gate_to_a_failure_to_done(self):
        self.started()
        going = 'Drafting the research questions.'
        asking = 'Waiting for your decision on the research questions.'
        broke, later = 'The research stopped after three tries.', 'Doing the research again.'
        over = ('The blueprint is approved. The later stages are not automated yet: carry on '
                'with your assistant.')
        working = a_run('working', going, steps=steps('done', 'working'), workers=[
            {'id': 'w1', 'label': 'The research questions', 'started_at': '2030-01-02T03:04:05Z',
             'lines': ['Read your answers', 'Listed what to ask', 'Drafting question 4']}],
            spent={'dollars': 0.4, 'tokens': 18200})
        waiting = a_run('waiting', asking, steps=steps('done', 'done', 'waiting'),
                        spent={'dollars': 0.62, 'tokens': 30100})
        failed = a_run('failed', broke, spent={'dollars': 1.9, 'tokens': 81000}, steps=[
            *steps('done', 'done', 'done')[:3],
            a_step('research', 'Do the research', 'agent', 'failed', attempts=3, seconds=754,
                   dollars=1.28, error='The agent could not be reached.'),
            *steps()[4:]], problem={
                'what': 'The research was tried three times and the agent could not be reached.',
                'kept': 'Your answers and the approved research questions.',
                'action': 'retry', 'label': 'Try the research again'})
        again = a_run('working', later, steps=steps('done', 'done', 'done', 'working'),
                      spent={'dollars': 1.9, 'tokens': 81000})
        done = a_run('done', over, steps=steps(*['done'] * 7),
                     spent={'dollars': 3.25, 'tokens': 140000})

        lists = [self.listed('working', going)]
        details = [self.detail('working', going)]
        self.at_the_questions_gate()
        lists.append(self.listed('waiting', asking))
        details.append(self.detail('waiting', asking))
        # The questions are approved on the page, as the person would, and the run goes on.
        self.decide('approve', 'research-plan', seen=self.gate('research-plan')['sha256'])
        lists += [self.listed('failed', broke, needs=True), self.listed('working', later),
                  self.listed('done', over)]
        details += [self.detail('failed', broke), self.detail('working', later),
                    self.detail('done', over)]
        answers = self.answers(**{
            'GET /api/trainings': lists, 'GET /api/training': details,
            # The list is read first, then what a run that needs its person asks, then the run.
            'GET /api/run': [working, waiting, waiting, failed, failed, again, done],
            'POST /api/run': [again]})
        result = self.run_page(answers, [
            {'snapshot': 'home'},
            {'click': 'Open Rolling restarts'}, {'snapshot': 'working'},
            {'click': 'What it did just before'},
            {'poll': True}, {'snapshot': 'waiting'},
            {'poll': True}, {'snapshot': 'failed'},
            {'click': 'Try the research again'}, {'snapshot': 'again'},
            {'poll': True}, {'snapshot': 'done'},
        ], notifications='granted')
        shots = result['snapshots']

        # Home says what the run is doing now, and the row shimmers because the run says so.
        home = shots['home']
        self.assertIn(going, home['text'])
        self.assertEqual((home['working'], home['filled']), (1, ['New training']))

        run = shots['working']
        self.assertEqual((run['heading'], run['current'], run['filled']),
                         ('Rolling restarts', ['Trainings'], []))
        for shown in ('Runs on this page', 'Working on its own', going,
                      'Nothing is needed from you right now.',
                      'Next it asks for your decision on the research questions.',
                      'Steps', 'Your answers', 'Draft the research questions', 'Working',
                      'To do', 'Your decision', 'Working now', 'Drafting question 4',
                      'Made so far', 'What it has cost', '$0.40', 'So far.',
                      'It stops and asks you at $20.00.', 'Drafted by Claude Code.'):
            self.assertIn(shown, run['text'])
        self.assertRegex(run['text'], r'18[,.  ]?200 tokens used\.')
        self.assertLess(run['text'].index('Draft the research questions'),
                        run['text'].index('Working now'))
        # What a worker did before is there to open, and not in the way.
        self.assertNotIn('Listed what to ask', run['text'].split('What it did just before')[0])
        self.assertEqual(run['buttons'][4:8], ['Back', 'Pause', 'Stop',
                                               'What it did just before'])
        self.assertEqual((run['working'], run['pace']), (1, 2000))
        self.assertEqual(set(run['beads']) - {'done', 'current', 'none'}, set())

        # At a gate, the one filled button opens it.
        gate = shots['waiting']
        self.assertEqual((gate['filled'], gate['title'], gate['working'], gate['pace']),
                         (['Review the research plan'],
                          '(1) Rolling restarts · Training Studio', 0, 5000))
        for shown in ('Waiting for you', asking,
                      'The research plan is waiting for your review.',
                      'Training Studio asks: Are these the right questions?', '$0.62'):
            self.assertIn(shown, gate['text'])
        self.assertNotIn('Pause', gate['buttons'])
        self.assertNotIn('Working now', gate['text'])
        self.assertIn('Review the research plan', gate['buttons'])
        said = f'Rolling restarts: The research plan is waiting for your review.'
        self.assertEqual(result['notifications'][0],
                         {'title': 'Training Studio needs you', 'body': said})

        # A failure says what happened, what was kept, and offers the one action.
        down = shots['failed']
        for shown in ('Stopped: something went wrong', broke, 'It has stopped, and needs you',
                      'What happened: The research was tried three times and the agent could '
                      'not be reached.',
                      'What was kept: Your answers and the approved research questions.',
                      'Failed', '3 tries · 13 minutes · $1.28',
                      'The agent could not be reached.'):
            self.assertIn(shown, down['text'])
        self.assertEqual(down['filled'], ['Try the research again'])
        for absent in ('Pause', 'Stop', 'Resume'):
            self.assertNotIn(absent, down['buttons'])
        self.assertIn('late', down['beads'])

        self.assertEqual(self.posts(result), [('/api/run', {'path': str(self.root),
                                                            'action': 'retry'})])
        retried = shots['again']
        self.assertIn(later, retried['text'])
        self.assertIn('Trying again.', retried['toasts'])
        self.assertNotIn('What happened', retried['text'])
        self.assertEqual((retried['filled'], retried['focus']), ([], 'title'))

        end = shots['done']
        for shown in ('Finished here', over, '$3.25', 'The research plan'):
            self.assertIn(shown, end['text'])
        self.assertEqual((end['filled'], end['working']), ([], 0))
        for absent in ('Pause', 'Stop', 'Resume'):
            self.assertNotIn(absent, end['buttons'])
        self.assertIn('Open the research plan', end['buttons'])

    def test_a_decision_at_a_gate_offers_the_way_back_to_the_run(self):
        self.started()
        self.at_the_questions_gate()
        asking, going = 'Waiting for your decision on the research questions.', 'Researching.'
        gate = {'path': str(self.root), 'artifact': 'research-plan'}
        lists, gates = [self.listed('waiting', asking)], [self.read('gate', **gate)]
        decided = self.captured('POST', '/api/decide', {
            **gate, 'decision': 'approve', 'seen': gates[0]['body']['sha256']})
        answers = self.answers(**{
            'GET /api/trainings': [*lists, self.listed('working', going)],
            'GET /api/gate': [*gates, self.read('gate', **gate)],
            'GET /api/training': [self.detail('working', going)],
            'POST /api/decide': [decided],
            'GET /api/run': [a_run('waiting', asking, steps=steps('done', 'done', 'waiting')),
                             a_run('working', going,
                                   steps=steps('done', 'done', 'done', 'working'))]})
        result = self.run_page(answers, [
            {'snapshot': 'home'},
            {'click': 'Review the research plan'}, {'snapshot': 'gate'},
            {'click': 'Ask for changes'}, {'snapshot': 'asking'}, {'click': 'Cancel'},
            {'click': 'Approve'}, {'click': 'Approve'}, {'snapshot': 'decided'},
            {'click': 'Watch it carry on'}, {'snapshot': 'run'},
        ])
        shots = result['snapshots']
        # The runner drives this training, so nobody is told an assistant makes the change.
        self.assertIn('Training Studio makes the change and brings it back here.',
                      shots['asking']['sheet'])
        self.assertNotIn('assistant', shots['asking']['sheet'])
        # A gate comes before a new training: it is the one filled button on home.
        self.assertEqual(shots['home']['filled'], ['Review the research plan'])
        self.assertIn('New training', shots['home']['buttons'])
        self.assertIn('Training Studio asks: Are these the right questions?',
                      shots['gate']['text'])
        self.assertEqual(shots['gate']['buttons'][5], 'Rolling restarts')
        self.assertIn('Approved.', shots['decided']['sheet'])
        self.assertIn('Watch it carry on', shots['decided']['buttons'])
        self.assertEqual(len(shots['decided']['filled']), 1)
        self.assertEqual(self.posts(result), [('/api/decide', {
            **gate, 'decision': 'approve', 'seen': gates[0]['body']['sha256']})])
        run = shots['run']
        self.assertEqual((run['heading'], run['filled']), ('Rolling restarts', []))
        self.assertIn(going, run['text'])
        self.assertIn('Pause', run['buttons'])

    def test_a_waiting_run_says_what_waits_once_and_sends_nobody_to_an_assistant(self):
        self.started()
        self.at_the_questions_gate()
        waiting = 'The research plan is waiting for your review.'
        answers = self.answers(**{
            'GET /api/trainings': [self.listed('waiting', waiting)],
            'GET /api/training': [self.detail('waiting', waiting)],
            'GET /api/run': [a_run('waiting', waiting, steps=steps('done', 'done', 'waiting'))]})
        result = self.run_page(answers, [
            {'click': 'Trainings'}, {'click': 'Open Rolling restarts'}, {'snapshot': 'run'},
            {'click': 'Everything about this training'}, {'snapshot': 'detail'},
        ])
        shots = result['snapshots']
        # The run and the training say the same sentence, so it is shown once.
        self.assertEqual(shots['run']['text'].count(waiting), 1)
        self.assertIn('Training Studio asks: Are these the right questions?',
                      shots['run']['text'])
        # One driver for a training: while the page runs it, nobody is sent to an assistant.
        self.assertIn('Watch the run', shots['detail']['buttons'])
        self.assertNotIn('Carry on with your assistant', shots['detail']['text'])
        self.assertNotIn('Start your assistant in this folder', shots['detail']['text'])

    def test_a_run_is_paused_resumed_and_stopped_and_a_refusal_changes_nothing(self):
        self.started()
        going, held = 'Doing the research.', 'Paused at the research.'
        ended = 'Stopped at the research.'
        working = a_run('working', going, steps=steps('done', 'done', 'done', 'working'))
        paused = a_run('paused', held, steps=steps('done', 'done', 'done', 'to-do'),
                       agent='codex', spent={'dollars': None, 'tokens': 5200})
        stopped = a_run('stopped', ended, steps=steps('done', 'done', 'done', 'to-do'))
        refusal = {'status': 409, 'body': {'error': 'It is in the middle of saving a step.'}}
        answers = self.answers(**{
            'GET /api/trainings': [self.listed('working', going)],
            'GET /api/training': [self.detail('working', going)],
            'GET /api/run': [working, paused, working, working, stopped],
            'POST /api/run': [paused, working, refusal, stopped]})
        result = self.run_page(answers, [
            {'click': 'Open Rolling restarts'},
            {'click': 'Pause'}, {'snapshot': 'paused'},
            {'click': 'Resume'}, {'snapshot': 'resumed'},
            {'click': 'Stop'}, {'snapshot': 'refused'},
            {'click': 'Stop'}, {'snapshot': 'stopped'},
        ])
        shots = result['snapshots']
        self.assertEqual(self.posts(result), [
            ('/api/run', {'path': str(self.root), 'action': action})
            for action in ('pause', 'resume', 'stop', 'stop')])
        paused_shot = shots['paused']
        # The control that was pressed is gone; the focus is on the one that undoes it.
        self.assertEqual((paused_shot['filled'], paused_shot['focus']), (['Resume'], 'Resume'))
        for shown in ('Paused', held, 'Nothing more is started until you resume it. '
                      'Everything made so far is kept.'):
            self.assertIn(shown, paused_shot['text'])
        self.assertIn('Stop', paused_shot['buttons'])
        self.assertNotIn('Pause', paused_shot['buttons'])
        # An agent that counts tokens and not dollars: the money limit cannot stop it.
        for shown in ('Codex says how many tokens it uses, not what they cost.',
                      'So the limit of $20.00 cannot stop it: watch the steps instead.'):
            self.assertIn(shown, paused_shot['text'])
        self.assertNotIn('It stops and asks you at', paused_shot['text'])
        self.assertIn('Carrying on.', shots['resumed']['toasts'])
        self.assertIn('Pause', shots['resumed']['buttons'])
        self.assertEqual((shots['resumed']['focus'], shots['refused']['focus']),
                         ('Pause', 'Stop'))
        # What was refused is said where it happened, and nothing has changed.
        self.assertIn('It is in the middle of saving a step. Nothing was changed.',
                      shots['refused']['text'])
        self.assertIn('Working on its own', shots['refused']['text'])
        end = shots['stopped']
        self.assertEqual((end['filled'], end['focus']), (['Resume'], 'Resume'))
        for shown in ('Stopped', ended, 'Everything made so far is kept. Resume, and it '
                      'carries on from where it stopped.'):
            self.assertIn(shown, end['text'])
        self.assertNotIn('Nothing was changed.', end['text'])
        self.assertNotIn('Stop', end['buttons'])

    def test_a_question_from_a_worker_is_answered_on_home_or_on_the_run(self):
        self.started()
        other = self.another('second')
        asking, going = 'Waiting for your answer.', 'Doing the research.'
        question = {'id': 'q-7', 'from': 'The worker on question 3',
                    'text': 'Two versions differ here.\nWhich one do your learners use?'}
        blocked = a_run('waiting', asking, steps=steps('done', 'done', 'done', 'waiting'),
                        question=question)
        carried = a_run('working', going, steps=steps('done', 'done', 'done', 'working'))
        needing = self.listed('waiting', asking, needs=True)
        moved = self.listed('waiting', asking, needs=True)
        moved['body']['trainings'][-1]['sentence'] = 'Something else changed.'
        answers = self.answers(**{
            'GET /api/trainings': [needing, moved, self.listed('working', going)],
            'GET /api/training': [self.detail('waiting', asking)],
            'GET /api/run': [blocked, blocked, carried], 'POST /api/answer': [carried]})
        box = 'Your answer for Rolling restarts'
        result = self.run_page(answers, [
            {'snapshot': 'home'},
            {'click': 'Send answer for Rolling restarts'}, {'snapshot': 'empty'},
            {'fill': box, 'value': 'The newer one', 'stay': True},
            {'poll': True}, {'snapshot': 'typing'},
            {'fill': box, 'value': '  The newer one, 2.4.  '},
            {'click': 'Send answer for Rolling restarts'}, {'snapshot': 'sent'},
        ])
        shots = result['snapshots']
        home = shots['home']
        self.assertEqual((home['title'], home['badge']),
                         ('(1) Training Studio', '1 thing needs you'))
        self.assertLess(home['text'].index('Needs you'), home['text'].index('In progress'))
        for shown in ('The worker on question 3 asks:', 'Two versions differ here.',
                      'Which one do your learners use?', 'Your answer'):
            self.assertIn(shown, home['text'])
        self.assertEqual((home['fields'], home['filled']), ({box: ''}, ['Open Rolling restarts']))
        self.assertEqual((shots['empty']['invalid'], shots['empty']['posts']), ([box], 0))
        self.assertIn('Write your answer first.', shots['empty']['text'])
        # The list changed while an answer was being written, and the box was left alone.
        typing = shots['typing']
        self.assertEqual((typing['fields'], typing['focus']), ({box: 'The newer one'},
                                                               'answer-0'))
        self.assertNotIn('Something else changed.', typing['text'])
        self.assertEqual(self.posts(result), [('/api/answer', {
            'path': str(self.root), 'id': 'q-7', 'answer': 'The newer one, 2.4.'})])
        sent = shots['sent']
        self.assertIn('Your answer is sent. It carries on from here.', sent['toasts'])
        self.assertEqual((sent['fields'], sent['badge']), ({}, ''))
        self.assertIn(going, sent['text'])
        self.assertTrue(str(other))

        # The same question on the run itself, where sending is the one filled button.
        answers = self.answers(**{
            'GET /api/trainings': [needing, self.listed('working', going)],
            'GET /api/training': [self.detail('waiting', asking)],
            'GET /api/run': [blocked, blocked, blocked, carried],
            'POST /api/answer': [carried]})
        result = self.run_page(answers, [
            {'click': 'Open Rolling restarts'}, {'snapshot': 'run'},
            {'fill': box, 'value': 'The newer', 'stay': True},
            {'poll': True}, {'snapshot': 'typing'},
            {'fill': box, 'value': 'The newer one.'},
            {'click': 'Send answer'}, {'snapshot': 'sent'},
        ])
        shots = result['snapshots']
        run = shots['run']
        self.assertEqual((run['filled'], run['heading']),
                         (['Send answer for Rolling restarts'], 'Rolling restarts'))
        self.assertLess(run['text'].index('Needs you'), run['text'].index('Steps'))
        self.assertIn('The worker on question 3 asks:', run['text'])
        self.assertEqual((shots['typing']['fields'], shots['typing']['focus']),
                         ({box: 'The newer'}, 'answer-run'))
        self.assertEqual(self.posts(result), [('/api/answer', {
            'path': str(self.root), 'id': 'q-7', 'answer': 'The newer one.'})])
        self.assertEqual((shots['sent']['fields'], shots['sent']['filled']), ({}, []))
        self.assertIn(going, shots['sent']['text'])

    def test_every_list_shows_running_work_and_guesses_only_where_no_run_is(self):
        self.started()
        by_hand, held = self.another('by hand'), self.another('held')
        found = self.read('trainings')
        runs = {str(self.root): {'state': 'working', 'sentence': 'Doing the research.'},
                str(held): {'state': 'paused', 'sentence': 'Paused at the research.'},
                str(by_hand): None}
        for item in found['body']['trainings']:
            item['run'] = runs[item['path']]
            # Long ago for the one that is working, just now for the two that are not.
            item['touched_at'] = ('2020-01-01T00:00:00Z' if item['path'] == str(self.root)
                                  else item['touched_at'])
        answers = self.answers(**{'GET /api/trainings': [found]})
        result = self.run_page(answers, [
            {'snapshot': 'home'}, {'click': 'Trainings'}, {'snapshot': 'trainings'},
            {'click': 'Status'}, {'snapshot': 'status'},
            {'click': 'Settings'}, {'snapshot': 'settings'},
        ])
        shots = result['snapshots']
        # Two rows shimmer: the run that says it is working, and the one with no run that
        # changed a moment ago. The paused run changed a moment ago too, and is still.
        for name in ('home', 'trainings'):
            with self.subTest(screen=name):
                self.assertEqual(shots[name]['working'], 2)
                for shown in ('Doing the research.', 'Paused', 'Paused at the research.'):
                    self.assertIn(shown, shots[name]['text'])
        self.assertEqual(shots['trainings']['filled'], ['New training'])
        for shown in ('Working on its own', 'Doing the research.', 'Paused',
                      'Paused at the research.', 'In progress'):
            self.assertIn(shown, shots['status']['text'])
        # Where a training is decided is offered only for one that no run drives.
        settings = shots['settings']
        self.assertEqual(settings['pressed'], ['In the conversation'])
        self.assertIn('By Hand', settings['text'].split('Where each training is decided')[1])
        self.assertNotIn('Held', settings['text'].split('Where each training is decided')[1])
        self.assertEqual(self.asked(result, 'run'), [])

    # --- milestone 3: the rest of a training ---------------------------------------------

    def to_the_last_step(self, *shape: dict) -> list:
        """A new training filled in as far as its last step, with `shape` chosen on the way."""
        return [{'click': 'New training'},
                {'fill': 'A short title', 'value': 'Rolling restarts'},
                {'fill': 'What should it teach?', 'value': 'How a rolling restart works.'},
                {'fill': 'Who is it for?', 'value': 'Platform engineers new to it.'},
                {'click': 'Continue'}, *shape, {'click': 'Continue'}]

    def test_each_sources_choice_says_what_it_means_and_is_what_is_sent(self):
        self.started()
        waits, going = 'Waiting for your documents.', 'Drafting the research questions.'
        first = 'First it waits for your documents. You add them on the next screen'
        meanings = (
            'The public web: it searches for pages anyone can read, and keeps every page it '
            'quotes with the training.',
            'Your documents only: it reads the documents you give it and nothing else, and '
            'never searches the web or opens a page. You add them right after starting, and '
            'they stay on this computer.',
            'Both: it reads your documents and researches the public web as well. You add the '
            'documents right after starting, and they stay on this computer.')
        plain = ('at least 5 times: at the research questions, at the research, and at the '
                 'blueprint, the learner guide and the brief.')
        shaped = [{'click': '101'}, {'click': 'No deck'}, {'click': 'Make scenarios for Yoodli'}]
        for choice, scope, shape in ((None, 'public-web', []),
                                     ('Your documents only', 'supplied-only', shaped),
                                     ('Both', 'both', [])):
            with self.subTest(scope):
                web = scope == 'public-web'
                state, says = ('working', going) if web else ('waiting', waits)
                run = a_run(state, says, steps=steps('done', 'working') if web else steps('done'),
                            documents=None if web else supplied())
                answers = self.answers(**{
                    'GET /api/trainings': [ok({'trainings': [], 'needs': 0}),
                                           self.listed(state, says, needs=not web)],
                    'POST /api/trainings': [ok({'path': str(self.root),
                                                'id': 'rolling-restarts', 'gates': 5})],
                    'GET /api/run': [run], 'GET /api/training': [self.detail(state, says)]})
                result = self.run_page(answers, [
                    *self.to_the_last_step(*shape),
                    *([{'click': choice}] if choice else []), {'snapshot': 'three'},
                    {'click': 'Start the training'}, {'snapshot': 'run'}])
                three, landed = result['snapshots']['three'], result['snapshots']['run']
                self.assertEqual(three['pressed'], [choice or 'The public web', 'Claude Code'])
                for said in meanings:
                    self.assertIn(said, three['text'])
                # With documents, the first thing it does is wait for them, and it says so.
                self.assertEqual(first in three['text'], not web)
                self.assertIn('It starts at once and works on its own.' if web
                              else 'Then it works on its own.', three['text'])
                (address, sent), = self.posts(result)
                self.assertEqual((address, sent['source_scope']), ('/api/trainings', scope))
                self.assertIn('Started. It is working on its own now.' if web
                              else 'Started. It waits for your documents first.',
                              landed['toasts'])
                self.assertEqual(landed['filled'], [] if web else ['That is all of them'])
                self.assertEqual('Add your documents' in landed['text'], not web)
                if shape:
                    # No levels, no deck, and Yoodli: each is counted or named as it is sent.
                    self.assertEqual((sent['levels'], sent['deck_target'], sent['yoodli']),
                                     ([], None, True))
                    self.assertIn(plain, three['text'])
                    self.assertIn('It asks once more for each practice scenario, and again '
                                  'for each one laid out for Yoodli.', three['text'])
                    self.assertIn('In all, it stops and asks for your decision at least 5 '
                                  'times.', landed['text'])

    def test_documents_are_added_refused_removed_and_then_that_is_all_of_them(self):
        self.started()
        waits, going = 'Waiting for your documents.', 'Drafting the research questions.'
        notes = a_document('Notes.MD', 8)
        scan = a_document('scan.docx', 4, 'It holds no text that can be read.')

        def asked(*added: dict) -> dict:
            return a_run('waiting', waits, steps=steps('done'), documents=supplied(*added))

        twice = {'status': 409,
                 'body': {'error': 'A document called Notes.MD was already added.'}}
        saving = {'status': 409, 'body': {'error': 'A step is being saved.'}}
        carried = a_run('working', going, steps=steps('done', 'working'),
                        documents=supplied(notes, waiting=False))
        answers = self.answers(**{
            'GET /api/trainings': [self.listed('waiting', waits, needs=True),
                                   self.listed('working', going)],
            'GET /api/training': [self.detail('waiting', waits)],
            # Read once for the list, once on opening the run, and once more when it carries on.
            'GET /api/run': [asked(), asked(), carried],
            'POST /api/documents': [asked(notes), asked(notes, scan), twice, asked(notes),
                                    saving, carried]})
        pick = 'Add documents'
        result = self.run_page(answers, [
            {'snapshot': 'home'},
            {'click': 'Open Rolling restarts'}, {'snapshot': 'empty'},
            {'attach': pick, 'files': [{'name': 'plan.rtf', 'text': 'A plan.'},
                                       {'name': 'big.docx', 'size': 9_000_000}]},
            {'snapshot': 'refused'},
            {'attach': pick, 'files': [{'name': 'Notes.MD', 'text': '# Notes\n'},
                                       {'name': 'scan.docx', 'bytes': [80, 75, 3, 4]}]},
            {'snapshot': 'added'},
            {'attach': pick, 'files': [{'name': 'Notes.MD', 'text': 'Again.'}]},
            {'snapshot': 'twice'},
            {'click': 'Remove scan.docx'}, {'snapshot': 'removed'},
            {'click': 'That is all of them'}, {'snapshot': 'not yet'},
            {'click': 'That is all of them'}, {'snapshot': 'done'},
        ])
        shots = result['snapshots']
        # A run that waits for documents needs its person, and home says what for.
        self.assertIn(waits, shots['home']['text'])
        self.assertEqual(shots['home']['filled'], ['Open Rolling restarts'])

        empty = shots['empty']
        self.assertEqual((empty['heading'], empty['filled'], empty['fields']),
                         ('Rolling restarts', ['That is all of them'], {pick: ''}))
        for shown in ('Waiting for you', waits, 'Add your documents',
                      'Nothing is researched until you have added them and chosen “That is '
                      'all of them”.', KEPT_HERE,
                      'It takes .txt, .md, .html, .htm and .docx files, each up to 8 MB, and '
                      '40 in all. You can choose several at once.', NO_PDF,
                      'Nothing is added yet.'):
            self.assertIn(shown, empty['text'])
        self.assertLess(empty['text'].index('Add your documents'), empty['text'].index('Steps'))
        # Nothing is said about copies where none were asked for.
        self.assertNotIn('Copies', empty['text'])

        # Another type, and one too large: refused beside the control, and nothing is sent.
        refused = shots['refused']
        for shown in ('plan.rtf was not added: only .txt, .md, .html, .htm and .docx files '
                      'are taken.',
                      'big.docx was not added: it is 9 MB, and a document can be at most '
                      '8 MB.', 'Nothing was sent.'):
            self.assertIn(shown, refused['text'])
        self.assertEqual((refused['invalid'], refused['focus'], refused['posts']),
                         ([pick], 'documents-file', 0))

        # Several at once, each with its size and whether it could be read, and why not.
        added = shots['added']
        for shown in ('2 documents added', 'Notes.MD', '8 bytes', 'Can be read', 'scan.docx',
                      '4 bytes', 'Cannot be read',
                      'It could not be read: It holds no text that can be read.',
                      'It is kept, and is not used for the research. Remove it, or carry on '
                      'without it.'):
            self.assertIn(shown, added['text'])
        self.assertIn('2 documents added.', added['toasts'])
        self.assertEqual((added['invalid'], added['focus'], added['off']),
                         ([], 'documents-file', []))
        self.assertNotIn('was not added', added['text'])
        self.assertIn('late', added['beads'])
        self.assertEqual(added['filled'], ['That is all of them'])

        # The runner's own refusal is shown as it gave it, and what was added is still there.
        said_no = shots['twice']
        self.assertIn('Notes.MD was not added. A document called Notes.MD was already added.',
                      said_no['text'])
        self.assertEqual(said_no['invalid'], [pick])
        self.assertIn('2 documents added', said_no['text'])

        removed = shots['removed']
        self.assertIn('scan.docx is removed.', removed['toasts'])
        self.assertIn('1 document added', removed['text'])
        self.assertNotIn('Remove scan.docx', removed['buttons'])
        self.assertIn('Remove Notes.MD', removed['buttons'])
        self.assertEqual((removed['invalid'], removed['focus']), ([], 'documents-file'))

        waiting = shots['not yet']
        self.assertIn('A step is being saved. Nothing was changed, and your documents are '
                      'still here.', waiting['text'])
        self.assertEqual((waiting['focus'], waiting['off'], waiting['filled']),
                         ('That is all of them', [], ['That is all of them']))

        done = shots['done']
        self.assertIn('That is all of them. It carries on from here.', done['toasts'])
        self.assertEqual((done['filled'], done['focus'], done['fields']), ([], 'title', {}))
        for shown in ('Working on its own', going, 'Your documents',
                      'These were given to the research. ' + KEPT_HERE, 'Notes.MD'):
            self.assertIn(shown, done['text'])
        for absent in ('That is all of them', 'Remove Notes.MD'):
            self.assertNotIn(absent, done['buttons'])
        self.assertNotIn('Add your documents', done['text'])
        self.assertLess(done['text'].index('Made so far'), done['text'].index('Your documents'))

        def coded(content: bytes) -> str:
            return base64.b64encode(content).decode()

        root = {'path': str(self.root)}
        self.assertEqual(self.posts(result), [('/api/documents', sent) for sent in (
            {**root, 'action': 'add', 'name': 'Notes.MD', 'content': coded(b'# Notes\n')},
            {**root, 'action': 'add', 'name': 'scan.docx', 'content': coded(b'PK\x03\x04')},
            {**root, 'action': 'add', 'name': 'Notes.MD', 'content': coded(b'Again.')},
            {**root, 'action': 'remove', 'name': 'scan.docx'},
            {**root, 'action': 'done'}, {**root, 'action': 'done'})])

    def test_no_more_documents_are_sent_than_there_is_room_for(self):
        self.started()
        waits = 'Waiting for your documents.'
        one, two = a_document('one.txt', 3), a_document('two.txt', 3)
        answers = self.answers(**{
            'GET /api/trainings': [self.listed('waiting', waits, needs=True)],
            'GET /api/training': [self.detail('waiting', waits)],
            # A run that waits for documents waits for its person, whatever it says of itself.
            'GET /api/run': [a_run('working', waits, documents=supplied(one, files=2))],
            'POST /api/documents': [a_run('working', waits,
                                          documents=supplied(one, two, files=2))]})
        result = self.run_page(answers, [
            {'click': 'Open Rolling restarts'}, {'snapshot': 'room for one'},
            {'attach': 'Add documents', 'files': [{'name': 'two.txt', 'text': 'two'},
                                                  {'name': 'three.txt', 'text': 'three'}]},
            {'snapshot': 'full'}])
        first, full = result['snapshots']['room for one'], result['snapshots']['full']
        self.assertIn('Waiting for you', first['text'])
        self.assertNotIn('Nothing is needed from you right now.', first['text'])
        self.assertIn('each up to 8 MB, and 2 in all.', first['text'])
        self.assertEqual(first['filled'], ['That is all of them'])
        self.assertIn('three.txt was not added: there is room for 2 documents and no more.',
                      full['text'])
        self.assertIn('2 documents added', full['text'])
        self.assertIn('1 document added.', full['toasts'])
        self.assertEqual([sent['name'] for _, sent in self.posts(result)], ['two.txt'])

    def test_each_copy_says_where_it_stands_and_the_copies_are_tried_again(self):
        self.started()
        going = 'Drafting the practice scenario.'
        guide = 'https://docs.example.com/document/d/guide/edit'
        brief = 'https://docs.example.com/document/d/brief/edit'
        no_pandoc = ('Pandoc is not installed on this computer. Install it, then try the '
                     'copies again.')

        def run(doc: str, word: str) -> dict:
            made = word == 'made'
            return a_run('working', going, steps=steps(*['done'] * 7), copies=[
                a_copy('document', 'the learner guide', 'google', 'made', guide),
                a_copy('document', 'the learner guide', 'word', 'made', 'document.docx'),
                a_copy('brief', 'the brief', 'google', doc, brief),
                a_copy('brief', 'the brief', 'word', word,
                       'product-brief.docx' if made else None, None if made else no_pandoc),
                # An address that is not a web address is never made into a link.
                a_copy('yoodli:main', 'the Yoodli scenario', 'word', 'made',
                       'javascript:alert(1)')])

        busy = {'status': 409, 'body': {'error': 'The copies are already being made.'}}
        answers = self.answers(**{
            'GET /api/trainings': [self.listed('working', going)],
            'GET /api/training': [self.detail('working', going)],
            'GET /api/run': [run('out-of-date', 'not-made')],
            'POST /api/copies': [busy, run('made', 'not-made'), run('made', 'made')]})
        again = 'Try the copies again'
        result = self.run_page(answers, [
            {'click': 'Open Rolling restarts'}, {'snapshot': 'copies'},
            {'click': again}, {'snapshot': 'refused'},
            {'click': again}, {'snapshot': 'one left'},
            {'click': again}, {'snapshot': 'all made'},
        ])
        shots = result['snapshots']
        first = shots['copies']
        for shown in ('Copies', 'Google Doc of the learner guide', 'Made',
                      'Word copy of the learner guide',
                      'Kept with the training as document.docx', 'Google Doc of the brief',
                      'Out of date', 'Its file has changed since this copy was made.',
                      'Word copy of the brief', 'Not made', no_pandoc,
                      'Kept with the training as javascript:alert(1)',
                      'A copy that is not made is listed as a limitation.'):
            self.assertIn(shown, first['text'])
        link = {'rel': 'noopener noreferrer', 'target': '_blank'}
        self.assertEqual(first['links'], [
            {'name': 'Open the Google Doc of the learner guide, in a new tab', 'href': guide,
             **link},
            {'name': 'Open the Google Doc of the brief, in a new tab', 'href': brief, **link}])
        # A copy is not what the run needs first, so trying again is not the filled button.
        self.assertIn(again, first['buttons'])
        self.assertEqual(first['filled'], [])
        self.assertLessEqual({'done', 'late', 'off'}, set(first['beads']))
        self.assertLess(first['text'].index('Made so far'), first['text'].index('Copies'))

        refused = shots['refused']
        self.assertIn('The copies are already being made. Nothing was changed: the copies are '
                      'as they were.', refused['text'])
        self.assertEqual(refused['focus'], again)
        self.assertIn('Out of date', refused['text'])

        left = shots['one left']
        self.assertIn('1 copy is still not made. Each says why.', left['toasts'])
        self.assertNotIn('Out of date', left['text'])
        self.assertNotIn('already being made', left['text'])
        self.assertEqual((left['focus'], again in left['buttons']), (again, True))

        made = shots['all made']
        self.assertIn('Every copy is made.', made['toasts'])
        self.assertNotIn(again, made['buttons'])
        self.assertNotIn('Not made', made['text'])
        self.assertEqual(made['focus'], 'title')
        self.assertEqual(self.posts(result), [('/api/copies', {'path': str(self.root)})] * 3)

    def test_the_deck_is_left_out_from_the_run_with_a_reason(self):
        self.started()
        left = 'Everything but the slide deck is made.'
        says = (f'{left} Training Studio does not make the deck yet: make it in a '
                'conversation with your assistant, or leave it out.')
        over = 'Finished, and ready to use, with 1 thing left out or limited.'
        reason = 'We present from the guide.'
        skip = {'path': str(self.root), 'artifact': 'deck', 'decision': 'skip', 'note': reason}
        lists, details = [self.listed('done', left)], [self.detail('done', left)]
        # The decision is the one a gate makes. What follows it is in the runner's words.
        decided = self.captured('POST', '/api/decide', skip)
        decided['body']['said'] = ('This stage is left out. You can bring it back from the '
                                   'training at any time. Writing the index.')
        lists.append(self.listed('done', over))
        details.append(self.detail('done', over))
        limited = [f'The deck stage was left out: {reason}']
        answers = self.answers(**{
            'GET /api/trainings': lists, 'GET /api/training': details,
            'GET /api/run': [
                a_run('done', left, steps=steps(*['done'] * 7),
                      deck={'says': says, 'artifact': 'deck'}),
                a_run('done', over, steps=steps(*['done'] * 7), finished={
                    'ready': True, 'limitations': limited, 'blocking': [],
                    'index': 'README.md'})],
            'POST /api/decide': [decided]})
        result = self.run_page(answers, [
            {'click': 'Open Rolling restarts'}, {'snapshot': 'deck'},
            {'click': 'Leave the deck out'}, {'snapshot': 'sheet'},
            {'click': 'Skip this stage'}, {'snapshot': 'no reason'},
            {'type': f'  {reason}  '}, {'click': 'Skip this stage'}, {'snapshot': 'left out'},
            {'click': 'Stay here'}, {'snapshot': 'after'},
        ])
        shots = result['snapshots']
        notice = shots['deck']
        for shown in ('Everything but the slide deck is made', left,
                      'What to do about the slide deck', says,
                      'Leaving it out takes a reason, which is kept with the training.'):
            self.assertIn(shown, notice['text'])
        self.assertNotIn('Finished here', notice['text'])
        # Making the deck elsewhere is as right as leaving it out, so neither is the filled one.
        self.assertIn('Leave the deck out', notice['buttons'])
        self.assertEqual(notice['filled'], [])
        for absent in ('Pause', 'Stop', 'Resume'):
            self.assertNotIn(absent, notice['buttons'])

        sheet = shots['sheet']
        self.assertIn('Why leave this stage out?', sheet['sheet'])
        self.assertEqual((sheet['filled'], sheet['focus'], sheet['posts']),
                         (['Skip this stage'], 'note-text', 0))
        self.assertIn('Give a reason first.', shots['no reason']['sheet'])
        self.assertEqual(shots['no reason']['posts'], 0)

        # Nothing was read at a gate, so no version is named: only the stage and the reason.
        self.assertEqual(self.posts(result), [('/api/decide', skip)])
        after = shots['left out']
        self.assertIn('This stage is left out.', after['sheet'])
        self.assertIn('Writing the index.', after['sheet'])
        self.assertEqual((after['filled'], after['focus']), (['Back to home'], 'sheet'))
        # It is decided from the run, so nobody is sent to the run they are already on.
        self.assertNotIn('Watch it carry on', after['buttons'])
        self.assertNotIn('Leave the deck out', after['buttons'])
        self.assertIn('Ready to use', after['text'])

        stayed = shots['after']
        self.assertEqual((stayed['sheet'], stayed['filled'], stayed['focus']),
                         ('', ['Open the index'], 'title'))
        self.assertIn(limited[0], stayed['text'])

    def test_a_finished_run_says_whether_it_is_ready_and_opens_its_index(self):
        self.started()
        over = 'Finished, and ready to use, with 2 things left out or limited.'
        limited = ['The deck stage was left out: We present from the guide.',
                   'The brief has no Word copy: pandoc is not installed on this computer.']
        index = '# Rolling restarts\n\n## Who it is for\n\nPlatform engineers new to it.\n'
        read = ok({'artifact': 'README.md', 'file': 'README.md', 'size': len(index),
                   'binary': False, 'text': index, 'truncated': False})
        asked = f'/api/file?{urlencode({"path": self.root, "artifact": "README.md"})}'
        answers = self.answers(**{
            'GET /api/trainings': [self.listed('done', over)],
            'GET /api/training': [self.detail('done', over)],
            'GET /api/run': [a_run('done', over, steps=steps(*['done'] * 7), finished={
                'ready': True, 'limitations': limited, 'blocking': [], 'index': 'README.md'})],
            'GET /api/file': [read]})
        result = self.run_page(answers, [
            {'click': 'Open Rolling restarts'}, {'snapshot': 'ready'},
            {'click': 'Open the index'}, {'snapshot': 'index'},
            {'poll': True}, {'click': 'Back'}, {'snapshot': 'back'},
        ])
        shots = result['snapshots']
        ready = shots['ready']
        for shown in ('Finished', over, 'Ready to use',
                      '2 things were left out or limited:', *limited,
                      'The index lists every file, what was checked, and how to use the '
                      'practice scenarios.'):
            self.assertIn(shown, ready['text'])
        self.assertNotIn('Finished here', ready['text'])
        self.assertEqual((ready['filled'], ready['working']), (['Open the index'], 0))
        for absent in ('Pause', 'Stop', 'Resume', 'Leave the deck out'):
            self.assertNotIn(absent, ready['buttons'])

        # The index is read like any other file of the training, once, and drawn as a document.
        page = shots['index']
        self.assertEqual((page['heading'], page['title'], page['current'], page['filled']),
                         ('The index', 'The index · Rolling restarts · Training Studio',
                          ['Trainings'], []))
        for shown in ('Who it is for', 'Platform engineers new to it.'):
            self.assertIn(shown, page['text'])
        self.assertNotIn('## Who', page['text'])
        self.assertEqual(page['buttons'][4:6], ['Back', 'Rolling restarts'])
        self.assertEqual(self.asked(result, 'file'), [asked])
        self.assertEqual((shots['back']['heading'], shots['back']['filled']),
                         ('Rolling restarts', ['Open the index']))

        # Not ready: what is in the way, what was kept, and the one thing to do next.
        stuck = 'Finished, but not ready to use: 1 thing is in the way.'
        blocking = ['The brief is not approved yet. Open it from the training and decide.']
        missing = {'status': 404, 'body': {'error': 'README.md does not exist yet.'}}
        answers = self.answers(**{
            'GET /api/trainings': [self.listed('done', stuck)],
            'GET /api/training': [self.detail('done', stuck)],
            'GET /api/run': [a_run('done', stuck, steps=steps(*['done'] * 7), finished={
                'ready': False, 'limitations': limited[:1], 'blocking': blocking,
                'index': 'README.md'})],
            'GET /api/file': [missing]})
        result = self.run_page(answers, [
            {'click': 'Open Rolling restarts'}, {'snapshot': 'not ready'},
            {'click': 'Open the index'}, {'snapshot': 'no index'},
            {'click': 'Back to the training'}, {'click': 'See what is in the way'},
            {'snapshot': 'in the way'},
        ])
        shots = result['snapshots']
        halted = shots['not ready']
        for shown in ('Finished, but not ready to use', stuck,
                      'Not ready to use yet', '1 thing is in the way:',
                      blocking[0], 'What was kept: everything that was made.',
                      '1 thing was left out or limited:', limited[0]):
            self.assertIn(shown, halted['text'])
        self.assertEqual(halted['filled'], ['See what is in the way'])
        self.assertIn('Open the index', halted['buttons'])
        self.assertIn('late', halted['beads'])
        # An index that cannot be read is not a dead end.
        gone = shots['no index']
        for shown in ('README.md does not exist yet.', 'Nothing was changed. The training and '
                      'everything it made are as they were.'):
            self.assertIn(shown, gone['text'])
        self.assertEqual((gone['heading'], gone['filled']),
                         ('The index cannot be opened', ['Back to the training']))
        detail = shots['in the way']
        self.assertEqual(detail['heading'], 'Rolling restarts')
        self.assertIn('In the way', detail['text'])
        self.assertIn('Watch the run', detail['buttons'])

    def at_the_yoodli_gate(self) -> dict:
        """A Yoodli scenario at its gate, laid out from a scenario that is approved. Returns
        the address of each gate and of the scenario's file."""
        self.research()
        self.content()
        self.scenario(yoodli=False)
        self.write('yoodli/main.md', test_cli.example('yoodli.md'))
        self.cli('save', 'yoodli:main', '--built')
        self.cli('checkpoint', '--approval', 'page', '--gate', 'yoodli:main', '--stage',
                 'yoodli', '--question', 'Is this ready to paste into Yoodli?')
        return {name: f'{{}}?{urlencode({"path": self.root, "artifact": name})}'
                for name in ('yoodli:main', 'scenario:main')}

    def gate_as_the_runner_gives_it(self, artifact: str, **more) -> dict:
        found = self.read('gate', path=str(self.root), artifact=artifact)
        found['body'].update(more)
        return found

    def test_a_scenario_says_whose_file_it_is_and_a_yoodli_scenario_is_read_beside_it(self):
        at = self.at_the_yoodli_gate()
        waits = 'The Yoodli scenario is waiting for your review.'
        beside = {'artifact': 'scenario:main', 'label': 'the practice scenario'}
        yours = 'This file is yours: you wrote it, and Training Studio does not rewrite it.'
        drafted = ('This file is Training Studio’s draft, written from the practice plan in '
                   'the blueprint.')
        laid_out = 'Laid out from the practice scenario'
        scenario, yoodli = (test_cli.example(name).splitlines()[0].lstrip('# ')
                            for name in ('scenario.md', 'yoodli.md'))

        def answers(whose: str, file: dict) -> dict:
            return self.answers(**{
                'GET /api/trainings': [self.listed('waiting', waits)],
                'GET /api/training': [self.detail('waiting', waits)],
                'GET /api/run': [a_run('waiting', waits, steps=steps(*['done'] * 7))],
                'GET ' + at['yoodli:main'].format('/api/gate'): [
                    self.gate_as_the_runner_gives_it('yoodli:main', beside=beside)],
                'GET ' + at['scenario:main'].format('/api/gate'): [
                    self.gate_as_the_runner_gives_it('scenario:main', whose=whose)],
                'GET /api/file': [file]})

        result = self.run_page(answers('you', self.read('file', path=str(self.root),
                                                        artifact='scenario:main')), [
            {'click': 'Review the Yoodli scenario'}, {'snapshot': 'yoodli'},
            {'poll': True}, {'snapshot': 'later'},
            {'click': 'Rolling restarts'}, {'click': 'Open the practice scenario'},
            {'snapshot': 'scenario'},
        ])
        shots = result['snapshots']
        pair = shots['yoodli']
        self.assertEqual((pair['heading'], pair['filled']), ('The Yoodli scenario', ['Approve']))
        # Both are on the screen: the one being decided, and the one it was laid out from.
        for shown in (laid_out, 'Here to compare with. What you are deciding is the Yoodli '
                      'scenario, not this.', scenario, yoodli, 'Checked for you'):
            self.assertIn(shown, pair['text'])
        self.assertLess(pair['text'].index(yoodli), pair['text'].index(laid_out))
        self.assertNotIn('This file is', pair['text'])
        # It is read with the address every file of a training is read with, and once.
        self.assertEqual(shots['later']['text'], pair['text'])
        self.assertEqual(self.asked(result, 'file'), [at['scenario:main'].format('/api/file')])

        own = shots['scenario']
        self.assertEqual(own['heading'], 'The practice scenario')
        self.assertIn(yours, own['text'])
        self.assertIn('your own wording is laid out under the headings', own['text'])
        self.assertNotIn(laid_out, own['text'])
        self.assertNotIn(drafted, own['text'])

        # A scenario the runner drafted says so. One that cannot be read beside the Yoodli
        # scenario says what happened, and the document being decided is still there.
        missing = {'status': 404, 'body': {'error': 'scenario.md does not exist yet.'}}
        result = self.run_page(answers('runner', missing), [
            {'click': 'Review the Yoodli scenario'}, {'snapshot': 'yoodli'},
            {'click': 'Open it on its own'}, {'snapshot': 'scenario'},
        ])
        shots = result['snapshots']
        for shown in (laid_out, 'It could not be read. scenario.md does not exist yet.',
                      'Nothing was changed, and what you are deciding is not affected.', yoodli):
            self.assertIn(shown, shots['yoodli']['text'])
        self.assertEqual(shots['yoodli']['filled'], ['Approve'])
        self.assertEqual(shots['scenario']['heading'], 'The practice scenario')
        self.assertIn(drafted, shots['scenario']['text'])
        self.assertNotIn(yours, shots['scenario']['text'])

    def test_home_files_a_finished_training_under_finished_and_says_when_the_deck_is_left(self):
        self.research(yoodli=False, copies=())
        for name, file in (('blueprint', 'blueprint.md'), ('document', 'document.md'),
                           ('brief', 'product-brief.md')):
            self.make(name, file, test_cli.example(file))
        self.scenario(yoodli=False)
        left = ('Everything but the slide deck is made. Training Studio does not make the '
                'deck yet.')
        over = 'Finished, and ready to use.'
        lists = [self.listed('done', left)]
        # The deck is made in a conversation, and the runner then finishes the training.
        self.deck()
        lists.append(self.listed('done', over))
        self.assertEqual([found['body']['trainings'][0]['state'] for found in lists],
                         ['in-progress', 'finished'])
        result = self.run_page(self.answers(**{'GET /api/trainings': lists}), [
            {'snapshot': 'home'}, {'click': 'Trainings'}, {'snapshot': 'trainings'},
            {'click': 'Status'}, {'snapshot': 'status'},
            {'click': 'Home'}, {'poll': True}, {'snapshot': 'finished'},
            {'click': 'Trainings'}, {'snapshot': 'finished trainings'},
        ])
        shots = result['snapshots']
        # The deck is all that is left: one sentence says so, in the page's own words.
        home = shots['home']
        self.assertEqual(home['text'].count(DECK_LEFT), 1)
        self.assertLess(home['text'].index('In progress'), home['text'].index(DECK_LEFT))
        for absent in ('Finished', left):
            self.assertNotIn(absent, home['text'])
        self.assertEqual((home['working'], home['filled']), (0, ['New training']))
        for name in ('trainings', 'status'):
            with self.subTest(screen=name):
                for shown in ('In progress', DECK_LEFT):
                    self.assertIn(shown, shots[name]['text'])
                self.assertNotIn('Finished here', shots[name]['text'])

        # Finished by the runner: under Finished, and nowhere under In progress.
        done = shots['finished']
        self.assertLess(done['text'].index('Finished'), done['text'].index(over))
        for absent in ('In progress', 'Finished here', DECK_LEFT):
            self.assertNotIn(absent, done['text'])
        self.assertEqual((done['working'], done['beads']), (0, ['done']))
        self.assertIn('Open Rolling restarts', done['buttons'])
        every = shots['finished trainings']
        self.assertIn('Finished', every['text'])
        for absent in ('In progress', 'Finished here'):
            self.assertNotIn(absent, every['text'])

    def test_the_plain_desk_shows_none_of_it(self):
        self.at_the_blueprint_gate()
        answers = {'GET /api/trainings': [self.read('trainings')],
                   'GET /api/computer': [self.read('computer')],
                   'GET /api/training': [self.read('training', path=str(self.root))]}
        result = self.run_page(answers, [
            {'snapshot': 'home'}, {'poll': True},
            {'click': 'Trainings'}, {'snapshot': 'trainings'},
            {'click': 'Open Rolling restarts'}, {'snapshot': 'training'},
            {'click': 'Settings'}, {'snapshot': 'settings'},
        ])
        # It is asked once, answered 404, and nothing the runner serves is asked for again.
        self.assertEqual(self.asked(result, 'capabilities'), ['/api/capabilities'])
        for endpoint in ('setup', 'agents', 'run', 'share'):
            self.assertEqual(self.asked(result, endpoint), [])
        shots = result['snapshots']
        for name, shot in shots.items():
            with self.subTest(screen=name):
                self.assertTrue(shot['sidebar'])
                for absent in ('New training', 'Share now', 'Change the set-up',
                               'Watch the run'):
                    self.assertNotIn(absent, shot['buttons'])
                for absent in ('Workspace', 'shared', 'Set-up'):
                    self.assertNotIn(absent, shot['text'])
        self.assertEqual(shots['home']['filled'], ['Review the blueprint'])
        self.assertEqual(shots['training']['heading'], 'Rolling restarts')
        self.assertIn('How this training is decided', shots['training']['text'])
        self.assertIn('Nothing you read or decide here is sent anywhere else.',
                      shots['settings']['text'])


MARKUP_TITLE = '<img src=x onerror=alert(1)>'


class AnnounceTests(unittest.TestCase):
    """What the command prints, and to whom."""

    class Server:
        address = 'http://127.0.0.1:4321/'
        url = 'http://127.0.0.1:4321/#token=the-key-only-a-person-may-hold'

    def test_a_terminal_is_given_the_link_whole_and_nothing_is_opened(self):
        printed = cmd_desk.announce(self.Server, True, opener=never)
        self.assertEqual(printed, {'url': self.Server.url})

    def test_anything_else_is_given_the_address_without_its_key(self):
        opened = []
        printed = cmd_desk.announce(self.Server, False, opener=lambda url: opened.append(url)
                                    or True)
        self.assertEqual(printed, {'address': 'http://127.0.0.1:4321/', 'opened': True,
                                   'note': cmd_desk.NOT_A_PERSON})
        self.assertEqual(opened, [self.Server.url])
        self.assertNotIn('the-key', json.dumps(printed))
        self.assertNotIn('token', json.dumps(printed))
        self.assertIn('run this command in a terminal of your own', printed['note'])

    def test_where_no_browser_can_be_opened_it_says_so(self):
        printed = cmd_desk.announce(self.Server, False, opener=lambda url: False)
        self.assertEqual((printed['opened'], printed['address']),
                         (False, 'http://127.0.0.1:4321/'))
        with mock.patch.dict(os.environ, {'BROWSER': 'a-browser'}):
            with mock.patch.object(cmd_desk.webbrowser, 'open',
                                   side_effect=RuntimeError('none')):
                self.assertFalse(cmd_desk.show(self.Server.url))
            with mock.patch.object(cmd_desk.webbrowser, 'open', return_value=True) as opened:
                self.assertTrue(cmd_desk.show(self.Server.url))
            opened.assert_called_once_with(self.Server.url)

    def test_with_no_screen_no_browser_is_started_at_all(self):
        without = {name: value for name, value in os.environ.items()
                   if name not in ('BROWSER', 'DISPLAY', 'WAYLAND_DISPLAY')}
        with mock.patch.dict(os.environ, without, clear=True), \
                mock.patch.object(cmd_desk.sys, 'platform', 'linux'), \
                mock.patch.object(cmd_desk.webbrowser, 'open', never):
            self.assertFalse(cmd_desk.show(self.Server.url))
            self.assertFalse(cmd_desk.announce(self.Server, False)['opened'])


class WireTests(DeskCase):
    """A decision sent over a real connection, as the browser sends one."""

    def setUp(self):
        super().setUp()
        self.at_the_blueprint_gate()
        self.approve = {'path': str(self.root), 'artifact': 'blueprint', 'decision': 'approve',
                        'seen': self.sha('blueprint.md')}

    def test_a_decision_from_the_page_is_made_and_seen_in_status(self):
        gate = self.api('gate', path=str(self.root), artifact='blueprint')
        self.assertEqual((gate['waiting'], gate['decisions'][0], gate['sha256']),
                         (True, 'approve', self.approve['seen']))
        outcome = self.send('decide', self.approve)
        self.assertEqual(outcome['decided']['by'], 'page')
        self.assertEqual(self.cli('status')['artifacts']['blueprint'], 'approved')
        self.assertEqual(self.api('trainings')['needs'], 0)

    def test_a_decision_without_the_key_the_origin_or_json_is_refused(self):
        before = self.on_disk()
        body = json.dumps(self.approve).encode()
        origin = f'http://127.0.0.1:{self.desk.port}'
        json_kind = {'Content-Type': 'application/json'}
        for label, expect, options in (
                ('no key', 403, {'token': False, 'headers': {**json_kind, 'Origin': origin}}),
                ('no origin', 403, {'headers': json_kind}),
                ('another origin', 403, {'headers': {**json_kind,
                                                     'Origin': 'http://example.com'}}),
                ('a form', 415, {'headers': {
                    'Origin': origin, 'Content-Type': 'application/x-www-form-urlencoded'}}),
                ('another host', 403, {'host': 'example.com',
                                       'headers': {**json_kind, 'Origin': origin}})):
            with self.subTest(label):
                status, headers, data = self.fetch('/api/decide', method='POST', body=body,
                                                   **options)
                self.assertEqual(status, expect, data)
                self.assertEqual(headers.get_content_type(), 'application/json')
                for name, value in SECURITY_HEADERS.items():
                    self.assertEqual(headers.get_all(name), [value])
        self.assertEqual(self.on_disk(), before)

    def test_a_body_that_is_too_long_is_refused_unread(self):
        before = self.on_disk()
        long = json.dumps({**self.approve, 'note': 'x' * desk.BODY_LIMIT}).encode()
        refusal = self.send('decide', long, 413)
        self.assertIn('64,000 bytes', refusal['error'])
        self.assertEqual(self.on_disk(), before)
        self.assertEqual(self.api('trainings')['needs'], 1)

    def test_every_other_method_is_still_refused(self):
        before = self.on_disk()
        body = json.dumps(self.approve).encode()
        headers = {'Origin': f'http://127.0.0.1:{self.desk.port}',
                   'Content-Type': 'application/json'}
        for method in ('PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD', 'TRACE'):
            for target, allow in (('/api/decide', 'POST'), ('/api/approval', 'POST'),
                                  ('/api/computer', 'GET, POST'), ('/api/trainings', 'GET')):
                with self.subTest(method=method, target=target):
                    status, replied, _ = self.fetch(target, method=method, body=body,
                                                    headers=headers)
                    self.assertEqual((status, replied['Allow']), (405, allow))
        status, replied, _ = self.fetch('/api/decide', method='GET')
        self.assertEqual((status, replied['Allow']), (405, 'POST'))
        self.assertEqual(self.on_disk(), before)

    def test_another_site_cannot_ask_leave_to_send_a_decision(self):
        status, headers, _ = self.fetch('/api/decide', method='OPTIONS', token=False, headers={
            'Origin': 'http://example.com', 'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'content-type,x-training-studio-token'})
        self.assertEqual(status, 405)
        self.assertFalse([name for name in headers if name.lower().startswith('access-control')])

    def test_the_computer_is_looked_at_only_when_asked(self):
        with mock.patch.object(computer, 'check', return_value={'ready': True}) as looked:
            self.assertEqual(self.api('computer'), {'computer': None})
            self.assertEqual(self.send('computer', {}), {'computer': {'ready': True}})
            self.assertEqual(self.api('computer'), {'computer': {'ready': True}})
        looked.assert_called_once_with(google=False)


class CommandTests(DeskCase):
    """`training.py desk`, run by a person in a terminal and by anything else."""

    def launch(self, *args, stdout=subprocess.PIPE, opened: Path | None = None):
        environment = dict(os.environ)
        if opened is not None:
            # A stand-in for the browser: it writes down the link it was asked to open.
            recorder = self.root.parent / 'recorder.py'
            recorder.write_text('import sys\nopen(sys.argv[1], "w").write(sys.argv[2])\n')
            environment['BROWSER'] = f'{sys.executable} {recorder} {opened} %s'
        process = subprocess.Popen(
            [sys.executable, str(test_cli.CLI), 'desk', *args], cwd=self.root, stdout=stdout,
            stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True, env=environment)
        guard = threading.Timer(30, process.kill)
        guard.start()

        def finish():
            guard.cancel()
            if process.poll() is None:
                process.kill()
                process.wait()
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        self.addCleanup(finish)
        return process

    def usable_signals(self) -> list:
        """SIGINT is ignored in a process started in the background by some shells."""
        ignored = signal.getsignal(signal.SIGINT) == signal.SIG_IGN
        return [signal.SIGTERM] if ignored else [signal.SIGINT, signal.SIGTERM]

    @unittest.skipIf(os.name == 'nt', 'signals are delivered differently on Windows')
    def test_to_anything_but_a_terminal_it_prints_no_key_and_opens_the_page_itself(self):
        self.cli('init', '--title', 'Topic')
        for how in self.usable_signals():
            with self.subTest(signal.Signals(how).name):
                opened = self.root.parent / f'opened-{int(how)}.txt'
                process = self.launch(opened=opened)
                line = process.stdout.readline()
                printed = json.loads(line)
                self.assertEqual(set(printed), {'address', 'opened', 'note'})
                self.assertRegex(printed['address'], r'^http://127\.0\.0\.1:\d+/$')
                self.assertNotIn('token', line)
                self.assertNotIn('#', line)
                self.assertIn('terminal of your own', printed['note'])
                self.assertTrue(printed['opened'])
                # The key went to the browser and nowhere else.
                url = opened.read_text()
                self.assertRegex(url, r'^http://127\.0\.0\.1:\d+/#token=[A-Za-z0-9_-]{32,}$')
                address, _, fragment = url.partition('#')
                token = fragment.removeprefix('token=')
                self.assertEqual(address, printed['address'])
                self.assertNotIn(token, line)
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

    @unittest.skipIf(os.name == 'nt', 'there is no pseudo-terminal on Windows')
    def test_to_a_terminal_it_prints_the_link_whole_and_opens_nothing(self):
        import pty
        import select
        self.cli('init', '--title', 'Topic')
        opened = self.root.parent / 'opened.txt'
        primary, secondary = pty.openpty()
        self.addCleanup(os.close, primary)
        process = self.launch(stdout=secondary, opened=opened)
        os.close(secondary)
        line = b''
        while not line.endswith(b'\n'):
            ready, _, _ = select.select([primary], [], [], 20)
            self.assertTrue(ready, 'the command printed nothing')
            line += os.read(primary, 4096)
        url = json.loads(line)['url']
        self.assertRegex(url, r'^http://127\.0\.0\.1:\d+/#token=[A-Za-z0-9_-]{32,}$')
        address, _, fragment = url.partition('#')
        status, _, _ = ask(f'{address}api/trainings',
                           {desk.TOKEN_HEADER: fragment.removeprefix('token=')})
        self.assertEqual(status, 200)
        self.assertFalse(opened.exists())
        process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(timeout=20), 0)

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
        self.assertEqual(again.address, f'http://127.0.0.1:{self.desk.port}/')


class PackageTests(unittest.TestCase):
    def guidance(self, name: str = 'desk') -> str:
        return (helpers.SKILL / 'references' / f'{name}.md').read_text(encoding='utf-8')

    def test_the_guidance_fits_in_500_estimated_tokens(self):
        self.assertLessEqual(validate_package.estimate(self.guidance()), 500)

    def test_the_page_is_part_of_the_package(self):
        for name in ('references/desk.md', 'scripts/desk.py', 'scripts/cmd_desk.py',
                     'scripts/computer.py', *(f'scripts/desk/{name}' for name in PAGE_FILES)):
            self.assertIn(name, validate_package.REQUIRED)
        files, budget = validate_package.loading_sets()['desk']
        self.assertEqual((files, budget), (['SKILL.md', 'references/desk.md'], 2000))

    def test_the_guidance_names_no_assistant_and_none_of_its_tools(self):
        for name in ('desk', 'gates', 'intake'):
            for word in ('Claude', 'Codex', 'Bash', 'run_in_background', 'BashOutput',
                         'KillShell'):
                self.assertNotIn(word, self.guidance(name))

    def test_the_guidance_says_how_a_gate_is_decided_on_the_page(self):
        guidance = self.guidance()
        for needed in ('training.py desk', 'terminal of their own', '--gate', '`status`',
                       '`requests`', 'Never open it yourself', 'session.json',
                       'Do not ask for approval in chat'):
            self.assertIn(needed, guidance)
        self.assertIn('desk reference', self.guidance('gates'))
        self.assertIn('--gate', self.guidance('gates'))
        self.assertIn('--approval page', self.guidance('intake'))


if __name__ == '__main__':
    unittest.main()
