"""What a slide deck is made from: the runner's own rules, and what its workers are told.

What a caller needs to know
---------------------------
    deck.handoff(title, level, blueprint, said, settings, ...)   # deck-handoff.md, as text
    deck.rules(outline, blueprint, budget)      # what the runner refuses in an outline
    deck.shown(outline, design=None)            # an outline as its slides, for a person
    deck.design_rules(outline, design)          # what the runner refuses in a design
    proposal = deck.proposal(outline, design)   # the slides tool's design proposal
    deck.unresolved(proposal)                   # what it still needs, a sentence each
    whole = deck.complete(outline, listed, words)   # with direction, layouts, house rules
    deck.lead(part)                             # a cover, section or closing slide, put right
    deck.brief(written, whole, previews)        # a section's brief, for a worker with tools
    spec = deck.fixed(whole, ids, number)       # what a section's composer may not change
    deck.kept(section, spec)                    # what the runner refuses in a section
    deck.as_approved(section, spec)             # each approved intent, as it was approved
    deck.icons(design)                          # each concept's icon, across the deck
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
- A design is how each slide is drawn, written by the outline's writer beside the outline
  when the slides tool keeps a design session: for each slide its intent, composition,
  asset and qualifications, and nothing else. `proposal` joins the two in the tool's schema
  2, taking each slide's title, copy, notes and objectives from the outline, so that the
  copy the person approves has one source.
- HOUSE is what the composers are told that no program can check. It goes into the outline
  as its house rules and into each section's brief. A deck drawn from an approved design
  has DESIGNED_HOUSE instead, which draws what the design approved rather than leaving its
  visuals to the composer.
- `design` is the plan the slides tool approved, as `design check` returns it. Each
  section's brief then carries the approved design of its slides and the icon each concept
  has across the whole deck, and a composer copies each slide's `intent` into its section
  exactly. `fixed` takes the wording from the approved copy and adds the intent and the
  wording the copy must keep. A deck without a design is told and held to what it always
  was.
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
CLOSING_WORDS = 10      # words a closing slide's title and subtitle may hold between them
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
DESIGNED_HOUSE = HOUSE[:-1] + (
    'Draw what the approved design says: its visual, its composition and the assets it '
    'selected. An icon names a recognisable thing: the same icon for the same concept '
    'across the deck, never twice on one slide.',
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
DESIGNED = ('id', 'intent', 'composition', 'asset', 'qualifications')   # a worker's to write
LEAD = 'outline'        # what a cover, section or closing slide cites, as the slides tool does
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
               'A last content slide that says what to practise next'
               + (': ' + ', '.join(scenarios) if scenarios else '')
               + ', then a closing slide.')
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
        if kind == 'closing':
            # A closing slide is the template's own, with room for a few words and no body.
            said = f"{slide.get('title') or ''} {slide.get('subtitle') or ''}".split()
            extra = sorted(key for key in slide if key not in COVER)
            if extra or len(said) > CLOSING_WORDS:
                problems.append(f'{ident}: a closing slide is the brand\'s own last slide: a '
                                f'title and one subtitle line, {CLOSING_WORDS} words at most '
                                'between them, and nothing drawn under it. Put anything the '
                                'audience should read, such as what to practise next, on a '
                                'content slide before it.')
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


def shown(outline, design=None) -> list[dict]:
    """An outline as its slides, in order, for a person to read. With the design proposed
    with it, each slide also says how it is drawn; without, its `design` is None."""
    def text(slide: dict, key: str) -> str | None:
        return slide[key] if isinstance(slide.get(key), str) and slide[key].strip() else None

    drawn = {slide.get('id'): drawn_as(slide) for slide in slides_of(design)}

    return [{'id': str(slide.get('id') or ''), 'kind': str(slide.get('kind') or ''),
             'title': str(slide.get('title') or ''), 'subtitle': text(slide, 'subtitle'),
             'understand': text(slide, 'understand'),
             'points': [{'label': str(point.get('label') or ''),
                         'text': str(point.get('text') or '')} for point in _points(slide)],
             'caveat': text(slide, 'caveat'), 'source': text(slide, 'source'),
             'notes': text(slide, 'notes'),
             'serves': [str(source) for source in slide.get('sources') or ()
                        if isinstance(slide.get('sources'), list)],
             'design': drawn.get(slide.get('id'))}
            for slide in slides_of(outline)]


# --- the design proposed with the outline ------------------------------------------------

def design_rules(outline, design) -> list[str]:
    """What the runner refuses in the design a worker hands in with an outline, before the
    slides tool sees it: one entry for every slide, in the outline's order, holding only
    what is the worker's to write. Each problem is a sentence the worker can act on."""
    if not isinstance(design, dict) or not isinstance(design.get('slides'), list):
        return ['The design is one JSON object, with one entry for each slide under "slides".']
    problems = [f'Leave out `{key}`: the design holds its slides and nothing else.'
                for key in design if key != 'slides']
    wanted = [slide.get('id') for slide in slides_of(outline)]
    entries = design['slides']
    if [entry.get('id') if isinstance(entry, dict) else None for entry in entries] != wanted:
        return problems + ['The design has one entry for every slide of the outline, the '
                           'cover, section and closing slides too, in its order: '
                           + ', '.join(str(ident) for ident in wanted) + '.']
    for entry in entries:
        extra = sorted(key for key in entry if key not in DESIGNED)
        if extra:
            problems.append(f"{entry['id']}: leave out " + ', '.join(f'`{key}`' for key in extra)
                            + '. The title, the copy, the notes and the objectives are taken '
                            'from the outline.')
    return problems


