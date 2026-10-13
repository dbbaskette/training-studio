"""Workspace behaviour. Tests named row_NN cover the state-transition matrix in the plan (A7)."""
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

import helpers
from helpers import CHAIN, TrainingCase
import workspace
from workspace import WorkspaceError


class PlainCase(TrainingCase):
    """A plain training with the optional Yoodli stage on, initialised."""

    def setUp(self):
        super().setUp()
        workspace.init(self.root, 'Topic', yoodli=True, copies=['word'])


class LevelCase(TrainingCase):
    """A training with levels 101 and 301, initialised."""

    def setUp(self):
        super().setUp()
        workspace.init(self.root, 'Topic', levels=['301', '101'], yoodli=True, copies=['word'])

    def through(self, last: str, *levels: str) -> None:
        """Approve the shared artifacts, then each level's chain up to `last`."""
        self.approved('intake', 'research-plan', 'research')
        chain = ('blueprint', 'document', 'brief')
        for level in levels:
            self.approved(*(f'{base}@{level}' for base in chain[:chain.index(last) + 1]))


class InitTests(TrainingCase):
    def test_init_creates_a_plain_session_at_intake(self):
        session = workspace.init(self.root, 'Rolling Restarts 101')
        self.assertEqual(session['id'], 'rolling-restarts-101')
        self.assertEqual(session['stage'], 'intake')
        self.assertEqual(session['levels'], [])
        self.assertEqual(session['settings']['brief_kind'], 'product')
        self.assertEqual(session['settings']['stages'], ['document', 'brief', 'deck', 'scenario'])
        self.assertIsNone(session['findings'])
        self.assertEqual(workspace.load(self.root), session)

    def test_init_sorts_and_keeps_levels(self):
        session = workspace.init(self.root, 'Topic', levels=['301', '101'])
        self.assertEqual(session['levels'], ['101', '301'])

    def test_row_46_init_refuses_an_unknown_level(self):
        with self.assertRaisesRegex(WorkspaceError, '101, 201, 301, 401'):
            workspace.init(self.root, 'Topic', levels=['101', '501'])

    def test_init_refuses_a_directory_that_already_has_a_training(self):
        workspace.init(self.root, 'First')
        with self.assertRaisesRegex(WorkspaceError, 'already exists'):
            workspace.init(self.root, 'Second')

    def test_row_38_init_names_deliverable_files_already_present(self):
        self.write('README.md', 'mine\n')
        self.write('document.md', 'mine\n')
        with self.assertRaisesRegex(WorkspaceError, 'README.md, document.md'):
            workspace.init(self.root, 'Topic')
        self.assertFalse((self.root / '.training-studio').exists())

    def test_init_checks_deliverable_names_inside_level_folders(self):
        self.write('301/blueprint.md', 'mine\n')
        with self.assertRaisesRegex(WorkspaceError, '301/blueprint.md'):
            workspace.init(self.root, 'Topic', levels=['301'])

    def test_init_leaves_sources_and_scenarios_alone(self):
        self.write('sources/notes.txt', 'keep me\n')
        self.write('scenario.md', '# Scenario: mine\n')
        workspace.init(self.root, 'Topic')
        self.assertEqual((self.root / 'scenario.md').read_text(), '# Scenario: mine\n')

    def test_row_37_init_refuses_a_directory_holding_the_skill(self):
        package = self.root / 'skills' / 'training-studio'
        package.mkdir(parents=True)
        with mock.patch.object(workspace, 'SKILL_DIR', package):
            with self.assertRaisesRegex(WorkspaceError, 'holds the Training Studio skill'):
                workspace.init(self.root, 'Topic')
            with self.assertRaisesRegex(WorkspaceError, 'holds the Training Studio skill'):
                workspace.init(package, 'Topic')

    def test_init_refuses_unknown_settings(self):
        with self.assertRaisesRegex(WorkspaceError, 'pptx, google'):
            workspace.init(self.root, 'Topic', deck_target='keynote')
        with self.assertRaisesRegex(WorkspaceError, 'product, competitive'):
            workspace.init(self.root, 'Topic', brief_kind='battlecard')


class RecordTests(PlainCase):
    def test_load_refuses_an_unknown_schema(self):
        path = workspace.session_path(self.root)
        session = json.loads(path.read_text())
        session['schema'] = 99
        path.write_text(json.dumps(session))
        with self.assertRaisesRegex(WorkspaceError, 'schema 99'):
            workspace.load(self.root)

    def test_row_35_a_record_that_is_not_json_is_refused_and_left_alone(self):
        path = workspace.session_path(self.root)
        path.write_text('{not json')
        with self.assertRaisesRegex(WorkspaceError, 'not valid JSON'):
            workspace.save(self.root, 'intake')
        self.assertEqual(path.read_text(), '{not json')

    def test_row_35_a_record_missing_a_key_is_refused(self):
        path = workspace.session_path(self.root)
        session = json.loads(path.read_text())
        del session['artifacts']
        path.write_text(json.dumps(session))
        with self.assertRaisesRegex(WorkspaceError, '"artifacts"'):
            workspace.status(self.root)

    def test_commands_refuse_a_directory_without_a_training(self):
        empty = self.root / 'elsewhere'
        empty.mkdir()
        with self.assertRaisesRegex(WorkspaceError, 'Run init first'):
            workspace.save(empty, 'intake')
        self.assertEqual(list(empty.iterdir()), [])

    def test_store_leaves_only_the_record_behind(self):
        names = sorted(path.name for path in (self.root / '.training-studio').iterdir())
        self.assertEqual(names, ['session.json'])

    def test_row_33_a_held_lock_refuses_a_second_writer(self):
        self.write('intake.md', 'v1\n')
        lock = self.write('.training-studio/lock', str(os.getpid()))
        before = workspace.session_path(self.root).read_text()
        with self.assertRaisesRegex(WorkspaceError, 'Another Training Studio command'):
            workspace.save(self.root, 'intake')
        self.assertEqual(workspace.session_path(self.root).read_text(), before)
        self.assertTrue(lock.exists())

    def test_row_34_a_lock_left_by_a_dead_process_is_taken_over(self):
        finished = subprocess.Popen([sys.executable, '-c', 'pass'])
        finished.wait()
        self.write('.training-studio/lock', str(finished.pid))
        self.write('intake.md', 'v1\n')
        workspace.save(self.root, 'intake')
        self.assertFalse((self.root / '.training-studio' / 'lock').exists())


