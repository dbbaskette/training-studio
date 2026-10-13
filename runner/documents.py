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
  never shares: the file as it was sent and, beside it, its text. Nothing else is written.
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
"""
from __future__ import annotations

from pathlib import Path

TYPES = ('.txt', '.md', '.html', '.htm', '.docx', '.pdf')
LIMITS = {'bytes': 8_000_000, 'files': 40}
FOLDER = 'sources/supplied'


def accepts() -> tuple[str, ...]:
    raise NotImplementedError


def add(root: Path, name: str, data: bytes) -> dict:
    raise NotImplementedError


def remove(root: Path, name: str) -> None:
    raise NotImplementedError


def listed(root: Path) -> list[dict]:
    raise NotImplementedError


def sources(root: Path) -> tuple[list[dict], list[dict]]:
    raise NotImplementedError
