# Training Studio phase 3: Google Docs round-trip

Date: 2026-10-12
Status: implemented

## Purpose

Let the learner guide and the brief go to Google Docs for review and come back, without losing an edit on either side and without breaking the approval model.

## Scope

In: the `document` and `brief` artifacts (and their level forms, such as `document@101`). Push a markdown artifact to a Google Doc, pull edits back, report sync state.

Out: decks (owned by `harness-slides`), comments and suggestions in Google Docs, sharing and permissions, any artifact other than document and brief.

## Files

| File | Responsibility |
| --- | --- |
| `skills/training-studio/scripts/gdocs.py` | State, three-way sync logic, comment anchoring, transports. No argument parsing |
| `skills/training-studio/scripts/cmd_google.py` | The command plug-in: `register(commands)` and handlers |
| `skills/training-studio/references/google.md` | Guidance for the assistant, within 1,000 estimated tokens |
| `tests/test_google.py` | Tests, with a fake transport and a stubbed HTTP layer. No network |
| `docs/google-docs.md` | A page for users, linked from the README |

## State

`.training-studio/google.json`, written with `home.write_json`:

```json
{
  "schema": 1,
  "docs": {
    "document": {
      "file_id": "…", "url": "…", "title": "…",
      "local_sha256": "…",
      "remote_sha256": "…",
      "anchors": [["What a rolling restart does", "<!-- covers: O1 K1.1 K1.3 -->"]],
      "synced_at": "2026-10-12T15:04:00Z"
    }
  }
}
```

`local_sha256` is the hash of the local file at the last sync. `remote_sha256` is the hash of the Google Doc's markdown export at the last sync, taken by exporting straight after a push, so that Google's own reformatting is never mistaken for an edit.

## Sync rules

Let "local changed" mean the local file's hash differs from `local_sha256`, and "remote changed" mean the current export's hash differs from `remote_sha256`.

| Command | Local changed | Remote changed | Result |
| --- | --- | --- | --- |
| `push` | any | no | Create the Doc if not linked, else replace its content. Record both hashes |
| `push` | any | yes | Refused: "The Google Doc changed since the last sync. Pull first." `--force` overrides |
| `pull` | no | yes | Apply the remote text to the local artifact through `workspace.save(root, artifact, source=…)`, so history keeps the old version and the artifact returns to `draft` |
| `pull` | yes | yes | Refused as a conflict. The remote text is written beside the artifact as `<name>.remote.md` and both are left for the user to reconcile |
| `pull` | any | no | Nothing to do |
| `status` | | | Per linked artifact: `in sync`, `local changed`, `remote changed`, `both changed`. `--offline` skips the export and reports local state only |

A pull that applies remote text makes the artifact a draft and everything built from it stale. That is correct: the content changed, so it needs approving again.

## Coverage comments must survive

Google Docs drops HTML comments. The document's `<!-- covers: … -->` and the brief's `<!-- findings: … -->` comments would be lost, and the checks would then fail.

- On push, each such comment is removed from the text sent to Google and remembered as an anchor: the text of the nearest heading above it, and the comment.
- On pull, each anchor's comment is put back on its own line under the heading with that text.
- An anchor whose heading no longer exists is reported by name in the result as `unplaced`, and the pull still completes. The assistant then tells the user and the comment is re-added by hand.
- Matching is on heading text with surrounding whitespace and numbering such as `2. ` ignored.

## Transports

`gdocs.py` defines a small interface and two ways to satisfy it.

```python
class Transport:
    def create(self, title: str, markdown: str) -> dict: ...   # {'file_id', 'url'}
    def update(self, file_id: str, markdown: str) -> None: ...
    def export(self, file_id: str) -> str: ...                 # markdown
```

**`GcloudTransport`.** Standard library only. Gets a token from `gcloud auth print-access-token` and calls the Drive v3 REST API with `urllib`:

