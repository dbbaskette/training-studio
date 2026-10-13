# Studio Runner: design for a decision

Date: 2026-10-13
Status: accepted on 2026-10-13. The owner chose the runner (approach B in section 4). Milestone 0 was run the same day on both agents and ended "go, with changes"; the changes are folded in below. Nothing else is built yet.

## 1. The decision

Training Studio, `harness-research` and `harness-slides` run today as skills inside a chat harness. The model reads guidance, decides which command to run next, and is trusted to stop at each gate.

The question is whether to put a program in charge instead: a **runner** that walks the stages itself, uses a model only for bounded pieces of work, and stops at gates that the model cannot reach.

This document recommends doing that, in an order where the first milestone is useful on its own and the riskiest assumptions are tested before most of the work is spent.

## 2. What it must do

These came from the owner.

1. **Gates enforced in code.** The model cannot approve, skip a gate or run stages out of order.
2. **Unattended runs.** Start a training and leave. It works until it needs a person, and several can run at once.
3. **Same behaviour everywhere.** One policy for files, network and shell, set by the runner, not by whichever harness is in use.
4. **Team use.** A teammate can run it without installing the skills or learning how they work.
5. **Either agent, one per run.** A run is started on Claude or on Codex and stays on it.
6. **A local web page** is where reviews are read and gates are approved. It must be inviting, easy to use and easy to follow from one step to the next.

Covered first: Training Studio, `harness-research` and `harness-slides`. Other pipelines, such as one for blog posts, follow the same pattern later.

### Not in scope

- A hosted service. Each person runs it on their own computer. The only shared piece is a git repository.
- Its own agent loop. The runner uses Claude Code and Codex as workers; it does not reimplement them.
- Rewriting the two harness skills. Their command lines are called as they are.

## 3. What exists today

Four background investigations on 2026-10-13 read the two harness repositories and the vendors' documentation. Where something was read but not run, it says so.

| | Training Studio | harness-research | harness-slides |
| --- | --- | --- | --- |
| Code | Python 3.11, standard library | Node 20, standard library | Node 20 with four packages, Python, Poppler |
| What the code does | State, approval bound to content and inputs, checks, readiness, copies, hub, a read-only page | Validates and stores a plan and findings; renders a report | Dozens of commands: outline check, compile, preview, critique, render, import to Drive |
| What the model does | Writes each artifact; presents each gate; runs the commands in order | All searching, reading, judging and writing | Writes the outline and slide compositions; judges rendered slides |
| Gates in code | Approval is recorded and checked, but the model runs the command | None | None on the default path; approval is free text |

Things a runner has to work around, all found by reading code, not by running it:

- **harness-research:** every error is one line of prose with exit code 1. Its lock has no recovery after a crash. `status` rewrites the report. A run can reach "complete" with no evidence, because unanswered verdicts count as answered.
- **harness-slides:** a failed critique or an incomplete outline returns exit code 0, so results must be read from the JSON. The default path keeps no record of which stage a deck is at.
- **Shared, and already drifting:** the two harness skills carry copies of the same guidance sync that now differ by about 90 lines, and installers that follow one design with different code.

What the vendors offer. The options named here were confirmed in the help text of the installed command lines on 2026-10-13 (Claude Code 2.1.287, Codex 0.162.1); how they behave is from documentation.

- **Claude.** `claude -p` runs once and exits. It takes appended instructions, a tool list, a permission mode, a settings file, a choice of which settings to load, a spending limit, a JSON schema for the result and a list of MCP servers to use and no others. Its sandbox wraps shell commands only; file tools are limited by permission rules instead.
- **Codex.** `codex exec` does the same job, with a working directory, a sandbox mode, JSON events, a schema for the final answer, images as input and `--ignore-user-config`. Network access is off by default inside its workspace sandbox.
- **Both** accept tools supplied by another program through MCP.
- **A common protocol** (the Agent Client Protocol) reaches both through adapters. The Codex adapter rests on a component OpenAI calls experimental. It is not the base to build on now.

## 4. Approaches considered

