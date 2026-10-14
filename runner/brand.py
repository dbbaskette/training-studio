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
- `Brand(run=...)` replaces how the command is run. The tests' stand-in, in
  tests/stand_ins/brand.py, has one made-up brand and needs neither Node nor an installed
  skill.

Added to the above
------------------
- `found()` returns [{'name', 'version', 'runtime', 'brands'}], `runtime` being the skill's
  folder as text, with links followed. Give one to `Brand(runtime=...)` to use that skill.
  `version` is the number its version line ends with, or None. `brand.version` is the same
  for a Brand.
- `found(home=...)` and `locations(home)` look in that folder in place of the person's
  home folder, which is how the installer asks about the home it installs into. The
  override, when set, is still the only place looked.
- Every brand `brands()` lists has at least one variant. `export` and `audit` take None
  for the variant all the same, and then leave the choice to the skill.
- `brand.runtime` is the folder of the skill a Brand uses. Give it to `Brand(runtime=...)`
  to use that same skill somewhere else, as the worker tools' server does.
- A skill's companion command is the script in its `scripts` folder that is named for the
  skill. It is run only when the folder holds a SKILL.md and the script mentions brands,
  and then only to ask for its brands and its version.
- `export` returns its three paths as text. A folder a failed export made is removed.
- `icons` gives each icon as {'id', 'name', 'category', 'native'}. One whose `native` is
  false is a picture, which the slides tool will not place.
- `audit` gives a blocker in the shape of a warning, and `slide` as the slide's number.
  `status` is the skill's own word: PASS, WARN or BLOCKED.
- `ready()` returns the readiness check's own JSON, whatever it found: `ok`, and its
  `checks` and `capabilities`, each with a name and how it stands.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
from workspace import WorkspaceError

from runner import companion as companions

VARIABLE = 'BRAND_SKILL_RUNTIME'
TIMEOUT = 120
DELIVERIES = ('reading', 'live')
NAMED = re.compile(r'^[\w.-]{1,80}$')
NUMBER = re.compile(r'^\d+\.\d+\.\d+$')   # a version, as a version line ends with it
NOISE = re.compile(r'^\((?:node:\d+\)|Use `node )')   # Node's own warnings, not the skill's
NOT_WHOLE = ('The brand skill answered with something other than the JSON it should. '
             'Check that it is installed whole.')
NO_NODE = ('A brand skill needs Node.js 20 or newer, which was not found on this computer. '
           'Install it, then try again.')


class Refused(WorkspaceError):
    """The brand skill said no. `problems` holds the lines it gave."""

    def __init__(self, problems: list[str]):
        super().__init__('The brand skill refused: ' + ' '.join(problems))
        self.problems = problems


def locations(home: Path | None = None) -> list[Path]:
    """Every folder that may be an installed skill. The override, when set, is the only
    place looked. `home` stands in for the person's home folder."""
    return companions.locations(VARIABLE, home=home)


def companion(folder: Path, *names: str) -> Path | None:
    """The command that comes with a skill: the script in its `scripts` folder named for
    the skill, by its package's name, its folder's or one of `names`. None when the folder
    is not a skill or the script says nothing of brands. Nothing is run."""
    try:
        if not (folder / 'SKILL.md').is_file():
            return None
        package = json.loads((folder / 'package.json').read_text(encoding='utf-8'))['name']
    except PermissionError:
        return None   # a folder this program may not look into is no skill of its own
    except (OSError, ValueError, KeyError, TypeError):
        package = None
    for name in (package, folder.name, *names):
        if not isinstance(name, str) or not NAMED.match(name):
            continue
        script = folder / 'scripts' / f'{name}.mjs'
        try:
            with open(script, encoding='utf-8', errors='replace') as stream:
                return script if 'brands' in stream.read(200_000) else None
        except OSError:
            continue
    return None


