"""Shared setup for the runner's tests: its import path, a job folder, a pretend web, and
an engine with scripted workers, the stand-in for harness-research, and small stand-ins
for the person's documents, the copies, the index, the slides tool and a brand skill
behind it."""
import hashlib
import json
import os
import re
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zlib
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


# --- processes a test started ------------------------------------------------------------

# A command that leaves a sleep behind holding its output open, writes its own process ID
# and the sleep's to the file it is given, and waits.
LEAVES = ('sleep 300 &\nprintf "%s\\n%s\\n" $$ $! > "$1.part" && mv "$1.part" "$1"\n'
          'sleep 300\n')


def gone(pid: int) -> bool:
    """True when a process has ended, whether or not anything has collected it yet."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    try:
        state = Path(f'/proc/{pid}/stat').read_text().rpartition(')')[2].split()[0]
    except (OSError, IndexError):
        return False
    return state == 'Z'


def still_running(pids, seconds: float = 5) -> list[int]:
    """Those of `pids` still running after up to `seconds`. Each is killed then, so that
    no test leaves a process behind whatever it finds."""
    deadline = time.monotonic() + seconds
    while True:
        left = [pid for pid in pids if not gone(pid)]
        if not left or time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    for pid in left:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    return left


def written(path: Path, seconds: float = 10) -> list[int]:
    """The process IDs a command writes to a file, one a line, once it has written them."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            text = path.read_text()
        except OSError:
            text = ''
        if text.endswith('\n'):
            return [int(line) for line in text.split()]
        time.sleep(0.02)
    raise AssertionError(f'Nothing was written to {path}.')


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
CHOSEN = {'brand': 'example-co', 'variant': 'light'}
NO_SLIDES = ('The slides tool is not on this computer. The Training Studio README says where '
             'to get it.')
NO_BRAND_SKILL = ('No brand skill is on this computer. A deck is made with one: install the '
                  'one your organisation uses.')
OUTLINE = {'version': 1, 'title': 'Rolling restarts', 'delivery': 'reading', 'minutes': 25, 'slides': [
    {'id': 'cover-restarts', 'kind': 'cover', 'title': 'Rolling restarts',
     'subtitle': 'What they do, and when capacity holds',
     'notes': '1 min. Welcome, and what is assumed.'},
    {'id': 'what-it-does', 'kind': 'content', 'relation': 'order', 'focal': 'One batch at a time',
     'title': 'A rolling restart replaces instances one batch at a time',
     'understand': 'Instances are replaced in batches while the app keeps serving.',
     'points': [{'label': 'Batch', 'text': 'Instances are replaced one batch at a time.'},
                {'label': 'Traffic', 'text': 'The app keeps serving while it restarts.'}],
     'source': 'Platform documentation: restarts',
     'notes': '6 min. Walk the three-instance example.', 'sources': ['O1']},
    {'id': 'when-capacity-holds', 'kind': 'content', 'relation': 'contrast',
     'focal': 'More than one instance',
     'title': 'Capacity holds only with more than one instance',
     'understand': 'A single instance has nothing to hold capacity while it restarts.',
     'points': [{'label': 'Several', 'text': 'The others carry the load.'},
                {'label': 'One', 'text': 'Requests are dropped while it restarts.'}],
     'caveat': 'A single-instance app still drops requests while it restarts.',
     'notes': '7 min. Health checks start the next batch.', 'sources': ['O2']},
    {'id': 'the-objection', 'kind': 'content', 'relation': 'contrast', 'rhythm': 'breathing',
     'focal': 'It depends on the instance count',
     'title': 'Rolling does not always mean zero downtime',
     'understand': 'The claim is true only for an app with several instances.',
     'points': [{'label': 'Claim', 'text': 'Rolling always means zero downtime.'},
                {'label': 'Correction', 'text': 'Only with more than one instance.'}],
     'notes': '7 min. Correct the claim without dismissing the customer.', 'sources': ['O3']},
    {'id': 'check-yourself', 'kind': 'content', 'relation': 'order', 'focal': 'Say it aloud',
     'title': 'Check what you can now explain',
     'understand': 'Each question tests one objective.',
     'points': [{'label': 'Describe', 'text': 'What happens to the instances?'},
                {'label': 'Explain', 'text': 'Why does one instance lose capacity?'}],
     'notes': '3 min. One question for each objective.', 'sources': ['O1', 'O2', 'O3']},
    {'id': 'closing-practice', 'kind': 'closing', 'title': 'Next: practise the objection',
     'notes': '1 min. Point to the practice scenario.'}]}


def designed(outline: dict, **slides) -> dict:
    """The design a worker hands in with an outline: a diagram for each content slide, the
    first with an icon still to be found, and direct text for each lead slide. `slides`
    replaces the entry of a slide, by its ID with dashes as underscores."""
    entries = []
    for slide in outline['slides']:
        content = slide.get('kind') == 'content'
        entry = {'id': slide['id'], 'intent': {
            'takeaway': slide['title'],
            'audienceQuestion': f"Why does it matter that {slide['title'].lower()}?",
            'relationship': slide.get('relation') or 'opening',
            'rationale': ('The parts and how they connect are spatial, so a diagram shows them.'
                          if content else 'A title slide names the subject and nothing else.'),
            'alternative': ({'treatment': 'A list of the points',
                             'reason': 'A list hides how the parts connect.'} if content else
                            {'treatment': 'A picture of a cluster',
                             'reason': 'It would decorate the title without explaining it.'}),
            'visual': {'family': 'diagram' if content else 'text',
                       'purpose': ('Show the points as the parts of one mechanism.'
                                   if content else 'Name the subject plainly.')}},
            'composition': ('Native boxes for each point, joined left to right, the focal '
                            'statement above them.' if content else
                            "The brand's own layout for this slide, with its words alone."),
            'asset': {'description': 'Native boxes and connectors.' if content else
                      'No asset.', 'disposition': 'selected' if content else 'not-needed',
                      'reason': ('The boxes carry the relation.' if content else
                                 'The words are the slide.')}}
        if content and not any(item.get('asset', {}).get('candidates') for item in entries):
            entry['asset']['candidates'] = [{'assetId': 'icon_instance', 'kind': 'icon',
                                             'ref': 'server', 'concept': 'An instance',
                                             'status': 'pending'}]
        entries.append(slides.get(slide['id'].replace('-', '_'), entry))
    return {'slides': entries}


