# Studio Runner, milestone 5: the team

Date: 2026-10-13
Status: specified. Builds on milestones 2 to 4.

## Purpose

A teammate can run Training Studio without installing the skills or learning how they work, and several people can share one workspace without treading on each other.

## Scope

In: an installer that brings the runner; one driver for each training, with taking over and handing over; staying in step with what teammates share; several runs at once, shown honestly; a notification when the page is closed; publishing a finished training inside the workspace; bringing a training started in a conversation into the runner.

Out: reusing a teammate's scenarios or audience descriptions in a new training, which the older team hub offers from a conversation and which can follow once publishing here has been used; two people deciding gates of the same training; a hosted service of any kind.

## 1. The installer brings the runner

`installer/install.py` already installs the skill for Claude Code and Codex, keeps versions, rolls back and removes. It gains the runner.

- The runner is installed with each version, beside the helper, and finds the helper's modules in either layout: a checkout of this repository or an installed version.
- A way to open it that needs no terminal knowledge: on macOS a double-click launcher, "Open Training Studio", which starts the runner in a terminal window of the person's own, so the page opens with its key in their browser and nowhere else. On any system, a one-line command the installer prints.
- **The two companion skills come with it.** Today the installer only reports that harness-research or harness-slides is missing. It now installs each one's small stub skill: the entry that skill keeps in its own repository for this purpose, which points at that repository and brings the skill's runtime and current guidance from there. Each stub is taken from the companion's repository at a revision this installer pins and verifies, is installed for the same agents as Training Studio, and is left alone when a newer one is already there. Nothing of a companion is copied into this repository.
- The installer says what else the runner needs and does not have, each with how to get it: git with a name and email, an agent that is installed and signed in, Node, and for decks a brand skill, which is an organisation's own and is not installed from here. It asks before changing anything, as now.
- Update, check, roll back and remove cover the runner. A runner that is serving is never replaced underneath itself: the installer says to close it first.

## 2. One driver for each training

A training in a shared workspace is run from one computer at a time.

- **The driver** is recorded in the training's run record: who (the git identity), which computer (an identifier the runner makes once for each computer, with no personal data in it), and since when.
- **Taking a training** is a commit that names the driver. Starting a training takes it. In a shared workspace the commit is pushed before the runner does any work for that training. If the push is refused because someone else took it first, the runner drops its own claim and says who has it.
- **Everyone else reads.** On another computer the training is in every list with who is running it. Its run can be opened and read: steps, files, reviews. It has no pause, stop, decide or answer there.
- **Taking over** is offered on a training someone else drives, with a confirmation that says whose it is, since when, and that their runner will stop working on it. It is the same commit. The other runner learns of it the next time it shares or fetches: it stops that training, keeps what it had, and says who took it and when.
- **Handing over** clears the driver, so that anyone may take the training. A finished training has no driver.
- **A runner that is closed still holds its trainings.** Nothing times out by itself: a person takes over when they mean to.
- A workspace that is a folder on one computer has no drivers; nothing changes there.

This rule is what keeps two computers from writing one training's record. If it is broken by hand and the same file changes on both sides, sharing already stops, puts things back and reports; the page then says which training, and that one side must take over.

## 3. Staying in step

- The runner fetches the workspace when it starts, when the page asks, and every few minutes while it serves. A fetch never changes a training this computer drives.
- A training a teammate started appears in the lists with its driver. One a teammate finished appears under Finished.
- Sharing after each decision, or only when asked, is unchanged.

## 4. Several runs at once

The limit on how many trainings work at once exists. This milestone makes it visible and fair: a training waiting for its turn says so and how many are ahead of it; trainings take turns in the order they became ready; the status screen shows every run on this computer, what each is doing, what each has cost, and the trainings teammates drive, apart from this computer's own.

## 5. A notification when the page is closed

The page already notifies through the browser while it is open. When no page is open and a training needs the person, the runner can tell them through the computer's own notifications. It is off until turned on in Settings, says only the training's title and that it needs a decision, and is sent once for each thing that needs them. Where the computer has no way to notify, the setting says so.

## 6. Publishing inside the workspace

A finished training can be published from its screen. Publishing marks a point in the workspace's history: a tag for that training and revision, on the commit where it stood, pushed with the workspace. Nothing is copied and no second repository is used.

- Each publish is the next numbered revision of that training and is never moved afterwards.
- What is published is what the workspace already shares for that training at that commit. Supplied documents and saved pages are not in it, because the workspace never shares them.
- A training that is not ready can be published; the revision records that it was not, and the page says so before publishing and after.
- The page lists what the workspace has published: each training, its latest revision, when and by whom, whether it was ready, and its index to read.
- The older team hub, driven from a conversation, is unchanged and separate.

## 7. Bringing a training into the runner

A training started in a conversation lives in a folder of its own. From its screen on the page, "Run this from here" copies it into the workspace as a new training folder, sets its decisions to the page, starts a run record that takes it, and commits. The original folder is left exactly as it was, with nothing deleted; the page says where the copy is and that the copy is now the one to work on. The runner then carries on from wherever the files say the training is, including a gate that is waiting.

It is refused, with a sentence, for a training that is already in the workspace, one whose record cannot be read, or one with a file the workspace would not accept.

## 8. Tests

- The installer against a temporary home: the runner installed, found in both layouts, the launcher written, update and rollback, refusal while a runner serves, each companion's stub installed from a local stand-in for its repository, a stub that fails its check refused, a newer stub left alone, and each missing thing reported.
- Two runners against one bare repository: taking, a refused second claim, reading without controls, taking over and the other side stopping, handing over, a broken rule reported.
- Fetching on a timer without touching a driven training.
- Turns taken in order, and the status of several runs.
- Notifications through a replaced command, sent once.
- Publishing: revisions numbered, tags pushed, never moved, the list.
- Bringing a training in: the copy, the original untouched, each refusal, and the run carrying on at a waiting gate.
- The page's new parts through their own controls.

## Done when

- The suite passes and `validate_package.py` prints `ok`.
- On one computer with two separate data folders standing in for two people, against one bare repository: one starts a training, the other sees it and cannot decide, takes it over, and the first is told.
- A training started in a conversation is brought in and carried on to its next gate on the page.
- The installer is run into a temporary home and the runner opened from what it installed.
- Not claimed without people: two real computers, and a teammate who has never seen it installing and running a training.

## Appendix: what the page asks the runner

- List items and `GET /api/run` gain `driver`: `null` for a training nobody drives, else `{"name", "here": bool, "since"}`. A training driven elsewhere answers `GET /api/run` with `"mine": false` and every changing address answers 409 with who has it.
- `POST /api/drive` with `{"path", "action": "take" | "hand-over"}` returns the run.
- `GET /api/run` for a training waiting its turn gains `queue`: `{"ahead": int}`.
- `GET /api/setup` gains `notify`: `{"on": bool, "can": bool, "problem": str or null}`; `POST /api/setup` takes `notify`.
- `POST /api/publish` with `{"path"}` returns `{"revision", "ready": bool, "shared": bool, "notice"}`. `GET /api/published` returns `{"published": [{"path", "id", "title", "revision", "at", "by", "ready"}]}`.
- `POST /api/adopt` with `{"path"}` returns `{"path", "id"}` of the copy.
- `GET /api/status` returns every run on this computer and the trainings driven elsewhere, in the shape the status screen shows.
