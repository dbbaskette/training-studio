"""The harness-slides command line, called from Python.

What a caller needs to know
---------------------------
    slides = Slides()                              # finds the installed tool, or refuses
    slides.version()
    slides.outline_contract(brand)                 # text a worker is told
    report = slides.outline_check(outline, brand)  # {'status', 'slides', 'delivery',
                                                   #  'wordBudget', 'words', 'findings'}
    slides.outline_start(outline, brand, folder)   # the tool splits the deck into sections
    slides.compose_contract(brand)                 # text a worker is told
    slides.layouts(brand)                          # {'default', 'layouts': [{'name', 'title',
                                                   #                           'subtitles', 'pictures'}]}
    report = slides.compile(composition, brand, folder=None, design=None, section=False)
                                                   # checks; with a folder, writes
    slides.merge(parts, composition)
    shown = slides.preview(compiled, folder, renderer, file_id=None, slide=None, design=None,
                           section=False)
    slides.critique(preview_folder, assessment)
    made = slides.render(compiled, deck)
    slides.cited(compiled)                         # {objective: [slide numbers]}, from the scene
    slides.reading()                               # {name: text}: the tool's own guidance
    slides.drive_check()                           # whether Google access reaches Drive
    slides.drive_import(deck, name)                # {'id', 'name', 'url'}
    slides.designs()                               # whether it keeps a design session
    slides.sections()                              # whether it checks a section against it
    slides.design_propose(project, proposal, expected=None, brand=None)   # with its question
    slides.design_status(project)
    slides.design_check(project)                   # {'plan', 'revision', 'buildAllowed'}
    slides.design_respond(project, reply)          # a person's answer to the question
    slides.capabilities()                          # what it says it has, or None
    slides.has('review-packets')                   # whether it says it has that one
    slides.lacks()                                 # what a new deck needs and it lacks
    slides.assets()                                # whether it keeps an asset manifest
    slides.asset_status(project, design=None)      # {'manifest', 'assets': [{..., 'state'}]}
    slides.asset_check(project, brand=None, design=None)   # {'status': 'ready', ...}, or
                                                   # Refused
    slides.asset_icon(project, icon, ident, alt=None, brand=None)
    slides.asset_supplied(project, file, ident, alt, source, kind='supplied',
                          restrictions=None)       # a person's picture, recorded
    slides.images_status()                         # whether an image provider is set up
    slides.generate_image(project, ident, prompt, output, slide, alt=None)
    slides.reviews()                               # whether it reviews a build against the design
    made = slides.review_prepare(compiled, output, design, renderer=None, file_id=None)
                                                   # renders output/deck.pptx
    slides.review_slide(output, slide)             # one slide's packet: criteria, prompts
    slides.review_packets(output)                  # every slide's packet, in one call
    slides.review_mark(output, revision, numbers, note)       # its pictures were looked at
    slides.review_assess(output, revision, assessment)        # with what is unresolved
    slides.design_present(project, output, revision)          # the deck put to the person

- `brand` is the path of an exported brand-contract.json. `outline`, `composition`, `parts`
  and `assessment` are paths of JSON files; `folder`, `compiled`, `preview_folder` and
  `deck` are paths. The tool refuses to write over anything, so every output path is new.
- Every call returns the tool's own JSON, or its text for a contract.
- When the tool says no, Refused is raised: a WorkspaceError that carries the lines it
  printed, one problem each, in `problems`. A compile that finds text that does not fit, or
  a check that fails, is a refusal with those lines; give them to the worker as they are.
- `preview` returns {'deck', 'deckSha256', 'contactSheet', 'renderer', 'fileId', 'url',
  'slides': [{'id', 'number', 'title', 'image', 'findings': [{'severity', 'code',
  'detail'}]}]}, where `image` is a PNG's path. `renderer` is 'drive' or 'local'. With
  'drive', pass the `file_id` an earlier preview returned so that one file is written again
  and no second one is made; a first preview makes the file.
- Previews through Drive must be taken one at a time: two at once cross their pictures.
  `preview` holds a lock of its own for that, so callers may call it from several threads.
- `critique` records one assessment for one preview and returns {'critical', 'major',
  'minor', 'status'}. The tool says 'clear' unless a finding is critical; the counts are
  what a caller should go by.
- `render` and `preview` never leave a deck behind that cannot be opened: when the tool
  fails after writing one, the file is removed before Refused is raised.
- `ready()` says, without starting anything that writes, what this computer has: the tool
  and its version, the programs it uses to turn a render into pictures, LibreOffice, and
  whether Google access reaches Drive. Each missing thing is a sentence for a person.
- The runtime is the folder named by HARNESS_SLIDES_RUNTIME when that is set, else the
  first usual install location that holds one. `Slides(run=...)` replaces how the command
  is run. The tests' stand-in, in tests/stand_ins/slides.py, behaves like the real command
  for every call above and needs neither Node nor an installed skill.

Added to the above
------------------
- `Slides()` asks the tool for its version and refuses one older than MINIMUM, the oldest
  a deck already begun keeps working with. What a new deck needs is said by capability and
  never by version: `lacks()` names each of NEEDED the tool lacks, in order, and NAMES says
  each as a person reads it. RELEASE is the release a person is told to update to, the one
  the installer pins.
- Paths in what a call returns are text, as the tool printed them. Where the tool leaves
  something out, `preview` gives None: `contactSheet` for one slide, `fileId` and `url` for
  a local render. What else the tool said is still there, `critic` among them.
- `cited` leaves out the tool's own mark on a cover, section or closing slide ('outline').
- `drive_check` is True or False. It is False too when Drive would not turn a PowerPoint
  file into slides, since previews and the finished deck both need that.
- A refusal by `preview` that had already written its file in Drive says so in `left`:
  {'fileId', 'url'}. Pass that `fileId` to the next preview, or a second file is made.
- `ready()` returns {'tool', 'version', 'pictures', 'local', 'drive', 'missing'}: four
  yes-or-no answers, the version, and the sentences. `ready(slides, which=...)` asks a given
  Slides, and looks for programs some other way, which is how a test asks. With
  `drive=False` Drive is not asked at all, and `drive` is None.
- Every call that writes removes what it wrote when it fails, so the same path can be
  tried again. Nothing that was there before the call is ever removed.
- `reading()` returns the guidance the tool's own workers are sent to read, as
  {name: text}: 'design guidance', 'composition guidance', 'drafting guidance', 'gallery'
  (what its examples are for), and 'example order', 'example contrast' and so on, one drawn
  slide for each relation the tool has an example of. They are files of the installed
  tool, read and never run, each from inside its folder and cut off at READ_MOST
  characters. One the installed version does not have is left out. A caller chooses which
  a worker needs; `example(relation)` is the name of one relation's example.
- The design session is the tool's record of what a person approved of how each slide is
  drawn, kept in `project`, a folder of the deck's own. `designs()` asks the tool whether it
  has the session as a deck's outline gate needs it: a proposal of schema 2, one question
  for the whole plan (`--mode batch`), and refusals as JSON. 0.13.1 has none of the three.
  Every design call asks for JSON, so a refusal of one carries `found`, each problem as
  {'code', 'slide', 'asset', 'provider', 'detail', 'recoverable', 'next', 'fallback'?},
  with `codes` and the design `revision` it named. Its lines are the details.
- `design_respond` sends a person's answer, and nothing else may: no worker is given it.
  The reply names the question and revision that were put to the person, so an answer to
  anything older is refused as `design-revision-stale`.
- `sections()` asks the tool whether it checks a build against the approved design one
  section at a time (`--section`), with refusals as JSON. 0.13.1 does not know `--section`.
  The tool is asked, as for `designs()`: `--section` without a design project is refused as
  JSON `input-invalid` before any file is read, so nothing is read or written.
- `compile` and `preview` with `design`, the design project, check the slides against the
  design approved there now: every approved slide in order, or with `section` a run of
  neighbouring ones, each with its approved title and, where a slide gives one, its
  approved `intent`. They then ask for refusals as JSON, so a `design-mismatch` names its
  slide in `found`. Without `design` the command is as 0.13.1 takes it.
- `capabilities()` is the set of names `version` lists, which a tool after 0.13.1 gives,
  or None for one that lists none. `designs()`, `sections()` and `assets()` read it first
  and ask the tool by a refusal only when it lists nothing; so does `lacks()`. `has(name)`
  is whether the list names it: a tool that lists nothing has none of them. A caller uses
  what a capability gives only where `has` says so, and does as before where it does not.
- The asset manifest is the tool's record of each picture and icon a deck may use, kept in
  `project`, the deck's design project. `assets()` says whether the tool keeps one: its
  capability `assets`, or for a tool that lists none, whether `assets status` of an empty
  folder that is thrown away answers as JSON. Every asset call asks for JSON, so a refusal
  carries `found` and `codes`, each problem with its `asset`, `provider` and `next`. The tool
  keeps the files, their hashes, alt text, sources and provenance; nothing here keeps a
  credential. `asset_supplied` is the person's alone: no worker is given it.
- `generate_image` asks the tool's own image provider, set up as the tool says, for the
  approved artwork of one slide drawn as generated art. The tool refuses any other slide.
- The design-bound review of a composition is `review --compiled` with `--design-project`:
  the tool renders the whole build itself into `output/deck.pptx`, which is the reviewed
  deck to deliver, and pictures each slide. `reviews()` is its capability `compose-review`;
  a tool that lists no capabilities has none, so nothing is asked by a refusal. Every review
  call asks for JSON. `review_prepare` returns the tool's summary: {'output', 'revision',
  'slides', 'pending', 'creativeReviewComplete', 'readyForUserReview', 'designReview',
  'qualityRevision', 'assessmentBinding', ...}; the record it wrote is `output/review.json`.
  `review_slide` returns {'revision', 'assessmentBinding', 'slide': the prompt, with its
  'criteria', 'objects', 'expectedText', 'sources' and any 'proseCards', 'findings'}, and
  checks the review's receipts first. `review_mark` records that the pictures were looked
  at, and `review_assess` records an assessment, a file of the shape the tool takes, and
  adds `unresolved`. A changed deck, picture, build or design revision is refused as
  `review-stale`, a changed asset copy as `asset-hash-changed`, and a computer without
  LibreOffice or Poppler as `renderer-unavailable`.
- Where the tool has them: `review_prepare` with `renderer` 'drive' renders through Google
  Drive (`review-google-renderer`), writing again the file `file_id` names, and returns
  its `fileId` and `url`; a refusal after the upload names that file in `left`.
  `review_packets` gives every slide's packet in one call (`review-packets`): {'revision',
  'assessmentBinding', 'designReview', 'slides': [{'number', 'id', 'planId', 'title',
  'image', 'imageSha256', 'mark', 'packet', 'findings'}]}, `packet` being what
  `review_slide` gives as `slide`. `design_present` puts a reviewed deck to the person in
  the design session, its unresolved findings listed (`design-present-findings`); only
  `design_respond` with the person's own answer approves it.
- `slides.runtime` is the folder the tool is installed in, with links followed. Give it to
  `Slides(runtime=...)` to use that same tool somewhere else, as the worker tools' server
  does. `Slides(read=...)` replaces how a guidance file is read.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path

import runner  # noqa: F401  puts the core on the import path
from workspace import WorkspaceError

from runner import companion

VARIABLE = 'HARNESS_SLIDES_RUNTIME'
MINIMUM = '0.13.1'      # the oldest runtime taken: a deck begun on it carries on there
RELEASE = '0.14.1'      # what a person is told to update to, as the installer pins it
# What a new deck needs of the slides tool, by the names its `version` lists.
NEEDED = ('design-schema-2', 'design-batch', 'json-refusals', 'compose-section', 'assets',
          'compose-review')
# Each capability, as a person reads it.
NAMES = {'assets': 'an asset manifest for the pictures and icons a deck uses',
         'assets-approved-candidates': 'checking every asset an approved design names',
         'canonical-digests': 'designs compared whatever order their keys are in',
         'compose-icon-assets': 'icons placed by the asset they are recorded as',
         'compose-review': 'a whole deck reviewed against its approved design',
         'compose-section': 'a section checked against the approved design',
         'design-batch': 'one question for a whole design',
         'design-icon-ids': 'an exact icon named in a design',
         'design-present-findings': 'a reviewed deck put to you with its findings',
         'design-schema-2': 'a design proposed with its words and its assets',
         'json-refusals': 'refusals a program can read',
         'native-charts': 'charts drawn as charts',
         'relative-records': 'records that move with the deck',
         'review-google-renderer': 'a review rendered through Google Drive',
         'review-input-refusals': 'a review asked wrongly refused plainly',
         'review-packets': "every slide's review given in one call",
         'review-sources-from-slide': 'an assessment that takes its sources from the slide'}
RENDERERS = ('drive', 'local')
SCRIPT = Path('scripts') / 'harness-slides.mjs'
TIMEOUT = 300    # a local preview may wait two minutes for LibreOffice, then draw each slide
LEAD = 'outline'  # what the tool cites on a cover, section or closing slide
PROGRAMS = {'soffice': 'HARNESS_SOFFICE', 'pdftoppm': 'HARNESS_PDFTOPPM',
            'pdfinfo': 'HARNESS_PDFINFO'}   # the variables the tool reads for each program
COUNTED = re.compile(r'^\d+ problems to fix:$')
NOISE = re.compile(r'^\((?:node:\d+\)|Use `node )')   # Node's own warnings, not the tool's
LEFT = re.compile(r'The (?:preview|review) deck is in Drive \((\S+)\); retry with '
                  r'(?:--renderer google )?--file-id (\S+?)\.$')
PREVIEWING = threading.Lock()   # one preview at a time, whoever asks
GUIDES = {'design guidance': 'design.md', 'composition guidance': 'compositions.md',
          'drafting guidance': 'draft.md', 'gallery': 'gallery.md'}   # under REFERENCES
REFERENCES = Path('references')
GALLERY = REFERENCES / 'gallery'    # one drawn slide for each relation, as JSON
READ_MOST = 60_000      # characters of one guidance file that are handed on
RELATIONS = ('order', 'dependency', 'hierarchy', 'membership', 'contrast', 'parallel',
             'overlap', 'quantity', 'none')   # what a slide can show, as the tool names them


class Refused(WorkspaceError):
    """The slides tool said no. `problems` holds the lines it gave, one problem each. When it
    was asked for its refusal as JSON, `found` holds each problem as the tool gave it and
    `revision` the design revision it named; otherwise `found` is empty."""

    def __init__(self, problems: list[str], refusal: dict | None = None):
        super().__init__('The slides tool refused: ' + ' '.join(problems))
        self.problems = problems
        self.found = list((refusal or {}).get('problems') or ())
        self.revision = (refusal or {}).get('designRevision')

    @property
    def codes(self) -> list[str]:
        """The code of each problem, in order, when the refusal came as JSON."""
        return [str(problem.get('code')) for problem in self.found]

    @property
    def left(self) -> dict | None:
        """The file a failed preview had already written in Drive, or None."""
        for line in self.problems:
            found = LEFT.search(line)
            if found:
                return {'fileId': found[2], 'url': found[1]}
        return None


def locations() -> list[Path]:
    """Where an installed harness-slides may be. The override, when set, is the only place
    looked."""
    return companion.locations(VARIABLE, 'harness-slides', 'Harness Slides')


def find_runtime() -> Path:
    """The installed harness-slides, with links followed so one version is used throughout.
    Refuses when there is none."""
    return companion.find_runtime(locations(), SCRIPT, VARIABLE, 'harness-slides',
                                  'a deck cannot be made')


def run_command(command: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """Run the command line once: (exit code, standard output, standard error)."""
    return companion.run_command(command, cwd, TIMEOUT, 'The slides tool')


def _numbers(version: str) -> tuple:
    return tuple(int(part) for part in re.findall(r'\d+', version)[:3])


def _blocked(out: str) -> dict | None:
    """A refusal the tool printed as JSON on its standard output, or None when it printed
    none."""
    try:
        found = json.loads(out)
    except ValueError:
        return None
    if not isinstance(found, dict) or found.get('status') != 'blocked' \
            or not isinstance(found.get('problems'), list) or not found['problems'] \
            or not all(isinstance(problem, dict) for problem in found['problems']):
        return None
    return found


def _problems(err: str, code: int) -> list[str]:
    """The tool's own lines: one problem alone, or each one listed under a count."""
    lines = [line.strip() for line in err.splitlines() if line.strip()]
    lines = [line for line in lines if not NOISE.match(line)]
    for index, line in enumerate(lines):
        if COUNTED.match(line):
            lines = lines[index + 1:]
            break
    return lines or [f'it ended with exit code {code}']


