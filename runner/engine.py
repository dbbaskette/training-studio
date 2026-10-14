"""The engine: walks each training's pipeline, hands jobs to workers and stops at gates.

What a caller needs to know
---------------------------
    engine = Engine()                        # the real agents and harness-research
    engine.resume()                          # pick up every training in the workspace
    engine.resume(wait=False)                # the same, fetching in the background
    made = engine.start(form)                # {'path', 'id', 'gates'}; the run starts at once
    engine.view(path)                        # what the page shows for one run
    engine.act(path, 'pause')                # or 'resume', 'stop', 'retry'
    engine.answer(path, question_id, text)   # a person answers a worker's question
    engine.supply(path, 'add', name, data)   # a document of theirs; or 'remove', or 'done'
    engine.whose(path, 'scenario:main')      # who wrote a scenario: 'runner' or 'you'
    engine.copies_again(path)                # make the copies that are not made, again
    engine.outline(path, level, 'approve')   # a person's decision about what a deck says
    engine.picture(path, number, artifact=)  # one slide's picture, as PNG bytes
    engine.deck_gate(path, 'deck')           # what gate 6 adds for a deck the runner made
    engine.deck_needs()                      # what this computer has for making a deck
    engine.models('codex')                   # the models an agent offers, and their levels
    engine.decided(path, outcome)            # commit a decision the page just recorded
    engine.carry_on(path)                    # then share if that is wanted, and wake the run
    engine.share()                           # fetch, replay and push the workspace
    engine.fetch()                           # fetch and replay; nothing is sent
    engine.drive(path, 'take')               # take a training, or take it over; 'hand-over'
    engine.hold(path)                        # refuse, saying who has it, if it is not ours
    engine.standing()                        # every run here, those driven elsewhere, and
                                             # what `upkeep` found of the skills here
    engine.publish(path)                     # the next revision of a training, as a tag
    engine.published()                       # each training's latest published revision
    engine.leaving(path)                     # what deleting a training would do
    engine.delete(path, title)               # stop it, delete it, and share that
    engine.bring(folder)                     # copy a conversation's training in, and run it
    engine.serving()                         # fetch on a timer, and notify, while serving
    engine.seen(); engine.tell()             # a page asked; notify if none has for a while
    engine.close()                           # end every worker; nothing half-made is kept

- The next step is never remembered. Each time, `pipeline.survey` works it out from the
  training's files, so starting the runner again resumes every training where it was.
- The run record, `.training-studio/run.json` in the training's folder, holds only what the
  files cannot say: the agent, model and reasoning level chosen when the training started,
  the limits, each
  try at each step with its times, cost, outcome and error, which research run the plan
  was handed to, a worker's question and the person's answers, why the run is halted,
  where its research may look and whether the person's documents are all added, which
  scenario files the runner drafted, which copies it tried to make and why one could
  not be made, and for each deck what its outline was written from, whether what it says
  is put to the person, what they decided, and which deck was saved. It is committed with
  everything else.
- One try at an agent step: an empty job folder under `agents.staging()`, a brief, a
  worker, and results taken only from what the worker tools accepted. A draft is saved
  through the core and committed. A step is tried up to three times, with the reason for
  the last failure added to the brief; then the training stops and says what went wrong.
  An agent that cannot be reached is not tried again until the person asks.
- A research question that fails three times does not stop the training. It is left
  unanswered and named at gate 2, where the person decides. Research with no answer at all
  does stop it.
- The engine never approves. It sets a gate through the core and waits. The page records
  the person's decision through the core, then calls `decided` and `carry_on`. What a deck
  says has a gate of the runner's own, kept in the run record: the engine puts it to the
  person and waits, and `outline` is how the page records what they decided.
- Where the slides tool keeps a design session, what a deck says is written with how each
  slide is drawn, and the gate puts both to the person as one decision. The design is
  proposed to the tool, the page's decision is sent to it as the one answer to its
  question, and the approval binds the outline, the proposal and the tool's revision. A
  deck keeps the gate it was first written with, so a deck already under way when the tool
  gains the session is decided on its words alone, as before.
- After the blueprints it goes one level at a time: the guide, the brief, each practice
  scenario, each Yoodli scenario, with the copies the training asked for made after each
  approval. A copy that cannot be made is noted with the reason and never holds it up.
  The index is written last. A stage the person left out is passed over, and something
  made from what has since changed is made again and put to them again.
- A deck is made for each level after its brief: the handoff, the brand exported and
  checked, what the deck says written by a worker and put to the person at the runner's
  own gate, the tool's split into sections, the sections drawn side by side by workers
  that look at what they draw, the whole deck merged, compiled and previewed, a review by
  a worker that drew nothing, the sections with a major finding about how they are drawn
  drawn again, at most twice, and then the previewed deck itself saved through the core
  with the brand's audit and the reviewed coverage, for gate 6. The brand's export is
  checked before each step that uses it: a brand that changed underneath stops the deck
  and says so. A render that fails leaves nothing behind. Previews are taken one at a
  time on this computer.
- On a computer that cannot make a deck, a training that wants one is taken through every
  other stage. It then stops, done as far as the runner goes, with `deck_left` in its
  view saying what is missing; the index is written once the deck is left out, or
  approved in a conversation. `look_again` looks at the computer afresh and wakes them.
- When a training has a brand, the writers of its guide, its brief and its scenarios are
  given the brand's rules for how the organisation and its products are named.
- A training researched from the person's documents waits for them first. Nothing is
  drafted or researched until `supply(path, 'done')`.
- A training whose decisions were moved to a conversation is left alone, except that its
  index is written when that is all there is left to do. Moving them back wakes it.
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
  `documents`, `copies` and `index` are the three modules of those names, or anything
  with the same functions; a test gives its own, so that none reads a PDF, asks Google or
  runs a converter. `slides` and `brand` make the wrappers of the slides tool and of a
  brand skill, each refusing with a sentence when this computer has none.
- What this computer has for a deck is looked at when asked and reused for a few minutes:
  the slides tool and its version, a brand skill and its brands, and from the slides
  module's `ready(slides)` whether LibreOffice (`local`) or Google Drive (`drive`) can render and
  whether the programs that make pictures (`pictures`) are there, with its sentences for
  what is missing under `missing`.
- The slides wrapper's `reading()` gives the tool's own guidance as {name: text}. It is
  kept beside the two contracts when the brand is exported. A composer is handed the
  design guidance, the composition guidance, what the gallery is for and the example of
  each relation its own slides have; the outline's writer is handed the drafting guidance.
- A deck's workers use the slides tool and the brand skill the engine uses: each job is
  told where they are, from `Slides.runtime` and `Brand.runtime`.
- In a workspace with a shared repository, a training is run from one computer at a time.
  Its run record names the driver. Starting a training takes it, and the claim is pushed
  before any work; `drive` takes one nobody has, takes one over, or hands one over. A
  claim the shared repository refuses is dropped, and the refusal says who has it. Every
  change a person asks for goes through `hold` first, and the engine works on nothing
  that is not this computer's. A finished training has no driver. A workspace that is a
  folder on this computer has no drivers at all, and nothing here changes for it.
- `share` and `fetch` both learn first what the shared repository now says. A training
  this computer drove that someone else has taken is stopped at once: its commits that
  were never shared are set aside under a ref, nothing more is written to it, and its
  view says who took it and when, in `taken` and in `notice`, until this computer takes it
  back; that is remembered in the data folder. When the same file was changed on two computers, the
  view of that training says that one side must take it over. `take` does that: this
  computer's unshared commits for it are set aside, and it carries on from what is shared.
  `notice` says in plain words that what was set aside is kept on this computer; the names
  git keeps it under are in the view's `kept`, for someone who brings it back. `clash` is
  true while the notice is about a training changed on two computers.
- Of a training someone else drives, this computer knows only what was last shared. Its
  state is `elsewhere` whatever its files say, no step of it is shown as working, and
  `last_shared` is {'at', 'by', 'says'}: when that was, whose commit it was, and where the
  training stood then, said of the past. Its sentence says the same.
- Trainings take turns in the order they became ready, as many at once as the settings
  allow. One that waits says how many are ahead of it.
- A notification is sent only when it is turned on in the settings, no page has asked
  anything for PAGE_OPEN seconds, and a training of this computer's needs a decision. It
  is sent once for each thing, and what was sent is remembered in the data folder.
- A published revision is a tag on the commit where the workspace stands, numbered from
  1 for each training, never moved, and pushed without force. See `team.publish`.
- `delete` takes a training this computer runs, in any state, or a finished one nobody
  runs. A run that works is stopped first, as Stop does, and the deletion waits until no
  thread, step or slot of it is left; one that has not ended in STOP_WAIT seconds is left
  stopped and nothing is deleted. The folder is taken out of the branch in one commit that
  says who and when, shared as any change is, and what only this computer kept for it
  goes: its ignored files, its job folders, its notes in the data folder and its place in
  the lists. Published revisions, files in Google Drive and anything `set_aside` kept stay.
  A deletion that is not yet shared, of a training a teammate takes meanwhile, is set
  aside when that is learned, so their version comes back whole and `notice` says so. A
  training a fetch brings in deleted elsewhere is let go of here, leftovers and all.
- `bring` copies a training's folder into the workspace under the name its title gives,
  moves its decisions to the page, gives it a run record that takes it, and commits. The
  folder it came from is only read. The run then carries on from what the files say.
"""
from __future__ import annotations

import contextvars
import json
import re
import secrets
import shutil
import threading
import time
from collections import deque
from dataclasses import replace
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

import runner  # noqa: F401  puts the core on the import path
import computer
import home
import hub
import workspace
from workspace import WorkspaceError

from runner import agents, companion, deck, gitstate, pipeline, settings, team, worker_tools
from runner import brand as brand_skill
from runner import copies as copies_made
from runner import documents as documents_kept
from runner import index as index_written
from runner import research as research_cli
from runner import slides as slides_tool

SCHEMA = 1
RECORD = f'{workspace.STATE_DIR}/run.json'
# Written when a step starts and removed when it ends, and never shared. One left behind
# says the runner ended in the middle of a step, not that a person changed a file.
IN_HAND = f'{workspace.STATE_DIR}/step.lock'
AT_ONCE = 3             # research questions worked on at the same time
LINES = 6               # the last things a worker did that the page is shown
READY_FOR = 60          # seconds a look at an agent is reused
MODELS_FOR = 3600       # seconds a list of an agent's models is reused
MODELS_MISSED = 60      # seconds before a list that could not be made is asked for again
LOOKED_FOR = 300        # seconds a look at what this computer has for a deck is reused
BUSY_TRIES = 20         # times a finding is offered while another save holds the lock
ACTIONS = ('pause', 'resume', 'stop', 'retry')
DRIVING = ('take', 'hand-over')
FETCH_EVERY = 180       # seconds between fetches while the runner serves
TICK = 15               # seconds between looks at whether to notify
PAGE_OPEN = 45          # seconds since a page last asked, while one counts as open
# What went wrong in the work done in the background while the runner serves, by job.
BACKGROUND = {'fetch': 'The last look for what your team shared did not work: {said}. It '
                       'is tried again every few minutes.',
              'tell': "The last try at telling you through this computer's notifications "
                      'did not work: {said}. It is tried again in a few seconds.'}
NO_DRIVERS = ('This workspace is a folder on this computer, so its trainings are not taken '
              'or handed over.')
TAKEN = '{name} took this training over on {when}. This computer stopped working on it.'
SET_ASIDE = (' What this computer had made and not yet shared is kept on this computer, and '
             'can be brought back.')
THEIRS = '{name} is running this training from another computer.'
LAST = ' What is here is what was last shared{when}. {then} It may have moved on since.'
BROKEN = ('"{title}" was changed on this computer and on another at the same time, so '
          'nothing here can be shared. One side must take it over. Taking it over here '
          'carries on from the shared version; what this computer made and never shared is '
          'set aside and kept.')
UNREACHED = ('The shared repository could not be reached, so this training cannot be taken '
             'now. Nothing was changed. Try again when it can be reached.')
CHECKING = ('The runner has just started and is still looking at what your team shared while '
            'it was closed. Nothing was changed. Try again in a moment.')
STALLED = ('Something went wrong while the runner picked its trainings up ({failure}), so this '
           'one may not carry on by itself. Close the runner and start it again.')
# The steps of a deck, and what the engine does for each. What a deck says is drafted like
# any other draft, and gate 6 is the core's.
DECK = {'deck-handoff': '_handoff', 'deck-brand': '_export', 'gate:deck-outline': '_ask',
        'deck-start': '_split', 'deck-sections': '_sections', 'deck-repair': '_sections',
        'deck-whole': '_whole', 'deck-review': '_review', 'deck-save': '_keep'}
SUPPLYING = ('add', 'remove', 'done')
DECIDING = ('approve', 'revise')    # what a person may decide about what a deck says
STATES = {'working': 'working', 'waiting': 'waiting for you', 'paused': 'paused',
          'stopped': 'stopped', 'failed': 'stopped on a problem',
          'done': 'finished as far as the runner takes it'}
WORK = ('agent', 'code', 'gate')
KEPT = 'Everything kept before this step is still here. Nothing from the tries that failed '\
       'was kept.'
AWAY = ("This training's decisions are made in the conversation now, so the runner is "
        'leaving it alone. Move them back to the page to have the runner carry on.')
NO_PDF = 'This computer cannot read a PDF: save it as text or as a Word file first.'
NOT_HERE = ('The documents this training was researched from are on another computer. '
            'Research cannot be run again here until they are added again.')
SETTLED = ('The research for this training was planned from the documents already added, so '
           'they cannot be changed now.')
PREVIEWS = 'previews'   # in the per-user data folder: the render's turn, and each deck's file
DECK_KEPT = ('What you approved the deck should say is kept, and so is everything made '
             'before it.')
CHANGED = '{it} has changed since it was opened. Read the new version before deciding.'
DESIGN_GONE = ('What this deck says is written with its design, which the slides tool on '
               'this computer cannot keep. Update harness-slides, then try again.')
SECTIONS_GONE = ('This deck is drawn from the design you approved, and the slides tool on '
                 'this computer cannot check a section against it. Update harness-slides, '
                 'then try again.')
ASSETS_WAIT = ('The deck is not drawn until what its approved design uses is to hand. {said}')
ASSETS_KEPT = ('What you approved the deck should say, and how it is drawn, is kept, and so is '
               'everything made before. Nothing needs approving again.')
NOT_SUPPLIED = ('{asset} is not a picture the approved design of this deck asks you for. '
                'Supply one of those it lists.')
PICTURES = {b'\x89PNG\r\n\x1a\n': '.png', b'\xff\xd8\xff': '.jpg', b'GIF87a': '.gif',
            b'GIF89a': '.gif'}   # what a supplied picture may be, by how its file begins
DESIGN_DIFFERS = ('The design you approved is not what the slides tool holds as approved, so '
                  'the deck cannot be started. {said}')
NOT_CHOSEN = ("How a deck's previews are rendered has not been chosen. Choose Google Drive "
              'or LibreOffice in Settings.')
NO_RENDERER = ('This computer has no way to render previews of slides. Install LibreOffice, '
               'or give it Google access that reaches Drive.')
NO_DRIVE = ('Previews are set to go through Google Drive, and Google access from this '
            'computer does not reach Drive. Sign in to Google with Drive access, or choose '
            'LibreOffice in Settings.')
NO_LOCAL = ('Previews are set to be rendered with LibreOffice, which this computer does not '
            'have. Install it, or choose Google Drive in Settings.')
NO_PICTURES = ('The programs the slides tool uses to turn a render into pictures are not on '
               'this computer.')
BRAND_CHANGED = ('The brand changed underneath this deck after it was exported. {said} Try '
                 'again to export it afresh. The slides are then drawn again from what you '
                 'approved the deck should say.')
NO_PICTURE = 'There is no picture of that slide on this computer.'
STOP_WAIT = 30          # seconds a run that is being deleted may take to end
NOT_YOURS = ('{name} runs this training from another computer, so it cannot be deleted from '
             'here. Take it over first if you mean to delete it.')
NOT_TAKEN = ('Nobody is running this training, so it cannot be deleted from here until '
             'someone takes it. Take it first if you mean to delete it.')
