"""What a slide deck is made from: the runner's own rules, and what its workers are told.

What a caller needs to know
---------------------------
    deck.handoff(title, level, blueprint, said, settings, ...)   # deck-handoff.md, as text
    deck.rules(outline, blueprint, budget)      # what the runner refuses in an outline
    deck.shown(outline)                         # an outline as its slides, for a person
    whole = deck.complete(outline, listed, words)   # with direction, layouts, house rules
    deck.lead(part)                             # a cover, section or closing slide, put right
    deck.brief(written, whole, previews)        # a section's brief, for a worker with tools
    spec = deck.fixed(whole, ids, number)       # what a section's composer may not change
    deck.kept(section, spec)                    # what the runner refuses in a section
    deck.checked(finding, slides)               # one finding of a review, or why it is wrong
    deck.to_repair(findings, sections)          # the sections a review sends back
    deck.before(slides)                         # what a deck of this size has cost before

- Nothing here starts anything, reads a training or knows about runs. Each function takes
  text or parsed JSON and gives back text, parsed JSON or a list of sentences.
- An outline is the slides tool's own format: what each slide says, and nothing about how
  it is drawn. The tool checks its shape. `rules` adds the four things the runner holds an
  outline to: every content slide names the blueprint objectives it serves and every
  objective is served; no slide shows more words than the budget, counting its title,
  points, caveat and source together; a cover carries a title and one subtitle line; and
  nothing the blueprint lists under its open gaps is on a slide in the blueprint's words.
- HOUSE is what the composers are told that no program can check. It goes into the outline
  as its house rules and into each section's brief.
- `brief` rewrites the brief the slides tool writes for one section. That brief is written
  for a worker at a shell, with paths to read and a folder to write in. A worker here has
  tools and no files, so those parts are replaced and everything else is kept as written.
- A section keeps every approved word: `kept` holds its title, objectives, caveat, source
  line and notes to the outline's, and looks for each point's words among the text the
  slide draws. What is drawn, and how, is the composer's.
- A finding is about `drawing` or about `content`. Only a major or critical finding about
  drawing sends a section back to its composer. One about what a slide says is the
  person's to settle, at the outline.
- QUESTIONS are the eight the slides tool asks of every slide, numbered as it numbers
  them, in the runner's words. The tool's own are not handed to a caller, so a change to
  them there has to be made here too.
"""
from __future__ import annotations

import json
import re

import runner  # noqa: F401  puts the core on the import path
import checks
from workspace import WorkspaceError

PREVIEWS = 4            # times one composer may render its section
REPAIRS = 2             # rounds of drawing again after a review
DELIVERY = 'reading'    # a deck is read alone as well as presented
DIRECTION = {'focal': 'headingPrimary', 'neutral': 'canvasSecondary'}
RATE = {'dollars': 0.40, 'minutes': 1.25}   # a slide, as the first decks cost
KINDS = ('cover', 'section', 'content', 'closing')
LEADS = ('cover', 'section', 'closing')
LATER = ('direction', 'layouts', 'house', 'approval')
COVER = ('id', 'kind', 'title', 'subtitle', 'notes')
NAMED = {'cover': ('title', 'cover'), 'section': ('section', 'divider'),
         'closing': ('closing', 'thank', 'end')}
