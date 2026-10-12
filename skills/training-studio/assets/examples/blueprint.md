# Blueprint: Rolling restarts

Illustrative example of the required shape. Its content is not researched.

## Frame
Audience: solutions engineers who deploy apps but have not had to explain restart behaviour to a customer.
Purpose: field enablement
Time: 25 min

## Sizing
Lesson. The research supports three objectives that fit in 25 minutes. Rollback behaviour was cut: its research question is still pending.

## Objectives
### O1 — Describe what a rolling restart does [recall]
### O2 — Explain when a rolling restart keeps capacity [explain]
### O3 — Handle the objection that rolling restarts guarantee zero downtime [handle]

## M1 — Rolling restarts (25 min)
Objectives: O1, O2, O3
- K1.1: A rolling restart replaces instances one batch at a time. [R:availability]
- K1.2: Capacity holds only when more than one instance is running. [R:availability] [R:instance-min]
- K1.3: Health checks decide when the next batch starts. [R:health-checks]
- K1.4: Rolling restarts give zero downtime for every app type. [unsupported]
Misconception: "Rolling always means zero downtime." Correction: a single-instance app still drops requests while it restarts. [R:zero-downtime]
Example: A three-instance web app restarted one instance at a time while it serves traffic.

## Assessment plan
- O1: Check: What happens to an app's instances during a rolling restart? | Observe: States that instances are replaced in batches.
- O2: Check: Why does a single-instance app lose capacity during a rolling restart? | Observe: Explains the more-than-one-instance condition.
- O3: Check: A customer says rolling restarts guarantee zero downtime. What do you say? | Observe: Corrects the claim without dismissing the customer and agrees a next step.

## Practice plan
- main: roleplay. Objectives: O1, O2, O3. A sceptical platform lead who saw dropped requests last week and was told that could not happen.

## Open gaps
- K1.4: no evidence was found for the zero-downtime claim, so the training does not teach it.
- Rollback after a failed restart is not covered; the research question is still pending.
