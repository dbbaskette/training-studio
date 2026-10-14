# Studio Runner, milestone 4: the slide deck

Date: 2026-10-13
Status: specified, after two spikes. Builds on milestone 3, which makes everything but the deck.

## Purpose

The deck is the last stage the runner does not make. This milestone builds it with the two skills that already own it: `harness-slides`, which plans, draws, previews and renders editable slides, and a brand skill, which owns the identity, the native template, the type, the icons and the brand's own audit. The runner drives both, gives each piece of judgment to a confined worker, and puts two things to the person: what the deck says, and the deck itself.

A deck is always a brand deck. With no brand skill on the computer the deck stage says what is missing; a plain deck is not offered.

## What the spikes showed

Two spikes were run on 2026-10-13 against the installed tools (`harness-slides` 0.13.0 and a brand skill at 0.13.0), outside this repository.

- **A confined worker can see a picture that a runner tool returns,** on Claude Code and on Codex. Both read small text off a slide picture correctly. So composing and reviewing need no file access.
- **An eight-slide branded deck was built end to end by confined workers:** an outline writer, two section composers side by side, an independent reviewer, then the render and the brand's audit. About ten minutes of agent time and $3.15 on Claude Code. A repair round on the reviewer's findings cost $2.31 more.
- **Seeing the slides matters.** A composer redrew a slide twice after seeing arrows run through its headings, which no automatic check reported.
- **The first build was accurate and on brand, and not good.** One label in each list of equals was set large and coloured, because every slide must name a focal point and the composers put it on one of several peers. The repair round fixed that and the cover, and left five major findings, four of them new. Two independent reviewers disagreed with each other about one slide.
- **Some things a composer cannot fix.** Caveat and source lines are set by the tool in the brand's `caption` role, which is smaller than the brand's own audit allows. The outline's word budget counts body words and ignores the title, caveat and source, so slides came out denser than the audit allows. A slide whose approved words do not fit its drawing needs fewer words, which is the outline's business.
- **Previews.** The tool renders through Google Drive or through LibreOffice. There is no third way. A Drive render took six to nine seconds. One preview file is enough for a whole deck, but only when renders are taken one at a time: two at once crossed their pictures. The tool never deletes a preview file.
- **The deck that is delivered must be the deck that was reviewed.** A fresh render of the same slides has a different hash.
- **The tool says "clear" while major findings remain.** Only a critical finding blocks it.
- **One defect stops the real tools today.** The slides tool cannot render the brand's template as the brand skill exports it: the render writes a relationship attribute into a part whose root does not declare that namespace, fails, and leaves a broken file behind. The spike went round it by normalising a copy of the template. The runner must not do that; see "What this milestone waits on".

## Scope

In: the deck stage for each level, from the handoff to an approved deck, as PowerPoint or as Google Slides; the brand as a step of the process; what the page needs for the outline and the deck; previews through Google Drive or LibreOffice; the brand's naming rules for the writers of the guide and the brief.

Out: choosing between two or three looks for a deck (the default direction is used); editing a deck by hand and bringing the edits back; images made by a model; the team features of milestone 5.

## 1. What a computer needs

The check of this computer, which the status screen already shows, gains the deck's needs, each in a sentence with what to do about it:

- the slides tool, installed, and new enough;
- a brand skill, installed;
- a way to render previews: LibreOffice on this computer, or Google access that reaches Drive;
- the small programs the slides tool uses to turn a render into pictures.

A training that wants a deck on a computer that cannot make one is taken through every other stage, as in milestone 3, and the deck notice says what is missing instead of "not automated yet".

**Previews are a choice made at set-up,** with what each means said plainly. LibreOffice: nothing leaves this computer. Google Drive: each deck keeps one presentation named "Preview: …" in your Drive, written again at each render; the runner never deletes it, and Settings lists the ones it made, each with its address, so that you can.

## 2. Two new modules

