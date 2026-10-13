"""The copies a training asked for: which are wanted, making them, and what happens when
one cannot be made.

Nothing here reaches Google or runs gcloud or pandoc: a pretend Drive takes the Docs and a
pretend converter makes the Word files.
"""
import subprocess
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import runner_support  # noqa: F401  puts the runner on the import path
from test_cli import Flow, example, levelled
from test_google import FakeTransport
import gdocs
import workspace
from workspace import WorkspaceError

from runner import copies

TOKEN = 'stand-in-access-token-0123456789abcdef'
FORBIDDEN = ('artifact', 'stale', 'lineage')
FILES = (('blueprint', 'blueprint.md'), ('document', 'document.md'),
         ('brief', 'product-brief.md'))
REFUSAL = ('Google Drive refused the request (HTTP 403: The caller does not have permission). '
           'Check that the signed-in account may edit the Doc, or run `gcloud auth login '
           '--enable-gdrive-access`.')


def setUpModule():
    """A slip in a test must fail here. It must never start a program or reach Google."""
    for owner, name in ((subprocess, 'run'), (urllib.request, 'urlopen')):
        blocked = mock.Mock(side_effect=AssertionError(f'A test tried to use {name}.'))
        patcher = mock.patch.object(owner, name, blocked)
        patcher.start()
        unittest.addModuleCleanup(patcher.stop)


class Converter:
    """A pretend Word converter. It writes a file that says what it was made from."""

    def __init__(self):
        self.made: list[str] = []

    def __call__(self, source: Path, target: Path) -> None:
        self.made.append(source.name)
        target.write_bytes(b'Word copy of: ' + source.read_bytes())


class Refusing(FakeTransport):
    """A Drive that says no to everything, in the words the core's own transport uses."""

    def create(self, title, markdown):
        raise WorkspaceError(REFUSAL)

    update = create


class Built(Flow):
    """Trainings made with the core itself and the example files, with no copy made yet."""

    def setUp(self):
        super().setUp()
        self.drive, self.word = FakeTransport(), Converter()

    def level(self, level: str | None = None) -> None:
        """One level's blueprint, and whichever of its guide, brief, deck and scenarios the
        training still wants, each approved."""
        session = workspace.load(self.root)
        wanted = [stage for stage in session['settings']['stages']
                  if stage not in session['unavailable']]
        at, folder = (f'@{level}', f'{level}/') if level else ('', '')
        for name, file in FILES:
            text = example(file)
            if name == 'blueprint' and level:
                text = levelled(text, level)
            if name == 'blueprint' or name in wanted:
                self.make(f'{name}{at}', f'{folder}{file}', text)
        if 'deck' in wanted:
            self.deck(level)
        if 'scenario' in wanted:
            self.scenario(level, 'yoodli' in wanted)

    def built(self, *kinds: str, yoodli: bool = False, levels: tuple = (),
              without: tuple = ()) -> None:
        """A whole training, approved, that keeps these kinds of copy and leaves these
        stages out."""
        self.research(*(('--levels', ','.join(levels)) if levels else ()), yoodli=yoodli,
                      copies=kinds)
        for stage in without:
            self.cli('skip', stage, '--reason', 'Not wanted for this training')
        for level in levels or (None,):
            self.level(level)

    def copy(self, **changes) -> tuple[list[dict], dict]:
        return copies.make(self.root, **{'google': self.drive, 'word': self.word, **changes})

    def shown(self, problems=None) -> list[tuple]:
        """Each wanted copy as (what of, kind, state)."""
        return [(entry['artifact'], entry['kind'], entry['state'])
                for entry in copies.wanted(self.root, problems)]

    def revise(self, name: str = 'document', file: str = 'document.md') -> None:
        """The person changes a file that was approved, and approves it again."""
        self.write(file, example(file) + '\nOne more line.\n')
        self.cli('approve', name)


# --- what is wanted ------------------------------------------------------------------------

