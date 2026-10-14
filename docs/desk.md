# The page

Training Studio has a page that runs in your browser, on your own computer. It shows what needs you, where every training stands, and whether this computer is ready. If you choose, it is also the only place a stage can be approved.

## Open it

Run this in a terminal of your own:

```bash
~/.local/share/training-studio/training desk
```

It prints one line with a link. Open the link exactly as it is printed: the part after `#` is a key, and the page does not work without it. The command runs until you press Ctrl-C, and the page stops working when it does. Each time you run it you get a new link. Add `--port 8765` to choose the port.

The installer writes `training`, for a linked checkout too, and it finds a Python new enough itself. Without the installer, run `python3 skills/training-studio/scripts/training.py desk` in a checkout of this repository, with Python 3.11 or newer.

You can also ask your assistant to open the page. It then opens in your browser by itself, and your assistant is never shown the key: when the command is not run in a terminal, it prints only the address and says so. For a training that is decided on the page, your assistant does not open it at all. It asks you to run the command yourself.

## Home

Home opens on what needs you.

- **Needs you** lists each training that is waiting at a gate, or has a question for you, with one sentence saying what is waiting. The button in the toolbar takes you to the first of them.
- **In progress** shows the trainings that are being worked on, each with its row of stages.
- **Finished** shows the ones that are complete.

The count beside Home, and in the tab's title, is how many things need you. Turn on notifications in Settings and the browser tells you when something new does, while the page is open in a tab.

The same row of stages appears everywhere. A stage is done, in progress, yours to review, not started, left out, or could not be made, and each of those has its own shape as well as its own colour.

## A gate

A gate is one thing to read and one decision to make.

- **The document** is shown as a document, not as its source. A research plan is shown as its questions. A deck is not text, so the page gives its name, its size and where it is.
- **What changed** compares it, line by line, with the version you last approved. It is one press away, above the document.
- **Checked for you** says how many automatic checks passed. **Worth a look** names any that did not, says why something is out of date, and shows your assistant's latest review note.

Then decide, from the toolbar:

| You choose | What happens |
| --- | --- |
| Approve | This version is approved, against what it was built from. The page asks you to confirm |
| Ask for changes | You say what should change, in your own words. Nothing is approved |
| Rebuild it | It is made again. You can say what to do differently |
| Skip this stage | The stage is left out. You give a reason, and can bring it back later |
| Accept as it is | Offered when something it was built from has changed. You give a reason |

After a decision the page says what happens next and offers the next thing that needs you. You can close it. Go back to your assistant and say you have decided: it reads what you chose and carries on.

If the document changes while you have it open, the page says so and waits for you to look at the new version. You never approve something you were not shown.

## Deciding on the page, or in the conversation

Each training is decided in one of two places. Change it in Settings, or on the training's own screen.

- **In the conversation.** You approve by telling your assistant. This is how every training starts unless you ask otherwise.
- **On this page.** Only the page can approve, skip a stage or bring one back. If your assistant tries, the helper refuses and tells it to send you here. Only the page can move a training back to the conversation.

To start a training this way, ask for it at the beginning: "I want to approve each stage on the page."

Be clear about what this does. It stops an assistant that follows its instructions, or that slips, from approving for you. It does not make forgery impossible: an assistant with a shell that set out to rewrite the training's record could still do so. The guidance forbids that. [The runner](runner.md) closes the gap for the stages it drives: its agents have no shell and cannot reach the training's files at all.

## Trainings, Status and Settings

- **Trainings** shows every training on this computer as a card. Open one to see its files, what is in the way, its checks, what was left out, which objectives its scenarios exercise, its research and the guidance it is pinned to. From there you can open any file, bring back a stage that was left out, and copy a sentence that asks your assistant to resume.
- **Status** shows everything at once: each training's stage, where it stands, how long since it changed and how many things are in its way. **Check this computer** looks for what a training needs: Claude Code and Codex, each installed, signed in where that can be asked, and reachable from the network you are on; Node; the two companion skills; and, as extras, the Google Cloud CLI and pandoc. Anything missing comes with how to put it right. The check asks each tool for its version, asks Codex whether it is signed in, and opens a connection to each service. It never starts an assistant.
- **Settings** holds notifications and where each training is decided.

The page keeps itself up to date. You do not need to reload it.

## Is it private?

Yes. The page is local.

- The server listens on `127.0.0.1` only, so no other computer can reach it.
- The page loads nothing from the internet: no fonts, scripts or images from anywhere else.
- Every request for data must carry the key from your link. A decision must also come from the page itself, as JSON. Anything else is refused.
- It can read and change only the trainings in this computer's list, and within a training only the files Training Studio manages.
- Whatever is in a file, a note or a title is shown as text. Nothing in it is ever run or treated as a web page.
- The only time anything leaves your computer is when you press **Check this computer**, which opens a connection to each assistant's service to see whether your network lets it through. It sends nothing.

## What it does not do

- **It does not start or run a training.** Your assistant does that, in a conversation.
- **It shows the trainings this computer knows about.** A training is known once it has been created here, or once your assistant has read its status here.
- **It runs only while its command runs.**

A training whose record cannot be read is still listed, with the reason, so one broken folder never hides the others.

## Less glass, less motion

The page is drawn like a Mac app: translucent glass for the sidebar, the toolbar and the controls, solid paper for anything you read. If your system asks for reduced transparency, more contrast or reduced motion, the page uses solid surfaces and stops moving. It also does so in a browser that cannot blur what is behind glass.

## For the curious

`training.py desk [--port N]` prints one line of JSON and then serves until it is interrupted. In a terminal the line is `{"url": "..."}`. Anywhere else it is `{"address": "...", "opened": true, "note": "..."}`, with no key in it.

| Request | Returns |
| --- | --- |
| `GET /` | The page. Its other files are `app.js`, `markdown.js` and `style.css` |
| `GET /api/trainings` | Every known training: where it is, what it is waiting for, its row of stages, and how many need you |
| `GET /api/training?path=P` | One training: what `status` and `check` report, and the same in plain words |
| `GET /api/gate?path=P&artifact=A` | One file at its gate: the document, what changed, what was checked, and the decisions on offer |
| `GET /api/file?path=P&artifact=A` | The text of one file, or its name and size if it is not text |
| `GET /api/computer` | The last check of this computer, if there was one |
| `POST /api/decide` | Records a decision: `path`, `artifact`, `decision`, and a `note` and the version `seen` where they apply |
| `POST /api/approval` | Moves a training's approval to the page or back: `path`, `mode` |
| `POST /api/computer` | Checks this computer now |

Every `/api/` request needs the key, in a header named `X-Training-Studio-Token`. A `POST` also needs an `Origin` header naming the page's own address and a JSON body. The page's files live with the scripts, in `skills/training-studio/scripts/desk/`. The design is in the [milestone 1 specification](superpowers/specs/2026-10-13-milestone-1-page-approval.md).
