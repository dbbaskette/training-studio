"""The runner's server: every address the appendices of the milestone 2 and milestone 3
specifications name, each thing it refuses, and what the desk's own answers gain.

Most classes ask the page without a socket, so they run where a port cannot be opened.
WireTests talks to a real server on a local port and is skipped where that is not allowed.
Nothing starts an agent, looks at the real computer or touches the network.
"""
import base64
import json
import os
import stat
import time
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from email.message import Message
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

import helpers
from runner_support import (CHOSEN, FORM, NO_BRAND_SKILL, SCENARIO, Brand, Slides, StudioCase,
                            asks, fails, left)

import computer
import desk
import home
import workspace
from runner import agents, gitstate, page, pipeline, settings
from workspace import WorkspaceError

VERSION = (helpers.SKILL / 'VERSION').read_text().strip()
GETS = ('/api/capabilities', '/api/setup', '/api/agents', '/api/run')
POSTS = ('/api/setup/check', '/api/setup', '/api/trainings', '/api/run', '/api/answer',
         '/api/documents', '/api/copies', '/api/share')
BOTH = ('/api/setup', '/api/run', '/api/trainings')
RUN_KEYS = ['agent', 'copies', 'deck', 'deck_left', 'documents', 'driver', 'finished', 'mine',
            'model', 'notice', 'outline', 'problem', 'question', 'queue', 'sentence', 'spent',
            'state', 'steps', 'taken', 'workers']
STEP_KEYS = ['attempts', 'dollars', 'error', 'id', 'kind', 'label', 'seconds', 'status']
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def never(*args, **kwargs):
    raise AssertionError('A test must never look at the real computer.')


