"""The training desk: a local, read-only page showing every training on this computer.

The server answers GET only, on 127.0.0.1 only. It reads through the same functions the
command line uses, so the page shows what the assistant sees, and it has nothing that writes.
"""
from __future__ import annotations

import codecs
import json
import secrets
import socketserver
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import home
import training
import workspace

HOST = '127.0.0.1'
TOKEN_HEADER = 'X-Training-Studio-Token'
PAGE_DIR = Path(__file__).resolve().parent / 'desk'
PAGE = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/index.html': ('index.html', 'text/html; charset=utf-8'),
    '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
    '/style.css': ('style.css', 'text/css; charset=utf-8'),
}
JSON = 'application/json; charset=utf-8'
SECURITY_HEADERS = {
    'Content-Security-Policy': "default-src 'self'",
    'X-Content-Type-Options': 'nosniff',
    'Cache-Control': 'no-store',
}
STATUSES = ('approved', 'draft', 'stale', 'not-started', 'skipped', 'unavailable')
TEXT_SUFFIXES = ('.md', '.json')
PREVIEW_LIMIT = 1_000_000


class Refusal(Exception):
    """A request the desk will not answer, with the HTTP status to refuse it with."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def describe(failure: Exception) -> str:
    """An error in the words the command line would use for it."""
    if isinstance(failure, (workspace.WorkspaceError, Refusal)):
        return str(failure)
    return f'{type(failure).__name__}: {failure}'


def as_json(status: int, value) -> tuple[int, str, bytes]:
    # "<" never leaves as itself, so no reader can take an answer for markup.
    text = json.dumps(value, sort_keys=True).replace('<', '\\u003c')
    return status, JSON, text.encode('utf-8')


# --- what the desk reads --------------------------------------------------------

def read(root: Path) -> tuple[dict, dict]:
    """A training's status report and check result, as the command line gives them.

    The same as `status` and `check`, except that reading here is not remembered in the
    registry: the desk writes nothing.
    """
    return training.describe(root), training.run_checks(root)


def touched(root: Path, seen: str) -> str:
    """When a training was last seen or its record last changed, whichever is later."""
    events = workspace.load(root)['events']
    stamps = [event['at'] for event in events
              if isinstance(event, dict) and isinstance(event.get('at'), str)]
    return max([seen, *stamps])


def known(entry: dict) -> dict:
    """What the registry says about a training, which is all there is if its record is broken."""
    seen = entry.get('seen_at')
    return {'path': entry['path'], 'title': entry.get('title'), 'levels': entry.get('levels'),
            'touched_at': seen if isinstance(seen, str) else ''}


def trainings() -> list[dict]:
    """Every training in the registry, most recently touched first."""
    listed = []
    for entry in home.trainings():
        item = known(entry)
        root = Path(entry['path'])
        try:
            report, result = read(root)
            counts = dict.fromkeys(STATUSES, 0)
            for state in report['artifacts'].values():
                counts[state] = counts.get(state, 0) + 1
            item.update(title=report['title'], levels=report['levels'], stage=report['stage'],
                        touched_at=touched(root, item['touched_at']), counts=counts,
                        ready=result['ready'], blocking=len(result['blocking']))
        except Exception as failure:  # one record that cannot be read must not hide the rest
            item['error'] = describe(failure)
        listed.append(item)
    return sorted(listed, key=lambda item: item['touched_at'], reverse=True)


def registered(path: str) -> dict:
    """The registry's entry for `path`. Any other folder is refused, whatever it holds."""
    for entry in home.trainings():
        if entry['path'] == path:
            return entry
    raise Refusal(HTTPStatus.FORBIDDEN, 'That folder is not a training this computer knows.')


def detail(path: str) -> dict:
    """One registered training: its status report and its check result."""
    item = known(registered(path))
    root = Path(path)
    try:
        report, result = read(root)
        item.update(title=report['title'], levels=report['levels'],
                    touched_at=touched(root, item['touched_at']), status=report, check=result)
    except Exception as failure:  # shown on the page, like the same training in the list
        item['error'] = describe(failure)
    return item


def preview(path: str, name: str) -> dict:
    """The text of one artifact's file, or just its name and size if it is not text."""
    registered(path)
    root = Path(path)
    session = workspace.load(root)
    if name not in workspace.artifact_names(root, session):
        raise Refusal(HTTPStatus.FORBIDDEN, f'{name} is not an artifact of this training.')
    relative = workspace.artifact(root, session, name)['file']
    file = (root / relative).resolve()
    if root.resolve() not in file.parents:
        raise Refusal(HTTPStatus.FORBIDDEN, f'{relative} leads outside the training folder.')
    if not file.is_file():
        raise Refusal(HTTPStatus.NOT_FOUND, f'{relative} does not exist yet.')
    shown = {'artifact': name, 'file': relative, 'size': file.stat().st_size, 'binary': True}
    if file.suffix not in TEXT_SUFFIXES:
        return shown
    with open(file, 'rb') as stream:
        data = stream.read(PREVIEW_LIMIT)
    truncated = shown['size'] > len(data)
    try:
        # A cut can fall inside a character; the decoder holds the loose bytes back.
        text = codecs.getincrementaldecoder('utf-8')().decode(data, final=not truncated)
    except UnicodeDecodeError:
        return shown
    if '\0' in text:
        return shown
    return {**shown, 'binary': False, 'text': text, 'truncated': truncated}


