"""The slides tool's asset manifest, for the stand-in: `assets add-supplied`, `icon`, `status`
and `check`, `images status` and `generate`, and the images a composition names by asset ID,
as Harness Slides has them after 0.13.1.

    add_supplied(project, file, alt, source, restrictions=None, ident=None, kind='supplied')
    record_icon(project, icon, ident=None, alt=None, brand=None)
    status(project, design=None, env=None)       # each asset with its state
    check(project, design=None, brand=None, env=None)
    images_status(env)                           # whether an image provider is set up
    generate(project, ident, prompt, output, alt=None, slide=None, env=None, made=None)
    resolve(comp, project)                       # (composition, uses, problem lines)
    place(scene, base, uses)                     # (inputs.assets, copies to write)
    verify(folder)                               # a build's copies, before it is rendered

It keeps the tool's own rules, messages and codes, ported from scripts/lib/assets.mjs,
images.mjs and refusals.mjs, and writes the manifest where the tool does. Where it is
simpler than the real thing:

- An image provider is set up when `env` holds GEMINI_API_KEY or GOOGLE_API_KEY, as for the
  tool's default provider, and nothing else is asked. Generating calls `made(prompt)` for
  the picture's bytes, a stub, and never the network; without `made` it draws a small PNG of
  its own. The tool's private receipts of a paid request are not kept: a request made again
  with the same brief finds its picture in the deck and returns it, and one with another
  brief is refused as the tool refuses it.
- A picture's size is read from its header: PNG, JPEG and GIF, as the tool takes them.
- With `design`, the candidates are read from `design status`, as the tool reads them. So,
  as in the tool, an approved design has no candidates to sort: status answers only the
  slides of the question waiting now.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import struct
import time
import uuid
import zlib
from pathlib import Path

from stand_ins import design as designs
from stand_ins.design import Refusal

MANIFEST = '.harness-slides/assets.json'
KINDS = ('icon', 'supplied', 'generated', 'screenshot', 'chart')
FILE_KINDS = ('supplied', 'screenshot', 'chart')
FORMATS = {'png': '.png', 'jpg': '.jpg', 'gif': '.gif'}
IDENT = re.compile(r'^\w[\w.:-]{0,127}$', re.ASCII)
ICON = re.compile(r'^[\w.-]+$', re.ASCII)
REQUEST = re.compile(r'^[a-zA-Z0-9_-]{1,80}$')
STATES = {'asset-file-missing': 'file-missing', 'asset-hash-changed': 'hash-changed',
          'input-invalid': 'invalid'}
KEYS = ('GOOGLE_API_KEY', 'GEMINI_API_KEY')
MODEL = 'gemini-nano-banana-2.1'
# What the tool says for each image provider error, and the code each becomes (images.mjs).
SAID = {
    'key_required': 'No Gemini API key is set. 1. Open https://aistudio.google.com/apikey and '
                    'choose Create API key. 2. Put it in the environment as GEMINI_API_KEY '
                    '(GOOGLE_API_KEY also works and wins if both are set). Never paste it into '
                    'chat. 3. Run images check.',
    'request_id_conflict': 'This ID already belongs to a different image request. Reuse its '
                           'original brief or explicitly choose a new ID.',
}
STEPS = ['Open https://aistudio.google.com/apikey and choose Create API key.',
         'Put it in the environment as GEMINI_API_KEY (GOOGLE_API_KEY also works and wins if '
         'both are set). Never paste it into chat.', 'Run images check.']
MISSING = ('key_required', 'setup_required', 'python_311_required', 'runtime_unavailable',
           'requires_macos_or_linux', 'auth_required')
FAILED = ('key_rejected', 'billing_required', 'model_unavailable', 'rate_limited',
          'api_refused', 'network_unavailable', 'no_image_returned',
          'expected_one_generated_image', 'generation_uncertain', 'download_failed',
          'operation_timeout', 'invalid_worker_response', 'runtime_setup_failed',
          'image_operation_failed', 'busy')


class ImagesError(Refusal):
    """An image provider's error: its code, and the sentence the tool says for it."""

    def __init__(self, code: str):
        super().__init__(SAID.get(code, f'Image operation failed ({code}).'))
        self.code = code


