"""Format checks, run against the example files that the guidance uses as templates."""
import copy
import json
import unittest

import helpers
import checks


def example(name: str) -> str:
    return (helpers.EXAMPLES / name).read_text(encoding='utf-8')


BLUEPRINT = example('blueprint.md')
DOCUMENT = example('document.md')
SCENARIO = example('scenario.md')
YOODLI = example('yoodli.md')
PARSED = checks.parse_blueprint(BLUEPRINT)
OBJECTIVES = set(PARSED['objectives'])
PROFILE = json.loads((helpers.SKILL / 'assets' / 'profiles' / 'yoodli.json')
                     .read_text(encoding='utf-8'))


def named(results, name: str) -> dict:
    """The named check from a list of results or a lint report."""
    listed = results['checks'] if isinstance(results, dict) else results
    return next(item for item in listed if item['check'] == name)


def without_lines(text: str, *prefixes: str) -> str:
    return '\n'.join(line for line in text.splitlines()
                     if not line.startswith(prefixes)) + '\n'


def without_section(text: str, title: str) -> str:
    """A file with one `## ` section removed, whatever its number."""
    kept, skipping = [], False
    for line in text.splitlines():
        if line.startswith('## '):
            skipping = line[3:].split('. ', 1)[-1].strip() == title
        if not skipping:
            kept.append(line)
    return '\n'.join(kept) + '\n'


