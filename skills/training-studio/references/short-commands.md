# Short commands

| The user says | Do |
| --- | --- |
| "status", "where are we" | `training.py status`, then summarise in four lines |
| "check", "is it done" | `training.py check`, then report `blocking`, `limitations` and each check listed |
| "redo the deck" (or any stage) | Read that stage's reference, rebuild, present its gate |
| "skip the deck" | `training.py skip deck --reason "<their reason>"` |
| "bring back the deck" | `training.py skip deck --clear` |
| "just the document" | Skip scenario, brief and deck, and continue |
| "add Yoodli", "make it work in Yoodli" | `training.py skip yoodli --clear`, then read the Yoodli stage reference |
| "no Yoodli" | `training.py skip yoodli --reason "<their reason>"` |
| "use Google Slides", "use PowerPoint" | `training.py checkpoint --deck-target google`, or `pptx` |
| "make it a competitive brief" | `training.py checkpoint --brief-kind competitive`, then rebuild the brief |
| "add level 301" | `training.py checkpoint --levels 101,301`, then read the levels reference |
| "add a scenario" | Read the scenario stage reference |
| "more research on X" | The top-up in the research-handoff reference |
| "what changed", "restore the earlier one" | History, in the workspace reference |
| "what trainings do I have" | `training.py list` |

Rules that go with them:

- Yoodli is optional and off unless asked for. While it is on, the brief and the scenarios cannot be skipped: turn Yoodli off first.
- A stage is skipped for every level or for none.
- When `stage` is `done`, run `training.py check --complete` before saying anything about completeness. The marker does not prove the training is still complete.
- A refusal from the helper is shown to the user as it is.
