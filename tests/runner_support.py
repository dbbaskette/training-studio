"""Shared setup for the runner's tests: its import path, a job folder, a pretend web."""
import sys
import tempfile
import unittest
from pathlib import Path

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