class ArtifactTests(PlainCase):
    def test_unknown_artifacts_are_refused(self):
        with self.assertRaisesRegex(WorkspaceError, 'Unknown artifact'):
            workspace.save(self.root, 'poster')

    def test_a_plain_training_has_no_level_names(self):
        with self.assertRaisesRegex(WorkspaceError, 'has no levels'):
            workspace.artifact(self.root, workspace.load(self.root), 'blueprint@101')

    def test_the_brief_file_follows_its_kind(self):
        session = workspace.load(self.root)
        self.assertEqual(workspace.artifact(self.root, session, 'brief')['file'],
                         'product-brief.md')
        workspace.checkpoint(self.root, brief_kind='competitive')
        session = workspace.load(self.root)
        self.assertEqual(workspace.artifact(self.root, session, 'brief')['file'],
                         'competitive-brief.md')

    def test_row_16_a_new_scenario_file_is_discovered(self):
        self.assertNotIn('scenario:exec-cost', self.state())
        self.write('scenarios/exec-cost.md', '# Scenario: cost\n')
        state = self.state()
        self.assertEqual(state['scenario:exec-cost'], 'draft')
        self.assertEqual(state['yoodli:exec-cost'], 'not-started')

    def test_scenario_md_is_the_main_scenario(self):
        self.write('scenario.md', '# Scenario: main\n')
        report = workspace.status(self.root)
        self.assertEqual(report['files']['scenario:main'], 'scenario.md')
        self.assertEqual(report['files']['yoodli:main'], 'yoodli/main.md')

    def test_row_18_two_main_scenarios_are_ambiguous(self):
        self.write('scenario.md', '# Scenario: a\n')
        self.write('scenarios/main.md', '# Scenario: b\n')
        with self.assertRaisesRegex(WorkspaceError, 'ambiguous'):
            workspace.status(self.root)

    def test_row_19_other_files_are_ignored_not_adopted(self):
        self.write('scenarios/Draft Notes.md', 'notes\n')
        self.write('notes.md', 'notes\n')
        report = workspace.status(self.root)
        self.assertEqual(report['scenarios'], {'found': {},
                                               'ignored': ['scenarios/Draft Notes.md']})
        self.assertFalse(any(name.startswith('scenario:') for name in report['artifacts']))

    def test_row_26_saving_the_blueprint_updates_modules_and_size(self):
        self.build('intake', 'research-plan', 'research')
        self.write('blueprint.md', '## M1 — One (10 min)\n\n## M2 — Two (10 min)\n')
        workspace.save(self.root, 'blueprint', built=True)
        self.assertEqual(workspace.load(self.root)['sizing'][''],
                         {'size': 'course', 'modules': ['m1', 'm2']})
        self.write('blueprint.md', '## M1 — One (10 min)\n')
        workspace.save(self.root, 'blueprint', built=True)
        self.assertEqual(workspace.load(self.root)['sizing'][''],
                         {'size': 'lesson', 'modules': ['m1']})


class LevelArtifactTests(LevelCase):
    def test_level_artifacts_live_in_level_folders(self):
        report = workspace.status(self.root)
        self.assertEqual(report['files']['blueprint@101'], '101/blueprint.md')
        self.assertEqual(report['files']['brief@301'], '301/product-brief.md')
        self.assertEqual(report['files']['deck@301'], '301/deck.pptx')
        self.assertNotIn('blueprint', report['artifacts'])
        self.assertIn('research', report['artifacts'])

    def test_shared_artifacts_come_first_then_levels_in_order(self):
        names = list(workspace.status(self.root)['artifacts'])
        self.assertEqual(names[:4], ['intake', 'research-plan', 'research', 'blueprint@101'])
        self.assertLess(names.index('deck@101'), names.index('blueprint@301'))

    def test_a_level_artifact_reads_its_own_level(self):
        spec = workspace.artifact(self.root, workspace.load(self.root), 'yoodli:main@301')
        self.assertEqual(spec['file'], '301/yoodli/main.md')
        self.assertEqual(spec['upstream'],
                         ('blueprint@301', 'brief@301', 'scenario:main@301'))

    def test_an_unlisted_level_is_refused(self):
        with self.assertRaisesRegex(WorkspaceError, '101, 301'):
            workspace.artifact(self.root, workspace.load(self.root), 'blueprint@201')

    def test_row_47_scenarios_are_discovered_inside_level_folders(self):
        self.write('101/scenario.md', '# Scenario: a\n')
        self.write('101/scenarios/exec-cost.md', '# Scenario: b\n')
        self.write('scenario.md', '# Scenario: stray\n')
        report = workspace.status(self.root)
        self.assertEqual(report['scenarios']['found'],
                         {'scenario:exec-cost@101': '101/scenarios/exec-cost.md',
                          'scenario:main@101': '101/scenario.md'})
        self.assertEqual(report['scenarios']['ignored'], ['scenario.md'])

    def test_row_43_adding_a_level_leaves_the_others_alone(self):
        self.through('document', '101')
        workspace.checkpoint(self.root, levels=['101'])
        self.assertNotIn('blueprint@301', self.state())
        workspace.checkpoint(self.root, levels=['101', '301'])
        state = self.state()
        self.assertEqual(state['blueprint@301'], 'not-started')
        self.assertEqual((state['blueprint@101'], state['document@101']),
                         ('approved', 'approved'))

    def test_a_levelled_training_keeps_at_least_one_level(self):
        with self.assertRaisesRegex(WorkspaceError, 'at least one level'):
            workspace.checkpoint(self.root, levels=[])


class PlainLevelTests(PlainCase):
    def test_row_45_a_plain_training_cannot_gain_levels(self):
        with self.assertRaisesRegex(WorkspaceError, 'plain training'):
            workspace.checkpoint(self.root, levels=['101'])


class SaveTests(PlainCase):
    def history(self, name):
        folder = self.root / '.training-studio' / 'history' / name
        return sorted(path.read_text() for path in folder.iterdir())

    def test_save_records_the_file_on_disk(self):
        self.write('intake.md', 'v1\n')
        entry = workspace.save(self.root, 'intake')
        self.assertEqual(entry['sha256'], workspace.sha256_file(self.root / 'intake.md'))
        self.assertEqual(entry['built_from'], {})
        self.assertEqual(self.history('intake'), ['v1\n'])

    def test_row_41_save_from_keeps_a_hand_edit_nobody_saved(self):
        self.write('intake.md', 'hand edit never saved\n')
        incoming = self.write('incoming.md', 'v2\n')
        workspace.save(self.root, 'intake', source=incoming)
        self.assertEqual((self.root / 'intake.md').read_text(), 'v2\n')
        self.assertEqual(self.history('intake'), ['hand edit never saved\n', 'v2\n'])

    def test_row_63_an_edit_from_a_file_keeps_history_and_never_clears_staleness(self):
        self.approved(*CHAIN)
        self.write('blueprint.md', helpers.CONTENT['blueprint'] + 'edited\n')
        self.assertEqual(self.state()['document'], 'stale')
        incoming = self.write('incoming.md', 'an edit made somewhere else\n')
        workspace.save(self.root, 'document', source=incoming, edit=True)
        self.assertEqual((self.root / 'document.md').read_text(), 'an edit made somewhere else\n')
        self.assertEqual(self.state()['document'], 'stale')
        self.assertEqual(len(self.history('document')), 2)

    def test_save_refuses_when_an_input_is_missing(self):
        self.write('.training-studio/research-plan.json', '{}')
        with self.assertRaisesRegex(WorkspaceError, 'before intake exists'):
            workspace.save(self.root, 'research-plan')

    def test_save_pins_the_inputs_including_settings(self):
        self.build(*CHAIN)
        self.write('deck.pptx', helpers.DECK)
        entry = workspace.save(self.root, 'deck', built=True)
        self.assertEqual(entry['built_from'], {
            'blueprint': workspace.sha256_file(self.root / 'blueprint.md'),
            'document': workspace.sha256_file(self.root / 'document.md'),
            'setting:deck_target': None,
            'setting:brand': None,
        })

    def test_research_cannot_be_written_from_a_file(self):
        self.build('intake', 'research-plan')
        with self.assertRaisesRegex(WorkspaceError, 'harness-research'):
            workspace.save(self.root, 'research', source=self.write('x.md', 'x'))

    def test_row_36_a_symbolic_link_is_not_a_managed_file(self):
        target = self.write('elsewhere.md', 'v1\n')
        (self.root / 'intake.md').symlink_to(target)
        with self.assertRaisesRegex(WorkspaceError, 'symbolic link'):
            workspace.save(self.root, 'intake')

    def test_only_the_deck_takes_reviewed_coverage(self):
        self.write('intake.md', 'v1\n')
        with self.assertRaisesRegex(WorkspaceError, 'Only the deck'):
            workspace.save(self.root, 'intake', coverage={'O1': [2]})

    def test_deck_coverage_is_bound_to_the_deck_and_blueprint(self):
        self.build(*CHAIN)
        self.write('deck.pptx', helpers.DECK)
        entry = workspace.save(self.root, 'deck', built=True, coverage={'O1': [2], 'O2': []})
        review = entry['reviewed_coverage']
        self.assertEqual(review['objectives'], {'O1': [2], 'O2': []})
        self.assertEqual(review['deck_sha256'], entry['sha256'])
        self.assertEqual(review['blueprint_sha256'],
                         workspace.sha256_file(self.root / 'blueprint.md'))

    def test_row_22_bad_coverage_is_refused_and_nothing_is_recorded(self):
        self.build(*CHAIN)
        self.write('deck.pptx', helpers.DECK)
        for coverage, message in (({'O9': [1]}, 'O9 is not an objective'),
                                  ({'O1': [0]}, 'positive whole numbers'),
                                  ({'O1': 'three'}, 'positive whole numbers')):
            with self.assertRaisesRegex(WorkspaceError, message):
                workspace.save(self.root, 'deck', built=True, coverage=coverage)
        self.assertNotIn('deck', workspace.load(self.root)['artifacts'])


