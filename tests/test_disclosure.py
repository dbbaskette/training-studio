"""Progressive disclosure: each operation's loading set fits its budget (plan A9)."""
import unittest

import helpers
import validate_package

SIZES = validate_package.measured(helpers.SKILL)
SETS = validate_package.loading_sets()


class DisclosureTests(unittest.TestCase):
    def test_every_loading_set_fits_its_budget(self):
        for label, (files, budget) in SETS.items():
            with self.subTest(label):
                self.assertTrue(all(name in SIZES for name in files),
                                [name for name in files if name not in SIZES])
                self.assertLessEqual(sum(SIZES[name] for name in files), budget)

    def test_every_stage_and_mode_has_a_loading_set(self):
        stages = {path.stem for path in (helpers.SKILL / 'references' / 'stages').glob('*.md')}
        modes = {path.stem for path in (helpers.SKILL / 'references' / 'modes').glob('*.md')}
        budgeted = {label.partition(':')[2] for label in SETS if label.startswith('stage:')}
        self.assertEqual(stages - {'scenario', 'yoodli'}, budgeted)
        for stage in ('scenario', 'yoodli'):
            self.assertEqual(modes, {label.partition(':')[2] for label in SETS
                                     if label.startswith(f'{stage}:')})

    def test_the_entry_is_one_file_within_its_budget(self):
        self.assertLessEqual(SIZES['SKILL.md'], validate_package.BUDGET['skill'])
        self.assertEqual(SETS['start'][0][0], 'SKILL.md')

    def test_the_installed_entry_is_small_and_describes_the_same_skill(self):
        bootstrap = (helpers.REPO / 'bootstrap' / 'training-studio' / 'SKILL.md').read_text()
        entry = (helpers.SKILL / 'SKILL.md').read_text()
        self.assertLessEqual(validate_package.estimate(bootstrap), 400)
        self.assertEqual(bootstrap.split('---')[1], entry.split('---')[1])
        self.assertLessEqual(validate_package.estimate(bootstrap) + SIZES['SKILL.md'], 1400)

    def test_the_entry_links_every_reference_and_example_itself(self):
        linked = {resolved for _, resolved
                  in validate_package.local_links(helpers.SKILL / 'SKILL.md')}
        for name in SIZES:
            if name != 'SKILL.md':
                self.assertIn((helpers.SKILL / name).resolve(), linked, name)
