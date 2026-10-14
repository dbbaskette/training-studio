"""A training's checks and readiness, its status as a person reads it, and decisions.

The command line, the page and the runner all ask through here, so that each gets the same
answer. Nothing here prints or parses a command.
"""
from __future__ import annotations

import json
from pathlib import Path

import checks
import gdocs
import sync_guidance
import workspace

PROVISIONAL = ('Yoodli limits are provisional: they come from public help pages and have '
               'not all been confirmed in the live builder.')


def read(root: Path, relative: str) -> str | None:
    path = root / relative
    return path.read_text(encoding='utf-8') if path.is_file() else None


def run_checks(root: Path, show_all: bool = False) -> dict:
    """Run every check that applies to what exists, and report readiness."""
    session = workspace.load(root)
    state = workspace.statuses(root, session)
    wanted = session['settings']['stages']
    found = workspace.scenarios(root, session)['found']
    profile = json.loads(workspace.profile_for(root).read_text(encoding='utf-8'))
    outcomes, warnings, practice, blueprints = [], [], {}, {}
    without_scenario = []

    def file_of(name: str) -> str:
        return workspace.artifact(root, session, name)['file']

    plan = read(root, workspace.SHARED['research-plan'][0])
    if plan is not None:
        try:
            outcomes.append(checks.check_research_plan(json.loads(plan)))
        except ValueError:
            outcomes.append(checks.result('research-plan.items',
                                          ['The plan is not valid JSON.']))
    warnings += [f'{path} is not used as a scenario: it is outside a level folder or its '
                 'name is not lowercase letters, digits and hyphens.'
                 for path in workspace.scenarios(root, session)['ignored']]

    for level in session['levels'] or [None]:
        def named(base: str) -> str:
            return workspace.qualify(base, level)

        def add(results) -> None:
            for outcome in results if isinstance(results, list) else [results]:
                outcome['check'] = named(outcome['check'])
                outcomes.append(outcome)

        own = sorted(name for name in found if workspace.split(name)[1] == level)
        if 'scenario' in wanted and 'scenario' not in session['unavailable'] and not own:
            without_scenario.append(level or '')
        for name in own if 'scenario' in wanted else []:
            add(checks.check_scenario(read(root, found[name]), workspace.split(name)[0]))
        blueprint = read(root, file_of(named('blueprint')))
        if blueprint is None:
            continue
        linted = checks.lint_blueprint(blueprint, session['findings'], level)
        add(linted['checks'])
        warnings += [f'{named("blueprint")}: {text}' for text in linted['warnings']]
        parsed = blueprints[level] = checks.parse_blueprint(blueprint)

        document = read(root, file_of(named('document')))
        if 'document' in wanted and document is not None:
            add(checks.document_coverage(parsed, document))
        brief = read(root, file_of(named('brief')))
        if 'brief' in wanted and brief is not None:
            add(checks.check_brief(brief, session['settings']['brief_kind'],
                                   session['findings']))
        yoodli_texts, idents = [], set()
        for name in own if 'scenario' in wanted else []:
            base = workspace.split(name)[0]
            source = read(root, found[name])
            ident = base.partition(':')[2]
            idents.add(ident)
            actual = checks.parse_scenario(source)['mode']
            warnings += [f"The practice plan lists {named(base)} as {entry['mode']}; "
                         f'its scenario file says {actual}. The scenario file decides.'
                         for entry in parsed['practice']
                         if entry['id'] == ident and entry['mode'] != actual]
            if 'yoodli' not in wanted:
                continue
            output = read(root, file_of(name.replace('scenario:', 'yoodli:', 1)))
            if output is None:
                continue
            yoodli_texts.append(output)
            results = checks.check_yoodli(output, profile, checks.parse_scenario(source),
                                          set(parsed['objectives']),
                                          base.replace('scenario:', 'yoodli:', 1))
            if results[1]['provisional'] and PROVISIONAL not in warnings:
                warnings.append(PROVISIONAL)
            add(results)
        deck = named('deck')
        if state[deck] not in ('skipped', 'unavailable', 'not-started'):
            review = session['artifacts'].get(deck, {}).get('reviewed_coverage')
            add(checks.deck_coverage(
                parsed, review, workspace.sha256_file(root / file_of(deck)),
                workspace.sha256_file(root / file_of(named('blueprint')))))
        if 'scenario' in wanted:
            exercised = (checks.practice(parsed, yoodli_texts) if 'yoodli' in wanted
                         else checks.practice_from_plan(parsed, idents))
            warnings += [f'{level}: {text}' if level else text
                         for text in exercised.pop('warnings')]
            practice[level or ''] = exercised

    if len(blueprints) > 1:
        warnings += checks.level_overlap(blueprints)
    verdict = checks.readiness(
        [{'name': name, 'stage': workspace.artifact(root, session, name)['stage'],
          'status': status} for name, status in state.items()],
        workspace.export_states(root, session), outcomes,
        [stage for stage in workspace.SKIPPABLE
         if stage not in wanted and stage not in workspace.OPTIONAL],
        session['unavailable'], without_scenario, session.get('pending_question'),
        session['decisions'], 'yoodli' in wanted, gdocs.copy_states(root, session),
        session['requests'])
    failed = [outcome for outcome in outcomes if outcome['status'] == 'failed']
    passed = [outcome for outcome in outcomes if outcome['status'] == 'passed']
    return {
        'checks_passed': not failed,
        **verdict,
        'passed': len(passed),
        'checks': outcomes if show_all else [o for o in outcomes if o['status'] != 'passed'],
        'practice': practice if session['levels'] else practice.get('', {}),
        'warnings': warnings,
    }


def describe(root: Path) -> dict:
    """Status for the user: the workspace's, with the Google Docs it keeps and the guidance pin."""
    report = workspace.status(root)
    report['google_docs'] = gdocs.copy_states(root, workspace.load(root))
    report['guidance'] = sync_guidance.summary(root)
    return report


def decide(root: Path, target: str, decision: str, note: str | None = None,
           by: str = 'chat', seen: str | None = None) -> dict:
    """Record a decision and say which checks are failing once it is made.

    The command line and the page both decide through here; only `by` tells them apart.
    """
    outcome = workspace.decide(root, target, decision, note, by, seen)
    outcome['failing_checks'] = [item['check'] for item in run_checks(root)['checks']
                                 if item['status'] == 'failed']
    return outcome
