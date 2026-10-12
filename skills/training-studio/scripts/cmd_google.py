"""The `google` commands: send the document or the brief to a Google Doc and bring edits back.

A command plug-in. training.py finds this file, calls register(), and runs the handler set
on whichever sub-command was asked for. The rules themselves are in gdocs.py.
"""
from pathlib import Path

import gdocs


def push(args, root: Path) -> dict:
    if args.prepare:
        return gdocs.prepare(root, args.artifact, Path(args.prepare), args.title)
    return gdocs.push(root, args.artifact, gdocs.GcloudTransport(), args.force, args.title)


def record(args, root: Path) -> dict:
    return gdocs.record(root, args.artifact, args.file_id, args.url, Path(args.export),
                        args.title)


def pull(args, root: Path) -> dict:
    if args.source:
        return gdocs.pull(root, args.artifact, source=Path(args.source))
    return gdocs.pull(root, args.artifact, gdocs.GcloudTransport())


def status(args, root: Path) -> dict:
    return gdocs.status(root, None if args.offline else gdocs.GcloudTransport())


def unlink(args, root: Path) -> dict:
    return gdocs.unlink(root, args.artifact)


def register(commands) -> None:
    google = commands.add_parser(
        'google', help='send the document or the brief to a Google Doc and bring edits back')
    actions = google.add_subparsers(dest='google_command', required=True,
                                    metavar='push, record, pull, status or unlink')

    pushing = actions.add_parser('push', help='create the Doc, or replace its content')
    pushing.add_argument('artifact', help='document or brief, with @<level> if there are levels')
    how = pushing.add_mutually_exclusive_group()
    how.add_argument('--force', action='store_true',
                     help='replace the Doc even though it changed since the last sync')
    how.add_argument('--prepare', metavar='FILE',
                     help='only write the text to send, for a connector to transfer')
    pushing.add_argument('--title', help='the name of a new Doc')
    pushing.set_defaults(handler=push)

    recording = actions.add_parser('record', help='record a push a connector made')
    recording.add_argument('artifact')
    recording.add_argument('--file-id', required=True, help="the Doc's Google file ID")
    recording.add_argument('--url', required=True, help="the Doc's address")
    recording.add_argument('--export', required=True, metavar='FILE',
                           help="the Doc's markdown export, fetched after the push")
    recording.add_argument('--title', help="the Doc's name, if not the usual one")
    recording.set_defaults(handler=record)

    pulling = actions.add_parser('pull', help="bring the Doc's edits into the artifact")
    pulling.add_argument('artifact')
    pulling.add_argument('--from', dest='source', metavar='FILE',
                         help="the Doc's markdown export, fetched by a connector")
    pulling.set_defaults(handler=pull)

    reporting = actions.add_parser('status', help='sync state of every linked artifact')
    reporting.add_argument('--offline', action='store_true',
                           help='do not ask Google; report the local side only')
    reporting.set_defaults(handler=status)

    unlinking = actions.add_parser('unlink', help='forget the link; the Doc is not deleted')
    unlinking.add_argument('artifact')
    unlinking.set_defaults(handler=unlink)
