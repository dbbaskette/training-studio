# Milestone 1: approval and status on the page

Date: 2026-10-13
Status: to build
Parent: [Studio Runner design](2026-10-13-studio-runner-design.md), sections 5.4, 5.8 and 7.

## Purpose

Today a gate is approved by the assistant running `training.py approve` after the user says yes in chat. Nothing stops an assistant running it unasked. This milestone moves the decision to a local web page the assistant cannot use, and turns the read-only desk into the page the design describes: home, a gate, and status.

It serves trainings run by today's skills in a chat. The runner comes later and will reuse all of it.

## Scope

In: an approval mode that only the page can satisfy; recording what the user decided so the assistant can act on it; the page's home, gate and status screens; a readiness check of this computer; guidance, tests and documents.

Out: the runner, workers, state in git, starting a training from the page, cost, sharing.

## 1. Approval mode

- `settings.approval` is `chat` or `page`. A training started before this exists reads as `chat`.
- It is set with `init --approval page` or `checkpoint --approval page`.
- **Only the page can turn it back to `chat`.** `checkpoint --approval chat` from the command line is refused while it is `page`.
- While it is `page`, the command line refuses:
  - `approve <artifact>`, with or without `--accept-stale`, for every artifact except `intake`, whose approval records the user's own answers;
  - `skip <stage>` and `skip <stage> --clear`. `skip --unavailable` is still allowed: it reports that something could not run, which is not a decision.
- Each refusal says the decision is made on the page and how the user opens it.
- A decision made on the page is recorded with `by: "page"` on the approval and in the event log. One made from the command line is recorded with `by: "chat"`.

This raises the bar; it does not make forgery impossible. An assistant with a shell that set out to edit the session record could still do so, and the guidance forbids that. Say so plainly in the documents. Real confinement arrives with the runner.

## 2. Decisions and requests

A new core function records a decision. It is what the page calls; the command-line `approve` and `skip` call the same function with `by="chat"`.

| Decision | Needs | Effect |
| --- | --- | --- |
| `approve` | nothing | As `approve` today |
| `accept` | a reason | As `approve --accept-stale` today. Offered only when the artifact is stale |
| `revise` | a note | Approves nothing. Records an open request |
| `rebuild` | an optional note | Approves nothing. Records an open request |
| `skip` | a reason | As `skip` today, for the artifact's stage. Offered only for a stage that can be skipped |

- An open request is `{artifact, kind, note, at}`. It closes when that artifact is next saved with `--built` or `--from`, or when it is approved.
- `status` reports open requests as `requests`, and the session's approval mode.
- Every decision clears `pending_question`, sets `next_step` to a sentence saying what was decided, and appends a dated entry to `reviews/<artifact>.md` naming the decision and any note. The file is created if it is missing.
- `checkpoint` gains `--gate <artifact>`: which artifact is at the gate. `--no-question` clears it. `status` reports it as `gate`. Without it the page falls back to the first artifact in pipeline order that is a draft or stale.

State changes here need rows in the plan's state-transition matrix and tests named for them.

## 3. The page

Rebuild the desk's front end as three screens, following section 5.8 of the parent design, which is binding: what needs you first, plain words, a gate is something to read, one action to decide, you can leave, no dead ends.

**Home.**
- A greeting line that counts what needs the user.
- *Needs you:* one row per training with a gate waiting or an open question, each with the training's title, one sentence saying what is waiting, and a button to open it.
- *In progress:* trainings neither waiting nor finished, each with a row of stages showing done, current and not started, and one sentence saying where it is.
- *Finished:* trainings that are ready.
- A line at the foot saying whether this computer is ready, linking to status.
- An empty state that invites, when there are no trainings.

