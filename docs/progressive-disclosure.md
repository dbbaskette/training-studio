# Progressive disclosure: measured

Estimated tokens are characters divided by four, rounded up. They are a planning measure, not a tokenizer count. Budgets are in section 9.1 of the [design](superpowers/specs/2026-10-12-training-studio-core-pipeline-design.md) and are enforced by `validate_package.py` and `tests/test_disclosure.py`.

Regenerate the tables with:

```bash
python3 skills/training-studio/scripts/validate_package.py --measure
```

Measured 2026-10-13. Per-file budgets: `SKILL.md` 1,000; any reference 1,000; any example 1,200.

An installed copy reads a small entry first, which finds the guidance: 306 estimated tokens against a budget of 400. A development link reads `SKILL.md` directly.

| File | Estimated tokens |
| --- | ---: |
| `SKILL.md` | 967 |
| `references/desk.md` | 417 |
| `references/gates.md` | 801 |
| `references/google.md` | 991 |
| `references/hub.md` | 927 |
| `references/intake.md` | 743 |
| `references/levels.md` | 802 |
| `references/modes/pitch.md` | 438 |
| `references/modes/questionnaire.md` | 393 |
| `references/modes/roleplay.md` | 541 |
| `references/modes/tutor.md` | 454 |
| `references/privacy.md` | 319 |
| `references/profiles/yoodli.md` | 997 |
| `references/short-commands.md` | 433 |
| `references/stages/blueprint.md` | 898 |
| `references/stages/brief.md` | 895 |
| `references/stages/deck-handoff.md` | 863 |
| `references/stages/document.md` | 700 |
| `references/stages/package.md` | 781 |
| `references/stages/research-handoff.md` | 939 |
| `references/stages/research-plan.md` | 888 |
| `references/stages/scenario.md` | 851 |
| `references/stages/yoodli.md` | 591 |
| `references/workspace.md` | 998 |
| `assets/examples/blueprint.md` | 522 |
| `assets/examples/competitive-brief.md` | 720 |
| `assets/examples/document.md` | 748 |
| `assets/examples/product-brief.md` | 582 |
| `assets/examples/scenario.md` | 382 |
| `assets/examples/yoodli.md` | 1,119 |
| Whole library | 21,700 |

| Loading set | Estimated tokens | Budget |
| --- | ---: | ---: |
| `short-command` | 1,400 | 2,000 |
| `start` | 1,710 | 2,000 |
| `google` | 1,958 | 2,000 |
| `desk` | 1,384 | 2,000 |
| `hub` | 1,894 | 2,000 |
| `stage:research-plan` | 2,656 | 3,500 |
| `stage:research-handoff` | 2,707 | 3,500 |
| `stage:blueprint` | 3,188 | 3,500 |
| `stage:document` | 3,216 | 3,500 |
| `stage:brief` | 3,383 | 3,500 |
| `stage:deck-handoff` | 2,631 | 3,500 |
| `stage:package` | 2,549 | 3,500 |
| `levelled-blueprint` | 3,990 | 4,000 |
| `scenario:roleplay` | 3,542 | 4,000 |
| `yoodli:roleplay` | 5,398 | 6,000 |
| `scenario:pitch` | 3,439 | 4,000 |
| `yoodli:pitch` | 5,295 | 6,000 |
| `scenario:tutor` | 3,455 | 4,000 |
| `yoodli:tutor` | 5,311 | 6,000 |
| `scenario:questionnaire` | 3,394 | 4,000 |
| `yoodli:questionnaire` | 5,250 | 6,000 |

A loading set is what one operation reads. `stage:<name>` is resuming at that stage and reaching its gate: the entry, the stage reference, the gates reference and the stage template. The `yoodli:<mode>` sets apply only when the optional Yoodli stage is on. The whole library is never loaded at once.
