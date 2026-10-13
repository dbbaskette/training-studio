# Progressive disclosure: measured

Estimated tokens are characters divided by four, rounded up. They are a planning measure, not a tokenizer count. Budgets are in section 9.1 of the [design](superpowers/specs/2026-10-12-training-studio-core-pipeline-design.md) and are enforced by `validate_package.py` and `tests/test_disclosure.py`.

Regenerate the tables with:

```bash
python3 skills/training-studio/scripts/validate_package.py --measure
```

Measured 2026-10-12. Per-file budgets: `SKILL.md` 1,000; any reference 1,000; any example 1,200.

An installed copy reads a small entry first, which finds the guidance: 306 estimated tokens against a budget of 400. A development link reads `SKILL.md` directly.

| File | Estimated tokens |
| --- | ---: |
| `SKILL.md` | 944 |
| `references/desk.md` | 417 |
| `references/gates.md` | 792 |
| `references/google.md` | 991 |
| `references/hub.md` | 927 |
| `references/intake.md` | 743 |
| `references/levels.md` | 802 |
| `references/modes/pitch.md` | 438 |
| `references/modes/questionnaire.md` | 393 |
| `references/modes/roleplay.md` | 541 |
| `references/modes/tutor.md` | 454 |
| `references/privacy.md` | 319 |
| `references/profiles/yoodli.md` | 998 |
| `references/short-commands.md` | 433 |
| `references/stages/blueprint.md` | 898 |
| `references/stages/brief.md` | 865 |
| `references/stages/deck-handoff.md` | 863 |
| `references/stages/document.md` | 700 |
| `references/stages/package.md` | 768 |
| `references/stages/research-handoff.md` | 909 |
| `references/stages/research-plan.md` | 856 |
| `references/stages/scenario.md` | 851 |
| `references/stages/yoodli.md` | 577 |
| `references/workspace.md` | 999 |
| `assets/examples/blueprint.md` | 522 |
| `assets/examples/competitive-brief.md` | 720 |
| `assets/examples/document.md` | 748 |
| `assets/examples/product-brief.md` | 582 |
| `assets/examples/scenario.md` | 382 |
| `assets/examples/yoodli.md` | 1,092 |
| Whole library | 21,524 |

| Loading set | Estimated tokens | Budget |
| --- | ---: | ---: |
| `short-command` | 1,377 | 2,000 |
| `start` | 1,687 | 2,000 |
| `google` | 1,935 | 2,000 |
| `desk` | 1,361 | 2,000 |
| `hub` | 1,871 | 2,000 |
| `stage:research-plan` | 2,592 | 3,500 |
| `stage:research-handoff` | 2,645 | 3,500 |
| `stage:blueprint` | 3,156 | 3,500 |
| `stage:document` | 3,184 | 3,500 |
| `stage:brief` | 3,321 | 3,500 |
| `stage:deck-handoff` | 2,599 | 3,500 |
| `stage:package` | 2,504 | 3,500 |
| `levelled-blueprint` | 3,958 | 4,000 |
| `scenario:roleplay` | 3,510 | 4,000 |
| `yoodli:roleplay` | 5,326 | 6,000 |
| `scenario:pitch` | 3,407 | 4,000 |
| `yoodli:pitch` | 5,223 | 6,000 |
| `scenario:tutor` | 3,423 | 4,000 |
| `yoodli:tutor` | 5,239 | 6,000 |
| `scenario:questionnaire` | 3,362 | 4,000 |
| `yoodli:questionnaire` | 5,178 | 6,000 |

A loading set is what one operation reads. `stage:<name>` is resuming at that stage and reaching its gate: the entry, the stage reference, the gates reference and the stage template. The `yoodli:<mode>` sets apply only when the optional Yoodli stage is on. The whole library is never loaded at once.
