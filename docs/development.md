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
    validate_package.py     package and disclosure checks
bootstrap/training-studio/  the small entry an installed copy uses
guidance/manifest.json      which script version the guidance needs
installer/                  install.sh, install.py and a double-click launcher
tests/                      unit tests; temporary directories only
docs/                       this documentation, the spec, the plan and reviews
```

## Run the tests

```bash
python3 -m unittest discover -s tests -v
```

The suite needs only Python 3.11 or newer. It uses no network, no harness skill and no outside account.

```bash
python3 skills/training-studio/scripts/validate_package.py
```

The validator confirms the package is whole: required files exist, links resolve, and the progressive-disclosure rules hold.

## How the tests are organised

| File | Covers |
| --- | --- |
| `tests/test_workspace.py` | The state-transition matrix: status, approval, inputs, levels, exports, the lock |
| `tests/test_checks.py` | Each format check, run against the example files |
| `tests/test_cli.py` | The command line and readiness, including a course and a two-level training |
| `tests/test_package.py` | The validator, on a small synthetic package and on the real one |
| `tests/test_disclosure.py` | Every loading set against its budget |
| `tests/test_installer.py` | The installer, against a temporary home directory |
| `tests/test_sync.py` | Guidance sync, against a local git repository |
| `tests/test_google.py` | The Google Docs round-trip, against an in-memory transport and a stubbed HTTP layer |

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

## What is not yet verified

The automated suite covers the helper. It does not cover how an assistant follows the guidance. Live acceptance, described in increment 4 of the plan, is a real run through every gate on the harness you intend to use, plus building one roleplay in Yoodli. Its results belong in `docs/acceptance.md`.

## Later phases

Phase 1 is the core pipeline as a locally linked skill. Packaging with an installer, a Google Docs round-trip, a shared Team Hub and a browsing desk are planned as separate phases, each with its own specification. See section 12 of the design.
