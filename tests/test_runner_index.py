"""The index: readiness in sentences for a person, and README.md written from the record.

Every training here is made with the core itself and the example files. Nothing reaches
Google or runs a converter, and no model writes a word of the index.
"""
import json
import re
import subprocess
import unittest
import urllib.parse
import urllib.request
from unittest import mock

import helpers
import runner_support  # noqa: F401  puts the runner on the import path
from test_cli import example
from test_runner_copies import REFUSAL, Built, Refusing
import desk
import workspace
from workspace import WorkspaceError

from runner import copies, index

FORBIDDEN_WORDS = re.compile(r'\b(artifacts?|stale|lineage)\b', re.IGNORECASE)
HEADINGS = ['Objectives', 'What is here', 'Copies', 'Coverage', 'Open gaps and limitations',
            'Using the scenarios', 'Research']
READY = {'ready': True, 'blocking': [], 'limitations': [], 'file': 'README.md'}
LINK = re.compile(r'\]\(([^)]+)\)')
SUPPLIED = [{'id': 'runbook-docx', 'title': 'Runbook', 'origin': 'supplied Runbook.docx',
             'original_file': 'sources/supplied/runbook-docx.original.docx',
             'file': 'sources/supplied/runbook-docx.txt', 'limits': 'none'},
            {'id': 'notes-txt', 'title': 'Notes', 'origin': 'supplied Notes.txt',
             'original_file': 'sources/supplied/notes-txt.original.txt',
             'file': 'sources/supplied/notes-txt.txt', 'limits': 'none'}]


def setUpModule():
    """A slip in a test must fail here. It must never start a program or reach Google."""
    for owner, name in ((subprocess, 'run'), (urllib.request, 'urlopen')):
        blocked = mock.Mock(side_effect=AssertionError(f'A test tried to use {name}.'))
        patcher = mock.patch.object(owner, name, blocked)
        patcher.start()
        unittest.addModuleCleanup(patcher.stop)


class Indexed(Built):
    """A training and its index."""

    def page(self) -> str:
        return (self.root / 'README.md').read_text(encoding='utf-8')

    def section(self, heading: str | None = None) -> str:
        """One section of the index, without its heading. With no heading, what comes
        before the first."""
        parts = re.split(r'^## (.+)\n', self.page(), flags=re.MULTILINE)
        return parts[0] if heading is None else parts[parts.index(heading) + 1]

    def written(self, problems: dict | None = None) -> dict:
        """Write the index as the runner does, with the copies as they now stand."""
        return index.write(self.root, copies.wanted(self.root, problems))

    def approved_on(self, name: str) -> str:
        return workspace.load(self.root)['artifacts'][name]['approved']['at'][:10]

    def without_pandoc(self) -> tuple[list[dict], dict]:
        with mock.patch.object(copies.shutil, 'which', lambda name: None):
            return copies.make(self.root, google=self.drive)

    def research_from(self, scope: str, sources: list) -> None:
        """Say the research was run from these supplied documents, and approve it again."""
        record = {**helpers.RESEARCH, 'scope': scope, 'sources': sources}
        self.write('.harness-research/research.json', json.dumps(record))
        self.cli('approve', 'research')


# --- a finished training -------------------------------------------------------------------

