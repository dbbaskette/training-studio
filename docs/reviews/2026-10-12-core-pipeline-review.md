# Training Studio: spec and implementation plan review

Date: 2026-10-12
Reviewed repository commit: `1b5fc03`
Disposition: revise the output model and state handling before implementation.

Reviewed documents:

- [Core pipeline spec](../superpowers/specs/2026-10-12-training-studio-core-pipeline-design.md)
- [Implementation plan](../superpowers/plans/2026-10-12-training-studio-core-pipeline.md)

The repository currently contains the spec and plan, without an implemented
skill or test suite. Findings below concern the proposed design and the Python
code embedded in the plan. Selected code blocks were extracted into a disposable
directory and exercised on Python 3.14.5. Those probes confirm specific behavior;
they are not a full implementation acceptance run.

The core choices are sensible: one directory per training, a blueprint as the
teaching hub, explicit stage approvals, separate research and slides ownership,
and a small local helper. Keep those choices. The main changes are to define the
intended outputs correctly, bind approvals and reviews to their inputs, and make
completion checks distinguish unfinished work from verified deliverables.

## 1. Required correction: competitive document and Yoodli scenario are separate outputs

**User clarification:** the generic brief is a competitive document. Yoodli is a
scenario. It should not be a field-by-field version of a generic practice brief.

The spec's section 8.3 and plan Tasks 8, 9, 13 and 14 currently define
`generic.md` as a tool-neutral roleplay/system prompt and require Yoodli to say
the same thing. That model does not match the clarified requirement.

For the Valkey versus Redis example, the competitive brief explains the
comparison and the Yoodli scenario puts the learner in a conversation with an IT
executive who has Redis applications deployed and is considering changes to
reduce costs. These have different structures and purposes.

**Recommended changes:**

- Define the generic competitive deliverable as `competitive-brief.md`, with a
  `.docx` export when available. Reserve the existing `brief.md` for intake.
- Define the competitive brief's content contract: executive summary, comparison
  dimensions, supported differentiators, limitations, qualification questions,
  objections with evidence-based responses, and sources. Unknowns remain visible.
- Treat `yoodli.md` as a separate scenario output built from the approved training
  content, competitive brief, scenario input and Yoodli profile.
- Remove the rule requiring the competitive brief and Yoodli fields to contain
  identical wording. Check factual consistency and objective alignment instead.
- For topics that are not competitive comparisons, define the appropriate
  reference deliverable explicitly; do not force every training into a vendor
  comparison. The competitive-document requirement applies directly to the
  example clarified in this review.

Suggested dependency structure for a competitive training:

```text
approved research → blueprint → learner guide
approved research + blueprint + learner guide → competitive brief
competitive brief + learner guide + blueprint + scenario input + Yoodli profile
    → Yoodli scenario
```

This preserves the distinction between teaching material, competitive reference
material, and practice instructions.

## 2. Required addition: discover an editable scenario file

The scenario must be definable in a file that the skill picks up. A persona
sketch embedded in the blueprint is insufficient for this requirement.

**Recommended contract:**

- For a lesson, discover `scenario.md` in the training directory when the Yoodli
  stage starts or resumes.
- For a course, allow `scenarios/<module-id>.md` per module. A module-specific
  file takes precedence over the training-level file; show which file was used.
- Support an explicit scenario path when the user names an existing file. Do
  not silently select unrelated Markdown files from the directory.
- If no file exists, draft one from the user's request and blueprint and present
  it with the scenario output at the existing approval gate.
- Preserve a user-authored scenario file. Propose edits rather than overwriting
  it with generated content.
- Record the scenario file and its hash as an input dependency. Editing it makes
  the corresponding Yoodli output stale, without invalidating unrelated research,
  the learner guide or competitive brief.
- Validate the required scenario sections and objective mapping before building
  the Yoodli output. Explain conflicts with the blueprint rather than silently
  overriding the user's scenario.

Example `scenario.md` content:

