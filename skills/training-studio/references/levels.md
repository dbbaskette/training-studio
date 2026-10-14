# Levels

A level is a depth tier of the same subject. Each assumes the one before.

| Level | Depth | In field enablement |
| --- | --- | --- |
| 101 | What it is, why it matters, core vocabulary. No prerequisites | Positioning and the pitch |
| 201 | How it works, common tasks, standard use cases | Discovery, qualification, demonstration |
| 301 | Architecture, tuning, troubleshooting, trade-offs | Technical deep dive; objections from engineers |
| 401 | Internals, design at scale, edge cases | Architecture workshops; competitive displacement |

## What is shared and what is per level

Intake and research are done once. Everything from the blueprint down is produced for each level, in that level's folder: `301/blueprint.md`, `301/document.md`, `301/scenario.md`, `301/yoodli/`.

Artifact names carry the level: `blueprint@301`, `document@301`, `brief@301`, `deck@301`, `scenario:main@301`, `yoodli:main@301`. So do check names.

Levels are independent: editing one never makes another stale. A scenario file at the top of the directory belongs to no level and is ignored.

## Order of work

1. Research once, weighted toward the deepest level asked for. That level needs questions about mechanisms, limits and failure modes. If the levels together need more than 30 questions, propose splitting them across two directories.
2. Draft the blueprint for every level before any is approved, and present them together. Overlap and gaps between levels show only here.
3. Then finish one level at a time, lowest first: document, brief, deck, scenarios.

`approve` keeps this order itself: once every blueprint is approved it moves to the lowest level's document, after a level's last stage to the next level, and after the last level to the package.

One `README.md` covers the whole training, at the top. `deck-handoff.md` sits in the level's folder, and each level's deck is its own `harness-slides` task, as the deck-handoff reference describes.

## Writing a level

- The blueprint's frame carries `Level: 301` and says what the learner is assumed to have from earlier levels.
- A level does not re-teach an earlier one. It names that material as assumed. `check` warns when two levels state the same objective.
- Each level is sized on its own, and its brief is written to its depth.

## Adding a level later

`training.py checkpoint --add-level 301` adds 301 and leaves 101 as it is. A training past its blueprints goes back to the blueprint stage for 301. A level with work in it is never dropped. A plain training cannot be given levels; it needs a new directory.

If the new level needs more research, the top-up changes the shared research. Every existing level's blueprint and brief then show as stale. For a level the new findings do not touch, ask the user, then accept each as it is: `training.py approve blueprint@101 --accept-stale --reason "<their reason>"`, and the same for `brief@101`. That level's document, deck and scenarios then return to approved by themselves, because their own inputs did not change.
