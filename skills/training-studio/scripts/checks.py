"""Checks over training artifacts. Pure functions: text and data in, results out."""
from __future__ import annotations

import re

MODES = ('roleplay', 'pitch', 'tutor', 'questionnaire')
LEVELS = ('recall', 'explain', 'apply', 'handle')

SEPARATOR = r'\s*[—–:-]\s*'
OBJECTIVE = re.compile(rf'^### (O[1-9]\d*){SEPARATOR}(.+?)\s*\[({"|".join(LEVELS)})\]\s*$')
MODULE = re.compile(rf'^## (M[1-9]\d?){SEPARATOR}(.+?)\s*\((\d+) min\)\s*$')
KEY_POINT = re.compile(r'^- (K([1-9]\d?)\.[1-9]\d*):\s*\S')
FINDING = re.compile(r'\[R:([a-z0-9][a-z0-9-]{0,63})\]')
OBJECTIVE_ID = re.compile(r'\bO[1-9]\d*\b')
ASSESSMENT = re.compile(r'^- (O[1-9]\d*):\s*(.+)$')
PRACTICE = re.compile(r'^- ([a-z0-9][a-z0-9-]{0,63}):\s*([A-Za-z]+)\b(.*)$')
FRAME_LEVEL = re.compile(r'^Level:\s*(\S+)\s*$')
COMMENT = re.compile(r'<!--.*?-->', re.DOTALL)


def result(check: str, problems: list[str], unavailable: str | None = None) -> dict:
    """One check outcome: passed, failed, or unavailable with the reason."""
    if unavailable is not None:
        return {'check': check, 'status': 'unavailable', 'problems': [unavailable]}
    return {'check': check, 'status': 'failed' if problems else 'passed', 'problems': problems}


def tagged(pattern: re.Pattern, text: str, token: re.Pattern) -> list[str]:
    """Tokens named inside comments such as <!-- covers: O1 K1.2 -->, in order."""
    return [found for group in pattern.findall(text) for found in token.findall(group)]


# --- research plan --------------------------------------------------------------

QUESTION_ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
PLAN_SCOPES = ('public-web', 'supplied-only')


def check_research_plan(plan) -> dict:
    """Check a research plan is one harness-research will accept. `plan` is the parsed JSON."""
    name = 'research-plan.items'
    if not isinstance(plan, dict):
        return result(name, ['The plan must be a JSON object.'])
    problems = []
    if plan.get('purpose') != 'planning':
        problems.append('"purpose" must be "planning".')
    if plan.get('scope') not in PLAN_SCOPES:
        problems.append('"scope" must be one of: ' + ', '.join(PLAN_SCOPES))
    if 'input_files' in plan:
        problems.append('Leave out "input_files"; registering intake there makes '
                        'harness-research discard its findings when intake is edited.')
    items = plan.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 30:
        problems.append('"items" must hold 1 to 30 questions.')
        return result(name, problems)
    seen = set()
    for position, item in enumerate(items, start=1):
        identifier = item.get('id') if isinstance(item, dict) else None
        if not isinstance(identifier, str) or not QUESTION_ID.match(identifier):
            problems.append(f'Question {position} needs an "id" of lowercase letters, '
                            'digits and hyphens.')
        elif identifier in seen:
            problems.append(f'Question ID {identifier} is used more than once.')
        else:
            seen.add(identifier)
        question = item.get('question') if isinstance(item, dict) else None
        if not isinstance(question, str) or not question.strip():
            problems.append(f'Question {position} has no question text.')
    return result(name, problems)


# --- blueprint ----------------------------------------------------------------