def judgements(packets: list[dict], issues=()) -> list[dict]:
    """A reviewer's answer to a review against the design: a pass for every criterion of
    every slide, each with a reason of its own, except those `issues` gives, each as
    {'slide', 'criterion', 'severity', 'about', 'reason', 'fix'?}."""
    raised = {(issue['slide'], issue['criterion']): issue for issue in issues}
    made = []
    for packet in packets:
        prompt, checks = packet['slide'], []
        for criterion in prompt['criteria']:
            issue = raised.get((prompt['slide'], criterion['id']))
            cites = list(prompt.get('proseCards') or prompt['objects'])[:1]
            checks.append({'criterion': criterion['id'], 'status': 'pass',
                           'reason': f"On {prompt['slide']}, {criterion['id']} holds: "
                                     f"{prompt['title']}.", 'objects': cites}
                          if issue is None else {
                              'criterion': criterion['id'],
                              'status': issue.get('status', 'issue'), 'objects': cites,
                              **{key: issue[key] for key in ('severity', 'about', 'reason',
                                                             'fix') if key in issue}})
        made.append({'slide': prompt['slide'], 'checks': checks})
    return made


def left(sentence: str, *why: str) -> str:
    """What a training says when its deck is all that is left and cannot be made here.
    Without `why`, the computer has neither the slides tool nor a brand skill."""
    return sentence.format(why=' '.join(why or (NO_SLIDES, NO_BRAND_SKILL)))


