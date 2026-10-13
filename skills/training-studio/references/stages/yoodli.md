# Yoodli scenarios (optional)

This stage runs only when the user asked for it, which shows as `yoodli` in `settings.stages`.

- Turn it on: `training.py skip yoodli --clear`. It needs the brief and the scenarios, so restore those first if they were skipped.
- Turn it off: `training.py skip yoodli --reason "<why>"`. Files already written stay where they are and are no longer tracked.

For each approved scenario it writes `yoodli/<id>.md` (`yoodli:<id>`): the scenario laid out in the fields of Yoodli's roleplay Builder, with the brief as the AI's knowledge.

## Build

Read the Yoodli profile reference for the fields, limits and counts, and the mode reference for how that mode maps. Follow the example Yoodli scenario.

The file need not share wording with the brief, but every product fact in it must be one the brief supports.

Under each goal, outside the pasteable blocks:

- `<!-- criterion: 2 -->` names the success criterion the goal carries. Every criterion in the scenario file needs a goal; one goal may carry several.
- `<!-- assesses: O3 -->` names the objective it assesses, where one applies.

`training.py save yoodli:<id> --built`, then `training.py check --all`. With this stage on, the `practice` report is taken from the goals' `assesses` comments.

## Gate 8

For each, present the scenario and its Yoodli file together as the gates reference describes:

- which goal carries each success criterion,
- the counts against Yoodli's limits, and that the limits are provisional while `check` says so,
- whether the brief's Google Doc or export is `current`, since it is the file the user uploads,
- your judgment of whether the context and goals agree with the brief.

On approval, for each: `training.py approve yoodli:<id>`. If `exports` in `training.py status` lists `yoodli:<id>`, make its Word copy as the workspace reference describes and record it with `training.py export yoodli:<id>`, or `--unavailable "<why>"`.

Then `training.py checkpoint --no-question --stage package --next "Write the index"`. With levels, use the checkpoint in the levels reference: another level may remain.

## Afterwards

If the user edits a scenario file, its Yoodli scenario becomes stale and nothing else does. Rebuild that one.

Training Studio prepares files. Creating the roleplay in Yoodli, and uploading anything to it, are the user's actions.
