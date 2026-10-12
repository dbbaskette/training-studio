# Training Studio

Training Studio turns a topic into training material. You give it a subject, it researches it, and it builds the material with you one stage at a time. Nothing moves forward until you approve it.

It runs inside an AI coding assistant, Claude Code or Codex, as a skill.

## What you get

For each training:

- **A research report** with sources, so every claim can be traced.
- **A blueprint**: the learning objectives and outline.
- **A learner guide**: a document people read.
- **A brief**: a short reference about the subject. It is a product brief for one technology, or a competitive brief when you are comparing two.
- **A slide deck** that works both presented and handed out.
- **Practice scenarios**: a role-play situation you can write or edit yourself. If you use [Yoodli](https://yoodli.ai), it can also prepare a version ready to build there.

You can ask for one or more **levels**, from 101 (introduction) to 401 (expert). Each level gets its own set of material.

## Before you start

You need:

- Claude Code or Codex.
- Python 3.11 or newer.
- Two companion skills: [harness-research](https://github.com/dbbaskette/harness-research-skill), which does the research, and [harness-slides](https://github.com/dbbaskette/harness-slides-skill), which builds the deck. Without harness-slides you still get everything except the deck.

## Install

Download this repository, then run the installer from inside it:

```bash
sh installer/install.sh
```

On a Mac you can double-click `Install Training Studio.command` in the `installer` folder instead.

It installs the skill for Claude Code and Codex, whichever you have, and tells you if a companion skill is missing. It asks before changing anything. See [installation](docs/installation.md) for updating, going back a version and removing it.

## Your first training

**1. Make a folder for the topic.** One folder is one training. Do not use this repository's folder.

```bash
mkdir valkey-training
```

**2. Add anything you already have.** Put source documents in the folder if you want the research to use them. If you already know the practice situation you want, write it as `scenario.md` (see [writing a scenario](#writing-your-own-scenario)). Both are optional.

**3. Start your assistant in that folder and ask for the training.** For example:

> Use training-studio to build a 101 training on Valkey for teams running Redis, with a competitive brief.

**4. Answer a few questions.** It asks about the audience, what they already know, which levels you want, whether the brief is about one product or a comparison, and which of your documents to use.

**5. Review each stage.** It stops seven times and waits for you:

| It shows you | What to look for |
| --- | --- |
| The research questions | Are these the right things to find out? |
| The research findings | What was confirmed, and what could not be |
| The blueprint | Are these the right objectives, at the right size? |
| The learner guide | Does it teach what the blueprint promises? |
| The brief | Is it honest about weaknesses as well as strengths? |
| The deck | Does it cover every objective? |
| The scenarios | Is this the conversation you want people to practise? |

At each stop you can approve it, ask for changes, or skip that stage.

**6. Find your files.** They are ordinary files in your folder: `document.md`, `product-brief.md` or `competitive-brief.md`, the deck, and `scenario.md`, with Word copies where they could be made. If you asked for Yoodli scenarios there is a `yoodli/` folder too. `README.md` in your folder lists everything and says whether the training is complete.

## Things you can say

- "Where are we?" shows the current stage and what is waiting on you.
- "Is it done?" checks the whole training and lists anything missing.
- "Redo the deck." rebuilds one stage.
- "Skip the deck." leaves a stage out.
- "Just the document." builds only the learner guide.
- "Add a scenario." adds another practice situation.
- "More research on licensing." extends the research.
- "Put the guide in a Google Doc." sends the learner guide or the brief out for review. "Pull the Google Doc." brings the edits back.
- "What trainings do I have?" lists the trainings on this computer.
- "Open the desk." shows every training in your browser.

## Coming back later

Start your assistant in the same folder and ask for the training again. It picks up where it stopped.

You can edit any file yourself. The next time you ask, Training Studio notices the change, marks anything built from that file as out of date, and asks whether to rebuild it or keep it.

## Levels

Ask for the levels you want when you start, for example "101 and 301".

| Level | Covers |
| --- | --- |
| 101 | What it is and why it matters |
| 201 | How it works and common tasks |
| 301 | Architecture, tuning and troubleshooting |
| 401 | Internals and design at scale |

Research is done once and shared. Each level then gets its own folder, such as `101/` and `301/`, with its own blueprint, guide, brief, deck and scenarios. You can add a level later.

## Writing your own scenario

A scenario is a short file that describes a practice conversation: the situation, who the learner is, who the AI plays, how it opens, and what success looks like. Write it in plain language. This is a complete one:

```markdown
# Scenario: IT executive weighing Redis alternatives

## Situation
You are an IT executive with Redis applications in production. You want lower costs without risking reliability.

## Learner role
You are advising the executive on how to evaluate Valkey.

## AI role
Play the executive: cost-conscious, open to alternatives, sceptical of claims that ignore migration effort.

## Opening
"We have Redis in production. Where would you start?"

## Success criteria
- Asks about the current deployment before recommending anything.
- Separates what is known from what is assumed.
- Proposes a measured evaluation and a next step.
```

Save it as `scenario.md` in your training folder, or put several under `scenarios/`. Training Studio uses your file as written and never overwrites it. If you do not write one, it drafts one for you to edit.

## Using the scenarios in Yoodli

This part is optional. A scenario file already works with any AI that can play a role. If you use Yoodli, say "also make Yoodli scenarios" when you start, or "add Yoodli" at any time.

For each scenario, Training Studio then writes a file under `yoodli/` laid out in the same order as Yoodli's roleplay builder, so you can copy each part into its field. It also tells you which file to upload as the AI's reference material. You build the roleplay in Yoodli yourself; Training Studio does not upload anything. See [scenarios and Yoodli](docs/scenarios-and-yoodli.md).

## If something goes wrong

| What you see | What it means |
| --- | --- |
| It stops at research and names harness-research | That skill is not installed. Install it and ask again |
| The deck is "unavailable" | harness-slides is not installed. Everything else still works |
| A Word copy is "unavailable" | No converter was found. Installing [pandoc](https://pandoc.org) fixes it |
| Something is "stale" | A file it was built from has changed. Ask to rebuild it, or say it is fine as it is |
| It refuses to start in a folder | The folder already holds files with the names it uses, or it is this repository. Use a new folder |

## Status

This is the first of five planned phases. The helper that tracks your files is tested. A full run with a live assistant and a build in Yoodli have not been done yet, so expect rough edges and please report them.

## Learn more

- [Installation](docs/installation.md): what the installer does, and how to update, roll back or remove.
- [How it works](docs/how-it-works.md): the stages, approvals, what "stale" means, and the files in a training folder.
- [Scenarios and Yoodli](docs/scenarios-and-yoodli.md): the scenario format, and building a roleplay in Yoodli.
- [Google Docs](docs/google-docs.md): sending the learner guide or the brief to a Google Doc for review, and bringing the edits back.
- [The training desk](docs/desk.md): a page in your browser showing every training on this computer.
- [Development](docs/development.md): the repository, tests, and how to change the skill.
- [Design](docs/superpowers/specs/2026-10-12-training-studio-core-pipeline-design.md): the full specification.

## Licence

[MIT](LICENSE).