class FinishedTests(Indexed):
    def setUp(self):
        super().setUp()
        self.built()
        self.report = self.written()

    def test_a_finished_training_is_ready_and_its_index_has_the_eight_sections_in_order(self):
        self.assertEqual(self.report, READY)
        self.assertEqual(re.findall(r'^## (.+)$', self.page(), re.MULTILINE), HEADINGS)
        self.assertEqual(self.section().strip().splitlines(), [
            '# Rolling restarts', '', 'This training is ready.', '',
            '- **For:** solutions engineers who deploy apps but have not had to explain '
            'restart behaviour to a customer.',
            '- **Purpose:** field enablement', '- **Topic:** Rolling restarts',
            '- **Size:** a lesson, 25 minutes'])
        self.assertTrue(self.page().endswith('is not kept._\n'))

    def test_the_objectives_are_listed_in_plain_words(self):
        self.assertEqual(self.section('Objectives').strip().splitlines(), [
            '- Describe what a rolling restart does',
            '- Explain when a rolling restart keeps capacity',
            '- Handle the objection that rolling restarts guarantee zero downtime'])

    def test_every_file_is_listed_with_its_status_and_its_review(self):
        at = self.approved_on('document')
        rows = self.section('What is here').strip().splitlines()
        self.assertEqual(rows[:2], ['| What | File | Status | Review |',
                                    '| --- | --- | --- | --- |'])
        self.assertEqual([row.split(' | ')[0] for row in rows[2:]],
                         ['| The intake summary', '| The research plan', '| The research report',
                          '| The blueprint', '| The learner guide', '| The brief',
                          '| The slide deck', '| The practice scenario'])
        self.assertIn(f'| The learner guide | [document.md](document.md) | approved on {at} | '
                      '[its review](reviews/document.md) |', rows)
        # The research report is linked where its approved copy is kept in the open.
        self.assertIn(f'| The research report | [research-report.md](research-report.md) | '
                      f'approved on {at} | [its review](reviews/research.md) |', rows)

    def test_every_link_in_the_index_leads_to_a_file_that_is_there(self):
        targets = LINK.findall(self.page())
        self.assertGreater(len(targets), 15)
        for target in targets:
            with self.subTest(target):
                self.assertTrue((self.root / urllib.parse.unquote(target)).is_file())

    def test_a_training_that_asked_for_no_copies_says_so(self):
        self.assertEqual(self.section('Copies').strip(),
                         'No Google Docs or Word files were asked for.')

    def test_coverage_has_a_row_for_each_objective_and_the_basis_of_each_column(self):
        self.assertEqual(self.section('Coverage').strip().splitlines(), [
            '| Objective | Guide (declared) | Deck (reviewed) | Practice (exercised, from the '
            'practice plan) |',
            '| --- | --- | --- | --- |',
            '| O1: Describe what a rolling restart does | yes | slide 2 | yes |',
            '| O2: Explain when a rolling restart keeps capacity | yes | slide 2 | yes |',
            '| O3: Handle the objection that rolling restarts guarantee zero downtime | yes | '
            'slide 2 | yes |',
            '',
            '- Declared: a section of the guide says it teaches the objective. Whether it '
            'does is for a reader to judge.',
            '- Reviewed: the slides recorded for the objective when the deck was read '
            'against the blueprint.',
            '- Exercised: the blueprint\'s practice plan gives the objective to a scenario '
            'that has been written.'])

    def test_open_gaps_come_from_the_blueprint_and_limitations_from_the_check(self):
        self.assertEqual(self.section('Open gaps and limitations').strip().splitlines(), [
            '### Open gaps', '',
            '- K1.4: no evidence was found for the zero-downtime claim, so the training does '
            'not teach it.',
            '- Rollback after a failed restart is not covered; the research question is '
            'still pending.',
            '', '### Limitations', '', 'None.'])

    def test_the_scenarios_are_listed_with_how_to_use_them(self):
        said = self.section('Using the scenarios')
        self.assertIn('- [scenario.md](scenario.md): The zero-downtime objection (roleplay)\n',
                      said)
        self.assertIn('Each works with any AI that can play a role', said)
        self.assertIn('Give it the brief too, [product-brief.md](product-brief.md), as its '
                      'reference for facts.', said)
        self.assertNotIn('Yoodli', self.page())

    def test_the_research_is_linked_with_when_it_was_approved_and_what_it_found(self):
        self.assertEqual(self.section('Research').strip().splitlines()[:3], [
            '- The report: [research-report.md](research-report.md)',
            f"- Approved on {self.approved_on('research')}.",
            '- Findings: 5 supported by the sources, 1 contradicted by the sources, 1 without '
            'enough evidence, 1 not researched.'])

    def test_the_index_is_derived_and_never_saved_through_the_core(self):
        record = workspace.session_path(self.root).read_bytes()
        page = self.page()
        self.assertEqual(self.written(), READY)
        self.assertEqual(self.page(), page)
        self.assertEqual(workspace.session_path(self.root).read_bytes(), record)
        self.assertNotIn('README', record.decode())
        self.assertEqual([path for path in (self.root / '.training-studio').rglob('*')
                          if 'README' in path.name], [])
        self.assertTrue(self.check('--complete')['ready'])

    def test_readiness_writes_nothing_and_is_the_report_that_writing_gives(self):
        (self.root / 'README.md').unlink()
        self.assertEqual(index.readiness(self.root), READY)
        self.assertEqual(index.readiness(self.root, copies.wanted(self.root)), READY)
        self.assertFalse((self.root / 'README.md').exists())
        self.assertEqual(index.write(self.root), READY)
        self.assertEqual(index.FILE, 'README.md')

    def test_the_index_changes_when_the_training_does(self):
        before = self.page()
        self.cli('skip', 'deck', '--reason', 'The deck is not wanted after all')
        report = self.written()
        self.assertEqual(report['limitations'], ['The deck stage was left out'])
        self.assertNotEqual(self.page(), before)
        self.assertIn('This training is ready, with 1 limitation listed under "Open gaps and '
                      'limitations".', self.section())
        self.assertIn('| The slide deck | — | left out | [its review](reviews/deck.md) |',
                      self.section('What is here'))

    def test_a_link_that_would_overwrite_another_file_is_refused(self):
        secret = self.root.parent / 'secret.txt'
        secret.write_text('Nothing to do with the training.\n')
        (self.root / 'README.md').unlink()
        (self.root / 'README.md').symlink_to(secret)
        with self.assertRaisesRegex(WorkspaceError, 'symbolic link'):
            index.write(self.root)
        self.assertEqual(secret.read_text(), 'Nothing to do with the training.\n')

    def test_a_folder_with_no_training_has_no_index(self):
        empty = self.root.parent / 'empty'
        empty.mkdir()
        for act in (index.readiness, index.write):
            with self.assertRaisesRegex(WorkspaceError, 'No training in this directory'):
                act(empty)
        self.assertEqual(list(empty.iterdir()), [])


