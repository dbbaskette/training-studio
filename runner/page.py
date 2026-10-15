"""The runner's server: the desk's page, with the runner behind it.

What a caller needs to know
---------------------------
    server = page.Studio(engine, port)    # the desk's server, answering for the runner too
    server.url                            # the link, with its key; for a person only
    server.serve()                        # until interrupted; server.stop() ends the engine

- It serves the same page as the desk and keeps every one of its rules: it answers on the
  local machine only, checks the `Host` header, needs the key for every call, and takes a
  change only as a POST with a JSON body from the page's own origin. Those rules live in
  the desk's `Page`; `RunnerPage` adds addresses and never loosens a rule.
- What it adds is the contract in the appendices of the milestone 2, 3, 4 and 5
  specifications: whether the runner is here, set-up, the agents, starting a training, a
  run, an answer to a worker's question, the person's documents, the copies, sharing,
  the decision about what a deck says, a slide's picture, who drives a training, the
  status of every run, publishing, and bringing a training in.
- A training in a shared workspace is run from one computer. List items and `GET /api/run`
  carry `driver`: null when nobody drives it, else {"name", "here", "since"}; `mine`,
  whether this computer may change it (null in a list for a training no run drives);
  `notice`, a sentence saying that it was taken from this computer and that what this
  computer had not shared is kept here, or that the training was changed on two computers
  at once; and `last_shared`, {"at", "by", "says"} for a training someone else drives,
  whose state is `elsewhere`: only what was last shared is known here. A run also carries
  `queue`, {"ahead": n} while it waits its turn; `taken`, {"by", "at", "kept"} for one
  that was taken from this computer, until it is taken back; `kept`, the names git
  keeps under, in this computer's copy, whatever this computer set aside of the
  training; and `clash`, true while it stands changed on two computers. Every address that changes a training someone else drives, or
  nobody does, answers 409 with who has it: a decision, a move of its decisions, a run's
  actions, an answer, its documents, its copies, and what its deck says. A training
  driven elsewhere never counts as needing the person here.
- `GET /api/models?agent=codex` answers what an agent offers to choose from: {"agent",
  "models": [{"name", "label", "family", "about", "levels", "default_level"}], "levels",
  "source", "problem"}. `levels` beside the models are those a model that is not listed may
  be given, and `source` where a list the runner keeps came from. A list that could
  not be made is still answered, with no models and `problem` saying why, so the page can
  say so and still take a name typed in. It is kept a while, and listing holds up nothing
  else the page asks.
- `POST /api/drive` with {"path", "action"} takes a training (`take`), which also takes
  one over, or hands it over (`hand-over`), and answers the run. `POST /api/fetch` brings
  in what teammates shared and sends nothing: {"reached", "received", "notice"}.
- `GET /api/status` answers {"limit", "runs", "elsewhere"}: each run on this computer as
  {"path", "id", "title", "state", "sentence", "driver", "needs", "queue", "spent",
  "notice"}, and each training a teammate drives as the first six of those with
  `last_shared` and `notice`. `limit` is how many trainings work at once.
- `POST /api/publish` with {"path"} answers {"revision", "ready", "shared", "notice"}.
  `GET /api/published` answers {"published": [{"path", "id", "title", "revision", "at",
  "by", "ready", "current"}]}, each training's latest revision; `current` is false when
  the training has changed here since. A training someone else drives is
  not published from here.
- `GET /api/delete?path=` answers what deleting a training would do: {"path", "title",
  "state", "may", "why", "stops", "share", "revisions", "documents", "drive"}, where
  `drive` lists each file it left in Google Drive as {"what", "name", "url"}. `POST
  /api/delete` with {"path", "title"} deletes it, stopping it first, and answers
  {"deleted", "title", "shared", "notice"}. The title must be the training's own. A
  training a conversation made is 404 here: the runner never deletes a folder it does
  not drive.
- `GET /api/setup` and `GET /api/status` carry `upkeep`: what `upkeep.Upkeep.report` says
  of Training Studio and its skills on this computer, or null where the runner does not
  look. `POST /api/companions`, with {}, brings each companion skill that is missing or
  older than its pin, in the background, through the installer's own checked install, and
  answers `upkeep`. It is 409 while a training here is working, while an update is in
  hand, and when there is nothing to bring. The page asks for it only after the person
  said yes in its confirmation.
- `upkeep.versions` has a row each for Training Studio and its companions, with what is
  installed, the newest, the pins and a state. `POST /api/upgrade` with {"version"}
  installs that newer Training Studio beside this one, in the background, and answers
  `upkeep`; it is 409 from a checkout, while a training is working, while anything else is
  in hand, and when `version` is not the newest known. Once it is installed, `POST
  /api/restart` with {} stops the runner, which then opens the newer version on the same
  port with the same key; it is 409 while a training is working. `POST /api/versions` with
  {"dismiss": key} stops Home showing the versions until a newer one is out. The page asks
  for each only after the person said yes.
- `POST /api/brand` with {"repository", "release"} keeps the brand skill's repository once
  git can read it as this person, and answers the set-up; it is 400, with a sentence, when
  it cannot be read or has no such release. An empty repository forgets it. `POST
  /api/brand/install` with {"release"} installs that release of the brand skill with its own
  installer, in the background, and answers `upkeep`; it is 409 while a training is working,
  while anything else is in hand, while a companion waits for Update, and when `release`
  is not the one shown in `upkeep.versions.brand`.
- `GET /api/setup` carries `shared`, what the studios config every *-studio reads holds
  that Training Studio can use, and `shared_problem`, a sentence when that file could not
  be read. `POST /api/setup` takes `"for_all_studios": true` to write the shared values the
  save changed into that file too, and then answers `for_all_studios` beside the set-up.
  See `setup` and `studios_config`.
- `POST /api/adopt` with {"path"} copies a training this computer knows, started in a
  conversation, into the workspace, and answers {"path", "id"} of the copy.
- Every request that passes the rules tells the engine a page is open, which is how the
  runner knows not to notify through the computer instead.
- `POST /api/documents` alone may carry up to DOCUMENT_LIMIT bytes, because it carries a
  document, and only when it is asked with the key. Every other address keeps the desk's
  limit, and every one of the desk's rules still applies to this one.
- `GET /api/gate` gains `whose` for a practice scenario: who wrote its file. For a Yoodli
  scenario it gains `beside`, the scenario it was laid out from. For a deck it gains
  `slides`, `review`, `audit` and `coverage`; `review` and `audit` are null, and the other
  two empty, for a deck the runner did not make.
- `GET /api/slide` answers one slide's picture as `image/png`, and nothing else: of a deck
  the runner rendered, named by `artifact`, or of a `section`'s latest preview while a
  deck is drawn, by `number`. It needs the key like every other read. What it sends is
  never read from an address the request gives: the place is worked out from the
  training, the deck or the section, and the number, and only a PNG found there, inside
  the training's own folder or the folder of the worker drawing that section, is sent.
- `POST /api/outline` records what the person decided about what a deck says, which is the
  runner's own gate, and answers the run.
- A run carries `redesign`: each of its decks drawn without a design, as {"level",
  "artifact", "label", "may", "why"}. `POST /api/redesign` with {"path", "level"} draws one
  again from a design, after the person said yes in the page's confirmation, and answers
  the run. It is 409 while the training works, for a deck that has its design already, and
  where this computer cannot make a deck from one, saying why.
- A decision at gate 6 about a deck the slides tool put to the person with its review is
  sent to that tool first, as their answer to its question; a refusal there is 409, and
  the core records nothing.
- `POST /api/asset` with {"path", "level", "asset", "content", "alt", "source",
  "restrictions"?} gives the slides tool a picture the person supplies for an asset of
  their deck's approved design, and answers the run. `content` is the picture in base64;
  like a document, it may be up to DOCUMENT_LIMIT bytes. A deck waiting for it carries on.
- The page's check of this computer gains what a deck needs here. Asking for a new look
  also lets the trainings that were waiting on what was missing carry on, and looks at the
  skills again, putting back a link the installer placed that has gone missing.
- `GET /api/file` also answers for `README.md`, the index at the top of a training this
  computer knows, once it is written. The index is derived and is not one of a training's
  own files, so the desk alone refuses it.
- A refusal is `{"error": "<a sentence for a person>"}`. Something sent in the wrong shape
  is 400, a training this computer does not know is 403, a training no run is driving is
  404, and something that cannot be done as things stand is 409.
- The desk's lists gain `run`, and a training whose run has a question or a problem
  counts as needing the person. One that someone else drives, or nobody does, never
  does: it is `in-progress` here, and keeps `waiting` only so that what was waiting when
  it was last shared can be read. A decision made through the desk's own `decide` is
  committed and wakes that training's run, and what the page is told then says what the
  runner does next, not what an assistant in a conversation would.
- Reading never starts or wakes a run: `GET /api/run` can be asked for as often as the
  page likes.
- While a run is driving a training, its decisions cannot be moved back to a conversation:
  a gate the runner waits at would then be one an assistant could pass. They can be moved
  once the run is done as far as it goes, which is how a slide deck gets made. Moving them
  either way wakes the run, which then looks at the training's files again.
"""
from __future__ import annotations

