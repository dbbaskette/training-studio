"""Harness Slides' design-bound review of a composition, for the stand-in: `review --compiled`,
`--slide`, `--mark` and `--assessment` as its `main` has them (harness-slides-skill#50, with
#65's icons placed by asset ID), and `--packets`, `--renderer google` and an assessment's
sources taken from its slide as 0.14.1 has them (#67).

    Review(output, deck=draw, picture=picture, screens=screens, local=True, has=(),
           google=None)
    review.prepare(compiled, project)        # renders REVIEW/deck.pptx, and the summary
    review.prepare(compiled, project, renderer='google', file_id=None)   # through Drive
    review.inspect(slide)                    # one slide's prompt, findings and binding
    review.packets()                         # every slide's, in one call
    review.mark(revision, numbers, note)     # pixels looked at
    review.assess(revision, assessment)      # the creative assessment, with what is unresolved
    findings(record)                         # what design present lists for the person

It keeps the tool's rules, messages and codes, ported from scripts/lib/slide-review.mjs and
native-quality.mjs: the build's own prompts (an approved asset missing, a candidate not
placed, a mechanism drawn as prose cards and the diagram not drawn), the criteria the
assessment must answer, the five categories, and the receipts that bind the review to the
deck it rendered, its pictures, the build, the design revision and the asset copies. A
changed one is refused as `review-stale` or `asset-hash-changed`.

Where it is simpler than the real thing: the deck is what the stand-in's compose render
writes, its pictures are the stand-in's own, the slide IDs a presentation program would give
are 256 on, and the screens are the stand-in preview's. `local` False is a computer without
LibreOffice, refused as `renderer-unavailable` once the deck is written, as the tool does.
`has` is what the tool lists in `version`: `review-packets`, `review-google-renderer` and
`review-sources-from-slide` are played only where listed. `google(file_id, data, title)`
stands in for Drive: it returns {'fileId', 'url'} or refuses as the upload would.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path

from stand_ins import assets as manifest
from stand_ins import design as designs

QUESTIONS = {
    'title-support': 'Does the title follow from the actual cited evidence and visible '
                     'qualifications?',
    'visual-relationship': 'Which native actors, containment or connections explain this '
                           'relationship? Prose in boxes is not automatically a diagram.',
    'composition-decision': 'Compare this composition with the strongest feasible alternative '
                            'for the same content, not invented evidence or decorative '
                            'artwork.',
    'explanatory-value': 'What does the visual make easier to understand than reading the '
                         'same words in a list?',
    'focal-hierarchy': 'Identify the focal object and the meaning of each labeled '
                       'region/color.',
    'asset-purpose': 'Verify the specific approved icon/image/construction or no-asset '
                     'decision, actual asset presence and provenance.',
    'reading-order': 'Can the audience follow the takeaway, explanation and important caveats '
                     'at delivery size?',
    'technical-fit': 'Inspect actual native/export pixels for wrapping, contrast, spacing, '
                     'aspect ratio and inherited font styles.',
    'rendered-text-completeness': 'Compare expected native text with the image: are complete '
                                  'titles, heading prefixes, body labels and caveats visible?',
    'approved-design': 'Does this delivered construction and asset purpose implement the '
                       'user-approved design? Describe any material departure.',
    'repetition-justification': 'Across the whole deck, is equivalent geometry justified by '
                                'comparable content or does a different relationship need '
                                'recomposition?',
    'teaching-treatment': 'These cards carry a mechanism as prose with nothing drawn between '
                          'them. Does the treatment show the relationship the slide teaches, '
                          'or must the learner rebuild it from the sentences? Name what the '
                          'learner cannot see, or say why the cards teach it here. Boxes alone '
                          'are not the defect.'}
CATEGORIES = ('asset-failure', 'design-deviation', 'visual-teaching', 'fit-defect',
              'direct-text')
ASSET_CODES = ('approved-asset-missing', 'approved-candidate-missing', 'icon-repeated',
               'icon-alone', 'icon-two-meanings')
DEVIATION_CODES = ('approved-diagram-not-drawn',)
TEACHING_CODES = ('prose-cards', 'relational-text-only', 'sequence-without-edges',
                  'repeats-previous-layout', 'similar-geometry', 'similar-native-geometry',
                  'label-title', 'no-brief', 'no-direction', 'title-value-needs-support',
                  'text-only', 'dense-run', 'no-notes', 'text-density-review')
BY_CRITERION = {'asset-purpose': 'asset-failure', 'approved-design': 'design-deviation',
                'technical-fit': 'fit-defect', 'rendered-text-completeness': 'fit-defect',
                'reading-order': 'fit-defect', 'export-completeness': 'fit-defect'}
SPECIFIC = ('composition-decision', 'explanatory-value', 'asset-purpose',
            'rendered-text-completeness', 'approved-design', 'teaching-treatment')
MECHANISM = re.compile(r'cycle|loop|reconcil|sequence|order|flow|process|pipeline|step|stage|'
                       r'depend|caus|trigger|own|contain|hierarch|mechanism|lifecycle|'
                       r'hand-?off|interact|architecture|feedback|propagat|rout|transform|'
                       r'control', re.I)
LOOP = re.compile(r'cycle|loop|reconcil|repeat|again', re.I)
BUILD = ('scene.json', 'structure.json', 'compose-report.json', 'brand-contract.json')
IMAGE = re.compile(r'^slide-\d+-[a-f0-9]+\.png$')
MARKER = 'harness-slides-review-v1\n'
RENDERER = 'LibreOffice PDF / Poppler; verify fidelity in the target editor'
GOOGLE = 'Google Slides PDF export / Poppler; Google draws with its own fonts'
STATUSES = ('pass', 'issue', 'uncertain')


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bytes(path: Path) -> bytes:
    """A file a record names, or the refusal Node's own error is sorted into."""
    try:
        return Path(path).read_bytes()
    except FileNotFoundError:
        raise _refused(f"ENOENT: no such file or directory, lstat '{path}'", 'input-missing')


