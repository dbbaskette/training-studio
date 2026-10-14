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

Added to the above
------------------
- `found()` returns [{'name', 'runtime', 'brands'}], `runtime` being the skill's folder as
  text, with links followed. Give one to `Brand(runtime=...)` to use that skill.
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

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import weakref
import zipfile
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
from workspace import WorkspaceError

from runner import slides

VARIABLE = 'BRAND_SKILL_RUNTIME'
TIMEOUT = 120
DELIVERIES = ('reading', 'live')
SHARED = (('Library', 'Application Support'), ('.local', 'share'))  # each skill has a folder
SKILLS = (('.claude', 'skills'), ('.agents', 'skills'), ('.cursor', 'skills'))
NAMED = re.compile(r'^[\w.-]{1,80}$')
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
    override = os.environ.get(VARIABLE)
    if override:
        return [Path(override).expanduser()]

    def inside(folder: Path) -> list[Path]:
        try:
            return sorted(folder.iterdir())
        except OSError:
            return []

    user = home or Path.home()
    return [place / 'current' for parts in SHARED for place in inside(user.joinpath(*parts))] \
        + [place for parts in SKILLS for place in inside(user.joinpath(*parts))]


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
    try:
        done = subprocess.run(command, cwd=cwd, capture_output=True, timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL, encoding='utf-8', errors='replace')
    except subprocess.TimeoutExpired:
        raise WorkspaceError(f'The brand skill did not answer in {TIMEOUT} seconds.')
    except OSError as failure:
        raise WorkspaceError(f'The brand skill could not be started ({failure}).')
    return done.returncode, done.stdout, done.stderr


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


def _named(run, node: str, script: Path, otherwise: str) -> str:
    """What a skill calls itself: its version line without the number, else its folder."""
    try:
        code, out, _ = run([node, str(script), 'version'])
    except WorkspaceError:
        code, out = 1, ''
    name = out.strip().partition('\n')[0].rpartition(' ')[0].strip() if code == 0 else ''
    return name[:80] or otherwise


def _installed(run=None, home: Path | None = None):
    """Each brand skill on this computer: (its folder, its command, its name, its brands)."""
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
    return [{'name': name, 'runtime': str(runtime), 'brands': brands}
            for runtime, _, name, brands in _installed(run, home)]


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
            self.runtime, self.script, self.name, _ = next(_installed(run), [None] * 4)
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
        self.name = _named(self.run, self.node, self.script, hints[0])

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


def stand_in() -> Brand:
    """A Brand that needs nothing installed, for tests."""
    return Brand(runtime=Path('stand-in'), run=StandIn())


# --- a stand-in for tests ----------------------------------------------------------------

BRAND, VARIANTS = 'example', ('light', 'dark')
SOURCES = (('brand/tokens.json', 'tokens'), ('references/brand-rules.md', 'brand policy'),
           ('brand/presentation.json', 'presentation system'),
           ('assets/template.pptx', 'native template'),
           ('assets/icons.pptx', 'icon library'), ('references/icon-index.json', 'icon index'))
TOKENS = {
    'font': 'Arial',
    'colors': {
        'light': {'canvasPrimary': '#FFFFFF', 'canvasSecondary': '#E6E8EB',
                  'inkDeep': '#1F2430', 'inkSecondary': '#5A6170',
                  'headingPrimary': '#1F4E8C', 'accentAqua': '#0B7A75',
                  'statusAttention': '#B3261E'},
        'dark': {'canvasPrimary': '#14171F', 'canvasSecondary': '#262B36',
                 'inkDeep': '#F2F4F7', 'inkSecondary': '#B8BFCC',
                 'headingPrimary': '#8AB4F8', 'accentAqua': '#5CCFC9',
                 'statusAttention': '#F2B8B5'}},
    'language': {'headlineCase': 'sentence', 'preserveProductNamesAndAcronyms': True,
                 'names': ['Write Example Co in full, never ExCo.',
                           'Example Platform is a product: keep its capitals.']}}
