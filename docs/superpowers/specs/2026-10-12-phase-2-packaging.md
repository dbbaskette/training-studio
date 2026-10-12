# Training Studio phase 2: packaging

Date: 2026-10-12
Status: implemented

## Purpose

Let the guidance improve without anyone reinstalling, keep each training on the guidance it started with, and run the tests automatically. This phase also adds two small foundations the later phases build on.

## Guidance and scripts are separated

The skill has two kinds of content:

- **Guidance**: `SKILL.md`, `references/` and `assets/`. It is prose, templates and the Yoodli profile data. It can change often.
- **Scripts**: `scripts/`. They change state on the user's computer, so they are installed deliberately and never fetched.

An installed copy now has this layout:

```
~/.local/share/training-studio/versions/<version>-<hash>/
  SKILL.md        a small entry, the bootstrap
  VERSION
  source.json     where guidance is fetched from
  scripts/
  agents/
  guidance/       SKILL.md, references/, assets/ as they were when installed
```

A development link (`install --link`) points at the checkout instead, where the full `SKILL.md` is the entry and nothing is fetched.

## How a session finds its guidance

1. The assistant reads the installed entry, which tells it to run `sync_guidance.py start` in the training directory.
2. **A training that is already pinned** gets the guidance it was pinned to. This needs no network. The pinned files are verified against the hashes recorded in the pin, and rebuilt from the local cache if they were damaged.
3. **A directory with no training yet** gets the newest guidance from the repository's `main` branch. Nothing is written into the directory. When `training.py init` then creates the training, it pins that guidance.
4. The script prints the path of the guidance entry to read, the path of `training.py`, how fresh the guidance is, and a notice if it had to fall back.

The pin is `.training-studio/guidance.json`: the commit, the cache folder, a hash of every guidance file, the script version and the time.

## Compatibility

`guidance/manifest.json` at the repository root states the schema, the folder guidance lives in, and the oldest script version it works with:

```json
{"schema": 1, "content_root": "skills/training-studio", "minimum_runtime": "0.2.0"}
```

Guidance that needs newer scripts than are installed is not used. The session falls back to the installed guidance and tells the user to update the skill.

## Falling back, honestly

When the newest guidance cannot be fetched, whether the network is unavailable, `git` is missing or the manifest is not acceptable, the session uses the guidance that came with the installed scripts and says so in a `notice`: that it could not get the newest guidance, why, and that what it is using may be older. It never describes fallback guidance as current.

A training pinned while offline stays on the installed guidance until someone runs `update`.

## Moving a training to newer guidance

`sync_guidance.py update` re-pins a training to the newest guidance. It is run only when the user asks. Checks can give different results afterwards, and a changed Yoodli profile makes Yoodli scenarios stale, because the profile a training uses is the one in its pinned guidance.

## The main branch is live

New trainings fetch `main`. So `main` must always be usable: guidance that depends on a script change raises `minimum_runtime` in the same commit, and the scripts' `VERSION` is raised with it.

## Continuous integration

A GitHub Actions workflow runs the unit tests and the package validator on every pull request and on pushes to `main`, on Linux and macOS, with Python 3.11 and 3.13.

## Foundations for later phases

- **Command plug-ins.** Any `cmd_*.py` beside `training.py` can add sub-commands. It defines `register(commands)`, adds its parsers, and sets each one's `handler` default to a function taking `(args, root)` and returning the JSON to print. The Google, Hub and desk phases each add one such file and do not edit `training.py`.
- **A registry of trainings.** `home.py` records each training's directory in the per-user data folder when it is created or its status is read. `training.py list` shows them. This is what lets the Hub and the desk find trainings across directories.
- **One per-user data folder**, `~/.local/share/training-studio`, overridable with `TRAINING_STUDIO_DATA`. Tests set the override so they never touch the real one.

## What was not done

- Guidance is not signed. Its authenticity rests on fetching it from the repository over HTTPS, as with the companion skills.
- There is no automatic update of the scripts. Updating them is still: get the newer repository and run the installer.
