"""The engine: walks each training's pipeline, hands jobs to workers and stops at gates.

What a caller needs to know
---------------------------
    engine = Engine()                        # the real agents and harness-research
    engine.resume()                          # pick up every training in the workspace
    made = engine.start(form)                # {'path', 'id', 'gates'}; the run starts at once
    engine.view(path)                        # what the page shows for one run
    engine.act(path, 'pause')                # or 'resume', 'stop', 'retry'
    engine.answer(path, question_id, text)   # a person answers a worker's question
    engine.decided(path, outcome)            # commit a decision the page just recorded
    engine.carry_on(path)                    # then share if that is wanted, and wake the run
    engine.share()                           # fetch, replay and push the workspace
    engine.close()                           # end every worker; nothing half-made is kept

- The next step is never remembered. Each time, `pipeline.survey` works it out from the
  training's files, so starting the runner again resumes every training where it was.
- The run record, `.training-studio/run.json` in the training's folder, holds only what the
  files cannot say: the agent and model chosen when the training started, the limits, each
  try at each step with its times, cost, outcome and error, which research run the plan
  was handed to, a worker's question and the person's answers, and why the run is halted.
  It is committed with everything else.
- One try at an agent step: an empty job folder under `agents.staging()`, a brief, a
  worker, and results taken only from what the worker tools accepted. A draft is saved
  through the core and committed. A step is tried up to three times, with the reason for
  the last failure added to the brief; then the training stops and says what went wrong.
  An agent that cannot be reached is not tried again until the person asks.
- A research question that fails three times does not stop the training. It is left
  unanswered and named at gate 2, where the person decides. Research with no answer at all
  does stop it.
- The engine never approves. It sets a gate through the core and waits. The page records
  the person's decision through the core, then calls `decided` and `carry_on`.
- Everything the engine writes in the workspace is written and committed while it holds
  `engine.files`, so the folder matches its last commit whenever nothing is being written.
  Whoever else writes there in this process, such as the page recording a decision, holds
  it too, and lets go of it before calling `carry_on`, `act` or `answer`.
- Limits: a worker's time, what a training may spend where its agent reports spending,
  and three tries at a step. A training that has spent what it may stops and asks; "carry
  on" lets it spend as much again.
- What a person may ask of a run depends on its state: pause while it is working; stop
  while it is working, waiting or paused; resume while it is paused or stopped; and try
  again, or carry on, when a problem offers that. Anything else is refused in a sentence.
- `background=False` does every step in the caller's thread, which is how the tests drive
  it. `adapters` maps an agent's name to its adapter, and `research` makes the
  harness-research wrapper; both are replaceable so that no test starts an agent.
"""
from __future__ import annotations

import re
import secrets
import shutil
import threading
import time
from collections import deque
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
import home
import hub
import workspace
from workspace import WorkspaceError

from runner import agents, gitstate, pipeline, settings, worker_tools
from runner import research as research_cli

SCHEMA = 1
RECORD = f'{workspace.STATE_DIR}/run.json'
AT_ONCE = 3             # research questions worked on at the same time
LINES = 6               # the last things a worker did that the page is shown
READY_FOR = 60          # seconds a look at an agent is reused
BUSY_TRIES = 20         # times a finding is offered while another save holds the lock
ACTIONS = ('pause', 'resume', 'stop', 'retry')
STATES = {'working': 'working', 'waiting': 'waiting for you', 'paused': 'paused',
          'stopped': 'stopped', 'failed': 'stopped on a problem',
          'done': 'finished as far as the runner takes it'}
WORK = ('agent', 'code', 'gate')
BEFORE_DOCUMENT = ('intake', 'research-plan', 'research', 'blueprint')
KEPT = 'Everything kept before this step is still here. Nothing from the tries that failed '\
       'was kept.'


def read_record(root: Path) -> dict | None:
    """A training's run record, or None when no run is driving it."""
    path = root / RECORD
    if not path.is_file():
        return None
    record = home.read_json(path, None)
    if not isinstance(record, dict) or record.get('schema') != SCHEMA \
            or not isinstance(record.get('steps'), dict):
        raise WorkspaceError(f'The run record in {root.name} cannot be read, so the runner '
                             'will not drive this training.')
    return record


def new_record(agent: str, model: str | None, chosen: settings.Settings) -> dict:
    return {'schema': SCHEMA, 'agent': agent, 'model': model, 'started_at': home.now(),
            'limits': {'step_seconds': chosen.step_seconds,
                       'training_dollars': chosen.training_dollars},
            'steps': {}, 'research': None, 'question': None, 'answers': {}, 'halt': None,
            'problem': None, 'cleared': 0.0}


def attempts(record: dict, step: str | None = None) -> list[dict]:
    """Every try the record holds, or the tries at one step and the jobs under it."""
    return [attempt for name, entry in record['steps'].items()
            if step is None or name == step or name.startswith(f'{step}:')
            for attempt in entry.get('attempts', [])]