| | A. Gate page only | B. Runner, agents as workers | C. Own harness |
| --- | --- | --- | --- |
| What it is | Skills stay in chat; approval moves to the page | A program walks the stages and hands bounded jobs to Claude or Codex | Own agent loop, tools and sandbox on the model APIs |
| 1. Gates in code | Yes | Yes | Yes |
| 2. Unattended | No | Yes | Yes |
| 3. Same behaviour | No | Mostly | Yes |
| 4. Team use | Partly | Yes | Yes |
| Size | Small | Large | Very large, then permanent upkeep |

**Recommendation: B, with A as its first milestone.**

- A is needed by B anyway, and it is worth having with today's skills. If the rest disappoints, stop there and keep it.
- C buys identical behaviour on both vendors by rebuilding web search, page fetching, browsing, PDF reading and image review. Those are what the vendors' harnesses are good at and keep improving.
- B is "mostly" on goal 3 because the two agents search and browse the web with different tools. Section 5.6 narrows that gap; it does not close it.

## 5. The recommended design

### 5.1 The rule everything follows

**The worker never holds the keys.**

A worker is one agent run doing one job. It can read its inputs and write into one staging folder. It cannot write to the training directory, cannot run an approval, and cannot see the credentials the runner uses for Google or the hub. What it produces is checked by the runner before anything is kept.

With that rule, gate enforcement does not depend on a model following instructions, and it does not depend on a hook that only one vendor offers.

### 5.2 The parts

```
                 you
                  |
            +-----v------+     decisions      +------------------+
            |  the page  +------------------->|                  |
            | (browser)  |<---reviews, logs---+      runner      |
            +------------+                    |  walks stages,   |
                                              |  owns approval   |
   training directory  <----keeps checked-----+                  |
   (deliverables, reviews,                    +--+-----+------+--+
    session record)                              |     |      |
                                      code steps |     |      | agent steps
                       +-------------------------+     |      +-----------------+
                       |                               |                        |
              +--------v---------+          +----------v---------+     +--------v---------+
              | existing command |          |   worker tools     |     |  agent adapter   |
              | lines: training, |          | (submit, ask,      |<----+ Claude or Codex, |
              | research, slides |          |  save a source)    |     | in a staging     |
              +------------------+          +--------------------+     | folder           |
                                                                       +------------------+
```

- **Runner.** A local program. It holds the pipeline definitions, runs code steps itself, starts workers for agent steps, and is the only thing that records an approval.
- **Core.** The state model Training Studio already has: artifacts, what each was built from, approval bound to both, history, staleness, checks, readiness, copies and the hub. It moves under the runner and is shared by every pipeline.
- **Pipeline definitions.** Data, not prose: for each stage, its steps, and for each step whether it is code, an agent job or a gate.
- **Agent adapters.** One for Claude, one for Codex, behind the same small interface.
- **Worker tools.** A handful of tools the runner serves to the worker over MCP, the same for both vendors.
- **The page.** The training desk, grown from read-only into the place gates are decided.
- **Team workspace.** A folder in a git repository the team already shares. Every training is stored in it, one folder each, and with them all of the runner's state. Section 5.9.

### 5.3 One agent step, start to finish

1. **Prepare.** The runner makes an empty staging folder and gathers the step's inputs and nothing else.
2. **Brief.** It writes the worker's instructions: the guidance for this one step, the inputs, and what to hand back. The guidance is written for a worker: it is today's stage reference without the helper commands, which the worker cannot and must not run. The worker is not asked to discover skills.
3. **Run.** The adapter starts the agent in the staging folder under the run's policy, with a turn limit, a time limit and a spending limit.
4. **Hand back.** The worker returns its work by calling a tool: `submit_artifact`, `submit_finding`, `save_source` or `ask_person`. The runner validates each call with the checks that exist today and answers with the problems, so the worker can fix them and try again.
5. **Keep.** When the checks pass, the runner copies the result into the training directory and records it through the core.
6. **Fail safely.** If the limits are reached or the checks keep failing, the step stops in a state that says what went wrong, and the page shows it. Nothing half-made is kept.

A question from a worker (`ask_person`) pauses that step and appears on the page. Everything else carries on.

### 5.4 A gate

1. The runner writes the review from what it already has: the artifact, the check results, what is stale and why, and the worker's own judgment of its work, labelled as such.
2. The page shows the review beside the artifact, with a comparison against the previous version.
3. The person chooses: approve, revise with notes, rebuild, or skip.
4. The runner records the decision in the session record and appends it to `reviews/<artifact>.md`.

