"""Documents a person supplies for a training's research.

What a caller needs to know
---------------------------
    documents.TYPES                   # the endings ever taken, lower case, with the dot
    documents.LIMITS                  # {'bytes': the largest one document, 'files': how many}
    documents.accepts()               # the endings this computer can read now
    entry = documents.add(root, name, data)    # keep one document, given as bytes
    documents.remove(root, name)
    documents.listed(root)            # every entry, in the order they were added
    plan, offered = documents.sources(root)

- A document is kept under `sources/supplied/` in the training's folder, which the workspace
  never shares: the file as it was sent and, beside it, its text. The list of what was added
  is kept there too, in `index.json`. Nothing is written anywhere else.
- An entry is {'name', 'bytes', 'readable', 'problem', 'id', 'title', 'file', 'original',
  'sha256'}. `id` is a slug of the name, unique among the training's documents. `file` is the
  text's path from the training's folder and `original` the sent file's. `problem` is a
  sentence for a person when `readable` is false, else None.
- Text, Markdown, HTML and Word (.docx) are always read. A PDF is read with `pdftotext`
  when this computer has it, as fetched PDFs are; `accepts()` leaves `.pdf` out otherwise.
- `add` refuses with WorkspaceError and a sentence: a type that is not taken, a document
  over the limit, more documents than the limit, a name that is not a plain file name, and
  a name that was already added. A document whose text cannot be read is not refused: it is
  kept as not readable, with why, and is not a source.
- `sources(root)` gives the readable documents twice: as the research plan's `sources`, in
  the shape harness-research takes, and as what `worker_tools.prepare(sources=...)` is
  given, each with `supplied` set to its ID in the plan.
- Nothing here uses the network or starts an agent.

A document is never trusted. Its name is only ever a label: files are kept under its ID.
Its title is its name, not anything it says about itself. A Word file is a zip, so only its
document XML is unpacked, up to a limit, and that XML may declare no entities. Nothing a
document says is followed: no link, no include and no instruction.
"""
from __future__ import annotations

import hashlib
import io
import re
import shutil
import threading
import unicodedata
import zipfile
import zlib
from pathlib import Path
from xml.parsers import expat

import runner  # noqa: F401  puts the core on the import path
import home
import workspace
from workspace import WorkspaceError

from runner import worker_tools

TYPES = ('.txt', '.md', '.html', '.htm', '.docx', '.pdf')
LIMITS = {'bytes': 8_000_000, 'files': 40}
FOLDER = 'sources/supplied'

SCHEMA = 1
INDEX = f'{FOLDER}/index.json'
NAME = 120                  # characters in a document's name
UNPACKED = 40_000_000       # bytes of a Word file's XML that are unpacked
TEXT = 8_000_000            # characters of text kept from one document
IDENT = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
SEPARATORS = '/\\:'
# Characters that change the order a name is shown in, so it reads as another name.
REORDERING = '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069'
KINDS = {'.txt': 'text (.txt)', '.md': 'Markdown (.md)', '.html': 'web pages (.html)',
         '.docx': 'Word (.docx)', '.pdf': 'PDF (.pdf)'}
WORD_PART = re.compile(r'word/document\d*\.xml')
WORD = ('http://schemas.openxmlformats.org/wordprocessingml/2006/main',
        'http://purl.oclc.org/ooxml/wordprocessingml/main')
REPEATED = ('http://schemas.openxmlformats.org/markup-compatibility/2006', 'Fallback')
# What harness-research takes a snapshot that starts this way for: a file that is not text.
NOT_SNAPSHOTS = ('%PDF-', 'PK\x03\x04')

INSTEAD = 'Save it as text or as a Word document (.docx) and add that.'
NOT_TEXT = ('It does not hold text that can be read: it looks like another kind of file '
            f'with this ending. {INSTEAD}')
EMPTY = 'No text was found in it. Add a version that holds its words as text.'
EMPTY_PDF = ('No text was found in it. It may be a scan, which holds pictures of its pages '
             f'and not their words. {INSTEAD}')
NOT_WORD = ('It could not be opened as a Word document. If it has a password, take that off. '
            'Then save it again as .docx, or as text, and add that.')
TOO_BIG = ('It holds more than this computer will unpack from one Word document. Save it in '
           'smaller parts, or as text, and add those.')
TOO_LONG = (f'It holds more than {TEXT:,} characters of text, which is the most one '
            'document can. Add it in smaller parts.')
