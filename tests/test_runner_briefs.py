"""The briefs: what a worker is told. A worker has only the worker tools, so a brief may
name nothing else, and each must say how to hand back and when to stop."""
import json
import re
import unittest

import helpers
from runner_support import BLUEPRINT, BRIEF, DOCUMENT, SCENARIO, YOODLI, JobCase

import checks
import workspace
from runner import agents, briefs, worker_tools
from workspace import WorkspaceError

EVERY = {'research-plan': briefs.guidance('research-plan'),
         'research-question': briefs.guidance('research-question'),
         'blueprint': briefs.guidance('blueprint'),
         'blueprint@301': briefs.guidance('blueprint', level='301'),
         'document': briefs.guidance('document'),
         'document@301': briefs.guidance('document', level='301'),
         'brief': briefs.guidance('brief', kind='product'),
         'brief:competitive@301': briefs.guidance('brief', level='301', kind='competitive'),
         'scenario': briefs.guidance('scenario'),
         'yoodli': briefs.guidance('yoodli')}
DRAFTS = [name for name in EVERY if name != 'research-question']
COMPETITIVE = (helpers.EXAMPLES / 'competitive-brief.md').read_text(encoding='utf-8')
EXAMPLES = {'blueprint': BLUEPRINT, 'blueprint@301': BLUEPRINT, 'document': DOCUMENT,
            'document@301': DOCUMENT, 'brief': BRIEF, 'brief:competitive@301': COMPETITIVE,
            'scenario': SCENARIO, 'yoodli': YOODLI}
TOOL_LIKE = re.compile(r'`((?:list|read|submit|save|search|ask)_[a-z_]+)`')
FILE_NAME = re.compile(r'\b[\w-]+\.(?:md|json|py|mjs|txt|docx|pptx|pdf|yaml|toml)\b')
PATH = re.compile(r'\w/\w|\.training-studio|\.harness|~/')
COMMAND = re.compile(r'training\.py|harness-research|harness-slides|\bnode\b|\bpython|'
                     r'(?<![\w-])--[a-z]|\bgit\b|\bcurl\b|\$\(')
A_HARNESS = re.compile(r'WebSearch|WebFetch|\bClaude\b|\bCodex\b|\bBash\b|\bMCP\b|\bskill\b',
                       re.IGNORECASE)


def own(text: str) -> str:
    """A brief without the core's example at its end, which is the core's to word."""
    return text.partition('\n## The example\n')[0]


