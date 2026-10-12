# Training Studio phase 5: the training desk

Date: 2026-10-12
Status: implemented

## Purpose

Give the user one page, in their browser, showing every training on their computer and what state each is in: what is approved, what is stale, what is blocking, and where the files are.

## Scope

In: a local, read-only web page. A list of trainings, a detail view for one, and a plain preview of a deliverable's text.

Out: any change to a training from the page (approvals stay in the conversation with the assistant), anything served to another machine, user accounts, a build step.

## Files

| File | Responsibility |
| --- | --- |
| `skills/training-studio/scripts/desk.py` | The local server and its read-only API. No argument parsing |
| `skills/training-studio/scripts/cmd_desk.py` | The command plug-in |
| `skills/training-studio/scripts/desk/index.html`, `app.js`, `style.css` | The page. Plain HTML, CSS and JavaScript; no build, no external resources |
| `skills/training-studio/references/desk.md` | Guidance for the assistant, within 500 estimated tokens |
| `tests/test_desk.py` | Tests against a server on an ephemeral port. No browser needed |
| `docs/desk.md` | A page for users, linked from the README |

The page's files live under `scripts/` because they are served by the scripts and must be installed with them. Everything under `assets/` is guidance and can be newer than the scripts.

## The server

- Standard library `http.server`, bound to `127.0.0.1` only, on a port the system chooses unless `--port` is given.
- A random token is made at start. The URL printed to the user carries it in the fragment (`#token=…`), so it is not sent in a request line or logged. The page reads it and sends it as the `X-Training-Studio-Token` header on every API call.
- Every request is checked: the `Host` header must be `127.0.0.1` or `localhost` on the server's port, and API calls must carry the token. Anything else gets 403.
- Responses carry `Content-Security-Policy: default-src 'self'`, `X-Content-Type-Options: nosniff` and `Cache-Control: no-store`.
- Read-only: only `GET` is answered. There is no endpoint that changes anything.

`training.py desk [--port N]` prints one line of JSON with the URL and then serves until interrupted. `desk.py` exposes the server as a class so tests can start and stop it.

## The API

| Endpoint | Returns |
| --- | --- |
| `GET /api/trainings` | The trainings from `home.trainings()`, each with its title, levels, stage, counts of artifacts by status, and whether it is ready |
| `GET /api/training?path=P` | For one registered training: the status report, and the `check` result with blocking, limitations, warnings and practice |
| `GET /api/file?path=P&artifact=A` | The text of one artifact's file, for preview |

Rules:

- `path` must be a training in the registry. Any other path is refused, so the server can never be used to read arbitrary folders.
- `artifact` must be an artifact name of that training. The file served is the one `workspace.artifact` names for it. Binary files (the deck) return their name and size, not their bytes.
- A training whose record cannot be read is listed with its error, not dropped and not allowed to break the list.

`desk.py` gets status from `workspace.status` and the check result from `training.run_checks`, so the page shows exactly what the assistant sees.

## The page

One page, no framework.

- **List.** Each training: title, levels, stage, a readiness badge, counts by status, when it was last touched, and its folder. Sorted by most recent.
- **Detail.** Per level, a table of artifacts with status, file and export state. Then what is blocking, the limitations, warnings, which objectives the scenarios exercise, the research summary and the guidance it is pinned to.
- **Preview.** The text of a markdown artifact, shown as plain text. Markdown is not rendered and nothing in a file is ever treated as HTML.
- **Hand-off.** A button copies the folder path. Another copies a sentence to give the assistant, such as asking it to resume that training. The page changes nothing itself.

It must be usable at a phone's width and in both light and dark colour schemes, and every status must be distinguishable without relying on colour alone.

## Boundaries

- Local only. Nothing is sent anywhere. No external fonts, scripts or images.
- File contents are inserted as text, never as markup.
- The desk does not depend on the Team Hub or Google phases.

## Known limits to state in the docs

- Read-only: approving, skipping and rebuilding stay with the assistant.
- It shows trainings this computer knows about. A training is known once it has been created or had its status read on this computer.
- The server runs until stopped, and the page stops working when it is.

## Deviations

- **Two more fields in the list.** Each training also carries `touched_at` and `blocking`. `touched_at` is the later of when the registry last saw the training and the last change recorded in its session; the list is sorted by it. The registry alone would miss work done since status was last read. `blocking` is how many things block readiness, so the list can say more than ready or not.
- **An unreadable record is an answer, not a failure.** `GET /api/training` for a registered training whose record cannot be read returns 200 with `error` and no `status` or `check`, as the list does. `GET /api/file` for it returns 409.
- **The preview is capped.** A file's first 1,000,000 bytes are returned with `truncated: true`. A file that is not `.md` or `.json`, or is not valid UTF-8, is treated as binary.
- **A file that leads out of the folder is refused.** If an artifact's file is a symbolic link to somewhere outside the training folder, `GET /api/file` returns 403.
- **`GET /favicon.ico` returns 204,** so a browser's own request for an icon does not show as an error. It serves nothing.
- **The command also stops on a termination signal,** closing the server and exiting 0, as it does when interrupted. A command run in the background is usually stopped that way.
- **The tests skip where a local port cannot be opened.** Every server test binds a port on `127.0.0.1`. In an environment that forbids that, they are skipped with the reason rather than failed. The checks of the page's files and of the package still run.
