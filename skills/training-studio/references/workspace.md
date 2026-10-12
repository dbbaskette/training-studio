# Workspace

Deliverables are visible files in the training directory. Bookkeeping is under `.training-studio/`.

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
| `yoodli:<id>` | `yoodli/<id>.md` | `blueprint`, `brief`, `scenario:<id>`, the Yoodli profile |

`deck-handoff.md` and `README.md` are derived: regenerate them, never `save` them.

## Status

| Status | Meaning |
| --- | --- |
| `not-started` | The file does not exist |
| `draft` | Not approved in its current form |
| `approved` | The content and what it was built from are what the user approved |
| `stale` | Something it was built from has changed, or is itself stale |
| `skipped`, `unavailable` | The user skipped its stage, or it could not run |

Status is computed from the files each time. A hand edit shows as `draft` on the edited file and `stale` on what was built from it. Changing a setting makes only the artifacts that use it stale.

## Saving

| Command | Use |
| --- | --- |
| `training.py save <artifact> --built` | A first version, or a file another tool wrote in place |
| `training.py save <artifact> --from <file>` | A rebuilt version. Write it to a scratch file outside the directory first. The version it replaces is kept |
| `training.py save <artifact>` | A hand edit. It never claims a rebuild and never clears staleness |

Do not use `--built` or `--from` to make a stale flag go away. They say the artifact was rebuilt against its current inputs, and the rebuild then needs approval again.

## Exports

`document`, `brief` and each `yoodli:<id>` have an export, a `.docx` beside the source. Make it with `pandoc <source> -o <export>` if `pandoc` is on the path, otherwise with the harness's own document capability.

- Made: `training.py export <artifact>`, or `--file <path>` for another name or format.
- Could not be made: `training.py export <artifact> --unavailable "<why>"`.

`status` reports each export as `current`, `outdated`, `missing` or `unavailable`. Re-export after every change to the source. Never tell the user to upload an export that is not `current`.

## History and other rules

- Earlier versions are in `.training-studio/history/<artifact>/<sha256>.<extension>`, in the order given by `events` in `session.json`. Restore one with `training.py save <artifact> --from <that file>`.
- Never edit `session.json` or anything under `.training-studio/`.
- One command at a time. A second is refused while the first holds the lock.
- A refusal is `{"error": ...}` with exit code 2. Show it to the user as it is.
- The helper never commits to git. Commit for the user only when they ask.
