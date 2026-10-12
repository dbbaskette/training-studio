# Training Studio: core pipeline design (phase 1)

Date: 2026-10-12
Status: revision 2, written after an external review of revision 1 and updated as phase 1 was built

## 1. Purpose

Training Studio is a skill that turns a topic into researched training material.
Given a topic, it produces:

1. a cited research report,
2. a teaching blueprint,
3. a learner guide: a document to read,
4. a brief: a reference document about the subject. It is a **competitive
   brief** when the topic compares one thing against an alternative (Valkey
   versus Redis) and a **product brief** when the topic is one technology or
   product (Greenplum),
5. a slide deck that can be both presented and distributed,
6. practice scenarios, each defined in an editable file, and optionally a Yoodli scenario
   built from each one.

A training can be produced at one or more **levels**: 101, 201, 301 and 401.
Research is done once and shared. Everything else is produced separately for
each level, in that level's own folder. A training with no levels is a single
set of outputs.

The user approves each stage before the next begins. Work is saved in a
directory the user creates for that training, and can stop and resume at any
gate.

The learner guide teaches. The brief is reference material to consult and to
give an AI as its knowledge. A scenario is practice instructions. They have
different structures and are never required to share wording.

## 2. Scope

The full ambition is a guided installer, pinned guidance, a shared Team Hub,
a Google round-trip and a browsing desk. That is five subsystems, so it is
split into phases, each with its own spec and plan. **This spec covers phase 1
only: the core pipeline as a plain, locally linked skill.** Phases 2 to 5 are
outlined in section 12.

Out of phase 1: installer and guidance sync, Google Docs round-trip, Team Hub,
the desk, listing trainings across directories, saved defaults, reusable
audience profiles, vendor profiles other than Yoodli, SCORM or LTI packaging,
video.

## 3. Decisions

| Decision | Choice | Reason |
| --- | --- | --- |
| Training purpose | Field enablement, technical upskilling or general knowledge, chosen per run | One skill serves all three |
| Brief kind | Competitive or product, chosen at intake | A comparison topic and a single-technology topic need different reference documents |
| Unit of work | Lesson or multi-module course, proposed after research and confirmed at the blueprint gate | Size depends on what the research supports |
| Levels | Optional: any of 101, 201, 301 and 401. Research is shared; blueprint, document, brief, deck and scenarios are per level | User request. Levels serve different depths and audiences, so each needs its own deliverables |
| Order across levels | All blueprints are reviewed together, then each level is finished in turn, lowest first | Overlap and gaps between levels show at the blueprint; a complete level arrives early |
| Approval gates | One per stage: research plan, research, blueprint, document, brief, deck, scenario. Stages after research repeat for each level | User preference for control over speed |
| Approval lineage | An approval covers an artifact's content and its direct inputs | A rebuild against changed inputs needs approval again; accepting an unchanged upstream artifact does not force re-approval of everything below it |
| Practice | Scenario files the user can write or edit, discovered by the skill | User requirement |
| Yoodli | An optional stage, off unless asked for, that builds a Yoodli scenario from each scenario file | A scenario file works with any AI that can play a role. Yoodli is one target, and a third-party product not every user has |
| Scenario scope | Scenarios are a list independent of modules; each exercises the objectives its success criteria map to | One scenario per module would stamp the same scenario onto every module of a course |
| Deck use | One deck that reads without a presenter and can also be presented | User request |
| Deck planning | `harness-slides` plans narrative and slide content from the blueprint and document | User preference |
| Guidance loading | Progressive disclosure with measured, enforced budgets (section 9.1) | A skill should cost context only for the step in hand; an unenforced rule erodes as guidance grows |
| Build approach | Purpose-built Python core that delegates research and decks to the harness skills | A workspace built around one draft does not fit several deliverables that each need their own approval |
| Helper language | Python 3.11+, standard library only | No dependencies to install, and it matches the tooling later phases will build on |
| Workspace | The directory the harness is launched in is the training; deliverables visible, bookkeeping hidden | The user creates one directory per topic; `harness-research` keeps one research record per project directory |

## 4. Pipeline

| # | Stage | Done by | Produces | Gate |
| --- | --- | --- | --- | --- |
| 0 | Intake | Training Studio | `intake.md`, settings | The user's answers |
| 1 | Research plan | Training Studio | Up to 30 focused questions | Questions and source scope |
| 2 | Research | `harness-research` | Cited report with named gaps | The findings |
| 3 | Blueprint | Training Studio | `blueprint.md` | Sizing, objectives, outline, practice plan |
| 4 | Document | Training Studio | `document.md` and its export | The learner guide |
| 5 | Brief | Training Studio | `competitive-brief.md` or `product-brief.md` and its export | The brief |
| 6 | Deck | `harness-slides` | Google Slides or `deck.pptx` | The deck |
| 7 | Scenario | Training Studio and the user | Scenario files | Each scenario |
| 7a | Yoodli, optional | Training Studio | A Yoodli scenario for each scenario file, and its export | Each Yoodli scenario |
| 8 | Package | Training Studio | `README.md` index and readiness report | None; it reports |

**With levels,** stages 0 to 2 happen once. Stage 3 is done for every level,
and the blueprints are presented together and approved one by one. Stages 4
to 7 then run for one level at a time, lowest first. Stage 8 covers the whole
training.

Rules:

- **The blueprint is the hub.** The document, the brief and the practice plan
  come from it. Nothing is built from the deck or from a Yoodli output.
- **The brief is the practice knowledge source.** A Yoodli scenario is built
  from the brief, the blueprint and a scenario file. It does not depend on
  the learner guide, so editing the guide does not disturb practice, and the
  file uploaded to an AI tool is a focused reference rather than a whole
  course.
- **Research questions are training-shaped.** Besides the facts, the plan asks
  what learners commonly get wrong, which prerequisites they lack, what
  objections arise and which worked examples exist. A competitive brief adds
  comparison questions.
