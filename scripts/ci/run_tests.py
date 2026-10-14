#!/usr/bin/env python3
"""Run the test suite in parallel: each test class in a process of its own, the slowest first.

Usage: run_tests.py [--jobs N] [--times] [NAME ...]

A NAME is what unittest takes: a module (test_hub), a class (test_hub.SyncTests) or one test.
With none, every class in tests/ is run. The output of a class is shown only when it fails.
Standard library only, like the helper; `python3 -m unittest discover -s tests` still works.
"""
import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / 'tests'

# The slowest classes, slowest first, as `--times` showed them. They are handed out before the
# rest, so that none of them is started last and left running alone. The rest go out by how
# many tests they have. A class missing from here is only handed out later.
SLOW = (
    'test_runner_team.DriverTests',
    'test_runner_deck.FlowTests',
    'test_runner_deck.RepairTests',
    'test_runner_flow.ToTheEndTests',
    'test_installer.CompanionTests',
    'test_runner_deck.TroubleTests',
    'test_runner_deck.PageTests',
    'test_runner_flow.WorkerTests',
    'test_runner_team.PublishTests',
    'test_runner_flow.DeckTests',
    'test_runner_deck_whole.WholeDeckTests',
    'test_installer.RunnerTests',
)

# What a worker runs: one class, with its counts written to the file it is given.
WORKER = """
import json, sys, unittest
import helpers
suite = unittest.defaultTestLoader.loadTestsFromName(sys.argv[1])
result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(suite)
counts = {'run': result.testsRun, 'failures': len(result.failures),
          'errors': len(result.errors), 'skipped': len(result.skipped),
          'unexpected': len(result.unexpectedSuccesses)}
with open(sys.argv[2], 'w', encoding='utf-8') as out:
    json.dump(counts, out)
"""


def real_git() -> str | None:
    """The folder of the real git on macOS, or None.

    /usr/bin/git there is a shim that asks xcrun for the real one on every call, which makes
    each call about three times as slow, and the suite starts some twenty thousand of them.
    The folder also holds Xcode's own python3; the workers are started with this Python.
    Only the shim is replaced: a git of the person's own choosing, such as Homebrew's, is kept.
    """
    if sys.platform != 'darwin' or shutil.which('git') != '/usr/bin/git' \
            or not shutil.which('xcrun'):
        return None
    try:
        found = subprocess.run(['xcrun', '--find', 'git'], capture_output=True, text=True,
                               timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    path = Path(found.stdout.strip())
    return str(path.parent) if found.returncode == 0 and path.is_file() else None


def shards(names: list[str]) -> tuple[dict[str, int], list[str]]:
    """Each class to run, with its number of tests, and why any module could not be loaded.

    A class is named by the module it is loaded from, as discover does, so a class that one
    module imports from another is run in both, and the total is the same as discover's.
    """
    loader = unittest.TestLoader()
    found, broken = {}, []
    for name in names:
        if '.' in name:
            found[name] = loader.loadTestsFromName(name).countTestCases()
    modules = ([name for name in names if '.' not in name] if names
               else sorted(path.stem for path in TESTS.glob('test*.py')))
    for module_name in modules:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            broken.append(f'{module_name}\n{traceback.format_exc()}')
            continue
        for name, value in vars(module).items():
            if isinstance(value, type) and issubclass(value, unittest.TestCase):
                tests = loader.loadTestsFromTestCase(value).countTestCases()
                if tests:
                    found[f'{module_name}.{name}'] = tests
    return found, broken


def order(found: dict[str, int]) -> list[str]:
    """The known slow classes first, then the rest by how many tests each has."""
    known = [name for name in SLOW if name in found]
    rest = sorted((name for name in found if name not in SLOW),
                  key=lambda name: (-found[name], name))
    return known + rest


def run(name: str, env: dict, holder: str) -> dict:
    """Run one class in a process of its own and return its counts, time and output."""
    record = Path(holder) / f'{name}.json'
    started = time.monotonic()
    done = subprocess.run([sys.executable, '-c', WORKER, name, str(record)], cwd=ROOT,
                          env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    took = time.monotonic() - started
    try:
        counts = json.loads(record.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        counts = {'run': 0, 'failures': 0, 'errors': 1, 'skipped': 0, 'unexpected': 0}
    failed = done.returncode != 0 or any(counts[key] for key in ('failures', 'errors',
                                                                 'unexpected'))
    return {'name': name, 'counts': counts, 'took': took, 'failed': failed,
            'output': done.stdout}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('names', nargs='*', help='modules, classes or tests (default: all)')
    jobs = getattr(os, 'process_cpu_count', os.cpu_count)() or 1
    parser.add_argument('-j', '--jobs', type=int, default=jobs,
                        help=f'how many classes to run at once (default: {jobs})')
    parser.add_argument('--times', action='store_true',
                        help='list every class with the time it took, slowest first')
    args = parser.parse_args(argv)

    # The workers get the environment as it is now; importing the tests below changes it.
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join(filter(None, [str(TESTS), env.get('PYTHONPATH')]))
    git = real_git()
    if git:
        env['PATH'] = os.pathsep.join([git, env.get('PATH', '')])
    sys.path.insert(0, str(TESTS))
    started = time.monotonic()
    found, broken = shards(args.names)
    queue = order(found)
    workers = max(1, min(args.jobs, len(queue)))
    print(f'{sum(found.values())} tests in {len(queue)} classes, {workers} at a time; '
          f'git: {shutil.which("git", path=env.get("PATH"))}', file=sys.stderr)

    results = []
    with tempfile.TemporaryDirectory() as holder, ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(run, name, env, holder) for name in queue]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print('F' if result['failed'] else '.', end='', file=sys.stderr, flush=True)
    print(file=sys.stderr)
    took = time.monotonic() - started

    failed = [result for result in results if result['failed']]
    for result in sorted(failed, key=lambda result: result['name']):
        print('=' * 70, f'\n{result["name"]}\n', '-' * 70, sep='', file=sys.stderr)
        print(result['output'].rstrip(), file=sys.stderr)
    for text in broken:
        print('=' * 70, f'\nCould not load {text.rstrip()}', sep='', file=sys.stderr)
    if args.times:
        print('-' * 70, file=sys.stderr)
        for result in sorted(results, key=lambda result: -result['took']):
            print(f'{result["took"]:8.1f}s  {result["name"]}', file=sys.stderr)

    total = {key: sum(result['counts'][key] for result in results)
             for key in ('run', 'failures', 'errors', 'skipped', 'unexpected')}
    total['errors'] += len(broken)
    print('-' * 70, file=sys.stderr)
    print(f'Ran {total["run"]} tests in {took:.3f}s\n', file=sys.stderr)
    notes = [f'{label}={total[key]}' for key, label in (
        ('failures', 'failures'), ('errors', 'errors'), ('skipped', 'skipped'),
        ('unexpected', 'unexpected successes')) if total[key]]
    failing = failed or broken or not results
    outcome = 'FAILED' if failing else 'OK'
    print(f'{outcome} ({", ".join(notes)})' if notes else outcome, file=sys.stderr)
    if failed:
        print('Failed: ' + ' '.join(sorted(result['name'] for result in failed)),
              file=sys.stderr)
    return 1 if failing else 0


if __name__ == '__main__':
    sys.exit(main())
