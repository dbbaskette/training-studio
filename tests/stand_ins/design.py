"""The slides tool's design session, for the stand-in: `design propose`, `status`, `check`
and `respond` as Harness Slides has them after 0.13.1, with schema 2, the whole-plan
question and refusals as JSON.

    session = Session(project)
    session.propose(plan, expected=None, mode=None)   # the status, as the command prints it
    session.status()
    session.check()                                    # {'plan', 'revision', 'buildAllowed'}
    session.respond(reply)
    bound(slides, project, section)                    # a build, checked against the approval
    refusal(error, revision)                           # what --json prints for a refusal

It keeps the tool's own rules, messages and codes, ported from scripts/lib/design-session.mjs,
slide-decisions.mjs and refusals.mjs, and writes the session where the tool does. It stops
at the design: nothing is rendered here, so it never asks the rendered-review question.
The session names no project: the tool is told it with --project each time. A session
written when it did name one is read all the same, and loses the name when next written.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import uuid
from pathlib import Path

RECORD = Path('.harness-slides') / 'design' / 'session.json'
FAMILIES = ('text', 'icon', 'diagram', 'regions', 'table', 'chart', 'sourced-image',
            'generated-art', 'quote')
KINDS = ('icon', 'supplied', 'generated', 'screenshot', 'chart')
ASSETS = ('icon', 'sourced-image', 'generated-art')   # visual families that need an asset
SLIDE_KEYS = {1: ('id', 'title', 'sources', 'intent', 'visibleText', 'composition', 'asset'),
              2: ('id', 'title', 'sources', 'intent', 'visibleText', 'composition', 'asset',
                  'objectives', 'copy', 'qualifications', 'notes')}
INTENT = ('takeaway', 'relationship', 'rationale', 'evidence', 'audienceQuestion',
          'alternative', 'visual')
DECISIONS = ('approve', 'revise', 'batch', 'approve-remaining', 'autonomous')
IDENT = re.compile(r'^[_a-zA-Z][\w-]{4,63}$', re.ASCII)
ASSET_ID = re.compile(r'^[\w.:-]{1,128}$', re.ASCII)
RULE = ('Use an available native question tool; otherwise ask in chat. Async return, '
        'defaults and elapsed time are not approval.')
# [recoverable, next], as refusals.mjs has them, for the codes the design commands raise.
CODES = {
    'invalid-proposal': (True, 'Correct the proposal and propose it again'),
    'copy-mismatch': (True, 'Send copy without visibleText, or visibleText exactly as '
                            'rendered from copy'),
    'copy-qualification-missing': (True, 'Put the qualification in the slide copy, or agree '
                                         'a changed qualification with the person'),
    'asset-unresolved': (True, 'Resolve the asset, or propose the fallback for approval'),
    'design-missing': (True, 'Propose the design first with design propose'),
    'design-awaiting-approval': (True, "Show the pending slides and wait for the person's "
                                       'answer; design status has the current question'),
    'design-revision-requested': (True, 'Revise the proposal from the recorded feedback and '
                                        'propose it again'),
    'design-revision-stale': (True, 'Run design status and use its current revision and '
                                    'question'),
    'design-mismatch': (True, 'Build the approved slides in the approved order with their '
                              'approved titles, or propose the change for approval'),
    'design-state-invalid': (False, 'The design record was changed outside Harness Slides; '
                                    'propose the design again in a fresh project'),
    'design-busy': (True, 'Retry when the other design command ends. If none is running, a '
                          'stopped process left .harness-slides/design/.lock behind: remove '
                          'it and retry'),
    'invalid-response': (True, "Answer the current question with questionId, planRevision, "
                               "a decision and the person's words"),
    'composition-invalid': (True, 'Fix the composition and compile again'),
    'icon-unavailable': (True, 'Search the brand icon library for a current native icon ID'),
    'layout-unavailable': (True, 'Choose a layout listed by compose layouts'),
    'asset-missing': (True, 'Restore the file or correct its path, then compile again'),
    'asset-file-missing': (True, 'Restore the file at its recorded path, or record the asset '
                                 'again with assets add-supplied'),
    'asset-hash-changed': (True, 'Look at the changed file; if it is right, record it again '
                                 '(assets add-supplied, assets icon --brand or images '
                                 'generate), then retry'),
    'asset-conflict': (True, 'Choose a new asset ID with --id, or record the same file and '
                             'kind again'),
    'assets-busy': (True, 'Retry when the other asset command ends. If none is running, '
                          'remove .harness-slides/assets.lock and retry'),
    'provider-missing': (True, 'Set up the provider named in provider (images status says '
                               'what is missing), or record a supplied image with assets '
                               'add-supplied'),
    'provider-failed': (True, 'Check Google access with drive check, or preview with '
                              '--renderer local'),
    'review-stale': (True, 'Prepare the review again from the current build and design, '
                           'then inspect and assess it again'),
    'renderer-unavailable': (True, 'Install the named tool, or preview with the other '
                                   'renderer'),
    'output-exists': (True, 'Choose a new output directory'),
    'input-missing': (True, 'Check the path given on the command line'),
    'input-invalid': (True, 'Correct the input named in the detail and retry'),
    'unclassified': (False, 'Read the detail; ask the person before working around it'),
}
# Errors the tool raised before its codes existed, recognised by their wording as it does.
KNOWN = ((re.compile(r'Question or design revision changed|Design revision changed|Approved '
                     r'design revision changed|No existing design revision'),
          'design-revision-stale'),
         (re.compile(r'Awaiting design approval'), 'design-awaiting-approval'),
         (re.compile(r'differs? from the approved design|Generate only the selected '
                     r'approved'), 'design-mismatch'),
         (re.compile(r'New creative authoring needs --design-project'), 'design-missing'),
         (re.compile(r'changed outside the checkpoint|real directories'),
          'design-state-invalid'),
         (re.compile(r'Record the actual user response|Unknown design response|Autonomy is '
                     r'chosen|Only explicit whole-plan'), 'invalid-response'),
         (re.compile(r'Review revision changed|Assess the current creative review revision'),
          'review-stale'),
         (re.compile(r'Critique needs a judgment|Critique must|Use slide-specific evidence|'
                     r'Answer teaching-treatment|Provide revision, slide numbers'),
          'input-invalid'),
         (re.compile(r"is not in the project's asset manifest|needs the project that records "
                     r"it|resolves through the project's asset manifest"), 'asset-unresolved'),
         (re.compile(r'is missing from the project'), 'asset-file-missing'),
         (re.compile(r'changed since it was recorded'), 'asset-hash-changed'),
         (re.compile(r'unknown icon|is a picture, not native|no drawing in the library|hashed '
                     r'icon library'), 'icon-unavailable'))


class Refusal(ValueError):
    """What the tool says no with: its sentence, and the problems a caller can act on."""

    def __init__(self, message: str, *problems: dict):
        super().__init__(message)
        self.problems = list(problems)


def digest(value) -> str:
    """The tool's digest: SHA-256 of the value as JSON.stringify writes it."""
    return hashlib.sha256(json.dumps(value, separators=(',', ':'), ensure_ascii=False)
                          .encode('utf-8')).hexdigest()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec='milliseconds').replace('+00:00', 'Z')


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 20000


