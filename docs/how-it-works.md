# How it works

This page explains what Training Studio does behind the conversation. For the full specification, see the [design](superpowers/specs/2026-10-12-training-studio-core-pipeline-design.md).

## The stages

| Stage | Done by | Produces | Gate |
| --- | --- | --- | --- |
| Intake | Training Studio | `intake.md` and your settings | |
| Research plan | Training Studio | Up to 30 focused questions | 1 |
| Research | The harness-research skill | A cited report | 2 |
| Blueprint | Training Studio | Objectives, modules, assessment and practice plans | 3 |
| Document | Training Studio | The learner guide | 4 |
| Brief | Training Studio | A product or competitive brief | 5 |
| Deck | The harness-slides skill | Google Slides or PowerPoint | 6 |
| Scenario | You and Training Studio | Scenario files | 7 |
| Yoodli, optional | Training Studio | A Yoodli scenario for each scenario file | 8 |
| Package | Training Studio | The index and a readiness report | |

At each gate you approve, ask for changes, have it rebuilt, or skip. With levels, intake and research happen once, all the blueprints are reviewed together, and gates 4 to 8 then repeat for one level at a time.

The blueprint is the hub. The document and brief are written from it, and the deck is built from the blueprint and the document. A Yoodli scenario is built from your scenario file, the brief and the blueprint.

## Where facts come from

Every claim in the blueprint and the brief names the research finding it rests on. A finding is supported, contradicted, insufficient or unavailable; the last two are called unresolved. Only a supported finding can back a claim. A contradicted one can back the correction of a misconception, or the answer to an objection. Where the research could not establish something, the training says so under open gaps and the brief lists it under Unknowns. Nothing is filled in from the assistant's memory.

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

## Where you approve

Every decision at a gate is recorded with where it was made, and written into that file's review under `reviews/`.

- **In the conversation.** You tell your assistant, and it records your decision. This is the default.
- **On the page.** You decide on [the page](desk.md) in your browser. The helper then refuses `approve` and `skip` from the command line, so your assistant cannot record a decision you did not make. Asking for changes or a rebuild leaves a request your assistant acts on when you return to it; the request closes when the file is rebuilt or approved, and an open request keeps the training from being ready.

Moving a training to the page raises the bar; it does not make forgery impossible. An assistant with a shell that set out to rewrite the session record could still do so. The guidance forbids it, but only [the runner](runner.md) prevents it: there, each agent works in an empty folder outside your trainings, with no shell, and has no way to approve.

## Ready, or not

`check` reports two things. **Checks passed** means nothing it could check has failed. **Ready** means the training is complete: every wanted file is approved, nothing is stale, no check failed or could not run, and no Google Doc or Word copy you asked for is out of date. A question still waiting on you also blocks it. It lists what is blocking, and separately what was left out because you skipped it, it could not be produced, or you accepted it as it was after something it was built from changed.

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
  document.md              and document.docx, if you asked for Word copies
  product-brief.md         or competitive-brief.md; its .docx with Word copies, or for Yoodli
                           when you keep no Google Docs
  deck-handoff.md          the note given to harness-slides
  deck.pptx                or deck-link.md for Google Slides
  scenario.md              your scenario; more go under scenarios/
  yoodli/main.md           optional: the Yoodli scenario built from scenario.md
  reviews/                 what you were shown at each gate, and what you decided
  work/                    the assistant's working files; nothing here is a deliverable
  sources/                 the documents you selected
  .training-studio/        the session record and every earlier version
  .harness-research/       owned by harness-research
  .harness-slides/         owned by harness-slides
```

With levels, `intake.md`, `research-report.md` and `sources/` stay at the top, and everything from `blueprint.md` down sits in a folder per level: `101/`, `301/`. Each level's deck is built as its own harness-slides task inside that folder.

Every version of every file that was saved or approved is kept under `.training-studio/history/`, so an earlier version can be restored.

## Guidance and scripts

What your assistant follows is guidance: instructions, templates and the Yoodli field data. What changes files is a small set of scripts.

- Scripts are installed and never fetched.
- Guidance is fetched from this repository's `main` branch when a new training starts, and that training is pinned to it. The pin records the exact commit and a hash of every file.
- A pinned training needs no network to resume.
- If guidance cannot be fetched, the guidance installed with the scripts is used, and you are told it may be older.

See the [phase 2 design](superpowers/specs/2026-10-12-phase-2-packaging.md).

## The helper

The skill drives a small command-line helper, `skills/training-studio/scripts/training.py`. You never need to run it, but you can:

| Command | Does |
| --- | --- |
| `status` | The stage, what is waiting, and the status of every file |
| `check` | Runs every check that applies and reports readiness |
| `save`, `approve` | Record a version, and record your approval of it, which moves the training on once its stage is finished |
| `export` | Records a Word copy, when you asked for them |
| `google` | Sends the guide or the brief to a Google Doc and brings edits back |
| `skip` | Leaves a stage out, or brings it back |
| `checkpoint` | Records where the run stopped and what is at the gate, and changes settings such as which copies to keep. `--add-level` adds a level; a level with work in it is never dropped |
| `list` | The trainings on this computer |
| `desk` | Serves [the page](desk.md) until it is stopped |

It needs only Python and never commits to git. Apart from `google`, the team hub and, on the page, the check of this computer that you ask for, none of it touches the network. The assistant's instructions for using it are in [the workspace reference](../skills/training-studio/references/workspace.md).
