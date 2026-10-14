# Intake

## The directory

A training needs a directory of its own. If this one is the skill's repository, a home directory or a folder of unrelated projects, say so and ask the user to launch in a directory made for the topic. `training.py init` refuses the skill's own directory and any directory above it.

## Ask once

In a single message, ask only for what the user has not already said. Offer a default for each so they can answer in a line.

| Needed | Notes |
| --- | --- |
| Topic | Required |
| Levels | None, or any of 101, 201, 301, 401. A plain training cannot gain levels later, so if they might want more, start with one |
| Brief kind | `product` for one technology or product; `competitive` for a comparison, with both sides named |
| Audience | Their role and what they already know. Never infer an audience from a product name |
| Purpose | Field enablement, technical upskilling or general knowledge |
| Source scope | Public web, supplied documents only, or both |
| Time limit or size | Optional: "30 minutes", "one lesson", "a full course" |
| Deck target | Google Slides or PowerPoint, and any brand |
| Stages | All by default. Ask only if they hinted at wanting fewer |
| Yoodli | Optional and off. Turn it on only if they ask for Yoodli scenarios |
| Copies | Optional and off. `google` keeps each approved guide and brief in a Google Doc; `word` keeps a `.docx` of each. Either, both or neither |
| Approval | In chat by default. `page` if they would rather decide each stage on a page in their browser, where only they can approve |

## Files already in the directory

List the files, ignoring dot-directories.

- **Scenario files** are `scenario.md` and anything under `scenarios/` (inside a level folder when the training has levels). They are the user's practice scenarios, not sources. Tell the user which you found.
- **Possible sources** are everything else that looks like material. Name them and ask which to use. Use only those selected. Keep each original under `sources/` with a readable text snapshot beside it, with page, slide or heading locators, as `harness-research` requires. A file that cannot be read is a named coverage gap; never guess at its contents.

## Record it

1. `training.py init --title "<title>"`, adding `--levels 101,301`, `--brief-kind competitive`, `--deck-target pptx` or `google`, `--brand "<brand>"`, `--yoodli` and `--copies google word` as they apply. If it refuses, show the user why and stop.
2. Write `intake.md` with these `##` headings and nothing else: Topic, Levels, Brief, Audience, Purpose, Source scope, Time limit. Settings such as the deck target stay out of it, so changing them later does not mark the research stale.
3. `training.py save intake --built`, then `training.py approve intake`. The user's answers are the approval for this stage, and the training moves on to `research-plan`.
4. For each stage they do not want: `training.py skip <stage> --reason "<their words>"`.
5. If they chose the page, `training.py checkpoint --approval page`, last of all: from then on only the page skips or approves.

Then read the research-plan reference. If the training has levels, read the levels reference first.