MISTITLED = ('That is not the title of this training. Nothing was deleted: open the training '
             'again before you delete it.')
NOT_ENDED = ('It was stopped, but something it started has not ended yet, so it was not '
             'deleted. Try deleting it again in a moment.')
KEPT_BACK = ('{name} took this training on {when}, before your deletion of it was shared, so '
             'it was not deleted. It is as they shared it.')
WAITS = ('It is gone from this computer. Your team sees it gone the next time the workspace '
         'is shared.')
DRIVE = {'preview': 'Preview presentation', 'slides': 'Google Slides deck',
         'doc': 'Google Doc'}


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


def new_record(agent: str, model: str | None, chosen: settings.Settings,
               scope: str = pipeline.SCOPE, effort: str | None = None) -> dict:
    """A run record for a training that is starting. `scope` is where its research may
    look: anything but the public web alone waits for the person's documents first.
    `effort` is the reasoning level every worker is given; None for the agent's own."""
    supplied = None if scope == pipeline.SCOPE else {'scope': scope, 'done': None, 'count': 0}
    return {'schema': SCHEMA, 'agent': agent, 'model': model, 'effort': effort,
            'started_at': home.now(),
            'limits': {'step_seconds': chosen.step_seconds,
                       'training_dollars': chosen.training_dollars},
            'steps': {}, 'research': None, 'question': None, 'answers': {}, 'halt': None,
            'problem': None, 'cleared': 0.0, 'documents': supplied, 'drafted': [],
            'copies': {'problems': {}, 'tried': {}}, 'deck': {}, 'driver': None}


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


def older(version: str, needed: str) -> bool:
    """True when a version is older than the one that is needed."""
    def parts(text: str) -> tuple:
        return tuple(int(part) for part in re.findall(r'\d+', text)[:3])
    return parts(version) < parts(needed)


def folder_name(step: str) -> str:
    """A step's name as part of a folder's. A research question can never be mistaken for
    another step, whatever its ID."""
    if step.startswith('research:'):
        return 'question-' + step.partition(':')[2]
    return re.sub(r'[^a-z0-9]+', '-', step.lower()).strip('-')


def _refs(repo: Path, branch: str) -> tuple | None:
    """Where a clone's branch and what it knows of the remote's stand, told without starting
    git: each file git keeps them in, by when it was written, how large it is and which file
    it is. git writes a ref anew, never in place, so any change shows. None where the refs
    are not kept in such files."""
    folder = repo / '.git'
    if not folder.is_dir() or (folder / 'reftable').exists():
        return None
    marks: list = [str(repo), branch]
    for name in ('HEAD', f'refs/heads/{branch}', f'refs/remotes/origin/{branch}',
                 'packed-refs'):
        try:
            found = (folder / name).stat()
        except OSError:
            marks.append(None)
            continue
        marks.append((found.st_mtime_ns, found.st_size, found.st_ino))
    return tuple(marks)


class Elsewhere(WorkspaceError):
    """This computer may not change a training: someone else drives it, or nobody does."""


class _Gone(WorkspaceError):
    """A training stopped being this computer's while a step of it was in hand."""


class _Slots:
    """How many trainings may work at once, and whose turn is next: they take turns in
    the order they asked. The limit is read as each one starts to wait, and again when
    `renew` says the settings changed, so a change is felt without a restart, and a run
    that waits does not read the settings over and over."""

    def __init__(self, limit):
        self.read, self.limit, self.used = limit, None, 0
        self.changed = threading.Condition()
        self.waiting: list = []

    def take(self, closing, who=None) -> bool:
        who = object() if who is None else who
        with self.changed:
            self.waiting.append(who)
            self.limit = self.read()
            try:
                while self.used >= self.limit or self.waiting[0] is not who:
                    if closing():
                        return False
                    self.changed.wait(0.5)
                self.used += 1
                return True
            finally:
                self.waiting.remove(who)
                self.changed.notify_all()

    def ahead(self, who) -> int | None:
        """How many are waiting in front of one that waits. None for one that does not."""
        with self.changed:
            return next((place for place, waiting in enumerate(self.waiting)
                         if waiting is who), None)

    def give_back(self) -> None:
        with self.changed:
            self.used -= 1
            self.changed.notify_all()

    def renew(self) -> None:
        """The settings changed: read the limit again, and let whoever it now admits go."""
        with self.changed:
            self.limit = self.read()
            self.changed.notify_all()


class _Run:
    """What the engine holds for one training while it serves: nothing that is needed to
    resume it."""

    def __init__(self):
        self.thread: threading.Thread | None = None
        self.again = self.queued = self.busy = False
        self.gone = False   # it stopped being this computer's: nothing more is written
        self.stop = threading.Event()
        self.workers: dict[str, dict] = {}


