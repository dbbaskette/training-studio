"""The harness-slides wrapper, against a stand-in for the command line. Neither Node nor the
installed skill is needed, no program renders anything, and nothing touches the network.
"""
import copy
import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest import mock

import runner_support  # noqa: F401  puts the runner on the import path

from runner import brand, slides
from workspace import WorkspaceError

SCRIPT = Path('scripts') / 'harness-slides.mjs'
DIRECTION = {'focal': 'headingPrimary', 'neutral': 'canvasSecondary'}
STEPS = {'id': 'what-it-is', 'kind': 'content', 'relation': 'order', 'focal': 'Restart',
         'title': 'A rolling restart replaces a batch at a time',
         'understand': 'Capacity holds because only one batch is down at a time.',
         'points': [{'label': 'Drain', 'text': 'Stop sending traffic to one batch.'},
                    {'label': 'Restart', 'text': 'Restart the batch.'},
                    {'label': 'Check', 'text': 'Wait for the health check.'}],
         'caveat': 'Capacity holds only with more than one instance.',
         'source': 'Platform documentation: restarts', 'notes': 'Walk the three steps.',
         'sources': ['O1']}
PAIR = {'id': 'when-it-helps', 'kind': 'content', 'relation': 'contrast',
        'rhythm': 'breathing', 'title': 'Two instances keep an app serving',
        'understand': 'One instance cannot hold capacity through a restart.',
        'points': [{'label': 'One instance', 'text': 'The app is down while it restarts.'},
                   {'label': 'Two or more', 'text': 'One serves while the other restarts.'}],
        'sources': ['O2', 'O1']}
OUTLINE = {'version': 1, 'title': 'Rolling restarts 101', 'audience': 'Operators',
           'minutes': 20, 'direction': DIRECTION,
           'layouts': {'cover': 'Title Slide', 'section': 'Section Header',
                       'closing': 'Big Statement'},
           'slides': [{'id': 'cover-rolling', 'kind': 'cover', 'title': 'Rolling restarts 101',
                       'subtitle': 'Keeping capacity while instances restart',
                       'notes': 'Welcome.'},
                      STEPS, PAIR,
                      {'id': 'closing-next', 'kind': 'closing', 'title': 'Practise next'}]}


def installed(folder: Path) -> Path:
    """A folder that looks like an installed harness-slides."""
    (folder / 'scripts').mkdir(parents=True)
    (folder / SCRIPT).write_text('// the command line\n')
    return folder


def says(version: str = slides.MINIMUM):
    """A command line that only ever states its version."""
    return lambda command, cwd=None: (0, f'Harness Slides {version}\n', '')


def picture(path) -> tuple[int, int, bytes]:
    """A PNG read the long way: its width, its height and its rows of pixels."""
    data = Path(path).read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n', 'not a PNG'
    at, chunks = 8, {}
    while at < len(data):
        (length,), kind = struct.unpack('>I', data[at:at + 4]), data[at + 4:at + 8]
        body = data[at + 8:at + 8 + length]
        assert struct.unpack('>I', data[at + 8 + length:at + 12 + length])[0] \
            == zlib.crc32(kind + body), 'a chunk does not match its checksum'
        chunks[kind] = chunks.get(kind, b'') + body
        at += 12 + length
    width, height, depth, colour = struct.unpack('>IIBB', chunks[b'IHDR'][:10])
    rows = zlib.decompress(chunks[b'IDAT'])
    assert (depth, colour, len(rows)) == (8, 2, (width * 3 + 1) * height)
    return width, height, rows


class FindingTheRuntimeTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.home = Path(holder.name).resolve()
        patches = (mock.patch.dict(os.environ), mock.patch.object(Path, 'home',
                                                                  return_value=self.home))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        os.environ.pop(slides.VARIABLE, None)

    def test_the_override_is_the_only_place_looked(self):
        installed(self.home / '.claude' / 'skills' / 'harness-slides')
        chosen = installed(self.home / 'elsewhere')
        os.environ[slides.VARIABLE] = str(chosen)
        self.assertEqual(slides.find_runtime(), chosen)
        os.environ[slides.VARIABLE] = str(self.home / 'nowhere')
        with self.assertRaisesRegex(WorkspaceError, 'HARNESS_SLIDES_RUNTIME names .*nowhere, '
                                    'which does not hold harness-slides'):
            slides.find_runtime()

    def test_the_usual_install_locations_are_tried_in_turn(self):
        with self.assertRaisesRegex(WorkspaceError, 'The harness-slides skill is not '
                                    'installed on this computer, so a deck cannot be made'):
            slides.find_runtime()
        linked = installed(self.home / '.cursor' / 'skills' / 'harness-slides')
        self.assertEqual(slides.find_runtime(), linked)
        shared = installed(self.home / '.local' / 'share' / 'harness-slides' / 'current')
        self.assertEqual(slides.find_runtime(), shared)

    def test_links_are_followed_so_one_version_is_used_throughout(self):
        version = installed(self.home / 'Library' / 'Application Support' / 'Harness Slides'
                            / 'versions' / '0.13.0')
        (version.parent.parent / 'current').symlink_to(Path('versions') / '0.13.0')
        skill = self.home / '.agents' / 'skills'
        skill.mkdir(parents=True)
        (skill / 'harness-slides').symlink_to(version.parent.parent / 'current')
        self.assertEqual(slides.find_runtime(), version)
        self.assertEqual(slides.Slides(run=says()).runtime, version)

    def test_its_own_guidance_is_read_from_inside_its_folder_and_never_run(self):
        home = installed(self.home / 'runtime')
        (home / 'references' / 'gallery').mkdir(parents=True)
        for name, text in (('design.md', '# Design\n'), ('compositions.md', '# Compose\n'),
                           ('draft.md', 'x' * (slides.READ_MOST + 500)),
                           ('gallery/order.json', '{"brief": {"relation": "order"}}\n'),
                           ('gallery/unknown.json', '{}\n'), ('review.md', '# Review\n'),
                           ('gallery/none.json', '  \n')):
            (home / 'references' / name).write_text(text)
        (self.home / 'private.md').write_text('Not the tool\'s to hand on.\n')
        (home / 'references' / 'gallery.md').symlink_to(self.home / 'private.md')
        (home / 'references' / 'gallery' / 'contrast.json').symlink_to(
            home / 'references' / 'gallery' / 'order.json')
        ran = []
        tool = slides.Slides(runtime=home, run=lambda command, cwd=None: (
            ran.append(command) or (0, f'Harness Slides {slides.MINIMUM}\n', '')))
        self.assertEqual(tool.runtime, home)
        del ran[:]
        found = tool.reading()
        self.assertEqual(found, tool.reading(self.home / 'brand-contract.json'),
                         'it is the same for every brand')
        self.assertEqual(list(found), ['design guidance', 'composition guidance',
                                       'drafting guidance', 'example order',
                                       'example contrast'],
                         'only what a writer or a composer needs, a link out of the folder is '
                         'not followed, and what the tool does not have is left out')
        self.assertEqual((found['design guidance'], found['example order']),
                         ('# Design\n', '{"brief": {"relation": "order"}}\n'))
        self.assertEqual(len(found['drafting guidance']), slides.READ_MOST)
        self.assertEqual(ran, [], 'nothing is run to read it')
        self.assertEqual(slides.example('order'), 'example order')
        self.assertEqual(slides.Slides(runtime=self.home / 'nowhere', run=says()).reading(), {})

    def test_the_stand_in_has_short_guidance_of_its_own(self):
        found = slides.stand_in().reading()
        self.assertEqual(list(found), [
            'design guidance', 'composition guidance', 'drafting guidance', 'gallery',
            *(slides.example(relation) for relation in slides.RELATIONS[:-1])])
        self.assertTrue(all(len(text) < 2000 for text in found.values()))
        for relation in slides.RELATIONS[:-1]:
            drawn = json.loads(found[slides.example(relation)])
            self.assertEqual(drawn['brief']['relation'], relation)

    def test_the_real_command_needs_node(self):
        os.environ[slides.VARIABLE] = str(installed(self.home / 'runtime'))
        with mock.patch.object(slides.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(WorkspaceError, 'needs Node.js 20 or newer'):
                slides.Slides()
        with mock.patch.object(slides.shutil, 'which', return_value='/usr/bin/node'), \
                mock.patch.object(slides, 'run_command', says()):
            self.assertEqual(slides.Slides().node, '/usr/bin/node')

    def test_a_tool_that_is_too_old_is_refused_when_it_is_found(self):
        os.environ[slides.VARIABLE] = str(installed(self.home / 'runtime'))
        for version in (slides.MINIMUM, '0.14.0-beta.2', '1.0.0'):
            self.assertEqual(slides.Slides(run=says(version)).version(), version)
        for version in ('0.12.9', '0.9.0'):
            with self.assertRaisesRegex(WorkspaceError, f'harness-slides {version} is '
                                        f'installed, and a deck needs {slides.MINIMUM} or '
                                        'newer. Update it, then try again.'):
                slides.Slides(run=says(version))
        with self.assertRaisesRegex(WorkspaceError, 'did not say which version it is'):
            slides.Slides(run=lambda command, cwd=None: (0, 'Usage: ...\n', ''))


class CommandTests(unittest.TestCase):
    """What is run, and how its answers and refusals are read."""

    def setUp(self):
        self.ran, self.answers = [], []
        self.slides = slides.Slides(runtime=Path('/opt/harness-slides'), run=self.pretend)
        self.ran.clear()

    def pretend(self, command, cwd=None):
        self.ran.append(command)
        if command[2:] == ['--version']:
            return 0, f'Harness Slides {slides.MINIMUM}\n', ''
        return self.answers.pop(0) if self.answers else (0, '{"status": "sound"}\n', '')

    def test_asking_for_the_version_is_all_that_happens_when_it_is_made(self):
        ran = []
        slides.Slides(runtime=Path('/opt/harness-slides'),
                      run=lambda command, cwd=None: ran.append(command) or says()(command))
        self.assertEqual(ran, [['node', '/opt/harness-slides/scripts/harness-slides.mjs',
                                '--version']])

    def test_each_command_is_run_as_the_command_line_takes_it(self):
        deck = self.slides
        self.assertEqual(deck.outline_check(Path('/d/outline.json'), Path('/d/brand.json')),
                         {'status': 'sound'})
        deck.outline_start('/d/outline.json', '/d/brand.json', '/d/build')
        deck.layouts('/d/brand.json')
        deck.compile('/d/section-1.json', '/d/brand.json')
        deck.compile('/d/composition.json', '/d/brand.json', '/d/compiled')
        deck.merge('/d/build/parts.json', '/d/build/composition.json')
        deck.critique('/d/preview', '/d/assessment.json')
        deck.render('/d/compiled', '/d/deck.pptx')
        deck.drive_import('/d/deck.pptx', 'Rolling restarts 101')
        self.assertEqual({tuple(command[:2]) for command in self.ran},
                         {('node', '/opt/harness-slides/scripts/harness-slides.mjs')})
        self.assertEqual([command[2:] for command in self.ran], [
            ['outline', 'check', '--file', '/d/outline.json', '--brand', '/d/brand.json'],
            ['outline', 'start', '--file', '/d/outline.json', '--brand', '/d/brand.json',
             '--output', '/d/build'],
            ['compose', 'layouts', '--brand', '/d/brand.json'],
            ['compose', 'compile', '--file', '/d/section-1.json', '--brand', '/d/brand.json'],
            ['compose', 'compile', '--file', '/d/composition.json', '--brand',
             '/d/brand.json', '--output', '/d/compiled'],
            ['compose', 'merge', '--file', '/d/build/parts.json', '--output',
             '/d/build/composition.json'],
            ['compose', 'critique', '--file', '/d/preview', '--assessment',
             '/d/assessment.json'],
            ['compose', 'render', '--file', '/d/compiled', '--output', '/d/deck.pptx'],
            ['drive', 'import', '--file', '/d/deck.pptx', '--name', 'Rolling restarts 101']])

    def test_a_contract_comes_back_as_the_text_a_worker_is_told(self):
        self.answers = [(0, 'Outline v1\nFor a brand: 90 body words.\n', ''),
                        (0, 'Composition v1\nSizes, in points.\n\n', '')]
        self.assertEqual(self.slides.outline_contract('/d/brand.json'),
                         'Outline v1\nFor a brand: 90 body words.')
        self.assertEqual(self.slides.compose_contract('/d/brand.json'),
                         'Composition v1\nSizes, in points.')
        self.assertEqual([command[2:] for command in self.ran],
                         [['outline', 'contract', '--brand', '/d/brand.json'],
                          ['compose', 'contract', '--brand', '/d/brand.json']])

    def test_a_preview_names_its_renderer_and_reuses_a_file_only_in_drive(self):
        shown = {'deck': '/d/p/deck.pptx', 'deckSha256': 'abc', 'critic': '/d/p/critic.json',
                 'contactSheet': '/d/p/contact-sheet.png',
                 'renderer': 'Google Slides PDF export', 'fileId': 'file-1',
                 'url': 'https://docs.example.com/file-1', 'slides': [
                     {'id': 'cover-rolling', 'number': 1, 'title': 'Rolling restarts 101',
                      'image': '/d/p/slide-01.png', 'findings': []}]}
        local = {'deck': '/d/q/deck.pptx', 'deckSha256': 'def', 'renderer': 'LibreOffice',
                 'slides': shown['slides']}
        self.answers = [(0, json.dumps(shown), ''), (0, json.dumps(shown), ''),
                        (0, json.dumps(local), '')]
        first = self.slides.preview('/d/compiled', '/d/p', 'drive')
        self.assertEqual(first, {**shown, 'renderer': 'drive'})
        self.slides.preview('/d/compiled', '/d/p2', 'drive', file_id='file-1',
                            slide='what-it-is')
        offline = self.slides.preview('/d/compiled', '/d/q', 'local', file_id='file-1')
        self.assertEqual((offline['renderer'], offline['fileId'], offline['url'],
                          offline['contactSheet'], offline['deck']),
                         ('local', None, None, None, '/d/q/deck.pptx'))
        self.assertEqual([command[2:] for command in self.ran], [
            ['compose', 'preview', '--file', '/d/compiled', '--output', '/d/p', '--renderer',
             'google'],
            ['compose', 'preview', '--file', '/d/compiled', '--output', '/d/p2',
             '--renderer', 'google', '--file-id', 'file-1', '--slide', 'what-it-is'],
            ['compose', 'preview', '--file', '/d/compiled', '--output', '/d/q', '--renderer',
             'local']])

    def test_a_preview_is_rendered_through_drive_or_on_this_computer_and_nothing_else(self):
        with self.assertRaisesRegex(WorkspaceError, 'rendered through drive or local, not '
                                    'google'):
            self.slides.preview('/d/compiled', '/d/p', 'google')
        self.assertEqual(self.ran, [])
        self.answers = [(0, '{"status": "rendered"}', '')]
        with self.assertRaisesRegex(WorkspaceError, 'did not say where its slides are'):
            self.slides.preview('/d/compiled', '/d/p', 'local')

    def test_a_refusal_carries_each_line_the_tool_gave(self):
        fit = ('what-it-is/s1_drain: needs 373pt of height but has 292pt at 268pt wide; '
               'shorten the text, split the slide or restructure')
        focal = 'when-it-helps/s1_one: only the focal node may use the focal color'
        self.answers = [
            (1, '', f'2 problems to fix:\n{fit}\n{focal}\n'),
            (1, '', 'unbound prefix: line 1, column 786\n'),
            (1, 'ignored', '\n(node:41) ExperimentalWarning: something\n(Use `node '
             f'--trace-warnings ...` to show where)\n2 problems to fix:\n{fit}\n\n{focal}\n'),
            (3, '', '')]
        with self.assertRaises(slides.Refused) as refused:
            self.slides.compile('/d/section-1.json', '/d/brand.json')
        self.assertEqual(refused.exception.problems, [fit, focal])
        self.assertEqual(str(refused.exception), f'The slides tool refused: {fit} {focal}')
        self.assertIsInstance(refused.exception, WorkspaceError)
        self.assertIsNone(refused.exception.left)
        with self.assertRaises(slides.Refused) as refused:
            self.slides.render('/d/compiled', '/d/nowhere/deck.pptx')
        self.assertEqual(refused.exception.problems, ['unbound prefix: line 1, column 786'])
        with self.assertRaises(slides.Refused) as refused:
            self.slides.compile('/d/section-1.json', '/d/brand.json')
        self.assertEqual(refused.exception.problems, [fit, focal])
        with self.assertRaisesRegex(slides.Refused, 'it ended with exit code 3'):
            self.slides.layouts('/d/brand.json')

    def test_a_preview_that_failed_after_its_upload_says_what_it_left_in_drive(self):
        self.answers = [(1, '', 'The render has 8 pages for 2 slides; check the deck for an '
                         'import problem The preview deck is in Drive (https://docs.example.'
                         'com/d/file-9/edit); retry with --file-id file-9.\n')]
        with self.assertRaises(slides.Refused) as refused:
            self.slides.preview('/d/compiled', '/d/nowhere/p', 'drive')
        self.assertEqual(refused.exception.left,
                         {'fileId': 'file-9', 'url': 'https://docs.example.com/d/file-9/edit'})

    def test_an_answer_that_is_not_json_is_not_trusted(self):
        for answer in ('Usage: node scripts/harness-slides.mjs ...', '[1, 2]', ''):
            self.answers = [(0, answer, '')]
            with self.assertRaisesRegex(WorkspaceError, 'something other than the JSON'):
                self.slides.layouts('/d/brand.json')

    def test_the_version_is_read_from_what_the_command_prints(self):
        self.assertEqual(self.slides.version(), slides.MINIMUM)
        self.assertEqual(self.ran[0][2:], ['--version'])

    def test_drive_is_reached_or_it_is_not(self):
        self.answers = [(0, '{"account": "person@example.com", "pptxImportAdvertised": '
                         'true}', ''),
                        (0, '{"account": "person@example.com", "pptxImportAdvertised": '
                         'false}', ''),
                        (1, '', 'Google API request failed (HTTP 403). Check account, Drive '
                         'scopes, file access, and organization policy.\n'),
                        (0, 'not json', '')]
        self.assertIs(self.slides.drive_check(), True)
        self.assertIs(self.slides.drive_check(), False)
        self.assertIs(self.slides.drive_check(), False)
        self.assertEqual([command[2:] for command in self.ran], [['drive', 'check']] * 3)
        with self.assertRaisesRegex(WorkspaceError, 'something other than the JSON'):
            self.slides.drive_check()

    def test_a_command_that_hangs_or_cannot_start_is_a_refusal(self):
        self.assertEqual(slides.run_command([sys.executable, '-c', 'print("ok")']),
                         (0, 'ok\n', ''))
        slow = subprocess.TimeoutExpired(['node'], slides.TIMEOUT)
        with mock.patch.object(slides.subprocess, 'run', side_effect=slow):
            with self.assertRaisesRegex(WorkspaceError, 'did not answer in 300 seconds'):
                slides.run_command(['node'])
        with self.assertRaisesRegex(WorkspaceError, 'could not be started'):
            slides.run_command(['no-such-program-anywhere'])


class LeavingNothingBehindTests(unittest.TestCase):
    """A call that fails after it wrote removes what it wrote, and only that."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name).resolve()
        self.fate = (1, '', 'unbound prefix: line 1, column 786\n')
        self.slides = slides.Slides(runtime=Path('/opt/harness-slides'), run=self.pretend)

    def pretend(self, command, cwd=None):
        """Writes what the real command writes, then ends as `fate` says."""
        if command[2:] == ['--version']:
            return says()(command)
        output = Path(command[command.index('--output') + 1])
        if output.suffix:
            output.write_bytes(b'PK\x03\x04 a deck that cannot be opened')
        else:
            output.mkdir()
            (output / 'deck.pptx').write_bytes(b'PK\x03\x04 a deck that cannot be opened')
        if isinstance(self.fate, Exception):
            raise self.fate
        return self.fate

    def test_a_failed_render_leaves_nothing_behind(self):
        deck = self.root / 'deck.pptx'
        with self.assertRaises(slides.Refused) as refused:
            self.slides.render(self.root / 'compiled', deck)
        self.assertEqual(refused.exception.problems, ['unbound prefix: line 1, column 786'])
        self.assertEqual(list(self.root.iterdir()), [])
        self.fate = WorkspaceError('The slides tool did not answer in 300 seconds.')
        with self.assertRaisesRegex(WorkspaceError, 'did not answer'):
            self.slides.render(self.root / 'compiled', deck)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_a_failed_preview_leaves_nothing_behind(self):
        for self.fate in ((1, '', 'The render has 8 pages for 2 slides\n'),
                          (0, 'not json', ''), (0, '{"deck": "somewhere"}', ''),
                          WorkspaceError('The slides tool did not answer in 300 seconds.')):
            with self.subTest(self.fate):
                with self.assertRaises(WorkspaceError):
                    self.slides.preview(self.root / 'compiled', self.root / 'preview',
                                        'drive')
                self.assertEqual(list(self.root.iterdir()), [])

    def test_so_does_every_other_call_that_writes(self):
        for call, args in ((self.slides.outline_start, ('outline.json', 'brand.json')),
                           (self.slides.compile, ('composition.json', 'brand.json')),
                           (self.slides.merge, ('parts.json',))):
            for name in ('build', 'composition.json'):
                with self.subTest(call=call.__name__, name=name):
                    with self.assertRaises(slides.Refused):
                        call(*args, self.root / name)
                    self.assertEqual(list(self.root.iterdir()), [])

    def test_what_was_there_before_a_failed_call_is_never_removed(self):
        deck, folder = self.root / 'deck.pptx', self.root / 'preview'
        deck.write_bytes(b'PK\x03\x04 an earlier deck')
        folder.mkdir()
        (folder / 'kept.txt').write_text('an earlier preview\n')

        def refuses(command, cwd=None):
            return says()(command) if command[2:] == ['--version'] else (
                1, '', 'It already exists; choose a new output file\n')

        careful = slides.Slides(runtime=Path('/opt/harness-slides'), run=refuses)
        with self.assertRaisesRegex(slides.Refused, 'already exists'):
            careful.render(self.root / 'compiled', deck)
        with self.assertRaisesRegex(slides.Refused, 'already exists'):
            careful.preview(self.root / 'compiled', folder, 'local')
        self.assertEqual(deck.read_bytes(), b'PK\x03\x04 an earlier deck')
        self.assertEqual((folder / 'kept.txt').read_text(), 'an earlier preview\n')

    def test_what_a_call_wrote_is_kept_when_it_succeeds(self):
        self.fate = (0, '{"output": "deck.pptx", "slides": 4}', '')
        self.assertEqual(self.slides.render(self.root / 'compiled', self.root / 'deck.pptx'),
                         {'output': 'deck.pptx', 'slides': 4})
        self.assertTrue((self.root / 'deck.pptx').is_file())


class Deck(unittest.TestCase):
    """A made-up deck, a made-up brand, and both stand-ins."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name).resolve()
        self.slides, self.brand = slides.stand_in(), brand.stand_in()
        self.tool = self.slides.run
        self.contract = self.brand.export(self.root / 'brand', 'example', 'light')['contract']
        self.wrote = 0

    def write(self, value, name: str | None = None) -> Path:
        self.wrote += 1
        path = self.root / (name or f'written-{self.wrote}.json')
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def outline(self, *slides_, **changes) -> Path:
        """The outline as a file, with other slides or other fields when they are given."""
        return self.write({**OUTLINE, **({'slides': list(slides_)} if slides_ else {}),
                           **changes})

    def refusal(self, call, *args, **named) -> list[str]:
        with self.assertRaises(slides.Refused) as refused:
            call(*args, **named)
        return refused.exception.problems

    def composed(self, *drawn, **changes) -> Path:
        """A composition of the slides given, or of the whole deck drawn plainly."""
        lead = [{'id': s['id'], 'title': s['title'], 'layout': OUTLINE['layouts'][s['kind']],
                 **({'subtitle': s['subtitle']} if 'subtitle' in s else {}),
                 'sources': ['outline'], 'brief': {'rhythm': 'anchor'}}
                for s in OUTLINE['slides'] if s['kind'] != 'content']
        whole = [lead[0], slides.sketch(STEPS, 's1_'), slides.sketch(PAIR, 's1_'), lead[1]]
        return self.write({'version': 1, 'title': OUTLINE['title'], 'direction': DIRECTION,
                           'slides': list(drawn) or whole, **changes})

    def compiled(self, *drawn) -> Path:
        self.wrote += 1
        folder = self.root / f'compiled-{self.wrote}'
        self.slides.compile(self.composed(*drawn), self.contract, folder)
        return folder

    def previewed(self, **named) -> dict:
        self.wrote += 1
        return self.slides.preview(named.pop('compiled', None) or self.compiled(),
                                   self.root / f'preview-{self.wrote}',
                                   named.pop('renderer', 'drive'), **named)


class PreviewsOneAtATimeTests(Deck):
    def side_by_side(self, preview) -> list:
        """Four previews asked for at the same moment, each into its own folder."""
        compiled, failures = self.compiled(), []
        ready = threading.Barrier(4)

        def one(number):
            ready.wait()
            try:
                preview(compiled, self.root / f'side-{preview.__name__}-{number}')
            except Exception as failure:   # shown by the assertion below
                failures.append(failure)

        threads = [threading.Thread(target=one, args=(number,)) for number in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return failures

    def test_two_previews_at_once_never_overlap(self):
        self.tool.pause = 0.05

        def locked(compiled, folder):
            return self.slides.preview(compiled, folder, 'drive')

        self.assertEqual(self.side_by_side(locked), [])
        self.assertEqual(self.tool.at_once, 1)
        self.assertEqual(len(self.tool.files), 4)

    def test_without_the_lock_they_would(self):
        self.tool.pause = 0.2

        def unlocked(compiled, folder):
            code, _, said = self.tool(['node', 'script', 'compose', 'preview', '--file',
                                       str(compiled), '--output', str(folder)])
            self.assertEqual((code, said), (0, ''))

        self.assertEqual(self.side_by_side(unlocked), [])
        self.assertGreater(self.tool.at_once, 1)

    def test_the_lock_is_let_go_when_a_preview_is_refused(self):
        self.tool.drive = False
        self.assertIn('HTTP 403', self.refusal(self.previewed)[0])
        self.tool.drive = True
        self.assertEqual(len(self.previewed()['slides']), 4)


class ReadyTests(Deck):
    def test_it_says_what_this_computer_has(self):
        asked = []

        def which(program):
            asked.append(program)
            return f'/usr/bin/{program}'

        self.assertEqual(slides.ready(self.slides, which=which),
                         {'tool': True, 'version': slides.MINIMUM, 'pictures': True,
                          'local': True, 'drive': True, 'missing': []})
        self.assertEqual(asked, ['python3', 'pdftoppm', 'pdfinfo', 'soffice'])
        self.assertEqual(self.tool.calls, [['--version'], ['--version'], ['drive', 'check']])

    def test_each_missing_thing_is_a_sentence_for_a_person(self):
        self.tool.drive = False
        found = slides.ready(self.slides, which=lambda program: (
            None if program in ('pdfinfo', 'soffice') else program))
        self.assertEqual((found['tool'], found['pictures'], found['local'], found['drive']),
                         (True, False, False, False))
        self.assertEqual(found['missing'], [
            'Poppler (pdftoppm and pdfinfo) was not found, so a render cannot be turned '
            'into pictures. Install Poppler, then try again.',
            'LibreOffice was not found, so previews cannot be rendered on this computer. '
            'Install it, or render previews through Google Drive.',
            'Google access does not reach Drive, so previews cannot be rendered there. Run '
            '`gcloud auth login --enable-gdrive-access`, or render previews with '
            'LibreOffice.'])

    def test_a_tool_that_is_missing_is_said_once_and_drive_is_not_asked(self):
        with mock.patch.dict(os.environ, {slides.VARIABLE: str(self.root / 'nowhere')}):
            found = slides.ready(which=lambda program: program)
        self.assertEqual((found['tool'], found['version'], found['drive']),
                         (False, None, False))
        self.assertEqual(len(found['missing']), 1)
        self.assertIn('which does not hold harness-slides', found['missing'][0])
        without = slides.ready(self.slides, which=lambda program: (
            None if program == 'python3' else program))
        self.assertEqual((without['tool'], without['drive']), (False, False))
        self.assertRegex(without['missing'][0], 'writes a deck with python3')

    def test_the_tools_own_variables_say_where_its_programs_are(self):
        asked = []
        with mock.patch.dict(os.environ, {'HARNESS_SOFFICE': '/opt/office/soffice',
                                          'HARNESS_PDFINFO': '/opt/poppler/pdfinfo'}):
            slides.ready(self.slides, which=lambda program: asked.append(program) or 'yes')
        self.assertEqual(asked, ['python3', 'pdftoppm', '/opt/poppler/pdfinfo',
                                 '/opt/office/soffice'])


class StandInOutlineTests(Deck):
    """The stand-in checks and splits an outline as the real command line does."""

    def test_a_sound_outline_is_counted_slide_by_slide(self):
        report = self.slides.outline_check(self.outline(), self.contract)
        self.assertEqual({key: report[key] for key in ('status', 'slides', 'delivery',
                                                       'wordBudget', 'words', 'findings')},
                         {'status': 'sound', 'slides': 4, 'delivery': 'reading',
                          'wordBudget': 90, 'findings': [],
                          'words': {'what-it-is': 17, 'when-it-helps': 18}})
        self.assertEqual(len(report['outlineSha256']), 64)

    def test_what_the_words_need_comes_back_as_findings_with_the_tools_codes(self):
        pair = {**PAIR, 'rhythm': 'dense'}
        wordy = {**pair, 'id': 'too-many-words', 'title': STEPS['title'].upper(),
                 'points': [{'label': 'One', 'text': 'word ' * 50},
                            {'label': 'Two', 'text': 'word ' * 50}]}
        long = {**pair, 'id': 'long-title-here', 'title': 'This title is far too long to '
                'fit on the single line that the title of a content slide is given'}
        plain = {key: value for key, value in STEPS.items() if key != 'focal'}
        dense = [{**pair, 'id': f'dense-slide-{n}', 'title': f'Dense slide {n} says a thing'}
                 for n in range(3)]
        report = self.slides.outline_check(
            self.outline(OUTLINE['slides'][0], plain, wordy, long, *dense), self.contract)
        self.assertEqual(report['status'], 'sound; look at the findings')
        self.assertEqual(report['words']['too-many-words'], 102)
        self.assertEqual(report['findings'], [
            {'slide': 'long-title-here', 'code': 'title-too-long', 'detail':
             "The title runs to 2 lines and the brand's title holds 1. Shorten the claim."},
            {'slide': 'too-many-words', 'code': 'over-budget', 'detail':
             '102 body words; a slide delivered for reading carries about 90. Cut words or '
             'split the slide.'},
            {'slide': 'too-many-words', 'code': 'repeated-title',
             'detail': 'Same title as what-it-is.'},
            {'slide': 'dense-slide-0', 'code': 'dense-run', 'detail':
             '6 dense slides in a row from what-it-is. Lighten one and mark it breathing, '
             'or put a section slide between.'},
            {'slide': 'what-it-is', 'code': 'no-focal', 'detail': 'Nothing is named as the '
             'point of this slide. Name it, unless the slide compares equals.'}])

    def test_a_deck_delivered_live_carries_fewer_words_and_needs_notes(self):
        live = self.brand.export(self.root / 'live', 'example', 'light', 'live')['contract']
        wordy = {**PAIR, 'points': [{'label': 'One', 'text': 'word ' * 30},
                                    {'label': 'Two', 'text': 'word ' * 30}]}
        report = self.slides.outline_check(self.outline(STEPS, wordy, delivery='live'), live)
        self.assertEqual((report['delivery'], report['wordBudget']), ('live', 60))
        self.assertEqual([(found['slide'], found['code']) for found in report['findings']],
                         [('when-it-helps', 'over-budget'), ('when-it-helps', 'no-notes')])
        self.assertIn('62 body words; a slide delivered live carries about 60',
                      report['findings'][0]['detail'])
        self.assertEqual(self.refusal(self.slides.outline_check,
                                      self.outline(delivery='live'), self.contract),
                         ['outline: delivery is live, but the brand contract was exported '
                          'for reading; export it for live'])

    def test_a_point_of_its_own_counts_towards_the_words(self):
        own = {**STEPS, 'focal': 'One batch at a time'}
        report = self.slides.outline_check(self.outline(own), self.contract)
        self.assertEqual(report['words'], {'what-it-is': 22})

    def test_an_outline_that_is_not_one_is_refused_in_the_tools_words(self):
        cover = OUTLINE['slides'][0]
        for changes, slides_, lines in (
                ({'version': 2}, (), ['Use outline version 1 (run outline contract)']),
                ({'extra': 1, 'title': ''}, (), ['outline: unsupported field extra',
                                                 'outline: provide the deck title']),
                ({'slides': []}, (), ['outline: provide 1–100 slides']),
                ({'house': 'Sentence case.'}, (), ['outline: house is a list of lines']),
                ({'direction': {'focal': 'headingPrimary'}}, (),
                 ['outline: direction needs focal and neutral color roles']),
                ({}, ({**cover, 'sources': ['O1']}, {**STEPS, 'source_s': ['x']},
                      {**PAIR, 'kind': 'nope'}),
                 ['cover-rolling: a cover slide has no sources',
                  'what-it-is: a content slide has no source_s',
                  'when-it-helps: kind is one of cover|section|content|closing']),
                ({}, ({**STEPS, 'id': 'ab'}, {**PAIR, 'id': 'ab'}),
                 ['ab: invalid or repeated ID: ab', 'ab: invalid or repeated ID: ab']),
                ({}, ({**STEPS, 'sources': []}, {**PAIR, 'relation': 'rivalry'}),
                 ['what-it-is: provide sources: one or more IDs naming what the slide rests '
                  'on, such as request or author_knowledge', 'when-it-helps: relation is '
                  'one of order|dependency|hierarchy|membership|contrast|parallel|overlap|'
                  'quantity|none']),
                ({}, ({**STEPS, 'points': STEPS['points'][:1]},
                      {**PAIR, 'points': [{'label': 'One', 'size': 3}]}),
                 ['what-it-is: relation "order" needs at least 2 points; it has 1',
                  'when-it-helps: points is a list of up to 12 items, each with a label, a '
                  'text or both']),
                ({}, ({**cover, 'detail': 'A second line', 'subtitle': ''},
                      {**STEPS, 'understand': ''}),
                 ['cover-rolling: provide subtitle text or omit it', 'what-it-is: say in '
                  'one sentence what the audience must understand'])):
            with self.subTest(lines[0]):
                self.assertEqual(self.refusal(self.slides.outline_check,
                                              self.outline(*slides_, **changes),
                                              self.contract), lines)

    def test_a_deck_is_split_into_leads_and_sections_of_about_four(self):
        content = [{**PAIR, 'id': f'content-slide-{n}', 'title': f'Content slide {n} says a '
                    'thing'} for n in range(1, 11)]
        cover, closing = OUTLINE['slides'][0], OUTLINE['slides'][-1]
        section = {'id': 'section-two', 'kind': 'section', 'title': 'Part two'}
        started = self.slides.outline_start(
            self.outline(cover, *content, section, STEPS, closing), self.contract,
            self.root / 'build')
        build = self.root / 'build'
        self.assertEqual((started['output'], started['slides'], started['sections']),
                         (str(build), 14, 4))
        self.assertEqual(started['parts'], ['lead-1.json', 'section-1.json', 'section-2.json',
                                            'section-3.json', 'lead-2.json', 'section-4.json',
                                            'lead-3.json'])
        self.assertEqual(started['briefs'], [str(build / 'briefs' / f'section-{n}.md')
                                             for n in range(1, 5)])
        self.assertEqual(sorted(path.relative_to(build).as_posix()
                                for path in build.rglob('*') if path.is_file()),
                         ['briefs/section-1.md', 'briefs/section-2.md', 'briefs/section-3.md',
                          'briefs/section-4.md', 'lead-1.json', 'lead-2.json', 'lead-3.json',
                          'outline.json', 'parts.json', 'presentation-brief.md'])
        self.assertEqual(json.loads((build / 'parts.json').read_text()),
                         {'title': 'Rolling restarts 101', 'direction': DIRECTION,
                          'parts': started['parts']})
        table = (build / 'presentation-brief.md').read_text()
        for row in ('| Lead | lead-1.json | cover-rolling |',
                    '| Worker 1 | section-1.json | content-slide-1, content-slide-2, '
                    'content-slide-3, content-slide-4 |',
                    '| Worker 3 | section-3.json | content-slide-9, content-slide-10 |',
                    '| Lead | lead-2.json | section-two |',
                    '| Worker 4 | section-4.json | what-it-is |',
                    '| Lead | lead-3.json | closing-next |'):
            self.assertIn(row, table)
        self.assertEqual(json.loads((build / 'outline.json').read_text())['title'],
                         'Rolling restarts 101')
        self.assertEqual(stat_mode(build / 'parts.json'), 0o600)

    def test_seven_slides_are_split_four_and_three_and_one_section_stays_whole(self):
        content = [{**PAIR, 'id': f'content-slide-{n}', 'title': f'Content slide {n} says a '
                    'thing'} for n in range(1, 8)]
        self.slides.outline_start(self.outline(*content), self.contract, self.root / 'seven')
        table = (self.root / 'seven' / 'presentation-brief.md').read_text()
        self.assertIn('| Worker 2 | section-2.json | content-slide-5, content-slide-6, '
                      'content-slide-7 |', table)
        one = self.slides.outline_start(self.outline(*content[:4]), self.contract,
                                        self.root / 'four')
        self.assertEqual((one['parts'], one['next']),
                         (['section-1.json'],
                          'Build the section, then compose merge --file parts.json'))

    def test_a_lead_file_holds_the_slides_a_template_layout_draws(self):
        self.slides.outline_start(self.outline(), self.contract, self.root / 'build')
        lead = json.loads((self.root / 'build' / 'lead-1.json').read_text())
        self.assertEqual(lead, {'version': 1, 'title': 'Rolling restarts 101',
                                'direction': DIRECTION, 'slides': [
                                    {'id': 'cover-rolling', 'title': 'Rolling restarts 101',
                                     'layout': 'Title Slide', 'subtitle': 'Keeping capacity '
                                     'while instances restart', 'notes': 'Welcome.',
                                     'sources': ['outline'], 'brief': {'rhythm': 'anchor'}}]})
        self.assertEqual(self.slides.compile(self.root / 'build' / 'lead-1.json',
                                             self.contract)['slides'], 1)

    def test_a_brief_says_what_each_slide_must_say_under_the_tools_headings(self):
        self.slides.outline_start(
            self.outline(house=['Sentence case.'], approval=['Looks right.', 'Go ahead.'],
                         material=['The guide']), self.contract, self.root / 'build')
        brief = (self.root / 'build' / 'briefs' / 'section-1.md').read_text()
        self.assertEqual([line for line in brief.splitlines() if line.startswith('#')],
                         ['# Section 1 of Rolling restarts 101', '## The deck', '## Paths',
                          '## Direction, to copy unchanged', '## House style',
                          '## Your slides, in order', '## Preview', '## Return'])
        for line in (
                'Read `references/parallel-build.md`, the part headed "If you are a worker"',
                'Rolling restarts 101, for Operators, delivered for reading.',
                '- Runtime: `stand-in`', f'- Brand contract: `{self.contract}`',
                f"- Work directory: `{self.root / 'build'}`",
                '- Write your section to `section-1.json`, and keep your builds and previews '
                'under `w1/`.', '- Source material: The guide',
                '{"focal":"headingPrimary","neutral":"canvasSecondary"}', '- Sentence case.',
                'Prefix every node and edge ID you create with `s1_`.',
                '1. **`what-it-is`: "A rolling restart replaces a batch at a time"**',
                '   - The audience must understand: Capacity holds because only one batch is '
                'down at a time.',
                '   - Relation `order`. The point of the slide: Restart.',
                '   - Drain: Stop sending traffic to one batch.',
                '   - Caveat, to set on the slide as `caveat`: "Capacity holds only with more '
                'than one instance."',
                '   - Source line, to set on the slide as `source`: "Platform documentation: '
                'restarts"',
                "   - Speaker notes, to go in the slide's `notes`: Walk the three steps.",
                '   - Sources: ["O1"]',
                '   - Relation `contrast`, rhythm `breathing`. No focal point: it compares '
                'equals.', '   - Sources: ["O2","O1"]',
                'Before your section comes a cover slide; after it comes a closing slide.',
                'Use one Drive preview file of your own for every preview',
                'The section file, your final preview directory, the Drive file ID'):
            self.assertIn(line, brief)
        plan = (self.root / 'build' / 'presentation-brief.md').read_text()
        self.assertIn('For Operators. Delivered for reading. 4 slides.', plan)
        self.assertIn('## Approval\n\n> Looks right.\n>\n> Go ahead.\n', plan)

    def test_a_build_needs_what_a_draft_may_leave_open(self):
        long = {**PAIR, 'title': 'This title is far too long to fit on the single line that '
                'the title of a content slide is given'}
        bare = {key: value for key, value in OUTLINE.items()
                if key not in ('direction', 'layouts')}
        self.assertEqual(
            self.refusal(self.slides.outline_start, self.write({**bare, 'slides': [
                OUTLINE['slides'][0], long, OUTLINE['slides'][-1]]}), self.contract,
                self.root / 'build'),
            ["when-it-helps: The title runs to 2 lines and the brand's title holds 1. "
             'Shorten the claim.',
             'outline: name the template layout for cover slides in layouts.cover (run '
             'compose layouts)',
             'outline: name the template layout for closing slides in layouts.closing (run '
             'compose layouts)', 'outline: the build needs a direction; add one'])
        self.assertFalse((self.root / 'build').exists())
        self.slides.outline_start(self.outline(), self.contract, self.root / 'build')
        self.assertRegex(self.refusal(self.slides.outline_start, self.outline(),
                                      self.contract, self.root / 'build')[0],
                         "^EEXIST: file already exists, mkdir '.*build'$")
        self.assertTrue((self.root / 'build' / 'parts.json').is_file())


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


class StandInCompositionTests(Deck):
    """The stand-in compiles, merges, previews, records a critique and renders."""

    def drawn(self, **changes) -> dict:
        """The steps slide as a composer might hand it in: three boxes joined in a row."""
        return {'id': 'what-it-is', 'title': STEPS['title'], 'sources': ['O1'],
                'brief': {'relation': 'order', 'focal': 's1_restart'},
                'canvas': {'type': 'stack', 'direction': 'row', 'gap': 'wide', 'children': [
                    {'type': 'box', 'id': 's1_drain', 'text': 'Drain: stop the traffic.'},
                    {'type': 'box', 'id': 's1_restart', 'text': 'Restart the batch.'},
                    {'type': 'box', 'id': 's1_check', 'text': 'Check: wait for health.'}]},
                'connect': [{'id': 's1_edge1', 'from': 's1_drain', 'to': 's1_restart'},
                            {'id': 's1_edge2', 'from': 's1_restart', 'to': 's1_check'}],
                'caveat': STEPS['caveat'], 'source': STEPS['source'], 'notes': 'Say it.',
                **changes}

    def boxes(self, *changes) -> dict:
        canvas = copy.deepcopy(self.drawn()['canvas'])
        for box, change in zip(canvas['children'], changes):
            box.update(change)
        return canvas

    def test_a_composition_that_fits_is_checked_and_nothing_is_written(self):
        report = self.slides.compile(self.composed(self.drawn()), self.contract)
        self.assertEqual(report, {
            'status': 'fits; nothing written. Add a new --output directory to write the '
                      'build', 'slides': 1, 'measurement': 'estimated; brand font unavailable',
            'brandRevision': json.loads(Path(self.contract).read_text())['revision'],
            'groups': 0, 'connectors': 2, 'icons': 0,
            'room': {'what-it-is': '64.2 of 298.6'}})

    def test_with_a_folder_it_writes_what_a_preview_and_a_render_are_made_from(self):
        folder = self.root / 'compiled'
        report = self.slides.compile(self.composed(), self.contract, folder)
        self.assertEqual((report['output'], report['slides']), (str(folder), 4))
        self.assertEqual(sorted(path.name for path in folder.iterdir()),
                         ['brand-contract.json', 'compose-report.json', 'scene.json',
                          'structure.json'])
        scene = json.loads((folder / 'scene.json').read_text())
        self.assertEqual([(slide['id'], slide['sources']) for slide in scene['slides']],
                         [('cover-rolling', ['outline']), ('what-it-is', ['O1']),
                          ('when-it-helps', ['O2', 'O1']), ('closing-next', ['outline'])])
        steps = scene['slides'][1]
        self.assertEqual(steps['notes'], 'Walk the three steps.')
        said = [element.get('text') for element in steps['elements']]
        for words in (STEPS['title'], STEPS['caveat'], STEPS['source'],
                      'Restart: Restart the batch.'):
            self.assertIn(words, said)
        self.assertEqual(steps['elements'][0], {
            'id': 'what-it-is_title', 'type': 'text', 'x': 48, 'y': 36, 'width': 864,
            'height': 60, 'text': STEPS['title'], 'fontSize': 28, 'bold': True,
            'color': '#1F4E8C', 'role': 'title'})
        structure = json.loads((folder / 'structure.json').read_text())
        self.assertEqual(structure['layouts'], [
            {'slide': 'cover-rolling', 'layout': 'Title Slide',
             'placeholders': ['cover-rolling_subtitle']},
            {'slide': 'closing-next', 'layout': 'Big Statement', 'placeholders': []}])
        self.assertEqual((structure['direction'], len(structure['connectors'])),
                         (DIRECTION, 2))
        self.assertEqual(structure['briefs'][1], {'slide': 'what-it-is', 'relation': 'order',
                                                  'focal': 's1_whatitis_p2',
                                                  'rhythm': 'dense'})
        kept = json.loads((folder / 'compose-report.json').read_text())
        self.assertEqual((kept['sceneDigest'], kept['inputs']['brand']['path']),
                         (report['sceneDigest'], self.contract))
        self.assertRegex(self.refusal(self.slides.compile, self.composed(), self.contract,
                                      folder)[0], '^EEXIST: file already exists, mkdir')

    def test_text_that_does_not_fit_is_refused_by_node_and_by_line(self):
        long = self.boxes({'text': 'Capacity ' * 400})
        self.assertEqual(
            self.refusal(self.slides.compile, self.composed(self.drawn(canvas=long)),
                         self.contract),
            ['what-it-is/s1_drain: needs 3739.2pt of height but has 298.6pt at 269.33pt '
             'wide: the text runs to 148 lines of 20pt and 10 fit; shorten the text, split '
             'the slide or restructure'])
        title = 'This title is far too long to fit on the single line that the title of a ' \
                'content slide is given'
        self.assertEqual(
            self.refusal(self.slides.compile, self.composed(self.drawn(title=title)),
                         self.contract),
            ['what-it-is/title: needs 77.2pt of height but has 60pt: it runs to 2 lines of '
             '28pt and 1 fits; shorten the title'])
        column = {'type': 'stack', 'direction': 'column', 'id': 's1_steps',
                  'children': [{'type': 'text', 'id': f's1_line{n}', 'text': 'Line ' * 30}
                               for n in range(6)]}
        self.assertRegex(
            self.refusal(self.slides.compile, self.composed(
                self.drawn(canvas=column, connect=[], brief={'relation': 'none'})),
                self.contract)[0],
            r'^what-it-is/s1_steps: needs [\d.]+pt of height but has 298.6pt at 864pt wide; '
            'shorten the text')

    def test_a_second_focal_node_and_a_raw_colour_or_size_are_refused(self):
        self.assertEqual(
            self.refusal(self.slides.compile, self.composed(self.drawn(canvas=self.boxes(
                {'fill': 'headingPrimary'}, {}, {'color': 'headingPrimary'}))),
                self.contract),
            ['what-it-is/s1_drain: only the focal node may use the focal color',
             'what-it-is/s1_check: only the focal node may use the focal color'])
        self.assertEqual(
            self.refusal(self.slides.compile, self.composed(self.drawn(canvas=self.boxes(
                {'fontSize': 10}, {'fill': 'canvasSecondary'}, {'fill': '#FF0000'}))),
                self.contract),
            ['what-it-is/s1_drain: unsupported node field; never silently drop content',
             'what-it-is/s1_restart: the focal node takes the focal color; remove its fill',
             'what-it-is/s1_check: fill must be a brand color role: canvasPrimary, '
             'canvasSecondary, inkDeep, inkSecondary, headingPrimary, accentAqua, '
             'statusAttention',
             # A node that broke a rule is not on the slide for an edge to join.
             'what-it-is/s1_edge1: edges connect two distinct nodes on this slide'])
        self.assertEqual(
            self.refusal(self.slides.compile, self.composed(self.drawn(canvas=self.boxes(
                {'fill': 'accentAqua'}))), self.contract),
            ['what-it-is/s1_drain: fill accentAqua is not in the deck direction '
             '(canvasSecondary, canvasPrimary)'])

    def test_an_unknown_layout_or_icon_is_refused_at_compile(self):
        cover = {'id': 'cover-rolling', 'title': 'Rolling restarts 101', 'sources':
                 ['outline'], 'layout': 'No Such Layout', 'subtitle': 'Keeping capacity'}
        icons = self.boxes()
        icons['children'] += [{'type': 'icon', 'id': 's1_icon1', 'icon': 'ex-nope'},
                              {'type': 'icon', 'id': 's1_icon2', 'icon': 'ex-photo'},
                              {'type': 'icon', 'id': 's1_icon3', 'icon': 'ex-database'}]
        self.assertEqual(
            self.refusal(self.slides.compile,
                         self.composed(cover, self.drawn(canvas=icons)), self.contract),
            ['s1_icon1: unknown icon ex-nope; search the brand icon library for a current '
             'ID', 's1_icon2: icon ex-photo is a picture, not native geometry; choose '
             'another', 'cover-rolling: the template has no layout named No Such Layout. '
             'Available: Title Slide, Title Only, Agenda, Section Header, Quote, Big '
             'Statement, Picture and Title, Thank You, Blank'])
        icons['children'] = icons['children'][:3] + icons['children'][-1:]
        report = self.slides.compile(self.composed(self.drawn(canvas=icons)), self.contract)
        self.assertEqual(report['icons'], 1)
        two = {**cover, 'layout': 'Title Slide', 'detail': 'A second line'}
        self.assertEqual(self.refusal(self.slides.compile, self.composed(two), self.contract),
                         ['cover-rolling: layout Title Slide has 1 subtitle placeholders; '
                          'remove the extra text'])
        drawn = {**cover, 'layout': 'Title Slide', 'canvas': {'type': 'spacer'}}
        self.assertEqual(self.refusal(self.slides.compile, self.composed(drawn),
                                      self.contract)[0],
                         'cover-rolling: a slide with a template layout has no canvas, '
                         'edges, caveat or source; put content on a standard slide')

    def test_a_relation_must_be_drawn_and_the_focal_node_must_be_there(self):
        loose = self.drawn(connect=[], canvas={**self.boxes(), 'type': 'grid', 'columns': 3})
        del loose['canvas']['direction']
        self.assertEqual(
            self.refusal(self.slides.compile, self.composed(loose), self.contract),
            ['what-it-is: relation "order" is not drawn. Join nodes with edges, use '
             'chevrons in sequence or stack the steps in a column, or set the relation to '
             '"none" if the words are enough'])
        self.assertEqual(
            self.refusal(self.slides.compile, self.composed(self.drawn(
                brief={'relation': 'order', 'focal': 's1_nothing'})), self.contract),
            ['what-it-is: brief.focal names s1_nothing, which is not a box or text on this '
             'slide'])
        self.assertEqual(
            self.refusal(self.slides.compile, self.composed(self.drawn(
                connect=[{'id': 's1_edge1', 'from': 's1_drain', 'to': 's1_gone'}])),
                self.contract),
            ['what-it-is/s1_edge1: edges connect two distinct nodes on this slide'])
        self.assertEqual(
            self.refusal(self.slides.compile, self.composed(self.drawn(), direction=None),
                         self.contract), ['direction must be an object'])
        bare = json.loads(self.composed(self.drawn()).read_text())
        del bare['direction']
        self.assertEqual(self.refusal(self.slides.compile, self.write(bare), self.contract),
                         ['what-it-is: brief.focal needs a deck direction that names the '
                          'focal color'])

    def test_it_knows_the_common_nodes_and_says_so_of_any_other(self):
        table = {'type': 'table', 'id': 's1_table', 'rows': [['a', 'b'], ['c', 'd']]}
        self.assertEqual(
            self.refusal(self.slides.compile, self.composed(self.drawn(
                canvas=table, connect=[], brief={'relation': 'none'})), self.contract),
            ['what-it-is/s1_table: unknown node type'])
        self.assertEqual(
            self.refusal(self.slides.compile, self.composed(
                {key: value for key, value in self.drawn(connect=[]).items()
                 if key not in ('canvas', 'brief')}), self.contract),
            ['what-it-is/undefined: unknown node type'])
        again = self.drawn(canvas=self.boxes({'id': 's1_restart'}))
        self.assertEqual(
            self.refusal(self.slides.compile, self.composed(again), self.contract)[0],
            'what-it-is/s1_restart: invalid or repeated ID: s1_restart is already used in '
            'this deck')

    def test_every_relation_of_an_outline_can_be_sketched_and_compiled(self):
        figure = [{'label': '99.9%', 'text': 'of requests served through a restart'},
                  {'label': 'Before', 'text': 'Requests failed for a minute.'}]
        for relation in slides.RELATIONS:
            for focal in (None, 'Drain', 'One batch at a time'):
                with self.subTest(relation=relation, focal=focal):
                    slide = {**STEPS, 'relation': relation,
                             **({'points': figure} if relation == 'quantity' else {})}
                    slide.pop('focal')
                    if focal:
                        slide['focal'] = focal
                    drawn = slides.sketch(slide, 's2_')
                    self.assertEqual((drawn['id'], drawn['title'], drawn['sources'],
                                      drawn['caveat'], drawn['source'], drawn['notes']),
                                     tuple(STEPS[key] for key in (
                                         'id', 'title', 'sources', 'caveat', 'source',
                                         'notes')))
                    report = self.slides.compile(self.composed(drawn), self.contract)
                    self.assertEqual(report['slides'], 1)
        self.assertEqual(slides.sketch(STEPS, 's1_')['brief'],
                         {'relation': 'order', 'focal': 's1_whatitis_p2'})

    def test_sections_are_merged_in_the_order_their_manifest_lists(self):
        build = self.root / 'build'
        self.slides.outline_start(self.outline(), self.contract, build)
        section = {'version': 1, 'title': OUTLINE['title'], 'direction': DIRECTION,
                   'slides': [slides.sketch(STEPS, 's1_'), slides.sketch(PAIR, 's1_')]}
        self.assertEqual(self.refusal(self.slides.merge, build / 'parts.json',
                                      build / 'composition.json'),
                         ['section-1.json: cannot be read as JSON (ENOENT)'])
        (build / 'section-1.json').write_text(json.dumps(section))
        merged = self.slides.merge(build / 'parts.json', build / 'composition.json')
        self.assertEqual(merged, {
            'output': str(build / 'composition.json'), 'slides': 4,
            'parts': [{'part': 'lead-1.json', 'slides': 1},
                      {'part': 'section-1.json', 'slides': 2},
                      {'part': 'lead-2.json', 'slides': 1}],
            'next': 'compile and preview the whole deck; consistency across sections is '
                    'judged there'})
        whole = json.loads((build / 'composition.json').read_text())
        self.assertEqual([slide['id'] for slide in whole['slides']],
                         ['cover-rolling', 'what-it-is', 'when-it-helps', 'closing-next'])
        self.assertEqual(self.slides.compile(build / 'composition.json', self.contract,
                                             build / 'compiled')['slides'], 4)
        self.assertRegex(self.refusal(self.slides.merge, build / 'parts.json',
                                      build / 'composition.json')[0],
                         '^EEXIST: file already exists, open')

    def test_parts_that_disagree_or_share_an_id_are_refused(self):
        first = {'version': 1, 'title': 'Deck', 'direction': DIRECTION,
                 'slides': [self.drawn()]}
        other = {**first, 'direction': {'focal': 'accentAqua', 'neutral': 'canvasSecondary'}}
        self.write(first, 'first.json')
        self.write(other, 'other.json')
        self.write({'not': 'a composition'}, 'empty.json')
        parts = self.write({'title': 'Deck', 'direction': DIRECTION,
                            'parts': ['first.json', 'other.json', 'empty.json']})
        self.assertEqual(self.refusal(self.slides.merge, parts, self.root / 'merged.json'), [
            "other.json: its direction differs from the deck's; copy the deck direction "
            'unchanged',
            *(f'other.json: ID {ident} is already used in first.json; give each section its '
              'own ID prefix' for ident in ('what-it-is', 's1_drain', 's1_restart',
                                            's1_check', 's1_edge1', 's1_edge2')),
            'empty.json: is not a composition with slides'])
        self.assertEqual(self.refusal(self.slides.merge, self.write({'parts': ['x.json']}),
                                      self.root / 'merged.json'),
                         ['parts.json needs the deck title'])
        self.assertFalse((self.root / 'merged.json').exists())

    def test_a_preview_writes_a_picture_of_each_slide_and_says_where(self):
        compiled = self.compiled()
        shown = self.slides.preview(compiled, self.root / 'preview', 'drive')
        folder = self.root / 'preview'
        self.assertEqual(sorted(path.name for path in folder.iterdir()),
                         ['contact-sheet.png', 'critic.json', 'deck.pdf', 'deck.pptx',
                          'preview.json', 'slide-01.png', 'slide-02.png', 'slide-03.png',
                          'slide-04.png'])
        self.assertEqual({key: shown[key] for key in ('deck', 'contactSheet', 'renderer',
                                                      'fileId', 'url', 'critic')},
                         {'deck': str(folder / 'deck.pptx'), 'renderer': 'drive',
                          'contactSheet': str(folder / 'contact-sheet.png'),
                          'fileId': 'stand-in-preview-1', 'critic': str(folder / 'critic.json'),
                          'url': 'https://docs.google.com/presentation/d/stand-in-preview-1/'
                                 'edit'})
        self.assertEqual(shown['slides'], [
            {'id': ident, 'number': number, 'title': title, 'findings': [],
             'image': str(folder / f'slide-0{number}.png')}
            for number, (ident, title) in enumerate((
                ('cover-rolling', 'Rolling restarts 101'), ('what-it-is', STEPS['title']),
                ('when-it-helps', PAIR['title']), ('closing-next', 'Practise next')), 1)])
        drawn = [picture(slide['image']) for slide in shown['slides']]
        self.assertEqual({(width, height) for width, height, _ in drawn}, {(320, 180)})
        self.assertEqual(len({rows for _, _, rows in drawn}), 4, 'each slide looks different')
        self.assertEqual(picture(shown['contactSheet'])[:2], (640, 90))
        self.assertEqual(shown['deckSha256'],
                         slides.hashlib.sha256(Path(shown['deck']).read_bytes()).hexdigest())
        kept = json.loads((folder / 'preview.json').read_text())
        self.assertEqual((kept['schema'], kept['renderer'], kept['emitter'], kept['next']),
                         (1, 'Google Slides PDF export', 'native template', 'Reuse this '
                          'Drive file for the next preview: --file-id stand-in-preview-1'))
        self.assertEqual({key: kept[key] for key in ('deck', 'deckSha256', 'slides',
                                                     'fileId', 'url', 'contactSheet')},
                         {key: shown[key] for key in ('deck', 'deckSha256', 'slides',
                                                      'fileId', 'url', 'contactSheet')})
        packet = json.loads((folder / 'critic.json').read_text())
        self.assertEqual((packet['deckSha256'], len(packet['questions']),
                          sorted(packet['grades'])),
                         (shown['deckSha256'], 8, ['critical', 'major', 'minor']))
        self.assertEqual(packet['slides'][1], {
            'number': 2, 'id': 'what-it-is', 'title': STEPS['title'],
            'image': str(folder / 'slide-02.png'), 'relation': 'order', 'rhythm': 'dense'})

    def test_one_file_is_written_again_when_its_id_is_given(self):
        compiled = self.compiled()
        first = self.previewed(compiled=compiled)
        again = self.previewed(compiled=compiled, file_id=first['fileId'])
        self.assertEqual((again['fileId'], again['url']), (first['fileId'], first['url']))
        self.assertNotEqual(again['deckSha256'], first['deckSha256'])
        self.assertEqual(self.tool.files, {'stand-in-preview-1': {
            'name': 'Preview: Rolling restarts 101', 'uploads': 2,
            'deckSha256': again['deckSha256']}})
        other = self.previewed(compiled=compiled)
        self.assertEqual((other['fileId'], len(self.tool.files)), ('stand-in-preview-2', 2))
        self.assertEqual(self.refusal(self.previewed, compiled=compiled, file_id='gone'),
                         ['Google API request failed (HTTP 404). Check account, Drive '
                          'scopes, file access, and organization policy.'])
        imported = self.slides.drive_import(first['deck'], 'Rolling restarts 101')
        self.assertEqual(self.refusal(self.previewed, compiled=compiled,
                                      file_id=imported['id']),
                         ['Refusing to overwrite a Drive file that is not a "Preview: …" '
                          'Google Slides deck. Omit --file-id to create a new preview file.'])

    def test_one_slide_can_be_drawn_alone_and_then_there_is_no_packet(self):
        shown = self.previewed(slide='when-it-helps')
        self.assertEqual([(slide['id'], slide['number']) for slide in shown['slides']],
                         [('when-it-helps', 3)])
        folder = Path(shown['deck']).parent
        self.assertEqual(sorted(path.name for path in folder.iterdir()),
                         ['deck.pdf', 'deck.pptx', 'preview.json', 'slide-03.png'])
        self.assertIsNone(shown['contactSheet'])
        self.assertNotIn('critic', shown)
        self.assertEqual(self.refusal(self.slides.critique, folder, self.write({})),
                         ['No critic packet here; run compose preview on the whole deck, '
                          'without --slide'])
        self.assertEqual(self.refusal(self.previewed, slide='nowhere'),
                         ['No slide nowhere; choose one of cover-rolling, what-it-is, '
                          'when-it-helps, closing-next'])

    def test_a_local_render_uses_no_file_and_either_renderer_can_be_missing(self):
        local = self.previewed(renderer='local')
        self.assertEqual((local['renderer'], local['fileId'], local['url']),
                         ('local', None, None))
        self.assertEqual(json.loads((Path(local['deck']).parent / 'preview.json').read_text())
                         ['renderer'], 'LibreOffice')
        self.assertEqual(self.tool.files, {})
        self.tool.local = self.tool.drive = False
        before = sorted(path.name for path in self.root.iterdir())
        self.assertEqual(self.refusal(self.previewed, renderer='local'),
                         ['LibreOffice (soffice) is not installed. Use --renderer google, or '
                          'install LibreOffice for offline previews.'])
        self.assertEqual(self.refusal(self.previewed),
                         ['Google API request failed (HTTP 403). Check account, Drive '
                          'scopes, file access, and organization policy.'])
        self.assertEqual([name for name in sorted(path.name for path in self.root.iterdir())
                          if name.startswith('preview') and name not in before], [])

    def test_a_crowded_slide_and_one_of_words_alone_are_pointed_out(self):
        crowded = self.drawn(connect=[], brief={'relation': 'none'}, canvas={
            'type': 'grid', 'columns': 3, 'children': [
                {'type': 'text', 'id': f's1_cell{n}', 'text': 'word ' * 12}
                for n in range(9)]})
        del crowded['caveat']   # its rule is a line, and a line is not words
        shown = self.previewed(compiled=self.compiled(crowded))
        self.assertEqual(shown['slides'][0]['findings'], [
            {'severity': 'warn', 'code': 'density',
             'detail': '120 visible text words; inspect reading effort'},
            {'severity': 'warn', 'code': 'text-only', 'detail': 'Consider a visual '
             'relationship or evidence when it serves the message'}])

    def assessment(self, shown: dict, *findings, **changes) -> Path:
        return self.write({'deckSha256': shown['deckSha256'], 'reviewer': 'independent',
                           'findings': list(findings), **changes})

    def test_a_critique_is_counted_and_is_clear_unless_a_finding_is_critical(self):
        major = {'slide': 'what-it-is', 'question': 3, 'severity': 'major',
                 'note': 'Two labels are emphasised at once.', 'fix': 'Emphasise one.'}
        minor = {'slide': 'cover-rolling', 'question': 6, 'severity': 'minor',
                 'note': 'The subtitle sits too low.'}
        shown = self.previewed()
        folder = Path(shown['deck']).parent
        recorded = self.slides.critique(folder, self.assessment(
            shown, major, minor, {**major, 'question': 2}, weakest=['what-it-is']))
        self.assertEqual(recorded, {
            'critique': str(folder / 'critique.json'), 'reviewer': 'independent',
            'critical': 0, 'major': 2, 'minor': 1, 'status': 'clear',
            'next': 'Fix the major findings in one pass, then preview again. Undo any fix '
                    'that causes a new finding.'})
        kept = json.loads((folder / 'critique.json').read_text())
        self.assertEqual((kept['findings'][1], kept['weakest'], kept['major'],
                          kept['deckSha256']), (minor, ['what-it-is'], 2, shown['deckSha256']))
        self.assertEqual(self.refusal(self.slides.critique, folder,
                                      self.assessment(shown)),
                         ['This render already has a critique; fix the slides, preview '
                          'again and critique the new render'])
        blocked = self.previewed()
        stopped = self.slides.critique(Path(blocked['deck']).parent, self.assessment(
            blocked, {**major, 'severity': 'critical'}))
        self.assertEqual((stopped['critical'], stopped['status']), (1, 'blocked'))
        self.assertIn('Do not deliver.', stopped['next'])
        clean = self.previewed()
        nothing = self.slides.critique(Path(clean['deck']).parent, self.assessment(
            clean, reviewer='author'))
        self.assertEqual((nothing['major'], nothing['status'], nothing['next']),
                         (0, 'clear', 'Clear to show the user.'))

    def test_a_critique_of_another_deck_or_in_another_shape_is_refused(self):
        shown = self.previewed()
        folder = Path(shown['deck']).parent
        good = {'slide': 'what-it-is', 'question': 1, 'severity': 'minor',
                'note': 'A long enough note.'}
        self.assertEqual(
            self.refusal(self.slides.critique, folder, self.assessment(
                shown, {'slide': 'nope', 'question': 9, 'severity': 'bad', 'note': 'short',
                        'fix': ''}, {**good, 'extra': 1}, deckSha256='b' * 64,
                reviewer='me', weakest=['a', 'b', 'c', 'd'])),
            ['deckSha256 is not the deck this packet describes; critique the latest render',
             'reviewer is independent (did not write the slides) or author',
             'finding 1: no slide nope in this deck', 'finding 1: question is 1 to 8',
             'finding 1: severity is critical, major or minor',
             'finding 1: note says what is wrong on this slide, in a sentence',
             'finding 1: fix is a sentence, or omitted',
             'finding 2: takes slide, question, severity, note and fix',
             'weakest names up to three slides of this deck'])
        self.assertEqual(self.refusal(self.slides.critique, folder,
                                      self.assessment(shown, good, extra=1)),
                         ['A critique takes deckSha256, reviewer, findings and weakest'])
        self.assertEqual(self.refusal(self.slides.critique, folder,
                                      self.assessment(shown, findings='none')),
                         ['findings is a list; use an empty list when there are none'])
        self.assertFalse((folder / 'critique.json').exists())

    def test_a_deck_is_rendered_to_a_new_file_that_starts_as_powerpoint_does(self):
        compiled = self.compiled()
        made = self.slides.render(compiled, self.root / 'deck.pptx')
        data = (self.root / 'deck.pptx').read_bytes()
        self.assertEqual(data[:4], b'PK\x03\x04')
        self.assertEqual(made, {
            'output': str(self.root / 'deck.pptx'), 'slides': 4, 'editable': True,
            'sha256': slides.hashlib.sha256(data).hexdigest(), 'status': 'unreviewed draft',
            'emitter': 'native template'})
        with zipfile.ZipFile(self.root / 'deck.pptx') as deck:
            self.assertEqual(deck.namelist(), [
                '[Content_Types].xml', 'ppt/presentation.xml', *(
                    f'ppt/slides/slide{number}.xml' for number in range(1, 5))])
            self.assertIn('<a:rPr sz="1400"/><a:t>Capacity holds only with more than one '
                          'instance.</a:t>', deck.read('ppt/slides/slide2.xml').decode())
        again = self.slides.render(compiled, self.root / 'again.pptx')
        self.assertNotEqual(again['sha256'], made['sha256'],
                            'a fresh render of the same slides is another file')
        self.assertEqual(self.refusal(self.slides.render, compiled, self.root / 'deck.pptx'),
                         [f"{self.root / 'deck.pptx'} already exists; choose a new output "
                          'file'])
        self.assertEqual((self.root / 'deck.pptx').read_bytes(), data)
        self.assertRegex(self.refusal(self.slides.render, self.root / 'nowhere',
                                      self.root / 'other.pptx')[0],
                         "^ENOENT: no such file or directory, open '.*nowhere/scene.json'$")

    def test_a_render_that_fails_after_writing_leaves_nothing_through_the_wrapper(self):
        compiled, line = self.compiled(), 'unbound prefix: line 1, column 786'
        self.tool.fails['compose render'] = line
        code, _, said = self.tool(['node', 'script', 'compose', 'render', '--file',
                                   str(compiled), '--output', str(self.root / 'raw.pptx')])
        self.assertEqual((code, said), (1, line + '\n'))
        self.assertEqual((self.root / 'raw.pptx').read_bytes()[:4], b'PK\x03\x04',
                         'as the tool once did, it leaves the file it had written')
        self.assertEqual(self.refusal(self.slides.render, compiled, self.root / 'deck.pptx'),
                         [line])
        self.assertFalse((self.root / 'deck.pptx').exists())
        del self.tool.fails['compose render']
        self.tool.fails['compose preview'] = 'The render has 8 pages for 4 slides'
        self.assertEqual(self.refusal(self.previewed, compiled=compiled),
                         ['The render has 8 pages for 4 slides'])
        self.assertEqual([path.name for path in self.root.iterdir()
                          if path.name.startswith('preview')], [])

    def test_a_brand_that_changed_underneath_stops_every_later_step(self):
        compiled, outline = self.compiled(), self.outline()
        tokens = self.brand.run.home / 'brand' / 'tokens.json'
        tokens.write_text(tokens.read_text().replace('#1F4E8C', '#123456'))
        line = ['Brand authority changed (tokens); resolve a fresh contract']
        for call, args in ((self.slides.outline_check, (outline, self.contract)),
                           (self.slides.layouts, (self.contract,)),
                           (self.slides.compile, (self.composed(), self.contract)),
                           (self.slides.preview, (compiled, self.root / 'preview', 'drive')),
                           (self.slides.render, (compiled, self.root / 'deck.pptx'))):
            with self.subTest(call.__name__):
                self.assertEqual(self.refusal(call, *args), line)
        edited = json.loads(Path(self.contract).read_text())
        edited['design']['colors']['headingPrimary'] = '#000000'
        self.assertEqual(self.refusal(self.slides.layouts, self.write(edited)),
                         ['Brand contract changed; resolve a fresh handoff'])
        self.assertEqual(self.refusal(self.slides.layouts, self.write({'schema': 1})),
                         ['Use resolved brand contract schema 1 with identity/variant'])

    def test_what_each_slide_cites_is_read_from_the_compiled_scene(self):
        self.assertEqual(self.slides.cited(self.compiled()), {'O1': [2, 3], 'O2': [3]})
        with self.assertRaisesRegex(WorkspaceError, 'does not hold a compiled deck'):
            self.slides.cited(self.root / 'nowhere')
        (self.root / 'broken').mkdir()
        (self.root / 'broken' / 'scene.json').write_text('{"slides": 4}')
        with self.assertRaisesRegex(WorkspaceError, 'Compile the deck again'):
            self.slides.cited(self.root / 'broken')

    def test_the_layouts_say_which_show_a_title_and_which_hold_a_canvas(self):
        found = self.slides.layouts(self.contract)
        self.assertEqual(found['default'], 'Title Only')
        self.assertIn({'name': 'Title Slide', 'title': True, 'subtitles': 1, 'pictures': 0,
                       'canvas': False}, found['layouts'])
        self.assertIn({'name': 'Thank You', 'title': False, 'subtitles': 0, 'pictures': 0,
                       'canvas': False}, found['layouts'])
        self.assertEqual([layout['name'] for layout in found['layouts'] if layout['canvas']],
                         ['Title Only'])

    def test_the_contracts_are_text_that_carries_the_brands_sizes(self):
        outline = self.slides.outline_contract(self.contract)
        self.assertTrue(outline.startswith('Outline v1 (AI-owned; words and decisions, no '
                                           'layout).'))
        self.assertTrue(outline.endswith('For example: a title holds 1 line at 28pt, about '
                                         '59 characters. A slide delivered for reading '
                                         'carries about 90 body words.'))
        composed = self.slides.compose_contract(self.contract)
        self.assertIn('Content area 864 wide by 360 high.', composed)
        self.assertIn('Text with no textRole uses bodyReference, the size for a deck '
                      'delivered for reading.', composed)

    def test_a_deck_is_put_in_drive_when_drive_is_there(self):
        shown = self.previewed()
        self.assertIs(self.slides.drive_check(), True)
        imported = self.slides.drive_import(shown['deck'], 'Rolling restarts 101')
        self.assertEqual(imported, {'id': 'stand-in-deck-2', 'name': 'Rolling restarts 101',
                                    'url': 'https://docs.google.com/presentation/d/'
                                           'stand-in-deck-2/edit'})
        self.assertEqual(self.tool.files['stand-in-deck-2']['deckSha256'],
                         shown['deckSha256'])
        notes = self.root / 'notes.txt'
        notes.write_text('not a deck')
        fake = self.root / 'fake.pptx'
        fake.write_text('not a deck')
        self.assertEqual(self.refusal(self.slides.drive_import, notes, 'Notes'),
                         ['Input must be a .pptx path.'])
        self.assertEqual(self.refusal(self.slides.drive_import, fake, 'Fake'),
                         ['Input is not a PPTX ZIP.'])
        self.tool.drive = False
        self.assertIs(self.slides.drive_check(), False)
        self.assertIn('Inspect Drive before retrying',
                      self.refusal(self.slides.drive_import, shown['deck'], 'Again')[0])

    def test_it_says_which_version_it_is_and_lists_its_calls(self):
        self.assertEqual(self.slides.version(), slides.MINIMUM)
        self.slides.layouts(self.contract)
        self.assertEqual(self.tool.calls, [['--version'], ['--version'],
                                           ['compose', 'layouts', '--brand', self.contract]])
        self.assertEqual(self.tool(['node', 'script', 'studio']),
                         (1, '', 'Unknown command/action; run --help\n'))
        self.assertEqual(self.tool(['node', 'script', 'compose', 'layouts', '--file', 'x']),
                         (1, '', '--file is not valid for this command\n'))
        self.assertEqual(self.refusal(self.slides.layouts, self.write(['not', 'a', 'brand'])),
                         ['Use resolved brand contract schema 1 with identity/variant'])


if __name__ == '__main__':
    unittest.main()
