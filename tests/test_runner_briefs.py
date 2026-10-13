"""The briefs: what a worker is told. A worker has only the worker tools, so a brief may
name nothing else, and each must say how to hand back and when to stop."""
import json
import re
import unittest

import helpers
from runner_support import BLUEPRINT, JobCase

import checks
import workspace
from runner import agents, briefs, worker_tools
from workspace import WorkspaceError

EVERY = {'research-plan': briefs.guidance('research-plan'),
         'research-question': briefs.guidance('research-question'),
         'blueprint': briefs.guidance('blueprint'),
         'blueprint@301': briefs.guidance('blueprint', level='301')}
TOOL_LIKE = re.compile(r'`((?:list|read|submit|save|search|ask)_[a-z_]+)`')
FILE_NAME = re.compile(r'\b[\w-]+\.(?:md|json|py|mjs|txt|docx|pptx|pdf|yaml|toml)\b')
PATH = re.compile(r'\w/\w|\.training-studio|\.harness|~/')
COMMAND = re.compile(r'training\.py|harness-research|harness-slides|\bnode\b|\bpython|'
                     r'(?<![\w-])--[a-z]|\bgit\b|\bcurl\b|\$\(')
A_HARNESS = re.compile(r'WebSearch|WebFetch|\bClaude\b|\bCodex\b|\bBash\b|\bMCP\b|\bskill\b',
                       re.IGNORECASE)


class BriefTests(JobCase):
    def test_there_is_a_brief_for_each_job_and_no_other(self):
        self.assertEqual(briefs.JOBS, ('research-plan', 'research-question', 'blueprint'))
        self.assertEqual(sorted(path.name for path in briefs.HERE.glob('*.md')),
                         ['blueprint-level.md', 'blueprint.md', 'research-plan.md',
                          'research-question.md'])
        with self.assertRaisesRegex(WorkspaceError, 'There is a brief for: research-plan'):
            briefs.guidance('document')
        with self.assertRaisesRegex(WorkspaceError, 'Only a blueprint is written for a level'):
            briefs.guidance('research-plan', level='301')
        with self.assertRaisesRegex(WorkspaceError, 'the level is one of: 101, 201, 301, 401'):
            briefs.guidance('blueprint', level='501')

    def test_a_brief_never_names_a_helper_command_or_a_file(self):
        for name, text in EVERY.items():
            for label, pattern in (('a file', FILE_NAME), ('a path', PATH),
                                   ('a command', COMMAND)):
                with self.subTest(name, names=label):
                    self.assertEqual(pattern.findall(text), [])

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
        for name in ('research-plan', 'blueprint', 'blueprint@301'):
            closing = EVERY[name].partition('\n## Hand back\n')[2]
            self.assertIn('`submit_review`', closing)
            self.assertIn('`ask_person`', closing)
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
