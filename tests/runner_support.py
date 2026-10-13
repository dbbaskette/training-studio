"""Shared setup for the runner's tests: its import path, a job folder, a pretend web, and
an engine with scripted workers and the stand-in for harness-research behind it."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers

sys.path.insert(0, str(helpers.REPO))

from runner import worker_tools  # noqa: E402

PUBLIC = '93.184.216.34'    # an address on the public internet; nothing ever connects to it
BLUEPRINT = (helpers.EXAMPLES / 'blueprint.md').read_text(encoding='utf-8')
PLAN = {'topic': 'Rolling restarts', 'items': [
    {'id': 'instance-min', 'question': 'How many instances keep capacity during a restart?',
     'public_query': 'rolling restart minimum instances'},
    {'id': 'health-checks', 'question': 'What starts the next batch?',
     'public_query': 'rolling restart health check batch'}]}
PAGE = """<html><head><title>Rolling  restarts</title><style>p {color: red}</style></head>
<body><script>var hidden = 1;</script>
<h1>Rolling restarts</h1>
<p>A rolling restart replaces instances one batch at a time, so the app keeps serving
traffic while it restarts.</p>
<p>Capacity holds only when more than one instance is running. The platform’s health
check decides when the next batch starts.</p>
</body></html>"""


class Web:
    """A pretend web: what each address answers, and the addresses each host name has."""

    def __init__(self):
        self.pages, self.hosts, self.asked = {}, {}, []

    def page(self, url: str, body, kind: str | None = 'text/html; charset=utf-8',
             status: int = 200, headers: dict | None = None, addresses=(PUBLIC,)) -> str:
        host = url.split('/')[2].rpartition('@')[2].partition(':')[0]
        self.hosts.setdefault(host, list(addresses))
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.pages[url] = (status, {**({'content-type': kind} if kind else {}),
                                    **(headers or {})}, data)
        return url

    def resolver(self, host: str) -> list[str]:
        if host not in self.hosts:
            raise OSError('Name or service not known')
        return self.hosts[host]

    def opener(self, url: str, address: str, limit: int):
        self.asked.append((url, address))
        answer = self.pages[url]
        if isinstance(answer, Exception):
            raise answer
        status, headers, data = answer
        return status, headers, data[:limit + 1]


class JobCase(unittest.TestCase):
    """A test with an empty folder for one job at self.job, and a pretend web."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.base = Path(holder.name).resolve()
        self.job = self.base / 'job'
        self.web = Web()

    def tools(self, **prepared) -> worker_tools.WorkerTools:
        """Prepare the job, when anything to prepare is given, and return its tools."""
        if prepared or not (self.job / 'job.json').exists():
            worker_tools.prepare(self.job, **prepared)
        return worker_tools.WorkerTools(self.job, opener=self.web.opener,
                                        resolver=self.web.resolver,
                                        pdf=lambda path: 'Text of the PDF.\n')

    def ok(self, outcome) -> str:
        self.assertTrue(outcome[0], outcome[1])
        return outcome[1]

    def refused(self, outcome) -> str:
        self.assertFalse(outcome[0], outcome[1])
        return outcome[1]


# --- the engine, with nothing real behind it ---------------------------------------------

URL = 'https://docs.example.com/restarts'
QUOTE = 'Capacity holds only when more than one instance is running.'
QUESTIONS = {'availability': 'When does a rolling restart keep capacity?',
             'instance-min': 'How many instances keep capacity during a restart?',
             'health-checks': 'What starts the next batch?',
             'zero-downtime': 'Do rolling restarts guarantee zero downtime?'}
FOUR = {'topic': 'Rolling restarts', 'items': [
    {'id': ident, 'question': question, 'public_query': f'rolling restart {ident}'}
    for ident, question in QUESTIONS.items()]}
FORM = {'title': 'Rolling restarts', 'topic': 'Rolling restarts on the platform',
        'audience': 'Solutions engineers who deploy apps', 'purpose': 'Field enablement',
        'levels': [], 'brief_kind': 'product', 'time_limit': '25 minutes',
        'source_scope': 'public-web', 'deck_target': None, 'brand': None, 'copies': [],
        'yoodli': False, 'agent': None, 'model': None}


def fails(detail: str = 'It stopped without finishing: the model gave up.',
          reason: str = 'failed', cost: float | None = None):
    """A worker that ends without handing anything back, as an agent that failed would."""
    from runner.agents import Outcome
    return lambda tools, job: Outcome(False, reason, detail, cost=cost)


def asks(question: str):
    """A worker that asks the person a question, which ends its job."""
    def act(tools, job):
        tools.ask_person(question)
    return act