def images_problem(error: ImagesError, provider: str = 'gemini-api', asset=None,
                   slide=None) -> dict:
    """imageProblem: setup the caller lacks is provider-missing, a provider that answered
    badly is provider-failed, and its message is the next step."""
    code = ('provider-missing' if error.code in MISSING else 'provider-failed'
            if error.code in FAILED else 'output-exists' if error.code == 'output_exists'
            else 'input-invalid')
    return {'code': code, 'provider': provider, 'asset': asset, 'slide': slide,
            'next': str(error), **({'recoverable': False}
                                   if error.code == 'generation_uncertain' else {})}


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text(value) -> bool:
    return isinstance(value, str) and value.strip() != '' and len(value) <= 2000


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _stringify(value) -> str:
    return json.dumps(value, separators=(',', ':'), ensure_ascii=False)


def _file_name(ident: str) -> str:
    return ident.replace(':', '_')


def api_key(env) -> str | None:
    """The variable an API key is set in, GOOGLE_API_KEY first, or None."""
    env = os.environ if env is None else env
    return next((name for name in KEYS if str(env.get(name) or '').strip()), None)


def image_info(data: bytes) -> dict | None:
    """{'format', 'width', 'height'} of a PNG, JPEG or GIF, read from its header."""
    if data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) >= 24:
        width, height = struct.unpack('>II', data[16:24])
        return {'format': 'png', 'width': width, 'height': height} if width and height \
            else None
    if data[:6] in (b'GIF87a', b'GIF89a') and len(data) >= 10:
        width, height = struct.unpack('<HH', data[6:10])
        return {'format': 'gif', 'width': width, 'height': height} if width and height \
            else None
    if data[:2] == b'\xff\xd8':
        at = 2
        while at + 9 < len(data):
            if data[at] != 0xFF:
                return None
            marker, size = data[at + 1], struct.unpack('>H', data[at + 2:at + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD,
                          0xCE, 0xCF):
                height, width = struct.unpack('>HH', data[at + 5:at + 9])
                return {'format': 'jpg', 'width': width, 'height': height} \
                    if width and height else None
            at += 2 + size
    return None


def png(width: int = 16, height: int = 9, shade: int = 90) -> bytes:
    """A small grey PNG: what the stub provider draws."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack('>I', len(data)) + kind + data
                + struct.pack('>I', zlib.crc32(kind + data)))
    rows = b''.join(b'\x00' + bytes([shade % 256]) * width for _ in range(height))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


# --- the project and its manifest ----------------------------------------------------------

def _root(project) -> Path:
    if not project:
        raise Refusal('Provide --project DIR, the project that holds the asset manifest')
    path = Path(os.path.abspath(project))
    if not path.exists():
        raise Refusal(f'No project directory at {project}', {'code': 'input-missing'})
    path = path.resolve()
    if not path.is_dir():
        raise Refusal(f'{project} is not a directory', {'code': 'input-invalid'})
    return path


def _relative_ok(path) -> bool:
    return isinstance(path, str) and path != '' and not os.path.isabs(path) \
        and '\\' not in path and all(part and part not in ('.', '..')
                                     for part in path.split('/'))


def _validate(manifest) -> dict:
    def bad(detail: str) -> Refusal:
        return Refusal(f'The asset manifest {MANIFEST} is not valid: {detail}. Restore it, or '
                       'record the assets again', {
                           'code': 'input-invalid', 'next': 'Restore .harness-slides/assets.json, '
                           'or remove it and record the assets again'})
    if not isinstance(manifest, dict) or manifest.get('schema') != 1 \
            or manifest.get('tool') != 'harness-slides-assets' \
            or not isinstance(manifest.get('assets'), list):
        raise bad('it is not a Harness Slides asset manifest')
    seen = set()
    for entry in manifest['assets']:
        ident = entry.get('assetId') if isinstance(entry, dict) else None
        if not isinstance(ident, str) or not IDENT.match(ident) or ident in seen \
                or entry.get('kind') not in KINDS:
            raise bad(f'entry {ident if ident is not None else "undefined"} needs a unique '
                      'asset ID and a known kind')
        seen.add(ident)
        if entry['kind'] != 'icon' and not _relative_ok(entry.get('path')):
            raise bad(f"{ident} has a path outside the project ({entry.get('path')})")
        if entry['kind'] == 'generated' and not _relative_ok(
                (entry.get('provenance') or {}).get('metadata')):
            raise bad(f'{ident} has a metadata path outside the project')
    return manifest


def _inside(base: Path, relative: str) -> Path:
    """regularInside: a regular file inside the project, links refused."""
    path = Path(os.path.normpath(base / relative))
    if base != path and base not in path.parents:
        raise Refusal('Path must stay inside the workspace')
    if not path.exists() and not path.is_symlink():
        raise FileNotFoundError(path)
    if path.is_symlink() or not path.is_file():
        raise Refusal('Expected a regular workspace file')
    if base.resolve() not in path.resolve().parents:
        raise Refusal('Path must stay inside the workspace')
    return path


def read_manifest(base: Path) -> dict:
    try:
        data = _inside(base, MANIFEST).read_text(encoding='utf-8')
    except FileNotFoundError:
        return {'schema': 1, 'tool': 'harness-slides-assets', 'assets': []}
    except Refusal as wrong:
        raise Refusal(f'The asset manifest must be a regular file inside the project ({wrong})',
                      {'code': 'input-invalid'})
    try:
        return _validate(json.loads(data))
    except ValueError as wrong:
        if isinstance(wrong, Refusal):
            raise
        raise Refusal(f'The asset manifest {MANIFEST} is not JSON', {'code': 'input-invalid'})


def _update(base: Path, change) -> dict:
    """One writer at a time; a second waits briefly, then is told what holds it."""
    folder = base / '.harness-slides'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if folder.is_symlink() or not folder.is_dir():
        raise Refusal('.harness-slides must be a real directory', {'code': 'input-invalid'})
    lock, tries = folder / 'assets.lock', 0
    while True:
        try:
            os.close(os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
            break
        except FileExistsError:
            if tries >= 60:
                raise Refusal('Another asset command holds .harness-slides/assets.lock',
                              {'code': 'assets-busy'})
            tries += 1
            time.sleep(0.05)
    try:
        manifest = read_manifest(base)
        result = change(manifest)
        if result['status'] != 'unchanged':
            temporary = folder / f'{uuid.uuid4()}.tmp'
            try:
                temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n',
                                     encoding='utf-8')
                temporary.replace(base / MANIFEST)
            finally:
                temporary.unlink(missing_ok=True)
        return {**result, 'manifest': MANIFEST}
    finally:
        lock.unlink(missing_ok=True)


def _put(manifest: dict, entry: dict) -> str:
    """Keeps the recorded time when nothing else changed, so a repeat says it is unchanged."""
    found = next((at for at, item in enumerate(manifest['assets'])
                  if item['assetId'] == entry['assetId']), None)
    if found is not None and _stringify({**manifest['assets'][found], 'recorded': 0}) \
            == _stringify({**entry, 'recorded': 0}):
        return 'unchanged'
    if found is None:
        manifest['assets'].append(entry)
        return 'recorded'
    manifest['assets'][found] = entry
    return 'updated'


def _conflict(ident: str, detail: str) -> Refusal:
    return Refusal(f'Asset {ident} is already recorded {detail}; choose a new --id',
                   {'code': 'asset-conflict', 'asset': ident})


def _within(base: Path, path: Path) -> str | None:
    """A path relative to the project with '/', or None when it lies outside."""
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return None


# --- recording -----------------------------------------------------------------------------

def add_supplied(project, file, alt, source, restrictions=None, ident=None,
                 kind='supplied') -> dict:
    if not file:
        raise Refusal('Provide the image file: assets add-supplied FILE --project DIR --alt '
                      'TEXT --source TEXT')
    if not _text(alt) or not _text(source):
        raise Refusal('Provide --alt with what the image shows and --source with where it '
                      'came from')
    if restrictions is not None and not _text(restrictions):
        raise Refusal('--restrictions is a sentence, or omitted')
    if kind not in FILE_KINDS:
        raise Refusal(f"--kind is one of {'|'.join(FILE_KINDS)}")
    base = _root(project)
    real = Path(os.path.abspath(file)).resolve(strict=True)
    data = real.read_bytes()
    info = image_info(data)
    if not info:
        raise Refusal(f'{file} is not a PNG, JPEG or GIF image', {'code': 'input-invalid'})
    asset = ident if ident is not None else re.sub(r'^[^\w]+', '', re.sub(
        r'[^\w.-]+', '-', real.stem, flags=re.ASCII), flags=re.ASCII)[:128]
    if not IDENT.match(asset):
        raise Refusal(f'Asset ID {asset} needs letters, digits, _ . : or -, starting with a '
                      'letter, digit or _', {'code': 'input-invalid'})
    within = _within(base, real)
    inside = within is not None and not within.startswith('.harness-slides/')
    path = within if inside else f"assets/supplied/{_file_name(asset)}{FORMATS[info['format']]}"
    sha256 = _hash(data)

    def change(manifest: dict) -> dict:
        before = next((item for item in manifest['assets'] if item['assetId'] == asset), None)
        if before and (before['kind'] != kind or before.get('path') != path
                       or not inside and before.get('sha256') != sha256):
            raise _conflict(asset, 'with different bytes' if before.get('path') == path
                            else f"for {before.get('path') or before.get('ref')}")
        if not inside:
            target = base.joinpath(*path.split('/'))
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            here = target.parent
            while here != base:
                if here.is_symlink():
                    raise Refusal(f'{_within(base, here)} is a link; managed assets stay in '
                                  'real directories', {'code': 'input-invalid'})
                here = here.parent
            try:
                with open(target, 'xb') as written:
                    written.write(data)
            except FileExistsError:
                if _hash(_inside(base, path).read_bytes()) != sha256:
                    raise _conflict(asset, f': {path} already holds a different file')
        entry = {'assetId': asset, 'kind': kind, 'path': path, 'sha256': sha256, 'alt': alt,
                 'source': source, 'restrictions': restrictions if restrictions is not None
                 else (before or {}).get('restrictions'), **info, 'ref': None,
                 'provenance': None, 'recorded': _now()}
        return {'status': _put(manifest, entry), 'assetId': asset, 'kind': kind, 'path': path,
                'sha256': sha256}
    return _update(base, change)


def _index(brand) -> tuple[dict, list[dict]]:
    """A checked brand contract and its icon index's entries."""
    from stand_ins import slides
    contract = slides.StandIn.contract(brand)
    library = (contract['design']['slides'].get('icon') or {}).get('library') or {}
    return contract, json.loads(Path(library['index']).read_text(encoding='utf-8'))['entries']


def _library_entry(contract: dict, entries: list[dict], icon: str, asset: str) -> dict:
    """The entry of a native icon in the brand's hashed library (checkIcons), with the hash of
    the index it came from."""
    library = (contract['design']['slides'].get('icon') or {}).get('library') or {}
    hashed = {source['path']: source['sha256'] for source in contract['sources']}
    if library.get('path') not in hashed or library.get('index') not in hashed:
        raise Refusal('This composition uses icons, but the brand contract names no hashed '
                      'icon library and index', {'code': 'icon-unavailable', 'asset': asset})
    entry = next((item for item in entries if item.get('id') == icon), None)
    if entry is None:
        wrong = f'{asset}: unknown icon {icon}; search the brand icon library for a current ID'
    elif not entry.get('native') or not ((entry.get('bounds') or [0] * 4)[2] > 0
                                         and (entry.get('bounds') or [0] * 4)[3] > 0):
        wrong = f'{asset}: icon {icon} is a picture, not native geometry; choose another'
    elif isinstance(entry.get('shapeIds'), list) and len(entry['shapeIds']) < 2:
        wrong = (f'{asset}: icon {icon} has no drawing in the library index, only its disc; '
                 'choose another')
    else:
        return {'entry': entry, 'indexSha256': hashed[library['index']]}
    raise Refusal(wrong, {'code': 'icon-unavailable', 'asset': asset})


def record_icon(project, icon, ident=None, alt=None, brand=None) -> dict:
    if not icon or len(icon) > 80 or not ICON.match(icon):
        raise Refusal('Provide the stable icon ID from the brand icon search: assets icon '
                      'ICON_ID --project DIR')
    if alt is not None and not _text(alt):
        raise Refusal('--alt is a short description, or omitted')
    asset = ident if ident is not None else icon
    if not IDENT.match(asset):
        raise Refusal(f'Asset ID {asset} needs letters, digits, _ . : or -',
                      {'code': 'input-invalid'})
    base = _root(project)
    found = provenance = sha256 = None
    if brand:
        contract, entries = _index(brand)
        found = _library_entry(contract, entries, icon, asset)
        sha256 = _hash(_stringify(found['entry']).encode('utf-8'))
        provenance = {'brandRevision': contract.get('revision'),
                      'brand': (contract.get('identity') or {}).get('id'),
                      'label': found['entry'].get('label'),
                      'indexSha256': found['indexSha256']}
    label = alt if alt is not None else (found['entry'].get('label') if found else None)

    def change(manifest: dict) -> dict:
        before = next((item for item in manifest['assets'] if item['assetId'] == asset), None)
        if before and (before['kind'] != 'icon' or before.get('ref') != icon):
            raise _conflict(asset, f"for {before.get('ref') or before.get('path')}")
        before = before or {}
        entry = {'assetId': asset, 'kind': 'icon', 'path': None,
                 'sha256': sha256 if sha256 is not None else before.get('sha256'),
                 'alt': label if label is not None else before.get('alt'),
                 'source': (f"Brand icon library ({provenance['brand']})" if provenance
                            else before.get('source')
                            or 'Brand icon library; not checked against a brand'),
                 'restrictions': before.get('restrictions'), 'ref': icon,
                 'provenance': provenance or before.get('provenance'), 'recorded': _now()}
        return {'status': _put(manifest, entry), 'assetId': asset, 'kind': 'icon', 'ref': icon,
                'alt': entry['alt'], 'checked': bool(provenance)}
    return _update(base, change)


def register_generated(project, result: dict, alt=None, slide=None) -> dict:
    """images generate records the picture it made, under its request ID."""
    base = _root(project)

    def local(path) -> str:
        within = _within(base, Path(path).resolve())
        if within is None:
            raise Refusal(f'{path} is outside the project', {'code': 'input-invalid'})
        return within

    path, metadata = local(result['path']), local(result['metadata'])
    data, sidecar = Path(result['path']).read_bytes(), Path(result['metadata']).read_bytes()
    made = json.loads(sidecar)
    if _hash(data) != result['sha256'] or made.get('sha256') != result['sha256']:
        raise Refusal(f'{path} does not match its sidecar',
                      {'code': 'asset-hash-changed', 'asset': result['id']})
    if alt is not None and not _text(alt):
        raise Refusal('--alt is a short description, or omitted')

    def change(manifest: dict) -> dict:
        before = next((item for item in manifest['assets']
                       if item['assetId'] == result['id']), None)
        if before and (before['kind'] != 'generated' or before.get('path') != path
                       or before.get('sha256') != result['sha256']):
            raise _conflict(result['id'], f"for {before.get('path') or before.get('ref')}")
        before = before or {}
        entry = {'assetId': result['id'], 'kind': 'generated', 'path': path,
                 'sha256': result['sha256'],
                 'alt': alt if alt is not None else before.get('alt'),
                 'source': f"Generated by {made['provider']}"
                           + (f" ({made['model']})" if made.get('model') else '')
                           + f", request {made['requestId']}",
                 'restrictions': before.get('restrictions'),
                 'format': made.get('format') or Path(path).suffix[1:],
                 'width': result.get('width') or made.get('width'),
                 'height': result.get('height') or made.get('height'), 'ref': None,
                 'provenance': {'provider': made['provider'], 'model': made.get('model'),
                                'requestId': made['requestId'], 'created': made.get('created'),
                                'promptSha256': made.get('promptSha256'),
                                'metadata': metadata, 'metadataSha256': _hash(sidecar),
                                'slide': slide if slide is not None
                                else (before.get('provenance') or {}).get('slide')},
                 'recorded': _now()}
        return {'status': _put(manifest, entry), 'assetId': result['id']}
    return _update(base, change)


# --- what is recorded, and what is wrong with it -------------------------------------------

def _problem_of(base: Path, entry: dict) -> dict | None:
    """What is wrong with one recorded asset now, or None. Read-only."""
    def file(path: str, what: str) -> dict:
        try:
            return {'bytes': _inside(base, path).read_bytes()}
        except FileNotFoundError:
            return {'code': 'asset-file-missing', 'detail': f"Asset {entry['assetId']}: "
                    f'{what} {path} is missing from the project'}
        except Refusal:
            return {'code': 'input-invalid', 'detail': f"Asset {entry['assetId']}: {path} "
                    'must be a regular file inside the project'}

    if entry['kind'] == 'icon':
        return None
    found = file(entry['path'], 'file')
    if found.get('code'):
        return {**found, 'asset': entry['assetId']}
    if _hash(found['bytes']) != entry.get('sha256'):
        return {'code': 'asset-hash-changed', 'asset': entry['assetId'],
                'detail': f"Asset {entry['assetId']}: {entry['path']} changed since it was "
                          'recorded'}
    if entry['kind'] == 'generated':
        metadata = entry['provenance']['metadata']
        found = file(metadata, 'sidecar')
        if found.get('code'):
            return {**found, 'asset': entry['assetId']}
        if _hash(found['bytes']) != entry['provenance'].get('metadataSha256'):
            return {'code': 'asset-hash-changed', 'asset': entry['assetId'],
                    'detail': f"Asset {entry['assetId']}: its sidecar {metadata} changed since "
                              'it was recorded'}
    return None


def _candidates(manifest: dict, design, env) -> tuple[list, list, list]:
    """Design candidates matched to the manifest by asset ID. Those missing are pending;
    generated art also needs a provider. Read from `design status`, as the tool reads them."""
    plan = designs.Session(design).status()
    resolved, pending, problems = [], [], []
    for slide in plan['slides']:
        for candidate in (slide.get('asset') or {}).get('candidates') or []:
            entry = next((item for item in manifest['assets']
                          if item['assetId'] == candidate['assetId']), None)
            item = {'slide': slide['id'], 'assetId': candidate['assetId'],
                    'kind': candidate['kind'], 'concept': candidate['concept']}
            if entry and entry['kind'] != candidate['kind']:
                problems.append({
                    'code': 'asset-conflict', 'slide': slide['id'], 'asset': candidate['assetId'],
                    'detail': f"{slide['id']}: candidate {candidate['assetId']} is a "
                              f"{candidate['kind']}, but the manifest records a {entry['kind']}",
                    'next': "Record the candidate under its own asset ID, or correct the "
                            "candidate's kind in the proposal"})
                pending.append(item)
                continue
            if entry:
                resolved.append(item)
                continue
            pending.append(item)
            if candidate['kind'] == 'generated' and not api_key(env):
                problems.append({
                    'code': 'provider-missing', 'slide': slide['id'],
                    'asset': candidate['assetId'], 'provider': 'gemini-api',
                    'detail': f"{slide['id']}: candidate {candidate['assetId']} is generated "
                              'art, and no Gemini API key is set to generate it'})
            else:
                then = {'icon': f"Record it with assets icon ICON_ID --id {candidate['assetId']}",
                        'generated': 'Generate it with images generate once its slide is '
                                     'approved'}.get(candidate['kind'],
                                                     'Record it with assets add-supplied FILE '
                                                     f"--id {candidate['assetId']}")
                problems.append({
                    'code': 'asset-unresolved', 'slide': slide['id'],
                    'asset': candidate['assetId'],
                    'detail': f"{slide['id']}: candidate {candidate['assetId']} "
                              f"({candidate['kind']}, {candidate['concept']}) is not in the "
                              "project's asset manifest", 'next': then})
    return resolved, pending, problems


def status(project, design=None, env=None) -> dict:
    base = _root(project)
    manifest, listed = read_manifest(base), []
    for entry in manifest['assets']:
        found = _problem_of(base, entry)
        listed.append({**entry, 'state': STATES[found['code']] if found else 'ok'})
    result = {'manifest': MANIFEST, 'assets': listed}
    if design:
        resolved, pending, _ = _candidates(manifest, design, env)
        result['candidates'] = {'resolved': resolved, 'pending': pending}
    return result


def check(project, design=None, brand=None, env=None) -> dict:
    base = _root(project)
    manifest, problems = read_manifest(base), []
    for entry in manifest['assets']:
        found = _problem_of(base, entry)
        if found:
            problems.append(found)
    if brand:
        contract, entries = _index(brand)
        for entry in [item for item in manifest['assets'] if item['kind'] == 'icon']:
            try:
                found = _library_entry(contract, entries, entry['ref'], entry['assetId'])
            except Refusal as wrong:
                problems.append({**wrong.problems[0], 'detail': str(wrong)})
                continue
            if entry.get('sha256') and _hash(_stringify(found['entry']).encode('utf-8')) \
                    != entry['sha256']:
                problems.append({'code': 'asset-hash-changed', 'asset': entry['assetId'],
                                 'detail': f"Asset {entry['assetId']}: icon {entry['ref']} "
                                           'changed in the brand library since it was recorded',
                                 'next': 'Look at the icon again, then record it with assets '
                                         'icon --brand'})
    sorted_ = None
    if design:
        sorted_ = _candidates(manifest, design, env)
        problems += sorted_[2]
    if problems:
        raise Refusal(problems[0]['detail'] if len(problems) == 1 else
                      f'{len(problems)} asset problems:\n'
                      + '\n'.join(problem['detail'] for problem in problems), *problems)
    return {'status': 'ready', 'manifest': MANIFEST, 'assets': len(manifest['assets']),
            **({'candidates': {'resolved': sorted_[0], 'pending': sorted_[1]}}
               if sorted_ else {})}


# --- images ------------------------------------------------------------------------------

def images_status(env=None) -> dict:
    """images status, for the default provider: whether a key is set. Nothing is asked."""
    key = api_key(env)
    found = {'status': 'configured' if key else 'key_required', 'provider': 'gemini-api',
             'model': MODEL, 'keyVariable': key, 'liveChecked': False, 'paid': True}
    return found if key else {**found, 'steps': list(STEPS)}


def generate(project, ident, prompt, output, alt=None, slide=None, env=None,
             made=None) -> dict:
    """images generate with the default provider, as a stub: checks what the tool checks,
    writes the picture and its sidecar in the deck, and records it in the manifest."""
    base = Path(os.path.abspath(project)) if project else None
    if base is not None and ident and output and base.exists():
        entry = next((item for item in read_manifest(base.resolve())['assets']
                      if item['assetId'] == ident), None)
        stem = re.sub(r'\.[^./]*$', '', str(output).replace(os.sep, '/'))
        if entry and (entry['kind'] != 'generated'
                      or re.sub(r'\.[^./]*$', '', entry['path']) != stem):
            raise _conflict(ident, f"for {entry.get('path') or entry.get('ref')}")
    if not project or not ident:
        raise ImagesError('project_and_id_required')
    if not REQUEST.match(ident):
        raise ImagesError('request_id_required')
    if not prompt or not output:
        raise ImagesError('brief_and_output_required')
    if not base.exists():
        raise ImagesError('project_not_found')
    base = base.resolve()
    parts = [part for part in re.split(r'[\\/]+', str(output))]
    if os.path.isabs(str(output)) or '..' in parts or len(parts) < 2 or parts[0] != 'assets':
        raise ImagesError('output_must_be_in_assets')
    if not str(output).lower().endswith('.png'):
        raise ImagesError('output_must_be_png')
    target = base.joinpath(*parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    brief = Path(prompt).read_text(encoding='utf-8').strip()
    if not brief:
        raise ImagesError('empty_prompt')
    stem, sidecar = target.with_suffix(''), target.with_suffix('.image.json')
    asked = _hash(brief.encode('utf-8'))
    if sidecar.exists():   # the same request again: its picture is already in the deck
        known = json.loads(sidecar.read_text(encoding='utf-8'))
        if known.get('promptSha256') != asked:
            raise ImagesError('request_id_conflict')
        data = target.read_bytes()
    else:
        if not api_key(env):
            raise ImagesError('key_required')
        for path in (sidecar, *(stem.with_suffix(suffix) for suffix in ('.png', '.jpg',
                                                                         '.webp'))):
            if path.exists():
                raise ImagesError('output_exists')
        data = made(brief) if made else png()
        info = image_info(data)
        if not info:
            raise ImagesError('invalid_image')
        with open(target, 'xb') as written:
            written.write(data)
        known = {'provider': 'gemini-api', 'api': 'interactions', 'requestId': ident,
                 'generated': True, 'model': MODEL, 'created': _now(), 'promptSha256': asked,
                 'styleSha256': None, 'referenceSha256': [], 'aspectRatio': '16:9',
                 'imageSize': '2K', 'format': info['format'], 'width': info['width'],
                 'height': info['height'], 'sha256': _hash(data)}
        with open(sidecar, 'x', encoding='utf-8') as written:
            written.write(json.dumps(known, indent=2) + '\n')
    result = {'status': 'downloaded', 'id': ident, 'path': str(target),
              'width': known['width'], 'height': known['height'], 'sha256': _hash(data),
              'metadata': str(sidecar)}
    register_generated(base, result, alt, slide)
    return result


# --- a composition's images ----------------------------------------------------------------

def resolve(comp, project) -> tuple[dict, dict, list[str]]:
    """Each image a composition names by asset ID, resolved to the project's file, with its
    recorded alt text when the composition gives none. Problems are composition lines."""
    out, uses, problems, wanted = json.loads(json.dumps(comp)), {}, [], []

    def walk(node) -> None:
        if not isinstance(node, dict):
            return
        if node.get('type') == 'image' and 'asset' in node and 'src' not in node:
            wanted.append((node, node.get('id'), node.get('id')))
        for kid in [*(node.get('children') if isinstance(node.get('children'), list)
                      else []), node.get('hub')]:
            walk(kid)

    for slide in out.get('slides') if isinstance(out, dict) and isinstance(
            out.get('slides'), list) else []:
        if not isinstance(slide, dict):
            continue
        walk(slide.get('canvas'))
        picture = slide.get('picture')
        if isinstance(picture, dict) and 'asset' in picture and 'src' not in picture:
            wanted.append((picture, f"{slide.get('id')}_picture", slide.get('id')))
    if not wanted:
        return out, uses, problems
    base = _root(project) if project else None
    manifest = read_manifest(base) if base else None
    for node, ident, where in wanted:
        asset, line = node['asset'], None
        entry = next((item for item in manifest['assets'] if item['assetId'] == asset),
                     None) if manifest else None
        if not isinstance(asset, str) or not asset:
            line = f'{where}: asset must be an asset ID from assets status'
        elif not base:
            line = (f'{where}: image asset {asset} needs the project that records it; pass '
                    '--asset-project DIR')
        elif not entry:
            line = (f"{where}: asset {asset} is not in the project's asset manifest; record it "
                    'with assets add-supplied or images generate')
        elif entry['kind'] == 'icon':
            line = (f"{where}: asset {asset} is a brand icon; place it as an icon node with "
                    f"icon {entry['ref']}")
        else:
            found = _problem_of(base, entry)
            if found:
                line = f"{where}: asset {asset} " + (
                    f"file {entry['path']} is missing from the project"
                    if found['code'] == 'asset-file-missing' else
                    f"file {entry['path']} changed since it was recorded"
                    if found['code'] == 'asset-hash-changed' else
                    f"file {entry['path']} must be a regular file inside the project")
        alt = node['alt'] if node.get('alt') is not None else (entry or {}).get('alt')
        del node['asset']
        if line:
            problems.append(line)
            node['src'], node['alt'] = f'asset:{asset}', alt if alt is not None \
                else 'unresolved asset'
            continue
        if alt is None:
            problems.append(f'{where}: asset {asset} has no recorded alt text; give the image '
                            'alt')
        node['src'] = str(base.joinpath(*entry['path'].split('/')))
        node['alt'] = alt if alt is not None else 'missing alt'
        uses[ident] = {'assetId': asset, 'kind': entry['kind'], 'path': node['src'],
                       'source': entry['path'], 'sha256': entry['sha256']}
    return out, uses, problems


def place(scene: dict, base: Path, uses: dict) -> tuple[list[dict], dict]:
    """The images of a compiled scene: a file named by src keeps its absolute path; an asset
    is copied into OUTPUT/assets and named relatively. Returns inputs.assets and the copies."""
    assets, copies = [], {}
    for slide in scene['slides']:
        for element in slide['elements']:
            if element.get('type') != 'image' or str(element.get('src')).startswith('https://'):
                continue
            use = uses.get(element['id'])
            if not use:
                path = Path(base, element['src']).resolve()
                if not path.exists():
                    raise Refusal(f"{slide['id']}/{element['id']}: image {element['src']} is "
                                  f'missing ({path})', {'code': 'asset-missing',
                                                        'slide': slide['id'],
                                                        'asset': element['id']})
                element['src'] = str(path)
                assets.append({'object': element['id'], 'path': str(path),
                               'sha256': _hash(path.read_bytes())})
                continue
            try:
                data = Path(use['path']).read_bytes()
            except FileNotFoundError:
                raise Refusal(f"{slide['id']}/{element['id']}: asset {use['assetId']} file "
                              f"{use['source']} is missing from the project", {
                                  'code': 'asset-file-missing', 'slide': slide['id'],
                                  'asset': use['assetId']})
            if _hash(data) != use['sha256']:
                raise Refusal(f"{slide['id']}/{element['id']}: asset {use['assetId']} file "
                              f"{use['source']} changed since it was recorded", {
                                  'code': 'asset-hash-changed', 'slide': slide['id'],
                                  'asset': use['assetId']})
            element['src'] = (f"assets/{_file_name(use['assetId'])}"
                              f"{Path(use['source']).suffix.lower()}")
            copies[element['src']] = data
            assets.append({'object': element['id'], 'slide': slide['id'],
                           'asset': use['assetId'], 'kind': use['kind'],
                           'path': element['src'], 'source': use['source'],
                           'sha256': use['sha256']})
    return assets, copies


def verify(folder) -> None:
    """Before a compiled folder is rendered: each copied asset is still the file compiled."""
    folder = Path(folder)
    try:
        report = json.loads((folder / 'compose-report.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        return
    for asset in (report.get('inputs') or {}).get('assets') or []:
        # An icon is drawn from the brand library at render, so the build holds no copy of it.
        if not asset.get('asset') or asset.get('kind') == 'icon':
            continue
        slide = asset.get('slide')
        try:
            data = _inside(folder.resolve(), asset['path']).read_bytes()
        except FileNotFoundError:
            raise Refusal(f"{asset['object']}: asset {asset['asset']} copy {asset['path']} is "
                          'missing from the build', {
                              'code': 'asset-file-missing', 'slide': slide,
                              'asset': asset['asset'], 'next': 'Compile the composition again'})
        if _hash(data) != asset['sha256']:
            raise Refusal(f"{asset['object']}: asset {asset['asset']} copy {asset['path']} "
                          'changed since it was compiled', {
                              'code': 'asset-hash-changed', 'slide': slide,
                              'asset': asset['asset'], 'next': 'Compile the composition again'})