Each wraps a command line, as `runner/research.py` wraps harness-research, and each has a stand-in that behaves like the real thing for tests.

- **`runner/slides.py`**: finds the installed slides tool; one function for each command the pipeline uses (the outline's contract, check, draft and start; the composition's contract, layouts, compile, merge, preview, critique and render; the Drive check and import; coverage of a scene). A refusal carries the tool's own lines. It never leaves a broken deck behind: a render that fails removes what it wrote.
- **`runner/brand.py`**: finds a brand skill on the computer without naming one. A brand skill is a skill whose companion command lists its brands, exports a slides contract, searches its icons and audits a deck. The set-up screen shows which was found and lets a different one be named. It wraps: the brands and their variants; the contract export and its check; the icon search; the audit of a finished deck; its own readiness check.

No brand's name appears in this repository.

## 3. The brand in the process

- **Chosen at the start.** The form's free-text brand becomes a choice of brand and variant, read from the brand skill. It is recorded in the training's settings, where a change already makes the deck out of date.
- **Exported for each deck,** into the deck's own folder, for reading delivery: a deck from Training Studio is both presented and handed out, and every slide must make sense alone. The export is checked again before each later step; a brand that changed underneath a deck stops it with a sentence.
- **Naming rules for the writers.** The export carries the brand's rules for how the organisation and its products are named. When a brand is chosen, the writers of the guide, the brief and the scenarios are given those rules as an input. Tone is not taken from the brand.
- **Icons.** A composer has a tool that searches the brand's icon library and is told when one helps.
- **The audit.** The finished deck is run through the brand's own audit. Its result is shown at the deck's gate under "Checked for you", warnings and all.

## 4. The pipeline

For each level, in the deck's own place: after the brief and before the scenarios.

| Step | Who | What |
| --- | --- | --- |
| The handoff | Runner | Writes `deck-handoff.md` from the record: goal, audience and duration, use, required elements, sources, output |
| The brand | Runner | Exports and checks the contract; reads the outline's and the composition's contracts and the template's layouts from the slides tool |
| The outline | Worker | Writes what each slide says, from the handoff, the blueprint, the guide and the research findings. Checked with the tool's own check and with the runner's rules below |
| **Gate: what the deck says** | Person | The outline as its slides: each title, what it should leave the audience understanding, its points, its caveat and its notes. Approve, or say what should change |
| The start | Runner | Adds the direction, the layouts for cover, section and closing slides, and the house rules; has the tool split the deck into sections; puts the lead slides right; rewrites each section's brief for a worker with tools and no files |
| The sections | Workers, side by side | Each draws its section and looks at it: check, preview, revise, hand in |
| The whole deck | Runner | Merges the sections, compiles, previews |
| The review | A different worker | Looks at every slide's picture and answers the tool's questions about each; says which slides address each objective |
| Repair, at most twice | Workers | Each section with a major finding about how it is drawn is drawn again, given its findings |
| The deck | Runner | Keeps the previewed deck as the deck; runs the brand's audit; for Google Slides, imports it; saves it and the reviewed coverage through the core |
| **Gate 6: the deck** | Person | The slides themselves, full size, with what the review still finds, the audit's result and the coverage |

**The outline's rules,** checked by the runner as well as told to the worker:

- every content slide names the blueprint's objectives it serves, and every objective is served by some slide;
- the word budget counts what will be seen: title, points, caveat and source together;
- a cover carries a title and one subtitle line, and no more;
- anything under the blueprint's open gaps stays out.

Told to the worker and to the composers, because no program can check them: equals share one size and weight; the focal point is what the title singles out and never one of several peers, so a slide that lists equals is given a focal that is not one of them; nothing is drawn that the title does not announce.

**The outline's gate is the runner's own.** The core knows one file for this stage, the deck. The outline is kept in the deck's folder and its approval in the run record, with the person's words copied into the outline as the tool expects. A change to the blueprint or the guide after it puts it to the person again.