def png(shade: int = 0) -> bytes:
    """A real PNG, one pixel across, in a shade of grey that tells one from another."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack('>I', len(data)) + kind + data
                + struct.pack('>I', zlib.crc32(kind + data)))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 0, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes([0, shade % 256]))) + chunk(b'IEND', b''))


def drawn(spec: dict, wording=None, placing=None) -> dict:
    """A section as a composer would hand it in: every approved word, plainly stacked, and
    each approved intent copied. `wording` changes a piece of text on its way to the slide,
    and `placing` adds nodes below the words of a slide, by its ID."""
    wording, slides = wording or (lambda text: text), []
    for slide in spec['slides']:
        stem = f"{spec['prefix']}{slide['id'].replace('-', '_')}"
        texts = [{'type': 'text', 'id': f'{stem}_{mark}{number}', 'text': wording(point[key]),
                  **({'textRole': 'label'} if key == 'label' else {})}
                 for number, point in enumerate(slide['points'], start=1)
                 for mark, key in (('h', 'label'), ('t', 'text'))]
        made = {'id': slide['id'], 'title': slide['title'], 'sources': slide['sources'],
                'brief': {'relation': 'order', 'focal': f'{stem}_t1', 'rhythm': 'anchor'},
                'canvas': {'type': 'stack', 'direction': 'column', 'children': [
                    *texts, *(placing or {}).get(slide['id'], ())]},
                'notes': slide['notes']}
        made.update({key: slide[key] for key in ('caveat', 'source') if slide[key]})
        made.update({'intent': json.loads(slide['intent'])} if 'intent' in slide else {})
        slides.append(made)
    return {'version': 1, 'title': spec['title'], 'direction': spec['direction'],
            'slides': slides}


FORM = {'title': 'Rolling restarts', 'topic': 'Rolling restarts on the platform',
        'audience': 'Solutions engineers who deploy apps', 'purpose': 'Field enablement',
        'levels': [], 'brief_kind': 'product', 'time_limit': '25 minutes',
        'source_scope': 'public-web', 'deck_target': None, 'brand': None, 'copies': [],
        'yoodli': False, 'agent': None, 'model': None, 'effort': None}


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
        self.outline_said = OUTLINE
        self.design_said = None     # the design handed in with it, when one is asked for
        self.placing = {}       # what a composer adds to a slide below its words, by slide ID
        self.found = []     # what each review in turn finds; nothing, once this runs out

    def then(self, kind: str, *acts) -> None:
        """Queue what the next jobs of one kind do: `research-plan`, `blueprint`,
        `document`, `brief`, `scenario`, `yoodli`, `outline`, `section`, `review`,
        `question`, or `question:<id>` for one research question."""
        self.queued.setdefault(kind, []).extend(acts)

    def of(self, kind: str) -> list:
        return [job for seen, job, spec in self.jobs if seen.partition(':')[0] == kind
                or seen == kind]

    def __call__(self, tools, job):
        from runner.agents import Outcome
        spec = tools.job
        kind = (f"question:{spec['finding']}" if spec['finding'] else
                'review' if spec.get('review') else next(iter(spec['artifacts'])))
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


    def outline(self, tools, job):
        said = json.dumps(self.outline_said)
        design = None if not tools.job['artifacts']['outline'].get('design') else json.dumps(
            self.design_said or designed(self.outline_said))
        checked = tools.check_outline(said, design)
        assert checked[1].startswith('Nothing to put right'), checked[1]
        accepted = tools.submit_outline(said, design)
        assert accepted[0], accepted[1]
        tools.submit_review('Six slides. The check slide is the one I am least sure of.')

    def section(self, tools, job):
        made = drawn(tools.job['artifacts']['section'], placing=self.placing)
        if tools.job['look']:  # drawn again after a review: never the same drawing twice
            made['slides'][0]['brief']['rhythm'] = f'drawn again, {len(self.jobs)}'
        made = json.dumps(made)
        shown = tools.preview_section(made)
        assert shown[0], shown[1]
        accepted = tools.submit_section(made, 'Nothing: it read well at once.',
                                        'The second slide is the weaker.')
        assert accepted[0], accepted[1]

    def review(self, tools, job):
        review = tools.job['review']
        for slide in review['slides']:
            looked = tools.look_at_slide(slide['number'])
            assert looked[0], looked[1]
        if review.get('judged'):   # against the design: every criterion of every slide
            accepted = tools.submit_judgements(judgements(
                review['judged']['packets'], self.found.pop(0) if self.found else []))
        else:
            accepted = tools.submit_assessment(self.found.pop(0) if self.found else [])
        assert accepted[0], accepted[1]
        objectives, most = review['objectives'], len(review['slides'])
        kept = tools.submit_coverage({objective: [min(number, most)] for number, objective
                                      in enumerate(objectives, start=2)}, 'One slide each.')
        assert kept[0], kept[1]


class Slides:
    """Stands in for the slides tool's wrapper, by the docstring of `runner.slides`. It
    writes what the tool writes, small: an outline's split into sections of two slides
    with the brief the tool writes for each, a scene, a deck that begins as a PowerPoint
    file does, and a real PNG for each slide. `refuse` maps a call to the lines it says
    no with. It takes no turn of its own at previewing, so `most` says how many previews
    were ever under way at once."""
    VERSION = '0.13.1'
    runtime = Path('/opt/slides-tool/versions/0.13.1')
    READING = {'design guidance': 'Design from the claim in the title.\n',
               'composition guidance': 'A canvas holds stacks, boxes and text.\n',
               'drafting guidance': 'One claim a slide.\n',
               'gallery': 'One drawn slide for each relation.\n',
               'example order': '{"brief": {"relation": "order"}}\n',
               'example contrast': '{"brief": {"relation": "contrast"}}\n'}
    LAYOUTS = [{'name': 'Closing words', 'title': False, 'subtitles': 0, 'pictures': 0},
               {'name': 'Picture and title', 'title': True, 'subtitles': 1, 'pictures': 1},
               {'name': 'Title slide', 'title': True, 'subtitles': 1, 'pictures': 0},
               {'name': 'Section divider', 'title': True, 'subtitles': 0, 'pictures': 0},
               {'name': 'Closing with title', 'title': True, 'subtitles': 0, 'pictures': 0}]

    def __init__(self):
        self.calls, self.refuse, self.findings, self.files = [], {}, {}, []
        # What the computer has beside this tool: LibreOffice, Google access that reaches
        # Drive, and the programs that turn a render into pictures.
        self.have = {'local': False, 'drive': True, 'pictures': True}
        self.budget, self.busy, self.most, self.counting = 90, 0, 0, threading.Lock()
        self.imported, self.took = [], 0.01
        # Whether this tool keeps a design session, as the one after 0.13.1 does, and the
        # answers it was sent. `gate` says whether it checks a section against the design:
        # None, as it keeps one. `keeps` says whether it keeps a deck's assets, played by
        # the stand-in's manifest: `env` is where it finds an image provider's key, and
        # `made` stands in for the provider.
        self.design, self.replies, self.gate = False, [], None
        self.keeps, self.env, self.made = False, {}, None
        # Whether it reviews a whole build against the approved design, played by the
        # stand-in's review, which renders with LibreOffice: `have['local']`.
        self.judges, self.rendered, self.assessed = False, 0, []
        # What it says it has in `version`, beyond the above: the names the runner asks
        # `has` about, each played as Harness Slides 0.14.1 has it. `lacking` is what it
        # says a new deck needs and it lacks: nothing unless a test says, so that a deck
        # the tests begin without a design stands for one begun before new decks needed
        # one, and carries on as it began.
        self.listed, self.lacking, self.presented, self.reviewed = set(), [], [], []

    def _asked(self, name: str, *given) -> None:
        from runner import slides
        self.calls.append((name, *(str(item) for item in given)))
        if name in self.refuse:
            raise slides.Refused(list(self.refuse[name]))

    def _new(self, path) -> Path:
        from runner import slides
        if Path(path).exists():
            raise slides.Refused([f'{Path(path).name} is already there. Give a new place.'])
        return Path(path)

    @staticmethod
    def _read(path) -> dict:
        return json.loads(Path(path).read_text(encoding='utf-8'))

    def version(self) -> str:
        return self.VERSION

    def capabilities(self):
        return frozenset(self.listed) if self.listed else None

    def has(self, name: str) -> bool:
        return name in self.listed

    def lacks(self) -> list[str]:
        return list(self.lacking)

    def reading(self, brand=None) -> dict:
        self._asked('reading')
        return dict(self.READING)

    def outline_contract(self, brand) -> str:
        self._asked('outline_contract', brand)
        return f'An outline is one JSON object. A slide holds at most {self.budget} words.\n'

    def compose_contract(self, brand) -> str:
        self._asked('compose_contract', brand)
        return 'A section is one JSON object. Its roles are label and body.\n'

    def layouts(self, brand) -> dict:
        self._asked('layouts', brand)
        return {'default': 'canvas', 'layouts': [dict(layout) for layout in self.LAYOUTS]}

    def outline_check(self, outline, brand) -> dict:
        self._asked('outline_check', outline, brand)
        slides = self._read(outline)['slides']
        found = [{'slide': slide['id'], 'code': 'no-notes', 'detail': 'It has no notes.'}
                 for slide in slides if not slide.get('notes')]
        words = {slide['id']: sum(len(f"{point['label']} {point['text']}".split())
                                  for point in slide.get('points') or ())
                 for slide in slides}
        found += [{'slide': ident, 'code': 'over-budget',
                   'detail': f'{count} words against {self.budget}.'}
                  for ident, count in words.items() if count > self.budget]
        return {'status': 'findings' if found else 'ok', 'slides': len(slides),
                'delivery': 'reading', 'wordBudget': self.budget, 'words': words,
                'findings': found}

    def outline_start(self, outline, brand, folder) -> dict:
        from runner import slides
        self._asked('outline_start', outline, brand, folder)
        whole, folder = self._read(outline), self._new(folder)
        named = {layout['name'] for layout in self.LAYOUTS}
        for slide in whole['slides']:
            wanted = (whole.get('layouts') or {}).get(slide['kind'])
            if slide['kind'] != 'content' and wanted not in named:
                raise slides.Refused([f"There is no layout for a {slide['kind']} slide."])
        if not whole.get('direction'):
            raise slides.Refused(['The outline has no direction.'])
        (folder / 'briefs').mkdir(parents=True)
        parts, run, leads = [], [], 0

        def section() -> None:
            number = sum(part.startswith('section') for part in parts) + 1
            parts.append(f'section-{number}.json')
            (folder / 'briefs' / f'section-{number}.md').write_text(
                self._brief(whole, number, list(run), brand, folder), encoding='utf-8')
            run.clear()

        for slide in whole['slides']:
            if slide['kind'] == 'content':
                run.append(slide)
                if len(run) == 2:
                    section()
                continue
            if run:
                section()
            leads += 1
            parts.append(f'lead-{leads}.json')
            lead = {key: slide[key] for key in ('id', 'title', 'subtitle', 'detail', 'notes')
                    if key in slide}
            (folder / parts[-1]).write_text(json.dumps({
                'version': 1, 'title': whole['title'], 'direction': whole['direction'],
                'slides': [{**lead, 'layout': whole['layouts'][slide['kind']],
                            'sources': ['outline'], 'brief': {'rhythm': 'anchor'}}]}))
        if run:
            section()
        (folder / 'outline.json').write_text(json.dumps(whole))
        (folder / 'parts.json').write_text(json.dumps({
            'title': whole['title'], 'direction': whole['direction'], 'parts': parts}))
        (folder / 'presentation-brief.md').write_text(f"# {whole['title']}\n")
        return {'output': str(folder), 'sections': len(parts) - leads}

    @staticmethod
    def _brief(whole: dict, number: int, slides: list, brand, folder: Path) -> str:
        """The brief the tool writes for one section, as it writes it."""
        lines = [f"# Section {number} of {whole['title']}", '',
                 'You are building one section of a deck. Other sections are being built at '
                 'the same time. Read `references/parallel-build.md`, the part headed "If '
                 'you are a worker", in the guidance for this task, and follow what it '
                 'tells you to read.', '', '## The deck', '',
                 f"{whole['title']}, delivered {whole.get('delivery')}. The user has "
                 'approved what each slide says. How each is drawn is yours to design.', '',
                 '## Paths', '', '- Runtime: `/opt/slides-tool/versions/0.13.0`',
                 f'- Brand contract: `{brand}`', f'- Work directory: `{folder}`',
                 f'- Write your section to `section-{number}.json`, and keep your builds '
                 f'and previews under `w{number}/`.', '', '## Direction, to copy unchanged',
                 '', '```json', json.dumps(whole['direction']), '```', '', '## House style',
                 '', 'None given beyond the direction.', '', '## Your slides, in order', '',
                 f'Prefix every node and edge ID you create with `s{number}_`. Slide IDs, '
                 'titles, wording and order are fixed.', '']
        for position, slide in enumerate(slides, start=1):
            lines += [f"{position}. **`{slide['id']}`: \"{slide['title']}\"**",
                      f"   - The audience must understand: {slide.get('understand')}"]
            lines += [f"   - {point['label']}: {point['text']}" for point in slide['points']]
            lines += [f"   - Sources: {json.dumps(slide['sources'])}", '']
        lines += ['## Preview', '', 'Use one Drive preview file of your own for every '
                  'preview, and say which it was.', '', '## Return', '',
                  'The section file, your final preview directory, the Drive file ID, what '
                  'you changed after looking, and what still bothers you.', '']
        return '\n'.join(lines)

    def _bound(self, slides: list, design, section: bool):
        """A build held to the design approved in `design`, by the design stand-in, which
        keeps the tool's rules. A refusal comes as JSON would."""
        from runner import slides as tool
        from stand_ins import design as designs
        if design is None:
            return None
        try:
            return designs.bound(slides, design, section, self.has('canonical-digests'))
        except (designs.Refusal, ValueError) as refused:
            found = designs.refusal(refused, designs.Session(design).revision())
            raise tool.Refused([problem['detail'] for problem in found['problems']], found)

    def compile(self, composition, brand, folder=None, design=None, section=False) -> dict:
        from runner import slides
        self._asked('compile', composition, brand, folder,
                    *([design, f'section={section}'] if design else []))
        made = self._read(composition)
        text = json.dumps(made)
        problems = [f"{slide.get('id')}: nothing is drawn." for slide in made.get('slides', [])
                    if 'canvas' not in slide and 'layout' not in slide]
        problems += ['A text does not fit: it needs 7 lines and has 4.'] \
            if 'TOO LONG TO FIT' in text else []
        uses, icons = {}, {}
        if self.keeps and design is not None:   # a picture is placed by its asset ID
            from stand_ins import assets as manifest
            _, uses, unresolved, icons = manifest.resolve(
                made, design, self.has('compose-icon-assets'))
            problems += unresolved
        if problems:
            raise slides.Refused(problems)
        approved = self._bound(made['slides'], design, section)
        report = {'sceneDigest': hashlib.sha256(text.encode()).hexdigest(),
                  'slides': len(made['slides']), 'room': {}}
        if folder is None:
            return {**report, 'status': 'compiles'}
        self._new(folder).mkdir(parents=True)
        structure = {'connectors': [], 'icons': [], 'layouts': [
            {'slide': slide['id'], 'layout': slide['layout']} for slide in made['slides']
            if 'layout' in slide]}
        (Path(folder) / 'scene.json').write_text(json.dumps({'title': made.get('title'), 'slides': [
            {**{key: slide.get(key) for key in ('id', 'title', 'sources', 'notes', 'intent')
                if key != 'intent' or key in slide},
             'elements': self._elements(slide, structure)} for slide in made['slides']],
            # Each picture is copied into the build, so what it is now is in the deck.
            **({'assets': {use['assetId']: use['sha256'] for use in uses.values()}}
               if uses else {})}))
        # What a review of the build reads beside its scene.
        (Path(folder) / 'structure.json').write_text(json.dumps(structure))
        (Path(folder) / 'brand-contract.json').write_text(Path(brand).read_text()
                                                          if Path(brand).is_file() else '{}')
        placed = [{'object': icon['id'], 'slide': icon['slide'], 'asset': mine['assetId'],
                   'kind': 'icon', 'ref': mine['ref'], 'sha256': mine['sha256']}
                  for icon in structure['icons'] for mine in [icons.get(icon['id'])] if mine]
        (Path(folder) / 'compose-report.json').write_text(json.dumps({
            'inputs': {'assets': placed}, **({'designRevision': approved['revision'],
                                          'designScope': approved['scope']}
                                         if approved else {})}))
        return {**report, 'output': str(folder)}

    @staticmethod
    def _elements(slide: dict, structure: dict) -> list[dict]:
        """What a slide draws, as a scene lists it: its title, then every node of its canvas
        that shows words, one under the other; its icons and edges go in its structure."""
        found = [{'id': f"{slide['id']}_title", 'type': 'text', 'role': 'title',
                  'text': slide.get('title'), 'x': 0, 'y': 0, 'width': 900, 'height': 40}]

        def walk(node) -> None:
            if isinstance(node, list):
                for item in node:
                    walk(item)
            elif isinstance(node, dict):
                if node.get('type') == 'icon':
                    structure['icons'].append({'slide': slide['id'], 'id': node.get('id'),
                                               'icon': node.get('icon')})
                elif isinstance(node.get('id'), str) and isinstance(node.get('text'), str):
                    found.append({'id': node['id'], 'type': 'shape' if node.get('type') == 'box'
                                  else 'text', 'text': node['text'], 'x': 0,
                                  'y': 40 * len(found), 'width': 900, 'height': 40})
                for value in node.values():
                    if isinstance(value, (dict, list)):
                        walk(value)

        walk(slide.get('canvas'))
        structure['connectors'] += [{'slide': slide['id'], 'id': edge.get('id'),
                                     'from': edge.get('from'), 'to': edge.get('to')}
                                    for edge in slide.get('connect') or ()]
        return found

    def merge(self, parts, composition) -> dict:
        self._asked('merge', parts, composition)
        listed = self._read(parts)
        slides = [slide for part in listed['parts']
                  for slide in self._read(Path(parts).parent / part)['slides']]
        self._new(composition).write_text(json.dumps({
            'version': 1, 'title': listed['title'], 'direction': listed['direction'],
            'slides': slides}))
        return {'output': str(composition), 'slides': len(slides)}

    def preview(self, compiled, folder, renderer, file_id=None, slide=None, design=None,
                section=False) -> dict:
        from runner import slides
        if design is not None:
            self._asked('preview_design', compiled, design, f'section={section}')
            self._bound(self._read(Path(compiled) / 'scene.json')['slides'], design, section)
        with self.counting:
            self.busy += 1
            self.most = max(self.most, self.busy)
        try:
            time.sleep(self.took)
            folder = self._new(folder)
            folder.mkdir(parents=True)
            scene = (Path(compiled) / 'scene.json').read_bytes()
            (folder / 'deck.pptx').write_bytes(b'PK\x03\x04' + scene)
            if 'preview' in self.refuse:  # as the real tool fails: after it wrote a file
                (folder / 'deck.pptx').unlink()
            self._asked('preview', compiled, folder, renderer, file_id)
            if renderer == 'drive' and file_id is None:
                self.files.append(f'file-{len(self.files) + 1}')
            shown = []
            for number, made in enumerate(json.loads(scene)['slides'], start=1):
                image = folder / f'slide-{number:02d}.png'
                image.write_bytes(png(number))
                shown.append({'id': made['id'], 'number': number, 'title': made['title'],
                              'image': str(image),
                              'findings': list(self.findings.get(made['id'], ()))})
            mine = file_id or (self.files[-1] if renderer == 'drive' else None)
            return {'deck': str(folder / 'deck.pptx'), 'renderer': renderer, 'fileId': mine,
                    'deckSha256': hashlib.sha256((folder / 'deck.pptx').read_bytes())
                    .hexdigest(), 'contactSheet': str(folder / 'contact-sheet.png'),
                    'url': f'https://docs.example.com/presentation/d/{mine}/edit' if mine
                    else None, 'slides': shown}
        finally:
            with self.counting:
                self.busy -= 1

    def critique(self, preview_folder, assessment) -> dict:
        from runner import slides
        self._asked('critique', preview_folder, assessment)
        given, folder = self._read(assessment), Path(preview_folder)
        problems = []
        if (folder / 'critique.json').exists():
            problems.append('This render already has a critique.')
        if given.get('deckSha256') != hashlib.sha256(
                (folder / 'deck.pptx').read_bytes()).hexdigest():
            problems.append('The assessment is of another render.')
        problems += [f"{finding.get('slide')}: the note is too short."
                     for finding in given['findings'] if len(finding.get('note', '')) < 12]
        problems += [f'{key} is not something a finding has.' for finding in given['findings']
                     for key in finding if key not in ('slide', 'question', 'severity',
                                                       'note', 'fix')]
        if problems:
            raise slides.Refused(problems)
        (folder / 'critique.json').write_text(json.dumps(given))
        counts = {grade: sum(finding['severity'] == grade for finding in given['findings'])
                  for grade in ('critical', 'major', 'minor')}
        return {**counts, 'status': 'blocked' if counts['critical'] else 'clear'}

    def render(self, compiled, deck) -> dict:
        self._asked('render', compiled, deck)
        self._new(deck).write_bytes(b'PK\x03\x04 rendered again')
        return {'output': str(deck)}

    def cited(self, compiled) -> dict:
        self._asked('cited', compiled)
        found: dict[str, list] = {}
        for number, slide in enumerate(self._read(Path(compiled) / 'scene.json')['slides'],
                                       start=1):
            for objective in slide.get('sources') or ():
                if objective != 'outline':
                    found.setdefault(objective, []).append(number)
        return found

    def drive_check(self) -> bool:
        self._asked('drive_check')
        return self.have['drive']

    def designs(self) -> bool:
        return self.design

    def sections(self) -> bool:
        return self.design if self.gate is None else self.gate

    def _session(self, name: str, project, act, *given):
        """A design command, played by the design stand-in, which keeps the tool's rules
        and writes the session where the tool does. A refusal comes as JSON would."""
        from runner import slides
        from stand_ins import design as designs
        self._asked(name, project, *given)
        session = designs.Session(project, self.listed)
        try:
            return act(session)
        except (designs.Refusal, ValueError) as refused:
            found = designs.refusal(refused, session.revision())
            raise slides.Refused([problem['detail'] for problem in found['problems']], found)

    def design_propose(self, project, proposal, expected=None, brand=None) -> dict:
        """With `brand`, an icon named by its library ID is held to Brand.ICONS."""
        return self._session('design_propose', project, lambda session: session.propose(
            self._read(proposal), expected, 'batch', Brand.ICONS if brand else None),
            proposal, *([f'brand={brand}'] if brand else []))

    def design_status(self, project) -> dict:
        return self._session('design_status', project, lambda session: session.status())

    def design_present(self, project, output, revision) -> dict:
        self.presented.append((str(project), str(output), revision))
        return self._session('design_present', project,
                             lambda session: session.present(output, revision), output)

    def design_check(self, project) -> dict:
        return self._session('design_check', project, lambda session: session.check())

    def design_respond(self, project, reply) -> dict:
        self.replies.append(dict(reply))
        return self._session('design_respond', project,
                             lambda session: session.respond(reply))

    def _manifest(self, name: str, act, *given):
        """An asset command, played by the stand-in's manifest, which keeps the tool's rules
        and writes where the tool does. A refusal comes as JSON would."""
        from runner import slides
        from stand_ins import assets as manifest
        from stand_ins import design as designs
        self._asked(name, *given)
        try:
            return act(manifest)
        except manifest.ImagesError as failed:
            refused = designs.Refusal(str(failed), manifest.images_problem(
                failed, 'gemini-api', given[1] if len(given) > 1 else None,
                given[2] if len(given) > 2 else None))
        except FileNotFoundError as missing:
            refused = designs.Refusal(f"ENOENT: no such file or directory, realpath "
                                      f"'{missing.filename}'")
        except (designs.Refusal, ValueError) as said:
            refused = said
        found = designs.refusal(refused, None)
        raise slides.Refused([problem['detail'] for problem in found['problems']], found)

    def assets(self) -> bool:
        return self.keeps

    def asset_status(self, project, design=None) -> dict:
        return self._manifest('asset_status', lambda kept: kept.status(
            project, design, self.env, self.has('assets-approved-candidates')), project,
            *([f'design={design}'] if design else []))

    def asset_check(self, project, brand=None, design=None) -> dict:
        """This file's small brand has no icon library: an icon is held to Brand.ICONS."""
        def act(kept):
            known = {entry['id']: entry for entry in Brand.ICONS}
            for entry in kept.read_manifest(Path(project).resolve())['assets']:
                if brand and entry['kind'] == 'icon' and entry['ref'] not in known:
                    from stand_ins import design as designs
                    raise designs.Refusal(f"{entry['assetId']}: unknown icon {entry['ref']}; "
                                          'search the brand icon library for a current ID',
                                          {'code': 'icon-unavailable',
                                           'asset': entry['assetId']})
            every = self.has('assets-approved-candidates')
            return kept.check(project, design, None, self.env, every,
                              Brand.ICONS if brand and every else None)
        return self._manifest('asset_check', act, project,
                              *([f'design={design}'] if design else []))

    def asset_icon(self, project, icon, ident, alt=None, brand=None) -> dict:
        def act(kept):
            known = {entry['id']: entry for entry in Brand.ICONS}
            if brand and (icon not in known or not known[icon]['native']):
                from stand_ins import design as designs
                raise designs.Refusal(f'{ident}: unknown icon {icon}; search the brand icon '
                                      'library for a current ID',
                                      {'code': 'icon-unavailable', 'asset': ident})
            return kept.record_icon(project, icon, ident, alt or (
                known.get(icon) or {}).get('name'))
        return self._manifest('asset_icon', act, project, ident, icon)

    def asset_supplied(self, project, file, ident, alt, source, kind='supplied',
                       restrictions=None) -> dict:
        return self._manifest('asset_supplied', lambda kept: kept.add_supplied(
            project, file, alt, source, restrictions, ident, kind), project, ident, file)

    def images_status(self) -> dict:
        return self._manifest('images_status', lambda kept: kept.images_status(self.env))

    def generate_image(self, project, ident, prompt, output, slide, alt=None) -> dict:
        from stand_ins import design as designs

        def act(kept):
            approved = designs.Session(project).check()['plan']
            if not any(made['id'] == slide and made['intent']['visual']['family']
                       == 'generated-art' for made in approved['slides']):
                raise designs.Refusal('Generate only the selected approved slide artwork')
            with tempfile.TemporaryDirectory() as folder:
                brief = Path(folder) / 'brief.txt'
                brief.write_text(prompt, encoding='utf-8')
                return kept.generate(project, ident, brief, output, alt, slide, self.env,
                                     self.made)
        return self._manifest('generate_image', act, project, ident, slide)

    def reviews(self) -> bool:
        return self.judges

    def _reviewing(self, name: str, output, act, *given):
        """A review command, played by the stand-in's review, which keeps the tool's rules
        and writes where the tool does. A refusal comes as JSON would."""
        from runner import slides
        from stand_ins import design as designs
        from stand_ins import review as reviewing
        self._asked(name, output, *given)

        def picture(slide, scene) -> bytes:
            return png(scene['slides'].index(slide) + 1)

        def written(path, scene) -> None:
            self.rendered += 1
            Path(path).write_bytes(b'PK\x03\x04' + json.dumps(scene).encode()
                                   + str(self.rendered).encode())

        def google(file_id, data, title) -> dict:
            if not self.have['drive']:
                raise designs.Refusal('Google Slides could not render the deck: Google API '
                                      'request failed (HTTP 403).',
                                      {'code': 'provider-failed', 'provider': 'google'})
            file_id = file_id or f'review-{len(self.reviewed) + 1}'
            self.reviewed.append(file_id)
            return {'fileId': file_id,
                    'url': f'https://docs.example.com/presentation/d/{file_id}/edit'}

        review = reviewing.Review(output, deck=written, picture=picture,
                                  screens=lambda scene, structure: [],
                                  local=self.have['local'], has=self.listed, google=google)
        try:
            return act(review)
        except (designs.Refusal, ValueError) as refused:
            found = designs.refusal(refused, None)
            raise slides.Refused([problem['detail'] for problem in found['problems']], found)

    def review_prepare(self, compiled, output, design, renderer=None, file_id=None) -> dict:
        through = 'google' if renderer == 'drive' else 'local'
        made = self._reviewing('review_prepare', output, lambda review: review.prepare(
            compiled, design, renderer=through, file_id=file_id), compiled,
            *([f'renderer={through}', f'file={file_id}'] if renderer == 'drive' else []))
        return {**made, 'fileId': made.get('fileId'), 'url': made.get('url')}

    def review_packets(self, output) -> dict:
        return self._reviewing('review_packets', output, lambda review: review.packets())

    def review_slide(self, output, slide) -> dict:
        return self._reviewing('review_slide', output, lambda review: review.inspect(slide),
                               slide)

    def review_mark(self, output, revision, numbers, note) -> dict:
        return self._reviewing('review_mark', output, lambda review: review.mark(
            revision, list(numbers), note), revision)

    def review_assess(self, output, revision, assessment) -> dict:
        self.assessed.append(assessment)
        return self._reviewing('review_assess', output,
                               lambda review: review.assess(revision, assessment), revision)

    def drive_import(self, deck, name) -> dict:
        self._asked('drive_import', deck, name)
        self.imported.append(Path(deck).read_bytes())
        ident = f'slides-{len(self.imported)}'
        return {'id': ident, 'name': name,
                'url': f'https://docs.example.com/presentation/d/{ident}/edit'}