class WantedTests(Built):
    def test_a_training_that_asked_for_none_wants_none_and_makes_none(self):
        self.built()
        self.assertEqual(copies.wanted(self.root), [])
        self.assertEqual(self.copy(), ([], {}))
        self.assertEqual((self.drive.calls, self.word.made), ([], []))

    def test_each_wanted_copy_is_an_entry_in_the_order_of_what_it_is_a_copy_of(self):
        self.built('google', 'word')
        self.assertEqual(copies.wanted(self.root), [
            {'artifact': 'document', 'label': 'the learner guide', 'kind': 'google',
             'state': 'not-made', 'link': None, 'problem': None},
            {'artifact': 'document', 'label': 'the learner guide', 'kind': 'word',
             'state': 'not-made', 'link': None, 'problem': None},
            {'artifact': 'brief', 'label': 'the brief', 'kind': 'google',
             'state': 'not-made', 'link': None, 'problem': None},
            {'artifact': 'brief', 'label': 'the brief', 'kind': 'word',
             'state': 'not-made', 'link': None, 'problem': None}])

    def test_what_is_wanted_is_what_the_core_says_and_nothing_else(self):
        for kinds, yoodli in ((('google',), False), (('word',), False), ((), True),
                              (('google',), True), (('google', 'word'), True)):
            with self.subTest(kinds=kinds, yoodli=yoodli):
                self.setUp()
                self.built(*kinds, yoodli=yoodli)
                session = workspace.load(self.root)
                self.assertEqual(
                    sorted((entry['artifact'], entry['kind'])
                           for entry in copies.wanted(self.root)),
                    sorted([(name, 'google') for name in gdocs.copy_states(self.root, session)]
                           + [(name, 'word')
                              for name in workspace.export_states(self.root, session)]))

    def test_with_yoodli_on_and_no_copies_asked_for_the_upload_is_still_wanted(self):
        self.built(yoodli=True)
        self.assertEqual(self.shown(), [('brief', 'word', 'not-made'),
                                        ('yoodli:main', 'word', 'not-made')])
        self.assertEqual(copies.wanted(self.root)[1]['label'], 'the Yoodli scenario')

    def test_a_training_with_levels_wants_each_levels_copies(self):
        self.built('word', yoodli=True, levels=('101', '301'))
        self.assertEqual([(entry['artifact'], entry['label'])
                          for entry in copies.wanted(self.root)],
                         [('document@101', 'the level 101 learner guide'),
                          ('brief@101', 'the level 101 brief'),
                          ('yoodli:main@101', 'the level 101 Yoodli scenario'),
                          ('document@301', 'the level 301 learner guide'),
                          ('brief@301', 'the level 301 brief'),
                          ('yoodli:main@301', 'the level 301 Yoodli scenario')])
        made, problems = self.copy()
        self.assertEqual([entry['link'] for entry in made],
                         ['101/document.docx', '101/product-brief.docx', '101/yoodli/main.docx',
                          '301/document.docx', '301/product-brief.docx',
                          '301/yoodli/main.docx'])
        self.assertTrue(all((self.root / entry['link']).is_file() for entry in made))
        self.assertTrue(self.check('--complete')['ready'])

    def test_a_copy_of_something_not_approved_yet_is_listed_and_left_alone(self):
        self.research(yoodli=False, copies=('google', 'word'))
        self.make('blueprint', 'blueprint.md', example('blueprint.md'))
        self.write('document.md', example('document.md'))
        self.cli('save', 'document', '--built')
        self.assertEqual(self.copy(), ([], {}))
        self.assertEqual((self.drive.calls, self.word.made), ([], []))
        self.assertEqual({(entry['state'], entry['problem'])
                          for entry in copies.wanted(self.root)}, {('not-made', None)})
        self.cli('approve', 'document')
        made, _ = self.copy()
        self.assertEqual([(entry['artifact'], entry['kind']) for entry in made],
                         [('document', 'google'), ('document', 'word')])


# --- making them ---------------------------------------------------------------------------