SYSTEM = {   # the brand's slide geometry and type, in points
    'canvas': {'width': 960, 'height': 540},
    'titleBox': {'x': 48, 'y': 36, 'width': 864, 'height': 60},
    'contentBox': {'x': 48, 'y': 120, 'width': 864, 'height': 360},
    'reservedBottom': 492, 'spacing': {'inset': 16, 'column': 28},
    'typography': {
        'title': {'size': 28, 'bold': True, 'colorRole': 'headingPrimary'},
        'body': {'size': 24, 'bold': False, 'colorRole': 'inkDeep'},
        'bodyReference': {'size': 20, 'bold': False, 'colorRole': 'inkDeep'},
        'label': {'size': 20, 'bold': True, 'colorRole': 'inkDeep'},
        'caption': {'size': 14, 'bold': False, 'colorRole': 'inkSecondary'},
        'metric': {'size': 60, 'bold': True, 'colorRole': 'accentAqua'},
        'quote': {'size': 30, 'bold': False, 'colorRole': 'inkDeep'}},
    'chart': {'seriesRoles': ['headingPrimary', 'accentAqua']},
    'table': {'headerFillRole': 'headingPrimary', 'headerTextRole': 'canvasPrimary'},
    'icon': {'size': 48}}
ICONS = (('ex-database', 'Data', 'Icon database', True),
         ('ex-cloud', 'Platform', 'Icon cloud', True),
         ('ex-cloud-lock', 'Security', 'Icon cloud lock', True),
         ('ex-gears', 'Operations', 'Icon gears restart', True),
         ('ex-photo', 'People', 'Icon team photo', False))   # a picture, not a drawing
RULES = '# Example Co brand rules\n\nSquare corners. One accent on a slide.\n'
ICON_USAGE = 'Usage: example-brand icons --query <words> [--limit <1-20>] [--json]'
MAX_WORDS, MIN_TEXT = 60, 18   # what the audit allows a slide
RUN = re.compile(r'<a:r><a:rPr sz="(\d+)"/><a:t>([^<]*)</a:t></a:r>')
PART = re.compile(r'^ppt/slides/slide(\d+)\.xml$')
PLACEHOLDER = re.compile(r'lorem ipsum|click to add', re.IGNORECASE)
FLAGS = ('json', 'compact', 'no-previews', 'strict')


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Said(Exception):
    """What the command would print before ending with an error code."""

    def __init__(self, line: str, code: int = 1):
        super().__init__(line)
        self.code = code