class Brand:
    """Stands in for a brand skill's wrapper, by the docstring of `runner.brand`: one
    made-up brand in two variants, an export with the guide that says how the
    organisation is named, a few icons and an audit. `revision` is what the brand's
    sources are at now: change it, and a contract exported before no longer holds."""
    name = 'Example Co brand kit'
    runtime = Path('/opt/brand-kit')
    VOICE = ('# How Example Co is named\n\nWrite Example Co, in two words. Never ExampleCo, '
             'and never the Example Company.\n')
    ICONS = [{'id': 'icon-server', 'name': 'Server', 'category': 'Hardware', 'native': True},
             {'id': 'icon-clock', 'name': 'Clock', 'category': 'Time', 'native': True},
             {'id': 'icon-server-rack', 'name': 'Server rack', 'category': 'Hardware',
              'native': True},
             {'id': 'icon-server-photo', 'name': 'Server photo', 'category': 'Pictures',
              'native': False}]

    def __init__(self):
        self.revision, self.refuse, self.exports, self.audited = 1, {}, [], []
        self.warnings = [{'code': 'SMALL_TEXT', 'slide': 2, 'says': 'Text under 18 points.'},
                         {'code': 'SMALL_TEXT', 'slide': 3, 'says': 'Text under 18 points.'},
                         {'code': 'HIGH_TEXT_DENSITY', 'slide': 3,
                          'says': 'Many words for one slide.'}]

    def _asked(self, name: str) -> None:
        from runner import brand
        if name in self.refuse:
            raise brand.Refused(list(self.refuse[name]))

    def brands(self) -> list[dict]:
        return [{'brand': 'example-co', 'name': 'Example Co', 'variants': ['light', 'dark']}]

    def export(self, folder, brand_id, variant, delivery='reading') -> dict:
        from runner import brand
        self._asked('export')
        folder = Path(folder)
        if folder.exists():
            raise brand.Refused([f'{folder.name} is already there. Give a new folder.'])
        folder.mkdir(parents=True)
        (folder / 'brand-contract.json').write_text(json.dumps({
            'brand': brand_id, 'variant': variant, 'delivery': delivery,
            'revision': self.revision}))
        (folder / 'DESIGN.md').write_text('# How Example Co looks\n')
        (folder / 'VOICE.md').write_text(self.VOICE)
        self.exports.append((folder.name, brand_id, variant, delivery))
        return {'contract': str(folder / 'brand-contract.json'),
                'design': str(folder / 'DESIGN.md'), 'voice': str(folder / 'VOICE.md')}

    def contracts(self) -> bool:
        return 'contracts' not in self.refuse

    def check(self, contract) -> None:
        from runner import brand
        self._asked('check')
        if json.loads(Path(contract).read_text())['revision'] != self.revision:
            raise brand.Refused(["The brand's own files have changed since this was "
                                 'exported.'])

    def icons(self, words, limit=5) -> list[dict]:
        self._asked('icons')
        return [dict(icon) for icon in self.ICONS
                if all(word in icon['name'].lower() for word in words.lower().split())][:limit]

    def audit(self, deck, brand_id, variant) -> dict:
        self._asked('audit')
        self.audited.append((Path(deck).read_bytes(), brand_id, variant))
        return {'status': 'WARN' if self.warnings else 'PASS', 'blockers': [],
                'warnings': [dict(warning) for warning in self.warnings]}

    def ready(self) -> dict:
        return {'ready': True}


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
        import assess
        import desk
        found = assess.run_checks(root)
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