class MakingTests(Built):
    def test_every_wanted_copy_of_something_approved_is_made_and_recorded_by_the_core(self):
        self.built('google', 'word')
        made, problems = self.copy()
        self.assertEqual(problems, {})
        self.assertEqual(made, [
            {'artifact': 'document', 'label': 'the learner guide', 'kind': 'google',
             'state': 'made', 'link': 'https://docs.example.com/d/doc1/edit', 'problem': None},
            {'artifact': 'document', 'label': 'the learner guide', 'kind': 'word',
             'state': 'made', 'link': 'document.docx', 'problem': None},
            {'artifact': 'brief', 'label': 'the brief', 'kind': 'google',
             'state': 'made', 'link': 'https://docs.example.com/d/doc2/edit', 'problem': None},
            {'artifact': 'brief', 'label': 'the brief', 'kind': 'word',
             'state': 'made', 'link': 'product-brief.docx', 'problem': None}])
        self.assertEqual(made, copies.wanted(self.root))
        status = self.cli('status')
        self.assertEqual((status['google_docs'], status['exports']),
                         ({'document': 'current', 'brief': 'current'},
                          {'document': 'current', 'brief': 'current'}))
        self.assertEqual((self.root / 'document.docx').read_bytes(),
                         b'Word copy of: ' + example('document.md').encode())
        # The Doc holds the guide's words, without the comments that Google would drop.
        self.assertIn('## Why this matters', self.drive.docs['doc1'])
        self.assertNotIn('<!--', self.drive.docs['doc1'])
        report = self.check('--complete')
        self.assertEqual((report['ready'], report['limitations']), (True, []))

    def test_a_copy_that_is_current_is_left_alone(self):
        self.built('google', 'word')
        self.copy()
        calls, converted = list(self.drive.calls), list(self.word.made)
        self.assertEqual(self.copy(), ([], {}))
        self.assertEqual((self.drive.calls, self.word.made), (calls, converted))

    def test_nothing_is_approved_skipped_or_decided_by_making_copies(self):
        self.built('google', 'word')
        before = workspace.load(self.root)
        self.copy()
        after = workspace.load(self.root)
        for key in ('artifacts', 'decisions', 'settings', 'stage', 'requests', 'unavailable'):
            self.assertEqual(after[key], before[key], key)

    def test_a_copy_is_made_again_when_its_file_is_changed_and_approved_again(self):
        self.built('google', 'word')
        self.copy()
        self.write('document.md', example('document.md') + '\nOne more line.\n')
        self.assertEqual(self.shown(), [('document', 'google', 'out-of-date'),
                                        ('document', 'word', 'out-of-date'),
                                        ('brief', 'google', 'made'), ('brief', 'word', 'made')])
        self.assertEqual([entry['link'] for entry in copies.wanted(self.root)][:2],
                         ['https://docs.example.com/d/doc1/edit', 'document.docx'])
        # Changed, and not approved yet: the copies wait for the person.
        self.assertEqual(self.copy(), ([], {}))
        self.cli('approve', 'document')
        made, problems = self.copy()
        self.assertEqual(([(entry['artifact'], entry['kind']) for entry in made], problems),
                         ([('document', 'google'), ('document', 'word')], {}))
        self.assertEqual(self.drive.did('update'), [('update', 'doc1')])
        self.assertEqual(len(self.drive.did('create')), 2)
        self.assertIn('One more line.', self.drive.docs['doc1'])
        self.assertIn(b'One more line.', (self.root / 'document.docx').read_bytes())
        self.assertEqual({state for _, _, state in self.shown()}, {'made'})

    def test_a_training_reached_by_another_path_still_has_its_copies_made(self):
        self.built('word')
        other = self.root.parent / 'another-way-in'
        other.symlink_to(self.root, target_is_directory=True)
        made, _ = copies.make(other, word=self.word)
        self.assertEqual([entry['link'] for entry in made],
                         ['document.docx', 'product-brief.docx'])


# --- a Google Doc that cannot be made ------------------------------------------------------

