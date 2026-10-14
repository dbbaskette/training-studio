# Development

Working agreements for this repository are in [AGENTS.md](../AGENTS.md). The specification is the [design](superpowers/specs/2026-10-12-training-studio-core-pipeline-design.md) and the build order is the [plan](superpowers/plans/2026-10-12-training-studio-core-pipeline.md).

## Layout

```
skills/training-studio/
  SKILL.md                  the entry: start or resume, and the loading map
  references/               one file per stage, mode and concern
  assets/examples/          one example per format; templates and test fixtures
  assets/profiles/          Yoodli's fields, limits and prerequisites, as data
  scripts/
    training.py             the command line
    workspace.py            the session record, status, approval, exports
    checks.py               format checks and readiness
    home.py                 the per-user data folder and the registry of trainings
    sync_guidance.py        fetches, pins and verifies guidance
    cmd_*.py                optional command modules, discovered automatically
    cmd_google.py           the `google` commands
    gdocs.py                the Google Docs round-trip: sync rules, comment anchors, transports
    cmd_hub.py              the hub commands
    hub.py                  the team hub: publish, find, get, share, sync
    cmd_desk.py             the desk command, which prints the link only to a terminal
    desk.py                 the page's local server: what it reads and the decisions it records
    computer.py             the check of this computer that the status screen asks for
    desk/                   the page: index.html, app.js, markdown.js and style.css
    validate_package.py     package and disclosure checks
runner/                     the runner: see its own section below
bootstrap/training-studio/  the small entry an installed copy uses
guidance/manifest.json      which script version the guidance needs
installer/                  install.sh, install.py and a double-click launcher
                            companions.json pins each companion skill to one revision
tests/                      unit tests; temporary directories only
docs/                       this documentation, the spec, the plan and reviews
```

## Run the tests

```bash
python3 scripts/ci/run_tests.py
```

That runs the whole suite in parallel, each test class in a process of its own, as many at a time as the computer has processors, the slowest classes first. It shows a class's output only when that class fails, ends with a count like unittest's, and exits non-zero on any failure. On a Mac it puts the real git first on `PATH`, because `/usr/bin/git` there asks `xcrun` for it on every call and the suite starts about twenty thousand. On a 12-core Mac it takes about two minutes, where plain unittest takes about nineteen.

Give it modules, classes or tests to run only those, `--jobs N` to change how many run at once, and `--times` to list every class with the time it took. When a class becomes one of the slowest, add it to `SLOW` at the top of the script so it is started early.

```bash
python3 scripts/ci/run_tests.py test_hub test_cli.CheckTests --times
```

Plain unittest still works, one test at a time, for the whole suite or any one module:

```bash
python3 -m unittest discover -s tests -v
cd tests && python3 -m unittest test_cli
```

The suite needs only Python 3.11 or newer. It uses no network, no harness skill and no outside account.

Every test that uses git keeps it from working in the background, which could still be writing when a test's temporary folder is removed. `GIT_CONFIG_COUNT` does not reach the receiving end of a push to a local path, so a test that writes a gitconfig writes it through `helpers.gitconfig`, which adds the settings that do.

Tests that open a local port are skipped where that is not allowed. Tests that run the page's own scripts, through `tests/page_harness.js`, need Node and are skipped without it; nothing else does.

```bash
python3 skills/training-studio/scripts/validate_package.py
```

The validator confirms the package is whole: required files exist, links resolve, and the progressive-disclosure rules hold.

## Continuous integration

Two workflows run on a pull request.

- **`ci.yml`** runs on GitHub's own runners: Ubuntu and macOS, Python 3.11 and 3.13.
- **`verify-tart.yml`** runs on disposable virtual machines on the owner's Mac, through an on-demand runner service kept outside this repository. It runs only for the owner's own pull requests from a branch of this repository, and only once that service has been told about this repository. Its filter is read from the base branch, never from the pull request.

Both run the same thing, `scripts/ci/check.sh`: the whole suite through `scripts/ci/run_tests.py`, then the package check.

That service pins the exact contents of every workflow here. **A change to either workflow file takes effect only after its new hash is recorded in the service's own configuration,** so say so in the pull request that makes one.

To run the suite by hand in a disposable macOS virtual machine, with Tart and the shared Tart test runner installed:

```bash
TRAINING_STUDIO_TART_BASE=<a stopped base> bash scripts/ci/tart-macos.sh --dry-run
```

Drop `--dry-run` to run it. The clone is deleted afterwards; its logs are kept.

## How the tests are organised