def _refused(message: str, code: str, **more) -> designs.Refusal:
    return designs.Refusal(message, {'code': code, **more})


def _stale(message: str) -> designs.Refusal:
    return _refused(message, 'review-stale')


def finding_category(code: str) -> str:
    return ('asset-failure' if code in ASSET_CODES else 'design-deviation'
            if code in DEVIATION_CODES else 'visual-teaching' if code in TEACHING_CODES
            else 'fit-defect')


def criterion_category(ident: str) -> str:
    return BY_CRITERION.get(ident, 'visual-teaching')


def _listed(items: list[str]) -> str:
    return ''.join(items) if len(items) < 2 else f"{', '.join(items[:-1])} and {items[-1]}"


def _inside(a: dict, b: dict) -> bool:
    """Whether `a` encloses `b`."""
    return (a['x'] <= b['x'] + .5 and a['y'] <= b['y'] + .5
            and a['x'] + a['width'] >= b['x'] + b['width'] - .5
            and a['y'] + a['height'] >= b['y'] + b['height'] - .5)


def _words(text) -> int:
    return len((text or '').strip().split()) or 1   # ''.split(/\s+/) is one empty word


def audit(scene: dict, structure: dict, report: dict, plan: dict, revision: str,
          screens: list, binding: str, built: str, artifact: str) -> dict:
    """auditCompositionReview: a compiled composition judged against its approved design,
    with the native critique's criteria. Screens are prompts to look, never approval."""
    if len(scene['slides']) != len(plan['slides']) or any(
            slide['id'] != planned['id'] for slide, planned in zip(scene['slides'],
                                                                  plan['slides'])):
        raise ValueError('The compiled slides differ from the approved design')
    findings, prompts = [], []
    templated = {entry['slide'] for entry in structure.get('layouts') or ()
                 if entry.get('layout') != '@subtitled'}
    direct = {slide['id'] for slide in plan['slides']
              if slide['intent']['visual']['family'] == 'text'}
    for found in screens:
        category = finding_category(found['code'])
        findings.append({**{key: value for key, value in found.items() if key != 'metrics'},
                         'category': 'direct-text' if category == 'visual-teaching'
                         and found['slide'] in direct else category})
    placed_all = [{key: entry.get(key) for key in ('object', 'slide', 'asset', 'kind',
                                                   'sha256')}
                  for entry in (report.get('inputs') or {}).get('assets') or ()
                  if entry.get('asset')]
    for slide, proposed in zip(scene['slides'], plan['slides']):
        family = proposed['intent']['visual']['family']
        body = [e for e in slide['elements'] if e.get('role') != 'title'
                and e.get('text') != slide['title']]
        edges = [c for c in structure.get('connectors') or () if c['slide'] == slide['id']]
        icons = [c for c in structure.get('icons') or () if c['slide'] == slide['id']]
        # An icon placed by asset ID is listed with the assets, but it is drawn as an icon.
        placed = [a for a in placed_all if a['slide'] == slide['id'] and a['kind'] != 'icon']

        def icon_asset(ident, mine=slide['id']):
            return next((a['asset'] for a in placed_all if a['kind'] == 'icon'
                         and a['slide'] == mine and a['object'] == ident), None)

        shapes = [e for e in body if e['type'] == 'shape']
        region = any(a is not b and _inside(a, b) for a in shapes for b in shapes)
        pictures = any(e['type'] in ('image', 'table', 'chart') for e in body)
        missing = family in designs.ASSETS and not (
            icons if family == 'icon' else placed or any(e['type'] == 'image' for e in body))
        if missing:
            findings.append({'slide': slide['id'], 'code': 'approved-asset-missing',
                             'severity': 'error', 'category': 'asset-failure', 'detail': (
                                 f'The approved visual is {family}, and the build places none '
                                 'on this slide. Place the approved asset, or propose the '
                                 'change for approval.')})
        asset = proposed['asset']
        candidates = (asset.get('candidates') or []) if asset['disposition'] == 'selected' \
            else []
        if not missing and candidates and not any(
                any(x['icon'] == c['ref'] or icon_asset(x['id']) == c['assetId']
                    for x in icons) if c['kind'] == 'icon'
                else any(a['asset'] == c['assetId'] for a in placed) for c in candidates):
            named = '; '.join(f"{c['assetId']}: {c['concept']}" for c in candidates)
            findings.append({'slide': slide['id'], 'code': 'approved-candidate-missing',
                             'severity': 'warn', 'category': 'asset-failure', 'detail': (
                                 f'None of the approved asset candidates ({named}) is on this '
                                 'slide. Place one, or judge under asset-purpose why the slide '
                                 'teaches without it.')})
        cards = [e for e in shapes if _words(e.get('text')) >= 3
                 and not re.search(r'chevron|homePlate', e.get('shape') or '', re.I)]
        relationship = proposed['intent']['relationship'].strip()
        drawn = family in ('diagram', 'regions')
        prose = (slide['id'] not in direct and slide['id'] not in templated
                 and family not in ('table', 'chart', 'quote')
                 and (drawn or bool(MECHANISM.search(relationship))) and len(cards) >= 2
                 and not edges and not region and not pictures)
        if prose:
            labels = [card['text'].split('\n')[0].strip() for card in cards]
            loop = LOOP.search(f"{relationship} {proposed['intent']['takeaway']}")
            findings.append({
                'slide': slide['id'], 'objects': [card['id'] for card in cards],
                'code': 'prose-cards', 'severity': 'warn', 'category': 'visual-teaching',
                'detail': (f'The approved relationship is "{relationship}", but '
                           f'{_listed(labels)} are {len(cards)} cards of prose with nothing '
                           'drawn between them: no edge, region or picture shows how one '
                           'leads to another. The learner has to rebuild the '
                           f'{relationship} from the sentences'
                           + (', and nothing shows the step that closes the loop'
                              if loop else '')
                           + '. Say in teaching-treatment what the learner cannot see, or '
                             'why the cards teach it here.')})
            if drawn:
                findings.append({'slide': slide['id'], 'code': 'approved-diagram-not-drawn',
                                 'severity': 'warn', 'category': 'design-deviation',
                                 'detail': (f'The approved treatment is a {family}: '
                                            f"\"{proposed['composition']}\" The build draws no "
                                            'edge or region. Build the approved construction, '
                                            'or propose the change for approval.')})
        repeated = any(f['slide'] == slide['id'] and f['code'] in (
            'similar-geometry', 'repeats-previous-layout') for f in findings)
        ids = list(dict.fromkeys([*(e['id'] for e in slide['elements']),
                                  *(e['id'] for e in edges), *(e['id'] for e in icons)]))
        prompts.append({
            'slide': slide['id'], 'title': slide['title'], 'component': 'composition',
            'treatment': 'direct-text' if slide['id'] in direct else family,
            'intent': proposed['intent'], 'sources': proposed['sources'], 'objects': ids,
            'expectedText': [{'object': e['id'], 'text': e['text']}
                             for e in slide['elements'] if (e.get('text') or '').strip()],
            'approvedCopy': proposed.get('visibleText'),
            'approvedComposition': proposed['composition'], 'assetCandidate': asset,
            'assetObjects': [*placed, *({'object': c['id'], 'icon': c['icon'],
                                         **({'asset': icon_asset(c['id'])}
                                            if icon_asset(c['id']) else {})}
                                        for c in icons)],
            **({'proseCards': [card['id'] for card in cards]} if prose else {}),
            'criteria': [{'id': ident, 'question': question}
                         for ident, question in QUESTIONS.items()
                         if (repeated if ident == 'repetition-justification'
                             else prose if ident == 'teaching-treatment' else True)]})
    groups = [json.loads(group) for group in dict.fromkeys(
        json.dumps(f['relatedSlides']) for f in findings if f['code'] == 'similar-geometry')]
    quality = {
        'schema': 1, 'policy': 3, 'kind': 'composition', 'sceneDigest': designs.digest(scene),
        'structureDigest': designs.digest(structure), 'designRevision': revision,
        'build': binding, 'assets': placed_all, 'builtArtifactDigest': built,
        'artifactDigest': artifact,
        'bindings': [{'planId': slide['id'], 'slide': slide['id']} for slide in plan['slides']],
        'prompts': prompts, 'findings': findings,
        'deckReview': {'groups': groups, 'questions': [
            'What does each visual make easier to understand than the same words in a list?',
            'Which repeated geometry supports comparison, and which different relationship '
            'needs recomposition?']},
        'limitations': ['Screens and prose-card prompts point at slides to look at; they do '
                        'not judge comprehension.', 'The rendered deck is a LibreOffice render; '
                        'verify fidelity in the target editor.']}
    quality['revision'] = designs.digest(quality)
    return quality


