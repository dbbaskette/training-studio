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
    validate_package.py     package and disclosure checks
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

Tests named `test_row_NN` implement a row of the state-transition matrix in section A7 of the plan. A change to status, approval, inputs or readiness adds or updates a row and its test.

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