No worker tool approves anything. The command-line helper refuses `approve` for a training that is run this way.

### 5.5 The adapters

Both implement one interface: start a job with instructions, a folder, a policy, limits and a result schema; stream events; return a result and what it cost.

| | Claude | Codex |
| --- | --- | --- |
| How it is started | `claude -p --restricted --output-format stream-json` | `codex exec --json` |
| Folder | The folder it is started in | `--cd` |
| Instructions | `--append-system-prompt` and the prompt | The prompt |
| Files | No shell and no file tools: the worker has only the runner's tools | The same. With its shell off, Codex cannot read a file at all |
| Network | None: no shell and no fetching tool. Research gets a search tool | Off unless enabled for the run with `-c` |
| Ignores the person's own setup | `--restricted` and `--strict-mcp-config`; an organisation's managed policy still applies | `--ignore-user-config` and `--ignore-rules`, and no instruction files in the folder |
| Nothing can ask a question | `--permission-prompts none` | Approval policy `never` |
| Result | `--json-schema` | `--output-schema` |
| Worker tools | `--mcp-config` | An MCP server given with `-c` |
| Limits | `--max-budget-usd`; the runner enforces the time limit | The runner enforces the time limit |
| Sign-in | The person's own Claude Code sign-in | The person's own Codex sign-in |

Both columns were tested in milestone 0. The Codex column needed more than is shown: a list of features switched off (connected apps, plugins, browser and computer use, sub-agents, hooks, the shell), its web tool disabled outside research, and the runner's tools marked as approved. The exact commands are in the milestone's results.

The adapters are deliberately thin. If a control exists on one side only, the design does not rely on it.

### 5.6 One policy

A run has one policy, and each step picks a profile from it.

| Profile | Files | Shell | Network |
| --- | --- | --- | --- |
| `write` (drafting an artifact) | Staging folder | No | None |
| `research` (one question) | Staging folder | No | A search tool; pages only through the runner |
| `review` (judging rendered slides) | Staging folder | No | None |

No profile has a shell or file tools. Milestone 0 showed that drafting, research and review need only the runner's tools: the brief carries the inputs, a runner tool serves anything larger, and results come back through runner tools. Everything needing a command, such as compiling a deck, is a step the runner runs itself. A worker's folder is then only a place to stand; it is still kept out of any shared temporary folder, and each worker is given a temporary folder of its own.

Two things narrow the difference between vendors:

- **Sources are saved through the runner.** A worker that finds a page calls `save_source`; the runner fetches it, stores the snapshot and its hash, and returns the text. Both vendors then quote from the same bytes. The worker hands back exact quotes and the runner works out where each sits.
- **Guidance is handed over, not discovered.** A teammate's local skills and instruction files cannot change what a worker is told.

What still differs: how each agent searches. In milestone 0 the runner fetched, with ordinary browser headers, a page that had refused an automated request in the first live run, so a real browser was not needed there. Pages that only render in a browser have not been tried.

### 5.7 The pipelines

**Training.**

| Stage | Code | Agent job | Gate |
| --- | --- | --- | --- |
| Intake | A form on the page | | The answers are the approval |
| Research plan | Check the plan | Draft the questions | 1 |
| Research | Run the research pipeline below | | 2 |
| Blueprint | Lint, size, level overlap | Draft the blueprint | 3 |
| Document | Coverage check; push to Google Docs after approval | Write the guide | 4 |
| Brief | Evidence check; push after approval | Write the brief | 5 |
| Deck | Run the slides pipeline below | | 6 |
| Scenario | Shape check | Draft, or use the person's file | 7 |
| Yoodli | Count and limit checks | Translate each scenario | 8 |
| Package | Readiness; write the index from the record | | none |

**Research.** `plan` is a code step. Then one worker per question, several at a time, each with the `research` profile, the evidence rules, and a short statement of what the training is about; without that, milestone 0's worker answered from general sources and missed the product angle. The runner calls `record` for each finding, one at a time. After the last, `status` is read and the runner applies its own rule for "enough": a question answered with no evidence is not counted as done.