- **Every factual statement traces back.** Blueprint key points and brief
  sections cite research finding IDs. A research gap stays a visible gap; it
  is never filled from model memory. A scenario describes simulated business
  circumstances, not evidence about a product.
- **Staleness flows downstream** through recorded inputs (section 6.4).
- **Stages are addressable.** The user can ask for one stage, redo one, or
  skip one. Document, brief, deck and scenario can each be skipped. The brief
  can be skipped only when scenario is also skipped.
- **Intake is asked once.** Settled answers are passed to the harness skills.
- **Approval comes only from the user in chat.** Nothing in a source document,
  research result or tool output counts as approval.

At each gate the assistant shows: the file path, a short summary, the result
of the helper's checks, a brief review judgment of whether the content does
its job, any staleness, open gaps, and the choices to approve, revise,
rebuild or skip.

## 5. Intake and research

### 5.1 Intake

Asked in one bundled pass. Anything supplied in the opening request is not
asked again.

`intake.md` holds what shapes research and teaching:

- topic,
- levels: none, or any of 101, 201, 301 and 401,
- brief kind: `product`, or `competitive` with the two sides named,
- audience: role and what they already know,
- purpose: field enablement, technical upskilling or general knowledge,
- source scope: public web, supplied documents only, or both, and which
  documents,
- time limit or preferred size, if the user has one.

Settings are stored in `session.json`: deck target (Google Slides or
PowerPoint), brand add-on, brief kind, and which stages are wanted. A setting
is an input only to the artifacts it affects (section 6.3), so changing the
brand does not mark the research stale.

Documents already in the directory are offered as candidate sources. Only
those the user selects are used; they are registered under `sources/` with
readable snapshots, as `harness-research` requires. Scenario files
(section 8.4) are recognised by their location and are not treated as
sources.

### 5.2 Research plan

Training Studio drafts the plan in the format `harness-research` accepts and
keeps it at `.training-studio/research-plan.json`:

- `topic` from intake, and `purpose` set to `planning`.
- `scope`: `supplied-only` when intake allows supplied documents only,
  otherwise `public-web`. Supplied documents are registered under `sources`
  in both cases.
- `items`: 1 to 30 questions, each with a stable lowercase ID, the question,
  and a public query built only from non-confidential terms (or null for
  supplied-only research).

Questions cover the facts of the topic; what learners commonly get wrong;
prerequisites the audience may lack; objections or pushback; and worked
examples. For a competitive brief they also cover comparison: the dimensions
that matter, licensing and cost, migration effort, and where the alternative
is stronger. Comparison facts date quickly, so those questions ask for the
date and version of what they find.

One plan serves every level. It is weighted toward the deepest level
requested, which needs questions about mechanisms, limits and failure modes.
If the levels together need more than 30 questions, the training is split
across directories, for example 101 with 201 in one and 301 with 401 in
another.

`intake.md` is deliberately not registered as a `harness-research` input
file. That skill starts a new, empty run whenever a registered input changes,
so a typo fix would discard live findings. Training Studio tracks that
dependency itself.

Questions are asked neutrally. One that embeds a claim can come back
contradicted, and a contradicted finding can back only a correction or a
response to an objection; where the truth is something to teach, the neutral
question that establishes it is asked as well.

`check` verifies the plan is one `harness-research` will accept: 1 to 30
questions, each with a usable ID and text, and no registered input files.

Gate 1 presents the questions as a readable list, not as JSON.

### 5.3 Research handoff

After gate 1 the assistant starts a `harness-research` task with the training
directory as its project, saves the approved plan through that skill's
helper, and follows that skill's own guidance. Training Studio records the
task ID, runtime and run with `pin`. On resume or revision it continues that
pinned task through the skill's resume entrypoint; it does not start a new
one.

Research is ready for gate 2 only after the completion checks that
`harness-research` defines.

**The approved research bundle.** Approving gate 2 records, together: the
hash of the live report `.harness-research/research-report.md`, the hash of
the record `.harness-research/research.json`, and the run ID. It copies the
report to `research-report.md` and stores the findings index (finding ID to
status) in `session.json`. The record is read only if its `schema` is 1 and
its `owner` is `harness-research`.

Research returns to `draft`, and everything built from it becomes stale, when
any of these differs from the approved bundle: the live report, the record,
or the approved copy `research-report.md`.

Training Studio does not fingerprint evidence snapshots itself. That is the
job of `harness-research`. On resume and before each later gate, the
assistant refreshes that skill's status through the pinned runtime. If it
reports stale evidence, its refreshed report changes, which Training Studio
then sees as a changed bundle.

## 6. Workspace

### 6.1 Layout

One directory is one training. The user creates a directory for the topic
(for example `valkey-training`), launches the harness there and starts the
skill. Training content never lives in the skill's own repository.

```
valkey-training/               the directory the harness was launched in
  README.md                    index, written at stage 8
  intake.md
  research-report.md           the approved report, copied at gate 2
  blueprint.md
  document.md
  document.docx                export
  competitive-brief.md         or product-brief.md
  competitive-brief.docx       export
  deck-handoff.md              one-page note given to harness-slides
  deck.pptx                    or deck-link.md for Google Slides
  scenario.md                  a scenario; its ID is "main"
  scenarios/
    exec-cost.md               further scenarios; the ID is the file name
  yoodli/
    main.md                    Yoodli scenario built from scenario.md
    main.docx                  export
    exec-cost.md
  sources/                     selected documents and readable snapshots
  .training-studio/
    session.json
    research-plan.json
    history/
    lock
  .harness-research/           owned by harness-research
  .harness-slides/             owned by harness-slides
```

The training directory is the `--project` directory for both harness skills.

**With levels,** the shared files stay at the top and each level has a folder
holding the same set of outputs:

```
valkey-training/
  README.md
  intake.md
  research-report.md
  101/
    blueprint.md
    document.md, document.docx
    product-brief.md, product-brief.docx
    deck-handoff.md, deck.pptx
    scenario.md, scenarios/, yoodli/
    .harness-slides/
  301/
    the same set
  sources/
  .training-studio/
  .harness-research/
```

