# Milestone 2: the runner, through the blueprint

Date: 2026-10-13
Status: to build, after milestone 1
Parent: [Studio Runner design](2026-10-13-studio-runner-design.md), sections 5.1 to 5.9. Milestone 0's results, in the plan of the same date, fix the worker modes.

## Purpose

A program that takes a training from a filled-in form to approved blueprints with nobody in a chat: it drafts the research plan, runs the research, drafts each blueprint, and stops at each gate for a decision on the page.

## Scope

In: the engine, the worker tools, both agent adapters, the workspace repository, the training pipeline up to and including the blueprint gate, the research pipeline, and the page's additions: starting a training, watching a run, answering a worker's question.

Out: everything after the blueprint, slides, sharing a workspace between people, an installer.

## Where it lives

Inside this repository, under `runner/`, reusing the helper's modules in `skills/training-studio/scripts/` as its core. The parent design assumed a new repository. The page and the core both live here, and splitting them now would mean two copies. Record the change in the parent design; a split can follow later.

Python 3.11 or newer, standard library only.

## 1. The workspace

- `studio workspace init <folder>` makes the folder a git repository if it is not one, with `trainings/`, a README and an ignore file. It is remembered as this computer's workspace.
- A training is `trainings/<id>/`, created through the core's own `init`, in `page` approval mode.
- Ignored: `work/`, `sources/`, the two harness skills' guidance caches, lock files.
- The runner commits after every kept step and every decision, with a message that says what happened. It never pushes in this milestone.
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

Supplied documents chosen at intake are converted to text by the runner where it can (text, markdown, and PDF when `pdftotext` is present) and offered to workers as sources. One it cannot read is reported at the gate as a gap.

If `harness-research` is not installed, the training stops before research and says so.

**Briefs** are written for workers: each stage reference's substance without any helper command, since a worker cannot and must not run one.

## 6. The page

Built on milestone 1's page, and offered only when the runner serves it.

- **New training:** three short steps. The topic and who it is for; the shape, with a default for every choice; sources, the agent and the limits. Before it starts it says how many times it will ask for a decision.
- **A run:** the row of stages; what is happening now in a sentence; a short live list of what each worker is doing; what has been made; cost so far; pause, resume and stop.
- **Home and status** show running work as it happens.
- **A question from a worker** appears under "Needs you" with a box to answer in.
- A failed step says what happened, what was kept, and offers one action.

The runner is started by a person: `studio serve` prints the link in a terminal, by the rule milestone 1 set.

## 7. Tests

- The engine, from start to gate 3, with the scripted adapter and a stand-in for `harness-research`: the happy path, a refused draft that is fixed, a step that fails three times, a revise request, a skip, a worker's question, a restart in the middle of research, and a limit reached.
- The worker tools: every refusal, the quote placement, and the fetch rules without touching the network.
- The workspace: what is committed, what is ignored, and the commit after each step and decision.
- The adapters: the exact command and environment each builds. Tests never start a real agent.
- Server tests for the new endpoints, with the same safety rules as milestone 1.

## Done when

- The suite passes and `validate_package.py` prints `ok`.
- A real training on a small topic runs on Claude from the form to approved blueprints, with decisions made on the page, and the workspace's history shows a commit for each step and decision.
- One step runs on Codex.
- A walk-through by someone who has not seen it is still to do; it needs a person.
