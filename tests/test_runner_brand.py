"""The brand skill wrapper, against a stand-in for a brand skill's own command. Neither Node
nor an installed skill is needed, and nothing touches the network.
"""
import gc
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import runner_support  # noqa: F401  puts the runner on the import path

from runner import brand, slides
from stand_ins import brand as brand_stand_in
from stand_ins import slides as slides_stand_in
from test_runner_slides import DIRECTION, OUTLINE, PAIR, STEPS
from workspace import WorkspaceError

LISTED = [{'brand': 'acme', 'name': 'Acme Works', 'variants': ['light', 'dark']},
          {'brand': 'acme-labs', 'name': 'Acme Labs', 'variants': ['light']}]
COMMAND = ('const commands = { version: "version.mjs", brands: "brands.mjs", '
           'contract: "contract.mjs" };\n')


def skill(folder: Path, name: str, command: str = COMMAND, package: bool = True) -> Path:
    """A folder that looks like an installed skill with a command of its own."""
    (folder / 'scripts').mkdir(parents=True)
    (folder / 'SKILL.md').write_text(f'---\nname: {name}\n---\n')
    (folder / 'scripts' / f'{name}.mjs').write_text(command)
    if package:
        (folder / 'package.json').write_text(json.dumps({'name': name, 'version': '1.2.3'}))
    return folder


class Commands:
    """Pretend command lines, by the script that is run: what each lists as its brands and
    what it calls itself. One that is not listed here answers as some other tool would."""

    def __init__(self):
        self.ran, self.known = [], {}

    def knows(self, folder: Path, name: str, brands=LISTED, title: str | None = 'Acme Brand'):
        self.known[str(folder.resolve() / 'scripts' / f'{name}.mjs')] = (brands, title)

    def __call__(self, command, cwd=None):
        self.ran.append(command)
        brands, title = self.known.get(command[1], (None, None))
        if command[2:] == ['brands', '--json'] and brands is not None:
            return 0, json.dumps(brands), ''
        if command[2:] == ['version'] and title:
            return 0, f'{title} 1.2.3\n', ''
        return 1, '', 'Unknown command/action; run --help\n'