def _bound(design, section: bool) -> list[str]:
    """What compile and preview add to be checked against an approved design."""
    if design is None:
        if section:
            raise WorkspaceError('A section is checked against the approved design, so it '
                                 'needs the design project.')
        return []
    return ['--design-project', str(design), *(['--section'] if section else []), '--json']


@contextlib.contextmanager
def _new(path):
    """A file or folder a call is about to make. When the call fails, what it wrote is
    removed; what was already there is never touched."""
    path = Path(path)
    there = path.exists() or path.is_symlink()
    try:
        yield
    except BaseException:
        if not there and path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
        elif not there:
            path.unlink(missing_ok=True)
        raise


def example(relation: str) -> str:
    """What `reading()` calls the drawn example of one relation."""
    return f'example {relation}'


def read_guidance(runtime: Path, relative: Path) -> str | None:
    """One guidance file of an installed tool, as text, or None when it has no such file.
    Only a file inside the tool's own folder is read, links followed, and no more of it
    than READ_MOST characters. Nothing is run."""
    try:
        inside, file = Path(runtime).resolve(), (Path(runtime) / relative).resolve()
        if inside not in file.parents or not file.is_file():
            return None
        with file.open(encoding='utf-8', errors='replace') as handle:
            return handle.read(READ_MOST)
    except (OSError, RuntimeError):
        return None