NOT_PDF = f'This PDF could not be read. It may be damaged or protected. {INSTEAD}'
NO_READER = f'This computer cannot read PDFs. {INSTEAD}'
UNREADABLE = f'It could not be read. {INSTEAD}'
GONE = ('It is no longer in this training\'s folder on this computer. Remove it here, then '
        'add it again.')

_CHANGING = threading.RLock()   # one change to the list at a time


class _Unreadable(Exception):
    """A document with no text that could be read. It says why, in a sentence."""


# --- what is taken -------------------------------------------------------------------------

def pdf_reader() -> bool:
    """True when this computer can read a PDF: pdftotext is installed."""
    return shutil.which('pdftotext') is not None


def accepts() -> tuple[str, ...]:
    """The endings this computer can read now."""
    return tuple(ending for ending in TYPES if ending != '.pdf' or pdf_reader())


def _shown(name) -> str:
    """A name that was sent, safe to say back: short, and with nothing that cannot be
    printed."""
    return worker_tools.clip(''.join(character if character.isprintable() else '?'
                                     for character in str(name)), 80)


def _plain(name) -> str | None:
    """A name as it is kept, or None when it is not a plain file name: it has a folder in
    it, starts with a dot, or holds characters a file name should not."""
    if not isinstance(name, str):
        return None
    plain = unicodedata.normalize('NFC', name)
    hostile = (not plain or plain != plain.strip() or plain.startswith('.')
               or any(character in SEPARATORS + REORDERING
                      or unicodedata.category(character) in ('Cc', 'Cs', 'Zl', 'Zp')
                      for character in plain))
    return None if hostile else plain


def _ending(plain: str) -> str:
    return '.' + plain.rpartition('.')[2].lower() if '.' in plain else ''


def _same(one: str, other: str) -> bool:
    """True for two names a computer may take for the same file."""
    return one.casefold() == other.casefold()


def _checked(name, data) -> tuple[str, str, bytes]:
    """A sent document's name, ending and bytes, once each may be taken."""
    plain = _plain(name)
    if plain is None:
        raise WorkspaceError(f'"{_shown(name)}" is not a plain file name. Give the document '
                             'a name with no folder in it, such as notes.docx, and add it '
                             'again.')
    if len(plain) > NAME:
        raise WorkspaceError(f'"{_shown(plain)}" is a name of more than {NAME} characters. '
                             'Give the document a shorter name and add it again.')
    ending, taken = _ending(plain), accepts()
    if ending == '.pdf' and ending not in taken:
        raise WorkspaceError(f'"{plain}" is a PDF, and this computer cannot read PDFs. '
                             f'{INSTEAD}')
    if ending not in taken:
        kinds = [KINDS[kind] for kind in taken if kind in KINDS]
        raise WorkspaceError(f'"{plain}" is not a kind of document that can be read here. '
                             f"These are: {', '.join(kinds[:-1])} and {kinds[-1]}. Save it "
                             'as one of those and add it again.')
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise WorkspaceError(f'"{plain}" arrived as something other than a file, so it was '
                             'not kept.')
    data = bytes(data)
    if len(data) > LIMITS['bytes']:
        raise WorkspaceError(f'"{plain}" is {len(data) / 1_000_000:.1f} MB. The most one '
                             f"document can be is {LIMITS['bytes'] // 1_000_000} MB. Add a "
                             'smaller part of it, or save it as text and add that.')
    return plain, ending, data


# --- where they are kept -------------------------------------------------------------------

def _folder(root: Path) -> Path:
    """Where the documents are kept. Refused unless it is, or can be, a real folder inside
    the training's own, so nothing is ever read or written anywhere else."""
    if not workspace.session_path(root).is_file():
        raise WorkspaceError('There is no training in that folder, so it has no documents.')
    folder = root / FOLDER
    real = all(not part.is_symlink() and (part.is_dir() or not part.exists())
               for part in (folder.parent, folder))
    if not real or root.resolve() not in folder.resolve().parents:
        raise WorkspaceError(f'{FOLDER} in this training is not a real folder of its own, so '
                             'no document was read or kept. Move what is there out of the '
                             'way, then try again.')
    return folder


def _files(ident: str, ending: str) -> tuple[str, str]:
    """Where a document's text and the file as it was sent are kept, from the training's
    folder. Both come from its ID, never from the name it was sent with."""
    return f'{FOLDER}/{ident}.txt', f'{FOLDER}/{ident}.original{ending}'


