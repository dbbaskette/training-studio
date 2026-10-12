"""The Google Docs round-trip: anchors, the sync rules, the commands and the gcloud transport.

Nothing here reaches the network. The sync rules run against an in-memory transport, and
GcloudTransport runs against a stubbed token command and a stubbed HTTP layer.
"""
import contextlib
import functools
import io
import json
import os
import re
import subprocess
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import helpers
from helpers import TrainingCase
import checks
import gdocs
import training
import workspace
from workspace import WorkspaceError

CLI = helpers.SCRIPTS / 'training.py'
TOKEN = 'stand-in-access-token-0123456789abcdef'
COMMENTS = ['<!-- covers: O3 -->', '<!-- covers: O1 K1.1 K1.3 -->', '<!-- covers: O2 K1.2 -->']
ANCHORS = [['Why this matters', COMMENTS[0]],
           ['What a rolling restart does', COMMENTS[1]],
           ['When capacity holds', COMMENTS[2]]]


def setUpModule():
    """A slip in a test must fail here. It must never run gcloud or reach Google."""
    really_run = subprocess.run

    def run(command, *args, **options):
        if list(command)[:1] == ['gcloud']:
            raise AssertionError('A test tried to run gcloud.')
        return really_run(command, *args, **options)

    blocked = mock.Mock(side_effect=AssertionError('A test tried to reach the network.'))
    for owner, name, stand_in in ((subprocess, 'run', run), (urllib.request, 'urlopen', blocked)):
        patcher = mock.patch.object(owner, name, stand_in)
        patcher.start()
        unittest.addModuleCleanup(patcher.stop)


def example(name: str) -> str:
    return (helpers.EXAMPLES / name).read_text(encoding='utf-8')


DOCUMENT = example('document.md')
BRIEF = example('product-brief.md')


def google_style(markdown: str) -> str:
    """What a Doc gives back: no HTML comments, and its own idea of how to write a list."""
    text = re.sub(r'<!--.*?-->\n?', '', markdown, flags=re.DOTALL)
    return '\ufeff' + text.replace('\n- ', '\n* ').replace('\n', '\r\n')


class FakeTransport(gdocs.Transport):
    """An in-memory Drive. It can create, replace and export, and nothing else."""

    def __init__(self):
        self.docs: dict[str, str] = {}
        self.titles: dict[str, str] = {}
        self.calls: list[tuple] = []
        self.fail_export = 0

    def create(self, title, markdown):
        file_id = f'doc{len(self.docs) + 1}'
        self.docs[file_id], self.titles[file_id] = markdown, title
        self.calls.append(('create', file_id))
        return {'file_id': file_id, 'url': f'https://docs.example.com/d/{file_id}/edit'}

    def update(self, file_id, markdown):
        self.docs[file_id] = markdown
        self.calls.append(('update', file_id))

    def export(self, file_id):
        self.calls.append(('export', file_id))
        if self.fail_export:
            self.fail_export -= 1
            raise WorkspaceError('Could not reach Google Drive. Try again.')
        return google_style(self.docs[file_id])

    def edit(self, file_id, old, new):
        """Someone edits the Doc in the browser."""
        assert old in self.docs[file_id], old
        self.docs[file_id] = self.docs[file_id].replace(old, new)

    def did(self, action):
        return [call for call in self.calls if call[0] == action]


# --- anchors ------------------------------------------------------------------------

class AnchorTests(unittest.TestCase):
    def test_strip_removes_each_comment_and_remembers_the_heading_above_it(self):
        text, anchors = gdocs.strip_comments(DOCUMENT)
        self.assertNotIn('<!--', text)
        self.assertEqual(anchors, ANCHORS)
        self.assertIn('## Why this matters\n\nA customer restarts', text)

    def test_the_examples_survive_a_round_trip_unchanged(self):
        for name in ('document.md', 'product-brief.md', 'competitive-brief.md'):
            with self.subTest(name):
                original = example(name)
                text, anchors = gdocs.strip_comments(original)
                self.assertNotIn('<!--', text)
                self.assertEqual(gdocs.restore_comments(text, anchors), (original, []))

    def test_the_brief_keeps_its_findings_comments(self):
        text, anchors = gdocs.strip_comments(BRIEF)
        self.assertIn(['2. What it is and where it fits', '<!-- findings: availability -->'],
                      anchors)
        restored, unplaced = gdocs.restore_comments(google_style(text), anchors)
        self.assertEqual(unplaced, [])
        self.assertEqual(checks.FINDINGS_COMMENT.findall(restored),
                         checks.FINDINGS_COMMENT.findall(BRIEF))

    def test_a_restored_document_declares_the_same_coverage(self):
        text, anchors = gdocs.strip_comments(DOCUMENT)
        restored, _ = gdocs.restore_comments(google_style(text), anchors)
        self.assertEqual(checks.tagged(checks.COVERS, restored, checks.COVERED_ID),
                         checks.tagged(checks.COVERS, DOCUMENT, checks.COVERED_ID))

    def test_headings_match_whatever_the_whitespace_and_numbering(self):
        anchors = [['2. Capabilities', '<!-- findings: availability -->'],
                   ['Limits', '<!-- findings: instance-min -->']]
        for heading in ('## Capabilities', '##   2.  Capabilities  ', '## 7) Capabilities',
                        '## 2\\. Capabilities', '## **2. Capabilities**', '### Capabilities ##'):
            with self.subTest(heading):
                text, unplaced = gdocs.restore_comments(
                    f'# Brief\n\n{heading}\n\nText.\n\n## 3. Limits\n\nMore.\n', anchors)
                self.assertEqual(unplaced, [])
                self.assertIn(f'{heading}\n\n<!-- findings: availability -->\n\nText.', text)
                self.assertIn('## 3. Limits\n\n<!-- findings: instance-min -->\n\nMore.', text)

    def test_an_anchor_whose_heading_is_gone_is_reported_and_the_rest_are_placed(self):
        text, unplaced = gdocs.restore_comments(
            '# Title\n\n## Why this matters\n\nText.\n\n## Renamed\n\nMore.\n', ANCHORS[:2])
        self.assertEqual(unplaced, [{'heading': 'What a rolling restart does',
                                     'comment': COMMENTS[1]}])
        self.assertIn('## Why this matters\n\n<!-- covers: O3 -->\n\nText.', text)
        self.assertNotIn(COMMENTS[1], text)

    def test_a_comment_goes_back_under_the_right_one_of_two_headings_with_the_same_text(self):
        original = ('# Course\n\n## Restarts\n\n### Summary\n\nFirst.\n\n## Health checks\n\n'
                    '### Summary\n\n<!-- covers: O4 -->\n\nSecond.\n')
        text, anchors = gdocs.strip_comments(original)
        self.assertEqual(anchors, [['Summary', '<!-- covers: O4 -->', 2]])
        self.assertEqual(gdocs.restore_comments(text, anchors), (original, []))
        gone, unplaced = gdocs.restore_comments('# Course\n\n### Summary\n\nFirst.\n', anchors)
        self.assertEqual(unplaced, [{'heading': 'Summary', 'comment': '<!-- covers: O4 -->'}])
        self.assertNotIn('<!--', gone)

    def test_two_comments_under_one_heading_both_come_back(self):
        original = '## Section\n\n<!-- covers: O1 -->\n<!-- covers: K1.1 -->\n\nText.\n'
        text, anchors = gdocs.strip_comments(original)
        self.assertEqual(text, '## Section\n\nText.\n')
        self.assertEqual(gdocs.restore_comments(text, anchors), (original, []))

    def test_a_comment_above_every_heading_goes_back_to_the_top(self):
        text, anchors = gdocs.strip_comments('<!-- covers: O1 -->\n\n# Title\n\nText.\n')
        self.assertEqual((text, anchors), ('# Title\n\nText.\n', [['', '<!-- covers: O1 -->']]))
        self.assertEqual(gdocs.restore_comments(text, anchors),
                         ('<!-- covers: O1 -->\n\n# Title\n\nText.\n', []))

    def test_a_comment_sharing_a_line_with_text_is_lifted_out_of_it(self):
        text, anchors = gdocs.strip_comments('## Section <!-- covers: O1 -->\n\nText.\n')
        self.assertEqual(text, '## Section\n\nText.\n')
        self.assertEqual(anchors, [['Section', '<!-- covers: O1 -->']])

    def test_a_code_block_is_neither_searched_for_headings_nor_stripped(self):
        original = ('## Real\n\n<!-- covers: O1 -->\n\n```\n# not a heading\n'
                    '<!-- covers: O9 -->\n```\n\nText.\n')
        text, anchors = gdocs.strip_comments(original)
        self.assertEqual(anchors, [['Real', '<!-- covers: O1 -->']])
        self.assertIn('<!-- covers: O9 -->', text)
        self.assertEqual(gdocs.restore_comments(text, anchors), (original, []))

    def test_other_html_comments_are_left_in_the_text(self):
        text, anchors = gdocs.strip_comments('## Section\n\n<!-- a note -->\n\nText.\n')
        self.assertEqual((text, anchors), ('## Section\n\n<!-- a note -->\n\nText.\n', []))

    def test_line_endings_and_a_byte_order_mark_do_not_change_the_hash(self):
        self.assertEqual(gdocs.digest('\ufeff# Title\r\n\r\nText.\r\n\r\n'),
                         gdocs.digest('# Title\n\nText.\n'))
        self.assertNotEqual(gdocs.digest('# Title\n\nText!\n'), gdocs.digest('# Title\n\nText.\n'))


