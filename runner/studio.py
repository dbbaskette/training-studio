#!/usr/bin/env python3
"""The runner's command line.

    studio serve [--port N]    start the runner and print the link to its page
    studio status              what is set up and where every run is, as JSON for a script

`serve` is started by a person. To a terminal it prints the link whole, with its key. To
anything else, such as an assistant or a pipe, it prints the address without the key and
opens the page in the browser itself, so only the person ever holds the key. It runs until
it is interrupted, and picks every training up where its files say it is when started again.
It fetches a shared workspace when it starts and every few minutes while it serves, and can
tell the person through the computer's own notifications when no page is open.
One runner serves on a computer at a time: a second would undo what the first is doing.
"""
import sys

if sys.version_info < (3, 11):
    sys.exit('The runner needs Python 3.11 or newer; this is ' + sys.version.split()[0] + '.')

import argparse
import json
import os
import signal
from contextlib import contextmanager
from pathlib import Path

if not __package__:  # started by its path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import runner  # noqa: F401,E402  puts the core on the import path
import cmd_desk  # noqa: E402
import home  # noqa: E402
from workspace import WorkspaceError  # noqa: E402

from runner import engine as engines  # noqa: E402
from runner import gitstate, page, setup  # noqa: E402


def alive(pid: int) -> bool:
    """True while a process with this number exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextmanager
def only_runner():
    """Be the one runner serving on this computer, or refuse. A runner that ended without
    saying so is not counted."""
    path = home.data_root() / 'runner.pid'
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            kept = path.read_text(encoding='utf-8').strip() if path.is_file() else ''
            if kept.isdigit() and int(kept) != os.getpid() and alive(int(kept)):
                raise WorkspaceError(
                    f'A runner is already serving on this computer (process {kept}). Use '
                    'its page, or stop it before starting another. If none is running, '
                    f'remove {path} and try again.')
            path.unlink(missing_ok=True)
            continue
        os.write(handle, f'{os.getpid()}\n'.encode())
        os.close(handle)
        break
    else:
        raise WorkspaceError(f'Could not write {path}, which says a runner is serving.')
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def serve(args, make=engines.Engine, out=None, opener=cmd_desk.show) -> int:
    """Print one line of JSON, then serve until interrupted."""
    out = out or sys.stdout
    space = gitstate.current()
    if space is not None:
        gitstate.identity(space.repo)  # nothing can be recorded without one; says the fix
    with only_runner():
        engine = make()
        server = page.Studio(engine, args.port)
        signal.signal(signal.SIGTERM, cmd_desk.interrupt)
        try:
            print(json.dumps(cmd_desk.announce(server, out.isatty(), opener)), file=out,
                  flush=True)
            engine.resume()
            server.serve()
        except KeyboardInterrupt:
            pass
        finally:
            server.stop()
    return 0


def status(args, make=engines.Engine, out=None) -> int:
    """What is set up on this computer and where every run is. Starts nothing."""
    engine = make()
    report = {'version': gitstate.installed(), **setup.describe(engine), **engine.status()}
    print(json.dumps(report, indent=2, sort_keys=True), file=out or sys.stdout)
    return 0


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog='studio', description=__doc__.splitlines()[0])
    commands = top.add_subparsers(dest='command', required=True)
    serving = commands.add_parser('serve', help='start the runner and print the link')
    serving.add_argument('--port', type=cmd_desk.port, default=0,
                         help='the local port to serve on (default: one the system chooses)')
    serving.set_defaults(handler=serve)
    commands.add_parser('status', help='what is set up and where every run is, as JSON'
                        ).set_defaults(handler=status)
    return top


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.handler(args)
    except WorkspaceError as refusal:
        print(json.dumps({'error': str(refusal)}))
        return 2
    except OSError as failure:
        print(json.dumps({'error': f'{type(failure).__name__}: {failure}'}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
