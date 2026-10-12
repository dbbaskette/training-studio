# Training Studio Core Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Training Studio skill: a Python helper that tracks one training's artifacts, approvals, exports and readiness in the directory the harness is launched in, and the guidance that takes a topic through research, a blueprint, a learner guide, a brief, a deck and practice scenarios.

**Architecture:** One directory is one training. A standard-library Python CLI keeps a session record, content-addressed history and computed status (`workspace.py`) and runs format checks and a readiness report (`checks.py`). The pipeline is guidance: a router `SKILL.md` that loads one reference per stage. Research is delegated to `harness-research` and decks to `harness-slides`; the helper never calls them or the network.

**Tech Stack:** Python 3.11+ standard library (`argparse`, `hashlib`, `json`, `os`, `pathlib`, `re`, `unittest`). Markdown guidance. No third-party packages.

**Spec:** [docs/superpowers/specs/2026-10-12-training-studio-core-pipeline-design.md](../specs/2026-10-12-training-studio-core-pipeline-design.md), revision 2. Section numbers below refer to it.

---

## How this plan is organised

This is revision 2. It follows the [review](../../reviews/2026-10-12-core-pipeline-review.md): four increments in place of seventeen tasks, contracts in place of embedded code, and a state-transition matrix whose rows are tests.

- **Contracts first.** Part A fixes the interfaces, formats and algorithms. Code appears only where it settles a contract.
- **Tests before code, by increment.** Within an increment, write the tests for a contract, then the code. Run the targeted tests named at each milestone. Run the whole suite once at the end of increment 4.
- **Revision 1 is reusable.** Commit `1b5fc03` holds a complete, tested implementation of the previous design inside the old plan (101 tests passing). Recover it with `git show 1b5fc03:docs/superpowers/plans/2026-10-12-training-studio-core-pipeline.md`. The parts marked "carry over" below can be lifted from it; everything else is new or changed.
- **No training content in this repository.** Tests use temporary directories. Live acceptance uses directories outside it.
- **Commit at each milestone.** If the host's sandbox refuses a git write, rerun it through the host's permission flow.

## Part A: Contracts

### A1. Files

| File | Responsibility |
| --- | --- |
| `skills/training-studio/scripts/workspace.py` | Session record, artifact map, inputs, saves, history, status, approval, exports, skip, checkpoint, pin, lock |
| `skills/training-studio/scripts/checks.py` | Pure functions: blueprint lint; brief, scenario and Yoodli checks; coverage; readiness |
| `skills/training-studio/scripts/training.py` | Command line: parsing, dispatch, structured errors, the `check` aggregation |
| `skills/training-studio/scripts/validate_package.py` | Required files exist; guidance links resolve; disclosure budgets and the one-hop rule hold; `--measure` prints the table (A9) |
| `skills/training-studio/assets/profiles/yoodli.json` | Yoodli types, fields, prerequisites and limits, with provenance |
| `skills/training-studio/assets/examples/` | `blueprint.md`, `document.md`, `competitive-brief.md`, `product-brief.md`, `scenario.md`, `yoodli.md` |
| `skills/training-studio/SKILL.md`, `agents/openai.yaml`, `references/**` | Guidance (A8) |
| `tests/helpers.py` | Import path, temporary training directory, builders, sample data |
| `tests/test_workspace.py` | The state-transition matrix (A7) |
| `tests/test_checks.py` | Format checks against the examples (A5) |
| `tests/test_cli.py` | The CLI in a subprocess, including readiness |
| `tests/test_package.py` | The package validator |
| `tests/test_disclosure.py` | Each loading set in A9 fits its budget |
| `docs/progressive-disclosure.md` | The measured table of files and loading sets |

### A2. Artifacts, stages and inputs

Stages: `intake`, `research-plan`, `research`, `blueprint`, `document`, `brief`, `deck`, `scenario`, `package`, `done`. Skippable: `document`, `brief`, `deck`, `scenario`.

| Artifact | File | Stage | Inputs |
| --- | --- | --- | --- |
| `intake` | `intake.md` | intake | none |
| `research-plan` | `.training-studio/research-plan.json` | research-plan | `intake` |
| `research` | `.harness-research/research-report.md` | research | `research-plan` |
| `blueprint` | `blueprint.md` | blueprint | `intake`, `research` |
| `document` | `document.md` | document | `blueprint` |
| `brief` | `competitive-brief.md` or `product-brief.md`, by `settings.brief_kind` | brief | `blueprint`, `research`, `setting:brief_kind` |
| `deck` | `deck-link.md` when `settings.deck_target` is `google`, else `deck.pptx` | deck | `blueprint`, `document` (or `research` when document is skipped), `setting:deck_target`, `setting:brand` |
| `scenario:<id>` | `scenario.md` for `main`, else `scenarios/<id>.md` | scenario | none |
| `yoodli:<id>` | `yoodli/<id>.md` | scenario | `blueprint`, `brief`, `scenario:<id>`, `profile` |

