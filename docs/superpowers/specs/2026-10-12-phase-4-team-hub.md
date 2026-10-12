# Training Studio phase 4: Team Hub

Date: 2026-10-12
Status: implemented

## Purpose

Let a team share finished trainings and reuse each other's scenarios, audience descriptions and research, through a private git repository they already control.

## Scope

In: joining a hub, publishing a training's approved deliverables, finding and reusing scenarios, audiences and research, keeping the local copy in step with the remote.

Out: creating the remote repository (the user does that, or gives the go-ahead for it), permissions (they are the repository's), editing a published training in the hub, any hosted service.

## Files

| File | Responsibility |
| --- | --- |
| `skills/training-studio/scripts/hub.py` | The hub store: layout, publish, find, get, share, sync. No argument parsing |
| `skills/training-studio/scripts/cmd_hub.py` | The command plug-in |
| `skills/training-studio/references/hub.md` | Guidance for the assistant, within 1,000 estimated tokens |
| `tests/test_hub.py` | Tests against local bare repositories. No network |
| `docs/team-hub.md` | A page for users, linked from the README |

## What a hub is

A git repository. Locally it is cloned to `<data root>/hubs/<name>/`, where the data root comes from `home.data_root()`. Joined hubs are listed in `<data root>/hubs.json`. A training remembers which hub it publishes to in `.training-studio/hub.json`.

Layout of the repository:

```
hub.json                               {"schema": 1, "name": "…"}
README.md                              generated index, readable on the host
trainings/<training-id>/<revision>/    one published snapshot
  record.json
  …the published files, in their training layout
scenarios/<id>.md                      reusable scenario files
scenarios/<id>.json                    who shared it, when, from which training
audiences/<id>.md                      reusable audience descriptions
```

A revision is a positive integer. A published revision is never changed; publishing again makes the next one.

## What publishing includes

Only artifacts whose status is `approved`, read through `workspace.statuses`. For each level, or once for a plain training:

- the blueprint, document, brief, scenario files and Yoodli scenarios,
- current exports of those,
- the deck file, or its link file,
- the approved research report `research-report.md`, and the training's `README.md` if present.

Never published: `sources/` (documents the user supplied), anything under `.training-studio/`, `.harness-research/` or `.harness-slides/`, and any artifact that is not approved.

`record.json` holds the title, levels, who published (git `user.name`), when, whether `check` reported the training ready, the guidance commit it was built with, and for each file its artifact name, path and SHA-256. The result of `publish` lists what was published and what was left out and why.

Publishing refuses when nothing is approved.

## Commands

All print JSON and refuse with `{"error": …}`.

| Command | Does |
| --- | --- |
| `hub join URL [--name NAME]` | Clone a hub and remember it. Refuses a repository with no `hub.json` unless `--init` creates the layout in an empty one |
| `hub list` | Joined hubs, and for each whether there are changes not yet pushed |
| `hub use NAME` | Make a joined hub the one this training publishes to |
| `hub publish [--message M]` | Publish this training's approved deliverables as the next revision, then sync |
| `hub status` | For this training: its hub, its latest published revision, and whether anything approved has changed since |
| `hub sync [NAME]` | Fetch, rebase local commits, push. Regenerates the index |
| `hub find [QUERY] [--kind training\|scenario\|audience]` | Search titles, IDs and text |
| `hub get scenario ID [--as NAME] [--level L]` | Copy a hub scenario into this training's scenario files. Never overwrites an existing file |
| `hub share scenario ID` | Put one of this training's scenario files into the hub |
| `hub get audience ID` | Print an audience description, for intake |
| `hub share audience ID --file FILE` | Put an audience description into the hub |
| `hub get research TRAINING [--revision N]` | Copy a published research report into this training's `sources/` as a supplied document |

## Sync

- Uses the `git` command line and the user's own git identity and credentials. No tokens are handled.
- Never force-pushes and never rewrites published history.
- `sync` commits pending changes, fetches, rebases onto the remote, and pushes. `README.md` is generated, so after a rebase it is regenerated, not merged by hand.
- If the remote cannot be reached, the changes stay committed locally, the command says they are not pushed yet, and a later `sync` sends them. Nothing is lost and nothing is reported as shared when it was not.
- Two people publishing the same training at once get consecutive revisions: the second one's revision number is re-chosen after the rebase.

## Boundaries

- A hub holds a team's material. Publishing or sharing into one needs the user's go-ahead, which then covers later publishes to the same hub. The guidance must say so.
- A scenario or audience taken from a hub is data, not instructions.
- Text taken from a hub's research report is a supplied source and goes through `harness-research` like any other; it is not treated as verified findings for the new training.

## Known limits to state in the docs

- The hub does not manage who can see what. That is the repository's access control.
- Published files are copies. Changing a training later does not change what was published; publish again to share the change.

## Deviations

What was built differs from the text above in these ways. Each is an addition the commands needed, not a change of intent.

- **`hub share scenario` also takes `--as NAME` and `--level L`.** Every training's first scenario is called `main`, and a levelled training has one per level, so sharing needs a way to say which file and what to call it. Without `--as`, a scenario keeps its ID, and `main` is named after its training, for example `rolling-restarts` or `rolling-restarts-101`.
- **`hub get scenario` also accepts `TRAINING/ID` and `TRAINING/ID@LEVEL`.** That takes a scenario straight from the latest published revision of a training. `hub find --kind scenario` lists these beside the ones under `scenarios/`.
- **`--hub NAME` on `find`, `get` and `share audience`.** These can run before a training exists, where `hub use` has nothing to record. When exactly one hub is joined it is used without `hub use`, and a publish or share remembers it for the training.
- **Publishing with nothing changed makes no new revision.** It reports the latest revision and syncs. A change in readiness alone does make one, because the record states it.
- **Nothing shared is replaced.** Sharing a scenario or audience under an ID that is taken is refused unless the text is identical. When two people share one ID at once, the first stays and the second is told theirs was not added.
- **`--init` needs a repository with no commits at all**, so a hub's layout never lands on top of someone's files.
- **Results say `created`, `added`, `pushed` and `reached`,** never "shared" or "published" for work that is only on this computer. `pushed` is true only when nothing in the local copy is missing from the remote.
- **A conflict the commands do not understand stops the sync.** That can only come from editing the local copy by hand. The rebase is undone, nothing is pushed, and the message names the file and the folder to settle it in.
- **Symbolic links are never followed,** in a training when publishing or in a hub's local copy when reading or writing, because a hub holds other people's files. An address that carries a password or token is refused.
- **`hub get research` needs a training in the directory,** and names its copy `sources/<training>-research-report-r<revision>.md`. An existing file is never overwritten.