import base64
import binascii
import threading
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
import desk
import home
import workspace
from workspace import WorkspaceError

from runner import engine as engines
from runner import gitstate, pipeline, setup

READS = ('/api/capabilities', '/api/setup', '/api/agents', '/api/models', '/api/run',
         '/api/slide', '/api/status', '/api/published', '/api/delete')
WRITES = ('/api/setup/check', '/api/setup', '/api/trainings', '/api/run', '/api/answer',
          '/api/documents', '/api/copies', '/api/share', '/api/outline', '/api/drive',
          '/api/publish', '/api/adopt', '/api/fetch', '/api/delete', '/api/companions',
          '/api/asset', '/api/upgrade', '/api/restart', '/api/versions', '/api/redesign',
          '/api/brand', '/api/brand/install')
PNG = 'image/png'
DOCUMENTS = '/api/documents'
ASSET = '/api/asset'
DOCUMENT_LIMIT = 12_000_000     # bytes: one document of the largest size, in base64
CLOSE = 'You can close this page; it says when it needs you again.'
HALTED = ('This training is not running, so nothing more happens until you resume it or '
          'try again.')
RUNNER_DECIDES = ('The runner is driving this training, so its decisions are made on the '
                  'page.')


def shaped(action, *args):
    """Run something that reads what was sent. Its refusal means the request was wrong."""
    try:
        return action(*args)
    except WorkspaceError as refusal:
        raise desk.Refusal(HTTPStatus.BAD_REQUEST, str(refusal))