def assessed(quality: dict, assessment) -> dict:
    """assessCritique and assessNativeCritique: an assessment that answers every criterion of
    every slide, with slide-specific reasons and the prose cards cited. Returns what is
    unresolved, each with its category."""
    payload = {key: value for key, value in quality.items() if key != 'revision'}
    if quality.get('revision') != designs.digest(payload):
        raise ValueError('Quality report changed')
    slides = assessment.get('slides') if isinstance(assessment, dict) else None
    if not isinstance(assessment, dict) or assessment.get('schema') != 1 \
            or assessment.get('sceneDigest') != quality['sceneDigest'] \
            or assessment.get('qualityRevision') != quality['revision'] \
            or assessment.get('artifactDigest') != quality['artifactDigest'] \
            or not isinstance(slides, list) or len(slides) != len(quality['prompts']) \
            or len({s.get('id') if isinstance(s, dict) else None for s in slides}) \
            != len(slides):
        raise ValueError('Critique must cover the current quality revision and each slide '
                         'exactly once')
    unresolved = []
    for prompt in quality['prompts']:
        mine = next((s for s in slides if isinstance(s, dict) and s.get('id') == prompt['slide']),
                    None)
        listed = (mine or {}).get('checks')
        if not isinstance(listed, list) or len(listed) != len(prompt['criteria']) or len(
                {c.get('criterion') if isinstance(c, dict) else None for c in listed}) \
                != len(listed):
            raise ValueError('Critique must assess each required criterion exactly once')
        for criterion in prompt['criteria']:
            c = next((c for c in listed if isinstance(c, dict)
                      and c.get('criterion') == criterion['id']), None)
            objects, sources = (c or {}).get('objects'), (c or {}).get('sources')
            if not c or c.get('status') not in STATUSES or not isinstance(c.get('reason'), str) \
                    or not c['reason'].strip() or not isinstance(objects, list) or not objects \
                    or any(ident not in prompt['objects'] for ident in objects) \
                    or not isinstance(sources, list) or not sources \
                    or any(ident not in prompt['sources'] for ident in sources):
                raise ValueError('Critique needs a judgment, reason, actual object IDs and '
                                 'retained sources')
            if c['status'] != 'pass':
                unresolved.append({'slide': prompt['slide'], 'criterion': c['criterion'],
                                   'status': c['status'], 'detail': c['reason'],
                                   'objects': objects, 'sources': sources})
    for criterion in SPECIFIC:
        reasons = set()
        for slide in slides:
            c = next((c for c in slide['checks'] if c['criterion'] == criterion), None)
            if not c or c['status'] != 'pass':
                continue
            reason = ' '.join(c['reason'].split()).lower()
            if reason in reasons:
                raise ValueError(f'Use slide-specific evidence for {criterion}; a duplicated '
                                 'bulk approval is insufficient')
            reasons.add(reason)
    for prompt in quality['prompts']:
        if not prompt.get('proseCards'):
            continue
        mine = next(s for s in slides if s['id'] == prompt['slide'])
        c = next(c for c in mine['checks'] if c['criterion'] == 'teaching-treatment')
        if not any(ident in prompt['proseCards'] for ident in c['objects']):
            raise ValueError(f"Answer teaching-treatment on {prompt['slide']} about the cards "
                             f"it names: cite at least one of {', '.join(prompt['proseCards'])}")
    unresolved = [{**entry, 'category': criterion_category(entry['criterion'])}
                  for entry in unresolved]
    unresolved += [{'slide': f['slide'], 'criterion': 'asset-purpose', 'status': 'issue',
                    'detail': f['detail'],
                    'category': f.get('category') or finding_category(f['code'])}
                   for f in quality['findings'] if f['severity'] == 'error']
    return {'unresolved': unresolved, 'complete': not unresolved}


