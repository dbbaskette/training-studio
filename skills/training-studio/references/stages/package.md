# Package

The last stage writes the index and reports whether the training is ready. It has no gate.

## Check readiness

Run `training.py check --complete --all` and `training.py status`.

- `ready` is true only when every wanted artifact is approved, nothing is stale, no check failed or could not run, no copy is out of date, and no question is waiting on the user.
- `blocking` lists each reason it is not ready.
- `limitations` lists what was skipped at the user's request or could not be produced.

If `ready` is false, resolve what you can, tell the user what remains, and do not describe the training as complete.

## Write `README.md`

1. **Title, audience, purpose, size and levels**, from intake and the blueprints.
2. **Objectives**, in plain language. With levels, a section per level.
3. **What is here.** A table of every artifact: what it is, its file as a link, and its status. Link its gate review in `reviews/` where there is one.
4. **Copies.** Each Google Doc that `google_docs` reports `current`, with its link from `training.py google status --offline`, and each export that is `current`, with its path. List none that is not `current`. If Yoodli is on and the brief has no `current` copy to upload, say the Yoodli handoff is incomplete and what the user can do instead.
5. **Coverage**, one row per objective, with the basis of each column in its heading:
   - "Document (declared)", from the `document.coverage` check.
   - "Deck (reviewed)", from the recorded review.
   - "Practice (exercised)", from the `practice` report, naming its `basis`.
   A stage that was skipped or unavailable shows that word, not a tick.
6. **Open gaps**, from the blueprints, and **limitations**, from `check`.
7. **Using the scenarios.** Where the scenario files are, and that each works with any AI that can play a role, with the brief as its reference. If Yoodli is on: where the Yoodli files are, that building the roleplay in Yoodli's Builder is the baseline, and that Yoodli's limits are provisional until the user confirms a paste.
8. **Research.** A link to `research-report.md`, with the approval date and the count of findings by status, both from `research` in `training.py status`.

`README.md` is derived. Rewrite it when anything changes; never `save` it.

## Report

Tell the user in a few lines: what was produced, whether it is ready, what is blocking, the limitations and the open gaps.

Then `training.py checkpoint --stage done --next "Nothing pending"`. The marker records where the run stopped. It does not prove the training stays complete: a later edit makes `ready` false again, so run `check` whenever the user comes back.

## Afterwards

If Yoodli was used: when the user reports how a paste into Yoodli went, note each field name or limit that differed. A successful paste confirms the fields were accepted. It says nothing about factual grounding or the quality of the goals.

Corrections belong in the skill's `assets/profiles/yoodli.json` and its Yoodli profile reference, which are changed in the skill's repository, not from a training directory. Tell the user what to change there.
