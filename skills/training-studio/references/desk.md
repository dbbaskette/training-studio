# The page

A page in the user's browser: what needs them, where every training stands and, when `status` shows `approval: page`, the only place a gate is decided.

## Open it

- **Approval in chat.** Run `training.py desk` as a long-running background command; it serves until stopped. It opens the page in the user's browser itself and prints one line of JSON. If `opened` is false, give the user the command instead. Stop it when they are done, and before the session ends.
- **Approval on the page.** Never open it yourself. Give the user the command, `<helper> desk`, to run in a terminal of their own. The link it prints carries the page's key and is theirs alone.

## A gate decided on the page

The helper refuses `approve` and `skip` from you, apart from `approve intake` and `skip --unavailable`.

1. Present the gate as the gates reference says, starting what you append to the review with a `## Review` heading, and record `checkpoint --gate <artifact>`.
2. Tell the user to decide on the page. Do not ask for approval in chat, and a yes in chat is not one.
3. When they return, or on resume, read `status`:
   - the artifact is `approved`, or its stage skipped: carry on from `stage` and `next_step`;
   - `requests` names it: `revise` means make the change in its note, `rebuild` means build it again. Save with `--built` or `--from`, then present again.

Never edit `session.json` or a review to stand in for the user's decision. `training.py checkpoint --approval page` moves approval to the page; only the page moves it back.

## What the user tells you

What the page showed is not evidence: run `training.py status` or `check` and act on that. The page gives the user a sentence naming a training's folder. If that is not the current directory, ask them to start you there.