class BlueprintTests(unittest.TestCase):
    def lint(self, text=BLUEPRINT, findings=helpers.FINDINGS, level=None):
        return checks.lint_blueprint(text, findings, level)

    def test_the_example_passes_every_check(self):
        report = self.lint()
        self.assertEqual([item['status'] for item in report['checks']], ['passed'] * 4)
        self.assertEqual(report['warnings'], [])

    def test_parse_reads_objectives_modules_and_the_practice_plan(self):
        self.assertEqual(PARSED['objectives']['O3']['level'], 'handle')
        module = PARSED['modules']['M1']
        self.assertEqual((module['minutes'], module['objectives']), (25, ['O1', 'O2', 'O3']))
        self.assertEqual(module['key_points']['K1.2']['findings'],
                         ['availability', 'instance-min'])
        self.assertTrue(module['key_points']['K1.4']['unsupported'])
        self.assertEqual(PARSED['practice'],
                         [{'id': 'main', 'mode': 'roleplay', 'objectives': ['O1', 'O2', 'O3']}])

    def test_a_plain_hyphen_works_as_the_heading_separator(self):
        report = self.lint(BLUEPRINT.replace(' — ', ' - '))
        self.assertEqual(named(report, 'blueprint.structure')['status'], 'passed')

    def test_an_objective_without_a_level_is_not_understood(self):
        problems = named(self.lint(BLUEPRINT.replace(' [recall]', '')),
                         'blueprint.structure')['problems']
        self.assertIn('Not understood: ### O1 — Describe what a rolling restart does', problems)

    def test_a_duplicate_id_fails(self):
        report = self.lint(BLUEPRINT.replace('- K1.3:', '- K1.2:'))
        self.assertIn('Duplicate ID: K1.2', named(report, 'blueprint.structure')['problems'])

    def test_a_key_point_numbered_for_another_module_fails(self):
        report = self.lint(BLUEPRINT.replace('- K1.3:', '- K2.3:'))
        self.assertIn('K2.3 is under M1; its number should start K1.',
                      named(report, 'blueprint.structure')['problems'])

    def test_the_practice_plan_must_name_a_known_mode_and_objectives(self):
        report = self.lint(BLUEPRINT.replace('- main: roleplay. Objectives: O1, O2, O3.',
                                             '- main: debate. Objectives: O1, O9.'))
        problems = named(report, 'blueprint.structure')['problems']
        self.assertIn('Practice plan: main has unknown mode debate.', problems)
        self.assertIn('Practice plan: main names unknown objective O9.', problems)

    def test_the_practice_plan_is_optional(self):
        report = self.lint(without_section(BLUEPRINT, 'Practice plan'))
        self.assertEqual(named(report, 'blueprint.structure')['status'], 'passed')

    def test_row_50_a_levelled_blueprint_states_the_level_of_its_folder(self):
        levelled = BLUEPRINT.replace('Time: 25 min', 'Time: 25 min\nLevel: 201')
        self.assertEqual(named(self.lint(levelled, level='201'),
                               'blueprint.structure')['status'], 'passed')
        for text in (levelled, BLUEPRINT):
            self.assertIn('The frame must say "Level: 301", the level of its folder.',
                          named(self.lint(text, level='301'), 'blueprint.structure')['problems'])

    def test_an_objective_outside_every_module_fails(self):
        report = self.lint(BLUEPRINT.replace('Objectives: O1, O2, O3\n', 'Objectives: O1, O2\n'))
        self.assertIn('O3 is not in any module.',
                      named(report, 'blueprint.objectives')['problems'])

    def test_an_objective_needs_a_check_and_an_observation(self):
        for text in (without_lines(BLUEPRINT, '- O2: Check:'),
                     BLUEPRINT.replace('| Observe: Explains', '| Explains')):
            self.assertIn('O2 needs an assessment entry with "Check:" and "Observe:".',
                          named(self.lint(text), 'blueprint.objectives')['problems'])

    def test_a_key_point_without_a_citation_fails(self):
        report = self.lint(BLUEPRINT.replace(' [R:health-checks]', ''))
        self.assertIn('K1.3 cites no finding and is not marked [unsupported].',
                      named(report, 'blueprint.key-points')['problems'])

    def test_an_unsupported_point_must_be_listed_as_a_gap(self):
        report = self.lint(BLUEPRINT.replace('- K1.4: no evidence', '- No evidence'))
        self.assertIn('K1.4 is [unsupported] and must be listed under "## Open gaps".',
                      named(report, 'blueprint.key-points')['problems'])

    def test_a_module_needs_an_example(self):
        report = self.lint(without_lines(BLUEPRINT, 'Example:'))
        self.assertEqual(named(report, 'blueprint.key-points')['problems'],
                         ['M1 has no "Example:" line.'])

    def test_an_unknown_finding_fails(self):
        report = self.lint(BLUEPRINT.replace('[R:health-checks]', '[R:made-up]'))
        self.assertIn('K1.3 cites unknown finding made-up.',
                      named(report, 'blueprint.citations')['problems'])

    def test_a_key_point_cannot_rest_on_an_unresolved_finding(self):
        report = self.lint(BLUEPRINT.replace('[R:health-checks]', '[R:vendor-claim]'))
        self.assertIn('K1.3 cites vendor-claim, which is insufficient, not supported.',
                      named(report, 'blueprint.citations')['problems'])

    def test_only_a_correction_may_cite_a_contradicted_finding(self):
        self.assertEqual(named(self.lint(), 'blueprint.citations')['status'], 'passed')
        report = self.lint(BLUEPRINT.replace('[R:health-checks]', '[R:zero-downtime]'))
        self.assertEqual(named(report, 'blueprint.citations')['problems'],
                         ['K1.3 cites zero-downtime, which is contradicted, not supported.'])

    def test_citations_are_unavailable_without_a_findings_index(self):
        self.assertEqual(named(self.lint(findings=None), 'blueprint.citations')['status'],
                         'unavailable')

    def test_too_many_objectives_for_a_lesson_is_a_warning_not_a_failure(self):
        extra = ''.join(f'### O{n} — Recall fact {n} [recall]\n' for n in (4, 5, 6))
        text = BLUEPRINT.replace('## M1 —', extra + '\n## M1 —')
        text = text.replace('Objectives: O1, O2, O3\n', 'Objectives: O1, O2, O3, O4, O5, O6\n')
        self.assertEqual(self.lint(text)['warnings'],
                         ['M1 has 6 objectives; a lesson usually has 5 or fewer.'])

    def test_row_49_levels_that_repeat_an_objective_get_a_warning(self):
        other = checks.parse_blueprint(BLUEPRINT.replace(
            '### O2 — Explain when a rolling restart keeps capacity [explain]',
            '### O2 — Tune batch sizes for a large fleet [apply]'))
        warnings = checks.level_overlap({'101': PARSED, '301': other})
        self.assertEqual(warnings, [
            'Levels 101 and 301 both state the objective '
            '"Describe what a rolling restart does".',
            'Levels 101 and 301 both state the objective '
            '"Handle the objection that rolling restarts guarantee zero downtime".'])
        self.assertEqual(checks.level_overlap({'101': PARSED}), [])


