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

Left out, `copies` is asked of `copies.wanted` here. Whether a copy that was not made
blocks the training or only limits it is the core's rule. With Yoodli on, the brief's copy
is the file a person uploads: a training that keeps only Google Docs is not ready until
the brief has one.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
import checks
import desk
import training
import workspace

from runner import copies as copying

FILE = 'README.md'
SECTIONS = ('Objectives', 'What is here', 'Copies', 'Coverage', 'Open gaps and limitations',
            'Using the scenarios', 'Research')
NONE = '—'
# The helper's reasons that are about one copy, and which kind of copy each is about.
ABOUT_A_COPY = tuple((re.compile(pattern, re.DOTALL), kind) for pattern, kind in (
    (r'(\S+) has no export(?:, and .*)?', 'word'),
    (r'Yoodli handoff incomplete: no export of (\S+)', 'word'),
    (r'The export of (\S+) is out of date', 'word'),
    (r'(\S+) is not in a Google Doc(?:, and .*)?', 'google'),
    (r'The Google Doc of (\S+) is behind its file', 'google')))
A_FAILED_CHECK = re.compile(r'(\S+\.\S+) failed')
FINDINGS = (('supported', 'supported by the sources'),
            ('contradicted', 'contradicted by the sources'),
            ('insufficient', 'without enough evidence'),
            ('unavailable', 'with no source that could be read'),
            ('pending', 'not researched'))
BASIS = {'Yoodli goals': ('from the Yoodli goals',
                          'a goal in a Yoodli scenario says it assesses the objective'),
         'practice plan': ('from the practice plan',
                           'the blueprint\'s practice plan gives the objective to a '
                           'scenario that has been written')}
DERIVED = ('_This page is written from the training\'s record and is written again when the '
           'training changes, so a change made to it here is not kept._')


@dataclass
class _Training:
    """Everything the index is written from, read once."""
    root: Path
    session: dict
    status: dict            # the core's status
    checked: dict           # the core's check, with every outcome
    copies: list            # what copies.wanted gave
    blueprints: dict        # level, or None for a plain training, to its parsed blueprint

    @property
    def levels(self) -> list:
        return self.session['levels'] or [None]

    def file(self, name: str) -> str:
        return self.status['files'][name]

    def text(self, name: str) -> str | None:
        return training.read(self.root, self.file(name))

    def left(self, stage: str) -> str | None:
        """The word for a stage that has nothing to show, or None when it was made."""
        if stage not in self.session['settings']['stages']:
            return desk.WORDS['skipped']
        return desk.WORDS['unavailable'] if stage in self.session['unavailable'] else None

    def outcome(self, check: str) -> dict | None:
        return next((item for item in self.checked['checks'] if item['check'] == check), None)

    def supplied(self) -> list:
        """The documents the research plan was given, as the research record lists them."""
        record = workspace.research_record(self.root) or {}
        return [source for source in record.get('sources') or [] if isinstance(source, dict)]


def _read(root: Path, copies: list[dict] | None) -> _Training:
    root = Path(root)
    session = workspace.load(root)
    found = _Training(root, session, workspace.status(root),
                      training.run_checks(root, show_all=True),
                      copying.wanted(root) if copies is None else list(copies), {})
    for level in found.levels:
        text = found.text(workspace.qualify('blueprint', level))
        found.blueprints[level] = checks.parse_blueprint(text) if text is not None else None
    return found


# --- readiness -----------------------------------------------------------------------------

def readiness(root: Path, copies: list[dict] | None = None) -> dict:
    """Whether the training is ready, what blocks it and what it had to leave out."""
    return _report(_read(root, copies))


def write(root: Path, copies: list[dict] | None = None) -> dict:
    """Write README.md from the record, and say whether the training is ready."""
    found = _read(root, copies)
    report = _report(found)
    workspace.write_atomic(workspace.managed(found.root, FILE),
                           _index(found, report).encode('utf-8'))
    return report