| File | Covers |
| --- | --- |
| `tests/test_workspace.py` | The state-transition matrix: status, approval, inputs, levels, exports, the lock |
| `tests/test_checks.py` | Each format check, run against the example files |
| `tests/test_cli.py` | The command line and readiness, including a course and a two-level training |
| `tests/test_package.py` | The validator, on a small synthetic package and on the real one |
| `tests/test_disclosure.py` | Every loading set against its budget |
| `tests/test_installer.py` | The installer, against a temporary home directory and a stand-in repository for each companion |
| `tests/test_sync.py` | Guidance sync, against a local git repository |
| `tests/test_google.py` | The Google Docs round-trip, against an in-memory transport and a stubbed HTTP layer |
| `tests/test_desk.py` | The page: what it reads and records, everything it refuses, the command, the check of this computer with its commands stubbed, and the page's scripts and colours |
| `tests/test_hub.py` | The team hub, against bare git repositories in temporary directories |
| `tests/test_runner_*.py` | The runner: workers with a scripted agent, the worker tools against a pretend web, the workspace against bare git repositories, research against a stand-in for harness-research, the slide deck against stand-ins for the slides tool and a brand skill, the pipelines, the engine and its server, and two people sharing one workspace |

The page's scripts are tested in a document that has no HTML parser, so a script that wrote markup would fail. That checks what the scripts build, name and send. It does not replace looking at the page in a browser.

Tests named `test_row_NN` implement a row of the state-transition matrix in section A7 of the plan. A change to status, approval, inputs or readiness adds or updates a row and its test.

## Working on the skill

Link your checkout so your assistant uses your changes as you make them:

```bash
sh installer/install.sh install --link
```

Bump `skills/training-studio/VERSION` when you release a change. The installed version is named by that number and a hash of every file.

## The main branch is live

New trainings fetch their guidance from `main`. Keep it usable at every commit. If guidance needs a script change, raise `minimum_runtime` in `guidance/manifest.json` and `skills/training-studio/VERSION` in the same change; older installs then keep their installed guidance and tell the user to update.

## Adding a command

Put a `cmd_<name>.py` beside `training.py`. It defines `register(commands)`, adds its sub-parsers, and sets each one's `handler` to a function taking `(args, root)` and returning the JSON to print. `training.py` finds it without being edited.

## Changing a format

A format lives in four places, and they change together:

1. the checker in `checks.py`,
2. its tests,
3. the example under `assets/examples/`, which the tests read,
4. the guidance that points to the example.

## Changing guidance

Guidance is loaded progressively. `SKILL.md` is the whole entry and links every reference and example itself, so nothing is more than one hop away. Each stage file carries the commands its stage needs.

Budgets are enforced. When a file goes over, cut it. Measured sizes are in [progressive disclosure](progressive-disclosure.md), regenerated with:

```bash
python3 skills/training-studio/scripts/validate_package.py --measure
```

Guidance names no harness-specific tools, so it runs on Claude Code and Codex alike.

## The runner

`runner/` is a program beside the skill, not part of it. It imports the helper's own modules and adds nothing to them except that the page's server can be given more addresses to answer. [The runner](runner.md) says what it does for a person; this is how it is put together.

```
runner/
  studio.py                 the command line: serve and status
  page.py                   the page's server, with the runner behind it
  setup.py, settings.py     this computer's workspace, agent and limits
  engine.py                 walks each training, hands out jobs, stops at gates
  pipeline.py               the pipelines as data, and where a training is in them
  agents.py                 starts Claude Code or Codex as a confined worker for one job
  worker_tools.py           the only tools a worker has, and the checks on what it hands back
  gitstate.py               the workspace: one folder in a git repository
  companion.py              finds a companion skill, and runs a command so Stop ends all of it
  research.py               the harness-research command line, called from Python
  documents.py              the documents a person supplies for research
  copies.py                 the Google Docs and Word files a training asked for
  index.py                  readiness, and README.md written from the record
  deck.py                   the runner's own rules for a deck, and what its workers are told
  slides.py                 the harness-slides command line, called from Python
  brand.py                  a brand skill on this computer, called from Python
  team.py                   sharing a workspace: the driver, notifications, publishing, bringing in
  briefs/                   what a worker is told for each kind of job
```

Three rules hold it together.

- **The next step is never remembered.** `pipeline.survey` works it out from the training's files each time, so a runner that is started again resumes every training. The run record holds only what the files cannot say.
- **A worker never holds the keys.** It gets an empty folder outside the workspace and the runner's own tools, and nothing else. Only what those tools accepted is kept, and it is saved through the core, which is the only thing that can approve, and only when the page says a person did.
- **Every rule about who may ask stays in the desk.** `runner/page.py` adds addresses to the page's server and never loosens one of its rules.

No test starts a real agent, the real harness-research, the slides tool or a brand skill. Each is replaceable: `agents.Scripted`, `research.StandIn`, `slides.StandIn` and `brand.StandIn`. A change to the engine or the pipelines is finished with one real training, through the page, on each agent it claims to support.

