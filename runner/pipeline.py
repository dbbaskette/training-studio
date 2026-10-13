"""The pipelines the runner walks: a training from the form to its index, and research.

What a caller needs to know
---------------------------
    form = pipeline.check_form(sent)             # what the page's form may say
    root = pipeline.create(space, form)          # a training, through the core's own init
    found = pipeline.survey(root, run, ...)      # where it is, worked out from its files
    found.next                                   # the one thing to do now
    work = pipeline.work(root, found, step, ...) # what a worker is told and given
    pipeline.keep_draft(root, step, handed, ...) # save a checked draft through the core

- TRAINING and RESEARCH are the pipelines as data: each step is code the runner runs, a
  job for an agent, or something a person decides. `steps(levels, ...)` lays a training's
  out in order. Intake and research are done once. Every level's blueprint is drafted
  before the first is put to the person. Everything after that is done for one level at a
  time, lowest first: the guide, the brief, each practice scenario, each Yoodli scenario.
  The index is written last, once.
- `survey` remembers nothing. It reads the core's record, the requests a person made, the
  research record and the training's files, and says which steps are done. The next step
  is the first that is not. `run` is the training's run record, which holds what the files
  cannot say: which research run the approved plan was handed to, which questions a
  person's request has researched again, how each try at a step went, which scenario files
  the runner drafted, which copies it has tried to make, and whether the person has said
  their documents are all added. `copies` is what `copies.wanted` returned and `supplied`
  what `documents.listed` returned; both are read, never called, here.
- A stage the person left out, or that could not be made, has no steps. Something made
  from a version of its inputs that has since changed is made again, and comes back to
  its gate: a blueprint, a guide, a brief or a Yoodli scenario. Nothing is ever accepted
  as it is here.
- A practice scenario is drafted only when the blueprint's practice plan names it and it
  has no file. A file the person wrote is taken in as it is. Only a request from them has
  a worker lay it out, in their own words.
- The slide deck is not made here. A training that wants one stops with `next.kind`
  `'deck'` when the deck is all that is left; the index is written once the deck is
  approved in a conversation, or left out.
- A training is made in `page` approval mode, so nothing here can approve a draft. The
  two exceptions are the person's own choices, typed into the form: intake, which the core
  lets anyone record, and leaving the deck out when the form says no deck.
- Sentences a person will read never say "artifact", "stale" or "lineage".
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field, replace
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
import checks
import home
import sync_guidance
import workspace
from workspace import WorkspaceError

from runner import briefs, gitstate, settings

ATTEMPTS = 3            # tries at one step: the first, and two more with the reason added
QUESTIONS = 3           # questions the workers on one step may put to the person
PLAN = workspace.SHARED['research-plan'][0]
REPORT = workspace.SHARED['research'][0]
INDEX = 'README.md'
# Written on a computer when its person says their documents are all added. Like the
# documents it sits beside, it is never shared, so each computer is told for itself.
ADDED = 'sources/.all-added'
MADE = ('draft', 'stale', 'approved')
CURRENT = ('draft', 'approved')     # made from what its inputs are now
UNRESOLVED = ('insufficient', 'unavailable')
SCOPE = 'public-web'
SCOPES = ('public-web', 'supplied-only', 'both')
SOURCES = {'public-web': 'Public web', 'supplied-only': 'Your documents only',
           'both': 'The public web and your documents'}
NO_DECK = 'No deck was chosen when this training was started.'
DECK_LEFT = ('Everything but the slide deck is made. The deck is not automated yet: make it '
             'in a conversation with your assistant, or leave it out.')
DECK_AGAIN = ('Everything but the slide deck is settled. The deck is not approved as it '
              'stands, and decks are not automated yet: finish it in a conversation with '
              'your assistant, or leave it out.')
DECLARED = ('Coverage is declared: each section says in a comment what it teaches, and the '
            'check reads only those comments. Whether the prose teaches it is for you to '
            'read.')
PROVISIONAL = ("Yoodli's limits are provisional: they come from its public help pages and "
               'have not all been confirmed in its live builder.')
LIMITS = {'title': 120, 'topic': 2000, 'audience': 2000, 'purpose': 500, 'time_limit': 200,
          'brand': 200}
HEADINGS = ('Topic', 'Levels', 'Brief', 'Audience', 'Purpose', 'Source scope', 'Time limit')
GATE = ('Your review of {it}', 'Waiting for your review of {it}')
COPIES = ('Make the copies of {it}', 'Making the copies of {it}')

# The training pipeline: stage, step, kind, and what the step does in the words a list
# shows and the words a sentence uses. {it} is what the step is about.
TRAINING = (
    ('intake', 'intake', 'code', 'Record your answers', 'Recording your answers'),
    ('research-plan', 'documents', 'gate', 'Add your documents',
     'Waiting for your documents'),
    ('research-plan', 'research-plan', 'agent', 'Draft {it}', 'Drafting {it}'),
    ('research-plan', 'gate:research-plan', 'gate', *GATE),
    ('research', 'research-start', 'code', 'Hand the approved questions to research',
     'Handing the approved questions to research'),
    ('research', 'research', 'agent', 'Research each question', 'Researching the questions'),
    ('research', 'research-report', 'code', 'Write {it}', 'Writing {it}'),
    ('research', 'gate:research', 'gate', *GATE),
    ('blueprint', 'blueprint', 'agent', 'Draft {it}', 'Drafting {it}'),
    ('blueprint', 'gate:blueprint', 'gate', *GATE),
    ('document', 'document', 'agent', 'Write {it}', 'Writing {it}'),
    ('document', 'gate:document', 'gate', *GATE),
    ('document', 'copies:document', 'code', *COPIES),
    ('brief', 'brief', 'agent', 'Write {it}', 'Writing {it}'),
    ('brief', 'gate:brief', 'gate', *GATE),
    ('brief', 'copies:brief', 'code', *COPIES),
    ('scenario', 'scenario', 'agent', 'Draft {it}', 'Drafting {it}'),
    ('scenario', 'gate:scenario', 'gate', *GATE),
    ('yoodli', 'yoodli', 'agent', 'Lay out {it}', 'Laying out {it}'),
    ('yoodli', 'gate:yoodli', 'gate', *GATE),
    ('yoodli', 'copies:yoodli', 'code', *COPIES),
    ('deck', 'deck', 'gate', 'The slide deck, made in a conversation or left out',
     'Finishing everything but the slide deck'),
    ('package', 'package', 'code', 'Write the index', 'Writing the index'),
)
# How the rows are laid out: once for the training, once for each level, and within a level
# once for each practice scenario.
EACH_LEVEL = ('document', 'brief', 'scenario', 'yoodli')
EACH_SCENARIO = ('scenario', 'yoodli')
LAST = ('deck', 'package')
STAGES = tuple(stage for stage in workspace.SKIPPABLE if stage not in workspace.OPTIONAL)
# A scenario the person wrote: taken in as it is, and laid out only when they ask.
OWN = ('Take in {it}, as you wrote it', 'Taking in {it}, as you wrote it')
LAID = ('Lay out {it}, in your own words', 'Laying out {it}, in your own words')
# The research pipeline: the steps above that make it up, and what each one runs.
RESEARCH = (
    ('research-start', 'harness-research plan, with the approved plan'),
    ('research', 'one worker for each question, and harness-research record for each '
                 'finding, one at a time'),
    ('research-report', 'harness-research status, then the report saved through the core'),
)
RESEARCHED = ('research-plan', *(name for name, _ in RESEARCH))
ARTIFACTS = {'research-plan': 'research-plan', 'gate:research-plan': 'research-plan',
             'research-report': 'research', 'gate:research': 'research',
             'blueprint': 'blueprint', 'gate:blueprint': 'blueprint',
             'document': 'document', 'gate:document': 'document',
             'copies:document': 'document', 'brief': 'brief', 'gate:brief': 'brief',
             'copies:brief': 'brief', 'scenario': 'scenario', 'gate:scenario': 'scenario',
             'yoodli': 'yoodli', 'gate:yoodli': 'yoodli', 'copies:yoodli': 'yoodli'}
# What each check looks at, for the review a gate shows. Keyed by the kind of file and the
# last part of the check's name.
CHECKED = {
    ('research-plan', 'items'): 'The questions are in the form research takes, each with '
                                'an ID of its own.',
    ('blueprint', 'structure'): 'The headings, the IDs and the practice plan are in the '
                                'shape a blueprint needs.',
    ('blueprint', 'objectives'): 'Every objective is in a module and has an assessment '
                                 'entry.',
    ('blueprint', 'key-points'): 'Every key point cites a finding or is marked unsupported, '
                                 'and every module has an example.',
    ('blueprint', 'citations'): 'Every finding cited exists and has the verdict its use '
                                'needs.',
    ('document', 'coverage'): 'Every objective and every supported key point is named in a '
                              'coverage comment, and no unsupported one is.',
    ('brief', 'sections'): 'The title and the eight numbered sections are there, in order, '
                           'and none is empty.',
    ('brief', 'findings'): 'Each evidence section names findings that exist and have the '
                           'verdict it needs.',
    ('scenario', 'sections'): 'The title, the sections a scenario needs, the list of '
                              'success criteria and the mode.',
    ('yoodli', 'fields'): 'Every field Yoodli needs is there, with a type, personas and '
                          'goals that fit.',
    ('yoodli', 'limits'): "Each field is within Yoodli's limit and states its real length.",
    ('yoodli', 'mapping'): 'Every success criterion is carried by a goal, and every '
                           'objective a goal names is in the blueprint.',
}


@dataclass(frozen=True)
class Step:
    """One step of a training."""
    id: str
    kind: str                     # 'code', 'agent' or 'gate'
    label: str                    # what it does: "Draft the research plan"
    doing: str                    # the same as it happens: "Drafting the research plan"
    stage: str                    # the core's stage it belongs to
    artifact: str | None = None   # what it makes or puts to the person, by the core's name


@dataclass(frozen=True)
class Next:
    """The one thing to do now."""
    kind: str                         # 'agent', 'code', 'gate', 'wait', 'documents', 'deck',
    #                                   'done' or 'stuck'
    step: Step | None = None
    request: dict | None = None       # what the person asked for, when the step answers it
    questions: tuple[str, ...] = ()   # research: the questions to work on now
    why: str = ''                     # 'stuck': what is wrong, in a sentence


@dataclass(frozen=True)
class Research:
    """Where the research stands, read from its record."""
    handed: bool                  # harness-research holds the approved plan
    run: str | None               # the research run findings are recorded in
    questions: dict               # question ID to the question, in the plan's order
    queries: dict                 # question ID to its public search words, or None
    verdicts: dict                # question ID to its verdict, or 'pending'
    todo: tuple[str, ...]         # the questions to work on now
    saved: bool                   # the report on disk is the one the core recorded

    @property
    def unread(self) -> list[str]:
        return [ident for ident, verdict in self.verdicts.items() if verdict == 'pending']

    @property
    def unresolved(self) -> list[str]:
        return [ident for ident, verdict in self.verdicts.items() if verdict in UNRESOLVED]


@dataclass(frozen=True)
class Survey:
    """Where a training is, worked out from its files."""
    session: dict
    state: dict                   # every file's status, as the core computes it
    steps: tuple[Step, ...]
    done: frozenset
    next: Next
    research: Research
    asked: dict                   # open requests, by what each is about
    practice: dict = field(default_factory=dict)   # each level's scenarios, by ID
    own: frozenset = frozenset()  # the scenarios a person wrote, by the core's name
    copies: tuple = ()            # every copy the training asks for, as `copies.wanted` gave
    scope: str = SCOPE            # where its research may look


# --- the form ----------------------------------------------------------------------------

def _words(sent: dict, name: str, needed: bool) -> str | None:
    value = sent.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        if needed:
            raise WorkspaceError(f'A training needs {_a(name)}.')
        return None
    if not isinstance(value, str) or len(value) > LIMITS[name]:
        raise WorkspaceError(f'Give the {name.replace("_", " ")} as text of at most '
                             f'{LIMITS[name]:,} characters.')
    return value.strip()


def _a(name: str) -> str:
    return ('an ' if name[0] in 'aeiou' else 'a ') + name.replace('_', ' ')


def _listed(sent: dict, name: str) -> list[str]:
    value = sent.get(name)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise WorkspaceError(f'Give {name} as a list.')
    return value


def check_form(sent: dict) -> dict:
    """The form's answers, once each makes sense. Refuses with a sentence for a person."""
    form = {name: _words(sent, name, name in ('title', 'topic', 'audience', 'purpose'))
            for name in LIMITS}
    form['levels'] = workspace.check_levels(_listed(sent, 'levels'))
    form['copies'] = workspace.check_copies(_listed(sent, 'copies'))
    form['brief_kind'] = sent.get('brief_kind') or 'product'
    workspace.check_choice(form['brief_kind'], workspace.BRIEF_KINDS, 'The brief kind')
    form['deck_target'] = sent.get('deck_target')
    workspace.check_choice(form['deck_target'], workspace.DECK_TARGETS, 'The deck target')
    form['source_scope'] = sent.get('source_scope') or SCOPE
    workspace.check_choice(form['source_scope'], SCOPES, 'The source scope')
    if not isinstance(sent.get('yoodli', False), bool):
        raise WorkspaceError('Say whether Yoodli scenarios are wanted with true or false.')
    form['yoodli'] = sent.get('yoodli', False)
    form['agent'] = None if sent.get('agent') is None else settings.check_agent(sent['agent'])
    form['model'] = settings.check_model(sent.get('model'))
    return form


