"""The Google Docs round-trip for the document and the brief.

Keeps the link record, applies the sync rules, carries coverage comments across a format
that drops them, and talks to Google Drive. No argument parsing: cmd_google.py does that.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import re
import secrets
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import home
import workspace
from workspace import WorkspaceError

SCHEMA = 1
RECORD = f'{workspace.STATE_DIR}/google.json'
SYNCED = ('document', 'brief')
STATES = {(False, False): 'in sync', (True, False): 'local changed',
          (False, True): 'remote changed', (True, True): 'both changed'}
FILE_ID = re.compile(r'^[A-Za-z0-9_-]+$')

# --- coverage comments ------------------------------------------------------------
# Google Docs drops HTML comments, so they stay here while the text is away.

COMMENT = re.compile(r'<!--\s*(?:covers|findings):.*?-->', re.DOTALL)
HEADING = re.compile(r'^ {0,3}#{1,6}[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$')
FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})')
NUMBERING = re.compile(r'^\d+(?:\.\d+)*[.)]\s+')
BLANK_LINE = re.compile(r'[ \t]*\r?\n')


def scan(text: str) -> tuple[list[tuple[int, int, str]], list[tuple[int, int]]]:
    """Headings as (start, end of line, text), and the spans of fenced code blocks."""
    headings, fences, fence, offset = [], [], None, 0
    for line in text.splitlines(keepends=True):
        marker = FENCE.match(line)
        if fence is not None:
            if marker and marker.group(1)[0] == fence[0]:
                fences.append((fence[1], offset + len(line)))
                fence = None
        elif marker:
            fence = (marker.group(1)[0], offset)
        else:
            found = HEADING.match(line.rstrip('\r\n'))
            if found:
                title = COMMENT.sub('', found.group(1)).strip()
                headings.append((offset, offset + len(line), title))
        offset += len(line)
    if fence is not None:
        fences.append((fence[1], len(text)))
    return headings, fences


def heading_key(title: str) -> str:
    """A heading's text as it is matched: no numbering, spacing or export decoration."""
    plain = re.sub(r'\\([^\w\s])', r'\1', title)
    plain = re.sub(r'[*_`]', '', plain).strip()
    return ' '.join(NUMBERING.sub('', plain).split())


def strip_comments(text: str) -> tuple[str, list[list]]:
    """The text without its coverage comments, and an anchor for each one removed.

    An anchor is [heading text, comment]: the nearest heading above the comment. Under a
    heading whose text is used more than once it has a third item, which one, counting
    from 1, unless it is the first.
    """
    headings, fences = scan(text)
    anchors, kept, position = [], '', 0
    for match in COMMENT.finditer(text):
        if any(start <= match.start() < end for start, end in fences):
            continue
        above = [title for start, _, title in headings if start < match.start()]
        anchor = [above[-1] if above else '', match.group(0)]
        nth = sum(1 for title in above if heading_key(title) == heading_key(anchor[0]))
        anchors.append(anchor + [nth] if nth > 1 else anchor)

        line_start = text.rfind('\n', 0, match.start()) + 1
        newline = text.find('\n', match.end())
        line_end = len(text) if newline < 0 else newline + 1
        own_line = not (text[line_start:match.start()] + text[match.end():line_end]).strip()
        if own_line:
            kept += text[position:line_start]
            position = line_end
            follows = BLANK_LINE.match(text, position)
            if follows and (not kept.strip() or kept.endswith(('\n\n', '\n\r\n'))):
                position = follows.end()
        else:
            kept += text[position:match.start()].rstrip(' \t')
            position = match.end()
    return kept + text[position:], anchors


def restore_comments(text: str, anchors: list) -> tuple[str, list[dict]]:
    """Put each comment back on its own line under its heading.

    Returns the text, and the anchors whose heading is no longer there.
    """
    headings, _ = scan(text)
    found: dict[str, list[int]] = {}
    for _, end, title in headings:
        found.setdefault(heading_key(title), []).append(end)
    placed: dict[int, list[str]] = {}
    unplaced = []
    for title, comment, *rest in anchors:
        ends = found.get(heading_key(title), []) if title else [0]
        nth = rest[0] if rest else 1
        if len(ends) < nth:
            unplaced.append({'heading': title, 'comment': comment})
        else:
            placed.setdefault(ends[nth - 1], []).append(comment)
    out, position = '', 0
    for end in sorted(placed):
        out += text[position:end]
        if end and not out.endswith('\n'):
            out += '\n'
        out += ('\n' if end else '') + '\n'.join(placed[end]) + '\n'
        if text[end:].strip() and not BLANK_LINE.match(text, end):
            out += '\n'
        position = end
    return out + text[position:], unplaced