### The slide deck

- **Two wrappers, each with a stand-in.** `slides.py` and `brand.py` each wrap one command line and say in their docstrings what a caller gets back. `slides.stand_in()` and `brand.stand_in()` keep the real tools' rules: an outline is checked, a section is compiled, a preview is real pictures, the audit reads the deck. No brand's name is in this repository.
- **Two sets of tests.** `tests/test_runner_deck.py` drives the flow against small fakes in `tests/runner_support.py`, which make each kind of trouble easy to cause. `tests/test_runner_deck_whole.py` drives the same flow against the two stand-ins, with workers that use their tools as an agent would. A change to either wrapper or to the flow must pass both.
- **The deck's steps are the runner's own.** The core knows one file for the stage, the deck. What the deck says has a gate the runner keeps in its run record; gate 6 is the core's.
- **What is shared and what is not.** `deck-handoff.md`, `deck/outline.json`, `deck/review.json` and the deck are committed. Everything a deck is built with is under `work/deck/`, which is ignored: the exported brand, the tool's guidance, the sections, the builds and the pictures.
- **One tool, one brand skill.** The engine tells each deck job where the slides tool and the brand skill are, from `Slides.runtime` and `Brand.runtime`, so the worker tools' server uses the same two.
- **Previews are taken one at a time** on a computer, whoever is drawing, through one lock file in the runner's own data folder.
- **The tool's guidance is read, never copied here.** `Slides.reading()` reads the installed tool's own design and drafting guidance and its gallery, and the engine hands a worker the parts its job needs.

### The team

- **One driver, kept in the run record.** `team.ours` is the one question asked before anything is written to a training: in a shared workspace, does its record name this computer? Every change a person asks for goes through `engine.hold` first, and the engine works on nothing that is not this computer's. A workspace with no shared repository has no drivers, and `ours` is always true there.
- **A claim is pushed before any work.** `engine._take` and `engine._claimed` commit the claim and push it; a claim the shared repository does not take is dropped, and the refusal says who has the training.
- **What was never shared is set aside, never lost and never pushed.** `gitstate.set_aside` takes one training's unshared commits out of the branch and keeps them under `refs/training-studio/kept/`, in that computer's clone only. `gitstate.kept` lists them for the page.
- **A training someone else drives is `elsewhere`.** The engine says when it was last shared and where it stood then (`last_shared`), and never that it is working. Its commits tell it that; nothing asks the other computer.
- **A sentence a person reads is the runner's.** That a training was taken, or was changed on two computers, is `notice` on the run, the list and the status. The page shows it and keeps nothing of its own about it, so it is the same after a reload.
- **Two people are two data folders.** `TeamCase` in `tests/runner_support.py` gives each person a data folder and a git identity against one bare repository, and `tests/test_runner_team.py` drives two engines through it. `TeamScreenTests` in `tests/test_desk.py` drives the page against answers written out in the runner's shapes; when a shape changes, both change.
- **The installer brings the runner.** `installer/install.py` copies `runner/` beside the helper's scripts in each installed version, where `runner/__init__.py` finds them, and writes the launchers. Each companion is fetched at the commit `installer/companions.json` pins and installed by its own installer; `install.py pin` moves a pin.

## What is not yet verified

The automated suite covers the helper, the installer and the runner. It does not cover how an assistant follows the guidance. Live acceptance, described in increment 4 of the plan, is a real run through every gate on the harness you intend to use, plus building one roleplay in Yoodli. Its results belong in `docs/acceptance.md`.

## Phases and milestones

All five phases are built, each from its own specification:

1. [The core pipeline](superpowers/specs/2026-10-12-training-studio-core-pipeline-design.md), as a skill.
2. [Packaging](superpowers/specs/2026-10-12-phase-2-packaging.md): the installer.
3. [The Google Docs round-trip](superpowers/specs/2026-10-12-phase-3-google-round-trip.md).
4. [The team hub](superpowers/specs/2026-10-12-phase-4-team-hub.md).
5. [The page](superpowers/specs/2026-10-12-phase-5-training-desk.md).

The runner came after them, in milestones from [its design](superpowers/specs/2026-10-13-studio-runner-design.md): [approval on the page](superpowers/specs/2026-10-13-milestone-1-page-approval.md), [the runner's core](superpowers/specs/2026-10-13-milestone-2-runner-core.md), [the rest of a training](superpowers/specs/2026-10-13-milestone-3-rest-of-training.md), [the slide deck](superpowers/specs/2026-10-13-milestone-4-slides.md) and [the team](superpowers/specs/2026-10-13-milestone-5-team.md).