**Slides.** A worker writes the outline; the runner checks it and renders the draft; a gate approves it. Workers compose sections in parallel; the runner compiles and renders previews. A separate worker answers the review questions about the rendered slides, and the runner records its answers. A gate shows the slides themselves. The runner then renders the deck and imports it.

Objectives are passed to the slides pipeline as source identifiers. Its existing coverage command can then say which slides cover which objective without a model.

### 5.8 The page

The page is the product. The people using it include teammates who have never seen the skills, so it has to be inviting, obvious and hard to get lost in. That is a requirement with tests, set out below, not a hope.

**What it must be like**

1. **What needs you comes first.** The home screen opens on the gates to decide and the questions to answer, above everything else. Someone who opens the page and does only the first thing on it is always doing the right thing.
2. **Plain words.** No "artifact", "stale" or "lineage" on screen. A training is "waiting for your review", "working on its own", "stopped: it needs a decision" or "finished".
3. **A gate is something to read.** The document is rendered as a document, with the review beside it: what was checked for you, and what is worth a look. What changed since last time is one click away.
4. **Deciding takes one action.** Approve, or say what should change in your own words. Rebuild and skip are there, and out of the way.
5. **You can leave.** After a decision the page says what happens next and that it can be closed. It tells you when you are needed again, through the browser's own notifications and a count in the tab title.
6. **You always know where a training is.** One row of stages, the same everywhere: done, in progress, yours to review, not started.
7. **No dead ends.** Every failure says what happened, what was kept, and offers one clear next step.
8. **Nothing is final by accident.** An approval can be reopened. Because state is in git, reopening is safe.
9. **Usable by everyone.** Works from the keyboard, readable by a screen reader, never relies on colour alone, comfortable in light and dark and at a narrow width.

**The flow**

```
home  ->  new training  ->  the run  ->  a gate  ->  the next thing that needs you
  ^                                         |
  +-----------------------------------------+
```

- **Home.** What needs you; what is working on its own, with the stage it has reached; what is finished. One button starts a new training. A line at the foot says whether this computer is ready.
- **New training.** Three short steps: the topic and who it is for; its shape, with a sensible default for every choice; the sources and the agent. Before it starts, it says how many times it will ask for you.
- **The run.** The row of stages, what is happening now in a sentence, the files made so far, and what it has cost. Detail about what a worker did is there to open, not in the way.
- **A gate.** The document, the review, the decision. After deciding, the page goes to the next thing that needs you, or back to home if nothing does.
- **Status.** Everything at once, for when more than one training is running: every run and its stage, how long it has been there, the workers running now, anything that failed with the reason, cost, and whether the computer is ready (Claude Code and Codex signed in and reachable from the network it is on now, Node and the two harness skills present, Google access working).
- **Settings.** The workspace, the agent to use by default, limits, notifications.

**States that are designed, not left over**

| State | What the page shows |
| --- | --- |
| First time | The set-up screen: the team's repository and the folder in it, when to share, the agent to use, and the limits, each checked as it is given. Then "Start your first training" |
| Nothing yet | An invitation to start, not an empty table |
| Working | What it is doing in a sentence, and what it will ask of you next |
| Waiting for you | The decision, first on the home screen |
| A step failed | What happened, what was kept, and one suggested action |
| Not signed in, or offline | Which thing is missing and how to put it right; work already done stays readable |

**How this is checked**

- **A design pass before each screen is built:** a mockup, reviewed, then code. The first mockups of home and a gate were shown to the owner on 2026-10-13.
- **A walk-through at milestones 1 and 2** with someone who has not seen it, given four tasks and no instructions: start a training, decide a gate, ask for a change, find the finished deck. What trips them is fixed before the milestone is called done.
- **Three questions every screen must answer at a glance:** what is happening, what is needed from me, what happens next.
- **Automated:** each screen is exercised from the keyboard and checked for contrast and labels in the test suite.

**Safety**

The desk is read-only today, answers on the local machine only, and requires a token. It gains write endpoints for decisions. Two rules come with that:

- **A person starts it, not an assistant.** Today the helper prints the page's address, with its token, to whoever ran the command. If an assistant ran it, the assistant could post a decision. The runner is launched by the person and never prints the token where a worker can read it.
- **Decisions need the token and a same-origin request**, as reads do now.

