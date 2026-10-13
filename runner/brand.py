"""A brand skill on this computer, called from Python.

What a caller needs to know
---------------------------
    brand = Brand()                           # finds a brand skill, or refuses
    brand.name                                # what the skill calls itself
    brand.brands()                            # [{'brand', 'name', 'variants': [str]}]
    made = brand.export(folder, brand_id, variant, delivery='reading')
    brand.check(contract)                     # refuses when the brand changed underneath
    brand.icons(words, limit=5)               # [{'id', 'name', ...}] from its icon library
    report = brand.audit(deck, brand_id, variant)
    brand.ready()                             # what the skill's own readiness check says

- A brand skill is a skill whose companion command lists its brands, exports a slides
  contract, searches its icons and audits a deck. Nothing here names a particular brand:
  the skill is found by looking in the usual install locations for a companion command
  that answers. BRAND_SKILL_RUNTIME names one outright; `found()` lists every one that
  was found, for the set-up screen.
- `export` writes into a new folder and returns {'contract', 'design', 'voice'}: the paths
  of brand-contract.json and of the two guides the skill writes beside it, the second of
  which holds how the organisation and its products are named. `delivery` is 'reading' or
  'live'.
- `audit` returns {'status', 'blockers': [...], 'warnings': [{'code', 'slide', 'says'}]}.
  A warning is not a refusal; the caller shows it.
- When the skill says no, Refused is raised: a WorkspaceError that carries its lines.
- No call here uses the network. Nothing a brand skill prints is ever run.
- `Brand(run=...)` replaces how the command is run; `stand_in()` gives a Brand backed by
  StandIn, with one made-up brand, a contract the slides stand-in accepts, a few icons and
  an audit, and needs neither Node nor an installed skill.
"""
from __future__ import annotations

from workspace import WorkspaceError

VARIABLE = 'BRAND_SKILL_RUNTIME'


class Refused(WorkspaceError):
    """The brand skill said no. `problems` holds the lines it gave."""

    def __init__(self, problems: list[str]):
        super().__init__('The brand skill refused: ' + ' '.join(problems))
        self.problems = problems


def found() -> list[dict]:
    raise NotImplementedError


class Brand:
    def __init__(self, runtime=None, run=None):
        raise NotImplementedError


class StandIn:
    def __init__(self):
        raise NotImplementedError


def stand_in() -> Brand:
    raise NotImplementedError