SEVERITIES = ('critical', 'major', 'minor')
GRAVE = SEVERITIES[:2]
ABOUT = ('drawing', 'content')
NOTE = 12               # the shortest note the slides tool takes for a finding
HOUSE = (
    'Equals share one size and weight. Never set one of several peers larger, bolder or in '
    'another colour.',
    'The focal point is what the title singles out, and never one of several peers. A slide '
    'that lists equals has a focal that is not one of them.',
    'Draw nothing the title does not announce.',
    'Titles and labels are in sentence case. Names and acronyms stay as they are written.',
    'Boxes have square corners.',
    "A caveat and a source line go in the slide's own caveat and source fields, never in "
    'the drawing.',
    'Leave out badges, labels on arrows and small print wherever the slide reads without '
    'them.',
    'An icon is optional. Use one only where it names a recognisable thing, the same icon '
    'for the same thing, never twice on one slide.',
)
QUESTIONS = (
    'After three seconds, is the main point clear, and is it the claim in the title?',
    'Does the eye land first on what carries the point?',
    'Is there exactly one emphasis?',
    'Does everything on the slide support the title?',
    'Is each label inside or right beside what it names?',
    'Is the space balanced, with nothing stranded or crowded?',
    'Is the slide consistent with its neighbours in style, and different from them in '
    'layout unless they are meant to be compared?',
    'Does every picture and icon explain something?',
)
WORD = re.compile(r"[^\W_]+(?:['’.-][^\W_]+)*")
KEY_POINT = re.compile(r'^- (K\d+\.\d+):\s*(.+?)\s*(?:\[[^\]]*\]\s*)*$')
POINTER = re.compile(r'Read `references/[^\n]*')
USE = ('The deck is both presented and handed out. Every slide must make sense to someone '
       'reading it alone, so no slide may depend on its speaker notes for meaning. The notes '
       'carry the talk track and timing for a presenter.')


# --- the handoff -------------------------------------------------------------------------

def frame(blueprint: str) -> dict:
    """What a blueprint's frame says, keyed by the word before each colon, in lower case."""
    found, inside = {}, False
    for line in blueprint.splitlines():
        if line.startswith('## '):
            inside = line[3:].strip().lower() == 'frame'
        elif inside and ':' in line:
            key, _, value = line.partition(':')
            found[key.strip().lower()] = value.strip()
    return found


def handoff(title: str, level: str | None, blueprint: str, said: dict, target: str | None,
            brand: tuple[str, str] | None, guide: bool, scenarios=None) -> str:
    """deck-handoff.md: one page, written from the record, under the headings the skill's
    own deck stage gives it. `said` is what intake says, `guide` whether the training has
    a learner guide, and `scenarios` the practice scenarios its closing slide points to,
    or None when the training has no practice."""
    parsed, framed = checks.parse_blueprint(blueprint), frame(blueprint)
    modules = '; '.join(f"{ident}, {module['title']}"
                        for ident, module in parsed['modules'].items())
    closing = ('A closing slide.' if scenarios is None else
               'A closing slide that points to the practice scenarios'
               + (': ' + ', '.join(scenarios) if scenarios else '') + '.')
    made = {'google': 'Google Slides', 'pptx': 'PowerPoint'}.get(target, 'not chosen')
    lines = [f'# Deck handoff: {title}' + (f', level {level}' if level else ''), '',
             'Written by the runner from the record of this training. It is written again '
             'whenever the blueprint or the settings change.', '',
             '## Goal', '', 'After the deck the audience can:', '']
    lines += [f"- {objective['text']} ({ident})"
              for ident, objective in parsed['objectives'].items()]
    lines += ['', '## Audience and duration', '',
              f"Audience: {framed.get('audience') or said.get('audience') or 'not given'}",
              f"Duration: {framed.get('time') or said.get('time limit') or 'not given'}"]
    lines += [f'Level: {level}'] if level else []
    lines += ['', '## Use', '', USE, '', '## Required elements', '',
              '- The objectives near the start.',
              '- A check for understanding in each module' + (f': {modules}.' if modules
                                                              else '.'),
              '- A recap.', f'- {closing}', '', '## Sources', '',
              'The blueprint, ' + ('the learner guide and ' if guide else 'and ')
              + 'the research findings.', '', '## Research', '',
              'Complete. Work from the sources only and start no new research. Anything '
              "under the blueprint's open gaps stays out.", '', '## Output', '',
              made + (f', in the brand {brand[0]}' + (f' ({brand[1]}).' if brand[1] else '.')
                      if brand else
                      ', with no brand chosen.'), '']
    return '\n'.join(lines)


# --- the outline's rules -----------------------------------------------------------------

