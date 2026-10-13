# Milestone 2: the runner, through the blueprint

Date: 2026-10-13
Status: to build, after milestone 1
Parent: [Studio Runner design](2026-10-13-studio-runner-design.md), sections 5.1 to 5.9. Milestone 0's results, in the plan of the same date, fix the worker modes.

## Purpose

A program that takes a training from a filled-in form to approved blueprints with nobody in a chat: it drafts the research plan, runs the research, drafts each blueprint, and stops at each gate for a decision on the page.

## Scope

In: the engine, the worker tools, both agent adapters, the workspace repository, the training pipeline up to and including the blueprint gate, the research pipeline, and the page's additions: starting a training, watching a run, answering a worker's question.

Out: everything after the blueprint, research from supplied documents, slides, two people driving trainings in one workspace, an installer.

## Where it lives

Inside this repository, under `runner/`, reusing the helper's modules in `skills/training-studio/scripts/` as its core. The parent design assumed a new repository. The page and the core both live here, and splitting them now would mean two copies. Record the change in the parent design; a split can follow later.

Python 3.11 or newer, standard library only.

## 1. The workspace

Trainings are stored in a repository the team already shares, which other tools and people also write to. The runner owns one folder in it and nothing else.

- **A workspace is a repository, a folder inside it and a branch.** The folder is `trainings` unless the person chooses another. A training is `<folder>/<id>/`, created through the core's own `init`, in `page` approval mode.
- **The runner keeps a clone of its own** under the per-user data folder. It never works in a clone a person or another tool is using.
- **It never touches anything outside its folder.** It reads, writes, stages and commits only paths under it. Files at the repository's root that belong to another tool are left alone.
- **Every tool that shares the repository has a `hub.json` of its own,** which points to the repository and at that tool's particular folder. Training Studio's is `<folder>/hub.json`: the tool's name, a schema number, the workspace's name, the repository's address, the branch, the folder, and the oldest helper version that can use it. Another tool's `hub.json`, at the root or anywhere else, is not ours: it is never written, and never mistaken for ours.
- **Set-up** creates the folder if it is missing, with a README, an ignore file and that `hub.json` inside it, filled in from the set-up screen. Ignored: `work/`, `sources/`, the two harness skills' guidance caches, lock files.
- **A second person setting up** gives the repository's address. The runner finds Training Studio's `hub.json`, adopts its folder and branch, and asks for nothing it already says. It refuses one written for a newer helper than the one installed.
- **It commits** after every kept step and every decision, with a message that says what happened.
- **Sharing** is fetch, replay local commits on top of the remote's, push. It never force-pushes. A person chooses when: after each decision, which is the default, or only when they ask. If the remote cannot be reached or refuses, the work stays committed locally and the page says it is not shared yet.
- **A local folder with no remote** also works, for trying the runner out and for tests.
- When to share, and where this computer keeps its clone, are this computer's settings. They are not written into the repository.
- It refuses to start without a git identity, with the sentence that fixes it.

## 2. The engine

- **The next step is worked out from the files, not remembered.** Given a training, the engine reads the core's status, the open requests and the gate, and returns one of: an agent step, a code step, waiting on a person, or nothing left in this milestone. Restarting the runner therefore resumes every training without a recovery procedure.
- **A run record** in the training's folder holds what cannot be worked out: the agent and model chosen, the limits, and for each step attempted its times, cost, outcome and error. It is committed.
- **An agent step:** make an empty staging folder outside the workspace and outside any shared temporary folder; write the brief; start the worker; accept results only through the worker tools; on acceptance, save through the core and commit. On failure or a limit reached, retry up to twice with the reason added to the brief, then stop the training in a state that says what went wrong.
- **A gate:** when a stage's drafts pass their checks, write the review, set the gate and the question through the core, and wait. A decision made on the page wakes the engine: approve, continue; revise or rebuild, run the step again with the note; skip, continue.
- **Limits** per step: time, spend where the agent reports it, and attempts. Per training: a total spend at which it stops and asks.
- Several trainings can run at once, up to a small configurable number. Research questions within a training run several at a time.

## 3. Worker tools

One MCP server over standard input and output, started for each job, scoped to that job. Workers have no other tool except, for research, the agent's search tool.