**A gate.** Reached from a row on home; also for any artifact from a training's own view.
- The training's title and the row of stages, with the stage under review marked.
- The document, rendered as a document, not as source text. Markdown is rendered in the browser by a small renderer written for this page: headings, paragraphs, lists, tables, block quotes, code, emphasis and links, built as DOM nodes with text content only. The research plan is shown as its questions. A deck is shown as its name, size and, for a link, the link text. HTML comments in a document, such as coverage comments, are not shown.
- *What changed:* a line comparison with the version last approved, when there is one.
- *Checked for you* and *Worth a look:* this artifact's passed checks as a count, each failed or unavailable check by name and reason, whether it is stale and why, and the latest entry in `reviews/<artifact>.md`.
- The decision bar: Approve; Ask for changes, which needs a note; and, under More, Rebuild, Skip this stage and, when stale, Accept as it is. A missing note or reason is refused beside the control, not by the server alone.
- After a decision: a sentence saying what happens next and that the page can be closed, then the next thing that needs the user, or home.
- When the training's approval mode is `chat`, the decision bar is replaced by a sentence saying approval happens in the conversation, with one control to move it to the page.

**Status.**
- Every training: title, levels, stage, its state in plain words, how long since it last changed, and how many things block it. Each opens the training's own view, which keeps what the desk shows today: files, checks, practice, research, guidance.
- This computer: Claude Code and Codex, each installed, signed in where that can be asked without side effects, and reachable from the current network; Node; the `harness-research` and `harness-slides` skills; `gcloud`; `pandoc` as optional. Each failing item says how to put it right. The check runs when asked for and its result is cached briefly; it never runs an agent.

**Everywhere.**
- Plain words. Never "artifact", "stale" or "lineage" on screen. Suggested: "waiting for your review", "out of date", "in progress", "finished", "left out".
- Updates itself without a reload. The tab title carries a count of what needs the user, and the browser's notification is used, once permission is given, when something new needs them.
- Works from the keyboard, with visible focus, labelled controls and no meaning carried by colour alone. Light and dark. Usable at phone width.
- **The look is a native Mac app in a liquid glass style** (the owner, 2026-10-13, after seeing a plainer mockup). A translucent sidebar and a floating glass toolbar over a soft, slowly drifting backdrop; glass cards for what needs you; capsule controls; a highlight on glass that follows the pointer; system type and the system's accent colour; light and dark as two designed appearances.
- **Glass is for navigation and controls; reading happens on a solid surface.** The document at a gate, the comparison and any long text are opaque.
- **The look gives way when it should.** Where the browser cannot blur, or the person has asked for less transparency, more contrast or less motion, surfaces become solid and movement stops. Text on glass keeps its contrast whatever is behind it.

## 4. Safety

- The server still answers only on the local machine, checks the `Host` header and requires the token on every API call.
- New write endpoints accept `POST` with a JSON body only, and also require an `Origin` header equal to the page's own origin. Every other method stays refused.
- **The link with its token is never printed to something that is not a person.** When standard output is a terminal, `desk` prints the link as now. When it is not, it prints the address without the token and a sentence telling the reader to run the command in a terminal of their own, and it opens the page in the default browser itself if it can. A training in `page` mode is therefore opened by its user.
- A path, an artifact name and a decision are validated on the server exactly as reads are today: registered trainings only, known artifacts only.
- Notes and reasons are stored as text and shown as text.

## 5. Guidance

- The gates reference: in `page` mode the assistant presents the gate as now, records the checkpoint with `--gate`, tells the user to decide on the page, and does not ask for approval in chat. When the user returns, or on resume, it reads `status`: approved, carry on; an open request, act on it and present again; skipped, carry on.
- The desk reference is rewritten for the page, including that the assistant gives the user the command to run and does not open the page itself when approval is on the page.
- Intake offers approval on the page as an option.
- Budgets hold. The gates reference has almost no room: say the least there and put the rest in the desk reference. Cut, never raise a budget. `validate_package.py` must print `ok`.

## 6. Tests and documents

- Tests for every rule in sections 1, 2 and 4, for the gate fallback, for requests opening and closing, and for the readiness check with its commands stubbed. Server tests bind a local port and are skipped where that is not allowed.
- `docs/desk.md` rewritten for a new user. The README's "Things you can say" and "Learn more" updated. `docs/how-it-works.md` updated where approval is described.
- New matrix rows in the plan, with `test_row_NN` tests.
- `VERSION` and `minimum_runtime` become 0.8.0.

## Done when