def parse_blueprint(text: str) -> dict:
    """Read a blueprint's frame, objectives, modules, plans and gaps."""
    parsed = {'level': None, 'objectives': {}, 'modules': {}, 'assessment': {},
              'practice': [], 'open_gaps': '', 'malformed': [], 'duplicates': []}
    section, module = None, None
    for line in text.splitlines():
        if line.startswith('## '):
            module = None
            head = MODULE.match(line)
            if head:
                section = 'module'
                if head.group(1) in parsed['modules']:
                    parsed['duplicates'].append(head.group(1))
                module = parsed['modules'].setdefault(head.group(1), {
                    'title': head.group(2), 'minutes': int(head.group(3)), 'objectives': [],
                    'key_points': {}, 'misconceptions': [], 'examples': 0})
            elif re.match(r'^## M\d', line):
                section = None
                parsed['malformed'].append(line)
            else:
                section = line[3:].strip().lower()
        elif section == 'frame':
            level = FRAME_LEVEL.match(line)
            if level:
                parsed['level'] = level.group(1)
        elif section == 'objectives' and line.startswith('### '):
            head = OBJECTIVE.match(line)
            if not head:
                parsed['malformed'].append(line)
            elif head.group(1) in parsed['objectives']:
                parsed['duplicates'].append(head.group(1))
            else:
                parsed['objectives'][head.group(1)] = {'text': head.group(2),
                                                       'level': head.group(3)}
        elif section == 'module':
            _module_line(parsed, module, line)
        elif section == 'assessment plan':
            entry = ASSESSMENT.match(line)
            if entry:
                parsed['assessment'][entry.group(1)] = entry.group(2)
        elif section == 'practice plan' and line.startswith('- '):
            entry = PRACTICE.match(line)
            if entry:
                parsed['practice'].append({'id': entry.group(1), 'mode': entry.group(2).lower(),
                                           'objectives': OBJECTIVE_ID.findall(entry.group(3))})
            else:
                parsed['malformed'].append(line)
        elif section == 'open gaps':
            parsed['open_gaps'] += line + '\n'
    return parsed


def _module_line(parsed: dict, module: dict, line: str) -> None:
    if line.startswith('Objectives:'):
        module['objectives'] += OBJECTIVE_ID.findall(line)
    elif line.startswith('- K'):
        point = KEY_POINT.match(line)
        if not point:
            parsed['malformed'].append(line)
            return
        if any(point.group(1) in other['key_points'] for other in parsed['modules'].values()):
            parsed['duplicates'].append(point.group(1))
        module['key_points'][point.group(1)] = {
            'module_number': point.group(2), 'findings': FINDING.findall(line),
            'unsupported': '[unsupported]' in line}
    elif line.startswith('Misconception:'):
        module['misconceptions'].append({'text': line, 'findings': FINDING.findall(line)})
    elif line.startswith('Example:'):
        module['examples'] += 1


def lint_blueprint(text: str, findings: dict | None, level: str | None = None) -> dict:
    """Check a blueprint against its contract. `findings` maps finding ID to status."""
    parsed = parse_blueprint(text)
    objectives, modules = parsed['objectives'], parsed['modules']

    structure = [f'Not understood: {line.strip()}' for line in parsed['malformed']]
    structure += [f'Duplicate ID: {identifier}' for identifier in parsed['duplicates']]
    if not objectives:
        structure.append('No objectives found under "## Objectives".')
    if not modules:
        structure.append('No modules found.')
    if level is not None and parsed['level'] != level:
        structure.append(f'The frame must say "Level: {level}", the level of its folder.')
    for identifier, module in modules.items():
        for point, detail in module['key_points'].items():
            if detail['module_number'] != identifier[1:]:
                structure.append(f'{point} is under {identifier}; '
                                 f'its number should start K{identifier[1:]}.')
    for entry in parsed['practice']:
        if entry['mode'] not in MODES:
            structure.append(f"Practice plan: {entry['id']} has unknown mode {entry['mode']}.")
        for objective in entry['objectives']:
            if objective not in objectives:
                structure.append(f"Practice plan: {entry['id']} names unknown "
                                 f'objective {objective}.')

    placement = []
    placed = {objective for module in modules.values() for objective in module['objectives']}
    for identifier in objectives:
        if identifier not in placed:
            placement.append(f'{identifier} is not in any module.')
        entry = parsed['assessment'].get(identifier, '')
        if 'Check:' not in entry or 'Observe:' not in entry:
            placement.append(f'{identifier} needs an assessment entry '
                             'with "Check:" and "Observe:".')
    for identifier, module in modules.items():
        if not module['objectives']:
            placement.append(f'{identifier} has no "Objectives:" line.')
        for objective in module['objectives']:
            if objective not in objectives:
                placement.append(f'{identifier} lists unknown objective {objective}.')

    points = []
    for identifier, module in modules.items():
        if not module['key_points']:
            points.append(f'{identifier} has no key points.')
        if module['examples'] == 0:
            points.append(f'{identifier} has no "Example:" line.')
        for misconception in module['misconceptions']:
            if not misconception['findings']:
                points.append(f'A misconception in {identifier} cites no finding.')
        for point, detail in module['key_points'].items():
            if detail['unsupported']:
                if not re.search(rf'\b{re.escape(point)}\b', parsed['open_gaps']):
                    points.append(f'{point} is [unsupported] and must be listed '
                                  'under "## Open gaps".')
            elif not detail['findings']:
                points.append(f'{point} cites no finding and is not marked [unsupported].')

    checks = [result('blueprint.structure', structure),
              result('blueprint.objectives', placement),
              result('blueprint.key-points', points),
              _citations(modules, findings)]

    warnings = []
    lesson = len(modules) == 1
    for identifier, module in modules.items():
        count = len(module['objectives'])
        if lesson and count > 5:
            warnings.append(f'{identifier} has {count} objectives; '
                            'a lesson usually has 5 or fewer.')
        if not lesson and not 3 <= count <= 5:
            warnings.append(f'{identifier} has {count} objectives; '
                            'a course module usually has 3 to 5.')
    if lesson and sum(module['minutes'] for module in modules.values()) > 45:
        warnings.append('A lesson usually runs 45 minutes or less; consider a course.')
    if len(modules) > 6:
        warnings.append('More than 6 modules; consider separate trainings.')
    return {'checks': checks, 'warnings': warnings}