def _report(found: _Training) -> dict:
    why = {(entry.get('artifact'), entry.get('kind')): entry['problem']
           for entry in found.copies
           if entry.get('problem') and entry.get('state') != 'made'}
    return {'ready': found.checked['ready'],
            'blocking': [_said(found, reason, why) for reason in found.checked['blocking']],
            'limitations': [_said(found, reason, why)
                            for reason in found.checked['limitations']],
            'file': FILE}


def _said(found: _Training, reason: str, why: dict) -> str:
    """One of the helper's reasons as a sentence for a person: in the page's words, with
    what a failed check found, and with why a copy was not made where that is known."""
    plain, more = desk.plainly(reason), []
    failed = A_FAILED_CHECK.fullmatch(reason)
    if failed:
        problems = (found.outcome(failed[1]) or {}).get('problems') or []
        more = problems[:2] + ([f'And {len(problems) - 2} more.'] if len(problems) > 2 else [])
    for pattern, kind in ABOUT_A_COPY:
        about = pattern.fullmatch(reason)
        if about and why.get((about[1], kind)):
            more = [why[about[1], kind]]
    return ' '.join([plain.rstrip('.') + '.', *more]) if more else plain


# --- the words and marks of a Markdown page ------------------------------------------------

def _line(text) -> str:
    """Text from a record or a file as one line of the page."""
    return ' '.join(str(text or '').split())


def _cell(text) -> str:
    return _line(text).replace('|', '\\|') or NONE


def _link(words: str, target: str) -> str:
    """A link to a file of the training, or to a web address when that is what it is."""
    web = target.startswith(('https://', 'http://'))
    address = urllib.parse.quote(target, safe=":/?#@!$&*+,;=%~._-" if web else '/')
    return f"[{_line(words).replace('[', '(').replace(']', ')')}]({address})"


def _linked(found: _Training, relative: str) -> str:
    """A file's path as a link when the file is there, else as words."""
    return _link(relative, relative) if (found.root / relative).is_file() else relative


def _blocks(found: _Training, part) -> list[str]:
    """One part of a section for each level, lowest first, each under its own heading. A
    plain training has no levels, so its one part has no heading."""
    lines: list[str] = []
    for level in found.levels:
        lines += [*([] if level is None else [f'### Level {level}', '']),
                  *part(found, level), '']
    return lines[:-1]


def _headed(text: str) -> dict[str, str]:
    """What a file says under each `##` heading, keyed by the heading in lower case."""
    found, heading = {}, None
    for line in text.splitlines():
        if line.startswith('## '):
            heading = line[3:].strip().lower()
            found[heading] = ''
        elif heading is not None:
            found[heading] += line + '\n'
    return found


# --- 1. who and what it is for -------------------------------------------------------------

def _size(parsed: dict | None) -> str:
    modules = (parsed or {}).get('modules')
    if not modules:
        return 'not sized yet: it has no blueprint'
    minutes = sum(module['minutes'] for module in modules.values())
    kind = 'a lesson' if len(modules) == 1 else f'a course of {len(modules)} modules'
    return f'{kind}, {minutes} minutes'


def _framed(found: _Training, level) -> dict[str, str]:
    """What a blueprint's frame says: who it is for, why and how long."""
    text = found.text(workspace.qualify('blueprint', level)) or ''
    stated = (line.partition(':') for line in _headed(text).get('frame', '').splitlines())
    return {key.strip().lower(): _line(value) for key, _, value in stated if value.strip()}


