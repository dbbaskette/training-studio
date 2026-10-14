"""Deleting a training: who may, a working one stopped first, what goes and what stays,
teammates learning of it, a teammate taking it at the same moment, and the page's addresses.

Each test is a row of the table in milestone 5, section 9. Nothing starts an agent or
touches the network: workers are scripted, and a team is two data folders against one bare
repository.
"""
import json
import threading
import time
from dataclasses import replace
from email.message import Message
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

import helpers  # noqa: F401
from runner_support import (FORM, LEAVES, StudioCase, TeamCase, still_running, written)

import desk
import home
import workspace
from runner import agents, companion, engine as engines, gitstate, page, pipeline, settings
from runner import team
from workspace import WorkspaceError

DELETED = r'^Rolling restarts: {name} deletes this training, on \d{{4}}-\d\d-\d\d at \d\d:\d\d UTC$'
STARTED = 'Rolling restarts: start the training from the form'
LEAVING = ['documents', 'drive', 'may', 'path', 'revisions', 'share', 'state', 'stops',
           'title', 'why']


def title(root: Path) -> str:
    return workspace.load(root)['title']


class Deleting:
    """What a test needs to delete a training as the page does, and to look for what is
    left of it."""

    def deleted(self, root: Path, engine=None) -> dict:
        return (engine or self.engine).delete(root, title(root))

    def plant(self, root: Path) -> None:
        """What this computer keeps for a training outside its folder, and a little of
        another training's beside it."""
        jobs = agents.staging()
        jobs.mkdir(parents=True, exist_ok=True)
        (jobs / f'{root.name}--blueprint-1-abcdef').mkdir()
        (jobs / f'{root.name}-2--blueprint-1-abcdef').mkdir()
        team.keep('notified', {str(root): 'gate:blueprint:abc', '/elsewhere': 'gate:x'})
        team.keep('taken', {str(root): {'name': None, 'at': None, 'kept': None}})
        (root / 'sources').mkdir(exist_ok=True)
        (root / 'sources' / 'page.html').write_text('A saved page.\n')
        (root / 'work').mkdir(exist_ok=True)
        (root / 'work' / 'slide-1.png').write_bytes(b'not really a picture')

    def nothing_left(self, root: Path, engine=None) -> None:
        engine = engine or self.engine
        jobs = agents.staging()
        self.assertFalse(root.exists(), 'the folder and everything only kept here are gone')
        self.assertEqual(sorted(path.name for path in jobs.iterdir()),
                         [f'{root.name}-2--blueprint-1-abcdef'])
        self.assertEqual(team.kept('notified'), {'/elsewhere': 'gate:x'})
        self.assertEqual(team.kept('taken'), {})
        self.assertNotIn(str(root), [entry['path'] for entry in home.trainings()])
        self.assertNotIn(str(root), json.loads(home.registry_path().read_text())['trainings'])
        self.assertEqual((engine.trainings(), engine.status(), engine.view(root)),
                         ([], {'trainings': []}, None))
        self.assertEqual(engine.standing()['runs'], [])
        self.assertNotIn(str(root), engine._runs)