def count(text) -> int:
    """How many words a piece of text has."""
    return len(WORD.findall(text)) if isinstance(text, str) else 0


def _points(slide: dict) -> list[dict]:
    return [point for point in slide.get('points') or () if isinstance(point, dict)]


def visible(slide: dict) -> int:
    """The words a slide will show: its title, its points, its caveat and its source."""
    return (count(slide.get('title')) + count(slide.get('caveat')) + count(slide.get('source'))
            + sum(count(point.get('label')) + count(point.get('text'))
                  for point in _points(slide)))


def plain(text) -> str:
    """Text as it is compared: lower case, one space between its words, nothing else."""
    return ' '.join(WORD.findall(text.lower())) if isinstance(text, str) else ''


def gaps(blueprint: str) -> dict:
    """The key points a deck must leave out: each one the blueprint marks as unsupported
    or names under its open gaps, with its wording."""
    points, section = {}, None
    for line in blueprint.splitlines():
        if line.startswith('## '):
            section = line[3:].strip().lower()
        found = KEY_POINT.match(line)
        if found and section != 'open gaps':
            points[found.group(1)] = (found.group(2), '[unsupported]' in line)
    named = set(re.findall(r'\bK\d+\.\d+\b', checks.parse_blueprint(blueprint)['open_gaps']))
    return {ident: text for ident, (text, unsupported) in points.items()
            if unsupported or ident in named}


def _says(slide: dict) -> str:
    """Everything a slide says, to its audience and to its presenter, as it is compared."""
    said = [slide.get(key) for key in ('title', 'subtitle', 'understand', 'focal', 'caveat',
                                       'notes')]
    said += [point.get(key) for point in _points(slide) for key in ('label', 'text')]
    return ' . '.join(plain(text) for text in said if text)


def slides_of(outline) -> list[dict]:
    """An outline's slides, leaving out anything that is not one."""
    found = outline.get('slides') if isinstance(outline, dict) else None
    return [slide for slide in found or () if isinstance(slide, dict)]


def rules(outline, blueprint: str, budget: int | None = None) -> list[str]:
    """What the runner holds an outline to, beyond the slides tool's own check. Each
    problem is a sentence the worker can act on. `budget` is the most words one slide may
    show, when the tool has said."""
    if not isinstance(outline, dict) or not slides_of(outline):
        return ['The outline is one JSON object with its slides under "slides".']
    problems = [f'Leave out `{key}`: it is added after you hand the outline in.'
                for key in LATER if key in outline]
    if outline.get('delivery') not in (None, DELIVERY):
        problems.append(f'This deck is read alone as well as presented: set `delivery` to '
                        f'"{DELIVERY}".')
    objectives = list(checks.parse_blueprint(blueprint)['objectives'])
    left_out, served = gaps(blueprint), set()
    for slide in slides_of(outline):
        ident, kind = slide.get('id') or 'a slide', slide.get('kind')
        if kind == 'cover':
            extra = sorted(key for key in slide if key not in COVER)
            if extra:
                problems.append(f'{ident}: a cover carries a title and one subtitle line, '
                                'and no more. Leave out ' + ', '.join(extra) + '.')
            if '\n' in str(slide.get('subtitle') or '').strip():
                problems.append(f'{ident}: the subtitle of a cover is one line.')
        if kind == 'content':
            sources = slide.get('sources')
            sources = sources if isinstance(sources, list) else []
            unknown = [str(source) for source in sources if source not in objectives]
            if unknown:
                problems.append(f'{ident}: `sources` names ' + ', '.join(unknown) + ', which '
                                'the blueprint does not have. It may hold only the '
                                'objectives this slide serves: ' + ', '.join(objectives) + '.')
            elif not sources:
                problems.append(f'{ident}: `sources` is empty. Name the objectives this '
                                'slide serves, or leave the slide out.')
            served.update(sources)
            if budget and visible(slide) > budget:
                problems.append(f'{ident}: {visible(slide)} words will be seen, counting the '
                                f'title, the points, the caveat and the source. The most is '
                                f'{budget}. Say less, or make it two slides.')
        said = _says(slide)
        problems += [f'{ident}: this states {gap}, which the blueprint lists under its open '
                     'gaps. Leave it out.' for gap, text in left_out.items()
                     if plain(text) and plain(text) in said]
    missing = [objective for objective in objectives if objective not in served]
    if missing:
        problems.append('No slide serves ' + ', '.join(missing) + '. Every objective is '
                        'named in the `sources` of at least one content slide.')
    return problems


