# Mode: tutor

The AI teaches the material in conversation and checks understanding as it goes. Use it for `explain` and `apply` objectives, and as the usual mode for technical upskilling.

## Drafting the scenario

- **Mode.** `tutor`.
- **Situation.** What the learner is about to do that makes this material matter.
- **Learner role.** What they should be able to do by the end.
- **AI role.** A patient tutor who knows the brief. No character is needed.
- **Opening.** The tutor's first question, which finds out what the learner already knows.
- **Questions.** For each key point, one question that checks understanding and not recall. "Why does a single-instance app lose capacity?" checks understanding. "What is a rolling restart?" checks recall. For each `apply` objective, one new case the learner has not seen in the document.
- **Success criteria.** For `explain`: gives the reason in their own words. For `apply`: reaches a sound answer on the new case and can say why. Repeating the tutor's words back meets neither.
- **Constraints.** The tutor stays inside the brief and says so when asked about something outside it.

A conversation can show that a learner explains a procedure and reasons about a case. It cannot show they can carry the procedure out. Write the criteria for what the conversation can actually observe.

## In the Yoodli scenario

- The type is Tutor. No persona is required.
- Context tells the AI, as "you": to teach the key points in order, one at a time; for each to explain briefly, give the example, then ask before moving on; when an answer is wrong, to ask a narrower question first and explain only if the learner stays stuck; to watch for the listed misconceptions; and to close with the new case. The questions go at the end of Context.
- One goal per success criterion.
