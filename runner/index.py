"""The index: README.md at the top of a training, written from its record.

What a caller needs to know
---------------------------
    report = index.readiness(root, copies=None)     # nothing is written
    report = index.write(root, copies=None)         # writes README.md, then the same report

- `report` is {'ready', 'blocking', 'limitations', 'file'}. `ready`, `blocking` and
  `limitations` are what `training.py check --complete --all` computes, in sentences for a
  person. `file` is 'README.md'.
- `copies` is what `copies.wanted` returned. A copy that was not made is a limitation, and
  only a copy that is made is listed in the index.
- The index has the eight sections the skill's package reference lists, in that order. All
  of it is derived from the training's files and record: intake, the blueprints, the
  checks, the research record and the copies. No model writes any of it.
- README.md is derived. It is written straight to the training's folder and never saved
  through the core.
"""
from __future__ import annotations

from pathlib import Path

FILE = 'README.md'


def readiness(root: Path, copies: list[dict] | None = None) -> dict:
    raise NotImplementedError


def write(root: Path, copies: list[dict] | None = None) -> dict:
    raise NotImplementedError