def shown(outline) -> list[dict]:
    """An outline as its slides, in order, for a person to read."""
    def text(slide: dict, key: str) -> str | None:
        return slide[key] if isinstance(slide.get(key), str) and slide[key].strip() else None

    return [{'id': str(slide.get('id') or ''), 'kind': str(slide.get('kind') or ''),
             'title': str(slide.get('title') or ''), 'subtitle': text(slide, 'subtitle'),
             'understand': text(slide, 'understand'),
             'points': [{'label': str(point.get('label') or ''),
                         'text': str(point.get('text') or '')} for point in _points(slide)],
             'caveat': text(slide, 'caveat'), 'source': text(slide, 'source'),
             'notes': text(slide, 'notes'),
             'serves': [str(source) for source in slide.get('sources') or ()
                        if isinstance(slide.get('sources'), list)]}
            for slide in slides_of(outline)]


def before(slides: int) -> dict:
    """What a deck of this many slides has cost before, in dollars and minutes of agent
    time. A round of drawing again after a review has cost as much again."""
    return {'dollars': round(RATE['dollars'] * slides, 2),
            'minutes': round(RATE['minutes'] * slides, 1)}


# --- starting the deck -------------------------------------------------------------------

def layouts(listed, slides: list[dict]) -> dict:
    """The template layout for each kind of lead slide an outline has: one that shows a
    title, has room for the subtitle if there is one and no place for a picture, and is
    named for that kind of slide where the template has such a one."""
    chosen = {}
    listed = [layout for layout in listed or () if isinstance(layout, dict)
              and isinstance(layout.get('name'), str)]
    for kind in LEADS:
        mine = [slide for slide in slides if slide.get('kind') == kind]
        if not mine:
            continue
        need = 1 if any(slide.get('subtitle') for slide in mine) else 0
        fits = [layout for layout in listed
                if layout.get('title') and (layout.get('subtitles') or 0) >= need]
        fits = [layout for layout in fits if not layout.get('pictures')] or fits
        named = [layout for layout in fits
                 if any(word in layout['name'].lower() for word in NAMED[kind])] or fits
        exact = [layout for layout in named if (layout.get('subtitles') or 0) == need]
        if not named:
            raise WorkspaceError(
                f"The brand's template has no layout that shows the title of a {kind} "
                'slide' + (' with its subtitle' if need else '') + ', so the deck cannot '
                'be started with this brand.')
        chosen[kind] = (exact or named)[0]['name']
    return chosen


def complete(outline: dict, listed, words: list[str]) -> dict:
    """An approved outline as the slides tool starts a deck from: with the direction, a
    layout for each kind of lead slide, the house rules, and the person's own words of
    approval."""
    return {**outline, 'delivery': DELIVERY, 'direction': dict(DIRECTION),
            'layouts': layouts(listed, slides_of(outline)), 'house': list(HOUSE),
            'approval': list(words)}


def lead(part: dict) -> dict:
    """A lead slide's file as the compiler takes it. A cover has no second line under its
    subtitle: no layout holds one."""
    slides = [{key: value for key, value in slide.items() if key != 'detail'}
              if isinstance(slide, dict) else slide for slide in part.get('slides') or ()]
    return {**part, 'slides': slides}


def _part(text: str, heading: str, body: str, renamed: str | None = None) -> str:
    """A brief with what is under one heading replaced. A heading the brief does not have
    is added at its end."""
    new = f'## {renamed or heading}\n\n{body.strip()}\n'
    pattern = re.compile(rf'^## {re.escape(heading)}[^\n]*\n.*?(?=^## |\Z)', re.S | re.M)
    if pattern.search(text):
        return pattern.sub(lambda found: new + '\n', text, count=1)
    return text.rstrip('\n') + '\n\n' + new