def run_command(command: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """Run the command line once: (exit code, standard output, standard error)."""
    return companions.run_command(command, cwd, TIMEOUT, 'The brand skill')


def _lines(err: str, code: int) -> list[str]:
    """What the skill said was wrong, without the usage it prints after."""
    lines = []
    for line in (line.strip() for line in err.splitlines()):
        if line.startswith('Usage:'):
            break
        if line and not NOISE.match(line):
            lines.append(line)
    return lines or [f'it ended with exit code {code}']


def _listing(listed) -> list[dict] | None:
    """A brands listing in the shape it should have, or None."""
    def text(value) -> bool:
        return isinstance(value, str) and bool(value.strip())

    if not isinstance(listed, list) or not listed or not all(
            isinstance(one, dict) and text(one.get('brand')) and text(one.get('name'))
            and isinstance(one.get('variants'), list) and one['variants']
            and all(map(text, one['variants'])) for one in listed):
        return None
    return [{'brand': one['brand'], 'name': one['name'], 'variants': list(one['variants'])}
            for one in listed]


def _asked(run, node: str, script: Path) -> list[dict] | None:
    """What a companion command lists as its brands, or None when it is not a brand
    skill's."""
    try:
        code, out, _ = run([node, str(script), 'brands', '--json'])
        return _listing(json.loads(out)) if code == 0 else None
    except (WorkspaceError, ValueError):
        return None


def _named(run, node: str, script: Path, otherwise: str) -> tuple[str, str | None]:
    """What a skill calls itself, and its version: its version line without the number,
    else its folder; and that number, else None."""
    try:
        code, out, _ = run([node, str(script), 'version'])
    except WorkspaceError:
        code, out = 1, ''
    name, _, number = (out.strip().partition('\n')[0] if code == 0 else '').rpartition(' ')
    number = number.removeprefix('v')
    return name.strip()[:80] or otherwise, number if NUMBER.match(number) else None


def _installed(run=None, home: Path | None = None):
    """Each brand skill on this computer: (its folder, its command, (its name, its version),
    its brands)."""
    node = 'node' if run else shutil.which('node')
    seen = set()
    for place in locations(home) if node else []:
        try:
            runtime = place.resolve()
        except (OSError, RuntimeError):
            continue   # a link that leads nowhere
        hints = [name for name in (place.name, place.parent.name)
                 if name != 'current'] or ['brand']
        script = None if runtime in seen else companion(runtime, *hints)
        seen.add(runtime)
        brands = _asked(run or run_command, node, script) if script else None
        if brands:
            yield runtime, script, _named(run or run_command, node, script, hints[0]), brands


def found(run=None, home: Path | None = None) -> list[dict]:
    """Every brand skill on this computer, for the set-up screen and the installer. With no
    Node there is nothing to ask, so none is found. `home` stands in for the home folder."""
    return [{'name': name, 'version': version, 'runtime': str(runtime), 'brands': brands}
            for runtime, _, (name, version), brands in _installed(run, home)]


def _variant(variant: str | None) -> list[str]:
    """How a variant is named to the skill. With none named, the skill chooses."""
    return ['--variant', variant] if variant else []


class Brand:
    """The brands, contract, icons and audit commands of one installed brand skill.
    `runtime` is the folder it is installed in, and `name` what it calls itself."""

    def __init__(self, runtime: Path | None = None, run=None):
        self.run = run or run_command
        self.node = 'node' if run else shutil.which('node')
        if self.node is None:
            raise WorkspaceError(NO_NODE)
        if runtime is None:
            self.runtime, self.script, called, _ = next(_installed(run), [None] * 4)
            self.name, self.version = called or (None, None)
            if self.runtime is None and os.environ.get(VARIABLE):
                raise WorkspaceError(f'{VARIABLE} names {os.environ[VARIABLE]}, which does '
                                     'not hold a brand skill. Point it at an installed '
                                     'one, or unset it.')
            if self.runtime is None:
                raise WorkspaceError('No brand skill was found on this computer, so a deck '
                                     'cannot be made. Install one, or name its folder in '
                                     f'{VARIABLE}, then try again.')
            return
        self.runtime = Path(runtime)
        hints = [name for name in (self.runtime.name, self.runtime.parent.name)
                 if name != 'current'] or ['brand']
        self.script = companion(self.runtime.resolve(), *hints)
        if self.script is None and not run:
            raise WorkspaceError(f'{runtime} does not hold a brand skill: a skill whose own '
                                 'command lists its brands. Name the folder of an installed '
                                 'one.')
        self.script = self.script or self.runtime / 'scripts' / f'{hints[0]}.mjs'
        self.name, self.version = _named(self.run, self.node, self.script, hints[0])

    def _answer(self, *args: str, kind=dict, report: bool = False):
        """The command's JSON. An audit or a readiness check that found something ends with
        an error code and is an answer all the same."""
        code, out, err = self.run([self.node, str(self.script), *args])
        try:
            answered = json.loads(out)
        except ValueError:
            answered = None
        if code != 0 and not (report and isinstance(answered, kind)):
            raise Refused(_lines(err, code))
        if not isinstance(answered, kind):
            raise WorkspaceError(NOT_WHOLE)
        return answered

    def brands(self) -> list[dict]:
        """The brands the skill holds, each with the variants it comes in."""
        listed = _listing(self._answer('brands', '--json', kind=list))
        if listed is None:
            raise WorkspaceError(NOT_WHOLE)
        return listed

    def export(self, folder: Path, brand_id: str, variant: str | None,
               delivery: str = 'reading') -> dict:
        """Export one brand's contract for slides into a new folder."""
        if delivery not in DELIVERIES:
            raise WorkspaceError(f'A brand is exported for {DELIVERIES[0]} or '
                                 f'{DELIVERIES[1]} delivery, not {delivery}.')
        folder = Path(folder)
        there = folder.exists()
        made = {'contract': folder / 'brand-contract.json', 'design': folder / 'DESIGN.md',
                'voice': folder / 'VOICE.md'}
        try:
            self._answer('contract', 'export', '--medium', 'slides', '--brand', brand_id,
                         *_variant(variant), '--delivery', delivery, '--output',
                         str(folder))
            if not all(path.is_file() for path in made.values()):
                raise WorkspaceError('The brand skill exported a brand without the three '
                                     'files it should write. Check that it is installed '
                                     'whole.')
        except WorkspaceError:
            if not there:
                shutil.rmtree(folder, ignore_errors=True)
            raise
        return {key: str(path) for key, path in made.items()}

    def check(self, contract: Path) -> dict:
        """Check an exported contract against the brand as it is now. A brand that changed
        since the export is refused, with a line that says what changed."""
        return self._answer('contract', 'check', '--file', str(contract))

    def icons(self, words: str, limit: int = 5) -> list[dict]:
        """Search the icon library. Every word must match, so fewer words find more."""
        answered = self._answer('icons', '--query', words, '--limit', str(limit), '--json',
                                '--no-previews')
        results = answered.get('results')
        if not isinstance(results, list):
            raise WorkspaceError(NOT_WHOLE)
        return [{'id': icon['id'], 'name': icon.get('label') or icon['id'],
                 'category': icon.get('category'), 'native': bool(icon.get('native'))}
                for icon in results if isinstance(icon, dict)
                and isinstance(icon.get('id'), str)]

    def audit(self, deck: Path, brand_id: str, variant: str | None) -> dict:
        """Run the brand's own audit over a finished deck."""
        report = self._answer('presentation', '--brand', brand_id, *_variant(variant),
                              '--file', str(deck), '--json', report=True)

        def said(kept: str) -> list[dict]:
            return [{'code': one.get('ruleId'), 'slide': one.get('slide'),
                     'says': one.get('remediation')}
                    for one in report.get(kept) or [] if isinstance(one, dict)]

        return {'status': report.get('status'), 'blockers': said('blockers'),
                'warnings': said('warnings')}

    def ready(self) -> dict:
        """What the skill's own readiness check finds on this computer. It asks Google
        nothing."""
        return self._answer('doctor', '--profile', 'presentation', '--json', report=True)
