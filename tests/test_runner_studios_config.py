"""The studios config: the one file of the values every *-studio shares, written when one of
them is saved. Every test points STUDIOS_CONFIG at a file in a temporary folder of its own."""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  keeps every test away from the real per-user files
import runner_support  # noqa: F401  puts the runner on the import path

from workspace import WorkspaceError

from runner import studios_config

# A file another studio wrote: its own layout, keys Training Studio does not know, and a
# member it does know set out on one line.
THEIRS = """{
    "schema": 1,
    "team": {"repository": "https://github.com/acme/team.git", "branch": "main",
             "reviewers": ["sam", "kim"]},
    "person": { "name": "Dan Baskette" },
    "assistant": { "agent": "claude", "model": "opus", "effort": "high" },
    "brand": { "brand": "tanzu", "variant": "light" },
    "output": "google",
    "share": "decision",
    "blog": {"tone": "plain", "drafts": 3, "nested": {"a": [1, 2, {"b": null}]}}
}
"""


class StudiosConfigCase(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.folder = Path(holder.name).resolve()
        self.file = self.folder / 'config' / 'studios-config.json'
        patch = mock.patch.dict(os.environ, {'STUDIOS_CONFIG': str(self.file)})
        patch.start()
        self.addCleanup(patch.stop)

    def write(self, text) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            self.file.write_bytes(text)
        else:
            self.file.write_text(text, encoding='utf-8')


class ReadTests(StudiosConfigCase):
    def test_the_file_is_named_by_the_environment_or_is_in_the_config_folder(self):
        self.assertEqual(studios_config.path(), self.file)
        with mock.patch.dict(os.environ, {'HOME': str(self.folder)}):
            os.environ.pop('STUDIOS_CONFIG')
            self.assertEqual(studios_config.path(),
                             self.folder / '.config' / 'studios-config.json')
        self.assertEqual(studios_config.PATH.parts[-2:], ('.config', 'studios-config.json'))

    def test_no_file_is_nothing_shared_and_nothing_wrong(self):
        self.assertEqual(studios_config.read(), ({}, None))
        self.assertFalse(self.file.exists())

    def test_a_file_is_read_as_it_is(self):
        self.write(THEIRS)
        found, problem = studios_config.read()
        self.assertIsNone(problem)
        self.assertEqual(found, json.loads(THEIRS))

    def test_a_file_that_cannot_be_used_is_empty_with_one_sentence(self):
        for text, why in (('{"schema": 1, ', 'it is not valid JSON'),
                          ('[1, 2]', 'it does not hold a JSON object'),
                          ('{"schema": 2}', 'it is written for a newer version'),
                          ('{"schema": "one"}', 'it is written for a newer version'),
                          (b'\xff\xfe{}', 'it is not text in UTF-8')):
            with self.subTest(text=text):
                self.write(text)
                found, problem = studios_config.read()
                self.assertEqual(found, {})
                self.assertIn(why, problem)
                self.assertTrue(problem.startswith(str(self.file) + ' could not be read'))
                self.assertTrue(problem.endswith(
                    ', so Training Studio uses its built-in defaults for the values every '
                    'studio shares, and saves none of them, until it can be read.'))
                self.assertEqual(problem.count('. '), 0, 'one sentence')
                self.assertTrue(problem.endswith('.'))

    def test_a_folder_in_its_place_cannot_be_read(self):
        self.file.mkdir(parents=True)
        found, problem = studios_config.read()
        self.assertEqual(found, {})
        self.assertIn('could not be read', problem)

    def test_a_file_in_the_home_folder_is_named_from_there(self):
        with mock.patch.object(Path, 'home', lambda: self.folder):
            self.assertEqual(studios_config.shown(self.folder / '.config' / 'x.json'),
                             '~/.config/x.json')
        self.assertEqual(studios_config.shown(self.file), str(self.file))


class UpdateTests(StudiosConfigCase):
    def test_a_first_write_makes_the_file_with_its_schema(self):
        written = studios_config.update({'team': {'repository': 'git@example.com:t/r.git'}})
        self.assertEqual(written, {'schema': 1,
                                   'team': {'repository': 'git@example.com:t/r.git'}})
        self.assertEqual(json.loads(self.file.read_text()), written)
        self.assertTrue(self.file.read_text().endswith('\n'))

    def test_only_what_changes_is_written_and_every_other_byte_stays(self):
        self.write(THEIRS)
        written = studios_config.update({'assistant': {'model': 'sonnet'}, 'share': 'asked'})
        expected = (THEIRS.replace('"model": "opus"', '"model": "sonnet"')
                    .replace('"share": "decision"', '"share": "asked"'))
        self.assertEqual(self.file.read_text(encoding='utf-8'), expected)
        self.assertEqual(written, json.loads(expected))

    def test_a_new_member_is_added_beside_the_others_in_their_layout(self):
        self.write(THEIRS)
        studios_config.update({'person': {'email': 'dan@example.com'},
                               'team': {'folder': 'shared'}, 'colour': 'blue'})
        text = self.file.read_text(encoding='utf-8')
        self.assertIn('"person": { "name": "Dan Baskette", "email": "dan@example.com" },',
                      text)
        self.assertIn('"reviewers": ["sam", "kim"],\n             "folder": "shared"}', text)
        self.assertTrue(text.endswith('"nested": {"a": [1, 2, {"b": null}]}},\n'
                                      '    "colour": "blue"\n}\n'), text)
        before = json.loads(THEIRS)
        before['person']['email'] = 'dan@example.com'
        before['team']['folder'] = 'shared'
        before['colour'] = 'blue'
        self.assertEqual(json.loads(text), before)

    def test_a_new_group_and_an_empty_one_are_filled(self):
        self.write('{"schema": 1, "team": {}}')
        studios_config.update({'team': {'branch': 'main'},
                               'assistant': {'agent': 'codex', 'model': None}})
        self.assertEqual(self.file.read_text(),
                         '{"schema": 1, "team": {"branch": "main"}, "assistant": '
                         '{"agent": "codex", "model": null}}')

    def test_an_empty_file_object_takes_the_schema_first(self):
        self.write('{}\n')
        studios_config.update({'share': 'asked'})
        self.assertEqual(json.loads(self.file.read_text()), {'schema': 1, 'share': 'asked'})

    def test_a_value_that_is_not_an_object_is_replaced_by_one(self):
        self.write('{"schema": 1, "team": "ours", "share": "decision"}')
        studios_config.update({'team': {'branch': 'main'}})
        self.assertEqual(self.file.read_text(),
                         '{"schema": 1, "team": {"branch": "main"}, "share": "decision"}')

    def test_a_value_that_is_the_same_is_not_written_at_all(self):
        self.write(THEIRS)
        before = self.file.stat().st_mtime_ns
        os.utime(self.file, ns=(before - 10_000_000_000, before - 10_000_000_000))
        studios_config.update({'share': 'decision', 'assistant': {'agent': 'claude'}})
        self.assertEqual(self.file.read_text(encoding='utf-8'), THEIRS)
        self.assertEqual(self.file.stat().st_mtime_ns, before - 10_000_000_000)

    def test_a_key_given_twice_in_the_file_is_changed_where_json_reads_it(self):
        self.write('{"schema": 1, "share": "decision", "share": "asked"}')
        studios_config.update({'share': 'decision'})
        self.assertEqual(self.file.read_text(),
                         '{"schema": 1, "share": "decision", "share": "decision"}')

    def test_escapes_and_unicode_in_untouched_keys_stay_as_they_were(self):
        text = '{"schema": 1, "note": "caf\\u00e9 \\"quoted\\" \\\\ é", "share": "asked"}'
        self.write(text)
        studios_config.update({'share': 'decision'})
        self.assertEqual(self.file.read_text(encoding='utf-8'),
                         text.replace('"asked"', '"decision"'))

    def test_an_address_with_a_password_or_token_is_refused_and_nothing_is_written(self):
        self.write(THEIRS)
        for address in ('https://dan:hunter2@github.com/acme/team.git',
                        'https://ghp_abcdefghijklmnopqrstuvwxyz@github.com/acme/team.git'):
            for group in ('team', 'brand'):
                with self.subTest(address=address, group=group), \
                        self.assertRaisesRegex(WorkspaceError, 'password or token'):
                    studios_config.update({group: {'repository': address}})
        self.assertEqual(self.file.read_text(encoding='utf-8'), THEIRS)

    def test_the_brand_skills_repository_and_release_are_written_beside_the_brand(self):
        self.write(THEIRS)
        studios_config.update({'brand': {'repository': 'git@github.com:acme/brand.git',
                                          'release': 'v1.4.0'}})
        self.assertEqual(self.file.read_text(encoding='utf-8'), THEIRS.replace(
            '"variant": "light" }', '"variant": "light", "repository": '
            '"git@github.com:acme/brand.git", "release": "v1.4.0" }'))

    def test_a_file_that_cannot_be_read_is_never_written_over(self):
        self.write('{"schema": 1, "team": ')
        refused = (f'{self.file} could not be read (it is not valid JSON), so no value every '
                   'studio shares can be saved until it can, and the file was left as it is.')
        for attempt in (lambda: studios_config.update({'share': 'asked'}),
                        studios_config.writable):
            with self.assertRaises(WorkspaceError) as caught:
                attempt()
            self.assertEqual(str(caught.exception), refused)
        self.assertEqual(self.file.read_text(), '{"schema": 1, "team": ')
        self.file.write_text('{"schema": 1}')
        self.assertIsNone(studios_config.writable())

    def test_only_plain_values_are_written(self):
        for changes in ({'share': ['asked']}, {'team': {'branch': {'name': 'x'}}},
                        {'schema': 2}, [], {'team': 'main'}):
            with self.subTest(changes=changes), self.assertRaises(WorkspaceError):
                studios_config.update(changes)
        self.assertFalse(self.file.exists())

    def test_the_write_is_whole_or_not_at_all(self):
        self.write(THEIRS)
        with mock.patch.object(os, 'replace', side_effect=OSError('disk full')), \
                self.assertRaisesRegex(WorkspaceError, 'could not be written'):
            studios_config.update({'share': 'asked'})
        self.assertEqual(self.file.read_text(encoding='utf-8'), THEIRS)
        self.assertEqual(sorted(path.name for path in self.file.parent.iterdir()),
                         ['studios-config.json'])

    def test_its_permissions_are_kept(self):
        self.write(THEIRS)
        self.file.chmod(0o600)
        studios_config.update({'share': 'asked'})
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)

    def test_a_link_to_the_file_is_written_through_and_stays_a_link(self):
        real = self.folder / 'dotfiles' / 'studios-config.json'
        real.parent.mkdir()
        real.write_text(THEIRS, encoding='utf-8')
        self.file.parent.mkdir()
        self.file.symlink_to(real)
        studios_config.update({'share': 'asked'})
        self.assertTrue(self.file.is_symlink())
        self.assertEqual(json.loads(real.read_text())['share'], 'asked')


if __name__ == '__main__':
    unittest.main()