def _fields(value, keys) -> bool:
    return isinstance(value, dict) and all(key in keys for key in value)


def _list(value, most: int) -> bool:
    return isinstance(value, list) and 0 < len(value) <= most and all(map(_text, value))


def _squash(value: str) -> str:
    return ' '.join(value.lower().split())


def render(copy: dict) -> str:
    """A schema-2 slide's approved visible text: the focal statement when it is not a
    point's label, the points, the caveat, the source."""
    lines = []
    if 'focal' in copy and not any(point.get('label') == copy['focal']
                                   for point in copy['points']):
        lines.append(copy['focal'])
    for point in copy['points']:
        lines.append(f"{point['label']}: {point['text']}" if 'label' in point
                     and 'text' in point else point.get('label', point.get('text')))
    if 'caveat' in copy:
        lines.append(copy['caveat'])
    if 'source' in copy:
        lines.append(f"Source: {copy['source']}")
    return '\n'.join(lines)


def _copy(copy) -> bool:
    return (_fields(copy, ('points', 'focal', 'caveat', 'source'))
            and isinstance(copy.get('points'), list) and len(copy['points']) <= 12
            and (bool(copy['points']) or 'focal' in copy)
            and all(_fields(point, ('label', 'text')) and ('label' in point or 'text' in point)
                    and all(_text(point[key]) for key in ('label', 'text') if key in point)
                    for point in copy['points'])
            and all(_text(copy[key]) for key in ('focal', 'caveat', 'source') if key in copy))