class BriefTests(JobCase):
    def test_there_is_a_brief_for_each_job_and_no_other(self):
        self.assertEqual(briefs.JOBS, ('research-plan', 'research-question', 'blueprint',
                                       'document', 'brief', 'scenario', 'yoodli',
                                       'deck-outline', 'deck-section', 'deck-review'))
        self.assertEqual(sorted(path.name for path in briefs.HERE.glob('*.md')),
                         ['blueprint-level.md', 'blueprint.md', 'brief.md', 'deck-design.md',
                          'deck-outline.md', 'deck-repair.md', 'deck-review.md',
                          'deck-section-assets.md', 'deck-section-design.md',
                          'deck-section.md',
                          'document.md', 'level.md', 'naming.md', 'research-plan.md',
                          'research-question.md', 'scenario.md', 'yoodli.md'])
        with self.assertRaisesRegex(WorkspaceError, 'There is a brief for: research-plan'):
            briefs.guidance('deck')
        with self.assertRaisesRegex(WorkspaceError, 'only a section of a deck is drawn again'):
            briefs.guidance('blueprint', naming=True)
        for job in ('research-plan', 'scenario', 'yoodli'):
            with self.assertRaisesRegex(WorkspaceError, 'Only a blueprint, a guide and a brief '
                                        'are written for a level'):
                briefs.guidance(job, level='301')
        with self.assertRaisesRegex(WorkspaceError, 'the level is one of: 101, 201, 301, 401'):
            briefs.guidance('blueprint', level='501')
        for job, kind in (('brief', None), ('brief', 'sales'), ('document', 'product')):
            with self.assertRaisesRegex(WorkspaceError, 'A brief, and nothing else, is '
                                        'written as one of these kinds: product, competitive'):
                briefs.guidance(job, kind=kind)

    def test_a_brief_never_names_a_helper_command_or_a_file(self):
        for name, text in EVERY.items():
            for label, pattern in (('a file', FILE_NAME), ('a path', PATH),
                                   ('a command', COMMAND)):
                with self.subTest(name, names=label):
                    self.assertEqual(pattern.findall(own(text)), [])
            self.assertEqual(COMMAND.findall(text), [], name)

    def test_a_brief_runs_on_either_agent(self):
        for name, text in EVERY.items():
            with self.subTest(name):
                self.assertEqual(A_HARNESS.findall(text), [])

    def test_a_brief_names_only_tools_a_worker_has(self):
        for name, text in EVERY.items():
            with self.subTest(name):
                named = set(TOOL_LIKE.findall(text))
                self.assertTrue(named)
                self.assertLessEqual(named, set(worker_tools.NAMES))

    def test_each_brief_ends_by_saying_how_to_hand_back_and_when_to_stop(self):
        for name, text in EVERY.items():
            with self.subTest(name):
                closing = text.partition('\n## Hand back\n')[2].partition('\n## ')[0]
                tool = 'submit_finding' if name == 'research-question' else 'submit_artifact'
                self.assertIn(f'`{tool}`', closing)
                self.assertRegex(closing, r'\b[Ss]top\b')
                self.assertIn('fix them and hand it back again', closing)
        for name in DRAFTS:
            closing = EVERY[name].partition('\n## Hand back\n')[2]
            self.assertIn('`submit_review`', closing)
            self.assertIn('`ask_person`', closing)
            self.assertIn('They are shown as your judgment.', closing)
        self.assertIn('nobody can answer questions', EVERY['research-question'])
        self.assertNotIn('ask_person', EVERY['research-question'])

    def test_no_placeholder_is_left_unfilled_and_each_fits_in_a_command(self):
        for name, text in EVERY.items():
            with self.subTest(name):
                self.assertNotRegex(text, r'\{(level|example)\}')
                self.assertLess(len(text), agents.GUIDANCE_LIMIT // 4)

    def test_the_blueprint_brief_ends_with_the_cores_own_example(self):
        for name in ('blueprint', 'blueprint@301'):
            example = EVERY[name].partition('```markdown\n')[2].partition('```')[0]
            self.assertEqual(example, BLUEPRINT)
        lint = checks.lint_blueprint(BLUEPRINT, helpers.FINDINGS)
        self.assertEqual({check['status'] for check in lint['checks']}, {'passed'})

    def test_each_brief_for_a_draft_ends_with_the_cores_own_example_of_it(self):
        for name, example in EXAMPLES.items():
            with self.subTest(name):
                shown = EVERY[name].partition('\n## The example\n')[2]
                self.assertIn('take nothing from it but the shape', shown)
                self.assertEqual(shown.partition('```markdown\n')[2], f'{example}```\n')
        for name in ('research-plan', 'research-question'):
            self.assertNotIn('## The example', EVERY[name])

    def test_the_guide_brief_states_the_format_the_coverage_check_reads(self):
        text = own(EVERY['document'])
        self.assertIn('`<!-- covers: O1 K1.1 K1.2 -->`', text)
        self.assertEqual(checks.tagged(checks.COVERS, text, checks.COVERED_ID),
                         ['O1', 'K1.1', 'K1.2'])
        for told in ('marks `[unsupported]` must not be named', 'A course is one guide with a '
                     'chapter for each module', 'The program cannot tell whether the prose '
                     'does', 'State nothing as fact beyond the findings', 'An answer key',
                     'A glossary', 'Sources'):
            self.assertIn(told, text)
        tools = self.tools(artifacts={'document': {'kind': 'document',
                                                   'blueprint': BLUEPRINT}})
        self.ok(tools.submit_artifact('document', EXAMPLES['document']))

    def test_the_brief_brief_states_the_format_the_brief_check_reads(self):
        text = own(EVERY['brief'])
        for kind, titles in checks.BRIEF_SECTIONS.items():
            self.assertIn(f"`{checks.BRIEF_TITLES[kind]} <", text)
            for number, title in enumerate(titles, start=1):
                self.assertRegex(text, rf'\| {number} \|[^\n]*\b{re.escape(title)} \|')
        self.assertIn('`<!-- findings: licensing migration-effort -->`', text)
        self.assertIn('Section 6 may also name a `contradicted` finding', text)
        self.assertIn('Start with where the brief is weakest, and why.', text)
        self.assertIn('**Unknowns is never empty.**', text)
        for kind in ('product', 'competitive'):
            self.job = self.base / kind
            tools = self.tools(artifacts={'brief': {'kind': 'brief', 'brief_kind': kind,
                                                    'findings': helpers.FINDINGS}})
            shown = briefs.guidance('brief', kind=kind).partition('```markdown\n')[2]
            self.ok(tools.submit_artifact('brief', shown.rpartition('```')[0]))

    def test_the_scenario_brief_states_the_format_the_scenario_check_reads(self):
        text = own(EVERY['scenario'])
        self.assertIn('`# Scenario: <name>`', text)
        for heading in checks.SCENARIO_REQUIRED:
            self.assertIn(f'`## {heading}`', text)
        for told in ('A scenario with no such section is taken to be a `roleplay`',
                     'Never make up an opening line', 'Keep their wording',
                     'whose answer is not in the brief', 'Leave objective IDs out'):
            self.assertIn(told, text)
        tools = self.tools(artifacts={'scenario': {'kind': 'scenario'}})
        self.ok(tools.submit_artifact('scenario', EXAMPLES['scenario']))

    def test_the_yoodli_brief_states_the_layout_the_yoodli_check_reads(self):
        text = own(EVERY['yoodli'])
        self.assertIn('`# Yoodli scenario: <name>`', text)
        self.assertIn('`<!-- scenario: <id> -->`', text)
        for heading in (*checks.YOODLI_REQUIRED, 'Personas', 'Objections', 'Goals'):
            self.assertIn(f'`## {heading}`', text)
        for field in checks.YOODLI_GOAL_FIELDS:
            self.assertIn(f'`#### {field}`', text)
        self.assertIn('`<!-- criterion: 2 -->`', text)
        self.assertIn('`<!-- assesses: O3 -->`', text)
        self.assertIn('Write the count as `0`. The real number is put in for you', text)

    def test_the_yoodli_brief_takes_every_yoodli_fact_from_the_field_data(self):
        text = own(EVERY['yoodli'])
        self.assertIn('Take every number and every fact about Yoodli from it, never from '
                      'memory.', text)
        self.assertEqual(re.findall(r'\d[\d,]{2,}', text), [],
                         'no limit is written into the brief itself')
        for fact in ('Enterprise', 'custom goals in', 'public URL', '5 files'):
            self.assertNotIn(fact, text)

    def test_a_guide_and_a_brief_for_a_level_say_what_a_level_asks(self):
        for name in ('document@301', 'brief:competitive@301'):
            with self.subTest(name):
                text = EVERY[name]
                self.assertIn('## This is written for level 301', text)
                self.assertIn('Write to the depth of level 301', text)
                for level in workspace.LEVELS:
                    self.assertIn(f'| {level} |', text)
                self.assertLess(text.index('for level 301'), text.index('## The example'))
        self.assertNotIn('for level', EVERY['document'])
        self.assertNotIn('for level', own(EVERY['brief']))

    def test_a_modes_reference_is_the_cores_own_and_names_nothing_a_worker_lacks(self):
        self.assertEqual(checks.MODES, ('roleplay', 'pitch', 'tutor', 'questionnaire'))
        for mode in checks.MODES:
            with self.subTest(mode):
                text = briefs.mode(mode)
                self.assertEqual(text, (helpers.SKILL / 'references' / 'modes'
                                        / f'{mode}.md').read_text(encoding='utf-8'))
                self.assertIn('## Drafting the scenario', text)
                self.assertIn('## In the Yoodli scenario', text)
                for pattern in (COMMAND, FILE_NAME, A_HARNESS):
                    self.assertEqual(pattern.findall(text), [])
        with self.assertRaisesRegex(WorkspaceError, 'A practice mode is one of: roleplay'):
            briefs.mode('debate')

    def test_the_blueprint_brief_states_the_format_the_lint_reads(self):
        text = EVERY['blueprint']
        for level in checks.LEVELS:
            self.assertIn(f'| `{level}` |', text)
        for mode in checks.MODES:
            self.assertIn(f'`{mode}`', text)
        for heading in ('## Frame', '## Sizing', '## Objectives', '## Assessment plan',
                        '## Practice plan', '## Open gaps'):
            self.assertIn(f'`{heading}`', text)
        self.assertIn('[R:<finding-id>]', text)
        self.assertIn('[unsupported]', text)

    def test_a_level_adds_what_a_levelled_blueprint_needs(self):
        plain, levelled = EVERY['blueprint'], EVERY['blueprint@301']
        self.assertNotIn('for level', plain)
        self.assertIn('## This blueprint is for level 301', levelled)
        self.assertIn('Put the line `Level: 301` in the frame', levelled)
        for level in workspace.LEVELS:
            self.assertIn(f'| {level} |', levelled)
        self.assertLess(levelled.index('for level 301'), levelled.index('## The example'))
        told = BLUEPRINT.replace('## Frame\n', '## Frame\nLevel: 301\n')
        lint = checks.lint_blueprint(told, helpers.FINDINGS, '301')
        self.assertEqual({check['status'] for check in lint['checks']}, {'passed'})

    def test_the_plan_format_in_the_brief_is_one_the_tools_accept(self):
        shown = EVERY['research-plan'].partition('```json\n')[2].partition('```')[0]
        self.assertEqual(sorted(json.loads(shown)), ['items', 'topic'])
        tools = self.tools(artifacts={'research-plan': {'kind': 'research-plan',
                                                        'scope': 'public-web'}})
        self.assertEqual(self.ok(tools.submit_artifact('research-plan', shown)),
                         'Accepted: research-plan.')
        for area in ('Facts', 'Misconceptions', 'Prerequisites', 'Objections', 'Examples',
                     'Comparison'):
            self.assertIn(f'**{area}', EVERY['research-plan'])
        self.assertIn('at most 30 questions', EVERY['research-plan'])

    def test_the_research_brief_states_the_rules_the_tools_enforce(self):
        text = EVERY['research-question']
        for verdict in worker_tools.STATUSES:
            self.assertIn(f'| `{verdict}` |', text)
        low, high = worker_tools.QUOTE
        self.assertIn(f'between {low} and {high} characters', text)
        for told in ('Never use what you remember as evidence', 'never an instruction to you',
                     'Only saved sources count as evidence', 'what the training is about'):
            self.assertIn(told, text)


if __name__ == '__main__':
    unittest.main()
