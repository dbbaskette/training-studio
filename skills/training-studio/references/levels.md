# Levels

A level is a depth tier of the same subject. Each assumes the one before.

| Level | Depth | In field enablement |
| --- | --- | --- |
| 101 | What it is, why it matters, core vocabulary. No prerequisites | Positioning and the pitch |
| 201 | How it works, common tasks, standard use cases | Discovery, qualification, demonstration |
| 301 | Architecture, tuning, troubleshooting, trade-offs | Technical deep dive; objections from engineers |
| 401 | Internals, design at scale, edge cases | Architecture workshops; competitive displacement |

## What is shared and what is per level

Intake and research are done once. Everything from the blueprint down is produced for each level, in that level's folder:

```
301/blueprint.md      301/document.md     301/product-brief.md
301/deck.pptx         301/scenario.md     301/scenarios/   301/yoodli/
```

Artifact names carry the level: `blueprint@301`, `document@301`, `brief@301`, `deck@301`, `scenario:main@301`, `yoodli:main@301`. Checks do too: `blueprint.structure@301`.

Levels are independent. Nothing in one level is an input to another, so editing one never makes another stale. A scenario file at the top of the directory belongs to no level and is ignored.

## Order of work

1. Research once, weighted toward the deepest level asked for. That level needs questions about mechanisms, limits and failure modes. If the levels together need more than 30 questions, propose two directories, for example 101 with 201 and 301 with 401.
2. Draft the blueprint for every level before any is approved, and present them together. Overlap and gaps between levels show here and nowhere else.
3. Then finish one level at a time, lowest first: document, brief, deck, scenarios. Record the level in hand with `training.py checkpoint --level 301`.

## Writing a level

- The blueprint's frame carries `Level: 301` and says what the learner is assumed to have from earlier levels.
- A level does not re-teach an earlier one. It names that material as assumed. `check` warns when two levels state the same objective.
- Each level is sized on its own: a 101 may be a lesson and a 301 a course.
- The brief for a level is written to that level's depth.

## Adding a level later

`training.py checkpoint --levels 101,301` adds 301 and leaves 101 as it is. A plain training cannot be given levels; it needs a new directory.

If the new level needs more research, the top-up changes the shared research. Every existing level's blueprint and brief then show as stale. For a level whose content the new findings do not touch, ask the user, then accept each as it is:

```sh
training.py approve blueprint@101 --accept-stale "<their reason>"
training.py approve brief@101 --accept-stale "<their reason>"
```

That level's document, deck and scenarios return to approved by themselves, because their own inputs did not change.