def _copy(slide: dict) -> dict:
    """What a slide shows besides its title, as the slides tool's design takes it: a content
    slide's points, focal statement, caveat and source; a lead slide's subtitle, or its
    title when it has nothing else."""
    def text(value) -> bool:
        return isinstance(value, str) and bool(value.strip())

    if slide.get('kind') != 'content':
        return {'points': [], 'focal': slide['subtitle'] if text(slide.get('subtitle'))
                else slide.get('title')}
    copy = {'points': [{key: point[key] for key in ('label', 'text') if text(point.get(key))}
                       for point in _points(slide)]}
    copy['points'] = [point for point in copy['points'] if point]
    copy.update({key: slide[key] for key in ('focal', 'caveat', 'source')
                 if text(slide.get(key))})
    if not copy['points'] and 'focal' not in copy:
        copy['focal'] = slide.get('title')
    return copy


def proposal(outline, design) -> dict:
    """The design proposal the slides tool keeps, in its schema 2, made from an outline and
    the design handed in with it, which `design_rules` has let through. The outline gives
    each slide its title, its visible copy, its notes and the objectives it serves, which
    are also its sources; a lead slide's source is the outline itself. The design gives
    the rest. A slide's evidence is its sources unless the design names its own."""
    written = {entry['id']: entry for entry in design['slides']}
    slides = []
    for slide in slides_of(outline):
        mine, content = written[slide['id']], slide.get('kind') == 'content'
        sources = [str(source) for source in slide.get('sources') or ()] if content else []
        intent = mine.get('intent')
        if isinstance(intent, dict) and 'evidence' not in intent:
            intent = {**intent, 'evidence': sources or [LEAD]}
        made = {'id': slide['id'], 'title': slide.get('title'), 'sources': sources or [LEAD]}
        made.update({'objectives': sources} if sources else {})
        made['copy'] = _copy(slide)
        made.update({'qualifications': mine['qualifications']}
                    if 'qualifications' in mine else {})
        made.update({'notes': slide['notes']} if isinstance(slide.get('notes'), str)
                    and slide['notes'].strip() else {})
        made.update(composition=mine.get('composition'), intent=intent, asset=mine.get('asset'))
        slides.append(made)
    return {'schema': 2, 'title': outline.get('title'), 'scope': 'new', 'slides': slides}


def drawn_as(slide: dict) -> dict:
    """How one slide of a design proposal is drawn, for a person to read beside its copy."""
    intent = slide.get('intent') if isinstance(slide.get('intent'), dict) else {}
    asset = slide.get('asset') if isinstance(slide.get('asset'), dict) else {}
    visual = intent.get('visual') if isinstance(intent.get('visual'), dict) else {}
    other = intent.get('alternative') if isinstance(intent.get('alternative'), dict) else {}
    return {'claim': intent.get('takeaway'), 'question': intent.get('audienceQuestion'),
            'family': visual.get('family'), 'purpose': visual.get('purpose'),
            'drawn': slide.get('composition'), 'why': intent.get('rationale'),
            'alternative': ({'treatment': other.get('treatment'), 'reason': other.get('reason')}
                            if other else None),
            'asset': {key: asset.get(key) for key in ('description', 'disposition', 'reason')},
            'candidates': [{key: candidate.get(key) for key in ('kind', 'ref', 'concept',
                                                                 'status')}
                           for candidate in asset.get('candidates') or ()
                           if isinstance(candidate, dict)],
            'keeps': [str(kept) for kept in slide.get('qualifications') or ()]}


def unresolved(design) -> list[str]:
    """What a design proposal still needs, a sentence each: an asset it could not find, and
    each candidate not yet resolved."""
    found = []
    for number, slide in enumerate(design.get('slides') or (), start=1):
        shown = drawn_as(slide)
        if shown['asset']['disposition'] == 'unavailable':
            found.append(f'Slide {number}: the asset it would use is unavailable, so it is '
                         'drawn another way.')
        found += [f"Slide {number}: the {candidate['kind']} \"{candidate['ref']}\" for "
                  f"{candidate['concept']} is not resolved yet."
                  for candidate in shown['candidates'] if candidate['status'] == 'pending']
    return found


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