class DocumentTests(unittest.TestCase):
    def test_the_example_covers_the_blueprint_by_declaration(self):
        result = checks.document_coverage(PARSED, DOCUMENT)
        self.assertEqual((result['check'], result['status'], result['basis']),
                         ('document.coverage', 'passed', 'declared'))

    def test_an_uncovered_objective_and_key_point_fail(self):
        result = checks.document_coverage(
            PARSED, DOCUMENT.replace('<!-- covers: O2 K1.2 -->', ''))
        self.assertEqual(result['problems'], ['K1.2 is not covered by any section.',
                                              'O2 is not covered by any section.'])

    def test_an_unsupported_key_point_must_not_be_taught(self):
        result = checks.document_coverage(
            PARSED, DOCUMENT.replace('covers: O2 K1.2', 'covers: O2 K1.2 K1.4'))
        self.assertEqual(result['problems'], ['K1.4 is [unsupported] and must not be taught.'])

    def test_an_id_that_is_not_in_the_blueprint_fails(self):
        result = checks.document_coverage(
            PARSED, DOCUMENT.replace('covers: O2 K1.2', 'covers: O2 K1.2 O9'))
        self.assertEqual(result['problems'], ['O9 is not in the blueprint.'])


class BriefTests(unittest.TestCase):
    PRODUCT = example('product-brief.md')
    COMPETITIVE = example('competitive-brief.md')

    def check(self, text, kind='product', findings=helpers.FINDINGS):
        return checks.check_brief(text, kind, findings)

    def test_both_examples_pass(self):
        for text, kind in ((self.PRODUCT, 'product'), (self.COMPETITIVE, 'competitive')):
            self.assertEqual([item['status'] for item in self.check(text, kind)],
                             ['passed', 'passed'], kind)

    def test_a_brief_of_the_wrong_kind_fails(self):
        problems = named(self.check(self.PRODUCT, 'competitive'), 'brief.sections')['problems']
        self.assertIn('The title must start with "# Competitive brief:".', problems)
        self.assertIn('Section "Comparison" is missing.', problems)

    def test_a_missing_section_fails(self):
        result = named(self.check(without_section(self.PRODUCT, 'Limitations')),
                       'brief.sections')
        self.assertEqual(result['problems'], ['Section "Limitations" is missing.'])

    def test_unknowns_may_not_be_left_empty(self):
        start = self.PRODUCT.index('## 7. Unknowns')
        end = self.PRODUCT.index('## 8. Sources')
        text = self.PRODUCT[:start] + '## 7. Unknowns\n\n' + self.PRODUCT[end:]
        self.assertEqual(named(self.check(text), 'brief.sections')['problems'],
                         ['Section "Unknowns" is empty.'])

    def test_a_section_holding_only_its_comment_is_empty(self):
        start = self.PRODUCT.index('## 4. Limitations')
        end = self.PRODUCT.index('## 5. Qualification questions')
        text = (self.PRODUCT[:start] + '## 4. Limitations\n\n<!-- findings: instance-min -->\n\n'
                + self.PRODUCT[end:])
        self.assertEqual(named(self.check(text), 'brief.sections')['problems'],
                         ['Section "Limitations" is empty.'])

    def test_sections_out_of_order_fail(self):
        start = self.PRODUCT.index('## 7. Unknowns')
        end = self.PRODUCT.index('## 8. Sources')
        moved = self.PRODUCT[:start] + self.PRODUCT[end:] + '\n' + self.PRODUCT[start:end]
        problems = named(self.check(moved), 'brief.sections')['problems']
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith('Sections are out of order'))

    def test_an_evidence_section_must_name_a_finding(self):
        text = self.PRODUCT.replace('<!-- findings: availability health-checks -->\n', '')
        self.assertEqual(named(self.check(text), 'brief.findings')['problems'],
                         ['Section "Capabilities" names no findings.'])

    def test_unknown_and_unresolved_findings_fail(self):
        text = self.PRODUCT.replace('<!-- findings: availability health-checks -->',
                                    '<!-- findings: made-up vendor-claim -->')
        self.assertEqual(named(self.check(text), 'brief.findings')['problems'], [
            'Section "Capabilities" names unknown finding made-up.',
            'Section "Capabilities" rests on vendor-claim, which is insufficient.'])

    def test_a_contradicted_finding_is_allowed_only_under_objections(self):
        self.assertEqual(named(self.check(self.PRODUCT), 'brief.findings')['status'], 'passed')
        text = self.PRODUCT.replace('<!-- findings: availability health-checks -->',
                                    '<!-- findings: zero-downtime -->')
        self.assertEqual(named(self.check(text), 'brief.findings')['problems'],
                         ['Section "Capabilities" rests on zero-downtime, which is contradicted.'])

    def test_findings_are_unavailable_without_an_index(self):
        result = named(self.check(self.PRODUCT, findings=None), 'brief.findings')
        self.assertEqual(result['status'], 'unavailable')