def _citations(modules: dict, findings: dict | None) -> dict:
    if findings is None:
        return result('blueprint.citations', [],
                      unavailable='No approved findings index; approve the research first.')
    problems = []
    for identifier, module in modules.items():
        for point, detail in module['key_points'].items():
            for finding in detail['findings']:
                if finding not in findings:
                    problems.append(f'{point} cites unknown finding {finding}.')
                elif findings[finding] != 'supported':
                    problems.append(f'{point} cites {finding}, which is '
                                    f'{findings[finding]}, not supported.')
        for misconception in module['misconceptions']:
            for finding in misconception['findings']:
                if finding not in findings:
                    problems.append(f'A misconception in {identifier} cites '
                                    f'unknown finding {finding}.')
                elif findings[finding] not in ('supported', 'contradicted'):
                    problems.append(f'A misconception in {identifier} cites {finding}, '
                                    f'which is {findings[finding]}.')
    return result('blueprint.citations', problems)


def level_overlap(blueprints: dict[str, dict]) -> list[str]:
    """Warnings for objectives stated at more than one level. Keys are levels."""
    seen: dict[str, str] = {}
    warnings = []
    for level in sorted(blueprints):
        for identifier, objective in blueprints[level]['objectives'].items():
            wording = ' '.join(objective['text'].lower().split())
            if wording in seen:
                warnings.append(f'Levels {seen[wording]} and {level} both state the '
                                f'objective "{objective["text"]}".')
            else:
                seen[wording] = level
    return warnings


# --- document -------------------------------------------------------------------

COVERS = re.compile(r'<!--\s*covers:\s*(.*?)\s*-->')
COVERED_ID = re.compile(r'\b(?:O[1-9]\d*|K[1-9]\d?\.[1-9]\d*)\b')


def document_coverage(parsed: dict, document: str) -> dict:
    """Declared coverage: every objective and supported key point is claimed by a section."""
    points = {point: detail for module in parsed['modules'].values()
              for point, detail in module['key_points'].items()}
    unsupported = {point for point, detail in points.items() if detail['unsupported']}
    expected = (set(parsed['objectives']) | set(points)) - unsupported
    covered = set(tagged(COVERS, document, COVERED_ID))
    problems = [f'{identifier} is not covered by any section.'
                for identifier in sorted(expected - covered)]
    problems += [f'{identifier} is [unsupported] and must not be taught.'
                 for identifier in sorted(covered & unsupported)]
    problems += [f'{identifier} is not in the blueprint.'
                 for identifier in sorted(covered - expected - unsupported)]
    outcome = result('document.coverage', problems)
    outcome['basis'] = 'declared'
    return outcome


# --- brief ----------------------------------------------------------------------

NUMBERED = re.compile(r'^## \d+\. (.+?)\s*$')
FINDINGS_COMMENT = re.compile(r'<!--\s*findings:\s*(.*?)\s*-->')
FINDING_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,63}')
BRIEF_SECTIONS = {
    'competitive': ('Executive summary', 'Comparison', 'Differentiators', 'Limitations',
                    'Qualification questions', 'Objections and responses', 'Unknowns',
                    'Sources'),
    'product': ('Executive summary', 'What it is and where it fits', 'Capabilities',
                'Limitations', 'Qualification questions', 'Objections and responses',
                'Unknowns', 'Sources'),
}
BRIEF_TITLES = {'competitive': '# Competitive brief:', 'product': '# Product brief:'}
EVIDENCE = slice(1, 6)
REBUTTAL = 'Objections and responses'


