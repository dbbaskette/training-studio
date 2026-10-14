# Google Docs

The `document` and the `brief` can go to a Google Doc for review and come back. Nothing else can; a deck belongs to `harness-slides`. With levels, name the level: `document@101`. The markdown file stays the source. The Doc is a copy people edit.

## Ask first

Creating or changing a Google Doc is an action on the user's behalf and needs their go-ahead. A go-ahead for one Doc covers later updates to that Doc. A new Doc, or another artifact, needs asking again. If `settings.copies` in `training.py status` includes `google`, the user asked for Google Docs for this training: that is the go-ahead for its documents and briefs. Send only what the user asked for. Never delete a Doc or change who can see it; sharing is the user's action. If a source was private, say so first, as the privacy reference describes.

## Through gcloud

| Command | Does |
| --- | --- |
| `training.py google push <artifact>` | Creates the Doc, or replaces its content. `--title "<name>"` names a new one |
| `training.py google pull <artifact>` | Brings the Doc's edits into the file |
| `training.py google status` | Each linked artifact: `in sync`, `local changed`, `remote changed` or `both changed`. `--offline` looks at the local file only |
| `training.py google unlink <artifact>` | Forgets the link. The Doc stays |

A refusal that names `gcloud` gives the command that fixes it. Show it to the user to run; signing in is theirs to do. Or use a connector.

## Through the harness's own Google Drive connector

Here you move the text and the helper keeps the books. The connector must make a Doc from markdown and export one as markdown; if it cannot, say so and stop. Keep scratch files outside the training directory.

1. If the artifact is already linked, export the Doc as markdown and run `training.py google pull <artifact> --from <export>`. Go on only when it answers `nothing to do`.
2. `training.py google push <artifact> --prepare <file>` writes the text to send. It reports `linked`, and the `file_id` to replace or the `title` for a new Doc.
3. Create the Doc from that file, or replace the linked Doc's content with it. Send that file, never the artifact's own.
4. Export the Doc as markdown, then `training.py google record <artifact> --file-id <id> --url <url> --export <export>`.

To pull later, do step 1.

## Coverage comments

Google Docs drops HTML comments. A push holds back each `<!-- covers: … -->` and `<!-- findings: … -->` comment, and a pull puts each back under the heading it sat under. Renumbering a heading is fine. If the pull lists a comment under `unplaced`, its heading is gone from the Doc: tell the user which one, add the comment by hand under the section that now covers it, and run `training.py save <artifact>`.

## What a pull does to approval

A pull that brings in edits is a hand edit, as the workspace reference describes. It replaces the file and keeps the old version in history. The artifact becomes `draft` and what was built from it `stale`, even if both were approved; one already stale stays stale. Tell the user, run `training.py check`, and present the stage's gate again. After approval, make its copies again and rebuild what is stale, or ask whether to accept it.

Google rewrites markdown on export, so formatting can change where the words did not. Comments and suggestions left in the Doc are not read: ask the user to accept or reject suggestions before a pull.

## Conflicts

- **`push` refused, the Doc changed:** pull first. `--force` throws the Doc's edits away; use it only when the user says to.
- **`pull` refused, both changed:** neither side was altered, and the Doc's text is beside the artifact as `<name>.remote.md`. Show the user the differences, put what they choose into the artifact's file, and run `training.py save <artifact>`. Then `training.py google push <artifact> --force`, or steps 2 to 4 with a connector. Delete the `.remote.md` file.