class Slides:
    """The outline, compose and drive commands of one installed harness-slides. `runtime`
    is the folder it is installed in."""

    def __init__(self, runtime: Path | None = None, run=None, read=None):
        self.run = run or run_command
        self.read = read or read_guidance
        self.runtime = Path(runtime) if runtime else find_runtime()
        self.node = 'node' if run else shutil.which('node')
        self._designs: bool | None = None
        self._sections: bool | None = None
        self._assets: bool | None = None
        self._reviews: bool | None = None
        self._capabilities: frozenset | None = None
        self._asked_capabilities = False
        if self.node is None:
            raise WorkspaceError('harness-slides needs Node.js 20 or newer, which was not '
                                 'found on this computer. Install it, then try again.')
        found = self.version()
        if not _numbers(found):
            raise WorkspaceError('harness-slides did not say which version it is. Check '
                                 'that it is installed whole.')
        if _numbers(found) < _numbers(MINIMUM):
            raise WorkspaceError(f'harness-slides {found} is installed, and a deck needs '
                                 f'{MINIMUM} or newer. Update it, then try again.')

    def _call(self, *args: str) -> str:
        code, out, err = self.run([self.node, str(self.runtime / SCRIPT), *args])
        if code != 0:
            found = _blocked(out) if '--json' in args else None
            if found:
                raise Refused([str(problem.get('detail') or problem.get('code'))
                               for problem in found['problems']], found)
            raise Refused(_problems(err, code))
        return out

    def _json(self, *args: str) -> dict:
        try:
            found = json.loads(self._call(*args))
        except ValueError:
            found = None
        if not isinstance(found, dict):
            raise WorkspaceError('The slides tool answered with something other than the '
                                 'JSON it should. Check that it is installed whole.')
        return found

    def version(self) -> str:
        """The runtime's version, as it states it."""
        return self._call('--version').strip().rpartition(' ')[2]

    # --- the outline ---

    def outline_contract(self, brand: Path) -> str:
        """What an outline holds and how much a slide of this brand carries, as text."""
        return self._call('outline', 'contract', '--brand', str(brand)).strip()

    def outline_check(self, outline: Path, brand: Path) -> dict:
        """Check an outline. An outline that is not one is refused; one whose words need
        work comes back with `findings`, each {'slide', 'code', 'detail'}."""
        return self._json('outline', 'check', '--file', str(outline), '--brand', str(brand))

    def outline_start(self, outline: Path, brand: Path, folder: Path) -> dict:
        """Split an approved outline into its parts, in a new folder: a lead file for each
        run of cover, section and closing slides, a brief for each section of content
        slides, and parts.json, which lists them all in order."""
        with _new(folder):
            return self._json('outline', 'start', '--file', str(outline), '--brand',
                              str(brand), '--output', str(folder))

    # --- the composition ---

    def compose_contract(self, brand: Path) -> str:
        """How a slide is drawn and the sizes this brand gives, as text."""
        return self._call('compose', 'contract', '--brand', str(brand)).strip()

    def layouts(self, brand: Path) -> dict:
        """The layouts of the brand's template. One with `title` false shows no title."""
        return self._json('compose', 'layouts', '--brand', str(brand))

    def compile(self, composition: Path, brand: Path, folder: Path | None = None,
                design: Path | None = None, section: bool = False) -> dict:
        """Check a composition, a whole deck or one section. With a new folder, write what
        a preview and a render are made from. With `design`, it is checked against the
        design approved in that project: as the whole deck, or as one `section`."""
        args = ['compose', 'compile', '--file', str(composition), '--brand', str(brand),
                *_bound(design, section)]
        if folder is None:
            return self._json(*args)
        with _new(folder):
            return self._json(*args, '--output', str(folder))

    def merge(self, parts: Path, composition: Path) -> dict:
        """Join the files parts.json lists, which sit beside it, into one composition."""
        with _new(composition):
            return self._json('compose', 'merge', '--file', str(parts), '--output',
                              str(composition))

    def preview(self, compiled: Path, folder: Path, renderer: str,
                file_id: str | None = None, slide: str | None = None,
                design: Path | None = None, section: bool = False) -> dict:
        """Render what was compiled and return each slide as a picture, in a new folder.
        `slide` names one slide to draw; the whole deck is still rendered. With `design`,
        the build is checked first against the design approved there now, as `compile`
        checks it."""
        if renderer not in RENDERERS:
            raise WorkspaceError(f'A preview is rendered through {RENDERERS[0]} or '
                                 f'{RENDERERS[1]}, not {renderer}.')
        args = ['compose', 'preview', '--file', str(compiled), '--output', str(folder),
                '--renderer', 'google' if renderer == 'drive' else 'local']
        if file_id and renderer == 'drive':
            args += ['--file-id', file_id]
        if slide:
            args += ['--slide', slide]
        args += _bound(design, section)
        with PREVIEWING, _new(folder):
            shown = self._json(*args)
            if not shown.get('deck') or not isinstance(shown.get('slides'), list):
                raise WorkspaceError('The slides tool rendered a preview and did not say '
                                     'where its slides are. Check that it is installed '
                                     'whole.')
        return {**shown, 'renderer': renderer, 'contactSheet': shown.get('contactSheet'),
                'fileId': shown.get('fileId'), 'url': shown.get('url')}

    def critique(self, preview_folder: Path, assessment: Path) -> dict:
        """Record a reviewer's findings against the render they looked at. One preview
        takes one critique; a second is refused."""
        return self._json('compose', 'critique', '--file', str(preview_folder),
                          '--assessment', str(assessment))

    def render(self, compiled: Path, deck: Path) -> dict:
        """Write the deck as a new PowerPoint file. Its hash differs from a preview's deck
        of the same slides, so deliver the deck that was looked at."""
        with _new(deck):
            return self._json('compose', 'render', '--file', str(compiled), '--output',
                              str(deck))

    def cited(self, compiled: Path) -> dict:
        """Which slides cite each objective, by number, read from the compiled scene."""
        try:
            scene = json.loads((Path(compiled) / 'scene.json').read_text(encoding='utf-8'))
            found: dict = {}
            for number, slide in enumerate(scene['slides'], 1):
                for source in slide.get('sources') or []:
                    if source != LEAD and number not in found.setdefault(source, []):
                        found[source].append(number)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise WorkspaceError(f'{compiled} does not hold a compiled deck, so what its '
                                 'slides cite cannot be read. Compile the deck again.')
        return found

    # --- the design session ---

    def designs(self) -> bool:
        """Whether this tool keeps the design session a deck's outline is approved through:
        a proposal of schema 2, one question for the whole plan, and refusals as JSON. The
        tool is asked, not its version: a proposal from a file that is not there, in an empty
        folder that is thrown away, is refused as JSON by a tool that has all three, and
        nothing is written. The answer is kept."""
        listed = self.capabilities()
        if self._designs is None and listed is not None:
            self._designs = {'design-batch', 'design-schema-2', 'json-refusals'} <= listed
        if self._designs is None:
            try:
                with tempfile.TemporaryDirectory() as folder:
                    code, out, _ = self.run([
                        self.node, str(self.runtime / SCRIPT), 'design', 'propose',
                        '--project', str(Path(folder) / 'project'), '--file',
                        str(Path(folder) / 'none.json'), '--mode', 'batch', '--json'])
            except (WorkspaceError, OSError):
                code, out = 0, ''
            self._designs = code != 0 and _blocked(out) is not None
        return self._designs

    def sections(self) -> bool:
        """Whether this tool checks a section against the approved design, as a deck drawn
        from one needs: `--section` beside `--design-project` on compile and preview, with
        refusals as JSON. Asked as `designs` asks, and kept: `--section` alone is refused as
        JSON `input-invalid` by a tool that has it, before the file it names is read."""
        listed = self.capabilities()
        if self._sections is None and listed is not None:
            self._sections = {'compose-section', 'json-refusals'} <= listed
        if self._sections is None:
            try:
                with tempfile.TemporaryDirectory() as folder:
                    code, out, _ = self.run([
                        self.node, str(self.runtime / SCRIPT), 'compose', 'compile', '--file',
                        str(Path(folder) / 'none.json'), '--section', '--json'])
            except (WorkspaceError, OSError):
                code, out = 0, ''
            found = _blocked(out) if code != 0 else None
            self._sections = bool(found) and [problem.get('code') for problem
                                              in found['problems']] == ['input-invalid']
        return self._sections

    def capabilities(self) -> frozenset | None:
        """What the tool says it has, as `version` lists it, or None when it lists nothing,
        as 0.13.1 and the builds before the list do not. Asked once."""
        if not self._asked_capabilities:
            self._asked_capabilities = True
            try:
                found = json.loads(self._call('version'))
            except (WorkspaceError, OSError, ValueError):
                found = None
            listed = found.get('capabilities') if isinstance(found, dict) else None
            self._capabilities = frozenset(str(name) for name in listed) \
                if isinstance(listed, list) else None
        return self._capabilities

    def has(self, name: str) -> bool:
        """Whether the tool's `version` lists this capability. A tool that lists none has
        none of them."""
        return name in (self.capabilities() or ())

    def lacks(self) -> list[str]:
        """Each capability a new deck needs that this tool lacks, in the order of NEEDED.
        Read from what `version` lists; for a tool that lists nothing, the design session,
        the section check and the asset manifest are asked as `designs`, `sections` and
        `assets` ask, and a review against the design is lacking, since no such tool has
        it."""
        listed = self.capabilities()
        if listed is not None:
            return [name for name in NEEDED if name not in listed]
        found = {'compose-review'}
        if not self.designs():
            found |= {'design-schema-2', 'design-batch', 'json-refusals'}
        if not self.sections():
            found.add('compose-section')
        if not self.assets():
            found.add('assets')
        return [name for name in NEEDED if name in found]

    def assets(self) -> bool:
        """Whether this tool keeps an asset manifest a deck's pictures and icons are recorded
        in: its capability `assets`, or for a tool that lists none, whether `assets status` of
        an empty folder, thrown away after, answers as JSON. Nothing is written. Kept."""
        if self._assets is None:
            listed = self.capabilities()
            if listed is not None:
                self._assets = 'assets' in listed
            else:
                try:
                    with tempfile.TemporaryDirectory() as folder:
                        code, out, _ = self.run([
                            self.node, str(self.runtime / SCRIPT), 'assets', 'status',
                            '--project', folder, '--json'])
                    found = json.loads(out) if code == 0 else None
                except (WorkspaceError, OSError, ValueError):
                    found = None
                self._assets = isinstance(found, dict) and isinstance(found.get('assets'),
                                                                      list)
        return self._assets

    def design_propose(self, project: Path, proposal: Path, expected: str | None = None,
                       brand: Path | None = None) -> dict:
        """Propose a design in `project`, a folder that exists, as one question for the
        whole plan. A changed proposal names the revision it replaces in `expected`. Slides
        whose approved design is unchanged keep their approval. With `brand`, each icon the
        proposal names by its library ID is checked against the brand's library, which a
        tool with `design-icon-ids` does."""
        args = ['design', 'propose', '--project', str(project), '--file', str(proposal),
                '--mode', 'batch', '--json']
        return self._json(*args, *(['--expected', expected] if expected else []),
                          *(['--brand', str(brand)] if brand else []))

    def design_status(self, project: Path) -> dict:
        """Where the design of `project` stands, with the question waiting now."""
        return self._json('design', 'status', '--project', str(project), '--json')

    def design_check(self, project: Path) -> dict:
        """The approved design, which may be built. Refused until every slide is approved."""
        return self._json('design', 'check', '--project', str(project), '--json')

    def design_respond(self, project: Path, reply: dict) -> dict:
        """Record a person's answer: {'questionId', 'planRevision', 'decision',
        'feedback'}. Only what the person decided is ever sent."""
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'reply.json'
            file.write_text(json.dumps(reply, ensure_ascii=False), encoding='utf-8')
            return self._json('design', 'respond', '--project', str(project), '--file',
                              str(file), '--json')

    # --- the asset manifest ---

    def asset_status(self, project: Path, design: Path | None = None) -> dict:
        """Each asset recorded in `project`, as {'manifest', 'assets'}: each with its
        `assetId`, `kind`, `path` (none for an icon), `sha256`, `alt`, `source`,
        `restrictions`, `ref` (an icon's library ID), `provenance` and `state`: 'ok',
        'file-missing', 'hash-changed' or 'invalid'. With `design`, the design project, it
        adds `candidates`: {'resolved', 'pending'}, each {'slide', 'assetId', 'kind',
        'concept', 'ref'?}."""
        return self._json('assets', 'status', '--project', str(project),
                          *(['--design-project', str(design)] if design else []), '--json')

    def asset_check(self, project: Path, brand: Path | None = None,
                    design: Path | None = None) -> dict:
        """Refuse a recorded file that is missing or changed, and with `brand` an icon the
        brand's library no longer has as it was recorded. With `design`, also each asset the
        design names that is not recorded: on a tool with `assets-approved-candidates`,
        every one of the stored plan, approved or not."""
        return self._json('assets', 'check', '--project', str(project),
                          *(['--design-project', str(design)] if design else []),
                          *(['--brand', str(brand)] if brand else []), '--json')

    def asset_icon(self, project: Path, icon: str, ident: str, alt: str | None = None,
                   brand: Path | None = None) -> dict:
        """Record the brand icon `icon`, a library ID, as the asset `ident`. With `brand` the
        ID is checked against the brand's hashed icon index."""
        return self._json('assets', 'icon', icon, '--project', str(project), '--id', ident,
                          *(['--alt', alt] if alt else []),
                          *(['--brand', str(brand)] if brand else []), '--json')

    def asset_supplied(self, project: Path, file: Path, ident: str, alt: str, source: str,
                       kind: str = 'supplied', restrictions: str | None = None) -> dict:
        """Record a picture the person gave as the asset `ident`. A file from outside the
        project is copied into it; one inside is recorded as it is now."""
        return self._json('assets', 'add-supplied', str(file), '--project', str(project),
                          '--id', ident, '--alt', alt, '--source', source, '--kind', kind,
                          *(['--restrictions', restrictions] if restrictions else []),
                          '--json')

    def images_status(self) -> dict:
        """Whether the tool's image provider is set up: {'status', 'provider', 'steps'?}.
        It reads its own setup and asks nobody."""
        return self._json('images', 'status', '--json')

    def generate_image(self, project: Path, ident: str, prompt: str, output: str, slide: str,
                       alt: str | None = None) -> dict:
        """Have the tool's image provider make the approved artwork of `slide` from the
        brief `prompt`, at `output` inside the project's assets folder, and record it as the
        asset `ident`. A request made again with the same brief costs nothing more."""
        with tempfile.TemporaryDirectory() as folder:
            brief = Path(folder) / 'brief.txt'
            brief.write_text(prompt, encoding='utf-8')
            return self._json('images', 'generate', '--project', str(project), '--id', ident,
                              '--prompt-file', str(brief), '--output', output,
                              '--design-project', str(project), '--slide', slide,
                              *(['--alt', alt] if alt else []), '--json')

    # --- the design-bound review of a composition ---

    def reviews(self) -> bool:
        """Whether this tool reviews a whole compiled deck against its approved design and
        renders the deck it reviews: its capability `compose-review`. A tool that lists no
        capabilities has none, so it is not asked by a refusal."""
        if self._reviews is None:
            self._reviews = 'compose-review' in (self.capabilities() or ())
        return self._reviews

    def review_prepare(self, compiled: Path, output: Path, design: Path,
                       renderer: str | None = None, file_id: str | None = None) -> dict:
        """Render a whole deck compiled against the design approved in `design` into
        `output/deck.pptx`, picture each slide, and prepare its creative review. An unchanged
        build keeps its deck and its receipts. Renders are taken one at a time. With
        `renderer` 'drive' it is rendered through Google Drive, writing again the file
        `file_id` names when one is given; otherwise with LibreOffice."""
        args = ['review', '--compiled', str(compiled), '--output', str(output),
                '--design-project', str(design)]
        if renderer == 'drive':
            args += ['--renderer', 'google', *(['--file-id', file_id] if file_id else [])]
        with PREVIEWING:
            made = self._json(*args, '--json')
        return {**made, 'fileId': made.get('fileId'), 'url': made.get('url')}

    def review_slide(self, output: Path, slide: str) -> dict:
        """One slide's part of a prepared review, by its ID, once its receipts are checked."""
        return self._json('review', '--output', str(output), '--slide', slide, '--json')

    def review_packets(self, output: Path) -> dict:
        """Every slide's part of a prepared review, in deck order, once its receipts are
        checked: one call in place of one for each slide."""
        found = self._json('review', '--output', str(output), '--packets', '--json')
        if not isinstance(found.get('slides'), list):
            raise WorkspaceError('The slides tool gave a review without its slides. Check '
                                 'that it is installed whole.')
        return found

    def review_mark(self, output: Path, revision: str, numbers: list[int], note: str) -> dict:
        """Record that the pictures of these slides were looked at, for this revision."""
        return self._json('review', '--output', str(output), '--mark',
                          ','.join(str(number) for number in numbers), '--revision', revision,
                          '--note', note, '--json')

    def review_assess(self, output: Path, revision: str, assessment: dict) -> dict:
        """Record a creative assessment of this revision: every criterion of every slide."""
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'assessment.json'
            file.write_text(json.dumps(assessment, ensure_ascii=False), encoding='utf-8')
            return self._json('review', '--output', str(output), '--assessment', str(file),
                              '--revision', revision, '--json')

    def design_present(self, project: Path, output: Path, revision: str) -> dict:
        """Put the deck a review in `output` rendered, of this review revision, to the person
        as the design session's rendered question, with what its assessment leaves unresolved
        listed. Returns the design's status, with that question."""
        return self._json('design', 'present', '--project', str(project), '--output',
                          str(output), '--revision', revision, '--accept-findings', '--json')

    # --- what the tool's own workers read ---

    def reading(self, brand: Path | None = None) -> dict:
        """The tool's guidance for whoever writes an outline or draws a slide, as
        {name: text}. It is the same for every brand, so `brand` changes nothing."""
        wanted = {name: REFERENCES / file for name, file in GUIDES.items()}
        wanted.update({example(relation): GALLERY / f'{relation}.json'
                       for relation in RELATIONS})
        found = {name: self.read(self.runtime, relative) for name, relative in wanted.items()}
        return {name: text for name, text in found.items()
                if isinstance(text, str) and text.strip()}

    # --- Google Drive ---

    def drive_check(self) -> bool:
        """Whether Google access reaches Drive and Drive turns PowerPoint into slides. It
        reads one fact about the account and changes nothing."""
        try:
            found = self._json('drive', 'check')
        except Refused:
            return False
        return bool(found.get('account')) and found.get('pptxImportAdvertised') is not False

    def drive_import(self, deck: Path, name: str) -> dict:
        """Put a deck in Drive as Google Slides. It is not tried twice: an upload that
        failed may still have made a file."""
        return self._json('drive', 'import', '--file', str(deck), '--name', name)


