"""Shared test setup: import path, a temporary training directory, sample data."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / 'skills' / 'training-studio'
SCRIPTS = SKILL / 'scripts'
EXAMPLES = SKILL / 'assets' / 'examples'
sys.path.insert(0, str(SCRIPTS))

CONTENT = {
    'blueprint': ('# Blueprint\n\n## Objectives\n### O1 — Recall a thing [recall]\n'
                  '### O2 — Explain a thing [explain]\n\n## M1 — Basics (20 min)\n'),
    'research-plan': '{"topic": "T", "items": []}\n',
}
RESEARCH = {
    'schema': 1,
    'owner': 'harness-research',
    'run': 'run-1',
    'items': [
        {'id': 'availability', 'question': 'When does a rolling restart keep capacity?'},
        {'id': 'instance-min', 'question': 'How many instances are needed?'},
        {'id': 'health-checks', 'question': 'What starts the next batch?'},
        {'id': 'vendor-claim', 'question': 'Is zero downtime guaranteed?'},
        {'id': 'rollback', 'question': 'How is a failed restart rolled back?'},
        {'id': 'zero-downtime', 'question': 'Do rolling restarts guarantee zero downtime?'},
        {'id': 'other-platform', 'question': 'How does the alternative restart apps?'},
        {'id': 'licensing', 'question': 'How is each platform licensed?'},
    ],
    'results': {
        'availability': {'status': 'supported'},
        'instance-min': {'status': 'supported'},
        'health-checks': {'status': 'supported'},
        'vendor-claim': {'status': 'insufficient'},
        'zero-downtime': {'status': 'contradicted'},
        'other-platform': {'status': 'supported'},
        'licensing': {'status': 'supported'},
    },
    'inputs': {},
}
FINDINGS = {
    'availability': 'supported',
    'instance-min': 'supported',
    'health-checks': 'supported',
    'vendor-claim': 'insufficient',
    'rollback': 'pending',
    'zero-downtime': 'contradicted',
    'other-platform': 'supported',
    'licensing': 'supported',
}
CHAIN = ('intake', 'research-plan', 'research', 'blueprint', 'document')


class TrainingCase(unittest.TestCase):
    """A test with an empty training directory at self.root and a private Yoodli profile."""

    def setUp(self):
        import workspace
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        base = Path(holder.name).resolve()
        self.root = base / 'training'
        self.root.mkdir()
        self.profile = base / 'yoodli.json'
        self.profile.write_text('{"revision": 1}\n', encoding='utf-8')
        patcher = mock.patch.object(workspace, 'PROFILE', self.profile)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, relative: str, text: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def build(self, *names: str) -> None:
        """Write and save each named artifact, in order, as freshly built."""
        import workspace
        for name in names:
            session = workspace.load(self.root)
            content = CONTENT.get(name.partition('@')[0], f'{name} v1\n')
            self.write(workspace.artifact(self.root, session, name)['file'], content)
            workspace.save(self.root, name, built=True)

    def approved(self, *names: str) -> None:
        """Build and approve each named artifact, in order."""
        import workspace
        for name in names:
            self.build(name)
            workspace.approve(self.root, name)

    def state(self) -> dict:
        import workspace
        return workspace.statuses(self.root, workspace.load(self.root))
