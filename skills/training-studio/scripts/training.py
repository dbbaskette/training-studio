#!/usr/bin/env python3
"""Training Studio helper. Run from the training directory; every command prints JSON."""
import sys

if sys.version_info < (3, 11):
    sys.exit('Training Studio needs Python 3.11 or newer; this is '
             + sys.version.split()[0] + '.')

import argparse
import importlib.util
import json
from pathlib import Path

import checks
import gdocs
import home
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


class JsonParser(argparse.ArgumentParser):
    """An argument parser whose usage errors are JSON, like every other refusal."""

    def error(self, message):
        print(json.dumps({'error': message}))
        sys.exit(2)


def comma_list(text: str) -> list[str]:
    return [part.strip() for part in text.split(',') if part.strip()]


def plugins() -> list:
    """Optional command modules: every cmd_*.py beside this file.

    Each defines register(commands), which adds its sub-commands and gives each a `handler`
    default: a function taking (args, root) and returning the JSON to print.
    """
    found = []
    for path in sorted(Path(__file__).resolve().parent.glob('cmd_*.py')):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        found.append(module)
    return found


def describe(root: Path) -> dict:
    """Status for the user: the workspace's, with the Google Docs it keeps and the guidance pin."""
    report = workspace.status(root)
    report['google_docs'] = gdocs.copy_states(root, workspace.load(root))
    report['guidance'] = sync_guidance.summary(root)
    return report


def summarise(root: Path) -> dict:
    """Status for the user; also remembers where this training is."""
    report = describe(root)
    home.remember(root, report['title'], report['levels'])
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
    init.add_argument('--yoodli', action='store_true',
                      help='also build a Yoodli scenario from each scenario file (optional)')
    init.add_argument('--copies', nargs='*', choices=workspace.COPIES, default=[],
                      help='copies to keep of each document and brief (optional)')
    init.add_argument('--approval', choices=workspace.APPROVAL, default='chat',
                      help='where gates are decided: in the conversation, or on the page')

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
    checkpoint.add_argument('--copies', nargs='*', choices=workspace.COPIES,
                            help='copies to keep of each document and brief; alone, none')
    checkpoint.add_argument('--gate', metavar='ARTIFACT',
                            help='the artifact waiting at the gate; --no-question clears it')
    checkpoint.add_argument('--approval', choices=workspace.APPROVAL,
                            help='where gates are decided; only the page moves it back to chat')

    pin = commands.add_parser('pin', help='record a harness skill task to resume with')
    pin.add_argument('skill')
    pin.add_argument('--task', required=True)
    pin.add_argument('--runtime', required=True)
    pin.add_argument('--run')
    pin.add_argument('--level', help='the level this task belongs to, for a per-level deck')

    check = commands.add_parser('check', help='run the checks and report readiness')
    check.add_argument('--complete', action='store_true',
                       help='exit 1 unless the training is ready')
    check.add_argument('--all', action='store_true', help='list checks that passed too')

    commands.add_parser('list', help='the trainings on this computer, most recent first')
    for plugin in plugins():
        plugin.register(commands)
    return top


def dispatch(args: argparse.Namespace, root: Path) -> dict:
    handler = getattr(args, 'handler', None)
    if handler is not None:
        return handler(args, root)
    if args.command == 'list':
        return {'trainings': home.trainings()}
    if args.command == 'init':
        workspace.init(root, args.title, args.levels, args.brief_kind, args.deck_target,
                       args.brand, args.yoodli, args.copies, args.approval)
        sync_guidance.adopt(root)
        return summarise(root)
    if args.command == 'status':
        return summarise(root)
    if args.command == 'save':
        coverage = None
        if args.coverage:
            coverage = json.loads(Path(args.coverage).read_text(encoding='utf-8'))
        source = Path(args.source) if args.source else None
        entry = workspace.save(root, args.artifact, source, args.built, coverage)
        state = workspace.status(root)['artifacts'][args.artifact]
        return {'artifact': args.artifact, 'sha256': entry['sha256'], 'status': state}
    if args.command == 'approve':
        return decide(root, args.artifact, 'accept' if args.accept_stale else 'approve',
                      args.accept_stale)
    if args.command == 'export':
        return workspace.export(root, args.artifact, args.file, args.unavailable)
    if args.command == 'skip':
        if args.unavailable and not args.clear:  # a report that it could not run, not a decision
            return workspace.skip(root, args.stage, args.reason, unavailable=True)
        return decide(root, args.stage, 'restore' if args.clear else 'skip', args.reason)
    if args.command == 'checkpoint':
        return workspace.checkpoint(root, args.stage, args.next_step, args.question,
                                    args.no_question, args.deck_target, args.brand,
                                    args.brief_kind, args.level, args.levels, args.copies,
                                    args.approval, args.gate)
    if args.command == 'pin':
        return workspace.pin(root, args.skill, args.task, args.runtime, args.run,
                             args.level)
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
