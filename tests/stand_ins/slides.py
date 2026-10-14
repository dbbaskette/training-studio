"""A stand-in for the harness-slides command line, for tests.

    slides = stand_in()        # the runner's Slides, with StandIn behind it
    sketch(slide, prefix)      # one content slide of an outline, drawn plainly

`sketch` draws a slide as a section's composer might. StandIn's `fails`, `drive`, `local`
and `pause` make it refuse, lose its Drive or its LibreOffice, or take its time; `files` is
what it "keeps in Drive". StandIn says in its own docstring where it is simpler than the
real compiler. `stand_in()` reads `Slides` from the runner's module when it is called, so a
test that has replaced that class gets its replacement.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import struct
import threading
import time
import zipfile
import zlib
from pathlib import Path
from xml.sax.saxutils import escape

from runner import slides as tool
from runner.slides import GALLERY, LEAD, MINIMUM, REFERENCES, RELATIONS


def stand_in() -> tool.Slides:
    """A Slides that needs nothing installed."""
    command = StandIn()
    return tool.Slides(runtime=Path('stand-in'), run=command, read=command.read)


IDENT = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_-]{4,40}$')
KINDS = ('cover', 'section', 'content', 'closing')
RHYTHMS = ('anchor', 'dense', 'breathing')
FEWEST = {**dict.fromkeys(RELATIONS, 2), 'quantity': 1, 'none': 0}
BUDGETS = {'live': 60, 'reading': 90}   # body words a slide carries, by how it is delivered
OUTLINE = ('version', 'title', 'audience', 'delivery', 'minutes', 'direction', 'layouts',
           'material', 'house', 'approval', 'slides')
SLIDE = {'cover': ('subtitle', 'detail'), 'section': ('subtitle',), 'closing': (),
         'content': ('understand', 'relation', 'focal', 'rhythm', 'points', 'caveat',
                     'source', 'sources')}
COMPOSED = ('id', 'title', 'sources', 'canvas', 'connect', 'notes', 'layout', 'subtitle',
            'detail', 'picture', 'brief', 'caveat', 'source')
NODES = {'stack': ('direction', 'gap', 'align', 'children'),
         'grid': ('columns', 'gap', 'children'), 'free': ('children',),
         'box': ('text', 'shape', 'fill', 'color', 'textRole', 'align', 'children', 'gap',
                 'style'),
         'text': ('text', 'textRole', 'color', 'align'), 'icon': ('icon', 'color', 'style'),
         'rule': (), 'spacer': ()}
SHAPES = {'rect': (1, 1), 'ellipse': (.7, .7), 'roundRect': (1, 1), 'diamond': (.5, .5),
          'hexagon': (.6, .65), 'chevron': (.6, 1), 'can': (1, .6)}   # the room text gets
DRAWN = {   # how each relation must show in the structure, and what to say when it does not
    'order': (lambda f: f['edges'] or f['chevrons'] > 1 or f['layers'], 'Join nodes with '
              'edges, use chevrons in sequence or stack the steps in a column'),
    'dependency': (lambda f: f['edges'], 'Join the nodes with edges'),
    'hierarchy': (lambda f: f['edges'] or f['nested'] or f['layers'],
                  'Use edges, nested boxes or stacked layers'),
    'membership': (lambda f: f['members'], 'Put the members inside a box'),
    'contrast': (lambda f: f['pair'], 'Place the things compared side by side'),
    'parallel': (lambda f: f['peers'],
                 'Place the peers in a grid, a row or a column of like nodes'),
    'quantity': (lambda f: f['metric'], 'Show the number with the metric text role')}
ROLES = ('title', 'body', 'bodyReference', 'label', 'caption', 'metric', 'quote')
COLOURS = ('canvasPrimary', 'canvasSecondary', 'inkDeep', 'headingPrimary', 'accentAqua')
LAYOUTS = (   # the one template the stand-in knows: name, title, subtitles, pictures
    ('Title Slide', True, 1, 0), ('Title Only', True, 0, 0), ('Agenda', False, 0, 0),
    ('Section Header', True, 1, 0), ('Quote', False, 0, 1), ('Big Statement', True, 0, 0),
    ('Picture and Title', True, 1, 1), ('Thank You', False, 0, 0), ('Blank', False, 0, 0))
DEFAULT = 'Title Only'
QUESTIONS = (
    'After three seconds, is the main point clear, and is it the claim in the title?',
    'Does the eye land first on the element that carries the point?',
    'Is there exactly one emphasis?',
    'Does every element support the title?',
    'Is each label inside or right beside what it names?',
    'Is the space balanced, with nothing stranded or crowded?',
    'Is the slide consistent with its neighbours in style, and different from them in '
    'layout unless they are meant to be compared?',
    'Does every image and icon explain something?')
GRADES = {'critical': 'The slide misleads, cannot be read, or its point cannot be found. '
                      'Blocks delivery.',
          'major': 'The slide works but is clearly weaker than it should be. Fix it.',
          'minor': 'A small flaw. Log it.'}
NO_DRIVE = ('Google API request failed (HTTP {}). Check account, Drive scopes, file access, '
            'and organization policy.')
OPTIONS = {'outline contract': ('brand',), 'outline check': ('file', 'brand'),
           'outline start': ('file', 'brand', 'output'), 'compose contract': ('brand',),
           'compose layouts': ('brand',), 'compose compile': ('file', 'brand', 'output'),
           'compose merge': ('file', 'output'),
           'compose preview': ('file', 'output', 'slide', 'file-id', 'renderer'),
           'compose critique': ('file', 'assessment'), 'compose render': ('file', 'output'),
           'drive check': (), 'drive import': ('file', 'name', 'folder-id')}
PICTURE = 320   # how wide the stand-in draws a slide, in pixels
BRIEF = (   # what the tool writes for the worker of one section, word for word
    '# Section {number} of {title}\n\n'
    'You are building one section of a deck. Other sections are being built at the same '
    'time. Read `references/parallel-build.md`, the part headed "If you are a worker", in '
    'the guidance for this task, and follow what it tells you to read.\n\n'
    '## The deck\n\n'
    '{title}{audience}, delivered {said}. The user has approved what each slide says. How '
    'each is drawn is yours to design.\n\n'
    '## Paths\n\n'
    '- Runtime: `{runtime}`\n- Brand contract: `{brand}`\n- Work directory: `{output}`\n'
    '- Write your section to `{name}`, and keep your builds and previews under '
    '`w{number}/`. Touch nothing else in the work directory.\n{material}\n\n'
    '## Direction, to copy unchanged\n\n```json\n{direction}\n```\n\n'
    '## House style\n{house}\n\n'
    '## Your slides, in order\n\n'
    'Prefix every node and edge ID you create with `s{number}_`. Slide IDs, titles, '
    'wording and order are fixed.\n{slides}\n\n'
    'Before your section comes {before}; after it comes {after}. Do not echo a neighbour, '
    'and make your own slides differ from each other.\n\n'
    '## Preview\n\n'
    'Use one Drive preview file of your own for every preview, and say which it was.\n\n'
    '## Return\n\n'
    'The section file, your final preview directory, the Drive file ID, what you changed '
    'after looking, and what still bothers you.\n')
GUIDANCE = {   # what the stand-in's guidance files say: a few invented lines each
    'design.md': '# Designing a slide\n\nStart from what the slide must make its audience '
                 'understand. Give it one emphasis, and let the structure show the '
                 'relation.\n',
    'compositions.md': '# Compositions\n\nA slide is a canvas of stacks, grids, boxes and '
                       'text, with edges that join nodes. Its brief names the relation, the '
                       'focal node and the rhythm.\n',
    'draft.md': '# Drafting an outline\n\nOne claim a slide, said in its title. Each point '
                'is a label and a sentence. Name the relation between the points.\n',
    'gallery.md': '# The gallery\n\nOne drawn slide for each relation. Copy the reasoning '
                  'and never the layout.\n'}
SHOWN = {'id': 'worked-example', 'kind': 'content',
         'title': 'An example of one relation, drawn',
         'points': [{'label': 'First', 'text': 'One thing.'},
                    {'label': 'Second', 'text': 'Another thing.'}], 'sources': ['example']}
PRESENTATION = (
    '# {title}\n\n{audience}Delivered {said}. {count} slides.\n\n'
    'Outline: `outline.json`, SHA-256 `{digest}`.\n\n'
    '## Approval\n\n{approval}\n\n'
    '## Direction\n\n```json\n{direction}\n```\n\n'
    '## House style\n{house}\n\n'
    '## Parts\n\n| Who | File | Slides |\n| --- | --- | --- |\n{table}\n')


class _Said(ValueError):
    """What the command would print before exiting with 1."""


def _said(problems: list[str]) -> _Said:
    return _Said(problems[0] if len(problems) == 1
                 else f'{len(problems)} problems to fix:\n' + '\n'.join(problems))


def _str(value) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 20000


def _number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _hex(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value) is not None


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _compact(value) -> str:
    return json.dumps(value, separators=(',', ':'), ensure_ascii=False)


def _pretty(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + '\n'


def _tidy(number: float):
    """Two decimal places, and a whole number without its point."""
    rounded = math.floor(number * 100 + .5) / 100
    return int(rounded) if rounded == int(rounded) else rounded


def _words(text) -> int:
    return len(str(text or '').split())


def _read(path) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError:
        raise _Said(f"ENOENT: no such file or directory, open '{path}'")


def _load(path):
    data = _read(path)
    try:
        return json.loads(data.decode('utf-8'))
    except ValueError as wrong:
        raise _Said(f'{wrong} is not valid JSON')


def _write(path: Path, content) -> None:
    """A new file, as the tool writes one: never over another, and for its owner only."""
    try:
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise _Said(f"EEXIST: file already exists, open '{path}'")
    with os.fdopen(handle, 'wb') as stream:
        stream.write(content.encode('utf-8') if isinstance(content, str) else content)


def _folder(path: Path) -> Path:
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        raise _Said(f"EEXIST: file already exists, mkdir '{path}'")
    except OSError:
        raise _Said(f"ENOENT: no such file or directory, mkdir '{path}'")
    return path


def _wide(text: str, size: float) -> float:
    """A line's width without the brand's font: the tool's own estimate, a little wide."""
    return sum(.85 if letter in 'MW@%' else .27 if letter in "il., '" else .53
               for letter in text) * size


def _tall(text: str, style: dict, width: float) -> float:
    lines = sum(max(1, math.ceil(_wide(line, style['size']) / max(1, width - 7.2)))
                for line in text.split('\n'))
    return lines * style['size'] * 1.25 + 7.2


def _title_lines(contract: dict, titles: list[str]) -> tuple[int, list[int]]:
    """How many lines the brand's title holds, and how many each title runs to."""
    sl = contract['design']['slides']
    style, box = sl['typography']['title'], sl['titleBox']
    one, line = _tall('Ag', style, 1e4), style['size'] * 1.25
    return (max(1, math.floor((box['height'] - one + .5) / line) + 1),
            [math.floor((_tall(title, style, box['width']) - one) / line + .5) + 1
             for title in titles])