### 5.9 State lives in git

All state is files, and the files are in a git repository. There is no database and no server.

- **The team workspace is one folder in a repository the team already shares, and every training is stored in it,** one folder each. The repository may hold other tools' work too; the runner reads and writes only its own folder. The session record, the artifacts, the reviews and the run log all sit in the training's folder, as they do today. The runner keeps a clone of its own on each person's computer.
- **The runner commits at every point worth returning to:** a step whose result was kept, a gate decision, a change of settings. Each commit says what happened in its message.
- **A gate decision is a commit by the person who made it.** Who approved what, and when, is then in the history under their own git identity, with the review file in the same commit.
- **The comparison at a gate is a git diff** between the version last approved and the one in front of the person.
- **Restart is simple.** After a crash the runner compares the folder with the last commit, discards what was half-made and resumes at the first step that did not finish.
- **Going back is a git operation.** Any earlier state of a training can be looked at or restored. The helper's own store of earlier versions can be retired once this works.
- **Workers never see the repository.** Staging folders are outside it, so no worker can commit or read its history.

What is not committed:

| Kept out | Why |
| --- | --- |
| Staging folders and other working files | They are scratch |
| `sources/` by default | Supplied documents may be private, and saved pages are large: the first live run kept about 90 MB of them. A workspace can opt in |
| The guidance caches the two harness skills keep, which contain git repositories of their own | They are fetched again when needed |
| Lock files, tokens, anything a sign-in wrote | They belong to one computer |

Without `sources/`, a teammate can read the research and build on it, but cannot check a quote against its source or add to the research until the sources are fetched again. The approval of the research is bound to hashes that are committed, so it stays verifiable.

Staleness already works and is unchanged: an edited file makes what was built from it stale, and the runner offers to rebuild exactly those.

**One driver per training.** A training started in the runner is run from the page. The skills keep working for trainings started in chat. A chat-driven training can be handed to the runner; the reverse is not planned.

### 5.10 Team use

- One installer for the runner, which brings the pipelines with it.
- Each person needs Claude Code or Codex installed and signed in, plus Node for the two harness skills.
- **Trainings are stored in the team workspace.** The runner keeps its own clone on each person's computer and commits there as it works. It shares after each decision, unless the person chose to share only when they ask; the set-up screen says which.
- **Work in progress becomes visible to the team once it is pushed:** drafts, intake answers and gate reviews, not only finished work. Until then it is on one computer. Sources stay out unless the workspace opts in.
- **Different trainings never collide,** because each is its own folder. The runner replays local commits on top of the remote's, as the team hub does today, and never force-pushes.
- **One person drives a training at a time.** Taking a training over is a small commit that names the driver. If two people take the same one, the second push is refused and the runner says who has it. Handing over is the same commit in reverse.
- **Publishing no longer needs a second repository.** With trainings stored in the team workspace, a published revision can be a tag on the training's folder at an approved state, and shared scenarios and audience descriptions can be folders in the same repository. That would fold today's team hub into the workspace. It is assumed here and settled at milestone 5.

### 5.11 Where the code lives

- **In the Training Studio repository, under `runner/`.** An earlier version of this design assumed a new repository. The page and the core both live in this one, and a second repository would have meant two copies of each. Decided on 2026-10-13 when milestone 2 was specified; a split can follow if it is wanted.
- **Python, standard library only**, because the core is already Python and both agents are started as command lines. No vendor SDK is needed.
- **The two harness skills stay where they are** and are called at pinned versions. Merging them into this repository is a later choice, not a precondition.
- **Training Studio's helper** shrinks to a front end over the shared core.

## 6. Changes the existing skills need

Small, and worth making whether or not the runner is built.

| Skill | Change |
| --- | --- |
| harness-research | Errors as JSON with a code. Recovery from a lock left by a dead process. A `status` that writes nothing. |
| harness-slides | A record of where a deck is on the default path. Approval recorded as data, not free text. A structured request to replace the prose handoff. |
| Both | One shared copy of guidance sync and the installer. |
| Training Studio | Approval that can be limited to the page. |

## 7. Milestones