class GoogleTests(Built):
    def test_a_refused_doc_is_not_made_says_why_and_the_rest_carries_on(self):
        self.built('google', 'word')
        made, problems = self.copy(google=Refusing())
        self.assertEqual(problems, {'document': REFUSAL, 'brief': REFUSAL})
        self.assertEqual([(entry['artifact'], entry['kind']) for entry in made],
                         [('document', 'word'), ('brief', 'word')])
        # Kept by the caller and passed back, the reason is shown with the copy it is about.
        self.assertEqual([(entry['kind'], entry['state'], entry['problem'])
                          for entry in copies.wanted(self.root, problems)],
                         [('google', 'not-made', REFUSAL), ('word', 'made', None)] * 2)
        self.assertEqual({entry['problem'] for entry in copies.wanted(self.root)}, {None})
        # The core has nowhere to say why, but it does say the Doc is not there.
        report = self.check('--complete')
        self.assertEqual((report['ready'], report['limitations']),
                         (True, ['document is not in a Google Doc',
                                 'brief is not in a Google Doc']))

    def test_trying_again_makes_what_was_refused_and_its_reason_is_no_longer_shown(self):
        self.built('google')
        _, problems = self.copy(google=Refusing())
        made, again = self.copy()
        self.assertEqual((len(made), again), (2, {}))
        self.assertEqual({(entry['state'], entry['problem'])
                          for entry in copies.wanted(self.root, problems)}, {('made', None)})

    def test_a_computer_with_no_google_access_set_up_is_told_how_to_set_it_up(self):
        self.built('google', 'word')
        with mock.patch.object(copies.shutil, 'which', lambda name: None), \
                mock.patch.object(gdocs, 'GcloudTransport',
                                  mock.Mock(side_effect=AssertionError('not without gcloud'))):
            made, problems = copies.make(self.root, word=self.word)
        self.assertEqual(problems, {'document': copies.NOT_SET_UP, 'brief': copies.NOT_SET_UP})
        self.assertEqual(copies.NOT_SET_UP, 'Google access is not set up on this computer: '
                         'the gcloud command was not found. Install the Google Cloud CLI, run '
                         '`gcloud auth login --enable-gdrive-access` in a terminal, then try '
                         'the copies again.')
        self.assertEqual(len(made), 2)

    def test_left_out_the_transport_is_the_access_this_computer_already_has(self):
        self.built('google')
        signed_out = subprocess.CompletedProcess(['gcloud'], 1, stdout='', stderr='no account')
        with mock.patch.object(copies.shutil, 'which', lambda name: f'/opt/tools/{name}'), \
                mock.patch.object(subprocess, 'run', mock.Mock(return_value=signed_out)) as ran:
            made, problems = copies.make(self.root)
        self.assertEqual(made, [])
        self.assertEqual(set(problems), {'document', 'brief'})
        self.assertIn('gcloud has no signed-in account', problems['document'])
        self.assertEqual(ran.call_args.args[0], ['gcloud', 'auth', 'print-access-token'])

    def test_no_credential_is_ever_in_what_is_returned_or_recorded(self):
        self.built('google')
        signed_in = subprocess.CompletedProcess(['gcloud'], 0, stdout=TOKEN + '\n', stderr='')
        down = urllib.error.URLError(f'no route, Authorization: Bearer {TOKEN}')
        with mock.patch.object(copies.shutil, 'which', lambda name: f'/opt/tools/{name}'), \
                mock.patch.object(subprocess, 'run', mock.Mock(return_value=signed_in)), \
                mock.patch.object(urllib.request, 'urlopen', mock.Mock(side_effect=down)):
            made, problems = copies.make(self.root)
        self.assertEqual((made, set(problems)), ([], {'document', 'brief'}))
        self.assertIn('Could not reach Google Drive', problems['document'])
        kept = ''.join(path.read_text(errors='replace')
                       for path in self.root.rglob('*') if path.is_file())
        self.assertNotIn(TOKEN, repr((made, problems, copies.wanted(self.root, problems))) + kept)

    def test_a_doc_someone_has_edited_is_never_written_over(self):
        self.built('google')
        self.copy()
        self.drive.edit('doc1', 'A customer restarts', 'A customer, a colleague says, restarts')
        theirs = self.drive.docs['doc1']
        self.revise()
        made, problems = self.copy()
        self.assertEqual(made, [])
        self.assertEqual(problems, {'document': copies.REWORDED[0][1]})
        self.assertIn('Someone has changed the Google Doc since it was last sent, so it was '
                      'left as it is.', problems['document'])
        self.assertEqual((self.drive.docs['doc1'], self.drive.did('update')), (theirs, []))
        entry = copies.wanted(self.root, problems)[0]
        self.assertEqual((entry['state'], entry['link'], entry['problem']),
                         ('out-of-date', 'https://docs.example.com/d/doc1/edit',
                          problems['document']))

    def test_what_the_core_says_to_an_assistant_is_said_for_a_person(self):
        self.built('google')
        self.copy()
        self.revise()

        class Lost(FakeTransport):
            def export(self, file_id):
                raise WorkspaceError(
                    'Google could not find the Doc. It may have been deleted, or the '
                    'signed-in account cannot open it. Run google unlink for the artifact, '
                    'then push to make a new Doc.')

        _, problems = self.copy(google=Lost())
        self.assertEqual(problems, {'document': copies.REWORDED[1][1]})
        for said in (copies.NOT_SET_UP, copies.NO_PANDOC, *(ours for _, ours in copies.REWORDED)):
            self.assertFalse([word for word in FORBIDDEN if word in said.lower()], said)
            self.assertIn('try the copies again', said)

    def test_a_drive_that_fails_in_a_way_nobody_expected_does_not_stop_the_run(self):
        self.built('google', 'word')

        class Broken(FakeTransport):
            def create(self, title, markdown):
                raise RuntimeError(f'reply was not JSON: Bearer {TOKEN}')

        made, problems = self.copy(google=Broken())
        self.assertEqual([entry['kind'] for entry in made], ['word', 'word'])
        self.assertEqual(problems['document'], 'Google Drive did not answer as it should have '
                         '(RuntimeError), so the Google Doc was not made. Wait a little, then '
                         'try the copies again.')

    def test_a_push_that_stopped_half_way_is_finished_and_never_makes_a_second_doc(self):
        self.built('google')
        self.drive.fail_export = 1
        made, problems = self.copy()
        self.assertEqual(([entry['artifact'] for entry in made], set(problems)),
                         (['brief'], {'document'}))
        self.assertEqual(self.shown(problems)[0], ('document', 'google', 'out-of-date'))
        made, problems = self.copy()
        self.assertEqual(([entry['artifact'] for entry in made], problems), (['document'], {}))
        self.assertEqual(len(self.drive.did('create')), 2)


