# Progressive disclosure: measured

Estimated tokens are characters divided by four, rounded up. They are a planning measure, not a tokenizer count. Budgets are in section 9.1 of the [design](superpowers/specs/2026-10-12-training-studio-core-pipeline-design.md) and are enforced by `validate_package.py` and `tests/test_disclosure.py`.

Regenerate the tables with:

```bash
python3 skills/training-studio/scripts/validate_package.py --measure
```

Measured 2026-10-12. Per-file budgets: `SKILL.md` 1,000; any reference 1,000; any example 1,200.

| File | Estimated tokens |
| --- | ---: |
| `SKILL.md` | 819 |
| `references/gates.md` | 710 |
| `references/intake.md` | 684 |
| `references/levels.md` | 717 |
| `references/modes/pitch.md` | 438 |
| `references/modes/questionnaire.md` | 393 |
| `references/modes/roleplay.md` | 541 |
| `references/modes/tutor.md` | 454 |
| `references/privacy.md` | 317 |
| `references/profiles/yoodli.md` | 917 |
| `references/short-commands.md` | 371 |
| `references/stages/blueprint.md` | 875 |
| `references/stages/brief.md` | 832 |
| `references/stages/deck-handoff.md` | 808 |
| `references/stages/document.md` | 639 |
| `references/stages/package.md` | 673 |
| `references/stages/research-handoff.md` | 889 |
| `references/stages/research-plan.md` | 721 |
| `references/stages/scenario.md` | 899 |
| `references/workspace.md` | 817 |
| `assets/examples/blueprint.md` | 522 |
| `assets/examples/competitive-brief.md` | 720 |
| `assets/examples/document.md` | 748 |
| `assets/examples/product-brief.md` | 582 |
| `assets/examples/scenario.md` | 382 |
| `assets/examples/yoodli.md` | 1,092 |
| Whole library | 17,560 |

| Loading set | Estimated tokens | Budget |
| --- | ---: | ---: |
| `short-command` | 1,190 | 2,000 |
| `start` | 1,503 | 2,000 |
| `stage:research-plan` | 2,250 | 3,500 |
| `stage:research-handoff` | 2,418 | 3,500 |
| `stage:blueprint` | 2,926 | 3,500 |
| `stage:document` | 2,916 | 3,500 |
| `stage:brief` | 3,081 | 3,500 |
| `stage:deck-handoff` | 2,337 | 3,500 |
| `stage:package` | 2,202 | 3,500 |
| `levelled-blueprint` | 3,643 | 4,000 |
| `scenario:roleplay` | 5,360 | 6,000 |
| `scenario:pitch` | 5,257 | 6,000 |
| `scenario:tutor` | 5,273 | 6,000 |
| `scenario:questionnaire` | 5,212 | 6,000 |

A loading set is what one operation reads. `stage:<name>` is resuming at that stage and reaching its gate: the entry, the stage reference, the gates reference and the stage template. The whole library is never loaded at once.
