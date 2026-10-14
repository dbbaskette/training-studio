# The runner

The runner is a program that takes a training from a short form to its finished files on its own, and stops each time it needs your decision. You work on [the page](desk.md) in your browser. There is no conversation with an assistant: the runner starts an AI agent for each piece of work, checks what comes back, keeps it, and waits for you at each gate.

It is early. It makes the research, the blueprint, the learner guide, the brief, the slide deck, the practice scenarios and, if you want them, their layout for Yoodli. A deck needs more on your computer than the rest does. Where that is missing, the training is taken through everything else and the page says what the deck still needs.

## What you need

The [installer](installation.md) brings the runner, offers the two companion skills, and says which of these this computer still lacks.

- Python 3.11 or newer.
- Claude Code or Codex, installed and signed in as you. The runner uses your own sign-in. It has no key of its own.
- [harness-research](https://github.com/dbbaskette/harness-research-skill), installed. The research cannot run without it. The installer offers it.
- git, set up with your name and email. For a repository your team shares, git must reach it without asking for anything. The runner never waits for a password, a passphrase or a question about a host key. If `git clone` works for its address in a terminal without asking, the runner can use it.

A slide deck needs four more things. The Status screen shows each one, and what to do about one that is missing.

- [harness-slides](https://github.com/dbbaskette/harness-slides-skill), version 0.13.1 or newer. It draws and renders the slides. The installer offers it.
- A brand skill: a skill that holds your organisation's brands, its slide template and its icons. A deck is always made in a brand. Without a brand skill no deck is offered. It is your organisation's own, so the installer does not bring it.
- A way to turn slides into pictures, so that they can be looked at before they come to you: LibreOffice on this computer, or Google access that reaches Drive.
- Poppler, the small programs (`pdftoppm` and `pdfinfo`) that turn a render into pictures.

## Start it

On a Mac, double-click "Open Training Studio" in the Applications folder inside your home folder. A terminal window of your own opens and the page opens in your browser.

On any system, run the line the installer printed. With the usual locations it is:

```bash
sh ~/.local/share/training-studio/studio
```

From a copy of the repository, without installing, it is `python3 runner/studio.py serve --open`.

The window prints one line with a link, and opens it for you. The part of the link after `#` is a key, and the page does not work without it. If you open the page yourself, use the link exactly as it is printed. The runner works for as long as that window is open. Press Ctrl-C in it, or close it, to end. Nothing is lost: start it again and every training carries on from where its files say it is.

One runner serves on a computer at a time. The installer will not update, go back a version or remove while it is open: close it first.

## Set it up

The first time, the page opens on set-up. It asks three things.

- **Where your trainings are kept.** Give the address of a repository your team shares, or a folder on this computer for trying things out. The runner keeps a copy of the repository for itself and writes inside one folder of it, `trainings` unless you choose another, and nowhere else. Other tools can keep their own folders in the same repository. Each answer is checked as you give it: that the repository can be reached and written to, that git knows who you are, and that the folder can be used.
- **When your team sees the work.** After each decision, or only when you press "Share now". Sharing never forces: if someone else changed the same file, the page says so and your work stays on your computer until it is sorted out.
- **The agent and the limits.** Which agent drafts by default, which of its models and how hard it reasons, the longest one step may take, the most one training may spend, and how many trainings may work at once.
  - The models are the agent's own. Codex lists them itself; the list is asked for when the choice is shown and kept for an hour. Claude Code has no list, so its four names are offered: Fable, Opus, Sonnet and Haiku, each meaning the latest of its kind. "The agent's own choice" leaves the model to the agent, and "Another model…" takes a name the list does not have. If the list cannot be had, the page says so, and a name can still be typed.
  - The reasoning level is how much the agent thinks before it answers: more is slower, and costs more. Only the levels the chosen model takes are offered, and choosing another agent or model lets go of a level it does not take. "The agent's own choice" leaves that to the agent too.
  - The last step of "New training" asks the same, starting from these. A training keeps what it started with, and every step of it uses that.

Where this computer can make a deck, set-up asks two more things.

- **How slide previews are made.** With LibreOffice, the pictures are made on this computer and nothing leaves it. Through Google Drive, each deck keeps one presentation named "Preview: …" in your Drive, written again at each render. Where LibreOffice is there and you have not chosen, it is used: nothing is sent to Drive unless you choose it. Once you have chosen LibreOffice, Drive is not asked about at all.
- **Which brand skill to use,** when more than one was found.

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
| Writes what each slide of the deck says | You approve the words, or say what should change |
| Draws the slides in the brand, looks at them, has them reviewed and puts right what the review finds | You approve the deck |
| Drafts each practice scenario the blueprint plans | You approve each one |
| Lays each scenario out for Yoodli, when you asked for that | You approve each one |
| Makes the copies you asked for and writes the index | Nothing: it says it is finished, and what is not ready |

At each stop the page shows the document, what was checked for you, and the agent's own notes on its draft, labelled as its judgment. Ask for changes in your own words and the runner makes them and brings the new version back.

With levels, every blueprint is drafted first. Then each level is finished in turn, lowest first.

**The deck.** Choose "No deck" when you start and the deck is left out. Otherwise you choose its brand and the brand's variant from what your brand skill offers, and whether it is a PowerPoint file or Google Slides. The deck is made for each level after its brief, and you decide twice.

- **What the deck says.** Every slide's title, points, caveat and notes, before any slide is drawn. Words are quick to change here and slow to change later. The run says what a deck of this size has cost before.
- **The deck itself.** Every slide as a picture, with what the review still finds, the result of the brand's own check, and which slides cover each objective. The file you approve is the one whose pictures you are shown.

Between the two, the slides are drawn in sections, side by side, by agents that look at a preview of what they draw. A different agent then reviews every slide. Sections with something badly wrong in how they are drawn are drawn again, at most twice. After that the deck comes to you as it is, with what remains listed, the gravest first. A finding about what a slide says is never fixed for you: it is listed, and "Ask for changes" takes you back to the words.

On a computer that cannot make a deck, everything else is made and the run says what is missing. Put it right and check this computer again on the Status screen, make the deck with your assistant, or press "Leave the deck out". The index is written once the deck is settled.

**What is left in Google Drive.** When previews are made through Drive, each deck leaves one preview presentation there. The runner never deletes anything in your Drive. Settings lists each one with its address, so that you can. A deck you asked for as Google Slides is one more file in your Drive, and its address is kept in the training.

**A scenario of your own.** A scenario file you wrote in the training's folder is used as it is and never rewritten. It comes to you at its gate with what the format check found. Ask for changes there and your own wording is laid out under the headings; nothing is invented.

**Copies.** A Google Doc is made with the Google access this computer already has, and a Word file with `pandoc` when it is installed. A copy that cannot be made never stops the run: the run shows which, and why, and offers to try again.

You can close the page while it works. Home, and the browser if you turned notifications on, say when something needs you. With the page closed altogether, this computer can tell you itself: see [When the page is closed](#when-the-page-is-closed).

## Your own documents

The last step of "New training" asks where the research looks: the public web, your documents only, or both.

When documents are wanted, the run waits for them before anything else. Add text, Markdown, HTML or Word files, and PDFs when this computer has `pdftotext`. Each is shown with its size and whether it could be read. Press "That is all of them" and the run begins.

Your documents stay on this computer. Passages quoted from them appear in the research report, which is shared with your team. With documents only, the agents doing the research cannot search the web or open a page.

## Watching a run

A training's run shows every step, how long each took and what it cost, and what each agent at work is doing now. From there you can:

- **Pause.** The step in hand finishes; nothing new starts until you resume.
- **Stop.** The agents at work are ended, and so is anything a step is running, such as a slide preview. Nothing they started is left running. Everything already kept stays. Resume carries on from there.
- **Try again**, when a step failed. A step is tried up to three times, with the reason for the last failure given to the next try. Then the training stops and says what went wrong and what was kept.
- **Answer a question.** An agent that needs something only you know can ask. The run waits for your answer.

A training that has spent what it may stops and asks before it spends more. Claude Code says what each step cost. Codex reports tokens and not dollars, so the money limit cannot stop it: the page says so, and the limit on time still applies.

## With a team

When your trainings are kept in a repository your team shares, several people can work in the same workspace. One rule keeps them from treading on each other: **each training is run from one computer at a time.** None of this applies to a folder on one computer, where nothing changes.

**Who runs a training.** Starting a training makes it yours: your name and this computer are recorded in it, and that is shared before any work is done. If a teammate started one with the same name at the same moment, the first to be shared stands and the other is told.

On every other computer the training is listed apart, under "Run by your teammates", with who runs it and since when. It can be opened and read there: the steps, the files, the reviews. Nothing there can pause it, stop it, decide a gate or answer a question.

A computer knows only what was last shared about a teammate's training. So the page does not say it is working or waiting. It says when it was last shared, where it stood then, and that it may have moved on since.

**Taking over.** "Take it over" on a teammate's training makes it yours. The page first says whose it is, since when, and that their runner will stop working on it. Their runner learns of it the next time it shares or looks for teammates' work. It stops that training and says who took it and when. Anything it had made and not yet shared is kept on that computer, out of the way, and can be brought back with git; the page says where. If someone else took the training since you last looked, the page says who has it now and asks again.

**Handing over.** "Hand over" lets go of a training, so that anyone on your team may take it. Until someone does, nothing more happens to it. A finished training is handed over by itself: nobody runs it. It can be read and published from any computer, and "Take it" makes it yours again when something in it should change.

A runner that is closed still holds its trainings. Nothing passes to someone else on its own: a person takes over when they mean to.

**If the rule is broken.** If the same training is changed on two computers anyway, for instance by hand, sharing stops and nothing is overwritten. Home, Settings and the training's own run say which training it is. "Carry on from the shared version" puts it right on one side: what that computer made and never shared is set aside and kept, and the training carries on from what the team has.

**Staying in step.** The runner looks for what teammates shared when it starts, every few minutes while it is open, and when you press "Look now". The page does not wait for it: it opens at once, and your trainings carry on once the runner has looked. Until then, a change you ask for is refused with a sentence that says why, so nothing is done to a training a teammate took while your runner was closed. A slow repository never holds up a decision. If looking, or a notification, goes wrong, the Status screen says what went wrong and when, until it next works. Looking never changes a training this computer runs. Sharing after each decision, or only when you ask, is as you set it. Starting, taking and handing over a training are always shared at once, and anything not yet shared goes with them.

**Several at once.** Settings says how many trainings may work at once on this computer. One that waits says how many are ahead of it, and they take turns in the order they became ready. The Status screen shows every run on this computer with what it is doing and what it has cost, and your teammates' trainings apart.

### When the page is closed

In Settings, "Tell me when no page is open" lets this computer notify you through its own notifications when a training needs your decision and no page is open. It is off until you turn it on. It says the training's title and that it needs a decision, once for each thing. It says nothing about a training you paused or stopped yourself, or one a teammate runs. Where the computer has no way to notify, the setting says so and stays off.

### Publishing

A finished training has a "Publish" button. Publishing marks the training, exactly as it stands, as its next numbered revision in the workspace. Nothing is copied and no second repository is used. A revision is never moved afterwards: publish again, and that is the next one.

A training that is not ready can still be published, and the revision says that it was not. Documents you supplied and saved pages are not part of a revision, because the workspace never shares them.

"Published", on the Trainings screen, lists each training at its latest revision: when, by whom, whether it was ready, and its index to read. Where a training has changed on this computer since, the list says so, because the index it opens is the training as it stands now.

Published while your team's repository cannot be reached, a revision is kept on this computer and goes with the next share.

This is separate from the older [team hub](team-hub.md), which is used from a conversation and is unchanged.

### Bringing a training in

A training you started in a conversation lives in a folder of its own. Open it on the page and press "Run this from here". It is copied into the workspace as a new training, named from its title. The copy's decisions are made on the page, and it carries on from wherever the training had got to, including a gate that was waiting.

The original folder is left exactly as it was, with nothing deleted. From then on the copy is the one to work on, and the page says where both are. It is refused, with the reason, when the workspace already has a training of that name, when the training's record cannot be read, or when the folder holds something a workspace does not take.

## What the runner guarantees

- **Only you approve.** A training the runner drives is decided on the page, and nowhere else. The runner has no way to approve a draft, and neither has an agent.
- **An agent cannot touch your files.** Each agent works in an empty folder outside your trainings, with no shell and no file tools. It can read what the runner gives it, search the web when the job is research, and hand back a draft or a finding. The runner checks what is handed back before anything is kept.
- **Quotes are real.** The runner fetches each source itself and keeps a copy. A finding is kept only when every quote in it is found, word for word, in the saved page.
- **Everything is recorded.** Each step, decision and request is a commit in the workspace, saying what happened. The pages a finding quotes stay on your computer; they are not shared.

## Good to know

- An agent the runner starts is still your own Claude Code or Codex. It knows what that agent normally knows about your account, such as the address you are signed in with, and Codex also reads your own instructions file and the names of your skills. None of that gives it a way to reach your files.
- A research question that fails three times does not stop the training. It is named as not researched when the research comes to you, and you decide whether that matters.
- The brand's own check warns on every slide with a caveat or a source line, because those lines are set smaller than the check allows. The warning is shown at the deck's gate. It is not something the runner can put right.
- A deck is drawn in the default look. Choosing between looks, editing a deck by hand and bringing the edits back, and pictures made by a model are not in the runner.
- What a deck is built from stays on the computer that built it and is not shared: the drawings, the previews and the pictures. Your team gets the deck, what it says, and what its gate showed. On another computer the deck's gate shows no pictures.
- Bringing edits back from a Google Doc, and reusing a teammate's scenarios or audiences in a new training, are not in the runner yet. The [team hub](team-hub.md) does the second from a conversation.
- A training made in a conversation is not picked up by the runner until you bring it in, and a training the runner drives should not also be driven from a conversation while it runs.
- Working as a team has been tried with two people's data on one computer against one repository. Two real computers, and a teammate installing it for the first time, have not been tried yet.
- `sh ~/.local/share/training-studio/studio status` prints what is set up and where every run is, as JSON. From a copy of the repository it is `python3 runner/studio.py status`.

The design is in [the runner's specification](superpowers/specs/2026-10-13-studio-runner-design.md). Working as a team is specified in [milestone 5](superpowers/specs/2026-10-13-milestone-5-team.md).
