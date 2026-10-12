"""The command line, including the check aggregation and readiness (matrix rows that name check)."""
import contextlib
import io
import json
import subprocess
import sys

import helpers
from helpers import TrainingCase
import training

CLI = helpers.SCRIPTS / 'training.py'


def example(name: str) -> str:
    return (helpers.EXAMPLES / name).read_text(encoding='utf-8')


def levelled(text: str, level: str) -> str:
    return text.replace('Time: 25 min', f'Time: 25 min\nLevel: {level}')


COURSE_BLUEPRINT = (
    example('blueprint.md')
    .replace('\n## M1 —', '### O4 — Describe what a health check reports [recall]\n'
             '### O5 — Explain how health checks pace a restart [explain]\n'
             '### O6 — Choose a health check for a slow-starting app [apply]\n\n## M1 —')
    .replace('\n## Assessment plan\n', '\n## M2 — Health checks (20 min)\n'
             'Objectives: O4, O5, O6\n'
             '- K2.1: A health check reports whether an instance can serve. [R:health-checks]\n'
             '- K2.2: A restart continues only when new instances pass. [R:health-checks]\n'
             'Example: An app that takes ninety seconds to start.\n\n## Assessment plan\n')
    .replace('\n## Practice plan\n', '- O4: Check: What does a health check report? | Observe: '
             'States readiness to serve.\n- O5: Check: How do health checks pace a restart? | '
             'Observe: Links passing checks to the next batch.\n- O6: Check: Which check suits '
             'a slow app? | Observe: Picks one and says why.\n\n## Practice plan\n'))
COURSE_DOCUMENT = (example('document.md')
                   + '\n## Health checks\n\n<!-- covers: O4 O5 O6 K2.1 K2.2 -->\n\nText.\n')


class Flow(TrainingCase):
    """Drives the helper the way the assistant does, in process."""

    def cli(self, *args, expect=0) -> dict:
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            try:
                code = training.main(['--dir', str(self.root), *args])
            except SystemExit as stopped:
                code = stopped.code
        self.assertEqual(code, expect, captured.getvalue())
        return json.loads(captured.getvalue())

    def make(self, artifact: str, relative: str, text: str) -> None:
        """Write an artifact's file, save it as built and approve it."""
        self.write(relative, text)
        self.cli('save', artifact, '--built')
        self.cli('approve', artifact)

    def research(self, *init_args) -> None:
        self.cli('init', '--title', 'Rolling restarts', *init_args)
        self.make('intake', 'intake.md', '# Intake\n\n## Topic\nRolling restarts\n')
        plan = {'topic': 'Rolling restarts', 'items': helpers.RESEARCH['items']}
        self.make('research-plan', '.training-studio/research-plan.json', json.dumps(plan))
        self.write('.harness-research/research.json', json.dumps(helpers.RESEARCH))
        self.make('research', '.harness-research/research-report.md', '# Research brief\n')

    def content(self, level: str | None = None, blueprint: str | None = None,
                document: str | None = None) -> None:
        """Blueprint, document and brief for one level, with the two exports."""
        at = f'@{level}' if level else ''
        folder = f'{level}/' if level else ''
        text = blueprint or example('blueprint.md')
        self.make(f'blueprint{at}', f'{folder}blueprint.md',
                  levelled(text, level) if level else text)
        self.make(f'document{at}', f'{folder}document.md', document or example('document.md'))
        self.make(f'brief{at}', f'{folder}product-brief.md', example('product-brief.md'))
        for name in ('document', 'product-brief'):
            self.write(f'{folder}{name}.docx', f'exported {name}')
        self.cli('export', f'document{at}')
        self.cli('export', f'brief{at}')

    def deck(self, level: str | None = None, objectives=('O1', 'O2', 'O3')) -> None:
        at = f'@{level}' if level else ''
        folder = f'{level}/' if level else ''
        self.write(f'{folder}deck.pptx', 'stand-in for a built deck')
        coverage = self.root.parent / 'coverage.json'
        coverage.write_text(json.dumps({objective: [2] for objective in objectives}))
        self.cli('save', f'deck{at}', '--built', '--coverage', str(coverage))
        self.cli('approve', f'deck{at}')

    def scenario(self, level: str | None = None) -> None:
        at = f'@{level}' if level else ''
        folder = f'{level}/' if level else ''
        self.make(f'scenario:main{at}', f'{folder}scenario.md', example('scenario.md'))
        self.make(f'yoodli:main{at}', f'{folder}yoodli/main.md', example('yoodli.md'))

    def complete(self, level: str | None = None) -> None:
        self.content(level)
        self.deck(level)
        self.scenario(level)

    def check(self, *args, expect=0) -> dict:
        return self.cli('check', *args, expect=expect)

    def by_name(self, report: dict) -> dict:
        return {item['check']: item for item in report['checks']}