class StatusTests(PlainCase):
    def test_nothing_started(self):
        state = self.state()
        self.assertEqual(state['intake'], 'not-started')
        self.assertEqual(state['deck'], 'not-started')

    def test_a_file_never_saved_is_a_draft(self):
        self.write('intake.md', 'v1\n')
        self.assertEqual(self.state()['intake'], 'draft')

    def test_row_01_a_hand_edit_makes_dependents_stale(self):
        self.approved(*CHAIN)
        self.write('blueprint.md', helpers.CONTENT['blueprint'] + 'edited\n')
        state = self.state()
        self.assertEqual((state['blueprint'], state['document']), ('draft', 'stale'))

    def test_staleness_is_transitive(self):
        self.build(*CHAIN)
        self.write('intake.md', 'changed\n')
        state = self.state()
        self.assertEqual(state['intake'], 'draft')
        for name in ('research-plan', 'research', 'blueprint', 'document'):
            self.assertEqual(state[name], 'stale', name)

    def test_row_03_a_plain_save_never_clears_staleness(self):
        self.approved(*CHAIN)
        self.write('blueprint.md', helpers.CONTENT['blueprint'] + 'edited\n')
        workspace.approve(self.root, 'blueprint')
        workspace.save(self.root, 'document')
        self.assertEqual(self.state()['document'], 'stale')

    def test_row_11_a_brand_change_touches_only_the_deck(self):
        self.approved(*CHAIN, 'brief')
        self.write('deck.pptx', helpers.DECK)
        workspace.save(self.root, 'deck', built=True)
        workspace.approve(self.root, 'deck')
        workspace.checkpoint(self.root, brand='Acme')
        state = self.state()
        self.assertEqual((state['deck'], state['document'], state['brief']),
                         ('stale', 'approved', 'approved'))

    def test_row_12_a_new_deck_target_is_a_deck_not_yet_started(self):
        self.approved(*CHAIN, 'deck')
        workspace.checkpoint(self.root, deck_target='google')
        self.assertEqual(self.state()['deck'], 'not-started')

    def test_row_13_a_new_brief_kind_is_a_brief_not_yet_started(self):
        self.approved(*CHAIN, 'brief')
        workspace.checkpoint(self.root, brief_kind='competitive')
        self.assertEqual(self.state()['brief'], 'not-started')

    def test_row_14_editing_a_scenario_touches_only_its_yoodli_output(self):
        self.approved(*CHAIN, 'brief', 'scenario:main', 'yoodli:main')
        self.write('scenario.md', 'rewritten by the user\n')
        state = self.state()
        self.assertEqual((state['scenario:main'], state['yoodli:main']), ('draft', 'stale'))
        self.assertEqual((state['document'], state['brief']), ('approved', 'approved'))

    def test_row_15_a_profile_change_touches_only_yoodli_outputs(self):
        self.approved(*CHAIN, 'brief', 'scenario:main', 'yoodli:main',
                      'scenario:exec-cost', 'yoodli:exec-cost')
        self.profile.write_text('{"revision": 2}\n', encoding='utf-8')
        state = self.state()
        self.assertEqual((state['yoodli:main'], state['yoodli:exec-cost']), ('stale', 'stale'))
        others = {name: value for name, value in state.items()
                  if not name.startswith('yoodli:') and name != 'deck'}
        self.assertEqual(set(others.values()), {'approved'})

    def test_row_17_a_removed_scenario_stays_visible(self):
        self.approved(*CHAIN, 'brief', 'scenario:exec-cost', 'yoodli:exec-cost')
        (self.root / 'scenarios' / 'exec-cost.md').unlink()
        state = self.state()
        self.assertEqual((state['scenario:exec-cost'], state['yoodli:exec-cost']),
                         ('not-started', 'stale'))

    def test_the_status_report_is_flat_and_lists_what_is_stale(self):
        self.build('intake', 'research-plan')
        self.write('intake.md', 'changed\n')
        report = workspace.status(self.root)
        self.assertEqual(report['stale'], ['research-plan'])
        self.assertEqual(report['artifacts']['intake'], 'draft')
        self.assertEqual(report['files']['intake'], 'intake.md')
        self.assertNotIn('events', report)


class LevelStatusTests(LevelCase):
    def test_row_42_editing_one_level_leaves_the_other_alone(self):
        self.through('document', '101', '301')
        self.write('301/blueprint.md', helpers.CONTENT['blueprint'] + 'edited\n')
        state = self.state()
        self.assertEqual((state['blueprint@301'], state['document@301']), ('draft', 'stale'))
        self.assertEqual((state['blueprint@101'], state['document@101']),
                         ('approved', 'approved'))

    def test_row_44_a_research_change_is_settled_level_by_level(self):
        self.through('brief', '101', '301')
        self.write('.harness-research/research-report.md', 'research v2\n')
        workspace.save(self.root, 'research', built=True)
        workspace.approve(self.root, 'research')
        state = self.state()
        self.assertEqual((state['blueprint@101'], state['document@101'], state['brief@101']),
                         ('stale', 'stale', 'stale'))
        workspace.approve(self.root, 'blueprint@101', accept_stale='No new facts for 101')
        workspace.approve(self.root, 'brief@101', accept_stale='No new facts for 101')
        state = self.state()
        self.assertEqual((state['blueprint@101'], state['document@101'], state['brief@101']),
                         ('approved', 'approved', 'approved'))
        self.assertEqual((state['blueprint@301'], state['document@301'], state['brief@301']),
                         ('stale', 'stale', 'stale'))