# --- copies, and Yoodli --------------------------------------------------------------------

class CopyTests(Indexed):
    def test_only_a_copy_that_is_made_is_listed_and_each_has_its_link(self):
        self.built('google', 'word', yoodli=True)
        self.copy()
        self.assertEqual(self.written(), READY)
        self.assertEqual(self.section('Copies').strip().splitlines(), [
            '- The learner guide, as a Google Doc: [open it](https://docs.example.com/d/doc1/'
            'edit)',
            '- The learner guide, as a Word file: [document.docx](document.docx)',
            '- The brief, as a Google Doc: [open it](https://docs.example.com/d/doc2/edit)',
            '- The brief, as a Word file: [product-brief.docx](product-brief.docx)',
            '- The Yoodli scenario, as a Word file: [yoodli/main.docx](yoodli/main.docx)'])

    def test_a_word_copy_that_could_not_be_made_is_a_limitation_that_says_why(self):
        self.built('word')
        self.without_pandoc()
        report = self.written()
        self.assertEqual(report, {**READY, 'limitations': [
            f'The learner guide has no Word copy. {copies.NO_PANDOC}',
            f'The brief has no Word copy. {copies.NO_PANDOC}']})
        # The reason is the core's own record, so it is there whoever asks.
        self.assertEqual(index.readiness(self.root), report)
        self.assertIn('This training is ready, with 2 limitations listed under', self.section())
        self.assertEqual(self.section('Copies').strip(), 'A copy that is missing or out of '
                         'date is not listed here. Why is under "Open gaps and limitations".')
        self.assertIn(f'### Limitations\n\n- The learner guide has no Word copy. '
                      f'{copies.NO_PANDOC}\n- The brief has', self.page())

    def test_a_google_doc_that_was_refused_is_a_limitation_with_the_reason_it_was_given(self):
        self.built('google', 'word')
        _, problems = self.copy(google=Refusing())
        report = self.written(problems)
        self.assertEqual(report, {**READY, 'limitations': [
            f'The learner guide is not in a Google Doc. {REFUSAL}',
            f'The brief is not in a Google Doc. {REFUSAL}']})
        self.assertEqual(index.readiness(self.root)['limitations'],
                         ['The learner guide is not in a Google Doc',
                          'The brief is not in a Google Doc'])
        listed = self.section('Copies')
        self.assertIn('- The learner guide, as a Word file: [document.docx](document.docx)',
                      listed)
        self.assertNotIn('Google Doc:', listed)
        self.assertIn('A copy that is missing or out of date is not listed here.', listed)

    def test_a_copy_that_is_out_of_date_blocks_and_is_not_listed(self):
        self.built('google', 'word', without=('deck',))
        self.copy()
        self.revise()
        report = self.written()
        self.assertEqual((report['ready'], report['blocking']), (False, [
            'The Word copy of the learner guide is out of date',
            'The Google Doc of the learner guide is behind its file']))
        self.assertNotIn('learner guide', self.section('Copies'))
        self.assertIn('- The brief, as a Word file', self.section('Copies'))
        self.copy()
        self.assertEqual(self.written()['blocking'], [])
        self.assertIn('- The learner guide, as a Word file', self.section('Copies'))

    def test_with_yoodli_on_a_brief_with_no_copy_to_upload_is_said_plainly(self):
        self.built('google', yoodli=True)
        with mock.patch.object(copies.shutil, 'which', lambda name: None):
            _, problems = copies.make(self.root)
        report = self.written(problems)
        # The core's rule: the brief's copy is the file a person uploads to Yoodli.
        self.assertEqual(report, {'ready': False, 'file': 'README.md', 'blocking': [
            'The brief is not in a Google Doc, and the Yoodli scenario names it as the file to '
            f'upload. {copies.NOT_SET_UP}'], 'limitations': [
            f'The learner guide is not in a Google Doc. {copies.NOT_SET_UP}']})
        self.assertEqual(self.check('--complete', expect=1)['blocking'], [
            'brief is not in a Google Doc, and the Yoodli scenario names it as the file to '
            'upload'])
        self.assertIn('This training is not ready yet. What is still to do is listed under '
                      '"Open gaps and limitations".', self.section())
        self.assertIn('### Still to do\n\n- The brief is not in a Google Doc, and the Yoodli',
                      self.section('Open gaps and limitations'))
        self.assertIn('The Yoodli handoff is incomplete: the brief has no current copy to '
                      'upload. Until it has, you can make one yourself: copy the text of '
                      '[product-brief.md](product-brief.md) into a Word file or a Google Doc, '
                      'and upload that.', self.section('Copies'))
        self.copy()
        self.assertEqual(self.written(), READY)
        self.assertNotIn('handoff', self.page())

    def test_with_yoodli_on_a_word_copy_that_could_not_be_made_limits_the_handoff(self):
        self.built(yoodli=True)
        self.without_pandoc()
        report = self.written()
        self.assertEqual(report, {**READY, 'limitations': [
            f'The Yoodli handoff is incomplete: the brief has no Word copy. {copies.NO_PANDOC}',
            f'The Yoodli scenario has no Word copy. {copies.NO_PANDOC}']})
        self.assertIn('The Yoodli handoff is incomplete: the brief has no current copy to '
                      'upload.', self.section('Copies'))

    def test_a_brief_that_is_not_written_yet_is_not_called_a_missing_upload(self):
        self.research(yoodli=True, copies=())
        self.make('blueprint', 'blueprint.md', example('blueprint.md'))
        self.assertFalse(self.written()['ready'])
        self.assertNotIn('handoff', self.page())
        self.assertIn('No scenario has been written yet.', self.section('Using the scenarios'))

    def test_with_yoodli_on_the_index_says_how_the_yoodli_files_are_used(self):
        self.built(yoodli=True)
        self.copy()
        self.assertEqual(self.written(), READY)
        self.assertIn('| Objective | Guide (declared) | Deck (reviewed) | Practice (exercised, '
                      'from the Yoodli goals) |', self.section('Coverage'))
        self.assertIn('- Exercised: a goal in a Yoodli scenario says it assesses the '
                      'objective.', self.section('Coverage'))
        self.assertIn('| The Yoodli scenario | [yoodli/main.md](yoodli/main.md) | approved on',
                      self.section('What is here'))
        self.assertIn(
            'For Yoodli, each scenario is also laid out in Yoodli\'s own fields: '
            '[yoodli/main.md](yoodli/main.md). Building the roleplay in Yoodli\'s Builder, '
            'pasting each block into the field its heading names, is the baseline. Yoodli\'s '
            'limits are taken from its public help pages and are provisional until you '
            'confirm that a paste was accepted.', self.section('Using the scenarios'))

    def test_a_copy_kept_under_a_name_with_spaces_is_still_linked(self):
        self.built('word')
        self.copy()
        self.write('my copies/guide v2 (final).docx', 'exported')
        self.cli('export', 'document', '--file', 'my copies/guide v2 (final).docx')
        self.written()
        self.assertIn('- The learner guide, as a Word file: [my copies/guide v2 (final).docx]'
                      '(my%20copies/guide%20v2%20%28final%29.docx)', self.section('Copies'))

    def test_only_what_the_copies_say_is_made_is_listed(self):
        self.built('google', 'word')
        handed = [{'artifact': 'document', 'label': 'the learner guide', 'kind': 'google',
                   'state': 'made', 'link': 'javascript:alert(1)', 'problem': None},
                  {'artifact': 'brief', 'label': 'the brief', 'kind': 'google',
                   'state': 'out-of-date', 'link': 'https://docs.example.com/d/doc2/edit',
                   'problem': None},
                  {'artifact': 'brief', 'label': 'the brief', 'kind': 'word',
                   'state': 'not-made', 'link': None, 'problem': 'It is being made.'}]
        index.write(self.root, handed)
        self.assertEqual(self.section('Copies').strip(), 'A copy that is missing or out of '
                         'date is not listed here. Why is under "Open gaps and limitations".')
        self.assertNotIn('javascript', self.page())


