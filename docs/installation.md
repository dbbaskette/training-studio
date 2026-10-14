# Installation

The installer puts a copy of Training Studio on your computer: the skill your assistant uses, and the [runner](runner.md), the program that makes a training from a page in your browser. It links the skill into your assistant's skill folder, gives you a way to open the runner, and offers to bring the two companion skills. It needs Python 3.11 or newer.

## Install

From a terminal, inside this repository:

```bash
sh installer/install.sh
```

On a Mac you can instead double-click `Install Training Studio.command` in the `installer` folder.

It tells you what it is about to do and asks before changing anything. It then asks about each companion skill separately. When it finishes it lists where the skill was linked, how to open Training Studio, and anything you still need.

## What it does

1. Checks that the skill package is whole.
2. Copies it, and the runner with it, to `~/.local/share/training-studio/versions/<version>`.
3. Runs the copy's own checks, and starts the copied runner far enough to see that it loads.
4. Points `~/.local/share/training-studio/current` at that copy.
5. Links the skill into each assistant it finds:
   - Claude Code: `~/.claude/skills/training-studio`
   - Codex: `~/.agents/skills/training-studio`
6. Writes the ways to open the runner. See [Open Training Studio](#open-training-studio).
7. Offers each companion skill that is missing or older than the one Training Studio was made with. See [The companion skills](#the-companion-skills).
8. Reports what else is needed and is not there, each with how to get it:
   - git, and whether it knows your name and email. The runner keeps trainings in a git repository and records who decided what.
   - Claude Code or Codex. Codex can be asked whether it is signed in. Claude Code cannot be asked without starting it, so the report reminds you to run `claude` once.
   - Node 20 or newer, which the companion skills run on.
   - A brand skill, for slide decks. A brand skill is your organisation's own. It is not installed from here, and without one everything is made except the deck.
   - `pandoc`, which matters only if you ask for Word copies.

It installs for every assistant whose skill folder already exists. To choose, add `--target claude`, `--target codex` or `--target both`; a named assistant's folder is created if it is missing.

## Open Training Studio

On a Mac, the installer writes `Open Training Studio.command` into the `Applications` folder inside your home folder. Double-click it. A terminal window of your own opens, the runner starts in it, and the page opens in your browser. Leave the window open while you work. Close it, or press Ctrl-C in it, to stop. Nothing is lost by stopping.

On any system, the installer prints one line that does the same. With the usual locations it is:

```bash
sh ~/.local/share/training-studio/studio
```

The page works only with its key, which the runner makes each time it starts. The key goes to your own terminal and your own browser and is never written to a file. That is why the runner is started by you, in a window of yours, and not in the background.

Both launchers open whichever version is current, so updating or going back a version needs no change to them. A file of your own with the same name is never overwritten.

## The companion skills

Research is done by [harness-research](https://github.com/dbbaskette/harness-research-skill) and decks are built by [harness-slides](https://github.com/dbbaskette/harness-slides-skill). Each lives in its own repository. Nothing of either is kept in this one.

### How each one means to be installed

Each companion keeps a small entry in its repository, `bootstrap/SKILL.md`. That entry is what your assistant reads. It fetches the companion's current guidance from its own repository, and it runs only the helper programs that are installed on your computer. So the entry does not work alone: the helpers must be beside it.

Each companion also has its own installer. It copies the helpers into a shared folder of its own, makes the small entry the skill's `SKILL.md`, and links the skill for the assistants. It keeps every version it has installed, and it refuses to touch a skill it did not place.

Training Studio's installer therefore does not lay a companion out itself. A copy made our own way would be one the companion's installer later refuses to update. It fetches the companion and runs the companion's own installer.

### What happens when you say yes

1. The one pinned revision is fetched from the companion's repository into `~/.local/share/training-studio/companions/<name>/<revision>`. No sign-in is asked for: the repositories are public.
2. It is checked. The commit must be the pinned one, and one SHA-256 over every file must match the pin. The small entry must name the skill, and the installer must be there. If any check fails, nothing is kept and nothing is run.
3. The companion's installer is run with Node from that checked copy.
4. What it left is checked: each assistant you chose must now have the skill, at that version, with exactly the entry that was checked.

A companion that is already there at the pinned version or newer is left alone and not fetched. One that is there some other way, so that its version cannot be read, is also left alone, and the report says so.

### Why this is safe, and where it stops

- **Nothing is run without your yes.** The question is asked for each companion. `--yes` answers only the first question, about Training Studio itself. When no one is there to answer, no companion is fetched. `--companions install` is the way to say yes in advance, on the command line.
- **Nothing is run that was not checked.** The pin is a file in this repository, `installer/companions.json`. You already trust this repository when you run its installer. The pin names a commit, which git identifies by the content of every file, and adds a SHA-256 of our own over the same files. A repository that changed, a tag that was moved, or a download that was altered on the way fails the check.
- **The kept copy is checked again** each time before it is used.
- **The companion's installer changes little.** It adds a version to its own shared folder and adds links. It does not replace a skill it did not place, and it does not need administrator rights.
- **harness-slides also downloads packages.** Its installer gets the packages its slide engine needs from npm. They are the versions its own lock file names, with the hashes that file holds, and their install scripts are not run. The installer says this before you answer.

Where it stops:

- The pin says the code is the code that was looked at when the pin was made. It does not say more about that code than its authors do.
- A companion's installer registers the skill for every assistant it knows: Codex, Claude Code and Cursor. That is wider than `--target`.
- After it is installed, a companion fetches its own guidance from its own repository when you start work with it. That is how it works however it was installed. Its guidance holds no programs.

### Keeping the pins

For whoever keeps this repository. To move a companion to a newer release:

```bash
python3 installer/install.py pin harness-slides --revision v0.13.1
```

This fetches that tag or commit, and writes its commit, its version and the SHA-256 of its files into `installer/companions.json`. Read what changed in the companion between the old commit and the new one, run the installer into a temporary home, then commit the file. The pin records the commit, not the tag, so a tag that moves later changes nothing.

## Guidance updates itself; scripts do not

The skill has two parts. The **scripts** and the **runner** change files on your computer, so they only change when you run the installer. The **guidance**, the instructions your assistant follows, is fetched from this repository when you start a new training, so improvements reach you without reinstalling.

Each training stays on the guidance it started with, so a training does not change under you halfway through. To move one to the newest guidance, ask your assistant to update the guidance for that training.

If the newest guidance cannot be fetched, for example with no network, the assistant uses the guidance that was installed with the scripts and tells you it may be older.

## See what is installed

```bash
sh installer/install.sh check
```

This changes nothing. It reports the installed version, whether each link still points where the installer put it, how to open the runner and whether it is open now, each companion's version, and what is missing.

To see what an install would do without doing it:

```bash
sh installer/install.sh install --dry-run
```

## Update

Close Training Studio if it is open. Get the newer version of this repository and run the installer again. The new copy is installed beside the old one, the runner with it, and the links move to it. Trainings you have already made are not touched; they live in your own folders.

The installer never changes anything while the runner is working. It says so and stops. Close the runner's window, or press Ctrl-C in it, and run the installer again. This holds for going back a version and for removing too.

## Go back a version

```bash
sh installer/install.sh rollback
```

This points the links at the version that was installed before the current one, and its runner with it. The companion skills are not changed: each keeps its own versions, and its own installer is the way to go back.

## Remove

```bash
sh installer/install.sh uninstall
```

This removes the links and the launchers the installer placed. It leaves alone any link that has since been pointed somewhere else. The installed copies stay in `~/.local/share/training-studio/versions`, and the fetched copies of the companions in `~/.local/share/training-studio/companions`; delete those folders yourself if you no longer want them.

The companion skills stay installed, because other tools may use them. Each one's own README says how it is managed.

## If something is in the way

If `training-studio` already exists in a skill folder as a real folder, the installer stops and leaves it alone. Move it yourself, or add `--replace` to have the installer move it to `~/.local/share/training-studio/backups`. Nothing is ever deleted.

An existing link is simply replaced, and the installer records where it used to point.

## For development

To work on the skill and have your assistant use your changes straight away, link to the checkout instead of copying it:

```bash
sh installer/install.sh install --link
```

Nothing is copied, the launchers open the checkout's own runner, and there is nothing to roll back to.

## Options

| Option | Does |
| --- | --- |
| `install`, `check`, `rollback`, `uninstall` | The action. `install` is the default |
| `--target claude`, `codex` or `both` | Which assistant to install for |
| `--companions ask`, `install` or `skip` | The companion skills. `ask` is the default: each is offered, and none is brought when no one is there to answer. `install` says yes in advance. `skip` brings none |
| `--link` | Link to this checkout; copy nothing |
| `--replace` | Move aside a real folder that is in the way |
| `--yes` | Do not ask before making changes. Needed when no one is there to answer. It does not say yes to a companion |
| `--dry-run` | Say what an install would do; change nothing |
| `--json` | Print the result as JSON |
| `pin <companion> --revision <tag or commit>` | For whoever keeps this repository: pin a companion |
