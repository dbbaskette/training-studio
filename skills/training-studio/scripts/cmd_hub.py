"""The `hub` commands: share finished work with a team, and reuse what the team has shared."""
from pathlib import Path

import assess
import hub
import sync_guidance
from workspace import WorkspaceError


def join(args, root: Path) -> dict:
    return hub.join(args.url, args.name, args.init)


def listing(args, root: Path) -> dict:
    return hub.listing(root)


def use(args, root: Path) -> dict:
    return hub.use(root, args.name)


def publish(args, root: Path) -> dict:
    ready = assess.run_checks(root)['ready']
    pin = sync_guidance.summary(root)
    return hub.publish(root, ready, pin['commit'] if pin else None, args.message)


def status(args, root: Path) -> dict:
    return hub.status(root)


def sync(args, root: Path) -> dict:
    # `hub sync NAME` came before --hub, and guidance already fetched may still use it.
    if args.name and args.hub and args.name != args.hub:
        raise WorkspaceError('Name the hub once, with --hub NAME.')
    return hub.sync(hub.resolve(root, args.hub or args.name))


def find(args, root: Path) -> dict:
    return hub.find(hub.resolve(root, args.hub), ' '.join(args.query), args.kind)


def get_scenario(args, root: Path) -> dict:
    return hub.get_scenario(root, hub.resolve(root, args.hub), args.id, args.rename,
                            args.level)


def share_scenario(args, root: Path) -> dict:
    return hub.share_scenario(root, args.id, args.rename, args.level)


def get_audience(args, root: Path) -> dict:
    return hub.get_audience(hub.resolve(root, args.hub), args.id)


def share_audience(args, root: Path) -> dict:
    return hub.share_audience(hub.resolve(root, args.hub), args.id, Path(args.file))


def get_research(args, root: Path) -> dict:
    return hub.get_research(root, hub.resolve(root, args.hub), args.training, args.revision)


def register(commands) -> None:
    top = commands.add_parser('hub', help='share with a team hub, and reuse what it holds')
    actions = top.add_subparsers(dest='action', required=True, metavar='ACTION')

    def add(group, name: str, handler, text: str, hub_option: bool = False):
        parser = group.add_parser(name, help=text)
        parser.set_defaults(handler=handler)
        if hub_option:
            parser.add_argument('--hub', metavar='NAME',
                                help="a joined hub, if not this training's or the only one")
        return parser

    joining = add(actions, 'join', join, 'clone a hub and remember it')
    joining.add_argument('url', metavar='URL', help="the hub repository's address")
    joining.add_argument('--name', help='what to call it on this computer')
    joining.add_argument('--init', action='store_true',
                         help='lay out a new hub in an empty repository')

    add(actions, 'list', listing, 'joined hubs, and whether each has changes not yet pushed')
    add(actions, 'use', use, 'make a joined hub the one this training publishes to'
        ).add_argument('name', metavar='NAME', help='the name of a joined hub')
    add(actions, 'publish', publish, "publish this training's approved deliverables"
        ).add_argument('--message', metavar='TEXT', help='a line about this revision')
    add(actions, 'status', status, "this training's hub, its latest revision, and changes since")
    add(actions, 'sync', sync, 'fetch, rebase local commits and push', hub_option=True
        ).add_argument('name', metavar='NAME', nargs='?',
                       help='the same as --hub NAME, kept for older guidance')

    finding = add(actions, 'find', find, 'search titles, IDs and text', hub_option=True)
    finding.add_argument('query', metavar='QUERY', nargs='*', help='the words to look for')
    finding.add_argument('--kind', choices=('training', 'scenario', 'audience'),
                         help='look only for this kind of thing')

    getting = actions.add_parser('get', help='take something from a hub').add_subparsers(
        dest='what', required=True, metavar='WHAT')
    sharing = actions.add_parser('share', help='put something into a hub').add_subparsers(
        dest='what', required=True, metavar='WHAT')
    for group, handler, text, hub_option in (
            (getting, get_scenario, "copy a hub scenario into this training's scenario files",
             True),
            (sharing, share_scenario, "put one of this training's scenario files into its hub",
             False)):
        scenario = add(group, 'scenario', handler, text, hub_option)
        scenario.add_argument('id', metavar='ID', help="the scenario's ID")
        scenario.add_argument('--as', dest='rename', metavar='NAME',
                              help='the name to give the copy')
        scenario.add_argument('--level', help='the level, when this training has levels')

    add(getting, 'audience', get_audience, 'print an audience description, for intake',
        hub_option=True).add_argument('id', metavar='ID', help="the audience's ID")
    audience = add(sharing, 'audience', share_audience, 'put an audience description into a hub',
                   hub_option=True)
    audience.add_argument('id', metavar='ID', help='the ID to share it under')
    audience.add_argument('--file', required=True, metavar='FILE',
                          help='the description, a Markdown file the user wrote')

    research = add(getting, 'research', get_research,
                   "copy a published research report into this training's sources/",
                   hub_option=True)
    research.add_argument('training', metavar='TRAINING', help="the published training's ID")
    research.add_argument('--revision', type=int, metavar='N',
                          help='an older revision (default: the latest)')
