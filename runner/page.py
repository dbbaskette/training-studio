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
- What it adds is the contract in the milestone 2 specification's appendix: whether the
  runner is here, set-up, the agents, starting a training, a run, an answer to a worker's
  question, and sharing.
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
  a gate the runner waits at would then be one an assistant could pass.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus

import runner  # noqa: F401  puts the core on the import path
import desk
import workspace
from workspace import WorkspaceError

from runner import engine as engines
from runner import gitstate, pipeline, setup

READS = ('/api/capabilities', '/api/setup', '/api/agents', '/api/run')
WRITES = ('/api/setup/check', '/api/setup', '/api/trainings', '/api/run', '/api/answer',
          '/api/share')
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
        return super().read(path, one)

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
        elif state == 'done':
            coming = pipeline.LATER  # "Approved." has already said what was approved
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
            self.engine.changed(path, f'decisions are now made {workspace.WHERE[mode]}')
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


class Studio(desk.Desk):
    """The runner's server: the desk's, with a page that also answers for the runner."""

    def __init__(self, engine: engines.Engine, port: int = 0):
        super().__init__(port, page=lambda chosen: RunnerPage(chosen, engine))
        self.engine = engine

    def stop(self) -> None:
        super().stop()
        self.engine.close()