**A section composer** has these tools and no others: read its inputs (its brief, the composition's contract, the tool's design guidance, an example for each kind of slide it draws); check a draft, which compiles it and returns what the compiler refuses; preview a draft, which renders it and returns each slide as a picture with the renderer's own findings; search icons; hand in. It has four previews. What it hands in must be what it last previewed, and must keep every approved word: title, points, caveat, source, notes and the objectives each slide serves. The runner checks both.

**Previews are taken one at a time,** whatever is being drawn side by side, because that is what the renderer can do.

**The reviewer is independent:** a worker that drew nothing, given the pictures and the questions. It looks at full-size slides, not the contact sheet, which loses the template's artwork. On a second round it is also given the earlier findings and asked whether each is put right.

**Repair is bounded and narrow.** Only major and critical findings are repaired. A finding about how a slide is drawn goes back to that section's composer. A finding about what a slide says is not a composer's to fix: it is kept for the person, at the deck's gate, with "Ask for changes" leading back to the outline. After two rounds the deck goes to its gate as it is, with what remains.

**The deck is never called clear while a major finding remains.** The gate lists what remains, major first, in the reviewer's words, each with its slide.

**Gate 6 names the exact deck.** The file saved through the core is the previewed deck whose pictures the page shows, so the approval's hash is of what was seen.

**Cost.** Before the deck starts, the run says what a deck of this size has cost before: the spike's rate was about forty cents and a minute and a quarter of agent time a slide, and as much again for a repair round. The deck spends from the same limit as the rest of the training.

## 5. Worker tools

- A tool's result may carry pictures as well as text.
- New validators call the slides tool: the outline against its check, a section against the compiler.
- A job's own folder may hold decks and pictures of several megabytes. It is removed when the job's result is kept, as now, and nothing in it is ever committed. In the training, only the last preview of the whole deck is kept, beside the deck, and the workspace does not share it.

## 6. The page

- **New training:** the brand and its variant, as a choice. With no brand skill, the deck choice says a deck cannot be made on this computer and why.
- **Set-up and Settings:** how previews are rendered, and the preview files left in Drive.
- **The run:** the deck's steps as they are reached; while sections are drawn, the latest preview of each; what a deck of this size has cost before.
- **The outline's gate:** the slides in order, as something to read.
- **The deck's gate:** every slide as a picture, one at a time and as a strip; what the review still finds; the audit; the coverage, both as reviewed and as cited. Pictures are served only for a deck the runner rendered, by number, to the page that holds the key.
- **Status:** the deck's needs on this computer.

## 7. Tests

- Both modules against their stand-ins, and each stand-in against the real tool's recorded behaviour: what it writes, prints and refuses.
- The pipeline with scripted workers: a deck from handoff to approved, for PowerPoint and for Google Slides, plain and with levels; the outline's rules; a hand-in that differs from its preview; a hand-in that changed an approved word; previews taken one at a time; repair, its limit, and a content finding kept for the person; a failed render leaving nothing behind; a brand that changed; a computer with no brand skill, no slides tool, no renderer.
- Picture results through the tools server.
- The page's new parts, driven through their own controls.

No test starts a real agent, the slides tool, a brand skill or Google.

## What this milestone waits on

Three things were found in the tools the runner drives. Each is reported to its owner; none is worked round here.

1. **The render failure** described above. It is put right in version 0.13.1 of the slides tool, which is the oldest version `slides.MINIMUM` accepts, so nothing waits on it any more.
2. **Caveat and source lines are smaller than the brand's audit allows.** The audit will warn on every content slide until the brand's type role or its audit changes.
3. **The outline's word budget counts body words only.** The runner applies its own budget of visible words on top.

## Done when

- The suite passes and `validate_package.py` prints `ok`.
- A real training with a deck runs on Claude from the form to an approved deck in the brand's template, decided on the page, with previews through Google Drive.
- The outline's gate and one section are run for real on Codex.
- Not claimed without a person: that a deck is good. The gate is where that is judged.