def spent(record: dict) -> tuple[float | None, int | None]:
    """What a training has cost so far, where its agent said: dollars and tokens."""
    tried = attempts(record)
    dollars = [attempt['dollars'] for attempt in tried if attempt.get('dollars') is not None]
    tokens = [attempt['tokens'] for attempt in tried if attempt.get('tokens') is not None]
    return (round(sum(dollars), 4) if dollars else None, sum(tokens) if tokens else None)


def last_error(record: dict, step: str) -> str | None:
    """Why the last try at a step failed, while it has failed since it last worked."""
    entry = pipeline.tries(record, step)
    tried = [attempt for attempt in entry.get('attempts', []) if attempt.get('error')]
    return tried[-1]['error'] if tried and entry.get('failed') else None


def folder_name(step: str) -> str:
    """A step's name as part of a folder's. A research question can never be mistaken for
    another step, whatever its ID."""
    if step.startswith('research:'):
        return 'question-' + step.partition(':')[2]
    return re.sub(r'[^a-z0-9]+', '-', step.lower()).strip('-')


class _Slots:
    """How many trainings may work at once. The limit is asked for each time, so a change
    of settings is felt without a restart."""

    def __init__(self, limit):
        self.limit, self.used, self.changed = limit, 0, threading.Condition()

    def take(self, closing) -> bool:
        with self.changed:
            while self.used >= self.limit():
                if closing():
                    return False
                self.changed.wait(0.5)
            self.used += 1
            return True

    def give_back(self) -> None:
        with self.changed:
            self.used -= 1
            self.changed.notify_all()


class _Run:
    """What the engine holds for one training while it serves: nothing that is needed to
    resume it."""

    def __init__(self):
        self.thread: threading.Thread | None = None
        self.again = self.queued = self.busy = False
        self.stop = threading.Event()
        self.workers: dict[str, dict] = {}


