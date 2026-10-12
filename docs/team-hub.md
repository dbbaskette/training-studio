# Team hub

A hub lets a team share finished trainings and reuse each other's scenarios, audience descriptions and research. It is a private git repository that your team already controls. Training Studio adds nothing hosted: there is no service, no account and no token to hand over.

## What you need

- `git`, signed in to wherever your team keeps repositories. If `git clone` works for the hub's address in a terminal without asking for a password, Training Studio can use it.
- One private repository for the hub. Someone on the team creates it, empty, on your usual git host. Who can read and write it is decided there.

## Setting it up

The first person tells their assistant the repository is new:

> Join our team hub at `<the repository's address>`. It is a new, empty repository, so set it up.

Everyone else:

> Join the team hub at `<the repository's address>`.

The hub is copied to your computer, under `~/.local/share/training-studio/hubs/`. You can join more than one. If you do, say which one a training should publish to.

## Publishing a training

> Publish this training to the team hub.

Your assistant tells you what will be published and asks before it does. Once you have said yes for a hub, it does not ask again each time you publish to that same hub.

Each publish is a numbered revision. A revision is never changed afterwards. If you improve the training, publish again and it becomes the next revision.

**What is published.** Only what you have approved: the blueprint, the learner guide, the brief, the deck or the link to it, your scenarios, Yoodli scenarios if you made them, the Word copies that are up to date, the approved research report, and the training's `README.md`.

**What is never published.** The documents you supplied under `sources/`, the bookkeeping folders (`.training-studio/`, `.harness-research/`, `.harness-slides/`), your intake notes, and anything you have not approved. A draft or out-of-date file stays behind, and you are told which files were left out and why.

A training does not have to be complete to be published. The revision records whether it was ready at the time.

## Reusing what the team shared

> What is in the hub about rolling restarts?

Your assistant brings your copy up to date and searches titles, IDs and text. Then you can ask for:

- **A scenario.** "Use the zero-downtime scenario from the hub." It is copied into your training as a scenario file you own and can edit. It never replaces a scenario you already have.
- **An audience description.** "Use the platform leads audience from the hub." It is offered to you when the training starts, and you can change it.
- **Research.** "Use the research from the rolling restarts training." The published report is copied into your `sources/` folder as a document you supplied. Your new training still does its own research; the report is checked like any other source, and nothing in it counts as established until then.

You can also read a teammate's whole training. It is in the hub's folder on your computer, and on your git host.

To share one scenario or one audience description without publishing a training:

> Share this scenario to the hub.

> Share this audience description to the hub as "platform-leads".

Only an approved scenario can be shared. Nothing already in the hub is replaced: if the name is taken, you are asked for another.

## When the hub cannot be reached

If you are offline, or the host refuses the change, your work is kept on your computer and you are told plainly that it has **not** been shared. Nothing is lost. Ask your assistant to "sync the hub" later and it is sent then.

If two people publish the same training at the same moment, both are kept. The second one becomes the next revision number.

Training Studio never force-pushes and never rewrites what is already in the hub.

## What a hub looks like

```
hub.json                             marks the repository as a hub
README.md                            an index, rebuilt automatically; readable on your git host
trainings/<training>/<revision>/     one published revision
  record.json                        who published it, when, whether it was ready, and each file's hash
  blueprint.md, document.md, ...     the published files, laid out as in the training folder
scenarios/<id>.md                    a shared scenario
scenarios/<id>.json                  who shared it, when, and from which training
audiences/<id>.md                    a shared audience description
```

A training's name in the hub comes from its title: "Rolling restarts" is `rolling-restarts`. Two trainings with the same title share one history of revisions, so give different trainings different titles.

## The commands

Your assistant runs these for you. Each prints JSON.

| Command | Does |
| --- | --- |
| `hub join URL [--name NAME] [--init]` | Copies a hub to this computer. `--init` sets up a new one in an empty repository |
| `hub list` | The hubs you have joined, and whether any has changes not yet sent |
| `hub use NAME` | Chooses the hub this training publishes to |
| `hub publish [--message TEXT]` | Publishes this training's approved files as the next revision, then syncs |
| `hub status` | This training's hub, its latest revision, and what has changed since |
| `hub sync [NAME]` | Fetches what others shared, sends what is waiting, and rebuilds the index |
| `hub find [WORDS] [--kind training\|scenario\|audience]` | Searches titles, IDs and text |
| `hub get scenario ID [--as NAME] [--level LEVEL]` | Copies a scenario into this training |
| `hub share scenario ID [--as NAME] [--level LEVEL]` | Puts one of this training's scenarios into the hub |
| `hub get audience ID` | Prints an audience description |
| `hub share audience ID --file FILE` | Puts an audience description into the hub |
| `hub get research TRAINING [--revision N]` | Copies a published research report into `sources/` |

`find`, `get` and `share audience` also take `--hub NAME`, for when you have joined several hubs and are not inside a training that has chosen one.

A scenario published inside a training is fetched as `TRAINING/ID`, or `TRAINING/ID@LEVEL` for a training with levels. `hub find` shows the exact ID to use.

## Limits

- **The hub does not manage who can see what.** Anyone who can read the repository can read everything in it. Access is whatever your git host says it is.
- **Published files are copies.** Changing a training later does not change what was published. Publish again to share the change.
- **Every revision is a full copy of its files.** A hub with many revisions of large decks grows, as any git repository does.
- **Shared scenarios and audience descriptions are not updated in place.** Share the improved one under a new name, or edit the file in the repository yourself.
- **Signing in is git's job.** Training Studio never asks for or stores a password or token, and it will not wait for one. If git cannot reach the hub without prompting, fix that in git first.
- **A change you make by hand in the hub's folder** is sent on the next sync. If it clashes with a teammate's change to the same file, the sync stops and tells you where to sort it out with git.
