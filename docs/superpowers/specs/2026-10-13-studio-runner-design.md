# Studio Runner: design for a decision

Date: 2026-10-13
Status: accepted on 2026-10-13. The owner chose the runner (approach B in section 4). Nothing is built yet; milestone 0 is next.

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
6. **A local web page** is where reviews are read and gates are approved.

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
- **Team workspace.** One git repository per team. Every training is stored in it, one folder each, and with them all of the runner's state. Section 5.9.

### 5.3 One agent step, start to finish

1. **Prepare.** The runner makes a staging folder and copies in the step's inputs and nothing else.
2. **Brief.** It writes the worker's instructions: the guidance for this one step, the inputs, and what to hand back. The guidance is the text of today's stage reference. The worker is not asked to discover skills.
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
| How it is started | `claude -p --output-format stream-json` | `codex exec --json` |
| Folder | The folder it is started in | `--cd` |
| Instructions | `--append-system-prompt` and the prompt | The prompt |
| Writes limited to the folder | Shell sandbox, plus permission rules on the file tools, both from `--settings` | `--sandbox workspace-write` |
| Network | Sandbox allow-list for shell; permission rules for fetching | Off unless enabled for the run with `-c` |
| Ignores the person's own setup | `--setting-sources` and `--strict-mcp-config`; an organisation's managed policy still applies | `--ignore-user-config`, and no instruction files in the folder |
| Result | `--json-schema` | `--output-schema` |
| Worker tools | `--mcp-config` | An MCP server given with `-c` |
| Limits | `--max-budget-usd`; the runner enforces the time limit | The runner enforces the time limit |
| Sign-in | The person's own Claude Code sign-in | The person's own Codex sign-in |

The adapters are deliberately thin. If a control exists on one side only, the design does not rely on it.

### 5.6 One policy

A run has one policy, and each step picks a profile from it.

| Profile | Files | Shell | Network |
| --- | --- | --- | --- |
| `write` (drafting an artifact) | Staging folder | No | None |
| `research` (one question) | Staging folder | Yes | Public web, minus a deny list |
| `build` (compiling a deck) | Staging folder | Yes | Named hosts only |

Two things narrow the difference between vendors:

- **Sources are saved through the runner.** A worker that finds a page calls `save_source`; the runner fetches it, stores the snapshot and its hash, and returns the text. Both vendors then quote from the same bytes.
- **Guidance is handed over, not discovered.** A teammate's local skills and instruction files cannot change what a worker is told.

What still differs: how each agent searches, and whether it can drive a real browser. The first live run needed a browser to read pages that refused automated requests. Section 7 tests this before anything else is built.

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

**Research.** `plan` is a code step. Then one worker per question, several at a time, each with the `research` profile and only the evidence rules. The runner calls `record` for each finding, one at a time. After the last, `status` is read and the runner applies its own rule for "enough": a question answered with no evidence is not counted as done.

**Slides.** A worker writes the outline; the runner checks it and renders the draft; a gate approves it. Workers compose sections in parallel; the runner compiles and renders previews. A separate worker answers the review questions about the rendered slides, and the runner records its answers. A gate shows the slides themselves. The runner then renders the deck and imports it.

Objectives are passed to the slides pipeline as source identifiers. Its existing coverage command can then say which slides cover which objective without a model.

### 5.8 The page

- **Status:** everything at once, on one screen that keeps itself up to date.
  - Every run: its stage, what it is doing or waiting for, and how long it has been there.
  - What needs a person, first: gates to decide and questions to answer.
  - The workers running now, and anything that failed, with the reason.
  - What each run has cost so far.
  - Whether this computer is ready: Claude Code and Codex installed and signed in, Node and the two harness skills present, Google access working.
- **A run:** stages and steps, what each worker is doing now, what it cost.
- **A gate:** the review, the artifact, the comparison, the choices.
- **Start:** the intake form, the agent to use, the limits.

The desk is read-only today, answers on the local machine only, and requires a token. It gains write endpoints for decisions. Two rules come with that:

- **A person starts it, not an assistant.** Today the helper prints the page's address, with its token, to whoever ran the command. If an assistant ran it, the assistant could post a decision. The runner is launched by the person and never prints the token where a worker can read it.
- **Decisions need the token and a same-origin request**, as reads do now.

### 5.9 State lives in git

All state is files, and the files are in a git repository. There is no database and no server.

- **The team workspace is one git repository, and every training is stored in it,** one folder each. The session record, the artifacts, the reviews and the run log all sit in the training's folder, as they do today. Each person works in their own clone.
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
- **Trainings are stored in the team workspace.** Each person clones it and works there. The runner commits locally as it works. It pushes when the person says so, or after each gate decision if the workspace is set that way; pushing is never silent by default.
- **Work in progress becomes visible to the team once it is pushed:** drafts, intake answers and gate reviews, not only finished work. Until then it is on one computer. Sources stay out unless the workspace opts in.
- **Different trainings never collide,** because each is its own folder. The runner replays local commits on top of the remote's, as the team hub does today, and never force-pushes.
- **One person drives a training at a time.** Taking a training over is a small commit that names the driver. If two people take the same one, the second push is refused and the runner says who has it. Handing over is the same commit in reverse.
- **Publishing no longer needs a second repository.** With trainings stored in the team workspace, a published revision can be a tag on the training's folder at an approved state, and shared scenarios and audience descriptions can be folders in the same repository. That would fold today's team hub into the workspace. It is assumed here and settled at milestone 5.

### 5.11 Where the code lives

- **A new repository** for the runner, the core, the adapters, the page and the pipeline definitions.
- **Python, standard library only**, because the core is already Python and both agents are started as command lines. No vendor SDK is needed.
- **The two harness skills stay where they are** and are called at pinned versions. Merging them into the new repository is a later choice, not a precondition.
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
| 1 | **Approval and status on the page.** The desk decides gates and gains the status screen, for trainings run by today's skills; the helper refuses `approve` elsewhere | Goal 1, with today's skills | Small |
| 2 | **Runner, training through the blueprint.** Core moved; state committed to git at each step and gate; intake form; research plan; the research pipeline; gates 1 to 3; live worker activity and cost on the status screen | Goals 1 to 3 on the hardest stage | Large |
| 3 | **The rest of training.** Document, brief, scenarios, Yoodli, package, Google Docs, hub | A whole training without a chat | Medium |
| 4 | **Slides.** The deck pipeline, with slides shown at the gate | The last delegated stage | Large |
| 5 | **Team.** Installer, shared workspaces with one driver per training, several runs at once, notifications | Goal 4 | Medium |

Stop after milestone 0 if research is clearly worse unattended. Stop after milestone 1 if that is enough control.

## 8. Risks and open questions

- **Research quality without a browser.** Covered by milestone 0.
- **Judging slides from images.** Both agents must read rendered slides in an unattended run. Codex takes images as input and Claude reads image files; neither has been tried here.
- **Vendor churn.** Codex's flags and documentation have moved several times this year. Thin adapters limit the damage; they do not remove it.
- **Passing worker tools to Codex while ignoring user configuration.** The override option exists. Whether the two combine as needed is not verified; part of milestone 0.
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

### Assumed until the owner says otherwise

- Today's team hub folds into the workspace: a published revision is a tag, and shared scenarios and audiences are folders in it.
- Nothing is pushed without the person saying so, unless a workspace is set to push after each gate.
- The runner itself is a new repository, in Python, created at milestone 2. Milestones 0 and 1 do not need it.
- Milestone 0 comes first, and its result can end the project.