# --- text and hashes -----------------------------------------------------------------

def canonical(text: str) -> str:
    """Exported text with one kind of line ending, no byte order mark and one final newline.

    None of these can be an edit, and each differs between the ways an export reaches us.
    """
    plain = text.removeprefix('\ufeff').replace('\r\n', '\n').replace('\r', '\n').rstrip()
    return plain + '\n' if plain else ''


def digest(text: str) -> str:
    """The hash of an export, as it is recorded and compared."""
    return hashlib.sha256(canonical(text).encode('utf-8')).hexdigest()


# --- the link record -----------------------------------------------------------------

def is_anchor(value) -> bool:
    return (isinstance(value, list) and len(value) in (2, 3)
            and all(isinstance(part, str) for part in value[:2])
            and (len(value) == 2 or (type(value[2]) is int and value[2] > 0)))


def read_links(root: Path) -> dict:
    path = workspace.managed(root, RECORD)
    if not path.is_file():
        return {'schema': SCHEMA, 'docs': {}}
    links = home.read_json(path, None)
    usable = (isinstance(links, dict) and links.get('schema') == SCHEMA
              and isinstance(links.get('docs'), dict)
              and all(isinstance(entry, dict) and isinstance(entry.get('file_id'), str)
                      and isinstance(entry.get('anchors'), list)
                      and all(is_anchor(anchor) for anchor in entry['anchors'])
                      for entry in links['docs'].values()))
    if not usable:
        raise WorkspaceError(f'{RECORD} is not a Google Docs record this helper can read; '
                             'refusing to change it.')
    return links


def write_links(root: Path, links: dict) -> None:
    home.write_json(workspace.managed(root, RECORD), links)


def linked(links: dict, name: str) -> dict:
    entry = links['docs'].get(name)
    if entry is None:
        raise WorkspaceError(f'{name} is not linked to a Google Doc. Push it first.')
    return entry


def target(root: Path, name: str) -> tuple[dict, dict, Path]:
    """The session, the artifact's details and its file, for an artifact that may be synced."""
    session = workspace.load(root)
    if workspace.split(name)[0] not in SYNCED:
        raise WorkspaceError(f'{name} does not go to Google Docs; only the document and the '
                             'brief do.')
    spec = workspace.artifact(root, session, name)
    return session, spec, workspace.managed(root, spec['file'])


def titled(session: dict, name: str, entry: dict | None, title: str | None) -> str:
    """The Doc's name: the one it has, the one asked for, or one made from the training's."""
    if entry and title:
        raise WorkspaceError(f'{name} is already linked to a Google Doc; a title only names '
                             'a new one.')
    if entry and entry.get('title'):
        return entry['title']
    base, level = workspace.split(name)
    kind = 'learner guide' if base == 'document' else f"{session['settings']['brief_kind']} brief"
    return title or f"{session['title']}: {kind}" + (f' ({level})' if level else '')


def local(path: Path, spec: dict) -> tuple[str, str]:
    """The local file's text and hash, read once so the two always agree."""
    if not path.is_file():
        raise WorkspaceError(f"{spec['file']} does not exist, so there is nothing to send.")
    data = path.read_bytes()
    return data.decode('utf-8'), hashlib.sha256(data).hexdigest()


def exported(source: Path) -> str:
    """A Doc's markdown export that a connector saved to a file."""
    if not source.is_file():
        raise WorkspaceError(f'{source} does not exist.')
    text = canonical(source.read_text(encoding='utf-8'))
    if not text:
        raise WorkspaceError(f'{source} is empty. Export the Doc as markdown and try again.')
    return text


# --- the sync rules ------------------------------------------------------------------

def prepare(root: Path, name: str, out: Path, title: str | None = None) -> dict:
    """Write the text a connector should send. Records nothing."""
    session, spec, path = target(root, name)
    entry = read_links(root)['docs'].get(name, {})
    title = titled(session, name, entry, title)
    text, anchors = strip_comments(local(path, spec)[0])
    out = out.resolve()
    if out == root or root in out.parents:
        raise WorkspaceError('Write the prepared text to a file outside the training directory.')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(text.encode('utf-8'))
    return {'artifact': name, 'prepared': str(out), 'comments_held': len(anchors),
            'linked': bool(entry), 'file_id': entry.get('file_id'), 'url': entry.get('url'),
            'title': title}


