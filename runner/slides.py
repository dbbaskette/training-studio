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
    report = slides.compile(composition, brand, folder=None)   # checks; with a folder, writes
    slides.merge(parts, composition)
    shown = slides.preview(compiled, folder, renderer, file_id=None, slide=None)
    slides.critique(preview_folder, assessment)
    made = slides.render(compiled, deck)
    slides.cited(compiled)                         # {objective: [slide numbers]}, from the scene
    slides.reading()                               # {name: text}: the tool's own guidance
    slides.drive_check()                           # whether Google access reaches Drive
    slides.drive_import(deck, name)                # {'id', 'name', 'url'}
    slides.designs()                               # whether it keeps a design session
    slides.design_propose(project, proposal, expected=None)   # with its question
    slides.design_status(project)
    slides.design_check(project)                   # {'plan', 'revision', 'buildAllowed'}
    slides.design_respond(project, reply)          # a person's answer to the question

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
- `Slides()` asks the tool for its version and refuses one older than MINIMUM.
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
MINIMUM = '0.13.1'
RENDERERS = ('drive', 'local')
SCRIPT = Path('scripts') / 'harness-slides.mjs'
TIMEOUT = 300    # a local preview may wait two minutes for LibreOffice, then draw each slide
LEAD = 'outline'  # what the tool cites on a cover, section or closing slide
PROGRAMS = {'soffice': 'HARNESS_SOFFICE', 'pdftoppm': 'HARNESS_PDFTOPPM',
            'pdfinfo': 'HARNESS_PDFINFO'}   # the variables the tool reads for each program
COUNTED = re.compile(r'^\d+ problems to fix:$')
NOISE = re.compile(r'^\((?:node:\d+\)|Use `node )')   # Node's own warnings, not the tool's
LEFT = re.compile(r'The preview deck is in Drive \((\S+)\); retry with --file-id (\S+?)\.$')
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

    def compile(self, composition: Path, brand: Path, folder: Path | None = None) -> dict:
        """Check a composition, a whole deck or one section. With a new folder, write what
        a preview and a render are made from."""
        args = ['compose', 'compile', '--file', str(composition), '--brand', str(brand)]
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
                file_id: str | None = None, slide: str | None = None) -> dict:
        """Render what was compiled and return each slide as a picture, in a new folder.
        `slide` names one slide to draw; the whole deck is still rendered."""
        if renderer not in RENDERERS:
            raise WorkspaceError(f'A preview is rendered through {RENDERERS[0]} or '
                                 f'{RENDERERS[1]}, not {renderer}.')
        args = ['compose', 'preview', '--file', str(compiled), '--output', str(folder),
                '--renderer', 'google' if renderer == 'drive' else 'local']
        if file_id and renderer == 'drive':
            args += ['--file-id', file_id]
        if slide:
            args += ['--slide', slide]
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

    def design_propose(self, project: Path, proposal: Path,
                       expected: str | None = None) -> dict:
        """Propose a design in `project`, a folder that exists, as one question for the
        whole plan. A changed proposal names the revision it replaces in `expected`. Slides
        whose approved design is unchanged keep their approval."""
        args = ['design', 'propose', '--project', str(project), '--file', str(proposal),
                '--mode', 'batch', '--json']
        return self._json(*args, *(['--expected', expected] if expected else []))

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