- create: multipart upload with `mimeType` `application/vnd.google-apps.document` and a `text/markdown` body, which Drive converts.
- update: media upload of `text/markdown` to the existing file.
- export: `files/<id>/export?mimeType=text/markdown`.

A missing `gcloud`, a missing Drive scope or an HTTP error becomes a clear refusal that says what to do (for example `gcloud auth login --enable-gdrive-access`). No token is ever written to disk or printed.

**The assistant's own connector.** When the harness has a Google Drive connector, the assistant does the transfer and the helper only keeps the books:

- `google push <artifact> --prepare FILE` writes the comment-free text to FILE and records nothing.
- `google record <artifact> --file-id ID --url URL --export FILE` records a completed push, taking FILE as the Doc's export.
- `google pull <artifact> --from FILE` applies the sync rules with FILE as the remote export.

So every rule above works with remote text supplied either way.

## Commands

All print JSON and refuse with `{"error": …}`, like the rest of the helper.

| Command | Does |
| --- | --- |
| `google push ARTIFACT [--force] [--title T]` | Push through gcloud |
| `google push ARTIFACT --prepare FILE` | Write the text to send, for a connector |
| `google record ARTIFACT --file-id ID --url URL --export FILE` | Record a push made by a connector |
| `google pull ARTIFACT [--from FILE]` | Pull through gcloud, or from an export a connector fetched |
| `google status [--offline]` | Sync state of every linked artifact |
| `google unlink ARTIFACT` | Forget the link. The Doc is not deleted |

## Boundaries

- Creating or changing a Google Doc is an action on the user's behalf. The guidance must say it needs the user's go-ahead, and that a go-ahead for one Doc covers later updates to that Doc.
- Nothing is pushed that was not asked for. Only `document` and `brief`.
- The helper never deletes a Doc and never changes sharing.

## Known limits to state in the docs

- Google rewrites markdown on export, so a pulled file's formatting can differ from what was pushed even where the words are the same.
- Comments and suggestions in Google Docs are not read.
- Live verification against Google needs a signed-in user. The automated tests use a fake transport.

## Deviations

What was built differs from the text above in these ways. Each is a narrowing or an addition; no rule in the sync table changed.

- **Repeated headings.** An anchor under a heading whose text is used more than once carries a third item, which occurrence it is, counting from 1. The first occurrence stays a pair, so the state for a document with unique headings is exactly as shown.
- **Heading matching** also ignores what an export adds around a heading: backslash escapes such as `2\.`, emphasis markers and closing `#`s.
- **The remote hash** is taken after dropping a byte order mark, unifying line endings and trimming the end of the text, so the same export fetched through gcloud and through a connector hashes the same.
- **A push cut short.** Between changing the Doc and reading it back, the link is stored with both hashes empty. If the read-back fails, the next push updates that Doc instead of creating a second one, and a pull is refused until then.
- **`status --offline`** reports `local changed` or `local unchanged`. It never says `in sync`, because the Doc was not looked at.
- **`status`** reports `unavailable`, with the reason, for a link to an artifact the training no longer has, such as a removed level.
- **A pull is recorded as an edit.** `workspace.save` gained an `edit` flag for this: the old version goes to history, but what the artifact was built from is left alone, so pulling into a stale artifact leaves it stale.
- **The conflict file** `<name>.remote.md` has the coverage comments put back, so it can be saved as the artifact as it is.
- **`record`** takes an optional `--title`, to keep the name a connector gave a new Doc.
- **`--title`** is refused for an artifact that is already linked; the helper never renames a Doc.
- **`--prepare FILE`** must be outside the training directory, so a prepared copy can never overwrite an artifact.
- **An empty export** is refused by `pull` and `record`.
- **Only `covers` and `findings` comments** are held back and restored. Any other HTML comment is sent as it is and Google decides what happens to it.

Not verified: any call to Google. `GcloudTransport` is tested against a stubbed token command and a stubbed HTTP layer only. Whether Drive accepts the markdown upload and update as written, and what its markdown export does to numbered headings and tables, needs a run with a signed-in account.