class Workers:
    """Scripted workers. Each kind of job does the right thing unless a test queues
    something else for it with `then`. `jobs` lists every job that was started."""

    def __init__(self):
        self.jobs, self.queued, self.plan, self.cost = [], {}, FOUR, None
        self.blueprint_text = BLUEPRINT

    def then(self, kind: str, *acts) -> None:
        """Queue what the next jobs of one kind do: `research-plan`, `blueprint`,
        `question`, or `question:<id>` for one research question."""
        self.queued.setdefault(kind, []).extend(acts)

    def of(self, kind: str) -> list:
        return [job for seen, job, spec in self.jobs if seen.partition(':')[0] == kind
                or seen == kind]

    def __call__(self, tools, job):
        from runner.agents import Outcome
        spec = tools.job
        kind = (f"question:{spec['finding']}" if spec['finding'] else
                'research-plan' if 'research-plan' in spec['artifacts'] else 'blueprint')
        self.jobs.append((kind, job, spec))
        queued = self.queued.get(kind) or self.queued.get(kind.partition(':')[0])
        act = queued.pop(0) if queued else getattr(self, kind.partition(':')[0]
                                                    .replace('-', '_'))
        returned = act(tools, job)
        if isinstance(returned, Outcome) or self.cost is None:
            return returned
        return Outcome(True, text=returned or '', cost=self.cost,
                       tokens={'input': 1000, 'cached': 800, 'output': 200}, seconds=1.5)

    def research_plan(self, tools, job):
        accepted = tools.submit_artifact('research-plan', json.dumps(self.plan))
        assert accepted[0], accepted[1]
        tools.submit_review('Four questions. I left rollback out: it is a topic of its own.')

    def question(self, tools, job):
        ident = tools.job['finding']
        tools.save_source(URL)
        verdict = 'contradicted' if ident == 'zero-downtime' else 'supported'
        accepted = tools.submit_finding(ident, verdict, f'What the page says about {ident}.',
                                        evidence=[{'source_id': 's1', 'quote': QUOTE}])
        assert accepted[0], accepted[1]

    def blueprint(self, tools, job):
        level = tools.job['artifacts']['blueprint'].get('level')
        text = self.blueprint_text if level is None else self.blueprint_text.replace(
            'Time: 25 min', f'Time: 25 min\nLevel: {level}')
        accepted = tools.submit_artifact('blueprint', text)
        assert accepted[0], accepted[1]
        tools.submit_review('A lesson. O3 is the objective I am least sure of.')


class StudioCase(unittest.TestCase):
    """A person with a data folder and a git identity of their own, a workspace, scripted
    workers, a pretend web and the stand-in for harness-research. Nothing real is started
    and nothing leaves this computer."""

    BACKGROUND = False

    def setUp(self):
        from runner import engine as engines, gitstate, research
        from runner.agents import Scripted
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.base = Path(holder.name).resolve()
        (self.base / 'no-templates').mkdir()
        (self.base / 'gitconfig').write_text(
            '[user]\n\tname = Alex\n\temail = alex@example.com\n[init]\n\tdefaultBranch = '
            f"main\n\ttemplateDir = {self.base / 'no-templates'}\n")
        self.web = Web()
        self.web.page(URL, PAGE)
        patches = [
            mock.patch.dict(os.environ, {'TRAINING_STUDIO_DATA': str(self.base / 'data'),
                                         'GIT_CONFIG_GLOBAL': str(self.base / 'gitconfig'),
                                         'GIT_CONFIG_NOSYSTEM': '1'}),
            mock.patch.object(worker_tools, 'fetch_once', self.web.opener),
            mock.patch.object(worker_tools, 'resolve', self.web.resolver)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        for name in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE'):
            os.environ.pop(name, None)
        self.engines, self.gitstate = engines, gitstate
        self.research = research.stand_in()
        self.workers = Workers()
        self.adapters = {'claude': Scripted(self.workers), 'codex': Scripted(self.workers)}
        self.space = self.set_up()
        self.engine = self.make()

    def set_up(self):
        """The workspace: a folder with no remote, unless a test wants another."""
        return self.gitstate.local(self.base / 'team-work')

    def make(self, **options):
        """An engine as the runner would start one, with nothing real behind it."""
        options = {'adapters': self.adapters, 'research': lambda: self.research,
                   'background': self.BACKGROUND, **options}
        engine = self.engines.Engine(**options)
        self.addCleanup(engine.close)
        return engine

    def start(self, **changes) -> Path:
        from runner import pipeline
        return Path(self.engine.start(pipeline.check_form({**FORM, **changes}))['path'])

    def view(self, root: Path) -> dict:
        return self.engine.view(root)

    def state(self, root: Path) -> str:
        return self.view(root)['state']

    def steps(self, root: Path) -> dict:
        return {step['id']: step for step in self.view(root)['steps']}

    def decide(self, root: Path, target: str, decision: str = 'approve',
               note: str | None = None, engine=None) -> dict:
        """Decide as the page does: through the desk's own decide, on the runner's page."""
        import workspace
        from runner import page
        seen = None
        if decision in ('approve', 'accept'):
            session = workspace.load(root)
            seen = workspace.sha256_file(
                root / workspace.artifact(root, session, target)['file'])
        return page.RunnerPage(8765, engine or self.engine).decide(
            str(root), target, decision, note, seen)

    def to_gate(self, root: Path, gate: str) -> None:
        """Approve what is waiting until `gate` is the one waiting."""
        import workspace
        for _ in range(8):
            waiting = workspace.status(root)['gate']
            self.assertIsNotNone(waiting, self.view(root))
            if waiting == gate:
                return
            self.decide(root, waiting)
        self.fail(f'{gate} never came up for review')

    def git(self, *args: str, repo: Path | None = None) -> str:
        done = subprocess.run(['git', *args], cwd=repo or self.space.repo,
                              capture_output=True, text=True, check=True)
        return done.stdout.strip()

    def log(self) -> list[str]:
        """What each commit says happened, oldest first."""
        return self.git('log', '--reverse', '--format=%s').splitlines()

    def record(self, root: Path) -> dict:
        return json.loads((root / '.training-studio' / 'run.json').read_text())