# --- the sync rules, against the in-memory transport --------------------------------

class SyncCase(TrainingCase):
    """An approved learner guide and brief, with a deck built from the guide."""

    levels: tuple = ()

    def setUp(self):
        super().setUp()
        workspace.init(self.root, 'Rolling restarts', levels=list(self.levels))
        self.approved('intake', 'research-plan', 'research')
        self.at = f'@{self.levels[0]}' if self.levels else ''
        self.folder = f'{self.levels[0]}/' if self.levels else ''
        self.document, self.brief = f'document{self.at}', f'brief{self.at}'
        self.make(f'blueprint{self.at}', f'{self.folder}blueprint.md', example('blueprint.md'))
        self.make(self.document, f'{self.folder}document.md', DOCUMENT)
        self.make(self.brief, f'{self.folder}product-brief.md', BRIEF)
        self.approved(f'deck{self.at}')
        self.drive = FakeTransport()

    def make(self, name: str, relative: str, text: str) -> None:
        self.write(relative, text)
        workspace.save(self.root, name, built=True)
        workspace.approve(self.root, name)

    def file(self, name: str = 'document.md') -> Path:
        return self.root / f'{self.folder}{name}'

    def record(self) -> dict:
        return json.loads((self.root / '.training-studio' / 'google.json').read_text('utf-8'))

    def linked(self, name: str | None = None) -> dict:
        return self.record()['docs'][name or self.document]

    def history(self, folder: str = 'document') -> list[str]:
        kept = self.root / '.training-studio' / 'history' / folder
        return sorted(path.read_text('utf-8') for path in kept.iterdir())

    def refused(self, pattern: str):
        return self.assertRaisesRegex(WorkspaceError, pattern)