Each level's deck is its own `harness-slides` task with the level's folder as
its project, because that skill keeps one workspace per project directory.
Research stays one task at the top.

A training is plain or levelled, decided at intake. Levels can be added to or
removed from a levelled training later; removing one stops tracking its
folder and leaves the files in place. A plain training cannot become
levelled, because that would mean moving approved files.

When the skill starts, it looks for `.training-studio/session.json` in the
working directory. If the record exists, the skill resumes that training and
shows its status. If not, it begins intake for a new one. `init` refuses to
run:

- when the directory already contains a file with a deliverable's name, and
  names the files;
- when the directory is, or contains, the skill's own package.

### 6.2 Session record

`session.json` is the single record for a training:

```json
{
  "schema": 1,
  "id": "valkey-for-redis-teams",
  "title": "Valkey for Redis teams",
  "levels": [],
  "level": null,
  "sizing": {"": {"size": "lesson", "modules": ["m1"]}},
  "stage": "brief",
  "next_step": "Present the brief for approval",
  "pending_question": null,
  "settings": {
    "deck_target": "pptx",
    "brand": null,
    "brief_kind": "competitive",
    "stages": ["document", "brief", "deck", "scenario"]
  },
  "unavailable": {},
  "pins": {
    "harness-research": {"task": "…", "runtime": "…", "run": "…"},
    "harness-slides": {"task": "…", "runtime": "…"}
  },
  "research": {"report_sha256": "…", "record_sha256": "…", "run": "…"},
  "findings": {"licensing": "supported", "migration-effort": "insufficient"},
  "artifacts": {
    "blueprint": {
      "file": "blueprint.md",
      "sha256": "…",
      "built_from": {"intake": "…", "research": "…"},
      "approved": {"sha256": "…", "inputs": {"intake": "…", "research": "…"},
                   "at": "2026-10-12T15:04:00Z"}
    }
  },
  "exports": {},
  "decisions": [],
  "events": []
}
```

`stage` is one of `intake`, `research-plan`, `research`, `blueprint`,
`document`, `brief`, `deck`, `scenario`, `package`, `done`. `level` is the
level being worked on, in a levelled training. Both are markers for
resuming. They never stand in for computed status or readiness. `sizing`
holds the size and modules read from each level's blueprint.

The helper validates the record's structure on every load, not only its
schema number, and refuses to write to a record it does not recognise.

### 6.3 Artifacts and inputs

| Artifact | File | Inputs |
| --- | --- | --- |
| `intake` | `intake.md` | none |
| `research-plan` | `.training-studio/research-plan.json` | `intake` |
| `research` | The research bundle (section 5.3) | `research-plan` |
| `blueprint` | `blueprint.md` | `intake`, `research` |
| `document` | `document.md` | `blueprint` |
| `brief` | `competitive-brief.md` or `product-brief.md` | `blueprint`, `research`, the brief-kind setting |
| `deck` | `deck.pptx` or `deck-link.md` | `blueprint`, `document` (or `research` when the document is skipped), the deck-target and brand settings |
| `scenario:<id>` | `scenario.md` or `scenarios/<id>.md` | none; it is an input the user owns |
| `yoodli:<id>` | `yoodli/<id>.md` | `blueprint`, `brief`, `scenario:<id>`, the Yoodli profile |

An artifact's inputs are the hashes of its upstream artifacts plus the
settings and profile revision that affect it. Changing the brand therefore
makes only the deck stale; changing the Yoodli profile makes only the Yoodli
outputs stale; editing a scenario file makes only its own Yoodli output
stale.

**Levels.** In a levelled training, every artifact from `blueprint` down
exists once per level. Its name carries the level, as in `blueprint@301` and
`yoodli:main@301`; its file sits in that level's folder; and its inputs are
the artifacts of the same level. `intake`, `research-plan` and `research`
are shared. Levels are independent in the record: nothing in one level is an
input to another, so editing the 301 blueprint leaves all 101 work as it
was.

`deck-handoff.md` and `README.md` are derived and untracked. Exports are
tracked separately (section 6.5).

**Scenario discovery.** `scenario.md` in the training directory has the ID
`main`. Each `scenarios/<id>.md` has the ID of its file name, which must be
lowercase letters, digits and hyphens. Having both `scenario.md` and
`scenarios/main.md` is refused as ambiguous. Other markdown files are never
picked up as scenarios. In a levelled training, discovery runs inside each
level's folder, and a scenario file at the top belongs to no level and is
reported as ignored. The set is computed on every read, so adding or
removing a file is seen at once. A Yoodli output whose scenario file has been
removed stays listed and shows as stale.

### 6.4 Status and approval

Status is computed on every read and never stored. In order of precedence:

1. `skipped`: the user skipped the stage.
2. `unavailable`: the stage could not run, for example no `harness-slides`.
3. `not-started`: the file does not exist.
4. `stale`: the artifact's recorded inputs differ from its current inputs, or
   an upstream artifact is itself stale.
5. `draft`: not approved in its current form (see below).
6. `approved`.

**An approval covers content and lineage.** It records the artifact's hash
and the inputs it was built from. An artifact is `approved` only when its
current hash equals the approved hash and its recorded inputs equal the
approved inputs.

- A hand edit changes the hash: the artifact is `draft` and what was built
  from it is `stale`.
- A rebuild against changed inputs changes the recorded inputs: the artifact
  is `draft` even if the rebuild produced identical bytes.
- Recording a hand edit never changes the recorded inputs, so it can never
  clear staleness.

**Accepting a stale artifact** requires the user's reason. It re-pins the
inputs, approves that content against them, and records the old inputs, the
new inputs and the reason under `decisions`. It does not approve anything
downstream. A downstream artifact stays approved only if its own direct
inputs are byte-for-byte what it was approved against. Research built from an
unchanged plan therefore stays approved when that plan is accepted as it is;
a blueprint that reads the changed intake directly does not.

