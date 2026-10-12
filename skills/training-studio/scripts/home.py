"""Where Training Studio keeps what belongs to this computer rather than to one training."""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

NAME = 'training-studio'


def data_root() -> Path:
    """The per-user data folder. TRAINING_STUDIO_DATA overrides it, for tests and odd setups."""
    override = os.environ.get('TRAINING_STUDIO_DATA')
    if override:
        return Path(override).expanduser()
    return Path.home() / '.local' / 'share' / NAME


def now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def read_json(path: Path, default):
    """A JSON file's content, or `default` if it is missing or unreadable."""
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def write_json(path: Path, value) -> None:
    """Write JSON so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f'.{path.name}.pending-{secrets.token_hex(4)}')
    try:
        pending.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)


# --- the registry of trainings on this computer ---------------------------------

def registry_path() -> Path:
    return data_root() / 'registry.json'


def remember(root: Path, title: str, levels: list[str]) -> None:
    """Note that a training lives at `root`. Never fails the command that calls it."""
    try:
        registry = read_json(registry_path(), {})
        trainings = registry.get('trainings') if isinstance(registry, dict) else None
        trainings = trainings if isinstance(trainings, dict) else {}
        trainings[str(root)] = {'title': title, 'levels': levels, 'seen_at': now()}
        write_json(registry_path(), {'schema': 1, 'trainings': trainings})
    except OSError:
        pass


def trainings() -> list[dict]:
    """Every remembered training whose directory still holds one, newest first."""
    registry = read_json(registry_path(), {})
    found = registry.get('trainings') if isinstance(registry, dict) else None
    listed = []
    for path, entry in (found or {}).items():
        if (Path(path) / f'.{NAME}' / 'session.json').is_file():
            listed.append({'path': path, **entry})
    return sorted(listed, key=lambda item: item.get('seen_at', ''), reverse=True)
