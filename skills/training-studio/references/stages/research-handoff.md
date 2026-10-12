# Research handoff

The `harness-research` skill does the research. Training Studio hands it the approved plan and records what comes back.

If `harness-research` is not installed, stop here and point to https://github.com/dbbaskette/harness-research-skill. Nothing else may stand in for it.

## Run

1. Load the `harness-research` skill and follow its entrypoint with this directory as the project.
   - **First time:** start a task. It returns a task ID and a runtime path. Record them: `training.py pin harness-research --task <id> --runtime <path>`.
   - **Resuming or revising:** continue the pinned task through that skill's resume entrypoint, with the task ID from `training.py status`. Do not start another. A task is that skill's guidance and runtime record; it is not a new chat or session.
2. Save the approved plan with that skill's helper: `node "<runtime>/scripts/harness-research.mjs" plan --project . --file .training-studio/research-plan.json`. Pin again, adding `--run <the run it returns>`.
3. Follow that skill's own guidance to investigate each question and record each finding as you go. Intake is settled: do not ask the user again about scope, sources or purpose.
4. Do that skill's completion checks: refresh its status, open the report, confirm the findings are saved.

A failed guidance fetch or a blocked network is handled by that skill's rules. Report the failure. Never describe research as current when it is not.

## Gate 2

`training.py save research --built`, then present the gate, taking the numbers from the `harness-research` report and its status output: counts of supported, contradicted, insufficient and unavailable findings; each unresolved question by name; document coverage gaps. Name any question still pending. Approving with questions pending is the user's decision.

`training.py approve research` approves a bundle: the live report, the record `.harness-research/research.json` and the copy it writes to `research-report.md`. It stores the findings index that citations are checked against. If it warns the index could not be read, tell the user that citation checks will report `unavailable`.

Afterwards a change to any of the three returns research to `draft` and makes everything built from it stale. Never edit `research-report.md`.

Then `training.py checkpoint --no-question --stage blueprint --next "Draft the blueprint"` and read the blueprint reference.

## Keeping research current

On resume, and before each later gate, refresh `harness-research` status through the pinned runtime: `node "<runtime>/scripts/harness-research.mjs" status --project .`. If it reports stale evidence, its report changes and `training.py status` shows research as `draft`. Tell the user; do not carry on as if the findings still held.

## Research top-up

Use this when a gap matters enough to research further, or a new level needs more.

1. Write an extended plan to a scratch file: every existing question unchanged, with the same ID, plus the new ones.
2. `training.py save research-plan --from <that file>`. Present gate 1 for the added questions only, then `training.py approve research-plan`.
3. Save the plan with the `harness-research` helper. A changed plan starts a new run with no results; the previous run is kept under `.harness-research/history/`.
4. Record each earlier finding again from the saved previous run, without browsing again, wherever its evidence snapshots are unchanged. Investigate only the new questions.
5. Repeat gate 2. Blueprints and briefs then show as stale: rebuild those the new findings affect, and ask the user about accepting the rest as they are.
