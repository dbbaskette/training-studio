# Phase 1 acceptance

Live acceptance needs a person: a real run through every gate with an assistant, and one roleplay built in Yoodli. Nothing on this page is filled in by simulation. Automated verification is described in [development](development.md).

| | |
| --- | --- |
| Date | 2026-10-12 |
| Harness and version | Not recorded |
| Skill commit | `a450e5b` (0.6.0), through a development link |
| harness-research version | 0.8.0 |
| harness-slides version | Not reached |

## Run 1: a full training

Directory (outside this repository): a new, empty directory made for the run.
Topic: a family of Kubernetes data operators, with a requirement to cover every member of a named set.
Levels: 101 and 201.
Brief kind: product. Copies: Google Docs only. Yoodli: on, turned on after intake.

The run stopped at gate 2, waiting on the user. Gates 3 to 7 are still to do.

| Gate | Artifact | Outcome | Notes |
| --- | --- | --- | --- |
| 1 | research-plan | Approved | 26 questions. The assistant wrote the readable list to a file of its own as well as showing it |
| 2 | research | Presented, not yet decided | 21 supported, 5 insufficient. The helper read the real `harness-research` record without trouble |
| 3 | blueprint | | |
| 4 | document | | |
| 5 | brief | | |
| 6 | deck | | |
| 7 | scenario and Yoodli scenario | | |

Record refusals and failed checks as well as approvals.

### Hand edit

What was edited after the document gate, the `status` output before and after, and how it was resolved.

### Interrupt and resume

The gate where the session was ended. What the resumed session said first. Which guidance files it read, compared with the `stage:<name>` loading set in [progressive disclosure](progressive-disclosure.md).

### A scenario the user wrote

The file, whether it was used as written, and anything the assistant proposed changing.

### Final `check --complete --all`

```json
```

## Run 2: "just the document"

Directory:
The order the stages were skipped in, and what `status` and `check` reported.

## Run 3: supplied documents only

Directory:
The documents selected, and whether any public search was attempted.

## Yoodli

Built in the Builder from `yoodli/<id>.md`.

| Field | Name matched | Value accepted | Notes |
| --- | --- | --- | --- |
| Roleplay name | | | |
| Type | | | |
| Description | | | |
| Context | | | |
| Personas | | | |
| Objections | | | |
| Goals | | | |
| AI assets | | | |
| Settings | | | |

Account: plan, role, and whether custom goals and AI assets were available.
Roleplay Agent tried: yes / no. Result:

Limits confirmed, to be recorded as `verified` in `skills/training-studio/assets/profiles/yoodli.json`:

## Problems found

From run 1. The helper accepted every command; these are the places the skill was wrong or unclear.

| Problem | Fixed in |
| --- | --- |
| With Yoodli on, the helper asked for a Word copy of each brief although the user had chosen Google Docs and no Word files. The training could not have been ready without one | 0.7.0: the brief's Google Doc, downloaded as a PDF, is the upload |
| `research` in `status` was `null` at gate 2, while the research was being reviewed | 0.7.0: it summarises the live record before approval |
| Nothing said where working files or gate write-ups belong, so they were left at the top level beside the deliverables | 0.7.0: `work/` and `reviews/` |
| The question establishing the members of the named set came from the person's brief, not from the guidance | 0.7.0: the research-plan reference asks for it |

Not the skill's: `harness-research` could not fetch its guidance until the sandbox allowed network access, and several public pages refused automated retrieval. Both were reported as they happened.

## Follow-ups

- Finish run 1 from gate 2, on 0.7.0 or later.
- The run used a development link, so the installed copy, its bootstrap entry and its pinned guidance have not been exercised live.
- Runs 2 and 3, and a paste into Yoodli, are still to do.
