"""The pipelines the runner walks: a training as far as the blueprint, and research.

What a caller needs to know
---------------------------
    form = pipeline.check_form(sent)             # what the page's form may say
    root = pipeline.create(space, form)          # a training, through the core's own init
    found = pipeline.survey(root, run)           # where it is, worked out from its files
    found.next                                   # the one thing to do now
    work = pipeline.work(root, found, step, ...) # what a worker is told and given
    pipeline.keep_draft(root, step, handed)      # save a checked draft through the core

- TRAINING and RESEARCH are the pipelines as data: each step is code the runner runs, a
  job for an agent, or a gate a person decides. `steps(levels)` lays a training's out in
  order. With levels, every blueprint is drafted before the first is put to the person.
- `survey` remembers nothing. It reads the core's record, the requests a person made and
  the research record, and says which steps are done. The next step is the first that is
  not. `run` is the training's run record, which holds what the files cannot say: which
  research run the approved plan was handed to, which questions a person's request has
  researched again, and how each try at a step went.
- A training is made in `page` approval mode, so nothing here can approve a draft. The
  one exception is intake, which the core lets anyone record: it is the person's own
  answers, typed into the form.
- Supplied documents are not part of this milestone: the form's `source_scope` is taken
  only as `public-web`.
- Sentences a person will read never say "artifact", "stale" or "lineage".
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
import home
import sync_guidance
import workspace
from workspace import WorkspaceError

from runner import briefs, gitstate, settings

ATTEMPTS = 3            # tries at one step: the first, and two more with the reason added
QUESTIONS = 3           # questions the workers on one step may put to the person
PLAN = workspace.SHARED['research-plan'][0]
REPORT = workspace.SHARED['research'][0]
MADE = ('draft', 'stale', 'approved')
UNRESOLVED = ('insufficient', 'unavailable')
SCOPE = 'public-web'
SCOPES = ('public-web', 'supplied-only', 'both')
NOT_YET = ('Supplied documents are not available in the runner yet. Choose the public web '
           'for this training.')
LATER = ('The later stages are not automated yet. This training can be continued in a chat '
         'with your assistant.')
LIMITS = {'title': 120, 'topic': 2000, 'audience': 2000, 'purpose': 500, 'time_limit': 200,
          'brand': 200}
HEADINGS = ('Topic', 'Levels', 'Brief', 'Audience', 'Purpose', 'Source scope', 'Time limit')

# The training pipeline, as far as the blueprint: stage, step, kind, and what the step does
# in the words a list shows and the words a sentence uses. {it} is what the step is about.
TRAINING = (
    ('intake', 'intake', 'code', 'Record your answers', 'Recording your answers'),
    ('research-plan', 'research-plan', 'agent', 'Draft {it}', 'Drafting {it}'),
    ('research-plan', 'gate:research-plan', 'gate', 'Your review of {it}',
     'Waiting for your review of {it}'),
    ('research', 'research-start', 'code', 'Hand the approved questions to research',
     'Handing the approved questions to research'),
    ('research', 'research', 'agent', 'Research each question', 'Researching the questions'),
    ('research', 'research-report', 'code', 'Write {it}', 'Writing {it}'),
    ('research', 'gate:research', 'gate', 'Your review of {it}',
     'Waiting for your review of {it}'),
    ('blueprint', 'blueprint', 'agent', 'Draft {it}', 'Drafting {it}'),
    ('blueprint', 'gate:blueprint', 'gate', 'Your review of {it}',
     'Waiting for your review of {it}'),
)
# The research pipeline: the steps above that make it up, and what each one runs.
RESEARCH = (
    ('research-start', 'harness-research plan, with the approved plan'),
    ('research', 'one worker for each question, and harness-research record for each '
                 'finding, one at a time'),
    ('research-report', 'harness-research status, then the report saved through the core'),
)
ARTIFACTS = {'research-plan': 'research-plan', 'gate:research-plan': 'research-plan',
             'research-report': 'research', 'gate:research': 'research',
             'blueprint': 'blueprint', 'gate:blueprint': 'blueprint'}


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
    kind: str                         # 'agent', 'code', 'gate', 'wait', 'done' or 'stuck'
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
    scope = sent.get('source_scope') or SCOPE
    workspace.check_choice(scope, SCOPES, 'The source scope')
    if scope != SCOPE:
        raise WorkspaceError(NOT_YET)
    form['source_scope'] = scope
    if not isinstance(sent.get('yoodli', False), bool):
        raise WorkspaceError('Say whether Yoodli scenarios are wanted with true or false.')
    form['yoodli'] = sent.get('yoodli', False)
    form['agent'] = None if sent.get('agent') is None else settings.check_agent(sent['agent'])
    form['model'] = settings.check_model(sent.get('model'))
    return form


def gates(form: dict) -> int:
    """How many times a training made from this form asks for a decision."""
    return 2 + max(1, len(form['levels']))


def intake_text(form: dict) -> str:
    """The form's answers as intake.md: the headings intake has, and nothing else."""
    answers = {
        'Topic': form['topic'],
        'Levels': ', '.join(form['levels']) or 'None',
        'Brief': form['brief_kind'],
        'Audience': form['audience'],
        'Purpose': form['purpose'],
        'Source scope': 'Public web',
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
    approval mode, with intake written from the answers and approved as the person's own."""
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
          level: str | None = None) -> Step:
    base = ARTIFACTS.get(ident)
    artifact = None if base is None else workspace.qualify(base, level)
    it = workspace.label(artifact) if artifact else ''
    return Step(workspace.qualify(ident, level), kind, label.format(it=it),
                doing.format(it=it), stage, artifact)


