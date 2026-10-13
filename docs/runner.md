# The runner

The runner is a program that takes a training from a short form to an approved blueprint on its own, and stops each time it needs your decision. You work on [the page](desk.md) in your browser. There is no conversation with an assistant: the runner starts an AI agent for each piece of work, checks what comes back, keeps it, and waits for you at each gate.

It is early. Today it runs a training as far as the blueprint. The learner guide, the brief, the deck and the practice scenarios are still made in a conversation with your assistant, as the [README](../README.md) describes.

## What you need

- A copy of this repository, and Python 3.11 or newer.
- Claude Code or Codex, installed and signed in as you. The runner uses your own sign-in. It has no key of its own.
- [harness-research](https://github.com/dbbaskette/harness-research-skill), installed. The research cannot run without it.
- git, set up with your name and email.

## Start it

Run this in a terminal of your own, from your copy of the repository:

```bash
python3 runner/studio.py serve
```

It prints one line with a link. Open the link exactly as it is printed: the part after `#` is a key, and the page does not work without it. The runner works for as long as this command runs. Press Ctrl-C to end it. Nothing is lost: start it again and every training carries on from where its files say it is.

One runner serves on a computer at a time.

## Set it up

The first time, the page opens on set-up. It asks three things.

- **Where your trainings are kept.** Give the address of a repository your team shares, or a folder on this computer for trying things out. The runner keeps a copy of the repository for itself and writes inside one folder of it, `trainings` unless you choose another, and nowhere else. Other tools can keep their own folders in the same repository. Each answer is checked as you give it: that the repository can be reached and written to, that git knows who you are, and that the folder can be used.
- **When your team sees the work.** After each decision, or only when you press "Share now". Sharing never forces: if someone else changed the same file, the page says so and your work stays on your computer until it is sorted out.
- **The agent and the limits.** Which agent drafts by default, the longest one step may take, the most one training may spend, and how many trainings may work at once.

Nothing is changed until you save. You can change any of it later in Settings.

## Start a training

"New training" asks for a title, what it should teach, who it is for, and a few choices that already have answers. Then it starts at once.

| The runner does this on its own | Then it stops for you |
| --- | --- |
| Drafts the research questions | You approve them, or ask for changes |
| Researches each question, several at a time, and writes the report | You approve the research, or ask for more |
| Drafts the blueprint, one for each level | You approve each blueprint |

At each stop the page shows the document, what was checked for you, and the agent's own notes on its draft, labelled as its judgment. Ask for changes in your own words and the runner makes them and brings the new version back.

You can close the page while it works. Home, and the browser if you turned notifications on, say when something needs you.

## Watching a run

A training's run shows every step, how long each took and what it cost, and what each agent at work is doing now. From there you can:

- **Pause.** The step in hand finishes; nothing new starts until you resume.
- **Stop.** The agents at work are ended. Everything already kept stays. Resume carries on from there.
- **Try again**, when a step failed. A step is tried up to three times, with the reason for the last failure given to the next try. Then the training stops and says what went wrong and what was kept.
- **Answer a question.** An agent that needs something only you know can ask. The run waits for your answer.

A training that has spent what it may stops and asks before it spends more. Claude Code says what each step cost. Codex reports tokens and not dollars, so the money limit cannot stop it: the page says so, and the limit on time still applies.

## What the runner guarantees

- **Only you approve.** A training the runner drives is decided on the page, and nowhere else. The runner has no way to approve a draft, and neither has an agent.
- **An agent cannot touch your files.** Each agent works in an empty folder outside your trainings, with no shell and no file tools. It can read what the runner gives it, search the web when the job is research, and hand back a draft or a finding. The runner checks what is handed back before anything is kept.
- **Quotes are real.** The runner fetches each source itself and keeps a copy. A finding is kept only when every quote in it is found, word for word, in the saved page.
- **Everything is recorded.** Each step, decision and request is a commit in the workspace, saying what happened. The pages a finding quotes stay on your computer; they are not shared.

## Good to know

- An agent the runner starts is still your own Claude Code or Codex. It knows what that agent normally knows about your account, such as the address you are signed in with, and Codex also reads your own instructions file and the names of your skills. None of that gives it a way to reach your files.
- A research question that fails three times does not stop the training. It is named as not researched when the research comes to you, and you decide whether that matters.
- Research uses the public web. Documents of your own are not offered in the runner yet.
- A training made in a conversation is not picked up by the runner, and a training the runner drives should not also be driven from a conversation while it runs.
- `python3 runner/studio.py status` prints what is set up and where every run is, as JSON.

The design is in [the runner's specification](superpowers/specs/2026-10-13-studio-runner-design.md).
