# Studio Runner, milestone 3: the rest of a training

Date: 2026-10-13
Status: specified. Builds on milestone 2, which takes a training from the form to approved blueprints.

## Purpose

A whole training without a conversation. After the blueprints the runner writes the learner guide and the brief, drafts the practice scenarios, lays them out for Yoodli when that is wanted, makes the copies that were asked for, and writes the index. It stops at every gate the skill has. The slide deck is the one stage it still does not make; that is milestone 4.

## Scope

In: the guide, the brief, scenarios, Yoodli scenarios, the package step, copies after approval, research from documents the person supplies, and what the page needs for each.

Out: the slide deck (milestone 4). Publishing to a team hub and reusing a team's scenarios, which the design settles at milestone 5 with the workspace. Bringing edits back from a Google Doc. Uploading a scenario file through the page.

## 1. The pipeline after the blueprints

The steps are added to `pipeline.TRAINING` as data, in the shape milestone 2 gave it. `survey` still remembers nothing: every step's state is read from the training's files, its record and the run record.

With levels, everything below is done for one level at a time, lowest first, as the skill's levels reference says. A plain training is one pass.

| Stage | The runner does | A worker does | Gate |
| --- | --- | --- | --- |
| Document | Coverage check; copies after approval | Writes the learner guide | 4 |
| Brief | Evidence check; copies after approval | Writes the brief | 5 |
| Deck | Nothing yet. See below | | |
| Scenario | Shape check | Drafts each scenario the blueprint's practice plan names and the person has not written | 7, once for each scenario |
| Yoodli, when it is on | Counts and limits against the Yoodli profile; copies after approval | Lays each approved scenario out in Yoodli's fields | 8, once for each |
| Package | Readiness; writes `README.md` from the record | | none |

**The deck.** A training that was started with "No deck" has its deck stage left out through the core when it is made, with that as the recorded reason. The form's choice does nothing today; this puts that right. A training that wants a deck is taken through every other stage. It then stops, finished as far as the runner goes, and says: everything but the slide deck is made; the deck is not automated yet; make it in a conversation with your assistant, or leave it out. "Leave the deck out" on the page is the skip decision milestone 1 already has, with a reason. Once the deck is left out, or approved from a conversation, the package step runs.

**A stage the person left out** is passed over. Leaving out the brief also leaves nothing for Yoodli to rest on; the core already refuses that, and the page says why.

**Scenarios.** The practice plan in a level's blueprint names its scenarios and their modes. For each one with no file, a worker drafts `scenario.md` (the ID `main`) or `scenarios/<id>.md`. A file the person wrote is never rewritten by the runner. It is saved and put to them as it is, with what the shape check found. If they ask for changes at its gate, a worker lays their own wording out under the headings and asks for anything missing; it does not invent an opening line. The run record notes which scenario files the runner drafted, so that it can tell them from a person's.

**Requests.** Asking for changes or a rebuild at any of these gates works as it does at gates 1 to 3: the step is done again with the note and the earlier draft, and the new version comes back to the same gate.

**Later changes.** When something approved earlier is changed and approved again, the core marks what was built from it as out of date. The runner then does those steps again, in order, and each comes back to its gate. Nothing is accepted as it is without the person: "Accept as it is" is their decision, on the page.

## 2. Worker jobs

Each job is one worker in an empty folder with the runner's tools, as in milestone 2. What it is told is a brief under `runner/briefs/`, written from the stage's reference in the skill without any helper command, plus the example file for the format. A draft is handed back with `submit_artifact` and checked before it is kept; the worker's own notes go to the gate labelled as its judgment.

| Job | Inputs | Checked with |
| --- | --- | --- |
| The learner guide | Intake, this level's blueprint, the research findings, and what earlier levels' blueprints cover, as assumed | `checks.document_coverage` against the blueprint: every objective and supported key point is named in a coverage comment, and no unsupported one is |
| The brief | Intake, this level's blueprint with its open gaps, the research findings, the kind of brief | `checks.check_brief`: title, numbered sections in order, findings comments that exist and have the right verdict |
| A scenario | Intake, the blueprint's practice plan, the approved brief, the mode's reference | `checks.check_scenario` |
| A Yoodli scenario | The approved scenario, the approved brief, the Yoodli profile, the mode's reference | `checks.check_yoodli` with the profile: fields, goals, counts and limits, and that every success criterion has a goal |

`worker_tools.VALIDATORS` gains `document`, `brief`, `scenario` and `yoodli`. Each takes what its check needs in the job's `artifacts` entry, as `blueprint` takes `level` and `findings` today. A check that could not run is recorded for the gate and not held against the worker.

The review note at each gate says what was checked. At gate 4 it also says that coverage is declared: a section claims to teach something, and whether the prose does is for the person to read. At gate 5 it carries where the worker thinks the brief is weakest. At gate 8 it names which goal carries each success criterion, the counts against Yoodli's limits and that the limits are provisional while the profile says so, and whether the brief has a copy to upload.

