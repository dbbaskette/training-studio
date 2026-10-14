"""A stand-in for a brand skill's companion command, for tests.

    brand = stand_in()         # the runner's Brand, with StandIn behind it

StandIn knows one made-up brand, Example Co, with a contract the slides stand-in accepts,
a few icons and an audit, and needs neither Node nor an installed skill. `stand_in()` reads
`Brand` from the runner's module when it is called, so a test that has replaced that class
gets its replacement.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import tempfile
import weakref
import zipfile
from pathlib import Path

from stand_ins import slides

from runner import brand as skill
from runner.brand import DELIVERIES


def stand_in() -> skill.Brand:
    """A Brand that needs nothing installed."""
    return skill.Brand(runtime=Path('stand-in'), run=StandIn())


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