def numbered_sections(text: str) -> list[tuple[str, str]]:
    """Numbered sections of a brief, in the order they appear: (title, body)."""
    found: list[list[str]] = []
    for line in text.splitlines():
        head = NUMBERED.match(line)
        if head:
            found.append([head.group(1), ''])
        elif found:
            found[-1][1] += line + '\n'
    return [(title, body) for title, body in found]


def check_brief(text: str, kind: str, findings: dict | None) -> list[dict]:
    """Check a brief has every section for its kind and rests on supported findings."""
    expected = BRIEF_SECTIONS[kind]
    sections = numbered_sections(text)
    bodies = {title.lower(): body for title, body in sections}

    shape = []
    if not text.lstrip().startswith(BRIEF_TITLES[kind]):
        shape.append(f'The title must start with "{BRIEF_TITLES[kind]}".')
    for title in expected:
        if title.lower() not in bodies:
            shape.append(f'Section "{title}" is missing.')
        elif not COMMENT.sub('', bodies[title.lower()]).strip():
            shape.append(f'Section "{title}" is empty.')
    present = [title.lower() for title, _ in sections
               if title.lower() in {name.lower() for name in expected}]
    if not any('missing' in problem for problem in shape) \
            and present != [title.lower() for title in expected]:
        shape.append('Sections are out of order; expected: ' + ', '.join(expected) + '.')
    outcomes = [result('brief.sections', shape)]

    if findings is None:
        outcomes.append(result(
            'brief.findings', [],
            unavailable='No approved findings index; approve the research first.'))
        return outcomes
    evidence = []
    for title in expected[EVIDENCE]:
        body = bodies.get(title.lower())
        if body is None:
            continue
        named = tagged(FINDINGS_COMMENT, body, FINDING_ID)
        if not named:
            evidence.append(f'Section "{title}" names no findings.')
        allowed = ('supported', 'contradicted') if title == REBUTTAL else ('supported',)
        for finding in named:
            if finding not in findings:
                evidence.append(f'Section "{title}" names unknown finding {finding}.')
            elif findings[finding] not in allowed:
                evidence.append(f'Section "{title}" rests on {finding}, '
                                f'which is {findings[finding]}.')
    outcomes.append(result('brief.findings', evidence))
    return outcomes


# --- scenario -------------------------------------------------------------------

SCENARIO_TITLE = re.compile(r'^# Scenario:\s*(\S.*?)\s*$', re.MULTILINE)
SCENARIO_REQUIRED = ('Situation', 'Learner role', 'AI role', 'Opening', 'Success criteria')
LIST_ITEM = re.compile(r'^\s*(?:[-*]|\d+\.)\s+(\S.*?)\s*$', re.MULTILINE)


def parse_scenario(text: str) -> dict:
    """Read a scenario file: title, mode, sections and numbered success criteria."""
    title = SCENARIO_TITLE.search(text)
    sections, name = {}, None
    for line in text.splitlines():
        if line.startswith('## '):
            name = line[3:].strip().lower()
            sections[name] = ''
        elif name is not None:
            sections[name] += line + '\n'
    stated = sections.get('mode', '').split()
    return {'title': title.group(1) if title else None,
            'mode': stated[0].lower() if stated else 'roleplay',
            'sections': sections,
            'criteria': LIST_ITEM.findall(sections.get('success criteria', ''))}


def check_scenario(text: str, label: str) -> dict:
    """Check a scenario file has what a Yoodli scenario is built from."""
    scenario = parse_scenario(text)
    problems = []
    if scenario['title'] is None:
        problems.append('The file must start with "# Scenario: <name>".')
    for title in SCENARIO_REQUIRED:
        if not scenario['sections'].get(title.lower(), '').strip():
            problems.append(f'Section "{title}" is missing or empty.')
    if scenario['sections'].get('success criteria', '').strip() and not scenario['criteria']:
        problems.append('Success criteria must be a list, one criterion per item.')
    if scenario['mode'] not in MODES:
        problems.append(f"Mode \"{scenario['mode']}\" is not one of: " + ', '.join(MODES))
    return result(f'{label}.sections', problems)