## 3. Copies

After an approval at gates 4, 5 and 8 the runner makes the copies the core's status asks for. These are code steps. No worker is involved.

- **Google Docs.** Through the helper's own Google code, with the access this computer already has. The runner never asks for, stores or prints a credential. If Google access is not set up, or the push is refused, the copy is recorded as not made, with the reason in a sentence, and the run carries on.
- **Word.** With `pandoc` when it is on the path, recorded with the core's `export`. Otherwise recorded as unavailable with the reason.

A copy that could not be made is shown on the run and listed as a limitation in the index. "Try the copies again" on the page makes them again. A copy is made again when its document is approved again.

With Yoodli on and no current copy of the brief to upload, gate 8 says the Yoodli handoff is incomplete and what the person can do.

## 4. The package

A code step, when nothing wanted is left to make or decide.

1. `checks.readiness`, as `training.py check --complete --all` computes it.
2. `README.md` is written by code from the record, with the eight sections the package reference lists: who and what it is for; the objectives in plain words; every file with its status and its review; the current copies; the coverage table with the basis of each column; open gaps and limitations; how to use the scenarios; the research. It is derived and never saved through the core.
3. The stage is set to `done`.

A training that is ready finishes with a sentence saying so and how many limitations it has. One that is not ready stops and lists what is blocking, each with the screen to go to.

## 5. Your own documents

The form's last step offers the sources: the public web, your documents only, or both.

When documents are wanted, the first thing the run does is wait for them. The run's screen has a place to add files, shows each with its size and whether it could be read, lets one be removed, and has a button for "That is all of them". Nothing is researched until that is pressed.

- **What is taken.** Text, Markdown, HTML and Word (`.docx`) always. PDF when `pdftotext` is on this computer, as for fetched pages; otherwise the page says to save it as text or Word. At most 8 MB each and 40 files.
- **Where they go.** Under `sources/supplied/` in the training, which the workspace never shares. The page says so: your documents stay on this computer, and passages quoted from them appear in the research report, which is shared.
- **How they are used.** Each is a source in the research plan, in the shape harness-research defines, and is offered to every research worker before it starts. With documents only, the plan's scope is `supplied-only`, no question has search words, and the workers get no web search and cannot fetch pages. With both, the scope is `public-web` with the sources listed.
- **The questions.** The worker drafting them is told what was supplied, by title, so the questions fit what the documents can answer.

A training on another computer that shares the workspace has the report and its quotes but not the documents. Research cannot be run again there until they are added again; the page says so.

## 6. The page

- **New training.** The sources choice is live. The step that says how many times it will ask counts the later gates: one for each guide and brief, and one for each scenario and Yoodli scenario once those are known.
- **The run.** The later steps appear as they are reached. Adding documents, as above. A line for each copy: made, with its link; out of date; or not made, with why and "Try the copies again". The deck notice with "Leave the deck out". A finished training says it is finished, shows its limitations, and opens the index.
- **Gates 7 and 8.** A scenario's gate says whose file it is. A Yoodli scenario's gate shows the scenario beside it.
- **Home.** A training the runner has finished is under Finished, not In progress.

Everything else about a gate is milestone 1's.

## 7. Three new modules

Each is a module of its own with nothing in it about runs, so that it can be built and tested apart. The engine is given them as it is given its agents and harness-research, and a test replaces them.

- `runner/documents.py`: the documents a person supplies. Keeps them, reads their text, and gives them to the research plan and to the workers.
- `runner/copies.py`: the Google Docs and Word files a training asked for. Says which are wanted and makes them.
- `runner/index.py`: readiness, and `README.md` written from the record.

The docstring at the top of each is its interface.

## 8. Tests

- The pipeline and the engine with scripted workers: a plain training and a two-level one from the form to done; Yoodli on and off; a deck wanted, left out from the start, and left out at the end; a stage skipped; a change asked for at each new gate; an earlier approval changed, and what is done again.
- A person's scenario file: used as it is, never rewritten, laid out only on request.
- Each new validator against the example files and against a draft that fails.
- Copies with the stubbed Google transport: made, refused, not set up; Word with and without `pandoc`.
- The index, against a finished training's record.
- Supplied documents: each type, a file that cannot be read, the limits, removal, the plan's scope and sources, and that a documents-only worker cannot reach the web.
- The page's new parts, driven through its own controls, as milestone 2's are.

No test starts a real agent, the real harness-research or Google.

## Done when

- The suite passes and `validate_package.py` prints `ok`.
- A real training with no deck and Yoodli on runs on Claude from the form to finished, decided on the page.
- A real training from supplied documents only runs through research on either agent.
- Not claimed without a person: a real push to Google Docs, and a paste into Yoodli.

## What the first real runs showed

Run on 2026-10-13, through the page in a browser, against a stand-in team repository that already held another tool's files.