| Tool | Does |
| --- | --- |
| `list_inputs`, `read_input` | The step's inputs, by name. Long ones are read in parts |
| `submit_artifact` | Hands back a draft. It is checked with the core's own checks; problems come back to fix |
| `submit_review` | The worker's own notes on its draft, shown at the gate as its judgment |
| `save_source`, `read_source`, `search_source` | Research: the runner fetches a public page or PDF, keeps it under the training's `sources/`, and serves its text |
| `submit_finding` | Research: one finding with exact quotes. The runner finds each quote's place and refuses one that is not there |
| `ask_person` | Ends the job with a question. It appears on the page; the answer goes into the brief when the step runs again |

`save_source` fetches only public `http` and `https` addresses, refuses private and local ones, and caps the size.

## 4. Agents

Two adapters behind one interface: start a job with a brief, a folder, a profile and limits; stream what the worker is doing; return the outcome and the cost. A third, scripted adapter drives the worker tools from Python for tests.

Use the modes milestone 0 arrived at, with no built-in tools at all:

- **Claude:** `claude -p --restricted --strict-mcp-config --mcp-config … --permission-prompts none --tools ""`, the runner's tools allowed, the search tool added for research, no session kept, a spending limit, events as JSON. The brief's guidance goes in the appended system prompt and the job in standard input. Environment variables that belong to another Claude session are not passed on.
- **Codex:** `codex exec --json --sandbox workspace-write --ignore-user-config --ignore-rules --skip-git-repo-check --ephemeral`, with the features milestone 0 lists switched off including the shell, the web tool `disabled` or, for research, `live`, and the runner's server marked as approved.
- Each worker gets a temporary folder of its own.
- Before a run starts, and on the status screen, the adapter says whether its agent is installed, signed in and reachable now.

## 5. The pipelines

**Training, to the blueprint.**

| Stage | Steps |
| --- | --- |
| Intake | The page's form becomes `intake.md` and the training's settings. Approved as the person's own answers |
| Research plan | A worker drafts the questions. Checked. Gate 1 |
| Research | The research pipeline below. Gate 2 |
| Blueprint | One worker per level drafts a blueprint. Linted. Gate 3, once per level |

After gate 3 the training waits with a sentence saying the later stages are not automated yet and can be continued in a chat.

**Research.**

1. `harness-research plan` with the approved plan.
2. One worker per question, with the evidence rules, the question, and what the training is about and who it is for.
3. Each accepted finding is recorded with `harness-research record`, one at a time.
4. `harness-research status`. A question is done when it has a finding; the gate reports how many are supported, unresolved and unread, and names each unresolved one.
5. The report is saved through the core for gate 2.

Supplied documents are not in this milestone. The form offers public web research only, and the runner refuses any other choice with a sentence saying so. They come with milestone 3.

If `harness-research` is not installed, the training stops before research and says so.

**Briefs** are written for workers: each stage reference's substance without any helper command, since a worker cannot and must not run one.

## 6. The page

Built on milestone 1's page, and offered only when the runner serves it.

- **Set-up**, shown first on a computer where nothing is configured, and reachable afterwards as settings. Until the workspace is set, nothing else is offered.
  - The team's repository, by address, or a local folder; the folder inside it; the branch; when to share. These fill in Training Studio's `hub.json` the first time, and are read back from it for everyone after.
  - The agent to use by default, and its model.
  - Limits: time for a step, spend for a training, how many trainings run at once.
  - Each answer is checked as it is given, in plain words: the repository can be reached and written to, git knows who the person is, the agent is installed, signed in and reachable, the two harness skills are present. A failing check says how to put it right.
- **New training:** three short steps. The topic and who it is for; the shape, with a default for every choice; sources, the agent and the limits. Before it starts it says how many times it will ask for a decision.
- **A run:** the row of stages; what is happening now in a sentence; a short live list of what each worker is doing; what has been made; cost so far; pause, resume and stop.
- **Home and status** show running work as it happens.
- **A question from a worker** appears under "Needs you" with a box to answer in.
- A failed step says what happened, what was kept, and offers one action.

The runner is started by a person: `studio serve` prints the link in a terminal, by the rule milestone 1 set.

## 7. Tests

- The engine, from start to gate 3, with the scripted adapter and a stand-in for `harness-research`: the happy path, a refused draft that is fixed, a step that fails three times, a revise request, a skip, a worker's question, a restart in the middle of research, and a limit reached.
- The worker tools: every refusal, the quote placement, and the fetch rules without touching the network.
- The workspace: what is committed, what is ignored, the commit after each step and decision, that nothing outside the folder is ever staged, and sharing against a local bare repository including a refused push and an unreachable remote.
- The adapters: the exact command and environment each builds. Tests never start a real agent.
- Server tests for the new endpoints, with the same safety rules as milestone 1.

