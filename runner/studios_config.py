"""The studios config: the one file of the values every *-studio on this computer shares.

What a caller needs to know
---------------------------
    found, problem = studios_config.read()       # ({}, None) when there is no file
    studios_config.update({'share': 'asked'})     # when the person saves a shared value

- The file is `~/.config/studios-config.json`, or the one `STUDIOS_CONFIG` names, which is
  how tests keep away from a real one. Training Studio, Blog Studio and Presentation Studio
  read the same file, in this shape, where every key is optional:

      {"schema": 1, "team": {"repository", "branch"}, "person": {"name"},
       "assistant": {"agent", "model", "effort"},
       "brand": {"repository", "release", "brand", "variant"}, "output", "share"}

  It is the only place these values are kept: no studio keeps a copy of its own. A studio
  ignores the keys it does not use and those it does not know. `null` is the same as
  leaving a key out.
- `read` never refuses, and reads the file afresh each time. A file that cannot be read, is
  not JSON, is not an object or is of another schema is read as empty, with a sentence that
  says so for the page to show. What each value means to Training Studio, and whether it
  can be used, is `settings`' and `setup`'s to say.
- `update` changes only the members it is given, by editing them in the file's own text, so
  every other key keeps its bytes, its order and its layout, and a key it does not know is
  never removed. A value that is the same already is not written, and nothing changed is no
  write at all. The file is written whole or not at all, keeps its permissions, and a link
  to it is written through. It refuses a repository address that carries a password or a
  token, a value that is not plain, and a file it could not read, which it leaves as it is.
- Writers take turns: `update` holds an exclusive lock on the file beside it, its name with
  `.lock` added, which every studio takes the same way, from reading the file to replacing
  it. It waits a few seconds for another writer, then refuses. `guard`, when given, is
  called with what the file holds while the lock is held, and refuses by raising: that is
  how a form opened before another studio changed a value is kept from writing over it.
- Nothing secret belongs in the file: tokens and sign-ins stay with gcloud, gh and git.
- Only the runner uses this file. The helper's own commands never read it.
"""
from __future__ import annotations

import fcntl
import json
import os
import secrets
import time
from contextlib import contextmanager
from json import decoder
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
import hub
from workspace import WorkspaceError

SCHEMA = 1
PATH = Path.home() / '.config' / 'studios-config.json'
GROUPS = ('team', 'person', 'assistant', 'brand')   # keys whose value is an object
WORDS = ('output', 'share')                         # keys whose value is a word
SECRET = ('That address carries a password or token. Give the address without it; git '
          'signs in with your own credentials.')
SPACE = decoder.WHITESPACE
DECODE = json.JSONDecoder()
WAIT = 10.0     # seconds a write waits for another studio's to finish


def path() -> Path:
    """Where the file is: the one STUDIOS_CONFIG names, else in ~/.config."""
    named = os.environ.get('STUDIOS_CONFIG')
    if named:
        return Path(named).expanduser()
    return Path.home() / '.config' / 'studios-config.json'


def shown(where: Path) -> str:
    """A path as a person would write it: from ~ when it is in their home folder."""
    try:
        return '~/' + Path(where).relative_to(Path.home()).as_posix()
    except ValueError:
        return str(where)


USING = (', so Training Studio uses its built-in defaults for the values every studio '
         'shares, and saves none of them, until it can be read.')
REFUSED = (', so no value every studio shares can be saved until it can, and the file was '
           'left as it is.')


def _unreadable(where: Path, why: str) -> str:
    return f'{shown(where)} could not be read ({why}){USING}'


def _parsed(where: Path, text: str) -> tuple[dict, str | None]:
    try:
        found = json.loads(text)
    except ValueError:
        return {}, _unreadable(where, 'it is not valid JSON')
    if not isinstance(found, dict):
        return {}, _unreadable(where, 'it does not hold a JSON object')
    schema = found.get('schema', SCHEMA)
    if type(schema) is not int or schema != SCHEMA:
        return {}, _unreadable(where, 'it is written for a newer version of the studios')
    return found, None


def _text(where: Path) -> tuple[str | None, str | None]:
    """The file's text, or None when there is none; and why it could not be read."""
    try:
        return where.read_text(encoding='utf-8'), None
    except FileNotFoundError:
        return None, None
    except UnicodeDecodeError:
        return None, _unreadable(where, 'it is not text in UTF-8')
    except OSError as failure:
        return None, _unreadable(where, str(failure.strerror or 'it cannot be opened').lower())


def read() -> tuple[dict, str | None]:
    """What the file holds, and a sentence when it could not be used. No file is ({}, None);
    a file that cannot be used is ({}, the sentence)."""
    where = path()
    text, problem = _text(where)
    if text is None:
        return {}, problem
    return _parsed(where, text)


# --- writing -----------------------------------------------------------------------------

def _plain(value) -> bool:
    return value is None or isinstance(value, (str, bool, int, float))


def _check(changes) -> None:
    """Refuse what is not for this file: a value that is not plain, or a secret."""
    if not isinstance(changes, dict) or 'schema' in changes:
        raise WorkspaceError('Give the shared values as the studios config names them.')
    for key, value in changes.items():
        whole = isinstance(value, dict) and all(
            isinstance(name, str) and _plain(inner) for name, inner in value.items())
        if not isinstance(key, str) or (key in GROUPS and not whole) or (
                key in WORDS and not (value is None or isinstance(value, str))) or (
                not whole and not _plain(value)):
            raise WorkspaceError(f'"{key}" cannot be written to the studios config as it is.')
    for group in ('team', 'brand'):
        address = (changes.get(group) or {}).get('repository')
        if isinstance(address, str) and hub.ADDRESS_WITH_SECRET.match(address.strip()):
            raise WorkspaceError(SECRET)