- `env -u PYTHONDONTWRITEBYTECODE python3 -m unittest discover -s tests` passes with port binding allowed, and `validate_package.py` prints `ok`.
- With a training in `page` mode, `approve` and `skip` from the command line are refused, and the same decisions made on the page are recorded and visible in `status`.
- The three screens work on real data in a browser, in light and dark, at desktop and phone width.
- A walk-through by someone who has not seen it is still to do; it needs a person and is not part of the build.

## Deviations

Recorded when it was built. Each is something the text above does not say, or says differently.

- **Two more screens, and the decision in the toolbar.** The sidebar the look asks for has four entries: Home, Trainings, Status and Settings. Trainings lists every training as a card. Settings holds notifications and where each training is decided. Status still shows every training and this computer. The main action of a screen, at a gate the decision, sits in the toolbar, not in a bar beneath the document.
- **Cards are translucent but do not blur.** Only the sidebar, the toolbar, a sheet and a toast blur what is behind them, to keep the page smooth. A card sits straight on the backdrop, which is already soft.
- **The accent colour fills; it does not write.** The system's accent is used for the filled button and the bead that is filling. Links and the focus ring use a fixed blue, because an accent the person chose may not be readable as text.
- **A decision is confirmed in a sheet.** Approve, and bringing a stage back, open a sheet that drops from the toolbar and ask once more. The decisions that take a note are written in the same sheet. The sheet does not cover the document, so it can still be read while a note is written.
- **What changed is a second view of the document,** chosen with a control above it, not a section of the review column.
- **A sixth decision, `restore`.** The command line refuses `skip --clear` in `page` mode and says the decision is made on the page, so the page has to be able to make it. It also takes a stage by name, which is how Yoodli is turned on there.
- **`skip --clear` is still allowed from the command line when the stage is wanted,** where all it does is clear an `--unavailable` mark. That is a report, like `--unavailable` itself.
- **A request is refused from the command line in `page` mode too,** as `approve` and `skip` are.
- **An approval names the version that was read.** The page sends the hash of the document it showed, and an approval of anything else is refused. If the document changes while it is open, the page says so and waits. Without this a file rewritten while the page was open could be approved unseen.
- **An open request blocks readiness** (row 95). Otherwise a training could report itself ready with a change the user asked for still to make.
- **Every decision clears the recorded gate** as well as the question.
- **Decisions made in the conversation are written to the review and set `next_step` too,** because they go through the same function. The gates reference no longer tells the assistant to append the decision itself.
- **The page does not decide for a training whose approval is in the conversation.** The server refuses it; the page offers the control that moves approval.
- **A gate needs a question or a recorded gate to count as waiting.** The fallback to the first draft or out-of-date file applies when a question is recorded without a gate, which is what guidance pinned before this version does. A draft with neither is in progress, not waiting.
- **Intake turns approval on last.** The guidance records `--approval page` with the checkpoint that ends intake, after the stages the user left out, since `skip` is refused once it is on.
- **Signed in is not asked of Claude Code.** None of the commands the check may run says so without starting it. The page says it cannot be asked.
- **The Google Cloud CLI counts against readiness only when a training on this computer keeps a Google Doc or builds Google Slides.** Otherwise it is listed as an extra, like pandoc.
- **Which service Codex is reached at is an assumption.** The check connects to `chatgpt.com`, or to `api.openai.com` when `codex login status` mentions an API key. Neither was confirmed against Codex itself.
- **No text browser is started.** Where there is no screen, the page is not opened and the output says so.
- **Two more response headers:** `X-Frame-Options: DENY` and `Referrer-Policy: no-referrer`.
- **A fourth page file, `markdown.js`,** so the renderer can be tested on its own.
- **"Working" is a guess.** The page cannot see an assistant at work. A row shimmers when its training's record changed in the last three minutes.
- **What 5.8 asks of the test suite is met only in part.** Each screen is driven through its controls, and checked for names, for one filled button, and for the three words that must not appear, by running the page's scripts under Node in a document with no HTML parser. Contrast is computed from the stylesheet's tokens. No browser is driven, so focus order, the glass and the motion are checked by eye only.