# --- a stage left out ----------------------------------------------------------------------

class LeftOutTests(Indexed):
    def test_a_deck_left_out_from_the_start_is_a_limitation_and_shows_as_left_out(self):
        self.built(without=('deck',))
        self.assertEqual(self.written(), {**READY, 'limitations': ['The deck stage was left '
                                                                 'out']})
        self.assertIn('| O1: Describe what a rolling restart does | yes | left out | yes |',
                      self.section('Coverage'))
        self.assertIn('| The slide deck | — | left out |', self.section('What is here'))

    def test_a_stage_that_could_not_be_made_says_so_and_why(self):
        self.research(yoodli=False, copies=())
        self.cli('skip', 'deck', '--unavailable', '--reason', 'The slide builder is missing')
        self.level()
        self.assertEqual(self.written(), {**READY, 'limitations': [
            'The deck stage could not be made: The slide builder is missing']})
        self.assertIn('| yes | could not be made | yes |', self.section('Coverage'))
        self.assertIn('| The slide deck | — | could not be made |',
                      self.section('What is here'))

    def test_a_training_with_no_practice_says_it_has_no_scenarios(self):
        self.built(without=('scenario', 'deck'))
        self.assertEqual(self.written()['limitations'],
                         ['The deck stage was left out', 'The practice stage was left out'])
        self.assertEqual(self.section('Using the scenarios').strip(), 'The practice stage was '
                         'left out of this training, so it has no scenarios.')
        coverage = self.section('Coverage')
        self.assertIn('| Deck (reviewed) | Practice (exercised) |', coverage)
        self.assertIn('| yes | left out | left out |', coverage)
        self.assertNotIn('Exercised:', coverage)

    def test_a_training_with_no_guide_or_brief_shows_what_it_does_have(self):
        self.built(without=('document', 'brief'))
        self.assertEqual(self.written()['limitations'],
                         ['The learner guide stage was left out', 'The brief stage was left out'])
        self.assertIn('| left out | slide 2 | yes |', self.section('Coverage'))
        self.assertIn('This training has no brief, so there is no reference file to give it '
                      'with the scenario.', self.section('Using the scenarios'))
        self.assertNotIn('](document.md)', self.page())

    def test_something_accepted_as_it_was_is_a_limitation_in_the_persons_own_words(self):
        self.built(without=('deck',))
        self.write('blueprint.md', example('blueprint.md') + '\nA note added later.\n')
        self.cli('approve', 'blueprint')
        self.cli('approve', 'document', '--accept-stale', 'The note changes nothing taught')
        self.cli('approve', 'brief', '--accept-stale', 'The note changes nothing taught')
        report = self.written()
        self.assertEqual(report['limitations'][1], 'The learner guide was accepted as it was, '
                         'after what it was built from changed: The note changes nothing taught')
        self.assertTrue(report['ready'], report['blocking'])


