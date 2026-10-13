"""Shared setup for the runner's tests: its import path, a job folder, a pretend web, and
an engine with scripted workers, the stand-in for harness-research, and small stand-ins
for the person's documents, the copies and the index behind it."""
import hashlib
import json
import os
import re
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
DOCUMENT = (helpers.EXAMPLES / 'document.md').read_text(encoding='utf-8')
BRIEF = (helpers.EXAMPLES / 'product-brief.md').read_text(encoding='utf-8')
SCENARIO = (helpers.EXAMPLES / 'scenario.md').read_text(encoding='utf-8')
YOODLI = (helpers.EXAMPLES / 'yoodli.md').read_text(encoding='utf-8')
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
        `document`, `brief`, `scenario`, `yoodli`, `question`, or `question:<id>` for one
        research question."""
        self.queued.setdefault(kind, []).extend(acts)

    def of(self, kind: str) -> list:
        return [job for seen, job, spec in self.jobs if seen.partition(':')[0] == kind
                or seen == kind]

    def __call__(self, tools, job):
        from runner.agents import Outcome
        spec = tools.job
        kind = f"question:{spec['finding']}" if spec['finding'] else next(
            iter(spec['artifacts']))
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
        if tools.job['fetch']:  # otherwise the person's first document is already s1
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

    def document(self, tools, job):
        accepted = tools.submit_artifact('document', DOCUMENT)
        assert accepted[0], accepted[1]
        tools.submit_review('Each section teaches what its comment says. The glossary is '
                            'short.')

    def brief(self, tools, job):
        accepted = tools.submit_artifact('brief', BRIEF)
        assert accepted[0], accepted[1]
        tools.submit_review('It is weakest on rollback, which the research did not settle.')

    def scenario(self, tools, job):
        accepted = tools.submit_artifact('scenario', SCENARIO)
        assert accepted[0], accepted[1]
        tools.submit_review('A roleplay: the objective is to handle an objection.')

    def yoodli(self, tools, job):
        # Every count is written as 0, as the brief says: the real ones are put in.
        accepted = tools.submit_artifact('yoodli', re.sub(r'\b[\d,]+ of ', '0 of ', YOODLI))
        assert accepted[0], accepted[1]
        tools.submit_review('Goal 3 carries criteria 3 and 4, which are one behaviour.')


class Documents:
    """Stands in for `runner.documents`, by its docstring. It reads only plain text: any
    other document that is taken is kept as one that could not be read."""
    TYPES = ('.txt', '.md', '.html', '.htm', '.docx', '.pdf')
    LIMITS = {'bytes': 8_000_000, 'files': 40}
    FOLDER = 'sources/supplied'

    def __init__(self, pdf: bool = False):
        self.pdf, self.kept = pdf, {}

    def accepts(self) -> tuple[str, ...]:
        return tuple(kind for kind in self.TYPES if kind != '.pdf' or self.pdf)

    def listed(self, root: Path) -> list[dict]:
        return [dict(entry) for entry in self.kept.get(str(root), [])
                if (Path(root) / entry['original']).is_file()]

    def add(self, root: Path, name: str, data: bytes) -> dict:
        from workspace import WorkspaceError
        added = self.listed(root)
        if not name or Path(name).name != name or name.startswith('.'):
            raise WorkspaceError('Give the document a plain file name.')
        if Path(name).suffix.lower() not in self.accepts():
            raise WorkspaceError(f'{name} is not a kind of document that can be read here. '
                                 'Save it as text or as a Word file.')
        if len(data) > self.LIMITS['bytes']:
            raise WorkspaceError(f'{name} is larger than 8 MB.')
        if len(added) >= self.LIMITS['files']:
            raise WorkspaceError('A training takes at most 40 documents.')
        if any(entry['name'] == name for entry in added):
            raise WorkspaceError(f'{name} was already added.')
        ident = worker_tools.slug(Path(name).stem)
        folder = Path(root) / self.FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
        try:
            if Path(name).suffix.lower() not in ('.txt', '.md'):
                raise ValueError
            text, problem = worker_tools.tidy(data.decode('utf-8')), None
            (folder / f'{ident}.text').write_text(text, encoding='utf-8')
        except ValueError:
            problem = f'{name} could not be read. Save it as text and add it again.'
        entry = {'name': name, 'bytes': len(data), 'readable': problem is None,
                 'problem': problem, 'id': ident, 'title': Path(name).stem,
                 'file': f'{self.FOLDER}/{ident}.text', 'original': f'{self.FOLDER}/{name}',
                 'sha256': hashlib.sha256(data).hexdigest()}
        self.kept.setdefault(str(root), []).append(entry)
        return dict(entry)

    def remove(self, root: Path, name: str) -> None:
        from workspace import WorkspaceError
        entry = next((entry for entry in self.listed(root) if entry['name'] == name), None)
        if entry is None:
            raise WorkspaceError(f'{name} is not one of the documents added.')
        for file in (entry['file'], entry['original']):
            (Path(root) / file).unlink(missing_ok=True)
        self.kept[str(root)] = [kept for kept in self.kept[str(root)] if kept['name'] != name]

    def sources(self, root: Path) -> tuple[list[dict], list[dict]]:
        readable = [entry for entry in self.listed(root) if entry['readable']]
        plan = [{'id': entry['id'], 'title': entry['title'], 'file': entry['file'],
                 'original_file': entry['original'], 'limits': 'none'} for entry in readable]
        offered = [{'title': entry['title'], 'origin': f"Supplied: {entry['name']}",
                    'text': (Path(root) / entry['file']).read_text(encoding='utf-8'),
                    'file': entry['file'], 'supplied': entry['id']} for entry in readable]
        return plan, offered


class Drive:
    """A pretend Google Drive, kept in memory, for the stand-in below."""

    def __init__(self):
        self.docs = {}

    def create(self, title: str, markdown: str) -> dict:
        ident = f'doc{len(self.docs) + 1}'
        self.docs[ident] = markdown
        return {'file_id': ident, 'url': f'https://docs.example.com/d/{ident}/edit'}

    def update(self, file_id: str, markdown: str) -> None:
        self.docs[file_id] = markdown

    def export(self, file_id: str) -> str:
        return self.docs[file_id]


class Copies:
    """Stands in for `runner.copies`, by its docstring. What is wanted is what the core
    says, and a copy is made through the core: a Google Doc in a pretend Drive, a Word
    copy as a small file. `refuse` maps a kind of copy to why none can be made."""
    STATES = {'current': 'made', 'outdated': 'out-of-date'}

    def __init__(self):
        self.drive, self.refuse, self.calls = Drive(), {}, 0

    def wanted(self, root: Path, problems: dict | None = None) -> list[dict]:
        import gdocs
        import workspace
        session, listed = workspace.load(root), []
        docs = gdocs.read_links(root)['docs']
        for name, state in gdocs.copy_states(root, session).items():
            now = self.STATES.get(state, 'not-made')
            listed.append({'artifact': name, 'label': workspace.label(name), 'kind': 'google',
                           'state': now, 'link': (docs.get(name) or {}).get('url'),
                           'problem': None if now == 'made' else (problems or {}).get(name)})
        for name, state in workspace.export_states(root, session).items():
            made, now = session['exports'].get(name) or {}, self.STATES.get(state, 'not-made')
            listed.append({'artifact': name, 'label': workspace.label(name), 'kind': 'word',
                           'state': now, 'link': made.get('file'),
                           'problem': made.get('unavailable') if now != 'made' else None})
        return listed

    def make(self, root: Path, google=None, word=None) -> tuple[list[dict], dict]:
        import gdocs
        import workspace
        self.calls += 1
        session, problems, made = workspace.load(root), {}, []
        state = workspace.statuses(root, session)
        for entry in self.wanted(root):
            name = entry['artifact']
            if entry['state'] == 'made' or state.get(name) != 'approved':
                continue
            file = Path(root) / workspace.artifact(root, session, name)['file']
            if entry['kind'] == 'google' and 'google' in self.refuse:
                problems[name] = self.refuse['google']
            elif entry['kind'] == 'google':
                gdocs.push(root, name, self.drive, force=True)
                made.append((name, 'google'))
            elif 'word' in self.refuse:
                workspace.export(root, name, unavailable=self.refuse['word'])
            else:
                file.with_suffix('.docx').write_bytes(b'PK\x03\x04 a Word copy of '
                                                      + file.read_bytes())
                workspace.export(root, name)
                made.append((name, 'word'))
        return [entry for entry in self.wanted(root, problems)
                if (entry['artifact'], entry['kind']) in made], problems


class Index:
    """Stands in for `runner.index`, by its docstring: readiness as the core's own check
    computes it, in the page's words, and a README that says the same."""
    FILE = 'README.md'

    def readiness(self, root: Path, copies: list[dict] | None = None) -> dict:
        import desk
        import training
        found = training.run_checks(root)
        limited = [desk.plainly(reason) for reason in found['limitations']]
        return {'ready': found['ready'], 'limitations': limited,
                'blocking': [desk.plainly(reason) for reason in found['blocking']],
                'file': self.FILE}

    def write(self, root: Path, copies: list[dict] | None = None) -> dict:
        import workspace
        report = self.readiness(root, copies)
        lines = [f"# {workspace.load(root)['title']}", '',
                 'Ready.' if report['ready'] else 'Not ready yet.', '']
        lines += [f'- {reason}' for reason in report['blocking'] + report['limitations']]
        lines += [f"- {entry['label']}: {entry['link']}" for entry in copies or ()
                  if entry['state'] == 'made']
        (Path(root) / self.FILE).write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return report


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
        self.documents, self.copies, self.index = Documents(), Copies(), Index()
        patches = [
            mock.patch.dict(os.environ, {'TRAINING_STUDIO_DATA': str(self.base / 'data'),
                                         'GIT_CONFIG_GLOBAL': str(self.base / 'gitconfig'),
                                         'GIT_CONFIG_NOSYSTEM': '1'}),
            mock.patch.object(worker_tools, 'fetch_once', self.web.opener),
            mock.patch.object(worker_tools, 'resolve', self.web.resolver),
            # An engine made the ordinary way gets these too, so that no test can reach a
            # PDF reader, a converter or Google through the three real modules.
            mock.patch.multiple(engines, documents_kept=self.documents,
                                copies_made=self.copies, index_written=self.index)]
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
                   'documents': self.documents, 'copies': self.copies, 'index': self.index,
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
        for _ in range(60):
            waiting = workspace.status(root)['gate']
            self.assertIsNotNone(waiting, self.view(root))
            if waiting == gate:
                return
            self.decide(root, waiting)
        self.fail(f'{gate} never came up for review')

    def to_end(self, root: Path) -> list[str]:
        """Approve everything put to the person until nothing is, and say what that was."""
        import workspace
        approved = []
        for _ in range(60):
            waiting = workspace.status(root)['gate']
            if waiting is None:
                return approved
            self.decide(root, waiting)
            approved.append(waiting)
        self.fail('The training never stopped asking')

    def send(self, root: Path, name: str, text: str = 'Capacity holds only when more than '
             'one instance is running.\n') -> dict:
        """Add one of the person's documents, as the page does."""
        return self.engine.supply(root, 'add', name, text.encode('utf-8'))

    def git(self, *args: str, repo: Path | None = None) -> str:
        done = subprocess.run(['git', *args], cwd=repo or self.space.repo,
                              capture_output=True, text=True, check=True)
        return done.stdout.strip()

    def log(self) -> list[str]:
        """What each commit says happened, oldest first."""
        return self.git('log', '--reverse', '--format=%s').splitlines()

    def record(self, root: Path) -> dict:
        return json.loads((root / '.training-studio' / 'run.json').read_text())