class ScenarioTests(unittest.TestCase):
    def test_the_example_passes(self):
        result = checks.check_scenario(SCENARIO, 'scenario:main')
        self.assertEqual((result['check'], result['status']),
                         ('scenario:main.sections', 'passed'))

    def test_parse_numbers_the_success_criteria(self):
        scenario = checks.parse_scenario(SCENARIO)
        self.assertEqual(scenario['title'], 'The zero-downtime objection')
        self.assertEqual(scenario['mode'], 'roleplay')
        self.assertEqual(len(scenario['criteria']), 4)
        self.assertEqual(scenario['criteria'][3], 'Leaves with an agreed next step.')

    def test_the_mode_defaults_to_roleplay(self):
        text = without_section(SCENARIO, 'Mode')
        self.assertEqual(checks.parse_scenario(text)['mode'], 'roleplay')
        self.assertEqual(checks.check_scenario(text, 'scenario:main')['status'], 'passed')

    def test_each_required_section_is_required(self):
        for title in checks.SCENARIO_REQUIRED:
            result = checks.check_scenario(without_section(SCENARIO, title), 'scenario:main')
            self.assertEqual(result['problems'], [f'Section "{title}" is missing or empty.'])

    def test_optional_sections_are_optional(self):
        text = SCENARIO
        for title in ('Concerns and pushback', 'Constraints', 'Session settings'):
            text = without_section(text, title)
        self.assertEqual(checks.check_scenario(text, 'scenario:main')['status'], 'passed')

    def test_success_criteria_must_be_a_list(self):
        start = SCENARIO.index('## Success criteria')
        end = SCENARIO.index('## Constraints')
        text = SCENARIO[:start] + '## Success criteria\n\nDo well.\n\n' + SCENARIO[end:]
        self.assertEqual(checks.check_scenario(text, 'scenario:main')['problems'],
                         ['Success criteria must be a list, one criterion per item.'])

    def test_an_unknown_mode_and_a_missing_title_fail(self):
        text = SCENARIO.replace('\nroleplay\n', '\ndebate\n').replace('# Scenario:', '# Notes:')
        self.assertEqual(checks.check_scenario(text, 'scenario:main')['problems'], [
            'The file must start with "# Scenario: <name>".',
            'Mode "debate" is not one of: roleplay, pitch, tutor, questionnaire'])