def _object(text: str, at: int) -> tuple[list, int]:
    """The members of the object whose brace is at `at`, each as (key, key_at, colon,
    value_at, value_end), and where its closing brace is. The text is known to be JSON."""
    members = []
    at = SPACE.match(text, at + 1).end()
    while text[at] != '}':
        key_at = at
        key, key_end = decoder.scanstring(text, at + 1)
        value_at = SPACE.match(text, SPACE.match(text, key_end).end() + 1).end()
        _, value_end = DECODE.raw_decode(text, value_at)
        members.append((key, key_at, text[key_end:value_at], value_at, value_end))
        at = SPACE.match(text, value_end).end()
        if text[at] == ',':
            at = SPACE.match(text, at + 1).end()
    return members, at


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _same(one, other) -> bool:
    return type(one) is type(other) and one == other


def _edits(text: str, at: int, changes: dict, current: dict) -> list:
    """What to change in the object at `at` so that it holds `changes`: (start, end, text)
    each, touching nothing else. A key given twice is changed where JSON reads it, last."""
    members, close = _object(text, at)
    last = {member[0]: member for member in members}
    edits, added = [], []
    for key, value in changes.items():
        if key not in last:
            added.append((key, value))
            continue
        _, _, _, value_at, value_end = last[key]
        held = current.get(key)
        if isinstance(value, dict) and isinstance(held, dict):
            edits.extend(_edits(text, value_at, value, held))
        elif not _same(held, value):
            edits.append((value_at, value_end, _dump(value)))
    if added:
        if members:
            _, key_at, colon, _, value_end = members[-1]
            before = text[:key_at]
            space = text[len(before.rstrip(' \t\r\n')):key_at]
            # Beside a lone member written against its brace, a comma takes a space.
            space = space or (' ' if len(members) == 1 else '')
            edits.append((value_end, value_end, ''.join(
                f',{space}{_dump(key)}{colon}{_dump(value)}' for key, value in added)))
        else:
            edits.append((close, close, ', '.join(
                f'{_dump(key)}: {_dump(value)}' for key, value in added)))
    return edits


def writable() -> None:
    """Refuse, with a sentence, while the file cannot be read: nothing may be written then."""
    problem = read()[1]
    if problem:
        raise WorkspaceError(problem.removesuffix(USING) + REFUSED)




def lock_path() -> Path:
    """The file every studio locks while it writes the studios config: beside it."""
    where = path()
    return where.with_name(where.name + '.lock')


@contextmanager
def _locked():
    """Hold the lock every studio takes to write the file, or refuse once it stays taken.
    The lock goes with the process, so one that ends never leaves it held."""
    where = lock_path()
    try:
        where.parent.mkdir(parents=True, exist_ok=True)
        handle = os.open(where, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    except OSError as failure:
        raise WorkspaceError(f'{shown(path())} could not be written '
                             f'({str(failure.strerror or failure).lower()}), so it was left '
                             'as it is.')
    try:
        deadline = time.monotonic() + WAIT
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise WorkspaceError(f'Another studio is changing {shown(path())}, so '
                                         'nothing was saved. Try again in a moment.')
                time.sleep(0.05)
        yield
    finally:
        os.close(handle)


def update(changes: dict, guard=None) -> dict:
    """Write these values into the file, merged with what it holds, and return what it then
    holds. `changes` is shaped as the file is: {"share": ..., "team": {"branch": ...}}.
    `guard`, when given, is called with what the file holds before anything is written, and
    refuses by raising."""
    _check(changes)
    with _locked():
        return _update(changes, guard)


def _update(changes: dict, guard) -> dict:
    where = path()
    target = where.resolve() if where.is_symlink() else where
    text, problem = _text(target)
    found = {}
    if text is not None:
        found, problem = _parsed(where, text)
    if problem:
        raise WorkspaceError(problem.removesuffix(USING) + REFUSED)
    if guard is not None:
        guard(found)
    if text is None:
        written = json.dumps({'schema': SCHEMA, **changes}, indent=2, ensure_ascii=False) + '\n'
    else:
        start = SPACE.match(text, 0).end()
        wanted = changes if 'schema' in found else {'schema': SCHEMA, **changes}
        written = text
        for begin, end, put in sorted(_edits(text, start, wanted, found), reverse=True):
            written = written[:begin] + put + written[end:]
        if written == text:
            return found
    mode = target.stat().st_mode & 0o7777 if text is not None else None
    pending = target.with_name(f'.{target.name}.pending-{secrets.token_hex(4)}')
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        pending.write_text(written, encoding='utf-8')
        if mode is not None:
            os.chmod(pending, mode)
        os.replace(pending, target)
    except OSError as failure:
        raise WorkspaceError(f'{shown(where)} could not be written '
                             f'({str(failure.strerror or failure).lower()}), so it was left '
                             'as it is.')
    finally:
        pending.unlink(missing_ok=True)
    return json.loads(written)