def steps(levels) -> tuple[Step, ...]:
    """Every step of a training with these levels, in the order it is walked."""
    listed = []
    for stage, ident, kind, label, doing in TRAINING:
        # Row by row, so every level's blueprint is drafted before the first gate 3.
        for level in (levels or [None]) if stage == 'blueprint' else [None]:
            listed.append(_step(stage, ident, kind, label, doing, level))
    return tuple(listed)


def gate_for(artifact: str) -> Step:
    """The gate that puts one file to the person."""
    stage = workspace.split(artifact)[0]
    it = workspace.label(artifact)
    return Step(f'gate:{artifact}', 'gate', f'Your review of {it}',
                f'Waiting for your review of {it}', stage, artifact)


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


def _done(step: Step, state: dict, asked: dict, found: Research) -> bool:
    if step.id == 'intake':
        return state['intake'] == 'approved'
    if step.kind == 'gate':
        return state[step.artifact] == 'approved'
    if step.stage == 'research':
        if state['research'] == 'approved' and 'research' not in asked:
            return True
        if step.id == 'research-start':
            return found.handed
        if step.id == 'research':
            return found.handed and not found.todo
        return found.handed and found.saved and 'research' not in asked
    return state[step.artifact] in MADE and step.artifact not in asked


def survey(root: Path, run: dict | None = None) -> Survey:
    """Where a training is and the one thing to do now, from its files and its run record."""
    session = workspace.load(root)
    state = workspace.statuses(root, session)
    asked = {str(request.get('artifact')): request for request in session['requests']}
    found = research(root, session, run, asked.get('research'))
    listed = steps(session['levels'])
    done = frozenset(step.id for step in listed if _done(step, state, asked, found))
    first = next((step for step in listed if step.id not in done), None)
    return Survey(session, state, listed, done, _next(first, session, state, asked, found),
                  found, asked)


def _next(first: Step | None, session: dict, state: dict, asked: dict,
          found: Research) -> Next:
    if first is None:
        return Next('done')
    if first.id == 'intake':
        if state['intake'] == 'not-started':
            return Next('stuck', first, why='The answers this training was started from are '
                        'missing, so it cannot go on. Start a new training in its place.')
        first = gate_for('intake')  # someone changed the answers: they are put to the person
    if first.kind == 'gate':
        waiting = session.get('gate') == first.artifact and session.get('pending_question')
        return Next('wait' if waiting else 'gate', first)
    request = asked.get('research' if first.stage == 'research' else first.artifact)
    if first.kind == 'code':
        return Next('code', first, request)
    return Next('agent', first, request, found.todo if first.id == 'research' else ())


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
           answered: list[dict], thing: str) -> str:
    """The part of a task that says why this job is being done again."""
    parts = []
    if request and request.get('kind') == 'revise':
        parts.append(f'You are revising an earlier draft. What the person asked for:\n\n'
                     f"{request.get('note') or ''}")
    elif request:
        note = f" They added:\n\n{request['note']}" if request.get('note') else ''
        parts.append(f'The person asked for {thing} to be made again from the start.{note}')
    if request and earlier:
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


