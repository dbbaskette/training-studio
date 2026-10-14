"""The team: one driver for each training, staying in step, turns, notifications, publishing
inside the workspace, bringing a training in, and what the page asks for each.

Two people are two data folders and two git identities on this computer, against one bare
repository. Nothing starts an agent, shows a real notification or touches the network.
"""
import hashlib
import json
import os
import subprocess
import threading
import time
import unittest
from contextlib import contextmanager
from dataclasses import replace
from email.message import Message
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

from runner_support import FORM, FOUR, StudioCase, TeamCase, asks

import desk
import home
import hub
import workspace
from runner import engine as engines
from runner import gitstate, page, pipeline, settings, team
from workspace import WorkspaceError

STAMP = r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$'
STARTED = 'Rolling restarts: start the training from the form'


@contextmanager
def asked():
    """The name of every git command run inside, in order."""
    ran, real = [], hub.run

    def spy(repo, *args, **named):
        ran.append(hub.subcommand(args))
        return real(repo, *args, **named)

    with mock.patch.object(hub, 'run', spy):
        yield ran


def tree(folder: Path) -> dict:
    """Every file under a folder, with what it holds."""
    return {path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.rglob('*')) if path.is_file()}


class Asking:
    """Asks a person's page, without a socket, as the page itself would."""

    PORT = 8765

    def ask(self, person, endpoint: str, sent=None, expect: int = 200, **params):
        made = getattr(person, 'page', None)
        if made is None:
            made = person.page = page.RunnerPage(self.PORT, person.engine)
        headers = Message()
        headers['Host'] = f'127.0.0.1:{self.PORT}'
        headers[desk.TOKEN_HEADER] = made.token
        target = f'/api/{endpoint}' + (f'?{urlencode(params)}' if params else '')
        body = None
        if sent is not None:
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


class Team(TeamCase, Asking):
    def started(self, person=None, **changes) -> Path:
        person = person or self.alex
        with self.be(person):
            form = pipeline.check_form({**FORM, **changes})
            return Path(person.engine.start(form)['path'])

    def seen(self, person, root: Path) -> dict:
        with self.be(person):
            return person.engine.view(self.theirs(person, root))

    def fetch(self, person) -> dict:
        return self.as_(person, person.engine.fetch)

    def drive(self, person, root: Path, action: str = 'take') -> dict:
        return self.as_(person, person.engine.drive, self.theirs(person, root), action)

    def approve(self, person, root: Path, target: str) -> dict:
        with self.be(person):
            return self.decide(self.theirs(person, root), target, engine=person.engine)

    def head(self, person) -> str:
        return self.git('rev-parse', 'HEAD', repo=person.space.repo)

    def kept(self, person) -> list[str]:
        return self.git('for-each-ref', '--format=%(refname)', 'refs/training-studio/kept/',
                        repo=person.space.repo).splitlines()