```markdown
# Scenario: IT executive evaluating Redis alternatives

## Situation
You are an IT executive with Redis-based applications already deployed.
You are exploring whether changes could reduce costs while preserving
the reliability and capabilities your applications require.
This is a hypothetical practice situation.

## Learner role
You are advising the executive on how to evaluate Valkey as a possible
alternative. Begin with discovery before recommending a change.

## AI role
Play the IT executive. Be cost-conscious and open to alternatives, but
skeptical of claims that ignore migration effort or operational risk.

## Opening
"We have Redis running in production. Where would you start if we wanted
to explore lower costs without putting our applications at risk?"

## Concerns and pushback
- Which applications and requirements should we examine first?
- What compatibility questions need to be resolved?
- How would we estimate the total cost, including migration and operations?
- How would we evaluate support and ownership of production incidents?
- What would a pilot, success criteria and rollback plan look like?

## Success criteria
- Discovers the current deployment and business constraints.
- Explains relevant differences using the approved competitive brief.
- Separates supported facts from assumptions and unknowns.
- Discusses total cost rather than promising an unsupported savings amount.
- Proposes a measured evaluation and an agreed next step.

## Constraints
Use the approved competitive brief and learner guide for product facts.
Do not invent compatibility guarantees, pricing or customer evidence.
If the reference material cannot answer a question, acknowledge the gap.

## Session settings
Target duration: 10 minutes.
Give feedback against the success criteria at the end.
```

The scenario describes simulated business circumstances, not evidence about
either product. Product claims still require research support. Map the success
criteria to approved objective IDs when producing the rubric.

**Plan impact:** update the artifact map, discovery/resume guidance, staleness
logic, scenario examples and tests. Replace the generic-practice checks with
competitive-document checks, and add scenario-input checks.

## 3. High priority: required files can be missing while `check` succeeds

**Location:** plan Task 11, `run_checks`, around line 2564.

With a valid blueprint but no document, deck or practice files, the proposed
helper returned `ok: true` with only the four blueprint checks. Missing Yoodli
files are never reported because the loop checks only files that exist.
Unavailable checks also do not make `ok` false.

This is useful as an incremental lint operation, but insufficient as a
completion check. Packaging could present a successful result for incomplete
work.

**Recommendation:** separate progress linting from gate/package readiness, for
example `check --stage yoodli` and `check --complete`. Report missing required
artifacts, unapproved or stale artifacts, and unavailable checks explicitly.
Return separate `checks_passed` and `ready` results. A user-requested skipped stage
should not count as a failure; an unavailable requested deliverable should be
reported as a limitation rather than silently satisfying completion.

**Acceptance:** deleting a required scenario output or document after approval
must make completion readiness false. A blueprint-only run can still pass its
own stage checks.

## 4. High priority: approval must include the input revision

**Location:** spec sections 6.3–6.4; plan Tasks 3–5, `record`, `_status`, `approve`.

Approval currently means only that the artifact's bytes match an approved hash.
`save --built` replaces its dependency pins but preserves its old approval.

**Confirmed:** after changing and approving a blueprint, an existing document
was stale. Saving the unchanged document with `--built` made it `approved`
without another approval. Also, accepting an unchanged research plan after a
brief edit restored the existing research to `approved` automatically. The
blueprint stayed stale because it separately depends on the brief.

**Recommendation:** bind approval to the artifact hash and a digest of its
dependency revisions. A rebuild or accepted change of input lineage should
require approval for that new lineage, even when output bytes are identical.
Accepting one stale artifact should not silently accept its dependents. Record
the input revisions and reason in the decision history.

Use a consistent dependency fingerprint that can include file content,
scenario inputs, relevant settings, research run identity and profile version.

**Acceptance:** an unchanged-byte rebuild returns to draft; accepting stale
research-plan content does not implicitly approve its downstream research.

## 5. High priority: pin the research record and approved copy together

**Location:** spec section 5.3; plan Tasks 4–5, `research_findings` and `approve`.

The spec says divergence between the live and approved research reports returns
research to draft. The proposed implementation hashes only the live report.
Editing `research-report.md`, which downstream work reads, left research
`approved` in a probe.

The findings index is also imported separately from `research.json`, without
binding it to the report hash, pinned run or evidence state. Training Studio's
status does not independently detect changed source snapshots before the
research helper refreshes its report.

**Recommendation:** define an approved research bundle: report hash, findings
record hash, run ID, selected-source/evidence fingerprint and refreshed research
status. Verify report-copy integrity and record ownership/schema at approval.
Refresh research currency at resume and downstream gates through the pinned
harness helper. Never treat a cached `supported` status as proof that changed
evidence remains valid.

**Acceptance:** altered approved copies, mismatched run IDs and stale evidence
are visible before downstream work can be approved.