class DeleteTests(Deleting, StudioCase):
    """One person, a workspace on this computer."""

    def test_a_paused_training_is_deleted_with_everything_this_computer_kept_for_it(self):
        def pauses(tools, job):
            self.engine.act(self.space.training('rolling-restarts'), 'pause')
            self.workers.research_plan(tools, job)

        self.workers.then('research-plan', pauses)
        root = self.start(source_scope='both')
        self.send(root, 'handbook.txt')
        self.engine.supply(root, 'done')
        self.assertEqual(self.state(root), 'paused')
        self.plant(root)
        self.assertTrue((root / 'sources' / 'supplied' / 'handbook.txt').is_file())
        leaving = self.engine.leaving(root)
        self.assertEqual(sorted(leaving), LEAVING)
        self.assertEqual(
            {key: leaving[key] for key in ('may', 'why', 'stops', 'state', 'share', 'revisions',
                                           'documents', 'drive', 'title')},
            {'may': True, 'why': None, 'stops': False, 'state': 'paused', 'share': None,
             'revisions': 0, 'documents': 1, 'drive': [], 'title': 'Rolling restarts'})

        said = self.deleted(root)
        self.assertEqual(said, {'deleted': True, 'title': 'Rolling restarts', 'shared': None,
                                'notice': None})
        self.assertRegex(self.log()[-1], DELETED.format(name='Alex'))
        self.assertEqual(self.git('ls-files', '--', gitstate.inside(self.space, root)), '')
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.nothing_left(root)
        # The name is free again.
        self.assertEqual(self.start(), root)

    def test_a_stopped_training_is_deleted(self):
        root = self.start()
        self.engine.act(root, 'stop')
        self.assertEqual(self.engine.leaving(root)['state'], 'stopped')
        self.deleted(root)
        self.assertFalse(root.exists())
        self.assertRegex(self.log()[-1], DELETED.format(name='Alex'))

    def test_a_training_waiting_at_a_gate_is_deleted(self):
        root = self.start()
        self.assertEqual(self.state(root), 'waiting')
        self.deleted(root)
        self.assertFalse(root.exists())

    def test_a_finished_published_training_is_deleted_and_its_revisions_and_drive_files_stay(self):
        root = self.start(copies=['google'])
        self.to_end(root)
        self.assertEqual(self.state(root), 'done')
        self.assertEqual(self.engine.publish(root)['revision'], 1)
        previews = home.data_root() / engines.PREVIEWS
        previews.mkdir(parents=True, exist_ok=True)
        (previews / 'mine.json').write_text(json.dumps({
            'name': 'Preview: Rolling restarts', 'url': 'https://slides.example.com/p/1',
            'training': 'Rolling restarts', 'path': str(root)}))
        (previews / 'other.json').write_text(json.dumps({
            'name': 'Preview: Health checks', 'url': 'https://slides.example.com/p/2',
            'training': 'Health checks', 'path': str(root.parent / 'health-checks')}))
        leaving = self.engine.leaving(root)
        self.assertEqual((leaving['may'], leaving['stops'], leaving['revisions']),
                         (True, False, 1))
        drive = leaving['drive']
        self.assertIn({'what': 'Preview presentation', 'name': 'Preview: Rolling restarts',
                       'url': 'https://slides.example.com/p/1'}, drive)
        docs = [entry for entry in drive if entry['what'] == 'Google Doc']
        self.assertTrue(docs, drive)
        self.assertTrue(all(entry['url'].startswith('https://docs.example.com/d/')
                            for entry in docs))
        self.assertNotIn('Preview: Health checks', [entry['name'] for entry in drive])
        tags = self.git('tag', '--list')

        self.deleted(root)
        self.assertFalse(root.exists())
        self.assertEqual(self.git('tag', '--list'), tags, 'every revision stays')
        self.assertEqual(self.engine.published(), [], 'and the page no longer lists it')
        self.assertEqual([entry['name'] for entry in self.engine.previews_left()],
                         ['Preview: Rolling restarts', 'Preview: Health checks'],
                         'Drive files are never touched, and Settings still lists them')

    def test_a_google_slides_deck_is_named_among_the_drive_files(self):
        root = self.start()
        (root / 'deck-link.md').write_text(
            '# Slide deck: Rolling restarts\n\n- URL: https://slides.example.com/d/9\n'
            '- Title: Rolling restarts\n- ID: 9\n')
        self.assertIn({'what': 'Google Slides deck', 'name': 'Rolling restarts',
                       'url': 'https://slides.example.com/d/9'},
                      self.engine.leaving(root)['drive'])

    def test_the_title_must_be_the_one_the_page_showed(self):
        root = self.start()
        log = self.log()
        with self.assertRaisesRegex(WorkspaceError, 'Nothing was deleted'):
            self.engine.delete(root, 'Health checks')
        self.assertEqual((self.log(), self.state(root)), (log, 'waiting'))

    def test_nothing_is_deleted_while_the_runner_is_still_looking(self):
        root = self.start()
        self.engine._checking = True
        with self.assertRaisesRegex(WorkspaceError, 'still looking'):
            self.deleted(root)
        self.assertTrue(root.is_dir())

    def test_a_folder_the_runner_does_not_drive_is_never_deleted(self):
        chat = self.base / 'started-in-a-chat'
        chat.mkdir()
        workspace.init(chat, 'Started in a chat')
        home.remember(chat, 'Started in a chat', [])
        with self.assertRaisesRegex(WorkspaceError, 'No run is driving this training'):
            self.engine.delete(chat, 'Started in a chat')
        with self.assertRaisesRegex(WorkspaceError, 'No run is driving this training'):
            self.engine.leaving(chat)
        self.assertTrue((chat / '.training-studio' / 'session.json').is_file())

    def test_deleting_ends_a_command_its_step_is_running_and_everything_it_started(self):
        pids, said = self.base / 'pids', []

        def runs_a_command(tools, job):
            companion.run_command(['sh', '-c', LEAVES, 'sh', str(pids)], None, 60, 'A tool')

        def deletes():
            written(pids)
            root = self.space.training('rolling-restarts')
            said.append(self.engine.leaving(root)['stops'])
            said.append(self.engine.delete(root, 'Rolling restarts'))

        self.workers.then('research-plan', runs_a_command)
        deleting = threading.Thread(target=deletes)
        deleting.start()
        started = time.monotonic()
        root = Path(self.engine.start(pipeline.check_form(FORM))['path'])
        deleting.join(20)
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(still_running(written(pids)), [], 'nothing it started is left')
        self.assertEqual(said[0], True, 'the confirmation says it is stopped first')
        self.assertEqual(said[1]['deleted'], True)
        self.assertFalse(root.exists())
        self.assertRegex(self.log()[-1], DELETED.format(name='Alex'))
        self.assertNotIn('Rolling restarts: this step was stopped: Drafting the research plan',
                         self.log(), 'the step in hand kept nothing')


