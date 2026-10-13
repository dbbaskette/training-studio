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
    slides.drive_check()                           # whether Google access reaches Drive
    slides.drive_import(deck, name)                # {'id', 'name', 'url'}

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
  is run; `stand_in()` gives a Slides backed by StandIn, which behaves like the real
  command for every call above, needs neither Node nor an installed skill, renders small
  real PNGs, and uses neither Drive nor LibreOffice.
"""
from __future__ import annotations

from workspace import WorkspaceError

VARIABLE = 'HARNESS_SLIDES_RUNTIME'
MINIMUM = '0.13.0'
RENDERERS = ('drive', 'local')


class Refused(WorkspaceError):
    """The slides tool said no. `problems` holds the lines it gave, one problem each."""

    def __init__(self, problems: list[str]):
        super().__init__('The slides tool refused: ' + ' '.join(problems))
        self.problems = problems


class Slides:
    def __init__(self, runtime=None, run=None):
        raise NotImplementedError


class StandIn:
    def __init__(self):
        raise NotImplementedError


def stand_in() -> Slides:
    raise NotImplementedError