# --- a training that is not ready ----------------------------------------------------------

class NotReadyTests(Indexed):
    def unfinished(self) -> None:
        """Research and a blueprint approved, and a guide not approved that leaves O2 out."""
        self.research(yoodli=False, copies=())
        self.make('blueprint', 'blueprint.md', example('blueprint.md'))
        self.write('document.md', example('document.md').replace('<!-- covers: O2 K1.2 -->',
                                                                 '<!-- covers: K1.2 -->'))
        self.cli('save', 'document', '--built')

    def test_what_is_blocking_is_said_in_sentences_and_the_index_never_says_ready(self):
        self.unfinished()
        report = self.written()
        self.assertEqual(report, {'ready': False, 'limitations': [], 'file': 'README.md',
                                  'blocking': [
                                      'The learner guide is not approved yet',
                                      'The brief is not started',
                                      'The slide deck is not started',
                                      'No scenario file found.',
                                      'A check failed: document.coverage. O2 is not covered '
                                      'by any section.']})
        self.assertNotIn('is ready', self.page())
        self.assertIn('This training is not ready yet.', self.section())
        self.assertEqual(self.section('Open gaps and limitations').strip().splitlines()[:7], [
            '### Still to do', '', *(f'- {reason}' for reason in report['blocking'])])
        coverage = self.section('Coverage')
        self.assertIn('| O1: Describe what a rolling restart does | yes | not made | no |',
                      coverage)
        self.assertIn('| O2: Explain when a rolling restart keeps capacity | no | not made | '
                      'no |', coverage)
        self.assertIn('| The learner guide | [document.md](document.md) | not approved yet | '
                      '— |', self.section('What is here'))
        self.assertIn('| The brief | — | not started | — |', self.section('What is here'))
        self.assertEqual(self.section('Using the scenarios').strip(),
                         'No scenario has been written yet.')

    def test_the_report_is_the_checks_own_reason_for_reason(self):
        for build in (self.unfinished, lambda: self.built('google', 'word', yoodli=True),
                      lambda: self.built('word', levels=('101', '301'), without=('deck',))):
            with self.subTest(build):
                self.setUp()
                build()
                report = index.readiness(self.root)
                checked = self.check('--complete', '--all', expect=0 if report['ready'] else 1)
                self.assertEqual(report['ready'], checked['ready'])
                for ours, theirs in ((report['blocking'], checked['blocking']),
                                     (report['limitations'], checked['limitations'])):
                    self.assertEqual(len(ours), len(theirs))
                    for said, reason in zip(ours, theirs):
                        self.assertTrue(said.startswith(desk.plainly(reason).rstrip('.')),
                                        (said, reason))

    def test_a_failed_check_says_what_it_found_and_how_much_more(self):
        self.unfinished()
        self.write('document.md', '# Rolling restarts\n\nNothing is claimed here.\n')
        blocking = index.readiness(self.root)['blocking']
        self.assertIn('A check failed: document.coverage. K1.1 is not covered by any section. '
                      'K1.2 is not covered by any section. And 4 more.', blocking)

    def test_a_file_that_is_out_of_date_is_said_in_plain_words(self):
        self.built('word')
        self.copy()
        self.write('blueprint.md', example('blueprint.md') + '\nA note added later.\n')
        self.cli('approve', 'blueprint')
        report = self.written()
        self.assertEqual(report['blocking'][:3], ['The learner guide is out of date',
                                                  'The brief is out of date',
                                                  'The slide deck is out of date'])
        self.assertIn('| The learner guide | [document.md](document.md) | out of date |',
                      self.section('What is here'))
        self.assertIn('| yes | not reviewed | yes |', self.section('Coverage'))
        for said in (self.page(), *report['blocking'], *report['limitations']):
            self.assertIsNone(FORBIDDEN_WORDS.search(said), said)

    def test_no_index_says_the_words_a_person_is_never_shown(self):
        for build in (lambda: self.built('google', 'word', yoodli=True, levels=('101', '301')),
                      lambda: self.built(without=('deck', 'scenario')), self.unfinished):
            with self.subTest(build):
                self.setUp()
                build()
                self.without_pandoc()
                report = self.written()
                for said in (self.page(), *report['blocking'], *report['limitations']):
                    self.assertIsNone(FORBIDDEN_WORDS.search(said), said)

    def test_before_there_is_a_blueprint_the_index_says_what_is_missing(self):
        self.research(yoodli=False, copies=())
        report = self.written()
        self.assertFalse(report['ready'])
        self.assertIn('- **Size:** not sized yet: it has no blueprint', self.section())
        self.assertIn('- **Topic:** Rolling restarts', self.section())
        self.assertEqual(self.section('Objectives').strip(), 'The blueprint is not written '
                         'yet, so there are no objectives to list.')
        self.assertEqual(self.section('Coverage').strip(), 'The blueprint is not written yet, '
                         'so there is no coverage to show.')
        self.assertIn('### Open gaps\n\nThe blueprint is not written yet.', self.page())

    def test_before_there_is_any_research_the_index_says_so(self):
        self.cli('init', '--title', 'Rolling restarts')
        self.assertFalse(self.written()['ready'])
        self.assertEqual(self.section('Research').strip().splitlines()[0],
                         'No research has been recorded yet.')