## Deviations

Where what was built differs from the text above, the code is right and this section says how.

**Where things are kept**

- Everything a deck is built with is under `work/deck/` in the deck's own place, which is ignored and never shared: the exported brand, what the slides tool tells its workers, the sections, the builds, the last preview and its pictures. `deck-handoff.md`, `deck/outline.json`, `deck/review.json` (what the gate showed of the deck that was saved) and the deck itself are shared.
- A deck that is saved and current has no steps left, on any computer. On a computer that did not render it, its gate shows the review, the audit and the coverage, and no pictures.

**The pipeline**

- A section drawn again exactly as it was is not rendered or reviewed again.
- With no way of rendering chosen at set-up, LibreOffice is used when it is there. Google Drive is never chosen silently.
- The person's words of approval go into the copy of the outline that is handed to the slides tool, not into `deck/outline.json`.
- The reviewer's eight questions are the runner's own list, in `deck.QUESTIONS`, numbered as the tool numbers its own. The tool does not hand its questions to a caller.
- Every finding of the tool's own check of an outline is held against the outline's writer, the ones the tool only asks to be looked at among them.
- The tool splits a deck into sections at its section slides. A deck with no section slide is one section, drawn by one worker.
- A composer is offered only the icons the slides tool can place. One that is a picture is left out of what a search returns.
- The slides wrapper has no call for the tool's own first draft of an outline, and the runner does not use one: the outline is the worker's. The brand wrapper's readiness check is wrapped and not yet shown on the page.
- A brand skill lists every brand with at least one variant. The brand wrapper still takes no variant, and then leaves the choice to the skill.

**What a worker is given**

- `Slides.reading()` reads the installed tool's own guidance: its design guidance, its composition guidance, its drafting guidance, what its gallery is for, and one drawn example for each relation. Each is a file inside the tool's folder, read and never run, and cut off at a fixed length. The brand step keeps them beside the two contracts.
- A composer's inputs are its brief, the composition contract, the design guidance, the composition guidance, the gallery, and the example of each relation its own slides have. The outline's writer is also given the drafting guidance. Guidance the installed tool does not have is left out.
- The engine tells each job of a deck where the slides tool and the brand skill are, from `Slides.runtime` and `Brand.runtime`, so the worker tools' server uses the same two as the engine.

**The page and the runner**

- In `GET /api/run`, a section's `slides` are numbered within that section's own latest preview, from 1. Those are the numbers `GET /api/slide?path=&section=&number=` takes: where a slide falls in the deck is not known until the sections are merged. `titles` beside them gives each its title.
- A section's pictures, and `deck` in the run, are answered only while that deck is in hand: from its first step until its gate is decided.
- `outline` in the run carries `sha256`, and the page sends it back as `seen` with its decision. A decision about words that changed since they were read is refused.
- `brand` in `GET /api/setup` carries `skills`: every brand skill found, as `{"name", "path", "chosen"}`. `POST /api/setup` takes `brand_skill`, one of those paths. The page offers the choice when more than one was found.
- The gate's `audit` also carries `blockers`: what the brand's check holds against the deck, or why it could not be run.

**The core**

- One change: the page's Content-Security-Policy is `default-src 'self'; img-src 'self' blob:`, so that a slide fetched with the key in its header can be shown from memory. Nothing else in the policy changed.

## What the first real run showed

Run on 2026-10-13, through the page in a browser, on Claude Code, with the slides tool at 0.13.1 and a brand skill at 0.13.1, previews through Google Drive.