`approve` refuses when any upstream artifact is neither approved nor skipped.

**When shared research changes,** for example after a top-up for a new
level, every level's blueprint and brief become stale, because both read
research directly. Accepting a level's blueprint as it is restores that
level's document and deck with no further approval, since their own inputs
are unchanged. The brief is accepted or rebuilt separately.

### 6.5 Exports

An export is a converted copy for sharing or upload: `document.docx`, the
brief's `.docx`, and each `yoodli/<id>.docx`. Exports have no approval gate,
but the helper records, for each one, the source hash it was made from, its
own hash and its path, or the reason it could not be produced.

An export is `current`, `outdated` (its source changed since), `missing`
(the file is gone or was never recorded) or `unavailable` (recorded with a
reason).

When the optional Yoodli stage is on, the Yoodli scenario names the brief's
export as the knowledge file to upload, and that export becomes required. The assistant never tells the user to upload a file that is not
`current`. If the brief's export is unavailable, the Yoodli handoff is
reported as incomplete, with what the user can do instead.

Export uses, in order: `pandoc` if on the path; otherwise the harness's own
document-creation capability; otherwise the export is recorded as
unavailable.

### 6.6 History

`history/` holds content-addressed copies of every version the helper has
seen. A save through the helper first copies the on-disk version into
history if it is not already there, then replaces the file atomically, then
records the new version. Versions that were saved or approved are always
recoverable. A hand edit that is overwritten by another hand edit before any
save is not.

### 6.7 Helper

A Python 3.11+ standard-library CLI with no network access. It checks the
Python version at start and fails with a clear message on older versions.

Files:

- `training.py`: argument parsing and command dispatch.
- `workspace.py`: record, artifact map, inputs, saves, history, status,
  approval, exports, lock.
- `checks.py`: blueprint lint, brief, scenario and Yoodli checks, coverage,
  readiness.
- `validate_package.py`: the package's own integrity.

Commands, all returning JSON:

| Command | Does |
| --- | --- |
| `init` | Creates `.training-studio/session.json`; takes the title, brief kind, deck target and brand |
| `status` | Stage, next step, pending question, every artifact's status and export state, scenarios found and files ignored |
| `save` | Records an artifact. `--from FILE` replaces it and `--built` records a file written in place; both re-pin its inputs. A plain `save` records a hand edit and keeps the earlier inputs. For the deck, also takes the reviewed coverage |
| `approve` | Records approval of the current content and lineage; refuses a stale artifact unless accepted with a reason |
| `export` | Records an export of an artifact, or that it is unavailable and why |
| `skip` | Marks a stage skipped or unavailable, or clears the mark |
| `checkpoint` | Sets stage, next step, pending question and settings |
| `pin` | Records a harness skill's task ID, runtime and run |
| `check` | Runs every check that applies and reports readiness |

**`check` reports two things.** `checks_passed` says no check that ran has
failed; a run with only a blueprint can pass. `ready` says the training is
complete: every wanted artifact exists and is approved, nothing is stale, no
applicable check failed or could not run, no export is out of date, and
every upload the outputs name has a current export or is recorded as
unavailable. `blocking` lists each reason `ready` is false.
`limitations` lists what was skipped at the user's request or could not be
produced, including an export that could not be made. A skipped stage is not
a failure. An unavailable deliverable or export is a limitation that the
package must state; it is never counted as done.
`check --complete` exits non-zero unless `ready` is true.

A question still waiting on the user blocks readiness. An artifact accepted
as it was after its inputs changed is listed under limitations with the
reason given. Scenario files that were passed over are named in a warning.
`approve` reports any checks that are failing at that moment, so an approval
is never silent about them.

Output is compact by default (section 9.1): `check` lists the checks that
did not pass and gives a count of those that did. `check --all` lists every
check.

The helper never commits to git, never calls a harness skill and never
contacts the network.

### 6.8 Robustness

- **One writer at a time.** Commands that change state take
  `.training-studio/lock`. A second command fails with a clear message
  instead of overwriting the first one's changes. A lock left by a process
  that no longer exists is taken over.
- **Readable failures.** Malformed JSON, a missing or unreadable file and a
  permission error are returned as `{"error": …}`, like any other refusal.
- **Managed paths stay inside the directory.** A managed file that is a
  symbolic link is refused.
- **No transaction journal.** Status is computed from the files, so an
  update interrupted between two files leaves a state that `status` reports
  truthfully and that rerunning the command repairs. Inputs are validated
  before anything is changed.

## 7. Blueprint

### 7.1 Contents

`blueprint.md` is built backward: outcomes first, then evidence of learning,
then content.

1. **Frame.** Audience and prior knowledge, purpose, total time, and for a
   competitive brief the two sides being compared.
2. **Sizing and reasoning.** See 7.2.
3. **Objectives `O1…`.** One observable behaviour each, with a level:
   `recall`, `explain`, `apply` or `handle` (live conversation skills).
4. **Modules `M1…`.** Each lists its objectives and duration, and contains:
   - key points `K<module>.<n>`, each citing research findings as `[R:<id>]`,
   - misconceptions, each with its correction and citation,
   - one worked example or scenario.
5. **Assessment plan.** For every objective, a knowledge-check question for
   the document and what a practice session should observe.
6. **Practice plan.** The scenarios proposed or already supplied: for each,
   its ID, mode (`roleplay`, `pitch`, `tutor` or `questionnaire`) and the
   objectives it exercises.
7. **Open gaps.** Research questions that came back unresolved, and what the
   training omits as a result.

Fragment:

```markdown
### O2 — Explain when rolling restarts are safe [explain]

## M1 — Deployment strategies (20 min)
Objectives: O1, O2
- K1.3: A rolling restart keeps capacity only if instances exceed one. [R:availability] [R:instance-min]
- K1.4: Vendor claims zero downtime for all app types. [unsupported]
Misconception: "Rolling means zero downtime." Correction: single-instance apps still drop requests. [R:instance-min]
```