def _candidates(found) -> bool:
    return (isinstance(found, list) and 0 < len(found) <= 12
            and len({item.get('assetId') if isinstance(item, dict) else None
                     for item in found}) == len(found)
            and all(_fields(item, ('assetId', 'kind', 'ref', 'concept', 'alt', 'status'))
                    and isinstance(item.get('assetId'), str)
                    and ASSET_ID.match(item['assetId']) is not None
                    and item.get('kind') in KINDS and _text(item.get('ref'))
                    and _text(item.get('concept'))
                    and ('alt' not in item or _text(item['alt']))
                    and item.get('status') in ('resolved', 'pending') for item in found))


def decision(intent, sources) -> None:
    """slide-decisions.mjs: a content-based intent, required on every proposed slide."""
    if not intent:
        raise ValueError('Every new slide needs a content-based intent')
    if not isinstance(intent, dict) or any(key not in INTENT for key in intent):
        raise ValueError('Unsupported intent field')
    for key in ('takeaway', 'relationship', 'rationale'):
        if not _text(intent.get(key)):
            raise ValueError(f'Provide intent {key}')
    evidence = intent.get('evidence')
    if not isinstance(evidence, list) or not evidence \
            or any(item not in sources for item in evidence):
        raise ValueError('Intent evidence must be retained in slide sources')
    if not _text(intent.get('audienceQuestion')):
        raise ValueError('Provide the audience question for this slide')
    other = intent.get('alternative')
    if not _fields(other, ('treatment', 'reason')) or not _text(other.get('treatment')) \
            or not _text(other.get('reason')):
        raise ValueError('Provide an alternative treatment and content-specific rejection '
                         'reason')
    visual = intent.get('visual')
    if not _fields(visual, ('family', 'purpose', 'route')) \
            or visual.get('family') not in FAMILIES or not _text(visual.get('purpose')) \
            or ('route' in visual and not _text(visual['route'])):
        raise ValueError('Provide a visual family and communicative purpose (text/no asset is '
                         'valid)')