def gates(form: dict) -> int:
    """The fewest times a training made from this form asks for a decision: the research
    plan and the research, and a blueprint, a guide and a brief for each level. Each
    practice scenario adds one, and nobody knows how many there are until a blueprint
    names them."""
    return 2 + 3 * max(1, len(form['levels']))


def intake_text(form: dict) -> str:
    """The form's answers as intake.md: the headings intake has, and nothing else."""
    answers = {
        'Topic': form['topic'],
        'Levels': ', '.join(form['levels']) or 'None',
        'Brief': form['brief_kind'],
        'Audience': form['audience'],
        'Purpose': form['purpose'],
        'Source scope': SOURCES[form['source_scope']],
        'Time limit': form['time_limit'] or 'None given',
    }
    return '\n'.join(f'## {heading}\n\n{answers[heading]}\n' for heading in HEADINGS)


def answers(root: Path) -> dict:
    """What intake.md says under each of its headings, keyed by the heading in lower case."""
    try:
        text = (root / 'intake.md').read_text(encoding='utf-8')
    except OSError:
        return {}
    found, heading = {}, None
    for line in text.splitlines():
        if line.startswith('## '):
            heading = line[3:].strip().lower()
            found[heading] = []
        elif heading is not None:
            found[heading].append(line)
    return {heading: '\n'.join(lines).strip() for heading, lines in found.items()}


