# Scenarios and Yoodli

## The scenario file

A scenario describes one practice conversation. It is a file you own: Training Studio reads it, never overwrites it, and proposes changes for you to accept or refuse.

| Section | Required | What goes in it |
| --- | --- | --- |
| `# Scenario: <name>` | yes | A title |
| `## Mode` | no | `roleplay` (the default), `pitch`, `tutor` or `questionnaire` |
| `## Situation` | yes | The made-up circumstances |
| `## Learner role` | yes | Who the learner is and what they are trying to do |
| `## AI role` | yes | Who the AI plays and how it behaves |
| `## Opening` | yes | The AI's first line |
| `## Concerns and pushback` | no | What the AI raises |
| `## Questions` | no | Questions to ask, for the modes that use them |
| `## Success criteria` | yes | A list, one thing the learner should do per item |
| `## Constraints` | no | What the AI must not invent |
| `## Session settings` | no | How long, and how it ends |

See the [example scenario](../skills/training-studio/assets/examples/scenario.md).

The situation is fiction about the practice setting. Facts about the product come only from the brief, so the AI cannot be asked to defend something the research did not support.

### Where the file goes

- `scenario.md` in the training folder is the main scenario.
- Any file under `scenarios/` is another one. Name it in lowercase with hyphens, such as `scenarios/exec-cost.md`.
- With levels, the same names go inside the level's folder: `301/scenario.md`.

Other markdown files are never picked up as scenarios. Editing a scenario makes only its own Yoodli scenario out of date.

### The four modes

| Mode | The AI | Use it to practise |
| --- | --- | --- |
| roleplay | Plays a customer or colleague | A live conversation, such as answering an objection |
| pitch | Listens, then asks questions | Presenting, and handling questions afterwards |
| tutor | Teaches and checks understanding | Explaining and applying the material |
| questionnaire | Asks a fixed set of questions | A knowledge check |

## The Yoodli scenario

For each scenario, Training Studio writes `yoodli/<name>.md`. It lays your scenario out in the order of Yoodli's roleplay Builder: roleplay name, type, description, context, personas, objections, goals, AI assets and settings. Each value sits in its own block so it copies cleanly, with a character count beside the fields that have a limit.

Each goal carries one or more of your success criteria. Every criterion has a goal.

See the [example Yoodli scenario](../skills/training-studio/assets/examples/yoodli.md).

### Building it in Yoodli

**The Builder is the baseline.** Create a roleplay, paste each block into the field its heading names, and create the goals as custom goals.

**Roleplay Agent is optional.** You can give Yoodli's agent the Yoodli file and the brief and let it draft the roleplay. It cannot create new custom goals, so create those in the Builder first and ask the agent to add them. Compare its draft with the file.

**The reference file.** Upload the brief's Word copy as an AI asset. Turning on strict mode keeps the AI within the brief, and uses more of the roleplay's capacity.

Training Studio prepares these files on your computer. It does not create, upload or enable anything in Yoodli.

### What your Yoodli account needs

According to Yoodli's help pages as of October 2026:

| To do this | You need |
| --- | --- |
| Create custom goals | An organisation on an Enterprise plan |
| Add AI assets | To be a content creator or admin, editing an organisation roleplay |
| Use Roleplay Agent | To be an owner or admin in an organisation with Conversational Roleplay enabled |

### Limits are provisional

The field names and character limits come from Yoodli's public help pages. They have not been confirmed in the live Builder, and Training Studio says so until someone does. If a field name or limit differs when you paste, the fix belongs in `skills/training-studio/assets/profiles/yoodli.json`, where each limit is recorded with its source and date.

A successful paste shows that Yoodli accepted the fields. It does not show that the scenario is well grounded or that the goals grade well. That judgment is yours.

## Other tools

The scenario file and the brief are not tied to Yoodli. The scenario file reads as a set of instructions for any AI that can play a role, and the brief works as its reference document.
