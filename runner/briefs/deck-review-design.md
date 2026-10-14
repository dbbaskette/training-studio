## What you are given

Your task says which deck this is. `list_inputs` shows your inputs; read each with `read_input`.

- **The review** was prepared by the slides tool against the design the person approved for every slide: what each slide claims, the relationship it teaches and how it was approved to be drawn. It lists the criteria to answer, each slide with the criteria that apply to it, the objects on it you may cite with their words, and what the tool's own screens point at. It ends with the objectives of the lesson, and after the slides have been drawn again with what an earlier review found.
- `look_at_slide` shows one slide at full size, by its number. Look at every slide, in order, before you hand anything in.

## The assessment

Answer every criterion the review lists for a slide, for every slide, from what you see on it:

- `criterion`: its name.
- `status`: `pass`, `issue` or `uncertain`.
- `reason`: why, for this slide. A pass says what on this slide earns it; the same words for two slides are refused.
- `objects`: the objects on the slide your judgement rests on, by their IDs.

For each `issue` or `uncertain`, also:

- `severity`: `critical`, `major` or `minor`, as your input defines them.
- `about`: `drawing` when drawing the slide again would put it right and keep its approved visual concept and its words; `content` when only a change to what the slide says, its words or its facts, would; `concept` when the approved visual concept itself does not teach the claim and another one would. The last two are not put right by drawing: they go back to the person, who approved the words and the concept.
- `fix`: what would put it right, when you can say. It may be left out.

Judge whether each visual teaches. Ask what the learner can see that they could not read in a list of the same words. A slide that teaches a mechanism, a flow, ownership or containment shows its parts and how they connect, accurately. Boxes are not a fault in themselves, and neither is a missing icon. A slide approved as direct text, such as a question or a quotation, passes without any picture when it serves its purpose.

Where the review lists prose cards on a slide, answer `teaching-treatment` about them and cite at least one card: say what the learner cannot see, or why the cards teach it here.

Judge only what is visible in the pictures. Do not propose a change to the colours of the brand. Be exact and unsparing: a slide that is merely acceptable still gets its findings, and a deck is not good because it is on brand.

When your input lists what an earlier review found, the slides were drawn again since. Look for each of those findings. Where one is not put right, answer its criterion so again.

Name up to three weakest slides, the weakest first.

## Hand back

1. Call `submit_judgements` with every slide's answers and your weakest slides. The slides tool checks it against this exact render. If it comes back with problems, fix them and hand it back again.
2. Call `submit_coverage` with the slides for each objective, and a line on why those slides.
3. Then stop. Your last message can be one line.

Nobody can answer questions in this job. Judge, and say what you found.