def create(space: gitstate.Workspace, form: dict) -> Path:
    """Start a training in the workspace from the form: the core's own init, in `page`
    approval mode, with intake written from the answers and approved as the person's own.
    A form that says no deck leaves the deck stage out, through the core, as their choice."""
    ident = workspace.slugify(form['title'])
    root = space.training(ident)
    if root.exists():
        raise WorkspaceError(f'This workspace already has a training in {space.folder}/'
                             f'{ident}. Give this one a different title.')
    root.mkdir(parents=True)
    try:
        workspace.init(root, form['title'], form['levels'], form['brief_kind'],
                       form['deck_target'], form['brand'], form['yoodli'], form['copies'],
                       approval='page')
        sync_guidance.adopt(root)
        if form['deck_target'] is None:
            workspace.skip(root, 'deck', reason=NO_DECK, by='page')
        workspace.write_atomic(root / 'intake.md', intake_text(form).encode('utf-8'))
        workspace.save(root, 'intake', built=True)
        workspace.approve(root, 'intake', by='page')
        workspace.checkpoint(root, stage='research-plan',
                             next_step='Draft the research plan')
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)  # a training is made whole or not at all
        raise
    home.remember(root, form['title'], form['levels'])
    return root


# --- the steps ---------------------------------------------------------------------------

def _step(stage: str, ident: str, kind: str, label: str, doing: str,
          level: str | None = None, scenario: str | None = None) -> Step:
    base = ARTIFACTS.get(ident)
    if scenario is not None:
        base, ident = f'{base}:{scenario}', f'{ident}:{scenario}'
    artifact = None if base is None else workspace.qualify(base, level)
    it = workspace.label(artifact) if artifact else ''
    return Step(workspace.qualify(ident, level), kind, label.format(it=it),
                doing.format(it=it), stage, artifact)


def steps(levels, stages=STAGES, practice=None, copies=(), documents: bool = False,
          own=(), laid=()) -> tuple[Step, ...]:
    """Every step of a training, in the order it is walked.

    `stages` are the stages it wants, of those a person may leave out. `practice` gives
    each level's scenario IDs, once a blueprint or a file names them. `copies` names what
    a copy is kept of, and `documents` says the person supplies documents. `own` are the
    scenarios a person wrote, and `laid` those of them they have asked to have laid out.
    """
    listed, practice = [], practice or {}

    def lay(row: tuple, level: str | None = None) -> None:
        stage, ident = row[0], row[1]
        for scenario in practice.get(level, ()) if stage in EACH_SCENARIO else [None]:
            step = _step(*row, level, scenario)
            if ident.startswith('copies:') and step.artifact not in copies:
                continue
            if ident == 'scenario' and step.artifact in (*own, *laid):
                words = LAID if step.artifact in laid else OWN
                step = _step(stage, ident, 'agent' if step.artifact in laid else 'code',
                             *words, level, scenario)
            listed.append(step)

    for row in TRAINING:
        # Row by row, so every level's blueprint is drafted before the first gate 3.
        if row[0] in (*EACH_LEVEL, *LAST) or (row[1] == 'documents' and not documents):
            continue
        for level in (levels or [None]) if row[0] == 'blueprint' else [None]:
            lay(row, level)
    for level in levels or [None]:
        for row in TRAINING:
            if row[0] in EACH_LEVEL and row[0] in stages:
                lay(row, level)
    for row in TRAINING:
        if row[0] == 'package' or (row[0] == 'deck' and 'deck' in stages):
            lay(row)
    return tuple(listed)


def gate_for(artifact: str) -> Step:
    """The gate that puts one file to the person."""
    stage = workspace.split(artifact)[0].partition(':')[0]
    it = workspace.label(artifact)
    return Step(f'gate:{artifact}', 'gate', GATE[0].format(it=it), GATE[1].format(it=it),
                stage, artifact)


def wanted(session: dict) -> list[str]:
    """The stages a training wants and can have, of those a person may leave out."""
    return [stage for stage in session['settings']['stages']
            if stage not in session['unavailable']]


def planned(text: str | None, ident: str) -> str | None:
    """What a blueprint's practice plan says of one scenario: its line, without the ID."""
    section = None
    for line in (text or '').splitlines():
        if line.startswith('## '):
            section = line[3:].strip().lower()
        elif section == 'practice plan' and line.startswith(f'- {ident}:'):
            return line.partition(':')[2].strip()
    return None


def practice(root: Path, session: dict) -> dict:
    """Each level's practice scenarios, in the order they are worked on: those its
    blueprint's practice plan names, with the mode and the objectives it gives each, then
    any other scenario file the person has. Keyed by level, or None for a plain training;
    empty when scenarios are not wanted."""
    if 'scenario' not in wanted(session):
        return {}
    found, listed = workspace.scenarios(root, session)['found'], {}
    for level in session['levels'] or [None]:
        text = _read(root / workspace.artifact(
            root, session, workspace.qualify('blueprint', level))['file'])
        named = {entry['id']: {'mode': entry['mode'], 'objectives': entry['objectives'],
                               'plan': planned(text, entry['id'])}
                 for entry in checks.parse_blueprint(text or '')['practice']}
        for name in found:
            base, its = workspace.split(name)
            if its == level:
                named.setdefault(base.partition(':')[2],
                                 {'mode': None, 'objectives': [], 'plan': None})
        listed[level] = named
    return listed


# --- where a training is -----------------------------------------------------------------

def tries(run: dict | None, step: str) -> dict:
    """What the run record holds for one step: its tries, and how many have failed in a
    row since the last one that worked or the last fresh start."""
    kept = ((run or {}).get('steps') or {}).get(step)
    return kept if isinstance(kept, dict) else {'failed': 0, 'attempts': []}


def spent(run: dict | None, step: str) -> bool:
    """True when a step has failed as often as it may."""
    return tries(run, step).get('failed', 0) >= ATTEMPTS


def _named(ident: str, note: str | None) -> bool:
    """True when a person's note names a research question by its ID."""
    return bool(note) and re.search(
        rf'(?<![a-z0-9-]){re.escape(ident)}(?![a-z0-9-])', note.lower()) is not None


def _open(verdicts: dict, note: str | None) -> list[str]:
    """The questions a person's note names, and those with no settled answer."""
    return [ident for ident, verdict in verdicts.items()
            if _named(ident, note) or verdict in ('pending', *UNRESOLVED)]


def again(root: Path, run: dict | None, request: dict) -> list[str]:
    """The questions a request about the research has researched again: those its note
    names and those with no settled answer, or every question when there are neither.
    Worked out once, when the request is made, and kept in the run record."""
    found = research(root, workspace.load(root), run, None)
    return _open(found.verdicts, request.get('note')) or list(found.questions)


def research(root: Path, session: dict, run: dict | None, request: dict | None) -> Research:
    """Where the research stands. Nothing is run: the record is read as it lies."""
    plan = home.read_json(root / PLAN, None)
    record = workspace.research_record(root)
    items = [item for item in (plan.get('items') if isinstance(plan, dict) else None) or []
             if isinstance(item, dict) and isinstance(item.get('id'), str)]
    questions = {item['id']: str(item.get('question') or '') for item in items}
    queries = {item['id']: item.get('public_query') for item in items}
    handed_to = (run or {}).get('research') or {}
    handed = bool(record and record.get('run') and record['run'] == handed_to.get('run')
                  and handed_to.get('plan') == workspace.sha256_file(root / PLAN))
    index = workspace.findings_index(record) if handed else {}
    verdicts = {ident: index.get(ident, 'pending') for ident in questions}
    asked = handed_to.get('again') or {}
    if not handed:
        todo = []
    elif request is None:
        todo = [ident for ident in questions if verdicts[ident] == 'pending']
    elif asked.get('at') == request.get('at'):
        todo = [ident for ident in questions if ident in asked.get('left', [])]
    else:
        todo = _open(verdicts, request.get('note'))
    entry = session['artifacts'].get('research') or {}
    saved = (bool(entry.get('sha256'))
             and entry['sha256'] == workspace.sha256_file(root / REPORT))
    return Research(handed, record.get('run') if handed else None, questions, queries,
                    verdicts, tuple(ident for ident in todo
                                    if not spent(run, f'research:{ident}')), saved)


