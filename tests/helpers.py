"""Shared test setup: import path, a temporary training directory, sample data."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Nothing a test does may touch the real per-user data folder.
_DATA = tempfile.TemporaryDirectory()
os.environ['TRAINING_STUDIO_DATA'] = _DATA.name

# After a commit, a fetch or a push, git starts auto-gc and maintenance in the background. That
# work can still be writing when a test's temporary directory is removed, which fails the
# removal. GIT_CONFIG_COUNT reaches every git a test starts itself, but for a push to a local
# path git drops it before it starts receive-pack, so the receiving repository never reads it.
# GIT_CONFIG_GLOBAL does reach receive-pack, so every gitconfig a test uses carries these too:
# the one below, and each one a test writes through gitconfig().
QUIET_GIT = {'maintenance.auto': 'false', 'gc.auto': '0', 'receive.autogc': 'false'}
for _index, (_key, _value) in enumerate(QUIET_GIT.items()):
    os.environ[f'GIT_CONFIG_KEY_{_index}'] = _key
    os.environ[f'GIT_CONFIG_VALUE_{_index}'] = _value
os.environ['GIT_CONFIG_COUNT'] = str(len(QUIET_GIT))


def gitconfig(path: Path, text: str = '') -> Path:
    """Write a gitconfig for GIT_CONFIG_GLOBAL to name: the text given, then the settings
    that keep git from working in the background."""
    quiet = ''.join(f'[{key.partition(".")[0]}]\n\t{key.partition(".")[2]} = {value}\n'
                    for key, value in QUIET_GIT.items())
    path.write_text(text + quiet, encoding='utf-8')
    return path


# A test that writes no gitconfig of its own uses this one, never the developer's.
_GIT = tempfile.TemporaryDirectory()
os.environ['GIT_CONFIG_GLOBAL'] = str(gitconfig(Path(_GIT.name) / 'gitconfig'))

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / 'skills' / 'training-studio'
SCRIPTS = SKILL / 'scripts'
EXAMPLES = SKILL / 'assets' / 'examples'
sys.path.insert(0, str(SCRIPTS))

CONTENT = {
    'blueprint': ('# Blueprint\n\n## Objectives\n### O1 — Recall a thing [recall]\n'
                  '### O2 — Explain a thing [explain]\n\n## M1 — Basics (20 min)\n'),
    'research-plan': '{"topic": "T", "items": []}\n',
    'deck': 'PK\x03\x04 deck v1\n',
}
DECK = CONTENT['deck']
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
PLAN = {
    'topic': 'Rolling restarts',
    'purpose': 'planning',
    'scope': 'public-web',
    'sources': [],
    'items': [dict(item, public_query=None, claim=None) for item in RESEARCH['items']],
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
        real = SKILL / 'assets' / 'profiles' / 'yoodli.json'
        self.profile.write_text(real.read_text(encoding='utf-8') if real.is_file()
                                else '{"revision": 1}\n', encoding='utf-8')
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


# What a stand-in for pandoc does once it has logged its arguments. Each is the body of a
# Python script; `arguments` holds what pandoc was given.
PANDOC_MAKES = ("target = Path(arguments[arguments.index('--output') + 1])\n"
                "target.write_bytes(b'docx of ' + Path(arguments[-1]).read_bytes())\n")
PANDOC_FAILS = ("sys.stderr.write('[WARNING] Could not fetch resource\\n'\n"
                "                 'pandoc: Could not parse ' + arguments[-1] + '\\n')\n"
                'sys.exit(64)\n')
PANDOC_WITHOUT_SANDBOX = ("if '--sandbox' in arguments:\n"
                          "    sys.stderr.write('Unknown option --sandbox.\\n')\n"
                          '    sys.exit(2)\n' + PANDOC_MAKES)
PANDOC_HANGS = 'time.sleep(30)\n'


def fake_pandoc(folder: Path, body: str = PANDOC_MAKES) -> Path:
    """A stand-in for pandoc in `folder`, to put first on PATH. It writes each call's
    arguments, as a JSON list, to calls.log beside it. No test needs pandoc installed."""
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / 'pandoc.py'
    script.write_text('import json, sys, time\nfrom pathlib import Path\n'
                      'arguments = sys.argv[1:]\n'
                      "with open(Path(__file__).with_name('calls.log'), 'a') as log:\n"
                      "    log.write(json.dumps(arguments) + '\\n')\n" + body, encoding='utf-8')
    launcher = folder / 'pandoc'
    launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n',
                        encoding='utf-8')
    launcher.chmod(0o755)
    return launcher


def pandoc_calls(folder: Path) -> list[list[str]]:
    """The arguments of every call made to the stand-in in `folder`."""
    import json
    log = folder / 'calls.log'
    return ([json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
            if log.is_file() else [])