def categorized(quality: dict, assessment) -> dict:
    """categorizeReview: prompts from the build, judgements from the assessment, and the
    slides approved as direct text, in five categories."""
    categories = {category: [] for category in CATEGORIES}
    for f in quality['findings']:
        categories[f.get('category') or finding_category(f['code'])].append({
            'slide': f['slide'], 'kind': 'prompt', 'code': f['code'], 'severity': f['severity'],
            'detail': f['detail'], **({'objects': f['objects']} if f.get('objects') else {})})
    judged = None
    if assessment:
        try:
            judged = assessed(quality, assessment)
        except (ValueError, KeyError, TypeError, AttributeError):
            judged = None
    for entry in (judged or {}).get('unresolved') or ():
        if entry.get('objects'):
            categories[entry['category']].append({
                'slide': entry['slide'], 'kind': 'judgement', 'criterion': entry['criterion'],
                'status': entry['status'], 'detail': entry['detail'],
                'objects': entry['objects']})
    for prompt in quality['prompts']:
        if prompt.get('treatment') == 'direct-text' \
                or prompt['intent']['visual']['family'] == 'text':
            categories['direct-text'].append({
                'slide': prompt['slide'], 'kind': 'treatment',
                'purpose': prompt['intent']['visual']['purpose'],
                'reason': (prompt.get('assetCandidate') or {}).get('reason'),
                'accepted': None if judged is None else not any(
                    entry['slide'] == prompt['slide'] for entry in judged['unresolved'])})
    return {'schema': 1, 'categories': categories,
            'complete': bool(judged and judged['complete'])}


