"""The copies a training asked for: a Google Doc or a Word file of a guide, a brief or a
Yoodli scenario.

What a caller needs to know
---------------------------
    copies.wanted(root, problems=None)       # every copy the training asks for, as shown
    made, problems = copies.make(root, google=None, word=None)

- An entry is {'artifact', 'label', 'kind', 'state', 'link', 'problem'}. `kind` is 'google'
  or 'word'. `state` is 'made', 'out-of-date' or 'not-made'. `link` is the Doc's address,
  or the Word file's path from the training's folder, once there is one. `label` is the
  artifact's name as a person reads it.
- What is wanted is what the core says: `gdocs.copy_states` for Google Docs and
  `workspace.export_states` for Word. This module adds no rule of its own about which
  artifacts get a copy.
- `make` makes every wanted copy of an approved artifact that is not current, and leaves
  the rest alone. It never raises for a copy that cannot be made. A Word copy that cannot
  be made is recorded through the core as unavailable, with the reason. A Google Doc that
  cannot be made has nowhere in the core to say why, so `make` returns `problems`:
  {artifact: sentence}. The caller keeps them and passes them back to `wanted`.
- `google` is a `gdocs.Transport`; left out, it is `gdocs.GcloudTransport()`, which uses
  the Google access this computer already has. No credential is asked for, stored or
  printed here. `word` is a callable (source: Path, target: Path) -> None; left out, it
  runs `pandoc`, and a computer without it gets a sentence saying so.
- Nothing is approved, skipped or decided here.
"""
from __future__ import annotations

from pathlib import Path


def wanted(root: Path, problems: dict | None = None) -> list[dict]:
    raise NotImplementedError


def make(root: Path, google=None, word=None) -> tuple[list[dict], dict]:
    raise NotImplementedError
