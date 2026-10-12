# Blueprint

The blueprint turns research into a teaching plan. Design it backward: what the learner must be able to do, how you would know they can, then the content that gets them there.

Follow the shape of the example blueprint exactly. `training.py check` reads its headings, IDs and line prefixes.

## Sections, in this order

`## Frame`, `## Sizing`, `## Objectives`, one `## M<n> — <title> (<minutes> min)` per module, `## Assessment plan`, `## Practice plan`, `## Open gaps`. A plain hyphen or a colon works in place of the dash.

The frame gives the audience, purpose and time, and for a competitive brief the two sides. With levels it also has a line `Level: 301` and says what earlier levels are assumed.

## Sizing

| Size | When |
| --- | --- |
| Lesson | Up to 5 objectives and 45 minutes. One module |
| Course | 2 to 6 modules of 3 to 5 objectives each |
| Separate trainings | More than 6 modules. Propose a split, each part in its own directory |

Propose the size the research supports and give the reason. Do not pad to reach a size. A time limit from intake wins: fit it, and list what was cut.

## Objectives

`### O<n> — <one observable behaviour> [<level>]`

| Level | The learner can |
| --- | --- |
| `recall` | State it |
| `explain` | Say why or when, in their own words |
| `apply` | Use it on a new case |
| `handle` | Hold a live conversation about it: answer an objection, run a discovery call |

Write behaviours you could watch someone do. "Understand rolling restarts" is not one. "Explain when a rolling restart keeps capacity" is.

## Modules

Under each module heading, one item per line:

- `Objectives: O1, O2`
- `- K<module>.<n>: <one claim> [R:<finding-id>]` for each key point. Cite every finding the claim rests on. Only `supported` findings can be cited.
- `- K1.4: <claim> [unsupported]` for a claim the research could not support. It will not be taught, and it must also appear under Open gaps.
- `Misconception: "<what people believe>" Correction: <what is true> [R:<finding-id>]`. A correction may cite a `contradicted` finding.
- `Example: <one concrete worked example>`. At least one per module.

## Assessment plan

One line per objective: `- O1: Check: <knowledge-check question> | Observe: <what a practice session should show>`

The check goes into the document; the observation guides the scenarios. Each must ask for the behaviour its objective names: explaining a procedure is not evidence of being able to perform it.

## Practice plan

One line per scenario, proposed or already supplied: `- <scenario-id>: <mode>. Objectives: O2, O3. <who the AI plays, in a phrase>`

Modes are `roleplay`, `pitch`, `tutor` and `questionnaire`. Use `roleplay` or `pitch` for `handle` objectives. If the user already has scenario files, list those and say which objectives each exercises. The section is optional when scenarios are skipped.

## Open gaps

Every unresolved research question that affects the training, every `[unsupported]` key point by its ID, and what the training leaves out as a result.

## Gate 3

Write the first version to `blueprint.md` and run `training.py save blueprint --built`. Save later versions with `--from <file>`. Run `training.py check` and fix what fails.

Present the gate as the gates reference describes. If a gap matters, offer a research top-up before approval.

On approval: `training.py approve blueprint`, then `training.py checkpoint --no-question --stage document --next "Write the learner guide"`. With levels, approve every level's blueprint first and use the checkpoint in the levels reference.