class Notifier:
    """Stands in for the computer's own notifications: `sent` lists each title told.
    `way` is the sentence it gives when a test says this computer has no way to notify."""

    def __init__(self):
        self.sent, self.way = [], None

    def can(self) -> tuple:
        return (self.way is None, self.way)

    def send(self, title: str) -> bool:
        if self.way is not None:
            return False
        self.sent.append(title)
        return True


class StudioCase(unittest.TestCase):
    """A person with a data folder and a git identity of their own, a workspace, scripted
    workers, a pretend web and the stand-in for harness-research. Nothing real is started
    and nothing leaves this computer."""

    BACKGROUND = False

    def setUp(self):
        from runner import engine as engines, gitstate
        from stand_ins import research as research_stand_in
        from runner.agents import Scripted
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.base = Path(holder.name).resolve()
        (self.base / 'no-templates').mkdir()
        helpers.gitconfig(
            self.base / 'gitconfig',
            '[user]\n\tname = Alex\n\temail = alex@example.com\n[init]\n\tdefaultBranch = '
            f"main\n\ttemplateDir = {self.base / 'no-templates'}\n")
        self.web = Web()
        self.web.page(URL, PAGE)
        self.documents, self.copies, self.index = Documents(), Copies(), Index()
        self.notifier = Notifier()
        # Nothing on this computer makes a deck until a test gives it the two stand-ins.
        self.slides, self.brand = None, None
        self.real = (engines.slides_tool.Slides, engines.brand_skill.Brand)
        patches = [
            mock.patch.dict(os.environ, {'TRAINING_STUDIO_DATA': str(self.base / 'data'),
                                         'GIT_CONFIG_GLOBAL': str(self.base / 'gitconfig'),
                                         'GIT_CONFIG_NOSYSTEM': '1'}),
            mock.patch.object(worker_tools, 'fetch_once', self.web.opener),
            mock.patch.object(worker_tools, 'resolve', self.web.resolver),
            # An engine made the ordinary way gets these too, so that no test can reach a
            # PDF reader, a converter or Google through the three real modules.
            mock.patch.multiple(engines, documents_kept=self.documents,
                                copies_made=self.copies, index_written=self.index),
            # The engine and a worker's tools both find the slides tool and a brand skill
            # through these two, so no test can reach a real one.
            mock.patch.object(engines.slides_tool, 'Slides', self.the_slides),
            mock.patch.object(engines.brand_skill, 'Brand', self.the_brand),
            # No test ever reaches the computer's own notifications.
            mock.patch.object(engines.team, 'Notifier', lambda *given, **named: self.notifier),
            mock.patch.object(engines.brand_skill, 'found', lambda: [] if self.brand is None
                              else [{'name': self.brand.name,
                                     'runtime': str(self.brand.runtime),
                                     'brands': self.brand.brands()}]),
            # The module's own look at this computer, asked about the programs a test
            # says are here and never about the ones that really are.
            mock.patch.object(engines.slides_tool, 'ready', lambda slides=None, which=None,
                              drive=True, look=engines.slides_tool.ready: look(
                                  slides, which=self.which, drive=drive))]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        for name in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE'):
            os.environ.pop(name, None)
        self.engines, self.gitstate = engines, gitstate
        self.research = research_stand_in.stand_in()
        self.workers = Workers()
        self.adapters = {'claude': Scripted(self.workers), 'codex': Scripted(self.workers)}
        self.space = self.set_up()
        self.engine = self.make()

    def which(self, program: str) -> str | None:
        """Where a program is, on the computer a test describes: Python always, and
        LibreOffice and the programs that make pictures as the slides stand-in says."""
        have = getattr(self.slides, 'have', None) or {
            'local': getattr(getattr(self.slides, 'run', None), 'local', False),
            'pictures': True}
        here = {'python3': True, 'soffice': have['local'], 'pdftoppm': have['pictures'],
                'pdfinfo': have['pictures']}
        return f'/usr/bin/{Path(program).name}' if here.get(Path(program).name) else None

    def stand_ins(self, design: bool = False, assets: bool = False,
                  current: bool = False) -> tuple:
        """The stand-ins in tests/stand_ins, which keep the rules of the real slides tool
        and of a real brand skill. Give them to `self.slides` and `self.brand`. With
        `design`, the slides tool is the one after 0.13.1, with its design session; with
        `assets`, the one that keeps a deck's assets too, and says so in `version`; with
        `current`, the 0.14.1 release."""
        from stand_ins import brand as brand_stand_in, slides as slides_stand_in
        tool, skill = self.real
        with mock.patch.object(self.engines.slides_tool, 'Slides', tool), \
                mock.patch.object(self.engines.brand_skill, 'Brand', skill):
            return (slides_stand_in.stand_in(design, assets, current),
                    brand_stand_in.stand_in())

    def the_slides(self, runtime=None, run=None):
        from workspace import WorkspaceError
        if self.slides is None:
            raise WorkspaceError(NO_SLIDES)
        return self.slides

    def the_brand(self, runtime=None, run=None):
        from workspace import WorkspaceError
        if self.brand is None:
            raise WorkspaceError(NO_BRAND_SKILL)
        return self.brand

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