- **A whole training on Claude Code, with no conversation.** No deck, Yoodli on, research from the public web. Eleven decisions on the page: the questions, the research, the blueprint, the guide, the brief, three practice scenarios and their three Yoodli layouts. Twenty-six steps, none failed; about 14 minutes of agent time; $6.11 as Claude Code reported it. It finished ready, with its limitations listed: the deck left out, and no Word copies because `pandoc` is not on that computer. The index was written and shared. The other tool's files were untouched.
- **Research from supplied documents only, on Codex.** A Markdown file and a Word file added through the page's own file picker. Eight of eight questions answered, every quote from one of the two documents, the plan's scope `supplied-only` with no search words. The documents stayed under `sources/supplied/` on that computer; nothing of them is in the shared repository except the passages the report quotes.

Put right because of it:

- The index listed the training's own files as raw Markdown links. On the page they are now named plainly. They are still never links: only a web address becomes one.
- The documents card said where documents are kept twice, once in the page's words and once in the runner's. The runner's note now carries only what the page cannot know.
- A size limit was worded "7.6 MB" on the page and "8 MB" by the runner. Limits are now in the round megabytes they are set in.
- A 20-minute lesson's blueprint planned three practice scenarios, which meant six more decisions that nothing had announced. The blueprint's gate now says how many it plans and how many decisions that is, and that asking for changes is how to have fewer.

Not run for real: a push to Google Docs, a Word copy made by `pandoc`, a PDF among the supplied documents, a training with levels, and a paste into Yoodli.

## Deviations

Recorded when it was built. Each is something the text above does not say, or says differently.

- **Anything out of date is made again by itself,** from the blueprint down, and comes back to its gate. Milestone 2 put an out-of-date blueprint to the person first. A research plan put out of date by a change to the answers is still put to the person.
- **A redo that hands back the same text stays approved,** so no gate follows it.
- **Within a level every scenario is drafted before the first is put to the person,** and likewise the Yoodli layouts.
- **Only scenarios the practice plan names are drafted.** A blueprint that plans none leaves a training that wants practice not ready; its gate says so.
- **"That is all of them" is kept on each computer,** beside the documents. After it, the documents cannot be changed.
- **The documents keep one more file than the specification says:** their list, with the order they were added in and why one could not be read.
- **A copy of something not yet approved is not shown.** A copy that has fallen behind its document is.
- **Readiness is the core's, unchanged.** With Yoodli on and Google Docs as the only copy, a brief with no Google Doc is blocking, because Yoodli needs a file to upload. A Word copy that could not be made is a limitation. The finished training says which, and offers to try the copies again.
- **A training whose decisions were moved to a conversation is left alone,** except that its index is written. A deck approved there is picked up the next time the run is woken.
- **A runner that is started again discards half-made work only for a step that was in hand,** which a file kept out of git marks. "Finished" is no longer final, so the earlier rule would have removed a person's own edits.
- **New kinds of step:** adding documents and the deck notice are shown as decisions; a person's own scenario is taken in by a step of the runner's own.
- **What is blocking is given as sentences.** Nothing yet names the screen to go to for each.
- **Milestone 2's trainings carry on.** One left at "the later stages are not automated yet" continues by itself when the runner next starts.

## Appendix: what the page asks the runner

Additions to milestone 2's contract. Everything there stands.

- `POST /api/trainings`: `source_scope` may be `public-web`, `supplied-only` or `both`. `deck_target: null` leaves the deck out.
- `GET /api/run` gains:
  - `documents`: `null` when none are wanted, else `{"waiting": bool, "added": [{"name", "bytes", "readable": bool, "problem": str or null}], "types": [str], "limits": {"bytes": int, "files": int}, "note": str}`. `waiting` is true until "That is all of them".
  - `copies`: `[{"artifact", "label", "kind": "google" | "word", "state": "made" | "out-of-date" | "not-made", "link": str or null, "problem": str or null}]`.
  - `deck`: `null`, or `{"says": str, "artifact": str}` when the deck is all that is left; `artifact` is what to send to `POST /api/decide` with the decision `skip`.
  - `finished`: `null`, or `{"ready": bool, "limitations": [str], "blocking": [str], "index": "README.md"}`.
  - `state` may now be `done` with `finished` set, which means finished; `done` with `deck` set means the deck is all that is left.
- `GET /api/gate` gains, for a scenario, `"whose": "you" | "runner"`: who wrote the file. For a Yoodli scenario it gains `"beside": {"artifact", "label"}`, the scenario it was laid out from, which the page reads with `GET /api/file`.
- `POST /api/trainings` still answers `gates`, now the fewest times the training will ask: gates 1 and 2, and a blueprint, a guide and a brief for each level, less any stage left out. Scenarios are not known until a blueprint names them, so the page says "at least".
- `POST /api/documents` with `{"path", "action": "add" | "remove" | "done", "name": str, "content": base64}` returns the run. `name` and `content` only as the action needs. This address alone takes a body of up to 12 MB.
- `POST /api/copies` with `{"path"}` makes the copies again and returns the run.
- List items' `run.state` may be `done`; a finished training's own `state` is the core's, so Home files it under Finished.
