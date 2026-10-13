# Installation

The installer puts a copy of the skill on your computer and links it into your assistant's skill folder. It needs Python 3.11 or newer and nothing else.

## Install

From a terminal, inside this repository:

```bash
sh installer/install.sh
```

On a Mac you can instead double-click `Install Training Studio.command` in the `installer` folder.

It tells you what it is about to do and asks before changing anything. When it finishes it lists where the skill was linked, and anything you still need, such as a companion skill.

## What it does

1. Checks that the skill package is whole.
2. Copies it to `~/.local/share/training-studio/versions/<version>`.
3. Runs the copy's own checks.
4. Points `~/.local/share/training-studio/current` at that copy.
5. Links the skill into each assistant it finds:
   - Claude Code: `~/.claude/skills/training-studio`
   - Codex: `~/.agents/skills/training-studio`
6. Reports what else Training Studio needs and whether it is there: the `harness-research` and `harness-slides` skills, Node 20 or newer for them, and `pandoc`, which matters only if you ask for Word copies.

It installs for every assistant whose skill folder already exists. To choose, add `--target claude`, `--target codex` or `--target both`; a named assistant's folder is created if it is missing.

The installer does not install the companion skills. It tells you which are missing and where to get them.

## Guidance updates itself; scripts do not

The skill has two parts. The **scripts** change files on your computer, so they only change when you run the installer. The **guidance**, the instructions your assistant follows, is fetched from this repository when you start a new training, so improvements reach you without reinstalling.

Each training stays on the guidance it started with, so a training does not change under you halfway through. To move one to the newest guidance, ask your assistant to update the guidance for that training.

If the newest guidance cannot be fetched, for example with no network, the assistant uses the guidance that was installed with the scripts and tells you it may be older.

## See what is installed

```bash
sh installer/install.sh check
```

This changes nothing. It reports the installed version, whether each link still points where the installer put it, and what is missing.

To see what an install would do without doing it:

```bash
sh installer/install.sh install --dry-run
```

## Update

Get the newer version of this repository and run the installer again. The new copy is installed beside the old one and the links move to it. Trainings you have already made are not touched; they live in your own folders.

## Go back a version

```bash
sh installer/install.sh rollback
```

This points the links at the version that was installed before the current one.

## Remove

```bash
sh installer/install.sh uninstall
```

This removes the links the installer placed. It leaves alone any link that has since been pointed somewhere else. The installed copies stay in `~/.local/share/training-studio/versions`; delete that folder yourself if you no longer want them.

## If something is in the way

If `training-studio` already exists in a skill folder as a real folder, the installer stops and leaves it alone. Move it yourself, or add `--replace` to have the installer move it to `~/.local/share/training-studio/backups`. Nothing is ever deleted.

An existing link is simply replaced, and the installer records where it used to point.

## For development

To work on the skill and have your assistant use your changes straight away, link to the checkout instead of copying it:

```bash
sh installer/install.sh install --link
```

Nothing is copied, and there is nothing to roll back to.

## Options

| Option | Does |
| --- | --- |
| `install`, `check`, `rollback`, `uninstall` | The action. `install` is the default |
| `--target claude`, `codex` or `both` | Which assistant to install for |
| `--link` | Link to this checkout; copy nothing |
| `--replace` | Move aside a real folder that is in the way |
| `--yes` | Do not ask before making changes. Needed when no one is there to answer |
| `--dry-run` | Say what an install would do; change nothing |
| `--json` | Print the result as JSON |
