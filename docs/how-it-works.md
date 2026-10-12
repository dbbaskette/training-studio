# How it works

This page explains what Training Studio does behind the conversation. For the full specification, see the [design](superpowers/specs/2026-10-12-training-studio-core-pipeline-design.md).

## The stages

| # | Stage | Done by | Produces |
| --- | --- | --- | --- |
| 0 | Intake | Training Studio | `intake.md` and your settings |
| 1 | Research plan | Training Studio | Up to 30 focused questions |
| 2 | Research | The harness-research skill | A cited report |
| 3 | Blueprint | Training Studio | Objectives, modules, assessment and practice plans |
| 4 | Document | Training Studio | The learner guide |
| 5 | Brief | Training Studio | A product or competitive brief |
| 6 | Deck | The harness-slides skill | Google Slides or PowerPoint |
| 7 | Scenario | You and Training Studio | Scenario files and a Yoodli scenario for each |
| 8 | Package | Training Studio | The index and a readiness report |

Stages 1 to 7 each end at a gate where you approve, revise, rebuild or skip. With levels, stages 0 to 2 happen once, all the blueprints are reviewed together, and stages 4 to 7 then run one level at a time.

The blueprint is the hub. The document and brief are written from it, and the deck is built from the blueprint and the document. A Yoodli scenario is built from your scenario file, the brief and the blueprint.

## Where facts come from

Every claim in the blueprint and the brief names the research finding it rests on. A finding is supported, contradicted, or unresolved. Only supported findings can back a claim. Where the research could not establish something, the training says so under open gaps and the brief lists it under Unknowns. Nothing is filled in from the assistant's memory.

## Approval, and what "stale" means

Each file has a status:

| Status | Meaning |
| --- | --- |
| not-started | The file does not exist yet |
| draft | Not approved in its current form |
| approved | You approved exactly this content, built from exactly these inputs |
| stale | Something it was built from has changed since |
| skipped | You chose to leave its stage out |
| unavailable | Its stage could not run |

Status is worked out from the files each time, so editing a file by hand is safe and is always noticed.

An approval covers both the content and what it was built from. Three consequences:

- Edit an approved file and it becomes a draft. Anything built from it becomes stale.
- Rebuild a file against changed inputs and it needs approving again, even if the text came out the same.
- Accept a stale file as it is, with a reason, and only that file is approved. Files below it stay approved only if their own inputs did not change.

Changing a setting affects only what uses it. A new brand makes the deck stale and leaves the research alone.

## Ready, or not

`check` reports two things. **Checks passed** means nothing it could check has failed. **Ready** means the training is complete: every wanted file is approved, nothing is stale, no check failed or could not run, and no Word copy is out of date. A question still waiting on you also blocks it. It lists what is blocking, and separately what was left out because you skipped it, it could not be produced, or you accepted it as it was after something it was built from changed.

Some checks are stronger than others, and the report says which:

- **Document coverage is declared.** Each section says which objectives it teaches. That proves the claim was made, not that the prose teaches well.
- **Deck coverage is reviewed.** The assistant reads the finished slides and records what it found. The review is tied to that exact deck and stops counting if the deck changes.
- **Practice is reported.** The report lists which objectives your scenarios exercise. A scenario need not cover them all.

## The training folder

```
valkey-training/
  README.md                index and readiness report
  intake.md
  research-report.md       the approved research report
  blueprint.md
  document.md              and document.docx
  product-brief.md         or competitive-brief.md, and its .docx
  deck-handoff.md          the note given to harness-slides
  deck.pptx                or deck-link.md for Google Slides
  scenario.md              your scenario; more go under scenarios/
  yoodli/main.md           the Yoodli scenario built from scenario.md
  sources/                 the documents you selected
  .training-studio/        the session record and every earlier version
  .harness-research/       owned by harness-research
  .harness-slides/         owned by harness-slides
```

With levels, `intake.md`, `research-report.md` and `sources/` stay at the top, and everything from `blueprint.md` down sits in a folder per level: `101/`, `301/`. Each level's deck is built as its own harness-slides task inside that folder.

Every version of every file that was saved or approved is kept under `.training-studio/history/`, so an earlier version can be restored.

## The helper

The skill drives a small command-line helper, `skills/training-studio/scripts/training.py`. You never need to run it, but you can:

| Command | Does |
| --- | --- |
| `status` | The stage, what is waiting, and the status of every file |
| `check` | Runs every check that applies and reports readiness |
| `save`, `approve` | Record a version, and record your approval of it |
| `export` | Records a Word or PDF copy |
| `skip` | Leaves a stage out, or brings it back |
| `checkpoint` | Records where the run stopped, and changes settings |

It needs only Python, never touches the network, and never commits to git. The assistant's instructions for using it are in [the workspace reference](../skills/training-studio/references/workspace.md).