## 6. High priority: invalidate a deck review when its basis changes

**Location:** plan Tasks 3 and 10, `save` and `deck_coverage`.

`reviewed_coverage` survives replacement of the deck. A probe replaced an
approved deck with different bytes and retained passing coverage from the old
deck.

**Recommendation:** record coverage with the reviewed deck hash, blueprint
revision, review time and basis. Clear it or report it unavailable when the deck
or relevant blueprint changes. Validate objective IDs and positive integer slide
numbers. Keep the stated phase-1 limitation for undetected remote Google edits,
but record the remote deck identity and review time.

**Acceptance:** replacing `deck.pptx` requires a fresh coverage review.

## 7. High priority: track export readiness separately from source approval

**Location:** spec sections 6.3, 8.1 and 8.3; plan document/Yoodli guidance.

`.docx` exports are untracked, yet the practice instructions require
`document.docx` as the knowledge source. Markdown-only completion is allowed.
This leaves no reliable way to distinguish a current export, an old export,
and an export that was never produced.

**Recommendation:** exports need not have separate human approval gates, but
record their source fingerprint, output hash, format and availability. Regenerate
after source approval and verify that the attached knowledge file corresponds
to that approved content. If DOCX export is unavailable, identify a supported
alternative or mark the Yoodli handoff incomplete; do not instruct the user to
upload a missing file.

Apply the same rule to the new competitive-brief export. Avoid using an entire
large course document where a focused module reference would be sufficient.

**Acceptance:** changing the guide or competitive brief invalidates its export
readiness, and the package identifies the exact files ready for upload.

## 8. Correct the Yoodli delivery assumptions

**Location:** spec section 8.3; plan Tasks 9, 14 and 17.

