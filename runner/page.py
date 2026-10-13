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
- What it adds is the contract in the appendices of the milestone 2 and milestone 3
  specifications: whether the runner is here, set-up, the agents, starting a training, a
  run, an answer to a worker's question, the person's documents, the copies, and sharing.
- `POST /api/documents` alone may carry up to DOCUMENT_LIMIT bytes, because it carries a
  document, and only when it is asked with the key. Every other address keeps the desk's
  limit, and every one of the desk's rules still applies to this one.
- `GET /api/gate` gains `whose` for a practice scenario: who wrote its file. For a Yoodli
  scenario it gains `beside`, the scenario it was laid out from.
- `GET /api/file` also answers for `README.md`, the index at the top of a training this
  computer knows, once it is written. The index is derived and is not one of a training's
  own files, so the desk alone refuses it.
- A refusal is `{"error": "<a sentence for a person>"}`. Something sent in the wrong shape
  is 400, a training this computer does not know is 403, a training no run is driving is
  404, and something that cannot be done as things stand is 409.
- The desk's lists gain `run`, and a training whose run has a question or a problem
  counts as needing the person. A decision made through the desk's own `decide` is
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
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
import desk
import workspace
from workspace import WorkspaceError

from runner import engine as engines
from runner import gitstate, pipeline, setup

READS = ('/api/capabilities', '/api/setup', '/api/agents', '/api/run')
WRITES = ('/api/setup/check', '/api/setup', '/api/trainings', '/api/run', '/api/answer',
          '/api/documents', '/api/copies', '/api/share')
DOCUMENTS = '/api/documents'
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
        if path == '/api/capabilities':
            return desk.as_json(HTTPStatus.OK, {'runner': True,
                                                'version': gitstate.installed()})
        if path == '/api/setup':
            return desk.as_json(HTTPStatus.OK, setup.describe(self.engine))
        if path == '/api/agents':
            return desk.as_json(HTTPStatus.OK, {'agents': self.agents()})
        if path == '/api/run':
            return desk.as_json(HTTPStatus.OK, self.run(one('path')))
        if path == '/api/gate':
            return desk.as_json(HTTPStatus.OK, self.gate(one('path'), one('artifact')))
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
        return shown

    def body_limit(self, target: str, headers) -> int:
        """A document may be sent whole, to its own address, by whoever holds the key.
        Anyone else's request there is held to the desk's limit, so it is refused unread."""
        if target.partition('?')[0] == DOCUMENTS:
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
        if found is None or 'error' in item:
            return item
        if found['needs'] and item.get('state') != 'needs-you':
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
        found = self.engine.brief(path)
        if found is not None and mode == 'chat' and found['state'] != 'done':
            raise desk.Refusal(HTTPStatus.CONFLICT, RUNNER_DECIDES)
        with self.engine.files:
            reply = super().move_approval(path, mode)
            driven = self.engine.changed(path, f'decisions are now made '
                                         f'{workspace.WHERE[mode]}')
        if driven:
            self.engine.wake(path)
        return reply

    # --- writes --------------------------------------------------------------------------

    def write(self, path: str, sent: dict):
        if path == '/api/setup/check':
            return desk.as_json(HTTPStatus.OK, shaped(setup.check, sent))
        if path == '/api/setup':
            return desk.as_json(HTTPStatus.OK,
                                setup.apply(self.engine, shaped(setup.read, sent)))
        if path == '/api/trainings':
            form = shaped(pipeline.check_form, sent)
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
        return super().write(path, sent)

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

    def __init__(self, engine: engines.Engine, port: int = 0):
        super().__init__(port, page=lambda chosen: RunnerPage(chosen, engine))
        self.engine = engine

    def stop(self) -> None:
        super().stop()
        self.engine.close()