# --- a Word copy that cannot be made -------------------------------------------------------

class WordTests(Built):
    def reason(self, name: str = 'document') -> str:
        return workspace.load(self.root)['exports'][name]['unavailable']

    def test_a_computer_without_pandoc_records_through_the_core_why_there_is_no_copy(self):
        self.built('word')
        with mock.patch.object(copies.shutil, 'which', lambda name: None):
            made, problems = copies.make(self.root)
        self.assertEqual((made, problems), ([], {}))
        self.assertEqual(self.reason(), 'Word copies are made with pandoc, which is not on '
                         'this computer. Install it, then try the copies again.')
        self.assertEqual(self.cli('status')['exports'],
                         {'document': 'unavailable', 'brief': 'unavailable'})
        self.assertEqual(copies.wanted(self.root), [
            {'artifact': 'document', 'label': 'the learner guide', 'kind': 'word',
             'state': 'not-made', 'link': None, 'problem': copies.NO_PANDOC},
            {'artifact': 'brief', 'label': 'the brief', 'kind': 'word',
             'state': 'not-made', 'link': None, 'problem': copies.NO_PANDOC}])
        report = self.check('--complete')
        self.assertEqual((report['ready'], report['limitations']),
                         (True, ['document has no export', 'brief has no export']))
        self.assertEqual(list(self.root.rglob('*.docx')), [])

    def test_trying_again_with_a_converter_makes_the_copy(self):
        self.built('word')
        with mock.patch.object(copies.shutil, 'which', lambda name: None):
            copies.make(self.root)
        made, _ = self.copy()
        self.assertEqual([entry['state'] for entry in made], ['made', 'made'])
        self.assertEqual(self.cli('status')['exports'],
                         {'document': 'current', 'brief': 'current'})
        self.assertEqual(self.check('--complete')['limitations'], [])

    def test_a_converter_that_fails_leaves_no_half_made_file_and_says_why(self):
        self.built('word')

        def gives_up(source, target):
            target.write_bytes(b'half a file')
            raise OSError('disk full')

        def makes_nothing(source, target):
            return None

        def refuses(source, target):
            raise WorkspaceError('The converter is out of order today. Try the copies again.')

        for convert, reason in (
                (gives_up, 'The Word copy could not be made (OSError). Try the copies again.'),
                (makes_nothing, 'The converter left no Word file. Try the copies again.'),
                (refuses, 'The converter is out of order today. Try the copies again.')):
            with self.subTest(convert.__name__):
                self.assertEqual(copies.make(self.root, word=convert), ([], {}))
                self.assertEqual((self.reason(), self.reason('brief')), (reason, reason))
                self.assertEqual([path.name for path in self.root.iterdir()
                                  if 'docx' in path.name], [])

    def test_a_copy_that_cannot_be_made_again_is_no_longer_called_current(self):
        self.built('word')
        self.copy()
        self.revise()

        def broken(source, target):
            raise OSError('gone')

        self.assertEqual(copies.make(self.root, word=broken), ([], {}))
        self.assertEqual(self.shown(), [('document', 'word', 'not-made'),
                                        ('brief', 'word', 'made')])
        self.assertEqual(copies.wanted(self.root)[0]['link'], None)

    def test_with_yoodli_on_the_brief_and_each_yoodli_scenario_get_a_word_copy(self):
        self.built(yoodli=True)
        made, _ = self.copy()
        self.assertEqual([(entry['artifact'], entry['link']) for entry in made],
                         [('brief', 'product-brief.docx'), ('yoodli:main', 'yoodli/main.docx')])
        report = self.check('--complete')
        self.assertEqual((report['ready'], report['limitations']), (True, []))


