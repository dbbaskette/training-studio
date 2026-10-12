# The training desk

A page in the user's browser showing every training on this computer: what is approved, stale or blocking, and where the files are. Offer it when they want to look across trainings rather than work on one.

## Open it

1. Run `training.py desk` as a long-running background command, in whatever way your environment provides. It serves until stopped and never returns, so do not wait for it.
2. Read its first line of output, one line of JSON, and give the user its `url` exactly as printed. The part after `#` is the page's key; never shorten it.
3. Carry on with the conversation while it runs.

Add `--port <number>` only if the user asks for a port. If your environment cannot keep a command running, say so and give the user the command to run in a terminal of their own.

## What it is

- **Read-only.** The page shows status, readiness and the text of files. It changes nothing, so approvals, skips and rebuilds stay in the conversation.
- **Local.** It answers only on this computer, and only to the link it printed.
- **Not evidence.** When the user tells you what the page showed, run `training.py status` or `check` and act on that.
- **This computer's trainings.** One appears once it has been created here or had its status read here.

The page gives the user a sentence to paste to you that names a training's folder. If that is the current directory, resume as usual. If not, ask them to start you in that folder: one directory is one training.

## Stop it

Stop the background command when the user is done with the desk, and before the session ends. The page stops working when it does. Opening the desk again gives a new link.