def plan_id(record: dict, ident: str) -> str:
    """planIdOf: the approved slide a rendered slide is, or the ID itself."""
    return next((entry['planId'] for entry in record.get('designBinding') or ()
                 if entry['nativeId'] == ident), ident)


def findings(record: dict) -> list[dict] | None:
    """reviewFindings: what the assessment leaves unresolved, by the approved slide's ID, as
    design present --accept-findings lists it for the person. None without an assessment."""
    if not record.get('creativeQuality') or not record.get('creativeAssessment'):
        return None
    return [{'slide': plan_id(record, entry['slide']), 'criterion': entry['criterion'],
             'status': entry['status'], 'category': entry['category'],
             'detail': entry['detail'], **({'objects': entry['objects']}
                                           if entry.get('objects') else {})}
            for entry in assessed(record['creativeQuality'],
                                  record['creativeAssessment'])['unresolved']]


def from_slide(quality: dict, assessment):
    """withSlideSources: a check that leaves out its sources takes its slide's; sources that
    are given must be the slide's."""
    if not isinstance(assessment, dict) or not isinstance(assessment.get('slides'), list):
        return assessment
    problems, slides = [], []
    for slide in assessment['slides']:
        prompt = next((p for p in quality['prompts'] if isinstance(slide, dict)
                       and p['slide'] == slide.get('id')), None)
        if prompt is None or not isinstance(slide.get('checks'), list):
            slides.append(slide)
            continue
        checks = []
        for check in slide['checks']:
            if isinstance(check, dict) and check.get('sources') is None:
                check = {**check, 'sources': list(prompt['sources'])}
            elif isinstance(check, dict):
                given = check['sources']
                stray = [x for x in given if x not in prompt['sources']] \
                    if isinstance(given, list) else []
                if not isinstance(given, list) or not given or stray:
                    problems.append({'code': 'input-invalid', 'slide': slide['id'], 'detail': (
                        f"{slide['id']}: {check.get('criterion')} "
                        + (f"cites {', '.join(stray)}, not among the slide's sources "
                           f"({', '.join(prompt['sources'])})" if stray else
                           "gives sources that are not a list of the slide's sources")
                        + ". Leave sources out to use the slide's own")})
            checks.append(check)
        slides.append({**slide, 'checks': checks})
    if problems:
        raise designs.Refusal(problems[0]['detail'] if len(problems) == 1 else
                              f'{len(problems)} problems in the assessment:\n'
                              + '\n'.join(problem['detail'] for problem in problems),
                              *problems)
    return {**assessment, 'slides': slides}


def _recorded(base: Path, target, project) -> str:
    """recordedPath: relative to the record's folder when both lie in the project."""
    target, base = Path(os.path.abspath(target)), Path(os.path.abspath(base))
    if project:
        root = Path(os.path.abspath(project))
        if root in (base, *base.parents) and root in (target, *target.parents):
            return Path(os.path.relpath(target, base)).as_posix() or '.'
    return str(target)


def _located(base: Path, path) -> Path:
    """recordedLocation: a path a record names, resolved against its folder."""
    return Path(os.path.abspath(Path(base) / path))


