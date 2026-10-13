# Workspace

Deliverables are files in the training directory. Bookkeeping is under `.training-studio/`.

## Artifacts

| Artifact | File | Built from |
| --- | --- | --- |
| `intake` | `intake.md` | nothing |
| `research-plan` | `.training-studio/research-plan.json` | `intake` |
| `research` | `.harness-research/research-report.md`; copied to `research-report.md` on approval | `research-plan` |
| `blueprint` | `blueprint.md` | `intake`, `research` |
| `document` | `document.md` | `blueprint` |
| `brief` | `product-brief.md` or `competitive-brief.md` | `blueprint`, `research`, the brief kind |
| `deck` | `deck.pptx`, or `deck-link.md` for Google Slides | `blueprint`, `document`, the deck target and brand |
| `scenario:<id>` | `scenario.md` (the ID is `main`) or `scenarios/<id>.md` | nothing; the user owns it |
| `yoodli:<id>`, only if Yoodli is on | `yoodli/<id>.md` | `blueprint`, `brief`, `scenario:<id>`, the Yoodli profile |

`deck-handoff.md` and `README.md` are derived: regenerate them, never `save` them.

## Status

| Status | Meaning |
| --- | --- |
| `not-started` | The file does not exist |
| `draft` | Not approved in its current form |
| `approved` | The content and what it was built from are what the user approved |
| `stale` | Something it was built from has changed, or is itself stale |
| `skipped`, `unavailable` | Its stage was skipped, or could not run |

Status is computed from the files each time. Changing a setting makes only the artifacts that use it stale.

## Saving

| Command | Use |
| --- | --- |
| `training.py save <artifact> --built` | A first version, or a file another tool wrote in place |
| `training.py save <artifact> --from <file>` | A rebuilt version. Write it to a scratch file outside the directory first. The version it replaces is kept |
| `training.py save <artifact>` | A hand edit. It never claims a rebuild and never clears staleness |

Never use `--built` or `--from` to clear a stale flag. They say the artifact was rebuilt against its current inputs, and the rebuild then needs approval again.

**When the user has edited a file themselves:** `status` shows it as `draft` and what depends on it as `stale`. Say so. If they are still working, `training.py save <artifact>` records the edit and approves nothing. When they are done, `training.py approve <artifact>` records and approves it. Then rebuild what became stale, or ask whether to accept it.

## Copies

`settings.copies` in `status` is what the user chose: `google`, `word`, both or neither. Change it with `training.py checkpoint --copies google word`; `--copies` alone is none. Each wanted copy is `current`, `outdated`, `missing` or, for Word, `unavailable`.

- **Google Docs.** `google_docs` lists each document and brief. `training.py google push <artifact>` makes or updates one; see the google reference.
- **Word.** `exports` lists each artifact that needs a `.docx` beside its source. With Yoodli on it lists the brief and each `yoodli:<id>` whatever was chosen. Make one with `pandoc <source> -o <export>`, or the harness's own document capability. Then `training.py export <artifact>` (`--file <path>` for another name or format), or `--unavailable "<why>"`.

Redo a copy after every change to its source. Never tell the user to share or upload one that is not `current`. For a one-off Word copy while `word` is off, make it and record nothing.

## History and other rules

- Earlier versions are in `.training-studio/history/`, in a folder named for the artifact with `:` and `@` written as `-` (`scenario-main-101`), each file named by its SHA-256. `events` in `session.json` gives the order. Restore one with `training.py save <artifact> --from <that file>`.
- Never edit `session.json` or the history. The research plan is the only file under `.training-studio/` that you write.
- A refusal is `{"error": ...}` with exit code 2. Show it to the user as it is. Run one command at a time.
- The helper never commits to git. Commit only when the user asks.