class PandocTests(Built):
    """The converter that is used when none is given, with a pretend pandoc behind it."""

    def setUp(self):
        super().setUp()
        self.ran: list[list[str]] = []
        self.answers: list = []
        self.built('word')
        for owner, name, stand_in in ((copies.shutil, 'which', lambda name: f'/opt/tools/{name}'),
                                      (subprocess, 'run', self.run_pandoc)):
            patcher = mock.patch.object(owner, name, stand_in)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_pandoc(self, command, **options):
        self.ran.append(command)
        answer = self.answers.pop(0) if self.answers else 0
        if isinstance(answer, Exception):
            raise answer
        code, said = answer if isinstance(answer, tuple) else (answer, '')
        if code == 0:
            Path(command[command.index('--output') + 1]).write_bytes(b'PK made by pandoc')
        return subprocess.CompletedProcess(command, code, stdout='', stderr=said)

    def test_pandoc_is_kept_to_the_one_file_it_is_given(self):
        made, _ = copies.make(self.root)
        self.assertEqual([entry['link'] for entry in made],
                         ['document.docx', 'product-brief.docx'])
        self.assertEqual((self.root / 'document.docx').read_bytes(), b'PK made by pandoc')
        command = self.ran[0]
        self.assertEqual(command[:6], ['/opt/tools/pandoc', '--sandbox', '--from',
                                       'markdown-raw_attribute', '--to', 'docx'])
        self.assertEqual(command[-1], str(self.root / 'document.md'))
        self.assertEqual(len(self.ran), 2)
        # The copy is made outside the training and moved in whole.
        self.assertNotIn(str(self.root), command[command.index('--output') + 1])

    def test_an_older_pandoc_is_used_as_it_is_only_for_a_file_that_names_no_picture(self):
        self.answers = [(6, 'Unknown option --sandbox.'), 0, (6, 'Unknown option --sandbox.'), 0]
        made, _ = copies.make(self.root)
        self.assertEqual(len(made), 2)
        self.assertEqual(['--sandbox' in command for command in self.ran],
                         [True, False, True, False])

        self.write('document.md', example('document.md') + '\n![a chart](/etc/passwd)\n')
        self.cli('approve', 'document')
        self.answers = [(6, '[WARNING] Deprecated: something\nUnknown option --sandbox.\n'
                         'Try pandoc --help for more information.')]
        self.assertEqual(copies.make(self.root), ([], {}))
        self.assertEqual(len(self.ran), 5)
        self.assertEqual(workspace.load(self.root)['exports']['document']['unavailable'],
                         'pandoc could not make the Word copy (Unknown option --sandbox). Put '
                         'that right, then try the copies again.')

    def test_a_pandoc_that_does_not_finish_or_cannot_start_is_a_reason_not_an_error(self):
        timed_out = subprocess.TimeoutExpired(['pandoc'], copies.TIMEOUT)
        self.answers = [timed_out, OSError(8, 'Exec format error')]
        self.assertEqual(copies.make(self.root), ([], {}))
        exports = workspace.load(self.root)['exports']
        self.assertEqual(exports['document']['unavailable'], 'pandoc did not finish in 120 '
                         'seconds, so the Word copy was not made. Try the copies again.')
        self.assertEqual(exports['brief']['unavailable'], 'pandoc could not be started (Exec '
                         'format error), so the Word copy was not made. Try the copies again.')

    def test_what_pandoc_says_is_recorded_without_where_this_computer_keeps_things(self):
        self.answers = [(1, f'pandoc: {self.root}/document.md: withBinaryFile: failed'),
                        (1, f'pandoc: {self.root}/document.md: withBinaryFile: failed'), 0]
        copies.make(self.root)
        reason = workspace.load(self.root)['exports']['document']['unavailable']
        self.assertEqual(reason, 'pandoc could not make the Word copy (pandoc: /document.md: '
                         'withBinaryFile: failed). Put that right, then try the copies again.')
        self.assertNotIn(str(self.root.parent), reason)


if __name__ == '__main__':
    unittest.main()
