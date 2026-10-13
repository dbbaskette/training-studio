"""The `desk` command: serve the page until interrupted."""
import json
import os
import signal
import sys
import webbrowser

NOT_A_PERSON = ('The link that opens the page carries its key, and the key is shown only to a '
                'person. To get the link, run this command in a terminal of your own.')


def interrupt(*_):
    raise KeyboardInterrupt


def port(text: str) -> int:
    number = int(text)
    if not 0 <= number <= 65535:
        raise ValueError(text)
    return number


def has_a_screen() -> bool:
    """Whether a browser with a window can be expected. A text browser is never started:
    it would take over the output this command is printing to."""
    return (sys.platform in ('darwin', 'win32')
            or any(os.environ.get(name) for name in ('BROWSER', 'DISPLAY', 'WAYLAND_DISPLAY')))


def show(url: str) -> bool:
    """Open the page in the default browser. False if there is none to open it in."""
    if not has_a_screen():
        return False
    try:
        return bool(webbrowser.open(url))
    except Exception:  # no browser after all: the user runs the command themselves
        return False


def announce(server, to_a_person: bool, opener=show) -> dict:
    """What the command prints, once. A terminal is a person and is given the link, whole.

    Anything else, an assistant or a pipe, is given the address without its key. The page is
    then opened in the browser instead, so that only the user ever holds the key.
    """
    if to_a_person:
        return {'url': server.url}
    return {'address': server.address, 'opened': opener(server.url), 'note': NOT_A_PERSON}


def serve(args, root):
    """Print one line of JSON, then serve. Never returns: it exits when stopped."""
    import desk  # only when asked for, so no other command loads the server
    server = desk.Desk(args.port)
    signal.signal(signal.SIGTERM, interrupt)
    try:
        print(json.dumps(announce(server, sys.stdout.isatty())), flush=True)
        server.serve()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    raise SystemExit(0)


def register(commands):
    desk = commands.add_parser(
        'desk', help='open the page: every training on this computer, and where gates are '
                     'decided')
    desk.add_argument('--port', type=port, default=0,
                      help='the local port to serve on (default: one the system chooses)')
    desk.set_defaults(handler=serve)