class Engine:
    """Drives every training in this computer's workspace."""

    def __init__(self, adapters=None, research=None, background: bool = True,
                 at_once: int = AT_ONCE):
        self.adapters = dict(adapters or agents.AGENTS)
        self.research = research or research_cli.Research
        self.background, self.at_once = background, at_once
        self.files = threading.RLock()
        self._lock = threading.RLock()
        self._runs: dict[str, _Run] = {}
        self._slots = _Slots(lambda: settings.load().parallel)
        self._closing = False
        self._unshared: str | None = None   # why the last try at sharing did not share
        self._sharing: threading.Thread | None = None
        self._share_again = False
        self._ready: dict[str, tuple[float, agents.Readiness]] = {}

    # --- what is driven ------------------------------------------------------------------

    @property
    def workspace(self) -> gitstate.Workspace | None:
        return gitstate.current()

    def space(self) -> gitstate.Workspace:
        found = self.workspace
        if found is None:
            raise WorkspaceError('No workspace is set up on this computer yet. Set one up '
                                 'first.')
        return found

    def driven(self, path) -> Path | None:
        """A training's folder when a run is driving it in this workspace, else None."""
        space, root = self.workspace, Path(path)
        if space is None or root.parent != space.root or not (root / RECORD).is_file():
            return None
        return root

    def trainings(self) -> list[Path]:
        """Every training in the workspace that a run is driving."""
        space = self.workspace
        if space is None:
            return []
        return [path.parent.parent for path in sorted(space.root.glob(f'*/{RECORD}'))]

    def adapter(self, name: str):
        found = self.adapters.get(name)
        if found is None:
            raise WorkspaceError(f'This runner has no agent called {name}.')
        return found() if isinstance(found, type) else found

    def ready(self, name: str, fresh: bool = False) -> agents.Readiness:
        """Whether an agent can be used now. A look is reused for a minute."""
        seen = self._ready.get(name)
        if fresh or seen is None or time.monotonic() - seen[0] >= READY_FOR:
            seen = self._ready[name] = (time.monotonic(), self.adapter(name).ready())
        return seen[1]

    def _run(self, root: Path) -> _Run:
        with self._lock:
            return self._runs.setdefault(str(root), _Run())

    def _load(self, root: Path) -> dict:
        record = read_record(root)
        if record is None:
            raise WorkspaceError('No run is driving this training.')
        return record

    def _store(self, root: Path, record: dict) -> None:
        home.write_json(root / RECORD, record)

    def _commit(self, root: Path, what: str) -> None:
        """Commit one training's folder, saying what happened. Call it holding `files`."""
        title = workspace.load(root)['title']
        gitstate.commit(self.space(), f'{title}: {what}', [root])

    # --- starting and picking up ---------------------------------------------------------

    def start(self, form: dict) -> dict:
        """Make a training from the form's answers and start its run."""
        space, chosen = self.space(), settings.load()
        gitstate.identity(space.repo)
        agent = form['agent'] or chosen.agent
        model = form['model'] or (chosen.model if agent == chosen.agent else None)
        ready = self.ready(agent)
        if not ready.ready:
            raise WorkspaceError(ready.problem)
        with self.files:
            root = pipeline.create(space, form)
            try:
                record = new_record(agent, model, chosen)
                self._tried(record, 'intake', home.now(), 0.0, 'kept')
                self._store(root, record)
                self._commit(root, 'start the training from the form')
            except BaseException:  # a training is started whole or not at all
                shutil.rmtree(root, ignore_errors=True)
                gitstate.discard(space, root)
                raise
        self.wake(root)
        return {'path': str(root), 'id': root.name, 'gates': pipeline.gates(form)}

    def adopt(self) -> None:
        """Make every training in the workspace known to this computer's page."""
        space = self.workspace
        if space is None:
            return
        with self.files:
            known = {entry['path'] for entry in home.trainings()}
            for path in sorted(space.root.glob(f'*/{workspace.STATE_DIR}/session.json')):
                root = path.parent.parent
                if str(root) in known:
                    continue
                try:
                    session = workspace.load(root)
                except WorkspaceError:
                    continue
                home.remember(root, session['title'], session['levels'])

    def resume(self) -> None:
        """Pick every training up where its files say it is. What a step left half-made
        when the runner last ended is discarded first, and so is a lock harness-research
        was left holding. A training that waits for a person, or that the runner has
        finished with, is left exactly as it is."""
        self.adopt()
        for root in self.trainings():
            try:
                record = self._load(root)
                found = pipeline.survey(root, record)
                if found.next.kind != 'done':
                    research_cli.unlock(root)
                if found.next.kind in WORK and not self._resting(record):
                    with self.files:
                        gitstate.discard(self.space(), root)
            except (WorkspaceError, OSError):
                continue  # its view says what is wrong; the others still run
            self.wake(root)

    def wake(self, path) -> None:
        """Have a training's run look at its files again and carry on if it can."""
        root = self.driven(path)
        if root is None or self._closing:
            return
        if not self.background:
            self._work(root, self._run(root))
            return
        run = self._run(root)
        with self._lock:
            if run.thread is not None and run.thread.is_alive():
                run.again = True
                return
            run.thread = threading.Thread(target=self._drive, args=(root, run), daemon=True,
                                          name=f'run-{root.name}')
            run.thread.start()

    def _drive(self, root: Path, run: _Run) -> None:
        while True:
            self._work(root, run)
            with self._lock:
                if run.again and not self._closing:
                    run.again = False
                    continue
                run.thread = None
                return

    def close(self) -> None:
        """End every worker and wait for the runs to notice. Nothing half-made is kept."""
        self._closing = True
        with self._lock:
            runs = list(self._runs.values())
        for run in runs:
            run.stop.set()
        for thread in [run.thread for run in runs] + [self._sharing]:
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=15)

    # --- one step after another ----------------------------------------------------------

    @staticmethod
    def _resting(record: dict) -> bool:
        """True while a run may start nothing: halted, failed, or waiting for an answer."""
        return bool(record.get('halt') or record.get('problem') or record.get('question'))

    def _work(self, root: Path, run: _Run) -> None:
        """Do one step after another until the training waits, ends or is halted."""
        if run.busy:  # woken from inside its own step: that step's end looks again anyway
            return
        held, last, run.busy = False, None, True
        try:
            while not self._closing:
                record = self._load(root)
                found = pipeline.survey(root, record)
                step = found.next
                if self._resting(record) or step.kind not in (*WORK, 'done'):
                    return
                if step.kind == 'done':
                    return self._hand_on(root, found)
                if self.background and not held:
                    run.queued = True
                    held = self._slots.take(lambda: self._closing)
                    run.queued = False
                    continue  # it may have waited a while: look at the files again
                if step.kind == 'code' and step.step.id == last:
                    return self._problem(root, step.step.id, 'failed', (
                        f'The runner could not get past this step: {step.step.label}.'),
                        'Everything kept so far is still here.')
                last = step.step.id if step.kind == 'code' else None
                self._do(root, run, found, step)
        except Exception as failure:  # whatever a step does, the runner keeps serving
            self._trouble(root, failure)
        finally:
            run.queued = run.busy = False
            if held:
                self._slots.give_back()

    def _do(self, root: Path, run: _Run, found: pipeline.Survey,
            step: pipeline.Next) -> None:
        if step.kind == 'gate':
            self._gate(root, step.step)
        elif step.step.id == 'research-start':
            self._hand_over(root, step.step)
        elif step.step.id == 'research-report':
            self._report(root, step.step)
        elif step.step.id == 'research':
            self._research(root, run, found, step)
        else:
            self._draft(root, run, found, step)

    def _trouble(self, root: Path, failure: Exception) -> None:
        """Stop a training on something the runner did not expect, and say what."""
        said = (str(failure) if isinstance(failure, WorkspaceError)
                else f'{type(failure).__name__}: {failure}')
        try:
            self._problem(root, None, 'failed', f'The runner could not go on: {said}',
                          'Everything kept so far is still here.')
        except Exception:  # the record cannot be written either; the view still says why
            pass

    def _problem(self, root: Path, step: str | None, state: str, what: str, kept: str,
                 action: str | None = 'retry') -> None:
        """Stop a training in a state that says what went wrong and offers one action."""
        label = {'retry': 'Try again', 'resume': 'Carry on'}.get(action)
        with self.files:
            record = self._load(root)
            record['problem'] = {'state': state, 'step': step, 'what': what, 'kept': kept,
                                 'action': action, 'label': label, 'at': home.now()}
            self._store(root, record)
            self._commit(root, f'stop. {workspace.shortened(what)}')

    def _tried(self, record: dict, step: str, started_at: str, seconds: float, outcome: str,
               error: str | None = None, dollars: float | None = None,
               tokens: int | None = None) -> dict:
        """Note one try at a step in a record. A try that worked clears the count of
        failures; one that failed adds to it."""
        entry = record['steps'].setdefault(step, {'failed': 0, 'attempts': []})
        entry['attempts'].append({
            'started_at': started_at, 'ended_at': home.now(), 'seconds': round(seconds, 1),
            'dollars': dollars, 'tokens': tokens, 'outcome': outcome, 'error': error})
        if outcome == 'kept':
            entry['failed'] = 0
        elif outcome == 'failed':
            entry['failed'] = entry.get('failed', 0) + 1
        return entry

    def _hand_on(self, root: Path, found: pipeline.Survey) -> None:
        """Nothing is left for the runner: say that the later stages are done in a chat."""
        if found.session['stage'] not in BEFORE_DOCUMENT:
            return
        with self.files:
            workspace.checkpoint(root, stage='document', next_step=pipeline.LATER)
            self._commit(root, 'every blueprint is approved; the later stages are not '
                         'automated yet')
        # No decision follows this one, so nothing else would ever share it.
        if self.space().share == gitstate.SHARE[0]:
            self.share_soon()

    def _gate(self, root: Path, step: pipeline.Step) -> None:
        """Put a checked draft to the person, through the core, and wait."""
        it = workspace.label(step.artifact)
        with self.files:
            workspace.checkpoint(root, stage=step.stage, gate=step.artifact,
                                 question=f'Approve {it}?',
                                 next_step=f'Waiting for your review of {it}')
            self._commit(root, f'ask for a review of {it}')

    # --- limits --------------------------------------------------------------------------

    def _left(self, record: dict) -> float:
        """What the training may still spend, in dollars. `cleared` is what it had spent
        when the person last said to carry on."""
        dollars = spent(record)[0] or 0.0
        return round(record['limits']['training_dollars'] + record.get('cleared', 0.0)
                     - dollars, 4)

    def _may_go(self, root: Path) -> bool:
        """Whether a worker may start now. Stops the training, and asks, once it has spent
        what it may."""
        with self.files:  # so that several workers starting at once stop it only once
            record = self._load(root)
            if self._closing or self._resting(record):
                return False
            if self._left(record) > 0:
                return True
            dollars, limit = spent(record)[0], record['limits']['training_dollars']
            self._problem(root, None, 'stopped', (
                f'This training has spent ${dollars:,.2f}. It stops and asks each time it '
                f'has spent another ${limit:,.2f}.'), 'Everything made so far is kept.',
                'resume')
            return False

    # --- one job for one worker ----------------------------------------------------------

    def _folder(self, root: Path, step: str, number: int) -> Path:
        """An empty folder for one try at one step, outside the workspace. Folders left by
        earlier tries at the same step are removed."""
        base, stem = agents.staging(), f'{root.name}--{folder_name(step)}-'
        left = re.compile(re.escape(stem) + r'\d+-[0-9a-f]{6}')
        for old in base.iterdir() if base.is_dir() else ():
            if left.fullmatch(old.name):
                shutil.rmtree(old, ignore_errors=True)
        return base / f'{stem}{number}-{secrets.token_hex(3)}'

    def _job(self, root: Path, run: _Run, step: pipeline.Step, work: pipeline.Work):
        """Run one worker on one job. Returns how the agent ended, what the worker tools
        accepted from it, when it started and the job's folder."""
        record = self._load(root)
        number = len(pipeline.tries(record, step.id).get('attempts', [])) + 1
        folder = self._folder(root, step.id, number)
        worker_tools.prepare(folder, **work.prepared)
        limits = agents.Limits(record['limits']['step_seconds'],
                               max(0.01, self._left(record)))
        job = agents.Job(work.guidance, work.task, folder, work.profile,
                         tuple(worker_tools.command(folder)), limits, record.get('model'))
        lines, started_at, clock = deque(maxlen=LINES), home.now(), time.monotonic()
        with self._lock:
            run.workers[step.id] = {'label': step.doing, 'started_at': started_at,
                                    'lines': lines}
        try:
            outcome = self.adapter(record['agent']).run(job, activity=lines.append,
                                                        stop=run.stop)
        except WorkspaceError as refusal:  # a job that was wrong before it started
            outcome = agents.Outcome(False, 'failed', str(refusal))
        finally:
            with self._lock:
                run.workers.pop(step.id, None)
        if run.stop.is_set() and outcome.reason != 'stopped':
            outcome = replace(outcome, finished=False, reason='stopped')
        if not outcome.seconds:
            outcome = replace(outcome, seconds=round(time.monotonic() - clock, 1))
        return outcome, worker_tools.collect(folder), started_at, folder

    @staticmethod
    def _cost(outcome: agents.Outcome) -> dict:
        tokens = outcome.tokens or {}
        counted = (tokens.get('input') or 0) + (tokens.get('output') or 0)
        return {'dollars': outcome.cost, 'tokens': counted if outcome.tokens else None}

    def _failed(self, root: Path, step: pipeline.Step, outcome: agents.Outcome,
                started_at: str, detail: str) -> None:
        """Note a try that did not work. After the last one a step may have, or when the
        agent cannot be used at all, the training stops and says so."""
        question = step.id.startswith('research:')
        with self.files:
            record = self._load(root)
            entry = self._tried(record, step.id, started_at, outcome.seconds, 'failed',
                                detail, **self._cost(outcome))
            self._store(root, record)
            self._commit(root, f'a try at this step did not work: {step.label}')
        if outcome.reason == 'unavailable':
            self._problem(root, 'research' if question else step.id, 'failed',
                          f"{self._title(record['agent'])} could not be used. {detail}", KEPT)
        elif not question and entry['failed'] >= pipeline.ATTEMPTS:
            self._problem(root, step.id, 'failed', (
                f'This step did not work in {pipeline.ATTEMPTS} tries: {step.label}. The '
                f'last one: {detail}'), KEPT)

    def _title(self, name: str) -> str:
        """An agent's name as a person knows it."""
        try:
            return getattr(self.adapter(name), 'title', name)
        except WorkspaceError:
            return name

    def _stopped(self, root: Path, step: pipeline.Step, outcome: agents.Outcome,
                 started_at: str) -> None:
        """Note a try that was ended on purpose. It is not held against the step."""
        with self.files:
            record = self._load(root)
            self._tried(record, step.id, started_at, outcome.seconds, 'stopped',
                        **self._cost(outcome))
            self._store(root, record)
            self._commit(root, f'this step was stopped: {step.label}')

    def _draft(self, root: Path, run: _Run, found: pipeline.Survey,
               step: pipeline.Next) -> None:
        """One try at a drafting step: the research plan, or one blueprint."""
        if not self._may_go(root):
            return
        record, it = self._load(root), step.step
        work = pipeline.work(root, found, it, step.request, last_error(record, it.id),
                             record['answers'].get(it.id, []))
        outcome, handed, started_at, folder = self._job(root, run, it, work)
        if outcome.reason == 'stopped':
            return self._stopped(root, it, outcome, started_at)
        if handed['artifacts']:
            with self.files:
                pipeline.keep_draft(root, it, handed, step.request)
                record = self._load(root)
                self._tried(record, it.id, started_at, outcome.seconds, 'kept',
                            **self._cost(outcome))
                self._store(root, record)
                self._commit(root, f'keep {workspace.label(it.artifact)}')
            shutil.rmtree(folder, ignore_errors=True)
        elif handed['question']:
            with self.files:
                record = self._load(root)
                self._tried(record, it.id, started_at, outcome.seconds, 'question',
                            **self._cost(outcome))
                record['question'] = {
                    'id': secrets.token_hex(6), 'step': it.id, 'text': handed['question'],
                    'from': f'The worker {it.doing[0].lower()}{it.doing[1:]}',
                    'at': home.now()}
                self._store(root, record)
                self._commit(root, f'a worker asks a question: {it.label}')
        else:
            self._failed(root, it, outcome, started_at,
                         pipeline.why_not(handed, outcome.detail))

    # --- research ------------------------------------------------------------------------

    def _hand_over(self, root: Path, step: pipeline.Step) -> None:
        """Give harness-research the approved plan. Without harness-research the training
        stops here and says so."""
        clock = time.monotonic()
        with self.files:
            try:
                status = self.research().plan(root, root / pipeline.PLAN)
            except WorkspaceError as refusal:
                return self._problem(root, step.id, 'stopped', str(refusal),
                                     'The research plan you approved is kept.')
            record = self._load(root)
            record['research'] = {'run': status.get('run'),
                                  'plan': workspace.sha256_file(root / pipeline.PLAN)}
            self._tried(record, step.id, home.now(), time.monotonic() - clock, 'kept')
            self._store(root, record)
            workspace.checkpoint(root, stage='research', next_step='Research each question')
            self._commit(root, 'hand the approved questions to research')

    def _research(self, root: Path, run: _Run, found: pipeline.Survey,
                  step: pipeline.Next) -> None:
        """One try at each question still to answer, several at a time."""
        def one(ident: str) -> None:
            if self._may_go(root):
                self._question(root, run, found, ident, step.request)

        if self.at_once <= 1 or len(step.questions) == 1:
            for ident in step.questions:
                one(ident)
            return
        with ThreadPoolExecutor(max_workers=self.at_once) as pool:
            for pending in [pool.submit(one, ident) for ident in step.questions]:
                pending.result()

    def _question(self, root: Path, run: _Run, found: pipeline.Survey, ident: str,
                  request: dict | None) -> None:
        """One try at one research question. An accepted finding is recorded at once."""
        it = pipeline.Step(f'research:{ident}', 'agent', f'Research the question {ident}',
                           f'Researching the question {ident}', 'research')
        work = pipeline.question_work(root, found, ident, request,
                                      last_error(self._load(root), it.id))
        outcome, handed, started_at, folder = self._job(root, run, it, work)
        if outcome.reason == 'stopped':
            return self._stopped(root, it, outcome, started_at)
        if handed['finding'] is None:
            return self._failed(root, it, outcome, started_at,
                                pipeline.why_not(handed, outcome.detail))
        with self.files:
            try:
                pipeline.keep_sources(root, handed)
                self._record(root, ident, handed['finding'])
            except WorkspaceError as refusal:
                refused = str(refusal)
            else:
                refused = None
                record = self._load(root)
                self._tried(record, it.id, started_at, outcome.seconds, 'kept',
                            **self._cost(outcome))
                asked = (record.get('research') or {}).get('again') or {}
                if ident in asked.get('left', []):
                    asked['left'].remove(ident)
                self._store(root, record)
                self._commit(root, f'keep the finding for {ident}')
        if refused:
            return self._failed(root, it, outcome, started_at, refused)
        shutil.rmtree(folder, ignore_errors=True)

    def _record(self, root: Path, ident: str, finding: dict) -> None:
        """Record one finding with harness-research, waiting out another save's lock."""
        handed_to = (self._load(root).get('research') or {}).get('run')
        for left in range(BUSY_TRIES, 0, -1):
            try:
                self.research().record(root, handed_to, ident, finding)
                return
            except research_cli.Refused as refusal:
                if not refusal.busy or left == 1:
                    raise
                time.sleep(0.25)

    def _report(self, root: Path, step: pipeline.Step) -> None:
        """Ask harness-research where the research stands, and save its report through
        the core for gate 2. Research that answered nothing stops the training instead."""
        clock = time.monotonic()
        with self.files:
            self.research().status(root)
            record = self._load(root)
            found = pipeline.survey(root, record).research
            reasons = {ident: last_error(record, f'research:{ident}')
                       for ident in found.unread}
            if len(found.unread) == len(found.verdicts):
                why = next((reason for reason in reasons.values() if reason), '')
                return self._problem(root, 'research', 'failed', (
                    f'None of the {len(found.verdicts)} research questions could be '
                    f'answered. {why}').strip(), 'The research plan you approved is kept.')
            pipeline.keep_report(root, found, reasons)
            (record.get('research') or {}).pop('again', None)
            self._tried(record, step.id, home.now(), time.monotonic() - clock, 'kept')
            self._store(root, record)
            self._commit(root, 'keep the research report')

    # --- what a person does --------------------------------------------------------------

    def _fresh(self, record: dict, step: str | None) -> None:
        """Let a step, and the jobs under it, be tried from the start again."""
        for name, entry in record['steps'].items():
            if step is None or name == step or name.startswith(f'{step}:'):
                entry['failed'] = 0

    def decided(self, path, outcome: dict) -> bool:
        """Commit a decision the page has just recorded. False when no run is driving the
        training, so there is nothing to commit or wake.

        Call it holding `files`, straight after the core records the decision, so the
        decision and its commit are one thing; then let go and call `carry_on`. A change
        the person asked for starts its step afresh.
        """
        root = self.driven(path)
        if root is None:
            return False
        with self.files:
            record = self._load(root)
            target = outcome.get('artifact')
            if outcome.get('request') and target:
                self._fresh(record, target)
                problem = record.get('problem') or {}
                if problem.get('step') == target:
                    record['problem'] = None
                if target == 'research' and record.get('research'):
                    record['research']['again'] = {
                        'at': outcome['request'].get('at'),
                        'left': pipeline.again(root, record, outcome['request'])}
                self._store(root, record)
            found = pipeline.survey(root, record)
            ahead = found.next.step
            if found.next.kind in WORK and ahead.stage != found.session['stage']:
                workspace.checkpoint(root, stage=ahead.stage)
            self._commit(root, outcome.get('next_step') or 'a decision was made on the page')
        return True

    def changed(self, path, what: str) -> bool:
        """Commit a change something else just made to a training a run is driving. Call
        it holding `files`. False when no run is driving the training."""
        root = self.driven(path)
        if root is None:
            return False
        with self.files:
            self._commit(root, what)
        return True

    def carry_on(self, path) -> None:
        """After a decision: share the workspace if it is shared after each decision, and
        wake the training's run. Sharing never holds the run up."""
        if self.space().share == gitstate.SHARE[0]:
            self.share_soon()
        self.wake(path)

    def act(self, path, action: str) -> dict:
        """Pause, resume, stop or try again, as the person asks."""
        root = self.driven(path)
        if root is None:
            raise WorkspaceError('No run is driving this training.')
        if action not in ACTIONS:
            raise WorkspaceError('A run can be asked to: ' + ', '.join(ACTIONS) + '.')
        run = self._run(root)
        with self.files:
            record = self._load(root)
            state = self.view(root)['state']
            problem = record.get('problem') or {}
            if action == 'pause':
                if state != 'working':
                    raise WorkspaceError('Only a training that is working can be paused. '
                                         f'This one is {STATES[state]}.')
                record['halt'] = 'paused'
            elif action == 'stop':
                if state not in ('working', 'waiting', 'paused'):
                    raise WorkspaceError(f'This training is {STATES[state]}, so there is '
                                         'nothing to stop.')
                record['halt'] = 'stopped'
                run.stop.set()
            elif action == 'resume':
                if state not in ('paused', 'stopped') and problem.get('action') != 'resume':
                    raise WorkspaceError('This training is not paused or stopped, so there '
                                         'is nothing to resume.')
            elif problem.get('action') != 'retry':
                raise WorkspaceError('Nothing here failed, so there is nothing to try again.')
            if action in ('resume', 'retry'):
                if problem.get('action') == 'resume':  # it may spend as much again
                    record['cleared'] = spent(record)[0] or 0.0
                elif problem:
                    self._fresh(record, problem.get('step'))
                record['problem'] = record['halt'] = None
                # the limits this computer has now
                chosen = settings.load()
                record['limits'] = {'step_seconds': chosen.step_seconds,
                                    'training_dollars': chosen.training_dollars}
            self._store(root, record)
            self._commit(root, {'pause': 'paused on the page', 'stop': 'stopped on the page',
                                'resume': 'resumed on the page',
                                'retry': 'asked to try again on the page'}[action])
        if action in ('resume', 'retry'):
            run.stop.clear()
            self.wake(root)
        return self.view(root)

    def answer(self, path, ident: str, text: str) -> dict:
        """Record a person's answer to a worker's question. The step runs again with it."""
        root = self.driven(path)
        if root is None:
            raise WorkspaceError('No run is driving this training.')
        with self.files:
            record = self._load(root)
            asked = record.get('question')
            if not asked or asked.get('id') != ident:
                raise WorkspaceError('That question is not waiting for an answer any more.')
            record['answers'].setdefault(asked['step'], []).append(
                {'question': asked['text'], 'answer': text.strip(), 'at': home.now()})
            record['question'] = None
            self._store(root, record)
            self._commit(root, 'a worker\'s question was answered on the page')
        self.wake(root)
        return self.view(root)

    # --- sharing -------------------------------------------------------------------------

    def share(self) -> dict:
        """Share the workspace now. Never fails a run: when it cannot share, the work stays
        on this computer and the notice says why."""
        space = self.space()
        with self.files:
            try:
                report = gitstate.sync(space)
            except WorkspaceError as refusal:
                report = {'shared': False, 'notice': str(refusal)}
        self._unshared = None if report['shared'] else report['notice']
        self.adopt()
        return {'shared': bool(report['shared']), 'notice': report['notice']}

    def share_soon(self) -> None:
        """Share without making anyone wait for it."""
        space = self.workspace
        if space is None or space.address is None:
            return
        if not self.background:
            self.share()
            return
        with self._lock:
            if self._sharing is not None and self._sharing.is_alive():
                self._share_again = True
                return
            self._sharing = threading.Thread(target=self._share_on, daemon=True,
                                             name='sharing')
            self._sharing.start()

    def _share_on(self) -> None:
        while True:
            try:
                self.share()
            except Exception as failure:  # sharing never ends the runner
                self._unshared = f'The work could not be shared ({failure}). It is kept on ' \
                                 'this computer.'
            with self._lock:
                if self._share_again and not self._closing:
                    self._share_again = False
                    continue
                self._sharing = None
                return

    def shared(self) -> dict:
        """Whether everything committed here has been shared, as far as can be told without
        asking the remote, and why the last try at sharing did not share it."""
        space = self.workspace
        if space is None or space.address is None:
            return {'shared': False, 'notice': None}
        waiting = hub.ahead(space.repo, f'refs/remotes/origin/{space.branch}')
        return {'shared': not waiting, 'notice': self._unshared if waiting else None}

    # --- what the page shows -------------------------------------------------------------

    def _doing(self, record: dict, found: pipeline.Survey) -> str:
        """What a working run is doing now, in a sentence."""
        step = found.next
        if step.kind == 'gate':
            return f'Getting {workspace.label(step.step.artifact)} ready for your review.'
        if step.step.id == 'research':
            verdicts = found.research.verdicts
            answered = len(verdicts) - len(found.research.unread)
            return (f'Researching the questions: {answered} of {len(verdicts)} answered so '
                    'far.')
        error = last_error(record, step.step.id)
        if error:
            return f'{step.step.doing} again. The last try did not work: {error}'
        return f'{step.step.doing}.'

    def _state(self, record: dict, found: pipeline.Survey, run: _Run) -> tuple[str, str]:
        """A run's state, and what is happening in a sentence."""
        problem, halt, step = record.get('problem'), record.get('halt'), found.next
        if problem:
            return problem.get('state', 'failed'), problem['what']
        if halt == 'stopped':
            return 'stopped', 'Stopped. Everything kept so far is still here.'
        if halt == 'paused':
            return 'paused', ('Pausing. The step in hand finishes first.' if run.workers
                              else 'Paused. Nothing new starts until you resume.')
        if record.get('question'):
            return 'waiting', f"A question is waiting for you: {record['question']['text']}"
        if step.kind == 'wait':
            it = workspace.sentence(workspace.label(step.step.artifact))
            return 'waiting', f'{it} is waiting for your review.'
        if step.kind == 'done':
            first = ('Every blueprint is approved.' if len(found.session['levels']) > 1
                     else 'The blueprint is approved.')
            return 'done', f'{first} {pipeline.LATER}'
        if step.kind == 'stuck':
            return 'failed', step.why
        if run.queued:
            return 'working', 'Waiting for its turn. Other trainings are working.'
        return 'working', self._doing(record, found)

    def _steps(self, record: dict, found: pipeline.Survey, state: str) -> list[dict]:
        """Every step of the training, with how it stands and what it has taken."""
        ahead = found.next.step.id if found.next.step else None
        current = 'intake' if ahead == 'gate:intake' else ahead
        failed = (record.get('problem') or {}).get('step')
        if state == 'failed' and failed not in [step.id for step in found.steps]:
            failed = current
        listed = []
        for step in found.steps:
            tried = attempts(record, step.id)
            dollars = [attempt['dollars'] for attempt in tried
                       if attempt.get('dollars') is not None]
            if step.id == failed:
                status = 'failed'
            elif step.id in found.done:
                status = 'done'
            elif step.id == current and state in ('working', 'waiting'):
                status = state
            else:
                status = 'to-do'
            listed.append({
                'id': step.id, 'label': step.label, 'kind': step.kind, 'status': status,
                'attempts': len(tried),
                'seconds': round(sum(attempt.get('seconds') or 0 for attempt in tried), 1)
                if tried else None,
                'dollars': round(sum(dollars), 4) if dollars else None,
                'error': self._error(record, found, step, status)})
        return listed

    @staticmethod
    def _error(record: dict, found: pipeline.Survey, step: pipeline.Step,
               status: str) -> str | None:
        """What last went wrong at a step that has not got past it. For research, how many
        questions have no answer because their workers failed."""
        if step.id == 'research':
            reasons = [last_error(record, f'research:{ident}')
                       for ident in found.research.unread]
            reasons = [reason for reason in reasons if reason]
            if not reasons:
                return None
            count = len(reasons)
            return (f'{count} question{"" if count == 1 else "s"} could not be answered. '
                    f'The last reason: {reasons[-1]}')
        return None if status == 'done' else last_error(record, step.id)

    def _workers(self, run: _Run) -> list[dict]:
        """The workers running now, each with the last few things it did."""
        with self._lock:
            live = list(run.workers.items())
        return [{'id': ident, 'label': worker['label'], 'started_at': worker['started_at'],
                 'lines': list(worker['lines'])} for ident, worker in live]

    def ahead(self, path) -> tuple[str, str] | None:
        """A run's state and what comes next, for the sentence shown after a decision.
        While it works that is the job its workers do next, or the review it is getting
        ready, not a step of the runner's own that is over in a moment. None when no run
        is driving the training."""
        root = self.driven(path)
        if root is None:
            return None
        record = self._load(root)
        found = pipeline.survey(root, record)
        state, sentence = self._state(record, found, self._run(root))
        if state != 'working':
            return state, sentence
        coming = [step for step in found.steps if step.id not in found.done]
        ahead = found.next.step if found.next.kind == 'gate' else next(
            (step for step in coming if step.kind != 'code'), found.next.step)
        if ahead.kind == 'gate':
            return state, f'Getting {workspace.label(ahead.artifact)} ready for your review.'
        return state, f'{ahead.doing} now.'

    def brief(self, path) -> dict | None:
        """A run in two words and a sentence, for a list. `needs` says a question or a
        problem is waiting for the person. None when no run is driving the training."""
        root = self.driven(path)
        if root is None:
            return None
        try:
            record = self._load(root)
            found = pipeline.survey(root, record)
        except (WorkspaceError, OSError) as failure:
            return {'state': 'failed', 'sentence': str(failure), 'needs': True,
                    'question': None}
        state, sentence = self._state(record, found, self._run(root))
        asked = record.get('question')
        needs = bool(asked or record.get('problem') or found.next.kind == 'stuck')
        return {'state': state, 'sentence': sentence, 'needs': needs,
                'question': asked['text'] if asked else None}

    def view(self, path) -> dict | None:
        """Everything the page shows for one run. None when no run is driving it."""
        root = self.driven(path)
        if root is None:
            return None
        record = self._load(root)
        found = pipeline.survey(root, record)
        run = self._run(root)
        state, sentence = self._state(record, found, run)
        asked, problem = record.get('question'), record.get('problem')
        if problem is None and found.next.kind == 'stuck':
            problem = {'what': found.next.why, 'action': None, 'label': None,
                       'kept': 'Everything in the training\'s folder is as it was.'}
        dollars, tokens = spent(record)
        return {
            'state': state, 'sentence': sentence, 'agent': record['agent'],
            'model': record.get('model'), 'steps': self._steps(record, found, state),
            'workers': self._workers(run),
            'spent': {'dollars': dollars, 'tokens': tokens},
            'question': ({'id': asked['id'], 'text': asked['text'], 'from': asked['from']}
                         if asked else None),
            'problem': ({key: problem.get(key) for key in ('what', 'kept', 'action', 'label')}
                        if problem else None)}

    def status(self) -> dict:
        """Every run in the workspace, for a script."""
        listed = []
        for root in self.trainings():
            found = self.brief(root) or {}
            listed.append({'path': str(root), 'id': root.name, 'state': found.get('state'),
                           'sentence': found.get('sentence')})
        return {'trainings': listed}