def _kept(root: Path) -> list[dict]:
    """What the list says was added. Anything in it that this module would not have written
    is passed over, and where each file is kept is worked out again, not read from it."""
    _folder(root)
    found = home.read_json(workspace.managed(root, INDEX), None)
    entries = found.get('documents') if isinstance(found, dict) else None
    if not isinstance(entries, list) or found.get('schema') != SCHEMA:
        return []
    kept, seen = [], set()
    for entry in entries:
        usable = (isinstance(entry, dict) and isinstance(entry.get('id'), str)
                  and IDENT.match(entry['id']) and entry['id'] not in seen
                  and isinstance(entry.get('name'), str)
                  and _plain(entry['name']) == entry['name']
                  and _ending(entry['name']) in TYPES)
        if usable:
            seen.add(entry['id'])
            kept.append(entry)
    return kept


def _entry(root: Path, kept: dict) -> dict:
    """One document as a caller is told about it, checked against what is on disk now."""
    file, original = _files(kept['id'], _ending(kept['name']))
    problem = kept.get('problem') if isinstance(kept.get('problem'), str) else None
    readable = kept.get('readable') is True and problem is None
    here = [(root / path).is_file() and not (root / path).is_symlink()
            for path in ((file, original) if readable else (original,))]
    if not all(here):
        readable, problem = False, GONE
    name = kept['name']
    return {'name': name, 'bytes': kept.get('bytes') if type(kept.get('bytes')) is int else 0,
            'readable': readable, 'problem': None if readable else problem or UNREADABLE,
            'id': kept['id'], 'title': _title(name), 'file': file if readable else None,
            'original': original,
            'sha256': kept.get('sha256') if isinstance(kept.get('sha256'), str) else None}


def _title(name: str) -> str:
    """What a document is called: its name without the ending. Never what it says it is
    called, which a worker would then be told as if a person had said it."""
    stem = ' '.join(name[:len(name) - len(_ending(name))].split())
    return stem if any(character.isalnum() for character in stem) else name


def _ident(plain: str, ending: str, taken: set[str]) -> str:
    """A slug of the name that no other document of the training has."""
    base = f'{worker_tools.slug(plain[:len(plain) - len(ending)])}-{ending[1:]}'
    ident, number = base, 1
    while ident in taken:
        number += 1
        ident = f'{base}-{number}'
    return ident


def _store(root: Path, kept: list[dict]) -> None:
    home.write_json(workspace.managed(root, INDEX), {'schema': SCHEMA, 'documents': kept})


# --- reading -------------------------------------------------------------------------------