### 7.2 Sizing

- **Lesson:** up to 5 objectives and up to 45 minutes. One module.
- **Course:** 2 to 6 modules of 3 to 5 objectives each.
- **Split:** a topic that needs more than 6 modules, or more than the 30
  research questions `harness-research` allows per plan, is proposed as
  separate trainings, each in its own directory.

A time limit from intake overrides the proposal. The blueprint then fits the
limit and lists what was cut.

### 7.3 Checks

`check` enforces:

- IDs are unique and well-formed.
- Every objective belongs to a module and has an assessment entry.
- Every key point cites at least one finding or is marked `[unsupported]`.
- A cited finding exists in the approved findings index and has status
  `supported`. A misconception's correction may cite a `contradicted`
  finding.
- An `[unsupported]` key point appears under open gaps.
- A practice-plan line names a known mode and known objectives.
- Module objective counts outside 3 to 5 produce a warning, not a failure.

If the findings index could not be read, the citation check reports
`unavailable`.

### 7.4 Research top-up

If the blueprint exposes a gap that matters, gate 3 offers more research. A
changed plan is a new run in `harness-research`, which starts with no
results and moves the prior run to its history. The top-up therefore keeps
the original questions unchanged, adds the new ones, re-records each prior
finding whose evidence snapshots are unchanged from the saved prior run, and
investigates only the new questions. Gate 2 is then repeated and the
blueprint rebuilt against the re-approved bundle.

### 7.5 Levels

A level is a depth tier of the same subject. Each assumes the one before.

| Level | Depth | In field enablement |
| --- | --- | --- |
| 101 | What it is, why it matters, core vocabulary. No prerequisites | Positioning and the pitch |
| 201 | How it works, common tasks, standard use cases | Discovery, qualification, demonstration |
| 301 | Architecture, tuning, troubleshooting, trade-offs | Technical deep dive; objections from engineers |
| 401 | Internals, design at scale, edge cases | Architecture workshops; competitive displacement |

Each level has its own blueprint, sized on its own (section 7.2). Its frame
states its level and what it assumes the learner already has. A level does
not re-teach what an earlier level covers; it names it as assumed.

The blueprints for all requested levels are drafted before any is approved
and are presented together, because that is where overlap and gaps between
levels can be seen.

`check` verifies that a levelled blueprint states the level of its folder,
and warns when two levels state the same objective.

## 8. Deliverables

Each has its own guidance file, loaded only when its stage runs, and an
example file that serves as both template and test fixture. In a levelled
training each level has its own set, written to that level's depth.

### 8.1 Document

The learner guide, written to stand alone as pre-read and leave-behind. A
course is one document with a chapter per module.

Structure: title, who it is for, time needed and what the reader will be
able to do; then per module an opening scenario, teaching prose organised
around the key points, the worked example, a "common mistake" callout per
misconception, a summary and a knowledge check; then the answer key,
glossary and sources.

Each section declares the objectives and key points it teaches in a
`covers` comment. `check` verifies that every objective and supported key
point is declared somewhere and that no `[unsupported]` point is. This is
**declared coverage**: it shows the section claims to teach something, not
that the prose does it well. The gate's review judgment covers that.

### 8.2 Brief

The reference document about the subject. It is consulted, not studied, and
it is the knowledge file given to an AI for practice.

**Competitive brief** (`competitive-brief.md`), in this order:

1. Executive summary
2. Comparison: the dimensions that matter, each side on each, with evidence
3. Differentiators the research supports
4. Limitations: where our side is weaker or the alternative is stronger
5. Qualification questions: how to tell whether it fits a given situation
6. Objections and responses, each response resting on evidence
7. Unknowns: what the research could not establish
8. Sources, with the date of each

**Product brief** (`product-brief.md`), in this order:

1. Executive summary
2. What it is and where it fits
3. Capabilities the research supports
4. Limitations, and when not to use it
5. Qualification questions
6. Objections and responses
7. Unknowns
8. Sources, with the date of each

Every evidence section (2 to 6) names the findings it rests on in a
`findings` comment. `check` verifies that each required section is present
and not empty, that each evidence section names at least one finding, and
that every named finding exists and is `supported`. A response to an
objection may also rest on a `contradicted` finding, since the objection's
claim was contradicted. Unknowns is never left empty: it lists what is not
known, or says that nothing was left unresolved.

A brief states weaknesses as plainly as strengths. A competitive brief that
only flatters one side fails the people who have to use it in front of a
customer.

### 8.3 Deck

Training Studio does not plan slides. It writes `deck-handoff.md`, one page
containing: goal, audience and duration; the requirement that the deck reads
without a presenter and can also be presented, so no slide depends on its
speaker notes for meaning; required elements (objectives, a check for
understanding per module, a recap, a closing pointer to practice); the
sources `blueprint.md`, `document.md` and `research-report.md`; a statement
that research is complete; and the output format and brand.

The assistant then starts a `harness-slides` task with the training
directory as its project and follows that skill's own guidance. Training
Studio records the task ID, runtime and where the deck landed.

**Coverage is a recorded review.** After the deck exists, the assistant
reads its slides and records which slides address each objective. The record
is bound to the hash of the deck and of the blueprint it was reviewed
against. If either changes, the review no longer applies and coverage is
reported as unavailable until the deck is reviewed again. Objective IDs must
exist and slide numbers must be positive integers. The helper refuses a deck file that is not a real
PowerPoint file, so a placeholder can never be recorded as the deck.

For Google Slides, the local record tracks `deck-link.md`, with the deck's
identity and the time of review. Edits made in Google after approval are not
detected in phase 1.

### 8.4 Scenarios

A scenario is a practice situation: who the learner is, who the AI plays,
how it opens, what pushback comes, and what success looks like. It is an
**input the user owns**. The user can write one before starting, edit one
the skill drafted, or add more at any time.

**Format.** A scenario file has these sections:

| Section | Required | Content |
| --- | --- | --- |
| `# Scenario: <name>` | yes | Title |
| `## Mode` | no | `roleplay` (the default), `pitch`, `tutor` or `questionnaire` |
| `## Situation` | yes | The simulated circumstances |
| `## Learner role` | yes | Who the learner is and what they are trying to do |
| `## AI role` | yes | Who the AI plays and how it behaves |
| `## Opening` | yes | The AI's first line or move |
| `## Concerns and pushback` | no | What the AI raises |
| `## Questions` | no | Questions to ask, for the modes that use them |
| `## Success criteria` | yes | A list; each item is one thing the learner should do |
| `## Constraints` | no | What the AI must not invent or assume |
| `## Session settings` | no | Duration and how the session ends |

The user never needs to know objective IDs to write one.

**Rules.**

- If no scenario file exists when the scenario stage starts, the assistant
  drafts `scenario.md` from the user's request, the blueprint's practice plan
  and the brief, and presents it at the gate with its Yoodli output.
- An existing scenario file is never overwritten with generated content. The
  assistant proposes changes and applies them only when the user agrees.
- When the user names a file elsewhere, the assistant copies it into
  `scenarios/` under a suitable ID, says so, and uses that copy.
- `check` validates the required sections before a Yoodli output is built.
- A scenario that conflicts with the blueprint or the brief is not silently
  corrected. The assistant explains the conflict and the user decides.
- Facts in a scenario's situation are fiction about the practice setting.
  Product facts the AI may use come only from the brief.

### 8.5 Yoodli scenario (optional)

This stage is off unless the user asks for it, at intake or later. While it
is off, no Yoodli artifact is listed or required, the scenario files are the
practice deliverable, and the objectives exercised are taken from the
blueprint's practice plan. Turning it on needs the brief and the scenarios;
while it is on, neither can be skipped.

`yoodli/<id>.md` is built from one scenario file, the brief, the blueprint
and the Yoodli profile. It expresses the scenario in the fields of Yoodli's
roleplay builder. It is not required to share wording with the brief.

Fields, in builder order: roleplay name, type, description, context,
personas, objections, goals, AI assets, knowledge-based goal source,
settings. Each pasteable value sits alone in a fenced block under the
heading that names its field, so it copies cleanly and the helper can count
its characters.

**Goals carry the mapping.** Each goal names the success criterion it comes
from and, where one applies, the objective it assesses, in comments outside
the pasteable blocks. `check` verifies that:

- every required field is present, every persona has all of its fields, and
  no field or heading is duplicated and no fence is left open;
- the type matches the scenario's mode, and goal types are ones Yoodli
  offers;
- every success criterion in the scenario file is carried by at least one
  goal, and no goal refers to a criterion that does not exist;
- every objective a goal names exists in the blueprint;
- every field is within its limit.

`check` reports the character count of each limited field. The counts shown
in the file are taken from that output, and `check` fails a stated count that is not the
real one.

**Objectives exercised** are reported, not enforced. A scenario the user
wrote need not touch every objective. `check` lists which objectives the
scenarios exercise between them and which they do not, and warns when a
`handle` objective is exercised by none.

Whether the scenario's context and goals are consistent with the brief is a
review judgment made at the gate and labelled as one.

**Delivery.** Building the roleplay in Yoodli's Builder, pasting field by
field, is the baseline path. Yoodli's Roleplay Agent can draft a roleplay
from uploaded files, but it cannot create new custom goals: those are
created in the Builder and then selected. The file says so, and says which
fields the agent can draft. Both paths have access prerequisites, which the
profile lists. Training Studio prepares local files only; creating or
enabling a roleplay in the service is the user's action.

The knowledge file to upload is the brief's export.

**Profile.** `assets/profiles/yoodli.json` holds Yoodli's types, goal types,
persona fields, prerequisites and limits. Each limit carries its value, the
URL it came from, the date it was collected and the date it was confirmed in
the live builder, which is empty until that happens. Limits are provisional
until confirmed. A successful paste confirms that the fields were accepted;
it says nothing about factual grounding or rubric quality.

| Limit | Value |
| --- | --- |
| Context | 10,000 characters |
| Personas per roleplay | 3 |
| Goal explanation | 2,500 characters |
| Goal achieved text | 1,000 characters |
| Goal missed text | 1,000 characters |
| Roleplay Agent inputs | 5 files and 1 public URL |

### 8.6 Package

Stage 8 writes `README.md`: title, audience, purpose, size, objectives; a
table of artifacts with status and links; the files ready to upload, taken
from export state; declared document coverage, reviewed deck coverage and
objectives exercised by the scenarios, each labelled by its basis; open
gaps; limitations; and how to use the scenario files.

In a levelled training the index has a section per level, and readiness
covers every level: one unfinished level makes `ready` false.

It runs `check --complete`. The training is described as complete only when
`ready` is true. Otherwise the report lists what is blocking.

## 9. Skill package

```
training-studio/
  README.md
  AGENTS.md
  skills/training-studio/
    SKILL.md                     the whole entry: start or resume, loading map
    references/
      short-commands.md
      levels.md
      intake.md
      gates.md
      workspace.md
      privacy.md
      stages/
        research-plan.md
        research-handoff.md
        blueprint.md
        document.md
        brief.md
        deck-handoff.md
        scenario.md
        package.md
      modes/
        roleplay.md
        pitch.md
        tutor.md
        questionnaire.md
      profiles/
        yoodli.md
    assets/
      profiles/yoodli.json
      examples/                  blueprint, document, competitive brief,
                                 product brief, scenario, Yoodli scenario
    scripts/
      training.py
      workspace.py
      checks.py
      validate_package.py
    agents/openai.yaml
  tests/
  docs/
```

The example files serve two purposes: the guidance points to them as the
template for each format, and the tests read them as fixtures. A format, its
checker and its template therefore cannot drift apart unnoticed.