# --- the server -----------------------------------------------------------------

class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        """A reader that hangs up early gets no traceback: the command's output stays one line."""

    def server_bind(self):
        # The base class looks its own name up, which can ask the network. Nothing here does.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class Handler(BaseHTTPRequestHandler):
    timeout = 30  # seconds a connection may sit idle before it is dropped

    def version_string(self):
        return 'TrainingStudioDesk'

    def do_GET(self):
        try:
            reply = self.server.desk.answer(self.path, self.headers)
        except Refusal as refusal:
            reply = as_json(refusal.status, {'error': str(refusal)})
        except workspace.WorkspaceError as refusal:
            reply = as_json(HTTPStatus.CONFLICT, {'error': str(refusal)})
        except Exception as failure:  # answered like any other, never a dropped connection
            reply = as_json(HTTPStatus.INTERNAL_SERVER_ERROR, {'error': describe(failure)})
        self.reply(*reply)

    def refuse_method(self):
        self.reply(*as_json(HTTPStatus.METHOD_NOT_ALLOWED,
                            {'error': 'The desk is read-only: it answers GET and nothing else.'}),
                   allow='GET')

    do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = refuse_method
    do_OPTIONS = do_TRACE = do_CONNECT = refuse_method

    def reply(self, status: int, kind: str | None, body: bytes, allow: str | None = None):
        self.send_response(status)
        if kind:
            self.send_header('Content-Type', kind)
        if allow:
            self.send_header('Allow', allow)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def end_headers(self):
        """Every response leaves through here, so every response carries these."""
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    def send_error(self, code, message=None, explain=None):
        """The base class's own refusals, as JSON like the rest rather than as a page."""
        self.close_connection = True
        self.reply(*as_json(code, {'error': message or HTTPStatus(code).phrase}))

    def log_message(self, format, *args):
        """Nothing is logged: the command's output is one line, and stays one line."""


class Desk:
    """The desk's server. `start` serves on a thread, `serve` blocks, `stop` ends either."""

    def __init__(self, port: int = 0):
        self.token = secrets.token_urlsafe(32)
        self.server = Server((HOST, port), Handler)
        self.server.desk = self
        self.port = self.server.server_address[1]
        self.hosts = {f'{name}:{self.port}' for name in (HOST, 'localhost')}
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        """The link for the user. The token rides in the fragment, which is never sent."""
        return f'http://{HOST}:{self.port}/#token={self.token}'

    def serve(self) -> None:
        self.server.serve_forever()

    def start(self) -> None:
        self._thread = threading.Thread(target=self.server.serve_forever, args=(0.05,),
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is not None:
            self.server.shutdown()
            self._thread.join()
            self._thread = None
        self.server.server_close()

    def answer(self, target: str, headers) -> tuple[int, str | None, bytes]:
        """Answer one GET, or raise the refusal."""
        hosts = headers.get_all('Host') or []
        if len(hosts) != 1 or hosts[0].strip().lower() not in self.hosts:
            raise Refusal(HTTPStatus.FORBIDDEN, 'The desk answers only at its own local address.')
        try:
            url = urlsplit(target)
        except ValueError:
            raise Refusal(HTTPStatus.BAD_REQUEST, 'That address cannot be read.')
        if url.path in PAGE:
            name, kind = PAGE[url.path]
            return HTTPStatus.OK, kind, (PAGE_DIR / name).read_bytes()
        if url.path == '/favicon.ico':
            return HTTPStatus.NO_CONTENT, None, b''
        if not url.path.startswith('/api/'):
            raise Refusal(HTTPStatus.NOT_FOUND, 'Nothing is served here.')
        supplied = headers.get(TOKEN_HEADER, '')
        if not secrets.compare_digest(supplied.encode('utf-8'), self.token.encode('utf-8')):
            raise Refusal(HTTPStatus.FORBIDDEN, 'This needs the token from the link the desk '
                                                'printed when it started.')
        query = parse_qs(url.query, keep_blank_values=True)

        def one(name: str) -> str:
            values = query.get(name, [])
            if len(values) != 1 or not values[0]:
                raise Refusal(HTTPStatus.BAD_REQUEST, f'Give one {name}.')
            return values[0]

        if url.path == '/api/trainings':
            return as_json(HTTPStatus.OK, {'trainings': trainings()})
        if url.path == '/api/training':
            return as_json(HTTPStatus.OK, detail(one('path')))
        if url.path == '/api/file':
            return as_json(HTTPStatus.OK, preview(one('path'), one('artifact')))
        raise Refusal(HTTPStatus.NOT_FOUND, 'Nothing is served here.')
