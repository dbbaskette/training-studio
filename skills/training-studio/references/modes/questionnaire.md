# Mode: questionnaire

The AI asks a fixed set of questions and the learner answers aloud or in text. Use it as a knowledge check for `recall` and `explain` objectives, and as the usual mode for general knowledge.

## Drafting the scenario

- **Mode.** `questionnaire`.
- **Situation.** One line on what this check is for.
- **Learner role.** Answer each question in their own words.
- **AI role.** A neutral examiner. No character is needed.
- **Opening.** The examiner says how many questions there are and asks the first.
- **Questions.** One or two per objective, each with the answer the brief supports. Start from the `Check:` questions in the blueprint's assessment plan and reword them, so the session does not repeat the document's knowledge check word for word. Ask open questions: one that can be answered yes or no checks nothing.
- **Success criteria.** One per objective, written as the content of a correct answer, so grading does not depend on phrasing.
- **Constraints.** The examiner does not teach, hint or confirm answers during the session. It may ask one follow-up when an answer is incomplete: "Can you say more about why?"

## In the Yoodli scenario

- The type is Questionnaire. No persona is required.
- Context tells the AI, as "you": to ask the questions one at a time, in order; not to teach or hint; to allow one follow-up per question; and to end after the last question and then give feedback against the goals. The questions go at the end of Context.
- One goal per success criterion: usually Binary for `recall` and Rated for `explain`.