def _decoded(data: bytes) -> str:
    """A text file's bytes as text: UTF-8, UTF-16 when it is marked so, else the encoding
    older Windows programs write."""
    if data[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return data.decode('utf-16', 'replace')
    if b'\x00' in data:
        raise _Unreadable(NOT_TEXT)
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        return data.decode('cp1252', 'replace')


def _page(data: bytes) -> str:
    """The readable text of an HTML file, in the encoding it declares."""
    if data[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return worker_tools.page_text(_decoded(data).encode('utf-8'),
                                      'text/html; charset=utf-8')[0]
    if b'\x00' in data:
        raise _Unreadable(NOT_TEXT)
    return worker_tools.page_text(data, 'text/html')[0]


class _Body:
    """The plain text of a Word document's XML, in the order it is written: a paragraph or
    a heading is a line, a list item a line that starts with a dash, and a table row a line
    with its cells set apart."""

    def __init__(self):
        self.lines: list[str] = []
        self.open: list[list] = []          # paragraphs not yet ended: [its text, a list item]
        self.cells: list[list[str]] = []    # table cells not yet ended, innermost last
        self.rows: list[list[str]] = []     # table rows not yet ended, innermost last
        self.in_text, self.skipping, self.chars = False, 0, 0

    def read(self, xml: bytes) -> str:
        parser = expat.ParserCreate(namespace_separator=' ')
        parser.buffer_text = True
        parser.StartElementHandler = self._start
        parser.EndElementHandler = self._end
        parser.CharacterDataHandler = self._data
        # A Word document declares nothing. One that does is refused before anything it
        # declares is read, so no entity is ever expanded or fetched.
        parser.StartDoctypeDeclHandler = self._declared
        parser.EntityDeclHandler = self._declared
        parser.ExternalEntityRefHandler = self._declared
        try:
            parser.Parse(xml, True)
        except expat.ExpatError:
            raise _Unreadable(NOT_WORD) from None
        return '\n'.join(self.lines)

    def _declared(self, *args) -> None:
        raise _Unreadable(NOT_WORD)

    def _start(self, name: str, attributes: dict) -> None:
        space, _, tag = name.rpartition(' ')
        # A text box is written twice, once for older programs, and a moved passage is
        # still written where it was moved from. Each is read once, where it is shown.
        if self.skipping or (space, tag) == REPEATED or (space in WORD and tag == 'moveFrom'):
            self.skipping += 1
        elif space not in WORD:
            return
        elif tag == 'p':
            self.open.append([[], False])
        elif tag == 't':
            self.in_text = True
        elif tag in ('tab', 'ptab'):
            self._add('\t')
        elif tag in ('br', 'cr'):
            self._add('\n')
        elif tag == 'noBreakHyphen':
            self._add('-')
        elif tag in ('numPr', 'numId') and self.open:
            # Numbering 0 is how a paragraph says it is not in the list its style puts it in.
            self.open[-1][1] = tag == 'numPr' or attributes.get(f'{space} val') != '0'
        elif tag == 'tc':
            self.cells.append([])
        elif tag == 'tr':
            self.rows.append([])
        elif tag == 'tbl' and not self.cells:
            self.lines.append('')

    def _end(self, name: str) -> None:
        if self.skipping:
            self.skipping -= 1
            return
        space, _, tag = name.rpartition(' ')
        if space not in WORD:
            return
        if tag == 't':
            self.in_text = False
        elif tag == 'p':
            self._paragraph()
        elif tag == 'tc':
            cell = ' '.join(part for part in self.cells.pop() if part)
            (self.rows[-1] if self.rows else self.lines).append(cell)
        elif tag == 'tr':
            cells = self.rows.pop()
            row = ' | '.join(cells) if any(cells) else ''
            (self.cells[-1] if self.cells else self.lines).append(row)
        elif tag == 'tbl' and not self.cells:
            self.lines.append('')

    def _data(self, text: str) -> None:
        if self.in_text and not self.skipping:
            self._add(text)

    def _add(self, text: str) -> None:
        if not self.open:
            return
        self.chars += len(text)
        if self.chars > TEXT:
            raise _Unreadable(TOO_LONG)
        self.open[-1][0].append(text)

    def _paragraph(self) -> None:
        parts, item = self.open.pop()
        text, self.in_text = ''.join(parts), False
        if self.cells:
            self.cells[-1].append(' '.join(text.split()))
        elif item and text.strip():
            self.lines.append('- ' + ' '.join(text.split()))
        else:
            self.lines += ['', *text.split('\n'), '']


def _word(data: bytes) -> str:
    """The text of a Word file. It is a zip: one part of it is unpacked, the document
    itself, and no more of that than UNPACKED bytes, whatever size it says it is."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            parts = [part for part in archive.infolist()
                     if WORD_PART.fullmatch(part.filename)]
            parts = [part for part in parts if part.filename == 'word/document.xml'] or parts
            # Named twice, a reader cannot know which one Word would show.
            if len(parts) != 1 or parts[0].compress_type not in (zipfile.ZIP_STORED,
                                                                 zipfile.ZIP_DEFLATED):
                raise _Unreadable(NOT_WORD)
            if parts[0].file_size > UNPACKED:
                raise _Unreadable(TOO_BIG)
            with archive.open(parts[0]) as stream:
                xml = stream.read(UNPACKED + 1)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, zlib.error, EOFError, OSError,
            RuntimeError, NotImplementedError, ValueError, KeyError):
        raise _Unreadable(NOT_WORD) from None
    if len(xml) > UNPACKED:
        raise _Unreadable(TOO_BIG)
    return _Body().read(xml)


def _pdf(path: Path) -> str:
    """The text of a kept PDF, read as fetched PDFs are."""
    try:
        text = worker_tools.pdf_text(path)
    except WorkspaceError:
        raise _Unreadable(NOT_PDF) from None
    if text is None:
        raise _Unreadable(NO_READER)
    return text


def _text(ending: str, data: bytes, original: Path) -> str:
    """A document's text as it is kept and quoted from. Raises _Unreadable with why when
    there is none to keep."""
    if not data:
        raise _Unreadable('It is empty.')
    if ending in ('.txt', '.md', '.html', '.htm') and data.startswith((b'%PDF-', b'PK\x03\x04')):
        raise _Unreadable(NOT_TEXT)
    if ending == '.docx':
        text = _word(data)
    elif ending == '.pdf':
        text = _pdf(original)
    elif ending in ('.html', '.htm'):
        text = _page(data)
    else:
        text = _decoded(data)
    # Kept exactly as a worker is given it, so the place of a quote is the same in both.
    text = worker_tools.tidy(text.encode('utf-8', 'replace').decode('utf-8'))
    if not text.strip():
        raise _Unreadable(EMPTY_PDF if ending == '.pdf' else EMPTY)
    if len(text) > TEXT:
        raise _Unreadable(TOO_LONG)
    if text.startswith(NOT_SNAPSHOTS):
        raise _Unreadable(NOT_TEXT)
    return text


# --- what a caller does --------------------------------------------------------------------

def add(root: Path, name: str, data: bytes) -> dict:
    """Keep one document and read its text. Returns its entry."""
    root = Path(root)
    plain, ending, data = _checked(name, data)
    with _CHANGING:
        kept = _kept(root)
        if any(_same(entry['name'], plain) for entry in kept):
            raise WorkspaceError(f'"{plain}" was already added. Remove it first if this is '
                                 'a newer version of it.')
        if len(kept) >= LIMITS['files']:
            raise WorkspaceError(f"This training already has {LIMITS['files']} documents, "
                                 'which is the most it can take. Remove one before adding '
                                 'another.')
        ident = _ident(plain, ending, {entry['id'] for entry in kept})
        file, original = (workspace.managed(root, path) for path in _files(ident, ending))
        try:
            workspace.write_atomic(original, data)
            try:
                text, problem = _text(ending, data, original), None
            except _Unreadable as unreadable:
                text, problem = None, str(unreadable)
            except Exception:  # whatever a document does to a reader, it is only not readable
                text, problem = None, UNREADABLE
            if text is None:
                file.unlink(missing_ok=True)
            else:
                workspace.write_atomic(file, text.encode('utf-8'))
            kept.append({'name': plain, 'bytes': len(data), 'readable': text is not None,
                         'problem': problem, 'id': ident,
                         'sha256': hashlib.sha256(data).hexdigest()})
            _store(root, kept)
        except BaseException:   # kept whole and listed, or not kept at all
            for path in (file, original):
                path.unlink(missing_ok=True)
            raise
        return _entry(root, kept[-1])


def remove(root: Path, name: str) -> None:
    """Take one document out of the training: the file that was sent, and its text."""
    root = Path(root)
    with _CHANGING:
        kept = _kept(root)
        wanted = unicodedata.normalize('NFC', name) if isinstance(name, str) else ''
        found = next((entry for entry in kept if entry['name'] == wanted), None) or next(
            (entry for entry in kept if _same(entry['name'], wanted)), None)
        if found is None:
            raise WorkspaceError(f'"{_shown(name)}" is not one of this training\'s '
                                 'documents.')
        # The files go first: a document a person removed must not stay on disk unlisted.
        try:
            for path in _files(found['id'], _ending(found['name'])):
                (root / path).unlink(missing_ok=True)
        except OSError as failure:
            raise WorkspaceError(f'"{found["name"]}" could not be taken off this computer '
                                 f'({failure.strerror or type(failure).__name__}). It is '
                                 'still one of this training\'s documents.') from None
        _store(root, [entry for entry in kept if entry is not found])


def listed(root: Path) -> list[dict]:
    """Every document's entry, in the order they were added."""
    root = Path(root)
    return [_entry(root, kept) for kept in _kept(root)]


def sources(root: Path) -> tuple[list[dict], list[dict]]:
    """The readable documents, as the research plan's `sources` and as what a worker is
    offered before its job starts."""
    root = Path(root)
    plan, offered = [], []
    for entry in listed(root):
        if not entry['readable']:
            continue
        origin = f"supplied {entry['name']}"
        plan.append({'id': entry['id'], 'title': entry['title'], 'origin': origin,
                     'original_file': entry['original'], 'file': entry['file'],
                     'limits': 'none'})
        offered.append({'title': entry['title'], 'origin': origin,
                        'text': (root / entry['file']).read_bytes().decode('utf-8'),
                        'file': entry['file'], 'supplied': entry['id']})
    return plan, offered