class LiveDeleteTests(Deleting, StudioCase):
    """The engine on threads of its own, as the runner serves it."""

    BACKGROUND = True

    def until(self, check, seconds: float = 30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            found = check()
            if found:
                return found
            time.sleep(0.02)
        self.fail('It did not happen in time.')

    def held(self, act):
        entered, go = threading.Event(), threading.Event()
        self.addCleanup(go.set)

        def script(tools, job):
            returned = act(tools, job)
            entered.set()
            go.wait(30)
            return returned
        return script, entered, go

    def test_a_working_training_is_stopped_first_and_deleted_once_nothing_of_it_runs(self):
        script, entered, go = self.held(self.workers.research_plan)
        self.workers.then('research-plan', script)
        root = self.start()
        self.assertTrue(entered.wait(30))
        self.assertEqual(self.engine.leaving(root)['stops'], True)
        run, said = self.engine._run(root), []
        deleting = threading.Thread(target=lambda: said.append(self.deleted(root)))
        deleting.start()
        self.until(lambda: run.stop.is_set())
        time.sleep(0.3)
        self.assertTrue(deleting.is_alive(), 'it waits for the step in hand to end')
        self.assertTrue(root.is_dir())
        go.set()
        deleting.join(30)
        self.assertEqual(said[0]['deleted'], True)
        self.assertFalse(root.exists())
        self.assertIsNone(run.thread)
        self.assertEqual((self.engine._slots.used, self.engine._slots.waiting), (0, []),
                         'no run and no slot is left behind')
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_a_training_waiting_its_turn_leaves_the_queue_at_once(self):
        settings.save(replace(settings.load(), parallel=1))
        script, entered, go = self.held(self.workers.research_plan)
        self.workers.then('research-plan', script)
        first = self.start()
        self.assertTrue(entered.wait(30))
        second = self.start(title='Health checks')
        self.until(lambda: self.view(second)['sentence'].startswith('Waiting for its turn'))
        self.assertEqual(self.engine.leaving(second)['stops'], True)
        started = time.monotonic()
        self.engine.delete(second, 'Health checks')
        self.assertLess(time.monotonic() - started, 5)
        self.assertFalse(second.exists())
        self.assertEqual(self.engine._slots.waiting, [])
        go.set()
        self.until(lambda: self.state(first) == 'waiting')
        self.until(lambda: self.engine._run(first).thread is None)
        self.assertEqual(self.engine._slots.used, 0)

    def test_a_run_that_does_not_end_in_time_is_left_stopped_and_nothing_is_deleted(self):
        script, entered, go = self.held(self.workers.research_plan)
        self.workers.then('research-plan', script)
        root = self.start()
        self.assertTrue(entered.wait(30))
        with mock.patch.object(engines, 'STOP_WAIT', 0.2), \
                self.assertRaisesRegex(WorkspaceError, 'has not ended yet'):
            self.deleted(root)
        self.assertTrue(root.is_dir())
        self.assertEqual(self.record(root)['halt'], 'stopped')
        go.set()
        self.until(lambda: self.engine._run(root).thread is None)
        self.assertEqual(self.state(root), 'stopped')
        self.deleted(root)
        self.assertFalse(root.exists())


class Asking:
    """Asks a person's page, without a socket, as the page itself would."""

    PORT = 8765

    def ask(self, person, endpoint: str, sent=None, expect: int = 200, origin: bool = True,
            key: bool = True, **params):
        made = getattr(person, 'page', None)
        if made is None:
            made = person.page = page.RunnerPage(self.PORT, person.engine)
        headers = Message()
        headers['Host'] = f'127.0.0.1:{self.PORT}'
        if key:
            headers[desk.TOKEN_HEADER] = made.token
        target = f'/api/{endpoint}' + (f'?{urlencode(params)}' if params else '')
        body = None
        if sent is not None:
            if origin:
                headers['Origin'] = f'http://127.0.0.1:{self.PORT}'
            headers['Content-Type'] = 'application/json'
            body = json.dumps(sent).encode()
        with self.be(person):
            try:
                status, _, data = made.answer(target, headers, 'POST' if body else 'GET', body)
                reply = json.loads(data)
            except desk.Refusal as refusal:
                status, reply = int(refusal.status), {'error': str(refusal)}
            except WorkspaceError as refusal:
                status, reply = 409, {'error': str(refusal)}
        self.assertEqual(int(status), expect, reply)
        return reply


class TeamDeleteTests(Deleting, Asking, TeamCase):
    """Two people sharing one workspace."""

    def started(self, person=None, **changes) -> Path:
        person = person or self.alex
        with self.be(person):
            return Path(person.engine.start(pipeline.check_form({**FORM, **changes}))['path'])

    def fetch(self, person) -> dict:
        return self.as_(person, person.engine.fetch)

    def finished(self) -> Path:
        root = self.started()
        with self.be(self.alex):
            self.to_end(root)
        return root

    def test_a_teammates_training_cannot_be_deleted_here(self):
        root = self.started()
        self.fetch(self.blake)
        theirs = self.theirs(self.blake, root)
        with self.be(self.blake):
            leaving = self.blake.engine.leaving(theirs)
            self.assertEqual(leaving['may'], False)
            self.assertIn('Alex runs this training from another computer, so it cannot be '
                          'deleted from here. Take it over first if you mean to delete it.',
                          leaving['why'])
            with self.assertRaisesRegex(engines.Elsewhere, 'Take it over first'):
                self.deleted(theirs, self.blake.engine)
        self.assertTrue((theirs / '.training-studio' / 'run.json').is_file())
        self.assertEqual(self.shared()[0], STARTED)

    def test_a_training_handed_over_before_it_finished_is_taken_before_it_is_deleted(self):
        root = self.started()
        self.as_(self.alex, self.alex.engine.drive, root, 'hand-over')
        self.fetch(self.blake)
        theirs = self.theirs(self.blake, root)
        with self.be(self.blake), self.assertRaisesRegex(engines.Elsewhere, 'Take it first'):
            self.deleted(theirs, self.blake.engine)
        with self.be(self.alex), self.assertRaisesRegex(engines.Elsewhere, 'Take it first'):
            self.deleted(root)
        self.as_(self.blake, self.blake.engine.drive, theirs, 'take')
        with self.be(self.blake):
            self.deleted(theirs, self.blake.engine)
        self.assertRegex(self.shared()[0], DELETED.format(name='Blake'))

    def test_deleting_shares_at_once_and_a_teammate_drops_it_without_fuss(self):
        root = self.started()
        self.fetch(self.blake)
        theirs = self.theirs(self.blake, root)
        # What the teammate keeps of it that git does not: it goes with it.
        (theirs / 'sources').mkdir()
        (theirs / 'sources' / 'page.html').write_text('Saved on their computer.\n')
        with self.be(self.blake):
            self.assertIn(str(theirs), [entry['path'] for entry in home.trainings()])
        with self.be(self.alex):
            said = self.deleted(root)
        self.assertEqual((said['deleted'], said['shared'], said['notice']), (True, True, None))
        self.assertRegex(self.shared()[0], DELETED.format(name='Alex'))

        self.assertEqual(self.fetch(self.blake)['reached'], True)
        self.assertFalse(theirs.exists())
        with self.be(self.blake):
            self.assertEqual(self.blake.engine.trainings(), [])
            self.assertEqual(home.trainings(), [])
            self.assertEqual(self.blake.engine.standing()['elsewhere'], [])
        self.assertEqual(self.ask(self.blake, 'trainings')['trainings'], [])

    def test_a_finished_training_is_deleted_from_any_computer(self):
        root = self.finished()
        self.assertEqual(self.as_(self.alex, self.alex.engine.publish, root)['revision'], 1)
        self.fetch(self.blake)
        theirs = self.theirs(self.blake, root)
        with self.be(self.blake):
            leaving = self.blake.engine.leaving(theirs)
            self.assertEqual((leaving['may'], leaving['revisions'], leaving['share']),
                             (True, 1, 'decision'))
            self.deleted(theirs, self.blake.engine)
        self.assertRegex(self.shared()[0], DELETED.format(name='Blake'))
        self.assertEqual(len(self.tags()), 1, 'the revision stays')
        self.fetch(self.alex)
        self.assertFalse(root.exists())
        with self.be(self.alex):
            self.assertEqual(self.alex.engine.published(), [])

    def test_with_sharing_only_when_asked_the_deletion_waits_for_share_now(self):
        with self.be(self.alex):
            gitstate.share_when('asked')
        root = self.started()
        self.fetch(self.blake)
        with self.be(self.alex):
            self.assertEqual(self.alex.engine.leaving(root)['share'], 'asked')
            said = self.deleted(root)
        self.assertEqual((said['deleted'], said['shared']), (True, False))
        self.assertIn('next time', said['notice'])
        self.assertFalse(root.exists(), 'it is gone from this computer at once')
        self.assertEqual(self.shared()[0], STARTED, 'and from the team only once it is shared')
        self.fetch(self.blake)
        self.assertTrue(self.theirs(self.blake, root).is_dir())
        self.assertEqual(self.as_(self.alex, self.alex.engine.share)['shared'], True)
        self.assertRegex(self.shared()[0], DELETED.format(name='Alex'))
        self.fetch(self.blake)
        self.assertFalse(self.theirs(self.blake, root).exists())

    def test_a_teammate_who_took_it_first_keeps_their_work(self):
        root = self.finished()
        self.fetch(self.blake)
        theirs = self.theirs(self.blake, root)
        self.as_(self.blake, self.blake.engine.drive, theirs, 'take')
        taken = self.shared()[0]
        self.assertEqual(taken, 'Rolling restarts: Blake takes this training')
        # Alex has not looked since, so this computer still has it finished and nobody's.
        with self.be(self.alex):
            self.assertEqual(self.alex.engine.leaving(root)['may'], True)
            with self.assertRaisesRegex(WorkspaceError, 'Blake took this training on .*, '
                                        'before your deletion of it was shared, so it was '
                                        'not deleted'):
                self.deleted(root)
            view = self.alex.engine.view(root)
            listed = [entry['path'] for entry in home.trainings()]
        self.assertEqual(self.shared()[0], taken, 'nothing of theirs was deleted')
        self.assertEqual((view['mine'], view['driver']['name']), (False, 'Blake'))
        self.assertIn('before your deletion of it was shared, so it was not deleted',
                      view['notice'])
        self.assertIn(str(root), listed)
        self.assertTrue((root / 'README.md').is_file())

    def test_a_teammate_who_took_it_before_share_now_keeps_their_work(self):
        with self.be(self.alex):
            gitstate.share_when('asked')
        root = self.finished()
        self.as_(self.alex, self.alex.engine.share)
        self.fetch(self.blake)
        with self.be(self.alex):
            self.deleted(root)
        theirs = self.theirs(self.blake, root)
        self.as_(self.blake, self.blake.engine.drive, theirs, 'take')
        with self.be(self.alex):
            self.alex.engine.share()
            view = self.alex.engine.view(root)
        self.assertEqual(self.shared()[0], 'Rolling restarts: Blake takes this training')
        self.assertEqual((view['mine'], view['driver']['name']), (False, 'Blake'))
        self.assertIn('so it was not deleted', view['notice'])

    def test_the_page_asks_what_would_go_and_deletes_with_every_rule_kept(self):
        made = page.RunnerPage(self.PORT, self.engine)
        self.assertIn('/api/delete', made.reads)
        self.assertIn('/api/delete', made.writes)
        root = self.started()
        path = str(root)
        self.ask(self.alex, 'delete', expect=403, key=False, path=path)
        leaving = self.ask(self.alex, 'delete', path=path)
        self.assertEqual(sorted(leaving), LEAVING)
        self.assertEqual((leaving['may'], leaving['title']), (True, 'Rolling restarts'))
        sent = {'path': path, 'title': 'Rolling restarts'}
        self.assertEqual(self.ask(self.alex, 'delete', sent, 403, origin=False)['error'],
                         'A change is accepted only from the page itself.')
        self.ask(self.alex, 'delete', sent, 403, key=False)
        self.assertEqual(self.ask(self.alex, 'delete', {'path': path}, 400)['error'],
                         'Give title as text.')
        self.ask(self.alex, 'delete', {'path': str(self.base), 'title': 'x'}, 403)
        self.assertIn('Nothing was deleted', self.ask(
            self.alex, 'delete', {'path': path, 'title': 'Health checks'}, 409)['error'])

        self.ask(self.blake, 'fetch', {})
        theirs = str(self.theirs(self.blake, root))
        self.assertIn('Take it over first', self.ask(
            self.blake, 'delete', {'path': theirs, 'title': 'Rolling restarts'}, 409)['error'])
        self.assertEqual(self.ask(self.blake, 'delete', path=theirs)['may'], False)

        said = self.ask(self.alex, 'delete', sent)
        self.assertEqual((said['deleted'], said['title']), (True, 'Rolling restarts'))
        self.assertEqual(self.ask(self.alex, 'trainings')['trainings'], [])
        self.ask(self.alex, 'run', expect=403, path=path)
        self.ask(self.alex, 'delete', sent, 403)

    def test_a_training_from_a_conversation_is_never_deleted_by_the_page(self):
        chat = self.base / 'started-in-a-chat'
        chat.mkdir()
        workspace.init(chat, 'Started in a chat')
        home.remember(chat, 'Started in a chat', [])
        self.ask(self.alex, 'delete', expect=404, path=str(chat))
        self.ask(self.alex, 'delete', {'path': str(chat), 'title': 'Started in a chat'}, 404)
        self.assertTrue((chat / '.training-studio' / 'session.json').is_file())


if __name__ == '__main__':
    import unittest
    unittest.main()