class Review:
    """One review folder. `deck(path, scene)` writes the deck a build renders to,
    `picture(slide, scene)` gives a slide's PNG, and `screens(scene, structure)` the
    preview's screens, each with its slide."""

    def __init__(self, output, deck, picture, screens, local: bool = True, has=(),
                 google=None):
        self.output = Path(os.path.abspath(output))
        self.deck, self.picture, self.screens, self.local = deck, picture, screens, local
        self.has, self.google = frozenset(has or ()), google

    # --- the folder ---

    def _record(self) -> dict | None:
        path = self.output / 'review.json'
        if not path.exists():
            return None
        record = json.loads(path.read_text(encoding='utf-8'))
        if record.get('schemaVersion') != 1 or record.get('tool') != 'harness-slides-review' \
                or not isinstance(record.get('slides'), list):
            raise ValueError('Not a Harness Slides review record')
        return record

    def _locked(self, act):
        self.output.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.output.is_symlink() or not self.output.is_dir():
            raise ValueError('Review output must be a real directory')
        existing = os.listdir(self.output)
        marker = self.output / '.harness-review'
        if existing and 'review.json' not in existing and not (
                marker.is_file() and marker.read_text(encoding='utf-8') == MARKER):
            raise ValueError('Choose an empty directory or an existing Harness Slides review '
                             'directory')
        lock = self.output / '.review-lock'
        handle = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(handle)
        try:
            if not existing:
                marker.write_text(MARKER, encoding='utf-8')
            return act(self._record())
        finally:
            lock.unlink(missing_ok=True)

    def _build(self, folder) -> dict:
        folder, files, values = Path(os.path.abspath(folder)), {}, {}
        for name in BUILD:
            try:
                data = (folder / name).read_bytes()
            except FileNotFoundError:
                raise _refused(f'{folder} is not a compiled composition: {name} is missing. '
                               'Compile it with compose compile --output', 'input-missing')
            files[name], values[name] = _hash(data), json.loads(data)
        return {'dir': folder, 'files': files, 'binding': designs.digest(files),
                'scene': values['scene.json'], 'structure': values['structure.json'],
                'report': values['compose-report.json']}

    def _save(self, record: dict) -> dict:
        project = _located(self.output, record['designProject']) \
            if record.get('designProject') else self.output

        def keep(path) -> str:
            return _recorded(self.output, _located(self.output, path), project)

        record['source']['file'] = keep(record['source']['file'])
        record['designProject'] = keep(record['designProject'])
        if record.get('compiled'):
            record['compiled']['dir'] = keep(record['compiled']['dir'])
        record['pending'] = [s['number'] for s in record['slides']
                             if (s.get('finalReview') or {}).get('revision') != record['revision']
                             or (s.get('finalReview') or {}).get('status') != 'reviewed']
        record['visualReviewComplete'] = not record['pending']
        record['creativeReviewComplete'] = bool(
            record.get('creativeQuality') and record.get('creativeAssessment')
            and assessed(record['creativeQuality'], record['creativeAssessment'])['complete'])
        record['readyForUserReview'] = record['visualReviewComplete'] and (
            not record.get('creativeReviewRequired') or record['creativeReviewComplete'])
        (self.output / 'contact-sheet.html').write_text(
            '<!doctype html><title>Slide review</title>' + ''.join(
                f"<img src=\"{s['image']}\">" for s in record['slides']), encoding='utf-8')
        temporary = self.output / f'review.json.{uuid.uuid4()}.tmp'
        temporary.write_text(json.dumps(record, indent=2, ensure_ascii=False) + '\n',
                             encoding='utf-8')
        temporary.replace(self.output / 'review.json')
        quality, remote = record.get('creativeQuality'), record.get('remote')
        return {
            **({'fileId': remote['fileId'], 'url': remote['url'],
                'next': 'Reuse this Drive file for the next Google render: --file-id '
                        + remote['fileId']} if remote else {}),
            'output': str(self.output), 'record': str(self.output / 'review.json'),
            'contactSheet': str(self.output / 'contact-sheet.html'),
            'revision': record['revision'], 'slides': len(record['slides']),
            'changed': [s['number'] for s in record['slides'] if not s.get('reused')],
            'pending': record['pending'], 'visualReviewComplete': record['visualReviewComplete'],
            'creativeReviewRequired': record.get('creativeReviewRequired', False),
            'creativeReviewComplete': record['creativeReviewComplete'],
            'readyForUserReview': record['readyForUserReview'],
            **({'designReview': categorized(quality, record.get('creativeAssessment')),
                'qualityRevision': quality['revision'],
                'assessmentBinding': self._binding(quality),
                'qualityReport': str(self.output / 'review.json')} if quality else {})}

    @staticmethod
    def _binding(quality: dict) -> dict:
        return {'schema': 1, 'sceneDigest': quality['sceneDigest'],
                'qualityRevision': quality['revision'],
                'artifactDigest': quality['artifactDigest']}

    # --- the commands ---

    def prepare(self, compiled, project, refresh: bool = False, renderer: str = 'local',
                file_id: str | None = None) -> dict:
        """review --compiled COMPILED --output REVIEW --design-project DIR, rendered with
        LibreOffice or, with `renderer` google, through Drive"""
        if renderer not in ('local', 'google'):
            raise _refused('Choose --renderer local or google', 'input-invalid')
        if file_id and renderer != 'google':
            raise _refused('--file-id names the Drive file a Google render reuses: give it '
                           'with --renderer google', 'input-invalid')

        def act(previous: dict | None) -> dict:
            build = self._build(compiled)
            if not build['report'].get('designRevision'):
                raise _refused('This build was compiled without --design-project, so it is not '
                               'bound to a design. Compile it with --design-project, then '
                               'review it', 'design-missing', next='Compile the composition '
                               'with --design-project, then prepare the review')
            if build['report'].get('designScope') == 'section':
                raise _refused('This build is a section. Review the whole deck: merge the '
                               'sections with compose merge, compile the merged deck with '
                               '--design-project, then review it', 'input-invalid')
            approved = designs.Session(project).check()
            if build['report']['designRevision'] != approved['revision']:
                raise _refused('This build was compiled against an older design revision. '
                               'Compile the composition again against the approved design, '
                               'then review it', 'review-stale', next='Compile the composition '
                               'again with --design-project, then prepare the review')
            designs.bound(build['scene']['slides'], project,
                          canonical='canonical-digests' in self.has)
            manifest.verify(build['dir'])
            file = self.output / 'deck.pptx'
            current = _hash(file.read_bytes()) if file.exists() else None
            reuse = bool(previous) and (previous.get('compiled') or {}).get('binding') \
                == build['binding'] and _located(self.output, previous['source']['file']) \
                == file and current == previous['source']['sha256']
            if not reuse:
                with tempfile.TemporaryDirectory() as scratch:
                    self.deck(Path(scratch) / 'deck.pptx', build['scene'])
                    shutil.copyfile(Path(scratch) / 'deck.pptx', file)
            data = file.read_bytes()
            revision = _hash(data)
            key = 'stand-in' if renderer == 'local' else 'stand-in google'
            if renderer == 'local' and not self.local:   # named before anything is rendered
                raise _refused('soffice is not installed. Review renders PPTX with LibreOffice '
                               '(soffice) and Poppler (pdftoppm, pdfinfo)',
                               'renderer-unavailable', provider='libreoffice')
            source = {'type': 'pptx', 'file': str(file), 'sha256': revision}
            same = bool(previous) and previous['source'].get('type') == 'pptx' \
                and _located(self.output, previous['source']['file']) == file \
                and previous.get('rendererKey') == key
            # An unchanged deck drawn by Google before keeps its pictures and uploads nothing.
            remote = (previous or {}).get('remote') if same else None
            if renderer == 'google' and not (same and previous['revision'] == revision
                                             and remote):
                remote = {'provider': 'google', **self.google(file_id, data,
                                                              build['scene'].get('title'))}
            pages = []
            for number, slide in enumerate(build['scene']['slides'], 1):
                page = {'number': number, 'id': str(255 + number),
                        'part': f'ppt/slides/slide{number}.xml', 'hidden': False,
                        'title': slide['title'], 'fingerprint': designs.digest(slide)}
                old = next((s for s in (previous or {}).get('slides') or ()
                            if same and s['id'] == page['id']
                            and s['fingerprint'] == page['fingerprint']
                            and s['number'] == number and s['hidden'] is False), None)
                kept = not refresh and old is not None and bool(IMAGE.match(old['image'])) \
                    and (self.output / old['image']).is_file() \
                    and _hash((self.output / old['image']).read_bytes()) == old['imageSha256']
                if kept:
                    page.update(reused=True, image=old['image'],
                                imageSha256=old['imageSha256'],
                                iterationReview=old.get('finalReview')
                                or old.get('iterationReview'),
                                finalReview=old.get('finalReview')
                                if previous['revision'] == revision else None)
                else:
                    picture = self.picture(slide, build['scene'])
                    digest = _hash(picture)
                    image = f'slide-{number:03d}-{digest[:16]}.png'
                    (self.output / image).write_bytes(picture)
                    page.update(reused=False, finalReview=None, image=image,
                                imageSha256=digest)
                pages.append(page)
            record = {'schemaVersion': 1, 'tool': 'harness-slides-review', 'source': source,
                      'revision': revision,
                      'renderer': RENDERER if renderer == 'local' else GOOGLE,
                      'rendererKey': key, 'slides': pages,
                      'designProject': str(Path(os.path.abspath(project))),
                      'designRevision': approved['revision'], 'creativeReviewRequired': True,
                      **({'remote': remote} if remote else {})}
            if len(pages) != len(approved['plan']['slides']):
                raise ValueError('The rendered deck and the approved design have different '
                                 'slide counts')
            record['compiled'] = {'dir': str(build['dir']), 'binding': build['binding'],
                                  'files': build['files'], 'native': []}
            record['creativeQuality'] = audit(
                build['scene'], build['structure'], build['report'], approved['plan'],
                approved['revision'], self.screens(build['scene'], build['structure']),
                build['binding'], designs.digest({'deck.pptx': revision}),
                designs.digest([[s['id'], s['imageSha256']] for s in pages]))
            record['designBinding'] = [{'nativeId': page['id'], 'planId': planned['id']}
                                       for page, planned in zip(pages,
                                                                approved['plan']['slides'])]
            if previous and previous.get('revision') == revision and (
                    previous.get('creativeQuality') or {}).get('revision') \
                    == record['creativeQuality']['revision']:
                record['creativeAssessment'] = previous.get('creativeAssessment')
            return self._save(record)
        return self._locked(act)

    def verify(self, record: dict | None = None) -> dict:
        """verifyReview: the receipts still hold, or `review-stale`."""
        record = record or self._record()
        if record is None:
            raise ValueError('Prepare native review first')
        source = _located(self.output, record['source']['file'])
        if _hash(_bytes(source)) != record['source']['sha256']:
            raise _stale('Deck changed after rendering; prepare review again')
        for slide in record['slides']:
            if not IMAGE.match(slide['image']) \
                    or _hash(_bytes(self.output / slide['image'])) != slide['imageSha256']:
                raise _stale('Preview changed; prepare review again')
        project = _located(self.output, record['designProject'])
        if designs.Session(project).revision() != record['designRevision']:
            raise _stale('Approved design revision changed after this review was prepared; '
                         'build the current design and prepare review again')
        designs.Session(project).check()
        folder = _located(self.output, record['compiled']['dir'])
        try:
            now = self._build(folder)
        except (designs.Refusal, OSError, ValueError) as wrong:
            raise _stale(f'The compiled build changed after this review was prepared '
                         f'({wrong}); prepare review again')
        if now['binding'] != record['compiled']['binding']:
            raise _stale('The compiled build changed after this review was prepared; prepare '
                         'review again')
        manifest.verify(folder)
        quality = record['creativeQuality']
        payload = {key: value for key, value in quality.items() if key != 'revision'}
        if quality['revision'] != designs.digest(payload) \
                or quality['artifactDigest'] != designs.digest(
                    [[s['id'], s['imageSha256']] for s in record['slides']]) \
                or quality['builtArtifactDigest'] != designs.digest(
                    {'deck.pptx': record['source']['sha256']}) \
                or quality['build'] != record['compiled']['binding']:
            raise _stale('Creative quality binding changed')
        if record.get('creativeAssessment'):
            assessed(quality, record['creativeAssessment'])
        return record

    def mark(self, revision, numbers, note, status: str = 'reviewed') -> dict:
        """review --output REVIEW --mark 1,2 --revision HASH --note TEXT"""
        if not revision or not (note or '').strip() or status not in ('reviewed', 'unresolved') \
                or not numbers:
            raise ValueError('Provide revision, slide numbers, status, and an inspection note')

        def act(record: dict | None) -> dict:
            if not record or record['revision'] != revision:
                raise ValueError('Review revision changed; inspect the current previews first')
            self.verify(record)
            known = {slide['number'] for slide in record['slides']}
            if any(type(number) is not int or number not in known for number in numbers):
                raise ValueError('Unknown slide number')
            for slide in record['slides']:
                if slide['number'] in numbers:
                    slide['finalReview'] = {
                        'revision': revision, 'status': status, 'note': note.strip(),
                        'checkedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(
                            timespec='milliseconds').replace('+00:00', 'Z')}
            return self._save(record)
        return self._locked(act)

    def assess(self, revision, assessment) -> dict:
        """review --output REVIEW --assessment critique.json --revision HASH"""
        def act(record: dict | None) -> dict:
            if not record or record['revision'] != revision \
                    or not record.get('creativeReviewRequired'):
                raise ValueError('Assess the current creative review revision')
            self.verify(record)
            given = from_slide(record['creativeQuality'], assessment) \
                if 'review-sources-from-slide' in self.has else assessment
            receipt = assessed(record['creativeQuality'], given)
            record['creativeAssessment'] = given
            return {**self._save(record), 'unresolved': receipt['unresolved']}
        return self._locked(act)

    def packets(self) -> dict:
        """review --output REVIEW --packets"""
        record = self.verify()
        quality = record.get('creativeQuality')
        if not quality:
            raise _refused('This review is not bound to a design, so it has no packets',
                           'input-invalid')
        slides = []
        for page in record['slides']:
            ident = plan_id(record, page['id'])
            packet = next((p for p in quality['prompts'] if p['slide'] in (page['id'], ident)),
                          None)
            slides.append({'number': page['number'], 'id': page['id'], 'planId': ident,
                           'title': page['title'], 'hidden': page['hidden'],
                           'image': str(self.output / page['image']),
                           'imageSha256': page['imageSha256'],
                           'mark': page.get('finalReview'), 'packet': packet,
                           'findings': [f for f in quality['findings']
                                        if packet and f['slide'] == packet['slide']]})
        return {'schema': 1, 'output': str(self.output), 'revision': record['revision'],
                'designRevision': record.get('designRevision'),
                'renderer': record['renderer'], 'assessmentBinding': self._binding(quality),
                'contactSheet': str(self.output / 'contact-sheet.html'),
                'deckReview': quality['deckReview'],
                'designReview': categorized(quality, record.get('creativeAssessment')),
                'visualReviewComplete': record['visualReviewComplete'],
                'creativeReviewComplete': record['creativeReviewComplete'],
                'readyForUserReview': record['readyForUserReview'], 'slides': slides}

    def inspect(self, slide: str) -> dict:
        """review --output REVIEW --slide ID"""
        record = self.verify()
        quality = record['creativeQuality']
        prompt = next((p for p in quality['prompts'] if p['slide'] == slide or any(
            b['planId'] == slide and b['nativeId'] == p['slide']
            for b in record.get('designBinding') or ())), None)
        if prompt is None:
            raise ValueError('Unknown creative review slide')
        return {'revision': record['revision'], 'assessmentBinding': self._binding(quality),
                'slide': prompt,
                'findings': [f for f in quality['findings'] if f['slide'] == prompt['slide']],
                'deckReview': quality['deckReview']}