class FindingABrandSkillTests(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.home = Path(holder.name).resolve()
        patches = (mock.patch.dict(os.environ), mock.patch.object(Path, 'home',
                                                                  return_value=self.home))
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        os.environ.pop(brand.VARIABLE, None)
        self.run = Commands()
        self.claude = self.home / '.claude' / 'skills'

    def test_a_brand_skill_is_known_by_what_its_own_command_answers(self):
        mine = skill(self.claude / 'acme-brand', 'acme-brand')
        self.run.knows(mine, 'acme-brand')
        other = skill(self.claude / 'deck-tool', 'deck-tool', '// renders brands of deck\n')
        self.assertEqual(brand.found(self.run), [
            {'name': 'Acme Brand', 'runtime': str(mine), 'brands': LISTED}])
        self.assertEqual(self.run.ran, [
            ['node', str(mine / 'scripts' / 'acme-brand.mjs'), 'brands', '--json'],
            ['node', str(mine / 'scripts' / 'acme-brand.mjs'), 'version'],
            ['node', str(other / 'scripts' / 'deck-tool.mjs'), 'brands', '--json']])
        chosen = brand.Brand(run=self.run)
        self.assertEqual((chosen.name, chosen.runtime, chosen.script),
                         ('Acme Brand', mine, mine / 'scripts' / 'acme-brand.mjs'))
        self.assertEqual(chosen.brands(), LISTED)

    def test_a_home_that_is_named_is_the_only_one_looked_in(self):
        # The installer asks about the home it installs into, which need not be the
        # person's own: nothing of theirs is looked at, or run, on its behalf.
        mine = skill(self.claude / 'acme-brand', 'acme-brand')
        self.run.knows(mine, 'acme-brand')
        other = self.home / 'another-home'
        theirs = skill(other / '.agents' / 'skills' / 'zeta-brand', 'zeta-brand')
        shared = skill(other / '.local' / 'share' / 'kept-brand' / 'current', 'kept-brand')
        self.run.knows(theirs, 'zeta-brand', title='Zeta Brand')
        self.assertEqual(brand.locations(other), [shared, theirs])
        self.assertEqual(brand.locations(), [mine])
        self.assertEqual([one['runtime'] for one in brand.found(self.run, home=other)],
                         [str(theirs)])
        self.assertEqual(brand.found(self.run, home=self.home / 'an-empty-home'), [])
        self.assertNotIn(str(mine / 'scripts' / 'acme-brand.mjs'),
                         [command[1] for command in self.run.ran])
        os.environ[brand.VARIABLE] = str(mine)
        self.assertEqual(brand.locations(other), [mine], 'the override is still the only place')

    def test_nothing_is_run_that_does_not_look_like_a_brand_skills_command(self):
        skill(self.claude / 'video-tool', 'video-tool', '// cuts a video\n')
        nameless = skill(self.claude / 'nameless', 'nameless')
        (nameless / 'SKILL.md').unlink()
        elsewhere = skill(self.claude / 'acme-brand', 'acme-brand')
        (elsewhere / 'scripts' / 'acme-brand.mjs').rename(elsewhere / 'scripts' / 'tool.mjs')
        odd = skill(self.claude / 'odd', 'odd', package=False)
        (odd / 'package.json').write_text('{"name": "../../outside"}')
        (self.claude / 'a-file.txt').write_text('not a folder\n')
        self.assertEqual(brand.found(self.run), [])
        self.assertEqual([command[1:] for command in self.run.ran],
                         [[str(odd / 'scripts' / 'odd.mjs'), 'brands', '--json']])

    def test_a_folder_that_cannot_be_looked_into_is_passed_over(self):
        mine = skill(self.claude / 'zeta-brand', 'zeta-brand')
        self.run.knows(mine, 'zeta-brand')
        (self.claude / 'kept-private').mkdir()
        (self.claude / 'gone').symlink_to(self.home / 'nowhere')
        (self.claude / 'round').symlink_to(self.claude / 'around')
        (self.claude / 'around').symlink_to(self.claude / 'round')
        real = Path.is_file

        def is_file(path, **named):
            if 'kept-private' in path.parts:
                raise PermissionError(1, 'Operation not permitted')
            return real(path, **named)

        with mock.patch.object(Path, 'is_file', is_file):
            self.assertEqual([one['name'] for one in brand.found(self.run)], ['Acme Brand'])

    def test_a_listing_in_another_shape_is_not_a_brand_skills(self):
        mine = skill(self.claude / 'acme-brand', 'acme-brand')
        for answer in ({}, [], ['acme'], [{'brand': 'acme'}],
                       [{'brand': 'acme', 'name': 'Acme Works', 'variants': []}],
                       [{'brand': 'acme', 'name': '', 'variants': ['light']}]):
            with self.subTest(answer):
                self.run.knows(mine, 'acme-brand', answer)
                self.assertEqual(brand.found(self.run), [])

        def hangs(command, cwd=None):
            raise WorkspaceError('The brand skill did not answer in 120 seconds.')

        self.assertEqual(brand.found(hangs), [])
        self.assertEqual(brand.found(lambda command, cwd=None: (0, 'not json', '')), [])

    def test_every_usual_place_is_looked_in_and_a_linked_skill_is_found_once(self):
        version = skill(self.home / 'Library' / 'Application Support' / 'Acme Brand'
                        / 'versions' / '1.2.3', 'acme-brand')
        (version.parent.parent / 'current').symlink_to(Path('versions') / '1.2.3')
        for harness in ('.claude', '.agents', '.cursor'):
            (self.home / harness / 'skills').mkdir(parents=True)
            (self.home / harness / 'skills' / 'acme-brand').symlink_to(
                version.parent.parent / 'current')
        shared = skill(self.home / '.local' / 'share' / 'other-brand' / 'current', 'tool',
                       package=False)
        (shared / 'scripts' / 'tool.mjs').rename(shared / 'scripts' / 'other-brand.mjs')
        plain = skill(self.home / '.agents' / 'skills' / 'third-brand', 'third-brand',
                      package=False)
        self.run.knows(version, 'acme-brand')
        self.run.knows(shared, 'other-brand', LISTED[:1], title=None)
        self.run.knows(plain, 'third-brand', LISTED[1:], title='Third Brand')
        self.assertEqual(brand.found(self.run), [
            {'name': 'Acme Brand', 'runtime': str(version), 'brands': LISTED},
            {'name': 'other-brand', 'runtime': str(shared), 'brands': LISTED[:1]},
            {'name': 'Third Brand', 'runtime': str(plain), 'brands': LISTED[1:]}])
        self.assertEqual(sum(command[2:] == ['brands', '--json'] for command in self.run.ran),
                         3, 'one skill behind four links is asked once')
        self.assertEqual(brand.Brand(run=self.run).runtime, version)

    def test_the_override_is_the_only_place_looked(self):
        usual = skill(self.claude / 'acme-brand', 'acme-brand')
        chosen = skill(self.home / 'elsewhere' / 'my-brand', 'my-brand')
        self.run.knows(usual, 'acme-brand')
        self.run.knows(chosen, 'my-brand', LISTED[1:], title='My Brand')
        os.environ[brand.VARIABLE] = str(chosen)
        self.assertEqual(brand.found(self.run), [
            {'name': 'My Brand', 'runtime': str(chosen), 'brands': LISTED[1:]}])
        self.assertEqual(brand.Brand(run=self.run).name, 'My Brand')
        os.environ[brand.VARIABLE] = str(self.home / 'nowhere')
        self.assertEqual(brand.found(self.run), [])
        with self.assertRaisesRegex(WorkspaceError, 'BRAND_SKILL_RUNTIME names .*nowhere, '
                                    'which does not hold a brand skill'):
            brand.Brand(run=self.run)

    def test_with_no_brand_skill_a_person_is_told_what_to_do(self):
        skill(self.claude / 'deck-tool', 'deck-tool')
        self.assertEqual(brand.found(self.run), [])
        with self.assertRaisesRegex(WorkspaceError, 'No brand skill was found on this '
                                    'computer, so a deck cannot be made. Install one, or '
                                    'name its folder in BRAND_SKILL_RUNTIME'):
            brand.Brand(run=self.run)

    def test_a_folder_can_be_named_outright(self):
        chosen = skill(self.home / 'kept' / 'my-brand', 'my-brand')
        self.run.knows(chosen, 'my-brand', title='My Brand')
        named = brand.Brand(runtime=chosen, run=self.run)
        self.assertEqual((named.name, named.script),
                         ('My Brand', chosen / 'scripts' / 'my-brand.mjs'))
        self.assertEqual(named.brands(), LISTED)
        with mock.patch.object(brand.shutil, 'which', return_value='/usr/bin/node'):
            with self.assertRaisesRegex(WorkspaceError, 'nothing-here does not hold a brand '
                                        'skill'):
                brand.Brand(runtime=self.home / 'nothing-here')

    def test_the_real_command_needs_node(self):
        mine = skill(self.claude / 'acme-brand', 'acme-brand')
        with mock.patch.object(brand.shutil, 'which', return_value=None):
            self.assertEqual(brand.found(), [])
            with self.assertRaisesRegex(WorkspaceError, 'needs Node.js 20 or newer'):
                brand.Brand()
        self.run.knows(mine, 'acme-brand')
        with mock.patch.object(brand.shutil, 'which', return_value='/usr/bin/node'), \
                mock.patch.object(brand, 'run_command', self.run):
            self.assertEqual(brand.Brand().node, '/usr/bin/node')
            self.assertEqual(self.run.ran[0][0], '/usr/bin/node')


class CommandTests(unittest.TestCase):
    """What is run, and how its answers and refusals are read."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name).resolve()
        self.ran, self.answers, self.exports = [], [], 3   # the files an export writes
        self.brand = brand.Brand(runtime=Path('/opt/acme-brand'), run=self.pretend)
        self.ran.clear()

    def pretend(self, command, cwd=None):
        self.ran.append(command)
        if command[2:] == ['version']:
            return 0, 'Acme Brand 1.2.3\n', ''
        if command[2:4] == ['contract', 'export'] and self.exports:
            folder = Path(command[command.index('--output') + 1])
            folder.mkdir()
            for name in ('brand-contract.json', 'DESIGN.md', 'VOICE.md')[:self.exports]:
                (folder / name).write_text('written\n')
        return self.answers.pop(0) if self.answers else (0, '{"status": "current"}\n', '')

    def test_it_is_called_what_its_version_line_says_or_by_its_folder(self):
        self.assertEqual((self.brand.name, self.brand.runtime, self.brand.script),
                         ('Acme Brand', Path('/opt/acme-brand'),
                          Path('/opt/acme-brand/scripts/acme-brand.mjs')))
        for answer in ((2, '', 'Unknown command: version.\n'), (0, '1.2.3\n', ''),
                       (0, '\n', '')):
            quiet = brand.Brand(runtime=Path('/opt/acme-brand'),
                                run=lambda command, cwd=None: answer)
            self.assertEqual(quiet.name, 'acme-brand')
        current = brand.Brand(runtime=Path('/opt/Acme Brand/current'),
                              run=lambda command, cwd=None: (1, '', ''))
        self.assertEqual((current.name, current.script),
                         ('Acme Brand', Path('/opt/Acme Brand/current/scripts/Acme Brand.mjs')))

    def test_each_command_is_run_as_the_skill_takes_it(self):
        self.answers = [(0, json.dumps(LISTED), ''), (0, '{}', ''), (0, '{}', ''),
                        (0, '{"results": []}', ''), (0, '{"status": "PASS"}', ''),
                        (0, '{"ok": true}', '')]
        self.assertEqual(self.brand.brands(), LISTED)
        self.brand.export(self.root / 'brand', 'acme', 'dark', delivery='live')
        self.brand.check('/d/brand/brand-contract.json')
        self.brand.icons('database failover', limit=8)
        self.brand.audit(Path('/d/deck.pptx'), 'acme', 'dark')
        self.brand.ready()
        self.assertEqual({tuple(command[:2]) for command in self.ran},
                         {('node', '/opt/acme-brand/scripts/acme-brand.mjs')})
        self.assertEqual([command[2:] for command in self.ran], [
            ['brands', '--json'],
            ['contract', 'export', '--medium', 'slides', '--brand', 'acme', '--variant',
             'dark', '--delivery', 'live', '--output', str(self.root / 'brand')],
            ['contract', 'check', '--file', '/d/brand/brand-contract.json'],
            ['icons', '--query', 'database failover', '--limit', '8', '--json',
             '--no-previews'],
            ['presentation', '--brand', 'acme', '--variant', 'dark', '--file',
             '/d/deck.pptx', '--json'],
            ['doctor', '--profile', 'presentation', '--json']])

    def test_an_export_says_where_its_three_files_are_and_is_for_reading_unless_told(self):
        made = self.brand.export(self.root / 'brand', 'acme', 'light')
        self.assertEqual(made, {'contract': str(self.root / 'brand' / 'brand-contract.json'),
                                'design': str(self.root / 'brand' / 'DESIGN.md'),
                                'voice': str(self.root / 'brand' / 'VOICE.md')})
        self.assertEqual(self.ran[0][-4:], ['--delivery', 'reading', '--output',
                                            str(self.root / 'brand')])
        self.assertIn('--variant', self.ran[0])
        self.brand.export(self.root / 'plain', 'acme', None)
        self.brand.audit('/d/deck.pptx', 'acme', None)
        self.assertEqual([call for call in self.ran[1:] if '--variant' in call or None in call],
                         [], 'with no variant named, the skill chooses')
        del self.ran[1:]
        with self.assertRaisesRegex(WorkspaceError, 'exported for reading or live delivery, '
                                    'not print'):
            self.brand.export(self.root / 'other', 'acme', 'light', delivery='print')
        self.assertEqual(len(self.ran), 1)

    def test_a_failed_export_leaves_no_folder_and_an_earlier_one_is_not_touched(self):
        self.answers = [(1, '', 'Unknown acme variant: sepia. Choose light, dark.\n')]
        with self.assertRaises(brand.Refused) as refused:
            self.brand.export(self.root / 'brand', 'acme', 'sepia')
        self.assertEqual(refused.exception.problems,
                         ['Unknown acme variant: sepia. Choose light, dark.'])
        self.exports = 2
        with self.assertRaisesRegex(WorkspaceError, 'without the three files it should '
                                    'write'):
            self.brand.export(self.root / 'brand', 'acme', 'light')
        self.assertEqual(list(self.root.iterdir()), [])
        self.exports = 0
        (self.root / 'brand').mkdir()
        (self.root / 'brand' / 'brand-contract.json').write_text('an earlier export\n')
        self.answers = [(1, '', "EEXIST: file already exists, mkdir 'brand'\n")]
        with self.assertRaisesRegex(brand.Refused, 'EEXIST'):
            self.brand.export(self.root / 'brand', 'acme', 'light')
        self.assertEqual((self.root / 'brand' / 'brand-contract.json').read_text(),
                         'an earlier export\n')

    def test_a_refusal_carries_the_skills_lines_without_its_usage(self):
        usage = ('Usage: acme-brand icons --query <words> [--limit <1-20>]\n'
                 '       acme-brand icons --id ID [--output icon.pptx]\n')
        self.answers = [
            (2, '', f'--query needs words to search for\n{usage}'),
            (1, '', '(node:7) Warning: something\n\nBrand authority changed (tokens); '
             'resolve a fresh contract\n'),
            (2, '', usage), (1, 'ignored', '')]
        with self.assertRaises(brand.Refused) as refused:
            self.brand.icons('   ')
        self.assertEqual(refused.exception.problems, ['--query needs words to search for'])
        self.assertEqual(str(refused.exception),
                         'The brand skill refused: --query needs words to search for')
        self.assertIsInstance(refused.exception, WorkspaceError)
        with self.assertRaises(brand.Refused) as refused:
            self.brand.check('/d/brand/brand-contract.json')
        self.assertEqual(refused.exception.problems,
                         ['Brand authority changed (tokens); resolve a fresh contract'])
        for code in (2, 1):
            with self.assertRaisesRegex(brand.Refused, f'it ended with exit code {code}'):
                self.brand.check('/d/brand/brand-contract.json')

    def test_an_answer_that_is_not_the_json_it_should_be_is_not_trusted(self):
        for call, answer in ((self.brand.brands, '{"brand": "acme"}'),
                             (self.brand.brands, '[{"brand": "acme"}]'),
                             (self.brand.brands, 'acme | Acme Works | light, dark'),
                             (lambda: self.brand.check('/d/c.json'), '[1, 2]'),
                             (lambda: self.brand.icons('cloud'), '{"results": "none"}'),
                             (self.brand.ready, '')):
            self.answers = [(0, answer, '')]
            with self.assertRaisesRegex(WorkspaceError, 'something other than the JSON'):
                call()

    def test_icons_are_given_by_id_and_name_and_a_page_of_them_is_left_out(self):
        self.answers = [(0, json.dumps({'query': 'cloud', 'totalMatches': 3, 'results': [
            {'kind': 'icon', 'slide': 22, 'category': 'Platform', 'label': 'Icon cloud',
             'id': 'fi-0001', 'native': True, 'bounds': [1, 2, 3, 4], 'preview': None},
            {'kind': 'icon', 'category': 'People', 'label': 'Icon cloud photo',
             'id': 'fi-0002', 'native': False},
            {'kind': 'page', 'slide': 30, 'category': 'Clouds'},
            {'kind': 'icon', 'id': 'fi-0003'}, 'stray']}), '')]
        self.assertEqual(self.brand.icons('cloud'), [
            {'id': 'fi-0001', 'name': 'Icon cloud', 'category': 'Platform', 'native': True},
            {'id': 'fi-0002', 'name': 'Icon cloud photo', 'category': 'People',
             'native': False},
            {'id': 'fi-0003', 'name': 'fi-0003', 'category': None, 'native': False}])
        self.assertEqual(self.ran[0][2:], ['icons', '--query', 'cloud', '--limit', '5',
                                           '--json', '--no-previews'])

    def test_an_audit_that_warns_or_blocks_is_an_answer_not_a_refusal(self):
        small = {'ruleId': 'SMALL_TEXT', 'severity': 'warning', 'slide': 2, 'shapeId': '3',
                 'observed': {'minimumPt': 14}, 'remediation': 'Make the text larger.'}
        dense = {'ruleId': 'HIGH_TEXT_DENSITY', 'severity': 'warning', 'slide': 3,
                 'shapeId': None, 'observed': {'words': 95}, 'remediation': 'Condense.'}
        left = {'ruleId': 'UNRESOLVED_PLACEHOLDER', 'severity': 'blocker', 'slide': 1,
                'shapeId': '2', 'remediation': 'Replace the starter text.'}
        self.answers = [
            (0, json.dumps({'status': 'WARN', 'blockers': [], 'warnings': [small, dense],
                            'slides': [], 'sha256': 'abc'}), ''),
            (2, json.dumps({'status': 'BLOCKED', 'blockers': [left], 'warnings': [small]}),
             ''),
            (0, json.dumps({'status': 'PASS', 'blockers': [], 'warnings': []}), ''),
            (2, '', 'Invalid argument: --file\nUsage: acme-brand presentation --file '
             '<deck.pptx>\n')]
        self.assertEqual(self.brand.audit('/d/deck.pptx', 'acme', 'light'), {
            'status': 'WARN', 'blockers': [], 'warnings': [
                {'code': 'SMALL_TEXT', 'slide': 2, 'says': 'Make the text larger.'},
                {'code': 'HIGH_TEXT_DENSITY', 'slide': 3, 'says': 'Condense.'}]})
        self.assertEqual(self.brand.audit('/d/deck.pptx', 'acme', 'light'), {
            'status': 'BLOCKED', 'warnings': [
                {'code': 'SMALL_TEXT', 'slide': 2, 'says': 'Make the text larger.'}],
            'blockers': [{'code': 'UNRESOLVED_PLACEHOLDER', 'slide': 1,
                          'says': 'Replace the starter text.'}]})
        self.assertEqual(self.brand.audit('/d/deck.pptx', 'acme', 'light'),
                         {'status': 'PASS', 'blockers': [], 'warnings': []})
        with self.assertRaises(brand.Refused) as refused:
            self.brand.audit('/d/deck.pptx', 'acme', 'light')
        self.assertEqual(refused.exception.problems, ['Invalid argument: --file'])

    def test_a_readiness_check_that_found_something_is_an_answer_too(self):
        report = {'profile': 'presentation', 'ok': False, 'checks': [
            {'name': 'python3', 'ok': False, 'detail': 'Install Python 3.9+.'}],
            'capabilities': [{'name': 'local-renderer', 'status': 'missing'}]}
        self.answers = [(1, json.dumps(report), ''), (1, '', 'It could not look.\n')]
        self.assertEqual(self.brand.ready(), report)
        with self.assertRaisesRegex(brand.Refused, 'It could not look.'):
            self.brand.ready()

    def test_a_command_that_hangs_or_cannot_start_is_a_refusal(self):
        self.assertEqual(brand.run_command([sys.executable, '-c', 'print("ok")']),
                         (0, 'ok\n', ''))
        with mock.patch.object(brand, 'TIMEOUT', 1):
            with self.assertRaisesRegex(WorkspaceError,
                                        '^The brand skill did not answer in 1 seconds.$'):
                brand.run_command([sys.executable, '-c', 'import time; time.sleep(30)'])
        with self.assertRaisesRegex(WorkspaceError, 'could not be started'):
            brand.run_command(['no-such-program-anywhere'])


class StandInTests(unittest.TestCase):
    """The stand-in is a made-up brand that behaves as a brand skill does."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name).resolve()
        self.brand, self.slides = brand_stand_in.stand_in(), slides_stand_in.stand_in()
        self.skill = self.brand.run

    def refusal(self, call, *args, **named) -> list[str]:
        with self.assertRaises(brand.Refused) as refused:
            call(*args, **named)
        return refused.exception.problems

    def exported(self, name: str = 'brand', variant: str = 'light', **named) -> dict:
        made = self.brand.export(self.root / name, 'example', variant, **named)
        return json.loads(Path(made['contract']).read_text())

    def deck(self, *content, name: str = 'deck') -> Path:
        """A deck of the content slides given, drawn plainly and rendered by the slides
        stand-in."""
        contract = self.brand.export(self.root / f'{name}-brand', 'example',
                                     'light')['contract']
        composition = self.root / f'{name}.json'
        composition.write_text(json.dumps({
            'version': 1, 'title': 'Rolling restarts 101', 'direction': DIRECTION,
            'slides': [slides_stand_in.sketch(slide, 's1_') for slide in content]}))
        self.slides.compile(composition, contract, self.root / f'{name}-compiled')
        self.slides.render(self.root / f'{name}-compiled', self.root / f'{name}.pptx')
        return self.root / f'{name}.pptx'

    def test_it_is_one_made_up_brand_in_two_variants(self):
        self.assertEqual(self.brand.name, 'Example Brand')
        self.assertEqual(self.brand.brands(), [
            {'brand': 'example', 'name': 'Example Co', 'variants': ['light', 'dark']}])
        self.assertEqual(self.skill.calls, [['version'], ['brands', '--json']])

    def test_an_export_writes_the_contract_and_its_two_guides_into_a_new_folder(self):
        made = self.brand.export(self.root / 'brand', 'example', 'light')
        folder = self.root / 'brand'
        self.assertEqual(sorted(path.name for path in folder.iterdir()),
                         ['DESIGN.md', 'VOICE.md', 'brand-contract.json'])
        self.assertEqual({path.stat().st_mode & 0o777 for path in folder.iterdir()}, {0o600})
        contract = json.loads(Path(made['contract']).read_text())
        self.assertEqual((contract['schema'], contract['identity'], contract['medium']),
                         (1, {'id': 'example', 'name': 'Example Co', 'variant': 'light'},
                          {'kind': 'slides', 'delivery': 'reading'}))
        self.assertEqual([source['kind'] for source in contract['sources']],
                         ['tokens', 'brand policy', 'presentation system', 'native template',
                          'icon library', 'icon index'])
        for source in contract['sources']:
            self.assertTrue(Path(source['path']).is_relative_to(self.skill.home))
        voice = Path(made['voice']).read_text()
        self.assertIn(f"Contract revision: {contract['revision']}", voice)
        self.assertIn('Write Example Co in full, never ExCo.', voice)
        self.assertIn('Example Platform is a product: keep its capitals.', voice)
        self.assertIn('Font: Arial. Color roles: {"canvasPrimary": "#FFFFFF"',
                      Path(made['design']).read_text())
        self.assertEqual(self.refusal(self.brand.export, folder, 'example', 'light')[0][:35],
                         'EEXIST: file already exists, mkdir ')
        self.assertEqual(len(list(folder.iterdir())), 3)

    def test_the_slides_stand_in_accepts_the_contract(self):
        made = self.brand.export(self.root / 'brand', 'example', 'light')
        self.assertEqual(self.slides.layouts(made['contract'])['default'], 'Title Only')
        self.assertIn('For example: a title holds 1 line at 28pt',
                      self.slides.outline_contract(made['contract']))

    def test_the_variant_and_the_delivery_make_it_another_contract(self):
        light, dark = self.exported('light'), self.exported('dark', 'dark')
        live = self.exported('live', delivery='live')
        self.assertEqual(len({light['revision'], dark['revision'], live['revision']}), 3)
        self.assertEqual((light['design']['colors']['canvasPrimary'],
                          dark['design']['colors']['canvasPrimary']), ('#FFFFFF', '#14171F'))
        self.assertEqual(live['medium'], {'kind': 'slides', 'delivery': 'live'})
        self.assertEqual(live['design'], light['design'])
        self.assertIn('Delivery: live; body role: body.',
                      (self.root / 'live' / 'DESIGN.md').read_text())

    def test_a_brand_or_a_variant_it_does_not_hold_is_refused(self):
        self.assertEqual(self.refusal(self.brand.export, self.root / 'a', 'nobody', 'light'),
                         ['Unknown brand: nobody. Choose Example Co.'])
        self.assertEqual(self.refusal(self.brand.export, self.root / 'a', 'example', 'sepia'),
                         ['Unknown example variant: sepia. Choose light, dark.'])
        self.assertEqual(list(self.root.iterdir()), [])
        self.exported('named', variant='dark')
        self.brand.export(self.root / 'by-name', 'Example Co', 'light')

    def test_a_contract_is_current_until_the_brand_changes_underneath_it(self):
        made = self.brand.export(self.root / 'brand', 'example', 'light')
        contract = json.loads(Path(made['contract']).read_text())
        self.assertEqual(self.brand.check(made['contract']), {
            'revision': contract['revision'], 'identity': contract['identity'],
            'medium': contract['medium'], 'sources': 6, 'status': 'current local sources'})
        rules = self.skill.home / 'references' / 'brand-rules.md'
        rules.write_text(rules.read_text() + 'Round corners after all.\n')
        self.assertEqual(self.refusal(self.brand.check, made['contract']),
                         ['Brand authority changed (brand policy); resolve a fresh contract'])
        fresh = self.exported('fresh')
        self.assertNotEqual(fresh['revision'], contract['revision'])
        self.assertEqual(self.brand.check(self.root / 'fresh' / 'brand-contract.json')
                         ['status'], 'current local sources')
        fresh['design']['colors']['headingPrimary'] = '#000000'
        (self.root / 'edited.json').write_text(json.dumps(fresh))
        self.assertEqual(self.refusal(self.brand.check, self.root / 'edited.json'),
                         ['Brand contract changed; resolve a fresh handoff'])
        self.assertRegex(self.refusal(self.brand.check, self.root / 'nowhere.json')[0],
                         '^ENOENT: no such file or directory')

    def test_a_folder_of_its_own_can_be_given_and_is_then_kept(self):
        first = brand_stand_in.StandIn(self.root / 'skill')
        self.assertEqual(first.home, self.root / 'skill')
        tokens = self.root / 'skill' / 'brand' / 'tokens.json'
        tokens.write_text(tokens.read_text().replace('#1F4E8C', '#123456'))
        again = brand.Brand(runtime=Path('stand-in'), run=brand_stand_in.StandIn(self.root / 'skill'))
        made = again.export(self.root / 'brand', 'example', 'light')
        self.assertEqual(json.loads(Path(made['contract']).read_text())['design']['colors']
                         ['headingPrimary'], '#123456')
        passing = brand_stand_in.StandIn()
        own = passing.home
        self.assertTrue((own / 'assets' / 'template.pptx').is_file())
        del passing
        gc.collect()
        self.assertFalse(own.exists(), 'a folder it made for itself goes when it does')

    def test_every_word_of_an_icon_search_must_match(self):
        cloud = {'id': 'ex-cloud', 'name': 'Icon cloud', 'category': 'Platform',
                 'native': True}
        lock = {'id': 'ex-cloud-lock', 'name': 'Icon cloud lock', 'category': 'Security',
                'native': True}
        self.assertEqual(self.brand.icons('cloud'), [cloud, lock])
        self.assertEqual(self.brand.icons('Cloud, LOCK'), [lock])
        self.assertEqual(self.brand.icons('clo'), [cloud, lock])
        self.assertEqual(self.brand.icons('cloud', limit=1), [cloud])
        self.assertEqual(self.brand.icons('database failover'), [])
        self.assertEqual(self.brand.icons('data'), [{'id': 'ex-database', 'category': 'Data',
                                                     'name': 'Icon database', 'native': True}])
        self.assertEqual(self.brand.icons('photo'), [{'id': 'ex-photo', 'category': 'People',
                                                      'name': 'Icon team photo',
                                                      'native': False}])
        self.assertEqual(self.refusal(self.brand.icons, ' ,, '),
                         ['--query needs words to search for'])
        self.assertEqual(self.refusal(self.brand.icons, 'cloud', limit=21),
                         ['--limit must be an integer from 1 to 20'])
        self.assertEqual(self.skill.calls[1], ['icons', '--query', 'cloud', '--limit', '5',
                                               '--json', '--no-previews'])

    def test_the_audit_warns_on_every_caveat_and_source_line_as_a_real_one_does(self):
        report = self.brand.audit(self.deck(STEPS, PAIR), 'example', 'light')
        self.assertEqual(report, {'status': 'WARN', 'blockers': [], 'warnings': [
            {'code': 'SMALL_TEXT', 'slide': 1,
             'says': 'Make the text larger, or move the detail to the notes.'}] * 2})
        self.assertEqual(self.brand.audit(self.deck(PAIR, name='plain'), 'example', 'dark'),
                         {'status': 'PASS', 'blockers': [], 'warnings': []})

    def test_the_audit_counts_the_words_a_slide_shows(self):
        wordy = {**PAIR, 'points': [{'label': 'One', 'text': 'word ' * 28},
                                    {'label': 'Two', 'text': 'word ' * 28}]}
        report = self.brand.audit(self.deck(wordy), 'example', 'light')
        self.assertEqual(report['warnings'], [
            {'code': 'HIGH_TEXT_DENSITY', 'slide': 1,
             'says': 'Cut the words the slide shows, or move detail to the notes.'}])
        code, out, _ = self.skill(['node', 'script', 'presentation', '--file',
                                   str(self.root / 'deck.pptx'), '--json'])
        whole = json.loads(out)
        self.assertEqual((code, whole['status'], whole['brand'], whole['variant'],
                          whole['thresholds'], whole['slides']),
                         (0, 'WARN', 'example', 'light', {'maxWords': 60, 'minTextPt': 18},
                          [{'slide': 1, 'words': 64, 'textObjects': 3, 'minFontPt': 20.0}]))
        self.assertEqual(whole['warnings'][0]['observed'],
                         {'words': 64, 'reviewThreshold': 60})

    def test_starter_text_left_in_a_slide_blocks_the_audit(self):
        left = {**PAIR, 'points': [{'label': 'One', 'text': 'Lorem ipsum dolor sit amet.'},
                                   {'label': 'Two', 'text': 'Click to add text'}]}
        deck = self.deck(left)
        self.assertEqual(self.brand.audit(deck, 'example', 'light'), {
            'status': 'BLOCKED', 'warnings': [], 'blockers': [
                {'code': 'UNRESOLVED_PLACEHOLDER', 'slide': 1,
                 'says': 'Replace the starter text with what the slide should say.'}] * 2})
        self.assertEqual(self.skill(['node', 'script', 'presentation', '--file', str(deck),
                                     '--json'])[0], 2)

    def test_the_audit_refuses_what_is_not_a_deck_or_not_its_brand(self):
        notes = self.root / 'notes.pptx'
        notes.write_text('PK\x03\x04 not an archive\n')
        self.assertEqual(self.refusal(self.brand.audit, notes, 'example', 'light'),
                         ['The file is not a PowerPoint package that can be read.'])
        self.assertEqual(self.refusal(self.brand.audit, self.root / 'deck.key', 'example',
                                      'light'), ['--file requires a .pptx path'])
        self.assertEqual(self.refusal(self.brand.audit, notes, 'nobody', 'light'),
                         ['Unknown brand: nobody. Choose Example Co.'])

    def test_its_readiness_check_answers_in_the_skills_shape(self):
        found = self.brand.ready()
        self.assertEqual((found['profile'], found['ok'], found['checks'][0]),
                         ('presentation', True, {'name': 'node', 'ok': True}))
        self.assertEqual(found['capabilities'][0], {'name': 'assets', 'status': 'available'})

    def test_it_refuses_a_command_it_does_not_have_and_lists_its_calls(self):
        self.assertEqual(self.skill(['node', 'script', 'layouts']),
                         (2, '', 'Unknown command: layouts. Run example-brand --help.\n'))
        self.assertEqual(self.skill(['node', 'script', 'contract', 'show']),
                         (1, '', 'Use contract export|check\n'))
        self.assertEqual(self.skill(['node', 'script', '--version']),
                         (0, 'Example Brand 0.0.0-stand-in\n', ''))
        self.assertEqual(self.skill.calls[1:], [['layouts'], ['contract', 'show'],
                                                ['--version']])

    def test_a_whole_deck_goes_through_both_stand_ins(self):
        """From an approved outline to a branded deck that was looked at, audited and put
        in Drive, as the pipeline will take one."""
        deck, made = self.slides, self.brand.export(self.root / 'brand', 'example', 'light')
        contract = made['contract']
        outline = self.root / 'outline.json'
        outline.write_text(json.dumps({**OUTLINE, 'approval': ['Looks right. Go ahead.']}))
        self.assertEqual(deck.outline_check(outline, contract)['findings'], [])
        started = deck.outline_start(outline, contract, self.root / 'build')
        self.assertEqual(started['parts'], ['lead-1.json', 'section-1.json', 'lead-2.json'])
        content = [slide for slide in OUTLINE['slides'] if slide['kind'] == 'content']
        section = self.root / 'build' / 'section-1.json'
        section.write_text(json.dumps({
            'version': 1, 'title': OUTLINE['title'], 'direction': DIRECTION,
            'slides': [slides_stand_in.sketch(slide, 's1_') for slide in content]}))
        self.brand.check(contract)
        self.assertEqual(deck.compile(section, contract)['slides'], 2)
        drawn = deck.compile(section, contract, self.root / 'section-compiled')
        first = deck.preview(drawn['output'], self.root / 'section-preview', 'drive')
        deck.merge(self.root / 'build' / 'parts.json', self.root / 'build' / 'whole.json')
        compiled = deck.compile(self.root / 'build' / 'whole.json', contract,
                                self.root / 'compiled')['output']
        shown = deck.preview(compiled, self.root / 'preview', 'drive',
                             file_id=first['fileId'])
        self.assertEqual((len(shown['slides']), shown['fileId'], len(deck.run.files)),
                         (4, first['fileId'], 1))
        assessment = self.root / 'assessment.json'
        assessment.write_text(json.dumps({
            'deckSha256': shown['deckSha256'], 'reviewer': 'independent', 'findings': [
                {'slide': 'what-it-is', 'question': 3, 'severity': 'major',
                 'note': 'The three steps are the same weight as the point.'}]}))
        self.assertEqual(deck.critique(self.root / 'preview', assessment)['major'], 1)
        self.assertEqual(Path(shown['deck']).read_bytes()[:4], b'PK\x03\x04')
        audit = self.brand.audit(shown['deck'], 'example', 'light')
        self.assertEqual((audit['status'], [(warning['code'], warning['slide'])
                                            for warning in audit['warnings']]),
                         ('WARN', [('SMALL_TEXT', 2), ('SMALL_TEXT', 2)]))
        self.assertEqual(deck.cited(compiled), {'O1': [2, 3], 'O2': [3]})
        self.assertEqual(deck.drive_import(shown['deck'], OUTLINE['title'])['name'],
                         'Rolling restarts 101')


if __name__ == '__main__':
    unittest.main()