@dataclass(frozen=True)
class _Seen:
    """What says whether a step is done: the files, the records and what a person asked."""
    root: Path
    session: dict
    state: dict
    asked: dict
    research: Research
    own: frozenset          # the scenarios a person wrote
    copies: dict            # each file a copy is kept of, with its copies
    tried: dict             # each of those, with the approved version copies were tried for
    supplied: bool          # the person's documents are all added, and here if needed


def _taken_in(seen: _Seen, name: str) -> bool:
    """True when a scenario a person wrote is recorded as it now is, and nothing is asked
    of it."""
    entry = seen.session['artifacts'].get(name) or {}
    file = seen.root / workspace.artifact(seen.root, seen.session, name)['file']
    return (name not in seen.asked and bool(entry.get('sha256'))
            and entry['sha256'] == workspace.sha256_file(file))


def _copied(seen: _Seen, name: str) -> bool:
    """True when every copy of an approved file is made, or was tried for this version: a
    copy that cannot be made never holds a training up."""
    approved = (seen.session['artifacts'].get(name) or {}).get('approved') or {}
    return (all(entry['state'] == 'made' for entry in seen.copies.get(name, ()))
            or seen.tried.get(name) == approved.get('sha256'))


def _done(step: Step, seen: _Seen) -> bool:
    state, asked, found = seen.state, seen.asked, seen.research
    if step.id == 'intake':
        return state['intake'] == 'approved'
    if step.id == 'documents':
        return seen.supplied
    if step.id == 'deck':
        return all(state.get(workspace.qualify('deck', level)) == 'approved'
                   for level in seen.session['levels'] or [None])
    if step.id == 'package':
        return seen.session['stage'] == 'done' and (seen.root / INDEX).is_file()
    made = state.get(step.artifact, 'not-started')
    if step.kind == 'gate':
        return made == 'approved'
    if step.id.startswith('copies:'):
        return made == 'approved' and _copied(seen, step.artifact)
    if step.stage == 'research':
        if state['research'] == 'approved' and 'research' not in asked:
            return True
        if step.id == 'research-start':
            return found.handed
        if step.id == 'research':
            return found.handed and not found.todo
        return found.handed and found.saved and 'research' not in asked
    if step.artifact in seen.own:
        return _taken_in(seen, step.artifact)
    # The questions are made from the person's own answers, so questions those answers
    # have dated are put to the person. Everything later is made again.
    kept = MADE if step.id == 'research-plan' else CURRENT
    return made in kept and step.artifact not in asked


def _supplied(root: Path, given: dict | None, supplied, needed: bool) -> bool:
    """True when the person has said their documents are all added, and they are on this
    computer if research still has to read them. Documents are never shared, so a training
    opened on another computer has none until they are added, and said to be all, there."""
    if not given:
        return True
    here = (root / ADDED).is_file() and any(entry.get('readable') for entry in supplied)
    return bool(given.get('done')) and (not given.get('count') or here or not needed)


def survey(root: Path, run: dict | None = None, copies=(), supplied=()) -> Survey:
    """Where a training is and the one thing to do now, from its files and its run record.
    `copies` is what `copies.wanted` returned, and `supplied` what `documents.listed` did."""
    session, run = workspace.load(root), run or {}
    state = workspace.statuses(root, session)
    asked = {str(request.get('artifact')): request for request in session['requests']}
    found = research(root, session, run, asked.get('research'))
    named, given = practice(root, session), run.get('documents')
    drafted = set(run.get('drafted') or ())
    own = frozenset(name for name in workspace.scenarios(root, session)['found']
                    if name not in drafted) if named else frozenset()
    kept: dict[str, list] = {}
    for entry in copies:
        kept.setdefault(entry['artifact'], []).append(entry)
    listed = steps(session['levels'], wanted(session), named, kept, bool(given),
                   own - asked.keys(), own & asked.keys())
    seen = _Seen(root, session, state, asked, found, own, kept,
                 (run.get('copies') or {}).get('tried') or {}, True)
    needed = any(not _done(step, seen) for step in listed if step.id in RESEARCHED)
    seen = replace(seen, supplied=_supplied(root, given, supplied, needed))
    done = frozenset(step.id for step in listed if _done(step, seen))
    first = next((step for step in listed if step.id not in done), None)
    return Survey(session, state, listed, done, _next(first, session, state, asked, found),
                  found, asked, named, own, tuple(copies), (given or {}).get('scope') or SCOPE)


def _next(first: Step | None, session: dict, state: dict, asked: dict,
          found: Research) -> Next:
    if first is None:
        return Next('done')
    if first.id == 'intake':
        if state['intake'] == 'not-started':
            return Next('stuck', first, why='The answers this training was started from are '
                        'missing, so it cannot go on. Start a new training in its place.')
        first = gate_for('intake')  # someone changed the answers: they are put to the person
    if first.id in ('documents', 'deck'):
        return Next(first.id, first)  # a person's to do; the core has no gate for either
    if first.kind == 'gate':
        waiting = session.get('gate') == first.artifact and session.get('pending_question')
        return Next('wait' if waiting else 'gate', first)
    request = asked.get('research' if first.stage == 'research' else first.artifact)
    if first.kind == 'code':
        return Next('code', first, request)
    return Next('agent', first, request, found.todo if first.id == 'research' else ())


def deck_says(found: Survey) -> str:
    """What to say when the deck is all that is left."""
    begun = any(found.state.get(workspace.qualify('deck', level), 'not-started')
                != 'not-started' for level in found.session['levels'] or [None])
    return DECK_AGAIN if begun else DECK_LEFT


def unmade(found: Survey) -> list[dict]:
    """The copies of approved files that are not made, or are behind their files. A copy
    of something not approved yet is not one: there is nothing to make it from."""
    return [entry for entry in found.copies if entry['state'] != 'made'
            and found.state.get(entry['artifact']) == 'approved']


def copies_say(found: Survey) -> str:
    """What to say of the copies that keep a training from being ready, or nothing."""
    for level in found.session['levels'] or [None]:
        brief = workspace.qualify('brief', level)
        if 'yoodli' in wanted(found.session) and found.state.get(brief) == 'approved' \
                and upload(found.copies, brief)[0] is None:
            return (' Yoodli needs a copy of the brief to upload, and none is made. Try the '
                    'copies again.')
    return ' A copy this training asked for is not made. Try the copies again.' \
        if unmade(found) else ''


def finished_says(report: dict, found: Survey | None = None) -> str:
    """What to say of a training whose index is written. `report` is what `index.readiness`
    returned. One that is not ready because of a copy says so, and what to do."""
    def things(count: int, verb: bool = False) -> str:
        words = f'{count} thing{"" if count == 1 else "s"}'
        return words + ((' is' if count == 1 else ' are') if verb else '')

    if not report['ready']:
        return ('Everything is made, but this training is not ready yet: '
                f"{things(len(report['blocking']), verb=True)} in the way."
                + (copies_say(found) if found else ''))
    if not report['limitations']:
        return 'This training is finished. Nothing is left out or limited.'
    return (f"This training is finished, with {things(len(report['limitations']))} left "
            'out or limited.')


# --- what a worker is told ---------------------------------------------------------------

@dataclass(frozen=True)
class Work:
    """One job for a worker: what it is told, and what its tools are set up with."""
    guidance: str
    task: str
    profile: str
    prepared: dict      # what worker_tools.prepare takes
    name: str = ''      # the name a draft is handed back under