def plan_work(root: Path, found: Survey, request: dict | None, error: str | None,
              answered: list[dict]) -> Work:
    """The job of drafting the research questions."""
    name = 'research-plan'
    earlier = _read(root / PLAN)
    task = ('Draft the research questions for this training.\n\n'
            f'{_about(root, found.session)}\n'
            'Sources that may be used: the public web.\n\n'
            f'Hand the questions back with submit_artifact under the name "{name}".'
            + _again(request, _questions(earlier) if earlier else None, error, answered,
                     'the questions'))
    prepared = {'inputs': {'intake': _read(root / 'intake.md') or ''},
                'artifacts': {name: {'kind': 'research-plan', 'scope': SCOPE, 'sources': []}},
                'ask': _can_ask(answered)}
    return Work(briefs.guidance('research-plan'), task, 'write', prepared, name)


def question_work(root: Path, found: Survey, ident: str, request: dict | None,
                  error: str | None) -> Work:
    """The job of researching one question."""
    query = found.research.queries.get(ident)
    task = ('Research this question for a training.\n\n'
            f'Question ID: {ident}\n'
            f'Question: {found.research.questions[ident]}\n'
            + (f'Search words to start from: {query}\n' if query else '')
            + f'\nThe training:\n{_about(root, found.session)}'
            + _again(None, None, error, [], 'the research'))
    if request and request.get('note'):
        task += ('\n\nThe person looked at the research and asked for this, which may or '
                 f"may not be about your question:\n\n{request['note']}")
    return Work(briefs.guidance('research-question'), task, 'research',
                {'finding': ident, 'fetch': True, 'ask': False})


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


def blueprint_work(root: Path, found: Survey, step: Step, request: dict | None,
                   error: str | None, answered: list[dict]) -> Work:
    """The job of drafting one blueprint."""
    session, name = found.session, 'blueprint'
    level = workspace.split(step.artifact)[1]
    file = root / workspace.artifact(root, session, step.artifact)['file']
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
            + _again(request, _read(file), error, answered, 'the blueprint'))
    prepared = {'inputs': {'intake': _read(root / 'intake.md') or '',
                           'research findings': findings_text(root)},
                'artifacts': {name: {'kind': 'blueprint', 'level': level,
                                     'findings': session.get('findings')}},
                'ask': _can_ask(answered)}
    return Work(briefs.guidance('blueprint', level=level), task, 'write', prepared, name)


def work(root: Path, found: Survey, step: Step, request: dict | None, error: str | None,
         answered: list[dict]) -> Work:
    """The job a drafting step gives a worker."""
    if step.id == 'research-plan':
        return plan_work(root, found, request, error, answered)
    return blueprint_work(root, found, step, request, error, answered)


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


def keep_draft(root: Path, step: Step, handed: dict, request: dict | None) -> None:
    """Save a draft the checks let through, with a review for the gate: what was checked,
    and the worker's own notes on it, labelled as its judgment."""
    draft = next(iter(handed['artifacts'].values()))
    workspace.save(root, step.artifact, source=draft['path'])
    passed = sum(outcome['status'] == 'passed' for outcome in draft['checks'])
    lines = [f'Checked for you: {passed} check{"" if passed == 1 else "s"} passed.']
    lines += [f"Could not be checked ({outcome['check']}): {outcome['problems'][0]}"
              for outcome in draft['checks'] if outcome['status'] == 'unavailable']
    lines += [f'Worth a look: {warning}' for warning in draft['warnings']]
    if request:
        asked = 'a new draft' if request.get('kind') == 'rebuild' else 'changes'
        lines.append(f'This version was made because you asked for {asked}'
                     + (f": {workspace.shortened(request['note'])}" if request.get('note')
                        else '.'))
    if handed['review']:
        lines += ['', 'The worker\'s own notes on its draft. They are its judgment, not a '
                  'check:', '', handed['review'].strip()]
    else:
        lines += ['', 'The worker left no notes on its draft.']
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