class ContractTests(TrainingCase):
    """The promises every command keeps, checked in a real subprocess."""

    def run_cli(self, *args, expect=0):
        done = subprocess.run([sys.executable, str(CLI), *args], cwd=self.root,
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, expect, done.stdout + done.stderr)
        return json.loads(done.stdout)

    def test_status_before_init_is_a_refusal_with_exit_code_2(self):
        self.assertEqual(self.run_cli('status', expect=2),
                         {'error': 'No training in this directory. Run init first.'})

    def test_init_works_from_the_current_directory(self):
        report = self.run_cli('init', '--title', 'Valkey', '--levels', '301,101',
                              '--brief-kind', 'competitive')
        self.assertEqual(report['levels'], ['101', '301'])
        self.assertEqual(report['files']['brief@101'], '101/competitive-brief.md')
        self.assertEqual(report['artifacts']['blueprint@301'], 'not-started')

    def test_row_35_a_broken_record_is_a_structured_error(self):
        self.run_cli('init', '--title', 'Topic')
        record = self.root / '.training-studio' / 'session.json'
        record.write_text('{not json')
        for command in (('status',), ('check',), ('save', 'intake')):
            self.assertIn('not valid JSON', self.run_cli(*command, expect=2)['error'])
        self.assertEqual(record.read_text(), '{not json')

    def test_usage_errors_are_json_too(self):
        self.assertIn('artifact', self.run_cli('save', expect=2)['error'])
        self.assertIn('invalid choice', self.run_cli('publish', expect=2)['error'])

    def test_unreadable_input_is_a_structured_error(self):
        self.run_cli('init', '--title', 'Topic')
        self.write('deck.pptx', 'deck')
        bad = self.write('coverage.json', '{not json')
        self.assertIn('error', self.run_cli('save', 'deck', '--coverage', str(bad), expect=2))
        missing = self.run_cli('save', 'deck', '--coverage', 'nowhere.json', expect=2)
        self.assertIn('FileNotFoundError', missing['error'])


class CommandTests(Flow):
    def test_approving_research_warns_about_pending_questions(self):
        self.cli('init', '--title', 'Rolling restarts')
        self.make('intake', 'intake.md', 'v1\n')
        self.make('research-plan', '.training-studio/research-plan.json', '{}')
        self.write('.harness-research/research.json', json.dumps(helpers.RESEARCH))
        self.write('.harness-research/research-report.md', '# Research brief\n')
        self.cli('save', 'research', '--built')
        approved = self.cli('approve', 'research')
        self.assertEqual(approved['warnings'], ['Research questions still pending: rollback'])

    def test_save_from_replaces_the_file_and_makes_dependents_stale(self):
        self.research()
        self.content()
        revised = self.root.parent / 'revised.md'
        revised.write_text(example('blueprint.md') + '\nRevised.\n')
        self.assertEqual(self.cli('save', 'blueprint', '--from', str(revised))['status'], 'draft')
        self.assertEqual(self.cli('status')['stale'], ['document', 'brief'])

    def test_a_stale_artifact_needs_the_users_reason(self):
        self.research()
        self.content()
        revised = self.root.parent / 'revised.md'
        revised.write_text(example('blueprint.md') + '\nRevised.\n')
        self.cli('save', 'blueprint', '--from', str(revised))
        self.cli('approve', 'blueprint')
        self.assertIn('older version', self.cli('approve', 'document', expect=2)['error'])
        self.cli('approve', 'document', '--accept-stale', 'Only a note was added')
        self.assertEqual(self.cli('status')['artifacts']['document'], 'approved')

    def test_settings_skips_pins_and_checkpoints_round_trip(self):
        self.cli('init', '--title', 'Topic', '--levels', '101')
        self.cli('checkpoint', '--stage', 'blueprint', '--level', '101', '--next', 'Draft it',
                 '--question', 'Approve?', '--brand', 'Tanzu', '--deck-target', 'google',
                 '--levels', '101,201')
        self.cli('pin', 'harness-research', '--task', 't-1', '--runtime', '/opt/r')
        self.cli('skip', 'deck', '--reason', 'Not needed')
        report = self.cli('status')
        self.assertEqual((report['stage'], report['level'], report['levels']),
                         ('blueprint', '101', ['101', '201']))
        self.assertEqual(report['pending_question'], 'Approve?')
        self.assertEqual(report['settings']['brand'], 'Tanzu')
        self.assertEqual(report['files']['deck@201'], '201/deck-link.md')
        self.assertEqual(report['artifacts']['deck@101'], 'skipped')
        self.assertEqual(report['pins']['harness-research']['task'], 't-1')
        self.assertIn('Only these stages', self.cli('skip', 'research', '--reason', 'x',
                                                    expect=2)['error'])

    def test_exports_are_recorded_and_reported(self):
        self.research()
        self.content()
        self.assertEqual(self.cli('status')['exports'],
                         {'document': 'current', 'brief': 'current'})
        self.cli('export', 'document', '--unavailable', 'No converter')
        self.assertEqual(self.cli('status')['exports']['document'], 'unavailable')