Guidance uses harness-neutral language so the skill runs on Claude Code and
Codex.

### 9.1 Progressive disclosure

The skill spends context only on what the current step needs. Guidance is
layered, and each layer is read only when its condition is met.

| Layer | What | Read when | Budget |
| --- | --- | --- | --- |
| 0 | Name and description | Always; the harness holds it | 100 |
| 1 | `SKILL.md` | The skill is invoked | 1,000 |
| 2 | One stage reference | That stage is being worked | 1,000 each |
| 3 | `gates.md` | The first gate of a session is presented | 1,000 |
| 3 | `workspace.md`, `privacy.md`, `short-commands.md`, `levels.md` | Only for what each covers: an unusual workspace operation, a public search or upload, a short command, a levelled training at intake or blueprint | 1,000 each |
| 4 | One mode file; the Yoodli profile reference | The scenario stage, and only the mode in use | 1,000 each |
| 5 | One example file | That format is being written for the first time in a session | 1,200 each |
| 6 | Helper scripts | Never read. They are run, and only their output enters context | none |
| 7 | `harness-research`, `harness-slides` | Only at their own stages, through their own entrypoints | theirs |

Budgets are estimated tokens, counted as characters divided by four, the
usual planning convention. They are a planning measure, not a tokenizer
count.

Rules:

- **`SKILL.md` is the whole entry.** It decides between starting and resuming
  by itself and needs no second file to do so.
- **One hop.** Every reference and every example is linked directly from the
  loading map in `SKILL.md`, with the condition for reading it. A reference
  may mention another file, but nothing is reachable only through a chain.
- **Stage files are self-contained.** Each carries the commands its stage
  needs, so a normal stage does not load `workspace.md`.
- **Resume reads forward only.** It loads the entry and the reference for the
  current stage, and nothing for stages already finished.
- **Read once.** A file read in a session is reused, not read again.
- **A stage reads only its inputs.** The assistant opens the artifacts listed
  as that stage's inputs in section 6.3, not the whole directory.
- **Helper output is compact.** `status` returns one status per artifact.
  `check` returns the checks that did not pass and a count of those that did.
  Neither returns the session record or its event log.

Loading sets, each with a budget for the guidance newly read:

| Operation | Files | Budget |
| --- | --- | --- |
| A short command such as status or check | `SKILL.md`, `short-commands.md` | 2,000 |
| Starting a new training | `SKILL.md`, `intake.md` | 2,000 |
| Resuming at a stage and reaching its gate | `SKILL.md`, the stage reference, `gates.md`, the stage's example | 3,500 |
| The scenario stage, the heaviest | `SKILL.md`, its stage reference, one mode file, the Yoodli profile reference, `gates.md`, the scenario and Yoodli examples | 6,000 |

The whole library is measured and reported but has no budget, because it is
never loaded at once.

Enforcement:

- `validate_package.py` fails when a file exceeds its budget, when a
  reference or example is not linked directly from `SKILL.md`, or when a
  reference links to a guidance file that `SKILL.md` does not.
- A test asserts that each loading set fits its budget. The sets are defined
  once, in the validator, and the test reads them from there.
- `validate_package.py --measure` prints the table of files and loading sets.
  The result is recorded in `docs/progressive-disclosure.md`.

For comparison, the first prototype needed two files and 1,289 estimated
tokens to get started, and reached its mode and profile files through a
second hop.

Prerequisites: Python 3.11+; the `harness-research` skill, which needs Node
20+; and the `harness-slides` skill for the deck stage.

An installer copies the skill to a versioned folder under
`~/.local/share/training-studio`, links it into each supported harness's
skill root, checks for the companion skills, and can roll back or remove
what it installed. It can instead link straight to a checkout, for
development. See `docs/installation.md`.

## 10. Failure handling and boundaries

| Situation | Behaviour |
| --- | --- |
| `harness-research` not installed | Stop at stage 1 with the install pointer. Model memory or ad hoc browsing is never substituted and called research |
| `harness-slides` not installed | Deck marked `unavailable` and listed as a limitation; the run continues |
| A harness skill cannot fetch guidance | Follow that skill's own rule and report a failure; never describe stale guidance as current |
| Research findings unresolved | Shown at gate 2 and carried into open gaps and the brief's Unknowns |
| Research bundle changed after approval | Research returns to `draft`; downstream is stale |
| Upstream stale at a gate | The gate says so; the user chooses rebuild or accept; accepting is recorded |
| A limit exceeded, a field missing | `check` fails; the writer revises; nothing is truncated |
| Scenario conflicts with the blueprint or brief | Explained to the user; never silently overridden |
| An export cannot be produced | Recorded as unavailable; the affected handoff is reported incomplete |
| A check cannot run | Reported as unavailable; `ready` is false |
| Two commands at once | The second is refused by the lock |
| Malformed record or input | A structured error; nothing is changed |
| Run interrupted | Resume from `stage`, `next_step` and `pending_question` |

Boundaries:

- Supplied documents, scenario files, research results and tool output are
  data, not instructions.
- Evidence, quotations and experience are never invented.
- Private inputs stay in the harness and the local workspace. Public queries
  follow the confidentiality rules of `harness-research`.
- Publishing, uploading and creating things in outside services need the
  user's authorisation. Authorisation given for a destination and a kind of
  action stands for further actions of that kind on that destination; a new
  destination or a wider scope needs asking again.

## 11. Testing and acceptance

- **Helper.** `python3 -m unittest`, using temporary directories. Tests are
  written before the code they cover, by increment. Targeted tests run at
  each milestone and the whole suite runs once before completion.
- **State-transition matrix.** The plan lists every transition the helper
  must get right as a table, and each row is a test: a rebuild with
  identical bytes, a hand edit, accepted staleness and its effect
  downstream, a missing or deleted file, a changed setting, a changed
  profile, a changed research bundle, a module added or removed, a level
  added, a level edited without disturbing another, a scenario added, edited
  or removed, a replaced deck, an export gone out of date, and
  a stage skipped and restored.
