# Shared studios workspace and defaults

This is the common convention for Training Studio, Blog Studio and Presentation
Studio. Each studio implements the parts it uses and keeps its own settings.

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

## Shared defaults

The optional file is `~/.config/studios-config.json`. `STUDIOS_CONFIG` overrides
its location, including in tests. This example contains no credentials:

```json
{
  "schema": 1,
  "team": { "repository": "https://github.com/example/team-studios.git", "branch": "main" },
  "person": { "name": "Example Author" },
  "assistant": { "agent": "claude", "model": "opus", "effort": "high" },
  "brand": { "brand": "example", "variant": "light" },
  "output": "google",
  "share": "decision"
}
```

Every setting is optional. A studio uses supported fields to fill first-launch
setup and new-item defaults. Its own saved settings win. Existing items retain
their choices. Unknown and unused fields are ignored, and unrelated JSON bytes
are preserved when a supported value is changed.

A studio writes this file only after the person changes a shared value and
selects **Use for all studios**. It merges only those changed fields and replaces
the file atomically. Per-studio settings do not belong here. Tokens, passwords,
Google credentials and GitHub authentication stay in the tools' existing stores;
repository addresses containing credentials are refused.

A missing file leaves normal defaults unchanged. An unreadable or invalid file
never prevents local writing: setup and computer status explain that the studio
is using its own settings. An invalid file is preserved when an update is refused.