# --- levels --------------------------------------------------------------------------------

class LevelTests(Indexed):
    def test_a_training_with_levels_has_a_part_for_each_level(self):
        self.built(levels=('101', '301'))
        self.assertEqual(self.written(), READY)
        self.assertEqual(self.section().strip().splitlines()[4:], [
            '- **Topic:** Rolling restarts', '- **Levels:** 101, 301',
            '  - **101:** a lesson, 25 minutes. For solutions engineers who deploy apps but '
            'have not had to explain restart behaviour to a customer.',
            '  - **301:** a lesson, 25 minutes. For solutions engineers who deploy apps but '
            'have not had to explain restart behaviour to a customer.'])
        for heading in ('Objectives', 'Coverage'):
            self.assertEqual(re.findall(r'^### (.+)$', self.section(heading), re.MULTILINE),
                             ['Level 101', 'Level 301'])
        self.assertEqual(self.section('Objectives').count('- Describe what a rolling restart'),
                         2)
        files = self.section('What is here')
        self.assertIn('| The level 101 learner guide | [101/document.md](101/document.md) | '
                      'approved on', files)
        self.assertIn('| The level 301 practice scenario | [301/scenario.md](301/scenario.md) |',
                      files)
        self.assertIn('**Level 301**\n\n- K1.4: no evidence was found',
                      self.section('Open gaps and limitations'))
        scenarios = self.section('Using the scenarios')
        self.assertIn('- [101/scenario.md](101/scenario.md): The zero-downtime objection '
                      '(roleplay, level 101)\n- [301/scenario.md](301/scenario.md)', scenarios)
        self.assertIn('Give it the brief of the same level too, as its reference for facts.',
                      scenarios)

    def test_one_unfinished_level_keeps_the_training_from_being_ready(self):
        self.research('--levels', '101,301', yoodli=False, copies=())
        self.level('101')
        report = self.written()
        self.assertFalse(report['ready'])
        self.assertIn('The level 301 blueprint is not started', report['blocking'])
        self.assertIn('No scenario file found for level 301.', report['blocking'])
        self.assertFalse([reason for reason in report['blocking'] if '101' in reason])
        self.assertIn('  - **301:** not sized yet: it has no blueprint', self.section())
        self.assertIn('### Level 301\n\nThe blueprint is not written yet, so there are no '
                      'objectives to list.', self.section('Objectives'))
        self.assertIn('### Level 101\n\n| Objective |', self.section('Coverage'))

    def test_with_yoodli_on_each_levels_handoff_is_spoken_for(self):
        self.built(yoodli=True, levels=('101', '301'))
        self.without_pandoc()
        self.written()
        listed = self.section('Copies')
        for level in ('101', '301'):
            self.assertIn(f'The Yoodli handoff is incomplete: the level {level} brief has no '
                          f'current copy to upload. Until it has, you can make one yourself: '
                          f'copy the text of [{level}/product-brief.md]({level}/product-brief'
                          '.md) into', listed)