`inputs(root, session, name)` returns one dictionary: each upstream artifact name mapped to the SHA-256 of its file (or `None` if missing), each `setting:<key>` mapped to its value, and `profile` mapped to the SHA-256 of `assets/profiles/yoodli.json`. This dictionary is what `built_from` and `approved.inputs` store.

Two module-level paths in `workspace.py` are resolved from the script's own location: `SKILL_DIR`, the package the helper runs from, and `PROFILE`, the Yoodli profile inside it. Tests point them at temporary copies to exercise rows 15 and 37 of A7.

Scenario discovery, computed on every read: `scenario.md` is `main`; `scenarios/<id>.md` where `<id>` matches `^[a-z0-9][a-z0-9-]{0,63}$`. Both `scenario.md` and `scenarios/main.md` present is a refusal. Other files under `scenarios/` are reported as ignored. Artifact names are the fixed ones plus `scenario:<id>` and `yoodli:<id>` for every ID that is discovered or already recorded in the session, so a removed scenario stays visible.

Skip rule: `brief` can be skipped only when `scenario` is skipped; `scenario` can be restored only when `brief` is wanted.

### A3. Status and approval

```python
def _status(root, session, name, known):
    spec = artifact(root, session, name)
    if spec['stage'] in SKIPPABLE and spec['stage'] not in session['settings']['stages']:
        return 'skipped'
    if spec['stage'] in session['unavailable']:
        return 'unavailable'
    current = sha256_file(root / spec['file'])
    if current is None:
        return 'not-started'
    entry = session['artifacts'].get(name)
    if entry is None:
        return 'draft'
    if any(known[upstream] == 'stale' for upstream in spec['upstream']):
        return 'stale'
    if entry['built_from'] != inputs(root, session, name):
        return 'stale'
    approved = entry.get('approved')
    if (approved and approved['sha256'] == current
            and approved['inputs'] == entry['built_from']
            and (name != 'research' or research_intact(root, session))):
        return 'approved'
    return 'draft'
```

`research_intact` is true when the record `.harness-research/research.json` and the copy `research-report.md` both hash to what `session['research']` recorded at approval.

`save(root, name, source=None, built=False, coverage=None)`:

- `source` given: refuse for `research`; validate every input exists; snapshot the on-disk file to history; replace it atomically; record with inputs re-pinned.
- `built=True`: record the on-disk file with inputs re-pinned.
- neither: record the on-disk file and keep `built_from` (pin it only if there is no record yet).
- `coverage` (deck only): validate that every key is an objective in the blueprint and every value is a list of positive integers; store `{deck_sha256, blueprint_sha256, at, objectives}`.
- Saving the blueprint updates `modules` and `size`.

`approve(root, name, accept_stale=None)`:

1. Refuse if the artifact is skipped or unavailable, or its file is missing.
2. Refuse if any upstream artifact is neither approved nor skipped.
3. Record the on-disk content as a hand edit (history snapshot, new hash, inputs kept).
4. If `built_from` differs from the current inputs: refuse without a reason; with one, append `{at, artifact, decision: 'accepted-stale', from, to, reason}` to `decisions` and re-pin.
5. Set `approved = {sha256, inputs, at}`.
6. For `research`: require the record's `schema == 1` and `owner == 'harness-research'` (otherwise findings are `None` with a warning); store `session['research'] = {report_sha256, record_sha256, run}`; copy the report to `research-report.md`; store the findings index; warn about pending questions.

