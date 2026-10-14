# Progressive disclosure: measured

Estimated tokens are characters divided by four, rounded up. They are a planning measure, not a tokenizer count. Budgets are in section 9.1 of the [design](superpowers/specs/2026-10-12-training-studio-core-pipeline-design.md) and are enforced by `validate_package.py` and `tests/test_disclosure.py`.

Regenerate the tables with:

```bash
python3 skills/training-studio/scripts/validate_package.py --measure
```

Measured 2026-10-14. Per-file budgets: `SKILL.md` 1,000; any reference 1,000; any example 1,200.

An installed copy reads a small entry first, which finds the guidance: 306 estimated tokens against a budget of 400. A development link reads `SKILL.md` directly.

| File | Estimated tokens |
| --- | ---: |
| `SKILL.md` | 970 |
| `references/desk.md` | 451 |
| `references/gates.md` | 820 |
| `references/google.md` | 982 |
| `references/hub.md` | 927 |
| `references/intake.md` | 799 |
| `references/levels.md` | 756 |
| `references/modes/pitch.md` | 438 |
| `references/modes/questionnaire.md` | 393 |
| `references/modes/roleplay.md` | 541 |
| `references/modes/tutor.md` | 454 |
| `references/privacy.md` | 319 |
| `references/profiles/yoodli.md` | 997 |
| `references/short-commands.md` | 392 |
| `references/stages/blueprint.md` | 861 |
| `references/stages/brief.md` | 815 |
| `references/stages/deck-handoff.md` | 840 |
| `references/stages/document.md` | 596 |
| `references/stages/package.md` | 738 |
| `references/stages/research-handoff.md` | 899 |
| `references/stages/research-plan.md` | 866 |
| `references/stages/scenario.md` | 778 |
| `references/stages/yoodli.md` | 563 |
| `references/workspace.md` | 998 |
| `assets/examples/blueprint.md` | 522 |
| `assets/examples/competitive-brief.md` | 720 |
| `assets/examples/document.md` | 748 |
| `assets/examples/product-brief.md` | 582 |
| `assets/examples/scenario.md` | 382 |
| `assets/examples/yoodli.md` | 1,119 |
| Whole library | 21,266 |

| Loading set | Estimated tokens | Budget |
| --- | ---: | ---: |
| `short-command` | 1,362 | 2,000 |
| `start` | 1,769 | 2,000 |
| `google` | 1,952 | 2,000 |
| `desk` | 1,421 | 2,000 |
| `hub` | 1,897 | 2,000 |
| `stage:research-plan` | 2,656 | 3,500 |
| `stage:research-handoff` | 2,689 | 3,500 |
| `stage:blueprint` | 3,173 | 3,500 |
| `stage:document` | 3,134 | 3,500 |
| `stage:brief` | 3,325 | 3,500 |
| `stage:deck-handoff` | 2,630 | 3,500 |
| `stage:package` | 2,528 | 3,500 |
| `levelled-blueprint` | 3,929 | 4,000 |
| `scenario:roleplay` | 3,491 | 4,000 |
| `yoodli:roleplay` | 5,392 | 6,000 |
| `scenario:pitch` | 3,388 | 4,000 |
| `yoodli:pitch` | 5,289 | 6,000 |
| `scenario:tutor` | 3,404 | 4,000 |
| `yoodli:tutor` | 5,305 | 6,000 |
| `scenario:questionnaire` | 3,343 | 4,000 |
| `yoodli:questionnaire` | 5,244 | 6,000 |

A loading set is what one operation reads. `stage:<name>` is resuming at that stage and reaching its gate: the entry, the stage reference, the gates reference and the stage template. The `yoodli:<mode>` sets apply only when the optional Yoodli stage is on. The whole library is never loaded at once.

When a training's gates are decided on the page, the assistant also reads the desk reference once in a session, on top of the stage's loading set. No loading set measures that sum.