# --- Yoodli scenario ----------------------------------------------------------------

HEADING = re.compile(r'^(#{2,4}) (.+?)\s*$')
SCENARIO_COMMENT = re.compile(r'<!--\s*scenario:\s*(\S+?)\s*-->')
CRITERION = re.compile(r'<!--\s*criterion:\s*(.*?)\s*-->')
ASSESSES = re.compile(r'<!--\s*assesses:\s*(.*?)\s*-->')
NUMBER = re.compile(r'\d+')
YOODLI_REQUIRED = ('Roleplay name', 'Type', 'Description', 'Context')
YOODLI_GOAL_FIELDS = ('Name', 'Type', 'Explanation', 'Achieved', 'Missed')
YOODLI_GOAL_LIMITS = (('Explanation', 'goal_explanation_chars'),
                      ('Achieved', 'goal_achieved_chars'),
                      ('Missed', 'goal_missed_chars'))


def fenced_fields(text: str) -> tuple[dict[tuple[str, ...], str], list[str]]:
    """Fenced blocks keyed by the headings above them, and structural problems found."""
    fields, problems = {}, []
    path, block, inside, headings = [], [], False, set()
    for line in text.splitlines():
        if line.startswith('```'):
            if inside:
                key = tuple(path)
                if key in fields:
                    problems.append(f'Field "{" / ".join(key)}" has more than one block.')
                fields[key] = '\n'.join(block)
            block, inside = [], not inside
        elif inside:
            block.append(line)
        else:
            head = HEADING.match(line)
            if head:
                depth = len(head.group(1)) - 2
                path = path[:depth] + [head.group(2)]
                if tuple(path) in headings:
                    problems.append(f'Heading "{" / ".join(path)}" appears more than once.')
                headings.add(tuple(path))
    if inside:
        problems.append('A fenced block is never closed.')
    return fields, problems


STATED_COUNT = re.compile(r'\b([\d,]+) of [\d,]+ characters\b')


def stated_counts(text: str) -> dict[tuple[str, ...], int]:
    """Character counts the file states beside its fields, keyed like the fields."""
    stated, path, inside = {}, [], False
    for line in text.splitlines():
        if line.startswith('```'):
            inside = not inside
        elif not inside:
            head = HEADING.match(line)
            if head:
                path = path[:len(head.group(1)) - 2] + [head.group(2)]
            else:
                found = STATED_COUNT.search(line)
                if found:
                    stated[tuple(path)] = int(found.group(1).replace(',', ''))
    return stated


def goal_comments(text: str) -> dict[str, dict]:
    """For each goal heading: the success criteria it carries and objectives it assesses."""
    goals, current, in_goals, inside = {}, None, False, False
    for line in text.splitlines():
        if line.startswith('```'):
            inside = not inside
        elif inside:
            continue
        elif line.startswith('## '):
            in_goals, current = line[3:].strip() == 'Goals', None
        elif in_goals and line.startswith('### '):
            current = line[4:].strip()
            goals[current] = {'criteria': [], 'assesses': []}
        elif current is not None:
            goals[current]['criteria'] += [int(number)
                                           for number in tagged(CRITERION, line, NUMBER)]
            goals[current]['assesses'] += tagged(ASSESSES, line, OBJECTIVE_ID)
    return goals