def _about(root: Path, session: dict) -> str:
    """What the training is about, who it is for and what it is for."""
    said = answers(root)
    levels = session['levels']
    lines = [f"Topic: {said.get('topic') or session['title']}",
             f"Audience: {said.get('audience') or 'not given'}",
             f"Purpose: {said.get('purpose') or 'not given'}",
             'Levels: ' + (', '.join(levels) if levels else 'none; this is one training'),
             'Kind of brief: ' + ('competitive; the topic names the two sides compared'
                                  if session['settings']['brief_kind'] == 'competitive'
                                  else 'product'),
             f"Time limit: {said.get('time limit') or 'none given'}"]
    return '\n'.join(lines)


def _again(request: dict | None, earlier: str | None, error: str | None,
           answered: list[dict], thing: str, dated: bool = False) -> str:
    """The part of a task that says why this job is being done again. `dated` says what
    the earlier draft was made from has changed since."""
    parts = []
    if request and request.get('kind') == 'revise':
        parts.append(f'You are revising an earlier draft. What the person asked for:\n\n'
                     f"{request.get('note') or ''}")
    elif request:
        note = f" They added:\n\n{request['note']}" if request.get('note') else ''
        parts.append(f'The person asked for {thing} to be made again from the start.{note}')
    elif dated and earlier:
        parts.append(f'What {thing} was made from has changed since the earlier draft, and '
                     'the person approved the change, so it is being made again. Keep what '
                     'still fits what your inputs say now, and change what does not.')
    if (request or dated) and earlier:
        parts.append(f'The earlier draft:\n\n{earlier}')
    if answered:
        asked = '\n\n'.join(f"Question: {item['question']}\nAnswer: {item['answer']}"
                            for item in answered)
        parts.append('A worker on this job asked the person before. Do not ask these '
                     f'again:\n\n{asked}')
    if error:
        parts.append(f'An earlier try at this job did not work: {error}\nTake care not to '
                     'end the same way.')
    return ''.join(f'\n\n{part}' for part in parts)


def _can_ask(answered: list[dict]) -> bool:
    return len(answered) < QUESTIONS


def _questions(text: str) -> str:
    """A research plan as its questions, one a line, or the text when it cannot be read."""
    try:
        return '\n'.join(f"- {item['id']}: {item['question']}"
                         for item in json.loads(text)['items'])
    except (ValueError, KeyError, TypeError):
        return text


def _titles(sources) -> str:
    return '\n'.join(f"- {source.get('title') or source.get('id')}" for source in sources)


def plan_work(root: Path, found: Survey, request: dict | None, error: str | None,
              answered: list[dict], sources=None) -> Work:
    """The job of drafting the research questions. `sources` is what `documents.sources`
    returned, for a training researched from documents the person supplied: the worker is
    told what they are, by title, and the plan it hands back lists them."""
    name, listed = 'research-plan', list((sources or ((), ()))[0])
    earlier = _read(root / PLAN)
    if found.scope == 'supplied-only':
        allowed = ('only the documents the person supplied. Ask what these can answer, and '
                   f'give no question any search words:\n{_titles(listed)}')
    elif listed:
        allowed = ('the public web, and these documents the person supplied. Ask what the '
                   f'documents can answer as well as what the web can:\n{_titles(listed)}')
    else:
        allowed = 'the public web.'
    task = ('Draft the research questions for this training.\n\n'
            f'{_about(root, found.session)}\n'
            f'Sources that may be used: {allowed}\n\n'
            f'Hand the questions back with submit_artifact under the name "{name}".'
            + _again(request, _questions(earlier) if earlier else None, error, answered,
                     'the questions'))
    scope = 'supplied-only' if found.scope == 'supplied-only' else SCOPE
    prepared = {'inputs': {'intake': _read(root / 'intake.md') or ''},
                'artifacts': {name: {'kind': 'research-plan', 'scope': scope,
                                     'sources': listed}},
                'ask': _can_ask(answered)}
    return Work(briefs.guidance('research-plan'), task, 'write', prepared, name)


def question_work(root: Path, found: Survey, ident: str, request: dict | None,
                  error: str | None, sources=None) -> Work:
    """The job of researching one question. The documents the person supplied are offered
    to it before it starts. One that works from those alone has no web search and cannot
    fetch a page."""
    offered, only = list((sources or ((), ()))[1]), found.scope == 'supplied-only'
    query = found.research.queries.get(ident)
    task = ('Research this question for a training.\n\n'
            f'Question ID: {ident}\n'
            f'Question: {found.research.questions[ident]}\n'
            + (f'Search words to start from: {query}\n' if query else '')
            + ('Work only from the documents the person supplied, which are saved for you '
               'already.\n' if only else 'The documents the person supplied are saved for '
               'you already. Read them as well as the web.\n' if offered else '')
            + f'\nThe training:\n{_about(root, found.session)}'
            + _again(None, None, error, [], 'the research'))
    if request and request.get('note'):
        task += ('\n\nThe person looked at the research and asked for this, which may or '
                 f"may not be about your question:\n\n{request['note']}")
    return Work(briefs.guidance('research-question'), task, 'write' if only else 'research',
                {'finding': ident, 'fetch': not only, 'ask': False, 'sources': offered})


def findings_text(root: Path) -> str:
    """The research as a worker reads it: each question's ID, verdict, summary and quotes."""
    record = workspace.research_record(root) or {'items': [], 'results': {}}
    lines = ['# Research findings', '',
             'Cite a finding by its ID. Only a supported finding can back a key point.', '']
    for item in record['items']:
        result = record['results'].get(item.get('id')) or {}
        lines += [f"## {item.get('id')}", '', f"Question: {item.get('question')}",
                  f"Verdict: {result.get('status', 'pending: it was not researched')}"]
        if result:
            lines += [f"Summary: {result.get('summary', '')}",
                      f"Limits: {result.get('limits', 'none')}"]
        for passage in result.get('evidence') or []:
            quote = ' '.join(str(passage.get('quote', '')).split())
            lines.append(f"Quoted from {passage.get('title')} ({passage.get('origin')}): "
                         f'"{quote}"')
        lines.append('')
    return '\n'.join(lines)


def _text(root: Path, session: dict, name: str) -> str | None:
    """The text of one of a training's files, by the core's name for it."""
    return _read(root / workspace.artifact(root, session, name)['file'])


def _inputs(inputs: dict) -> str:
    """A job's inputs, named as a task names them."""
    names = [f'"{name}"' for name in inputs]
    return ', '.join(names[:-1]) + (' and ' if len(names) > 1 else '') + names[-1]


def blueprint_work(root: Path, found: Survey, step: Step, request: dict | None,
                   error: str | None, answered: list[dict]) -> Work:
    """The job of drafting one blueprint."""
    session, name = found.session, 'blueprint'
    level = workspace.split(step.artifact)[1]
    own = sorted(workspace.split(scenario)[0].partition(':')[2]
                 for scenario in workspace.scenarios(root, session)['found']
                 if workspace.split(scenario)[1] == level)
    if 'scenario' not in session['settings']['stages']:
        practice = 'Practice scenarios are not wanted: leave the practice plan out.'
    elif own:
        practice = ('The person already has these practice scenarios: ' + ', '.join(own)
                    + '. List them in the practice plan.')
    else:
        practice = 'Practice scenarios are wanted: plan them.'
    task = (f'Draft {workspace.label(step.artifact)} for this training.\n\n'
            f'{_about(root, session)}\n'
            + (f'This blueprint is for level {level}.\n' if level else '')
            + f'{practice}\n\n'
            'Your inputs are "intake" and "research findings".\n'
            f'Hand the blueprint back with submit_artifact under the name "{name}".'
            + _again(request, _text(root, session, step.artifact), error, answered,
                     'the blueprint', found.state.get(step.artifact) == 'stale'))
    prepared = {'inputs': {'intake': _read(root / 'intake.md') or '',
                           'research findings': findings_text(root)},
                'artifacts': {name: {'kind': 'blueprint', 'level': level,
                                     'findings': session.get('findings')}},
                'ask': _can_ask(answered)}
    return Work(briefs.guidance('blueprint', level=level), task, 'write', prepared, name)


