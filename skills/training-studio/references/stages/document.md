# Document

The document is the learner guide: the pre-read and the leave-behind. It must teach on its own, with no presenter and no deck beside it.

Follow the shape of the example document. A course is one document with a chapter per module.

## Structure

1. Title, who it is for, time needed, and what the reader will be able to do. State the objectives in plain language, without their IDs.
2. For each module:
   - an opening scenario that shows why the module matters,
   - teaching sections organised around the key points,
   - the worked example from the blueprint,
   - one "Common mistake" callout per misconception,
   - a summary,
   - a knowledge check using the `Check:` questions from the assessment plan.
3. Answer key.
4. Glossary: every term the audience may not know.
5. Sources: the original URL or document behind each finding used.

## Coverage comments

Put `<!-- covers: O1 K1.1 K1.2 -->` under the heading of each section, naming the objectives and key points that section teaches. `training.py check` requires every objective and every supported key point to be named somewhere, and fails the document if an `[unsupported]` key point is named.

This is declared coverage. It proves a section claims to teach something, not that the prose does. Before the gate, read each section against its comment and say what you found.

## Writing

- State nothing as fact beyond the cited findings. To say more, research it first.
- Cite findings with numbered references that resolve in Sources.
- Define a term the first time it appears.
- Give every concept a concrete example before or straight after the abstract statement.
- Write to the audience in intake: assume what they know, explain what they do not.
- With levels, name what an earlier level covered as assumed. Do not teach it again.
- Prefer short sections with descriptive headings over long ones.

## Gate 4

Save with `training.py save document --built` the first time and `--from <file>` after that. Run `training.py check`, fix what fails, and present the gate as the gates reference describes.

On approval:

1. `training.py approve document`.
2. Export it: `pandoc document.md -o document.docx` if `pandoc` is on the path, otherwise the harness's own document capability. Then `training.py export document`. If neither works: `training.py export document --unavailable "<why>"`. Tell the user which happened.
3. `training.py checkpoint --no-question --stage brief --next "Write the brief"`.

Export again after any later change to `document.md`. The export is a copy; the markdown is the source.
