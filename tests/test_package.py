"""The package validator, tested on a small synthetic package and on the real one."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import helpers
import validate_package

GUIDANCE = [name for name in validate_package.REQUIRED
            if name.startswith(('references/', 'assets/examples/'))]


class SyntheticCase(unittest.TestCase):
    """A minimal package that satisfies the validator, to break one rule at a time."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.skill = Path(holder.name).resolve() / 'training-studio'
        for name in validate_package.REQUIRED:
            self.put(name, f'# {name}\n')
        links = '\n'.join(f'- [{name}]({name})' for name in GUIDANCE)
        self.put('SKILL.md', '---\nname: training-studio\ndescription: A short one.\n---\n\n'
                 + links + '\n')

    def put(self, name: str, text: str) -> None:
        path = self.skill / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def append(self, name: str, text: str) -> None:
        path = self.skill / name
        path.write_text(path.read_text(encoding='utf-8') + text, encoding='utf-8')

    def found(self) -> list[str]:
        return validate_package.problems(self.skill)

    def test_the_minimal_package_is_whole(self):
        self.assertEqual(self.found(), [])

    def test_a_missing_required_file_is_reported(self):
        (self.skill / 'references' / 'modes' / 'tutor.md').unlink()
        found = self.found()
        self.assertIn('Missing: references/modes/tutor.md', found)
        self.assertIn('SKILL.md links to missing references/modes/tutor.md', found)

    def test_a_broken_link_in_a_reference_is_reported(self):
        self.append('references/gates.md', '\nSee [nothing](nowhere.md).\n')
        self.assertEqual(self.found(), ['references/gates.md links to missing nowhere.md'])

    def test_external_links_are_not_followed(self):
        self.append('references/privacy.md', '\nSee [docs](https://example.com/missing).\n')
        self.assertEqual(self.found(), [])

    def test_a_reference_reached_only_through_another_is_reported(self):
        self.put('references/deep.md', '# Deep\n')
        self.append('references/gates.md', '\nSee [deep](deep.md).\n')
        self.assertEqual(self.found(), ['references/deep.md is not linked from SKILL.md, '
                                        'so it is more than one hop away'])

    def test_an_example_not_linked_from_the_entry_is_reported(self):
        self.put('assets/examples/extra.md', '# Extra\n')
        self.assertEqual(self.found(), ['assets/examples/extra.md is not linked from SKILL.md, '
                                        'so it is more than one hop away'])

    def test_files_over_budget_are_reported(self):
        self.append('references/intake.md', 'x' * 4000)
        self.append('assets/examples/document.md', 'y' * 4900)
        found = self.found()
        self.assertTrue(any(line.startswith('references/intake.md is 1') and
                            line.endswith('the budget is 1000') for line in found), found)
        self.assertTrue(any(line.startswith('assets/examples/document.md is 12') and
                            line.endswith('the budget is 1200') for line in found), found)

    def test_an_oversized_entry_or_description_is_reported(self):
        self.append('SKILL.md', 'z' * 4000)
        self.assertTrue(any(line.startswith('SKILL.md is ') for line in self.found()))
        self.put('SKILL.md', '---\nname: training-studio\ndescription: ' + 'word ' * 90
                 + '\n---\n\n' + '\n'.join(f'- [{name}]({name})' for name in GUIDANCE) + '\n')
        self.assertTrue(any(line.startswith('The description is ') for line in self.found()))

    def test_a_loading_set_over_budget_is_reported(self):
        for name in ('references/stages/scenario.md', 'references/modes/pitch.md',
                     'references/profiles/yoodli.md', 'references/gates.md'):
            self.append(name, 'x' * 3900)
        self.append('assets/examples/yoodli.md', 'x' * 4700)
        self.append('assets/examples/scenario.md', 'x' * 4700)
        found = self.found()
        self.assertTrue(any(line.startswith('Loading set scenario:pitch is ')
                            for line in found), found)

    def test_guidance_alone_can_be_checked(self):
        import shutil
        for name in ('scripts', 'agents'):
            shutil.rmtree(self.skill / name)
        (self.skill / 'VERSION').unlink()
        self.assertTrue(any(line.startswith('Missing: scripts/') for line in self.found()))
        self.assertEqual(validate_package.problems(self.skill, guidance_only=True), [])

    def test_measure_prints_files_and_loading_sets(self):
        table = validate_package.measure(self.skill)
        self.assertIn('| `SKILL.md` |', table)
        self.assertIn('| Whole library |', table)
        self.assertIn('| `scenario:roleplay` |', table)


class RealPackageTests(unittest.TestCase):
    def test_the_package_is_whole(self):
        self.assertEqual(validate_package.problems(helpers.SKILL), [])

    def test_the_main_function_reports_ok(self):
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = validate_package.main([str(helpers.SKILL)])
        self.assertEqual((code, printed.getvalue()), (0, 'ok\n'))