class PageCase(StudioCase):
    """The runner's page, asked without a socket."""

    PORT = 8765

    def setUp(self):
        super().setUp()
        for patcher in (mock.patch.object(computer, 'run', never),
                        mock.patch.object(computer, 'reach', never)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.page = page.RunnerPage(self.PORT, self.engine)
        self.origin = f'http://127.0.0.1:{self.PORT}'

    def headers(self, token=True, host=None, origin=None, kind=None) -> Message:
        made = Message()
        made['Host'] = host or f'127.0.0.1:{self.PORT}'
        if token:
            made[desk.TOKEN_HEADER] = self.page.token if token is True else token
        for name, value in (('Origin', origin), ('Content-Type', kind)):
            if value:
                made[name] = value
        return made

    def answer(self, method: str, target: str, body: bytes | None = None, **options):
        """One request, answered as the server would: the status, the JSON, and `Allow`."""
        try:
            status, _, data = self.page.answer(target, self.headers(**options), method, body)
        except desk.Refusal as refusal:
            return int(refusal.status), {'error': str(refusal)}, refusal.allow
        except WorkspaceError as refusal:
            return 409, {'error': str(refusal)}, None
        self.assertNotIn(b'<', data)
        return int(status), json.loads(data) if data else None, None

    def get(self, endpoint: str, expect: int = 200, **params):
        target = f'/api/{endpoint}' + (f'?{urlencode(params)}' if params else '')
        status, reply, _ = self.answer('GET', target)
        self.assertEqual(status, expect, reply)
        return reply

    def post(self, endpoint: str, sent, expect: int = 200, **options):
        """POST as the page does, unless `options` say otherwise."""
        options.setdefault('origin', self.origin)
        options.setdefault('kind', 'application/json')
        body = sent if isinstance(sent, (bytes, type(None))) else json.dumps(sent).encode()
        status, reply, _ = self.answer('POST', f'/api/{endpoint}', body, **options)
        self.assertEqual(status, expect, reply)
        return reply

    def started(self, **changes) -> str:
        return self.post('trainings', {**FORM, **changes})['path']

    def on_disk(self) -> dict:
        return {path.relative_to(self.base).as_posix(): path.read_bytes()
                for path in sorted(self.base.rglob('*'))
                if path.is_file() and '.git' not in path.parts}


class FirstTimeCase(PageCase):
    """A computer where nothing is set up yet."""

    def set_up(self):
        return None

    def bare(self, name: str = 'team-repo.git') -> Path:
        remote = self.base / name
        remote.mkdir()
        self.git('init', '--quiet', '--bare', repo=remote)
        self.git('symbolic-ref', 'HEAD', 'refs/heads/main', repo=remote)
        return remote

    def someone_else(self, remote: Path, **named) -> None:
        """A teammate sets the workspace up in the shared repository and shares it."""
        with mock.patch.dict(os.environ, {'TRAINING_STUDIO_DATA': str(self.base / 'theirs')}):
            self.assertTrue(gitstate.sync(gitstate.join(str(remote), **named))['shared'])


class CapabilityTests(PageCase):
    def test_the_runner_says_it_is_here(self):
        self.assertEqual(self.get('capabilities'), {'runner': True, 'version': VERSION})

    def test_the_plain_desk_answers_404_and_knows_none_of_the_runners_addresses(self):
        plain = desk.Page(self.PORT)
        headers = self.headers()
        headers.replace_header(desk.TOKEN_HEADER, plain.token)
        for target in GETS:
            with self.subTest(target):
                with self.assertRaises(desk.Refusal) as refused:
                    plain.answer(target, headers)
                self.assertEqual(refused.exception.status, 404)
        self.assertEqual((plain.reads, plain.writes), (desk.READS, desk.WRITES))
        self.assertEqual(plain.allowed('/api/trainings'), 'GET')
        listed = json.loads(plain.answer('/api/trainings', headers)[2])
        self.assertEqual(listed, {'trainings': [], 'needs': 0})

    def test_it_serves_the_desks_own_page(self):
        status, kind, body = self.page.answer('/', self.headers(token=False))
        self.assertEqual((status, kind), (200, 'text/html; charset=utf-8'))
        self.assertEqual(body, (desk.PAGE_DIR / 'index.html').read_bytes())


class RuleTests(PageCase):
    """Milestone 1's safety rules, on every address the runner adds."""

    def setUp(self):
        super().setUp()
        self.path = self.started()
        self.bodies = {'/api/setup/check': {'path': str(self.base / 'elsewhere')},
                       '/api/setup': {'limits': {'parallel': 4}},
                       '/api/trainings': {**FORM, 'title': 'Health checks'},
                       '/api/run': {'path': self.path, 'action': 'stop'},
                       '/api/answer': {'path': self.path, 'id': 'x', 'answer': 'Yes.'},
                       '/api/documents': {'path': self.path, 'action': 'add',
                                          'name': 'handbook.txt', 'content': 'V29yZHMu'},
                       '/api/copies': {'path': self.path},
                       '/api/share': {}}
        self.before = self.on_disk()

    def refused(self, method: str, target: str, expect: int, **options) -> dict:
        body = json.dumps(self.bodies[target]).encode() if method == 'POST' else None
        if method == 'POST':
            options.setdefault('origin', self.origin)
            options.setdefault('kind', 'application/json')
        status, reply, _ = self.answer(method, target, body, **options)
        self.assertEqual(status, expect, (target, reply))
        self.assertEqual(self.on_disk(), self.before, target)
        return reply

    def test_every_call_needs_the_key(self):
        for method, targets in (('GET', GETS), ('POST', POSTS)):
            for target in targets:
                with self.subTest(target=target, method=method):
                    for token in (False, 'not-the-key'):
                        said = self.refused(method, target, 403, token=token)
                        self.assertIn('needs the key', said['error'])

    def test_it_answers_only_at_its_own_local_address(self):
        for method, targets in (('GET', GETS), ('POST', POSTS)):
            for target in targets:
                with self.subTest(target=target, method=method):
                    said = self.refused(method, target, 403, host='example.com')
                    self.assertIn('only at its own local address', said['error'])

    def test_a_change_is_taken_only_from_the_page_itself(self):
        for target in POSTS:
            with self.subTest(target):
                for origin in (None, 'http://example.com', 'http://127.0.0.1:9999'):
                    options = {'origin': origin} if origin else {'origin': ''}
                    said = self.refused('POST', target, 403, **options)
                    self.assertIn('only from the page itself', said['error'])

    def test_a_change_is_taken_only_as_json(self):
        for target in POSTS:
            with self.subTest(target):
                self.refused('POST', target, 415, kind='application/x-www-form-urlencoded')
                status, said, _ = self.answer('POST', target, b'["a", "list"]',
                                              origin=self.origin, kind='application/json')
                self.assertEqual((status, said['error']),
                                 (400, 'Send the change as one JSON object.'))
                status, _, _ = self.answer('POST', target, None, origin=self.origin,
                                           kind='application/json')
                self.assertEqual(status, 413)
                status, _, _ = self.answer('POST', f'{target}?path=x', b'{}',
                                           origin=self.origin, kind='application/json')
                self.assertEqual(status, 400)
        self.assertEqual(self.on_disk(), self.before)

    def test_each_address_answers_only_its_own_methods(self):
        for target in GETS:
            expect = 'GET, POST' if target in BOTH else 'GET'
            self.assertEqual(self.page.allowed(target), expect)
        for target in POSTS:
            expect = 'GET, POST' if target in BOTH else 'POST'
            self.assertEqual(self.page.allowed(f'{target}?x=1'), expect)
        for target in set(GETS) - set(BOTH):
            status, _, allow = self.answer('POST', target, b'{}', origin=self.origin,
                                           kind='application/json')
            self.assertEqual((status, allow), (405, 'GET'))
        for target in set(POSTS) - set(BOTH):
            status, _, allow = self.answer('GET', target)
            self.assertEqual((status, allow), (405, 'POST'))
        for method in ('PUT', 'PATCH', 'DELETE'):
            status, _, allow = self.answer(method, '/api/run')
            self.assertEqual((status, allow), (405, 'GET, POST'))
        self.assertEqual(self.on_disk(), self.before)

    def test_the_desks_own_addresses_are_still_refused_as_before(self):
        self.assertEqual(self.answer('GET', '/api/decide')[::2], (405, 'POST'))
        self.assertEqual(self.answer('GET', '/api/nothing')[0], 404)
        status, said, _ = self.answer('GET', '/api/training?path=' + str(self.base))
        self.assertEqual((status, said['error']),
                         (403, 'That folder is not a training this computer knows.'))


class SetUpTests(FirstTimeCase):
    def test_nothing_is_set_up_at_first(self):
        self.assertEqual(self.get('setup'), {
            'configured': False, 'workspace': None,
            'agent': {'default': 'claude', 'model': None},
            'limits': {'step_seconds': 900, 'training_dollars': 20.0, 'parallel': 2},
            'previews': {'how': None, 'drive': False, 'local': False, 'left': []},
            'notify': {'on': False, 'can': True, 'problem': None},
            'brand': {'found': False, 'name': None, 'brands': [], 'skills': [],
                      'problem': NO_BRAND_SKILL}})
        said = self.post('trainings', FORM, 409)
        self.assertIn('No workspace is set up on this computer yet', said['error'])
        self.assertIn('No workspace is set up', self.post('share', {}, 409)['error'])
        self.assertEqual(self.get('trainings'), {'trainings': [], 'needs': 0})

    def test_a_folder_on_this_computer_becomes_the_workspace(self):
        folder = self.base / 'my-trainings'
        made = self.post('setup', {
            'path': str(folder), 'folder': 'courses', 'branch': 'main', 'name': 'my-work',
            'share_when': 'when-asked', 'agent': 'codex', 'model': 'a-model',
            'limits': {'step_seconds': 600, 'training_dollars': 7.5, 'parallel': 3}})
        self.assertEqual(made, {
            'configured': True,
            'workspace': {'name': 'my-work', 'repository': None, 'path': str(folder),
                          'folder': 'courses', 'branch': 'main', 'share_when': 'when-asked',
                          'shared': False, 'notice': None},
            'agent': {'default': 'codex', 'model': 'a-model'},
            'limits': {'step_seconds': 600, 'training_dollars': 7.5, 'parallel': 3},
            'previews': {'how': None, 'drive': False, 'local': False, 'left': []},
            'notify': {'on': False, 'can': True, 'problem': None},
            'brand': {'found': False, 'name': None, 'brands': [], 'skills': [],
                      'problem': NO_BRAND_SKILL}})
        self.assertEqual(self.get('setup'), made)
        marker = json.loads((folder / 'courses' / 'hub.json').read_text())
        self.assertEqual((marker['tool'], marker['name'], marker['folder'], marker['branch']),
                         ('training-studio', 'my-work', 'courses', 'main'))
        self.assertEqual(settings.load(), settings.Settings('codex', 'a-model', 600, 7.5, 3))
        path = self.started()
        self.assertEqual(Path(path), folder / 'courses' / 'rolling-restarts')
        self.assertEqual(self.get('run', path=path)['agent'], 'codex')

    def test_a_repository_becomes_the_workspace_in_a_copy_of_the_runners_own(self):
        remote = self.bare()
        made = self.post('setup', {'repository': str(remote), 'folder': None, 'branch': None,
                                   'name': None, 'share_when': 'each-decision',
                                   'agent': 'claude', 'model': None, 'limits': {}})
        space = made['workspace']
        self.assertEqual((space['name'], space['repository'], space['folder'],
                          space['branch'], space['share_when'], space['shared']),
                         ('team-repo', str(remote), 'trainings', 'main', 'each-decision',
                          False))
        self.assertEqual(Path(space['path']), gitstate.clones() / 'team-repo')
        self.assertEqual(self.post('share', {}), {'shared': True, 'notice': None})
        self.assertEqual(self.get('setup')['workspace']['shared'], True)

    def test_a_second_person_is_asked_for_nothing_the_repository_already_says(self):
        remote = self.bare()
        self.someone_else(remote, folder='courses', name='field-team')
        made = self.post('setup', {'repository': str(remote)})
        space = made['workspace']
        self.assertEqual((space['name'], space['folder'], space['branch']),
                         ('field-team', 'courses', 'main'))

    def test_the_settings_can_change_without_moving_the_workspace(self):
        folder = self.base / 'my-trainings'
        self.post('setup', {'path': str(folder)})
        changed = self.post('setup', {'share_when': 'when-asked', 'model': 'a-model',
                                      'limits': {'parallel': 4}})
        self.assertEqual((changed['workspace']['path'], changed['workspace']['share_when'],
                          changed['agent'], changed['limits']),
                         (str(folder), 'when-asked', {'default': 'claude', 'model': 'a-model'},
                          {'step_seconds': 900, 'training_dollars': 20.0, 'parallel': 4}))
        self.assertEqual(self.post('setup', {'agent': 'codex'})['agent'],
                         {'default': 'codex', 'model': None})

    def test_set_up_that_makes_no_sense_changes_nothing(self):
        folder = str(self.base / 'my-trainings')
        for sent, said in (
                ({}, "Give the repository's address, or a folder on this computer."),
                ({'path': folder, 'repository': 'https://example.com/team/team-repo.git'},
                 "Give the repository's address or a folder on this computer, not both."),
                ({'path': 'my-trainings'}, "Give the folder's whole path"),
                ({'path': folder, 'folder': '../outside'}, 'A workspace folder is letters'),
                ({'path': folder, 'branch': 'not a branch'}, 'cannot be the name of a branch'),
                ({'path': folder, 'name': 'two words'}, 'A workspace name is letters'),
                ({'path': folder, 'share_when': 'never'}, 'Sharing is one of: each-decision, '
                 'when-asked.'),
                ({'path': folder, 'agent': 'another'}, 'The agent is one of: claude, codex.'),
                ({'path': folder, 'model': 'two words'}, 'The model is the short name'),
                ({'path': folder, 'limits': [900]}, 'Give the limits as'),
                ({'path': folder, 'limits': {'step_seconds': 5}},
                 'The time for one step, in seconds, is a whole number from 60 to 7200.'),
                ({'path': folder, 'limits': {'training_dollars': 0}},
                 'What a training may spend, in dollars, is a number from 0.01 to 1000.'),
                ({'path': folder, 'limits': {'parallel': 2.5}},
                 'How many trainings run at once is a whole number from 1 to 8.'),
                ({'path': 7}, 'Give the path as text.')):
            with self.subTest(sent=sent):
                self.assertIn(said, self.post('setup', sent, 400)['error'])
        self.assertFalse(Path(folder).exists())
        self.assertEqual((self.get('setup')['configured'], settings.path().exists()),
                         (False, False))

    def test_set_up_needs_a_git_identity_and_says_how_to_give_one(self):
        (self.base / 'nobody.gitconfig').write_text('[user]\n\tuseConfigOnly = true\n')
        with mock.patch.dict(os.environ, {'GIT_CONFIG_GLOBAL':
                                          str(self.base / 'nobody.gitconfig')}):
            said = self.post('setup', {'path': str(self.base / 'my-trainings')}, 409)
            self.assertIn('git does not know who you are', said['error'])
            self.assertIn('git config --global user.name', said['error'])
            checked = self.post('setup/check', {'path': str(self.base / 'my-trainings')})
        self.assertEqual(self.get('setup')['configured'], False)
        who = checked['checks'][2]
        self.assertEqual((checked['ok'], who['what'], who['ok']),
                         (False, 'git knows who you are', False))
        self.assertIn('git config --global user.name "Your Name"', who['fix'])

    def test_setting_up_picks_up_the_trainings_already_in_the_workspace(self):
        remote = self.bare()
        with mock.patch.dict(os.environ, {'TRAINING_STUDIO_DATA': str(self.base / 'theirs')}):
            theirs = self.make()
            gitstate.join(str(remote))
            made = theirs.start(pipeline.check_form(FORM))
            self.assertTrue(theirs.share()['shared'])
        self.assertEqual(self.get('trainings')['trainings'], [])
        self.post('setup', {'repository': str(remote)})
        listed = self.get('trainings')['trainings']
        self.assertEqual([(item['title'], item['run']['state']) for item in listed],
                         [('Rolling restarts', 'waiting')])
        self.assertNotEqual(listed[0]['path'], made['path'])


class CheckTests(FirstTimeCase):
    """`POST /api/setup/check` looks, and changes nothing."""

    WHATS = ['can be reached', 'can be written to', 'git knows who you are',
             'The folder for trainings can be used']

    def check(self, expect: int = 200, **sent) -> dict:
        sent = {'repository': None, 'path': None, 'folder': None, 'branch': None, **sent}
        before = self.on_disk()
        found = self.post('setup/check', sent, expect)
        self.assertEqual(self.on_disk(), before, 'a check changes nothing')
        self.assertEqual(self.get('setup')['configured'], False)
        if gitstate.clones().exists():
            self.assertEqual(list(gitstate.clones().iterdir()), [])
        return found

    def shape(self, found: dict) -> None:
        self.assertEqual(sorted(found), ['checks', 'found', 'ok'])
        self.assertEqual(sorted(found['found']), ['branch', 'existing', 'folder', 'name'])
        for item, what in zip(found['checks'], self.WHATS, strict=True):
            self.assertEqual(sorted(item), ['fix', 'ok', 'what'])
            self.assertIn(what, item['what'])
            self.assertEqual(item['fix'] is None, item['ok'])
        self.assertEqual(found['ok'], all(item['ok'] for item in found['checks']))

    def test_a_new_folder_on_this_computer_can_be_used(self):
        found = self.check(path=str(self.base / 'my-trainings'))
        self.shape(found)
        self.assertEqual((found['ok'], found['found']), (True, {
            'name': 'my-trainings', 'folder': 'trainings', 'branch': 'main',
            'existing': False}))
        self.assertEqual([item['what'] for item in found['checks']], [
            'The folder can be reached', 'The folder can be written to',
            'git knows who you are', 'The folder for trainings can be used'])
        named = self.check(path=str(self.base / 'my-trainings'), folder='courses',
                           branch='trainings')
        self.assertEqual((named['found']['folder'], named['found']['branch']),
                         ('courses', 'trainings'))

    def test_an_unchosen_branch_is_the_one_git_would_give_the_repository(self):
        (self.base / 'trunk.gitconfig').write_text(
            '[user]\n\tname = Alex\n\temail = alex@example.com\n[init]\n\tdefaultBranch = '
            'trunk\n')
        with mock.patch.dict(os.environ, {'GIT_CONFIG_GLOBAL':
                                          str(self.base / 'trunk.gitconfig')}):
            found = self.check(path=str(self.base / 'my-trainings'))
            self.assertEqual(found['found']['branch'], 'trunk')
            made = self.post('setup', {'path': str(self.base / 'my-trainings'),
                                       'folder': None, 'branch': None})
        self.assertEqual(made['workspace']['branch'], 'trunk')
        remote = self.bare('other-repo.git')
        self.git('symbolic-ref', 'HEAD', 'refs/heads/develop', repo=remote)
        self.assertEqual(self.post('setup/check', {'repository': str(remote)})['found'][
            'branch'], 'develop')

    def test_a_folder_that_already_holds_a_workspace_says_what_it_holds(self):
        with mock.patch.dict(os.environ, {'TRAINING_STUDIO_DATA': str(self.base / 'theirs')}):
            gitstate.local(self.base / 'my-trainings', folder='courses', name='field-team')
        found = self.check(path=str(self.base / 'my-trainings'))
        self.shape(found)
        self.assertEqual((found['ok'], found['found']), (True, {
            'name': 'field-team', 'folder': 'courses', 'branch': 'main', 'existing': True}))

    def test_a_folder_that_cannot_be_the_workspace_says_why(self):
        (self.base / 'a-file').write_text('Not a folder.\n')
        clone = self.base / 'their-clone'
        self.git('clone', '--quiet', str(self.bare()), str(clone), repo=self.base)
        for path, said in ((self.base / 'a-file', 'is a file. Name a folder'),
                           (clone, 'is a copy of a shared repository that someone works in'),
                           (helpers.SKILL, 'holds Training Studio itself')):
            with self.subTest(path=path):
                found = self.check(path=str(path))
                self.shape(found)
                self.assertEqual((found['ok'], found['checks'][0]['ok']), (False, False))
                self.assertIn(said, found['checks'][0]['fix'])
                self.assertEqual(found['checks'][1]['fix'],
                                 'This is looked at once the folder can be reached.')

    @unittest.skipIf(os.geteuid() == 0, 'the superuser can write anywhere')
    def test_a_folder_that_cannot_be_written_to_says_so(self):
        locked = self.base / 'locked'
        locked.mkdir()
        locked.chmod(stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(locked.chmod, stat.S_IRWXU)
        found = self.check(path=str(locked / 'my-trainings'))
        self.assertEqual([item['ok'] for item in found['checks']], [True, False, True, True])
        self.assertIn('cannot be written to by you', found['checks'][1]['fix'])

    def test_a_repository_nobody_has_set_up_can_be_used(self):
        remote = self.bare()
        found = self.check(repository=str(remote))
        self.shape(found)
        self.assertEqual((found['ok'], found['found']), (True, {
            'name': 'team-repo', 'folder': 'trainings', 'branch': 'main', 'existing': False}))
        self.assertEqual([item['what'] for item in found['checks']], [
            'The repository can be reached', 'The repository can be written to',
            'git knows who you are', 'The folder for trainings can be used'])
        self.assertEqual(self.git('for-each-ref', repo=remote), '', 'nothing was pushed')

    def test_a_repository_a_teammate_set_up_says_what_it_holds(self):
        remote = self.bare()
        self.someone_else(remote, folder='courses', name='field-team')
        before = self.git('for-each-ref', repo=remote)
        found = self.check(repository=str(remote))
        self.shape(found)
        self.assertEqual((found['ok'], found['found']), (True, {
            'name': 'field-team', 'folder': 'courses', 'branch': 'main', 'existing': True}))
        self.assertEqual(self.git('for-each-ref', repo=remote), before)
        other = self.check(repository=str(remote), branch='another')
        self.assertEqual((other['ok'], other['checks'][3]['ok']), (False, False))
        self.assertIn("says this workspace's work is on the branch main, not another",
                      other['checks'][3]['fix'])

    def test_a_folder_that_belongs_to_another_tool_is_not_taken(self):
        remote = self.bare()
        clone = self.base / 'their-clone'
        self.git('clone', '--quiet', str(remote), str(clone), repo=self.base)
        (clone / 'decks').mkdir()
        (clone / 'decks' / 'hub.json').write_text('{"tool": "another-tool", "schema": 1}\n')
        self.git('add', '-A', repo=clone)
        self.git('commit', '--quiet', '-m', 'Another tool', repo=clone)
        self.git('push', '--quiet', 'origin', 'HEAD:main', repo=clone)
        found = self.check(repository=str(remote), folder='decks')
        self.assertEqual([item['ok'] for item in found['checks']], [True, True, True, False])
        self.assertIn('belongs to another tool', found['checks'][3]['fix'])
        self.assertEqual(self.check(repository=str(remote))['found']['existing'], False)

    def test_a_repository_that_cannot_be_reached_says_how_to_put_it_right(self):
        found = self.check(repository=str(self.base / 'nowhere.git'))
        self.shape(found)
        self.assertEqual([item['ok'] for item in found['checks']], [False, False, True, False])
        self.assertIn('The repository could not be reached (', found['checks'][0]['fix'])
        self.assertIn('Check the address, and that git can sign in to it without asking',
                      found['checks'][0]['fix'])
        self.assertEqual(found['found'], {'name': 'nowhere', 'folder': 'trainings',
                                          'branch': 'main', 'existing': False})

    def test_an_address_that_carries_a_secret_is_never_used(self):
        from runner import setup
        real = setup.hub.run

        def local_only(repo, *args):
            self.assertNotIn(args[0], ('ls-remote', 'clone', 'push', 'fetch'))
            return real(repo, *args)

        with mock.patch.object(setup.hub, 'run', local_only):
            found = self.check(repository='https://someone:a-token@example.com/team/repo.git')
        self.assertEqual(found['ok'], False)
        self.assertIn('carries a password or token', found['checks'][0]['fix'])

    @unittest.skipIf(os.geteuid() == 0, 'the superuser can write anywhere')
    def test_a_repository_that_can_only_be_read_says_so(self):
        remote = self.bare()
        remote.chmod(stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(remote.chmod, stat.S_IRWXU)
        found = self.check(repository=str(remote))
        self.assertEqual([item['ok'] for item in found['checks']], [True, False, True, True])
        self.assertIn('may read that repository but not write to it',
                      found['checks'][1]['fix'])

    def test_a_check_that_makes_no_sense_is_refused(self):
        folder = str(self.base / 'my-trainings')
        for sent, said in (
                ({}, "Give the repository's address, or a folder on this computer."),
                ({'path': folder, 'repository': str(self.base / 'team-repo.git')},
                 'not both'),
                ({'path': 'my-trainings'}, "Give the folder's whole path"),
                ({'path': folder, 'folder': 'two words'}, 'A workspace folder is letters'),
                ({'path': folder, 'branch': '-b'}, 'cannot be the name of a branch'),
                ({'repository': ['a', 'list']}, 'Give the repository as text.')):
            with self.subTest(sent=sent):
                self.assertIn(said, self.check(400, **sent)['error'])


class AgentTests(PageCase):
    def test_each_agent_says_whether_it_can_be_used_now(self):
        away = agents.Readiness('codex', True, None, False, '0.162', 'Codex is signed in but '
                                'cannot be used from this network. Try another network.')
        with mock.patch.object(self.engine.adapters['codex'], 'ready',
                               return_value=away) as looked:
            first = self.get('agents')
            self.assertEqual(self.get('agents'), first, 'a look is reused for a while')
            looked.assert_called_once_with()
        self.assertEqual(first, {'agents': [
            {'agent': 'claude', 'installed': True, 'signed_in': True, 'reachable': True,
             'version': 'scripted', 'problem': None},
            {'agent': 'codex', 'installed': True, 'signed_in': None, 'reachable': False,
             'version': '0.162', 'problem': away.problem}]})
        self.assertEqual(self.workers.jobs, [], 'looking starts no agent')

    def test_a_training_is_not_started_on_an_agent_that_cannot_be_used(self):
        away = agents.Readiness('claude', False, problem='Claude Code is not installed. '
                                'Install it and sign in, then try again.')
        with mock.patch.object(self.engine.adapters['claude'], 'ready', return_value=away):
            said = self.post('trainings', FORM, 409)
        self.assertEqual(said['error'], away.problem)
        self.assertEqual(self.get('trainings')['trainings'], [])


class StartTests(PageCase):
    def test_the_form_starts_a_training_and_its_run_at_once(self):
        made = self.post('trainings', {**FORM, 'levels': ['101', '201'], 'agent': 'codex',
                                       'model': 'a-model', 'brief_kind': 'competitive',
                                       'deck_target': 'google', 'brand': CHOSEN,
                                       'copies': ['google'], 'yoodli': True})
        root = self.space.training('rolling-restarts')
        self.assertEqual(made, {'path': str(root), 'id': 'rolling-restarts', 'gates': 8})
        run = self.get('run', path=made['path'])
        self.assertEqual((run['state'], run['agent'], run['model']),
                         ('waiting', 'codex', 'a-model'))
        status = workspace.status(root)
        self.assertEqual((status['levels'], status['approval'], status['gate']),
                         (['101', '201'], 'page', 'research-plan'))
        self.assertEqual(status['settings'], {
            'approval': 'page', 'brand': 'example-co/light', 'brief_kind': 'competitive',
            'copies': ['google'], 'deck_target': 'google',
            'stages': ['document', 'brief', 'deck', 'scenario', 'yoodli']})
        self.assertEqual(self.post('trainings', {'title': 'Health checks', 'topic': 'Health '
                                                 'checks', 'audience': 'Operators',
                                                 'purpose': 'Upskilling'})['gates'], 5)

    def test_the_form_says_where_research_may_look(self):
        for scope, title in (('supplied-only', 'From documents'), ('both', 'From both')):
            with self.subTest(scope):
                path = self.started(source_scope=scope, title=title)
                run = self.get('run', path=path)
                self.assertEqual((run['state'], run['documents']['waiting']),
                                 ('waiting', True))
        self.assertIsNone(self.get('run', path=self.started())['documents'])
        self.assertEqual(len(self.workers.jobs), 1, 'only the last has started drafting')

    def test_a_form_with_no_deck_leaves_the_deck_out(self):
        without = Path(self.started(deck_target=None))
        wanted = Path(self.started(deck_target='pptx', title='Health checks'))
        self.assertEqual(('deck' in workspace.status(without)['settings']['stages'],
                          'deck' in workspace.status(wanted)['settings']['stages']),
                         (False, True))

    def test_a_form_that_makes_no_sense_starts_nothing(self):
        for changes, said in (
                ({'title': ''}, 'A training needs a title.'),
                ({'title': None}, 'A training needs a title.'),
                ({'topic': '  '}, 'A training needs a topic.'),
                ({'audience': None}, 'A training needs an audience.'),
                ({'purpose': None}, 'A training needs a purpose.'),
                ({'title': 'x' * 121}, 'Give the title as text of at most 120 characters.'),
                ({'time_limit': 30}, 'Give the time limit as text'),
                ({'levels': ['999']}, 'Levels are chosen from: 101, 201, 301, 401'),
                ({'levels': '101'}, 'Give levels as a list.'),
                ({'brief_kind': 'other'}, 'The brief kind is one of: product, competitive'),
                ({'deck_target': 'keynote'}, 'The deck target is one of: pptx, google'),
                ({'copies': ['pdf']}, 'Copies are any of: google, word; or none.'),
                ({'yoodli': 'yes'}, 'Say whether Yoodli scenarios are wanted'),
                ({'source_scope': 'everything'}, 'The source scope is one of: public-web, '
                 'supplied-only, both'),
                ({'agent': 'another'}, 'The agent is one of: claude, codex.'),
                ({'model': '--flag'}, 'The model is the short name')):
            with self.subTest(changes=changes):
                self.assertIn(said, self.post('trainings', {**FORM, **changes}, 400)['error'])
        self.assertEqual((self.get('trainings')['trainings'], self.workers.jobs), ([], []))
        self.assertFalse(self.space.training('rolling-restarts').exists())

    def test_the_workspace_cannot_be_moved_while_a_training_is_working_in_it(self):
        seen = []

        def looks(tools, job):
            seen.append(self.post('setup', {'path': str(self.base / 'elsewhere')}, 409))
            seen.append(self.post('setup', {'limits': {'parallel': 3}}))
            self.workers.research_plan(tools, job)

        self.workers.then('research-plan', looks)
        path = self.started()
        self.assertEqual(seen[0]['error'], 'Trainings are working in the workspace this '
                         'computer uses now. Pause or stop them before moving to another.')
        self.assertEqual((seen[1]['limits']['parallel'], seen[1]['workspace']['path']),
                         (3, str(self.space.repo)))
        self.assertFalse((self.base / 'elsewhere').exists())
        self.assertEqual((self.get('run', path=path)['state'], len(self.workers.jobs)),
                         ('waiting', 1))

    def test_a_second_training_with_the_same_title_is_refused(self):
        self.started()
        said = self.post('trainings', FORM, 409)
        self.assertIn('already has a training in trainings/rolling-restarts', said['error'])


class RunTests(PageCase):
    def test_a_run_is_described_field_for_field(self):
        self.workers.cost = 0.5
        run = self.get('run', path=self.started())
        self.assertEqual(sorted(run), RUN_KEYS)
        self.assertEqual((run['state'], run['agent'], run['model'], run['workers'],
                          run['question'], run['problem']),
                         ('waiting', 'claude', None, [], None, None))
        self.assertEqual(run['spent'], {'dollars': 0.5, 'tokens': 1200})
        self.assertIsInstance(run['sentence'], str)
        for step in run['steps']:
            self.assertEqual(sorted(step), STEP_KEYS)
            self.assertIn(step['kind'], ('code', 'agent', 'gate'))
            self.assertIn(step['status'], ('done', 'working', 'waiting', 'failed', 'to-do'))
            self.assertIsInstance(step['attempts'], int)
        self.assertEqual(run['steps'][1], {
            'id': 'research-plan', 'label': 'Draft the research plan', 'kind': 'agent',
            'status': 'done', 'attempts': 1, 'seconds': 1.5, 'dollars': 0.5, 'error': None})

    def test_a_question_and_a_problem_are_described_field_for_field(self):
        self.workers.then('research-plan', asks('Which platform is this about?'))
        asking = self.get('run', path=self.started())
        self.assertEqual(sorted(asking['question']), ['from', 'id', 'text'])
        self.workers.then('research-plan', fails(), fails(), fails())
        failing = self.get('run', path=self.started(title='Health checks'))
        self.assertEqual(sorted(failing['problem']), ['action', 'kept', 'label', 'what'])
        self.assertEqual((failing['state'], failing['problem']['action'],
                          failing['problem']['label']), ('failed', 'retry', 'Try again'))

    def test_a_run_is_shown_only_for_a_training_a_run_is_driving(self):
        said = self.get('run', 400)
        self.assertEqual(said['error'], 'Give one path.')
        said = self.get('run', 403, path=str(self.base / 'elsewhere'))
        self.assertEqual(said['error'], 'That folder is not a training this computer knows.')
        chat = self.base / 'started-in-a-chat'
        chat.mkdir()
        workspace.init(chat, 'Started in a chat')
        home.remember(chat, 'Started in a chat', [])
        said = self.get('run', 404, path=str(chat))
        self.assertEqual(said['error'], 'No run is driving this training.')
        for sent in ({'path': str(chat), 'action': 'pause'},):
            self.assertEqual(self.post('run', sent, 404)['error'],
                             'No run is driving this training.')
        self.assertEqual(self.post('answer', {'path': str(chat), 'id': 'x', 'answer': 'Yes.'},
                                   404)['error'], 'No run is driving this training.')

    def test_a_run_can_be_paused_resumed_stopped_and_tried_again(self):
        path, paused = str(self.space.training('rolling-restarts')), []

        def pauses(tools, job):
            paused.append(self.post('run', {'path': path, 'action': 'pause'}))
            self.workers.research_plan(tools, job)

        self.workers.then('research-plan', pauses)
        self.assertEqual(self.started(), path)
        self.assertEqual((sorted(paused[0]), paused[0]['state'], paused[0]['workers'][0]['id']),
                         (RUN_KEYS, 'paused', 'research-plan'))
        self.assertEqual(self.get('run', path=path)['state'], 'paused')
        self.assertEqual(self.post('run', {'path': path, 'action': 'resume'})['state'],
                         'waiting')
        self.assertEqual(self.post('run', {'path': path, 'action': 'stop'})['state'],
                         'stopped')
        self.assertEqual(self.post('run', {'path': path, 'action': 'resume'})['state'],
                         'waiting')
        self.workers.then('research-plan', fails(), fails(), fails())
        failed = self.started(title='Health checks')
        self.assertEqual(self.get('run', path=failed)['state'], 'failed')
        again = self.post('run', {'path': failed, 'action': 'retry'})
        self.assertEqual((again['state'], again['problem']), ('waiting', None))

    def test_what_a_run_cannot_be_asked_is_refused_in_a_sentence(self):
        path = self.started()
        for sent, expect, said in (
                ({'path': path, 'action': 'restart'}, 400,
                 'A run can be asked to: pause, resume, stop, retry.'),
                ({'path': path}, 400, 'Give action as text.'),
                ({'action': 'pause'}, 400, 'Give path as text.'),
                ({'path': path, 'action': 'pause'}, 409, 'Only a training that is working '
                 'can be paused. This one is waiting for you.'),
                ({'path': path, 'action': 'resume'}, 409, 'This training is not paused or '
                 'stopped, so there is nothing to resume.'),
                ({'path': path, 'action': 'retry'}, 409, 'Nothing here failed, so there is '
                 'nothing to try again.'),
                ({'path': str(self.base / 'elsewhere'), 'action': 'pause'}, 403,
                 'That folder is not a training this computer knows.')):
            with self.subTest(sent=sent):
                self.assertEqual(self.post('run', sent, expect)['error'], said)
        self.assertEqual(self.get('run', path=path)['state'], 'waiting')

    def test_a_workers_question_is_answered_on_the_page(self):
        self.workers.then('research-plan', asks('Which platform is this about?'))
        path = self.started()
        asked = self.get('run', path=path)['question']
        for sent, expect, said in (
                ({'path': path, 'id': asked['id'], 'answer': ''}, 400, 'Give answer as text.'),
                ({'path': path, 'id': asked['id'], 'answer': '  \n'}, 400,
                 'Write an answer first.'),
                ({'path': path, 'answer': 'The public one.'}, 400, 'Give id as text.'),
                ({'path': path, 'id': 'another', 'answer': 'The public one.'}, 409,
                 'That question is not waiting for an answer any more.')):
            with self.subTest(sent=sent):
                self.assertEqual(self.post('answer', sent, expect)['error'], said)
        self.assertEqual(len(self.workers.jobs), 1)
        after = self.post('answer', {'path': path, 'id': asked['id'],
                                     'answer': 'The public one.'})
        self.assertEqual((sorted(after), after['state'], after['question']),
                         (RUN_KEYS, 'waiting', None))
        self.assertIn('Answer: The public one.', self.workers.jobs[-1][1].task)

    def test_sharing_says_whether_the_work_is_shared(self):
        said = self.post('share', {})
        self.assertEqual((sorted(said), said['shared']), (['notice', 'shared'], False))
        self.assertIn('no shared repository', said['notice'])


class ListTests(PageCase):
    """What milestone 1's lists gain."""

    def chat(self) -> Path:
        root = self.base / 'started-in-a-chat'
        root.mkdir()
        workspace.init(root, 'Started in a chat')
        home.remember(root, 'Started in a chat', [])
        return root

    def listed(self) -> dict:
        return {item['title']: item for item in self.get('trainings')['trainings']}

    def test_each_training_carries_its_run_or_none(self):
        path, chat = self.started(), self.chat()
        listed = self.listed()
        self.assertEqual(listed['Rolling restarts']['run'], {
            'state': 'waiting', 'sentence': 'The research plan is waiting for your review.'})
        self.assertIsNone(listed['Started in a chat']['run'])
        self.assertEqual(self.get('training', path=path)['run'],
                         listed['Rolling restarts']['run'])
        self.assertIsNone(self.get('training', path=str(chat))['run'])
        gate = listed['Rolling restarts']
        self.assertEqual((gate['state'], gate['waiting']['artifact'], gate['approval']),
                         ('needs-you', 'research-plan', 'page'))
        self.assertEqual(self.get('trainings')['needs'], 1)

    def test_a_run_with_a_question_counts_as_needing_the_person(self):
        self.workers.then('research-plan', asks('Which platform is this about?'))
        path = self.started()
        found = self.get('trainings')
        item = found['trainings'][0]
        self.assertEqual((found['needs'], item['state'], item['sentence']), (
            1, 'needs-you', 'A question is waiting for you: Which platform is this about?'))
        self.assertEqual(item['waiting'], {'artifact': None, 'label': None, 'recorded': False,
                                           'question': 'Which platform is this about?'})
        self.assertEqual(item['run']['state'], 'waiting')
        detail = self.get('training', path=path)
        self.assertEqual((detail['state'], detail['run']), ('needs-you', item['run']))
        self.assertEqual(desk.next_up(self.page.trainings()), {
            'path': path, 'title': 'Rolling restarts', 'artifact': None,
            'sentence': item['sentence']})

    def test_a_run_with_a_problem_counts_as_needing_the_person(self):
        self.workers.then('research-plan', fails(), fails(), fails())
        self.started()
        found = self.get('trainings')
        item = found['trainings'][0]
        self.assertEqual((found['needs'], item['state'], item['run']['state']),
                         (1, 'needs-you', 'failed'))
        self.assertTrue(item['sentence'].startswith('This step did not work in 3 tries'))
        self.assertEqual(item['waiting']['question'], None)

    def test_a_run_that_is_only_halted_does_not_need_the_person(self):
        path = self.started()
        self.post('run', {'path': path, 'action': 'stop'})
        self.post('decide', {'path': path, 'artifact': 'research-plan', 'decision': 'approve',
                             'seen': workspace.sha256_file(Path(path) / pipeline.PLAN)})
        found = self.get('trainings')
        item = found['trainings'][0]
        self.assertEqual((found['needs'], item['state'], item['run'], item['sentence']), (
            0, 'in-progress', {'state': 'stopped', 'sentence': 'Stopped. Everything kept so '
                               'far is still here.'},
            'Stopped. Everything kept so far is still here.'))

    def test_reading_never_starts_or_wakes_a_run(self):
        self.workers.then('research-plan', fails(), fails(), fails(), asks('Which platform?'))
        failed = self.started()
        asking = self.started(title='Health checks')
        chat = self.chat()
        before, jobs = self.on_disk(), len(self.workers.jobs)
        for _ in range(3):
            self.get('trainings')
            for path in (failed, asking):
                self.get('run', path=path)
                self.get('training', path=path)
            self.get('training', path=str(chat))
            self.get('setup')
            self.get('capabilities')
        self.assertEqual((self.on_disk(), len(self.workers.jobs)), (before, jobs))
        self.assertEqual([self.get('run', path=path)['state'] for path in (failed, asking)],
                         ['failed', 'waiting'])


class DecideTests(PageCase):
    def approve(self, path: str, name: str, expect: int = 200) -> dict:
        root = Path(path)
        file = root / workspace.artifact(root, workspace.load(root), name)['file']
        return self.post('decide', {'path': path, 'artifact': name, 'decision': 'approve',
                                    'seen': workspace.sha256_file(file)}, expect)

    def test_the_last_approval_says_the_training_is_finished_and_says_approved_once(self):
        path = self.started()
        for name in ('research-plan', 'research', 'blueprint', 'document', 'brief'):
            self.approve(path, name)
        said = self.approve(path, 'scenario:main')
        self.assertEqual(said['said'], 'Approved. This training is finished, with 1 thing '
                         'left out or limited.')
        self.assertIsNone(said['next'])
        self.assertEqual(self.get('run', path=path)['state'], 'done')

    def test_the_last_approval_before_the_deck_says_the_deck_is_all_that_is_left(self):
        path = self.started(deck_target='pptx')
        for name in ('research-plan', 'research', 'blueprint', 'document', 'brief'):
            self.approve(path, name)
        said = self.approve(path, 'scenario:main')
        self.assertEqual(said['said'], f'Approved. {left(pipeline.DECK_LEFT)}')
        run = self.get('run', path=path)
        self.assertEqual((run['state'], run['deck_left']), (
            'done', {'says': left(pipeline.DECK_LEFT), 'artifact': 'deck'}))
        item = self.get('trainings')['trainings'][0]
        self.assertEqual((item['state'], item['run']['state'], item['sentence']),
                         ('in-progress', 'done', left(pipeline.DECK_LEFT)))
        open_stages = [stage['stage'] for stage in item['stages']
                       if stage['state'] not in ('done', 'left-out')]
        self.assertEqual(open_stages, ['deck', 'package'],
                         'the deck is the only stage left besides the wrap-up')
        said = self.post('decide', {'path': path, 'artifact': run['deck_left']['artifact'],
                                    'decision': 'skip', 'note': 'No slides for this one.'})
        self.assertEqual(said['said'], 'This stage is left out. You can bring it back from '
                         'the training at any time. This training is finished, with 1 thing '
                         'left out or limited.')
        item = self.get('trainings')['trainings'][0]
        self.assertEqual((item['state'], item['run']['state']), ('finished', 'done'))
        self.assertEqual(self.get('run', path=path)['finished']['index'], 'README.md')

    def test_a_decision_made_through_the_desks_own_address_wakes_the_run(self):
        path = self.started()
        gate = self.get('gate', path=path, artifact='research-plan')
        self.assertEqual((gate['waiting'], gate['decisions'][0], gate['question']),
                         (True, 'approve', 'Approve the research plan?'))
        self.assertIn('Checked for you: 1 check passed.', gate['review'])
        said = self.approve(path, 'research-plan')
        self.assertEqual(said['decided']['by'], 'page')
        self.assertEqual(said['said'],
                         'Approved. The research report is waiting for your review.')
        for word in ('assistant', 'conversation'):
            self.assertNotIn(word, said['said'])
        self.assertEqual(said['next'], {
            'path': path, 'title': 'Rolling restarts', 'artifact': 'research',
            'sentence': 'The research report is waiting for your review.'})
        self.assertEqual(len(self.workers.of('question')), 4)
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertIn('Rolling restarts: The research plan was approved on the page.',
                      self.log())

    def test_a_decision_the_desk_refuses_changes_nothing_and_wakes_nothing(self):
        path = self.started()
        before = self.on_disk()
        said = self.post('decide', {'path': path, 'artifact': 'research-plan',
                                    'decision': 'approve', 'seen': 'another-version'}, 409)
        self.assertIn('has changed since it was opened', said['error'])
        self.post('decide', {'path': path, 'artifact': 'research-plan',
                             'decision': 'revise'}, 409)
        self.assertEqual((self.on_disk(), len(self.workers.jobs)), (before, 1))

    def test_a_training_no_run_is_driving_is_decided_as_the_desk_always_did(self):
        chat = self.base / 'started-in-a-chat'
        chat.mkdir()
        workspace.init(chat, 'Started in a chat', approval='page')
        home.remember(chat, 'Started in a chat', [])
        said = self.post('decide', {'path': str(chat), 'artifact': 'deck', 'decision': 'skip',
                                    'note': 'No slides.'})
        self.assertEqual(said['said'], f"{desk.SAID['skip']} {desk.BACK_TO_CHAT}")
        self.assertEqual(self.post('approval', {'path': str(chat), 'mode': 'chat'}),
                         {'approval': 'chat'})

    def test_decisions_cannot_be_moved_to_a_conversation_while_a_run_is_driving(self):
        path = self.started()
        said = self.post('approval', {'path': path, 'mode': 'chat'}, 409)
        self.assertEqual(said['error'], 'The runner is driving this training, so its '
                         'decisions are made on the page.')
        self.assertEqual(workspace.status(Path(path))['approval'], 'page')
        self.assertEqual(self.post('approval', {'path': path, 'mode': 'page'}),
                         {'approval': 'page'})
        self.to_end(Path(path))
        self.assertEqual(self.get('run', path=path)['state'], 'done')
        self.assertEqual(self.post('approval', {'path': path, 'mode': 'chat'}),
                         {'approval': 'chat'})
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertEqual(self.log()[-1],
                         'Rolling restarts: decisions are now made in the conversation')


class LaterTests(PageCase):
    """What milestone 3 adds: the person's documents, the copies, what a gate gains, and
    the index read as a file."""

    def sent(self, text: str = 'Capacity holds only when more than one instance is '
             'running.\n') -> str:
        return base64.b64encode(text.encode('utf-8')).decode('ascii')

    def test_documents_are_added_removed_and_settled_on_the_page(self):
        path = self.started(source_scope='supplied-only')
        run = self.post('documents', {'path': path, 'action': 'add', 'name': 'handbook.txt',
                                      'content': self.sent()})
        self.assertEqual(sorted(run), RUN_KEYS)
        self.assertEqual(sorted(run['documents']),
                         ['added', 'limits', 'note', 'types', 'waiting'])
        self.assertEqual(run['documents']['added'], [
            {'name': 'handbook.txt', 'bytes': 60, 'readable': True, 'problem': None}])
        self.assertEqual((run['documents']['types'][1], run['documents']['limits']),
                         ('.md', {'bytes': 8_000_000, 'files': 40}))
        self.post('documents', {'path': path, 'action': 'add', 'name': 'notes.md',
                                'content': self.sent('Notes.\n')})
        run = self.post('documents', {'path': path, 'action': 'remove', 'name': 'notes.md'})
        self.assertEqual([entry['name'] for entry in run['documents']['added']],
                         ['handbook.txt'])
        item = self.get('trainings')['trainings'][0]
        self.assertEqual((item['state'], item['run']['state'], self.get('trainings')['needs']),
                         ('needs-you', 'waiting', 1),
                         'a run that waits for documents needs its person')
        self.assertEqual(self.workers.jobs, [])
        run = self.post('documents', {'path': path, 'action': 'done'})
        self.assertEqual((run['documents']['waiting'], run['documents']['added'][0]['name'],
                          len(self.workers.jobs)), (False, 'handbook.txt', 1))
        self.assertEqual(self.get('run', path=path)['documents']['waiting'], False,
                         'the documents stay shown once they are settled')

    def test_what_makes_no_sense_about_a_document_is_refused_in_a_sentence(self):
        path = self.started(source_scope='both')
        web = self.started(title='Health checks')
        add = {'path': path, 'action': 'add', 'name': 'handbook.txt', 'content': self.sent()}
        for sent, expect, said in (
                ({**add, 'action': 'replace'}, 400, 'A document can be: add, remove, done.'),
                ({'path': path}, 400, 'Give action as text.'),
                ({'action': 'done'}, 400, 'Give path as text.'),
                ({**add, 'name': None}, 400, 'Give name as text.'),
                ({**add, 'content': None}, 400, 'Give content as text.'),
                ({**add, 'content': ['V29yZHMu']}, 400, 'Give content as text.'),
                ({'path': path, 'action': 'remove'}, 400, 'Give name as text.'),
                ({**add, 'content': 'not base64!'}, 400, 'That document did not arrive '
                 'whole. Add it again.'),
                ({**add, 'name': 'notes.pdf'}, 409, 'notes.pdf is not a kind of document '
                 'that can be read here. Save it as text or as a Word file.'),
                ({'path': path, 'action': 'remove', 'name': 'missing.txt'}, 409,
                 'missing.txt is not one of the documents added.'),
                ({**add, 'path': web}, 409, 'This training is researched from the public '
                 'web, so it takes no documents.'),
                ({**add, 'path': str(self.base / 'elsewhere')}, 403,
                 'That folder is not a training this computer knows.')):
            with self.subTest(sent=sent):
                self.assertEqual(self.post('documents', sent, expect)['error'], said)
        self.assertEqual(self.get('run', path=path)['documents']['added'], [])
        chat = self.base / 'started-in-a-chat'
        chat.mkdir()
        workspace.init(chat, 'Started in a chat')
        home.remember(chat, 'Started in a chat', [])
        for endpoint, sent in (('documents', {**add, 'path': str(chat)}),
                               ('copies', {'path': str(chat)})):
            self.assertEqual(self.post(endpoint, sent, 404)['error'],
                             'No run is driving this training.')

    def test_only_a_document_sent_with_the_key_may_be_larger_than_any_other_change(self):
        headers = self.headers()
        self.assertEqual(page.DOCUMENT_LIMIT, 12_000_000)
        self.assertGreater(page.DOCUMENT_LIMIT, 8_000_000 * 4 // 3,
                           'the largest document fits once it is in base64')
        self.assertEqual(self.page.body_limit('/api/documents', headers), 12_000_000)
        self.assertEqual(self.page.body_limit('/api/documents?x=1', headers), 12_000_000)
        for token in (False, 'not-the-key'):
            self.assertEqual(self.page.body_limit('/api/documents', self.headers(token=token)),
                             desk.BODY_LIMIT, 'a stranger is never read at length')
        for target in (*desk.WRITES, *(path for path in POSTS if path != '/api/documents'),
                       '/api/documents/more', '/api/nothing', '/', '//[', ''):
            self.assertEqual(self.page.body_limit(target, headers), 64_000, target)
        self.assertEqual(desk.Page(self.PORT).body_limit('/api/documents', headers), 64_000,
                         'the plain desk takes nothing larger at any address')
        status, said, _ = self.answer('POST', '/api/documents', None, origin=self.origin,
                                      kind='application/json')
        self.assertEqual((status, said['error']), (413, 'A change is at most 12,000,000 '
                         'bytes, with its length stated.'))
        status, said, _ = self.answer('POST', '/api/copies', None, origin=self.origin,
                                      kind='application/json')
        self.assertEqual((status, said['error']), (413, 'A change is at most 64,000 bytes, '
                         'with its length stated.'))

    def test_a_document_of_the_largest_size_is_taken(self):
        path = self.started(source_scope='both')
        large = 'A line of a long handbook.\n' * 280_000
        self.assertGreater(len(large), 7_500_000)
        run = self.post('documents', {'path': path, 'action': 'add', 'name': 'handbook.txt',
                                      'content': self.sent(large)})
        self.assertEqual(run['documents']['added'][0]['bytes'], len(large))

    def test_the_copies_are_made_again_on_the_page(self):
        self.copies.refuse['google'] = 'Google access is not set up on this computer.'
        path = self.started(copies=['google'])
        self.to_gate(Path(path), 'brief')
        shown = self.get('run', path=path)['copies']
        self.assertEqual(shown[0], {
            'artifact': 'document', 'label': 'the learner guide', 'kind': 'google',
            'state': 'not-made', 'link': None,
            'problem': 'Google access is not set up on this computer.'})
        self.copies.refuse.clear()
        run = self.post('copies', {'path': path})
        self.assertEqual(sorted(run), RUN_KEYS)
        self.assertEqual([(entry['artifact'], entry['state'], entry['link'], entry['problem'])
                          for entry in run['copies']], [
            ('document', 'made', 'https://docs.example.com/d/doc1/edit', None)],
            'the brief is not approved yet, so there is no copy of it to show')
        self.assertEqual(self.post('copies', {}, 400)['error'], 'Give path as text.')

    def test_a_scenarios_gate_says_whose_file_it_is(self):
        path = self.started()
        root = Path(path)
        self.to_gate(root, 'blueprint')
        (root / 'scenarios').mkdir()
        (root / 'scenarios' / 'objection.md').write_text(SCENARIO)
        self.to_gate(root, 'scenario:main')
        self.assertEqual(self.get('gate', path=path, artifact='scenario:main')['whose'],
                         'runner')
        theirs = self.get('gate', path=path, artifact='scenario:objection')
        self.assertEqual((theirs['whose'], theirs['label']),
                         ('you', 'The practice scenario "objection"'))
        self.assertNotIn('whose', self.get('gate', path=path, artifact='document'))
        chat = self.base / 'started-in-a-chat'
        chat.mkdir()
        workspace.init(chat, 'Started in a chat')
        home.remember(chat, 'Started in a chat', [])
        (chat / 'scenario.md').write_text(SCENARIO)
        self.assertIsNone(self.get('gate', path=str(chat), artifact='scenario:main')['whose'],
                          'with no run, nobody recorded who wrote it')

    def test_a_yoodli_scenarios_gate_names_the_scenario_to_show_beside_it(self):
        path = self.started(yoodli=True, levels=['101'])
        self.to_gate(Path(path), 'yoodli:main@101')
        shown = self.get('gate', path=path, artifact='yoodli:main@101')
        self.assertEqual(shown['beside'], {'artifact': 'scenario:main@101',
                                           'label': 'The level 101 practice scenario'})
        self.assertNotIn('whose', shown)
        beside = self.get('file', path=path, artifact=shown['beside']['artifact'])
        self.assertEqual((beside['file'], beside['text']), ('101/scenario.md', SCENARIO))
        self.assertIn('Which goal carries each success criterion', shown['review'])

    def test_the_index_is_read_as_a_file_once_it_is_written(self):
        path = self.started()
        said = self.get('file', 404, path=path, artifact='README.md')
        self.assertEqual(said['error'], 'The index has not been written yet.')
        self.to_end(Path(path))
        run = self.get('run', path=path)
        shown = self.get('file', path=path, artifact=run['finished']['index'])
        self.assertEqual(sorted(shown), ['artifact', 'binary', 'file', 'size', 'text',
                                         'truncated'])
        self.assertEqual((shown['artifact'], shown['file'], shown['binary'],
                          shown['truncated'], shown['text']),
                         ('README.md', 'README.md', False, False,
                          (Path(path) / 'README.md').read_text()))
        for artifact, expect in (('notes.md', 403), ('../README.md', 403),
                                 ('reviews/document.md', 403)):
            self.get('file', expect, path=path, artifact=artifact)
        said = self.get('file', 403, path=str(self.base / 'elsewhere'), artifact='README.md')
        self.assertEqual(said['error'], 'That folder is not a training this computer knows.')
        (Path(path) / 'README.md').unlink()
        (Path(path) / 'README.md').symlink_to(self.base / 'gitconfig')
        self.get('file', 403, path=path, artifact='README.md')


class WireCase(StudioCase):
    """The runner's server on a port the system chose."""

    def setUp(self):
        super().setUp()
        for patcher in (mock.patch.object(computer, 'run', never),
                        mock.patch.object(computer, 'reach', never)):
            patcher.start()
            self.addCleanup(patcher.stop)
        try:
            self.server = page.Studio(self.engine)
        except PermissionError as refused:
            self.skipTest(f'This environment does not allow listening on a local port: {refused}')
        self.addCleanup(self.server.stop)
        self.server.start()
        self.origin = f'http://127.0.0.1:{self.server.port}'

    def ask(self, target: str, sent=None, method: str | None = None, token: bool = True,
            **headers):
        headers = {name.replace('_', '-'): value for name, value in headers.items()}
        if token:
            headers[desk.TOKEN_HEADER] = self.server.token
        body = None
        if sent is not None:
            body = json.dumps(sent).encode()
            headers = {'Origin': self.origin, 'Content-Type': 'application/json', **headers}
        request = urllib.request.Request(self.origin + target, data=body, headers=headers,
                                         method=method or ('POST' if body else 'GET'))
        try:
            with DIRECT.open(request, timeout=20) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as refused:
            with refused:
                return refused.code, refused.headers, refused.read()


class WireTests(WireCase):
    def test_the_page_and_the_runner_are_served_together(self):
        status, headers, body = self.ask('/', token=False)
        self.assertEqual((status, headers.get_content_type()), (200, 'text/html'))
        self.assertEqual(body, (desk.PAGE_DIR / 'index.html').read_bytes())
        status, headers, body = self.ask('/api/capabilities')
        self.assertEqual((status, json.loads(body)),
                         (200, {'runner': True, 'version': VERSION}))
        self.assertEqual(headers['Content-Security-Policy'],
                         "default-src 'self'; img-src 'self' blob:")
        self.assertEqual(self.ask('/api/capabilities', token=False)[0], 403)
        self.assertTrue(self.server.url.endswith(f'#token={self.server.token}'))
        self.assertNotIn(self.server.token, self.server.address)

    def test_a_training_is_started_decided_and_watched_over_the_wire(self):
        status, _, body = self.ask('/api/trainings', FORM)
        self.assertEqual(status, 200, body)
        path = json.loads(body)['path']
        run = json.loads(self.ask('/api/run?' + urlencode({'path': path}))[2])
        self.assertEqual((run['state'], sorted(run)), ('waiting', RUN_KEYS))
        seen = workspace.sha256_file(Path(path) / pipeline.PLAN)
        status, _, body = self.ask('/api/decide', {
            'path': path, 'artifact': 'research-plan', 'decision': 'approve', 'seen': seen})
        self.assertEqual(status, 200, body)
        self.assertEqual(workspace.status(Path(path))['gate'], 'research')
        listed = json.loads(self.ask('/api/trainings')[2])
        self.assertEqual((listed['needs'], listed['trainings'][0]['run']['state']),
                         (1, 'waiting'))

    def test_a_change_without_the_key_the_origin_or_json_is_refused_over_the_wire(self):
        before = len(self.engine.trainings())
        for label, expect, options in (
                ('no key', 403, {'token': False}),
                ('another origin', 403, {'Origin': 'http://example.com'}),
                ('a form', 415, {'Content_Type': 'application/x-www-form-urlencoded'}),
                ('another host', 403, {'Host': 'example.com'})):
            with self.subTest(label):
                status, headers, body = self.ask('/api/trainings', FORM, **options)
                self.assertEqual(status, expect, body)
                self.assertEqual(headers.get_content_type(), 'application/json')
                self.assertEqual(headers['X-Frame-Options'], 'DENY')
                self.assertIn('error', json.loads(body))
        for method in ('PUT', 'DELETE', 'PATCH'):
            status, headers, _ = self.ask('/api/run', FORM, method=method)
            self.assertEqual((status, headers['Allow']), (405, 'GET, POST'))
        status, headers, _ = self.ask('/api/share', method='GET')
        self.assertEqual((status, headers['Allow']), (405, 'POST'))
        self.assertEqual((len(self.engine.trainings()), self.workers.jobs), (before, []))

    def test_something_that_cannot_be_done_is_answered_with_a_sentence_and_409(self):
        path = json.loads(self.ask('/api/trainings', FORM)[2])['path']
        status, _, body = self.ask('/api/run', {'path': path, 'action': 'retry'})
        self.assertEqual((status, json.loads(body)), (409, {
            'error': 'Nothing here failed, so there is nothing to try again.'}))
        status, _, body = self.ask('/api/trainings', {**FORM, 'source_scope': 'the-moon'})
        self.assertEqual((status, json.loads(body)['error']), (400, 'The source scope is one '
                         'of: public-web, supplied-only, both'))

    def test_a_document_is_the_only_long_body_and_only_with_the_key(self):
        path = json.loads(self.ask('/api/trainings', {**FORM, 'source_scope': 'both'})[2])[
            'path']
        # Just over what any other change may carry. A body refused unread has to fit in
        # what the connection holds, or the sender never gets to read the refusal.
        over = base64.b64encode(b'A line of a long handbook.\n' * 2_000).decode('ascii')
        self.assertGreater(len(over), desk.BODY_LIMIT)
        sent = {'path': path, 'action': 'add', 'name': 'handbook.txt', 'content': over}
        for label, expect, options in (
                ('no key', 403, {'token': False}),
                ('another origin', 403, {'Origin': 'http://example.com'}),
                ('a form', 415, {'Content_Type': 'application/x-www-form-urlencoded'}),
                ('another host', 403, {'Host': 'example.com'})):
            with self.subTest(label):
                status, _, body = self.ask('/api/documents', sent, **options)
                self.assertEqual(status, expect, body)
        self.assertEqual(self.documents.listed(Path(path)), [])
        status, _, body = self.ask('/api/documents', sent)
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)['documents']['added'][0]['bytes'], 27 * 2_000)
        for target in ('/api/answer', '/api/copies', '/api/decide', '/api/run'):
            status, _, body = self.ask(target, {'path': path, 'id': over, 'answer': over})
            self.assertEqual((status, json.loads(body)['error']), (413, 'A change is at most '
                             '64,000 bytes, with its length stated.'), target)
        large = base64.b64encode(b'A line of a long handbook.\n' * 150_000).decode('ascii')
        status, _, body = self.ask('/api/documents', {**sent, 'name': 'longer.txt',
                                                      'content': large})
        self.assertEqual((status, json.loads(body)['documents']['added'][1]['bytes']),
                         (200, 27 * 150_000), body[:200])

    def test_stopping_the_server_ends_the_engine(self):
        self.server.stop()
        self.assertTrue(self.engine._closing)


class LiveWireTests(WireCase):
    """The whole of it as the runner serves it: threads of its own, and a real connection."""

    BACKGROUND = True

    def run_of(self, path: str) -> dict:
        return json.loads(self.ask('/api/run?' + urlencode({'path': path}))[2])

    def until(self, path: str, check, seconds: float = 60) -> dict:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            run = self.run_of(path)
            if check(run):
                return run
            time.sleep(0.05)
        self.fail(f'It did not happen in time: {run}')

    def test_a_training_goes_from_the_form_to_finished_on_the_page(self):
        status, _, body = self.ask('/api/trainings', {**FORM, 'levels': ['101', '201']})
        self.assertEqual(status, 200, body)
        made = json.loads(body)
        path, root, decided = made['path'], Path(made['path']), 0
        for gate in ('research-plan', 'research', 'blueprint@101', 'blueprint@201',
                     'document@101', 'brief@101', 'scenario:main@101', 'document@201',
                     'brief@201', 'scenario:main@201'):
            self.until(path, lambda run: run['state'] == 'waiting'
                       and workspace.status(root)['gate'] == gate)
            shown = json.loads(self.ask('/api/gate?' + urlencode(
                {'path': path, 'artifact': gate}))[2])
            self.assertEqual((shown['waiting'], shown['decisions'][0]), (True, 'approve'))
            status, _, body = self.ask('/api/decide', {
                'path': path, 'artifact': gate, 'decision': 'approve',
                'seen': shown['sha256']})
            self.assertEqual(status, 200, body)
            decided += 1
        done = self.until(path, lambda run: run['state'] == 'done')
        self.assertEqual((decided, made['gates']), (10, 8))
        self.assertEqual({step['status'] for step in done['steps']}, {'done'})
        self.assertEqual((done['workers'], done['finished']['ready']), ([], True))
        self.assertEqual(len(self.workers.jobs), 13)
        self.until(path, lambda run: self.git('status', '--porcelain') == '')
        approved = [line for line in self.log() if line.endswith('approved on the page.')]
        self.assertEqual(len(approved), 10)
        status, _, body = self.ask('/api/file?' + urlencode(
            {'path': path, 'artifact': done['finished']['index']}))
        self.assertEqual((status, json.loads(body)['text'].splitlines()[0]),
                         (200, '# Rolling restarts'))


class PlainDeskTests(unittest.TestCase):
    def test_the_desk_still_serves_without_the_runner(self):
        try:
            plain = desk.Desk()
        except PermissionError as refused:
            self.skipTest(f'This environment does not allow listening on a local port: {refused}')
        self.addCleanup(plain.stop)
        plain.start()
        self.assertIs(type(plain.page), desk.Page)
        request = urllib.request.Request(f'http://127.0.0.1:{plain.port}/api/capabilities',
                                         headers={desk.TOKEN_HEADER: plain.token})
        with self.assertRaises(urllib.error.HTTPError) as refused:
            DIRECT.open(request, timeout=20)
        with refused.exception:
            self.assertEqual(refused.exception.code, 404)


class SettingsTests(StudioCase):
    """What this computer remembers for the runner."""

    def test_the_defaults_are_used_until_something_is_saved(self):
        self.assertEqual(settings.load(), settings.Settings('claude', None, 900, 20.0, 2))
        kept = settings.save(replace(settings.load(), agent='codex', parallel=4))
        self.assertEqual((settings.load(), kept.limits), (kept, {
            'step_seconds': 900, 'training_dollars': 20.0, 'parallel': 4}))
        self.assertEqual(settings.path().parent, home.data_root())
        self.assertNotIn(self.space.repo, settings.path().parents)

    def test_a_file_that_cannot_be_used_reads_as_the_defaults(self):
        for text in ('not json', '{"schema": 2, "agent": "codex"}',
                     '{"schema": 1, "agent": "another"}', '{"schema": 1, "parallel": 99}'):
            settings.path().write_text(text)
            self.assertEqual(settings.load(), settings.Settings())
        settings.path().write_text('{"schema": 1, "agent": "codex", "extra": true}')
        self.assertEqual(settings.load().agent, 'codex')


if __name__ == '__main__':
    unittest.main()