def push(root: Path, name: str, transport: Transport, force: bool = False,
         title: str | None = None) -> dict:
    """Create the Doc, or replace its content, and record both sides as they now stand."""
    session, spec, path = target(root, name)
    with workspace.locked(root):
        links = read_links(root)
        text, sha256 = local(path, spec)
        clean, anchors = strip_comments(text)
        entry = links['docs'].get(name)
        title = titled(session, name, entry, title)
        if entry is None:
            entry = {**transport.create(title, clean), 'title': title}
            result = 'created'
        else:
            known = entry.get('remote_sha256')
            if known and not force and digest(transport.export(entry['file_id'])) != known:
                raise WorkspaceError('The Google Doc changed since the last sync. Pull first.')
            transport.update(entry['file_id'], clean)
            result = 'updated'
        # Until the Doc is read back the link is kept with nothing to compare against, so a
        # failure here leads to another push of the same Doc and never to a second Doc.
        entry.update(anchors=anchors, local_sha256=None, remote_sha256=None,
                     synced_at=entry.get('synced_at'))
        links['docs'][name] = entry
        write_links(root, links)
        seen = digest(transport.export(entry['file_id']))
        entry.update(local_sha256=sha256, remote_sha256=seen, synced_at=home.now())
        write_links(root, links)
    return {'artifact': name, 'result': result, 'file': spec['file'], 'state': 'in sync',
            'file_id': entry['file_id'], 'url': entry['url'], 'title': entry['title'],
            'comments_held': len(anchors)}


def record(root: Path, name: str, file_id: str, url: str, export: Path,
           title: str | None = None) -> dict:
    """Record a push a connector made, taking `export` as the Doc's markdown export."""
    session, spec, path = target(root, name)
    if not FILE_ID.match(file_id):
        raise WorkspaceError('That is not a Google file ID: it holds only letters, digits, '
                             'hyphens and underscores.')
    if not url.startswith('https://'):
        raise WorkspaceError("Give the Doc's address, starting with https://.")
    remote = exported(export)
    with workspace.locked(root):
        links = read_links(root)
        text, sha256 = local(path, spec)
        anchors = strip_comments(text)[1]
        before = links['docs'].get(name, {})
        same = before if before.get('file_id') == file_id and not title else None
        entry = {'file_id': file_id, 'url': url, 'title': titled(session, name, same, title),
                 'local_sha256': sha256, 'remote_sha256': digest(remote), 'anchors': anchors,
                 'synced_at': home.now()}
        links['docs'][name] = entry
        write_links(root, links)
    return {'artifact': name, 'result': 'recorded', 'file': spec['file'], 'state': 'in sync',
            'file_id': file_id, 'url': url, 'title': entry['title'],
            'comments_held': len(anchors)}


def pull(root: Path, name: str, transport: Transport | None = None,
         source: Path | None = None) -> dict:
    """Bring the Doc's edits into the artifact. `source` is an export a connector fetched."""
    session, spec, path = target(root, name)
    entry = linked(read_links(root), name)
    if not entry.get('remote_sha256'):
        raise WorkspaceError(f'The last push of {name} did not finish, so there is nothing to '
                             'compare the Doc with. Push it again first.')
    remote = exported(source) if source else canonical(transport.export(entry['file_id']))
    if not remote:
        raise WorkspaceError(f"The Doc's export is empty; refusing to replace {spec['file']} "
                             'with nothing.')
    changed = workspace.sha256_file(path) != entry.get('local_sha256')
    if digest(remote) == entry['remote_sha256']:
        return {'artifact': name, 'result': 'nothing to do', 'file': spec['file'],
                'state': STATES[changed, False]}
    text, unplaced = restore_comments(remote, entry['anchors'])

    if changed:
        beside = Path(spec['file']).with_suffix('.remote.md').as_posix()
        workspace.write_atomic(workspace.managed(root, beside), text.encode('utf-8'))
        lost = ''.join(f' {item["comment"]} could not be put back in it: the heading '
                       f'"{item["heading"]}" is gone.' for item in unplaced)
        raise WorkspaceError(
            f"{spec['file']} and its Google Doc have both changed since the last sync. The "
            f"Doc's text is in {beside} and neither was altered.{lost} Reconcile the two in "
            f"{spec['file']}, then push with --force.")

    with tempfile.TemporaryDirectory() as scratch:
        incoming = Path(scratch) / path.name
        incoming.write_bytes(text.encode('utf-8'))
        # An edit made in Google is an edit, not a rebuild: it must not clear staleness.
        workspace.save(root, name, source=incoming, edit=True)
    with workspace.locked(root):
        links = read_links(root)
        links['docs'][name] = {**entry, 'local_sha256': workspace.sha256_file(path),
                               'remote_sha256': digest(remote),
                               'anchors': strip_comments(text)[1], 'synced_at': home.now()}
        write_links(root, links)
    after = workspace.statuses(root, workspace.load(root))
    return {'artifact': name, 'result': 'pulled', 'file': spec['file'], 'status': after[name],
            'stale': [other for other, state in after.items() if state == 'stale'],
            'unplaced': unplaced}