def brief(written: str, whole: dict, previews: int = PREVIEWS) -> str:
    """The brief the slides tool wrote for one section, for a worker with tools and no
    files. Its slides, their order and the direction are kept as written."""
    skeleton = json.dumps({'version': 1, 'title': whole.get('title'),
                           'direction': whole.get('direction') or DIRECTION,
                           'slides': ['your slides, in order']}, ensure_ascii=False)
    text = POINTER.sub('Your instructions say how to work; `list_inputs` shows what you '
                       'can read.', written)
    text = _part(text, 'Paths', f'''
One JSON object, the section, handed in with `submit_section`:

```json
{skeleton}
```

Each slide is `{{"id", "title", "sources", "brief": {{"relation", "focal": the ID of the node that carries the point, "rhythm"}}, "canvas", "connect"?, "caveat"?, "source"?, "notes"}}`. Copy each slide's `id`, `title`, `sources`, caveat, source line and notes exactly as they are given below, and keep every word of every point. The input "composition contract" has the exact format.''',
                 'What you write')
    text = _part(text, 'House style', '\n'.join(f'- {line}' for line in HOUSE))
    text = _part(text, 'Preview', f'''
`preview_section` renders your whole section and returns a picture of every slide, with what the renderer found. You have {previews} previews. `check_section` is free: use it until the section compiles before you spend a preview.''')
    return _part(text, 'Return', '''
Hand the section in with `submit_section`. It must be the version you last previewed. Say what you changed after looking at the pictures and what still bothers you, naming your weakest slide.''')


def named_in(written: str, whole: dict) -> list[str]:
    """The slides a section's brief gives its worker, by ID, in the outline's order."""
    return [slide['id'] for slide in slides_of(whole)
            if slide.get('kind') == 'content' and f"`{slide.get('id')}`" in written]


def fixed(whole: dict, ids: list[str], number: int) -> dict:
    """What the composer of one section may not change: the deck's title and direction,
    and for each of its slides the title, the objectives, the points, the caveat, the
    source line and the notes that were approved."""
    by_id = {slide.get('id'): slide for slide in slides_of(whole)}
    return {'title': whole.get('title'), 'direction': whole.get('direction') or DIRECTION,
            'prefix': f's{number}_',
            'slides': [{'id': ident, 'title': by_id[ident].get('title'),
                        'sources': list(by_id[ident].get('sources') or ()),
                        'points': [{'label': point.get('label'), 'text': point.get('text')}
                                   for point in _points(by_id[ident])],
                        'caveat': by_id[ident].get('caveat'),
                        'source': by_id[ident].get('source'),
                        'notes': by_id[ident].get('notes')} for ident in ids]}


# --- a section, as it is handed in -------------------------------------------------------

def _drawn(node, found: list[str], ids: list[str]) -> None:
    """Every piece of text a drawing shows, in the order it is written, and every ID in it.
    A badge's character is not one of the slide's words."""
    if isinstance(node, list):
        for item in node:
            _drawn(item, found, ids)
    elif isinstance(node, dict):
        if isinstance(node.get('id'), str) and ('type' in node or 'from' in node):
            ids.append(node['id'])
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                _drawn(value, found, ids)
            elif isinstance(value, str) and key in ('text', 'value', 'label', 'title') \
                    and node.get('type') != 'badge':
                found.append(value)


def _same(one, other) -> bool:
    return ' '.join(str(one or '').split()) == ' '.join(str(other or '').split())


def _caveat(slide: dict):
    stated = slide.get('caveat')
    return stated.get('text') if isinstance(stated, dict) else stated


