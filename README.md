# Training Studio

A skill that turns a topic into researched training material. You approve each stage before the next one starts.

For a topic it produces:

- a cited **research report**,
- a teaching **blueprint**,
- a **learner guide** to read,
- a **brief**: a product brief for one technology, or a competitive brief for a comparison,
- a **slide deck** that can be presented or handed out,
- **practice scenarios** you can write or edit, and a Yoodli scenario built from each.

A training can be built at one or more levels: 101, 201, 301 and 401. Research is done once; everything else is produced per level.

This is phase 1 of five. See the [design](docs/superpowers/specs/2026-10-12-training-studio-core-pipeline-design.md) and the [plan](docs/superpowers/plans/2026-10-12-training-studio-core-pipeline.md).

## Requirements

- Python 3.11 or newer.
- The [harness-research](https://github.com/dbbaskette/harness-research-skill) skill, which needs Node 20 or newer.
- The [harness-slides](https://github.com/dbbaskette/harness-slides-skill) skill, for decks. Without it the deck is reported as unavailable and the rest still runs.
- Optional: `pandoc`, for `.docx` exports. Without it the harness's own document capability is used, or the export is reported as unavailable.

## Install

From this repository, link the skill into the skill root of the harness you use.

Claude Code:

```bash
ln -s "$(pwd)/skills/training-studio" ~/.claude/skills/training-studio
```

Codex:

```bash
ln -s "$(pwd)/skills/training-studio" ~/.agents/skills/training-studio
```

## Use

One directory is one training. Make a directory for the topic, put any source documents and scenario files in it, and launch your harness there:

```bash
mkdir valkey-training
```

Then ask for the training, for example: "Use training-studio to build a 101 and 301 training on Valkey for teams running Redis, with a competitive brief." Intake asks about the levels, the audience, the purpose and which documents to use.

To resume, launch the harness in the same directory and ask again. It picks up at the stage where it stopped.

### Scenarios

A practice scenario is a markdown file you own: `scenario.md`, or any file under `scenarios/`. Write one before you start, or edit the one the skill drafts. The skill never overwrites it. See the [example](skills/training-studio/assets/examples/scenario.md).

## What a training directory holds

```
valkey-training/
  README.md                  index and readiness report
  intake.md                  intake answers
  research-report.md         the approved research report
  101/
    blueprint.md             objectives, modules, assessment and practice plans
    document.md, .docx       the learner guide
    competitive-brief.md, .docx
    deck.pptx                or deck-link.md for Google Slides
    scenario.md, scenarios/  your practice scenarios
    yoodli/                  a Yoodli scenario for each
  301/                       the same set
  sources/                   the documents you selected
  .training-studio/          session record and history
```

A training with no levels has the same files at the top instead of in level folders.

## Develop

```bash
python3 -m unittest discover -s tests -v
```

```bash
python3 skills/training-studio/scripts/validate_package.py
```

Guidance is loaded progressively and kept within measured budgets; see [progressive disclosure](docs/progressive-disclosure.md). Training content never lives in this repository; see [AGENTS.md](AGENTS.md).