Each ends with something that can be judged.

| | Milestone | Proves | Size |
| --- | --- | --- | --- |
| 0 | **Spike.** One research question and one drafting job, run on both agents in a locked staging folder, handing back through worker tools | That both agents can be confined, isolated from local setup and given the same tools; whether unattended research is as good as the interactive kind | Small |
| 1 | **Approval and status on the page.** The desk becomes the home, gate and status screens of section 5.8, for trainings run by today's skills; the helper refuses `approve` elsewhere. Ends with a walk-through by someone who has not seen it | Goal 1, with today's skills; whether the page is as easy as it must be | Medium |
| 2 | **Runner, training through the blueprint.** Core moved; state committed to git at each step and gate; intake form; research plan; the research pipeline; gates 1 to 3; live worker activity and cost on the status screen | Goals 1 to 3 on the hardest stage | Large |
| 3 | **The rest of training.** Document, brief, scenarios, Yoodli, package, Google Docs, hub | A whole training without a chat | Medium |
| 4 | **Slides.** The deck pipeline, with slides shown at the gate | The last delegated stage | Large |
| 5 | **Team.** Installer, shared workspaces with one driver per training, several runs at once, notifications | Goal 4 | Medium |

Stop after milestone 0 if research is clearly worse unattended. Stop after milestone 1 if that is enough control.

## 8. Risks and open questions

- **Codex workers still see some of the person's setup.** The list of installed skills and the global instruction file reach every Codex worker, so two people's Codex workers can behave differently. The fix is a separate home folder for workers holding only the sign-in; it needs the person's agreement and has not been tried.
- **Codex is costly per job.** Each job carried 50,000 to 190,000 input tokens of standing instructions, mostly cached.
- **An agent can be unreachable on a given network.** A run started on one agent stays on it, so a person on a network that blocks that agent cannot continue the run from there.
- **The account's email address reaches every worker** on Claude. The owner accepted this on 2026-10-13.
- **Pages that need a browser.** Not met in milestone 0; not ruled out.
- **Judging slides from images.** Both agents must read rendered slides in an unattended run. Codex takes images as input and Claude reads image files; neither has been tried here.
- **Vendor churn.** Codex's flags and documentation have moved several times this year. Thin adapters limit the damage; they do not remove it.
- **Passing worker tools to Codex while ignoring user configuration.** The override option exists. Whether the two combine as needed is not verified; it is part of the Codex half of milestone 0.
- **Two people on one training.** Git merges folders well and a single session record badly. The one-driver rule avoids the conflict; it does not resolve one if someone works around it.
- **Large files.** Decks and saved sources grow a repository. Sources are kept out by default; decks are committed, and that may need revisiting.
- **Two ways to run a training.** The skills and the runner must agree on the core. One shared core, with tests, is the mitigation.
- **Size.** This is a product, not a script. My estimate, not a measurement: milestones 2 and 4 are each about as large as everything built for Training Studio so far.
- **What is given up.** Improvements that arrive in the chat harnesses stop being free; the runner has to adopt them.

## 9. Decisions

- **Approach (2026-10-13, by the owner).** The runner, approach B, with a status screen on the page.
- **Sign-in and cost (2026-10-13, by the owner).** The runner starts `claude -p` and `codex exec` under each person's own sign-in. It automates work that person already does by hand in those tools, one run at a time; it is not a service offered to others. No API key or vendor SDK is involved.

- **Local, with state in git (2026-10-13, by the owner).** It runs on each person's computer and is not hosted. A git repository manages state, with a commit at every step and gate.
- **Trainings are stored in the team workspace (2026-10-13, by the owner).** One repository per team holds every training.
- **The workspace is a folder in a repository the team already uses for other work (2026-10-13, by the owner),** not a repository of its own, and a set-up screen configures it when the runner is first started.

### Assumed until the owner says otherwise

- Today's team hub folds into the workspace: a published revision is a tag, and shared scenarios and audiences are folders in it.
- Work is shared after each decision unless the person chooses to share only when they ask. The set-up screen says so.
- The runner is written in Python, standard library only.
- Milestones 1 and 2 are built on Claude first, behind the adapter interface, with the Codex adapter following in milestone 2 using the mode milestone 0 arrived at.