def kept(section, spec: dict) -> list[str]:
    """What the runner refuses in a section: anything that was fixed before its composer
    started and is not as it was, and any approved word that is gone."""
    if not isinstance(section, dict):
        return ['A section is one JSON object.']
    problems = []
    if section.get('direction') != spec['direction']:
        problems.append('`direction` is copied unchanged: ' + json.dumps(spec['direction']))
    if section.get('title') != spec['title']:
        problems.append(f"`title` is the deck's title: {json.dumps(spec['title'])}")
    slides = [slide for slide in section.get('slides') or () if isinstance(slide, dict)] \
        if isinstance(section.get('slides'), list) else []
    wanted = [slide['id'] for slide in spec['slides']]
    if [slide.get('id') for slide in slides] != wanted:
        return problems + ['The slides are exactly these, in this order: '
                           + ', '.join(wanted) + '.']
    for mine, theirs in zip(slides, spec['slides']):
        ident = theirs['id']
        if mine.get('title') != theirs['title']:
            problems.append(f"{ident}: the title is fixed: {json.dumps(theirs['title'])}")
        if mine.get('sources') != theirs['sources']:
            problems.append(f"{ident}: `sources` is fixed: {json.dumps(theirs['sources'])}")
        if 'layout' in mine:
            problems.append(f'{ident}: a slide you draw names no template layout.')
        texts, ids = [], []
        _drawn([mine.get('canvas'), mine.get('connect')], texts, ids)
        wrong = [found for found in ids if not found.startswith(spec['prefix'])]
        if wrong:
            problems.append(f"{ident}: every node and edge ID starts with {spec['prefix']}. "
                            'These do not: ' + ', '.join(wrong[:8]) + '.')
        on_slide = ' ' + ' '.join(plain(text) for text in texts) + ' '
        gone = [text for point in theirs['points'] for text in (point['label'], point['text'])
                if plain(text) and f' {plain(text)} ' not in on_slide]
        problems += [f'{ident}: these approved words are missing or changed: '
                     f'{json.dumps(text)}' for text in gone]
        for name, got in (('caveat', _caveat(mine)), ('source', mine.get('source')),
                          ('notes', mine.get('notes'))):
            if not _same(got, theirs[name]):
                problems.append(f'{ident}: `{name}` stays exactly as it was approved'
                                + (f': {json.dumps(theirs[name])}' if theirs[name]
                                   and name != 'notes' else '.' if theirs[name]
                                   else ': the slide has none.'))
    return problems


# --- what a review finds -----------------------------------------------------------------

def checked(finding, slides: list[dict]) -> tuple[dict | None, str | None]:
    """One finding of a review as it is kept, or why it cannot be. `slides` are the
    slides that were looked at, each with its `id` and `number`."""
    if not isinstance(finding, dict):
        return None, 'A finding is an object with slide, question, severity and note.'
    numbers = {slide['id']: slide['number'] for slide in slides}
    ident, question = finding.get('slide'), finding.get('question')
    if ident not in numbers:
        return None, f'{ident!r} is not a slide of this deck. Name a slide by its ID.'
    if type(question) is not int or not 1 <= question <= len(QUESTIONS):
        return None, f'{ident}: `question` is a number from 1 to {len(QUESTIONS)}.'
    if finding.get('severity') not in SEVERITIES:
        return None, f'{ident}: `severity` is one of: ' + ', '.join(SEVERITIES) + '.'
    note = finding.get('note')
    if not isinstance(note, str) or len(note.strip()) < NOTE:
        return None, f'{ident}: `note` is one sentence on what is wrong on the slide.'
    if finding.get('about', ABOUT[0]) not in ABOUT:
        return None, f'{ident}: `about` is one of: ' + ', '.join(ABOUT) + '.'
    fix = finding.get('fix')
    return {'slide': ident, 'number': numbers[ident], 'question': question,
            'severity': finding['severity'], 'about': finding.get('about', ABOUT[0]),
            'note': note.strip(),
            'fix': fix.strip() if isinstance(fix, str) and fix.strip() else None}, None


def ordered(findings) -> list[dict]:
    """Findings as a person reads them: the gravest first, then in slide order."""
    return sorted(findings or (), key=lambda finding: (
        SEVERITIES.index(finding['severity']), finding['number']))