def _about(found: _Training, report: dict) -> list[str]:
    count = len(report['limitations'])
    where = 'under "Open gaps and limitations"'
    if not report['ready']:
        lines = [f'This training is not ready yet. What is still to do is listed {where}.']
    elif count:
        lines = [f"This training is ready, with {count} limitation{'' if count == 1 else 's'} "
                 f'listed {where}.']
    else:
        lines = ['This training is ready.']
    intake = _headed(training.read(found.root, 'intake.md') or '')
    # Each level's blueprint says who that level is for, so only a plain training's stands
    # in for an answer intake does not have.
    frame = {} if found.session['levels'] else _framed(found, None)
    stated = [('For', intake.get('audience') or frame.get('audience')),
              ('Purpose', intake.get('purpose') or frame.get('purpose')),
              ('Topic', intake.get('topic'))]
    lines += ['', *(f'- **{label}:** {_line(value)}' for label, value in stated
                    if _line(value))]
    if found.session['levels']:
        lines.append('- **Levels:** ' + ', '.join(found.session['levels']))
        for level in found.levels:
            who = _framed(found, level).get('audience')
            lines.append(f'  - **{level}:** {_size(found.blueprints[level])}'
                         + (f'. For {who}' if who else ''))
    else:
        lines.append(f'- **Size:** {_size(found.blueprints[None])}')
    return lines


# --- 2. objectives -------------------------------------------------------------------------

def _objectives(found: _Training, level) -> list[str]:
    parsed = found.blueprints[level]
    if not parsed or not parsed['objectives']:
        return ['The blueprint is not written yet, so there are no objectives to list.']
    return [f"- {_line(objective['text'])}" for objective in parsed['objectives'].values()]


# --- 3. what is here -----------------------------------------------------------------------

def _files(found: _Training) -> list[str]:
    lines = ['| What | File | Status | Review |', '| --- | --- | --- | --- |']
    for name, state in found.status['artifacts'].items():
        file = found.file(name)
        if name == 'research' and (found.root / workspace.RESEARCH_COPY).is_file():
            file = workspace.RESEARCH_COPY      # the copy that was approved, kept in the open
        there = (found.root / file).is_file() and state not in ('skipped', 'not-started')
        status = desk.WORDS[state]
        approved = (found.session['artifacts'].get(name) or {}).get('approved')
        if state == 'approved' and approved:
            status += f" on {str(approved.get('at'))[:10]}"
        review = workspace.review_file(name)
        reviewed = (found.root / review).is_file()
        cells = (_cell(desk.named(name)), _link(file, file) if there else NONE, status,
                 _link('its review', review) if reviewed else NONE)
        lines.append('| ' + ' | '.join(cells) + ' |')
    return lines


# --- 4. copies -----------------------------------------------------------------------------

def _made(found: _Training, name: str | None = None) -> list[dict]:
    """The copies that are made and can be pointed to: all of them, or one file's."""
    return [entry for entry in found.copies
            if entry.get('state') == 'made' and isinstance(entry.get('link'), str)
            and isinstance(entry.get('artifact'), str)
            and (entry.get('kind') == 'word' or entry['link'].startswith('https://'))
            and name in (None, entry['artifact'])]


def _copies(found: _Training) -> list[str]:
    made = _made(found)
    lines = [f"- {workspace.sentence(workspace.label(entry['artifact']))}, as a "
             + (f"Google Doc: {_link('open it', entry['link'])}" if entry['kind'] == 'google'
                else f"Word file: {_link(entry['link'], entry['link'])}") for entry in made]
    if not found.copies:
        lines = ['No Google Docs or Word files were asked for.']
    elif len(made) < len(found.copies):
        lines += [*([''] if made else []), 'A copy that is missing or out of date is not '
                  'listed here. Why is under "Open gaps and limitations".']
    if found.left('yoodli') is None and found.left('brief') is None:
        for level in found.levels:
            brief = workspace.qualify('brief', level)
            if (found.root / found.file(brief)).is_file() and not _made(found, brief):
                lines += ['', f'The Yoodli handoff is incomplete: {workspace.label(brief)} '
                          'has no current copy to upload. Until it has, you can make one '
                          f'yourself: copy the text of {_linked(found, found.file(brief))} '
                          'into a Word file or a Google Doc, and upload that.']
    if made and found.supplied():
        lines += ['', 'The research used documents that were supplied. A copy holds '
                  'everything its file does, so read it before sharing it outside your '
                  'organisation.']
    return lines