class ApproveTests(PlainCase):
    def edit_and_reapprove_blueprint(self):
        self.approved(*CHAIN)
        self.write('blueprint.md', helpers.CONTENT['blueprint'] + 'edited\n')
        workspace.approve(self.root, 'blueprint')

    def test_approval_holds_until_the_file_changes(self):
        self.approved('intake')
        self.assertEqual(self.state()['intake'], 'approved')
        self.write('intake.md', 'hand edit\n')
        self.assertEqual(self.state()['intake'], 'draft')

    def test_row_40_approving_records_a_hand_edit_first(self):
        self.build('intake')
        self.write('intake.md', 'hand edit\n')
        workspace.approve(self.root, 'intake')
        self.assertEqual(self.state()['intake'], 'approved')
        history = self.root / '.training-studio' / 'history' / 'intake'
        self.assertEqual(len(list(history.iterdir())), 2)

    def test_row_39_approval_needs_upstream_approved_first(self):
        self.build('intake', 'research-plan')
        with self.assertRaisesRegex(WorkspaceError, 'intake is draft'):
            workspace.approve(self.root, 'research-plan')

    def test_a_missing_file_cannot_be_approved(self):
        with self.assertRaisesRegex(WorkspaceError, 'does not exist'):
            workspace.approve(self.root, 'intake')

    def test_row_02_a_rebuild_with_identical_bytes_needs_approval_again(self):
        self.edit_and_reapprove_blueprint()
        self.assertEqual(self.state()['document'], 'stale')
        workspace.save(self.root, 'document', built=True)
        self.assertEqual(self.state()['document'], 'draft')

    def test_row_04_a_stale_artifact_is_not_approved_without_a_reason(self):
        self.edit_and_reapprove_blueprint()
        with self.assertRaisesRegex(WorkspaceError, 'older version'):
            workspace.approve(self.root, 'document')
        self.assertEqual(self.state()['document'], 'stale')

    def test_row_05_accepting_staleness_records_the_lineage_and_reason(self):
        self.edit_and_reapprove_blueprint()
        before = workspace.load(self.root)['artifacts']['document']['built_from']
        workspace.approve(self.root, 'document', accept_stale='Wording only')
        self.assertEqual(self.state()['document'], 'approved')
        decision = workspace.load(self.root)['decisions'][-1]
        self.assertEqual(decision['artifact'], 'document')
        self.assertEqual(decision['reason'], 'Wording only')
        self.assertEqual(decision['from'], before)
        self.assertEqual(decision['to'],
                         {'blueprint': workspace.sha256_file(self.root / 'blueprint.md')})

    def test_row_06_accepting_an_unchanged_plan_keeps_its_research(self):
        self.approved(*CHAIN)
        self.write('intake.md', 'changed\n')
        workspace.approve(self.root, 'intake')
        self.assertEqual(self.state()['research'], 'stale')
        workspace.approve(self.root, 'research-plan', accept_stale='Questions still right')
        state = self.state()
        self.assertEqual((state['research-plan'], state['research'], state['blueprint']),
                         ('approved', 'approved', 'stale'))

    def test_approving_research_copies_the_report_and_indexes_findings(self):
        self.approved('intake', 'research-plan')
        self.build('research')
        self.write('.harness-research/research.json', json.dumps(helpers.RESEARCH))
        outcome = workspace.approve(self.root, 'research')
        self.assertEqual((self.root / 'research-report.md').read_text(), 'research v1\n')
        session = workspace.load(self.root)
        self.assertEqual(session['findings'], helpers.FINDINGS)
        self.assertEqual(session['research']['run'], 'run-1')
        self.assertEqual(outcome['warnings'], ['Research questions still pending: rollback'])

    def test_row_07_an_edited_copy_returns_research_to_draft(self):
        self.approved(*CHAIN)
        self.write('research-report.md', 'tampered\n')
        state = self.state()
        self.assertEqual((state['research'], state['blueprint']), ('draft', 'stale'))

    def test_row_08_a_changed_record_returns_research_to_draft(self):
        self.approved('intake', 'research-plan')
        self.build('research')
        self.write('.harness-research/research.json', json.dumps(helpers.RESEARCH))
        workspace.approve(self.root, 'research')
        self.assertEqual(self.state()['research'], 'approved')
        changed = dict(helpers.RESEARCH, run='run-2')
        self.write('.harness-research/research.json', json.dumps(changed))
        self.assertEqual(self.state()['research'], 'draft')

    def test_row_09_a_changed_live_report_returns_research_to_draft(self):
        self.approved(*CHAIN)
        self.write('.harness-research/research-report.md', 'research v2\n')
        state = self.state()
        self.assertEqual((state['research'], state['blueprint']), ('draft', 'stale'))

    def test_row_10_a_record_from_elsewhere_is_reported_not_guessed(self):
        self.approved('intake', 'research-plan')
        self.build('research')
        for record in ({'schema': 2}, dict(helpers.RESEARCH, owner='someone-else')):
            self.write('.harness-research/research.json', json.dumps(record))
            outcome = workspace.approve(self.root, 'research')
            self.assertIsNone(workspace.load(self.root)['findings'])
            self.assertIn('citation checks will report unavailable', outcome['warnings'][0])


class ExportTests(PlainCase):
    def setUp(self):
        super().setUp()
        self.approved(*CHAIN)
        self.write('document.docx', 'exported v1')

    def exports(self):
        return workspace.status(self.root)['exports']

    def test_an_export_is_missing_until_recorded_then_current(self):
        self.assertEqual(self.exports()['document'], 'missing')
        workspace.export(self.root, 'document')
        self.assertEqual(self.exports()['document'], 'current')

    def test_row_23_editing_the_source_makes_the_export_outdated(self):
        workspace.export(self.root, 'document')
        self.write('document.md', 'edited\n')
        self.assertEqual(self.exports()['document'], 'outdated')

    def test_row_24_a_deleted_export_is_missing(self):
        workspace.export(self.root, 'document')
        (self.root / 'document.docx').unlink()
        self.assertEqual(self.exports()['document'], 'missing')

    def test_an_export_can_be_recorded_as_unavailable(self):
        workspace.export(self.root, 'document', unavailable='No converter on this machine')
        self.assertEqual(self.exports()['document'], 'unavailable')

    def test_an_export_may_use_another_format(self):
        self.write('document.pdf', 'pdf')
        record = workspace.export(self.root, 'document', file='document.pdf')
        self.assertEqual(record['file'], 'document.pdf')

    def test_an_export_must_exist_and_stay_inside_the_directory(self):
        with self.assertRaisesRegex(WorkspaceError, 'does not exist'):
            workspace.export(self.root, 'document', file='nowhere.docx')
        with self.assertRaisesRegex(WorkspaceError, 'inside the training directory'):
            workspace.export(self.root, 'document', file='../yoodli.json')

    def test_only_documents_briefs_and_yoodli_outputs_are_exported(self):
        with self.assertRaisesRegex(WorkspaceError, 'not exported'):
            workspace.export(self.root, 'blueprint')
        self.assertEqual(sorted(self.exports()), ['brief', 'document'])