class Person:
    """One of two people who share a workspace: a data folder, a git identity, a clone of
    the workspace and an engine of their own."""

    def __init__(self, name: str, env: dict):
        self.name, self.env = name, env
        self.space = self.engine = None


class TeamCase(StudioCase):
    """Two people on one computer, standing in for two: each has a data folder and a git
    identity, and both have joined one bare repository. `self.engine` is Alex's. Anything
    done as one of them is done inside `with self.be(person):`."""

    def set_up(self):
        self.remote = self.base / 'team-repo.git'
        self.remote.mkdir()
        self.git('init', '--quiet', '--bare', repo=self.remote)
        self.git('symbolic-ref', 'HEAD', 'refs/heads/main', repo=self.remote)
        return self.gitstate.join(str(self.remote))

    def setUp(self):
        super().setUp()
        self.alex = Person('Alex', {name: os.environ[name] for name in (
            'TRAINING_STUDIO_DATA', 'GIT_CONFIG_GLOBAL')})
        self.alex.space, self.alex.engine = self.space, self.engine
        with self.be(self.alex):
            self.engine.share()     # the workspace's own files, so a teammate finds them
        self.blake = self.person('Blake')

    def person(self, name: str) -> Person:
        """Someone else, who joins the same repository from a computer of their own."""
        folder = self.base / name.lower()
        folder.mkdir()
        helpers.gitconfig(
            folder / 'gitconfig',
            f'[user]\n\tname = {name}\n\temail = {name.lower()}@example.com\n[init]\n\t'
            f"defaultBranch = main\n\ttemplateDir = {self.base / 'no-templates'}\n")
        made = Person(name, {'TRAINING_STUDIO_DATA': str(folder / 'data'),
                             'GIT_CONFIG_GLOBAL': str(folder / 'gitconfig')})
        with self.be(made):
            made.space = self.gitstate.join(str(self.remote))
            made.engine = self.make()
        return made

    def be(self, person: Person):
        """Act as one of them: their data folder and their git identity."""
        return mock.patch.dict(os.environ, person.env)

    def as_(self, person: Person, action, *args, **named):
        with self.be(person):
            return action(*args, **named)

    def theirs(self, person: Person, root: Path) -> Path:
        """The same training in someone else's copy of the workspace."""
        return person.space.training(Path(root).name)

    def shared(self) -> list[str]:
        """What the team's repository has been sent, newest first."""
        if not self.git('for-each-ref', 'refs/heads/main', repo=self.remote):
            return []
        return self.git('log', '--format=%s', 'main', repo=self.remote).splitlines()

    def tags(self) -> list[str]:
        return self.git('tag', '--list', repo=self.remote).splitlines()