## Done when

- The suite passes and `validate_package.py` prints `ok`.
- A real training on a small topic runs on Claude from the form to approved blueprints, with decisions made on the page, and the workspace's history shows a commit for each step and decision.
- One step runs on Codex.
- A walk-through by someone who has not seen it is still to do; it needs a person.

## Appendix: what the page asks the runner

The engine and the screens are built separately, so this is the contract between them. The server owns it: the screens are written to it exactly, and the server implements it exactly. Everything in milestone 1's API stays as it is.

Every call needs the key. Every `POST` also needs the page's own `Origin` and a JSON body, as in milestone 1. A refusal is `{"error": "<a sentence for a person>"}` with a 4xx status.

**Is the runner here?**

- `GET /api/capabilities` → `{"runner": true, "version": "<x.y.z>"}`. The plain desk answers 404, and the page then hides everything below.

**Set-up**

- `GET /api/setup` → `{"configured": bool, "workspace": W or null, "agent": {"default": "claude" | "codex", "model": str or null}, "limits": {"step_seconds": int, "training_dollars": number, "parallel": int}}`, where `W` is `{"name", "repository" (str or null), "path", "folder", "branch", "share_when": "each-decision" | "when-asked", "shared": bool, "notice": str or null}`.
- `POST /api/setup/check` with `{"repository": str or null, "path": str or null, "folder": str or null, "branch": str or null}` → `{"ok": bool, "found": {"name", "folder", "branch", "existing": bool}, "checks": [{"what": str, "ok": bool, "fix": str or null}]}`. It changes nothing. `existing` says a Training Studio `hub.json` was found and read. The checks cover: the repository can be reached, it can be written to, git knows who the person is.
- `POST /api/setup` with `{"repository" or "path", "folder", "branch", "name", "share_when", "agent", "model", "limits"}` → the same shape as `GET /api/setup`. It sets the workspace up, writes `hub.json` if it is missing, and saves this computer's settings.
- `GET /api/agents` → `{"agents": [{"agent", "installed", "signed_in" (bool or null), "reachable" (bool or null), "version", "problem" (str or null)}]}`, looked at when asked and cached briefly.

**Starting a training**

- `POST /api/trainings` with `{"title", "topic", "audience", "purpose", "levels": [str], "brief_kind": "product" | "competitive", "time_limit": str or null, "source_scope": "public-web" | "supplied-only" | "both", "deck_target": "pptx" | "google" | null, "brand": str or null, "copies": [str], "yoodli": bool, "agent": "claude" | "codex" or null, "model": str or null}` → `{"path": str, "id": str, "gates": int}`. `gates` is how many times it will ask for a decision. The run starts at once.

**A run**

- `GET /api/run?path=…` → `{"state": "working" | "waiting" | "paused" | "stopped" | "failed" | "done", "sentence": str, "agent": str, "model": str or null, "steps": [{"id", "label", "kind": "code" | "agent" | "gate", "status": "done" | "working" | "waiting" | "failed" | "to-do", "attempts": int, "seconds": number or null, "dollars": number or null, "error": str or null}], "workers": [{"id", "label", "started_at", "lines": [str]}], "spent": {"dollars": number or null, "tokens": int or null}, "question": {"id", "text", "from": str} or null, "problem": {"what": str, "kept": str, "action": "retry" | "resume" | null, "label": str or null} or null}`.
  - `sentence` says what is happening now in plain words. `lines` are the last few things a worker did.
  - `problem` is set when a step failed for good or a limit was reached.
- `POST /api/run` with `{"path", "action": "pause" | "resume" | "stop" | "retry"}` → the same shape as `GET /api/run`.
- `POST /api/answer` with `{"path", "id", "answer"}` → the same shape as `GET /api/run`.
- `POST /api/share` with `{}` → `{"shared": bool, "notice": str or null}`.

**Milestone 1's lists gain a little.** Each item of `GET /api/trainings`, and `GET /api/training`, carries `"run": {"state", "sentence"}` or `null` for a training no run is driving. A training whose run has a question or a problem counts as needing the user.

A decision made through `POST /api/decide` wakes that training's run.
