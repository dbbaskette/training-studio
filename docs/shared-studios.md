# Shared studios workspace and settings

This is the common convention for Training Studio, Blog Studio and Presentation
Studio. Each studio implements the parts it uses. Shared settings have one
source; limits and other studio-specific choices stay local.

## One repository

A team can give every studio the same repository address and branch, normally
`main`. Each studio keeps a separate clone under its own per-user data folder.
It records changes only inside its folder:

```text
<team-repository>/
  trainings/<training>/
  blogs/<blog>/
  presentations/<deck>/
```

Each studio folder has `README.md` and a `hub.json` marker with `schema` and
`tool`. The tool is `training-studio`, `blog-studio` or `presentation-studio`.
A studio refuses a marker belonging to another tool. It leaves the repository
root and the other studios' folders alone when making commits.

The repository holds readable writing, JSON records, document links and small
previews. Working folders (`work/`, `sources/`), harness guidance caches
(`**/.harness-*/guidance/`), locks and large renders stay on each computer.
Each studio maintains ignore rules inside its own folder. Blog Studio keeps
reusable reference text, voices and memory in `blogs/.shared/`.

A shared item has one driver. A computer shares its claim before starting work.
Taking over is explicit; another computer keeps its unshared commits under a
local recovery reference when it learns that its claim was replaced. Handing
an item over shares the release of its claim. An unreachable repository prevents
new claims; a current driver can retain decisions locally and retry sharing.

Every decision is a commit. Sharing fetches, replays and pushes without force.
The default is to share after each decision; `asked` means share only when the
person chooses **Share now**. Claims and handovers are always shared immediately.
Publishing records a numbered revision inside the repository; it does not send
content to a CMS or change the repository's visibility.

## One shared settings file

`~/.config/studios-config.json` is the single source of truth for settings the
studios share. `STUDIOS_CONFIG` overrides its location, including in tests.
This example contains no credentials:

```json
{
  "schema": 1,
  "team": { "repository": "https://github.com/example/team-studios.git", "branch": "main" },
  "person": { "name": "Example Author" },
  "assistant": { "agent": "claude", "model": "opus", "effort": "high" },
  "brand": {
    "repository": "https://github.com/example/brand-skill.git", "release": "v1.4.0",
    "brand": "example", "variant": "light"
  },
  "output": "google",
  "share": "decision"
}
```

Every setting is optional. Each studio reads the supported shared values from
this file on its next read, without a per-studio override or another saved copy.
Saving a shared value in Settings updates this file directly. There is no
**Use for all studios** toggle. Existing items retain the choices and contracts
they started with; these are saved item inputs, not another settings source.
Unknown and unused fields are ignored. Limits, preview renderer, concurrency,
installed skill paths and other studio-specific choices stay in local settings.

Writes merge only changed members, replace the file atomically, and preserve
unrelated JSON bytes, including unknown keys and formatting. Writers serialize
through the adjacent `.lock` file. A stale form preserves unrelated changes and
refuses a conflicting change to the same member. Tokens, passwords, Google
credentials and GitHub authentication stay in the tools' existing stores.
Repository addresses carrying credentials are refused. Brand repository and
release inputs use the same checks as the brand skill's Settings form.

Installing or upgrading a brand skill stays an explicit action in each studio's
Versions/Status view, using the skill's own installer at the shared repository
and release. Reading shared settings never installs software. A changed team
repository or branch never silently moves existing work: join it explicitly to
use it in that studio. A clone's marker and Git origin describe its actual
connection; they do not override the shared setting for a new join.

On the first run after upgrading, legacy shared values in that studio's settings
are copied only where the shared file lacks a member. A value already in the
shared file is kept, and the person is told. After the shared write succeeds,
the old local copies are removed. Repeating or resuming migration is safe.

A missing file means built-in defaults until shared settings are saved or
migrated. An unreadable or invalid file never prevents writing: setup and Status
say that built-in shared defaults are in use. Saving a shared value is refused
until the file is readable. The existing file and unmigrated local settings are
kept, without using those old local copies as overrides.