class CheckTests(Flow):
    def test_row_32_a_blueprint_alone_passes_its_checks_but_is_not_ready(self):
        self.research()
        self.make('blueprint', 'blueprint.md', example('blueprint.md'))
        report = self.check()
        self.assertTrue(report['checks_passed'])
        self.assertFalse(report['ready'])
        self.assertEqual((report['passed'], report['checks']), (4, []))
        for reason in ('document is not-started', 'brief is not-started',
                       'deck is not-started', 'No scenario file found.'):
            self.assertIn(reason, report['blocking'])
        self.check('--complete', expect=1)

    def test_check_before_a_blueprint_reports_what_is_missing(self):
        self.cli('init', '--title', 'Rolling restarts')
        report = self.check()
        self.assertEqual((report['checks_passed'], report['ready'], report['passed']),
                         (True, False, 0))
        self.assertIn('intake is not-started', report['blocking'])

    def test_a_scenario_is_checked_before_any_blueprint_exists(self):
        self.cli('init', '--title', 'Rolling restarts')
        self.write('scenario.md', example('scenario.md').replace('## Opening', '## Start'))
        report = self.check(expect=1)
        self.assertEqual(self.by_name(report)['scenario:main.sections']['problems'],
                         ['Section "Opening" is missing or empty.'])

    def test_a_lesson_reaches_ready(self):
        self.research()
        self.complete()
        report = self.check('--complete')
        self.assertEqual((report['checks_passed'], report['ready'], report['blocking']),
                         (True, True, []))
        self.assertEqual(report['passed'], 12)
        self.assertEqual(report['checks'], [])
        self.assertEqual(report['limitations'], ['yoodli:main has no export'])
        self.assertEqual(report['practice'],
                         {'exercised': ['O1', 'O2', 'O3'], 'not_exercised': []})
        self.assertEqual(len(report['warnings']), 1)
        self.assertIn('provisional', report['warnings'][0])
        everything = self.check('--all')
        self.assertEqual(len(everything['checks']), 12)
        self.assertEqual(self.by_name(everything)['document.coverage']['basis'], 'declared')

    def test_a_two_module_course_reaches_ready(self):
        self.research()
        self.content(blueprint=COURSE_BLUEPRINT, document=COURSE_DOCUMENT)
        self.deck(objectives=('O1', 'O2', 'O3', 'O4', 'O5', 'O6'))
        self.scenario()
        report = self.check('--complete')
        self.assertTrue(report['ready'], report['blocking'])
        self.assertEqual(self.cli('status')['sizing'][''],
                         {'size': 'course', 'modules': ['m1', 'm2']})
        self.assertEqual(report['practice']['not_exercised'], ['O4', 'O5', 'O6'])

    def test_a_failed_check_blocks_and_sets_the_exit_code(self):
        self.research()
        broken = example('blueprint.md').replace('[R:health-checks]', '[R:made-up]')
        self.write('blueprint.md', broken)
        self.cli('save', 'blueprint', '--built')
        report = self.check(expect=1)
        self.assertFalse(report['checks_passed'])
        self.assertEqual([item['check'] for item in report['checks']], ['blueprint.citations'])
        self.assertIn('blueprint.citations failed', report['blocking'])

    def test_a_check_that_cannot_run_blocks_readiness(self):
        self.cli('init', '--title', 'Rolling restarts')
        self.write('blueprint.md', example('blueprint.md'))
        report = self.check()
        self.assertTrue(report['checks_passed'])
        self.assertTrue(any(reason.startswith('blueprint.citations could not run')
                            for reason in report['blocking']))

    def test_row_20_replacing_the_deck_voids_its_coverage_review(self):
        self.research()
        self.complete()
        self.write('deck.pptx', 'a different deck')
        self.cli('save', 'deck', '--built')
        report = self.check()
        self.assertEqual(self.by_name(report)['deck.coverage']['status'], 'unavailable')
        self.assertFalse(report['ready'])

    def test_row_21_changing_the_blueprint_voids_the_coverage_review(self):
        self.research()
        self.complete()
        self.write('blueprint.md', example('blueprint.md') + '\nA note.\n')
        self.assertEqual(self.by_name(self.check())['deck.coverage']['status'], 'unavailable')

    def test_row_25_an_unavailable_brief_export_is_a_limitation(self):
        self.research()
        self.complete()
        self.cli('export', 'brief', '--unavailable', 'No converter on this machine')
        report = self.check('--complete')
        self.assertTrue(report['ready'])
        self.assertIn('Yoodli handoff incomplete: no export of brief', report['limitations'])

    def test_a_missing_brief_export_blocks_when_scenarios_are_wanted(self):
        self.research()
        self.complete()
        (self.root / 'product-brief.docx').unlink()
        report = self.check('--complete', expect=1)
        self.assertEqual(report['blocking'], ['brief has no export, and the Yoodli scenario '
                                              'names it as the file to upload'])

    def test_an_outdated_export_blocks(self):
        self.research()
        self.complete()
        self.write('document.docx', 'someone re-exported an older draft')
        self.assertIn('The export of document is out of date', self.check()['blocking'])

    def test_row_27_a_deleted_file_is_not_ready(self):
        self.research()
        self.complete()
        (self.root / 'document.md').unlink()
        report = self.check('--complete', expect=1)
        self.assertIn('document is not-started', report['blocking'])

    def test_row_28_the_done_marker_does_not_override_readiness(self):
        self.research()
        self.complete()
        self.cli('checkpoint', '--stage', 'done')
        self.assertTrue(self.check()['ready'])
        self.write('product-brief.md', example('product-brief.md') + '\nA late edit.\n')
        report = self.check('--complete', expect=1)
        self.assertIn('brief is draft', report['blocking'])
        self.assertIn('yoodli:main is stale', report['blocking'])
        self.assertEqual(self.cli('status')['stage'], 'done')

    def test_row_31_an_unavailable_deck_is_a_limitation_not_a_blocker(self):
        self.research()
        self.cli('skip', 'deck', '--unavailable', '--reason', 'harness-slides is not installed')
        self.content()
        self.scenario()
        report = self.check('--complete')
        self.assertTrue(report['ready'])
        self.assertIn('deck unavailable: harness-slides is not installed',
                      report['limitations'])

    def test_skipped_stages_are_limitations(self):
        self.research()
        self.cli('skip', 'scenario', '--reason', 'Later')
        self.cli('skip', 'brief', '--reason', 'Later')
        self.cli('skip', 'deck', '--reason', 'Later')
        self.make('blueprint', 'blueprint.md', example('blueprint.md'))
        self.make('document', 'document.md', example('document.md'))
        report = self.check('--complete')
        self.assertTrue(report['ready'])
        self.assertEqual(report['limitations'][:3],
                         ['brief was skipped', 'deck was skipped', 'scenario was skipped'])
        self.assertEqual(report['practice'], {})