class SkipTests(PlainCase):
    def test_row_29_the_brief_and_scenarios_stay_while_yoodli_is_wanted(self):
        for stage in ('brief', 'scenario'):
            with self.assertRaisesRegex(WorkspaceError, 'Turn Yoodli off'):
                workspace.skip(self.root, stage, reason='Deck only')

    def test_row_30_yoodli_cannot_be_turned_on_without_the_brief(self):
        workspace.skip(self.root, 'yoodli', reason='Not using it')
        workspace.skip(self.root, 'brief', reason='Deck only')
        with self.assertRaisesRegex(WorkspaceError, 'Restore the brief and the scenarios'):
            workspace.skip(self.root, 'yoodli', clear=True)

    def test_skipped_stages_report_skipped(self):
        self.write('scenario.md', '# Scenario\n')
        workspace.skip(self.root, 'yoodli', reason='Not using it')
        workspace.skip(self.root, 'scenario', reason='Not now')
        workspace.skip(self.root, 'document', reason='Not now')
        state = self.state()
        self.assertEqual((state['document'], state['scenario:main']), ('skipped', 'skipped'))
        self.assertNotIn('yoodli:main', state)

    def test_the_deck_builds_from_research_when_the_document_is_skipped(self):
        workspace.skip(self.root, 'document', reason='Deck only')
        spec = workspace.artifact(self.root, workspace.load(self.root), 'deck')
        self.assertEqual(spec['upstream'], ('blueprint', 'research'))

    def test_an_unavailable_stage_reports_unavailable(self):
        workspace.skip(self.root, 'deck', reason='harness-slides is not installed',
                       unavailable=True)
        self.assertEqual(self.state()['deck'], 'unavailable')

    def test_clearing_restores_the_stage_in_pipeline_order(self):
        workspace.skip(self.root, 'deck', reason='Later')
        outcome = workspace.skip(self.root, 'deck', clear=True)
        self.assertEqual(outcome['stages'], ['document', 'brief', 'deck', 'scenario', 'yoodli'])

    def test_only_deliverable_stages_can_be_skipped(self):
        with self.assertRaisesRegex(WorkspaceError, 'document, brief, deck, scenario'):
            workspace.skip(self.root, 'research', reason='No time')

    def test_a_skip_needs_a_reason(self):
        with self.assertRaisesRegex(WorkspaceError, 'Give a reason'):
            workspace.skip(self.root, 'deck')


class OptionalYoodliTests(TrainingCase):
    """Yoodli is off unless asked for (matrix rows 58 to 60)."""

    def setUp(self):
        super().setUp()
        workspace.init(self.root, 'Topic')
        self.write('scenario.md', '# Scenario: mine\n')

    def test_row_58_yoodli_is_off_by_default(self):
        state = self.state()
        self.assertEqual(state['scenario:main'], 'draft')
        self.assertFalse(any(name.startswith('yoodli:') for name in state))
        self.assertEqual(workspace.status(self.root)['exports'], {})

    def test_row_59_turning_yoodli_on_lists_its_artifacts(self):
        outcome = workspace.skip(self.root, 'yoodli', clear=True)
        self.assertEqual(outcome['stages'][-1], 'yoodli')
        self.assertEqual(self.state()['yoodli:main'], 'not-started')

    def test_row_60_without_yoodli_the_brief_is_not_tied_to_scenarios(self):
        workspace.skip(self.root, 'brief', reason='Guide only')
        self.assertEqual(self.state()['scenario:main'], 'draft')
        self.assertEqual(self.state()['brief'], 'skipped')

    def test_init_can_turn_yoodli_on(self):
        other = self.root.parent / 'other'
        other.mkdir()
        session = workspace.init(other, 'Topic', yoodli=True)
        self.assertEqual(session['settings']['stages'][-1], 'yoodli')


class CopiesTests(TrainingCase):
    """Copies of the document and the brief are kept only when asked for (matrix rows 64
    to 66 and 69)."""

    def exports(self) -> dict:
        return workspace.status(self.root)['exports']

    def test_row_64_a_training_keeps_no_copies_unless_asked(self):
        session = workspace.init(self.root, 'Topic')
        self.assertEqual(session['settings']['copies'], [])
        self.approved(*CHAIN)
        self.assertEqual(self.exports(), {})

    def test_init_records_the_copies_asked_for(self):
        session = workspace.init(self.root, 'Topic', copies=['word', 'google', 'word'])
        self.assertEqual(session['settings']['copies'], ['google', 'word'])
        self.assertEqual(self.exports(), {'brief': 'missing', 'document': 'missing'})

    def test_an_unknown_kind_of_copy_is_refused(self):
        with self.assertRaisesRegex(WorkspaceError, 'google, word; or none'):
            workspace.init(self.root, 'Topic', copies=['pdf'])
        workspace.init(self.root, 'Topic')
        with self.assertRaisesRegex(WorkspaceError, 'google, word; or none'):
            workspace.checkpoint(self.root, copies=['pdf'])

    def test_row_65_an_export_is_refused_while_word_copies_are_off(self):
        workspace.init(self.root, 'Topic', copies=['google'])
        self.approved(*CHAIN)
        self.write('document.docx', 'exported v1')
        with self.assertRaisesRegex(WorkspaceError, 'checkpoint --copies google word\\.'):
            workspace.export(self.root, 'document')
        self.assertEqual(workspace.load(self.root)['exports'], {})

    def test_row_70_with_google_docs_kept_yoodli_asks_for_no_word_copy(self):
        workspace.init(self.root, 'Topic', yoodli=True, copies=['google'])
        self.write('scenario.md', '# Scenario: mine\n')
        self.assertEqual(self.exports(), {})
        self.approved(*CHAIN, 'brief')
        self.write('product-brief.docx', 'exported v1')
        with self.assertRaisesRegex(WorkspaceError, 'Word copies are off'):
            workspace.export(self.root, 'brief')
        workspace.checkpoint(self.root, copies=['google', 'word'])
        self.assertEqual(sorted(self.exports()), ['brief', 'document', 'yoodli:main'])

    def test_row_66_without_copies_yoodli_takes_the_brief_as_a_word_file(self):
        workspace.init(self.root, 'Topic', yoodli=True)
        self.write('scenario.md', '# Scenario: mine\n')
        self.assertEqual(self.exports(), {'brief': 'missing', 'yoodli:main': 'missing'})
        self.approved(*CHAIN, 'brief')
        self.write('product-brief.docx', 'exported v1')
        workspace.export(self.root, 'brief')
        self.assertEqual(self.exports()['brief'], 'current')

    def test_row_69_copies_can_be_turned_on_and_off_without_staling_anything(self):
        workspace.init(self.root, 'Topic')
        self.approved(*CHAIN)
        before = self.state()
        outcome = workspace.checkpoint(self.root, copies=['word'])
        self.assertEqual(outcome['settings']['copies'], ['word'])
        self.assertEqual(self.exports(), {'brief': 'missing', 'document': 'missing'})
        self.write('document.docx', 'exported v1')
        workspace.export(self.root, 'document')
        self.assertEqual(self.exports()['document'], 'current')
        workspace.checkpoint(self.root, copies=[])
        self.assertEqual(self.exports(), {})
        self.assertEqual(self.state(), before)

    def test_a_checkpoint_that_does_not_mention_copies_leaves_them_alone(self):
        workspace.init(self.root, 'Topic', copies=['google'])
        workspace.checkpoint(self.root, stage='blueprint')
        self.assertEqual(workspace.load(self.root)['settings']['copies'], ['google'])

    def test_a_training_started_before_copies_were_a_choice_keeps_none(self):
        workspace.init(self.root, 'Topic', copies=['word'])
        path = workspace.session_path(self.root)
        session = json.loads(path.read_text(encoding='utf-8'))
        del session['settings']['copies']
        path.write_text(json.dumps(session), encoding='utf-8')
        self.assertEqual(workspace.load(self.root)['settings']['copies'], [])
        self.assertEqual(self.exports(), {})


