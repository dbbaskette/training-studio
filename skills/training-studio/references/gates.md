# Gates

Every stage ends at a gate. Nothing downstream starts until the user approves.

## Present

1. Run `training.py check` and `training.py status`.
2. Fix any failed check that is yours to fix, and check again.
3. Review the content yourself: does the prose teach what its coverage comment claims, does each assessment ask for the behaviour its objective names, and does the research support every factual statement? Say what you found and label it as your judgment. A passing check does not answer these.
4. Show the user, briefly:
   - the file to open,
   - what it contains, in five lines or fewer,
   - each check that failed or could not run, by name and reason, and the count that passed,
   - anything stale, and what changed upstream,
   - open gaps and limitations.
5. Offer the choices: approve, revise (they say what), rebuild, or skip the stage.
6. `training.py checkpoint --question "<the question you asked>" --next "Waiting for approval of <artifact>"`, so a resumed session knows it is at this gate and asks again.

A failed check you cannot fix is shown, never hidden.

## Decide

- **Approve.** Only on a clear yes from the user, in chat, about this artifact. Run `training.py approve <artifact>`, then `training.py checkpoint --no-question --stage <next stage> --next "<next step>"`.
- **Revise.** Make the change, save it with `training.py save <artifact> --from <file>`, check, and present again.
- **Stale.** Say so at the gate. The user either has it rebuilt or accepts it as it is: `training.py approve <artifact> --accept-stale "<their reason>"`. The reason is recorded. Accepting one artifact approves nothing below it.
- **Skip.** `training.py skip <stage> --reason "<their reason>"`.

An approval covers the content and what it was built from. Rebuilding against changed inputs needs approval again, even if the text came out the same.

## The gates

| Gate | Approve | Show in particular |
| --- | --- | --- |
| 1 | `research-plan` | The questions as a readable list grouped by area, and the source scope. Never JSON |
| 2 | `research` | Counts of supported, contradicted and unresolved findings; each unresolved question; source gaps |
| 3 | `blueprint` | Lesson or course, and why; objectives; module outline; practice plan; open gaps. Offer a research top-up if a gap matters |
| 4 | `document` | Length and structure; what you found reading each section against its coverage comment |
| 5 | `brief` | Where it is weakest; what is under Unknowns |
| 6 | `deck` | Where the deck is; the reviewed coverage of objectives |
| 7 | `scenario:<id>`, for each scenario | Whose file it is; its mode and success criteria; whether the brief supports what it asks |
| 8, only if Yoodli is on | `yoodli:<id>`, for each scenario | Which goal carries each success criterion; counts against limits; whether the brief's export is current |

Exports are made after approval; say then whether each was made.

With levels, gate 3 presents every level's blueprint together and approves each separately. The later gates then repeat for one level at a time, lowest first; the levels reference has the checkpoint that moves from one level to the next.