class DriverTests(Team):
    def test_this_computers_identifier_is_made_once_and_says_nothing_of_anyone(self):
        first = team.computer()
        self.assertRegex(first, r'^[0-9a-f]{16}$')
        self.assertEqual(team.computer(), first)
        kept = json.loads((home.data_root() / 'computer.json').read_text())
        self.assertEqual(kept, {'schema': 1, 'id': first})
        self.assertNotEqual(self.as_(self.blake, team.computer), first)

    def test_starting_a_training_takes_it_and_shares_the_claim_before_any_work(self):
        sent = []
        self.workers.then('research-plan', lambda tools, job: (
            sent.extend(self.shared()), self.workers.research_plan(tools, job))[1])
        root = self.started()
        self.assertEqual(sent[0], STARTED, 'the claim was shared before the first worker ran')
        driver = self.record(root)['driver']
        self.assertEqual((driver['name'], driver['computer']), ('Alex', team.computer()))
        self.assertRegex(driver['since'], STAMP)
        view = self.seen(self.alex, root)
        self.assertEqual((view['mine'], view['driver']),
                         (True, {'name': 'Alex', 'here': True, 'since': driver['since']}))
        self.assertEqual((view['taken'], view['notice'], view['queue']), (None, None, None))

    def test_a_teammate_reads_a_training_and_cannot_change_it(self):
        root = self.started()
        self.assertEqual(self.fetch(self.blake)['reached'], True)
        theirs = self.theirs(self.blake, root)
        view = self.seen(self.blake, root)
        self.assertEqual((view['mine'], view['driver']['name'], view['driver']['here']),
                         (False, 'Alex', False))
        self.assertIn('Alex is running this training from another computer', view['sentence'])
        self.assertTrue(view['steps'], 'its steps can be read')
        engine = self.blake.engine
        with self.be(self.blake):
            for change in (lambda: engine.act(theirs, 'stop'),
                           lambda: engine.answer(theirs, 'abc', 'An answer'),
                           lambda: engine.supply(theirs, 'done'),
                           lambda: engine.copies_again(theirs),
                           lambda: engine.outline(theirs, None, 'approve'),
                           lambda: engine.publish(theirs),
                           lambda: self.decide(theirs, 'research-plan', engine=engine),
                           lambda: page.RunnerPage(1, engine).move_approval(str(theirs),
                                                                            'chat'),
                           lambda: engine.drive(theirs, 'hand-over')):
                with self.assertRaisesRegex(engines.Elsewhere, 'Alex has been running this '
                                            'training from another computer since'):
                    change()
            self.assertEqual(engine.brief(theirs)['needs'], False)
            engine.resume()
        self.assertEqual(self.head(self.blake), self.git('rev-parse', 'main', repo=self.remote),
                         'nothing was written to it there')
        self.assertEqual(len(self.workers.jobs), 1, 'and nothing was worked on there')

    def test_a_second_claim_the_repository_refuses_is_dropped_and_says_who_has_it(self):
        root = self.started()
        self.drive(self.alex, root, 'hand-over')
        self.fetch(self.blake)
        theirs, real, raced = self.theirs(self.blake, root), gitstate.commit, []

        def alex_gets_there_first(space, message, paths=None):
            made = real(space, message, paths)
            if not raced and 'takes this training' in message:
                raced.append(True)
                with self.be(self.alex):
                    self.alex.engine.drive(root, 'take')
            return made

        before = self.head(self.blake)
        with mock.patch.object(gitstate, 'commit', alex_gets_there_first), \
                self.be(self.blake), \
                self.assertRaisesRegex(engines.Elsewhere, 'Alex took this training first, on '
                                       '.* so your claim was dropped'):
            self.blake.engine.drive(theirs, 'take')
        self.assertEqual(raced, [True])
        view = self.seen(self.blake, root)
        self.assertEqual((view['mine'], view['driver']['name'], view['taken']),
                         (False, 'Alex', None))
        self.assertEqual(self.head(self.blake), self.git('rev-parse', 'main', repo=self.remote))
        self.assertNotEqual(self.head(self.blake), before)
        self.assertEqual(self.kept(self.blake), [])
        self.assertNotIn('Blake takes this training', '\n'.join(self.shared()))
        self.assertEqual(self.seen(self.alex, root)['mine'], True)

    def test_a_training_someone_took_since_the_page_looked_is_not_taken_over_unasked(self):
        root = self.started()
        self.drive(self.alex, root, 'hand-over')
        self.fetch(self.blake)
        self.drive(self.alex, root)
        with self.assertRaisesRegex(engines.Elsewhere, 'Alex took this training on .* after '
                                    'this page last looked'):
            self.drive(self.blake, root)
        self.assertEqual(self.seen(self.blake, root)['driver']['name'], 'Alex')
        self.assertEqual(self.drive(self.blake, root)['mine'], True, 'now they mean it')

    def test_taking_over_stops_the_other_runner_which_keeps_what_it_had(self):
        with self.be(self.alex):
            gitstate.share_when('asked')
        root = self.started()
        self.approve(self.alex, root, 'research-plan')
        unshared = self.head(self.alex)
        self.assertEqual(self.shared()[0], STARTED)
        self.fetch(self.blake)
        taken = self.drive(self.blake, root)
        self.assertEqual((taken['mine'], taken['driver']['name'], taken['driver']['here']),
                         (True, 'Blake', True))
        self.assertEqual(self.shared()[0],
                         'Rolling restarts: Blake takes this training over from Alex')
        self.assertEqual(workspace.status(self.theirs(self.blake, root))['gate'],
                         'research-plan', "Blake's runner carried on from what was shared")

        self.assertEqual(self.fetch(self.alex)['reached'], True)
        view = self.seen(self.alex, root)
        self.assertEqual((view['mine'], view['driver']['name']), (False, 'Blake'))
        self.assertEqual(view['taken']['by'], 'Blake')
        self.assertRegex(view['taken']['at'], STAMP)
        self.assertEqual(self.kept(self.alex), [view['taken']['kept']])
        self.assertEqual(self.git('rev-parse', view['taken']['kept'], repo=self.alex.space.repo),
                         unshared, 'what this computer had made is kept')
        self.assertIn('Blake took this training over on', view['notice'])
        # The sentence is for a person: kept here, and can be brought back. The name git
        # keeps it under is a detail, given apart.
        self.assertIn('What this computer had made and not yet shared is kept on this '
                      'computer, and can be brought back.', view['notice'])
        self.assertNotIn('refs/', view['notice'])
        self.assertEqual(view['kept'], [view['taken']['kept']])
        with self.be(self.alex):
            listed = page.RunnerPage(1, self.alex.engine).trainings()[0]
            status = self.alex.engine.standing()
            again = self.make().view(root)
        self.assertEqual((listed['notice'], listed['mine']), (view['notice'], False))
        self.assertEqual(status['elsewhere'][0]['notice'], view['notice'])
        self.assertEqual((again['notice'], again['taken']), (view['notice'], view['taken']),
                         'a runner started again still says so')
        with self.assertRaisesRegex(engines.Elsewhere, 'Blake has been running'):
            self.approve(self.alex, root, 'research-plan')
        jobs = len(self.workers.jobs)
        with self.be(self.alex):
            self.alex.engine.resume()
            self.assertEqual(self.alex.engine.share()['shared'], True)
        self.assertEqual(len(self.workers.jobs), jobs, 'it works on it no more')
        self.assertEqual(self.shared()[0],
                         'Rolling restarts: Blake takes this training over from Alex',
                         "nothing of Alex's was put on top of Blake's")
        self.assertEqual(self.as_(self.alex, team.taken, root)['by'], 'Blake',
                         'and it is remembered on this computer')

        self.approve(self.blake, root, 'research-plan')
        self.fetch(self.alex)
        self.assertEqual(self.drive(self.alex, root)['taken'], None, 'taking it back clears it')

    def test_a_teammates_training_says_what_was_last_shared_and_never_what_it_does_now(self):
        with self.be(self.alex):
            gitstate.share_when('asked')
        root = self.started()   # the claim is shared; the plan drafted since is not
        self.fetch(self.blake)
        theirs = self.theirs(self.blake, root)
        view = self.seen(self.blake, root)
        # Its files say an agent's step is next. That is not this computer's to call
        # working: all it knows is what was shared, and when.
        self.assertEqual((view['state'], view['mine'], view['workers'], view['queue']),
                         ('elsewhere', False, [], None))
        self.assertNotIn('working', [step['status'] for step in view['steps']])
        last = view['last_shared']
        self.assertEqual((sorted(last), last['by']), (['at', 'by', 'says'], 'Alex'))
        self.assertRegex(last['at'], STAMP)
        self.assertEqual(last['says'], 'Then, the next step was to draft the research plan.')
        self.assertEqual(view['sentence'], (
            'Alex is running this training from another computer. What is here is what was '
            f"last shared, on {team.day(last['at'])}. {last['says']} It may have moved on "
            'since.'))
        with self.be(self.blake):
            listed = page.RunnerPage(1, self.blake.engine).trainings()[0]
            brief = self.blake.engine.brief(theirs)
        self.assertEqual((listed['run'], listed['mine'], listed['last_shared'], listed['state']),
                         ({'state': 'elsewhere', 'sentence': view['sentence']}, False, last,
                          'in-progress'))
        self.assertEqual((brief['state'], brief['needs']), ('elsewhere', False))
        self.assertEqual(self.seen(self.alex, root)['last_shared'], None,
                         'the computer that drives it knows what it is doing')

        # A gate of theirs was waiting for a decision when it was shared: not for this
        # person, and not known to be waiting still.
        self.as_(self.alex, self.engine.share)
        self.fetch(self.blake)
        view = self.seen(self.blake, root)
        self.assertEqual((view['state'], view['last_shared']['says']),
                         ('elsewhere', 'Then, the research plan was waiting for a decision.'))
        self.assertNotIn('waiting', [step['status'] for step in view['steps']])
        self.assertNotIn('your review', view['sentence'])
        listed = self.ask(self.blake, 'trainings')
        self.assertEqual((listed['needs'], listed['trainings'][0]['state'],
                          listed['trainings'][0]['waiting']['artifact']),
                         (0, 'in-progress', 'research-plan'),
                         'what was waiting can be read, and needs nobody here')

    def test_a_training_nobody_drives_is_published_as_it_is_and_changed_once_taken(self):
        root = self.started()
        self.drive(self.alex, root, 'hand-over')
        path = str(root)
        # Publishing changes nothing in a training, so it is the one thing that needs no
        # driver. Everything else is refused until someone takes it.
        self.assertEqual(self.ask(self.alex, 'publish', {'path': path})['revision'], 1)
        for endpoint, sent in (
                ('run', {'action': 'resume'}), ('copies', {}), ('approval', {'mode': 'chat'}),
                ('decide', {'artifact': 'research-plan', 'decision': 'approve',
                            'seen': 'abc'})):
            said = self.ask(self.alex, endpoint, {'path': path, **sent}, 409)['error']
            self.assertEqual(said, team.NOBODY, endpoint)
        self.fetch(self.blake)
        theirs = str(self.theirs(self.blake, root))
        self.assertEqual(self.ask(self.blake, 'publish', {'path': theirs})['revision'], 2)
        taken = self.ask(self.blake, 'drive', {'path': theirs, 'action': 'take'})
        self.assertEqual((taken['mine'], taken['state']), (True, 'waiting'))
        self.approve(self.blake, root, 'research-plan')

    def test_a_finished_training_is_published_by_anyone_and_taken_to_change_it(self):
        root = self.started()
        with self.be(self.alex):
            self.to_end(root)
        self.fetch(self.blake)
        theirs = str(self.theirs(self.blake, root))
        view = self.ask(self.blake, 'run', path=theirs)
        self.assertEqual((view['state'], view['mine'], view['driver'], view['last_shared'],
                          bool(view['finished'])), ('done', False, None, None, True))
        self.assertEqual(self.ask(self.blake, 'copies', {'path': theirs}, 409)['error'],
                         team.NOBODY)
        self.assertEqual(self.ask(self.blake, 'publish', {'path': theirs})['revision'], 1)
        taken = self.ask(self.blake, 'drive', {'path': theirs, 'action': 'take'})
        self.assertEqual((taken['mine'], taken['driver']['name']), (True, 'Blake'))
        self.ask(self.blake, 'copies', {'path': theirs})

    def test_handing_over_leaves_a_training_for_anyone_to_take(self):
        root = self.started()
        handed = self.drive(self.alex, root, 'hand-over')
        self.assertEqual((handed['mine'], handed['driver'], handed['state'], handed['sentence']),
                         (False, None, 'stopped', team.NOBODY))
        self.assertEqual(self.shared()[0], 'Rolling restarts: Alex hands this training over')
        with self.assertRaisesRegex(engines.Elsewhere, 'Nobody is running this training'):
            self.approve(self.alex, root, 'research-plan')
        self.fetch(self.blake)
        self.assertEqual(self.seen(self.blake, root)['driver'], None)
        self.assertEqual(self.drive(self.blake, root)['mine'], True)
        self.assertEqual(self.shared()[0], 'Rolling restarts: Blake takes this training')
        self.approve(self.blake, root, 'research-plan')
        self.assertEqual(workspace.status(self.theirs(self.blake, root))['gate'], 'research')

    def test_a_finished_training_has_no_driver(self):
        root = self.started()
        with self.be(self.alex):
            self.to_end(root)
        view = self.seen(self.alex, root)
        self.assertEqual((view['state'], view['driver'], view['mine']), ('done', None, False))
        self.fetch(self.blake)
        theirs = self.seen(self.blake, root)
        self.assertEqual((theirs['state'], theirs['driver']), ('done', None))

    def test_a_training_cannot_be_taken_while_the_repository_cannot_be_reached(self):
        root = self.started()
        self.fetch(self.blake)
        before = self.head(self.blake)
        self.remote.rename(self.base / 'moved-away.git')
        with self.assertRaisesRegex(WorkspaceError, 'could not be reached, so this training '
                                    'cannot be taken now'):
            self.drive(self.blake, root)
        self.assertEqual((self.head(self.blake), self.seen(self.blake, root)['mine']),
                         (before, False))

    def test_a_training_started_while_the_repository_is_away_is_still_started(self):
        self.remote.rename(self.base / 'moved-away.git')
        root = self.started()
        self.assertEqual(self.seen(self.alex, root)['mine'], True)
        self.assertIn('could not be reached', self.as_(self.alex, self.engine.shared)['notice'])

    def test_two_trainings_of_one_name_started_at_once_keep_the_first(self):
        self.started()
        with self.assertRaisesRegex(WorkspaceError, 'Someone else started a training in '
                                    'trainings/rolling-restarts at the same moment'):
            self.started(self.blake)
        view = self.seen(self.blake, self.alex.space.training('rolling-restarts'))
        self.assertEqual((view['mine'], view['driver']['name']), (False, 'Alex'))
        self.assertEqual(self.head(self.blake), self.git('rev-parse', 'main', repo=self.remote))

    def test_a_rule_broken_by_hand_is_reported_and_put_right_by_taking_over(self):
        root = self.started()
        clone = self.base / 'by-hand'
        self.git('clone', '--quiet', str(self.remote), str(clone), repo=self.base)
        record = clone / 'trainings' / 'rolling-restarts' / '.training-studio' / 'run.json'
        record.write_text(json.dumps(json.loads(record.read_text())))
        self.git('commit', '--quiet', '-am', 'Edited by hand', repo=clone)
        self.git('push', '--quiet', 'origin', 'HEAD:main', repo=clone)

        self.approve(self.alex, root, 'research-plan')
        found = self.as_(self.alex, self.engine.share)
        self.assertEqual(found['shared'], False)
        self.assertIn('"Rolling restarts" was changed on this computer and on another at the '
                      'same time', found['notice'])
        self.assertIn('One side must take it over', found['notice'])
        self.assertEqual(self.seen(self.alex, root)['notice'], found['notice'])
        mine = self.head(self.alex)

        taken = self.drive(self.alex, root)
        self.assertEqual(taken['mine'], True)
        self.assertIn('carries on from the shared version', taken['notice'])
        self.assertIn('kept on this computer, and can be brought back', taken['notice'])
        self.assertNotIn('refs/', taken['notice'])
        self.assertEqual(taken['kept'], self.kept(self.alex))
        self.assertEqual([self.git('rev-parse', ref, repo=self.alex.space.repo)
                          for ref in self.kept(self.alex)], [mine])
        self.assertEqual(self.as_(self.alex, self.engine.share)['shared'], True)
        self.assertEqual(self.seen(self.alex, root)['notice'], None)
        self.assertEqual(workspace.status(root)['gate'], 'research-plan',
                         'it carries on from what was shared')