Current Yoodli documentation says Roleplay Agent cannot create new custom goals;
those must be created in the Builder and then selected. Roleplay Agent also
requires appropriate organization access and the Conversational Roleplay
feature. The proposed two-file handoff should not imply that uploading the
scenario and guide guarantees creation of the specified custom rubric.
[Source: Roleplay Agent documentation](https://support.yoodli.ai/en/articles/15960287-create-roleplays-with-roleplay-agent).

**Recommendation:** make manual Builder assembly the baseline path. For the
Agent path, explain which fields it can create, require creation/selection of
custom goals, and compare the result against the authored scenario. Add feature
and role prerequisites to the profile. Distinguish preparing local files from
creating or enabling a roleplay in the service.

Strict mode uses more capacity, and AI Assets capacity depends on content size.
A full course guide may need a smaller module reference. This is separate from
Roleplay Agent's five-file input limit.
[Source: AI Assets documentation](https://support.yoodli.ai/en/articles/16054213-add-ai-assets-to-a-roleplay).

Store source URLs and verification dates per capability/limit, with a separate
live verification date. The public pages inspected during this review did not
reconfirm all numerical character limits in the proposed profile; retain them
as provisional until verified. Passing a paste test proves field acceptance,
not factual grounding or rubric quality.

## 9. Strengthen checks without overstating what they prove

**Location:** plan Tasks 7–10.

**Confirmed:** a document containing only a coverage comment passed document
coverage. A Yoodli persona with only a Name passed its checker despite missing
Role, Demeanor, Background and Behaviors.

Coverage comments establish declared coverage, not that the prose teaches an
objective or that a rubric assesses it well.

**Recommendation:** label comment-based results as declared coverage and add a
brief factual/pedagogical review at each content gate. Mechanically validate
persona fields, duplicate fields/headings, unterminated fences, allowed goal
types, objective references and the chosen scenario mode. Check that the Yoodli
scenario uses the approved reference material and preserves the scenario's
success criteria. Do not require its prose to match the competitive brief.

For each objective, review whether the assessment asks for the intended behavior.
Explaining a procedure is not sufficient evidence that a learner can perform
it. Describe conversational simulations of technical application accurately.

## 10. Include delivery settings and profile versions in dependencies

**Location:** spec section 5.1; plan Task 6, `checkpoint`.

Changing branding left an existing deck `approved` in a probe. Settings are
properly separate from research inputs, but are absent from deliverable
dependencies. Yoodli profile changes likewise lack a stored build fingerprint.

**Recommendation:** changes to branding/deck target invalidate only the affected
deck and handoff; changes to scenario mode or session settings invalidate the
scenario output; Yoodli profile changes invalidate affected mappings/checks.
Validate readiness when stages are restored. Do not let `stage: done` override
computed readiness after later edits.

## 11. Make local state changes recoverable and failures readable

**Location:** plan Tasks 2–6 and 11.

Atomic replacement of one file does not make artifact, report-copy and session
updates a single transaction. Concurrent commands can overwrite each other's
session changes. The CLI catches only `WorkspaceError`, so malformed JSON and
some filesystem failures escape the promised JSON response contract.

**Recommendation:** define a single-writer rule and enforce it with a workspace
lock. Validate input data before mutation; retain a small recovery record for
multi-file updates. Validate session structure beyond its schema number. Convert
expected parse, missing-file and permission failures into structured errors.
Refuse managed paths that escape the project through symlinks. Keep this small
and standard-library based; a database is unnecessary for phase 1.

**Acceptance:** interrupted writes are recoverable, concurrent writes cannot
silently lose decisions, and malformed state returns a useful error.

## 12. Simplify and strengthen the implementation plan

The 4,412-line plan embeds nearly the complete implementation and mandates
repeated red/green full-suite runs. Its happy-path fixtures are useful, but the
plan's successful test counts do not cover the failures demonstrated above.

Recommended plan changes:

1. Replace mandatory strict TDD and full-suite runs after every task with the
   user's agreed cadence: coherent functional increments, targeted checks at
   milestones, one full relevant suite before completion. Read the local CI
   reference and project CI instructions before selecting the full runner.
2. Organize work into four increments: artifact/state contracts; competitive
   brief and scenario checks; harness/guidance integration; packaging and
   acceptance. Keep exact code samples only where they clarify a contract.
3. Add a state-transition matrix covering rebuilds with identical bytes,
   accepted staleness, missing/deleted files, changed settings/profile,
   module additions/removals, and reactivated stages.
4. Add synthetic course fixtures and supplied-only research tests. Include
   scenario discovery, user-file preservation, per-module selection and scenario
   edits in the regression suite.
5. Parameterize the live-profile verification flag in tests. Task 17 currently
   anticipates an `IndexError` and instructs the implementer to rewrite an
   assertion after live verification. Test both states from the outset.
6. Add `.gitignore` for Python caches and disposable training bookkeeping, and
   verify that acceptance work cannot overwrite the skill repository.
7. Use the pinned research/slides task on resume or revision. State clearly that
   a harness skill task is its guidance/runtime record, not an automatically
   created new Codex chat.
8. Make installation and acceptance instructions host-aware. The plan currently
   uses Claude-only commands in Task 17 although the active host is Codex.
   Keep user-dependent live acceptance separate from automated verification.
9. Remove environment-specific claims that git writes always need a disabled
   sandbox. Follow the actual host permissions. Preserve already granted upload
   or editing authority rather than requiring fresh consent for every related
   action; seek new approval for new scope or destinations.

## Suggested revision order

1. Update spec purpose, pipeline, workspace layout and section 8.3 to separate
   the competitive brief from the scenario and add the scenario-file contract.
2. Update artifact dependencies and approval fingerprints before implementing
   storage/status code.
3. Define stage readiness, research-bundle integrity, export readiness and deck
   review invalidation, with explicit acceptance cases.
4. Rewrite the affected plan tasks and examples around those contracts.
5. Implement and verify local behavior, then perform the user-dependent Yoodli
   acceptance run on the intended host.

The recommended changes fit phase 1. They do not require the installer, Team
Hub, Google round-trip or training desk planned for later phases.

## Probe evidence

These results came from the proposed Python code extracted from the plan,
using disposable local fixtures and no network or third-party account access:

| Probe | Observed result |
| --- | --- |
| Valid blueprint; document, deck and practice files absent | `check` returned `ok: true` |
| Edit the approved `research-report.md` copy | Research stayed `approved` |
| Edit brief, approve it, accept unchanged stale research plan | Existing research returned to `approved` |
| Change blueprint, approve it, save unchanged document with `--built` | Document changed from `stale` to `approved` without approval |
| Replace deck after recording coverage | Old coverage still returned `passed` |
| Change deck brand setting | Deck stayed `approved` |
| Inspect artifact status | DOCX exports were absent |
| Yoodli persona contains only Name | Checker returned `passed` |
| Document contains only a complete coverage comment | Coverage returned `passed` |

The spec and implementation plan were left unchanged by this review.
