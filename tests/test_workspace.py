"""Workspace behaviour. Tests named row_NN cover the state-transition matrix in the plan (A7)."""
import json
import os
import subprocess
import sys
from unittest import mock

import helpers
from helpers import CHAIN, TrainingCase
import workspace
from workspace import WorkspaceError


class PlainCase(TrainingCase):
    """A plain training with the optional Yoodli stage on, initialised."""

    def setUp(self):
        super().setUp()
        workspace.init(self.root, 'Topic', yoodli=True)


class LevelCase(TrainingCase):
    """A training with levels 101 and 301, initialised."""

    def setUp(self):
        super().setUp()
        workspace.init(self.root, 'Topic', levels=['301', '101'], yoodli=True)

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
        self.assertEqual(sorted(workspace.status(self.root)['exports']), ['brief', 'document'])

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


class LevelCheckpointTests(LevelCase):
    def test_checkpoint_records_the_level_in_hand(self):
        workspace.checkpoint(self.root, stage='document', level='301')
        self.assertEqual(workspace.status(self.root)['level'], '301')
        with self.assertRaisesRegex(WorkspaceError, '101, 301'):
            workspace.checkpoint(self.root, level='201')
