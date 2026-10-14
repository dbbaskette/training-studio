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

import home
import sync_guidance
import workspace
from assess import decide, describe, run_checks


class JsonParser(argparse.ArgumentParser):
    """An argument parser whose usage errors are JSON, like every other refusal."""

    def error(self, message):
        print(json.dumps({'error': message}))
        sys.exit(2)


class ListOf(argparse.Action):
    """A flag that takes a list: values separated by spaces, or by commas as before, each
    one of `options`."""

    def __init__(self, option_strings, dest, options=(), **kwargs):
        self.options = tuple(options)
        kwargs.setdefault('metavar', '{' + ','.join(self.options) + '}')
        super().__init__(option_strings, dest, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        found = [part.strip() for value in values for part in value.split(',') if part.strip()]
        for value in found:
            if value not in self.options:
                parser.error(f'argument {option_string}: invalid choice: {value!r} '
                             f"(choose from {', '.join(self.options)})")
        setattr(namespace, self.dest, found)


def reason_for(flag: str, attached, reason: str | None) -> str | None:
    """The reason that goes with a flag: given with --reason, or after the flag itself, as
    guidance written before --reason does."""
    if attached is None:
        if reason is not None:
            raise workspace.WorkspaceError(f'--reason goes with {flag}.')
        return None
    if isinstance(attached, str):
        if reason is not None and reason != attached:
            raise workspace.WorkspaceError('Give the reason once, with --reason.')
        return attached
    if not (reason or '').strip():
        raise workspace.WorkspaceError(workspace.give_a_reason('chat'))
    return reason


def reasoned(parser, flag: str, text: str) -> None:
    """A flag that is given with --reason, and still takes the reason itself."""
    parser.add_argument(flag, nargs='?', const=True, metavar='REASON', help=text)


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


def summarise(root: Path) -> dict:
    """Status for the user; also remembers where this training is."""
    report = describe(root)
    home.remember(root, report['title'], report['levels'])
    return report


def parser() -> argparse.ArgumentParser:
    top = JsonParser(prog='training.py', description=__doc__)
    top.add_argument('--dir', default='.',
                     help='training directory (default: the current directory)')
    commands = top.add_subparsers(dest='command', required=True, parser_class=JsonParser)

    def settings(command, at_init: bool) -> None:
        """The settings init chooses and a checkpoint changes."""
        command.add_argument('--brief-kind', choices=workspace.BRIEF_KINDS,
                             default='product' if at_init else None,
                             help='the kind of brief to write (default at init: product)')
        command.add_argument('--deck-target', choices=workspace.DECK_TARGETS,
                             help='build the deck as a PowerPoint file or in Google Slides')
        command.add_argument('--brand', help='the brand the deck is built in; empty for none')
        command.add_argument('--copies', action=ListOf, options=workspace.COPIES, nargs='*',
                             default=[] if at_init else None,
                             help='copies to keep of each document and brief, separated by '
                                  'spaces; alone, none')

    init = commands.add_parser('init', help='start a training in this directory')
    init.add_argument('--title', required=True, help='the title of the training')
    init.add_argument('--levels', action=ListOf, options=workspace.LEVELS, nargs='+',
                      default=[], help='the levels, separated by spaces, for example 101 301; '
                                       'omit for a plain training')
    settings(init, at_init=True)
    init.add_argument('--yoodli', action='store_true',
                      help='also build a Yoodli scenario from each scenario file (optional)')
    init.add_argument('--approval', choices=workspace.APPROVAL, default='chat',
                      help='where gates are decided: in the conversation, or on the page')

    commands.add_parser('status', help='stage, next step and the status of every artifact')

    save = commands.add_parser('save', help='record an artifact')
    save.add_argument('artifact', help='the artifact, with @<level> if there are levels')
    how = save.add_mutually_exclusive_group()
    how.add_argument('--from', dest='source', metavar='FILE',
                     help='replace the artifact with this file; the old version is kept')
    how.add_argument('--built', action='store_true',
                     help='the file on disk is a fresh build against its inputs')
    save.add_argument('--coverage', metavar='FILE',
                      help='deck only: JSON mapping each objective to the slides covering it')

    approve = commands.add_parser('approve', help="record the user's approval")
    approve.add_argument('artifact', help='the artifact the user approved')
    reasoned(approve, '--accept-stale',
             "accept a stale artifact as it is, with the user's reason in --reason")
    approve.add_argument('--reason', help="the user's reason for accepting it as it is")

    export = commands.add_parser(
        'export', help='make a Word copy of an artifact with pandoc, and record it')
    export.add_argument('artifact', help='the document, the brief or a Yoodli scenario')
    made = export.add_mutually_exclusive_group()
    made.add_argument('--file', help='record a copy made another way, at this path, instead')
    reasoned(made, '--unavailable', 'record that no copy could be made, with why in --reason')
    export.add_argument('--reason', help='why no copy could be made')

    skip = commands.add_parser('skip', help='skip a stage, mark it unavailable, or restore it')
    skip.add_argument('stage', help='one of: ' + ', '.join(workspace.SKIPPABLE))
    skip.add_argument('--reason', help="the user's reason, or why the stage could not run")
    reasoned(skip, '--unavailable', 'the stage could not run, with why in --reason')
    skip.add_argument('--clear', action='store_true',
                      help='bring back a stage that was skipped or unavailable')

    checkpoint = commands.add_parser('checkpoint', help='record where the run is')
    checkpoint.add_argument('--stage', choices=workspace.STAGES,
                            help='the stage the training is at')
    checkpoint.add_argument('--level', choices=workspace.LEVELS,
                            help='the level being worked on')
    checkpoint.add_argument('--next', dest='next_step', metavar='TEXT',
                            help='the next step, in a sentence')
    question = checkpoint.add_mutually_exclusive_group()
    question.add_argument('--question', metavar='TEXT',
                          help='the question waiting on the user')
    question.add_argument('--no-question', action='store_true',
                          help='clear the waiting question and the gate')
    settings(checkpoint, at_init=False)
    levels = checkpoint.add_mutually_exclusive_group()
    levels.add_argument('--levels', action=ListOf, options=workspace.LEVELS, nargs='+',
                        help='the levels of a levelled training, separated by spaces; '
                             'never drops a level with work in it')
    levels.add_argument('--add-level', dest='add_levels', action=ListOf,
                        options=workspace.LEVELS, nargs='+',
                        help='add one or more levels to a levelled training')
    checkpoint.add_argument('--gate', metavar='ARTIFACT',
                            help='the artifact waiting at the gate; --no-question clears it')
    checkpoint.add_argument('--approval', choices=workspace.APPROVAL,
                            help='where gates are decided; only the page moves it back to chat')

    pin = commands.add_parser('pin', help='record a harness skill task to resume with')
    pin.add_argument('skill', choices=workspace.PINNABLE, help='the skill the task belongs to')
    pin.add_argument('--task', required=True, help="the task's ID in that skill")
    pin.add_argument('--runtime', required=True, help="the skill's runtime folder")
    pin.add_argument('--run', help="the run's ID, if the skill gives one")
    pin.add_argument('--level', choices=workspace.LEVELS,
                     help='the level this task belongs to, for a per-level deck')

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
        if args.accept_stale is True:  # the decision refuses a missing reason itself
            return decide(root, args.artifact, 'accept', args.reason)
        reason = reason_for('--accept-stale', args.accept_stale, args.reason)
        return decide(root, args.artifact, 'approve' if reason is None else 'accept', reason)
    if args.command == 'export':
        unavailable = reason_for('--unavailable', args.unavailable, args.reason)
        return workspace.export(root, args.artifact, args.file, unavailable,
                                convert=workspace.pandoc)
    if args.command == 'skip':
        reason = args.reason
        if isinstance(args.unavailable, str):  # the reason given after the flag, as before
            reason = reason_for('--unavailable', args.unavailable, args.reason)
        if args.unavailable and not args.clear:  # a report that it could not run, not a decision
            return workspace.skip(root, args.stage, reason, unavailable=True)
        return decide(root, args.stage, 'restore' if args.clear else 'skip', reason)
    if args.command == 'checkpoint':
        return workspace.checkpoint(root, args.stage, args.next_step, args.question,
                                    args.no_question, args.deck_target, args.brand,
                                    args.brief_kind, args.level, args.levels, args.copies,
                                    args.approval, args.gate, add_levels=args.add_levels)
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