# --- 5. coverage ---------------------------------------------------------------------------

def _guide(found: _Training, level, parsed: dict):
    text = found.text(workspace.qualify('document', level))
    if found.left('document') or text is None:
        return found.left('document') or 'not written'
    claimed = set(checks.tagged(checks.COVERS, text, checks.COVERED_ID))
    return {objective: 'yes' if objective in claimed else 'no'
            for objective in parsed['objectives']}


def _deck(found: _Training, level, parsed: dict):
    name = workspace.qualify('deck', level)
    if found.left('deck') or found.status['artifacts'][name] == 'not-started':
        return found.left('deck') or 'not made'
    outcome = found.outcome(workspace.qualify('deck.coverage', level))
    if outcome is None or outcome['status'] == 'unavailable':
        return 'not reviewed'       # or reviewed before the deck or the blueprint changed
    slides = found.session['artifacts'][name]['reviewed_coverage']['objectives']
    return {objective: _slides(slides.get(objective)) for objective in parsed['objectives']}


def _slides(numbers) -> str:
    if not numbers:
        return 'no'
    return ('slide ' if len(numbers) == 1 else 'slides ') + ', '.join(map(str, numbers))


def _practice(found: _Training, level, parsed: dict):
    report = found.checked['practice']
    report = report.get(level) if found.session['levels'] else report
    if found.left('scenario') or not report:
        return found.left('scenario') or 'not known', None
    return ({objective: 'yes' if objective in report['exercised'] else 'no'
             for objective in parsed['objectives']}, report['basis'])


def _coverage(found: _Training, level) -> list[str]:
    parsed = found.blueprints[level]
    if not parsed or not parsed['objectives']:
        return ['The blueprint is not written yet, so there is no coverage to show.']
    guide, deck = _guide(found, level, parsed), _deck(found, level, parsed)
    practice, basis = _practice(found, level, parsed)
    source, means = BASIS.get(basis, ('', ''))
    lines = ['| Objective | Guide (declared) | Deck (reviewed) | Practice (exercised'
             + (f', {source}' if source else '') + ') |', '| --- | --- | --- | --- |']
    for ident, objective in parsed['objectives'].items():
        cells = [column if isinstance(column, str) else column[ident]
                 for column in (guide, deck, practice)]
        lines.append(f"| {_cell(ident + ': ' + objective['text'])} | "
                     + ' | '.join(cells) + ' |')
    lines += ['', '- Declared: a section of the guide says it teaches the objective. '
              'Whether it does is for a reader to judge.',
              '- Reviewed: the slides recorded for the objective when the deck was read '
              'against the blueprint.']
    if means:
        lines.append(f'- Exercised: {means}.')
    return lines


# --- 6. open gaps and limitations ----------------------------------------------------------

def _gaps(found: _Training, level) -> list[str]:
    parsed = found.blueprints[level]
    if parsed is None:
        return ['The blueprint is not written yet.']
    return parsed['open_gaps'].strip().splitlines() or ['The blueprint lists none.']


def _open(found: _Training, report: dict) -> list[str]:
    lines = []
    if not report['ready']:
        lines += ['### Still to do', '', *(f'- {reason}' for reason in report['blocking']), '']
    lines += ['### Open gaps', '']
    for level in found.levels:
        lines += [*([] if level is None else [f'**Level {level}**', '']),
                  *_gaps(found, level), '']
    return [*lines, '### Limitations', '',
            *([f'- {reason}' for reason in report['limitations']] or ['None.'])]


# --- 7. using the scenarios ----------------------------------------------------------------

