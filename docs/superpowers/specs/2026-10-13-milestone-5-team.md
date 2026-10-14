# Studio Runner, milestone 5: the team

Date: 2026-10-13
Status: built. Builds on milestones 2 to 4. Where the code differs from this text, see Deviations at the end.

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

## 9. Deleting a training

Added after the milestone, for issue #42. Deleting changes no artifact's status, approval, inputs or readiness, so the core's state-transition matrix (A7 of the plan) is unchanged; what Delete does to a runner training is specified here, and each row below is a test in `tests/test_runner_delete.py` or, for the page, `DeleteScreenTests` in `tests/test_desk.py`.

- **Who may.** The computer that runs a training, in any state; anyone, for a finished training nobody runs. Anything else is refused with a sentence and nothing is changed: a teammate's training is taken over first, and a handed-over one that is not finished is taken first. The page sends the title it showed, and another title is refused.
- **Stopped first.** A run that works is stopped as Stop and taking over stop it: what the step in hand would write is not kept, and every agent and command it started is ended. One waiting for its turn leaves the queue. The deletion waits until no thread, step or slot of it is left; after 30 seconds the training is left stopped and nothing is deleted.
- **What goes.** The folder is taken out of the branch in one commit, `<title>: <name> deletes this training, on <day> at <time> UTC`, shared as any change is. Then what only this computer kept for it: its ignored files (supplied documents, saved pages, a deck's builds and pictures), its job folders, its notes in the data folder and its place in the registry.
- **What stays.** Published revisions, as tags; the Published list no longer shows a training that is gone. Files in Google Drive, which are listed in the confirmation with their addresses. What `set_aside` kept, which is never deleted.
- **A teammate at the same moment.** A deletion not yet shared, of a training a teammate takes meanwhile, is set aside when that is learned, like any unshared change of a training taken from this computer; their version comes back whole, and the training's `notice`, or the refusal of Delete itself when it shares at once, says so.
- **A teammate learns of it.** A fetch that brings in a deletion lets the training go on that computer too: its leftovers, its notes and its place in the lists. A teammate with unshared changes to it gets "changed on two computers" instead, and nothing is removed.
- **A conversation's training** is never deleted by the runner, and the page offers nothing for one.

| From | Delete does | Test |
| --- | --- | --- |
| Paused, this computer's | Deleted, with what only this computer kept | `DeleteTests.test_a_paused_training_is_deleted_with_everything_this_computer_kept_for_it` |
| Stopped, this computer's | Deleted | `DeleteTests.test_a_stopped_training_is_deleted` |
| Waiting at a gate, this computer's | Deleted | `DeleteTests.test_a_training_waiting_at_a_gate_is_deleted` |
| Working, a command in hand | Stopped, every process ended, then deleted; the step keeps nothing | `DeleteTests.test_deleting_ends_a_command_its_step_is_running_and_everything_it_started`, `LiveDeleteTests.test_a_working_training_is_stopped_first_and_deleted_once_nothing_of_it_runs` |
| Waiting its turn | Leaves the queue at once, then deleted | `LiveDeleteTests.test_a_training_waiting_its_turn_leaves_the_queue_at_once` |
| Working, and not ended in time | Left stopped; nothing deleted | `LiveDeleteTests.test_a_run_that_does_not_end_in_time_is_left_stopped_and_nothing_is_deleted` |
| Finished and published | Deleted; revisions and Drive files stay | `DeleteTests.test_a_finished_published_training_is_deleted_and_its_revisions_and_drive_files_stay` |
| Finished, nobody's, from another computer | Deleted | `TeamDeleteTests.test_a_finished_training_is_deleted_from_any_computer` |
| A teammate's | Refused; nothing changed | `TeamDeleteTests.test_a_teammates_training_cannot_be_deleted_here` |
| Handed over, not finished | Refused until taken | `TeamDeleteTests.test_a_training_handed_over_before_it_finished_is_taken_before_it_is_deleted` |
| Any, with another title, or while the runner is still looking | Refused; nothing changed | `DeleteTests.test_the_title_must_be_the_one_the_page_showed`, `DeleteTests.test_nothing_is_deleted_while_the_runner_is_still_looking` |
| Deleted here, sharing after each decision | Shared at once; a teammate's lists drop it | `TeamDeleteTests.test_deleting_shares_at_once_and_a_teammate_drops_it_without_fuss` |
| Deleted here, sharing only when asked | Gone here; shared with "Share now" | `TeamDeleteTests.test_with_sharing_only_when_asked_the_deletion_waits_for_share_now` |
| Taken by a teammate before the deletion was shared | Their version stands; the page says so | `TeamDeleteTests.test_a_teammate_who_took_it_first_keeps_their_work`, `TeamDeleteTests.test_a_teammate_who_took_it_before_share_now_keeps_their_work` |
| A conversation's training | Not offered; 404 | `DeleteTests.test_a_folder_the_runner_does_not_drive_is_never_deleted`, `TeamDeleteTests.test_a_training_from_a_conversation_is_never_deleted_by_the_page` |

`GET /api/delete?path=` answers {"path", "title", "state", "may", "why", "stops", "share", "revisions", "documents", "drive"}, `drive` being [{"what", "name", "url"}]. `POST /api/delete` with {"path", "title"} answers {"deleted", "title", "shared", "notice"}.

## Done when

- The suite passes and `validate_package.py` prints `ok`.
- On one computer with two separate data folders standing in for two people, against one bare repository: one starts a training, the other sees it and cannot decide, takes it over, and the first is told.
- A training started in a conversation is brought in and carried on to its next gate on the page.
- The installer is run into a temporary home and the runner opened from what it installed.
- Not claimed without people: two real computers, and a teammate who has never seen it installing and running a training.

## What the first real run showed

Run on 2026-10-13 on one computer, with two runners on two data folders and two git identities standing in for two people, against one stand-in repository, through the page in a browser, on Claude Code.

- The first person started a training; its claim was pushed at once. The second joined the same workspace, where the set-up screen read the folder, branch and name from the team's own file, and saw the training under "Run by your teammates", read-only, with no controls.
- The second took it over through the confirmation; the take-over is a commit in the shared repository, and their runner carried on from the last shared state. After a fetch the first person's page named who runs it now, and after the fixes below, said when they took it, that this computer stopped, and that what it had not shared is kept on this computer and can be brought back.
- A training made the conversation way was brought in from the page: copied into the workspace, started at once, and the original folder left exactly as it was.
- The installer was run, by its builder, into a temporary home against the companions' real repositories: both were fetched at their pinned commits, verified and installed, and the installed command ran.

Put right because of it: the page now shows the runner's own sentence about a take-over, across a reload; a teammate's training says when it was last shared and where it stood then, and no longer claims to know what is happening now; a finished training in a shared workspace can be taken.

Not run for real: two real computers, a notification through the computer's own notifications, publishing to a hosted repository, the double-click launcher, and a teammate who has never seen it.

## Appendix: what the page asks the runner

- List items and `GET /api/run` gain `driver`: `null` for a training nobody drives, else `{"name", "here": bool, "since"}`. A training driven elsewhere answers `GET /api/run` with `"mine": false` and every changing address answers 409 with who has it.
- `POST /api/drive` with `{"path", "action": "take" | "hand-over"}` returns the run.
- `GET /api/run` for a training waiting its turn gains `queue`: `{"ahead": int}`.
- `GET /api/setup` gains `notify`: `{"on": bool, "can": bool, "problem": str or null}`; `POST /api/setup` takes `notify`.
- `POST /api/publish` with `{"path"}` returns `{"revision", "ready": bool, "shared": bool, "notice"}`. `GET /api/published` returns `{"published": [{"path", "id", "title", "revision", "at", "by", "ready"}]}`.
- `POST /api/adopt` with `{"path"}` returns `{"path", "id"}` of the copy.
- `GET /api/status` returns every run on this computer and the trainings driven elsewhere, in the shape the status screen shows.

## Deviations

Where what was built differs from the text above, the code is right and this section says how.

**The installer**

- A companion's small entry cannot be installed alone: it points at a runtime that only the companion's own installer lays out. So each companion is fetched from its repository at the one commit `installer/companions.json` pins, checked file for file against the digest pinned with it, and then installed by its own installer. Nothing of a companion is copied into this repository, as specified.
- Bringing a companion is a step of its own, confirmed for each one. `--yes` agrees to installing Training Studio and does not cover it; `--companions install` does, and `--companions skip` declines. With nobody to ask, none is brought and the report says how to.
- A companion's installer registers the skill for the agents it chooses, which may be more than the ones Training Studio was installed for. The person is told so before agreeing.
- Rolling back and removing Training Studio leave the companions in place. They belong to their own installers, and the report names the ones left.
- The launcher starts the runner in a terminal window of the person's own with `studio serve --open`. That window is given the link whole, as any terminal of theirs is, and the page is opened in their browser. Started from anything that is not a terminal, `--open` changes nothing: the address is printed without its key and only the browser is handed the key.

**One driver for each training**

- A new training started while the shared repository cannot be reached still starts. Nobody else can know of a training that was never shared, so its claim goes with the next share.
- Starting a training pushes its claim even when sharing is set to only when asked. A push sends the branch, so commits made earlier and not yet shared go with it.
- A finished training has no driver, and neither has one that was handed over. Either is nobody's until someone takes it: every change to it answers 409 until then. Publishing is the one exception, because it changes nothing in the training; a training nobody drives can be published from any computer, and one that someone else drives cannot. The page offers "Take it" on a finished training for that reason.
- A finished training that is taken keeps its driver until it is handed over, or finishes again.
- When a training is taken from a computer, or was changed on two computers and one carries on from the shared version, that computer's commits that were never shared are taken out of the branch and kept under a name of the runner's own in that computer's clone, `refs/training-studio/kept/...`. They are never pushed and never deleted. The page says in plain words that they are kept and can be brought back, and gives the name as a detail.
- Taking a training refuses once when its driver changed since this computer last fetched, and says who has it now. Asking again takes it over from them.
- Of a training someone else drives, a computer knows only what was last shared. Its run answers with the state `elsewhere` whatever its files say, with no step shown as working or waiting, and with `last_shared`: when that was, whose commit it was, and where the training stood then. In lists it keeps what was waiting then, to be read, and never counts as needing the person.

**Staying in step, turns and notifications**

- The page can ask for a fetch at any time, and says in a sentence what came back.
- A notification is not sent for a training the person paused or stopped themselves. One with a problem is still told.
- Turning the notification on where the computer has no way to notify answers 409 with the reason, and the setting stays off.

**Publishing and bringing a training in**

- A revision published while the shared repository cannot be reached is kept on this computer and goes with the next share. If someone else has published that number meanwhile, theirs stands in the shared repository and this one is not renumbered: it stays on this computer only. Publishing again once the repository can be reached takes the next free number.
- The list of what is published says, for each training, whether it has changed on this computer since that revision. Its index opens as the training stands now, so the page says when that is not what was published.
- The page offers publishing on a finished training only. The runner would publish any training this computer may publish, and records whether it was ready.
- Bringing a training in names the copy's folder from the training's title, as a new training's is. A folder of that name already in the workspace refuses it.

**What the page asks the runner, beyond the appendix**

- List items and `GET /api/run` also carry `mine` (in a list, null for a training no run drives), `notice` and `last_shared` (`{"at", "by", "says"}`, or null). A run also carries `taken` (`{"by", "at", "kept"}` for one taken from this computer, until it is taken back), `kept` (the names git keeps what was set aside under) and `clash` (true while it stands changed on two computers).
- `POST /api/fetch` with `{}` returns `{"reached", "received", "notice"}` and sends nothing.
- `GET /api/status` returns `{"limit", "runs", "elsewhere"}`. Each run on this computer also has `needs`, `queue`, `spent` and `notice`; each training driven elsewhere also has `last_shared` and `notice`.
- `GET /api/setup` gives the workspace a `notice`: why the last share did not share, which is also where a training changed on two computers is named.
- Each entry of `GET /api/published` also has `current`.
