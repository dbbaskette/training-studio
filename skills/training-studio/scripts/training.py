#!/usr/bin/env python3
"""Training Studio helper. Run from the training directory; every command prints JSON."""
import sys

if sys.version_info < (3, 11):
    sys.exit('Training Studio needs Python 3.11 or newer; this is '
             + sys.version.split()[0] + '.')

import argparse
import json
from pathlib import Path

import checks
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
    profile = json.loads(workspace.PROFILE.read_text(encoding='utf-8'))
    outcomes, warnings, practice, blueprints = [], [], {}, {}
    without_scenario = []

    def file_of(name: str) -> str:
        return workspace.artifact(root, session, name)['file']

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
        yoodli_texts = []
        for name in own if 'scenario' in wanted else []:
            base = workspace.split(name)[0]
            source = read(root, found[name])
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
            exercised = checks.practice(parsed, yoodli_texts)
            warnings += [f'{level}: {text}' if level else text
                         for text in exercised.pop('warnings')]
            practice[level or ''] = exercised

    if len(blueprints) > 1:
        warnings += checks.level_overlap(blueprints)
    verdict = checks.readiness(
        [{'name': name, 'stage': workspace.artifact(root, session, name)['stage'],
          'status': status} for name, status in state.items()],
        workspace.export_states(root, session), outcomes,
        [stage for stage in workspace.SKIPPABLE if stage not in wanted],
        session['unavailable'], without_scenario)
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


class JsonParser(argparse.ArgumentParser):
    """An argument parser whose usage errors are JSON, like every other refusal."""

    def error(self, message):
        print(json.dumps({'error': message}))
        sys.exit(2)


def comma_list(text: str) -> list[str]:
    return [part.strip() for part in text.split(',') if part.strip()]


def parser() -> argparse.ArgumentParser:
    top = JsonParser(prog='training.py', description=__doc__)
    top.add_argument('--dir', default='.',
                     help='training directory (default: the current directory)')
    commands = top.add_subparsers(dest='command', required=True, parser_class=JsonParser)

    init = commands.add_parser('init', help='start a training in this directory')
    init.add_argument('--title', required=True)
    init.add_argument('--levels', type=comma_list, default=[],
                      help='comma-separated levels, for example 101,301; omit for none')
    init.add_argument('--brief-kind', default='product')
    init.add_argument('--deck-target')
    init.add_argument('--brand')

    commands.add_parser('status', help='stage, next step and the status of every artifact')

    save = commands.add_parser('save', help='record an artifact')
    save.add_argument('artifact')
    how = save.add_mutually_exclusive_group()
    how.add_argument('--from', dest='source', metavar='FILE',
                     help='replace the artifact with this file; the old version is kept')
    how.add_argument('--built', action='store_true',
                     help='the file on disk is a fresh build against its inputs')
    save.add_argument('--coverage', metavar='FILE',
                      help='deck only: JSON mapping each objective to the slides covering it')

    approve = commands.add_parser('approve', help="record the user's approval")
    approve.add_argument('artifact')
    approve.add_argument('--accept-stale', metavar='REASON',
                         help="the user's reason for accepting a stale artifact as it is")

    export = commands.add_parser('export', help='record a converted copy of an artifact')
    export.add_argument('artifact')
    made = export.add_mutually_exclusive_group()
    made.add_argument('--file', help='the export, if not the source name with .docx')
    made.add_argument('--unavailable', metavar='REASON',
                      help='the export could not be produced, and why')

    skip = commands.add_parser('skip', help='skip a stage, mark it unavailable, or restore it')
    skip.add_argument('stage')
    skip.add_argument('--reason')
    skip.add_argument('--unavailable', action='store_true')
    skip.add_argument('--clear', action='store_true')

    checkpoint = commands.add_parser('checkpoint', help='record where the run is')
    checkpoint.add_argument('--stage')
    checkpoint.add_argument('--level')
    checkpoint.add_argument('--next', dest='next_step', metavar='TEXT')
    question = checkpoint.add_mutually_exclusive_group()
    question.add_argument('--question', metavar='TEXT')
    question.add_argument('--no-question', action='store_true')
    checkpoint.add_argument('--deck-target')
    checkpoint.add_argument('--brand')
    checkpoint.add_argument('--brief-kind')
    checkpoint.add_argument('--levels', type=comma_list,
                            help='the levels of a levelled training, comma-separated')

    pin = commands.add_parser('pin', help='record a harness skill task to resume with')
    pin.add_argument('skill')
    pin.add_argument('--task', required=True)
    pin.add_argument('--runtime', required=True)
    pin.add_argument('--run')

    check = commands.add_parser('check', help='run the checks and report readiness')
    check.add_argument('--complete', action='store_true',
                       help='exit 1 unless the training is ready')
    check.add_argument('--all', action='store_true', help='list checks that passed too')
    return top


def dispatch(args: argparse.Namespace, root: Path) -> dict:
    if args.command == 'init':
        workspace.init(root, args.title, args.levels, args.brief_kind, args.deck_target,
                       args.brand)
        return workspace.status(root)
    if args.command == 'status':
        return workspace.status(root)
    if args.command == 'save':
        coverage = None
        if args.coverage:
            coverage = json.loads(Path(args.coverage).read_text(encoding='utf-8'))
        source = Path(args.source) if args.source else None
        entry = workspace.save(root, args.artifact, source, args.built, coverage)
        state = workspace.status(root)['artifacts'][args.artifact]
        return {'artifact': args.artifact, 'sha256': entry['sha256'], 'status': state}
    if args.command == 'approve':
        return workspace.approve(root, args.artifact, args.accept_stale)
    if args.command == 'export':
        return workspace.export(root, args.artifact, args.file, args.unavailable)
    if args.command == 'skip':
        return workspace.skip(root, args.stage, args.reason, args.unavailable, args.clear)
    if args.command == 'checkpoint':
        return workspace.checkpoint(root, args.stage, args.next_step, args.question,
                                    args.no_question, args.deck_target, args.brand,
                                    args.brief_kind, args.level, args.levels)
    if args.command == 'pin':
        return workspace.pin(root, args.skill, args.task, args.runtime, args.run)
    return run_checks(root, args.all)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        output = dispatch(args, Path(args.dir).resolve())
    except workspace.WorkspaceError as refusal:
        print(json.dumps({'error': str(refusal)}))
        return 2
    except (OSError, ValueError) as failure:
        print(json.dumps({'error': f'{type(failure).__name__}: {failure}'}))
        return 2
    print(json.dumps(output, indent=2, sort_keys=True))
    if args.command != 'check':
        return 0
    return 0 if (output['ready'] if args.complete else output['checks_passed']) else 1


if __name__ == '__main__':
    sys.exit(main())