class YoodliTests(unittest.TestCase):
    scenario = checks.parse_scenario(SCENARIO)

    def check(self, text=YOODLI, profile=PROFILE, scenario=None, objectives=OBJECTIVES):
        return checks.check_yoodli(text, profile, scenario or self.scenario, objectives,
                                   'yoodli:main')

    def problems(self, part: str, text: str) -> list:
        return named(self.check(text), f'yoodli:main.{part}')['problems']

    def test_the_example_passes_and_reports_counts(self):
        results = self.check()
        self.assertEqual([(item['check'], item['status']) for item in results],
                         [('yoodli:main.fields', 'passed'), ('yoodli:main.limits', 'passed'),
                          ('yoodli:main.mapping', 'passed')])
        counts = named(results, 'yoodli:main.limits')['counts']
        self.assertEqual(counts['Context'], 666)
        self.assertEqual(counts['Goal 1 Explanation'], 65)

    def test_the_example_states_its_real_counts(self):
        counts = named(self.check(), 'yoodli:main.limits')['counts']
        self.assertIn(f"{counts['Context']} of 10,000 characters", YOODLI)
        self.assertIn(f"{counts['Goal 3 Achieved']} of 1,000 characters", YOODLI)

    def test_limits_are_provisional_until_verified(self):
        self.assertTrue(named(self.check(), 'yoodli:main.limits')['provisional'])
        verified = copy.deepcopy(PROFILE)
        for limit in verified['limits'].values():
            limit['verified'] = '2026-11-01'
        self.assertFalse(named(self.check(profile=verified),
                               'yoodli:main.limits')['provisional'])

    def test_fenced_fields_are_keyed_by_their_headings(self):
        fields, problems = checks.fenced_fields(YOODLI)
        self.assertEqual(problems, [])
        self.assertEqual(fields[('Type',)], 'Objection Handling')
        self.assertEqual(fields[('Personas', 'Persona 1', 'Name')], 'Priya Nair')
        self.assertEqual(fields[('Goals', 'Goal 2', 'Type')], 'Rated')

    def test_a_persona_needs_every_field(self):
        start, end = YOODLI.index('#### Role'), YOODLI.index('## Objections')
        self.assertEqual(self.problems('fields', YOODLI[:start] + YOODLI[end:]), [
            f'Persona 1: field "{field}" is missing or empty.'
            for field in ('Role', 'Demeanor', 'Background', 'Behaviors')])

    def test_objection_handling_needs_a_persona(self):
        start, end = YOODLI.index('### Persona 1'), YOODLI.index('## Objections')
        self.assertIn('Type "Objection Handling" needs at least one persona.',
                      self.problems('fields', YOODLI[:start] + YOODLI[end:]))

    def test_a_duplicate_heading_fails(self):
        goal = YOODLI[YOODLI.index('### Goal 1'):YOODLI.index('### Goal 2')]
        problems = self.problems('fields', YOODLI.replace('### Goal 2', goal + '### Goal 2'))
        self.assertIn('Heading "Goals / Goal 1" appears more than once.', problems)

    def test_an_unterminated_fence_fails(self):
        cut = YOODLI[:YOODLI.rindex('```')]
        self.assertIn('A fenced block is never closed.', self.problems('fields', cut))

    def test_the_type_must_match_the_scenario_mode(self):
        tutor = dict(self.scenario, mode='tutor')
        problems = named(self.check(scenario=tutor), 'yoodli:main.fields')['problems']
        self.assertEqual(problems, ['Type "Objection Handling" does not match the scenario '
                                    'mode tutor; expected "Tutor".'])

    def test_unknown_types_fail(self):
        text = YOODLI.replace('Objection Handling\n```', 'Debate\n```')
        text = text.replace('```text\nBinary\n```', '```text\nGraded\n```')
        problems = self.problems('fields', text)
        self.assertTrue(any(item.startswith('Type "Debate" is not one of') for item in problems))
        self.assertTrue(any(item.startswith('Goal 1: type "Graded" is not one of')
                            for item in problems))

    def test_a_missing_required_field_fails(self):
        text = YOODLI.replace('```text\nThe zero-downtime objection\n```', '', 1)
        self.assertIn('Field "Roleplay name" is missing or empty.',
                      self.problems('fields', text))

    def test_a_brief_with_no_goals_fails(self):
        self.assertIn('At least one goal is required.',
                      self.problems('fields', YOODLI[:YOODLI.index('## Goals')]))

    def test_each_limit_is_enforced_with_its_count(self):
        over = YOODLI.replace('You are Priya Nair', 'x' * 10000 + ' You are', 1)
        self.assertEqual(self.problems('limits', over),
                         ['Context is 10656 characters; the limit is 10000.'])
        over = YOODLI.replace('States the batch-by-batch', 'y' * 1000 + ' States')
        self.assertEqual(self.problems('limits', over),
                         ['Goal 1: Achieved is 1039 characters; the limit is 1000.'])
        persona = YOODLI[YOODLI.index('### Persona 1'):YOODLI.index('## Objections')]
        extra = ''.join(persona.replace('Persona 1', f'Persona {n}') for n in (2, 3, 4))
        self.assertEqual(self.problems('limits', YOODLI.replace('## Objections',
                                                                extra + '## Objections')),
                         ['4 personas; the limit is 3.'])

    def test_every_success_criterion_must_be_carried_by_a_goal(self):
        text = YOODLI.replace('<!-- criterion: 3 4 -->', '<!-- criterion: 3 -->')
        self.assertEqual(self.problems('mapping', text), [
            'Success criterion 4 is not carried by any goal: '
            '"Leaves with an agreed next step."'])

    def test_a_goal_must_name_a_criterion_that_exists(self):
        self.assertEqual(self.problems('mapping', YOODLI.replace('criterion: 2 ', 'criterion: 9 ')),
                         ['Goal 2 names criterion 9; the scenario has 4.',
                          'Success criterion 2 is not carried by any goal: '
                          '"Explains that capacity holds only with more than one instance."'])
        text = YOODLI.replace('<!-- criterion: 1 -->\n', '')
        self.assertEqual(self.problems('mapping', text), [
            'Goal 1 names no success criterion.',
            'Success criterion 1 is not carried by any goal: '
            '"Describes what a rolling restart does."'])

    def test_a_goal_may_only_assess_a_known_objective(self):
        self.assertEqual(self.problems('mapping', YOODLI.replace('assesses: O3', 'assesses: O9')),
                         ['Goal 3 assesses unknown objective O9.'])

    def test_the_file_must_name_its_scenario(self):
        self.assertEqual(self.problems('mapping', YOODLI.replace('scenario: main', 'scenario: x')),
                         ['The file must name its scenario with <!-- scenario: main -->.'])

    def test_mapping_is_unavailable_without_its_scenario_or_blueprint(self):
        missing = checks.check_yoodli(YOODLI, PROFILE, None, OBJECTIVES, 'yoodli:main')
        self.assertEqual(named(missing, 'yoodli:main.mapping')['status'], 'unavailable')
        missing = checks.check_yoodli(YOODLI, PROFILE, self.scenario, None, 'yoodli:main')
        self.assertEqual(named(missing, 'yoodli:main.mapping')['status'], 'unavailable')