def check_yoodli(text: str, profile: dict, scenario: dict | None,
                 objectives: set[str] | None, label: str) -> list[dict]:
    """Check a Yoodli scenario's fields, limits and mapping back to its scenario file."""
    fields, structure = fenced_fields(text)
    limits = profile['limits']

    def value(*path: str) -> str:
        return fields.get(path, '')

    def grouped(group: str) -> list[str]:
        return sorted({path[1] for path in fields if len(path) == 3 and path[0] == group})

    shape = list(structure)
    for name in YOODLI_REQUIRED:
        if not value(name).strip():
            shape.append(f'Field "{name}" is missing or empty.')
    kind = value('Type').strip()
    if kind and kind not in profile['types']:
        shape.append(f'Type "{kind}" is not one of: ' + ', '.join(profile['types']))
    if kind and scenario is not None and scenario['mode'] in profile['mode_types']:
        expected = profile['mode_types'][scenario['mode']]
        if kind != expected:
            shape.append(f'Type "{kind}" does not match the scenario mode '
                         f'{scenario["mode"]}; expected "{expected}".')
    personas = grouped('Personas')
    if kind in profile['persona_required_types'] and not personas:
        shape.append(f'Type "{kind}" needs at least one persona.')
    for persona in personas:
        for field in profile['persona_fields']:
            if not value('Personas', persona, field).strip():
                shape.append(f'{persona}: field "{field}" is missing or empty.')
    listed = grouped('Goals')
    if not listed:
        shape.append('At least one goal is required.')
    for goal in listed:
        for field in YOODLI_GOAL_FIELDS:
            if not value('Goals', goal, field).strip():
                shape.append(f'{goal}: field "{field}" is missing or empty.')
        goal_type = value('Goals', goal, 'Type').strip()
        if goal_type and goal_type not in profile['goal_types']:
            shape.append(f'{goal}: type "{goal_type}" is not one of: '
                         + ', '.join(profile['goal_types']))

    sizes, used = [], {'context_chars', 'personas_max'}
    counts = {'Context': len(value('Context'))}
    stated = stated_counts(text)

    def confirm(path: tuple[str, ...], actual: int) -> None:
        if path in stated and stated[path] != actual:
            sizes.append(f'{" / ".join(path)} states {stated[path]} characters '
                         f'but has {actual}.')

    confirm(('Context',), counts['Context'])
    if counts['Context'] > limits['context_chars']['value']:
        sizes.append(f'Context is {counts["Context"]} characters; '
                     f'the limit is {limits["context_chars"]["value"]}.')
    if len(personas) > limits['personas_max']['value']:
        sizes.append(f'{len(personas)} personas; '
                     f'the limit is {limits["personas_max"]["value"]}.')
    for goal in listed:
        for field, limit in YOODLI_GOAL_LIMITS:
            used.add(limit)
            size = counts[f'{goal} {field}'] = len(value('Goals', goal, field))
            confirm(('Goals', goal, field), size)
            if size > limits[limit]['value']:
                sizes.append(f'{goal}: {field} is {size} characters; '
                             f'the limit is {limits[limit]["value"]}.')
    within = result(f'{label}.limits', sizes)
    within['counts'] = counts
    within['provisional'] = any(limits[limit]['verified'] is None for limit in used)

    return [result(f'{label}.fields', shape), within,
            _mapping(text, scenario, objectives, label)]


def _mapping(text: str, scenario: dict | None, objectives: set[str] | None,
             label: str) -> dict:
    name = f'{label}.mapping'
    if scenario is None:
        return result(name, [], unavailable='The scenario file is missing.')
    if objectives is None:
        return result(name, [], unavailable='The blueprint is missing.')
    problems = []
    ident = label.partition(':')[2].partition('@')[0]
    stated = SCENARIO_COMMENT.search(text)
    if not stated or stated.group(1) != ident:
        problems.append(f'The file must name its scenario with <!-- scenario: {ident} -->.')
    total = len(scenario['criteria'])
    carried = set()
    for goal, comments in goal_comments(text).items():
        if not comments['criteria']:
            problems.append(f'{goal} names no success criterion.')
        for number in comments['criteria']:
            if not 1 <= number <= total:
                problems.append(f'{goal} names criterion {number}; '
                                f'the scenario has {total}.')
            carried.add(number)
        for objective in comments['assesses']:
            if objective not in objectives:
                problems.append(f'{goal} assesses unknown objective {objective}.')
    for number, criterion in enumerate(scenario['criteria'], start=1):
        if number not in carried:
            problems.append(f'Success criterion {number} is not carried by any goal: '
                            f'"{criterion}"')
    return result(name, problems)


# --- deck coverage and practice --------------------------------------------------

def deck_coverage(parsed: dict, review: dict | None, deck_sha256: str | None,
                  blueprint_sha256: str | None) -> dict:
    """Deck coverage is a recorded review, valid only for the deck and blueprint reviewed."""
    if review is None:
        return result('deck.coverage', [],
                      unavailable='The deck has not been reviewed for coverage.')
    if (review['deck_sha256'], review['blueprint_sha256']) != (deck_sha256, blueprint_sha256):
        return result('deck.coverage', [], unavailable='The deck or the blueprint changed '
                      'after the coverage review; review the deck again.')
    outcome = result('deck.coverage', [f'{objective} was not found in the deck.'
                                       for objective in parsed['objectives']
                                       if not review['objectives'].get(objective)])
    outcome['basis'] = 'reviewed'
    return outcome