- **A training with a deck ran from the form to the deck's gate with no conversation.** The outline, two sections drawn side by side, a review, one repair round of both sections, a second review, and the deck saved as PowerPoint in the brand's template. The whole training cost $8.73 as Claude Code reported it, of which the deck was about $4.60.
- **The outline's gate earned its place.** The first outline was 18 slides for a 15-minute lesson. Asked on the page to cut it to eight, the worker did, and said what the cut cost: the recap, the worked examples and the misconceptions moved to speaker notes.
- **The deck's gate did not flatter the deck.** It showed one critical, one major and seventeen minor findings, each with its slide, with every slide as a picture made from the file being decided on. The critical one was real: the closing slide had a title and an empty body.

Put right because of it:

- The outline writer is told to size a deck to the time it has, about two minutes a slide.
- A closing slide is the brand's own last slide, which has no body: the runner now holds it to a title and one subtitle line of a few words, and the handoff asks for what to practise next on a drawn content slide before it. A slide the runner makes itself is one no repair round can reach.

Not run for real: a deck as Google Slides, a deck for a training with levels, LibreOffice previews, a second repair round, and a deck on Codex.

## The outline gate with a design

Added 2026-10-14 for issue #43, which is milestones 1 and 2 of the [visual teaching plan](../plans/2026-10-14-visual-teaching-in-decks.md) on this side. It follows Harness Slides' [design integration contract](https://github.com/dbbaskette/harness-slides-skill/blob/main/docs/specs/2026-10-14-design-integration-contract.md): schema 2 proposals, one question for the whole plan, and refusals as JSON. Harness Slides keeps the one record of design approval. The runner adapts to it and keeps no second approval model.

- **Whether a tool has it is asked of the tool.** `Slides.designs()` proposes a missing file into an empty folder that is thrown away, with `--mode batch --json`. A tool with the design session refuses as JSON on standard output and writes nothing; 0.13.1 does not know `--mode`. The version is not read for this. `MINIMUM` stays 0.13.1 until the release.
- **Each deck keeps the gate it started with.** When a deck's outline is first written, it is written with a design if the tool has the session, and with words alone if not. Its run record says which, and every later draft of that deck is written the same way. A deck that is already past its gate, or waiting at it, keeps its approval and its words-only gate. A deck written with a design, on a computer whose tool no longer has the session, stops with a sentence saying to update harness-slides.
- **The outline's writer hands in both together.** `check_outline` and `submit_outline` take `design` beside the outline: one entry for every slide, the cover, section and closing slides too, holding `intent` (the claim as `takeaway`, the audience question, the relationship, the rationale, the alternative weighed, and the visual with its teaching purpose), `composition`, `asset` with its candidates, and `qualifications`. The runner makes the schema-2 proposal from the two (`deck.proposal`). The title, the copy, the notes, the objectives and the sources come from the outline, so the visible copy has one source and the learning requirement, `understand`, stays apart from it. A lead slide's copy is its subtitle, or its title; its source is the outline. The proposal is checked by proposing it into a project of its own in the job's folder, which is then removed. Each JSON refusal goes back to the worker as its slide and detail, with the tool's fallback when it offers one.
- **What is kept.** `deck/design.json` is the proposal, beside `deck/outline.json`. The deck's own `deck/` folder is the design project, so the tool's record, `deck/.harness-slides/design/session.json`, is shared like the outline. A lock left by a stopped command is already ignored.
- **The gate.** `gate:deck-outline` proposes `deck/design.json` with `--mode batch`, and with `--expected` when the tool already holds a revision, so that a slide whose design is unchanged keeps its approval. The run record's `waiting` holds the outline's hash, and `design`: the proposal's hash, the revision, whether the tool already allows a build, and its question.
- **One decision, one answer.** The page's decision is sent to the tool as one `design respond`, with the question and revision that were put to the person. The feedback is the person's note, or, approving without one, the option they chose, word for word: `Approve the whole plan`, or `Approve these designs` when only some slides are asked about. When the tool has nothing to ask, because its approvals still hold after a change to the notes alone, approval is recorded against the revision and nothing is sent. No worker has a tool that answers, and nothing but `Engine.outline` calls `design_respond`.
- **The binding.** `approved` holds the outline's hash and `design: {sha256, revision}`. The gate is passed only while the outline, the proposal and the approval all match. The start runs `design check`, refuses a revision other than the one approved, and records the approved design, so a new design makes the start and everything after it stale.
- **A stale decision is refused.** The page sends `design`, the revision it read. A decision for another revision is refused before the tool is asked, and one the tool refuses as stale is refused with the same sentence. Nothing is recorded either way.
- **On the page** each slide's copy sits beside how it is drawn: the visual and its purpose, the layout, the claim, why, what it was weighed against, the asset decision and each candidate with whether it is resolved yet, and the wording the copy must keep. "Worth a look" lists every candidate not resolved yet. A slide whose design was approved before and is unchanged says so.
- **Tests.** Rows V01, V02, V03 and V13 of the plan's matrix are tests of those names in `tests/test_runner_deck.py`. `tests/fixtures/visual-contract/` is a copy of Harness Slides' contract fixture, and `tests/test_runner_slides.py` runs every `design` case in it through the wrapper. The command-line stand-in plays both 0.13.1 and the design session, and its output and session files were compared with the real command line from Harness Slides' `main`; they match apart from timestamps.