def _direction(direction, colours: dict) -> None:
    if not isinstance(direction, dict):
        raise _Said('direction must be an object')
    if any(key not in ('focal', 'neutral', 'meanings', 'motif') for key in direction):
        raise _Said('unsupported direction field')
    if 'focal' not in direction or 'neutral' not in direction:
        raise _Said('direction needs focal and neutral color roles')
    for key in ('focal', 'neutral'):
        if direction[key] not in colours:
            raise _Said(f"direction.{key} must be a brand color role: {', '.join(colours)}")
    if direction['focal'] == direction['neutral']:
        raise _Said('direction.focal and direction.neutral must differ')
    meanings = direction.get('meanings', {})
    if not isinstance(meanings, dict):
        raise _Said('direction.meanings maps color roles to what they stand for')
    for role, meaning in meanings.items():
        if role not in colours:
            raise _Said(f'direction.meanings uses {role}, which is not a brand color role')
        if role == direction['focal']:
            raise _Said('the focal color cannot also carry a meaning')
        if not _str(meaning):
            raise _Said(f'direction.meanings: say what {role} means')
    if colours[direction['neutral']].upper() == colours[direction['focal']].upper():
        raise _Said('direction.neutral is the same color as the focal; choose a different '
                    'one')


def _checked(outline, contract: dict) -> dict:
    """An outline against the tool's rules. What is wrong with its structure is said
    together; everything about its words comes back as findings."""
    if not isinstance(outline, dict) or outline.get('version') != 1:
        raise _Said('Use outline version 1 (run outline contract)')
    problems: list[str] = []

    def fail(where, message):
        problems.append(f'{where}: {message}')

    for key in outline:
        if key not in OUTLINE:
            fail('outline', f'unsupported field {key}')
    if not _str(outline.get('title')):
        fail('outline', 'provide the deck title')
    if 'audience' in outline and not _str(outline['audience']):
        fail('outline', 'audience is a short description, or omitted')
    if 'minutes' in outline and not (_number(outline['minutes'])
                                     and 0 < outline['minutes'] <= 600):
        fail('outline', 'minutes is the length of the talk, as a number')
    exported = contract['medium'].get('delivery')
    delivery = outline.get('delivery') or exported or 'reading'
    if delivery not in BUDGETS:
        fail('outline', 'delivery is live or reading')
    elif outline.get('delivery') and exported and delivery != exported:
        fail('outline', f'delivery is {delivery}, but the brand contract was exported for '
             f'{exported}; export it for {delivery}')
    for key in ('material', 'house', 'approval'):
        if key in outline and not (isinstance(outline[key], list)
                                   and all(map(_str, outline[key]))):
            fail('outline', f'{key} is a list of lines')
    named = outline.get('layouts')
    if 'layouts' in outline and not (isinstance(named, dict) and all(
            kind in ('cover', 'section', 'closing') and _str(name)
            for kind, name in named.items())):
        fail('outline', 'layouts names template layouts for cover, section and closing')
    if 'direction' in outline:
        try:
            _direction(outline['direction'], contract['design']['colors'])
        except _Said as said:
            fail('outline', str(said))
    slides = outline.get('slides')
    if not isinstance(slides, list) or not 1 <= len(slides) <= 100:
        fail('outline', 'provide 1–100 slides')
        raise _said(problems)
    seen = set()
    for index, slide in enumerate(slides):
        if not isinstance(slide, dict):
            fail(f'slide {index + 1}', 'each slide is an object')
            continue
        ident = slide.get('id')
        where = ident if _str(ident) else f'slide {index + 1}'
        if not isinstance(ident, str) or not IDENT.match(ident) or ident in seen:
            fail(where, f'invalid or repeated ID: {ident}')
        seen.add(ident)
        kind = slide.get('kind')
        if kind not in KINDS:
            fail(where, f"kind is one of {'|'.join(KINDS)}")
            continue
        for key in slide:
            if key not in ('id', 'kind', 'title', 'notes', *SLIDE[kind]):
                fail(where, f'a {kind} slide has no {key}')
        if not _str(slide.get('title')):
            fail(where, 'provide the title')
        for key in ('subtitle', 'detail', 'notes', 'caveat', 'source', 'focal'):
            if key in slide and not _str(slide[key]):
                fail(where, f'provide {key} text or omit it')
        if 'detail' in slide and 'subtitle' not in slide:
            fail(where, 'detail needs a subtitle before it')
        if kind != 'content':
            continue
        if not _str(slide.get('understand')):
            fail(where, 'say in one sentence what the audience must understand')
        relation = slide.get('relation')
        if relation not in RELATIONS:
            fail(where, f"relation is one of {'|'.join(RELATIONS)}")
            continue
        if 'rhythm' in slide and slide['rhythm'] not in RHYTHMS:
            fail(where, f"rhythm is one of {'|'.join(RHYTHMS)}")
        sources = slide.get('sources')
        if not isinstance(sources, list) or not sources or not all(map(_str, sources)):
            fail(where, 'provide sources: one or more IDs naming what the slide rests on, '
                 'such as request or author_knowledge')
        points = slide.get('points', [])
        if not isinstance(points, list) or len(points) > 12 or not all(
                isinstance(point, dict) and point and set(point) <= {'label', 'text'}
                and all(map(_str, point.values())) for point in points):
            fail(where, 'points is a list of up to 12 items, each with a label, a text or '
                 'both')
            continue
        if len(points) < FEWEST[relation]:
            fail(where, f'relation "{relation}" needs at least {FEWEST[relation]} point'
                 f"{'' if FEWEST[relation] == 1 else 's'}; it has {len(points)}")
        if relation == 'quantity' and points and 'label' not in points[0]:
            fail(where, "for quantity, the first point's label is the figure")
    if problems:
        raise _said(problems)

    findings, budget = [], BUDGETS[delivery]
    content = [slide for slide in slides if slide['kind'] == 'content']

    def find(slide, code, detail):
        findings.append({'slide': slide if isinstance(slide, str) else slide['id'],
                         'code': code, 'detail': detail})

    said = 'live' if delivery == 'live' else 'for reading'
    fit, lines = _title_lines(contract, [slide['title'] for slide in content])
    for slide, runs in zip(content, lines):
        if runs > fit:
            find(slide, 'title-too-long', f'The title runs to {runs} lines and the '
                 f"brand's title holds {fit}. Shorten the claim.")
    counts = {}
    for slide in content:
        points = slide.get('points', [])
        own = 'focal' in slide and not any(p.get('label') == slide['focal'] for p in points)
        counts[slide['id']] = sum(_words(p.get('label')) + _words(p.get('text'))
                                  for p in points) + (_words(slide['focal']) if own else 0)
        if counts[slide['id']] > budget:
            find(slide, 'over-budget', f"{counts[slide['id']]} body words; a slide "
                 f'delivered {said} carries about {budget}. Cut words or split the slide.')
    titles: dict = {}
    for slide in slides:
        key = slide['title'].strip().lower()
        if key in titles:
            find(slide, 'repeated-title', f'Same title as {titles[key]}.')
        titles.setdefault(key, slide['id'])
    run: list[str] = []
    for slide in [*slides, {'kind': 'end'}]:
        if slide['kind'] == 'content' and slide.get('rhythm', 'dense') == 'dense':
            run.append(slide['id'])
            continue
        if len(run) >= 4:
            find(run[3], 'dense-run', f'{len(run)} dense slides in a row from {run[0]}. '
                 'Lighten one and mark it breathing, or put a section slide between.')
        run = []
    for slide in content:
        if delivery == 'live' and not slide.get('notes'):
            find(slide, 'no-notes', 'A slide presented live needs speaker notes: what the '
                 'presenter says, and the source behind the claim.')
    for slide in content:
        if 'focal' not in slide and slide['relation'] not in ('contrast', 'parallel',
                                                              'none'):
            find(slide, 'no-focal', 'Nothing is named as the point of this slide. Name it, '
                 'unless the slide compares equals.')
    return {'delivery': delivery, 'budget': budget, 'counts': counts, 'findings': findings}