def _earlier(root: Path, session: dict, level: str | None) -> str | None:
    """What the levels below this one cover, for a guide that must not teach it again."""
    lines = []
    for earlier in session['levels'][:session['levels'].index(level)] if level else ():
        parsed = checks.parse_blueprint(
            _text(root, session, workspace.qualify('blueprint', earlier)) or '')
        lines += [f'## Level {earlier}', '', 'Assume the reader can already:', '']
        lines += [f"- {objective['text']}" for objective in parsed['objectives'].values()]
        lines.append('')
    return '\n'.join(lines) if lines else None


def document_work(root: Path, found: Survey, step: Step, request: dict | None,
                  error: str | None, answered: list[dict]) -> Work:
    """The job of writing one learner guide, from its level's blueprint and the research."""
    session, name = found.session, 'document'
    level = workspace.split(step.artifact)[1]
    blueprint = _text(root, session, workspace.qualify('blueprint', level)) or ''
    inputs = {'intake': _read(root / 'intake.md') or '', 'blueprint': blueprint,
              'research findings': findings_text(root)}
    earlier = _earlier(root, session, level)
    if earlier:
        inputs['earlier levels'] = earlier
    task = (f'Write {workspace.label(step.artifact)} for this training.\n\n'
            f'{_about(root, session)}\n'
            + (f'This guide is for level {level}.\n' if level else '')
            + f'\nYour inputs are {_inputs(inputs)}.\n'
            f'Hand the guide back with submit_artifact under the name "{name}".'
            + _again(request, _text(root, session, step.artifact), error, answered,
                     'the guide', found.state.get(step.artifact) == 'stale'))
    prepared = {'inputs': inputs,
                'artifacts': {name: {'kind': 'document', 'blueprint': blueprint}},
                'ask': _can_ask(answered)}
    return Work(briefs.guidance('document', level=level), task, 'write', prepared, name)


def brief_work(root: Path, found: Survey, step: Step, request: dict | None,
               error: str | None, answered: list[dict]) -> Work:
    """The job of writing one brief, of the kind the training asks for."""
    session, name = found.session, 'brief'
    level, kind = workspace.split(step.artifact)[1], session['settings']['brief_kind']
    inputs = {'intake': _read(root / 'intake.md') or '',
              'blueprint': _text(root, session, workspace.qualify('blueprint', level)) or '',
              'research findings': findings_text(root)}
    task = (f'Write {workspace.label(step.artifact)} for this training. It is a {kind} '
            f'brief.\n\n{_about(root, session)}\n'
            + (f'This brief is for level {level}.\n' if level else '')
            + f'\nYour inputs are {_inputs(inputs)}.\n'
            f'Hand the brief back with submit_artifact under the name "{name}".'
            + _again(request, _text(root, session, step.artifact), error, answered,
                     'the brief', found.state.get(step.artifact) == 'stale'))
    prepared = {'inputs': inputs,
                'artifacts': {name: {'kind': 'brief', 'brief_kind': kind,
                                     'findings': session.get('findings')}},
                'ask': _can_ask(answered)}
    return Work(briefs.guidance('brief', level=level, kind=kind), task, 'write', prepared,
                name)


def _mode(mode: str | None) -> str:
    """A practice mode there is a reference for: the default when none is stated."""
    return mode if mode in checks.MODES else checks.MODES[0]


def scenario_work(root: Path, found: Survey, step: Step, request: dict | None,
                  error: str | None, answered: list[dict]) -> Work:
    """The job of drafting one practice scenario the blueprint's practice plan names, or of
    laying out one the person wrote, in their own words, because they asked for that."""
    session, name = found.session, 'scenario'
    base, level = workspace.split(step.artifact)
    ident = base.partition(':')[2]
    named = (found.practice.get(level) or {}).get(ident) or {}
    earlier = _text(root, session, step.artifact)
    own = step.artifact in found.own and earlier is not None
    mode = _mode(checks.parse_scenario(earlier)['mode'] if own else named.get('mode'))
    inputs = {'intake': _read(root / 'intake.md') or '',
              'blueprint': _text(root, session, workspace.qualify('blueprint', level)) or ''}
    brief = (_text(root, session, workspace.qualify('brief', level))
             if 'brief' in wanted(session) else None)
    if brief:
        inputs['brief'] = brief
    inputs['mode reference'] = briefs.mode(mode)
    about = (f'{_about(root, session)}\n'
             + (f'This scenario is for level {level}.\n' if level else '')
             + f'Scenario ID: {ident}\nMode: {mode}\n'
             + (f"The practice plan says of it: {named['plan']}\n" if named.get('plan')
                else '')
             + ('' if brief else 'This training has no brief. Keep product facts to what '
                'the blueprint\'s key points say.\n')
             + f'\nYour inputs are {_inputs(inputs)}.\n'
             f'Hand the scenario back with submit_artifact under the name "{name}".')
    if own:
        asked = (request or {}).get('note')
        task = ('Lay out a practice scenario the person wrote themselves. They asked for '
                'it to be laid out under the headings a scenario needs. Keep their wording, '
                'as your guidance says under "When the scenario is the person\'s own".\n\n'
                + about + (f'\n\nWhat they asked for:\n\n{asked}' if asked else '')
                + f'\n\nTheir scenario, as they wrote it:\n\n{earlier}'
                + _again(None, None, error, answered, 'the scenario'))
    else:
        task = (f'Draft {workspace.label(step.artifact)} for this training.\n\n' + about
                + _again(request, earlier, error, answered, 'the scenario'))
    prepared = {'inputs': inputs,
                'artifacts': {name: {'kind': 'scenario', 'label': base,
                                     'mode': named.get('mode')}},
                'ask': _can_ask(answered)}
    return Work(briefs.guidance('scenario'), task, 'write', prepared, name)


def yoodli_facts(profile: dict) -> str:
    """The Yoodli profile as a worker reads it. Every fact about Yoodli a worker may state
    comes from here, so that they all come from the one file that records them."""
    limits, agent = profile.get('limits') or {}, profile.get('roleplay_agent') or {}
    assets = profile.get('ai_assets') or {}

    def limit(key: str) -> str:
        return f"{(limits.get(key) or {}).get('value', 0):,}"

    lines = ['# Yoodli field data', '',
             'Types: ' + ', '.join(profile.get('types') or ()) + '.',
             'The type for each mode: ' + '; '.join(
                 f'{mode} is {kind}' for mode, kind in (profile.get('mode_types') or {}).items())
             + '.',
             'Persona fields: ' + ', '.join(profile.get('persona_fields') or ()) + '.',
             'Types that need a persona: '
             + ', '.join(profile.get('persona_required_types') or ()) + '.',
             'Goal types: ' + ', '.join(profile.get('goal_types') or ()) + '.',
             '', '## Limits', '',
             f"- Context: {limit('context_chars')} characters",
             f"- Personas: {limit('personas_max')}",
             f"- A goal's Explanation: {limit('goal_explanation_chars')} characters",
             f"- A goal's Achieved: {limit('goal_achieved_chars')} characters",
             f"- A goal's Missed: {limit('goal_missed_chars')} characters"]
    if any((entry or {}).get('verified') is None for entry in limits.values()):
        lines += ['', 'These limits and the field names are provisional. They come from '
                  "Yoodli's public help pages and have not all been confirmed in its live "
                  'builder.']
    lines += ['', '## The agent that drafts a roleplay', '',
              f"- It takes up to {agent.get('files_max')} files and {agent.get('urls_max')} "
              'public address.',
              '- It drafts: ' + ', '.join(agent.get('drafts') or ()) + '.',
              '- It ' + ('can' if agent.get('creates_custom_goals') else 'cannot')
              + ' create new custom goals.',
              '- It ' + ('can edit existing roleplays.' if agent.get('edits_existing_roleplays')
                         else 'creates new roleplays only.'),
              '', '## What each part needs', '']
    lines += [f"- {entry.get('for')}: {entry.get('needs')}."
              for entry in profile.get('prerequisites') or ()]
    lines += ['', '## The knowledge file', '',
              '- Strict mode ' + ('uses more' if assets.get('strict_mode_uses_more_capacity')
                                  else 'does not use more') + " of the roleplay's capacity.",
              '- A PDF ' + ('can' if assets.get('pdf_can_be_shown_to_user') else 'cannot')
              + ' also be shown to the learner.',
              '- These cannot be shown to the learner: '
              + ', '.join(assets.get('show_to_user_disabled_for') or ()) + '.', '']
    return '\n'.join(lines)