## Sections built from the approved design

Added 2026-10-14 for issue #44, the rest of milestone 2 of the [visual teaching plan](../plans/2026-10-14-visual-teaching-in-decks.md) on this side. It follows the contract's "Sections": a section is declared with `--section` beside `--design-project`, and never inferred. Everything here is for a deck written with its design. A deck written with words alone is started, briefed, held and built exactly as before, whatever the tool can do.

- **Whether a tool can is asked of the tool.** `Slides.sections()` runs `compose compile --file <missing> --section --json` in a folder that is thrown away. A tool that checks sections refuses it as JSON `input-invalid` (`--section` needs `--design-project`) before it reads the file; 0.13.1 does not know `--section`. Having the design session is not taken to mean having this.
- **The start.** `deck-start` of a deck with a design needs `sections()`. Without it the step stops with "Update harness-slides, then try again" and the approval is kept; trying again once the tool can carries on without asking anything again. The start keeps the plan `design check` returned as `given/design.json`, written as the tool gave it, so its keys keep their order. A start without that file is not done, and is made again from the same approval. The house rules are `DESIGNED_HOUSE`: the rule that called an icon optional becomes "Draw what the approved design says", keeping that an icon names a recognisable thing, the same icon for the same concept, never twice on one slide.
- **The brief.** Each section's brief gains "The approved design": for each of its slides the claim, the question it answers, the relationship, the visual and its purpose, how it is drawn, why, what it was weighed against, the asset decision with its candidates, the wording it must keep, and its `intent` to copy. Then "Icons across the deck": every icon candidate of every slide, by concept, with the slides that show it, so that sections drawn side by side use one icon for one concept. The deck's direction is in the brief as before. Only icons can be placed yet; a composer names a picture it could not place when it hands in.
- **The guidance.** `briefs.guidance('deck-section', design=True)` replaces the parts of `deck-section.md` with the same headings in `deck-section-design.md`: the approved design is fixed, the composer realises it, draws direct text where the design chose it and adds nothing to decorate it, and places the icons the design names. Drawn again after a review, it puts a drawing right within its design; a finding that would need another concept is not its to act on. Without a design the guidance is the file as it was, word for word.
- **What is held.** `deck.fixed(..., design)` takes each slide's title and its points, caveat and source from the approved `copy`, adds the qualifications, and adds the approved `intent` as the JSON text the tool compares. `deck.kept` refuses a slide whose `intent` is missing or not the approved one, and a qualification that is not among the words the slide shows. The focal statement is part of the tool's approved text, but the page does not show it as copy, so it is not held as wording. Harness Slides compares intents as `JSON.stringify` writes them, so the order of keys counts; an intent equal to the approved one is written back in the approved order (`deck.as_approved`) before the tool sees it.
- **Built against it.** `check_section` and `preview_section` compile and preview with `--design-project deck/ --section --json`, and the whole deck is compiled and previewed with `--design-project deck/ --json`. A refusal comes back to the composer slide by slide, as the tool words it.
- **Tests.** V04 (a repair keeps the design approval) and V14 (a tool that cannot check a section) are tests of those names in `tests/test_runner_deck.py`. `tests/test_runner_slides.py` runs the fixture's `compose compile` cases against the design through the wrapper. The stand-in plays `--design-project`, `--section` and `--json` on compile and preview after 0.13.1, and was compared with the real command line from Harness Slides' `main` for 24 calls: the probe, sections and decks in every order, a changed title or intent, intents written without a project, and a preview after the design moved on. All were the same.