def complete(outline: dict, listed, words: list[str], designed: bool = False) -> dict:
    """An approved outline as the slides tool starts a deck from: with the direction, a
    layout for each kind of lead slide, the house rules, and the person's own words of
    approval. A deck `designed` is drawn from its approved design."""
    return {**outline, 'delivery': DELIVERY, 'direction': dict(DIRECTION),
            'layouts': layouts(listed, slides_of(outline)),
            'house': list(DESIGNED_HOUSE if designed else HOUSE), 'approval': list(words)}


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


def brief(written: str, whole: dict, previews: int = PREVIEWS, design=None) -> str:
    """The brief the slides tool wrote for one section, for a worker with tools and no
    files. Its slides, their order and the direction are kept as written. With `design`,
    the plan the slides tool approved, it also carries the approved design of each of its
    slides and the icon of each concept across the deck."""
    skeleton = json.dumps({'version': 1, 'title': whole.get('title'),
                           'direction': whole.get('direction') or DIRECTION,
                           'slides': ['your slides, in order']}, ensure_ascii=False)
    text = POINTER.sub('Your instructions say how to work; `list_inputs` shows what you '
                       'can read.', written)
    named = ('id', 'title', 'sources', *(('intent',) if design else ()))
    shape, copied = (''.join(f'{mark}{key}{mark}, ' for key in named) for mark in '"`')
    text = _part(text, 'Paths', f'''
One JSON object, the section, handed in with `submit_section`:

```json
{skeleton}
```

Each slide is `{{{shape}"brief": {{"relation", "focal": the ID of the node that carries the point, "rhythm"}}, "canvas", "connect"?, "caveat"?, "source"?, "notes"}}`. Copy each slide's {copied}caveat, source line and notes exactly as they are given below, and keep every word of every point. The input "composition contract" has the exact format.''',
                 'What you write')
    text = _part(text, 'House style', '\n'.join(
        f'- {line}' for line in (DESIGNED_HOUSE if design else HOUSE)))
    if design:
        text = _part(text, 'The approved design', drawn_from(design, named_in(written, whole)))
        text = _part(text, 'Icons across the deck', _icons_told(icons(design)))
    text = _part(text, 'Preview', f'''
`preview_section` renders your whole section and returns a picture of every slide, with what the renderer found. You have {previews} previews. `check_section` is free: use it until the section compiles before you spend a preview.''')
    return _part(text, 'Return', '''
Hand the section in with `submit_section`. It must be the version you last previewed. Say what you changed after looking at the pictures and what still bothers you, naming your weakest slide.''')


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def drawn_from(design, ids: list[str]) -> str:
    """What a section's composer is told of the approved design of its slides, one record
    each, with the intent it copies."""
    by_id = {slide.get('id'): slide for slide in slides_of(design)}
    lines = ['The person approved how each of your slides teaches together with what it '
             'says, in one decision. Draw each as its design says: the visual, what the '
             'composition places and joins, and the asset it selected. How you realise it '
             'is yours: the layout, the sizes, what is large. A slide whose visual is `text` '
             'is direct text by decision: draw it as text and add nothing to decorate it. If '
             'a design cannot be drawn as approved, draw the nearest you can and say so when '
             'you hand in. Another concept needs the person\'s approval.', '',
             'Only icons can be placed in this version. Where a design selects a picture, '
             'draw the rest as designed and name the picture when you hand in.', '',
             'Copy each slide\'s `intent` into it exactly as it is given here. The slides '
             'tool checks it against the approval.']
    for ident in ids:
        slide = by_id.get(ident) or {}
        shown = drawn_as(slide)
        lines += ['', f'### `{ident}`', '', f"- Claim: {shown['claim']}",
                  f"- The question it answers: {shown['question']}",
                  f"- Relationship: {(slide.get('intent') or {}).get('relationship')}",
                  f"- Visual: {shown['family']}. Its purpose: {shown['purpose']}",
                  f"- How it is drawn: {shown['drawn']}", f"- Why: {shown['why']}"]
        if shown['alternative']:
            lines.append(f"- Weighed against: {shown['alternative']['treatment']}. "
                         f"{shown['alternative']['reason']}")
        asset = shown['asset']
        lines.append(f"- Asset: {asset['description']} ({asset['disposition']}: "
                     f"{asset['reason']})")
        lines += [f"  - {candidate['kind']} \"{candidate['ref']}\" for {candidate['concept']}"
                  + (', still to be found' if candidate['status'] == 'pending' else '')
                  for candidate in shown['candidates']]
        lines += [f'- Wording it must keep: {_json(kept)}' for kept in shown['keeps']]
        lines += ['- `intent`, to copy:', '', '```json', _json(slide.get('intent')), '```']
    return '\n'.join(lines)