class CheckpointTests(PlainCase):
    def test_checkpoint_records_where_the_run_is(self):
        workspace.checkpoint(self.root, stage='blueprint', next_step='Present the blueprint',
                             question='Approve the blueprint?')
        report = workspace.status(self.root)
        self.assertEqual(report['stage'], 'blueprint')
        self.assertEqual(report['next_step'], 'Present the blueprint')
        self.assertEqual(report['pending_question'], 'Approve the blueprint?')
        workspace.checkpoint(self.root, clear_question=True)
        self.assertIsNone(workspace.status(self.root)['pending_question'])

    def test_checkpoint_refuses_an_unknown_stage(self):
        with self.assertRaisesRegex(WorkspaceError, 'The stage is one of'):
            workspace.checkpoint(self.root, stage='printing')

    def test_pin_records_the_task_to_resume(self):
        pins = workspace.pin(self.root, 'harness-research', task='t-1',
                             runtime='/opt/runtime', run='run-1')
        self.assertEqual(pins['harness-research'],
                         {'task': 't-1', 'runtime': '/opt/runtime', 'run': 'run-1'})
        self.assertEqual(workspace.status(self.root)['pins'], pins)

    def test_row_54_a_text_file_is_not_a_deck(self):
        self.build(*CHAIN)
        self.write('deck.pptx', 'A placeholder until the real deck is built.')
        with self.assertRaisesRegex(WorkspaceError, 'is not a PowerPoint file'):
            workspace.save(self.root, 'deck', built=True)
        self.assertNotIn('deck', workspace.load(self.root)['artifacts'])

    def test_pin_refuses_other_skills(self):
        with self.assertRaisesRegex(WorkspaceError, 'harness-research'):
            workspace.pin(self.root, 'another-skill', task='t', runtime='/r')


class ApprovalModeTests(PlainCase):
    """Where a gate is decided: in the conversation, or on the page (matrix rows 74 to 81)."""

    def events(self) -> list[dict]:
        return workspace.load(self.root)['events']

    def test_row_74_approval_is_in_chat_unless_asked_for(self):
        report = workspace.status(self.root)
        self.assertEqual((report['approval'], report['settings']['approval']), ('chat', 'chat'))
        self.assertEqual((report['gate'], report['requests']), (None, []))
        other = self.root.parent / 'other'
        other.mkdir()
        session = workspace.init(other, 'Topic', approval='page')
        self.assertEqual(session['settings']['approval'], 'page')
        with self.assertRaisesRegex(WorkspaceError, 'chat, page'):
            workspace.init(self.root.parent / 'another', 'Topic', approval='email')

    def test_row_74_a_training_started_before_the_page_reads_as_chat(self):
        path = workspace.session_path(self.root)
        session = json.loads(path.read_text(encoding='utf-8'))
        del session['settings']['approval'], session['requests'], session['gate']
        path.write_text(json.dumps(session), encoding='utf-8')
        report = workspace.status(self.root)
        self.assertEqual((report['approval'], report['gate'], report['requests']),
                         ('chat', None, []))
        self.build('intake')
        workspace.approve(self.root, 'intake')
        self.assertEqual(self.state()['intake'], 'approved')

    def test_a_record_with_an_unknown_approval_mode_is_refused(self):
        path = workspace.session_path(self.root)
        session = json.loads(path.read_text(encoding='utf-8'))
        session['settings']['approval'] = 'email'
        path.write_text(json.dumps(session), encoding='utf-8')
        with self.assertRaisesRegex(WorkspaceError, 'settings.approval'):
            workspace.status(self.root)

    def test_row_75_a_checkpoint_moves_approval_to_the_page(self):
        outcome = workspace.checkpoint(self.root, approval='page')
        self.assertEqual(outcome['settings']['approval'], 'page')
        self.assertEqual(workspace.status(self.root)['approval'], 'page')
        self.assertEqual(self.events()[-2], {'at': self.events()[-2]['at'], 'event': 'approval',
                                             'mode': 'page', 'by': 'chat'})
        with self.assertRaisesRegex(WorkspaceError, 'chat, page'):
            workspace.checkpoint(self.root, approval='email')

    def test_row_76_only_the_page_moves_approval_back_to_chat(self):
        workspace.checkpoint(self.root, approval='page')
        with self.assertRaisesRegex(WorkspaceError, 'only the page can move it back'):
            workspace.checkpoint(self.root, approval='chat')
        self.assertEqual(workspace.status(self.root)['approval'], 'page')
        workspace.checkpoint(self.root, approval='page', next_step='Still on the page')
        workspace.checkpoint(self.root, approval='chat', by='page')
        self.assertEqual(workspace.status(self.root)['approval'], 'chat')
        self.assertEqual(self.events()[-2]['by'], 'page')
        workspace.checkpoint(self.root, approval='chat')

    def test_row_77_the_command_line_cannot_approve_in_page_mode(self):
        self.approved('intake', 'research-plan')
        self.build('research')
        workspace.checkpoint(self.root, approval='page')
        for call in (lambda: workspace.approve(self.root, 'research'),
                     lambda: workspace.approve(self.root, 'research', accept_stale='Fine'),
                     lambda: workspace.decide(self.root, 'research', 'approve'),
                     lambda: workspace.decide(self.root, 'research', 'accept', 'Fine')):
            with self.assertRaisesRegex(
                    WorkspaceError, 'decided on the page.*training.py desk.*terminal of their own'):
                call()
        self.assertEqual(self.state()['research'], 'draft')
        self.assertFalse((self.root / 'reviews' / 'research.md').exists())

    def test_row_78_intake_is_still_approved_from_the_command_line_in_page_mode(self):
        workspace.checkpoint(self.root, approval='page')
        self.build('intake')
        outcome = workspace.decide(self.root, 'intake', 'approve')
        self.assertEqual((outcome['by'], outcome['approved']['by']), ('chat', 'chat'))
        self.assertEqual(self.state()['intake'], 'approved')

    def test_row_79_the_command_line_cannot_skip_or_restore_in_page_mode(self):
        workspace.skip(self.root, 'yoodli', reason='Not using it')
        workspace.checkpoint(self.root, approval='page')
        before = workspace.load(self.root)['settings']['stages']
        for call in (lambda: workspace.skip(self.root, 'deck', reason='Not needed'),
                     lambda: workspace.decide(self.root, 'deck', 'skip', 'Not needed'),
                     lambda: workspace.skip(self.root, 'yoodli', clear=True),
                     lambda: workspace.decide(self.root, 'yoodli', 'restore')):
            with self.assertRaisesRegex(WorkspaceError, 'decided on the page'):
                call()
        self.assertEqual(workspace.load(self.root)['settings']['stages'], before)

    def test_row_80_saying_a_stage_could_not_run_is_not_a_decision(self):
        workspace.checkpoint(self.root, approval='page')
        workspace.skip(self.root, 'deck', reason='harness-slides is not installed',
                       unavailable=True)
        self.assertEqual(self.state()['deck'], 'unavailable')
        workspace.skip(self.root, 'deck', clear=True)
        self.assertEqual(self.state()['deck'], 'not-started')

    def test_row_81_a_request_is_not_made_from_the_command_line_in_page_mode(self):
        self.build('intake')
        workspace.checkpoint(self.root, approval='page')
        for decision in ('revise', 'rebuild'):
            with self.assertRaisesRegex(WorkspaceError, 'decided on the page'):
                workspace.decide(self.root, 'intake', decision, 'Shorter')
        self.assertEqual(workspace.status(self.root)['requests'], [])