`export(root, name, file=None, unavailable=None)` applies to `document`, `brief` and `yoodli:<id>`. The default file is the source path with `.docx`. It stores `{file, source_sha256, sha256, at}` or `{unavailable: reason, at}`. Export state is `current`, `outdated` (the source hash or the export's own hash no longer matches), `missing` (no record, or the file is gone) or `unavailable`.

### A4. Command line

All commands print JSON. A refusal, malformed JSON, a missing or unreadable file and a permission error all print `{"error": "..."}` and exit 2. `--dir PATH` before the command selects another directory.

| Command | Flags |
| --- | --- |
| `init` | `--title T` (required), `--brief-kind product\|competitive` (default `product`), `--deck-target pptx\|google`, `--brand B` |
| `status` | none. Output adds `scenarios` (`found`, `ignored`) and each artifact's `export` state |
| `save ARTIFACT` | `--from FILE` or `--built` (mutually exclusive), `--coverage FILE` |
| `approve ARTIFACT` | `--accept-stale REASON` |
| `export ARTIFACT` | `--file PATH` or `--unavailable REASON` |
| `skip STAGE` | `--reason R`, `--unavailable`, `--clear` |
| `checkpoint` | `--stage`, `--next`, `--question` or `--no-question`, `--deck-target`, `--brand`, `--brief-kind` |
| `pin SKILL` | `--task`, `--runtime`, `--run` |
| `check` | `--complete`, `--all`. Exit 1 if any check failed; with `--complete`, exit 1 unless ready. Lists only the checks that did not pass unless `--all` is given |

`check` output:

```json
{
  "checks_passed": false,
  "ready": false,
  "blocking": ["document is draft", "document.coverage failed", "No scenario file found"],
  "limitations": ["deck unavailable: harness-slides is not installed"],
  "passed": 4,
  "checks": [{"check": "document.coverage", "status": "failed", "basis": "declared",
              "problems": ["O2 is not covered by any section."]}],
  "practice": {"exercised": ["O2", "O3"], "not_exercised": ["O1"]},
  "warnings": []
}
```

`status` returns one status per artifact as a flat map. Neither command returns the session record or its event log.

Readiness (spec 6.7):

- Every artifact of a wanted stage must be `approved`; otherwise `blocking` gets `<artifact> is <status>`.
- A wanted scenario stage with no scenario file is blocking.
- A failed check is blocking. A check that could not run is blocking, unless it belongs to a skipped or unavailable stage.
- An `outdated` export is blocking. When the scenario stage is wanted, the brief's export must be `current`; if it is `unavailable`, that is a limitation reading "Yoodli handoff incomplete: no brief export"; if `missing`, it is blocking.
- Skipped and unavailable stages, and other `missing` or `unavailable` exports, are limitations.
- `ready` is true when `blocking` is empty.

### A5. Formats and checks

Every format has an example under `assets/examples/`. The example is the template the guidance links to and the fixture the tests read.

**Blueprint.** As revision 1, with two changes. The assessment line is `- O1: Check: <question> | Observe: <what practice should show>`. The section `## Practice plan` replaces `## Interactive plan`; each line is `- <scenario-id>: <mode>. Objectives: O2, O3. <note>`, and the section is optional. Checks: `blueprint.structure`, `blueprint.objectives`, `blueprint.key-points`, `blueprint.citations`. A practice-plan line with an unknown mode or objective fails `blueprint.structure`. Carry over the parser and lint from revision 1 and drop the per-module mode requirement.

**Document.** As revision 1. The check is renamed `document.coverage` and its result carries `"basis": "declared"`.

**Brief.** Title `# Competitive brief: <title>` or `# Product brief: <title>`. Numbered sections, in order:

| # | Competitive | Product | Evidence section |
| --- | --- | --- | --- |
| 1 | Executive summary | Executive summary | no |
| 2 | Comparison | What it is and where it fits | yes |
| 3 | Differentiators | Capabilities | yes |
| 4 | Limitations | Limitations | yes |
| 5 | Qualification questions | Qualification questions | yes |
| 6 | Objections and responses | Objections and responses | yes |
| 7 | Unknowns | Unknowns | no |
| 8 | Sources | Sources | no |

An evidence section names its findings in `<!-- findings: licensing migration-effort -->` under its heading.

- `brief.sections`: every section for the kind is present, in order, and not empty.
- `brief.findings`: every evidence section names at least one finding; each exists in the findings index and is `supported`, except that section 6 may also name `contradicted` findings. `unavailable` when there is no findings index.

**Scenario.** Title `# Scenario: <name>`. Required sections: `## Situation`, `## Learner role`, `## AI role`, `## Opening`, `## Success criteria`. Optional: `## Mode`, `## Concerns and pushback`, `## Questions`, `## Constraints`, `## Session settings`. Success criteria are list items, numbered by their order from 1.

- `scenario:<id>.sections`: required sections present and not empty; at least one success criterion; `Mode`, if present, is one of the four modes.

**Yoodli scenario.** First line after the title: `<!-- scenario: <id> -->`. Headings and fenced `text` blocks as revision 1: `## Roleplay name`, `## Type`, `## Description`, `## Context`, `## Personas` with `### Persona N` and `#### Name`, `Role`, `Demeanor`, `Background`, `Behaviors`, `## Objections`, `## Goals` with `### Goal N` and `#### Name`, `Type`, `Explanation`, `Achieved`, `Missed`, then `## AI assets`, `## Knowledge-based goal source`, `## Settings`. Under each `### Goal N`, outside the blocks: `<!-- criterion: 2 -->` (required, one or more numbers) and `<!-- assesses: O3 -->` (optional).

- `yoodli:<id>.fields`: required fields present; every persona has all five fields; the type equals `profile.mode_types[mode]` for the scenario's mode; goal types are in the profile; no duplicate heading path; no unterminated fence.
- `yoodli:<id>.limits`: every limited field is within its limit. The result carries `counts`.
- `yoodli:<id>.mapping`: every success criterion number in the scenario file appears in some goal's `criterion` comment; no goal names a criterion out of range; every `assesses` objective exists in the blueprint.

**Coverage and practice.**

- `deck.coverage`: `unavailable` unless a review is recorded and its `deck_sha256` and `blueprint_sha256` match the current files; then failed for any objective with no slides. Carries `"basis": "reviewed"`.
- `practice` (not a check): the objectives named by `assesses` comments across all Yoodli scenarios, and those not named. A `handle` objective that no scenario exercises adds a warning.

### A6. Yoodli profile

```json
{
  "schema": 1,
  "profile": "yoodli",
  "types": ["Custom", "Tutor", "Pitch", "Objection Handling", "Questionnaire", "Interview"],
  "mode_types": {"roleplay": "Objection Handling", "pitch": "Pitch", "tutor": "Tutor", "questionnaire": "Questionnaire"},
  "persona_fields": ["Name", "Role", "Demeanor", "Background", "Behaviors"],
  "persona_required_types": ["Objection Handling", "Pitch"],
  "goal_types": ["Binary", "Rated", "Compound", "Knowledge-Based", "Screenshare"],
  "prerequisites": [
    "Builder: a role that can create roleplays in the organisation",
    "Roleplay Agent: organisation access and the Conversational Roleplay feature"
  ],
  "roleplay_agent": {
    "creates_custom_goals": false,
    "files_max": 5,
    "urls_max": 1,
    "source": "https://support.yoodli.ai/en/articles/15960287-create-roleplays-with-roleplay-agent"
  },
  "limits": {
    "context_chars": {"value": 10000, "source": "https://support.yoodli.ai/en/articles/9048809-yoodli-release-notes", "retrieved": "2026-10-12", "verified": null}
  }
}
```

`limits` has an entry of the same shape (`value`, `source`, `retrieved`, `verified`) for `personas_max`, `goal_explanation_chars`, `goal_achieved_chars` and `goal_missed_chars`, with the sources in Appendix A of the spec. `verified` is the date a limit was confirmed in the live builder, `null` until then. The check functions take the profile as an argument, so tests pass both a profile with every limit verified and one with none. The "provisional" warning appears when any limit used is unverified.

Before writing the profile, re-read the Roleplay Agent and AI Assets pages cited in the review and record only what they state.

### A7. State-transition matrix

Each row is one test in `tests/test_workspace.py` or, where it names `check`, `tests/test_cli.py`. "Approved chain" means intake, research-plan, research, blueprint and document built and approved in order.

| # | Given | When | Then |
| --- | --- | --- | --- |
| 1 | Approved chain | `blueprint.md` edited by hand | blueprint `draft`; document `stale` |
| 2 | Row 1, then blueprint approved | `save document --built`, bytes unchanged | document `draft`, not `approved` |
| 3 | Row 1, then blueprint approved | plain `save document` | document still `stale` |
| 4 | Row 1, then blueprint approved | `approve document` | refused |
| 5 | Row 1, then blueprint approved | `approve document --accept-stale R` | `approved`; decision holds old inputs, new inputs and R |
| 6 | Approved chain | intake edited and approved; `approve research-plan --accept-stale R` | plan `approved`; research `approved`; blueprint `stale` |
| 7 | Research approved | `research-report.md` edited | research `draft`; blueprint `stale` |
| 8 | Research approved | `.harness-research/research.json` changed | research `draft` |
| 9 | Research approved | live report changed | research `draft`; blueprint `stale` |
| 10 | Research record with `schema` 2 or another `owner` | `approve research` | findings `None`; warning returned |
| 11 | Deck approved | brand changed | deck `stale`; document and brief unchanged |
| 12 | Deck approved as `deck.pptx` | deck target set to `google` | deck `not-started` |
| 13 | Brief approved as product | brief kind set to `competitive` | brief `not-started` |
| 14 | `yoodli:main` approved | `scenario.md` edited | `scenario:main` `draft`; `yoodli:main` `stale`; document and brief unchanged |
| 15 | Two Yoodli scenarios approved | the profile file changes | both `stale`; nothing else changes |
| 16 | No scenario files | `scenarios/exec-cost.md` created | `scenario:exec-cost` `draft` and `yoodli:exec-cost` `not-started` are listed |
| 17 | `yoodli:exec-cost` approved | its scenario file deleted | scenario `not-started`; Yoodli `stale`; both still listed |
| 18 | `scenario.md` and `scenarios/main.md` both exist | `status` | refused as ambiguous |
| 19 | `scenarios/Draft Notes.md` and `notes.md` exist | `status` | the first is listed as ignored; neither is an artifact |
| 20 | Deck saved with coverage | deck replaced | `deck.coverage` `unavailable` |
| 21 | Deck saved with coverage | blueprint changed | `deck.coverage` `unavailable` |
| 22 | Coverage file names an unknown objective, or slide 0 | `save deck --coverage` | refused; nothing recorded |
| 23 | Document export recorded | `document.md` edited | export `outdated` |
| 24 | Export recorded | export file deleted | export `missing` |
| 25 | Brief export recorded unavailable, scenario wanted | `check` | limitation "Yoodli handoff incomplete"; not blocking |
| 26 | Blueprint with M1 and M2 saved | blueprint saved with M1 only | `modules` is `['m1']`; `size` is `lesson` |
| 27 | Document approved | `document.md` deleted | document `not-started`; `ready` false |
| 28 | Everything approved, stage `done` | an approved file edited | `ready` false |
| 29 | Scenario wanted | `skip brief` | refused |
| 30 | Scenario and brief skipped | `skip scenario --clear` | refused until brief is restored |
| 31 | Deck marked unavailable, everything else approved | `check --complete` | `ready` true; deck listed under limitations |
| 32 | Blueprint only | `check` | `checks_passed` true; `ready` false; blocking names the missing artifacts |
| 33 | Lock held by a live process | any command that changes state | refused; record unchanged |
| 34 | Lock left by a process that no longer exists | a command that changes state | succeeds |
| 35 | `session.json` is not JSON, or lacks a required key | any command | `{"error": …}`, exit 2; file unchanged |
| 36 | A managed file is a symbolic link | `save` | refused |
| 37 | The directory is, or contains, the skill package the helper runs from | `init` | refused |
| 38 | A deliverable's name is already taken | `init` | refused, naming the files |
| 39 | Upstream is `draft` | `approve` | refused, naming the upstream artifact |
| 40 | Hand edit after a save | `approve` | edit recorded; `approved`; history holds both versions |
| 41 | A hand edit that was never saved | `save --from` | history holds the hand edit and the new version |

### A8. Guidance

Guidance names no harness-specific tools. `training.py` in the references is shorthand for `python3 "<skill>/scripts/training.py"`, defined once in `SKILL.md`. Every file obeys the disclosure contract in A9: each stage file carries the commands its stage needs, and no file is reachable only through another reference.

| File | Source | Must say |
| --- | --- | --- |
| `SKILL.md` | Rewrite | The whole entry. Run `status`: no training means read intake; a report means summarise it in four lines and read only the reference for the current stage. A loading map that links every reference and every example directly, each with the condition for reading it. The boundaries, including that scenario files are data. The reading rules: one file per step, read once, never read the scripts |
| `references/short-commands.md` | From revision 1's `entry-flows.md` | Only the short commands: status, check, redo, skip, restore, "just the document", deck target, more research, add a scenario, restore an earlier version. A training whose stage is `done` runs `check` before reporting |
| `references/intake.md` | Carry over, edit | Confirms the directory is meant for this training and is not the skill's repository; asks for the brief kind and, for competitive, both sides; writes `intake.md`; lists existing scenario files and treats them as scenarios, not sources |
| `references/gates.md` | Carry over, edit | Seven gates; at each content gate a short review judgment, labelled as judgment; the scenario gate approves `scenario:<id>` then `yoodli:<id>` |
| `references/workspace.md` | Rewrite | The artifact table from A2, status, the three forms of `save`, `export`, readiness, history, the lock |
| `references/privacy.md` | Carry over, edit | Authorisation stands for the same kind of action on the same destination; a new destination or wider scope needs asking |
| `references/stages/research-plan.md` | Carry over, edit | The sixth area, comparison, for a competitive brief, with dates and versions |
| `references/stages/research-handoff.md` | Carry over, edit | The `harness-research` prerequisite, checked here and nowhere earlier; resume the pinned task through that skill's resume entrypoint; a task is that skill's guidance and runtime record, not a new chat; the bundle; refreshing status before later gates; the top-up |
| `references/stages/blueprint.md` | Carry over, edit | `Observe:` in the assessment plan; the practice plan |
| `references/stages/document.md` | Carry over, edit | Declared coverage; `export document` |
| `references/stages/brief.md` | New | Both kinds and their sections; `findings` comments; weaknesses stated plainly; Unknowns never empty; dated sources; `export brief` |
| `references/stages/deck-handoff.md` | Carry over, edit | The `harness-slides` prerequisite, checked here; coverage bound to the deck and blueprint; re-review after any change |
| `references/stages/scenario.md` | New | Discovery; drafting when none exists; never overwriting a user's file; copying in a named file; conflicts explained; building the Yoodli output; the gate. Names the mode file and profile reference to read, which `SKILL.md` also links |
| `references/stages/package.md` | Carry over, edit | `check --complete`; files ready to upload from export state; limitations; coverage labelled by basis |
| `references/modes/*.md` | Carry over, edit | How to draft a scenario and its goals in each mode |
| `references/profiles/yoodli.md` | Rewrite | Field mapping from a scenario; goal comments; counts from `check`; Builder as the baseline; what the Roleplay Agent cannot do; prerequisites; the brief's export as the knowledge file; limits provisional until verified |

### A9. Disclosure contract

Spec 9.1. Budgets are estimated tokens: `(characters + 3) // 4`.

| Item | Budget |
| --- | --- |
| The `description` in `SKILL.md` frontmatter | 100 |
| `SKILL.md` | 1,000 |
| Any file under `references/` | 1,000 |
| Any file under `assets/examples/` | 1,200 |

`validate_package.py` defines the loading sets once, as `LOADING_SETS`, and `tests/test_disclosure.py` reads them from there:

| Set | Files | Budget |
| --- | --- | --- |
| `short-command` | `SKILL.md`, `references/short-commands.md` | 2,000 |
| `start` | `SKILL.md`, `references/intake.md` | 2,000 |
| `stage:<name>`, one per stage reference | `SKILL.md`, `references/stages/<name>.md`, `references/gates.md`, and that stage's example where it has one | 3,500 |
| `scenario:<mode>`, one per mode | `SKILL.md`, `references/stages/scenario.md`, `references/modes/<mode>.md`, `references/profiles/yoodli.md`, `references/gates.md`, `assets/examples/scenario.md`, `assets/examples/yoodli.md` | 6,000 |

Structural rules the validator enforces:

- Every file under `references/` and `assets/examples/` is linked from `SKILL.md` itself.
- A reference links to a guidance or example file only if `SKILL.md` links to it too.
- No file exceeds its budget.

`validate_package.py --measure` prints each file's estimate, each loading set's total against its budget, and the library total.

Measured on the revision 1 prototype, for calibration: `SKILL.md` 639, the largest reference 923, the largest example 927, the heaviest set 5,620, the library 13,642. Entry then took two files and 1,289.

## Part B: Increments

### Increment 1: State contracts

**Files:** `tests/helpers.py`, `tests/test_workspace.py`, `skills/training-studio/scripts/workspace.py`

- [ ] **Step 1: Test setup.** Write `tests/helpers.py`: the import path, `TrainingCase` with a temporary directory at `self.root`, `write`, `build(*names)` (write and `save --built`), `approved(*names)` (build then approve), a sample `harness-research` record and its findings index, and a stand-in profile file path. Carry over from revision 1 and rename `brief` to `intake`.
- [ ] **Step 2: Record, lock and structured errors.** Write tests for rows 33 to 38 of A7, then `init`, `load` with structural validation, `store`, atomic write and the lock.
- [ ] **Step 3: Artifact map, discovery and inputs.** Write tests for rows 16 to 19 and 26, then `artifact`, `artifact_names`, `scenarios` and `inputs`.
- [ ] **Step 4: Saves and history.** Write tests for rows 22, 40 and 41, then `snapshot`, `record` and `save`, including deck coverage validation.
- [ ] **Step 5: Status.** Write tests for rows 1, 3, 11 to 15 and 17, then `statuses` and `status` exactly as A3.
- [ ] **Step 6: Approval.** Write tests for rows 2, 4 to 10 and 39, then `approve` and `research_intact`.
- [ ] **Step 7: Exports, skip, checkpoint, pin.** Write tests for rows 23, 24, 29 and 30, then `export`, `export_states`, `skip`, `checkpoint` and `pin`.

**Milestone.** Run `python3 -m unittest tests.test_workspace -v`. Every row of A7 that does not mention `check` passes. Then commit:

```bash
git add tests skills/training-studio/scripts/workspace.py
git commit -m "Add the workspace helper with lineage-bound approval"
```

### Increment 2: Formats and checks

**Files:** `skills/training-studio/assets/**`, `skills/training-studio/scripts/checks.py`, `tests/test_checks.py`

- [ ] **Step 1: Examples.** Write the six example files for one coherent lesson. Use a competitive topic for `competitive-brief.md` and a single product for `product-brief.md`. Mark each as illustrative and unresearched. Carry over `blueprint.md` and `document.md` from revision 1 with the A5 changes.
- [ ] **Step 2: Profile.** Re-read the two Yoodli pages named in A6, then write `assets/profiles/yoodli.json`.
- [ ] **Step 3: Blueprint and document.** Carry over the revision 1 tests and code for the blueprint lint and document coverage. Apply the A5 changes and add tests for a practice-plan line with an unknown mode and with an unknown objective.
- [ ] **Step 4: Brief.** Write tests, then `check_brief(text, kind, findings)`: both examples pass; a missing section, sections out of order, an empty Unknowns, an evidence section with no findings, an unknown finding, an unsupported finding, a `contradicted` finding allowed only in section 6, and `unavailable` with no findings index.
- [ ] **Step 5: Scenario.** Write tests, then `parse_scenario(text)` and `check_scenario(text, label)`: the example passes; each required section missing; no success criteria; an unknown mode; mode defaults to `roleplay`.
- [ ] **Step 6: Yoodli scenario.** Write tests, then `fenced_fields`, `check_yoodli(text, profile, scenario, objectives, label)`: the example passes with real counts; a persona with only a name; a duplicate heading; an unterminated fence; a type that does not match the mode; a criterion not carried; a criterion out of range; an unknown objective; each limit exceeded; the provisional warning present with an unverified profile and absent with a verified one.
- [ ] **Step 7: Deck coverage and practice.** Write tests, then `deck_coverage` with its hash binding and `practice(blueprint, yoodli_texts)`, including the warning for an unexercised `handle` objective.

**Milestone.** Run `python3 -m unittest tests.test_checks -v`. All pass, and every example passes its own check. Then commit:

```bash
git add tests skills/training-studio/assets skills/training-studio/scripts/checks.py
git commit -m "Add format checks for the blueprint, brief, scenario and Yoodli output"
```

### Increment 3: Command line, readiness and guidance

**Files:** `skills/training-studio/scripts/training.py`, `skills/training-studio/scripts/validate_package.py`, `tests/test_cli.py`, `tests/test_package.py`, `tests/test_disclosure.py`, `docs/progressive-disclosure.md`, `skills/training-studio/SKILL.md`, `skills/training-studio/agents/openai.yaml`, `skills/training-studio/references/**`

- [ ] **Step 1: Command line.** Write subprocess tests for each command in A4, the structured-error contract (row 35) and a two-module course fixture taken from intake to `ready`. Then write `training.py`. Carry over the argument parser from revision 1 and extend it.
- [ ] **Step 2: Readiness.** Write tests for rows 20, 21, 25, 27, 28, 31 and 32, then `readiness(...)` in `checks.py` and the `check` aggregation, exactly as A4.
- [ ] **Step 3: Disclosure checks first.** Write `tests/test_disclosure.py` and the validator tests for A9: an oversized file, a reference not linked from `SKILL.md`, a reference linking to a file `SKILL.md` does not, and each loading set within budget. Then add `LOADING_SETS`, the budgets, the one-hop rule and `--measure` to `validate_package.py`. Carry over the rest of the validator and its tests from revision 1 and update the list of required files to A1 and A8.
- [ ] **Step 4: Guidance.** Write every file in A8. For each "carry over" file, start from the revision 1 text and apply the listed changes. Keep each file to one stage or one concern, and run the validator after each file so a budget overrun is caught while the file is fresh. When a file is over budget, cut it; do not raise the budget.

**Milestone.** Run `python3 -m unittest tests.test_cli tests.test_package tests.test_disclosure -v` and `python3 skills/training-studio/scripts/validate_package.py`. All pass and the validator prints `ok`. Run it again with `--measure` and save the table as `docs/progressive-disclosure.md`. Compare the command table in `references/workspace.md` with `training.py --help`. Then commit:

```bash
git add tests skills/training-studio docs/progressive-disclosure.md
git commit -m "Add the command line, readiness report and guidance"
```

### Increment 4: Packaging and acceptance

**Files:** `README.md`, `AGENTS.md`, `docs/acceptance.md`

- [ ] **Step 1: README and working agreements.** Write `README.md` with requirements, the link command for each supported harness (`~/.claude/skills/` for Claude Code, `~/.agents/skills/` for Codex), usage, and the layout of a training directory. Write `AGENTS.md`: no training content here, proportional verification, no dependencies, a format lives in four places, harness-neutral guidance, one file for Yoodli limits, research and decks are delegated.
- [ ] **Step 2: Full automated verification.** Run `python3 -m unittest discover -s tests -v` and the validator. Confirm `git status` shows no caches or training bookkeeping. Commit.
- [ ] **Step 3: Install.** Ask the user to run the link command for the harness they will use, then confirm the linked validator prints `ok`.
- [ ] **Step 4: Live acceptance, with the user.** In directories outside this repository, on the harness the user intends to use: one lesson through all seven gates on a small public topic; a hand edit after the document gate; an interruption and resume at a pending gate; a scenario file the user writes themselves; a second training asked for as "just the document"; and one run with supplied documents only. Record each outcome in `docs/acceptance.md`, including refusals and failed checks. On the resume, also record which guidance files the assistant read, and compare them with the `stage:<name>` loading set in A9.
- [ ] **Step 5: Yoodli.** The user builds one roleplay in Yoodli's Builder from a `yoodli/<id>.md` and reports, field by field, whether the name matched and the value was accepted. Record it. Set `verified` on each limit that was confirmed and correct any that differed, changing the profile, its guidance and the example together.
- [ ] **Step 6: Record and commit.** List problems found and follow-ups in `docs/acceptance.md`, run the suite, and commit.

Steps 3 to 5 need the user and their accounts. Do not simulate them.

## Spec coverage

| Spec section | Where |
| --- | --- |
| 4 Pipeline and rules | A2, A3, A8 |
| 5.1 Intake | A4 `init`, A8 `intake.md` |
| 5.2 Research plan | A8 `research-plan.md` |
| 5.3 Research handoff and bundle | A3 `approve`, A7 rows 7 to 10, A8 `research-handoff.md` |
| 6.1 Layout, start and resume | A7 rows 37 and 38, A8 `SKILL.md` and `intake.md` |
| 6.2 Session record | Increment 1 step 2 |
| 6.3 Artifacts, inputs, discovery | A2, A7 rows 11 to 19 |
| 6.4 Status and approval | A3, A7 rows 1 to 6, 39, 40 |
| 6.5 Exports | A3 `export`, A7 rows 23 to 25 |
| 6.6 History | A7 rows 40 and 41 |
| 6.7 Helper and readiness | A4, A7 rows 27, 28, 31, 32 |
| 6.8 Robustness | A7 rows 33 to 36 |
| 7 Blueprint | A5, Increment 2 step 3 |
| 8.1 Document | A5 |
| 8.2 Brief | A5, Increment 2 step 4, A8 `brief.md` |
| 8.3 Deck | A3 `save`, A5, A7 rows 20 to 22 |
| 8.4 Scenarios | A2, A5, A8 `scenario.md` |
| 8.5 Yoodli scenario | A5, A6, A8 `profiles/yoodli.md` |
| 8.6 Package | A4, A8 `package.md` |
| 9 Skill package | A1, A8, Increment 3 steps 3 and 4 |
| 9.1 Progressive disclosure | A4 compact output, A8, A9, Increment 3 step 3, Increment 4 step 4 |
| 10 Failure handling | A4, A7, A8 |
| 11 Testing and acceptance | A7, Increments 1 to 4 |