def validate(plan) -> dict:
    """The plan as it is stored: a schema-2 slide given copy gains the visibleText rendered
    from it. Schema 1 is returned unchanged."""
    if not _fields(plan, ('schema', 'title', 'scope', 'slides')) \
            or plan.get('schema') not in (1, 2) or not _text(plan.get('title')) \
            or plan.get('scope') not in ('new', 'redesign') \
            or not isinstance(plan.get('slides'), list) or not 0 < len(plan['slides']) <= 100:
        raise Refusal('Design proposal needs schema:1 or 2, title, scope:new|redesign and '
                      '1–100 slides', {'code': 'invalid-proposal'})
    second, seen, slides = plan['schema'] == 2, set(), []
    for slide in plan['slides']:
        ident = slide.get('id') if isinstance(slide, dict) else None
        at = {'code': 'invalid-proposal', 'slide': ident if isinstance(ident, str) else None}
        copied = second and isinstance(slide, dict) and 'copy' in slide
        if not _fields(slide, SLIDE_KEYS[plan['schema']]) or not isinstance(ident, str) \
                or not IDENT.match(ident) or ident in seen or not _text(slide.get('title')) \
                or not (copied or _text(slide.get('visibleText'))) \
                or not _text(slide.get('composition')) \
                or not isinstance(slide.get('sources'), list) or not slide['sources'] \
                or not all(map(_text, slide['sources'])):
            raise Refusal('Each design slide needs a unique ID, title, visible copy, '
                          'composition and source/brief IDs', at)
        seen.add(ident)
        try:
            decision(slide.get('intent'), slide['sources'])
        except ValueError as wrong:
            raise Refusal(str(wrong), at)
        asset = slide.get('asset')
        if not _fields(asset, ('description', 'disposition', 'reason')
                       + (('candidates',) if second else ())) \
                or not _text(asset.get('description')) \
                or asset.get('disposition') not in ('selected', 'not-needed', 'unavailable') \
                or not _text(asset.get('reason')):
            raise Refusal('Describe a specific asset candidate or construction and its '
                          'selected/not-needed/unavailable decision', at)
        if second:
            if 'objectives' in slide and not _list(slide['objectives'], 20):
                raise Refusal(f'{ident}: objectives are 1–20 objective IDs', at)
            if 'qualifications' in slide and not _list(slide['qualifications'], 20):
                raise Refusal(f'{ident}: qualifications are 1–20 pieces of wording the copy '
                              'must keep', at)
            if 'notes' in slide and not _text(slide['notes']):
                raise Refusal(f'{ident}: notes are presenter notes, or omitted', at)
            if copied and not _copy(slide['copy']):
                raise Refusal(f'{ident}: copy is {{points:[{{label?,text?}}],focal?,caveat?,'
                              'source?} with at most 12 points and something to show', at)
            if copied and 'visibleText' in slide \
                    and slide['visibleText'] != render(slide['copy']):
                raise Refusal(f'{ident}: visibleText differs from the text rendered from copy; '
                              'send copy alone', {**at, 'code': 'copy-mismatch'})
            if 'candidates' in asset and not _candidates(asset['candidates']):
                raise Refusal(f'{ident}: each asset candidate needs a unique assetId, kind '
                              f"{'|'.join(KINDS)}, ref, concept, optional alt and status "
                              'resolved|pending', at)
        shown = render(slide['copy']) if copied else slide['visibleText']
        for kept in slide.get('qualifications') or ():
            if _squash(kept) not in _squash(shown):
                raise Refusal(f'{ident}: the qualification "{kept}" does not appear in the slide '
                              'copy', {**at, 'code': 'copy-qualification-missing'})
        if asset['disposition'] != 'selected' and slide['intent']['visual']['family'] in ASSETS:
            listed = asset.get('candidates') or []
            candidate = next((item for item in listed if item['status'] == 'pending'),
                             listed[0] if listed else None)
            concept = candidate['concept'] if candidate else asset['description']
            raise Refusal('An unresolved asset cannot be the selected visual; propose an '
                          'explicit fallback for approval',
                          {**at, 'code': 'asset-unresolved',
                           'asset': candidate['assetId'] if candidate else None,
                           'fallback': {'proposal': f'A native diagram (visual family '
                                                    f'"diagram") showing "{concept}" in place '
                                                    'of the unresolved asset'}})
        slides.append({**slide, 'visibleText': shown}
                      if copied and 'visibleText' not in slide else slide)
    return {**plan, 'slides': slides} if second else plan


def _binding(session: dict, slide: dict) -> str:
    """Presenter notes are not approved copy: changing them keeps a slide's approval."""
    plan = session['plan']
    return digest([plan['title'], plan['scope'], [item['id'] for item in plan['slides']],
                   {key: value for key, value in slide.items() if key != 'notes'}])


def _pending(session: dict) -> list[dict]:
    return [slide for slide in session['plan']['slides']
            if (session['approvals'].get(slide['id']) or {}).get('binding')
            != _binding(session, slide)]


def _question(session: dict) -> dict | None:
    if session.get('awaitingRevision'):
        return None
    left = _pending(session)
    if not left:
        return None     # the rendered question needs a render, which this never has
    ids = [slide['id'] for slide in (left[:1] if session['mode'] == 'guided' else left)]
    titles = '; '.join(slide['title'] for slide in session['plan']['slides']
                       if slide['id'] in ids)
    batch, whole = session['mode'] == 'batch', len(ids) == len(session['plan']['slides'])
    revision = session['revision']
    return {'id': digest(['design', revision, revision, ids]), 'phase': 'design',
            'revision': revision, 'planRevision': revision, 'slides': ids,
            'prompt': (f"Approve {'the whole design plan' if whole else 'the remaining designs'}"
                       f' ({titles}), or request changes?' if batch else
                       f'Approve the proposed design for {titles}, or request changes?'),
            'options': ([('Approve the whole plan' if whole else 'Approve these designs'),
                         'Request changes'] if batch else
                        ['Approve this design', 'Change this design',
                         'Review remaining designs together']),
            'wait': True, 'rule': RULE}