def _scenarios(found: _Training) -> list[str]:
    left = found.left('scenario')
    if left:
        return ['The practice stage was left out of this training, so it has no scenarios.'
                if left == desk.WORDS['skipped']
                else 'The scenarios could not be made. Why is under "Open gaps and '
                     'limitations".']
    written = found.status['scenarios']['found']
    if not written:
        return ['No scenario has been written yet.']
    lines, laid_out = [], []
    for name, file in written.items():
        scenario = checks.parse_scenario(training.read(found.root, file) or '')
        level = workspace.split(name)[1]
        lines.append(f"- {_link(file, file)}: {_line(scenario['title']) or 'untitled'} "
                     f"({scenario['mode']}" + (f', level {level})' if level else ')'))
        yoodli = name.replace('scenario:', 'yoodli:', 1)
        if (yoodli in found.status['files']
                and (found.root / found.file(yoodli)).is_file()):
            laid_out.append(_link(found.file(yoodli), found.file(yoodli)))
    lines += ['', 'Each works with any AI that can play a role: give it the scenario file '
              'and ask it to play the part the file describes.']
    if found.left('brief'):
        lines[-1] += (' This training has no brief, so there is no reference file to give '
                      'it with the scenario.')
    elif found.session['levels']:
        lines[-1] += ' Give it the brief of the same level too, as its reference for facts.'
    else:
        lines[-1] += (f" Give it the brief too, {_linked(found, found.file('brief'))}, as "
                      'its reference for facts.')
    if 'yoodli' in found.session['settings']['stages']:
        lines.append('')
        if found.left('yoodli'):
            lines.append('The Yoodli scenarios could not be made. Why is under "Open gaps '
                         'and limitations".')
        elif not laid_out:
            lines.append('No scenario has been laid out for Yoodli yet.')
        else:
            lines.append('For Yoodli, each scenario is also laid out in Yoodli\'s own fields: '
                         + ', '.join(laid_out) + '. Building the roleplay in Yoodli\'s '
                         'Builder, pasting each block into the field its heading names, is '
                         'the baseline.')
            if training.PROVISIONAL in found.checked['warnings']:
                lines[-1] += (' Yoodli\'s limits are taken from its public help pages and '
                              'are provisional until you confirm that a paste was accepted.')
    return lines


# --- 8. research ---------------------------------------------------------------------------

def _research(found: _Training) -> list[str]:
    summary = found.status['research']
    report = next((file for file in (workspace.RESEARCH_COPY, found.file('research'))
                   if (found.root / file).is_file()), None)
    if summary is None or report is None:
        return ['No research has been recorded yet.']
    counts = summary['findings']
    known = [f'{counts[status]} {words}' for status, words in FINDINGS if counts.get(status)]
    known += [f'{count} {status}' for status, count in counts.items()
              if status not in dict(FINDINGS)]
    at = summary['approved_at']
    lines = [f"- The report: {_link(report, report)}",
             f'- Approved on {at[:10]}.' if at else '- Not approved yet.',
             '- Findings: ' + (', '.join(known) or 'none yet') + '.']
    supplied = len(found.supplied())
    record = workspace.research_record(found.root) or {}
    if supplied:
        lines.append(f"- Sources: {supplied} document{'' if supplied == 1 else 's'} that "
                     + ('was' if supplied == 1 else 'were') + ' supplied'
                     + (', and nothing else' if record.get('scope') == 'supplied-only'
                        else ', and the public web')
                     + '. The documents themselves stay on the computer they were added '
                     'on. The report quotes passages from them.')
    elif record.get('scope') == 'public-web':
        lines.append('- Sources: the public web.')
    return lines


# --- the page ------------------------------------------------------------------------------

def _index(found: _Training, report: dict) -> str:
    """README.md: the eight sections of the package reference, in its order."""
    parts = (_blocks(found, _objectives), _files(found), _copies(found),
             _blocks(found, _coverage), _open(found, report), _scenarios(found),
             _research(found))
    lines = [f"# {_line(found.session['title'])}", '', *_about(found, report)]
    for heading, part in zip(SECTIONS, parts):
        lines += ['', f'## {heading}', '', *part]
    return '\n'.join([*lines, '', DERIVED]) + '\n'