class Engine:
    """Drives every training in this computer's workspace."""

    def __init__(self, adapters=None, research=None, background: bool = True,
                 at_once: int = AT_ONCE, documents=None, copies=None, index=None,
                 slides=None, brand=None, notifier=None):
        self.adapters = dict(adapters or agents.AGENTS)
        self.notifier = notifier or team.Notifier()
        self.upkeep = None    # what `studio serve` keeps of the skills here; see `upkeep`
        self._asked: float | None = None    # when a page last asked anything
        self._clash: dict[str, str] = {}    # trainings changed on two computers at once
        self._serving: threading.Thread | None = None
        self._ending = threading.Event()
        self._fetched = 0                   # fetches that reached the shared repository
        self._as_of: dict[tuple, tuple[int, object]] = {}   # what was read as of a fetch
        self._tags_unsent = True            # a published revision may be waiting to go
        self.research = research or research_cli.Research
        self.slides = slides or slides_tool.Slides
        self.brand = brand or brand_skill.Brand
        self._looked: tuple[float, dict] | None = None
        self._looking = threading.Lock()    # one look at this computer at a time
        self._ahead: tuple[tuple, int] | None = None    # the clone's refs, and commits unshared
        self._background: dict[str, dict] = {}  # what last went wrong in the background, by job
        self.documents = documents or documents_kept
        self.copies = copies or copies_made
        self.index = index or index_written
        self.background, self.at_once = background, at_once
        self.files = threading.RLock()
        self._lock = threading.RLock()
        self._runs: dict[str, _Run] = {}
        self._slots = _Slots(lambda: settings.load().parallel)
        self._closing = False
        self._unshared: str | None = None   # why the last try at sharing did not share
        self._checking = False              # the first fetch after starting is not done yet
        self._stalled: str | None = None    # what went wrong picking the trainings up
        self._sharing: threading.Thread | None = None
        self._share_again = False
        self._dropped: set[str] = set()     # trainings a fetch brings in deleted elsewhere
        self._ready: dict[str, tuple[float, agents.Readiness]] = {}
        self._models: dict[str, tuple[float, dict]] = {}  # each agent's list, and when
        self._listing: dict[str, threading.Lock] = {}     # one listing per agent at a time

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

    def models(self, name: str) -> dict:
        """What an agent offers to choose from: {'agent', 'models', 'levels', 'problem'},
        as `agents` describes. A list is kept for MODELS_FOR seconds, and one that could not
        be made, with the sentence that says why, for MODELS_MISSED. Each agent is asked by
        one caller at a time, and nothing else waits for it."""
        adapter = self.adapter(name)
        with self._lock:
            listing = self._listing.setdefault(name, threading.Lock())
        with listing:
            seen = self._models.get(name)
            if seen is not None and time.monotonic() - seen[0] < (
                    MODELS_FOR if seen[1]['problem'] is None else MODELS_MISSED):
                return seen[1]
            try:
                if not hasattr(adapter, 'models'):
                    raise WorkspaceError(f'{adapter.title} cannot list its models.')
                found = {'agent': name, **adapter.models(), 'problem': None}
            except WorkspaceError as failure:
                found = {'agent': name, 'models': [], 'levels': [], 'problem': str(failure)}
            self._models[name] = (time.monotonic(), found)
            return found

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

    def _wanted(self, root: Path, record: dict) -> list[dict]:
        """Every copy the training asks for, with why one could not be made."""
        return self.copies.wanted(root, (record.get('copies') or {}).get('problems') or {})

    def _survey(self, root: Path, record: dict, copies=None) -> pipeline.Survey:
        """Where a training is, with its copies and the person's documents looked at.
        `copies` saves looking at the copies again when the caller just has."""
        supplied = self.documents.listed(root) if record.get('documents') else ()
        copies = self._wanted(root, record) if copies is None else copies
        return pipeline.survey(root, record, copies, supplied, self._deck_here(root))

    def _deck_here(self, root: Path) -> dict | None:
        """What this computer has for a training's deck. Not looked at for a training
        that wants none."""
        if 'deck' not in pipeline.wanted(workspace.load(root)):
            return None
        needs = self.deck_needs()
        return {'missing': needs['missing'], 'brands': needs['brands']}

    @staticmethod
    def _away(found: pipeline.Survey) -> bool:
        """True when the training's decisions are made in a conversation, not on the page."""
        return found.session['settings']['approval'] != 'page'

    def _commit(self, root: Path, what: str) -> None:
        """Commit one training's folder, saying what happened. Call it holding `files`.
        Nothing is committed for a training that stopped being this computer's while a
        step was in hand: what the step wrote is put back, and the step ends."""
        if self._run(root).gone:
            gitstate.discard(self.space(), root)
            raise _Gone('This training is no longer run from this computer.')
        title = workspace.load(root)['title']
        gitstate.commit(self.space(), f'{title}: {what}', [root])

    # --- one driver for each training ----------------------------------------------------

    def mine(self, path) -> bool:
        """True when this computer may change a training: always in a workspace with no
        shared repository, else only while its run record names this computer."""
        root = self.driven(path)
        return root is not None and team.ours(self.workspace, self._load(root))

    def hold(self, path) -> None:
        """Refuse, saying who has it, a change to a training this computer does not
        drive, and any change while the runner that just started is still looking at what
        was shared. A training no run is driving is not the engine's to refuse."""
        root = self.driven(path)
        if root is None:
            return
        if self._checking:  # who drives it may have changed while the runner was closed
            raise WorkspaceError(CHECKING)
        why = team.elsewhere(self.workspace, self._load(root))
        if why:
            raise Elsewhere(why)

    def _held(self, path) -> Path:
        """A training's folder, once a run is driving it and it is this computer's."""
        root = self.driven(path)
        if root is None:
            raise WorkspaceError('No run is driving this training.')
        self.hold(root)
        return root

    def _pushed(self, root: Path, space: gitstate.Workspace) -> dict:
        """Share a claim just committed. Call it holding `files`."""
        return self._step(space, push=True)

    def drive(self, path, action: str) -> dict:
        """Take a training nobody drives, take one over, or hand one over. Returns its
        view. A claim is pushed before anything else is done; one the shared repository
        does not take is dropped, and the refusal says who has the training."""
        root = self.driven(path)
        if root is None:
            raise WorkspaceError('No run is driving this training.')
        if action not in DRIVING:
            raise WorkspaceError('A training can be asked to: ' + ', '.join(DRIVING) + '.')
        space = self.space()
        if space.address is None:
            raise WorkspaceError(NO_DRIVERS)
        if action == 'hand-over':
            self._hand(root, space)
            return self.view(root)
        kept = self._take(root, space)
        self.wake(root)
        shown = self.view(root)
        if kept and not shown.get('notice'):
            shown['notice'] = 'This training carries on from the shared version.' + SET_ASIDE
        return shown

    def _take(self, root: Path, space: gitstate.Workspace) -> str | None:
        """Make a training this computer's. Returns the ref that keeps what was set
        aside of this computer's own to do it, when anything was."""
        run, kept = self._run(root), (team.kept('taken').get(str(root)) or {}).get('kept')
        with self.files:
            was = (self._load(root).get('driver') or {}).get('computer')
            report = self._step(space, push=False)
            if not report.get('reached'):
                raise WorkspaceError(UNREACHED)
            if root.name in self._clash or (
                    not team.ours(space, self._load(root)) and gitstate.unshared(space, root)):
                kept = gitstate.set_aside(space, root) or kept
                self._as_of.pop(('kept', str(root)), None)
                report = self._step(space, push=False)
            if report.get('conflict'):
                raise WorkspaceError(report['notice'])
            record = self._load(root)
            now = record.get('driver') or None
            if team.ours(space, record):
                self._ours_again(root, run)
                return kept
            if now and now.get('computer') != was:
                raise Elsewhere(f"{now.get('name') or 'Someone'} took this training on "
                                f"{team.day(now.get('since'))}, after this page last "
                                'looked. Take it over from them if you mean to.')
            mine = team.claim(space)
            record['driver'] = mine
            self._store(root, record)
            run.gone = False
            self._commit(root, f"{mine['name']} takes this training" + (
                f" over from {now.get('name') or 'someone'}" if now else ''))
            report = self._pushed(root, space)
            record = self._load(root)
            if not team.ours(space, record):   # someone else's claim got there first
                self._forget(root, space)
                raise Elsewhere(self._first(space, record))
            if not report['shared']:
                gitstate.undo(space, root)
                raise WorkspaceError('The shared repository did not take your claim, so '
                                     'this training was not taken. '
                                     + (report.get('notice') or ''))
            self._ours_again(root, run)
        return kept

    @staticmethod
    def _first(space: gitstate.Workspace, record: dict) -> str:
        who = team.driver(space, record)
        if who is None:
            return ('Someone else changed this training first, so your claim was dropped. '
                    + team.NOBODY)
        return (f"{who['name']} took this training first, on {team.day(who['since'])}, so "
                'your claim was dropped. It can be read here. Take it over from them if '
                'you mean to.')

    def _ours_again(self, root: Path, run: _Run) -> None:
        """A training is this computer's: forget that it was ever taken from it."""
        run.gone = False
        run.stop.clear()
        self._clash.pop(root.name, None)
        taken = team.kept('taken')
        if taken.pop(str(root), None) is not None:
            team.keep('taken', taken)

    def _forget(self, root: Path, space: gitstate.Workspace) -> None:
        """A claim that lost: nothing was in it to keep, and the refusal says who won."""
        taken = team.kept('taken')
        lost = taken.pop(str(root), None)
        if lost is not None:
            gitstate.forget(space, lost.get('kept'))
            self._as_of.pop(('kept', str(root)), None)
            team.keep('taken', taken)

    def _hand(self, root: Path, space: gitstate.Workspace) -> None:
        run = self._run(root)
        with self.files:
            record = self._load(root)
            self.hold(root)
            name = (record.get('driver') or {}).get('name') or 'Someone'
            record['driver'] = None
            self._store(root, record)
            self._commit(root, f'{name} hands this training over')
            run.gone = True     # a step in hand ends, and keeps nothing
            run.stop.set()
            self._step(space, push=True)

    def _aside(self, root: Path, space: gitstate.Workspace, kept: str | None,
               name: str | None = None, when: str | None = None,
               deleted: bool = False) -> None:
        """Remember what was set aside for a training, and who took it when that is why.
        `deleted` says that what was set aside is this computer's deletion of it."""
        self._as_of.pop(('kept', str(root)), None)
        taken = team.kept('taken')
        before = taken.get(str(root)) or {}
        taken[str(root)] = {'name': name or before.get('name'),
                            'at': when or before.get('at'),
                            'kept': kept or before.get('kept'),
                            **({'deleted': True} if deleted else {})}
        team.keep('taken', taken)

    def _learn(self, space: gitstate.Workspace, at: str | None = None) -> None:
        """After a fetch, before anything is replayed: stop every training this computer
        drove that the shared repository now says is someone else's. Its commits that
        were never shared are set aside, so nothing of this computer's is put on top of
        theirs. `at` is the remote's commit about to be replayed on, which is what is
        read. Call it holding `files`."""
        arrived = gitstate.arrived(space, at)
        for root in self.trainings():
            try:
                record = read_record(root)
                if not record or not team.ours(space, record) \
                        or gitstate.inside(space, root / RECORD) not in arrived:
                    continue
                theirs = json.loads(gitstate.theirs(space, root / RECORD, at) or 'null')
            except (WorkspaceError, ValueError):
                continue
            if not isinstance(theirs, dict) or team.ours(space, theirs):
                continue    # changed on both sides under our name: the replay reports it
            run = self._run(root)
            run.gone = True
            run.stop.set()
            who = team.driver(space, theirs)
            by = gitstate.last_by(space, root / RECORD, at) or ('Someone', home.now())
            self._aside(root, space, gitstate.set_aside(space, root, at),
                        who['name'] if who else by[0], who['since'] if who else by[1])
        self._deleted(space, arrived, at)

    def _deleted(self, space: gitstate.Workspace, arrived: set[str], at: str | None) -> None:
        """What a fetch says about deletions, before anything is replayed. A training
        deleted elsewhere is noted, to be let go of once the replay has taken its files
        away. A deletion of this computer's that was never shared, of a training someone
        else changed meanwhile, is set aside, so their version comes back whole. Call it
        holding `files`."""
        names = set()
        for name in arrived:
            parts = PurePosixPath(name).parts
            if len(parts) > 2 and parts[0] == space.folder:
                names.add(parts[1])
        for name in sorted(names):
            root = space.training(name)
            session = root / workspace.STATE_DIR / 'session.json'
            try:
                if session.is_file():
                    if gitstate.theirs(space, session, at) is None:
                        self._dropped.add(str(root))
                    continue
                # A training new to this copy was never here to be deleted.
                if not gitstate.known(space, root):
                    continue
                theirs = gitstate.theirs(space, root / RECORD, at)
                if theirs is None or not gitstate.unshared(space, root, at):
                    continue
                record = json.loads(theirs)
            except (WorkspaceError, ValueError):
                continue
            who = team.driver(space, record if isinstance(record, dict) else None)
            by = gitstate.last_by(space, root / RECORD, at) or ('Someone', home.now())
            self._aside(root, space, gitstate.set_aside(space, root, at),
                        who['name'] if who else by[0], who['since'] if who else by[1],
                        deleted=True)

    def _clashed(self, space: gitstate.Workspace, report: dict) -> None:
        """Note which trainings the same file was changed for on two computers."""
        found = {}
        for name in report.get('conflict') or ():
            parts = PurePosixPath(name).parts
            if len(parts) > 2 and parts[0] == space.folder:
                try:
                    title = workspace.load(space.training(parts[1]))['title']
                except WorkspaceError:
                    title = parts[1]
                found[parts[1]] = BROKEN.format(title=title)
        if report.get('reached'):
            self._clash = found

    def _notice(self, root: Path, record: dict | None = None) -> str | None:
        """What a person should know about who drives a training: that it was taken from
        this computer, or that it was changed on two at once. `record` is its run record,
        where the caller has just read it."""
        if root.name in self._clash:
            return self._clash[root.name]
        if self.mine(root) if record is None else team.ours(self.workspace, record):
            return self._stalled
        lost = team.kept('taken').get(str(root))
        if not lost:
            return None
        if lost.get('deleted'):
            return KEPT_BACK.format(name=lost.get('name') or 'Someone',
                                    when=team.day(lost.get('at')))
        said = TAKEN.format(name=lost.get('name') or 'Someone', when=team.day(lost.get('at'))) \
            if lost.get('name') else ''
        return (said + (SET_ASIDE if lost.get('kept') else '')).strip() or None

    # --- starting and picking up ---------------------------------------------------------

    def start(self, form: dict) -> dict:
        """Make a training from the form's answers and start its run."""
        space, chosen = self.space(), settings.load()
        gitstate.identity(space.repo)
        # A form that names its agent says its model and level too, None being the
        # agent's own choice. One that names none takes this computer's settings.
        named = form['agent'] is not None
        agent = form['agent'] or chosen.agent
        model = form['model'] if named else form['model'] or chosen.model
        effort = settings.check_effort(form['effort'] if named
                                       else form['effort'] or chosen.effort, agent)
        ready = self.ready(agent)
        if not ready.ready:
            raise WorkspaceError(ready.problem)
        with self.files:
            root = pipeline.create(space, form)
            try:
                record = new_record(agent, model, chosen, form['source_scope'], effort)
                record['driver'] = team.claim(space)
                self._tried(record, 'intake', home.now(), 0.0, 'kept')
                self._store(root, record)
                self._commit(root, 'start the training from the form')
            except BaseException:  # a training is started whole or not at all
                shutil.rmtree(root, ignore_errors=True)
                gitstate.discard(space, root)
                raise
            self._claimed(root, space)
        self.wake(root)
        drawn = bool(form['deck_target'] and form['brand']) and not self.deck_needs()['missing']
        return {'path': str(root), 'id': root.name, 'gates': pipeline.gates(form, drawn)}

    def _claimed(self, root: Path, space: gitstate.Workspace) -> None:
        """Share the claim a new training was committed with, before any work is done
        for it. Someone else's training of the same name, started at the same moment,
        stands: this one is taken back and refused. A repository that cannot be reached
        holds nothing up, since nobody else can know of a training that was never
        shared. Call it holding `files`."""
        if space.address is None:
            return
        report = self._pushed(root, space)
        if root.name in self._clash or not team.ours(space, read_record(root) or {}):
            self._clash.pop(root.name, None)
            self._forget(root, space)
            if (root / RECORD).is_file() and team.ours(space, self._load(root)):
                gitstate.undo(space, root)
                shutil.rmtree(root, ignore_errors=True)
            self._step(space, push=False)
            raise WorkspaceError(
                f'Someone else started a training in {space.folder}/{root.name} at the same '
                'moment, and theirs was shared first. Yours was not started. Give it a '
                'different title, or look at theirs.')
        self._unshared = None if report['shared'] else report.get('notice')

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

    def resume(self, wait: bool = True) -> None:
        """Pick every training up where its files say it is. First, in each training this
        computer drove, what a step left half-made when the runner last ended in the
        middle of it is discarded, and so is a lock harness-research was left holding. A
        training that waits for a person, or that the runner has finished with, is left
        exactly as it is, and so is whatever a person changed while no step was in hand.
        Then the workspace is fetched, and a training someone else now drives, or nobody
        does, is left as it is; the others carry on. With `wait` false the fetch and what
        follows it happen in the background, so a page can be answered meanwhile."""
        ours = self._tidy()
        if wait or not self.background:
            self._pick_up(ours)
            return
        space = self.workspace
        self._checking = space is not None and space.address is not None
        threading.Thread(target=self._pick_up, args=(ours,), daemon=True,
                         name='resuming').start()

    def _tidy(self) -> list[Path]:
        """Put back what a step left half-made in each training this copy says is this
        computer's, and return those trainings. Nothing here asks the shared repository."""
        ours = []
        for root in self.trainings():
            try:
                record = self._load(root)
                if not team.ours(self.workspace, record):
                    continue
                found = self._survey(root, record)
                if found.next.kind != 'done':
                    research_cli.unlock(root)
                if (root / IN_HAND).exists() and found.next.kind in WORK \
                        and not self._resting(record) and not self._away(found):
                    with self.files:
                        gitstate.discard(self.space(), root)
                (root / IN_HAND).unlink(missing_ok=True)
            except (WorkspaceError, OSError):
                continue  # its view says what is wrong; the others still run
            ours.append(root)
        return ours

    def _pick_up(self, ours: list[Path]) -> None:
        """Fetch, then wake each of `ours` that is still this computer's. Nothing that
        goes wrong stops the rest: it is said on this computer's trainings instead."""
        try:
            self.fetch()
        except (WorkspaceError, OSError):
            pass    # what is here is still picked up
        except Exception as failure:  # the runner keeps serving, and says so
            self._stalled = STALLED.format(failure=failure)
        finally:
            self._checking = False
        try:
            self.adopt()
        except Exception as failure:
            self._stalled = STALLED.format(failure=failure)
        for root in ours:
            try:
                if self.mine(root):
                    self.wake(root)
            except (WorkspaceError, OSError):
                continue
            except Exception as failure:
                self._stalled = STALLED.format(failure=failure)

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
        self._ending.set()
        if self.upkeep is not None:
            self.upkeep.close()   # an update of the skills in hand is ended too
        with self._lock:
            runs = list(self._runs.values())
        for run in runs:
            run.stop.set()
        for thread in [run.thread for run in runs] + [self._sharing, self._serving]:
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
                if run.gone or not team.ours(self.workspace, record):
                    return  # someone else drives it, or nobody does
                found = self._survey(root, record)
                step = found.next
                if self._resting(record) or step.kind not in (*WORK, 'deck'):
                    return
                if self._away(found) and step.step.id != 'package':
                    return  # a conversation is driving it; only the index is still ours
                if step.kind == 'deck':
                    return self._hand_on(root, found)
                if self.background and not held:
                    run.queued = True
                    held = self._slots.take(lambda: self._closing or run.stop.is_set(), run)
                    run.queued = False
                    if not held:
                        return  # closing, stopped, or no longer this computer's
                    continue  # it may have waited a while: look at the files again
                if step.kind == 'code' and step.step.id == last:
                    return self._problem(root, step.step.id, 'failed', (
                        f'The runner could not get past this step: {step.step.label}.'),
                        'Everything kept so far is still here.')
                last = step.step.id if step.kind == 'code' else None
                (root / IN_HAND).write_text(f'{step.step.id}\n', encoding='utf-8')
                with companion.stopping(run.stop):  # a command a step runs ends on Stop
                    self._do(root, run, found, step)
                (root / IN_HAND).unlink(missing_ok=True)
        except _Gone:   # it is someone else's now: what the step wrote was put back
            (root / IN_HAND).unlink(missing_ok=True)
        except companion.Stopped:   # ended on purpose; IN_HAND stays for the next start
            pass
        except Exception as failure:  # whatever a step does, the runner keeps serving
            (root / IN_HAND).unlink(missing_ok=True)
            self._trouble(root, failure)
        finally:
            if held:    # given back before the run counts as ended
                self._slots.give_back()
            run.queued = run.busy = False

    def _do(self, root: Path, run: _Run, found: pipeline.Survey,
            step: pipeline.Next) -> None:
        drawing = DECK.get(pipeline.bare(step.step.id)) if step.step.stage == 'deck' else None
        if drawing:
            getattr(self, drawing)(root, run, found, step)
        elif step.kind == 'gate':
            self._gate(root, step.step)
        elif step.step.id == 'research-start':
            self._hand_over(root, step.step)
        elif step.step.id == 'research-report':
            self._report(root, step.step)
        elif step.step.id == 'research':
            self._research(root, run, found, step)
        elif step.step.id == 'package':
            self._package(root, step.step)
        elif step.step.id.startswith('copies:'):
            self._copy(root, step.step)
        elif step.kind == 'code':
            self._own(root, found, step.step)
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
                 action: str | None = 'retry', waits: str | None = None) -> None:
        """Stop a training in a state that says what went wrong and offers one action.
        `waits` names what it waits for, when something done on the page settles it."""
        label = {'retry': 'Try again', 'resume': 'Carry on'}.get(action)
        with self.files:
            record = self._load(root)
            record['problem'] = {'state': state, 'step': step, 'what': what, 'kept': kept,
                                 'action': action, 'label': label, 'at': home.now(),
                                 **({'waits': waits} if waits else {})}
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
        """The deck is all that is left, and it cannot be made here: say so through the
        core, once, with what is missing."""
        says = pipeline.deck_says(found)
        if (found.session['stage'], found.session.get('next_step')) == ('deck', says):
            return
        with self.files:
            workspace.checkpoint(root, stage='deck', next_step=says)
            self._commit(root, 'everything but the slide deck is made')
        self._last(root)

    def _last(self, root: Path) -> None:
        """Share what the runner did last for a training. No decision follows it, so
        nothing else would ever share it."""
        if self.space().share == gitstate.SHARE[0]:
            self.share_soon()

    @staticmethod
    def _level(step: pipeline.Step) -> str | None:
        return workspace.split(step.artifact)[1] if step.artifact else None

    def _gate(self, root: Path, step: pipeline.Step) -> None:
        """Put a checked draft to the person, through the core, and wait."""
        it = workspace.label(step.artifact)
        with self.files:
            workspace.checkpoint(root, stage=step.stage, gate=step.artifact,
                                 question=f'Approve {it}?', level=self._level(step),
                                 next_step=f'Waiting for your review of {it}')
            self._commit(root, f'ask for a review of {it}')

    # --- the code steps after the blueprint ----------------------------------------------

    def _own(self, root: Path, found: pipeline.Survey, step: pipeline.Step) -> None:
        """Take in a scenario the person wrote, as it is. Nothing in it is changed."""
        with self.files:
            pipeline.keep_own(root, step, found)
            record = self._load(root)
            self._tried(record, step.id, home.now(), 0.0, 'kept')
            self._store(root, record)
            self._commit(root, f'take in {workspace.label(step.artifact)}, as its person '
                         'wrote it')

    def _make(self, root: Path, record: dict) -> None:
        """Make every copy that is wanted and not made, and note in the record what was
        tried and why a Google Doc could not be made. Call it holding `files`."""
        problems = self.copies.make(root)[1]
        session, tried = workspace.load(root), {}
        for entry in self._wanted(root, record):
            approved = (session['artifacts'].get(entry['artifact']) or {}).get('approved')
            if approved:
                tried[entry['artifact']] = approved['sha256']
        record['copies'] = {'problems': dict(problems or {}), 'tried': tried}

    def _copy(self, root: Path, step: pipeline.Step) -> None:
        """After an approval: make the copies the training asked for. One that cannot be
        made is noted with the reason, and the run carries on."""
        clock = time.monotonic()
        with self.files:
            record = self._load(root)
            self._make(root, record)
            self._tried(record, step.id, home.now(), time.monotonic() - clock, 'kept')
            self._store(root, record)
            self._commit(root, f'make the copies of {workspace.label(step.artifact)}')

    def _package(self, root: Path, step: pipeline.Step) -> None:
        """Nothing wanted is left to make or decide: write the index from the record, and
        say through the core whether the training is ready."""
        clock = time.monotonic()
        with self.files:
            record = self._load(root)
            copies = self._wanted(root, record)
            report = self.index.write(root, copies)
            says = pipeline.finished_says(report, self._survey(root, record, copies))
            workspace.checkpoint(root, stage='done', next_step=says)
            self._tried(record, step.id, home.now(), time.monotonic() - clock, 'kept')
            record['driver'] = None     # a finished training has no driver
            self._store(root, record)
            self._commit(root, 'write the index; ' + (
                'the training is finished' if report['ready'] else
                'the training is not ready yet'))
        self._last(root)

    # --- what this computer has for a deck -----------------------------------------------

    def _look(self, fresh: bool = False) -> dict:
        """What this computer has for making a deck: the slides tool, what it can render
        with, a brand skill with its brands, and every brand skill found. A look is reused
        for a few minutes, and one is taken at a time: whoever asks meanwhile waits for it.
        Drive is not asked while previews are made with LibreOffice: it is then None."""
        with self._looking:
            seen = self._looked
            if not fresh and seen and time.monotonic() - seen[0] < LOOKED_FOR:
                return seen[1]
            found = {'tool': None, 'version': None, 'local': False, 'drive': False,
                     'pictures': False, 'lacks': [],
                     'runtimes': {'slides': None, 'brand': None},
                     'brand': {'found': False, 'name': None, 'brands': [], 'problem': None},
                     'skills': []}
            try:
                tool = self.slides()
                ready = slides_tool.ready(tool, drive=settings.load().previews != 'local')
                found.update(version=ready['version'], local=ready['local'],
                             drive=ready['drive'], pictures=ready['pictures'],
                             lacks=list(ready['missing']))
                found['runtimes']['slides'] = str(tool.runtime)
            except (WorkspaceError, OSError) as refusal:
                found['tool'] = str(refusal)
            try:
                skill = self._skill()
                found['runtimes']['brand'] = str(skill.runtime)
                found['brand'] = {
                    'found': True, 'name': str(skill.name), 'problem': None, 'brands': [
                        {'brand': str(entry.get('brand')), 'name': str(entry.get('name')),
                         'variants': [str(variant) for variant in entry.get('variants') or ()]}
                        for entry in skill.brands() if isinstance(entry, dict)]}
            except (WorkspaceError, OSError) as refusal:
                found['brand']['problem'] = str(refusal)
            try:
                found['skills'] = [entry for entry in brand_skill.found()
                                   if isinstance(entry, dict) and entry.get('runtime')]
            except (WorkspaceError, OSError):
                pass
            self._looked = (time.monotonic(), found)
            return found

    def deck_needs(self, fresh: bool = False) -> dict:
        """What a deck needs on this computer: `missing`, a sentence for each thing it
        lacks, each with what to do about it; `how`, the way previews are rendered here;
        whether `drive` and `local` can render; the `brand` skill found and its `brands`;
        and `items`, each need as a line of the page's check of this computer."""
        seen, chosen = self._look(fresh), settings.load().previews
        how = chosen or ('local' if seen['local'] else None)
        brand, renders = seen['brand'], None
        dated = None if seen['tool'] or not older(seen['version'], slides_tool.MINIMUM) else (
            f"The slides tool on this computer is version {seen['version']}, and a deck "
            f'needs {slides_tool.MINIMUM} or newer. Update it.')
        missing = [said for said in (seen['tool'], dated, brand['problem']) if said]
        if not seen['tool']:
            if how is None:
                renders = NOT_CHOSEN if seen['drive'] else NO_RENDERER
            elif not seen[how]:
                renders = NO_DRIVE if how == 'drive' else NO_LOCAL
            missing += [renders] if renders else []
            missing += [NO_PICTURES] if not seen['pictures'] else []
        fact, item = computer.fact, computer.item
        can = {True: 'ok', False: 'problem'}
        items = [
            item('deck-slides', 'The slides tool',
                 'missing' if seen['tool'] else 'problem' if dated else 'ok',
                 [fact('Installed', can[not seen['tool']], seen['version'] or 'not found')],
                 seen['tool'] or dated or ''),
            item('deck-brand', 'A brand skill', 'ok' if brand['found'] else 'missing',
                 [fact('Installed', can[brand['found']], brand['name'] or 'not found')],
                 brand['problem'] or ''),
            item('deck-previews', 'A way to render previews of slides',
                 'problem' if renders or seen['tool'] else 'ok',
                 [fact('LibreOffice on this computer', can[seen['local']]),
                  fact('Google Drive', 'unknown', 'not asked, as LibreOffice makes them')
                  if seen['drive'] is None else fact('Google Drive', can[seen['drive']]),
                  fact('Chosen', 'ok' if how else 'unknown',
                       {'drive': 'Google Drive', 'local': 'LibreOffice'}.get(how, 'not yet'))],
                 renders or ''),
            item('deck-pictures', 'The programs that turn a render into pictures',
                 'ok' if seen['pictures'] else 'missing',
                 [fact('Installed', can[seen['pictures']])],
                 ' '.join([NO_PICTURES, *seen['lacks']]) if not seen['pictures'] else '')]
        return {'missing': missing, 'how': how, 'drive': seen['drive'], 'local': seen['local'],
                'brand': dict(brand), 'brands': list(brand['brands']), 'items': items}

    def _skill(self):
        """The brand skill to use: the one the person named at set-up, else the first
        that is found."""
        named = settings.load().brand_skill
        return self.brand(runtime=named) if named else self.brand()

    def brand_skills(self) -> list[dict]:
        """Every brand skill found on this computer, as {'name', 'path', 'chosen'}, read
        from `brand.found()` with the rest of a look at this computer, and reused with it.
        `path` is where the skill is, which names it at set-up."""
        named = settings.load().brand_skill
        return [{'name': str(entry.get('name') or entry['runtime']),
                 'path': str(entry['runtime']),
                 'chosen': str(entry['runtime']) == named if named else number == 0}
                for number, entry in enumerate(self._look()['skills'])]

    def brands(self) -> list[dict] | None:
        """The brands the brand skill on this computer has, or None with no brand skill."""
        brand = self._look()['brand']
        return list(brand['brands']) if brand['found'] else None

    def saved(self) -> None:
        """The person saved new settings: a run waiting its turn reads the new limit now, and
        this computer is looked at again for what they changed about a deck."""
        self._slots.renew()
        self.deck_needs(fresh=True)

    def look_again(self) -> dict:
        """Look at this computer afresh, as the person asks, and let every training that
        was waiting on what it lacked carry on."""
        needs = self.deck_needs(fresh=True)
        for root in self.trainings():
            self.wake(root)
        return needs

    @staticmethod
    def _previews() -> Path:
        """Where this computer keeps the render's one turn, and for each deck the preview
        file it has in Google Drive. Nothing here is shared."""
        return home.data_root() / PREVIEWS

    def previews_left(self) -> list[dict]:
        """The preview files the runner has left in Google Drive from this computer. It
        never deletes one, so the person is shown each with its address."""
        folder = self._previews()
        kept = [home.read_json(path, None) for path in sorted(folder.glob('*.json'))] \
            if folder.is_dir() else []
        return [{key: entry.get(key) for key in ('name', 'url', 'training')}
                for entry in kept if isinstance(entry, dict) and entry.get('url')]

    def _how(self, root: Path, found: pipeline.Survey, level: str | None) -> dict:
        """How one deck's previews are taken, as `worker_tools.render` takes it."""
        title = found.session['title'] + (f', level {level}' if level else '')
        folder, space = self._previews(), self.space()
        folder.mkdir(parents=True, exist_ok=True)
        name = folder_name(f"{space.name}-{root.name}-{level or ''}")
        return {'renderer': self.deck_needs()['how'], 'lock': str(folder / 'render.lock'),
                'kept': str(folder / f'{name}.json'),
                'named': {'name': f'Preview: {title}', 'training': title, 'path': str(root)}}

    def _naming(self, root: Path, session: dict) -> str | None:
        """How the training's brand names the organisation and its products, exported
        afresh for one writer. None with no brand chosen, or no brand skill here."""
        chosen = pipeline.brand_of(session)
        if chosen is None or not self._look()['brand']['found']:
            return None
        folder = agents.staging() / f'{root.name}--names-{secrets.token_hex(3)}'
        folder.parent.mkdir(parents=True, exist_ok=True)
        try:
            made = self._skill().export(folder, *chosen, delivery=deck.DELIVERY)
            return Path(made['voice']).read_text(encoding='utf-8')
        except (WorkspaceError, OSError, KeyError, TypeError):
            return None
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    # --- the slide deck ------------------------------------------------------------------

    @staticmethod
    def _decided(record: dict, level: str | None) -> dict:
        """What a run record holds of one level's deck."""
        return record.setdefault('deck', {}).setdefault(level or '', {})

    @staticmethod
    def _note(root: Path, level: str | None, **changes) -> dict:
        """Note what this computer has built of a deck. Call it holding `files`."""
        built = {**pipeline.read_built(root, level), **changes}
        pipeline.write_built(root, level, built)
        return built

    def _done(self, root: Path, step: pipeline.Step, clock: float, what: str) -> None:
        """Note a step of the runner's own that worked, and commit. Call it holding
        `files`."""
        record = self._load(root)
        self._tried(record, step.id, home.now(), time.monotonic() - clock, 'kept')
        self._store(root, record)
        self._commit(root, what)

    def _brand_holds(self, root: Path, found: pipeline.Survey, step: pipeline.Step) -> bool:
        """Check a deck's exported brand again before a step that uses it. A brand that
        changed underneath stops the deck, and says so."""
        level = self._level(step)
        mine = found.decks[level]
        try:
            self._skill().check(pipeline.contract(root, mine))
        except WorkspaceError as refusal:
            with self.files:
                self._note(root, level, brand={**(mine.built.get('brand') or {}),
                                               'changed': str(refusal)})
            self._problem(root, step.id, 'stopped', BRAND_CHANGED.format(said=refusal),
                          DECK_KEPT)
            return False
        return True

    def _handoff(self, root: Path, run: _Run, found: pipeline.Survey,
                 step: pipeline.Next) -> None:
        """Write deck-handoff.md from the record. It is derived, and written again whenever
        the blueprint or the settings change."""
        it, clock = step.step, time.monotonic()
        level = self._level(it)
        with self.files:
            workspace.write_atomic(
                pipeline.place(root, level, pipeline.HANDOFF),
                pipeline.handoff_text(root, found.session, level).encode('utf-8'))
            workspace.checkpoint(root, stage='deck', level=level, next_step=it.label)
            self._done(root, it, clock, f'write the handoff for {workspace.label(it.artifact)}')

    def _export(self, root: Path, run: _Run, found: pipeline.Survey,
                step: pipeline.Next) -> None:
        """Export the brand for one deck, for reading delivery, into a folder of its own,
        and read what the slides tool tells a deck's workers for that brand."""
        it, clock, token = step.step, time.monotonic(), secrets.token_hex(3)
        level = self._level(it)
        work = pipeline.place(root, level, pipeline.WORK)
        folder, told = work / f'brand-{token}', work / f'told-{token}'
        work.mkdir(parents=True, exist_ok=True)
        try:
            chosen, tool = pipeline.brand_of(found.session), self.slides()
            made = self._skill().export(folder, *chosen, delivery=deck.DELIVERY)
            contract = Path(made['contract']).resolve()
            told.mkdir()
            (told / 'outline-contract.txt').write_text(tool.outline_contract(contract),
                                                       encoding='utf-8')
            (told / 'compose-contract.txt').write_text(tool.compose_contract(contract),
                                                       encoding='utf-8')
            home.write_json(told / 'layouts.json', tool.layouts(contract))
            for name, text in tool.reading(contract).items():
                worker_tools._write(told / pipeline.reading_file(name), text)
            kept = {'brand': chosen[0], 'variant': chosen[1], 'folder': folder.name,
                    'told': told.name, 'changed': None, 'at': home.now(),
                    'contract': contract.relative_to(work.resolve()).as_posix(),
                    'voice': (Path(made['voice']).resolve().relative_to(work.resolve())
                              .as_posix() if made.get('voice') else None),
                    'sha256': workspace.sha256_file(contract)}
        except (WorkspaceError, OSError, KeyError, ValueError, TypeError) as refusal:
            shutil.rmtree(folder, ignore_errors=True)
            shutil.rmtree(told, ignore_errors=True)
            return self._problem(root, it.id, 'stopped', (
                f'The brand could not be exported for this deck. {refusal}'), KEPT)
        with self.files:
            for old in (*work.glob('brand-*'), *work.glob('told-*')):
                if old not in (folder, told):
                    shutil.rmtree(old, ignore_errors=True)
            self._note(root, level, brand=kept)
            self._done(root, it, clock, f'export the brand for {workspace.label(it.artifact)}')

    def _designed(self, mine: pipeline.Deck) -> bool | None:
        """Whether what a deck says is written with its design. A deck keeps what it was
        first written with; a new one has a design when the slides tool can keep one. None
        when it was written with a design and the tool here can no longer keep one."""
        if mine.designed is False:
            return False
        try:
            can = self.slides().designs()
        except WorkspaceError:
            can = False
        return can if mine.designed is None else (True if can else None)

    def _sections_bound(self, root: Path, it: pipeline.Step, design) -> bool:
        """Whether a deck can be built here: one drawn from its approved design needs a
        slides tool that checks a section against it. Stops the training and says so when
        it cannot."""
        if not design:
            return True
        try:
            can = self.slides().sections()
        except WorkspaceError:
            can = False
        if not can:
            self._problem(root, it.id, 'stopped', SECTIONS_GONE, DECK_KEPT)
        return can

    def _with_assets(self) -> bool:
        """Whether the slides tool here keeps a deck's assets."""
        try:
            return self.slides().assets()
        except WorkspaceError:
            return False

    def _assets_hold(self, root: Path, it: pipeline.Step, level: str | None, plan: dict,
                     contract: Path, find: bool = False) -> dict | None:
        """Whether every asset an approved design uses is to hand: recorded in the slides
        tool's manifest of the deck, its file as it was recorded, and an icon as the brand
        has it. Generated art is its composer's to make, so it needs only the tool's image
        provider. With `find`, each icon not yet recorded is first found in the brand's
        library and recorded. Returns what each asset is now, or None when the deck waits,
        having said for what, asset by asset, and what to do."""
        tool, project = self.slides(), pipeline.place(root, level, pipeline.DESIGNS)
        wanted, said = deck.candidates(plan), []
        try:
            recorded = {entry['assetId']: entry
                        for entry in tool.asset_status(project).get('assets') or ()}
            if find:
                said += self._icons_found(project, contract, wanted, recorded)
                recorded = {entry['assetId']: entry
                            for entry in tool.asset_status(project).get('assets') or ()}
            try:
                tool.asset_check(project, contract)
            except slides_tool.Refused as refusal:
                said += [_assets_said(problem, recorded) for problem in refusal.found] \
                    or refusal.problems
            provider = None
            for candidate in wanted:
                entry, where = recorded.get(candidate['asset']), f"Slide `{candidate['slide']}`"
                what = f"\"{candidate['ref']}\" ({candidate['concept']})"
                if entry is not None and entry.get('kind') != candidate['kind']:
                    said.append(f"{where}: {candidate['asset']} is recorded as a "
                                f"{entry.get('kind')}, and its approved design asks for a "
                                f"{candidate['kind']}.")
                elif entry is not None or candidate['kind'] == 'icon' and find:
                    continue
                elif candidate['kind'] == 'generated':
                    provider = provider or tool.images_status()
                    if provider.get('status') != 'configured':
                        steps = ' '.join(str(step) for step in provider.get('steps') or ())
                        said.append(f"{where} is drawn as generated art, {what}, and the "
                                    f"slides tool's image provider ({provider.get('provider')})"
                                    f" is not set up: {provider.get('status')}. "
                                    + (steps or 'Set it up as harness-slides says.')
                                    + ' Then try again.')
                elif candidate['kind'] in pipeline.SUPPLIED:
                    said.append(f"{where} needs the {candidate['kind']} {what}. Supply it on "
                                'this page.')
                else:
                    said.append(f"{where} needs the icon {what}, which is not recorded yet.")
        except WorkspaceError as refusal:
            said.append(f'The slides tool could not say what is recorded. {refusal}')
        if said:
            self._problem(root, it.id, 'waiting', ASSETS_WAIT.format(said=' '.join(said)),
                          ASSETS_KEPT, waits='assets')
            return None
        return pipeline.assets_now(root, level)

    def _icons_found(self, project: Path, contract: Path, wanted: list[dict],
                     recorded: dict) -> list[str]:
        """Find each icon an approved design names, not yet recorded, in the brand's own
        library, and record it under the asset ID the design gave it, checked against the
        brand. Returns a sentence for each that could not be."""
        said, skill = [], None
        for candidate in wanted:
            if candidate['kind'] != 'icon' or candidate['asset'] in recorded:
                continue
            where = f"Slide `{candidate['slide']}`"
            try:
                skill = skill or self._skill()
                found = skill.icons(str(candidate['ref'] or candidate['concept']),
                                    worker_tools.ICONS)
            except WorkspaceError:
                found = []
            chosen = deck.icon_for(candidate['ref'], found)
            if chosen is None:
                said.append(f"{where} needs the icon \"{candidate['ref']}\" "
                            f"({candidate['concept']}), and the brand's icon library has none "
                            'by that name. Add one to the brand, then try again.')
                continue
            try:
                self.slides().asset_icon(project, chosen, candidate['asset'],
                                         candidate.get('alt'), contract)
            except slides_tool.Refused as refusal:
                said += [_assets_said(problem, recorded) for problem in refusal.found] \
                    or refusal.problems
        return said

    def _approved(self, root: Path, level: str | None, mine: pipeline.Deck) -> dict:
        """The plan a deck's start was drawn from, as the slides tool approved it."""
        return home.read_json(pipeline.place(root, level, pipeline.WORK)
                              / mine.start['folder'] / pipeline.APPROVED_DESIGN, {})

    def _propose(self, root: Path, level: str | None) -> dict:
        """Propose a deck's design to the slides tool as one question for the whole plan, in
        the deck's own folder, and say what is put to the person: the design file's hash,
        the revision, whether it may be built already, and the question. Call it holding
        `files`."""
        tool, project = self.slides(), pipeline.place(root, level, pipeline.DESIGNS)
        file = pipeline.place(root, level, pipeline.DESIGN)
        try:
            expected = tool.design_status(project)['revision']
        except slides_tool.Refused as refusal:
            if refusal.codes != ['design-missing']:
                raise
            expected = None
        status = tool.design_propose(project, file, expected)
        question = status.get('question') or None
        return {'sha256': workspace.sha256_file(file), 'revision': status['revision'],
                'allowed': bool(status.get('buildAllowed')),
                'question': {key: question.get(key) for key in ('id', 'slides', 'options')}
                if question else None}

    def _ask(self, root: Path, run: _Run, found: pipeline.Survey, step: pipeline.Next) -> None:
        """Put what a deck says to the person, at the runner's own gate, and wait. The
        core has no gate for it, so this one is kept in the run record. A deck written with
        its design proposes it to the slides tool first, so that the person's one decision
        answers the tool's own question."""
        it = step.step
        level, says = self._level(it), pipeline.subject(it)
        with self.files:
            design = None
            if found.decks[level].designed:
                try:
                    design = self._propose(root, level)
                except WorkspaceError as refusal:
                    return self._problem(root, it.id, 'failed', (
                        f'{workspace.sentence(says)} could not be put to you with its design. '
                        f'{refusal}'), KEPT)
            record = self._load(root)
            self._decided(record, level)['waiting'] = {
                'sha256': workspace.sha256_file(pipeline.place(root, level, pipeline.OUTLINE)),
                'design': design, 'at': home.now()}
            self._store(root, record)
            workspace.checkpoint(root, stage='deck', level=level,
                                 next_step=f'Waiting for your review of {says}')
            self._commit(root, f'ask for a review of {says}')

    def _split(self, root: Path, run: _Run, found: pipeline.Survey,
               step: pipeline.Next) -> None:
        """Start a deck from what the person approved: add the direction, the layouts for
        its lead slides and the house rules, have the slides tool split it into sections,
        put the lead slides right, and rewrite each section's brief for a worker with
        tools and no files."""
        it, clock, token = step.step, time.monotonic(), secrets.token_hex(3)
        if not self._brand_holds(root, found, it):
            return
        level = self._level(it)
        mine, work = found.decks[level], pipeline.place(root, level, pipeline.WORK)
        folder, source = work / f'start-{token}', work / f'outline-{token}.json'
        approved = mine.kept['approved']
        design, plan = approved.get('design'), None
        if design:
            if not self._sections_bound(root, it, design):
                return
            try:
                checked = self.slides().design_check(pipeline.place(root, level,
                                                                    pipeline.DESIGNS))
                if checked.get('revision') != design['revision']:
                    raise WorkspaceError('It holds another revision.')
                plan = checked['plan']
            except (WorkspaceError, KeyError, TypeError) as refusal:
                return self._problem(root, it.id, 'stopped', DESIGN_DIFFERS.format(
                    said=refusal), DECK_KEPT)
        # Its pictures and icons are to hand, and recorded, before any section is drawn.
        held, recorded = None, None
        if plan is not None and self._with_assets():
            with self.files:
                self._note(root, level, assets=True)
            held = self._assets_hold(root, it, level, plan, pipeline.contract(root, mine),
                                     find=True)
            if held is None:
                return
            recorded = pipeline.recorded(root, level)
        words = [f"Approved on the page, {approved['at']}."]
        words += [approved['note']] if approved.get('note') else []
        try:
            listed = home.read_json(work / mine.built['brand']['told'] / 'layouts.json', {})
            whole = deck.complete(mine.outline, (listed or {}).get('layouts'), words,
                                  designed=plan is not None)
            home.write_json(source, whole)
            self.slides().outline_start(source, pipeline.contract(root, mine), folder)
            sections = []
            for part in home.read_json(folder / 'parts.json', {})['parts']:
                ident = Path(part).stem
                if not pipeline.SECTION.match(ident):
                    made = json.loads((folder / part).read_text(encoding='utf-8'))
                    home.write_json(folder / part, deck.lead(made))
                    continue
                written = (folder / 'briefs' / f'{ident}.md').read_text(encoding='utf-8')
                slides = deck.named_in(written, whole)
                if not slides:
                    raise WorkspaceError(f'The slides tool gave {ident} no slides.')
                worker_tools._write(folder / 'given' / f'{ident}.md', deck.brief(
                    written, whole, design=plan, recorded=recorded).replace(
                    str(folder), '.').replace(
                    str(Path.home()), '~'))
                sections.append({'id': ident, 'file': part, 'slides': slides})
            if not sections:
                raise WorkspaceError('The slides tool split the deck into no sections.')
            home.write_json(folder / 'given' / 'outline.json', whole)
            if plan is not None:   # as the tool gave it: the order of its keys is kept
                worker_tools._write(folder / pipeline.APPROVED_DESIGN, json.dumps(
                    plan, indent=2, ensure_ascii=False) + '\n')
        except (WorkspaceError, OSError, KeyError, ValueError, TypeError) as refusal:
            shutil.rmtree(folder, ignore_errors=True)
            return self._problem(root, it.id, 'failed', (
                f'The deck could not be split into sections. {refusal}'), DECK_KEPT)
        finally:
            source.unlink(missing_ok=True)
        with self.files:
            for old in (*work.glob('start-*'), pipeline.place(root, level, pipeline.SHOTS),
                        pipeline.place(root, level, pipeline.DRAWN)):
                if old != folder:
                    shutil.rmtree(old, ignore_errors=True)
            self._note(root, level, sections={}, rounds=[], start={
                'outline': approved['sha256'], 'brand': mine.built['brand']['sha256'],
                'design': design, **({'assets': held} if held is not None else {}),
                'folder': folder.name, 'sections': sections, 'at': home.now()})
            self._done(root, it, clock, f'split {workspace.label(it.artifact)} into '
                       f"{len(sections)} section{'' if len(sections) == 1 else 's'}")

    def _sections(self, root: Path, run: _Run, found: pipeline.Survey,
                  step: pipeline.Next) -> None:
        """One try at each section still to draw, or to draw again, side by side. Their
        previews are still taken one at a time."""
        if not self._brand_holds(root, found, step.step):
            return
        level = self._level(step.step)
        mine = found.decks[level]
        if not self._sections_bound(root, step.step, mine.start.get('design')):
            return
        if mine.start.get('assets') is not None and self._assets_hold(
                root, step.step, level, self._approved(root, level, mine),
                pipeline.contract(root, mine)) is None:
            return
        how = self._how(root, found, level)

        def one(section: str) -> None:
            if self._may_go(root):
                self._section(root, run, found, step.step, section, how)

        if self.at_once <= 1 or len(step.questions) == 1:
            for section in step.questions:
                one(section)
            return
        with ThreadPoolExecutor(max_workers=self.at_once) as pool:
            for pending in [pool.submit(contextvars.copy_context().run, one, section)
                            for section in step.questions]:
                pending.result()

    def _section(self, root: Path, run: _Run, found: pipeline.Survey, whole: pipeline.Step,
                 section: str, how: dict) -> None:
        """One try at drawing one section. What is kept is what the worker last previewed:
        the section, and the pictures of that preview."""
        number, level = pipeline.numbered(section), self._level(whole)
        again = ' again' if pipeline.bare(whole.id) == 'deck-repair' else ''
        it = pipeline.Step(f'{whole.id}:{number}', 'agent',
                           f'Draw section {number} of {workspace.label(whole.artifact)}{again}',
                           f'Drawing section {number} of {workspace.label(whole.artifact)}'
                           f'{again}', 'deck', whole.artifact)
        work = pipeline.section_work(root, found, whole, section,
                                     last_error(self._load(root), it.id), how)
        outcome, handed, started_at, folder = self._job(root, run, it, work)
        if outcome.reason == 'stopped':
            return self._stopped(root, it, outcome, started_at)
        if not handed['artifacts'] or not handed['shown']:
            return self._failed(root, it, outcome, started_at,
                                pipeline.why_not(handed, outcome.detail))
        mine, base = found.decks[level], pipeline.place(root, level, pipeline.WORK)
        with self.files:
            turn = len(mine.rounds) if again else 0
            file = Path(mine.start['folder']) / 'drawn' / f'{section}-{turn}.json'
            draft = next(iter(handed['artifacts'].values()))
            worker_tools._write(base / file, draft['text'])
            shown = pipeline.place(root, level, pipeline.DRAWN) / section
            shutil.rmtree(shown, ignore_errors=True)
            shown.mkdir(parents=True)
            for slide in handed['shown']['slides']:
                (shown / f"{slide['number']}.png").write_bytes(
                    worker_tools.picture(slide['path']))
            drawn = dict(pipeline.read_built(root, level).get('sections') or {})
            drawn[section] = {
                'start': mine.start['folder'], 'round': turn, 'file': file.as_posix(),
                'sha256': workspace.sha256_file(base / file),
                'previews': handed['shown']['previews'],
                'pictures': [slide['number'] for slide in handed['shown']['slides']],
                'notes': (handed['review'] or '').strip() or None,
                **({'assets': _placed(root, level, draft['text'])}
                   if mine.start.get('assets') is not None else {})}
            self._note(root, level, sections=drawn)
            record = self._load(root)
            self._tried(record, it.id, started_at, outcome.seconds, 'kept',
                        **self._cost(outcome))
            self._store(root, record)
            self._commit(root, f'keep section {number} of {workspace.label(whole.artifact)}'
                         + (', drawn again' if again else ''))
        shutil.rmtree(folder, ignore_errors=True)

    def _whole(self, root: Path, run: _Run, found: pipeline.Survey,
               step: pipeline.Next) -> None:
        """Merge the sections with the lead slides, compile the whole deck and preview it.
        Only the last preview of a deck is kept, and a try that fails leaves nothing."""
        it, clock = step.step, time.monotonic()
        if not self._brand_holds(root, found, it):
            return
        level = self._level(it)
        mine, base = found.decks[level], pipeline.place(root, level, pipeline.WORK)
        start = base / mine.start['folder']
        folder, shots = start / f'whole-{secrets.token_hex(3)}', pipeline.place(
            root, level, pipeline.SHOTS)
        drawn = mine.built.get('sections') or {}
        if not self._sections_bound(root, it, mine.start.get('design')):
            return
        if mine.start.get('assets') is not None and self._assets_hold(
                root, it, level, self._approved(root, level, mine),
                pipeline.contract(root, mine)) is None:
            return
        # A deck drawn from its approved design is checked whole against it.
        bound = {'design': pipeline.place(root, level, pipeline.DESIGNS)} \
            if mine.start.get('design') else {}
        try:
            folder.mkdir()
            shutil.copyfile(start / 'parts.json', folder / 'parts.json')
            for part in home.read_json(start / 'parts.json', {})['parts']:
                made = drawn.get(Path(part).stem)
                (folder / part).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(base / made['file'] if made else start / part, folder / part)
            tool = self.slides()
            tool.merge(folder / 'parts.json', folder / 'composition.json')
            tool.compile(folder / 'composition.json', pipeline.contract(root, mine),
                         folder=folder / 'compiled', **bound)
            shown = worker_tools.render(tool, folder / 'compiled', folder / 'preview',
                                        {**self._how(root, found, level), **bound})
            file = Path(str(shown['deck'])).resolve()
            if (folder / 'preview').resolve() not in file.parents \
                    or file.read_bytes()[:4] != workspace.PPTX_SIGNATURE:
                raise WorkspaceError('The renderer did not leave a deck that can be opened.')
            slides = worker_tools.pictures(shown, folder / 'preview', shots)
            home.write_json(shots / pipeline.ABOUT, {'deck': shown['deckSha256'], 'slides': [
                {key: slide[key] for key in ('number', 'id', 'title')} for slide in slides]})
        except (WorkspaceError, OSError, KeyError, ValueError, TypeError) as refusal:
            shutil.rmtree(folder, ignore_errors=True)
            shutil.rmtree(shots, ignore_errors=True)
            return self._problem(root, it.id, 'failed', (
                f'The slides could not be put together and rendered. {refusal} Nothing of '
                'that try was kept.'), DECK_KEPT)
        with self.files:
            for old in start.glob('whole-*'):
                if old != folder:
                    shutil.rmtree(old, ignore_errors=True)
            rounds = [made for made in pipeline.read_built(root, level).get('rounds') or ()
                      if made.get('start') == mine.start['folder']]
            rounds.append({
                'start': mine.start['folder'], 'at': home.now(), 'review': None,
                'folder': folder.relative_to(base).as_posix(),
                'preview': (folder / 'preview').relative_to(base).as_posix(),
                'compiled': (folder / 'compiled').relative_to(base).as_posix(),
                'file': file.relative_to(base.resolve()).as_posix(),
                'made_from': {ident: made['sha256'] for ident, made in drawn.items()},
                **({'assets': {ident: fingerprint for made in drawn.values()
                               for ident, fingerprint in (made.get('assets') or {}).items()}}
                   if mine.start.get('assets') is not None else {}),
                'deck': shown['deckSha256'], 'slides': slides})
            self._note(root, level, rounds=rounds)
            self._done(root, it, clock, f'put {workspace.label(it.artifact)} together: '
                       f"{len(slides)} slide{'' if len(slides) == 1 else 's'}")

    def _review(self, root: Path, run: _Run, found: pipeline.Survey,
                step: pipeline.Next) -> None:
        """One try at the review of a whole deck, by a worker that drew none of it."""
        it = step.step
        if not self._may_go(root):
            return
        level = self._level(it)
        work = pipeline.work(root, found, it, None, last_error(self._load(root), it.id), [])
        outcome, handed, started_at, folder = self._job(root, run, it, work)
        if outcome.reason == 'stopped':
            return self._stopped(root, it, outcome, started_at)
        if handed['assessment'] is None or handed['coverage'] is None:
            return self._failed(root, it, outcome, started_at,
                                pipeline.why_not(handed, outcome.detail))
        with self.files:
            rounds = list(pipeline.read_built(root, level).get('rounds') or ())
            rounds[-1] = {**rounds[-1], 'review': {
                'findings': handed['assessment']['findings'],
                'weakest': handed['assessment']['weakest'],
                'coverage': handed['coverage']['objectives'], 'at': home.now()}}
            self._note(root, level, rounds=rounds)
            record = self._load(root)
            self._tried(record, it.id, started_at, outcome.seconds, 'kept',
                        **self._cost(outcome))
            self._store(root, record)
            self._commit(root, f'keep the review of {workspace.label(it.artifact)}')
        shutil.rmtree(folder, ignore_errors=True)

    def _keep(self, root: Path, run: _Run, found: pipeline.Survey, step: pipeline.Next) -> None:
        """Keep the previewed deck as the deck: run the brand's audit on it, put it into
        Google Slides when that is where it goes, and save it through the core with the
        coverage the reviewer read off its slides. The file saved is the one whose
        pictures the page shows."""
        it, clock = step.step, time.monotonic()
        if not self._brand_holds(root, found, it):
            return
        level, session = self._level(it), found.session
        mine, base = found.decks[level], pipeline.place(root, level, pipeline.WORK)
        last, title = mine.last, session['title'] + (f', level {level}' if level else '')
        file, link = base / last['file'], None
        try:
            audit = pipeline.audited(self._skill().audit(file, *pipeline.brand_of(session)))
        except WorkspaceError as refusal:
            audit = pipeline.audited(None, f"The brand's audit could not be run. {refusal}")
        try:
            cited = self.slides().cited(base / last['compiled'])
            if session['settings']['deck_target'] == 'google':
                link = deck.link(self.slides().drive_import(file, title), title, last['deck'])
        except WorkspaceError as refusal:
            return self._problem(root, it.id, 'failed', (
                f'The deck was drawn and reviewed, but could not be kept. {refusal}'),
                'The slides as they were drawn and reviewed are kept on this computer.')
        with self.files:
            shows = pipeline.deck_shows(root, session, mine, audit, cited)
            entry = pipeline.keep_deck(root, found, mine, None if link else file, link, shows)
            record = self._load(root)
            self._decided(record, level)['saved'] = {
                'deck': last['deck'], 'sha256': entry['sha256'], 'at': home.now()}
            self._store(root, record)
            self._done(root, it, clock, f'keep {workspace.label(it.artifact)}')

    def outline(self, path, level: str | None, decision: str, note: str | None = None,
                seen: str | None = None, design: str | None = None) -> dict:
        """Record what a person decided about what a deck says, as the page heard it:
        `approve`, or `revise` with what should change. Nothing else calls this: the
        engine puts an outline to the person and waits. `seen` is the outline that was read
        and `design` the revision of its design; either one that changed since is refused.
        A deck written with its design has the decision sent to the slides tool as its one
        answer to the tool's question, and approval binds the two."""
        root = self._held(path)
        if decision not in DECIDING:
            raise WorkspaceError('What a deck says can be decided as: '
                                 + ', '.join(DECIDING) + '.')
        note = (note or '').strip() or None
        if decision == 'revise' and not note:
            raise WorkspaceError('Say what should change.')
        with self.files:
            record = self._load(root)
            step = self._survey(root, record).next
            if step.kind != 'outline' or self._level(step.step) != level:
                raise WorkspaceError('What that deck says is not waiting for a decision.')
            kept, says = self._decided(record, level), pipeline.subject(step.step)
            asked = kept['waiting'].get('design')
            if (seen is not None and seen != kept['waiting']['sha256']) or (
                    asked and design is not None and design != asked['revision']):
                raise WorkspaceError(CHANGED.format(it=workspace.sentence(says)))
            if asked:
                self._answer(root, level, asked, decision, note, says)
            if decision == 'approve':
                kept['approved'] = {'sha256': kept['waiting']['sha256'], 'at': home.now(),
                                    'by': 'page', 'note': note}
                if asked:
                    kept['approved']['design'] = {'sha256': asked['sha256'],
                                                  'revision': asked['revision']}
                said = f'{workspace.sentence(says)} was approved on the page.'
            else:
                kept['asked'] = {'kind': 'revise', 'note': note, 'at': home.now()}
                self._fresh(record, step.step.id.replace('gate:', '', 1))
                said = (f'Changes to {says} were asked for on the page: '
                        f'{workspace.shortened(note)}')
            kept['waiting'] = None
            self._store(root, record)
            workspace.checkpoint(root, next_step=said)
            self._commit(root, said)
        self.carry_on(root)
        return self.view(root)

    def _answer(self, root: Path, level: str | None, asked: dict, decision: str,
                note: str | None, says: str) -> None:
        """Send the person's decision to the slides tool as its answer to the question that
        was put to them: the note in their words, or, approving without one, the option
        they chose, word for word. When the tool has nothing to ask, because its approvals
        still hold, nothing is sent. Call it holding `files`."""
        question = asked.get('question')
        if question is None:
            if decision == 'approve' and not asked.get('allowed'):
                raise WorkspaceError(f'The slides tool is not asking about the design of '
                                     f'{says}, and has not approved it. Ask for changes.')
            return
        reply = {'questionId': question['id'], 'planRevision': asked['revision'],
                 'decision': decision, 'feedback': note or question['options'][0]}
        try:
            answered = self.slides().design_respond(
                pipeline.place(root, level, pipeline.DESIGNS), reply)
        except slides_tool.Refused as refusal:
            if 'design-revision-stale' in refusal.codes:
                raise WorkspaceError(CHANGED.format(it=workspace.sentence(says)))
            raise WorkspaceError('The slides tool did not take your decision: '
                                 + ' '.join(refusal.problems))
        if decision == 'approve' and not answered.get('buildAllowed'):
            raise WorkspaceError('The slides tool took your approval and still waits on part '
                                 'of the design. Open it again.')

    # --- a deck, as the page is shown it -------------------------------------------------

    @staticmethod
    def _drawing(found: pipeline.Survey) -> pipeline.Step | None:
        """The step of a deck that is in hand, or None when the next step is not one."""
        step = found.next.step
        return step if step is not None and step.stage == 'deck' and found.decks else None

    def _before(self, found: pipeline.Survey, step: pipeline.Next) -> str:
        """What a deck of this size has cost before, said before any of it is drawn."""
        slides = len(deck.slides_of(found.decks[self._level(step.step)].outline))
        cost = deck.before(slides)
        return (f" A deck of {slides} slides has cost about ${cost['dollars']:,.2f} and "
                f"{cost['minutes']:g} minutes of agent time to draw before, and as much "
                'again each time its slides were drawn again after a review.')

    def _live(self, run: _Run, drawing: pipeline.Step | None) -> dict:
        """The sections workers are drawing now, each with how many previews it has taken
        and the slides its latest one shows."""
        with self._lock:
            working = {ident: worker.get('folder') for ident, worker in run.workers.items()}
        live = {}
        for ident, folder in working.items():
            step, _, number = ident.rpartition(':')
            if drawing is None or pipeline.bare(step) not in pipeline.SIDE_BY_SIDE \
                    or self._level(drawing) != workspace.split(step)[1] or folder is None:
                continue
            state = home.read_json(Path(folder) / 'state.json', {})
            live[f'section-{number}'] = {
                'previews': state.get('previews', 0),
                'slides': [slide['number'] for slide in state.get('shown') or ()]}
        return live

    @staticmethod
    def _given_up(record: dict, drawing: pipeline.Step | None) -> set:
        """The sections whose workers have failed as often as they may."""
        return {f"section-{name.rpartition(':')[2]}" for name in record['steps']
                if drawing is not None and pipeline.spent(record, name)
                and pipeline.bare(name.rpartition(':')[0]) in pipeline.SIDE_BY_SIDE
                and workspace.split(name.rpartition(':')[0])[1] == Engine._level(drawing)}

    def picture(self, path, number: int, artifact: str | None = None,
                section: str | None = None) -> bytes:
        """One slide's picture, as PNG bytes: of a deck the runner rendered, named by the
        core's name for it, or of a section's latest preview while a deck is drawn. Where
        the picture is kept is worked out from those and the number, and what is there is
        returned only if it is a picture inside the training's own folder, or inside the
        folder of the worker drawing that section."""
        root = self.driven(path)
        if root is None:
            raise WorkspaceError('No run is driving this training.')
        session, within = workspace.load(root), root
        if artifact is not None:
            if artifact not in workspace.artifact_names(root, session) \
                    or workspace.split(artifact)[0] != 'deck':
                raise WorkspaceError('That is not a slide deck of this training.')
            file = pipeline.picture_of(root, workspace.split(artifact)[1], number)
        else:
            record, run = self._load(root), self._run(root)
            drawing = self._drawing(self._survey(root, record))
            if drawing is None:
                raise WorkspaceError('No deck is being drawn in this training now.')
            file = pipeline.picture_of(root, self._level(drawing), number, section)
            with self._lock:
                live = run.workers.get(f"{drawing.id}:{pipeline.numbered(section)}") or {}
            if live.get('folder') and (Path(live['folder']) / 'shown' / file.name).is_file():
                within = Path(live['folder'])
                file = within / 'shown' / file.name
        if within.resolve() not in file.resolve().parents or not file.is_file():
            raise FileNotFoundError(NO_PICTURE)
        return worker_tools.picture(file)

    def deck_gate(self, path, artifact: str) -> dict:
        """What gate 6 adds for a deck: its slides whose pictures are here, what the
        review still finds, the brand's audit and the coverage."""
        root = Path(path)
        return pipeline.deck_gate(root, workspace.load(root), artifact)

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
        # A deck's worker is given the slides tool and the brand skill this engine uses.
        worker_tools.prepare(folder, **{**work.prepared, 'runtimes': dict(
            self._look()['runtimes']) if step.stage == 'deck' else {}})
        limits = agents.Limits(record['limits']['step_seconds'],
                               max(0.01, self._left(record)))
        job = agents.Job(work.guidance, work.task, folder, work.profile,
                         tuple(worker_tools.command(folder)), limits, record.get('model'),
                         record.get('effort'))
        lines, started_at, clock = deque(maxlen=LINES), home.now(), time.monotonic()
        with self._lock:
            run.workers[step.id] = {'label': step.doing, 'started_at': started_at,
                                    'lines': lines, 'folder': folder}
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
        """One try at a drafting step: the research plan, a blueprint, a guide, a brief, a
        practice scenario, a Yoodli scenario, or what a deck says."""
        it, says = step.step, pipeline.bare(step.step.id) == 'deck-outline'
        if (says and not self._brand_holds(root, found, it)) or not self._may_go(root):
            return
        designed = says and self._designed(found.decks[self._level(it)])
        if designed is None:
            return self._problem(root, it.id, 'stopped', DESIGN_GONE, KEPT)
        record = self._load(root)
        sources = (self.documents.sources(root)
                   if it.id == 'research-plan' and record.get('documents') else None)
        naming = (self._naming(root, found.session)
                  if it.stage in pipeline.NAMED and it.kind == 'agent' else None)
        work = pipeline.work(root, found, it, step.request, last_error(record, it.id),
                             record['answers'].get(it.id, []), sources, naming, designed)
        outcome, handed, started_at, folder = self._job(root, run, it, work)
        if outcome.reason == 'stopped':
            return self._stopped(root, it, outcome, started_at)
        if handed['artifacts']:
            with self.files:
                record = self._load(root)
                if it.stage == 'scenario' and it.artifact not in found.own \
                        and it.artifact not in record.setdefault('drafted', []):
                    # Noted before the file is written, so it is never taken for a person's.
                    record['drafted'].append(it.artifact)
                    self._store(root, record)
                if says:  # kept in the deck's own folder: its gate is the runner's
                    self._decided(record, self._level(it)).update(
                        outline=pipeline.keep_outline(root, found, self._level(it), handed,
                                                      step.request, designed),
                        asked=None, waiting=None)
                else:
                    pipeline.keep_draft(root, it, handed, step.request, found)
                self._tried(record, it.id, started_at, outcome.seconds, 'kept',
                            **self._cost(outcome))
                self._store(root, record)
                self._commit(root, 'keep ' + (f'what {workspace.label(it.artifact)} says'
                                              if says else workspace.label(it.artifact)))
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
            for pending in [pool.submit(contextvars.copy_context().run, one, ident)
                            for ident in step.questions]:
                pending.result()

    def _question(self, root: Path, run: _Run, found: pipeline.Survey, ident: str,
                  request: dict | None) -> None:
        """One try at one research question. An accepted finding is recorded at once."""
        it = pipeline.Step(f'research:{ident}', 'agent', f'Research the question {ident}',
                           f'Researching the question {ident}', 'research')
        record = self._load(root)
        sources = self.documents.sources(root) if record.get('documents') else None
        work = pipeline.question_work(root, found, ident, request, last_error(record, it.id),
                                      sources)
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
            found = self._survey(root, record).research
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
        self.hold(root)
        with self.files:
            record = self._load(root)
            target = outcome.get('artifact')
            if outcome.get('request') and target:
                self._fresh(record, target)
                base, level = workspace.split(target)
                for step in pipeline.DECK_STEPS if base == 'deck' else ():
                    self._fresh(record, workspace.qualify(step, level))
                problem = record.get('problem') or {}
                if problem.get('step') == target:
                    record['problem'] = None
                if target == 'research' and record.get('research'):
                    record['research']['again'] = {
                        'at': outcome['request'].get('at'),
                        'left': pipeline.again(root, record, outcome['request'])}
                self._store(root, record)
            found = self._survey(root, record)
            ahead = found.next.step
            if found.next.kind in WORK and ahead.stage != found.session['stage']:
                workspace.checkpoint(root, stage=ahead.stage, level=self._level(ahead))
            self._commit(root, outcome.get('said') or 'a decision was made on the page')
        return True

    def changed(self, path, what: str) -> bool:
        """Commit a change something else just made to a training a run is driving. Call
        it holding `files`. False when no run is driving the training."""
        root = self.driven(path)
        if root is None:
            return False
        self.hold(root)
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
        root = self._held(path)
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
        root = self._held(path)
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

    def supply(self, path, action: str, name: str | None = None,
               data: bytes | None = None) -> dict:
        """Add one of the person's documents, remove one, or take their word that they are
        all added. `data` is the document as it was sent. Nothing is researched until they
        are all added, and after that they cannot be changed."""
        root = self._held(path)
        if action not in SUPPLYING:
            raise WorkspaceError('A document can be: ' + ', '.join(SUPPLYING) + '.')
        with self.files:
            record = self._load(root)
            given = record.get('documents')
            if not given:
                raise WorkspaceError('This training is researched from the public web, so '
                                     'it takes no documents.')
            if self._survey(root, record).next.kind != 'documents':
                raise WorkspaceError(SETTLED)
            if action == 'add':
                self.documents.add(root, name or '', data or b'')
            elif action == 'remove':
                self.documents.remove(root, name or '')
            else:
                readable = [entry for entry in self.documents.listed(root)
                            if entry.get('readable')]
                if given['scope'] == 'supplied-only' and not readable:
                    raise WorkspaceError('Add at least one document that can be read first. '
                                         'This training is researched from your documents '
                                         'only.')
                given.update(done=home.now(), count=len(readable))
                (root / pipeline.ADDED).parent.mkdir(parents=True, exist_ok=True)
                (root / pipeline.ADDED).write_text(f"{given['done']}\n", encoding='utf-8')
                self._store(root, record)
                self._commit(root, (f'the documents are all added: {len(readable)} to '
                                    'research from') if readable else
                             'no documents were added; research uses the public web')
        if action == 'done':
            self.wake(root)
        return self.view(root)

    def supply_asset(self, path, level: str | None, asset: str, data: bytes, alt: str,
                     source: str, restrictions: str | None = None) -> dict:
        """Record a picture the person gives for one their deck's approved design asks
        for, through the slides tool, which keeps it. A picture recorded before is replaced
        where it is kept, so what is drawn with it is drawn again. A deck waiting for its
        pictures carries on, and nothing is approved again."""
        root = self._held(path)
        ending = next((suffix for start, suffix in PICTURES.items()
                       if data.startswith(start)), None)
        if ending is None:
            raise WorkspaceError('A picture is a PNG, JPEG or GIF file.')
        if not alt.strip() or not source.strip():
            raise WorkspaceError('Say what the picture shows and where it came from.')
        with self.files:
            record = self._load(root)
            mine = self._survey(root, record).decks.get(level)
            if mine is None or not mine.built.get('assets') \
                    or not (mine.kept.get('approved') or {}).get('design'):
                raise WorkspaceError('This deck takes no pictures from you: it is not drawn '
                                     'from an approved design whose slides tool keeps them.')
            design = home.read_json(pipeline.place(root, level, pipeline.DESIGN), {})
            wanted = next((candidate for candidate in deck.candidates(design)
                           if candidate['asset'] == asset
                           and candidate['kind'] in pipeline.SUPPLIED), None)
            if wanted is None:
                raise WorkspaceError(NOT_SUPPLIED.format(asset=asset))
            project = pipeline.place(root, level, pipeline.DESIGNS)
            entry = pipeline.recorded(root, level).get(asset) or {}
            target = (project / str(entry['path'])).resolve() if entry.get('path') else None
            if target is not None and project.resolve() not in target.parents:
                target = None
            before = target.read_bytes() if target is not None and target.is_file() else None
            staged = pipeline.place(root, level, pipeline.WORK) / f'supplied-{asset}{ending}'
            file = target or staged
            try:
                workspace.write_atomic(file, data)
                self.slides().asset_supplied(project, file, asset, alt.strip(),
                                             source.strip(), wanted['kind'],
                                             (restrictions or '').strip() or None)
            except WorkspaceError as refusal:
                if target is not None and before is not None:
                    workspace.write_atomic(target, before)
                raise WorkspaceError(f'The picture was not recorded. {refusal}')
            finally:
                staged.unlink(missing_ok=True)
            problem = record.get('problem') or {}
            if problem.get('waits') == 'assets':
                self._fresh(record, problem.get('step'))
                record['problem'] = None
                self._store(root, record)
            self._commit(root, f"supply the {wanted['kind']} {asset} for "
                         f"{workspace.label(mine.name)}")
        self.wake(root)
        return self.view(root)

    def copies_again(self, path) -> dict:
        """Make the copies that are not made, again, as the person asks. One that still
        cannot be made says why."""
        root = self._held(path)
        with self.files:
            record = self._load(root)
            self._make(root, record)
            self._store(root, record)
            copies = self._wanted(root, record)
            found = self._survey(root, record, copies)
            if found.next.kind == 'done':  # the index lists the copies, so it is written again
                report = self.index.write(root, copies)
                workspace.checkpoint(root, next_step=pipeline.finished_says(report, found))
            self._commit(root, 'make the copies again, as asked on the page')
        self.wake(root)
        return self.view(root)

    def whose(self, path, artifact: str) -> str | None:
        """Who wrote a scenario's file: 'runner' for one the runner drafted, else 'you'.
        None when no run is driving the training, which cannot tell."""
        root = self.driven(path)
        if root is None:
            return None
        return 'runner' if artifact in (self._load(root).get('drafted') or ()) else 'you'

    # --- sharing -------------------------------------------------------------------------

    def _step(self, space: gitstate.Workspace, push: bool) -> dict:
        """Get in step with the shared repository: fetch, learn which trainings are no
        longer this computer's, replay, and push if asked. Never raises for the remote's
        sake. `files` is held while the workspace is read or changed, and not while the
        shared repository is asked, so a decision never waits for a slow remote. A caller
        that must keep the files still until a claim is shared holds `files` itself."""
        try:
            report = gitstate.sync(space, push=push, before=lambda at: self._learn(space, at),
                                   held=self.files)
        except WorkspaceError as refusal:
            report = {'shared': False, 'reached': False, 'received': 0, 'conflict': [],
                      'notice': str(refusal)}
        with self.files:
            self._clashed(space, report)
            if self._clash:
                report['notice'] = ' '.join(self._clash.values())
            if report.get('reached'):
                self._fetched += 1
            dropped, self._dropped = self._dropped, set()
            for name in sorted(dropped):    # gone here too, unless the replay stopped
                if not (Path(name) / workspace.STATE_DIR / 'session.json').is_file():
                    self._let_go(Path(name))
        if report.get('reached'):
            if not push:
                team.fetch_tags(space)
            elif self._tags_unsent:
                self._tags_unsent = team.send_tags(space) is not None
        return report

    def share(self) -> dict:
        """Share the workspace now. Never fails a run: when it cannot share, the work stays
        on this computer and the notice says why."""
        report = self._step(self.space(), push=True)
        self._unshared = None if report['shared'] else report['notice']
        self.adopt()
        return {'shared': bool(report['shared']), 'notice': report['notice']}

    def fetch(self) -> dict:
        """Bring in what teammates have shared, and send nothing. A training this computer
        drives is never changed by it. Says whether the shared repository was reached,
        how many commits came in, and why not when it could not be done."""
        space = self.workspace
        if space is None or space.address is None:
            return {'reached': None, 'received': 0, 'notice': None}
        report = self._step(space, push=False)
        self.adopt()
        return {'reached': bool(report.get('reached')), 'received': report.get('received', 0),
                'notice': report.get('notice')}

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
        refs, seen = _refs(space.repo, space.branch), self._ahead
        if refs is not None and seen is not None and seen[0] == refs:
            waiting = seen[1]
        else:
            waiting = hub.ahead(space.repo, f'refs/remotes/origin/{space.branch}')
            self._ahead = None if refs is None else (refs, waiting)
        return {'shared': not waiting, 'notice': self._unshared if waiting else None}

    # --- what the page shows -------------------------------------------------------------

    def _doing(self, record: dict, found: pipeline.Survey) -> str:
        """What a working run is doing now, in a sentence."""
        step = found.next
        if step.kind == 'gate':
            return f'Getting {pipeline.subject(step.step)} ready for your review.'
        if step.step.stage == 'deck' and pipeline.bare(step.step.id) in pipeline.SIDE_BY_SIDE:
            mine = found.decks[self._level(step.step)]
            listed = len(mine.start.get('sections') or ())
            return (f'{step.step.doing}: {listed - len(step.questions)} of {listed} drawn '
                    'so far.')
        if step.step.id == 'research':
            verdicts = found.research.verdicts
            answered = len(verdicts) - len(found.research.unread)
            return (f'Researching the questions: {answered} of {len(verdicts)} answered so '
                    'far.')
        error = last_error(record, step.step.id)
        if error:
            return f'{step.step.doing} again. The last try did not work: {error}'
        return f'{step.step.doing}.'

    def _state(self, record: dict, found: pipeline.Survey, run: _Run,
               report: dict | None = None) -> tuple[str, str]:
        """A run's state, and what is happening in a sentence. `report` is how ready a
        training with its index written is; without it, what the index step said is used."""
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
        if step.kind == 'outline':
            it = workspace.sentence(pipeline.subject(step.step))
            return 'waiting', f'{it} is waiting for your review.{self._before(found, step)}'
        if step.kind == 'done':
            return 'done', (pipeline.finished_says(report, found) if report
                            else found.session.get('next_step') or 'This training is done.')
        if step.kind == 'deck':
            return 'done', pipeline.deck_says(found)
        if step.kind == 'stuck':
            return 'failed', step.why
        if self._away(found) and step.step.id != 'package':
            return 'done', AWAY
        if step.kind == 'documents':
            return 'waiting', self._asking(found.scope)
        if run.queued:
            ahead = self._slots.ahead(run) or 0
            return 'working', 'Waiting for its turn. ' + (
                'It is next.' if not ahead else '1 training is ahead of it.' if ahead == 1
                else f'{ahead} trainings are ahead of it.')
        return 'working', self._doing(record, found)

    def _queue(self, run: _Run) -> dict | None:
        """For a training waiting its turn: how many are ahead of it."""
        ahead = self._slots.ahead(run) if run.queued else None
        return None if ahead is None else {'ahead': ahead}

    def _since_fetch(self, what: str, root: Path, read):
        """Something read from the repository that only changes when it is fetched or
        pushed, read once for each time that happens."""
        kept = self._as_of.get((what, str(root)))
        if kept is None or kept[0] != self._fetched:
            kept = self._as_of[(what, str(root))] = (self._fetched, read())
        return kept[1]

    def _set_aside(self, root: Path) -> list[str]:
        """The names git keeps what this computer set aside of a training under."""
        space = self.workspace
        if space is None or space.address is None:
            return []
        return list(self._since_fetch('kept', root, lambda: gitstate.kept(space, root)))

    def _then(self, record: dict, found: pipeline.Survey) -> str:
        """Where a training stood when it was last shared, said of the past: nothing here
        knows what the computer that drives it is doing now."""
        problem, halt, step = record.get('problem'), record.get('halt'), found.next
        if problem:
            return f"Then, it had stopped: {problem['what']}"
        if halt:
            return 'Then, it was paused.' if halt == 'paused' else 'Then, it was stopped.'
        if record.get('question'):
            return 'Then, a question was waiting for an answer.'
        if step.kind in ('wait', 'outline'):
            return f'Then, {pipeline.subject(step.step)} was waiting for a decision.'
        if step.kind == 'documents':
            return 'Then, it was waiting for documents to be added.'
        if step.kind == 'stuck':
            return f'Then, it could not go on: {step.why}'
        if step.kind == 'done':
            return 'Then, it was finished.'
        if step.kind == 'deck':
            return f'Then: {pipeline.deck_says(found)}'
        if self._away(found):
            return 'Then, its decisions were being made in a conversation.'
        if step.kind == 'gate':
            return f'Then, {pipeline.subject(step.step)} was the next thing to be reviewed.'
        label = step.step.label
        return f'Then, the next step was to {label[:1].lower() + label[1:]}.'

    def _last_shared(self, root: Path, record: dict, found: pipeline.Survey) -> dict:
        """What is known of a training someone else drives: when it was last shared, by
        whom, and where it stood then. {'at', 'by', 'says'}."""
        space = self.workspace
        by, at = self._since_fetch('last', root, lambda: gitstate.last_by(space, root)) \
            or (None, None)
        try:
            at = datetime.fromisoformat(at).astimezone(timezone.utc).strftime(
                '%Y-%m-%dT%H:%M:%SZ') if at else None
        except ValueError:
            at = None
        return {'at': at, 'by': by, 'says': self._then(record, found)}

    def _whose(self, root: Path, record: dict, found: pipeline.Survey, state: str,
               sentence: str) -> tuple[bool, dict | None, str, str, dict | None]:
        """Whether a training is this computer's, who drives it, and its state and
        sentence as someone who can only read it is told them. One that someone else
        drives is `elsewhere`, whatever its files say: only what was last shared is known
        here, so the sentence says that and when, and the last item says it apart."""
        space = self.workspace
        mine, who = team.ours(space, record), team.driver(space, record)
        if mine:
            return mine, who, state, sentence, None
        if who is None:
            return mine, who, *((state, sentence) if state == 'done'
                                else ('stopped', team.NOBODY)), None
        last = self._last_shared(root, record, found)
        when = f", on {team.day(last['at'])}" if last['at'] else ''
        return mine, who, 'elsewhere', (THEIRS.format(name=who['name']) + LAST.format(
            when=when, then=last['says'])), last

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
            elif step.id == current and found.next.kind == 'deck':
                status = 'waiting'
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
        found = self._survey(root, record)
        state, sentence = self._state(record, found, self._run(root))
        if state != 'working':
            return state, sentence
        coming = [step for step in found.steps if step.id not in found.done]
        ahead = found.next.step if found.next.kind == 'gate' else next(
            (step for step in coming if step.kind != 'code'), found.next.step)
        if ahead.kind == 'gate' and ahead.artifact:
            return state, f'Getting {pipeline.subject(ahead)} ready for your review.'
        return state, f'{ahead.doing} now.'

    def brief(self, path) -> dict | None:
        """A run in two words and a sentence, for a list. `needs` says a question, a
        problem or a wait for the person's documents is waiting for them. None when no run
        is driving the training."""
        root = self.driven(path)
        if root is None:
            return None
        try:
            record = self._load(root)
        except (WorkspaceError, OSError) as failure:
            return self._unread(failure)
        return self._brief(root, record)

    @staticmethod
    def _unread(failure: Exception) -> dict:
        """A run in brief whose record or files could not be read."""
        return {'state': 'failed', 'sentence': str(failure), 'needs': True, 'question': None,
                'mine': True, 'driver': None, 'last_shared': None, 'notice': None}

    def _brief(self, root: Path, record: dict, found: pipeline.Survey | None = None) -> dict:
        """`brief`, from a record already read and, where there is one, a survey already
        made of it."""
        try:
            found = self._survey(root, record) if found is None else found
        except (WorkspaceError, OSError) as failure:
            return self._unread(failure)
        state, sentence = self._state(record, found, self._run(root))
        asked = record.get('question')
        needs = bool(asked or record.get('problem') or found.next.kind == 'stuck'
                     or (state == 'waiting' and found.next.kind in ('documents', 'outline')))
        mine, who, state, sentence, last = self._whose(root, record, found, state, sentence)
        return {'state': state, 'sentence': sentence, 'needs': needs and mine,
                'question': asked['text'] if asked and mine else None, 'mine': mine,
                'driver': who, 'last_shared': last, 'notice': self._notice(root, record)}

    @staticmethod
    def _asking(scope: str) -> str:
        """What a run waiting for the person's documents says."""
        only = ' This training is researched from them alone.' if scope == 'supplied-only' \
            else ''
        return ('Add your documents, then say that is all of them. Nothing is researched '
                f'until you do.{only}')

    def _supplied(self, root: Path, record: dict, found: pipeline.Survey) -> dict | None:
        """The person's documents, for a training that takes any: what is added, what
        this computer can take, and whether the run is waiting for them."""
        given = record.get('documents')
        if not given:
            return None
        added = self.documents.listed(root)
        types, waiting = list(self.documents.accepts()), found.next.kind == 'documents'
        note = []  # the page itself says where documents are kept
        if '.pdf' in self.documents.TYPES and '.pdf' not in types:
            note.append(NO_PDF)
        if given.get('count') and not any(entry.get('readable') for entry in added):
            note.append(NOT_HERE)
        return {'waiting': waiting,
                'added': [{key: entry.get(key) for key in ('name', 'bytes', 'readable',
                                                           'problem')} for entry in added],
                'types': types, 'limits': dict(self.documents.LIMITS), 'note': ' '.join(note)}

    @staticmethod
    def _copies(found: pipeline.Survey) -> list[dict]:
        """The copies the page shows: each one of a file that is approved, and each that
        is behind a file that has changed since. One not made of a file not approved yet
        is left out, since there is nothing to make it from. A copy's label is the core's
        name for its file, to read in the middle of a sentence."""
        return [{**{key: entry.get(key) for key in ('artifact', 'kind', 'state', 'link',
                                                    'problem')},
                 'label': workspace.label(entry['artifact'])} for entry in found.copies
                if entry['state'] != 'not-made'
                or found.state.get(entry['artifact']) == 'approved']

    def view(self, path) -> dict | None:
        """Everything the page shows for one run. None when no run is driving it."""
        root = self.driven(path)
        if root is None:
            return None
        record = self._load(root)
        copies = self._wanted(root, record)
        found = self._survey(root, record, copies)
        run, ending = self._run(root), found.next.kind
        resting = self._resting(record)
        report = self.index.readiness(root, copies) if ending == 'done' else None
        state, sentence = self._state(record, found, run, report)
        mine, who, state, sentence, last = self._whose(root, record, found, state, sentence)
        asked, problem = record.get('question'), record.get('problem')
        if problem is None and found.next.kind == 'stuck':
            problem = {'what': found.next.why, 'action': None, 'label': None,
                       'kept': 'Everything in the training\'s folder is as it was.'}
        dollars, tokens = spent(record)
        drawing = self._drawing(found)
        level = self._level(drawing) if drawing else None
        return {
            'state': state, 'sentence': sentence, 'agent': record['agent'],
            'mine': mine, 'driver': who, 'queue': self._queue(run) if mine else None,
            'notice': self._notice(root), 'taken': None if mine else team.taken(root),
            'last_shared': last, 'kept': self._set_aside(root),
            'clash': root.name in self._clash,
            'model': record.get('model'), 'effort': record.get('effort'),
            'steps': self._steps(record, found, state),
            'workers': self._workers(run),
            'spent': {'dollars': dollars, 'tokens': tokens},
            'question': ({'id': asked['id'], 'text': asked['text'], 'from': asked['from']}
                         if asked else None),
            'problem': ({key: problem.get(key) for key in ('what', 'kept', 'action', 'label')}
                        if problem else None),
            'documents': self._supplied(root, record, found),
            'copies': self._copies(found),
            'outline': pipeline.outline_view(root, found, level) if drawing else None,
            'deck': (pipeline.deck_view(root, found, level, self._live(run, drawing),
                                        self._given_up(record, drawing))
                     if drawing else None),
            'deck_left': ({'says': pipeline.deck_says(found), 'artifact': 'deck'}
                          if ending == 'deck' and not resting else None),
            'finished': ({'ready': bool(report['ready']),
                          'limitations': list(report['limitations']),
                          'blocking': list(report['blocking']), 'index': report['file']}
                         if report and not resting else None)}

    def status(self) -> dict:
        """Every run in the workspace, for a script."""
        listed = []
        for root in self.trainings():
            found = self.brief(root) or {}
            listed.append({'path': str(root), 'id': root.name, 'state': found.get('state'),
                           'sentence': found.get('sentence')})
        return {'trainings': listed}

    def standing(self) -> dict:
        """What the status screen shows: every run on this computer with what it is doing
        and what it has cost, and apart from those the trainings teammates drive. `limit`
        is how many trainings work at once."""
        space, runs, elsewhere = self.workspace, [], []
        for root in self.trainings():
            # The record is read once, and the title is taken from the survey's own reading
            # of the training. Only where the survey cannot be made is it read on its own.
            try:
                record = self._load(root)
            except (WorkspaceError, OSError):
                continue
            try:
                surveyed = self._survey(root, record)
                title = surveyed.session['title']
            except (WorkspaceError, OSError):
                try:
                    surveyed, title = None, workspace.load(root)['title']
                except (WorkspaceError, OSError):
                    continue
            found = self._brief(root, record, surveyed)
            shown = {'path': str(root), 'id': root.name, 'title': title,
                     'state': found.get('state'), 'sentence': found.get('sentence'),
                     'driver': found.get('driver')}
            if found.get('mine'):
                dollars, tokens = spent(record)
                runs.append({**shown, 'needs': bool(found.get('needs')),
                             'queue': self._queue(self._run(root)),
                             'spent': {'dollars': dollars, 'tokens': tokens},
                             'notice': found.get('notice')})
            elif shown['driver'] is not None:
                elsewhere.append({**shown, 'last_shared': found.get('last_shared'),
                                  'notice': found.get('notice')})
        return {'limit': settings.load().parallel, 'runs': runs, 'elsewhere': elsewhere,
                'background': self.went_wrong(),
                'upkeep': self.upkeep.report() if self.upkeep else None}

    def went_wrong(self) -> dict | None:
        """What last went wrong in the work the runner does by itself while it serves, as
        {'at', 'says'}, until that work next goes right. None when nothing has."""
        kept = list(self._background.values())
        return max(kept, key=lambda found: found['at']) if kept else None

    # --- a notification when no page is open ---------------------------------------------

    def seen(self) -> None:
        """A page asked something, so one is open."""
        self._asked = time.monotonic()

    def page_open(self) -> bool:
        """Whether a page is open, as far as the runner can tell: one asked recently."""
        return self._asked is not None and time.monotonic() - self._asked < PAGE_OPEN

    @staticmethod
    def _needs(record: dict, found: pipeline.Survey) -> str | None:
        """The one thing a training needs its person for now, named so that the same
        thing is never taken for a new one. None when it needs nothing, or the person
        halted it themselves."""
        problem, asked, step = record.get('problem'), record.get('question'), found.next
        if problem:
            return f"problem:{problem.get('at')}"
        if record.get('halt'):
            return None
        if asked:
            return f"question:{asked.get('id')}"
        if step.kind == 'wait':
            entry = found.session['artifacts'].get(step.step.artifact) or {}
            return f"gate:{step.step.artifact}:{entry.get('sha256')}"
        if step.kind == 'outline':
            mine = found.decks[workspace.split(step.step.artifact)[1]]
            return f"outline:{step.step.id}:{(mine.kept.get('waiting') or {}).get('sha256')}"
        if step.kind == 'documents':
            return 'documents'
        return f'stuck:{step.why}' if step.kind == 'stuck' else None

    def tell(self) -> list[str]:
        """Tell the person, through the computer's own notifications, about each training
        of this computer's that needs a decision: only when that is turned on and no
        page is open, and once for each thing. Returns the titles that were told."""
        if not settings.load().notify or self.page_open():
            return []
        space, sent, told = self.workspace, team.kept('notified'), []
        for root in self.trainings():
            try:
                record = self._load(root)
                if not team.ours(space, record):
                    continue
                found = self._survey(root, record)
            except (WorkspaceError, OSError):
                continue
            thing = self._needs(record, found)
            if thing is None or sent.get(str(root)) == thing:
                continue
            if self.notifier.send(found.session['title']):
                sent[str(root)] = thing
                told.append(found.session['title'])
        if told:
            team.keep('notified', sent)
        return told

    def serving(self, every: float = FETCH_EVERY, tick: float = TICK) -> None:
        """While the runner serves: fetch the workspace every few minutes, and look every
        few seconds at whether to notify. `close` ends it."""
        with self._lock:
            if self._serving is not None and self._serving.is_alive():
                return
            self._serving = threading.Thread(target=self._serve, args=(every, tick),
                                             daemon=True, name='in-step')
            self._serving.start()

    def _serve(self, every: float, tick: float) -> None:
        last = time.monotonic()
        while not self._ending.wait(tick):
            if time.monotonic() - last >= every:
                last = time.monotonic()
                if not self._kept('fetch', self.fetch):
                    continue
            self._kept('tell', self.tell)

    def _kept(self, job: str, action) -> bool:
        """Do one piece of the work done in the background. What goes wrong never ends the
        runner, and the next look tries again; it is kept for the Status screen until the
        same work goes right. False when it went wrong."""
        try:
            action()
        except Exception as failure:  # neither ever ends the runner; the next look tries again
            said = str(failure).strip().rstrip('.') or type(failure).__name__
            self._background[job] = {'at': home.now(), 'says': BACKGROUND[job].format(said=said)}
            return False
        self._background.pop(job, None)
        return True

    # --- publishing inside the workspace -------------------------------------------------

    def publish(self, path) -> dict:
        """Publish a training as it stands: the next numbered revision, a tag on the
        commit where the workspace is, pushed with it. One that is not ready is
        published all the same, and the revision says so."""
        root = self.driven(path)
        if root is None:
            raise WorkspaceError('No run is driving this training.')
        space = self.space()
        with self.files:
            record = self._load(root)
            who = team.driver(space, record)
            if who is not None and not who['here']:
                raise Elsewhere(team.elsewhere(space, record))
            by = gitstate.identity(space.repo)
            if space.address is not None:
                self._step(space, push=True)
            ready = bool(self.index.readiness(root, self._wanted(root, record))['ready'])
            made = team.publish(space, root.name, workspace.load(root)['title'], ready, by)
        said = []
        if not ready:
            said.append(f"Revision {made['revision']} was published before this training "
                        'was ready, and says so.')
        if space.address is None:
            said.append('This workspace has no shared repository, so the revision is kept '
                        'on this computer.')
        elif not made['shared']:
            self._tags_unsent = True
            said.append('The revision is kept on this computer and is not shared yet '
                        f"({made['why']}). It goes with the workspace the next time it is "
                        'shared.')
        return {'revision': made['revision'], 'ready': ready, 'shared': made['shared'],
                'notice': ' '.join(said) or None}

    def published(self) -> list[dict]:
        """What the workspace has published, as far as this copy knows: each training's
        latest revision."""
        space = self.workspace
        if space is None:
            return []
        # A training deleted since keeps its revisions in git, and is not listed.
        return [entry for entry in team.published(space)
                if (Path(entry['path']) / workspace.STATE_DIR / 'session.json').is_file()]

    # --- deleting a training -------------------------------------------------------------

    def _why_not(self, space: gitstate.Workspace, record: dict, state: str) -> str | None:
        """Why this computer may not delete a training, in a sentence; None when it may.
        A training is deleted by the computer that runs it, or, once it is finished and
        nobody runs it, by anyone."""
        if self._checking:
            return CHECKING
        if team.ours(space, record):
            return None
        who = team.driver(space, record)
        if who is None:
            return None if state == 'done' else NOT_TAKEN
        return NOT_YOURS.format(name=who['name'])

    def _drive_files(self, root: Path, copies: list[dict]) -> list[dict]:
        """What a training left in Google Drive, which the runner never deletes: the
        preview presentation of each deck, a deck kept as Google Slides, and each Google
        Doc copy. Each is {'what', 'name', 'url'}."""
        found, folder = [], self._previews()
        for path in sorted(folder.glob('*.json')) if folder.is_dir() else ():
            entry = home.read_json(path, None)
            if isinstance(entry, dict) and entry.get('url') and entry.get('path') == str(root):
                found.append({'what': DRIVE['preview'], 'name': entry.get('name'),
                              'url': entry['url']})
        for path in sorted(root.rglob('deck-link.md')):
            if 'work' in path.relative_to(root).parts:
                continue
            said = dict(re.findall(r'^- (URL|Title): (.+)$', path.read_text(encoding='utf-8',
                                                                            errors='replace'),
                                   re.MULTILINE))
            if said.get('URL'):
                found.append({'what': DRIVE['slides'], 'name': said.get('Title'),
                              'url': said['URL'].strip()})
        found += [{'what': DRIVE['doc'], 'name': workspace.sentence(entry['label']),
                   'url': entry['link']} for entry in copies
                  if entry.get('kind') == 'google' and entry.get('link')]
        return found

    def leaving(self, path) -> dict:
        """What deleting a training would do, for the confirmation: whether this computer
        may (`may`, and `why` not), whether it is stopped first (`stops`), when the team
        sees it gone (`share`: None, 'decision' or 'asked'), and what stays: its published
        `revisions` and the files it left in Google Drive (`drive`). `documents` is how
        many documents the person supplied for it."""
        root = self.driven(path)
        if root is None:
            raise WorkspaceError('No run is driving this training.')
        space, record = self.space(), self._load(root)
        copies = self._wanted(root, record)
        found = self._survey(root, record, copies)
        run = self._run(root)
        state = self._state(record, found, run)[0]
        why = self._why_not(space, record, state)
        mine, _, shown, _, _ = self._whose(root, record, found, state, '')
        return {'path': str(root), 'title': found.session['title'], 'state': shown,
                'may': why is None, 'why': why,
                'stops': bool(mine and (state == 'working' or run.workers or run.busy)),
                'share': None if space.address is None else space.share,
                'revisions': team.revisions(space, root.name),
                'documents': len(self.documents.listed(root)) if record.get('documents')
                else 0,
                'drive': self._drive_files(root, copies)}

    def delete(self, path, title: str) -> dict:
        """Delete a training, as the person asks on the page. `title` is the one the page
        showed, so a page that is out of date deletes nothing.

        A run that is working is stopped first, as Stop does, and nothing more it does is
        kept; once nothing of it is in hand, its folder is taken out of the branch in one
        commit that says who deleted it and when, and shared as any change is. What only
        this computer kept for it goes too. Published revisions and files in Google Drive
        stay. Returns {'deleted', 'title', 'shared', 'notice'}. If a teammate took the
        training before the deletion was shared, their version comes back whole and the
        refusal says so."""
        root = self.driven(path)
        if root is None:
            raise WorkspaceError('No run is driving this training.')
        space = self.space()
        by = gitstate.identity(space.repo)
        run = self._run(root)

        def allowed() -> None:
            record = self._load(root)
            if workspace.load(root)['title'] != title:
                raise WorkspaceError(MISTITLED)
            why = self._why_not(space, record, self._state(
                record, self._survey(root, record), run)[0])
            if why:
                raise Elsewhere(why)

        with self.files:
            allowed()
            run.gone = True     # the step in hand keeps nothing, as when it is taken
            run.stop.set()      # and every agent and command it started is ended
        if not self._ended(run):
            with self.files:
                run.gone = False
                record = self._load(root)
                record['halt'] = 'stopped'
                self._store(root, record)
                self._commit(root, 'stopped on the page')
            raise WorkspaceError(NOT_ENDED)
        with self.files:
            if not (root / RECORD).is_file():
                raise WorkspaceError('This training is not here any more.')
            allowed()           # a fetch meanwhile may have made it someone else's
            gitstate.remove(space, root, f'{title}: {by} deletes this training, on '
                                         f'{team.day(home.now())}')
            self._let_go(root, keep=True)
        report = None
        if space.address is not None and space.share == gitstate.SHARE[0]:
            report = self._step(space, push=True)
            self._unshared = None if report['shared'] else report['notice']
        with self.files:
            back = (root / RECORD).is_file()    # a teammate's version came back over it
            if not back:
                shutil.rmtree(root, ignore_errors=True)
        if back:
            self.adopt()
            raise WorkspaceError(self._notice(root) or KEPT_BACK.format(
                name='Someone', when='a moment ago'))
        shared = None if space.address is None else bool(report and report['shared'])
        return {'deleted': True, 'title': title, 'shared': shared,
                'notice': None if shared in (None, True) else WAITS}

    @staticmethod
    def _ended(run: _Run) -> bool:
        """Wait until nothing of a run is in hand: no thread, no step and no slot. False
        when something has not ended in STOP_WAIT seconds."""
        deadline = time.monotonic() + STOP_WAIT
        while True:
            thread = run.thread
            alive = (thread is not None and thread.is_alive()
                     and thread is not threading.current_thread())
            if not alive and not run.busy:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def _let_go(self, root: Path, keep: bool = False) -> None:
        """Forget a training that is gone: what this computer kept for it outside the
        workspace, its place in the lists, and what the engine held for it. Its folder
        goes too, unless `keep`, for a caller that removes it later. What `set_aside`
        kept in git is never deleted. Call it holding `files`."""
        run = self._run(root)
        run.gone = True
        run.stop.set()
        if not keep:
            shutil.rmtree(root, ignore_errors=True)
        jobs = agents.staging()
        for old in jobs.iterdir() if jobs.is_dir() else ():
            if old.name.startswith(f'{root.name}--'):
                shutil.rmtree(old, ignore_errors=True)
        for name in ('notified', 'taken'):
            kept = team.kept(name)
            if kept.pop(str(root), None) is not None:
                team.keep(name, kept)
        home.forget(root)
        with self._lock:
            self._runs.pop(str(root), None)
        self._clash.pop(root.name, None)
        self._as_of = {key: value for key, value in self._as_of.items()
                       if key[1] != str(root)}

    # --- bringing a training in ----------------------------------------------------------

    def bring(self, path) -> dict:
        """Copy a training that was started in a conversation into the workspace, move
        its decisions to the page, give it a run record that takes it, and commit. The
        folder it came from is only read. Returns {'path', 'id'} of the copy, which then
        carries on from wherever its files say it is."""
        space, chosen, top = self.space(), settings.load(), Path(path)
        gitstate.identity(space.repo)
        if top == space.root or space.root in top.resolve().parents:
            raise WorkspaceError('This training is already in the workspace.')
        try:
            session = workspace.load(top)
        except WorkspaceError as refusal:
            raise WorkspaceError("This training's record cannot be read, so it cannot be "
                                 f'brought into the workspace. {refusal}')
        root = space.training(workspace.slugify(session['title']))
        if root.exists():
            raise WorkspaceError(f'The workspace already has a training in {space.folder}/'
                                 f'{root.name}. If that is the copy made of this one, work '
                                 'on it there.')
        why = team.unacceptable(top)
        if why:
            raise WorkspaceError('This training cannot be brought into the workspace. '
                                 + why)
        with self.files:
            try:
                team.copy_in(top, root)
                if session['settings']['approval'] != 'page':
                    workspace.checkpoint(root, approval='page', by='page')
                self._store(root, self._brought(root, chosen, space))
                home.remember(root, session['title'], session['levels'])
                self._commit(root, 'bring the training in from a conversation')
            except BaseException:  # a training is brought in whole or not at all
                shutil.rmtree(root, ignore_errors=True)
                gitstate.discard(space, root)
                raise
            self._claimed(root, space)
        self.wake(root)
        return {'path': str(root), 'id': root.name}

    def _brought(self, root: Path, chosen: settings.Settings,
                 space: gitstate.Workspace) -> dict:
        """A run record for a training made elsewhere, saying what its files cannot:
        which research run holds its approved plan, and that the documents it was
        planned from are settled."""
        session = workspace.load(root)
        planned = workspace.statuses(root, session).get('research-plan', 'not-started')
        said = pipeline.answers(root).get('source scope')
        scope = next((name for name, label in pipeline.SOURCES.items() if label == said),
                     pipeline.SCOPE)
        record = new_record(chosen.agent, chosen.model, chosen, scope, chosen.effort)
        if record['documents'] and planned != 'not-started':
            record['documents'].update(done=home.now(), count=0)
        research = workspace.research_record(root)
        if planned == 'approved' and research and research.get('run'):
            record['research'] = {'run': research['run'],
                                  'plan': workspace.sha256_file(root / pipeline.PLAN)}
        record['driver'] = team.claim(space)
        self._tried(record, 'intake', home.now(), 0.0, 'kept')
        return record


def _assets_said(problem: dict, recorded: dict) -> str:
    """One problem the slides tool found with a deck's assets, as the person is told it. A
    supplied picture whose file is gone or changed is theirs to supply again."""
    detail = str(problem.get('detail') or problem.get('code'))
    entry = recorded.get(problem.get('asset')) or {}
    if problem.get('code') in ('asset-file-missing', 'asset-hash-changed') \
            and entry.get('kind') in pipeline.SUPPLIED:
        return f'{detail}. Supply it again on this page, or put the file back.'
    then = str(problem.get('next') or '')
    return f"{detail}. {then}." if then and then not in detail else f'{detail}.'


def _placed(root: Path, level: str | None, text: str) -> dict:
    """The recorded assets a section draws, with what each is now."""
    recorded = pipeline.recorded(root, level)
    try:
        section = json.loads(text)
    except ValueError:
        return {}
    now = pipeline.assets_now(root, level, recorded)
    return {ident: now.get(ident) for ident in deck.placed(section, recorded)}
