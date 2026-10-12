# Research plan

Draft the questions `harness-research` will answer, and have the user approve them, before any research runs. A run aimed at the wrong questions is the most expensive mistake in the pipeline.

## Draft

Write `.training-studio/research-plan.json` in the format `harness-research` accepts. It is the one file under `.training-studio/` that you write.

```json
{
  "topic": "<the topic from intake>",
  "purpose": "planning",
  "scope": "public-web",
  "sources": [],
  "items": [
    {
      "id": "instance-min",
      "question": "How many instances does an app need to keep capacity during a rolling restart?",
      "public_query": "rolling restart minimum instances capacity",
      "claim": null
    }
  ]
}
```

- **`purpose`** is always `planning`. It is a `harness-research` field, not the training's purpose.
- **`scope`** is `supplied-only` when intake allows supplied documents only, and `public-web` otherwise.
- **`sources`** has one entry per selected document, as `harness-research` defines them, with paths relative to the training directory.
- **`items`** holds 1 to 30 questions. Each `id` is lowercase letters, digits and hyphens. The blueprint and the brief cite these IDs, so name each for its subject: `instance-min`, not `q7`.
- **`public_query`** uses non-confidential public terms only, and is `null` for supplied-only research.
- **Leave out `input_files`.** If `intake.md` were registered there, `harness-research` would discard its findings whenever intake was edited.

## What to ask

A general research run collects facts. A training needs more.

1. **Facts.** What is true, with versions and dates where they matter.
2. **Misconceptions.** What do people commonly get wrong?
3. **Prerequisites.** What must this audience already understand, and where are the gaps likely?
4. **Objections.** What pushback and hard questions does the topic attract?
5. **Examples.** Which concrete cases, numbers or scenarios illustrate it?
6. **Comparison**, for a competitive brief only. Which dimensions matter to a buyer? How does each side do on each? Licensing and cost. Migration effort. Where is the alternative stronger? Ask for the date and version of every answer: comparison facts go out of date fast.

Weight the mix to the purpose: more objections for field enablement, more prerequisites and examples for technical upskilling. With levels, one plan serves them all; weight it toward the deepest level. Ask one thing per question, and prefer questions a source can answer with a passage.

Ask neutral questions. One that embeds a claim, such as "Do rolling restarts guarantee zero downtime?", can come back `contradicted`, and a contradicted finding can back only a correction or a response to an objection. Where the truth is something to teach, also ask the neutral question that establishes it: "What happens to a single-instance app during a rolling restart?"

If the topic needs more than 30 questions, it is too large for one training. Say so and propose a split, each part in its own directory.

## Gate 1

`training.py save research-plan --built`, then present the gate as the gates reference describes: the questions as a readable list grouped by the areas above, with the source scope.

On approval: `training.py approve research-plan`, then `training.py checkpoint --no-question --stage research --next "Run the research"`, then read the research-handoff reference.