class DecisionTests(PlainCase):
    """One function records every decision, from the page or the command line (matrix rows
    82 to 92)."""

    def review(self, name: str = 'document') -> str:
        return (self.root / 'reviews' / f'{name}.md').read_text(encoding='utf-8')

    def stale_document(self) -> None:
        self.approved(*CHAIN)
        self.write('blueprint.md', helpers.CONTENT['blueprint'] + 'edited\n')
        workspace.approve(self.root, 'blueprint')

    def at_the_document_gate(self, approval: str = 'page') -> None:
        self.approved(*CHAIN[:-1])
        self.build('document')
        workspace.checkpoint(self.root, approval=approval, gate='document',
                             question='Approve the guide?', next_step='Waiting')

    def test_row_82_a_decision_says_who_made_it(self):
        self.at_the_document_gate()
        outcome = workspace.decide(self.root, 'document', 'approve', by='page')
        self.assertEqual((outcome['decision'], outcome['by'], outcome['approved']['by']),
                         ('approve', 'page', 'page'))
        session = workspace.load(self.root)
        self.assertEqual(session['artifacts']['document']['approved']['by'], 'page')
        self.assertEqual(session['events'][-1]['event'], 'approve')
        self.assertEqual(session['events'][-1]['by'], 'page')
        self.assertEqual(session['artifacts']['blueprint']['approved']['by'], 'chat')
        self.assertEqual(self.state()['document'], 'approved')
        with self.assertRaisesRegex(WorkspaceError, 'chat, page'):
            workspace.decide(self.root, 'document', 'approve', by='someone')

    def test_row_83_accepting_as_it_is_needs_a_reason(self):
        self.stale_document()
        workspace.checkpoint(self.root, approval='page')
        with self.assertRaisesRegex(WorkspaceError, 'Give a reason'):
            workspace.decide(self.root, 'document', 'accept', '  ', by='page')
        with self.assertRaisesRegex(WorkspaceError, 'older version'):
            workspace.decide(self.root, 'document', 'approve', by='page')
        self.assertEqual(self.state()['document'], 'stale')
        workspace.decide(self.root, 'document', 'accept', 'Wording only', by='page')
        self.assertEqual(self.state()['document'], 'approved')
        decision = workspace.load(self.root)['decisions'][-1]
        self.assertEqual((decision['decision'], decision['reason'], decision['by']),
                         ('accepted-stale', 'Wording only', 'page'))
        self.assertIn('accepted as it is on the page', self.review())
        self.assertIn('> Wording only', self.review())

    def test_row_84_asking_for_changes_approves_nothing_and_opens_a_request(self):
        self.at_the_document_gate()
        with self.assertRaisesRegex(WorkspaceError, 'Say what should change'):
            workspace.decide(self.root, 'document', 'revise', by='page')
        self.assertEqual(workspace.status(self.root)['requests'], [])
        outcome = workspace.decide(self.root, 'document', 'revise', 'Shorten the opening',
                                   by='page')
        report = workspace.status(self.root)
        self.assertEqual(report['artifacts']['document'], 'draft')
        self.assertEqual(report['requests'], [{'artifact': 'document', 'kind': 'revise',
                                               'note': 'Shorten the opening',
                                               'at': outcome['request']['at']}])
        self.assertEqual(workspace.load(self.root)['events'][-1],
                         {'at': outcome['request']['at'], 'event': 'request',
                          'artifact': 'document', 'kind': 'revise', 'by': 'page'})

    def test_row_85_a_rebuild_is_a_request_whose_note_is_optional(self):
        self.at_the_document_gate()
        workspace.decide(self.root, 'document', 'rebuild', by='page')
        workspace.decide(self.root, 'document', 'rebuild', 'Start from the new research',
                         by='page')
        requests = workspace.status(self.root)['requests']
        self.assertEqual([(item['kind'], item['note']) for item in requests],
                         [('rebuild', None), ('rebuild', 'Start from the new research')])
        self.assertEqual(self.state()['document'], 'draft')
        with self.assertRaisesRegex(WorkspaceError, 'Nothing to change in brief'):
            workspace.decide(self.root, 'brief', 'rebuild', by='page')

    def test_row_86_a_request_closes_when_the_artifact_is_rebuilt(self):
        self.at_the_document_gate()
        workspace.decide(self.root, 'document', 'revise', 'Shorten the opening', by='page')
        workspace.decide(self.root, 'blueprint', 'rebuild', by='page')
        self.write('document.md', 'a hand edit\n')
        workspace.save(self.root, 'document')
        self.assertEqual(len(workspace.status(self.root)['requests']), 2)
        incoming = self.write('work/pulled.md', 'an edit pulled from elsewhere\n')
        workspace.save(self.root, 'document', source=incoming, edit=True)
        self.assertEqual(len(workspace.status(self.root)['requests']), 2)
        workspace.save(self.root, 'document', built=True)
        self.assertEqual([item['artifact'] for item in workspace.status(self.root)['requests']],
                         ['blueprint'])
        incoming = self.write('work/blueprint.md', helpers.CONTENT['blueprint'] + 'again\n')
        workspace.save(self.root, 'blueprint', source=incoming)
        self.assertEqual(workspace.status(self.root)['requests'], [])

    def test_row_87_a_request_closes_when_the_artifact_is_approved(self):
        self.at_the_document_gate()
        workspace.decide(self.root, 'document', 'revise', 'Shorten the opening', by='page')
        workspace.decide(self.root, 'document', 'approve', by='page')
        self.assertEqual(workspace.status(self.root)['requests'], [])

    def test_row_88_every_decision_clears_the_question_and_says_what_was_decided(self):
        said = {
            'approve': (None, 'The learner guide was approved on the page.'),
            'revise': ('Shorten it', 'Changes to the learner guide were asked for on the '
                                     'page: Shorten it'),
            'rebuild': (None, 'A rebuild of the learner guide was asked for on the page.'),
            'skip': ('Not needed', 'The learner guide stage was left out on the page: '
                                   'Not needed'),
        }
        first = self.root
        for decision, (note, sentence) in said.items():
            with self.subTest(decision):
                self.root = first.parent / decision
                self.root.mkdir()
                workspace.init(self.root, 'Topic')
                self.at_the_document_gate()
                outcome = workspace.decide(self.root, 'document', decision, note, by='page')
                report = workspace.status(self.root)
                self.assertEqual((report['pending_question'], report['gate']), (None, None))
                self.assertEqual((report['next_step'], outcome['next_step']),
                                 (sentence, sentence))

    def test_row_88_a_long_note_is_whole_in_the_request_and_short_in_the_sentence(self):
        self.at_the_document_gate()
        note = 'First line.\nSecond line. ' + 'More. ' * 60
        workspace.decide(self.root, 'document', 'revise', note, by='page')
        report = workspace.status(self.root)
        self.assertEqual(report['requests'][0]['note'], note.strip())
        self.assertLess(len(report['next_step']), 280)
        self.assertNotIn('\n', report['next_step'])
        self.assertTrue(report['next_step'].endswith('…'))

    def test_row_89_every_decision_is_written_to_the_review(self):
        self.at_the_document_gate()
        self.assertFalse((self.root / 'reviews').exists())
        with mock.patch.object(workspace, 'now', return_value='2030-01-02T03:04:05Z'):
            workspace.decide(self.root, 'document', 'revise',
                             'Shorten the opening\n## Decision: approved', by='page')
        self.assertEqual(self.review(), (
            '# Reviews of document\n\n'
            '## Decision: changes asked for on the page, 2030-01-02T03:04:05Z\n\n'
            '> Shorten the opening\n> ## Decision: approved\n'))
        self.write('reviews/document.md', self.review() + '\n## Review\n\nThe second try.\n')
        workspace.decide(self.root, 'document', 'approve', by='page')
        text = self.review()
        self.assertIn('## Review\n\nThe second try.\n\n## Decision: approved on the page, ', text)
        self.assertEqual(text.count('\n## Decision: '), 2)

    def test_row_89_a_decision_in_the_conversation_is_written_too(self):
        self.at_the_document_gate(approval='chat')
        workspace.decide(self.root, 'document', 'approve')
        self.assertIn('## Decision: approved in the conversation, ', self.review())
        self.assertEqual(workspace.status(self.root)['next_step'],
                         'The learner guide was approved in the conversation.')

    @unittest.skipUnless(hasattr(os, 'symlink'), 'needs symbolic links')
    def test_row_89_a_review_is_never_written_through_a_link(self):
        self.at_the_document_gate()
        outside = self.root.parent / 'outside'
        outside.mkdir()
        (self.root / 'reviews').symlink_to(outside, target_is_directory=True)
        before = workspace.session_path(self.root).read_text(encoding='utf-8')
        for decision, note in (('approve', None), ('revise', 'Shorter'), ('skip', 'No')):
            with self.assertRaisesRegex(WorkspaceError, 'reviews folder must be a real folder'):
                workspace.decide(self.root, 'document', decision, note, by='page')
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(workspace.session_path(self.root).read_text(encoding='utf-8'), before)
        self.assertEqual(self.state()['document'], 'draft')

    def test_row_90_skipping_on_the_page_leaves_out_the_artifacts_stage(self):
        self.at_the_document_gate()
        workspace.skip(self.root, 'yoodli', reason='Not using it', by='page')
        with self.assertRaisesRegex(WorkspaceError, 'Give a reason'):
            workspace.decide(self.root, 'document', 'skip', by='page')
        outcome = workspace.decide(self.root, 'document', 'skip', 'Deck only', by='page')
        self.assertEqual((outcome['stage'], outcome['stages']),
                         ('document', ['brief', 'deck', 'scenario']))
        self.assertEqual(self.state()['document'], 'skipped')
        self.assertEqual(workspace.load(self.root)['events'][-1]['by'], 'page')
        self.assertIn('its stage left out on the page', self.review())
        with self.assertRaisesRegex(WorkspaceError, 'Only these stages'):
            workspace.decide(self.root, 'blueprint', 'skip', 'No time', by='page')

    def test_row_91_a_stage_left_out_is_brought_back_on_the_page(self):
        self.at_the_document_gate()
        workspace.decide(self.root, 'document', 'skip', 'Deck only', by='page')
        outcome = workspace.decide(self.root, 'document', 'restore', by='page')
        self.assertIn('document', outcome['stages'])
        self.assertEqual(self.state()['document'], 'draft')
        self.assertEqual(workspace.status(self.root)['next_step'],
                         'The learner guide stage was brought back on the page.')
        workspace.decide(self.root, 'yoodli', 'skip', 'Not using it', by='page')
        workspace.decide(self.root, 'yoodli', 'restore', by='page')
        self.assertEqual(workspace.load(self.root)['settings']['stages'][-1], 'yoodli')

    def test_row_92_an_approval_is_of_the_version_that_was_read(self):
        self.at_the_document_gate()
        read = workspace.sha256_file(self.root / 'document.md')
        self.write('document.md', 'rewritten while the page was open\n')
        for decision, note in (('approve', None), ('accept', 'Fine')):
            with self.assertRaisesRegex(WorkspaceError, 'has changed since it was opened'):
                workspace.decide(self.root, 'document', decision, note, by='page', seen=read)
        self.assertEqual(self.state()['document'], 'draft')
        self.assertFalse((self.root / 'reviews').exists())
        now = workspace.sha256_file(self.root / 'document.md')
        workspace.decide(self.root, 'document', 'approve', by='page', seen=now)
        self.assertEqual(self.state()['document'], 'approved')

    def test_a_decision_names_an_artifact_of_this_training(self):
        self.at_the_document_gate()
        for target in ('poster', 'document@101', 'scenario:missing', '../document', ''):
            with self.assertRaisesRegex(WorkspaceError, 'is not an? (stage or an )?artifact'):
                workspace.decide(self.root, target, 'approve', by='page')
            with self.assertRaisesRegex(WorkspaceError, 'is not a stage or an artifact'):
                workspace.decide(self.root, target, 'skip', 'Why', by='page')
        with self.assertRaisesRegex(WorkspaceError, 'A decision is one of'):
            workspace.decide(self.root, 'document', 'publish', by='page')

    def test_a_refused_decision_changes_nothing(self):
        self.at_the_document_gate()
        self.write('blueprint.md', helpers.CONTENT['blueprint'] + 'edited\n')
        before = workspace.session_path(self.root).read_text(encoding='utf-8')
        with self.assertRaisesRegex(WorkspaceError, 'blueprint is draft'):
            workspace.decide(self.root, 'document', 'approve', by='page')
        self.assertEqual(workspace.session_path(self.root).read_text(encoding='utf-8'), before)
        self.assertFalse((self.root / 'reviews').exists())


