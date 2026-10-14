# Visual teaching in Training Studio decks

Make technical training decks explain concepts through diagrams, approved icons, and useful images. Harness Slides owns design, asset handling, compilation, and creative review. Training Studio supplies teaching requirements, presents decisions, and tracks approved inputs and outputs.

Status: in progress. Harness Slides has the design contract on `main`, unreleased (its #46 and #47). Training Studio proposes copy and visuals together at the outline gate, where the installed Harness Slides can take them (#43). Sections, assets and review are still to come.

## Evidence and intended outcome

The Kubernetes Operators 101 deck inspected on October 14 has 36 slides, 200 text nodes, 50 boxes, zero icon nodes, and zero image nodes in its saved composition. Its compiled structure has 35 connectors. Database, cloud, and Kubernetes icon searches succeed against the installed brand library. The omission already exists in the authored composition.

Training Studio makes icons optional, freezes every approved point as visible wording, and exposes no image acquisition tool to section composers. Its review asks whether existing images and icons explain something, without requiring consideration of a visual explanation. It passes selected composition guidance to workers rather than invoking the full design workflow.

Harness Slides 0.13.1 already includes design proposals and approvals, asset needs in deck plans, image commands, and creative review records. Reuse those facilities before adding new formats or commands. Check the exact compatibility of these facilities with section composition; their presence does not establish that they work together today.

Success means a learner can see the mechanism being taught. For example, a reconciliation slide shows desired state, observation, and corrective action; an architecture slide shows containment and ownership accurately. A text slide remains appropriate for a question or quotation. Neither icon counts nor layout variety alone establish success.

## Ownership

| Repository | Responsibility |
| --- | --- |
| `harness-slides-skill` | Visual proposals, design approval bindings, asset requests and resolution, compiler support, native output, creative review, reusable fixtures and guidance |
| `training-studio` | Teaching inputs, worker adapters, browser approval, orchestration, dependency checks, staleness, recovery and training coverage |
| `tanzu-brand` | Approved icon library, templates, brand tokens and brand compliance; change only if a reproducible brand interface defect is found |

Training Studio remains Python 3.11+ with standard library dependencies only. Core status and check commands remain offline. Do not embed slide design algorithms, image generation, or research logic in this repository.

## Milestone 1 Establish the integration contract

- [ ] Work from source checkouts of both repositories; inspect their local working agreements. Keep installed packages unchanged during development.
- [ ] Trace `deck contract/inspect/compile`, `design propose/status/check/respond/present`, image commands, composition compilation, native icon placement and creative review. Record which path supports each required operation and which combinations are unsupported.
- [ ] Choose one canonical Harness Slides design record for this integration. Prefer an adapter to the existing design session over a second approval model or an independently interpreted proposal in Training Studio.
- [ ] Define the boundary between required teaching meaning, approved visible copy, and presenter notes. Copy may be shortened while preparing a proposal, preserving sourced meaning and qualifications; after approval, visible wording remains fixed until the person approves a revision.
- [ ] Define the versioned handoff: slide ID, objective IDs, claim, visible copy, required qualifications, notes, proposed visual and its teaching purpose, concrete asset candidates, selected treatment, alternative considered, and rationale when direct text is appropriate. Reuse existing fields where possible.
- [ ] Define the response shape for unresolved assets, missing providers and failed design validation. A missing optional provider can lead to a revised native diagram proposal; it must not silently replace an approved visual with text.
- [ ] Add a compatibility fixture in each repository for the same handoff and refusal cases. Set the minimum compatible runtime only after the commands and schemas are implemented and released.

Acceptance: an integration test can propose and validate one architecture slide, one reconciliation slide and one justified text slide through public Harness Slides interfaces. This test establishes the chosen route before migrating the whole runner.

## Milestone 2 Plan visuals before approval

- [ ] In Harness Slides, reuse or extend the design proposal to include concrete asset candidates and a supported treatment for each teaching claim. Consider diagrams, approved icons, screenshots, charts with sourced data, supplied images, generated illustrations and direct text according to the subject.
- [x] In Training Studio, replace the text-only outline review with a combined copy and visual proposal at the existing outline gate. Show proposed visible copy, a wireframe or sufficiently concrete visual description, asset candidates, important caveats and any unresolved needs.
- [x] Keep one outline decision for the person. Record that decision against the exact copy and design revision in Harness Slides, through an adapter that accepts actual page decisions rather than simulated worker approval.
- [x] Separate learning requirements from verbatim slide copy during drafting. Preserve objective coverage and source qualifications while moving explanation into notes where the visible diagram remains understandable by itself.
- [ ] Carry the approved design and selected assets into every section brief. Retain the deck direction and shared concept-to-icon mapping across sections.
- [ ] Remove wording that makes visuals an afterthought. Keep relevance requirements and the freedom to choose direct text when it best teaches the claim.

Likely Training Studio files: `runner/briefs/deck-outline.md`, `runner/briefs/deck-section.md`, `runner/deck.py`, `runner/pipeline.py`, `runner/engine.py`, `runner/slides.py`, the outline review controls and their server handlers.

Acceptance: the outline review visibly proposes a Kubernetes architecture treatment and a reconciliation treatment. Approval binds both copy and design. Workers cannot substitute a different teaching concept without returning for revision.

## Milestone 3 Give composers usable assets

- [ ] Add only the Harness Slides capabilities missing from milestone 1. Prefer existing composition primitives when they can realize the approved design; do not migrate to a different compiler merely to obtain a new schema.
- [ ] Resolve and record relevant approved icons before section authoring. Share stable IDs for recurring concepts; retain icon search for refinements. Repeated actors in a diagram may reuse their identifying icon when that improves comprehension.
- [ ] Add narrowly scoped worker tools for listing approved assets and requesting or resolving assets through Harness Slides. Keep provider execution, file handling, provenance and generated-image metadata in Harness Slides.
- [ ] Make assets usable from compilation and preview directories through stable asset identifiers and managed paths. Preserve alt text, source or generation provenance, hashes and any applicable usage restrictions.
- [ ] Reuse Harness Slides' existing provider configuration and setup reporting. Do not invent a second credential store in Training Studio. Report missing configuration with the affected asset request.
- [ ] Include asset files and their hashes in the section and deck input fingerprints. Fail with a clear missing-asset response when a required approved asset cannot be resolved.
- [ ] Verify native icon geometry and editable diagram objects survive both PPTX and Google delivery. Raster illustrations remain images; record their provenance and inspect their final rendering.

Likely Training Studio files: `runner/worker_tools.py`, `runner/slides.py`, `runner/brand.py` only if its adapter needs changes, `runner/pipeline.py`, `runner/engine.py` and their targeted tests.

Acceptance: an integration fixture uses an approved icon and a supplied image, compiles them, and verifies them in native output. A separate configured acceptance run exercises generated artwork. Missing providers and missing files produce specific recoverable results.

## Milestone 4 Review whether visuals teach

- [ ] In Harness Slides, extend the creative assessment only where existing checks do not cover it: whether the treatment explains the claim, whether relationships and ownership are accurate, whether a useful asset candidate was considered, and whether the result fulfills the approved design.
- [ ] Detect a technical explanation delivered entirely as prose cards as a prompt for semantic review. The reviewer must explain the teaching defect; the mere presence of boxes or absence of icons is not a failure.
- [ ] Add report fields distinguishing asset failures, design deviations, visual teaching problems, fit defects and intentional direct-text treatments.
- [ ] In Training Studio, pass the canonical assessment to reviewers and display its actionable findings. Keep design judgments in Harness Slides and the review response, rather than implementing a second visual scorer in Python.
- [ ] Repair the affected sections when the approved concept can be preserved. A proposed change to copy, factual relationships or visual concept returns to the outline gate.
- [ ] Bind creative review to the rendered deck, approved design revision and resolved assets. Changed inputs invalidate the relevant receipts.

Acceptance: a prose-card rendering of a reconciliation mechanism receives a specific teaching finding. A clear reconciliation diagram passes that criterion. A justified direct-text knowledge check is accepted without decorative graphics.

## Milestone 5 Recovery and release

- [ ] Implement the state transitions below and named tests alongside each behavior change. Link these additions from the existing core pipeline plan and update its matrix where artifact inputs change.
- [ ] Existing approved decks stay readable and retain their approvals. Offer an explicit redesign action; do not silently rebuild them after an upgrade.
- [ ] Retain existing runtime and guidance pins for in-progress work. Adopting the new workflow is explicit and invalidates only the decisions and outputs affected by that adoption.
- [ ] Report compatibility at the Status screen before starting a deck, including missing brand export/check commands and required Harness Slides interfaces. Avoid relying on a brand listing or version number alone as proof of compatibility.
- [ ] Release Harness Slides first. Then update Training Studio's minimum Slides version, companion installer revision and wrapper tests to that verified release.
- [ ] If Training Studio guidance requires new helper behavior, bump `skills/training-studio/VERSION` and `guidance/manifest.json` minimum runtime together. Keep guidance within its current disclosure budgets and harness-neutral.
- [ ] For every changed training artifact format, update checker, tests, example and guidance together. Keep slide-specific schemas and canonical examples in Harness Slides.

## State transition matrix

These rows are implementation requirements, not new public status names. Map them to the existing state model and add new names only where necessary.

Implemented: V01, V02, V03 and V13, each a test of its name in Training Studio's `tests/test_runner_deck.py` (`DesignTests`). They map to the runner's own outline gate: "awaiting review" is `waiting` in the run record with the design's revision and question, and "approved" is `approved` holding the outline's hash and the design's hash and revision. The [milestone 4 spec](../specs/2026-10-13-milestone-4-slides.md#the-outline-gate-with-a-design) says how.

| Row | Starting condition | Event | Required result and test |
| --- | --- | --- | --- |
| V01 | Copy and visual proposal awaiting review | Person approves exact revision | Copy and design approval are recorded together; construction becomes eligible; `test_visual_01_approval_binds_copy_and_design` |
| V02 | Proposal awaiting review | Worker attempts approval | Refused; only the person's page decision can approve; `test_visual_02_worker_cannot_approve` |
| V03 | Proposal approved | Visible copy, claim or visual concept changes | Affected approval and downstream outputs become stale; proposal returns for review; `test_visual_03_design_change_requires_review` |
| V04 | Proposal approved | Layout fit repair preserves approved concept and wording | Existing design approval holds; render and assessment are regenerated; `test_visual_04_fit_repair_preserves_design` |
| V05 | Required asset unresolved | Provider unavailable or file missing | Construction waits with a specific explanation; saved work and approval remain; `test_visual_05_missing_asset_waits` |
| V06 | Waiting for asset | Correct asset is resolved | Affected work becomes runnable; no duplicate approval; `test_visual_06_asset_resolution_resumes` |
| V07 | Deck compiled or reviewed | Resolved asset content changes | Affected build and rendered review become stale; changed visual content requires design review when material; `test_visual_07_asset_change_invalidates_build` |
| V08 | Deck reviewed | Creative assessment finds a drawing defect | Affected section enters existing repair flow within its limits; `test_visual_08_drawing_finding_repairs_section` |
| V09 | Deck reviewed | Repair requires changing approved content or concept | Return to the outline review instead of silently changing it; `test_visual_09_content_change_returns_to_outline` |
| V10 | Legacy deck or pinned in-progress training | New runtime installed | Existing output, approvals and saved runtime pins remain valid; `test_visual_10_upgrade_preserves_existing_work` |
| V11 | Legacy workflow in progress | Person chooses redesign | Preserve previous artifacts; create proposal in the new workflow and invalidate affected outputs; `test_visual_11_explicit_redesign_migrates` |
| V12 | Setup reports deck capability missing | Compatible runtime installed and person checks again | Readiness refreshes; eligible waiting work resumes through existing scheduling rules; `test_visual_12_compatibility_refresh` |
| V13 | Proposal waiting for review | Person submits a decision for an older revision | Refused; current proposal and approvals remain unchanged; `test_visual_13_stale_decision_refused` |

## Verification and acceptance

Run targeted tests at each milestone. Harness Slides tests cover proposal records, compilation, assets, review and native preservation. Training Studio tests cover wrappers, worker tool permissions, approval controls, state transitions, coverage, recovery and compatibility. Its automated suite uses temporary directories and stand-ins, without network, live models or external accounts.

Run each repository's full required suite once after implementation is complete. For Training Studio also run `python3 skills/training-studio/scripts/validate_package.py`; use Python 3.11 or newer. A documentation-only edit to this plan needs a diff and link review, not the full suite.

Use disposable acceptance directories outside this repository. Copy selected approved teaching requirements from the Kubernetes Operators training for a before-and-after comparison; do not overwrite the live training. First run a four-slide vertical slice, then the complete deck after the slice succeeds.

| Acceptance example | What must be visible |
| --- | --- |
| Operator architecture | Kubernetes and workload actors identified; containment and control relationships accurate; approved icons used where they help recognition |
| Reconciliation | Desired state, observed state and corrective action visibly connected; direction and qualification supported by the teaching sources |
| Responsibility boundaries | Ownership or scope visibly separated without invented dependencies or nesting |
| Knowledge check | Readable question and choices; direct text allowed when it serves the assessment |
| Supplied screenshot or useful illustration | Correct asset, readable scale, alt text and provenance; required caveat retained |

Inspect every slide in final native PPTX and Google previews. Confirm editable diagrams, icon preservation, no missing assets, no invented claims, and objective coverage. Compare the selected examples with the original treatment and record why the new form makes the concept easier to understand. Asset counts are diagnostic, never a quota. Final visual acceptance belongs to the person reviewing the deck.

## Delivery order

1. Publish the shared interface and the three-slide contract fixture.
2. Deliver one vertical slice: proposal, page approval, approved icon, native diagram, render and creative review.
3. Add supplied images and the existing generated-image route, including missing-provider recovery.
4. Complete staleness, migration, setup compatibility and release checks.
5. Rebuild the disposable acceptance deck and review it before offering redesign of the live training.

Expected changes are two coordinated releases. Tanzu brand needs another release only if acceptance reveals an actual brand adapter defect.