class LevelCheckTests(Flow):
    def test_row_48_one_unfinished_level_blocks_the_training(self):
        self.research('--levels', '101,301')
        self.complete('101')
        report = self.check('--complete', expect=1)
        self.assertTrue(report['checks_passed'])
        self.assertIn('blueprint@301 is not-started', report['blocking'])
        self.assertIn('No scenario file found for level 301.', report['blocking'])
        self.assertFalse(any('@101' in reason for reason in report['blocking']))
        self.assertEqual(report['practice'],
                         {'101': {'exercised': ['O1', 'O2', 'O3'], 'not_exercised': []}})

    def test_both_levels_complete_is_ready(self):
        self.research('--levels', '101,301')
        self.complete('101')
        self.complete('301')
        report = self.check('--complete', '--all')
        self.assertTrue(report['ready'], report['blocking'])
        self.assertIn('yoodli:main.mapping@301', self.by_name(report))

    def test_row_49_repeated_objectives_across_levels_are_a_warning(self):
        self.research('--levels', '101,301')
        self.make('blueprint@101', '101/blueprint.md', levelled(example('blueprint.md'), '101'))
        self.make('blueprint@301', '301/blueprint.md', levelled(example('blueprint.md'), '301'))
        report = self.check()
        self.assertTrue(report['checks_passed'])
        overlap = [text for text in report['warnings'] if text.startswith('Levels 101 and 301')]
        self.assertEqual(len(overlap), 3)

    def test_row_50_a_blueprint_in_the_wrong_folder_fails(self):
        self.research('--levels', '101,301')
        self.write('301/blueprint.md', levelled(example('blueprint.md'), '201'))
        report = self.check(expect=1)
        failed = self.by_name(report)['blueprint.structure@301']
        self.assertEqual(failed['problems'],
                         ['The frame must say "Level: 301", the level of its folder.'])