class RunnerPage(desk.Page):
    """What the page may ask the runner, on top of what it may ask the desk."""
    reads = (*desk.READS, *READS)
    writes = (*desk.WRITES, *WRITES)

    def __init__(self, port: int, engine: engines.Engine):
        super().__init__(port)
        self.engine = engine

    # --- reads ---------------------------------------------------------------------------

    def read(self, path: str, one):
        self.engine.seen()
        if path == '/api/status':
            return desk.as_json(HTTPStatus.OK, self.engine.standing())
        if path == '/api/published':
            return desk.as_json(HTTPStatus.OK, {'published': self.engine.published()})
        if path == '/api/capabilities':
            return desk.as_json(HTTPStatus.OK, {'runner': True,
                                                'version': gitstate.installed()})
        if path == '/api/setup':
            return desk.as_json(HTTPStatus.OK, setup.describe(self.engine))
        if path == '/api/agents':
            return desk.as_json(HTTPStatus.OK, {'agents': self.agents()})
        if path == '/api/models':
            return desk.as_json(HTTPStatus.OK, shaped(self.engine.models, one('agent')))
        if path == '/api/run':
            return desk.as_json(HTTPStatus.OK, self.run(one('path')))
        if path == '/api/delete':
            return desk.as_json(HTTPStatus.OK, self.engine.leaving(self.driving(one('path'))))
        if path == '/api/gate':
            return desk.as_json(HTTPStatus.OK, self.gate(one('path'), one('artifact')))
        if path == '/api/slide':
            return HTTPStatus.OK, PNG, self.slide(one)
        if path == '/api/file' and one('artifact') == pipeline.INDEX:
            return desk.as_json(HTTPStatus.OK, self.index(one('path')))
        return super().read(path, one)

    def index(self, path: str) -> dict:
        """A training's index, in the shape the desk gives any of its files."""
        desk.registered(path)
        file = desk.inside(Path(path), pipeline.INDEX)
        if not file.is_file():
            raise desk.Refusal(HTTPStatus.NOT_FOUND, 'The index has not been written yet.')
        shown = {'artifact': pipeline.INDEX, 'file': pipeline.INDEX,
                 'size': file.stat().st_size, 'binary': True}
        found = desk.text_of(file)
        if found is None:
            return shown
        return {**shown, 'binary': False, 'text': found[0], 'truncated': found[1]}

    def gate(self, path: str, name: str) -> dict:
        """The desk's gate. A practice scenario's also says whose file it is, and a Yoodli
        scenario's names the scenario it was laid out from, to show beside it."""
        shown = desk.gate(path, name)
        kind = workspace.split(name)[0].partition(':')[0]
        if kind == 'scenario':
            shown['whose'] = self.engine.whose(path, name)
        elif kind == 'yoodli':
            source = name.replace('yoodli:', 'scenario:', 1)
            shown['beside'] = {'artifact': source, 'label': desk.named(source)}
        elif kind == 'deck':
            shown.update(self.engine.deck_gate(path, name))
        return shown

    def slide(self, one) -> bytes:
        """One slide's picture. The request names a training this computer knows, a deck
        of it or a section of the deck being drawn, and a number, and nothing else."""
        def given(name: str) -> str | None:
            try:
                return one(name)
            except desk.Refusal:
                return None

        path, artifact, section = one('path'), given('artifact'), given('section')
        if (artifact is None) == (section is None):
            raise desk.Refusal(HTTPStatus.BAD_REQUEST, 'Name the deck as artifact, or the '
                               'section, and not both.')
        if not one('number').isascii() or not one('number').isdigit():
            raise desk.Refusal(HTTPStatus.BAD_REQUEST, 'Give number as a whole number.')
        desk.registered(path)
        if self.engine.driven(path) is None:
            raise desk.Refusal(HTTPStatus.NOT_FOUND, 'No run is driving this training.')
        try:
            return shaped(self.engine.picture, path, int(one('number')), artifact, section)
        except OSError:
            raise desk.Refusal(HTTPStatus.NOT_FOUND, engines.NO_PICTURE)

    def computer(self, look: bool) -> dict | None:
        """The desk's look at this computer, with what a deck needs here. A new look is a
        new look at those too, and wakes the trainings that were waiting on them."""
        seen = super().computer(look)
        if seen is None:
            return None
        keep = getattr(self.engine, 'upkeep', None)
        if look and keep is not None:
            keep.again()
        needs = self.engine.look_again() if look else self.engine.deck_needs()
        wanted = self.uses_deck()
        items = [{**item, 'optional': not wanted} for item in needs['items']]
        wrong = [*seen['wrong'], *(item['name'] for item in items
                                   if item['state'] != 'ok' and wanted)]
        return {**seen, 'items': [*seen['items'], *items], 'wrong': wrong,
                'ready': seen['ready'] and not wrong}

    @staticmethod
    def uses_deck() -> bool:
        """Whether any training on this computer wants a deck."""
        for entry in home.trainings():
            try:
                if 'deck' in pipeline.wanted(workspace.load(Path(entry['path']))):
                    return True
            except (WorkspaceError, OSError):
                continue
        return False

    def body_limit(self, target: str, headers) -> int:
        """A document may be sent whole, to its own address, by whoever holds the key.
        Anyone else's request there is held to the desk's limit, so it is refused unread."""
        if target.partition('?')[0] in (DOCUMENTS, ASSET):
            try:
                self.check_token(headers)
            except desk.Refusal:
                return super().body_limit(target, headers)
            return DOCUMENT_LIMIT
        return super().body_limit(target, headers)

    def agents(self) -> list[dict]:
        """Each agent: installed, signed in and reachable now. Looked at when asked, both
        at once, and each look is reused for a minute."""
        names = list(self.engine.adapters)
        with ThreadPoolExecutor(max_workers=len(names) or 1) as pool:
            found = list(pool.map(self.engine.ready, names))
        return [{'agent': name, 'installed': ready.installed, 'signed_in': ready.signed_in,
                 'reachable': ready.reachable, 'version': ready.version,
                 'problem': ready.problem} for name, ready in zip(names, found)]

    def driving(self, path: str) -> str:
        """A training this computer knows, once a run drives it. Any other folder, such as
        one a conversation made, is never the runner's to change."""
        desk.registered(path)
        if self.engine.driven(path) is None:
            raise desk.Refusal(HTTPStatus.NOT_FOUND, 'No run is driving this training.')
        return path

    def run(self, path: str) -> dict:
        """One training's run, for a training this computer knows."""
        desk.registered(path)
        found = self.engine.view(path)
        if found is None:
            raise desk.Refusal(HTTPStatus.NOT_FOUND, 'No run is driving this training.')
        return found

    # --- the desk's lists ----------------------------------------------------------------

    def trainings(self) -> list[dict]:
        return [self.with_run(item) for item in super().trainings()]

    def detail(self, path: str) -> dict:
        return self.with_run(super().detail(path))

    def with_run(self, item: dict) -> dict:
        """Add a training's run to what the desk says about it. A run with a question or
        a problem makes the training one that needs the person."""
        found = self.engine.brief(item['path'])
        item['run'] = found and {'state': found['state'], 'sentence': found['sentence']}
        item['driver'] = found and found['driver']
        item['mine'] = None if found is None else found['mine']
        item['notice'] = found and found['notice']
        item['last_shared'] = found and found['last_shared']
        if found is None or 'error' in item:
            return item
        if not found['mine']:   # it waits for whoever drives it, not for the person here
            if item.get('state') == 'needs-you' or (item.get('state') == 'in-progress'
                                                    and found['state'] != 'done'):
                # What was waiting when it was last shared is kept, to be read.
                item.update(state='in-progress', sentence=found['sentence'])
        elif found['needs'] and item.get('state') != 'needs-you':
            item.update(state='needs-you', sentence=found['sentence'],
                        waiting={'artifact': None, 'label': None,
                                 'question': found['question'], 'recorded': False})
        elif item.get('state') == 'in-progress' and found['state'] != 'done':
            item['sentence'] = found['sentence']
        return item

    # --- the desk's changes --------------------------------------------------------------

    def decide(self, path: str, target: str, decision: str, note: str | None,
               seen: str | None) -> dict:
        """Record a decision as the desk does. For a training a run is driving it is then
        committed, shared if that is wanted, and the run is woken."""
        with self.engine.files:
            self.engine.hold(path)
            try:   # a deck the slides tool presented has the approval sent to it first
                self.engine.deck_decided(path, target, decision, note, seen)
            except WorkspaceError as refusal:
                raise desk.Refusal(HTTPStatus.CONFLICT, str(refusal))
            reply = super().decide(path, target, decision, note, seen)
            driven = self.engine.decided(path, reply['decided'])
        if not driven:
            return reply
        self.engine.carry_on(path)
        state, coming = self.engine.ahead(path)
        if state in ('paused', 'stopped', 'failed'):
            coming = HALTED
        elif state == 'working':
            coming = f'{coming} {CLOSE}'
        reply['said'] = f'{desk.SAID[decision]} {coming}'
        reply['next'] = desk.next_up(self.trainings())
        return reply

    def move_approval(self, path: str, mode: str) -> dict:
        """Move a training's decisions as the desk does, except away from the page while a
        run is driving the training. The change is committed for a training a run drove."""
        desk.registered(path)
        self.engine.hold(path)
        found = self.engine.brief(path)
        if found is not None and mode == 'chat' and found['state'] != 'done':
            raise desk.Refusal(HTTPStatus.CONFLICT, RUNNER_DECIDES)
        with self.engine.files:
            self.engine.hold(path)
            reply = super().move_approval(path, mode)
            driven = self.engine.changed(path, f'decisions are now made '
                                         f'{workspace.WHERE[mode]}')
        if driven:
            self.engine.wake(path)
        return reply

    # --- writes --------------------------------------------------------------------------

    def write(self, path: str, sent: dict):
        self.engine.seen()
        if path == '/api/drive':
            return desk.as_json(HTTPStatus.OK, self.drive(sent))
        if path == '/api/publish':
            return desk.as_json(HTTPStatus.OK, self.engine.publish(self.known(sent)))
        if path == '/api/adopt':
            return desk.as_json(HTTPStatus.OK, self.adopt(sent))
        if path == '/api/fetch':
            return desk.as_json(HTTPStatus.OK, self.engine.fetch())
        if path == '/api/companions':
            return desk.as_json(HTTPStatus.OK, {'upkeep': self.update()})
        if path == '/api/upgrade':
            version = desk.text(sent, 'version')
            return desk.as_json(HTTPStatus.OK, {'upkeep': self.keeper().upgrade(
                self.working(), version)})
        if path == '/api/restart':
            return desk.as_json(HTTPStatus.OK, {'upkeep': self.keeper().restart(
                self.working())})
        if path == '/api/versions':
            return desk.as_json(HTTPStatus.OK, {'upkeep': self.keeper().dismiss(
                desk.text(sent, 'dismiss'))})
        if path == '/api/brand':
            return desk.as_json(HTTPStatus.OK, shaped(setup.save_brand, self.engine, sent))
        if path == '/api/brand/install':
            release = desk.text(sent, 'release')
            return desk.as_json(HTTPStatus.OK, {'upkeep': self.keeper().install_brand(
                self.working(), release)})
        if path == '/api/delete':
            title = desk.text(sent, 'title')
            return desk.as_json(HTTPStatus.OK, self.engine.delete(
                self.driving(desk.text(sent, 'path')), title))
        if path == '/api/setup/check':
            return desk.as_json(HTTPStatus.OK, shaped(setup.check, sent))
        if path == '/api/setup':
            return desk.as_json(HTTPStatus.OK,
                                setup.apply(self.engine, shaped(setup.read, sent)))
        if path == '/api/trainings':
            form = shaped(pipeline.check_form, sent, self.engine.brands())
            return desk.as_json(HTTPStatus.OK, self.engine.start(form))
        if path == '/api/run':
            return desk.as_json(HTTPStatus.OK, self.act(sent))
        if path == '/api/answer':
            return desk.as_json(HTTPStatus.OK, self.answered(sent))
        if path == DOCUMENTS:
            return desk.as_json(HTTPStatus.OK, self.supplied(sent))
        if path == '/api/copies':
            return desk.as_json(HTTPStatus.OK, self.copied(sent))
        if path == '/api/share':
            return desk.as_json(HTTPStatus.OK, self.engine.share())
        if path == ASSET:
            return desk.as_json(HTTPStatus.OK, self.asset(sent))
        if path == '/api/outline':
            return desk.as_json(HTTPStatus.OK, self.outline(sent))
        if path == '/api/redesign':
            return desk.as_json(HTTPStatus.OK, self.redesign(sent))
        return super().write(path, sent)

    def update(self) -> dict:
        """Bring the companion skills that are missing or older, unless a training here is
        working: a step in hand keeps using the skill it started with."""
        return self.keeper().update(self.working())

    def keeper(self):
        """What looks after the skills here, or a refusal where nothing does."""
        keep = getattr(self.engine, 'upkeep', None)
        if keep is None:
            raise desk.Refusal(HTTPStatus.CONFLICT, 'This runner does not look after the '
                               'skills on this computer. Run the installer to update them.')
        return keep

    def working(self) -> bool:
        """Whether any training on this computer is working now."""
        return any((self.engine.brief(root) or {}).get('state') == 'working'
                   for root in self.engine.trainings())

    def known(self, sent: dict) -> str:
        """The training a change names, once this computer knows it and a run drives it."""
        path = desk.text(sent, 'path')
        self.run(path)
        return path

    def drive(self, sent: dict) -> dict:
        """Take a training, which takes over one someone else drives, or hand it over."""
        action = desk.text(sent, 'action')
        if action not in engines.DRIVING:
            raise desk.Refusal(HTTPStatus.BAD_REQUEST, 'A training can be asked to: '
                               + ', '.join(engines.DRIVING) + '.')
        return self.engine.drive(self.known(sent), action)

    def adopt(self, sent: dict) -> dict:
        """Bring a training this computer knows, started in a conversation, into the
        workspace. The copy is the one to work on; the folder it came from is left as it
        was."""
        path = desk.text(sent, 'path')
        desk.registered(path)
        return self.engine.bring(path)

    def outline(self, sent: dict) -> dict:
        """Record what the person decided about what a deck says: approve it, or say
        what should change. It is theirs alone to decide, and decided here."""
        path, decision = desk.text(sent, 'path'), desk.text(sent, 'decision')
        level, note = desk.text(sent, 'level', False), desk.text(sent, 'note', False)
        if decision not in engines.DECIDING:
            raise desk.Refusal(HTTPStatus.BAD_REQUEST, 'What a deck says can be decided '
                               'as: ' + ', '.join(engines.DECIDING) + '.')
        if decision == 'revise' and not (note or '').strip():
            raise desk.Refusal(HTTPStatus.BAD_REQUEST, 'Say what should change.')
        self.run(path)
        return self.engine.outline(path, level or None, decision, note,
                                   desk.text(sent, 'seen', False),
                                   desk.text(sent, 'design', False))

    def redesign(self, sent: dict) -> dict:
        """Draw a deck that was drawn without a design again from one, as the person asked,
        after they said yes in the page's confirmation. It is theirs alone to ask for."""
        path, level = desk.text(sent, 'path'), desk.text(sent, 'level', False)
        self.run(path)
        try:
            return self.engine.redesign(path, level or None)
        except WorkspaceError as refusal:
            raise desk.Refusal(HTTPStatus.CONFLICT, str(refusal))

    def asset(self, sent: dict) -> dict:
        """A picture the person supplies for their deck: it is theirs alone to give."""
        path, asset = desk.text(sent, 'path'), desk.text(sent, 'asset')
        alt, source = desk.text(sent, 'alt'), desk.text(sent, 'source')
        level = desk.text(sent, 'level', False)
        restrictions = desk.text(sent, 'restrictions', False)
        content = sent.get('content')
        if not isinstance(content, str) or not content:
            raise desk.Refusal(HTTPStatus.BAD_REQUEST, 'Give the picture as text.')
        if not alt.strip() or not source.strip():
            raise desk.Refusal(HTTPStatus.BAD_REQUEST, 'Say what the picture shows and where '
                               'it came from.')
        try:
            data = base64.b64decode(content, validate=True)
        except (binascii.Error, ValueError):
            raise desk.Refusal(HTTPStatus.BAD_REQUEST, 'That picture did not arrive whole. '
                               'Add it again.')
        self.run(path)
        try:
            return self.engine.supply_asset(path, level or None, asset, data, alt, source,
                                            restrictions or None)
        except WorkspaceError as refusal:
            raise desk.Refusal(HTTPStatus.CONFLICT, str(refusal))

    def act(self, sent: dict) -> dict:
        path, action = desk.text(sent, 'path'), desk.text(sent, 'action')
        if action not in engines.ACTIONS:
            raise desk.Refusal(HTTPStatus.BAD_REQUEST, 'A run can be asked to: '
                               + ', '.join(engines.ACTIONS) + '.')
        self.run(path)
        return self.engine.act(path, action)

    def answered(self, sent: dict) -> dict:
        path, ident = desk.text(sent, 'path'), desk.text(sent, 'id')
        answer = desk.text(sent, 'answer')
        if not answer.strip():
            raise desk.Refusal(HTTPStatus.BAD_REQUEST, 'Write an answer first.')
        self.run(path)
        return self.engine.answer(path, ident, answer)


    def supplied(self, sent: dict) -> dict:
        """Add one of the person's documents, remove one, or hear that they are all added."""
        path, action = desk.text(sent, 'path'), desk.text(sent, 'action')
        if action not in engines.SUPPLYING:
            raise desk.Refusal(HTTPStatus.BAD_REQUEST, 'A document can be: '
                               + ', '.join(engines.SUPPLYING) + '.')
        name, data = desk.text(sent, 'name', action != 'done'), None
        if action == 'add':
            content = sent.get('content')
            if not isinstance(content, str) or not content:
                raise desk.Refusal(HTTPStatus.BAD_REQUEST, 'Give content as text.')
            try:
                data = base64.b64decode(content, validate=True)
            except (binascii.Error, ValueError):
                raise desk.Refusal(HTTPStatus.BAD_REQUEST, 'That document did not arrive '
                                   'whole. Add it again.')
        self.run(path)
        return self.engine.supply(path, action, name, data)

    def copied(self, sent: dict) -> dict:
        path = desk.text(sent, 'path')
        self.run(path)
        return self.engine.copies_again(path)


class Studio(desk.Desk):
    """The runner's server: the desk's, with a page that also answers for the runner."""

    def __init__(self, engine: engines.Engine, port: int = 0, token: str | None = None):
        super().__init__(port, page=lambda chosen: RunnerPage(chosen, engine))
        self.engine = engine
        if token:   # a runner opened again in its own place keeps the key its page holds
            self.page.token = self.token = token

    def serve(self) -> None:
        self.engine.serving()
        super().serve()

    def leave(self, after: float = 0.5) -> None:
        """Stop serving shortly, once what is being answered has gone out."""
        threading.Timer(after, self.server.shutdown).start()

    def start(self) -> None:
        self.engine.serving()
        super().start()

    def stop(self) -> None:
        super().stop()
        self.engine.close()
