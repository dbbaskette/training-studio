# Training Studio working agreements

- **No training content here.** Tests use temporary directories. Acceptance runs use disposable directories outside this repository. The helper refuses to start a training in this directory.
- **Verification is proportional.** Work in coherent increments and run the targeted tests at each milestone. Run the whole suite once before calling work complete. A wording-only change to guidance needs `validate_package.py`, not the suite.
- **The helper has no dependencies.** Python 3.11 or newer, standard library only. The core commands, `status` and `check` among them, never use the network. Only guidance sync, `google` and `hub` do, each at the user's request.
- **A format lives in four places.** The files under `skills/training-studio/assets/examples/` are the templates the guidance points to and the fixtures the tests read. Changing a format means changing the checker, its tests, the example and the guidance together.
- **Guidance is disclosed progressively.** `SKILL.md` is the whole entry and links every reference and example itself. Each stage file carries its own commands. When a file goes over its budget, cut it; do not raise the budget. `validate_package.py` enforces this.
- **Guidance is harness-neutral.** It names no harness-specific tools, so it runs on Claude Code and Codex alike.
- **Yoodli facts live in one file:** `skills/training-studio/assets/profiles/yoodli.json`, each with its source and date. Record only what Yoodli's pages state.
- **`main` is live.** New trainings fetch their guidance from it. Guidance that needs a script change raises `minimum_runtime` in `guidance/manifest.json` and the `VERSION` together.
- **The README is for a new user.** It takes someone from nothing to a first training in plain language. Technical detail goes in `docs/` and is linked from it.
- **Research and decks are delegated.** Do not add research or slide-building logic here; they belong to `harness-research` and `harness-slides`.
- **State changes need a matrix row.** A change to status, approval, inputs or readiness adds or updates a row in the plan's state-transition matrix and its test.