class NoDriverTests(StudioCase):
    """A workspace that is a folder on one computer has no drivers."""

    def test_nothing_changes_where_there_is_no_shared_repository(self):
        root = self.start()
        view = self.view(root)
        self.assertEqual((view['mine'], view['driver'], view['taken']), (True, None, None))
        self.assertIsNone(self.record(root)['driver'])
        for action in engines.DRIVING:
            with self.assertRaisesRegex(WorkspaceError, 'is a folder on this computer'):
                self.engine.drive(root, action)
        self.to_end(root)
        self.assertEqual(self.view(root)['mine'], True)
        self.assertEqual(self.engine.fetch(), {'reached': None, 'received': 0, 'notice': None})


class InStepTests(Team):
    def test_a_teammates_trainings_are_adopted_into_the_lists_with_their_driver(self):
        root = self.started()
        with self.be(self.alex):
            self.to_end(root)
        going = self.started(title='Health checks')
        self.assertEqual(self.ask(self.blake, 'trainings'), {'trainings': [], 'needs': 0})
        self.assertEqual(self.ask(self.blake, 'fetch', {})['reached'], True)
        listed = {item['title']: item for item in self.ask(self.blake, 'trainings')['trainings']}
        self.assertEqual(self.ask(self.blake, 'trainings')['needs'], 0,
                         "a teammate's training never needs the person here")
        self.assertEqual(listed['Rolling restarts']['state'], 'finished')
        self.assertIsNone(listed['Rolling restarts']['driver'])
        theirs = listed['Health checks']
        self.assertEqual((theirs['state'], theirs['driver']['name'], theirs['driver']['here'],
                          theirs['mine'], theirs['run']['state']),
                         ('in-progress', 'Alex', False, False, 'elsewhere'))
        self.assertIsNone(theirs['waiting'], 'nothing was waiting when it was last shared')
        self.assertIn('Alex is running this training', theirs['sentence'])
        mine = {item['title']: item for item in self.ask(self.alex, 'trainings')['trainings']}
        self.assertEqual((mine['Health checks']['state'], mine['Health checks']['driver']['here']),
                         ('needs-you', True))
        path = str(self.theirs(self.blake, going))
        for read in ('training', 'run'):
            self.ask(self.blake, read, path=path)
        self.ask(self.blake, 'gate', path=path, artifact='intake')
        self.ask(self.blake, 'file', path=path, artifact='intake')

    def test_fetching_on_a_timer_never_touches_a_training_this_computer_drives(self):
        mine = self.started()
        theirs = self.started(self.blake, title='Health checks')
        before, head = tree(mine), self.head(self.alex)
        self.assertFalse(self.theirs(self.alex, theirs).exists())
        self.engine.serving(every=0.05, tick=0.05)
        deadline = time.monotonic() + 30
        while not self.theirs(self.alex, theirs).exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.engine.close()
        self.assertTrue((self.theirs(self.alex, theirs) / 'intake.md').is_file())
        self.assertEqual(tree(mine), before)
        self.assertEqual(self.git('diff', '--name-only', head, 'HEAD', '--', str(mine),
                                  repo=self.alex.space.repo), '')
        self.assertIn(str(self.theirs(self.alex, theirs)),
                      [entry['path'] for entry in home.trainings()])
        self.assertEqual(self.seen(self.alex, mine)['mine'], True)

    def test_the_runner_fetches_when_it_starts(self):
        theirs = self.started(self.blake)
        with self.be(self.alex):
            self.engine.resume()
        self.assertEqual(self.seen(self.alex, theirs)['driver']['name'], 'Blake')