class DeckAndPracticeTests(unittest.TestCase):
    REVIEW = {'deck_sha256': 'deck-1', 'blueprint_sha256': 'blueprint-1', 'at': 'then',
              'objectives': {'O1': [3], 'O2': [5, 6], 'O3': []}}

    def test_deck_coverage_is_unavailable_until_reviewed(self):
        result = checks.deck_coverage(PARSED, None, 'deck-1', 'blueprint-1')
        self.assertEqual(result['status'], 'unavailable')

    def test_deck_coverage_reports_the_review(self):
        result = checks.deck_coverage(PARSED, self.REVIEW, 'deck-1', 'blueprint-1')
        self.assertEqual((result['check'], result['status'], result['basis'], result['problems']),
                         ('deck.coverage', 'failed', 'reviewed',
                          ['O3 was not found in the deck.']))

    def test_a_review_of_another_deck_or_blueprint_does_not_count(self):
        for deck, blueprint in (('deck-2', 'blueprint-1'), ('deck-1', 'blueprint-2')):
            result = checks.deck_coverage(PARSED, self.REVIEW, deck, blueprint)
            self.assertEqual(result['status'], 'unavailable')
            self.assertIn('review the deck again', result['problems'][0])

    def test_practice_reports_what_the_scenarios_exercise(self):
        self.assertEqual(checks.practice(PARSED, [YOODLI]),
                         {'exercised': ['O1', 'O2', 'O3'], 'not_exercised': [], 'warnings': []})

    def test_an_unexercised_handle_objective_is_a_warning(self):
        report = checks.practice(PARSED, [YOODLI.replace('<!-- assesses: O3 -->\n', '')])
        self.assertEqual(report['not_exercised'], ['O3'])
        self.assertEqual(report['warnings'],
                         ['O3 is a handle objective that no scenario exercises.'])
        self.assertEqual(checks.practice(PARSED, [])['not_exercised'], ['O1', 'O2', 'O3'])
