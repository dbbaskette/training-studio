# Progressive disclosure: measured

Estimated tokens are characters divided by four, rounded up. They are a planning measure, not a tokenizer count. Budgets are in section 9.1 of the [design](superpowers/specs/2026-10-12-training-studio-core-pipeline-design.md) and are enforced by `validate_package.py` and `tests/test_disclosure.py`.

Regenerate the tables with:

```bash
python3 skills/training-studio/scripts/validate_package.py --measure
```

Measured 2026-10-12, after the guidance dry run. Per-file budgets: `SKILL.md` 1,000; any reference 1,000; any example 1,200.

| File | Estimated tokens |
| --- | ---: |
| `SKILL.md` | 952 |
| `references/gates.md` | 776 |
| `references/intake.md` | 685 |
| `references/levels.md` | 835 |
| `references/modes/pitch.md` | 438 |
| `references/modes/questionnaire.md` | 393 |
| `references/modes/roleplay.md` | 541 |
| `references/modes/tutor.md` | 454 |
| `references/privacy.md` | 317 |
| `references/profiles/yoodli.md` | 998 |
| `references/short-commands.md` | 371 |
| `references/stages/blueprint.md` | 899 |
| `references/stages/brief.md` | 836 |
| `references/stages/deck-handoff.md` | 863 |
| `references/stages/document.md` | 646 |
| `references/stages/package.md` | 701 |
| `references/stages/research-handoff.md` | 909 |
| `references/stages/research-plan.md` | 856 |
| `references/stages/scenario.md` | 971 |
| `references/workspace.md` | 948 |
| `assets/examples/blueprint.md` | 522 |
| `assets/examples/competitive-brief.md` | 720 |
| `assets/examples/document.md` | 748 |
| `assets/examples/product-brief.md` | 582 |
| `assets/examples/scenario.md` | 382 |
| `assets/examples/yoodli.md` | 1,092 |
| Whole library | 18,435 |

| Loading set | Estimated tokens | Budget |
| --- | ---: | ---: |
| `short-command` | 1,323 | 2,000 |
| `start` | 1,637 | 2,000 |
| `stage:research-plan` | 2,584 | 3,500 |
| `stage:research-handoff` | 2,637 | 3,500 |
| `stage:blueprint` | 3,149 | 3,500 |
| `stage:document` | 3,122 | 3,500 |
| `stage:brief` | 3,284 | 3,500 |
| `stage:deck-handoff` | 2,591 | 3,500 |
| `stage:package` | 2,429 | 3,500 |
| `levelled-blueprint` | 3,984 | 4,000 |
| `scenario:roleplay` | 5,712 | 6,000 |
| `scenario:pitch` | 5,609 | 6,000 |
| `scenario:tutor` | 5,625 | 6,000 |
| `scenario:questionnaire` | 5,564 | 6,000 |

A loading set is what one operation reads. `stage:<name>` is resuming at that stage and reaching its gate: the entry, the stage reference, the gates reference and the stage template. The whole library is never loaded at once.
