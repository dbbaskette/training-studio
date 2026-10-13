# Brief

The brief is the reference document about the subject. People consult it; they do not study it. It is also the knowledge file given to an AI for practice, so what it says must be right and no more than the research supports.

The brief kind is in `settings.brief_kind`. Follow the shape of the matching example brief. `training.py check` reads the title, the numbered headings and the findings comments.

## Sections, in this order

| # | Product brief (`product-brief.md`) | Competitive brief (`competitive-brief.md`) |
| --- | --- | --- |
| 1 | Executive summary | Executive summary |
| 2 | What it is and where it fits | Comparison |
| 3 | Capabilities | Differentiators |
| 4 | Limitations | Limitations |
| 5 | Qualification questions | Qualification questions |
| 6 | Objections and responses | Objections and responses |
| 7 | Unknowns | Unknowns |
| 8 | Sources | Sources |

The title is `# Product brief: <subject>` or `# Competitive brief: <ours> versus <theirs>`. Headings are numbered: `## 2. Comparison`.

## Evidence

Sections 2 to 6 are evidence sections. Under each heading put `<!-- findings: licensing migration-effort -->`, naming every finding the section rests on. Each must exist and be `supported`. Section 6 may also name a `contradicted` finding, because an objection often rests on a claim the research contradicted.

In the visible text, cite with numbered references that resolve in Sources. Give every source its date. A competitive brief also gives an "as of" date on each row of its comparison.

## What makes a brief worth having

- **State weaknesses as plainly as strengths.** Limitations says where the subject falls short and, in a competitive brief, where the alternative is stronger. A brief that only flatters one side fails the person using it in front of a customer.
- **Comparison is a table.** One row per dimension that matters to a buyer, a column for each side, and the evidence.
- **Differentiators are only what the research supports.** A difference you cannot cite goes under Unknowns.
- **Qualification questions cut both ways.** Include the ones whose answer means this is the wrong choice.
- **Each objection is in the words of whoever would raise it**, with a response that rests on evidence. Never include an objection the brief cannot answer from its own sections.
- **Unknowns is never empty.** List what the research could not establish, including the blueprint's open gaps that concern the subject. If nothing was left unresolved, say that.
- **Write to the level.** With levels, a 101 brief is short and plain; a 401 brief goes to internals and trade-offs.

Keep it to what someone can scan before a meeting. Detail that teaches belongs in the document.

## Gate 5

Save with `training.py save brief --built` the first time and `--from <file>` after that. Run `training.py check`, fix what fails, and present the gate as the gates reference describes. Say where the brief is weakest.

On approval:

1. `training.py approve brief`.
2. Make the copies `training.py status` asks for, as the workspace reference describes: a push if `google_docs` lists `brief`, a Word copy and `training.py export brief` if `exports` does. With Yoodli on, the brief's copy is the file the user uploads: its Google Doc when `google` is kept, otherwise a Word copy, which `exports` then lists whatever was chosen. Without one the Yoodli handoff is incomplete. Tell the user. If a Google Doc cannot be made, ask whether to drop `google`.
3. `training.py checkpoint --no-question --stage deck --next "Hand the deck to harness-slides"`.