class _Compiler:
    """A composition against one brand contract: the tool's rules, then whether each slide
    fits, measured by the tool's own estimate."""

    def __init__(self, contract: dict):
        design = contract['design']
        self.contract, self.sl, self.colours = contract, design['slides'], design['colors']
        self.roles = self.sl['typography']
        spacing = self.sl.get('spacing') or {}
        self.inset = spacing.get('inset', 16)
        self.gaps = {'none': 0, 'tight': self.inset / 2, 'normal': self.inset,
                     'wide': spacing.get('column', 28)}
        self.icon = (self.sl.get('icon') or {}).get('size', 48)
        self.body = 'body' if contract['medium'].get('delivery') == 'live' \
            else 'bodyReference'
        self.problems: list[str] = []
        self.summary: list[dict] = []
        self.room: list[dict] = []
        self.ids: set = set()

    def run(self, comp) -> tuple[dict, dict]:
        """The scene and its structure. What is wrong gathers in `problems`."""
        if not isinstance(comp, dict) or comp.get('version') != 1:
            raise _Said('Use composition version 1 (run compose contract)')
        if any(key not in ('version', 'title', 'slides', 'direction') for key in comp):
            raise _Said('Unsupported composition field')
        self.direction = direction = comp.get('direction')
        if 'direction' in comp:
            _direction(direction, self.colours)
        self.fills = [] if not direction else list(dict.fromkeys(
            [direction['neutral'], *direction.get('meanings', {}), 'canvasPrimary']))
        if not _str(comp.get('title')):
            raise _Said('Provide a deck title')
        slides = comp.get('slides')
        if not isinstance(slides, list) or not 1 <= len(slides) <= 100:
            raise _Said('Provide 1–100 slides')
        colours, roles = self.colours, self.roles
        scene = {'version': 2, 'title': comp['title'], 'mode': 'new',
                 'canvas': self.sl['canvas'],
                 'theme': {'font': self.contract['design']['fontFamily'],
                           'background': colours['canvasPrimary'],
                           'text': colours['inkDeep'], 'accent': colours['accentAqua'],
                           'muted': colours['canvasSecondary'],
                           'titleSize': roles['title']['size'],
                           'bodySize': roles[self.body]['size']}, 'slides': []}
        self.structure = {'groups': [], 'connectors': [], 'icons': [], 'layouts': [],
                          'adjusted': [], 'reading': [], 'unspoken': [],
                          'direction': direction, 'briefs': []}
        for s in slides:
            found: list[str] = []
            sid = s.get('id') if isinstance(s, dict) else None
            try:
                self.rules(s, found)
            except _Said as said:
                found.append(str(said))
            if found:
                # A slide that breaks a rule is not laid out; its title is still measured.
                if isinstance(s, dict) and 'layout' not in s and _str(s.get('title')) \
                        and _str(sid):
                    self.title_fit(s, found)
                self.problems += found
                continue
            self.sid, self.elements, self.tight, self.rects = sid, [], [], {}
            try:
                self.draw(s)
            except _Said as said:
                self.tight.append(str(said))
            if self.tight:
                self.problems += self.tight
                continue
            scene['slides'].append({'id': sid, 'title': s['title'], 'sources': s['sources'],
                                    'elements': self.elements,
                                    **({'notes': s['notes']} if 'notes' in s else {})})
        return scene, self.structure

    # --- the rules ---

    def claim(self, ident, where) -> None:
        if ident in self.ids:
            raise _Said(f'{where}: invalid or repeated ID: {ident} is already used in this '
                        'deck')
        if not isinstance(ident, str) or not IDENT.match(ident):
            raise _Said(f'{where}: invalid or repeated ID: {ident} must be 5 to 41 letters, '
                        'digits, _ or -, starting with a letter or _')
        self.ids.add(ident)

    def rules(self, s, found: list[str]) -> None:
        """One slide's rules. Every problem on it is gathered, so one compile shows all."""
        def fail(where, message):
            raise _Said(f'{where}: {message}')

        def attempt(check, *args):
            try:
                check(*args)
            except _Said as said:
                found.append(str(said))

        if not isinstance(s, dict):
            raise _Said('each slide must be an object')
        sid, direction, colours = s.get('id'), self.direction, self.colours
        if any(key not in COMPOSED for key in s):
            fail(sid, 'unsupported slide field')
        self.claim(sid, 'slide')
        self.claim(f'{sid}_title', sid)
        if not _str(s.get('title')):
            found.append(f'{sid}: provide a slide title')
        sources = s.get('sources')
        if not isinstance(sources, list) or not sources or not all(map(_str, sources)):
            found.append(f'{sid}: provide source references: one or more IDs naming what '
                         'the slide rests on, such as request or author_knowledge')
        brief = s.get('brief')
        if 'layout' in s:
            # A template layout slide fills that layout's placeholders and draws nothing.
            if not _str(s['layout']) or len(s['layout']) > 80:
                fail(sid, 'layout must be a template layout name')
            if any(key in s for key in ('canvas', 'connect', 'caveat', 'source')):
                fail(sid, 'a slide with a template layout has no canvas, edges, caveat or '
                     'source; put content on a standard slide')
            for key in ('subtitle', 'detail'):
                if key in s and not _str(s[key]):
                    fail(sid, f'provide {key} text or omit it')
            if 'detail' in s and 'subtitle' not in s:
                fail(sid, 'detail needs a subtitle before it')
            if 'brief' in s and not (isinstance(brief, dict) and set(brief) == {'rhythm'}
                                     and brief['rhythm'] in RHYTHMS):
                fail(sid, 'a template layout slide takes only brief.rhythm '
                     '(anchor|dense|breathing)')
            self.summary.append({'id': sid, 'nodes': 0, 'fills': [], 'edges': 0,
                                 'layout': s['layout']})
            return
        if 'detail' in s:
            found.append(f'{sid}: detail belongs to a slide with a template layout')
        for key in ('subtitle', 'source'):
            if key in s and not _str(s[key]):
                found.append(f'{sid}: provide {key} text or omit it')
        caveat = s.get('caveat')
        if 'caveat' in s and not _str(caveat) and not (
                isinstance(caveat, dict) and set(caveat) <= {'label', 'text'}
                and _str(caveat.get('text')) and _str(caveat.get('label', 'none'))
                and len(caveat.get('label', '')) <= 24):
            found.append(f'{sid}: caveat is a line of text, or {{label,text}} with a label '
                         'of a word or two')
        if 'brief' in s:
            if not isinstance(brief, dict) or any(
                    key not in ('relation', 'focal', 'rhythm') for key in brief):
                fail(sid, 'brief takes relation, focal and rhythm')
            if brief.get('relation') not in RELATIONS:
                found.append(f"{sid}: brief.relation must be one of {'|'.join(RELATIONS)}")
            elif 'rhythm' in brief and brief['rhythm'] not in RHYTHMS:
                found.append(f"{sid}: brief.rhythm must be one of {'|'.join(RHYTHMS)}")
            elif 'focal' in brief and not direction:
                found.append(f'{sid}: brief.focal needs a deck direction that names the '
                             'focal color')
        focal = brief.get('focal') if isinstance(brief, dict) else None
        only = 'only the focal node may use the focal color' \
            + ('' if focal else '; name it in brief.focal')
        local, leaves, fills = set(), set(), []
        facts = dict.fromkeys(('members', 'pair', 'peers', 'nested', 'layers', 'metric'),
                              False) | {'edges': 0, 'chevrons': 0, 'nodes': 0}

        def inspect(n, in_free):
            where = f'{sid}/{_tag(n)}'
            if not isinstance(n, dict) or n.get('type') not in NODES:
                fail(where, 'unknown node type')
            kind, kids = n['type'], n.get('children')
            if any(key not in ('id', 'type', 'weight', 'at', *NODES[kind]) for key in n):
                fail(where, 'unsupported node field; never silently drop content')
            facts['nodes'] += 1
            if kind in ('box', 'text', 'icon') or 'id' in n:
                self.claim(n.get('id'), where)
                local.add(n['id'])
            spot = n.get('at')
            if in_free and not (isinstance(spot, dict) and all(
                    _number(spot.get(key)) and 0 <= spot[key] <= 1
                    for key in ('x', 'y', 'width', 'height')) and spot['width'] > 0
                    and spot['height'] > 0 and spot['x'] + spot['width'] <= 1.0001
                    and spot['y'] + spot['height'] <= 1.0001):
                fail(where, 'free children need at:{x,y,width,height} within 0–1')
            if 'at' in n and not in_free:
                fail(where, 'at is only valid inside a free container')
            if 'weight' in n and not (_number(n['weight']) and 0 < n['weight'] <= 10):
                fail(where, 'weight must be above 0 and at most 10; weights are relative '
                     'shares, so 9.5 and 0.5 give 95% and 5%')
            if 'gap' in n and n['gap'] not in self.gaps:
                fail(where, f"gap must be one of {'|'.join(self.gaps)}")
            for key in ('fill', 'color'):
                if key in n and n[key] not in colours:
                    fail(where, f"{key} must be a brand color role: {', '.join(colours)}")
            if direction:
                mine = focal is not None and n.get('id') == focal
                if mine and (kind == 'text' and 'color' in n or kind == 'box'
                             and 'fill' in n):
                    fail(where, 'the focal node takes the focal color; remove its '
                         + ('fill' if kind == 'box' else 'color'))
                if n.get('color') == direction['focal'] \
                        or not mine and n.get('fill') == direction['focal']:
                    fail(where, only)
                if 'fill' in n and n['fill'] not in self.fills:
                    fail(where, f"fill {n['fill']} is not in the deck direction "
                         f"({', '.join(self.fills)})")
            if 'textRole' in n and n['textRole'] not in self.roles:
                fail(where, f"textRole must be one of {', '.join(self.roles)}")
            if kind == 'stack' and n.get('direction') not in ('row', 'column'):
                fail(where, 'stack needs direction row|column')
            if kind == 'grid' and not (type(n.get('columns')) is int
                                       and 1 <= n['columns'] <= 6):
                fail(where, 'grid needs 1–6 columns')
            if kind == 'text' and not _str(n.get('text')):
                fail(where, 'provide text')
            if kind == 'icon' and not (isinstance(n.get('icon'), str) and re.fullmatch(
                    r'[\w.-]{1,80}', n['icon'])):
                fail(where, 'icon needs a stable icon ID from the brand icon search')
            if kind == 'box':
                if 'text' in n and 'children' in n:
                    fail(where, 'a box holds text or children, not both')
                if 'text' in n and not _str(n['text']):
                    fail(where, 'provide box text')
                if n.get('shape', 'rect') not in SHAPES:
                    fail(where, f"shape must be one of {'|'.join(SHAPES)}")
                if 'style' in n and n['style'] not in ('solid', 'outline', 'bar'):
                    fail(where, 'style must be one of solid|outline|bar')
                facts['chevrons'] += n.get('shape') == 'chevron'
                if isinstance(kids, list):
                    # A heading and a body are a card, not a group.
                    inside = _compact(kids)
                    facts['members'] |= len(re.findall(
                        r'"type":"(?:box|icon)"', inside)) > 1 or len(re.findall(
                            r'"type":"(?:box|text|icon)"', inside)) > 2
                    facts['nested'] |= '"type":"box"' in inside
                fill = direction['focal'] if direction and n['id'] == focal else n.get(
                    'fill', direction['neutral'] if direction else 'canvasSecondary')
                if fill not in fills:
                    fills.append(fill)
            if kind in ('box', 'text'):
                leaves.add(n['id'])
                facts['metric'] |= n.get('textRole') == 'metric' and 'text' in n
            if kind in ('stack', 'grid', 'free') or 'children' in n:
                if not isinstance(kids, list) or not 1 <= len(kids) <= 12:
                    fail(where, 'provide 1–12 children')
            if kind in ('stack', 'grid', 'free'):
                # Like nodes side by side are a pair; in one column they are layers.
                kinds = [kid.get('type') if isinstance(kid, dict) else None for kid in kids]
                if sum(k in ('box', 'text', 'stack', 'grid') for k in kinds) > 1:
                    facts['peers'] |= sum(k in ('box', 'stack', 'grid') for k in kinds) > 1
                    if n.get('direction') == 'column' or n.get('columns') == 1:
                        facts['layers'] |= kinds.count('box') > 1
                    else:
                        facts['pair'] = True

        def walk(n, in_free):
            # One bad node does not hide the others: its children are still visited.
            attempt(inspect, n, in_free)
            if isinstance(n, dict) and isinstance(n.get('children'), list):
                for kid in n['children'][:12]:
                    walk(kid, n.get('type') == 'free')

        def edge(c):
            if not isinstance(c, dict) or any(
                    key not in ('id', 'from', 'to', 'label', 'arrow', 'color', 'route')
                    for key in c):
                fail(sid, 'unsupported edge field')
            self.claim(c.get('id'), f'{sid}/edge')
            where = f"{sid}/{c['id']}"
            if c.get('from') not in local or c.get('to') not in local \
                    or c['from'] == c['to']:
                fail(where, 'edges connect two distinct nodes on this slide')
            if 'label' in c and not _str(c['label']):
                fail(where, 'provide an edge label or omit it')
            if 'color' in c and c['color'] not in colours:
                fail(where, 'edge color must be a brand color role')
            if direction and c.get('color') == direction['focal']:
                fail(where, 'an edge cannot use the focal color; it belongs to the focal '
                     'node')

        before = len(found)
        walk(s.get('canvas'), False)
        connect = s.get('connect')
        facts['edges'] = len(connect) if isinstance(connect, list) else 0
        if len(found) == before:
            # These read the whole structure, so they mean something only once it is sound.
            if focal is not None and focal not in leaves:
                found.append(f'{sid}: brief.focal names {focal}, which is not a box or text '
                             'on this slide')
            relation = brief.get('relation') if isinstance(brief, dict) else None
            if relation in DRAWN and not DRAWN[relation][0](facts):
                found.append(f'{sid}: relation "{relation}" is not drawn. '
                             f'{DRAWN[relation][1]}, or set the relation to "none" if the '
                             'words are enough')
        if 'connect' in s and (not isinstance(connect, list) or len(connect) > 40):
            fail(sid, 'connect must be a list of at most 40 edges')
        for one in connect or []:
            attempt(edge, one)
        self.summary.append({'id': sid, 'nodes': facts['nodes'], 'fills': fills,
                             'edges': facts['edges']})

    # --- the fit ---

    def style(self, n: dict) -> dict:
        return self.roles[n.get('textRole') or self.body]

    def gap(self, n: dict) -> float:
        return self.gaps[n.get('gap') or 'normal']

    def row_widths(self, n: dict, width: float) -> list[float]:
        """In a row an icon or a rule takes its own width; the rest share what is left."""
        kids, gaps = n['children'], self.gap(n) * (len(n['children']) - 1)
        own = {'icon': self.icon, 'rule': self.inset / 2}

        def fixed(kid):
            return 0 if 'weight' in kid else own.get(kid['type'], 0)

        total = sum(kid.get('weight', 1) for kid in kids if not fixed(kid))
        usable = width - gaps - sum(map(fixed, kids))
        if not total or not usable > 0:
            every = sum(kid.get('weight', 1) for kid in kids)
            return [(width - gaps) * kid.get('weight', 1) / every for kid in kids]
        return [fixed(kid) or usable * kid.get('weight', 1) / total for kid in kids]

    def need(self, n: dict, width: float) -> float:
        """The least height a node can be given at this width."""
        if not width > 7.2:
            return math.inf
        kind, inset = n['type'], self.inset
        if kind == 'text':
            return _tall(n['text'], self.style(n), width)
        if kind in ('spacer', 'free'):
            return 0
        if kind in ('icon', 'rule'):
            return self.icon if kind == 'icon' else inset / 2
        if kind == 'box':
            # A rectangle pads its content; another shape confines it to an inner area.
            across, down = SHAPES[n.get('shape', 'rect')]
            pad = inset * 2 if across == down == 1 else 0
            inner = width - pad if pad else across * width
            if 'text' in n:
                return _tall(n['text'], self.style(n), inner) / down + pad \
                    if inner > 7.2 or pad else math.inf
            if n.get('children'):
                return self.need({**n, 'type': 'stack', 'direction': 'column'},
                                 max(1, inner)) / down + pad
            return 0   # an empty box is a drawn area, and can be as small as its share
        kids, gap = n['children'], self.gap(n)
        if kind == 'grid':
            rows = math.ceil(len(kids) / n['columns'])
            wide = (width - gap * (n['columns'] - 1)) / n['columns']
            return rows * max(self.need(kid, wide) for kid in kids) + gap * (rows - 1)
        if n['direction'] == 'row':
            return max(self.need(kid, wide)
                       for kid, wide in zip(kids, self.row_widths(n, width)))
        return sum(self.need(kid, width) for kid in kids) + gap * (len(kids) - 1)

    def title_fit(self, s: dict, into: list[str]) -> None:
        style, box = self.roles['title'], self.sl['titleBox']
        needs = _tall(s['title'], style, box['width'])
        if needs > box['height'] + .5:
            fit, (runs,) = _title_lines(self.contract, [s['title']])
            into.append(f"{s['id']}/title: needs {_tidy(needs)}pt of height but has "
                        f"{_tidy(box['height'])}pt: it runs to {runs} lines of "
                        f"{style['size']}pt and {fit} fit{'s' if fit == 1 else ''}; shorten "
                        'the title')

    def put(self, ident, kind, box: dict, **more) -> None:
        self.elements.append({'id': ident, 'type': kind,
                              **{key: _tidy(box[key]) for key in ('x', 'y', 'width',
                                                                  'height')}, **more})

    def words(self, ident, text, style: dict, box: dict, colour=None, **more) -> None:
        self.put(ident, 'text', box, text=text, fontSize=style['size'], bold=style['bold'],
                 color=colour or self.colours[style['colorRole']], **more)

    def draw(self, s: dict) -> None:
        """Lay one slide out: its elements, and every part of it that cannot fit."""
        sl, roles, inset, sid = self.sl, self.roles, self.inset, self.sid
        brief = s.get('brief') or {}
        self.focal = brief.get('focal')
        area = dict(sl['contentBox'])
        self.words(f'{sid}_title', s['title'], roles['title'], sl['titleBox'], role='title')
        if 'layout' in s:
            placeholders = []
            for key in ('subtitle', 'detail'):
                if key in s:
                    high = _tall(s[key], roles[self.body], area['width'])
                    self.words(f'{sid}_{key}', s[key], roles[self.body],
                               {**area, 'height': high})
                    placeholders.append(f'{sid}_{key}')
                    area['y'] += high + inset
            self.structure['layouts'].append({
                'slide': sid, 'layout': s['layout'], 'placeholders': placeholders,
                **({'pictures': [f'{sid}_picture']} if 'picture' in s else {})})
            self.structure['briefs'].append({'slide': sid,
                                             'rhythm': brief.get('rhythm', 'anchor')})
            return
        self.title_fit(s, self.tight)
        caption, gap = roles['caption'], inset / 2
        if 'subtitle' in s:
            high = _tall('Ag', roles['bodyReference'], 1e4)
            self.words(f'{sid}_subtitle', s['subtitle'], roles['bodyReference'],
                       {**area, 'height': high})
            area['y'] += high + gap
            area['height'] -= high + gap
        for key in ('source', 'caveat'):   # the source at the foot, the caveat above it
            if key in s:
                text = s[key] if isinstance(s[key], str) else ' '.join(
                    part for part in (s[key].get('label'), s[key]['text']) if part)
                high = _tall(text, caption, area['width'])
                area['height'] -= high
                self.words(f'{sid}_{key}', text, caption,
                           {**area, 'y': area['y'] + area['height'], 'height': high})
        if 'caveat' in s:
            area['height'] -= 4
            self.put(f'{sid}_caveat_rule', 'line',
                     {**area, 'y': area['y'] + area['height'] + 1, 'height': 1},
                     color=self.colours['inkDeep'], weight=1, arrow=False)
        if 'source' in s or 'caveat' in s:
            area['height'] -= gap
        if not area['height'] > inset * 2:
            self.tight.append(f'{sid}: the subtitle, caveat and source leave no room for '
                              'content; shorten or drop one')
            return
        self.place(s['canvas'], area)
        if self.tight:
            return
        if self.body == 'body' and not _str(s.get('notes')):
            self.structure['unspoken'].append(sid)
        used = self.need(s['canvas'], area['width'])
        if math.isfinite(used):
            self.room.append({'slide': sid, 'needs': _tidy(used),
                              'has': _tidy(area['height'])})
        shapes = [e for e in self.elements if e['type'] == 'shape']
        if brief.get('relation') == 'overlap' and not any(
                _crosses(a, b) for index, a in enumerate(shapes) for b in shapes[index + 1:]):
            raise _Said(f'{sid}: relation "overlap" is not drawn. Make two shapes intersect '
                        'in a free container, or set the relation to "none" if the words '
                        'are enough')
        if brief:
            self.structure['briefs'].append({
                'slide': sid, **{key: brief[key] for key in ('relation', 'focal')
                                 if brief.get(key)}, 'rhythm': brief.get('rhythm', 'dense')})
        for edge in s.get('connect') or []:
            self.join(edge)

    def short(self, n: dict, rect: dict, required: float) -> None:
        """Say that a node cannot fit, in the units its author can act on."""
        where = f"{self.sid}/{n.get('id') or n['type']}"
        if not math.isfinite(required):
            raise _Said(f'{where}: has no usable room; use fewer siblings, less nesting or '
                        'larger weights')
        lines = ''
        boxed = n['type'] == 'box' and 'text' in n \
            and SHAPES[n.get('shape', 'rect')] == (1, 1)
        if n['type'] == 'text' or boxed:
            style = self.style(n)
            line, pad = style['size'] * 1.25, 7.2 + (self.inset * 2 if boxed else 0)
            runs = max(1, math.floor((required - pad) / line + .5))
            fit = max(0, math.floor((rect['height'] - pad + .5) / line))
            lines = f": the text runs to {runs} line{'' if runs == 1 else 's'} of " \
                    f"{style['size']}pt and " \
                    + ('none fit' if fit == 0 else '1 fits' if fit == 1 else f'{fit} fit')
        self.tight.append(f'{where}: needs {_tidy(required)}pt of height but has '
                          f"{_tidy(rect['height'])}pt at {_tidy(rect['width'])}pt wide"
                          f'{lines}; shorten the text, split the slide or restructure')

    def place(self, n: dict, rect: dict) -> None:
        kind, sid, colours, inset = n['type'], self.sid, self.colours, self.inset
        where = f"{sid}/{n.get('id') or kind}"
        if kind == 'spacer':
            return
        if kind == 'icon' and rect['width'] < self.icon - .5:
            raise _Said(f'{where}: needs {_tidy(self.icon)}pt of width for an icon but has '
                        f"{_tidy(max(0, rect['width']))}pt")
        if kind != 'rule' and not (rect['width'] > inset and rect['height'] > 0):
            raise _Said(f'{where}: has no usable room; use fewer siblings, less nesting or '
                        'larger weights')
        # Leaves and columns own the fit check, so the line names the node to change.
        if 'children' not in n or kind == 'stack' and n['direction'] == 'column':
            required = self.need(n, rect['width'])
            if required > rect['height'] + .5:
                self.short(n, rect, required)
                return
        if n.get('id'):
            self.rects[n['id']] = rect
        direction = self.direction
        point = bool(direction) and n.get('id') == self.focal
        x, y, width, height = (rect[key] for key in ('x', 'y', 'width', 'height'))

        def at(left, top, wide, high) -> dict:
            return {'x': left, 'y': top, 'width': wide, 'height': high}

        if kind == 'text':
            self.words(n['id'], n['text'], self.style(n), rect,
                       colours[n['color']] if 'color' in n
                       else colours[direction['focal']] if point else None)
        elif kind == 'icon':
            # Icons are copied from the brand's library at render; the scene keeps a square.
            if not (self.sl.get('icon') or {}).get('library'):
                raise _Said(f'{where}: uses an icon, but the brand contract names no icon '
                            'library')
            side = min(width, height, self.icon * 2)
            slot = at(x + (width - side) / 2, y + (height - side) / 2, side, side)
            self.rects[n['id']] = slot
            self.structure['icons'].append({
                'slide': sid, 'id': n['id'], 'icon': n['icon'], 'order': len(self.elements),
                **{key: _tidy(value) for key, value in slot.items()}})
        elif kind == 'rule':
            across = width >= height
            self.put(n.get('id') or f'{sid}_rule{len(self.elements)}', 'line',
                     at(x, y + height / 2, width, 1) if across
                     else at(x + width / 2, y, 1, height), color=colours['inkDeep'],
                     weight=1, arrow=False)
        elif kind == 'box':
            first = len(self.elements)
            neutral = direction['neutral'] if direction else 'canvasSecondary'
            style = self.style(n)
            self.put(n['id'], 'shape', rect, shape=n.get('shape', 'rect'),
                     fill=colours[direction['focal'] if point else n.get('fill', neutral)],
                     **({'text': n['text'], 'fontSize': style['size'], 'bold': style['bold'],
                         'color': colours[n.get('color') or style['colorRole']]}
                        if 'text' in n else {}))
            if n.get('children'):
                across, down = SHAPES[n.get('shape', 'rect')]
                pad = inset if across == down == 1 else 0
                self.place({**n, 'type': 'stack', 'direction': 'column'},
                           at(x + (pad or width * (1 - across) / 2),
                              y + (pad or height * (1 - down) / 2),
                              width - pad * 2 if pad else width * across,
                              height - pad * 2 if pad else height * down))
                self.structure['groups'].append({
                    'slide': sid, 'id': f"{n['id']}_group",
                    'members': [e['id'] for e in self.elements[first:]]})
        elif kind == 'free':
            for kid in n['children']:
                spot = kid['at']
                self.place(kid, at(x + spot['x'] * width, y + spot['y'] * height,
                                   spot['width'] * width, spot['height'] * height))
        elif kind == 'grid':
            kids, gap, columns = n['children'], self.gap(n), n['columns']
            rows = math.ceil(len(kids) / columns)
            wide = (width - gap * (columns - 1)) / columns
            high = (height - gap * (rows - 1)) / rows
            for index, kid in enumerate(kids):
                self.place(kid, at(x + index % columns * (wide + gap),
                                   y + index // columns * (high + gap), wide, high))
        elif n['direction'] == 'row':
            for kid, wide in zip(n['children'], self.row_widths(n, width)):
                least = self.need(kid, wide)
                if least > height + .5:
                    self.short(kid, at(x, y, wide, height), least)
                else:
                    self.place(kid, at(x, y, wide, height))
                x += wide + self.gap(n)
        else:
            # Each part gets what its content needs, and the spare room goes by weight to
            # the parts that can use it.
            kids, gap = n['children'], self.gap(n)
            least = [self.need(kid, width) for kid in kids]
            share = [0 if kid['type'] in ('text', 'icon', 'rule') else kid.get('weight', 1)
                     for kid in kids]
            spare = max(0, height - gap * (len(kids) - 1) - sum(least))
            for kid, low, part in zip(kids, least, share):
                high = low + (spare * part / sum(share) if part else 0)
                self.place(kid, at(x, y, width, high))
                y += high + gap

    def join(self, edge: dict) -> None:
        """An edge, drawn across or down from one node to the other."""
        a, b = self.rects.get(edge['from']), self.rects.get(edge['to'])
        if a and b:
            ax, ay = a['x'] + a['width'] / 2, a['y'] + a['height'] / 2
            bx, by = b['x'] + b['width'] / 2, b['y'] + b['height'] / 2
            self.put(edge['id'], 'line', {'x': min(ax, bx), 'y': min(ay, by),
                                          'width': max(1, abs(bx - ax)),
                                          'height': max(1, abs(by - ay))},
                     color=self.colours['inkDeep'], weight=2, arrow=edge.get('arrow', True))
            if edge.get('label'):
                caption = self.roles['caption']
                self.words(f"{edge['id']}_label", edge['label'], caption,
                           {'x': (ax + bx) / 2, 'y': (ay + by) / 2,
                            'width': _wide(edge['label'], caption['size']) + 8.2,
                            'height': _tall(edge['label'], caption, 1e4)})
        self.structure['connectors'].append({
            'slide': self.sid, 'id': edge['id'], 'from': edge['from'], 'to': edge['to'],
            **({'label': f"{edge['id']}_label"} if edge.get('label') else {})})


def _tag(node) -> str:
    found = (node.get('id') or node.get('type')) if isinstance(node, dict) else None
    return str(found or 'undefined')


def _crosses(a: dict, b: dict) -> bool:
    """Two shapes that intersect without one simply sitting inside the other."""
    def inside(p, q):
        return p['x'] >= q['x'] and p['y'] >= q['y'] and p['x'] + p['width'] <= q['x'] \
            + q['width'] and p['y'] + p['height'] <= q['y'] + q['height']

    return a['x'] < b['x'] + b['width'] and b['x'] < a['x'] + a['width'] \
        and a['y'] < b['y'] + b['height'] and b['y'] < a['y'] + a['height'] \
        and not inside(a, b) and not inside(b, a)


def _colour(value) -> bytes:
    return bytes.fromhex(value[1:]) if _hex(value) else b'\x80\x80\x80'


def _drawn(slide: dict, scene: dict, wide: int = PICTURE) -> tuple[int, int, bytearray]:
    """A slide as pixels: each shape a block, each run of words and each line a bar."""
    canvas, theme = scene['canvas'], scene['theme']
    scale = wide / canvas['width']
    high = max(1, round(canvas['height'] * scale))
    pixels = bytearray(_colour(theme['background']) * (wide * high))

    def fill(x, y, width, height, colour):
        left, top = max(0, round(x * scale)), max(0, round(y * scale))
        right = min(wide, max(left + 1, round((x + width) * scale)))
        bottom = min(high, max(top + 1, round((y + height) * scale)))
        for row in range(top, bottom):
            pixels[(row * wide + left) * 3:(row * wide + right) * 3] = \
                _colour(colour) * max(0, right - left)

    for element in slide['elements']:
        x, y, width, height = (element[key] for key in ('x', 'y', 'width', 'height'))
        if element.get('fill'):
            fill(x, y, width, height, element['fill'])
        if element['type'] == 'line':
            fill(x, y, width, height, element['color'])
        elif element.get('text'):
            size = element.get('fontSize', theme['bodySize'])
            fill(x + 4, y + 4, min(width - 8, _wide(element['text'], size)), size * .5,
                 element.get('color', theme['text']))
    return wide, high, pixels


def _png(wide: int, high: int, pixels: bytearray) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack('>I', len(data)) + kind + data \
            + struct.pack('>I', zlib.crc32(kind + data))

    rows = b''.join(b'\x00' + bytes(pixels[row * wide * 3:(row + 1) * wide * 3])
                    for row in range(high))
    header = struct.pack('>IIBBBBB', wide, high, 8, 2, 0, 0, 0)   # eight bits, true colour
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) \
        + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')


def _sheet(pictures: list[tuple[int, int, bytearray]]) -> bytes:
    """Every slide at half size on one sheet, four to a row."""
    wide, high = pictures[0][0] // 2, pictures[0][1] // 2
    columns = min(4, len(pictures))
    rows = math.ceil(len(pictures) / columns)
    sheet = bytearray(b'\xff' * (wide * columns * high * rows * 3))
    for index, (full, _, pixels) in enumerate(pictures):
        left, top = index % columns * wide, index // columns * high
        for row in range(high):
            line = bytes(pixels[row * 2 * full * 3:(row * 2 + 1) * full * 3])
            start = ((top + row) * wide * columns + left) * 3
            sheet[start:start + wide * 3] = b''.join(line[pixel * 6:pixel * 6 + 3]
                                                     for pixel in range(wide))
    return _png(wide * columns, high * rows, sheet)


def sketch(slide: dict, prefix: str) -> dict:
    """One content slide of an outline, drawn plainly as a section's composer might: a box
    for each point, arranged so the slide's relation shows, every approved word kept. For
    tests. It fits when the words are few; the compiler says when they are not.

    `prefix` starts every node and edge ID, as a section's brief asks: 's1_' and so on.
    """
    points, relation = slide.get('points') or [], slide['relation']
    stem = prefix + re.sub(r'[^a-zA-Z0-9]', '', slide['id'])[:12]
    boxes = [{'type': 'box', 'id': f'{stem}_p{index}',
              'text': ': '.join(part for part in (point.get('label'), point.get('text'))
                                if part)} for index, point in enumerate(points, 1)]
    focal = next((box['id'] for box, point in zip(boxes, points)
                  if 'focal' in slide and point.get('label') == slide['focal']), None)
    connect = []
    if relation == 'quantity':
        # The first point's label is the figure; what it measures sits beside it.
        figure = {'type': 'text', 'id': f'{stem}_figure', 'text': points[0]['label'],
                  'textRole': 'metric'}
        said = [{**boxes[0], 'text': points[0]['text']}] if points[0].get('text') else []
        focal = figure['id'] if focal == boxes[0]['id'] else focal
        canvas = {'type': 'stack', 'direction': 'row',
                  'children': [figure, *said, *boxes[1:]]}
    elif relation == 'membership':
        canvas = {'type': 'box', 'id': f'{stem}_all', 'children': [
            {'type': 'grid', 'columns': min(3, len(boxes)), 'children': boxes}]}
    elif relation == 'overlap':
        canvas = {'type': 'free', 'children': [
            {**box, 'shape': 'ellipse',
             'at': {'x': index * .3, 'y': .05, 'width': .4, 'height': .9}}
            for index, box in enumerate(boxes[:3])]}
    elif relation in ('order', 'dependency', 'hierarchy'):
        canvas = {'type': 'stack', 'direction': 'column', 'gap': 'tight', 'children': boxes}
        connect = [{'id': f'{stem}_e{index}', 'from': first['id'], 'to': second['id']}
                   for index, (first, second) in enumerate(zip(boxes, boxes[1:]), 1)]
    else:
        canvas = {'type': 'grid', 'columns': min(3, len(boxes)) or 1,
                  'children': boxes or [{'type': 'spacer'}]}
    if 'focal' in slide and focal is None:
        # A point of its own, which is then shown on the slide too.
        focal = f'{stem}_point'
        canvas = {'type': 'stack', 'direction': 'column', 'gap': 'tight', 'children': [
            {'type': 'text', 'id': focal, 'text': slide['focal'], 'textRole': 'label'},
            {**canvas, 'weight': 3}]}
    brief = {'relation': relation, **({'focal': focal} if focal else {}),
             **({'rhythm': slide['rhythm']} if 'rhythm' in slide else {})}
    return {'id': slide['id'], 'title': slide['title'], 'sources': slide['sources'],
            'brief': brief, 'canvas': canvas, **({'connect': connect} if connect else {}),
            **{key: slide[key] for key in ('caveat', 'source', 'notes') if key in slide}}


class StandIn:
    """Behaves like the real command line for every call Slides makes, in Python.

    It keeps the tool's rules for an outline, splits a deck as the tool does, writes the
    same files in the same places, returns the same JSON and says no with the same lines.
    Where it is simpler than the real thing:

    - It draws stacks, grids, free containers, boxes, text, icons, rules and spacers, and
      calls any other node an unknown node type. It keeps the compiler's rules for those:
      IDs, fields, colours and the focal node, the relation that must be drawn, edges,
      template layouts and icons. It does not judge an arrow's label, a weight that content
      overrides, or ink on a fill.
    - Text is measured by the tool's own estimate, not with the brand's font, so a line
      holds a little less than it really does.
    - Its template is one invented set of layouts, and its two contracts are a few lines.
    - A slide's picture is 320 pixels wide and shows blocks and bars, not letters.
    - Its deck is an archive that starts as a PowerPoint file does and that no presentation
      program opens. The brand stand-in's audit reads it.

    `calls` lists the arguments of every call. `files` is what it keeps "in Drive", by ID.
    `at_once` is the most previews it ever had in progress together, and `pause` is how
    many seconds each takes. `drive` and `local` say whether Google access and LibreOffice
    are there. `fails` makes a command print a line and end with 1: before doing anything,
    except 'compose render', which fails after writing its file and leaves it there, as the
    first build of the tool at this version did.
    """

    def __init__(self):
        self.calls: list[list[str]] = []
        self.files: dict[str, dict] = {}
        self.fails: dict[str, str] = {}
        self.drive, self.local, self.pause, self.at_once = True, True, 0.0, 0
        self._busy, self._renders, self._guard = 0, 0, threading.Lock()

    def __call__(self, command: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
        args = [str(part) for part in command[2:]]
        self.calls.append(args)
        try:
            result = self._act(args)
        except (_Said, KeyError, TypeError, AttributeError, ValueError, OSError) as said:
            return 1, '', f'{said}\n'  # as the real one does: its lines, and exit code 1
        if isinstance(result, str):
            return 0, result + '\n', ''
        return 0, json.dumps(result, indent=2, ensure_ascii=False) + '\n', ''

    def read(self, runtime: Path, relative: Path) -> str | None:
        """A guidance file, as `read_guidance` gives one: a few invented lines for each
        guide, and for each relation but 'none' a slide of two points as `sketch` draws
        it."""
        relative = Path(relative)
        if relative.parent == GALLERY and relative.suffix == '.json' \
                and relative.stem in RELATIONS[:-1]:
            return json.dumps(sketch({**SHOWN, 'relation': relative.stem}, 'ex_'),
                              indent=2) + '\n'
        return GUIDANCE.get(relative.name) if relative.parent == REFERENCES else None

    def _act(self, args: list[str]):
        if args == ['--version']:
            return f'Harness Slides {MINIMUM}'
        name = ' '.join(args[:2])
        if name not in OPTIONS:
            raise _Said('Unknown command/action; run --help')
        options, rest = {}, args[2:]
        while rest:
            key = rest.pop(0).removeprefix('--')
            if key not in OPTIONS[name]:
                raise _Said(f'--{key} is not valid for this command')
            options[key] = rest.pop(0) if rest else None
        if name in self.fails and name != 'compose render':
            raise _Said(self.fails[name])
        return getattr(self, '_' + name.replace(' ', '_'))(options)

    # --- the brand ---

    @staticmethod
    def revision(contract: dict) -> str:
        """The hash a contract carries of everything else in it."""
        return _digest(_compact({key: value for key, value in contract.items()
                                 if key != 'revision'}).encode())

    @classmethod
    def contract(cls, path, medium: str | None = 'slides') -> dict:
        """A brand contract that is whole, unchanged, and whose sources are as they were."""
        if not path:
            raise _Said('Provide --brand brand-contract.json')
        contract = _load(path)
        try:
            kind, design = contract['medium']['kind'], contract['design']
            sound = contract['schema'] == 1 and _str(contract['identity']['id']) \
                and _str(contract['identity']['variant'])
        except (KeyError, TypeError):
            sound = False
        if not sound:
            raise _Said('Use resolved brand contract schema 1 with identity/variant')
        if kind not in ('slides', 'blog') or medium and kind != medium:
            raise _Said('Brand contract belongs to a different medium')
        sources, colours = contract.get('sources'), design.get('colors')
        if not isinstance(sources, list) or not sources or not all(
                isinstance(source, dict) and _str(source.get('path'))
                and re.fullmatch(r'[a-f0-9]{64}', str(source.get('sha256')))
                for source in sources):
            raise _Said('Brand authority needs hashed local sources')
        if not isinstance(colours, dict) or not all(map(_hex, colours.values())) \
                or not _str(design.get('fontFamily')):
            raise _Said('Brand design needs resolved colors and font family')
        for role in COLOURS:
            if role not in colours:
                raise _Said(f'Missing brand color role: {role}')
        if kind == 'slides':
            sl = design.get('slides') or {}
            if not all(isinstance(sl.get(key), dict)
                       for key in ('canvas', 'titleBox', 'contentBox', 'typography')):
                raise _Said('Slide brand contract needs canvas, safe boxes and typography')
            for role in ROLES:
                style = sl['typography'].get(role) or {}
                if not _number(style.get('size')) or type(style.get('bold')) is not bool \
                        or style.get('colorRole') not in colours:
                    raise _Said(f'Invalid brand typography: {role}')
        if contract.get('revision') != cls.revision(contract):
            raise _Said('Brand contract changed; resolve a fresh handoff')
        for source in sources:
            try:
                same = _digest(Path(source['path']).read_bytes()) == source['sha256']
            except OSError:
                same = False
            if not same:
                raise _Said(f"Brand authority changed ({source.get('kind', 'source')}); "
                            'resolve a fresh contract')
        return contract

    @staticmethod
    def _layouts(contract: dict) -> list[dict]:
        if not contract['design'].get('nativeTemplate'):
            raise _Said('This brand contract has no native template, so there are no '
                        'template layouts to choose')
        return [{'name': name, 'title': title, 'subtitles': subtitles, 'pictures': pictures,
                 'canvas': name == DEFAULT} for name, title, subtitles, pictures in LAYOUTS]

    # --- the outline ---

    def _outline_contract(self, options: dict) -> str:
        contract = self.contract(options.get('brand'))
        delivery = contract['medium'].get('delivery', 'reading')
        sl = contract['design']['slides']
        size, (fit, _) = sl['typography']['title']['size'], _title_lines(contract, [])
        return ('Outline v1 (AI-owned; words and decisions, no layout).\n'
                '{version:1,title,audience?,delivery?:live|reading,minutes?,direction?,'
                'layouts?:{cover?,section?,closing?},material?,house?,approval?,'
                'slides:[SLIDE]}\n'
                'SLIDE cover: {id,kind:cover,title,subtitle?,detail?,notes?}. section: '
                '{id,kind:section,title,subtitle?,notes?}. closing: '
                '{id,kind:closing,title,notes?}.\n'
                'SLIDE content: {id,kind:content,title,understand,relation,focal?,rhythm?,'
                'points:[{label?,text?}],caveat?,source?,notes?,sources:[one or more IDs]}.'
                f"\nrelation: {'|'.join(RELATIONS)}.\n"
                f"For {contract['identity']['id']}: a title holds {fit} line"
                f"{'' if fit == 1 else 's'} at {size}pt, about "
                f"{math.floor(sl['titleBox']['width'] / (size * .52)) * fit} characters. A "
                f"slide delivered {'live' if delivery == 'live' else 'for reading'} carries "
                f'about {BUDGETS[delivery]} body words.')

    def _outline(self, options: dict) -> tuple[bytes, dict, dict, dict]:
        if not options.get('file'):
            raise _Said('Provide --file outline.json')
        data, contract = _read(options['file']), self.contract(options.get('brand'))
        outline = _load(options['file'])
        return data, outline, contract, _checked(outline, contract)

    def _outline_check(self, options: dict) -> dict:
        data, outline, _, checked = self._outline(options)
        return {'status': 'sound; look at the findings' if checked['findings'] else 'sound',
                'slides': len(outline['slides']), 'delivery': checked['delivery'],
                'wordBudget': checked['budget'], 'words': checked['counts'],
                'findings': checked['findings'], 'outlineSha256': _digest(data)}

    def _outline_start(self, options: dict) -> dict:
        if not options.get('output'):
            raise _Said('Provide a new --output directory for the build')
        if not options.get('brand'):
            raise _Said('Provide --brand brand-contract.json; the build needs the brand')
        data, outline, _, checked = self._outline(options)
        slides, named = outline['slides'], outline.get('layouts') or {}
        # What a draft may leave open, a build may not.
        blocking = [f"{finding['slide']}: {finding['detail']}"
                    for finding in checked['findings'] if finding['code'] == 'title-too-long']
        for kind in dict.fromkeys(s['kind'] for s in slides if s['kind'] != 'content'):
            if not named.get(kind):
                blocking.append(f'outline: name the template layout for {kind} slides in '
                                f'layouts.{kind} (run compose layouts)')
        if not outline.get('direction'):
            blocking.append('outline: the build needs a direction; add one')
        if blocking:
            raise _said(blocking)
        output = _folder(Path(options['output']).resolve())
        _folder(output / 'briefs')
        title, direction = outline['title'], _compact(outline['direction'])
        said = 'live' if checked['delivery'] == 'live' else 'for reading'
        house = ''.join(f'\n- {line}' for line in outline.get('house') or []) \
            or '\nNone given beyond the direction.'
        parts, table, briefs = [], [], []

        def composition(held: list[dict]) -> str:
            return _pretty({'version': 1, 'title': title, 'direction': outline['direction'],
                            'slides': held})

        def beside(slide) -> str:
            if slide is None:
                return 'nothing'
            return f'the slide "{slide["title"]}", built by another worker' \
                if slide['kind'] == 'content' else f"a {slide['kind']} slide"

        def lead(held: list[dict]) -> None:
            name = f"lead-{sum(part.startswith('lead-') for part in parts) + 1}.json"
            _write(output / name, composition([
                {'id': s['id'], 'title': s['title'], 'layout': named[s['kind']],
                 **{key: s[key] for key in ('subtitle', 'detail', 'notes') if s.get(key)},
                 'sources': [LEAD], 'brief': {'rhythm': 'anchor'}} for s in held]))
            parts.append(name)
            table.append(f"| Lead | {name} | {', '.join(s['id'] for s in held)} |")

        def sections(run: list[dict], before, after) -> None:
            # Three or four neighbouring content slides: the unit one builder takes.
            count = math.ceil(len(run) / 4)
            size = math.ceil(len(run) / count)
            groups = [run[index * size:(index + 1) * size] for index in range(count)]
            for index, group in enumerate(groups):
                number = len(briefs) + 1
                name = f'section-{number}.json'
                brief = output / 'briefs' / f'section-{number}.md'
                _write(brief, BRIEF.format(
                    number=number, title=title, said=said, name=name, output=output,
                    audience=f", for {outline['audience']}" if outline.get('audience')
                    else '', runtime='stand-in', brand=Path(options['brand']).resolve(),
                    material='\n'.join(f'- Source material: {line}'
                                       for line in outline.get('material') or []),
                    direction=direction, house=house,
                    slides='\n'.join(self._asked(position, slide)
                                     for position, slide in enumerate(group, 1)),
                    before=beside(groups[index - 1][-1] if index else before),
                    after=beside(groups[index + 1][0] if index < len(groups) - 1
                                 else after)))
                parts.append(name)
                briefs.append(str(brief))
                table.append(f"| Worker {number} | {name} | "
                             f"{', '.join(s['id'] for s in group)} |")

        held, run, before = [], [], None
        for slide in slides:
            if slide['kind'] == 'content':
                if held:
                    lead(held)
                    before, held = held[-1], []
                run.append(slide)
            else:
                if run:
                    sections(run, before, slide)
                    run = []
                held.append(slide)
        if run:
            sections(run, before, None)
        if held:
            lead(held)
        _write(output / 'parts.json', _pretty({'title': title,
                                               'direction': outline['direction'],
                                               'parts': parts}))
        _write(output / 'outline.json', data)
        _write(output / 'presentation-brief.md', PRESENTATION.format(
            title=title, said=said, count=len(slides), digest=_digest(data),
            audience=f"For {outline['audience']}. " if outline.get('audience') else '',
            approval='\n>\n'.join(f'> {line}' for line in outline.get('approval') or [])
            or 'Record here what the user said when they approved the draft, in their '
               'words.', direction=direction, house=house, table='\n'.join(table)))
        return {'output': str(output), 'slides': len(slides), 'parts': parts,
                'sections': len(briefs), 'briefs': briefs, 'outlineSha256': _digest(data),
                'next': 'Hand each brief to a worker, or build the sections yourself in '
                        'order; then compose merge --file parts.json' if len(briefs) > 1
                else 'Build the section, then compose merge --file parts.json'}

    @staticmethod
    def _asked(position: int, s: dict) -> str:
        """What a brief asks of one slide."""
        rhythm = f", rhythm `{s['rhythm']}`" if s.get('rhythm') else ''
        point = f"The point of the slide: {s['focal']}." if s.get('focal') \
            else 'No focal point: it compares equals.'
        points = '\n'.join('   - ' + ': '.join(part for part in (p.get('label'),
                                                                 p.get('text')) if part)
                           for p in s.get('points') or [])
        extra = ''.join(f'\n   - {label}{s[key]}{end}' for key, label, end in (
            ('caveat', 'Caveat, to set on the slide as `caveat`: "', '"'),
            ('source', 'Source line, to set on the slide as `source`: "', '"'),
            ('notes', "Speaker notes, to go in the slide's `notes`: ", '')) if s.get(key))
        return (f'\n{position}. **`{s["id"]}`: "{s["title"]}"**\n'
                f"   - The audience must understand: {s['understand']}\n"
                f"   - Relation `{s['relation']}`{rhythm}. {point}\n{points}{extra}\n"
                f"   - Sources: {_compact(s['sources'])}")

    # --- the composition ---

    def _compose_contract(self, options: dict) -> str:
        contract = self.contract(options.get('brand'))
        compiler = _Compiler(contract)
        box, delivery = compiler.sl['contentBox'], contract['medium'].get('delivery')
        lines = ', '.join(f"{role} {_tidy(_tall('Ag', style, 400))}"
                          for role, style in compiler.roles.items() if role != 'title')
        return ('Composition v1 (AI-owned; describe structure, never coordinates).\n'
                '{version:1,title,direction?:DIRECTION,slides:[{id,title,sources,canvas:NODE,'
                'connect?:[EDGE],brief?:BRIEF,subtitle?,caveat?,source?,notes?} | '
                '{id,title,sources,layout:TEMPLATE LAYOUT NAME,subtitle?,detail?,notes?}]}\n'
                f"NODE types: {'|'.join(NODES)}. EDGE: {{id,from,to,label?,arrow?}}.\n"
                f"BRIEF: {{relation:{'|'.join(RELATIONS)},focal?:NODE id,rhythm?:"
                f"{'|'.join(RHYTHMS)}}}.\n"
                f"Sizes for {contract['identity']['id']}, in points.\n"
                f"Content area {_tidy(box['width'])} wide by {_tidy(box['height'])} high. "
                f"Gaps: tight {_tidy(compiler.gaps['tight'])}, normal "
                f"{_tidy(compiler.gaps['normal'])}, wide {_tidy(compiler.gaps['wide'])}. A "
                f'box pads its content by {compiler.inset} on each side. An icon is '
                f'{compiler.icon} square.\n'
                f'One line of text needs: {lines}. Text with no textRole uses '
                f'{compiler.body}, the size for a deck delivered '
                f"{'live' if delivery == 'live' else 'for reading'}.")

    def _compose_layouts(self, options: dict) -> dict:
        return {'default': DEFAULT,
                'layouts': self._layouts(self.contract(options.get('brand'))),
                'use': 'A slide on the default layout has a canvas. A slide that names '
                       'another layout fills its title and up to that many subtitle lines, '
                       'and has no canvas. A layout with title: false shows no title.'}

    def _compose_compile(self, options: dict) -> dict:
        if not options.get('file'):
            raise _Said('Provide --file composition.json, and a new --output directory to '
                        'write the build')
        data, contract = _read(options['file']), self.contract(options.get('brand'))
        comp, compiler, compiled = _load(options['file']), _Compiler(contract), None
        try:
            compiled = compiler.run(comp)
        except _Said as said:
            compiler.problems.append(str(said))
        # Unknown icons and layouts are caught now, not when the deck is rendered.
        problems = compiler.problems + self._asks(comp, contract)
        if problems:
            raise _said(problems)
        scene, structure = compiled
        report = {'schema': 1, 'brandRevision': contract['revision'],
                  'measurement': 'estimated; brand font unavailable',
                  'slides': compiler.summary, 'room': compiler.room}
        summary = {'slides': len(scene['slides']), 'brandRevision': contract['revision'],
                   'measurement': report['measurement'], 'groups': len(structure['groups']),
                   'connectors': len(structure['connectors']),
                   'icons': len(structure['icons']),
                   'room': {r['slide']: f"{r['needs']} of {r['has']}"
                            for r in compiler.room}}
        if not options.get('output'):
            return {'status': 'fits; nothing written. Add a new --output directory to '
                              'write the build', **summary}
        report['inputs'] = {
            'composition': {'path': str(Path(options['file']).resolve()),
                            'sha256': _digest(data)},
            'brand': {'path': str(Path(options['brand']).resolve()),
                      'sha256': _digest(_read(options['brand']))}, 'assets': []}
        report['sceneDigest'] = _digest(_compact(scene).encode())
        report['structureDigest'] = _digest(_compact(structure).encode())
        output = _folder(Path(options['output']).resolve())
        for name, value in (('scene.json', scene), ('structure.json', structure),
                            ('compose-report.json', report),
                            ('brand-contract.json', contract)):
            _write(output / name, _pretty(value))
        return {'output': str(output), 'sceneDigest': report['sceneDigest'], **summary}

    def _asks(self, comp, contract: dict) -> list[str]:
        """What is wrong with the icons and the template layouts a composition asks for,
        read straight from the file so that it is said even when a slide does not compile."""
        wrong, icons = [], []

        def walk(node):
            if isinstance(node, dict):
                if node.get('type') == 'icon' and isinstance(node.get('id'), str):
                    icons.append(node)
                for kid in node.get('children') or []:
                    walk(kid)

        slides = [s for s in (comp.get('slides') if isinstance(comp, dict) else None) or []
                  if isinstance(s, dict)]
        for s in slides:
            walk(s.get('canvas'))
        if icons:
            library = (contract['design']['slides'].get('icon') or {}).get('library') or {}
            hashed = [source['path'] for source in contract['sources']]
            if library.get('path') not in hashed or library.get('index') not in hashed:
                return ['This composition uses icons, but the brand contract names no '
                        'hashed icon library and index']
            known = {entry['id']: entry for entry in _load(library['index'])['entries']}
            for icon in icons:
                if icon.get('icon') not in known:
                    wrong.append(f"{icon['id']}: unknown icon {icon.get('icon')}; search "
                                 'the brand icon library for a current ID')
                elif not known[icon['icon']].get('native'):
                    wrong.append(f"{icon['id']}: icon {icon['icon']} is a picture, not "
                                 'native geometry; choose another')
        named = [s for s in slides if 'layout' in s]
        if named and not contract['design'].get('nativeTemplate'):
            return wrong + ['This composition uses template layouts, which need a brand '
                            'with a native template']
        layouts = {layout['name']: layout for layout in self._layouts(contract)} \
            if named else {}
        for s in named:
            match = layouts.get(' '.join(str(s['layout']).split()))
            if match is None:
                wrong.append(f"{s.get('id')}: the template has no layout named "
                             f"{s['layout']}. Available: {', '.join(layouts)}")
            elif sum(key in s for key in ('subtitle', 'detail')) > match['subtitles']:
                wrong.append(f"{s.get('id')}: layout {match['name']} has "
                             f"{match['subtitles']} subtitle placeholders; remove the extra "
                             'text')
            elif 'picture' in s and not match['pictures']:
                wrong.append(f"{s.get('id')}: layout {match['name']} has no picture slot; "
                             'remove the picture or choose a layout listed with pictures: 1')
        return wrong

    def _compose_merge(self, options: dict) -> dict:
        if not options.get('file') or not options.get('output'):
            raise _Said('Provide --file parts.json and a new --output composition.json')
        manifest, base = _load(options['file']), Path(options['file']).resolve().parent
        if not isinstance(manifest, dict) or any(
                key not in ('title', 'direction', 'parts') for key in manifest):
            raise _Said('parts.json takes title, direction and parts')
        if not _str(manifest.get('title')):
            raise _Said('parts.json needs the deck title')
        parts = manifest.get('parts')
        if not isinstance(parts, list) or not 1 <= len(parts) <= 40 \
                or not all(map(_str, parts)):
            raise _Said('parts.json lists 1–40 section files in deck order')
        slides, owner, problems, counts = [], {}, [], []

        def ids(node):
            if isinstance(node, dict):
                if isinstance(node.get('id'), str):
                    yield node['id']
                for kid in [*(node.get('children') or []), node.get('canvas'),
                            *(node.get('connect') or [])]:
                    yield from ids(kid)

        for name in parts:
            try:
                part = json.loads((base / name).read_text(encoding='utf-8'))
            except OSError:
                problems.append(f'{name}: cannot be read as JSON (ENOENT)')
                continue
            except ValueError as wrong:
                problems.append(f'{name}: cannot be read as JSON ({wrong})')
                continue
            if not isinstance(part, dict) or part.get('version') != 1 \
                    or not isinstance(part.get('slides'), list) or not part['slides']:
                problems.append(f'{name}: is not a composition with slides')
                continue
            if json.dumps(part.get('direction'), sort_keys=True) != json.dumps(
                    manifest.get('direction'), sort_keys=True):
                problems.append(f"{name}: its direction differs from the deck's; copy the "
                                'deck direction unchanged')
            for ident in (ident for s in part['slides'] for ident in ids(s)):
                if owner.setdefault(ident, name) != name:
                    problems.append(f'{name}: ID {ident} is already used in '
                                    f'{owner[ident]}; give each section its own ID prefix')
            slides += part['slides']
            counts.append({'part': name, 'slides': len(part['slides'])})
        if len(slides) > 100:
            problems.append(f'the parts hold {len(slides)} slides; a deck has at most 100')
        if problems:
            raise _said(problems)
        output = Path(options['output']).resolve()
        _write(output, _pretty({
            'version': 1, 'title': manifest['title'],
            **({'direction': manifest['direction']} if 'direction' in manifest else {}),
            'slides': slides}))
        return {'output': str(output), 'slides': len(slides), 'parts': counts,
                'next': 'compile and preview the whole deck; consistency across sections '
                        'is judged there'}

    def _compiled(self, folder) -> tuple[dict, dict]:
        """A folder compile wrote. Its brand must still be as it was when it was written."""
        folder = Path(folder).resolve()
        scene, structure = _load(folder / 'scene.json'), _load(folder / 'structure.json')
        self.contract(folder / 'brand-contract.json')
        return scene, structure

    def _deck(self, path: Path, scene: dict) -> str:
        """Write the deck: an archive with a part for each slide. Returns its hash."""
        with self._guard:
            self._renders += 1
            stamp = time.gmtime(1767225600 + self._renders * 2)[:6]   # no two alike
        try:
            with zipfile.ZipFile(path, 'x') as deck:
                def part(name: str, text: str) -> None:
                    deck.writestr(zipfile.ZipInfo(name, stamp), text)

                part('[Content_Types].xml', '<Types/>')
                part('ppt/presentation.xml', '<p:presentation><p:title>'
                     f"{escape(scene['title'])}</p:title></p:presentation>")
                for number, slide in enumerate(scene['slides'], 1):
                    runs = ''.join(
                        f"<a:r><a:rPr sz=\"{round(e.get('fontSize', 18) * 100)}\"/><a:t>"
                        f"{escape(e['text'])}</a:t></a:r>" for e in slide['elements']
                        if e.get('text'))
                    part(f'ppt/slides/slide{number}.xml', f'<p:sld>{runs}</p:sld>')
        except FileExistsError:
            raise _Said(f"EEXIST: file already exists, open '{path}'")
        return _digest(path.read_bytes())

    def _compose_render(self, options: dict) -> dict:
        if not options.get('file') or not options.get('output'):
            raise _Said('Provide --file COMPILED_DIR and a new --output deck.pptx')
        scene, _ = self._compiled(options['file'])
        output = Path(options['output']).resolve()
        if output.exists():
            raise _Said(f'{output} already exists; choose a new output file')
        digest = self._deck(output, scene)
        if 'compose render' in self.fails:
            raise _Said(self.fails['compose render'])   # and the file stays, as it did
        return {'output': str(output), 'slides': len(scene['slides']), 'sha256': digest,
                'editable': True, 'status': 'unreviewed draft', 'emitter': 'native template'}

    def _compose_preview(self, options: dict) -> dict:
        if not options.get('file') or not options.get('output'):
            raise _Said('Provide --file COMPILED_DIR and a new --output directory')
        renderer = options.get('renderer') or 'google'
        if renderer not in ('google', 'local'):
            raise _Said('Renderer must be google or local')
        scene, structure = self._compiled(options['file'])
        ids = [slide['id'] for slide in scene['slides']]
        wanted = options.get('slide')
        if wanted is not None and wanted not in ids:
            raise _Said(f"No slide {wanted}; choose one of {', '.join(ids)}")
        output = _folder(Path(options['output']).resolve())
        with self._guard:
            self._busy += 1
            self.at_once = max(self.at_once, self._busy)
        try:
            time.sleep(self.pause)
            return self._previewed(output, scene, structure, renderer, wanted,
                                   options.get('file-id'))
        except BaseException:
            shutil.rmtree(output, ignore_errors=True)   # the tool clears up after itself
            raise
        finally:
            with self._guard:
                self._busy -= 1

    def _previewed(self, output: Path, scene: dict, structure: dict, renderer: str,
                   wanted: str | None, file_id: str | None) -> dict:
        deck = output / 'deck.pptx'
        digest, remote = self._deck(deck, scene), {}
        if renderer == 'local' and not self.local:
            raise _Said('LibreOffice (soffice) is not installed. Use --renderer google, or '
                        'install LibreOffice for offline previews.')
        if renderer == 'google':
            if not self.drive:
                raise _Said(NO_DRIVE.format(403))
            with self._guard:
                if file_id is None:
                    file_id = f'stand-in-preview-{len(self.files) + 1}'
                    self.files[file_id] = {'name': f"Preview: {scene['title']}",
                                           'uploads': 0}
                kept = self.files.get(file_id)
                if kept is None:
                    raise _Said(NO_DRIVE.format(404))
                if not kept['name'].startswith('Preview: '):
                    raise _Said('Refusing to overwrite a Drive file that is not a '
                                '"Preview: …" Google Slides deck. Omit --file-id to create '
                                'a new preview file.')
                kept.update(uploads=kept['uploads'] + 1, deckSha256=digest)
            remote = {'fileId': file_id, 'url': self._url(file_id)}
        (output / 'deck.pdf').write_bytes(b'%PDF-1.4\n% a stand-in for the render\n')
        templated = {entry['slide'] for entry in structure.get('layouts') or []}
        slides, pictures = [], []
        for number, slide in enumerate(scene['slides'], 1):
            pictures.append(_drawn(slide, scene))
            if wanted not in (None, slide['id']):
                continue
            # Screens that need no render: prompts to look, not approval.
            findings, words = [], _words(' '.join(e.get('text', '')
                                                  for e in slide['elements']))
            if slide['id'] not in templated and words > 90:
                findings.append({'severity': 'warn', 'code': 'density', 'detail':
                                 f'{words} visible text words; inspect reading effort'})
            if slide['id'] not in templated and all(e['type'] == 'text'
                                                    for e in slide['elements']):
                findings.append({'severity': 'warn', 'code': 'text-only', 'detail':
                                 'Consider a visual relationship or evidence when it '
                                 'serves the message'})
            image = output / f'slide-{number:02d}.png'
            image.write_bytes(_png(*pictures[-1]))
            slides.append({'id': slide['id'], 'number': number, 'title': slide['title'],
                           'image': str(image), 'findings': findings})
        review = {}
        if wanted is None:
            # A render of the whole deck also gets one sheet and a reviewer's packet.
            review = {'contactSheet': str(output / 'contact-sheet.png'),
                      'critic': str(output / 'critic.json')}
            (output / 'contact-sheet.png').write_bytes(_sheet(pictures))
            briefs = {brief['slide']: brief for brief in structure.get('briefs') or []}
            _write(output / 'critic.json', _pretty({
                'schema': 1, 'deckSha256': digest, 'contactSheet': review['contactSheet'],
                'questions': list(QUESTIONS), 'grades': GRADES,
                'slides': [{'number': s['number'], 'id': s['id'], 'title': s['title'],
                            'image': s['image'],
                            **({'relation': briefs[s['id']]['relation']}
                               if briefs.get(s['id'], {}).get('relation') else {}),
                            'rhythm': briefs.get(s['id'], {}).get('rhythm', 'dense')}
                           for s in slides]}))
        result = {'schema': 1, 'output': str(output), 'deck': str(deck),
                  'deckSha256': digest, **review,
                  'renderer': 'Google Slides PDF export' if remote else 'LibreOffice',
                  'emitter': 'native template', **remote, 'slides': slides,
                  'status': 'rendered and screened; open each image and judge it. Screens '
                            'are prompts to look, not approval.',
                  **({'next': 'Reuse this Drive file for the next preview: --file-id '
                              f'{file_id}'} if remote else {})}
        _write(output / 'preview.json', _pretty(result))
        return result

    def _compose_critique(self, options: dict) -> dict:
        if not options.get('file') or not options.get('assessment'):
            raise _Said('Provide --file PREVIEW_DIR and --assessment critique.json')
        folder = Path(options['file']).resolve()
        try:
            packet = json.loads((folder / 'critic.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise _Said('No critic packet here; run compose preview on the whole deck, '
                        'without --slide')
        given, ids = _load(options['assessment']), {s['id'] for s in packet['slides']}
        if not isinstance(given, dict) or any(
                key not in ('deckSha256', 'reviewer', 'findings', 'weakest')
                for key in given):
            raise _Said('A critique takes deckSha256, reviewer, findings and weakest')
        problems, findings = [], given.get('findings')
        if given.get('deckSha256') != packet['deckSha256']:
            problems.append('deckSha256 is not the deck this packet describes; critique the '
                            'latest render')
        if given.get('reviewer') not in ('independent', 'author'):
            problems.append('reviewer is independent (did not write the slides) or author')
        if not isinstance(findings, list):
            problems.append('findings is a list; use an empty list when there are none')
            findings = []
        for number, finding in enumerate(findings, 1):
            where = f'finding {number}'
            if not isinstance(finding, dict) or any(
                    key not in ('slide', 'question', 'severity', 'note', 'fix')
                    for key in finding):
                problems.append(f'{where}: takes slide, question, severity, note and fix')
                continue
            if finding.get('slide') not in ids:
                problems.append(f"{where}: no slide {finding.get('slide')} in this deck")
            question = finding.get('question')
            if type(question) is not int or not 1 <= question <= len(QUESTIONS):
                problems.append(f'{where}: question is 1 to {len(QUESTIONS)}')
            if finding.get('severity') not in GRADES:
                problems.append(f'{where}: severity is critical, major or minor')
            note = finding.get('note')
            if not isinstance(note, str) or len(note.strip()) < 12:
                problems.append(f'{where}: note says what is wrong on this slide, in a '
                                'sentence')
            if 'fix' in finding and not _str(finding['fix']):
                problems.append(f'{where}: fix is a sentence, or omitted')
        weakest = given.get('weakest', [])
        if not isinstance(weakest, list) or len(weakest) > 3 \
                or any(ident not in ids for ident in weakest):
            problems.append('weakest names up to three slides of this deck')
        if problems:
            raise _said(problems)
        counts = {level: sum(f['severity'] == level for f in findings) for level in GRADES}
        status = 'blocked' if counts['critical'] else 'clear'
        try:
            _write(folder / 'critique.json', _pretty({
                'schema': 1, 'deckSha256': packet['deckSha256'],
                'reviewer': given['reviewer'],
                'recordedAt': time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime()),
                'findings': findings, 'weakest': weakest, **counts, 'status': status}))
        except _Said:
            raise _Said('This render already has a critique; fix the slides, preview again '
                        'and critique the new render')
        return {'critique': str(folder / 'critique.json'), 'reviewer': given['reviewer'],
                **counts, 'status': status,
                'next': 'Do not deliver. Fix each critical finding, preview the deck again '
                        'and have the new render critiqued.' if counts['critical']
                else 'Fix the major findings in one pass, then preview again. Undo any fix '
                     'that causes a new finding.' if counts['major']
                else 'Clear to show the user.'}

    # --- Google Drive ---

    @staticmethod
    def _url(file_id: str) -> str:
        return f'https://docs.google.com/presentation/d/{file_id}/edit'

    def _drive_check(self, options: dict) -> dict:
        if not self.drive:
            raise _Said(NO_DRIVE.format(403))
        return {'account': 'person@example.com', 'pptxImportAdvertised': True}

    def _drive_import(self, options: dict) -> dict:
        path = options.get('file') or ''
        if not path.lower().endswith('.pptx'):
            raise _Said('Input must be a .pptx path.')
        data = _read(path)
        if data[:4] != b'PK\x03\x04':
            raise _Said('Input is not a PPTX ZIP.')
        name = options.get('name') or Path(path).name[:-5]
        if not name.strip():
            raise _Said('Presentation name must not be empty.')
        if not self.drive:
            raise _Said(NO_DRIVE.format(403) + ' Inspect Drive before retrying; an '
                        'uncertain upload can create a duplicate.')
        with self._guard:
            file_id = f'stand-in-deck-{len(self.files) + 1}'
            self.files[file_id] = {'name': name, 'uploads': 1, 'deckSha256': _digest(data)}
        return {'id': file_id, 'name': name, 'url': self._url(file_id)}