def status(root: Path, transport: Transport | None = None) -> dict:
    """Sync state of every linked artifact. Without a transport, the local side only."""
    session = workspace.load(root)
    docs = {}
    for name, entry in sorted(read_links(root)['docs'].items()):
        report = docs[name] = {'url': entry.get('url'), 'title': entry.get('title'),
                               'synced_at': entry.get('synced_at')}
        try:
            report['file'] = workspace.artifact(root, session, name)['file']
        except WorkspaceError as problem:
            report.update(state='unavailable', problem=str(problem))
            continue
        changed = workspace.sha256_file(root / report['file']) != entry.get('local_sha256')
        if transport is None:
            report['state'] = 'local changed' if changed else 'local unchanged'
            continue
        known = entry.get('remote_sha256')
        moved = bool(known) and digest(transport.export(entry['file_id'])) != known
        report['state'] = STATES[changed, moved]
    return {'docs': docs, 'offline': transport is None}


def copy_states(root: Path, session: dict) -> dict[str, str]:
    """For a training that keeps Google Docs: whether each document and brief has a Doc,
    and whether the file has changed since the two last agreed. Nothing here asks Google."""
    if 'google' not in session['settings']['copies']:
        return {}
    docs = read_links(root)['docs']
    states = {}
    for name in workspace.artifact_names(root, session):
        if workspace.split(name)[0] not in SYNCED:
            continue
        entry = docs.get(name)
        if entry is None:
            states[name] = 'missing'
            continue
        file = workspace.artifact(root, session, name)['file']
        same = workspace.sha256_file(root / file) == entry.get('local_sha256')
        states[name] = 'current' if same else 'outdated'
    return states


def unlink(root: Path, name: str) -> dict:
    """Forget the link. The Doc is left exactly as it is."""
    workspace.load(root)
    with workspace.locked(root):
        links = read_links(root)
        entry = linked(links, name)
        del links['docs'][name]
        write_links(root, links)
    return {'artifact': name, 'unlinked': True, 'url': entry.get('url'),
            'note': 'The Google Doc was not deleted or changed.'}


# --- transports ------------------------------------------------------------------------

class Transport:
    """What the sync rules need from Google Drive. Nothing here deletes or shares."""

    def create(self, title: str, markdown: str) -> dict:
        """Make a Doc from markdown. Returns {'file_id', 'url'}."""
        raise NotImplementedError

    def update(self, file_id: str, markdown: str) -> None:
        """Replace a Doc's content with markdown."""
        raise NotImplementedError

    def export(self, file_id: str) -> str:
        """A Doc's content as markdown."""
        raise NotImplementedError


_FILES = 'https://www.googleapis.com/drive/v3/files'
_UPLOAD = 'https://www.googleapis.com/upload/drive/v3/files'
_VIEW = 'https://docs.google.com/document/d/{}/edit'
_DOC = 'application/vnd.google-apps.document'
_MARKDOWN = 'text/markdown; charset=UTF-8'
_SIGN_IN = 'gcloud auth login --enable-gdrive-access'
_TIMEOUT = 60


