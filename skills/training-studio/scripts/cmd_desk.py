"""The `desk` command: serve the training desk until interrupted."""
import json
import signal


def interrupt(*_):
    raise KeyboardInterrupt


def port(text: str) -> int:
    number = int(text)
    if not 0 <= number <= 65535:
        raise ValueError(text)
    return number


def serve(args, root):
    """Print one line of JSON with the link, then serve. Never returns: it exits when stopped."""
    import desk  # only when asked for, so no other command loads the server
    server = desk.Desk(args.port)
    signal.signal(signal.SIGTERM, interrupt)
    try:
        print(json.dumps({'url': server.url}), flush=True)
        server.serve()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    raise SystemExit(0)


def register(commands):
    desk = commands.add_parser(
        'desk', help='show every training on this computer in a browser, read-only')
    desk.add_argument('--port', type=port, default=0,
                      help='the local port to serve on (default: one the system chooses)')
    desk.set_defaults(handler=serve)