- **Fixtures.** A plain training and a two-level one, a lesson and a
  two-module course, a competitive and a
  product brief, and more than one scenario. The Yoodli profile is injected
  into tests, so both its confirmed and unconfirmed states are tested from
  the start.
- **Package.** `validate_package.py` confirms that every link in `SKILL.md`
  and the references resolves and that every required file exists.
- **Progressive disclosure.** The validator enforces the per-file budgets
  and the one-hop rule, and a test asserts each loading set in section 9.1
  fits its budget. Live acceptance records which guidance files were read on
  one resume, to confirm the assistant loads what the map says and no more.
- **Automated verification** ends there. It needs no network, no harness
  skill and no outside account.
- **Live acceptance** is separate and needs the user: one real run on a
  small public topic through every gate on the harness the user intends to
  use, including a hand edit, a resume after an interruption, a
  user-authored scenario, and a second training in its own directory with a
  stage skipped. Supplied-only research is exercised here, since the helper
  has no scope logic of its own. Results are recorded in
  `docs/acceptance.md`.
- **Yoodli.** The user's first paste into the Builder confirms or corrects
  the profile, field by field.

## 12. Later phases

Each gets its own spec.

2. **Packaging.** Done: see `2026-10-12-phase-2-packaging.md`.
3. **Google round-trip** for the document and brief.
4. **Team Hub.** Shared trainings, research, scenarios and audience
   profiles.
5. **Training desk.** A local page for browsing and managing trainings.

## 13. Known limits

- Yoodli's field names and limits come from its public help centre and are
  provisional until confirmed in the live builder.
- Document coverage is declared and deck coverage is reviewed. Neither
  proves the content teaches well.
- Whether a Yoodli scenario is consistent with the brief is a review
  judgment.
- Remote edits to a Google Slides deck are not detected.
- A research top-up re-records prior findings; it does not carry them over
  automatically.
- A hand edit overwritten by another hand edit before any save is not in
  history.
- Each training knows only its own directory.
- All levels of a training share one research run of at most 30 questions.
- A plain training cannot be converted to a levelled one.
- A stage is skipped for every level or for none.

## Appendix A: Yoodli sources

Collected 2026-10-12 from public pages.

- Builder: https://support.yoodli.ai/en/articles/11565137-create-custom-roleplays-with-the-builder
- Builder overview: https://support.yoodli.ai/en/articles/10055659-builder
- Tutor roleplay: https://support.yoodli.ai/en/articles/16443435-building-a-tutor-roleplay-in-yoodli
- Roleplay Agent: https://support.yoodli.ai/en/articles/15960287-create-roleplays-with-roleplay-agent
- Custom goals: https://support.yoodli.ai/en/articles/11556965-creating-custom-goals
- Customising practice: https://support.yoodli.ai/en/articles/9628260-customizing-practice
- AI Assets: https://support.yoodli.ai/en/articles/16054213-add-ai-assets-to-a-roleplay
- Release notes: https://support.yoodli.ai/en/articles/9048809-yoodli-release-notes
- Programs: https://support.yoodli.ai/en/articles/15281246-adding-media-and-documents-to-a-program

## Appendix B: Disposition of the review

Revision 1 was reviewed externally before any code was written. The review's
sections are listed here with what was done about each.

| Review section | Disposition | Where |
| --- | --- | --- |
| 1 Brief and scenario are separate outputs | Adopted. Extended to a product brief for single-technology topics | 1, 4, 8.2, 8.5 |
| 1 Brief built from the learner guide | Changed. The brief is built from research and blueprint, and is the scenario's only knowledge source, to cut re-approval and keep the upload focused | 4, 6.3 |
| 2 Editable scenario file | Adopted | 8.4 |
| 2 Per-module scenario with fallback | Changed. Scenarios are a list independent of modules | 3, 6.3, 8.4 |
| 3 `check` passes with files missing | Adopted as separate `checks_passed` and `ready` | 6.7 |
| 4 Approval bound to inputs | Adopted for direct inputs | 6.4 |
| 4 Accepting upstream must not approve downstream | Declined for artifacts whose own inputs are unchanged. Re-approving them adds a gate with nothing new to look at | 6.4 |
| 5 Research bundle | Adopted: report, record, run ID and copy are pinned together | 5.3 |
| 5 Fingerprint evidence independently | Declined. It duplicates `harness-research`; its status is refreshed instead | 5.3 |
| 6 Deck review bound to the deck | Adopted | 8.3 |
| 7 Export readiness | Adopted | 6.5 |
| 8 Yoodli delivery assumptions | Adopted | 8.5 |
| 9 Stronger checks, honest labels | Adopted | 8.1, 8.5 |
| 10 Settings and profile as inputs | Adopted | 6.3 |
| 11 Lock, structured errors, path checks | Adopted | 6.8 |
| 11 Recovery record for multi-file updates | Declined. Status is computed from files, so an interrupted update is visible and repaired by rerunning | 6.8 |
| 12 Plan structure and cadence | Adopted: four increments, contracts in place of embedded code, a state-transition matrix | Plan |
| 12 Supplied-only research unit tests | Moved to live acceptance; the helper has no scope logic | 11 |
| 12 `.gitignore` for Python caches | Already present. `init` now refuses to run inside the skill's package | 6.1 |

## Appendix C: Changes after the guidance dry run

After implementation, an independent agent followed the skill end to end
using only the guidance, with stand-ins for research and the deck. It
finished both levels of a two-level training and reported 18 findings. The
resulting changes: each level's deck is its own `harness-slides` task; a
placeholder cannot be recorded as the deck; the research plan is checked;
stated character counts are verified; a pending question blocks readiness;
accepted staleness and ignored scenario files are reported; `approve` names
failing checks; and resume duties, level-to-level checkpoints, the handling
of a user's free-form scenario and the history folder names are now stated
in the guidance. A dry run is not acceptance: the stand-ins mean research
and deck building were not exercised.