def ready(slides: Slides | None = None, which=shutil.which, drive: bool = True) -> dict:
    """What this computer has for a deck. Nothing is written; Drive is asked one question,
    unless `drive` is False: then it is not asked, and `drive` is None."""
    asking = drive
    version, missing = None, []
    try:
        slides = slides or Slides()
        version = slides.version()
        if which('python3') is None:
            raise WorkspaceError('harness-slides writes a deck with python3, which was not '
                                 'found on this computer. Install Python 3, then try again.')
    except WorkspaceError as problem:
        slides = None
        missing.append(str(problem))

    def has(program: str) -> bool:
        return which(os.environ.get(PROGRAMS[program]) or program) is not None

    pictures, local = has('pdftoppm') and has('pdfinfo'), has('soffice')
    drive = False if asking else None
    if slides is not None and asking:
        try:
            drive = slides.drive_check()
        except WorkspaceError:
            drive = False
    if not pictures:
        missing.append('Poppler (pdftoppm and pdfinfo) was not found, so a render cannot be '
                       'turned into pictures. Install Poppler, then try again.')
    if not local:
        missing.append('LibreOffice was not found, so previews cannot be rendered on this '
                       'computer. Install it, or render previews through Google Drive.')
    if slides is not None and drive is False:
        missing.append('Google access does not reach Drive, so previews cannot be rendered '
                       'there. Run `gcloud auth login --enable-gdrive-access`, or render '
                       'previews with LibreOffice.')
    return {'tool': slides is not None, 'version': version, 'pictures': pictures,
            'local': local, 'drive': drive, 'missing': missing}