class LevelDecisionTests(LevelCase):
    def test_a_stage_decision_is_written_to_every_level_of_that_stage(self):
        self.through('document', '101', '301')
        workspace.skip(self.root, 'yoodli', reason='Not using it')
        workspace.decide(self.root, 'document@301', 'skip', 'Guides come later', by='page')
        state = self.state()
        self.assertEqual((state['document@101'], state['document@301']),
                         ('skipped', 'skipped'))
        for name in ('document-101', 'document-301'):
            text = (self.root / 'reviews' / f'{name}.md').read_text(encoding='utf-8')
            self.assertIn('its stage left out on the page', text)
        self.assertEqual(workspace.status(self.root)['next_step'],
                         'The learner guide stage was left out on the page: Guides come later')

    def test_a_level_artifact_is_named_in_plain_words(self):
        self.assertEqual(workspace.label('blueprint@301'), 'the level 301 blueprint')
        self.assertEqual(workspace.label('scenario:exec-cost@101'),
                         'the level 101 practice scenario "exec-cost"')
        self.assertEqual(workspace.label('yoodli:main'), 'the Yoodli scenario')
        self.assertEqual(workspace.review_file('scenario:exec-cost@101'),
                         'reviews/scenario-exec-cost-101.md')


class GateTests(PlainCase):
    """Which artifact is at the gate (matrix rows 93 and 94)."""

    def test_row_93_a_checkpoint_records_the_gate_and_no_question_clears_it(self):
        self.build('intake')
        outcome = workspace.checkpoint(self.root, gate='intake', question='Approve it?')
        self.assertEqual(outcome['gate'], 'intake')
        self.assertEqual(workspace.status(self.root)['gate'], 'intake')
        workspace.checkpoint(self.root, next_step='Still waiting')
        self.assertEqual(workspace.status(self.root)['gate'], 'intake')
        workspace.checkpoint(self.root, clear_question=True)
        report = workspace.status(self.root)
        self.assertEqual((report['gate'], report['pending_question']), (None, None))

    def test_row_94_the_gate_names_an_artifact_of_this_training(self):
        for gate in ('poster', 'blueprint@101', 'scenario:missing', 'session.json'):
            with self.assertRaisesRegex(WorkspaceError, 'cannot be at the gate'):
                workspace.checkpoint(self.root, gate=gate, stage='blueprint')
        report = workspace.status(self.root)
        self.assertEqual((report['gate'], report['stage']), (None, 'intake'))


class LevelCheckpointTests(LevelCase):
    def test_checkpoint_records_the_level_in_hand(self):
        workspace.checkpoint(self.root, stage='document', level='301')
        self.assertEqual(workspace.status(self.root)['level'], '301')
        with self.assertRaisesRegex(WorkspaceError, '101, 301'):
            workspace.checkpoint(self.root, level='201')