class PushTests(SyncCase):
    def test_a_first_push_creates_a_doc_without_the_comments(self):
        result = gdocs.push(self.root, 'document', self.drive)
        self.assertEqual(self.drive.calls, [('create', 'doc1'), ('export', 'doc1')])
        self.assertNotIn('<!--', self.drive.docs['doc1'])
        self.assertIn('## What a rolling restart does', self.drive.docs['doc1'])
        self.assertEqual(self.drive.titles['doc1'], 'Rolling restarts: learner guide')
        self.assertEqual(result['result'], 'created')
        self.assertEqual(result['url'], 'https://docs.example.com/d/doc1/edit')
        self.assertEqual(result['comments_held'], 3)

    def test_a_push_records_the_link_as_the_spec_lays_it_out(self):
        gdocs.push(self.root, 'document', self.drive)
        record = self.record()
        self.assertEqual((record['schema'], list(record['docs'])), (1, ['document']))
        entry = record['docs']['document']
        self.assertEqual(sorted(entry), ['anchors', 'file_id', 'local_sha256', 'remote_sha256',
                                         'synced_at', 'title', 'url'])
        self.assertEqual(entry['anchors'], ANCHORS)
        self.assertEqual(entry['local_sha256'], workspace.sha256_file(self.file()))
        self.assertRegex(entry['synced_at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')

    def test_the_remote_hash_is_of_the_export_not_of_what_was_sent(self):
        gdocs.push(self.root, 'document', self.drive)
        entry = self.linked()
        self.assertEqual(entry['remote_sha256'], gdocs.digest(self.drive.export('doc1')))
        self.assertNotEqual(entry['remote_sha256'], gdocs.digest(self.drive.docs['doc1']))
        self.assertEqual(gdocs.status(self.root, self.drive)['docs']['document']['state'],
                         'in sync')

    def test_a_push_changes_nothing_about_approval(self):
        gdocs.push(self.root, 'document', self.drive)
        self.assertEqual(self.state()['document'], 'approved')
        self.assertEqual(self.state()['deck'], 'approved')
        self.assertEqual(self.file().read_text('utf-8'), DOCUMENT)

    def test_a_later_push_replaces_the_same_doc(self):
        gdocs.push(self.root, 'document', self.drive)
        self.write('document.md', DOCUMENT.replace('one batch at a time', 'in small batches'))
        result = gdocs.push(self.root, 'document', self.drive)
        self.assertEqual(result['result'], 'updated')
        self.assertEqual(list(self.drive.docs), ['doc1'])
        self.assertIn('in small batches', self.drive.docs['doc1'])
        self.assertEqual(self.linked()['local_sha256'], workspace.sha256_file(self.file()))
        self.assertEqual(gdocs.status(self.root, self.drive)['docs']['document']['state'],
                         'in sync')

    def test_a_push_is_refused_when_the_doc_changed(self):
        gdocs.push(self.root, 'document', self.drive)
        before = self.record()
        self.drive.edit('doc1', 'one batch at a time', 'a few at a time')
        self.write('document.md', DOCUMENT + '\nA local addition.\n')
        with self.refused(r'^The Google Doc changed since the last sync\. Pull first\.$'):
            gdocs.push(self.root, 'document', self.drive)
        self.assertEqual(len(self.drive.did('update')), 0)
        self.assertIn('a few at a time', self.drive.docs['doc1'])
        self.assertEqual(self.record(), before)

    def test_force_overrides_a_changed_doc(self):
        gdocs.push(self.root, 'document', self.drive)
        self.drive.edit('doc1', 'one batch at a time', 'a few at a time')
        self.write('document.md', DOCUMENT + '\nA local addition.\n')
        gdocs.push(self.root, 'document', self.drive, force=True)
        self.assertIn('A local addition.', self.drive.docs['doc1'])
        self.assertNotIn('a few at a time', self.drive.docs['doc1'])
        self.assertEqual(gdocs.status(self.root, self.drive)['docs']['document']['state'],
                         'in sync')

    def test_only_the_document_and_the_brief_can_be_pushed(self):
        for name in ('intake', 'research', 'blueprint', 'deck', 'scenario:main', 'yoodli:main'):
            with self.subTest(name), self.refused('only the document and the brief'):
                gdocs.push(self.root, name, self.drive)
        self.assertEqual(self.drive.calls, [])
        self.assertFalse((self.root / '.training-studio' / 'google.json').exists())

    def test_the_brief_goes_without_its_findings_comments(self):
        result = gdocs.push(self.root, 'brief', self.drive)
        self.assertNotIn('<!--', self.drive.docs['doc1'])
        self.assertEqual(result['title'], 'Rolling restarts: product brief')
        self.assertEqual(self.linked('brief')['anchors'][0],
                         ['2. What it is and where it fits', '<!-- findings: availability -->'])

    def test_a_title_names_a_new_doc_only(self):
        gdocs.push(self.root, 'document', self.drive, title='Restarts guide for review')
        self.assertEqual(self.drive.titles['doc1'], 'Restarts guide for review')
        self.assertEqual(self.linked()['title'], 'Restarts guide for review')
        with self.refused('already linked'):
            gdocs.push(self.root, 'document', self.drive, title='Another name')

    def test_nothing_is_pushed_when_the_file_does_not_exist(self):
        self.file().unlink()
        with self.refused('document.md does not exist'):
            gdocs.push(self.root, 'document', self.drive)
        self.assertEqual(self.drive.calls, [])

    def test_a_push_cut_short_keeps_the_link_so_a_retry_does_not_make_a_second_doc(self):
        self.drive.fail_export = 1
        with self.refused('Could not reach Google Drive'):
            gdocs.push(self.root, 'document', self.drive)
        self.assertEqual(self.linked()['file_id'], 'doc1')
        self.assertIsNone(self.linked()['remote_sha256'])
        with self.refused('did not finish'):
            gdocs.pull(self.root, 'document', self.drive)
        self.assertEqual(gdocs.status(self.root)['docs']['document']['state'], 'local changed')
        self.assertEqual(gdocs.push(self.root, 'document', self.drive)['result'], 'updated')
        self.assertEqual(list(self.drive.docs), ['doc1'])
        self.assertEqual(gdocs.status(self.root, self.drive)['docs']['document']['state'],
                         'in sync')

    def test_a_record_that_cannot_be_read_is_left_alone(self):
        path = self.root / '.training-studio' / 'google.json'
        for broken in ('{not json', '{"schema": 2, "docs": {}}', '{"schema": 1, "docs": []}',
                       '{"schema": 1, "docs": {"document": {"url": "x"}}}',
                       '{"schema": 1, "docs": {"document": {"file_id": "x", "anchors": [1]}}}'):
            path.write_text(broken, 'utf-8')
            with self.subTest(broken), self.refused('refusing to change it'):
                gdocs.push(self.root, 'document', self.drive)
            self.assertEqual(path.read_text('utf-8'), broken)
        self.assertEqual(self.drive.calls, [])


class PullTests(SyncCase):
    def setUp(self):
        super().setUp()
        gdocs.push(self.root, 'document', self.drive)

    def test_remote_edits_come_back_with_the_comments_under_their_headings(self):
        self.drive.edit('doc1', 'one batch at a time', 'a few at a time')
        result = gdocs.pull(self.root, 'document', self.drive)
        text = self.file().read_text('utf-8')
        self.assertEqual(result['result'], 'pulled')
        self.assertEqual(result['unplaced'], [])
        self.assertIn('a few at a time', text)
        self.assertNotIn('\r', text)
        self.assertNotIn('\ufeff', text)
        for heading, comment in ANCHORS:
            self.assertIn(f'## {heading}\n\n{comment}\n\n', text)
        self.assertEqual(checks.tagged(checks.COVERS, text, checks.COVERED_ID),
                         checks.tagged(checks.COVERS, DOCUMENT, checks.COVERED_ID))

    def test_a_pull_makes_an_approved_document_a_draft_and_what_was_built_from_it_stale(self):
        self.assertEqual((self.state()['document'], self.state()['deck']),
                         ('approved', 'approved'))
        self.drive.edit('doc1', 'one batch at a time', 'a few at a time')
        result = gdocs.pull(self.root, 'document', self.drive)
        self.assertEqual(self.state()['document'], 'draft')
        self.assertEqual(self.state()['deck'], 'stale')
        self.assertEqual(self.state()['brief'], 'approved')
        self.assertEqual((result['status'], result['stale']), ('draft', ['deck']))

    def test_a_pull_keeps_the_version_it_replaced_in_history(self):
        self.drive.edit('doc1', 'one batch at a time', 'a few at a time')
        gdocs.pull(self.root, 'document', self.drive)
        self.assertEqual(self.history(), sorted([DOCUMENT, self.file().read_text('utf-8')]))
        events = workspace.load(self.root)['events']
        self.assertEqual((events[-1]['event'], events[-1]['artifact']), ('save', 'document'))

    def test_after_a_pull_the_two_sides_are_in_sync_and_the_next_pull_does_nothing(self):
        self.drive.edit('doc1', 'one batch at a time', 'a few at a time')
        gdocs.pull(self.root, 'document', self.drive)
        entry = self.linked()
        self.assertEqual(entry['local_sha256'], workspace.sha256_file(self.file()))
        self.assertEqual(entry['remote_sha256'], gdocs.digest(self.drive.export('doc1')))
        self.assertEqual(entry['anchors'], ANCHORS)
        self.assertEqual(gdocs.status(self.root, self.drive)['docs']['document']['state'],
                         'in sync')
        pulled = self.file().read_bytes()
        self.assertEqual(gdocs.pull(self.root, 'document', self.drive)['result'], 'nothing to do')
        self.assertEqual(self.file().read_bytes(), pulled)

    def test_a_second_round_of_remote_edits_keeps_the_comments_too(self):
        self.drive.edit('doc1', 'one batch at a time', 'a few at a time')
        gdocs.pull(self.root, 'document', self.drive)
        self.drive.edit('doc1', 'a few at a time', 'in small batches')
        self.assertEqual(gdocs.pull(self.root, 'document', self.drive)['unplaced'], [])
        text = self.file().read_text('utf-8')
        self.assertIn('in small batches', text)
        self.assertEqual(checks.COVERS.findall(text), checks.COVERS.findall(DOCUMENT))

    def test_a_pull_does_nothing_when_the_doc_has_not_changed(self):
        result = gdocs.pull(self.root, 'document', self.drive)
        self.assertEqual((result['result'], result['state']), ('nothing to do', 'in sync'))
        self.assertEqual(self.file().read_text('utf-8'), DOCUMENT)
        self.assertEqual(self.state()['document'], 'approved')
        self.assertEqual(self.history(), [DOCUMENT])

    def test_a_pull_does_nothing_when_only_the_local_file_changed(self):
        self.write('document.md', DOCUMENT + '\nA local addition.\n')
        result = gdocs.pull(self.root, 'document', self.drive)
        self.assertEqual((result['result'], result['state']), ('nothing to do', 'local changed'))
        self.assertTrue(self.file().read_text('utf-8').endswith('A local addition.\n'))

    def test_a_pull_is_refused_when_both_sides_changed_and_the_doc_is_put_beside_the_file(self):
        local = DOCUMENT + '\nA local addition.\n'
        self.write('document.md', local)
        self.drive.edit('doc1', 'one batch at a time', 'a few at a time')
        before = self.record()
        with self.refused(r'both changed.*document\.remote\.md'):
            gdocs.pull(self.root, 'document', self.drive)
        self.assertEqual(self.file().read_text('utf-8'), local)
        beside = self.file('document.remote.md').read_text('utf-8')
        self.assertIn('a few at a time', beside)
        self.assertNotIn('A local addition.', beside)
        self.assertEqual(checks.COVERS.findall(beside), checks.COVERS.findall(DOCUMENT))
        self.assertEqual(self.record(), before)
        self.assertEqual(self.history(), [DOCUMENT])
        self.assertEqual(gdocs.status(self.root, self.drive)['docs']['document']['state'],
                         'both changed')

    def test_a_conflict_is_settled_by_reconciling_and_pushing_with_force(self):
        self.write('document.md', DOCUMENT + '\nA local addition.\n')
        self.drive.edit('doc1', 'one batch at a time', 'a few at a time')
        with self.refused('both changed'):
            gdocs.pull(self.root, 'document', self.drive)
        merged = self.file('document.remote.md').read_text('utf-8') + '\nA local addition.\n'
        self.write('document.md', merged)
        with self.refused('Pull first'):
            gdocs.push(self.root, 'document', self.drive)
        gdocs.push(self.root, 'document', self.drive, force=True)
        self.assertIn('A local addition.', self.drive.docs['doc1'])
        self.assertIn('a few at a time', self.drive.docs['doc1'])
        self.assertEqual(gdocs.status(self.root, self.drive)['docs']['document']['state'],
                         'in sync')

    def test_a_heading_removed_in_the_doc_is_reported_and_the_pull_still_completes(self):
        self.drive.edit('doc1', '## When capacity holds', '## Keeping capacity')
        result = gdocs.pull(self.root, 'document', self.drive)
        self.assertEqual(result['result'], 'pulled')
        self.assertEqual(result['unplaced'],
                         [{'heading': 'When capacity holds', 'comment': COMMENTS[2]}])
        text = self.file().read_text('utf-8')
        self.assertIn('## Keeping capacity', text)
        self.assertEqual(checks.COVERS.findall(text), ['O3', 'O1 K1.1 K1.3'])
        self.assertEqual(self.linked()['anchors'], ANCHORS[:2])

    def test_a_heading_renumbered_or_respaced_in_the_doc_still_takes_its_comment(self):
        self.drive.edit('doc1', '## What a rolling restart does',
                        '##   2. What a rolling restart does')
        self.assertEqual(gdocs.pull(self.root, 'document', self.drive)['unplaced'], [])
        self.assertIn(f'##   2. What a rolling restart does\n\n{COMMENTS[1]}\n\n',
                      self.file().read_text('utf-8'))

    def test_an_empty_export_never_replaces_the_file(self):
        empty = self.root.parent / 'empty.md'
        empty.write_text(' \n\n', 'utf-8')
        with self.refused('empty'):
            gdocs.pull(self.root, 'document', source=empty)
        self.assertEqual(self.file().read_text('utf-8'), DOCUMENT)

    def test_a_pull_needs_a_link(self):
        with self.refused('brief is not linked to a Google Doc'):
            gdocs.pull(self.root, 'brief', self.drive)
        with self.refused('only the document and the brief'):
            gdocs.pull(self.root, 'deck', self.drive)

    def test_a_pull_into_a_stale_document_leaves_it_stale(self):
        self.write('blueprint.md', example('blueprint.md') + '\nA late change.\n')
        self.assertEqual(self.state()['document'], 'stale')
        self.drive.edit('doc1', 'one batch at a time', 'a few at a time')
        result = gdocs.pull(self.root, 'document', self.drive)
        self.assertIn('a few at a time', self.file().read_text('utf-8'))
        self.assertEqual((result['status'], self.state()['document']), ('stale', 'stale'))

    def test_the_brief_pulls_the_same_way(self):
        gdocs.push(self.root, 'brief', self.drive)
        self.drive.edit('doc2', 'in batches rather than all at once', 'a few at a time')
        result = gdocs.pull(self.root, 'brief', self.drive)
        text = self.file('product-brief.md').read_text('utf-8')
        self.assertEqual((result['status'], result['unplaced']), ('draft', []))
        self.assertIn('a few at a time', text)
        self.assertEqual(checks.FINDINGS_COMMENT.findall(text),
                         checks.FINDINGS_COMMENT.findall(BRIEF))
        self.assertEqual(self.state()['document'], 'approved')


class LevelTests(SyncCase):
    levels = ('101', '301')

    def test_a_level_form_round_trips_in_its_own_folder(self):
        result = gdocs.push(self.root, 'document@101', self.drive)
        self.assertEqual(result['title'], 'Rolling restarts: learner guide (101)')
        self.assertEqual(list(self.record()['docs']), ['document@101'])
        self.drive.edit('doc1', 'one batch at a time', 'a few at a time')
        result = gdocs.pull(self.root, 'document@101', self.drive)
        self.assertEqual((result['status'], result['stale']), ('draft', ['deck@101']))
        self.assertIn('a few at a time', (self.root / '101' / 'document.md').read_text('utf-8'))
        self.assertEqual(len(self.history('document-101')), 2)

    def test_a_conflict_file_sits_in_the_level_folder(self):
        gdocs.push(self.root, 'brief@101', self.drive)
        self.write('101/product-brief.md', BRIEF + '\nLocal.\n')
        self.drive.edit('doc1', 'in batches rather than all at once', 'a few at a time')
        with self.refused(r'101/product-brief\.remote\.md'):
            gdocs.pull(self.root, 'brief@101', self.drive)
        self.assertTrue((self.root / '101' / 'product-brief.remote.md').is_file())

    def test_a_levelled_training_needs_the_level_named(self):
        with self.refused('name the level'):
            gdocs.push(self.root, 'document', self.drive)
        self.assertEqual(self.drive.calls, [])


class StatusTests(SyncCase):
    def state_of(self, transport=None, name='document') -> str:
        return gdocs.status(self.root, transport)['docs'][name]['state']

    def test_nothing_linked_is_an_empty_report_and_asks_google_nothing(self):
        self.assertEqual(gdocs.status(self.root, self.drive), {'docs': {}, 'offline': False})
        self.assertEqual(self.drive.calls, [])

    def test_each_of_the_four_states(self):
        gdocs.push(self.root, 'document', self.drive)
        gdocs.push(self.root, 'brief', self.drive)
        self.assertEqual(self.state_of(self.drive), 'in sync')
        self.write('document.md', DOCUMENT + '\nLocal.\n')
        self.assertEqual(self.state_of(self.drive), 'local changed')
        self.drive.edit('doc1', 'one batch at a time', 'a few at a time')
        self.assertEqual(self.state_of(self.drive), 'both changed')
        self.write('document.md', DOCUMENT)
        self.assertEqual(self.state_of(self.drive), 'remote changed')
        self.assertEqual(self.state_of(self.drive, 'brief'), 'in sync')

    def test_a_report_names_the_doc(self):
        gdocs.push(self.root, 'document', self.drive)
        report = gdocs.status(self.root, self.drive)['docs']['document']
        self.assertEqual((report['file'], report['url'], report['title']),
                         ('document.md', 'https://docs.example.com/d/doc1/edit',
                          'Rolling restarts: learner guide'))

    def test_offline_reports_the_local_side_only(self):
        gdocs.push(self.root, 'document', self.drive)
        self.drive.edit('doc1', 'one batch at a time', 'a few at a time')
        asked = len(self.drive.calls)
        report = gdocs.status(self.root)
        self.assertTrue(report['offline'])
        self.assertEqual(report['docs']['document']['state'], 'local unchanged')
        self.write('document.md', DOCUMENT + '\nLocal.\n')
        self.assertEqual(self.state_of(), 'local changed')
        self.assertEqual(len(self.drive.calls), asked)

    def test_a_link_to_an_artifact_the_training_no_longer_has_is_reported_not_fatal(self):
        gdocs.push(self.root, 'document', self.drive)
        record = self.record()
        record['docs']['document@301'] = dict(record['docs']['document'])
        (self.root / '.training-studio' / 'google.json').write_text(json.dumps(record), 'utf-8')
        report = gdocs.status(self.root, self.drive)['docs']
        self.assertEqual(report['document']['state'], 'in sync')
        self.assertEqual(report['document@301']['state'], 'unavailable')
        self.assertIn('no levels', report['document@301']['problem'])


class UnlinkTests(SyncCase):
    def test_unlink_forgets_the_link_and_leaves_the_doc(self):
        gdocs.push(self.root, 'document', self.drive)
        gdocs.push(self.root, 'brief', self.drive)
        asked = list(self.drive.calls)
        result = gdocs.unlink(self.root, 'document')
        self.assertEqual(result['url'], 'https://docs.example.com/d/doc1/edit')
        self.assertEqual(list(self.record()['docs']), ['brief'])
        self.assertEqual(self.drive.calls, asked)
        self.assertIn('doc1', self.drive.docs)
        with self.refused('not linked'):
            gdocs.pull(self.root, 'document', self.drive)
        with self.refused('not linked'):
            gdocs.unlink(self.root, 'document')

    def test_a_push_after_unlinking_makes_a_new_doc(self):
        gdocs.push(self.root, 'document', self.drive)
        gdocs.unlink(self.root, 'document')
        self.assertEqual(gdocs.push(self.root, 'document', self.drive)['result'], 'created')
        self.assertEqual(self.linked()['file_id'], 'doc2')


class ConnectorTests(SyncCase):
    """The assistant's own connector does the transfer; the helper keeps the books."""

    def setUp(self):
        super().setUp()
        self.scratch = self.root.parent / 'scratch'
        self.scratch.mkdir()

    def export(self, text: str, name: str = 'export.md') -> Path:
        path = self.scratch / name
        path.write_text(text, encoding='utf-8')
        return path

    def pushed(self, name: str = 'document') -> str:
        """Prepare, send through the connector, and record. Returns what was sent."""
        out = self.scratch / 'send.md'
        gdocs.prepare(self.root, name, out)
        sent = out.read_text('utf-8')
        gdocs.record(self.root, name, 'abc_123-XYZ', 'https://docs.example.com/d/abc/edit',
                     self.export(google_style(sent)))
        return sent

    def test_prepare_writes_the_text_to_send_and_records_nothing(self):
        out = self.scratch / 'send.md'
        result = gdocs.prepare(self.root, 'document', out)
        self.assertEqual(out.read_text('utf-8'), gdocs.strip_comments(DOCUMENT)[0])
        self.assertNotIn('<!--', out.read_text('utf-8'))
        self.assertFalse((self.root / '.training-studio' / 'google.json').exists())
        self.assertEqual((result['linked'], result['comments_held'], result['title']),
                         (False, 3, 'Rolling restarts: learner guide'))
        self.assertEqual(self.state()['document'], 'approved')

    def test_prepare_says_which_doc_is_already_linked(self):
        self.pushed()
        result = gdocs.prepare(self.root, 'document', self.scratch / 'again.md')
        self.assertEqual((result['linked'], result['file_id']), (True, 'abc_123-XYZ'))
        with self.refused('already linked'):
            gdocs.prepare(self.root, 'document', self.scratch / 'again.md', title='New name')

    def test_a_title_given_at_prepare_can_be_recorded(self):
        out = self.scratch / 'send.md'
        self.assertEqual(gdocs.prepare(self.root, 'brief', out, title='Brief for review')['title'],
                         'Brief for review')
        export = self.export(google_style(out.read_text('utf-8')))
        url = 'https://docs.example.com/d/abc/edit'
        gdocs.record(self.root, 'brief', 'abc', url, export, title='Brief for review')
        self.assertEqual(self.linked('brief')['title'], 'Brief for review')
        gdocs.record(self.root, 'brief', 'abc', url, export)
        self.assertEqual(self.linked('brief')['title'], 'Brief for review')
        gdocs.record(self.root, 'brief', 'another', url, export)
        self.assertEqual(self.linked('brief')['title'], 'Rolling restarts: product brief')

    def test_prepare_will_not_write_inside_the_training(self):
        for inside in ('document.md', 'scratch/send.md', '.training-studio/send.md'):
            with self.subTest(inside), self.refused('outside the training directory'):
                gdocs.prepare(self.root, 'document', self.root / inside)
        self.assertEqual(self.file().read_text('utf-8'), DOCUMENT)

    def test_record_notes_a_push_the_connector_made(self):
        self.pushed()
        entry = self.linked()
        self.assertEqual((entry['file_id'], entry['url']),
                         ('abc_123-XYZ', 'https://docs.example.com/d/abc/edit'))
        self.assertEqual(entry['anchors'], ANCHORS)
        self.assertEqual(entry['local_sha256'], workspace.sha256_file(self.file()))
        self.assertEqual(gdocs.status(self.root)['docs']['document']['state'], 'local unchanged')
        self.assertEqual(self.state()['document'], 'approved')

    def test_an_unchanged_export_pulls_nothing(self):
        sent = self.pushed()
        result = gdocs.pull(self.root, 'document', source=self.export(google_style(sent)))
        self.assertEqual((result['result'], result['state']), ('nothing to do', 'in sync'))
        self.assertEqual(self.file().read_text('utf-8'), DOCUMENT)

    def test_a_changed_export_is_pulled_under_the_same_rules(self):
        sent = self.pushed()
        edited = google_style(sent.replace('one batch at a time', 'a few at a time'))
        result = gdocs.pull(self.root, 'document', source=self.export(edited))
        self.assertEqual((result['result'], result['status'], result['stale'], result['unplaced']),
                         ('pulled', 'draft', ['deck'], []))
        text = self.file().read_text('utf-8')
        self.assertIn('a few at a time', text)
        self.assertEqual(checks.COVERS.findall(text), checks.COVERS.findall(DOCUMENT))
        again = gdocs.pull(self.root, 'document', source=self.export(edited))
        self.assertEqual(again['result'], 'nothing to do')

    def test_a_changed_export_conflicts_with_a_local_change(self):
        sent = self.pushed()
        self.write('document.md', DOCUMENT + '\nLocal.\n')
        edited = google_style(sent.replace('one batch at a time', 'a few at a time'))
        with self.refused('both changed'):
            gdocs.pull(self.root, 'document', source=self.export(edited))
        self.assertIn('a few at a time', self.file('document.remote.md').read_text('utf-8'))

    def test_record_refuses_what_it_cannot_trust(self):
        good = self.export(google_style(DOCUMENT))
        url = 'https://docs.example.com/d/abc/edit'
        cases = (('abc/../def', url, good, 'file ID'),
                 ('abc', 'http://docs.example.com/d/abc', good, 'https'),
                 ('abc', url, self.scratch / 'missing.md', 'does not exist'),
                 ('abc', url, self.export('', 'empty.md'), 'empty'))
        for file_id, link, path, pattern in cases:
            with self.subTest(pattern), self.refused(pattern):
                gdocs.record(self.root, 'document', file_id, link, path)
        with self.refused('only the document and the brief'):
            gdocs.record(self.root, 'deck', 'abc', url, self.export(google_style(DOCUMENT)))
        self.assertFalse((self.root / '.training-studio' / 'google.json').exists())


# --- the command line -----------------------------------------------------------------

class CommandCase(SyncCase):
    def cli(self, *args, expect=0) -> dict:
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            try:
                code = training.main(['--dir', str(self.root), *args])
            except SystemExit as stopped:
                code = stopped.code
        self.assertEqual(code, expect, captured.getvalue())
        return json.loads(captured.getvalue())

    def through_gcloud(self, transport):
        """Make the commands use `transport` where they would build a GcloudTransport."""
        patcher = mock.patch.object(gdocs, 'GcloudTransport', lambda: transport)
        patcher.start()
        self.addCleanup(patcher.stop)


class CommandTests(CommandCase):
    def test_the_connector_path_from_prepare_to_pull(self):
        scratch = self.root.parent
        send, export = scratch / 'send.md', scratch / 'export.md'
        prepared = self.cli('google', 'push', 'document', '--prepare', str(send))
        self.assertEqual((prepared['linked'], prepared['comments_held']), (False, 3))
        self.assertNotIn('<!--', send.read_text('utf-8'))
        self.assertEqual(self.cli('google', 'status', '--offline'), {'docs': {}, 'offline': True})

        export.write_text(google_style(send.read_text('utf-8')), 'utf-8')
        recorded = self.cli('google', 'record', 'document', '--file-id', 'abc123', '--url',
                            'https://docs.example.com/d/abc123/edit', '--export', str(export))
        self.assertEqual((recorded['result'], recorded['state']), ('recorded', 'in sync'))
        offline = self.cli('google', 'status', '--offline')
        self.assertEqual(offline['docs']['document']['state'], 'local unchanged')

        edited = (send.read_text('utf-8').replace('one batch at a time', 'a few at a time')
                  .replace('## When capacity holds', '## Capacity'))
        export.write_text(google_style(edited), 'utf-8')
        pulled = self.cli('google', 'pull', 'document', '--from', str(export))
        self.assertEqual((pulled['result'], pulled['status'], pulled['stale']),
                         ('pulled', 'draft', ['deck']))
        self.assertEqual(pulled['unplaced'],
                         [{'heading': 'When capacity holds', 'comment': COMMENTS[2]}])
        status = self.cli('status')
        self.assertEqual((status['artifacts']['document'], status['artifacts']['deck']),
                         ('draft', 'stale'))
        text = self.file().read_text('utf-8')
        self.assertIn('a few at a time', text)
        self.assertEqual(checks.COVERS.findall(text), ['O3', 'O1 K1.1 K1.3'])

    def test_a_conflict_is_a_refusal_with_exit_code_2(self):
        export = self.root.parent / 'export.md'
        export.write_text(google_style(gdocs.strip_comments(DOCUMENT)[0]), 'utf-8')
        self.cli('google', 'record', 'document', '--file-id', 'abc123', '--url',
                 'https://docs.example.com/d/abc123/edit', '--export', str(export))
        self.write('document.md', DOCUMENT + '\nLocal.\n')
        export.write_text(export.read_text('utf-8').replace('one batch', 'one small batch'),
                          'utf-8')
        refusal = self.cli('google', 'pull', 'document', '--from', str(export), expect=2)
        self.assertEqual(list(refusal), ['error'])
        self.assertIn('document.remote.md', refusal['error'])
        self.assertIn('one small batch', self.file('document.remote.md').read_text('utf-8'))

    def test_push_pull_status_and_unlink_through_gcloud(self):
        self.through_gcloud(self.drive)
        pushed = self.cli('google', 'push', 'document', '--title', 'Restarts for review')
        self.assertEqual((pushed['result'], pushed['title']), ('created', 'Restarts for review'))
        self.assertEqual(self.cli('google', 'status')['docs']['document']['state'], 'in sync')
        self.drive.edit('doc1', 'one batch at a time', 'a few at a time')
        self.assertEqual(self.cli('google', 'status')['docs']['document']['state'],
                         'remote changed')
        self.write('document.md', DOCUMENT + '\nLocal.\n')
        refusal = self.cli('google', 'push', 'document', expect=2)
        self.assertEqual(refusal,
                         {'error': 'The Google Doc changed since the last sync. Pull first.'})
        self.assertEqual(self.cli('google', 'push', 'document', '--force')['result'], 'updated')
        self.assertEqual(self.cli('google', 'pull', 'document')['result'], 'nothing to do')
        self.assertTrue(self.cli('google', 'unlink', 'document')['unlinked'])
        self.assertEqual(self.cli('google', 'status'), {'docs': {}, 'offline': False})
        self.assertIn('doc1', self.drive.docs)

    def test_refusals_and_usage_errors_are_json_with_exit_code_2(self):
        self.through_gcloud(self.drive)
        self.assertIn('only the document and the brief',
                      self.cli('google', 'push', 'blueprint', expect=2)['error'])
        self.assertIn('not linked', self.cli('google', 'pull', 'brief', expect=2)['error'])
        self.assertIn('not linked', self.cli('google', 'unlink', 'brief', expect=2)['error'])
        self.assertIn('error', self.cli('google', expect=2))
        self.assertIn('invalid choice', self.cli('google', 'share', expect=2)['error'])
        self.assertIn('--file-id', self.cli('google', 'record', 'document', expect=2)['error'])
        self.assertIn('not allowed with', self.cli('google', 'push', 'document', '--force',
                                                   '--prepare', 'x.md', expect=2)['error'])
        self.assertEqual(self.drive.calls, [])


class ContractTests(TrainingCase):
    """The plug-in in a real process, the way an assistant runs it."""

    def run_cli(self, *args, expect=0):
        done = subprocess.run([sys.executable, str(CLI), *args], cwd=self.root,
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, expect, done.stdout + done.stderr)
        return json.loads(done.stdout)

    def test_the_google_commands_are_found_without_editing_the_helper(self):
        self.assertEqual(self.run_cli('google', 'status', '--offline', expect=2),
                         {'error': 'No training in this directory. Run init first.'})
        self.run_cli('init', '--title', 'Topic')
        self.assertEqual(self.run_cli('google', 'status', '--offline'),
                         {'docs': {}, 'offline': True})
        self.assertEqual(self.run_cli('google', 'status'), {'docs': {}, 'offline': False})
        self.assertIn('document.md does not exist',
                      self.run_cli('google', 'push', 'document', '--prepare',
                                   str(self.root.parent / 'send.md'), expect=2)['error'])


# --- the gcloud transport, against a stubbed token command and HTTP layer ------------------

class Reply:
    def __init__(self, body: bytes):
        self.body = body

    def read(self) -> bytes:
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class StubDrive:
    """Stands in for urlopen: records every request and answers the way Drive v3 does."""

    def __init__(self):
        self.requests = []
        self.content = ''
        self.failure = None

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        self.timeout = timeout
        if self.failure is not None:
            raise self.failure
        if '/export' in request.full_url:
            return Reply(google_style(self.content).encode('utf-8'))
        if request.get_method() == 'POST':
            boundary = request.get_header('Content-type').partition('boundary=')[2]
            parts = request.data.decode('utf-8').split(f'--{boundary}')
            self.content = parts[2].partition('\r\n\r\n')[2].removesuffix('\r\n')
            return Reply(json.dumps({'id': 'abc123', 'webViewLink':
                                     'https://docs.example.com/d/abc123/edit'}).encode())
        self.content = request.data.decode('utf-8')
        return Reply(b'{"id": "abc123"}')


class StubGcloud:
    """Stands in for running the gcloud command."""

    def __init__(self, token=TOKEN, code=0, missing=False):
        self.token, self.code, self.missing = token, code, missing
        self.commands = []

    def __call__(self, command, **options):
        self.commands.append(command)
        if self.missing:
            raise FileNotFoundError(2, 'No such file or directory', 'gcloud')
        return subprocess.CompletedProcess(command, self.code, stdout=f'{self.token}\n',
                                           stderr=f'ERROR: something about {self.token}\n')


def http_error(code: int, message: str, reason: str = 'Refused') -> urllib.error.HTTPError:
    body = json.dumps({'error': {'code': code, 'message': message}}).encode()
    return urllib.error.HTTPError('https://www.googleapis.com/drive/v3/files', code, reason,
                                  {}, io.BytesIO(body))


class GcloudTransportTests(unittest.TestCase):
    def setUp(self):
        self.drive, self.gcloud = StubDrive(), StubGcloud()
        self.transport = gdocs.GcloudTransport(run=self.gcloud, urlopen=self.drive)

    def refused(self, pattern: str):
        return self.assertRaisesRegex(WorkspaceError, pattern)

    def test_a_transport_built_the_ordinary_way_cannot_get_out_of_these_tests(self):
        with self.assertRaisesRegex(AssertionError, 'gcloud'):
            gdocs.GcloudTransport().export('abc123')
        with self.assertRaisesRegex(AssertionError, 'network'):
            gdocs.GcloudTransport(run=self.gcloud).export('abc123')

    def test_create_uploads_markdown_for_drive_to_convert_into_a_doc(self):
        made = self.transport.create('Rolling restarts: learner guide', '# Title\n\nCafé.\n')
        request = self.drive.requests[0]
        self.assertEqual(request.get_method(), 'POST')
        self.assertTrue(request.full_url.startswith(
            'https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart'))
        kind = request.get_header('Content-type')
        self.assertTrue(kind.startswith('multipart/related; boundary='), kind)
        metadata, media = request.data.decode('utf-8').split(
            '--' + kind.partition('boundary=')[2])[1:3]
        self.assertIn('Content-Type: application/json', metadata)
        self.assertEqual(json.loads(metadata.partition('\r\n\r\n')[2]),
                         {'name': 'Rolling restarts: learner guide',
                          'mimeType': 'application/vnd.google-apps.document'})
        self.assertIn('Content-Type: text/markdown', media)
        self.assertEqual(media.partition('\r\n\r\n')[2], '# Title\n\nCafé.\n\r\n')
        self.assertEqual(made, {'file_id': 'abc123',
                                'url': 'https://docs.example.com/d/abc123/edit'})

    def test_update_uploads_markdown_to_the_existing_file(self):
        self.transport.update('abc123', '# Title\n\nNew.\n')
        request = self.drive.requests[0]
        self.assertEqual(request.get_method(), 'PATCH')
        self.assertEqual(request.full_url, 'https://www.googleapis.com/upload/drive/v3/files/'
                                           'abc123?uploadType=media')
        self.assertTrue(request.get_header('Content-type').startswith('text/markdown'))
        self.assertEqual(request.data, b'# Title\n\nNew.\n')

    def test_export_asks_for_markdown(self):
        self.drive.content = '# Title\n\n- Café.\n'
        self.assertEqual(self.transport.export('abc123'), '\ufeff# Title\r\n\r\n* Café.\r\n')
        request = self.drive.requests[0]
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(request.full_url, 'https://www.googleapis.com/drive/v3/files/abc123/'
                                           'export?mimeType=text%2Fmarkdown')
        self.assertIsNone(request.data)

    def test_every_request_carries_the_token_from_gcloud_and_a_timeout(self):
        self.transport.create('T', 'x')
        self.transport.export('abc123')
        self.assertEqual(self.gcloud.commands, [['gcloud', 'auth', 'print-access-token']])
        for request in self.drive.requests:
            self.assertEqual(request.get_header('Authorization'), f'Bearer {TOKEN}')
        self.assertGreater(self.drive.timeout, 0)

    def test_it_can_only_create_replace_and_export(self):
        public = [name for name in dir(gdocs.GcloudTransport) if not name.startswith('_')]
        self.assertEqual(public, ['create', 'export', 'update'])
        self.transport.create('T', 'x')
        self.transport.update('abc123', 'y')
        self.transport.export('abc123')
        self.assertEqual([request.get_method() for request in self.drive.requests],
                         ['POST', 'PATCH', 'GET'])
        for request in self.drive.requests:
            self.assertNotIn('permission', request.full_url)

    def test_a_missing_gcloud_says_what_to_install_and_run(self):
        transport = gdocs.GcloudTransport(run=StubGcloud(missing=True), urlopen=self.drive)
        with self.refused(r'gcloud command was not found.*gcloud auth login '
                          r'--enable-gdrive-access'):
            transport.export('abc123')
        self.assertEqual(self.drive.requests, [])

    def test_a_gcloud_that_is_not_signed_in_says_what_to_run(self):
        for stub in (StubGcloud(code=1), StubGcloud(token='')):
            transport = gdocs.GcloudTransport(run=stub, urlopen=self.drive)
            with self.refused('gcloud auth login --enable-gdrive-access') as caught:
                transport.create('T', 'x')
            self.assertNotIn(TOKEN, str(caught.exception))
        self.assertEqual(self.drive.requests, [])

    def test_a_missing_drive_scope_says_what_to_run(self):
        self.drive.failure = http_error(403, 'Request had insufficient authentication scopes.')
        with self.refused(r'does not include Google Drive.*gcloud auth login '
                          r'--enable-gdrive-access'):
            self.transport.export('abc123')

    def test_a_rejected_sign_in_says_what_to_run(self):
        self.drive.failure = http_error(401, 'Invalid Credentials')
        with self.refused('gcloud auth login --enable-gdrive-access'):
            self.transport.update('abc123', 'x')

    def test_a_doc_that_is_gone_says_to_unlink(self):
        self.drive.failure = http_error(404, 'File not found: abc123.')
        with self.refused('google unlink'):
            self.transport.export('abc123')

    def test_any_other_http_error_is_a_refusal_with_googles_reason(self):
        self.drive.failure = http_error(403, 'The user does not have sufficient permissions.')
        with self.refused(r'HTTP 403.*does not have sufficient permissions'):
            self.transport.update('abc123', 'x')
        self.drive.failure = urllib.error.HTTPError('https://x', 503, 'Unavailable', {},
                                                    io.BytesIO(b'<html>not json</html>'))
        with self.refused('HTTP 503'):
            self.transport.export('abc123')

    def test_no_network_is_a_refusal(self):
        self.drive.failure = urllib.error.URLError('Name or service not known')
        with self.refused('Could not reach Google'):
            self.transport.export('abc123')
        self.drive.failure = TimeoutError('timed out')
        with self.refused('Could not reach Google'):
            self.transport.export('abc123')

    def test_the_token_never_appears_in_a_refusal(self):
        failures = (http_error(403, f'Bad token {TOKEN} for this request'),
                    http_error(400, 'Bad request', reason=f'Bearer {TOKEN}'),
                    urllib.error.HTTPError('https://x', 500, f'Bearer {TOKEN}', {},
                                           io.BytesIO(f'oops {TOKEN}'.encode())),
                    urllib.error.URLError(f'proxy rejected Bearer {TOKEN}'))
        for failure in failures:
            self.drive.failure = failure
            with self.subTest(str(failure.reason)[:20]), \
                    self.assertRaises(WorkspaceError) as caught:
                self.transport.export('abc123')
            self.assertNotIn(TOKEN, str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)
            self.assertTrue(caught.exception.__suppress_context__)

    def test_an_odd_file_id_cannot_change_the_address(self):
        self.transport.update('abc/../../about?x=1', 'x')
        self.assertEqual(self.drive.requests[0].full_url,
                         'https://www.googleapis.com/upload/drive/v3/files/'
                         'abc%2F..%2F..%2Fabout%3Fx%3D1?uploadType=media')


class TokenTests(CommandCase):
    """An access token is used in memory and goes nowhere else."""

    def everything_written(self) -> bytes:
        folders = (self.root.parent, Path(os.environ['TRAINING_STUDIO_DATA']))
        return b'\n'.join(path.read_bytes() for folder in folders
                          for path in sorted(folder.rglob('*')) if path.is_file())

    def test_the_token_is_never_written_or_printed(self):
        drive, gcloud = StubDrive(), StubGcloud()
        made = functools.partial(gdocs.GcloudTransport, run=gcloud, urlopen=drive)
        printed, errors = io.StringIO(), io.StringIO()

        def cli(*args) -> int:
            with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(errors):
                return training.main(['--dir', str(self.root), *args])

        with mock.patch.object(gdocs, 'GcloudTransport', made):
            self.assertEqual(cli('google', 'push', 'document'), 0)
            self.assertEqual(cli('google', 'status'), 0)
            drive.content = drive.content.replace('one batch at a time', 'a few at a time')
            self.assertEqual(cli('google', 'pull', 'document'), 0)
            self.assertEqual(cli('google', 'push', 'brief'), 0)
            drive.failure = http_error(403, f'No access with {TOKEN}')
            self.assertEqual(cli('google', 'push', 'document', '--force'), 2)
            self.assertEqual(cli('google', 'status'), 2)
            drive.failure = urllib.error.URLError(f'Bearer {TOKEN} refused')
            self.assertEqual(cli('google', 'pull', 'document'), 2)
            self.assertEqual(cli('status'), 0)

        self.assertGreaterEqual(len(gcloud.commands), 7)
        self.assertGreaterEqual(len(drive.requests), 9)
        self.assertIn('a few at a time', self.file().read_text('utf-8'))
        self.assertIn('"error"', printed.getvalue())
        self.assertNotIn(TOKEN, printed.getvalue())
        self.assertNotIn(TOKEN, errors.getvalue())
        written = self.everything_written()
        self.assertIn(b'"file_id": "abc123"', written)
        self.assertNotIn(TOKEN.encode(), written)
        self.assertNotIn(b'Bearer', written)


if __name__ == '__main__':
    unittest.main()