def _status(session: dict, project: Path) -> dict:
    waiting, question = _pending(session), _question(session)
    plan = session['plan']['slides']
    return {'project': str(project), 'revision': session['revision'],
            'mode': session['mode'],
            'buildAllowed': not waiting and not session.get('awaitingRevision'),
            'pending': [slide['id'] for slide in waiting],
            'status': ('revision requested' if session.get('awaitingRevision') else
                       'awaiting design approval' if waiting else
                       'design approved; build permitted'),
            'feedback': session['feedback'], 'question': question,
            'slides': [{'number': plan.index(slide) + 1, **slide} for slide in plan
                       if question and slide['id'] in question['slides']],
            'renderedRevision': None, 'renderedReview': None, 'renderedAcceptance': False}


class Session:
    """One project's design session, kept where the tool keeps it."""

    def __init__(self, project):
        self.project = Path(os.path.abspath(project))   # as Node resolves it: links kept

    def _root(self) -> Path:
        """The project, which a command that writes needs to be a real folder already."""
        if not self.project.exists():
            raise Refusal(f"ENOENT: no such file or directory, lstat '{self.project}'",
                          {'code': 'input-missing'})
        if not self.project.is_dir() or self.project.is_symlink():
            raise Refusal('Design state needs real directories')
        return self.project

    def _read(self, root: Path) -> dict | None:
        path = root / RECORD
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise Refusal('Expected a regular workspace file', {'code': 'design-state-invalid'})
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict) or value.get('schema') != 1 \
                or value.get('tool') != 'harness-slides-design' \
                or value.get('revision') != digest(value.get('plan')):
            raise Refusal('Design state changed outside the checkpoint; recover the proposal')
        validate(value['plan'])
        value.pop('project', None)  # named by a session written before --project named it
        return value

    def _needed(self, root: Path) -> dict:
        found = self._read(root)
        if found is None:
            raise Refusal(f"ENOENT: no such file or directory, open '{root / RECORD}'",
                          {'code': 'design-missing'})
        return found

    def _locked(self, act):
        root = self._root()
        folder = root / RECORD.parent
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            handle = os.open(folder / '.lock', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise Refusal(f"EEXIST: file already exists, open '{folder / '.lock'}'",
                          {'code': 'design-busy'})
        os.close(handle)
        try:
            return act(root)
        finally:
            (folder / '.lock').unlink(missing_ok=True)

    @staticmethod
    def _save(root: Path, session: dict) -> dict:
        temporary = root / RECORD.parent / f'{uuid.uuid4()}.tmp'
        try:
            temporary.write_text(json.dumps(session, indent=2, ensure_ascii=False) + '\n',
                                 encoding='utf-8')
            temporary.replace(root / RECORD)
        finally:
            temporary.unlink(missing_ok=True)
        return _status(session, root)

    def revision(self) -> str | None:
        """The current revision, for a refusal: None when there is no readable record."""
        try:
            found = self._read(self.project)
        except (Refusal, OSError, ValueError):
            return None
        return found['revision'] if found else None

    def propose(self, plan, expected: str | None = None, mode: str | None = None) -> dict:
        if mode is not None and mode not in ('guided', 'batch'):
            raise Refusal("Choose the question mode guided or batch; autonomy is the person's "
                          'answer, not a proposal option', {'code': 'invalid-proposal'})
        plan = validate(plan)

        def act(root: Path) -> dict:
            old = self._read(root)
            if old and expected != old['revision']:
                raise Refusal('Design revision changed; use the current expected revision')
            if not old and expected:
                raise Refusal('No existing design revision')
            revision = digest(plan)
            session = {'schema': 1, 'tool': 'harness-slides-design',
                       'plan': json.loads(json.dumps(plan)), 'revision': revision,
                       'mode': mode or (old or {}).get('mode') or 'guided',
                       'approvals': (old or {}).get('approvals') or {},
                       'feedback': (old or {}).get('feedback') or [],
                       'responses': (old or {}).get('responses') or [],
                       'rendered': None, 'waiveRendered': bool((old or {}).get('waiveRendered'))}
            if old and old.get('awaitingRevision') and old['revision'] == revision:
                session['awaitingRevision'] = True
            if (old or {}).get('revision') != revision:
                session['waiveRendered'] = False
                session['responses'].append({'kind': 'proposal', 'revision': revision,
                                             'at': _now()})
            if old and mode and old['mode'] != mode:
                session['responses'].append({'kind': 'mode', 'mode': mode, 'at': _now()})
            return self._save(root, session)
        return self._locked(act)

    def status(self) -> dict:
        return _status(self._needed(self.project), self.project)

    def check(self) -> dict:
        session = self.approved()
        return {'plan': session['plan'], 'revision': session['revision'], 'buildAllowed': True}

    def approved(self, ids: list | None = None, section: bool = False) -> dict:
        """getApprovedDesign: the session once every slide is approved, and with `ids` only
        when they are the slides of a build in an order the approval allows: the whole plan,
        or with `section` a run of it."""
        session = self._needed(self.project)
        if session.get('awaitingRevision'):
            asked = (session['feedback'][-1] if session['feedback'] else {}).get('slides') or []
            waiting = [{'code': 'design-revision-requested', 'slide': ident}
                       for ident in asked] or [{'code': 'design-revision-requested'}]
        else:
            waiting = [{'code': 'design-awaiting-approval', 'slide': slide['id']}
                       for slide in _pending(session)]
        if waiting:
            raise Refusal('Awaiting design approval; show the proposed slide(s) and wait for an '
                          'actual user response before building', *waiting)
        found = order_problem([slide['id'] for slide in session['plan']['slides']], ids,
                              section) if ids is not None else None
        if found:
            raise Refusal(("The section's" if section else 'Authored') + ' slide IDs/order '
                          f"differ from the approved design: {found['why']}",
                          {'code': 'design-mismatch', 'slide': found['slide']})
        return session

    def respond(self, reply) -> dict:
        if not _fields(reply, ('questionId', 'planRevision', 'decision', 'feedback',
                               'waiveRendered')) or not _text(reply.get('feedback')) \
                or ('waiveRendered' in reply and not isinstance(reply['waiveRendered'], bool)):
            raise Refusal('Record the actual user response text, questionId, planRevision and '
                          'decision')

        def act(root: Path) -> dict:
            session = self._needed(root)
            question = _question(session)
            if not question or reply['questionId'] != question['id'] \
                    or reply['planRevision'] != session['revision']:
                raise Refusal('Question or design revision changed; do not apply a '
                              'stale/default response')
            if reply['decision'] not in DECISIONS:
                raise Refusal('Unknown design response')
            if reply.get('waiveRendered') \
                    and reply['decision'] not in ('autonomous', 'approve-remaining'):
                raise Refusal('Only explicit whole-plan/autonomous authorization can waive the '
                              'rendered checkpoint')
            session['responses'].append({**reply, 'phase': 'design',
                                         'slides': question['slides'], 'at': _now()})
            if reply['decision'] == 'batch':
                session['mode'] = 'batch'
            elif reply['decision'] == 'revise':
                session['feedback'].append({'phase': 'design', 'slides': question['slides'],
                                            'text': reply['feedback'],
                                            'revision': session['revision'],
                                            'renderRevision': None})
                session['awaitingRevision'] = True
                for ident in question['slides']:
                    session['approvals'].pop(ident, None)
                session['rendered'], session['waiveRendered'] = None, False
            else:
                every = reply['decision'] in ('approve-remaining', 'autonomous')
                for slide in session['plan']['slides']:
                    if every or slide['id'] in question['slides']:
                        session['approvals'][slide['id']] = {
                            'binding': _binding(session, slide), 'response': reply['feedback']}
                if reply['decision'] == 'autonomous':
                    session['mode'] = 'autonomous'
                session['waiveRendered'] = reply.get('waiveRendered',
                                                     session['waiveRendered'])
            return self._save(root, session)
        return self._locked(act)


def order_problem(planned: list, ids: list, section: bool) -> dict | None:
    """Where a build's slide IDs leave the approved order, as {'slide', 'why'}, or None. A
    deck starts at the first approved slide and ends at the last; a section starts wherever
    its first slide is approved and may end early."""
    start = (planned.index(ids[0]) if ids and ids[0] in planned else -1) if section else 0
    if start < 0:
        first = ids[0] if ids else None
        return {'slide': first, 'why': f'{first} is not in the approved design'}
    for at in range(max(len(ids), 0 if section else len(planned) - start)):
        want = planned[start + at] if start + at < len(planned) else None
        got = ids[at] if at < len(ids) else None
        if got == want:
            continue
        if got is None:
            return {'slide': want, 'why': f'approved slide {want} is missing at the end'}
        if got not in planned:
            return {'slide': got, 'why': f'{got} is not in the approved design'}
        if want is None or planned.index(got) < start + at or want in ids:
            return {'slide': got, 'why': f'{got} is out of the approved order'
                                         + (f'; {want} comes next' if want else '')}
        return {'slide': want, 'why': f'approved slide {want} is missing before {got}'}
    return None


def bound(slides: list, project, section: bool = False) -> dict | None:
    """requireSceneDesign: a build's slides, each {'id', 'title', 'intent'?}, held to the
    design approved in `project` now. Without a project nothing is checked, unless a slide
    carries an intent. Returns {'plan', 'revision', 'scope', 'slides'}, or None."""
    if not project:
        if any(slide.get('intent') for slide in slides):
            raise Refusal('New creative authoring needs --design-project and actual design '
                          'approval', {'code': 'design-missing', 'next': 'Pass '
                                       '--design-project with the project whose design the '
                                       'person approved'})
        return None
    ids = [slide['id'] for slide in slides]
    session = Session(project).approved(ids, section)
    by_id = {slide['id']: slide for slide in session['plan']['slides']}
    problems = []
    for slide in slides:
        want, ident = by_id[slide['id']], slide['id']
        if slide.get('title') != want['title']:
            problems.append({'code': 'design-mismatch', 'slide': ident, 'detail': (
                f'{ident}: its title differs from the approved design; revise the proposal '
                'before construction')})
        elif slide.get('intent') and digest(slide['intent']) != digest(want['intent']):
            problems.append({'code': 'design-mismatch', 'slide': ident, 'detail': (
                f'{ident}: its intent differs from the approved design; revise the proposal '
                'before construction')})
    if problems:
        raise Refusal(problems[0]['detail'] if len(problems) == 1 else
                      f'{len(problems)} slides differ from the approved design:\n'
                      + '\n'.join(problem['detail'] for problem in problems), *problems)
    return {'plan': session['plan'], 'revision': session['revision'],
            'scope': 'section' if section else 'deck', 'slides': ids}


def _classify(message: str) -> dict:
    if message.startswith('ENOENT'):
        return {'code': 'design-missing' if message.endswith("session.json'")
                else 'input-missing'}
    if 'is not valid JSON' in message:
        return {'code': 'input-invalid'}
    for pattern, code in KNOWN:
        if pattern.search(message):
            return {'code': code}
    return {'code': 'unclassified'}


def _shape(problem: dict, detail: str) -> dict:
    code = problem.get('code') if problem.get('code') in CODES else 'unclassified'
    recoverable, then = CODES[code]
    shaped = {'code': code, 'slide': problem.get('slide'), 'asset': problem.get('asset'),
              'provider': problem.get('provider'), 'detail': problem.get('detail') or detail,
              'recoverable': problem.get('recoverable', recoverable),
              'next': problem.get('next') or then}
    if problem.get('fallback'):
        shaped['fallback'] = {**problem['fallback'], 'needsApproval': True}
    return shaped


def refusal(error: Exception, revision: str | None) -> dict:
    """What --json prints on standard output when a design command refuses."""
    message, problems = str(error), getattr(error, 'problems', None) or []
    found = [_shape({**_classify(message), **problem}, message) for problem in problems] \
        or [_shape(_classify(message), message)]
    return {'schema': 1, 'status': 'blocked', 'designRevision': revision, 'problems': found}
