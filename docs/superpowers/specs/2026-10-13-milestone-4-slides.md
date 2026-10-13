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

1. **The render failure** described above. Until it is put right in the slides tool, a deck cannot be previewed or rendered with the brand's template as exported, so the real run in "Done when" cannot finish.
2. **Caveat and source lines are smaller than the brand's audit allows.** The audit will warn on every content slide until the brand's type role or its audit changes.
3. **The outline's word budget counts body words only.** The runner applies its own budget of visible words on top.

## Done when

- The suite passes and `validate_package.py` prints `ok`.
- A real training with a deck runs on Claude from the form to an approved deck in the brand's template, decided on the page, with previews through Google Drive. This needs the first item above.
- The outline's gate and one section are run for real on Codex.
- Not claimed without a person: that a deck is good. The gate is where that is judged.

## Appendix: what the page asks the runner

Additions to the earlier contracts. Everything there stands.

- `GET /api/setup` gains `previews`: `{"how": "drive" | "local" | null, "drive": bool, "local": bool, "left": [{"name", "url", "training"}]}`, and `brand`: `{"found": bool, "name": str or null, "brands": [{"brand", "name", "variants": [str]}], "problem": str or null}`. `POST /api/setup` takes `previews`: `"drive"` or `"local"`.
- `POST /api/trainings`: `brand` is now `{"brand", "variant"}` or `null`.
- `GET /api/run` gains `outline`: `null`, or `{"level": str or null, "waiting": bool, "slides": [{"id", "kind", "title", "subtitle", "understand", "points": [{"label", "text"}], "caveat", "source", "notes", "serves": [str]}], "checked": [str], "worth": [str], "note": str or null}`; and for a deck being drawn, `deck`: `{"level", "sections": [{"id", "state", "previews": int, "slides": [int]}], "pictures": int, "before": {"dollars": float, "minutes": float} or null}`. Milestone 3's `deck`, the notice when the deck is all that is left, is renamed `deck_left`.
- `POST /api/outline` with `{"path", "level", "decision": "approve" | "revise", "note"}` returns the run.
- `GET /api/gate` for a deck gains `slides`: `[{"number", "id", "title"}]`, `review`: `{"round": int, "findings": [{"slide", "number", "severity", "about": "drawing" | "content", "note", "fix"}]}`, `audit`: `{"status", "warnings": [{"code", "count", "says"}]}`, and `coverage`: `[{"objective", "says", "reviewed": [int], "cited": [int]}]`.
- `GET /api/slide?path=&artifact=&number=` answers one slide's picture as `image/png`, for a deck the runner rendered. It needs the key in its header like every other read, so the page fetches it and shows it from memory; a picture is never an address a document could point at. `GET /api/slide?path=&section=&number=` answers a section's latest preview.