Since Harness Slides #58 the design session names no folder: the tool is told the project with `--project` each time, and a compiled build names the files it was made from relative to itself when both lie in the project. The session the runner commits no longer holds a path of the computer that proposed it.

Not yet: assets (#45–#46), and the review against the design (milestone 4).

## Appendix: what the page asks the runner

Additions to the earlier contracts. Everything there stands.

- `GET /api/setup` gains `previews`: `{"how": "drive" | "local" | null, "drive": bool, "local": bool, "left": [{"name", "url", "training"}]}`, and `brand`: `{"found": bool, "name": str or null, "brands": [{"brand", "name", "variants": [str]}], "problem": str or null, "skills": [{"name", "path", "chosen": bool}]}`. `POST /api/setup` takes `previews`: `"drive"` or `"local"`, and `brand_skill`: the `path` of one of `skills`.
- `POST /api/trainings`: `brand` is now `{"brand", "variant"}` or `null`.
- `GET /api/run` gains `outline`: `null`, or `{"level": str or null, "waiting": bool, "sha256": str, "slides": [{"id", "kind", "title", "subtitle", "understand", "points": [{"label", "text"}], "caveat", "source", "notes", "serves": [str]}], "checked": [str], "worth": [str], "note": str or null}`; and for a deck being drawn, `deck`: `{"level", "sections": [{"id", "state", "previews": int, "slides": [int], "titles": [str]}], "pictures": int, "before": {"dollars": float, "minutes": float} or null}`. A section's `slides` are numbered within the section, from 1, and `titles` are theirs in the same order. Milestone 3's `deck`, the notice when the deck is all that is left, is renamed `deck_left`.
- `POST /api/outline` with `{"path", "level", "decision": "approve" | "revise", "note", "seen"}` returns the run. `seen` is the `sha256` of the outline that was read.
- Added with the design (issue #43): `outline` in `GET /api/run` gains `design`: `null` for words alone, or `{"revision": str or null, "asked": [slide ID]}`, the revision put to the person and the slides its question covers. Each of its `slides` gains `design`: `null`, or `{"claim", "question", "family", "purpose", "drawn", "why", "alternative": {"treatment", "reason"} or null, "asset": {"description", "disposition", "reason"}, "candidates": [{"kind", "ref", "concept", "status"}], "keeps": [str]}`. `POST /api/outline` takes `design`, the revision that was read.
- `GET /api/gate` for a deck gains `slides`: `[{"number", "id", "title"}]`, `review`: `{"round": int, "findings": [{"slide", "number", "severity", "about": "drawing" | "content", "note", "fix"}]}`, `audit`: `{"status", "warnings": [{"code", "count", "says"}]}`, and `coverage`: `[{"objective", "says", "reviewed": [int], "cited": [int]}]`.
- `GET /api/slide?path=&artifact=&number=` answers one slide's picture as `image/png`, for a deck the runner rendered. It needs the key in its header like every other read, so the page fetches it and shows it from memory; a picture is never an address a document could point at. `GET /api/slide?path=&section=&number=` answers a section's latest preview.
