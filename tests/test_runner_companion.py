"""Where a companion skill is looked for, and how its command is run: to its end, to its
time limit, or to a stop, with everything it started ended with it. The commands run here
are small shell scripts that leave a `sleep` behind holding their output open, and each
test checks that the `sleep` is gone.
"""
import contextvars
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import helpers
from runner_support import LEAVES, still_running, written

from runner import companion
from workspace import WorkspaceError


class LocationsTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.home = Path(holder.name).resolve()
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop('A_COMPANION', None)

    def test_a_named_companion_is_looked_for_where_it_is_installed(self):
        self.assertEqual(companion.locations('A_COMPANION', 'harness-tool', 'Harness Tool',
                                             self.home), [
            self.home / 'Library' / 'Application Support' / 'Harness Tool' / 'current',
            self.home / '.local' / 'share' / 'harness-tool' / 'current',
            self.home / '.claude' / 'skills' / 'harness-tool',
            self.home / '.agents' / 'skills' / 'harness-tool',
            self.home / '.cursor' / 'skills' / 'harness-tool'])

    def test_with_no_name_every_folder_in_those_places_is_listed(self):
        for folder in (self.home / '.local' / 'share' / 'one', self.home / '.cursor' / 'skills'
                       / 'two', self.home / '.claude' / 'skills' / 'three'):
            folder.mkdir(parents=True)
        self.assertEqual(companion.locations('A_COMPANION', home=self.home), [
            self.home / '.local' / 'share' / 'one' / 'current',
            self.home / '.claude' / 'skills' / 'three',
            self.home / '.cursor' / 'skills' / 'two'])

    def test_the_override_is_the_only_place_looked(self):
        os.environ['A_COMPANION'] = '~/elsewhere'
        self.assertEqual(companion.locations('A_COMPANION', 'harness-tool', 'Harness Tool'),
                         [Path('~/elsewhere').expanduser()])
        self.assertEqual(companion.locations('A_COMPANION', home=self.home),
                         [Path('~/elsewhere').expanduser()])


class RunCommandTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.base = Path(holder.name).resolve()
        self.pids = self.base / 'pids'

    def leaves(self) -> list[str]:
        return ['sh', '-c', LEAVES, 'sh', str(self.pids)]

    def test_what_it_prints_comes_back_as_text_with_its_exit_code(self):
        self.assertEqual(companion.run_command(
            [sys.executable, '-c', 'import sys\nprint("ok")\nprint("no", file=sys.stderr)\n'
             'sys.stdout.flush()\nsys.stdout.buffer.write(b"\\xff\\r\\n")\nsys.exit(3)'],
            None, 20, 'The tool'), (3, 'ok\n�\n', 'no\n'))

    def test_a_child_left_holding_the_output_ends_with_the_command(self):
        started = time.monotonic()
        code, out, _ = companion.run_command(['sh', '-c', 'sleep 30 &\necho $!'], self.base,
                                             20, 'The tool')
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(code, 0)
        self.assertEqual(still_running([int(out)]), [])

    def test_a_command_past_its_limit_is_ended_with_everything_it_started(self):
        for seconds in (3, 60):   # a busy computer may not have started it in 3 seconds
            started = time.monotonic()
            with self.assertRaisesRegex(WorkspaceError,
                                        f'^The tool did not answer in {seconds} seconds.$'):
                companion.run_command(self.leaves(), None, seconds, 'The tool')
            self.assertLess(time.monotonic() - started, seconds + 10)
            if self.pids.exists():
                break
        self.assertEqual(still_running(written(self.pids)), [])

    def test_a_stop_ends_the_command_and_everything_it_started(self):
        stop, stopped = threading.Event(), []

        def stops() -> None:   # once it has started, however busy the computer is
            written(self.pids, seconds=60)
            stopped.append(time.monotonic())
            stop.set()

        stopping = threading.Thread(target=stops)
        stopping.start()
        self.addCleanup(stop.set)
        with companion.stopping(stop), self.assertRaises(companion.Stopped) as raised:
            companion.run_command(self.leaves(), None, 120, 'The tool')
        stopping.join()
        self.assertLess(time.monotonic() - stopped[0], 10)
        self.assertEqual(str(raised.exception), 'The tool was stopped before it finished.')
        self.assertNotIsInstance(raised.exception, WorkspaceError)
        self.assertEqual(still_running(written(self.pids)), [])

    def test_a_stop_that_never_comes_changes_nothing(self):
        with companion.stopping(threading.Event()):
            self.assertEqual(companion.run_command(['echo', 'done'], None, 20, 'The tool'),
                             (0, 'done\n', ''))
        self.assertIsNone(companion.STOP.get())

    def test_a_stop_holds_in_its_own_thread_and_is_carried_to_a_pool_on_purpose(self):
        stop, seen = threading.Event(), {}

        def look(name: str) -> None:
            seen[name] = companion.STOP.get()

        with companion.stopping(stop):
            plain = threading.Thread(target=look, args=('plain',))
            carried = threading.Thread(target=contextvars.copy_context().run,
                                       args=(look, 'carried'))
            for thread in (plain, carried):
                thread.start()
                thread.join()
        self.assertEqual(seen, {'plain': None, 'carried': stop})

    def test_a_caller_that_is_killed_does_not_leave_the_command_running(self):
        # As when the worker tools' server is killed with the agent that started it.
        caller = subprocess.Popen([
            sys.executable, '-c', 'import sys\nsys.path.insert(0, sys.argv[1])\n'
            'from runner import companion\n'
            'companion.run_command(sys.argv[2:], None, 60, "The tool")\n',
            str(helpers.REPO), *self.leaves()])
        self.addCleanup(caller.wait)
        self.addCleanup(caller.kill)
        pids = written(self.pids, seconds=60)
        caller.kill()
        # The watcher may still be starting on a busy computer; it acts once it has.
        self.assertEqual(still_running(pids, seconds=60), [])

    def test_a_command_that_cannot_start_is_a_refusal(self):
        with self.assertRaisesRegex(WorkspaceError, '^The tool could not be started'):
            companion.run_command(['no-such-program-anywhere'], None, 20, 'The tool')


class FindRuntimeTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.base = Path(holder.name).resolve()
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop('A_COMPANION', None)

    def test_the_first_place_that_holds_the_script_is_used(self):
        script = Path('scripts') / 'harness-tool.mjs'
        places = [self.base / 'first', self.base / 'second', self.base / 'third']
        for place in places[1:]:
            (place / 'scripts').mkdir(parents=True)
            (place / script).write_text('// the command line\n')
        self.assertEqual(companion.find_runtime(places, script, 'A_COMPANION', 'harness-tool',
                                                'nothing can be made'), places[1])
        with self.assertRaisesRegex(WorkspaceError, '^The harness-tool skill is not installed '
                                    'on this computer, so nothing can be made. Install it, then '
                                    'try again.$'):
            companion.find_runtime(places[:1], script, 'A_COMPANION', 'harness-tool',
                                   'nothing can be made')
        os.environ['A_COMPANION'] = str(places[0])
        with self.assertRaisesRegex(WorkspaceError, '^A_COMPANION names .*first, which does '
                                    'not hold harness-tool. Point it at the installed skill, '
                                    'or unset it.$'):
            companion.find_runtime(places[:1], script, 'A_COMPANION', 'harness-tool',
                                   'nothing can be made')


if __name__ == '__main__':
    unittest.main()