class StandIn:
    """Behaves like a brand skill's companion command, in Python, for one made-up brand.

    Example Co comes in a light and a dark variant. Its contract is one the slides stand-in
    accepts, tied by hash to the files in `home`, the stand-in's own folder: change one and
    a contract exported before is refused, as a real brand's is. Its icon library holds
    five icons, one of them a picture. Its audit reads a deck the slides stand-in wrote and
    warns as a real one does: on text smaller than 18 points, which every caveat and source
    line is, and on more than 60 words on a slide. Starter text left in a slide ("Lorem
    ipsum", "Click to add") blocks it. `calls` lists the arguments of every call made.
    """

    def __init__(self, home: Path | None = None):
        self.calls: list[list[str]] = []
        if home is None:
            home = tempfile.mkdtemp(prefix='brand-stand-in-')
            weakref.finalize(self, shutil.rmtree, home, True)
        self.home = Path(home).resolve()
        index = {'entries': [{'id': ident, 'category': category, 'label': label,
                              'native': native, 'bounds': [0, 0, 100, 100],
                              'shapeIds': ['1', '2']}
                             for ident, category, label, native in ICONS]}
        for name, content in (('brand/tokens.json', TOKENS), ('references/brand-rules.md',
                                                              RULES),
                              ('brand/presentation.json', SYSTEM),
                              ('references/icon-index.json', index)):
            path = self.home / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(content if isinstance(content, str)
                                else json.dumps(content, indent=2) + '\n', encoding='utf-8')
        for name in ('assets/template.pptx', 'assets/icons.pptx'):
            path = self.home / name
            path.parent.mkdir(exist_ok=True)
            if not path.exists():
                with zipfile.ZipFile(path, 'w') as archive:
                    archive.writestr(zipfile.ZipInfo('[Content_Types].xml'), '<Types/>')

    def __call__(self, command: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
        args = [str(part) for part in command[2:]]
        self.calls.append(args)
        try:
            code, result = self._act(args)
        except _Said as said:
            return said.code, '', f'{said}\n'
        except (KeyError, TypeError, AttributeError, ValueError, OSError) as said:
            return 1, '', f'{said}\n'
        if isinstance(result, str):
            return code, result + '\n', ''
        return code, json.dumps(result, indent=2, ensure_ascii=False) + '\n', ''

    def _act(self, args: list[str]):
        name, rest = (args[0] if args else None), args[1:]
        action = rest.pop(0) if name == 'contract' and rest else None
        options: dict = {}
        while rest:
            key = rest.pop(0).removeprefix('--')
            options[key] = True if key in FLAGS else rest.pop(0) if rest else None
        if name in ('version', '--version'):
            return 0, 'Example Brand 0.0.0-stand-in'
        if name == 'brands':
            return 0, [{'brand': BRAND, 'name': 'Example Co', 'variants': list(VARIANTS)}]
        if name == 'contract' and action == 'export':
            return 0, self._export(options)
        if name == 'contract' and action == 'check':
            contract = slides.StandIn.contract(options.get('file'), medium=None)
            return 0, {'revision': contract['revision'], 'identity': contract['identity'],
                       'medium': contract['medium'], 'sources': len(contract['sources']),
                       'status': 'current local sources'}
        if name == 'contract':
            raise _Said('Use contract export|check')
        if name == 'icons':
            return 0, self._search(options)
        if name == 'presentation':
            return self._audit(options)
        if name == 'doctor':
            return 0, {'profile': options.get('profile', 'web'), 'ok': True,
                       'installation': {'root': str(self.home), 'version': '0.0.0-stand-in',
                                        'installations': []},
                       'checks': [{'name': 'node', 'ok': True},
                                  {'name': 'canonical-package', 'ok': True},
                                  {'name': 'python3', 'ok': True}],
                       'ready': False,
                       'capabilities': [{'name': 'assets', 'status': 'available'},
                                        {'name': 'native-authoring', 'status': 'unverified',
                                         'next': 'Check that a copy of a deck can be '
                                                 'edited.'}],
                       'manual': ['Having the tools is not the same as a deck that is '
                                  'ready.']}
        raise _Said(f'Unknown command: {name}. Run example-brand --help.', 2)

    def _chosen(self, options: dict) -> tuple[str, str]:
        """The brand and variant a call names: by its ID or its name, in any case."""
        brand, variant = options.get('brand') or BRAND, options.get('variant') or VARIANTS[0]
        if str(brand).strip().lower() not in (BRAND, 'example co'):
            raise _Said(f'Unknown brand: {brand}. Choose Example Co.')
        if variant not in VARIANTS:
            raise _Said(f"Unknown {BRAND} variant: {variant}. Choose {', '.join(VARIANTS)}.")
        return BRAND, variant

    def _export(self, options: dict) -> dict:
        delivery = options.get('delivery') or 'reading'
        if options.get('medium', 'slides') != 'slides' or delivery not in DELIVERIES:
            raise _Said('Choose medium slides and delivery live|reading')
        _, variant = self._chosen(options)
        if not options.get('output'):
            raise _Said('Choose a new output directory')
        sources = [{'path': str(self.home / name), 'kind': kind,
                    'sha256': _digest((self.home / name).read_bytes())}
                   for name, kind in SOURCES]
        by_kind = {source['kind']: source for source in sources}
        tokens = json.loads((self.home / 'brand/tokens.json').read_text(encoding='utf-8'))
        system = json.loads((self.home / 'brand/presentation.json').read_text(
            encoding='utf-8'))
        contract = {
            'schema': 1, 'identity': {'id': BRAND, 'name': 'Example Co', 'variant': variant},
            'medium': {'kind': 'slides', 'delivery': delivery}, 'sources': sources,
            'design': {
                'fontFamily': tokens['font'], 'colors': tokens['colors'][variant],
                'geometry': {'rectangularRadiusPx': 0},
                'references': {'guide': by_kind['brand policy']['path']},
                'slides': {**system, 'icon': {**system['icon'], 'library': {
                    'path': by_kind['icon library']['path'],
                    'index': by_kind['icon index']['path']}}},
                'nativeTemplate': {'path': by_kind['native template']['path'],
                                   'sha256': by_kind['native template']['sha256'],
                                   'layoutPart': 'ppt/slideLayouts/slideLayout2.xml',
                                   'masterPart': 'ppt/slideMasters/slideMaster1.xml'}},
            'language': {'organization': {'rules': tokens['language'],
                                          'toneStatus': 'unspecified; the brand sets '
                                                        'names, not tone'},
                         'authorVoice': {'status': 'unselected'}}}
        contract['revision'] = slides.StandIn.revision(contract)
        output = Path(options['output']).resolve()
        try:
            output.mkdir(mode=0o700)
        except FileExistsError:
            raise _Said(f"EEXIST: file already exists, mkdir '{output}'")
        design, language = contract['design'], contract['language']
        body = 'body' if delivery == 'live' else 'bodyReference'
        for name, text in (
                ('brand-contract.json', json.dumps(contract, indent=2) + '\n'),
                ('DESIGN.md', f"# Example Co design · slides\n\nContract revision: "
                 f"{contract['revision']}\n\nFont: {design['fontFamily']}. Color roles: "
                 f"{json.dumps(design['colors'])}.\n\nDelivery: {delivery}; body role: "
                 f"{body}. Typography: {json.dumps(design['slides']['typography'])}.\n"),
                ('VOICE.md', f"# Language and author voice\n\nContract revision: "
                 f"{contract['revision']}\n\nOrganization language: "
                 f"{json.dumps(language['organization'])}.\n\nAuthor voice status: "
                 'unselected.\n\nNo author voice was chosen. The brand says how things '
                 'are named, not how to sound.\n')):
            (output / name).write_text(text, encoding='utf-8')
            (output / name).chmod(0o600)
        return {'output': str(output), 'revision': contract['revision'],
                'identity': contract['identity'], 'medium': contract['medium'],
                'authorVoice': 'unselected'}

    def _search(self, options: dict) -> dict:
        def normal(text: str) -> list[str]:
            return re.sub(r'[^\w]+', ' ', text.lower()).split()

        try:
            brand, variant = self._chosen(options)
            terms = normal(str(options.get('query') or ''))
            if not terms:
                raise _Said('--query needs words to search for')
            if not re.fullmatch(r'[1-9]|1\d|20', str(options.get('limit', '5'))):
                raise _Said('--limit must be an integer from 1 to 20')
        except _Said as said:
            raise _Said(f'{said}\n{ICON_USAGE}', 2)
        index = json.loads((self.home / 'references/icon-index.json').read_text(
            encoding='utf-8'))
        # Every word must match: a short one a whole word, a longer one the start of one.
        matches = [{'kind': 'icon', **entry, 'preview': None} for entry in index['entries']
                   if all(any(word == term if len(term) < 3 else word.startswith(term)
                              for word in normal(entry['label'])) for term in terms)]
        limit = int(options.get('limit', 5))
        return {'query': options['query'], 'brand': brand, 'variant': variant,
                'source': str(self.home / 'assets/icons.pptx'), 'totalMatches': len(matches),
                'truncated': len(matches) > limit, 'results': matches[:limit],
                'guidance': 'Name an icon by its ID. One that is a picture cannot be '
                            'placed as a drawing.'}

    def _audit(self, options: dict) -> tuple[int, dict]:
        path = str(options.get('file') or '')
        if not path.lower().endswith('.pptx'):
            raise _Said('--file requires a .pptx path', 2)
        brand, variant = self._chosen(options)
        try:
            with zipfile.ZipFile(path) as deck:
                parts = sorted((name for name in deck.namelist() if PART.match(name)),
                               key=lambda name: int(PART.match(name)[1]))
                texts = [RUN.findall(deck.read(name).decode('utf-8')) for name in parts]
        except (OSError, zipfile.BadZipFile):
            raise _Said('The file is not a PowerPoint package that can be read.', 2)
        blockers, warnings, held = [], [], []

        def find(into, rule, slide, shape, observed, remediation):
            into.append({'ruleId': rule, 'slide': slide, 'shapeId': shape,
                         'severity': 'blocker' if into is blockers else 'warning',
                         'observed': observed, 'remediation': remediation})

        for number, runs in enumerate(texts, 1):
            for shape, (size, text) in enumerate(runs, 2):
                if int(size) / 100 < MIN_TEXT:
                    find(warnings, 'SMALL_TEXT', number, str(shape),
                         {'minimumPt': int(size) / 100},
                         'Make the text larger, or move the detail to the notes.')
                if PLACEHOLDER.search(text):
                    find(blockers, 'UNRESOLVED_PLACEHOLDER', number, str(shape),
                         'starter text', 'Replace the starter text with what the slide '
                         'should say.')
            words = sum(len(html.unescape(text).split()) for _, text in runs)
            if words > MAX_WORDS:
                find(warnings, 'HIGH_TEXT_DENSITY', number, None,
                     {'words': words, 'reviewThreshold': MAX_WORDS},
                     'Cut the words the slide shows, or move detail to the notes.')
            held.append({'slide': number, 'words': words, 'textObjects': len(runs),
                         'minFontPt': min((int(size) / 100 for size, _ in runs),
                                          default=None)})
        report = {'schemaVersion': 1, 'file': str(Path(path).resolve()),
                  'sha256': _digest(Path(path).read_bytes()),
                  'status': 'BLOCKED' if blockers else 'WARN' if warnings else 'PASS',
                  'coverage': 'How the file is built only. A pass says nothing of how the '
                              'slides look.',
                  'thresholds': {'maxWords': MAX_WORDS, 'minTextPt': MIN_TEXT},
                  'slides': held, 'blockers': blockers, 'warnings': warnings,
                  'brand': brand, 'variant': variant}
        return (2 if blockers else 0), report