class GcloudTransport(Transport):
    """The Drive v3 REST API over urllib, signed in through the gcloud command.

    The access token is held in memory for the life of this object and goes only into the
    Authorization header. It is never written, printed or put in a refusal.
    """

    def __init__(self, run=None, urlopen=None):
        self._run = run or subprocess.run
        self._urlopen = urlopen or urllib.request.urlopen
        self._token = None

    def create(self, title: str, markdown: str) -> dict:
        boundary = f'training-studio-{secrets.token_hex(16)}'
        metadata = json.dumps({'name': title, 'mimeType': _DOC})
        body = (f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'
                f'{metadata}\r\n--{boundary}\r\nContent-Type: {_MARKDOWN}\r\n\r\n'
                f'{markdown}\r\n--{boundary}--\r\n').encode('utf-8')
        reply = self._send('POST', f'{_UPLOAD}?uploadType=multipart&fields=id%2CwebViewLink',
                           body, f'multipart/related; boundary={boundary}')
        try:
            made = json.loads(reply)
            file_id = made['id']
        except (ValueError, KeyError, TypeError):
            raise WorkspaceError('Google Drive did not say which Doc it made. Look in Drive '
                                 'for a new Doc before pushing again.') from None
        return {'file_id': file_id, 'url': made.get('webViewLink') or _VIEW.format(file_id)}

    def update(self, file_id: str, markdown: str) -> None:
        address = f'{_UPLOAD}/{urllib.parse.quote(file_id, safe="")}?uploadType=media'
        self._send('PATCH', address, markdown.encode('utf-8'), _MARKDOWN)

    def export(self, file_id: str) -> str:
        reply = self._send('GET', f'{_FILES}/{urllib.parse.quote(file_id, safe="")}/export?'
                           + urllib.parse.urlencode({'mimeType': 'text/markdown'}))
        try:
            return reply.decode('utf-8')
        except UnicodeDecodeError:
            raise WorkspaceError("Google's export of the Doc was not readable text. "
                                 'Try again.') from None

    def _access_token(self) -> str:
        if self._token is None:
            try:
                done = self._run(['gcloud', 'auth', 'print-access-token'], capture_output=True,
                                 text=True, timeout=_TIMEOUT)
            except FileNotFoundError:
                raise WorkspaceError(
                    'The gcloud command was not found. Install the Google Cloud CLI and run '
                    f"`{_SIGN_IN}`, or use the assistant's Google Drive connector with "
                    'google push --prepare.') from None
            except (OSError, subprocess.SubprocessError):
                raise WorkspaceError(f'The gcloud command did not answer. Run `{_SIGN_IN}` '
                                     'and try again.') from None
            # Nothing gcloud printed is repeated: its output is where the token is.
            token = (done.stdout or '').strip() if done.returncode == 0 else ''
            if not token or len(token.split()) != 1:
                raise WorkspaceError('gcloud has no signed-in account it can give access '
                                     f'for. Run `{_SIGN_IN}` and try again.')
            self._token = token
        return self._token

    def _send(self, method: str, url: str, body: bytes | None = None,
              content_type: str | None = None) -> bytes:
        token = self._access_token()
        request = urllib.request.Request(url, data=body, method=method)
        request.add_header('Authorization', f'Bearer {token}')
        if content_type:
            request.add_header('Content-Type', content_type)
        try:
            with self._urlopen(request, timeout=_TIMEOUT) as response:
                return response.read()
        except urllib.error.HTTPError as failure:
            refusal = self._explain(failure)
        except (OSError, http.client.HTTPException) as failure:
            reason = getattr(failure, 'reason', None) or failure
            refusal = (f'Could not reach Google Drive ({reason}). Check the connection and '
                       'try again.')
        raise WorkspaceError(refusal.replace(token, '[token]')) from None

    @staticmethod
    def _explain(failure: urllib.error.HTTPError) -> str:
        """What an HTTP error from Drive means and what to do about it."""
        try:
            detail = json.loads(failure.read().decode('utf-8', 'replace'))['error']['message']
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            detail = failure.reason
        finally:
            failure.close()
        detail = ' '.join(str(detail or '').split())[:300].rstrip('.')
        if failure.code == 401:
            return f'Google did not accept the gcloud sign-in. Run `{_SIGN_IN}` and try again.'
        if failure.code == 403 and 'scope' in detail.lower():
            return ('The gcloud sign-in does not include Google Drive. '
                    f'Run `{_SIGN_IN}` and try again.')
        if failure.code == 404:
            return ('Google could not find the Doc. It may have been deleted, or the signed-in '
                    'account cannot open it. Run google unlink for the artifact, then push to '
                    'make a new Doc.')
        if failure.code == 403:
            return (f'Google Drive refused the request (HTTP 403: {detail}). Check that the '
                    f'signed-in account may edit the Doc, or run `{_SIGN_IN}`.')
        return f'Google Drive answered HTTP {failure.code} ({detail}). Try again shortly.'
