## The design

Your task asks for the design as well: how each slide teaches its claim. The person approves the words and the design together, in one decision, and the slides are drawn from both. Where a slide explains a mechanism, an architecture, a flow or a boundary, show it: the learner should see the parts and how they connect, not read a list about them. Direct text is right for a question, a quotation or a knowledge check. Choosing it is a decision with a reason, not something left out. The design guidance among your inputs is the slides tool's own advice on designing a slide: read it.

Hand the design in beside the outline, as `design` to `check_outline` and `submit_outline`. It is one JSON object with `slides`: one entry for every slide of the outline, the cover, section and closing slides too, in the outline's order. Each entry holds only these:

- `id`: the slide's ID in the outline.
- `intent`: `takeaway`, the claim the slide makes; `audienceQuestion`, the question it answers for the audience; `relationship`, what it shows, such as containment, a cycle, a sequence, a comparison or an assessment; `rationale`, why this treatment teaches the claim; `alternative`, the treatment you weighed and why you did not choose it, as `treatment` and `reason`; and `visual`, its `family` and its teaching `purpose`. The family is one of text, icon, diagram, regions, table, chart, sourced-image, generated-art or quote.
- `composition`: how the slide is drawn, concretely enough for someone else to draw it: what is placed where, what is joined to what, and where the eye lands first.
- `asset`: what the slide needs beyond its words. `description` names it, `disposition` is selected, not-needed or unavailable, and `reason` says why. List concrete candidates under `candidates`, each with `assetId`, `kind` (icon, supplied, generated, screenshot or chart), `ref` (an icon's name, or what the picture shows), `concept` (what it stands for on this slide) and `status`: resolved, or pending until someone finds or makes it.
- `qualifications`, when the slide has wording it must keep, such as the limit a caveat states. Each must appear in the slide's visible copy.

The title, the visible copy, the notes and the objectives come from the outline: leave them out of the design. The visible copy is a slide's points, its focal statement, its caveat and its source line. What the slide should leave the audience understanding is a requirement, not copy: it stays in `understand`. Where a diagram carries the meaning, shorten the copy and move the explanation into the notes, keeping every qualification the sources give.

A family that needs an asset (icon, sourced-image or generated-art) needs its asset selected. When it cannot be, the check says so and offers a native diagram instead: propose that, or another treatment that does not depend on the asset.

The check sends the design to the slides tool, which says slide by slide what it will not take. Nothing is kept by checking. In your notes, say which slides are drawn as text and why, and any asset that is still pending.