def icons(design) -> list[dict]:
    """The icon the approved design names for each concept, across every slide of the
    deck, as {'concept', 'ref', 'status', 'slides'}, in the order they first appear."""
    found: dict = {}
    for slide in slides_of(design):
        for candidate in drawn_as(slide)['candidates']:
            if candidate['kind'] != 'icon':
                continue
            made = found.setdefault((candidate['concept'], candidate['ref']), {
                'concept': candidate['concept'], 'ref': candidate['ref'],
                'status': candidate['status'], 'slides': []})
            made['status'] = 'resolved' if 'resolved' in (made['status'], candidate['status']) \
                else made['status']
            if slide.get('id') not in made['slides']:
                made['slides'].append(slide.get('id'))
    return list(found.values())


def _icons_told(listed: list[dict]) -> str:
    if not listed:
        return ('The approved design names no icon. Use one only where it names a '
                'recognisable thing, and the same one for the same thing in every section.')
    return '\n'.join(['The same concept has the same icon in every section of the deck. These '
                      'are the icons the approved design names, on every slide. Find each with '
                      '`search_icons` by its name and use the ID it gives you for that '
                      'concept, on any slide of yours that shows it.', ''] + [
        f"- {icon['concept']}: \"{icon['ref']}\", on " + ', '.join(
            f'`{ident}`' for ident in icon['slides']) for icon in listed])


def named_in(written: str, whole: dict) -> list[str]:
    """The slides a section's brief gives its worker, by ID, in the outline's order."""
    return [slide['id'] for slide in slides_of(whole)
            if slide.get('kind') == 'content' and f"`{slide.get('id')}`" in written]


def fixed(whole: dict, ids: list[str], number: int, design=None) -> dict:
    """What the composer of one section may not change: the deck's title and direction,
    and for each of its slides the title, the objectives, the points, the caveat, the
    source line and the notes that were approved. With `design`, the plan the slides tool
    approved, the title and the visible copy are the approved ones, and each slide also
    has the wording it must keep and its approved `intent`, as the JSON text the slides
    tool compares: a text keeps the order of its keys wherever it is kept."""
    by_id = {slide.get('id'): slide for slide in slides_of(whole)}
    made = {'title': whole.get('title'), 'direction': whole.get('direction') or DIRECTION,
            'prefix': f's{number}_',
            'slides': [{'id': ident, 'title': by_id[ident].get('title'),
                        'sources': list(by_id[ident].get('sources') or ()),
                        'points': [{'label': point.get('label'), 'text': point.get('text')}
                                   for point in _points(by_id[ident])],
                        'caveat': by_id[ident].get('caveat'),
                        'source': by_id[ident].get('source'),
                        'notes': by_id[ident].get('notes')} for ident in ids]}
    if design is None:
        return made
    approved = {slide.get('id'): slide for slide in slides_of(design)}
    for slide in made['slides']:
        mine = approved.get(slide['id']) or {}
        copy = mine.get('copy') if isinstance(mine.get('copy'), dict) else {}
        slide.update(title=mine.get('title'), points=[
            {'label': point.get('label'), 'text': point.get('text')}
            for point in copy.get('points') or () if isinstance(point, dict)],
            caveat=copy.get('caveat'), source=copy.get('source'),
            intent=json.dumps(mine.get('intent'), separators=(',', ':'), ensure_ascii=False),
            qualifications=[str(kept) for kept in mine.get('qualifications') or ()])
    return made


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
        if 'intent' not in theirs:
            continue
        if mine.get('intent') != json.loads(theirs['intent']):
            problems.append(f'{ident}: `intent` is copied exactly as it was approved. Your '
                            'brief gives it under the approved design.')
        shown = ' '.join(plain(text) for text in (*texts, _caveat(mine), mine.get('source'))
                         if isinstance(text, str))
        problems += [f'{ident}: the approved design keeps this wording, which is missing or '
                     f'changed: {json.dumps(kept)}' for kept in theirs['qualifications']
                     if plain(kept) and plain(kept) not in shown]
    return problems


def as_approved(section, spec: dict):
    """A section whose intents are written exactly as they were approved: each one that is
    the approved intent is given its keys in the approved order, which the slides tool
    compares as written. Anything else is left as it is, to be refused."""
    wanted = {slide['id']: json.loads(slide['intent']) for slide in spec['slides']
              if 'intent' in slide}
    if not wanted or not isinstance(section, dict) or not isinstance(section.get('slides'),
                                                                     list):
        return section
    return {**section, 'slides': [
        {**slide, 'intent': wanted[slide['id']]} if isinstance(slide, dict)
        and slide.get('id') in wanted and slide.get('intent') == wanted[slide['id']] else slide
        for slide in section['slides']]}


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
