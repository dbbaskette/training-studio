# Yoodli profile

`yoodli/<id>.md` expresses one scenario file in the fields of Yoodli's roleplay Builder. Yoodli has no import format and does not list markdown as an upload type, so the file is built for copying field by field.

Follow the shape of the example Yoodli scenario. `training.py check` reads its headings and fenced blocks.

## Fields, in Builder order

Start with `# Yoodli scenario: <name>` and `<!-- scenario: <id> -->`. Every pasteable value sits alone in its own fenced `text` block under the heading that names its field. Keep everything else, including comments and counts, outside the blocks.

| Heading | From the scenario | Limit |
| --- | --- | --- |
| `## Roleplay name` | The title | |
| `## Type` | The mode: `roleplay` is Objection Handling, `pitch` Pitch, `tutor` Tutor, `questionnaire` Questionnaire | |
| `## Description` | Situation and learner role, as the learner should see them | |
| `## Context` | AI role, opening, constraints and questions, as "you" statements | 10,000 characters |
| `## Personas`, then `### Persona 1` with `#### Name`, `Role`, `Demeanor`, `Background`, `Behaviors` | AI role. All five fields, for every persona | 3 personas |
| `## Objections` | Concerns and pushback, one per line | |
| `## Goals`, then `### Goal 1` with `#### Name`, `Type`, `Explanation`, `Achieved`, `Missed` | Success criteria | Explanation 2,500; Achieved 1,000; Missed 1,000 |
| `## AI assets` | The brief's export | |
| `## Knowledge-based goal source` | The brief's export, when used | |
| `## Settings` | Session settings | |

Goal types are Binary for something done or not done, and Rated for something done well or badly. Under each `### Goal`, outside the blocks, put `<!-- criterion: 2 -->` and, where one applies, `<!-- assesses: O3 -->`.

## Counts

Show the count and limit beside Context and each goal's Explanation, Achieved and Missed: "666 of 10,000 characters". Take every number from `counts` in the `training.py check --all` output. Never count by eye.

When a field is over its limit, shorten the wording and check again. Nothing is truncated for you.

## How the user builds it

State both paths at the top of the file.

1. **Builder, the baseline.** Create a roleplay and paste each block into the field its heading names. Create the goals as custom goals.
2. **Roleplay Agent, optional.** It takes up to 5 files and 1 public URL and drafts the name, description, context, personas, objections and rubric goals. It cannot create new custom goals: those are created in the Builder first and the agent is asked to add them. It creates new roleplays only. Have the user compare its draft with this file field by field.

Prerequisites, from Yoodli's help pages: custom goals need an organisation on an Enterprise plan; AI Assets need a content creator or admin editing an organisation roleplay; Roleplay Agent needs an owner or admin in an organisation with Conversational Roleplay enabled. If the user lacks one, say which part they cannot do.

## AI assets

Name the brief's export as the file to upload, and only if `training.py status` reports that export as `current`. Recommend strict mode, so the AI stays within the brief, and say that it uses more of the roleplay's capacity. Training Studio prepares the files; uploading them and creating the roleplay are the user's actions.

## What is provisional

Field names and limits come from Yoodli's public help pages. Each limit in `assets/profiles/yoodli.json` has its source, the date collected and the date confirmed in the live Builder, which is empty until the user confirms it. Say in the file that they are provisional while `check` warns that they are.