def grave(findings) -> list[dict]:
    """The findings that keep a deck from being called clear."""
    return [finding for finding in ordered(findings) if finding['severity'] in GRAVE]


def to_repair(findings, sections: list[dict]) -> list[str]:
    """The sections a review sends back to their composers: each with a major or critical
    finding about how one of its slides is drawn."""
    drawn = {finding['slide'] for finding in grave(findings) if finding['about'] == ABOUT[0]}
    return [section['id'] for section in sections if drawn & set(section['slides'])]


def remains(findings) -> str:
    """What a review still finds, counted, in a sentence. A deck is never called clear
    while a major finding remains."""
    left = grave(findings)
    if not left:
        small = len(findings or ())
        return ('The review found nothing major' + (f', and {small} small thing'
                f'{"" if small == 1 else "s"} worth a look.' if small else '.'))
    critical = sum(finding['severity'] == 'critical' for finding in left)
    major = len(left) - critical
    parts = [f'{critical} critical'] if critical else []
    parts += [f'{major} major'] if major else []
    return ('This deck is not clear: the review still finds ' + ' and '.join(parts)
            + f" thing{'' if len(left) == 1 else 's'} wrong.")


def told(findings, slides: list[dict]) -> str:
    """What a review found on some slides, as their composer is told it."""
    lines = ['# What the review found in your section', '',
             'Someone who drew none of these slides looked at each one as it was rendered '
             'and answered the same questions about it. Each "no" is below.', '']
    for slide in slides:
        mine = [finding for finding in ordered(findings) if finding['slide'] == slide['id']]
        if not mine:
            continue
        lines += [f"## Slide {slide['number']}: `{slide['id']}`, \"{slide['title']}\"", '']
        for finding in mine:
            what = ('This is about what the slide says, which is not yours to change: '
                    'leave the words as they are. ' if finding['about'] == ABOUT[1] else '')
            lines.append(f"- **{finding['severity']}**, \"{QUESTIONS[finding['question'] - 1]}"
                         f"\" {what}{finding['note']}"
                         + (f" Suggested: {finding['fix']}" if finding['fix'] else ''))
        lines.append('')
    return '\n'.join(lines)


def asked(objectives: dict, slides: list[dict], earlier=None) -> str:
    """What a reviewer is asked: the questions, how grave a "no" is, the slides, the
    objectives, and on a later round what was found before."""
    lines = ['# The review', '', '## The questions, asked of every slide', '']
    lines += [f'{number}. {question}' for number, question in enumerate(QUESTIONS, start=1)]
    lines += ['', '## How grave a "no" is', '',
              '- `critical`: the slide misleads, cannot be read, or its point cannot be '
              'found.',
              '- `major`: the slide works but is clearly weaker than it should be.',
              '- `minor`: a small flaw.', '', '## The slides', '']
    lines += [f"- {slide['number']}. `{slide['id']}`: \"{slide['title']}\"" for slide in slides]
    lines += ['', '## The objectives', '']
    lines += [f'- {ident}: {text}' for ident, text in objectives.items()]
    if earlier:
        lines += ['', '## What an earlier review found', '',
                  'These slides were drawn again since. Look for each of these, and where '
                  'one is not put right, record it again.', '']
        lines += [f"- Slide `{finding['slide']}`, {finding['severity']}, question "
                  f"{finding['question']}: {finding['note']}" for finding in ordered(earlier)]
    return '\n'.join(lines) + '\n'


def link(made: dict, title: str, rendered: str) -> str:
    """deck-link.md for a deck kept in Google Slides. It names the rendered deck it was
    made from, so that an approval of this file is an approval of those slides."""
    return (f"# Slide deck: {title}\n\n- URL: {made.get('url')}\n"
            f"- Title: {made.get('name') or title}\n- ID: {made.get('id')}\n"
            f'- Made from the rendered deck with the SHA-256 {rendered}\n')