# --- what the record holds -----------------------------------------------------------------

class RecordTests(Indexed):
    def test_research_from_supplied_documents_says_where_the_documents_are(self):
        self.research(yoodli=False, copies=('word',))
        self.research_from('supplied-only', SUPPLIED)
        self.level()
        self.copy()
        self.assertEqual(self.written(), READY)
        self.assertEqual(self.section('Research').strip().splitlines()[3],
                         '- Sources: 2 documents that were supplied, and nothing else. The '
                         'documents themselves stay on the computer they were added on. The '
                         'report quotes passages from them.')
        self.assertIn('The research used documents that were supplied. A copy holds everything '
                      'its file does, so read it before sharing it outside your organisation.',
                      self.section('Copies'))

    def test_research_from_documents_and_the_web_names_both(self):
        self.research(yoodli=False, copies=())
        self.research_from('public-web', SUPPLIED[:1])
        self.level()
        self.written()
        self.assertIn('- Sources: 1 document that was supplied, and the public web. The '
                      'documents themselves stay', self.section('Research'))
        self.assertNotIn('before sharing', self.section('Copies'))

    def test_research_from_the_web_alone_says_so(self):
        self.research(yoodli=False, copies=())
        self.research_from('public-web', [])
        self.level()
        self.written()
        self.assertEqual(self.section('Research').strip().splitlines()[3],
                         '- Sources: the public web.')

    def test_the_audience_and_purpose_are_the_persons_own_answers_when_intake_has_them(self):
        self.cli('init', '--title', 'Rolling restarts')
        self.make('intake', 'intake.md', '## Topic\n\nRolling restarts on the platform\n\n'
                  '## Audience\n\nSolutions engineers\nwho deploy apps\n\n## Purpose\n\n'
                  'Field enablement\n')
        self.written()
        self.assertEqual(self.section().strip().splitlines()[4:7], [
            '- **For:** Solutions engineers who deploy apps', '- **Purpose:** Field enablement',
            '- **Topic:** Rolling restarts on the platform'])

    def test_marks_in_the_record_cannot_break_the_page(self):
        self.research(yoodli=False, copies=())
        self.cli('skip', 'deck', '--reason', 'Not wanted')
        self.make('blueprint', 'blueprint.md', example('blueprint.md').replace(
            'Describe what a rolling restart does', 'Describe a restart | and <b>why</b>'))
        self.written()
        self.assertIn('| O1: Describe a restart \\| and <b>why</b> | not written | left out |',
                      self.section('Coverage'))
        self.assertIn('- Describe a restart | and <b>why</b>\n', self.section('Objectives'))


if __name__ == '__main__':
    unittest.main()