class TurnTests(StudioCase):
    BACKGROUND = True

    def until(self, check, seconds: float = 30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            found = check()
            if found:
                return found
            time.sleep(0.02)
        self.fail('It did not happen in time.')

    def test_turns_are_taken_in_the_order_they_were_asked_for(self):
        slots, order, waiting = engines._Slots(lambda: 1), [], []
        self.assertTrue(slots.take(lambda: False, 'first'))

        def wait(name: str) -> None:
            slots.take(lambda: False, name)
            order.append(name)
            slots.give_back()

        for name in ('second', 'third', 'fourth'):
            waiting.append(threading.Thread(target=wait, args=(name,), daemon=True))
            waiting[-1].start()
            self.until(lambda: slots.ahead(name) is not None)
        self.assertEqual([slots.ahead(name) for name in ('second', 'third', 'fourth', 'first')],
                         [0, 1, 2, None])
        slots.give_back()
        for thread in waiting:
            thread.join(30)
        self.assertEqual(order, ['second', 'third', 'fourth'])

    def test_a_turn_waited_for_reads_the_limit_once_and_again_when_settings_change(self):
        limit, read = [1], []

        def reading() -> int:
            read.append(limit[0])
            return limit[0]

        slots, done = engines._Slots(reading), threading.Event()
        self.assertTrue(slots.take(lambda: False, 'first'))
        waiting = threading.Thread(target=lambda: slots.take(lambda: False, 'second')
                                   and done.set(), daemon=True)
        waiting.start()
        self.until(lambda: slots.ahead('second') is not None)
        time.sleep(1.2)     # a waiting turn looks again every half a second
        self.assertEqual((read, done.is_set()), ([1, 1], False))
        limit[0] = 2
        slots.renew()
        self.assertTrue(done.wait(30))
        self.assertEqual(read, [1, 1, 2])
        waiting.join(30)

    def test_a_training_that_waits_says_how_many_are_ahead_and_status_shows_every_run(self):
        settings.save(replace(settings.load(), parallel=1))
        entered, go = threading.Event(), threading.Event()
        self.addCleanup(go.set)

        def held(tools, job):
            self.workers.research_plan(tools, job)
            entered.set()
            go.wait(60)

        self.workers.cost = 0.25
        self.workers.then('research-plan', held)
        first = self.start()
        self.assertTrue(entered.wait(30))
        second = self.start(title='Health checks')
        self.until(lambda: self.view(second)['queue'])
        third = self.start(title='Blue green')
        self.until(lambda: self.view(third)['queue'])
        self.assertEqual((self.view(first)['queue'], self.view(second)['queue'],
                          self.view(third)['queue']), (None, {'ahead': 0}, {'ahead': 1}))
        self.assertEqual((self.view(second)['sentence'], self.view(third)['sentence']),
                         ('Waiting for its turn. It is next.',
                          'Waiting for its turn. 1 training is ahead of it.'))
        found = self.engine.standing()
        self.assertEqual((sorted(found), found['limit'], found['elsewhere'],
                          found['background']),
                         (['background', 'elsewhere', 'limit', 'runs', 'upkeep'], 1, [], None))
        runs = {run['id']: run for run in found['runs']}
        self.assertEqual(sorted(runs['blue-green']), ['driver', 'id', 'needs', 'notice', 'path',
                                                      'queue', 'sentence', 'spent', 'state',
                                                      'title'])
        self.assertEqual({ident: run['queue'] for ident, run in runs.items()},
                         {'rolling-restarts': None, 'health-checks': {'ahead': 0},
                          'blue-green': {'ahead': 1}})
        self.assertEqual((runs['blue-green']['title'], runs['blue-green']['state'],
                          runs['blue-green']['path'], runs['blue-green']['driver']),
                         ('Blue green', 'working', str(third), None))
        self.assertIn('Drafting the research plan', runs['rolling-restarts']['sentence'])
        go.set()
        self.until(lambda: all(self.state(root) == 'waiting' for root in (first, second, third)))
        runs = {run['id']: run for run in self.engine.standing()['runs']}
        self.assertEqual([runs[ident]['spent']['dollars'] for ident in sorted(runs)],
                         [0.25, 0.25, 0.25])
        self.assertEqual({run['queue'] for run in runs.values()}, {None})
        order = [job.folder.name.split('--')[0] for _, job, _ in self.workers.jobs]
        self.assertEqual(order, ['rolling-restarts', 'health-checks', 'blue-green'])


class StandingTests(StudioCase):
    def test_status_reads_each_run_and_its_training_once(self):
        root = self.start()
        read_record, load, records, sessions = engines.read_record, workspace.load, [], []

        def record(where):
            records.append(Path(where))
            return read_record(where)

        def session(where, *given, **named):
            sessions.append(Path(where))
            return load(where, *given, **named)

        with mock.patch.object(engines, 'read_record', record), \
                mock.patch.object(engines.workspace, 'load', session):
            self.engine.brief(root)
            briefly = (len(records), len(sessions))
            records.clear()
            sessions.clear()
            found = self.engine.standing()
        self.assertEqual([run['title'] for run in found['runs']], ['Rolling restarts'])
        # Status reads no more than the run's own two words and a sentence do: its title is
        # taken from what that read.
        self.assertEqual(records, [root])
        self.assertEqual((len(records), len(sessions)), briefly)


class StatusTests(Team):
    def test_status_keeps_this_computers_runs_apart_from_those_driven_elsewhere(self):
        mine = self.started()
        theirs = self.started(self.blake, title='Health checks')
        self.fetch(self.alex)
        found = self.ask(self.alex, 'status')
        self.assertEqual([(run['id'], run['driver']['here'], run['needs'], run['state'])
                          for run in found['runs']],
                         [('rolling-restarts', True, False, 'waiting')])
        self.assertEqual(found['runs'][0]['path'], str(mine))
        self.assertEqual(found['elsewhere'], [{
            'path': str(self.theirs(self.alex, theirs)), 'id': 'health-checks',
            'title': 'Health checks', 'state': 'elsewhere',
            'sentence': found['elsewhere'][0]['sentence'],
            'driver': {'name': 'Blake', 'here': False,
                       'since': found['elsewhere'][0]['driver']['since']},
            'last_shared': found['elsewhere'][0]['last_shared'], 'notice': None}])
        self.assertRegex(found['elsewhere'][0]['driver']['since'], STAMP)
        self.assertRegex(found['elsewhere'][0]['sentence'],
                         r'^Blake is running this training from another computer\. What is '
                         r'here is what was last shared, on \d{4}-\d\d-\d\d at \d\d:\d\d UTC\. ')
        self.assertEqual(found['limit'], settings.load().parallel)
        self.assertEqual(found['runs'][0]['notice'], None)


class NotifierTests(unittest.TestCase):
    def notifier(self, system: str = 'Linux', have=(), environ=None, code: int = 0):
        ran = []

        def run(command, **named):
            ran.append(command)
            return subprocess.CompletedProcess(command, code)

        return team.Notifier(which=lambda name: f'/usr/bin/{name}' if name in have else None,
                             run=run, system=lambda: system, environ=environ or {}), ran

    def test_macos_uses_the_systems_own_command_and_hands_the_words_over_as_arguments(self):
        notifier, ran = self.notifier('Darwin', have=('osascript',))
        self.assertEqual(notifier.can(), (True, None))
        title = 'Restarts" & do shell script "true'
        self.assertTrue(notifier.send(title))
        self.assertEqual(ran[0][0], 'osascript')
        self.assertEqual(ran[0][-3:], ['--', 'Training Studio', f'"{title}" needs a decision.'])
        self.assertNotIn(title, ' '.join(ran[0][:-1]), 'never written into the script')

    def test_elsewhere_it_uses_what_is_present(self):
        notifier, ran = self.notifier(have=('notify-send',))
        self.assertTrue(notifier.send('Rolling restarts'))
        self.assertEqual(ran, [['notify-send', '--', 'Training Studio',
                                '"Rolling restarts" needs a decision.']])

    def test_the_command_can_be_replaced(self):
        notifier, ran = self.notifier('Darwin', have=('osascript',),
                                      environ={team.REPLACED: 'my-notify --quiet'})
        self.assertTrue(notifier.send('Rolling restarts'))
        self.assertEqual(ran, [['my-notify', '--quiet', 'Training Studio',
                                '"Rolling restarts" needs a decision.']])

    def test_a_computer_with_no_way_to_notify_says_so(self):
        notifier, ran = self.notifier()
        self.assertEqual(notifier.can(), (False, team.NO_WAY))
        self.assertFalse(notifier.send('Rolling restarts'))
        self.assertEqual(ran, [])
        self.assertNotRegex(team.NO_WAY, 'artifact|stale|lineage')

    def test_a_command_that_fails_is_not_counted_as_told(self):
        self.assertFalse(self.notifier(have=('notify-send',), code=1)[0].send('A title'))


class NotifyTests(StudioCase, Asking):
    def be(self, person):
        return mock.patch.dict(os.environ, {})

    def on(self) -> None:
        settings.save(replace(settings.load(), notify=True))

    def test_nothing_is_told_until_it_is_turned_on(self):
        self.start()
        self.assertEqual((settings.load().notify, self.engine.tell(), self.notifier.sent),
                         (False, [], []))

    def test_each_thing_that_needs_a_decision_is_told_once(self):
        self.on()
        self.workers.then('blueprint', asks('Which platform version?'))
        root = self.start()
        self.assertEqual(self.engine.tell(), ['Rolling restarts'])
        self.assertEqual(self.engine.tell(), [])
        self.assertEqual(self.make().tell(), [], 'nor again after the runner is started again')
        self.decide(root, 'research-plan')
        self.assertEqual(self.engine.tell(), ['Rolling restarts'], 'the next gate is new')
        self.decide(root, 'research')
        self.assertEqual(self.engine.tell(), ['Rolling restarts'], 'and so is a question')
        self.engine.act(root, 'stop')
        self.assertEqual(self.engine.tell(), [], 'a training its person stopped needs nothing')
        self.assertEqual(self.notifier.sent, ['Rolling restarts'] * 3,
                         'only the title is handed over')

    def test_nothing_is_told_while_a_page_is_open(self):
        self.on()
        self.start()
        self.engine.seen()
        self.assertEqual((self.engine.page_open(), self.engine.tell()), (True, []))
        with mock.patch.object(engines, 'PAGE_OPEN', 0):
            self.assertEqual((self.engine.page_open(), self.engine.tell()),
                             (False, ['Rolling restarts']))

    def test_what_went_wrong_in_the_background_is_said_until_it_goes_right(self):
        self.start()
        tried, again, go = [], threading.Event(), threading.Event()
        self.addCleanup(go.set)

        def tell():
            tried.append(1)
            if len(tried) == 1:
                raise RuntimeError('the notification service fell over.')
            again.set()
            go.wait(30)
            return []

        with mock.patch.object(self.engine, 'tell', tell):
            self.engine.serving(every=3600, tick=0.01)
            self.assertTrue(again.wait(30))
            wrong = self.engine.standing()['background']
            self.assertEqual(wrong['says'], "The last try at telling you through this "
                             "computer's notifications did not work: the notification service "
                             'fell over. It is tried again in a few seconds.')
            self.assertRegex(wrong['at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')
            go.set()
            for _ in range(500):
                if self.engine.standing()['background'] is None:
                    break
                time.sleep(0.01)
            self.assertIsNone(self.engine.standing()['background'])

    def test_any_request_from_the_page_says_one_is_open(self):
        self.person = type('Person', (), {'engine': self.engine})()
        self.assertFalse(self.engine.page_open())
        self.ask(self.person, 'capabilities')
        self.assertTrue(self.engine.page_open())

    def test_the_setting_is_read_and_changed_on_the_page(self):
        self.person = type('Person', (), {'engine': self.engine})()
        self.assertEqual(self.ask(self.person, 'setup')['notify'],
                         {'on': False, 'can': True, 'problem': None})
        self.assertEqual(self.ask(self.person, 'setup', {'notify': True})['notify']['on'], True)
        self.assertEqual(settings.load().notify, True)
        self.assertIn('true or false',
                      self.ask(self.person, 'setup', {'notify': 'yes'}, 400)['error'])
        self.assertEqual(self.ask(self.person, 'setup', {'notify': False})['notify']['on'], False)
        self.notifier.way = team.NO_WAY
        self.assertEqual(self.ask(self.person, 'setup')['notify'],
                         {'on': False, 'can': False, 'problem': team.NO_WAY})
        self.assertEqual(self.ask(self.person, 'setup', {'notify': True}, 409)['error'],
                         team.NO_WAY)
        self.assertEqual(settings.load().notify, False)


class TeamNotifyTests(Team):
    def test_a_teammates_training_is_never_told_here(self):
        with self.be(self.blake):
            settings.save(replace(settings.load(), notify=True))
        self.started()
        self.fetch(self.blake)
        self.assertEqual(self.as_(self.blake, self.blake.engine.tell), [])


class SlowRemoteTests(Team):
    @contextmanager
    def held_up(self, name: str):
        """Hold every `git <name>` up until the test lets it go. Yields two events: one
        set when the first is held, one the test sets to let them go."""
        reached, go, real = threading.Event(), threading.Event(), hub.run

        def slow(repo, *args, **named):
            if hub.subcommand(args) == name and not go.is_set():
                reached.set()
                go.wait(30)
            return real(repo, *args, **named)

        with mock.patch.object(hub, 'run', slow):
            try:
                yield reached, go
            finally:
                go.set()

    def test_a_decision_is_not_held_up_by_a_slow_push_or_fetch(self):
        root = self.started()
        with self.be(self.alex):
            gitstate.share_when('asked')    # so the decision itself sends nothing
        for name, sharing in (('push', self.engine.share), ('fetch', self.engine.fetch)):
            with self.subTest(name), self.be(self.alex), self.held_up(name) as (reached, go):
                behind = threading.Thread(target=sharing, daemon=True)
                behind.start()
                self.assertTrue(reached.wait(30), f'the {name} was never asked for')
                before, made = self.head(self.alex), []
                gate = workspace.status(root)['gate']
                deciding = threading.Thread(target=lambda: made.append(
                    self.decide(root, gate)), daemon=True)
                deciding.start()
                deciding.join(20)
                self.assertFalse(deciding.is_alive(), f'the decision waited for the {name}')
                self.assertTrue(behind.is_alive(), f'the {name} is still held up')
                self.assertEqual(made[0]['decided']['decision'], 'approve')
                self.assertNotEqual(self.head(self.alex), before, 'and it was committed')
                go.set()
                behind.join(30)
                self.assertFalse(behind.is_alive())
        self.assertEqual(self.as_(self.alex, self.engine.share)['shared'], True)

    def test_nothing_is_changed_on_the_page_until_the_first_look_after_starting(self):
        root = self.started()
        path, gate = str(root), workspace.status(root)['gate']
        with self.be(self.alex):
            self.engine.close()
            self.alex.engine = self.make(background=True)
        with self.be(self.alex), self.held_up('fetch') as (reached, go):
            self.alex.engine.resume(wait=False)
            self.assertTrue(reached.wait(30), 'the first look was never asked for')
            seen = workspace.sha256_file(
                root / workspace.artifact(root, workspace.load(root), gate)['file'])
            for endpoint, sent in (
                    ('decide', {'artifact': gate, 'decision': 'approve', 'seen': seen}),
                    ('copies', {}), ('run', {'action': 'pause'})):
                said = self.ask(self.alex, endpoint, {'path': path, **sent}, 409)['error']
                self.assertEqual(said, engines.CHECKING, endpoint)
            go.set()
            for thread in threading.enumerate():
                if thread.name == 'resuming':
                    thread.join(30)
        self.assertEqual(self.approve(self.alex, root, gate)['decided']['decision'], 'approve')

    def test_learning_who_drives_what_asks_git_once_for_every_training(self):
        mine = [self.started(), self.started(title='Health checks')]
        self.fetch(self.blake)
        with self.be(self.alex), asked() as ran:
            self.engine.fetch()
        self.assertNotIn('merge-base', ran, 'nothing came in, so there is nothing to learn')
        self.started(self.blake, title='Blue green')
        with self.be(self.alex), asked() as ran:
            self.assertEqual(self.engine.fetch()['received'], 1)
        self.assertEqual((ran.count('merge-base'), ran.count('diff')), (1, 1))
        self.assertEqual([self.seen(self.alex, root)['mine'] for root in mine], [True, True])


class PublishTests(Team):
    def tag(self, name: str) -> str:
        return self.git('rev-parse', f'refs/tags/{name}', repo=self.remote)

    def test_the_published_list_asks_git_twice_however_many_there_are(self):
        trainings = [self.started(), self.started(title='Health checks'),
                     self.started(title='Blue green')]
        for root in trainings:
            self.ask(self.alex, 'publish', {'path': str(root)})
        self.approve(self.alex, trainings[1], 'research-plan')
        with asked() as ran:
            listed = self.ask(self.alex, 'published')['published']
        self.assertEqual(ran, ['for-each-ref', 'cat-file'])
        self.assertEqual({entry['id']: entry['current'] for entry in listed},
                         {'rolling-restarts': True, 'health-checks': False,
                          'blue-green': True})

    def test_revisions_are_numbered_pushed_and_never_moved(self):
        root = self.started()
        with self.be(self.alex):
            self.to_end(root)
        first = self.ask(self.alex, 'publish', {'path': str(root)})
        self.assertEqual(first, {'revision': 1, 'ready': True, 'shared': True, 'notice': None})
        name = 'training-studio/trainings/rolling-restarts/1'
        self.assertEqual(self.tags(), [name])
        kept, stood = self.tag(name), self.git('rev-parse', 'main', repo=self.remote)
        self.assertEqual(self.git('rev-parse', f'{name}^{{commit}}', repo=self.remote), stood)

        self.fetch(self.blake)
        theirs = str(self.theirs(self.blake, root))
        listed = self.ask(self.blake, 'published')['published']
        self.assertEqual(listed, [{'path': theirs, 'id': 'rolling-restarts',
                                   'title': 'Rolling restarts', 'revision': 1,
                                   'at': listed[0]['at'], 'by': 'Alex', 'ready': True,
                                   'current': True}])
        self.assertRegex(listed[0]['at'], STAMP)
        self.assertEqual(self.ask(self.blake, 'publish', {'path': theirs})['revision'], 2)
        self.assertEqual(self.tags(), [name, name[:-1] + '2'])
        self.assertEqual(self.tag(name), kept, 'the first revision is where it was')
        self.fetch(self.alex)
        listed = self.ask(self.alex, 'published')['published']
        self.assertEqual([(entry['revision'], entry['by']) for entry in listed], [(2, 'Blake')])

    def test_two_people_publishing_one_number_at_once_get_consecutive_revisions(self):
        root = self.started()
        with self.be(self.alex):
            self.to_end(root)
        self.fetch(self.blake)
        real, raced = team.send_tags, []

        def blake_first(space, only=None):
            if only and not raced:
                raced.append(True)
                with self.be(self.blake):
                    made = self.blake.engine.publish(self.theirs(self.blake, root))
                self.assertEqual(made['revision'], 1)
            return real(space, only)

        with mock.patch.object(team, 'send_tags', blake_first), self.be(self.alex):
            mine = self.engine.publish(root)
        self.assertEqual((mine['revision'], mine['shared']), (2, True))
        self.assertEqual(len(self.tags()), 2)
        by = {entry['revision']: entry['by']
              for entry in self.as_(self.alex, team._tags, self.alex.space)}
        self.assertEqual(by, {1: 'Blake', 2: 'Alex'})

    def test_a_training_that_is_not_ready_is_published_and_says_so(self):
        root = self.started()
        made = self.ask(self.alex, 'publish', {'path': str(root)})
        self.assertEqual((made['revision'], made['ready'], made['shared']), (1, False, True))
        self.assertIn('Revision 1 was published before this training was ready', made['notice'])
        listed = self.ask(self.alex, 'published')['published']
        self.assertEqual((listed[0]['ready'], listed[0]['current']), (False, True))
        self.approve(self.alex, root, 'research-plan')
        self.assertEqual(self.ask(self.alex, 'published')['published'][0]['current'], False,
                         'the training has changed since that revision')

    def test_a_training_someone_else_drives_is_not_published_from_here(self):
        root = self.started()
        self.fetch(self.blake)
        said = self.ask(self.blake, 'publish', {'path': str(self.theirs(self.blake, root))}, 409)
        self.assertIn('Alex has been running this training', said['error'])
        self.assertEqual(self.tags(), [])

    def test_a_revision_made_while_the_repository_is_away_goes_with_the_next_share(self):
        root = self.started()
        self.remote.rename(self.base / 'moved-away.git')
        made = self.as_(self.alex, self.engine.publish, root)
        self.assertEqual((made['revision'], made['shared']), (1, False))
        self.assertIn('is not shared yet', made['notice'])
        (self.base / 'moved-away.git').rename(self.remote)
        self.assertEqual(self.tags(), [])
        self.assertEqual(self.as_(self.alex, self.engine.share)['shared'], True)
        self.assertEqual(self.tags(), ['training-studio/trainings/rolling-restarts/1'])

    def test_no_command_here_ever_forces_a_push_or_moves_a_tag(self):
        for module in (team, engines):
            source = Path(module.__file__).read_text().split('"""', 2)[2]
            for never in ('--force', "'-f'", '+refs', '--mirror', "'reset'"):
                self.assertNotIn(never, source, never)


class LocalPublishTests(StudioCase):
    def test_a_workspace_on_one_computer_keeps_its_revisions_here(self):
        root = self.start()
        self.to_end(root)
        made = self.engine.publish(root)
        self.assertEqual((made['revision'], made['ready'], made['shared']), (1, True, False))
        self.assertIn('no shared repository', made['notice'])
        self.assertEqual(self.git('tag', '--list'),
                         'training-studio/trainings/rolling-restarts/1')
        self.assertEqual(self.engine.publish(root)['revision'], 2)
        self.assertEqual([entry['revision'] for entry in self.engine.published()], [2])


class BringTests(Team):
    def chat(self, name: str = 'started-in-a-chat', title: str = 'Started in a chat') -> Path:
        """A training a conversation began, waiting at its first gate."""
        root = self.base / name
        root.mkdir()
        workspace.init(root, title)
        workspace.write_atomic(root / 'intake.md', pipeline.intake_text(
            pipeline.check_form({**FORM, 'title': title})).encode())
        workspace.save(root, 'intake', built=True)
        workspace.approve(root, 'intake')
        (root / pipeline.PLAN).parent.mkdir(parents=True, exist_ok=True)
        (root / pipeline.PLAN).write_text(json.dumps({
            **FOUR, 'purpose': 'planning', 'scope': 'public-web', 'sources': [],
            'items': [{**item, 'scope': 'public-web'} for item in FOUR['items']]}))
        workspace.save(root, 'research-plan', built=True)
        workspace.checkpoint(root, stage='research-plan', gate='research-plan',
                             question='Approve the research plan?')
        (root / 'sources').mkdir(exist_ok=True)
        (root / 'sources' / 'notes.txt').write_text('Kept beside the training.\n')
        home.remember(root, title, [])
        return root

    def test_a_training_is_copied_in_taken_and_carried_on_at_its_waiting_gate(self):
        chat = self.chat()
        before = tree(chat)
        self.assertEqual(workspace.load(chat)['settings']['approval'], 'chat')
        made = self.ask(self.alex, 'adopt', {'path': str(chat)})
        root = self.alex.space.training('started-in-a-chat')
        self.assertEqual(made, {'path': str(root), 'id': 'started-in-a-chat'})
        self.assertEqual(tree(chat), before, 'the original is exactly as it was')
        self.assertEqual(workspace.load(chat)['settings']['approval'], 'chat')
        self.assertEqual(workspace.load(root)['settings']['approval'], 'page')
        self.assertEqual((root / 'sources' / 'notes.txt').read_text(),
                         'Kept beside the training.\n')
        self.assertEqual(self.shared()[0],
                         'Started in a chat: bring the training in from a conversation')
        self.assertNotIn('sources', self.git('ls-tree', '-r', '--name-only', 'main',
                                             repo=self.remote))
        view = self.seen(self.alex, root)
        self.assertEqual((view['state'], view['mine'], view['driver']['name']),
                         ('waiting', True, 'Alex'))
        self.assertEqual(view['sentence'], 'The research plan is waiting for your review.')
        self.assertEqual(self.workers.jobs, [], 'nothing made in the conversation is made again')
        self.assertIn(str(root), [entry['path'] for entry in home.trainings()])
        self.approve(self.alex, root, 'research-plan')
        self.assertEqual(workspace.status(root)['gate'], 'research',
                         'the run carried on from the gate that was waiting')
        self.assertEqual(tree(chat), before)

    def test_what_cannot_be_brought_in_is_refused_in_a_sentence(self):
        chat = self.chat()
        root = self.started()
        self.assertEqual(self.ask(self.alex, 'adopt', {'path': str(root)}, 409)['error'],
                         'This training is already in the workspace.')
        self.assertEqual(self.ask(self.alex, 'adopt', {'path': str(self.base / 'unknown')},
                                  403)['error'],
                         'That folder is not a training this computer knows.')
        (chat / 'linked.md').symlink_to(chat / 'intake.md')
        said = self.ask(self.alex, 'adopt', {'path': str(chat)}, 409)['error']
        self.assertIn('linked.md is a symbolic link, which a workspace does not take', said)
        (chat / 'linked.md').unlink()
        (chat / 'nested' / '.git').mkdir(parents=True)
        self.assertIn('nested holds a repository of its own',
                      self.ask(self.alex, 'adopt', {'path': str(chat)}, 409)['error'])
        (chat / 'nested' / '.git').rmdir()
        with mock.patch.object(team, 'LARGEST', 10):
            self.assertIn('is larger than',
                          self.ask(self.alex, 'adopt', {'path': str(chat)}, 409)['error'])
        self.assertFalse(self.alex.space.training('started-in-a-chat').exists())
        self.assertEqual(self.git('status', '--porcelain', repo=self.alex.space.repo), '')

        self.ask(self.alex, 'adopt', {'path': str(chat)})
        self.assertIn('already has a training in trainings/started-in-a-chat',
                      self.ask(self.alex, 'adopt', {'path': str(chat)}, 409)['error'])

    def test_a_training_whose_record_cannot_be_read_is_refused(self):
        chat = self.chat()
        before = tree(chat)
        record = chat / '.training-studio' / 'session.json'
        kept = record.read_text()
        record.write_text('{not json')
        with self.be(self.alex), \
                self.assertRaisesRegex(WorkspaceError, "record cannot be read, so it cannot "
                                       'be brought into the workspace'):
            self.engine.bring(chat)
        record.write_text(kept)
        self.assertEqual(tree(chat), before)
        self.assertEqual(list(self.alex.space.root.glob('started*')), [])


class PageTests(Team):
    """The appendix, field for field, through the page's own addresses."""

    def test_the_new_addresses_keep_every_rule_of_the_page(self):
        made = page.RunnerPage(self.PORT, self.engine)
        for read in ('/api/status', '/api/published'):
            self.assertIn(read, made.reads)
            self.assertEqual(made.allowed(read), 'GET')
        for write in ('/api/drive', '/api/publish', '/api/adopt', '/api/fetch'):
            self.assertIn(write, made.writes)
            self.assertEqual(made.allowed(write), 'POST')
        headers = Message()
        headers['Host'] = f'127.0.0.1:{self.PORT}'
        with self.assertRaises(desk.Refusal) as refused:
            made.answer('/api/status', headers)
        self.assertEqual(int(refused.exception.status), 403, 'the key is still needed')

    def test_driving_a_training_on_the_page(self):
        root = self.started()
        path = str(root)
        run = self.ask(self.alex, 'run', path=path)
        self.assertEqual((run['mine'], run['driver']['name'], run['driver']['here']),
                         (True, 'Alex', True))
        self.ask(self.blake, 'fetch', {})
        theirs = str(self.theirs(self.blake, root))
        run = self.ask(self.blake, 'run', path=theirs)
        self.assertEqual((run['mine'], run['driver']['here'], run['queue'], run['taken']),
                         (False, False, None, None))
        for endpoint, sent in (
                ('run', {'action': 'stop'}), ('answer', {'id': 'abc', 'answer': 'Yes'}),
                ('documents', {'action': 'done'}), ('copies', {}), ('drive',
                                                                    {'action': 'hand-over'}),
                ('outline', {'decision': 'approve'}), ('approval', {'mode': 'chat'}),
                ('publish', {}),
                ('decide', {'artifact': 'research-plan', 'decision': 'approve',
                            'seen': 'abc'})):
            said = self.ask(self.blake, endpoint, {'path': theirs, **sent}, 409)['error']
            self.assertIn('Alex has been running this training from another computer since',
                          said, endpoint)
        self.assertIn('take, hand-over', self.ask(self.blake, 'drive', {
            'path': theirs, 'action': 'steal'}, 400)['error'])
        self.ask(self.blake, 'drive', {'path': str(self.base), 'action': 'take'}, 403)

        taken = self.ask(self.blake, 'drive', {'path': theirs, 'action': 'take'})
        self.assertEqual((taken['mine'], taken['driver']['name'], taken['state']),
                         (True, 'Blake', 'waiting'))
        self.assertEqual(self.ask(self.alex, 'fetch', {})['reached'], True)
        lost = self.ask(self.alex, 'run', path=path)
        self.assertEqual((lost['mine'], lost['taken']['by'], sorted(lost['taken'])),
                         (False, 'Blake', ['at', 'by', 'kept']))
        self.assertTrue(lost['taken']['kept'].startswith('refs/training-studio/kept/'))
        self.assertIn('Blake has been running',
                      self.ask(self.alex, 'run', {'path': path, 'action': 'stop'}, 409)['error'])
        handed = self.ask(self.blake, 'drive', {'path': theirs, 'action': 'hand-over'})
        self.assertEqual((handed['mine'], handed['driver']), (False, None))
        self.assertIn('Nobody is running this training',
                      self.ask(self.blake, 'run', {'path': theirs, 'action': 'stop'}, 409)['error'])


if __name__ == '__main__':
    unittest.main()