def upload(copies, brief: str) -> tuple[dict | None, str | None]:
    """The copy of a brief there is to give Yoodli: its Google Doc when one is made, else
    its Word file. With neither, why not, when a reason was kept."""
    own = [entry for entry in copies if entry['artifact'] == brief]
    made = sorted((entry for entry in own if entry['state'] == 'made'),
                  key=lambda entry: entry['kind'] != 'google')
    if made:
        return made[0], None
    return None, next((entry['problem'] for entry in own if entry.get('problem')), None)


def _objectives(parsed: dict, named: dict) -> str:
    lines = ['# The objectives', '']
    lines += [f"- {ident}: {objective['text']} [{objective['level']}]"
              for ident, objective in parsed['objectives'].items()]
    if named.get('objectives'):
        lines += ['', 'The practice plan gives this scenario: '
                  + ', '.join(named['objectives']) + '.']
    return '\n'.join(lines) + '\n'


def yoodli_work(root: Path, found: Survey, step: Step, request: dict | None,
                error: str | None, answered: list[dict]) -> Work:
    """The job of laying one approved scenario out in Yoodli's fields."""
    session, name = found.session, 'yoodli'
    base, level = workspace.split(step.artifact)
    ident = base.partition(':')[2]
    scenario = _text(root, session, workspace.qualify(f'scenario:{ident}', level)) or ''
    parsed = checks.parse_blueprint(
        _text(root, session, workspace.qualify('blueprint', level)) or '')
    profile = home.read_json(workspace.profile_for(root), None)
    mode = _mode(checks.parse_scenario(scenario)['mode'])
    inputs = {'scenario': scenario,
              'brief': _text(root, session, workspace.qualify('brief', level)) or '',
              'objectives': _objectives(parsed, (found.practice.get(level) or {})
                                        .get(ident) or {}),
              'Yoodli field data': yoodli_facts(profile if isinstance(profile, dict) else {}),
              'mode reference': briefs.mode(mode)}
    copy, why = upload(found.copies, workspace.qualify('brief', level))
    if copy is None:
        ready = ('No copy of the brief is ready to upload'
                 + (f': {why}' if why else '.') + ' Name no file under AI assets.')
    elif copy['kind'] == 'google':
        ready = ("The copy of the brief to upload is its Google Doc, downloaded from Google "
                 'as a PDF.')
    else:
        ready = f"The copy of the brief to upload is its Word file, {copy['link']}."
    task = (f'Lay {workspace.label(step.artifact.replace("yoodli:", "scenario:", 1))} out '
            f'for Yoodli.\n\n{_about(root, session)}\n'
            + (f'This scenario is for level {level}.\n' if level else '')
            + f'Scenario ID: {ident}\nMode: {mode}\n{ready}\n'
            f'\nYour inputs are {_inputs(inputs)}.\n'
            f'Hand the layout back with submit_artifact under the name "{name}".'
            + _again(request, _text(root, session, step.artifact), error, answered,
                     'the layout', found.state.get(step.artifact) == 'stale'))
    prepared = {'inputs': inputs,
                'artifacts': {name: {'kind': 'yoodli', 'label': base, 'profile': profile,
                                     'scenario': scenario,
                                     'objectives': sorted(parsed['objectives'])}},
                'ask': _can_ask(answered)}
    return Work(briefs.guidance('yoodli'), task, 'write', prepared, name)


WORKS = {'blueprint': blueprint_work, 'document': document_work, 'brief': brief_work,
         'scenario': scenario_work, 'yoodli': yoodli_work}


def work(root: Path, found: Survey, step: Step, request: dict | None, error: str | None,
         answered: list[dict], sources=None) -> Work:
    """The job a drafting step gives a worker. `sources` is what `documents.sources`
    returned, which only the research questions are drafted from."""
    if step.id == 'research-plan':
        return plan_work(root, found, request, error, answered, sources)
    kind = workspace.split(step.artifact)[0].partition(':')[0]
    return WORKS[kind](root, found, step, request, error, answered)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding='utf-8')
    except OSError:
        return None


# --- what is kept ------------------------------------------------------------------------

def why_not(handed: dict, said: str) -> str:
    """Why a job that ended handed back nothing that was kept, in a sentence."""
    refused = [problem for found in handed['problems'].values() for problem in found]
    if refused:
        return ('What it handed back did not pass the checks: ' + ' '.join(refused[:3])
                + (' And more.' if len(refused) > 3 else ''))
    return said or 'It ended without handing anything back.'


def _kind(artifact: str) -> str:
    """The kind of file an artifact is: `scenario:main@101` is a scenario."""
    return workspace.split(artifact)[0].partition(':')[0]


def _checked(artifact: str, outcomes: list[dict]) -> list[str]:
    """What the checks on a file found, for its review: how many passed and what each one
    looks at, then each that could not run or did not pass."""
    passed = [outcome for outcome in outcomes if outcome['status'] == 'passed']
    lines = [f'Checked for you: {len(passed)} check{"" if len(passed) == 1 else "s"} passed.']
    looked = [CHECKED.get((_kind(artifact), outcome['check'].partition('@')[0]
                           .rpartition('.')[2])) for outcome in passed]
    lines += [f'- {words}' for words in looked if words]
    lines += [f"Could not be checked ({outcome['check']}): {outcome['problems'][0]}"
              for outcome in outcomes if outcome['status'] == 'unavailable']
    for outcome in outcomes:
        if outcome['status'] == 'failed':
            lines.append(f"Did not pass ({outcome['check']}):")
            lines += [f'- {problem}' for problem in outcome['problems']]
    return lines


WHOSE = {
    'runner': 'The runner drafted this file, from the practice plan and the brief. It is '
              'yours to change from here.',
    'you': 'This is your own file, put to you as you wrote it. The runner changed nothing '
           'in it.',
    'laid': 'This is your own file, laid out under the headings a scenario needs because '
            'you asked for that. The wording is meant to be yours: read it against what '
            'you wrote.',
}


def _scenario_note(text: str, whose: str) -> list[str]:
    """What gate 7 shows of a scenario: whose file it is, its mode and its criteria."""
    parsed = checks.parse_scenario(text)
    return [WHOSE[whose],
            f"Mode: {parsed['mode']}. Success criteria: {len(parsed['criteria'])}."]


def _handoff(copies, brief: str) -> str:
    """Whether a brief has a copy to give Yoodli, and what to do when it has none."""
    copy, why = upload(copies, brief)
    if copy is None:
        return ('The Yoodli handoff is incomplete: the brief has no copy to upload yet'
                + (f' ({why})' if why else '') + '. Try the copies again from this '
                "training's page, or save the brief as a PDF or a Word file yourself and "
                'upload that.')
    what = 'its Google Doc' if copy['kind'] == 'google' else 'its Word file'
    return f"The brief has a copy to upload: {what}, {copy['link']}."


