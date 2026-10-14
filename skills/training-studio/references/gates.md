# Gates

Every stage ends at a gate. Nothing downstream starts until the user approves.

## Present

1. Run `training.py check` and `training.py status`.
2. Fix any failed check that is yours to fix, and check again.
3. Review the content yourself: does the prose teach what its coverage comment claims, does each assessment ask for the behaviour its objective names, and does the research support every factual statement? Say what you found and label it as your judgment. A passing check does not answer these.
4. Show the user, briefly, and append the same to `reviews/<artifact>.md`, writing `:` and `@` as `-`:
   - the file to open,
   - what it contains, in five lines or fewer,
   - each check that failed or could not run, by name and reason, and the count that passed,
   - anything stale, and what changed upstream,
   - open gaps and limitations.
5. Offer the choices: approve, revise (they say what), rebuild, or skip the stage.
6. `training.py checkpoint --gate <artifact> --question "<the question you asked>" --next "Waiting for approval of <artifact>"`, so a resumed session asks again.

## Decide

If `status` shows `approval: page`, the user decides on the page, not here: follow the desk reference.

- **Approve.** Only on a clear yes from the user, in chat, about this artifact. Run `training.py approve <artifact>`, then `training.py checkpoint --stage <next stage> --next "<next step>"`.
- **Revise or rebuild.** Write the new version to a scratch file outside the directory, save it with `training.py save <artifact> --from <file>`, check, and present again. A file another tool writes in place is saved as its stage reference says.
- **Stale.** Say so at the gate. The user either has it rebuilt or accepts it as it is: `training.py approve <artifact> --accept-stale "<their reason>"`. The reason is recorded. Accepting one artifact approves nothing below it.
- **Skip.** `training.py skip <stage> --reason "<their reason>"`.

An approval covers the content and what it was built from. Rebuilding against changed inputs needs approval again, even if the text came out the same.

## The gates

| Gate | Approve | Show in particular |
| --- | --- | --- |
| 1 | `research-plan` | The questions as a readable list grouped by area, and the source scope. Never JSON |
| 2 | `research` | Counts of supported, contradicted, insufficient and unavailable findings; each unresolved question, meaning insufficient or unavailable; source gaps |
| 3 | `blueprint` | Lesson or course, and why; objectives; module outline; practice plan; open gaps. Offer a research top-up if a gap matters |
| 4 | `document` | Length and structure; what you found reading each section against its coverage comment |
| 5 | `brief` | Where it is weakest; what is under Unknowns |
| 6 | `deck` | Where the deck is; the reviewed coverage of objectives |
| 7 | `scenario:<id>`, for each scenario | Whose file it is; its mode and success criteria; whether the brief supports what it asks |
| 8, only if Yoodli is on | `yoodli:<id>`, for each scenario | Which goal carries each success criterion; counts against limits; whether the brief's upload copy is current |

With levels, the levels reference gives the order of the gates.
