"""Whether this computer has what a training needs.

It asks each tool for its version, asks one for its sign-in, and opens a connection to each
assistant's service to see that this network lets it through. It runs only the commands
listed here and never starts an agent. Nothing a command prints about a sign-in is repeated.
"""
from __future__ import annotations

import re
import socket
import ssl
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

TIMEOUT = 8  # seconds any one command or connection may take
COMMANDS = {
    'claude': ('claude', '--version'),
    'codex': ('codex', '--version'),
    'codex-sign-in': ('codex', 'login', 'status'),
    'node': ('node', '--version'),
    'gcloud': ('gcloud', '--version'),
    'pandoc': ('pandoc', '--version'),
}
SERVICE = {'claude': 'api.anthropic.com', 'codex': 'chatgpt.com', 'codex-key': 'api.openai.com'}
SKILL_FOLDERS = {'Claude Code': ('.claude', 'skills'), 'Codex': ('.agents', 'skills')}
SKILLS = {
    'harness-research': 'Research cannot run without it.',
    'harness-slides': 'Without it everything is built except the slide deck.',
}
NODE_NEEDED = 20
VERSION = re.compile(r'\d+(?:\.\d+)+')


def run(command: tuple) -> dict:
    """Run one of the listed commands. Says whether it was found, whether it succeeded, and
    what it printed."""
    if command not in COMMANDS.values():
        raise ValueError(f'{command!r} is not a command the readiness check runs.')
    try:
        done = subprocess.run(list(command), capture_output=True, text=True, timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return {'found': False, 'ok': False, 'output': ''}
    except (OSError, subprocess.TimeoutExpired) as failure:
        return {'found': True, 'ok': False, 'output': type(failure).__name__}
    return {'found': True, 'ok': done.returncode == 0,
            'output': (done.stdout or done.stderr).strip()}


def reach(host: str) -> str | None:
    """Open a TLS connection to a service and close it. None if it opened, else why not.

    Nothing is sent: the handshake alone shows whether this network lets the service through,
    and whether something on the way is answering in its place.
    """
    try:
        with socket.create_connection((host, 443), timeout=TIMEOUT) as plain:
            with ssl.create_default_context().wrap_socket(plain, server_hostname=host):
                return None
    except ssl.SSLCertVerificationError:
        return ('something on this network answers in its place, so the connection cannot '
                'be trusted')
    except TimeoutError:
        return 'it did not answer in time'
    except OSError as failure:
        return f'the connection failed ({type(failure).__name__})'


def version(output: str) -> str:
    found = VERSION.search(output)
    return found.group(0) if found else ''


def fact(label: str, state: str, detail: str = '') -> dict:
    """One thing found out. `state` is ok, problem or unknown."""
    return {'label': label, 'state': state, 'detail': detail}


def assistant(ident: str, name: str, ran: dict, signed_in: dict | None, unreachable,
              host: str, sign_in: str) -> dict:
    """An assistant: installed, signed in where that can be asked, and reachable."""
    if not ran['found']:
        return item(ident, name, 'missing', [fact('Installed', 'problem', 'not found')],
                    f'Install {name}, then {sign_in}.')
    facts = [fact('Installed', 'ok' if ran['ok'] else 'problem', version(ran['output']))]
    fixes = [] if ran['ok'] else [f'{name} is installed but did not answer; reinstall it.']
    if signed_in is None:
        facts.append(fact('Signed in', 'unknown',
                          'cannot be asked without starting it; it says so itself when used'))
    elif signed_in['ok'] and 'not logged in' not in signed_in['output'].lower():
        facts.append(fact('Signed in', 'ok'))
    else:
        facts.append(fact('Signed in', 'problem', 'not signed in'))
        fixes.append(f'To sign in, {sign_in}.')
    if unreachable is None:
        facts.append(fact('Reachable from this network', 'ok', host))
    else:
        facts.append(fact('Reachable from this network', 'problem', f'{host}: {unreachable}'))
        fixes.append(f'This network does not let this computer reach {name}. Try another '
                     'network, or ask whoever runs this one.')
    return item(ident, name, 'problem' if fixes else 'ok', facts, ' '.join(fixes))


def item(ident: str, name: str, state: str, facts: list, fix: str = '',
         optional: bool = False) -> dict:
    """One line of the report. `state` is ok, missing or problem; `fix` is how to put it right."""
    return {'id': ident, 'name': name, 'state': state, 'facts': facts, 'fix': fix,
            'optional': optional}


def tool(ident: str, name: str, ran: dict, fix: str, optional: bool = False) -> dict:
    if ran['found'] and ran['ok']:
        return item(ident, name, 'ok', [fact('Installed', 'ok', version(ran['output']))],
                    optional=optional)
    found = 'did not answer' if ran['found'] else 'not found'
    return item(ident, name, 'problem' if ran['found'] else 'missing',
                [fact('Installed', 'problem', found)], fix, optional)


def skill(name: str, why: str, home: Path) -> dict:
    places = [harness for harness, parts in SKILL_FOLDERS.items()
              if home.joinpath(*parts, name).exists()]
    if places:
        return item(name, name, 'ok', [fact('Installed', 'ok', 'for ' + ' and '.join(places))])
    return item(name, name, 'missing', [fact('Installed', 'problem', 'not found')],
                f'{why} The Training Studio README says where to get it.')


def check(home: Path | None = None, google: bool = False) -> dict:
    """Look at this computer now. `google` says a training here keeps something in Google."""
    home = home or Path.home()
    with ThreadPoolExecutor(max_workers=8) as pool:
        ran = {key: pool.submit(run, command) for key, command in COMMANDS.items()}
        reached = {key: pool.submit(reach, host) for key, host in SERVICE.items()}
        ran = {key: pending.result() for key, pending in ran.items()}
        reached = {key: pending.result() for key, pending in reached.items()}
    codex_in = ran['codex-sign-in'] if ran['codex']['found'] else None
    # Codex talks to a different service when it is signed in with a key.
    keyed = bool(codex_in and codex_in['ok'] and 'api key' in codex_in['output'].lower())
    codex_host = 'codex-key' if keyed else 'codex'
    node = ran['node']
    major = version(node['output']).split('.')[0]
    if node['found'] and node['ok'] and major.isdigit() and int(major) < NODE_NEEDED:
        node = {**node, 'ok': False}
    items = [
        assistant('claude', 'Claude Code', ran['claude'], None, reached['claude'],
                  SERVICE['claude'], 'run `claude` in a terminal and follow its sign-in'),
        assistant('codex', 'Codex', ran['codex'], codex_in, reached[codex_host],
                  SERVICE[codex_host], 'run `codex login` in a terminal'),
        tool('node', 'Node', node, f'Install Node {NODE_NEEDED} or newer. The research and '
             'slide skills run on it.'),
        *(skill(name, why, home) for name, why in SKILLS.items()),
        tool('gcloud', 'Google Cloud CLI', ran['gcloud'],
             'Install the Google Cloud CLI, then run `gcloud auth login '
             '--enable-gdrive-access`. It is used only for Google Docs and Google Slides.',
             optional=not google),
        tool('pandoc', 'pandoc', ran['pandoc'],
             'Optional. Install pandoc if you want Word copies of guides and briefs.',
             optional=True),
    ]
    usable = [entry['name'] for entry in items[:2] if entry['state'] == 'ok']
    wrong = [entry['name'] for entry in items[2:]
             if entry['state'] != 'ok' and not entry['optional']]
    if not usable:
        wrong.insert(0, 'an assistant')
    return {'checked_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'ready': not wrong, 'assistants': usable, 'wrong': wrong, 'items': items}
