# The runner

The runner is a program that takes a training from a short form to its finished files on its own, and stops each time it needs your decision. You work on [the page](desk.md) in your browser. There is no conversation with an assistant: the runner starts an AI agent for each piece of work, checks what comes back, keeps it, and waits for you at each gate.

It is early. Today it makes everything except the slide deck: the research, the blueprint, the learner guide, the brief, the practice scenarios and, if you want them, their layout for Yoodli. A training that wants a deck is taken through everything else; the deck is then made in a conversation with your assistant, as the [README](../README.md) describes, or left out.

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
| Writes the learner guide | You approve it |
| Writes the brief | You approve it |
| Drafts each practice scenario the blueprint plans | You approve each one |
| Lays each scenario out for Yoodli, when you asked for that | You approve each one |
| Makes the copies you asked for and writes the index | Nothing: it says it is finished, and what is not ready |

At each stop the page shows the document, what was checked for you, and the agent's own notes on its draft, labelled as its judgment. Ask for changes in your own words and the runner makes them and brings the new version back.

With levels, every blueprint is drafted first. Then each level is finished in turn, lowest first.

**The deck.** Choose "No deck" when you start and the deck is left out. Otherwise, when everything else is approved, the run says the deck is all that is left. Make it with your assistant, or press "Leave the deck out"; the index is written once the deck is settled either way.

**A scenario of your own.** A scenario file you wrote in the training's folder is used as it is and never rewritten. It comes to you at its gate with what the format check found. Ask for changes there and your own wording is laid out under the headings; nothing is invented.

**Copies.** A Google Doc is made with the Google access this computer already has, and a Word file with `pandoc` when it is installed. A copy that cannot be made never stops the run: the run shows which, and why, and offers to try again.

You can close the page while it works. Home, and the browser if you turned notifications on, say when something needs you.

## Your own documents

The last step of "New training" asks where the research looks: the public web, your documents only, or both.

When documents are wanted, the run waits for them before anything else. Add text, Markdown, HTML or Word files, and PDFs when this computer has `pdftotext`. Each is shown with its size and whether it could be read. Press "That is all of them" and the run begins.

Your documents stay on this computer. Passages quoted from them appear in the research report, which is shared with your team. With documents only, the agents doing the research cannot search the web or open a page.

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
- Bringing edits back from a Google Doc, and publishing to a team hub, are not in the runner yet.
- A training made in a conversation is not picked up by the runner, and a training the runner drives should not also be driven from a conversation while it runs.
- `python3 runner/studio.py status` prints what is set up and where every run is, as JSON.

The design is in [the runner's specification](superpowers/specs/2026-10-13-studio-runner-design.md).