def _yoodli_note(root: Path, session: dict, artifact: str, draft: dict, copies) -> list[str]:
    """What gate 8 shows of a Yoodli scenario: which goal carries each success criterion,
    each count against its limit, and whether the brief has a copy to upload."""
    level = workspace.split(artifact)[1]
    scenario = checks.parse_scenario(
        _text(root, session, artifact.replace('yoodli:', 'scenario:', 1)) or '')
    fields, _ = checks.fenced_fields(draft['text'])
    goals = checks.goal_comments(draft['text'])

    def named(goal: str) -> str:
        name = fields.get(('Goals', goal, 'Name'), '').strip()
        return f'{goal} ({name})' if name else goal

    lines = ['', 'Which goal carries each success criterion:']
    for number, criterion in enumerate(scenario['criteria'], start=1):
        carried = [named(goal) for goal, said in goals.items() if number in said['criteria']]
        lines.append(f'- {number}. {criterion} Carried by: '
                     + (', '.join(carried) or 'no goal') + '.')
    profile = home.read_json(workspace.profile_for(root), None) or {}
    limits = {key: (entry or {}).get('value')
              for key, entry in (profile.get('limits') or {}).items()}
    within = next((outcome for outcome in draft['checks']
                   if outcome['check'].partition('@')[0].endswith('.limits')), {})
    counts = within.get('counts') or {}

    def against(count, key: str) -> str:
        limit = limits.get(key)
        return f'{count:,} of {limit:,}' if isinstance(limit, int) else f'{count:,}'

    personas = len({path[1] for path in fields if len(path) == 3 and path[0] == 'Personas'})
    lines += ['', "Counts against Yoodli's limits, in characters:",
              f"- Context: {against(counts.get('Context', 0), 'context_chars')}"]
    for goal in goals:
        sizes = [f"{field.lower()} {against(counts.get(f'{goal} {field}', 0), key)}"
                 for field, key in checks.YOODLI_GOAL_LIMITS]
        lines.append(f'- {goal}: ' + ', '.join(sizes))
    lines.append(f"- Personas: {against(personas, 'personas_max')}, counted in personas")
    if within.get('provisional'):
        lines.append(PROVISIONAL)
    lines += ['', _handoff(copies, workspace.qualify('brief', level))]
    return lines


def keep_draft(root: Path, step: Step, handed: dict, request: dict | None,
               found: Survey | None = None) -> None:
    """Save a draft the checks let through, with a review for the gate: what was checked,
    what that gate shows in particular, and the worker's own notes on the draft, labelled
    as its judgment. `found` is the training as it stood before the job."""
    draft = next(iter(handed['artifacts'].values()))
    kind, session = _kind(step.artifact), workspace.load(root)
    dated = found is not None and found.state.get(step.artifact) == 'stale'
    workspace.save(root, step.artifact, source=draft['path'])
    lines = _checked(step.artifact, draft['checks'])
    lines += [f'Worth a look: {warning}' for warning in draft['warnings']]
    if kind == 'document':
        lines.append(DECLARED)
    elif kind == 'scenario':
        lines += _scenario_note(draft['text'], 'laid' if found is not None
                                and step.artifact in found.own else 'runner')
    elif kind == 'yoodli':
        lines += _yoodli_note(root, session, step.artifact, draft,
                              found.copies if found else ())
    if request:
        asked = 'a new draft' if request.get('kind') == 'rebuild' else 'changes'
        lines.append(f'This version was made because you asked for {asked}'
                     + (f": {workspace.shortened(request['note'])}" if request.get('note')
                        else '.'))
    elif dated:
        lines.append('This version was made because what the earlier one was made from '
                     'changed, and you approved the change.')
    if handed['review'] and kind == 'brief':
        lines += ['', 'Where the worker thinks the brief is weakest, with its other notes. '
                  'They are its judgment, not a check:', '', handed['review'].strip()]
    elif handed['review']:
        lines += ['', 'The worker\'s own notes on its draft. They are its judgment, not a '
                  'check:', '', handed['review'].strip()]
    elif kind == 'brief':
        lines += ['', 'The worker left no notes, so nothing here says where the brief is '
                  'weakest. Read its Limitations and its Unknowns with that in mind.']
    else:
        lines += ['', 'The worker left no notes on its draft.']
    workspace.append_review(root, step.artifact, f'Ready for your review, {workspace.now()}',
                            '\n'.join(lines))


def keep_own(root: Path, step: Step, found: Survey) -> None:
    """Take in a scenario the person wrote: record it through the core as it is, changing
    nothing in it, with a review for the gate that says what the shape check found."""
    workspace.save(root, step.artifact)
    session = workspace.load(root)
    text = _text(root, session, step.artifact) or ''
    base, level = workspace.split(step.artifact)
    outcome = checks.check_scenario(text, base)
    lines = _scenario_note(text, 'you') + _checked(step.artifact, [outcome])
    if outcome['status'] == 'failed':
        lines.append('Ask for changes, and a worker will lay your own wording out under '
                     'the headings a scenario needs. It asks you for anything that is '
                     'missing; it makes nothing up.')
    named = (found.practice.get(level) or {}).get(base.partition(':')[2]) or {}
    stated = checks.parse_scenario(text)['mode']
    if named.get('mode') and named['mode'] != stated:
        lines.append(f"Worth a look: the practice plan lists this scenario as "
                     f"{named['mode']}; your file says {stated}. Your file decides.")
    workspace.append_review(root, step.artifact, f'Ready for your review, {workspace.now()}',
                            '\n'.join(lines))


def keep_sources(root: Path, handed: dict) -> None:
    """Copy the sources a finding quotes into the training's own sources folder, where
    harness-research reads them. They stay on this computer: the workspace ignores them."""
    quoted = {passage['file'] for passage in handed['finding'].get('evidence') or []}
    for source in handed['sources']:
        if source['file'] not in quoted:
            continue
        for name, path in ((source['file'], source['path']),
                           (source.get('original'), source.get('original_path'))):
            target = workspace.managed(root, name) if name else None
            if target is None or path is None or target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


def keep_report(root: Path, found: Research, reasons: dict) -> None:
    """Save the research report through the core, with a review for the gate: how many
    questions are supported, which are not settled, and which were not researched."""
    workspace.save(root, 'research', built=True)
    verdicts = found.verdicts
    count = {verdict: list(verdicts.values()).count(verdict)
             for verdict in set(verdicts.values())}
    total = len(verdicts)
    lines = [f"{count.get('supported', 0)} of {total} question{'' if total == 1 else 's'} "
             'have an answer the sources support.']
    if count.get('contradicted'):
        lines.append(f"{count['contradicted']} more state a claim that the sources "
                     'contradict.')
    if found.unresolved:
        lines += ['', f'Not settled ({len(found.unresolved)}):']
        lines += [f'- {ident}: {found.questions[ident]} ({verdicts[ident]})'
                  for ident in found.unresolved]
    if found.unread:
        lines += ['', f'Not researched ({len(found.unread)}):']
        lines += [f'- {ident}: {found.questions[ident]} '
                  f"({reasons.get(ident) or 'no reason was kept'})"
                  for ident in found.unread]
    if not found.unresolved and not found.unread:
        lines.append('Every question was researched and settled.')
    lines += ['', 'Each finding quotes its sources word for word, and each quote was found '
              'in the saved page before it was kept. Whether the sources are right is for '
              'you to judge.']
    workspace.append_review(root, 'research', f'Ready for your review, {workspace.now()}',
                            '\n'.join(lines))