def practice(parsed: dict, yoodli_texts: list[str]) -> dict:
    """Which objectives the scenarios exercise between them. A report, not a check."""
    named = {objective for text in yoodli_texts
             for comments in goal_comments(text).values()
             for objective in comments['assesses']}
    exercised = [objective for objective in parsed['objectives'] if objective in named]
    missed = [objective for objective in parsed['objectives'] if objective not in named]
    warnings = [f'{objective} is a handle objective that no scenario exercises.'
                for objective in missed if parsed['objectives'][objective]['level'] == 'handle']
    return {'basis': 'Yoodli goals', 'exercised': exercised, 'not_exercised': missed,
            'warnings': warnings}


def practice_from_plan(parsed: dict, scenario_ids: set[str]) -> dict:
    """Objectives the blueprint's practice plan gives to scenarios that exist."""
    named = {objective for entry in parsed['practice'] if entry['id'] in scenario_ids
             for objective in entry['objectives']}
    exercised = [objective for objective in parsed['objectives'] if objective in named]
    missed = [objective for objective in parsed['objectives'] if objective not in named]
    warnings = [f'{objective} is a handle objective that no scenario exercises.'
                for objective in missed if parsed['objectives'][objective]['level'] == 'handle']
    return {'basis': 'practice plan', 'exercised': exercised, 'not_exercised': missed,
            'warnings': warnings}


# --- readiness --------------------------------------------------------------------

def readiness(artifacts: list[dict], exports: dict[str, str], outcomes: list[dict],
              skipped: list[str], unavailable: dict[str, str],
              without_scenario: list[str], pending_question: str | None = None,
              decisions: list[dict] | None = None, yoodli: bool = False,
              docs: dict[str, str] | None = None) -> dict:
    """Whether the training is complete, what blocks it, and what it had to leave out.

    `artifacts` lists each artifact's name, stage and status. `without_scenario` names the
    levels (or '' for a plain training) that want scenarios and have no scenario file.
    `yoodli` says the optional Yoodli stage is wanted, which makes the brief's copy an upload:
    its export, or its Google Doc when no export is kept.
    `exports` and `docs` hold only the Word copies and Google Docs this training keeps.
    """
    blocking = [f"{item['name']} is {item['status']}" for item in artifacts
                if item['status'] not in ('approved', 'skipped', 'unavailable')]
    blocking += ['No scenario file found' + (f' for level {level}' if level else '') + '.'
                 for level in without_scenario]
    for outcome in outcomes:
        if outcome['status'] == 'failed':
            blocking.append(f"{outcome['check']} failed")
        elif outcome['status'] == 'unavailable':
            blocking.append(f"{outcome['check']} could not run: {outcome['problems'][0]}")
    if pending_question:
        blocking.append(f'A question is waiting on the user: {pending_question}')
    limitations = [f'{stage} was skipped' for stage in skipped]
    limitations += [f"{decision['artifact']} was accepted as it was after its inputs "
                    f"changed: {decision['reason']}" for decision in decisions or []
                    if decision.get('decision') == 'accepted-stale']
    limitations += [f'{stage} unavailable: {reason}' for stage, reason in unavailable.items()]
    approved = {item['name'] for item in artifacts if item['status'] == 'approved'}
    upload_needed = yoodli and 'yoodli' not in unavailable
    for name, state in exports.items():
        if state == 'outdated':
            blocking.append(f'The export of {name} is out of date')
        elif name not in approved or state == 'current':
            continue
        elif name.partition('@')[0] == 'brief' and upload_needed:
            if state == 'unavailable':
                limitations.append(f'Yoodli handoff incomplete: no export of {name}')
            else:
                blocking.append(f'{name} has no export, and the Yoodli scenario names it '
                                'as the file to upload')
        else:
            limitations.append(f'{name} has no export')
    for name, state in (docs or {}).items():
        if state == 'outdated':
            blocking.append(f'The Google Doc of {name} is behind its file')
        elif state != 'missing' or name not in approved:
            continue
        elif name.partition('@')[0] == 'brief' and upload_needed and name not in exports:
            # No Word copy is kept, so the Doc is what the user gives Yoodli.
            blocking.append(f'{name} is not in a Google Doc, and the Yoodli scenario names it '
                            'as the file to upload')
        else:
            limitations.append(f'{name} is not in a Google Doc')
    return {'ready': not blocking, 'blocking': blocking, 'limitations': limitations}
