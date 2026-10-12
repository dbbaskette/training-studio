# Deck handoff

The `harness-slides` skill plans and builds the deck. Training Studio does not write a slide plan. It writes a one-page handoff, starts the task, and records the result.

If `harness-slides` is not installed, run `training.py skip deck --unavailable --reason "harness-slides is not installed"`, tell the user, and move on to the scenario stage.

## Write `deck-handoff.md`

One page, with these headings:

- **Goal.** What the audience should be able to do after the deck, from the blueprint's objectives.
- **Audience and duration.** From intake and the blueprint.
- **Use.** The deck is both presented and distributed. Every slide must make sense to someone reading it alone, so no slide may depend on its speaker notes for meaning. The notes carry the talk track and timing for a presenter.
- **Required elements.** The objectives near the start; a check for understanding in each module; a recap; a closing slide that points to the practice scenarios.
- **Sources.** `blueprint.md`, `document.md` and `research-report.md`. When the document is skipped, `blueprint.md` and `research-report.md`.
- **Research.** Complete. Work from the sources only and start no new research. Anything under the blueprint's open gaps stays out.
- **Output.** Google Slides or PowerPoint, from `settings.deck_target`, and the brand from `settings.brand` if one is set.

`deck-handoff.md` is derived. Rewrite it whenever the blueprint or the settings change; never `save` it.

## Run

1. Load the `harness-slides` skill and follow its entrypoint with this directory as the project. Start a task the first time; on a later visit, continue the pinned task through that skill's resume entrypoint.
2. `training.py pin harness-slides --task <id> --runtime <path>`. With levels, use the level's folder as the project and add `--level <level>`.
3. Give it `deck-handoff.md` and the source files, and follow its own guidance. Intake is settled: answer its intake questions from the handoff. Its own draft and review steps with the user still apply.
4. Creating or changing a Google Slides deck follows that skill's authorisation rules.

## Record

- **PowerPoint:** `training.py save deck --from <the built .pptx>`. The helper refuses a file that is not a real PowerPoint file. If the deck could not be built, mark it unavailable; never record a placeholder.
- **Google Slides:** write `deck-link.md` with the deck's URL, title and ID, then `training.py save deck --built`.

## Review coverage

Read the finished slides and note which slides address each objective. Write the result to a scratch JSON file, objective ID to slide numbers, with an empty list for an objective you could not find:

```json
{"O1": [3], "O2": [5, 6], "O3": []}
```

Record it with `training.py save deck --coverage <file>`. This is your review judgment, so present it as reviewed, not as checked.

The review is tied to that exact deck and blueprint. If either changes, `check` reports the coverage as unavailable until you review the deck again and record it again.

## Gate 6

Present the gate as the gates reference describes: where the deck is, and the reviewed coverage, naming any objective you could not find.

On approval: `training.py approve deck`, then `training.py checkpoint --no-question --stage scenario --next "Prepare the scenarios"`.

Changing the deck target or the brand makes the deck stale. Edits made to a Google Slides deck after approval are not detected.
