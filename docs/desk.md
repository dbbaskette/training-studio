# The training desk

The desk is one page in your browser that shows every training on this computer: what is approved, what is stale, what is blocking, and where the files are.

It only reads. Approving, skipping and rebuilding stay in the conversation with your assistant.

## Open it

Ask your assistant:

> Open the desk.

It starts a small server on your computer and gives you a link. Open the link exactly as it is given. The part after `#` is a key, and the page does not work without it.

When you are done, say so, and your assistant stops the server. The page stops working when it does. Each time the desk is opened you get a new link.

You can also run it yourself from a terminal:

```bash
python3 ~/.local/share/training-studio/current/scripts/training.py desk
```

It prints one line with the link and runs until you press Ctrl-C. Add `--port 8765` to choose the port. In a checkout of this repository the helper is `skills/training-studio/scripts/training.py`.

## What you see

**The list.** Every training, most recently touched first. Each one shows its title, its levels, the stage it has reached, whether it is ready, how many files have each status, and its folder.

**One training.** Choose a training to see:

- its files, level by level, each with its status, its file name and whether its Word copy is current,
- what is blocking it,
- any check that failed or could not run, and why,
- its limitations: what was skipped, could not be produced, or was accepted as it was,
- warnings,
- which objectives its scenarios exercise,
- when the research was approved and how its findings came out,
- which guidance the training is pinned to.

**A file.** Choose a file name to read it. Markdown is shown as plain text, exactly as written. A deck is not text, so the page gives its name and size and leaves you to open it from the folder.

**Handing back to your assistant.** One button copies the training's folder. Another copies a sentence to paste to your assistant, asking it to resume that training. Start your assistant in that folder first: one folder is one training.

The page reads again when you come back to it, and whenever you press **Read again**.

## What the words mean

The page uses the same words as the rest of Training Studio. A file is `approved`, `draft`, `stale`, `not-started`, `skipped` or `unavailable`, and each status has its own shape as well as its own colour. A training is **ready** when every wanted file is approved, nothing is stale, and no check failed or could not run. See [how it works](how-it-works.md#approval-and-what-stale-means).

## What it does not do

- **It changes nothing.** There is no button that approves, skips or rebuilds. Tell your assistant instead.
- **It shows the trainings this computer knows about.** A training is known once it has been created here, or once your assistant has read its status here. A folder copied from another computer appears after you first ask about it.
- **It runs only while its server runs.** Close the page whenever you like; the server keeps going until it is stopped.
- **It does not render anything.** A file is shown as its text. Nothing in a file is ever run or treated as a web page.

A training whose record cannot be read is still listed, with the reason, so one broken folder never hides the others.

## Is it private?

Yes. The desk is local.

- The server listens on `127.0.0.1` only, so no other computer can reach it.
- The page loads nothing from the internet: no fonts, scripts or images from anywhere else. Nothing is sent anywhere.
- Every request for data must carry the key from your link. A request without it, or one that arrives under another site's name, is refused.
- It answers `GET` requests only. There is nothing to send it that would change a file.
- It can read only the trainings in this computer's list, and within a training only the files Training Studio manages. It cannot be pointed at another folder.

## For the curious

`training.py desk [--port N]` prints one line of JSON, `{"url": "..."}`, and then serves until it is interrupted.

| Request | Returns |
| --- | --- |
| `GET /` | The page. Its two other files are `app.js` and `style.css` |
| `GET /api/trainings` | Every known training: title, levels, stage, when it was last touched, a count of files by status, whether it is ready, and how many things are blocking it |
| `GET /api/training?path=P` | One training: what `status` reports, and what `check` reports |
| `GET /api/file?path=P&artifact=A` | The text of one file, or its name and size if it is not text |

The three `/api/` requests need the key, in a header named `X-Training-Studio-Token`. The page files live with the scripts, in `skills/training-studio/scripts/desk/`. The design is in the [phase 5 specification](superpowers/specs/2026-10-12-phase-5-training-desk.md).
