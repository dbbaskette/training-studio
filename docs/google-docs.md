# Google Docs

You can send the learner guide or the brief to a Google Doc, let people edit it there, and bring their edits back into your training folder. Nothing is lost on either side, and nothing that changed stays approved without you looking at it again.

This works for the learner guide and the brief only. A deck is built by harness-slides and is not covered here.

## What to say

- "Put the guide in a Google Doc." or "Put the brief in a Google Doc."
- "Pull the Google Doc." when people have finished editing.
- "Is the Google Doc up to date?" to see whether either side has changed.
- "Unlink the Google Doc." to stop tracking it. The Doc itself is left alone.

Your assistant asks before it creates or changes a Doc. Saying yes for one Doc covers later updates to that same Doc. It asks again for a new Doc.

## Google Docs for every guide and brief

If you say at the start that you want Google Docs, or later say "Keep the guide and the brief in Google Docs", that is your go-ahead for the whole training. Each guide and brief is put in a Doc when you approve it, and the Doc is updated when you approve a change.

- The training is not reported as ready while a Doc is behind its file.
- A guide or brief that has no Doc yet is listed as a limitation, not a blocker.
- `README.md` in your folder lists the links.

Word copies are a separate choice and are off unless you ask for them. You can have either, both or neither, and change your mind at any time: "Stop keeping Google Docs", or "Make Word copies too".

## What you need

One of these two.

**The Google Cloud command line, `gcloud`.** Install it from Google, then sign in once with Drive access:

```bash
gcloud auth login --enable-gdrive-access
```

Your assistant never sees your password, and Training Studio never stores the sign-in. Each time it talks to Google it asks `gcloud` for a short-lived pass, uses it, and forgets it.

**A Google Drive connector in your assistant.** If your assistant can already create and read Google Docs, it can do the sending and fetching itself. It needs to be able to make a Doc from markdown and read one back as markdown.

If you have neither, your assistant tells you what is missing.

## What happens

**Sending.** The first time, a new Doc is created in your Drive and you get its link. After that, sending again replaces that Doc's content with your file. Training Studio does not share it with anyone; sharing is yours to do.

**Editing.** People edit the Doc directly. Ask them to make real edits, or accept their suggestions before you pull: comments and suggestions in the Doc are not read.

**Pulling.** The Doc's text replaces your file. The version it replaces is kept in the training's history, so you can go back.

A pulled file is a draft again, even if you had approved it, and anything built from it, such as the deck, is marked out of date. That is deliberate: the content changed, so you get to read it and approve it before it counts as finished. Your assistant shows you what changed and asks.

## When both sides changed

If you edited the file and someone edited the Doc since the last time they matched, neither is overwritten.

- Sending is refused until you pull.
- Pulling is refused too, and the Doc's text is put beside your file as `document.remote.md` (or `product-brief.remote.md`, and so on).

Your assistant then shows you the differences, puts what you choose into your file, and sends the result to the Doc. You can delete the `.remote.md` file afterwards.

## The hidden notes in your files

The learner guide and the brief carry short hidden notes under their headings, such as `<!-- covers: O1 K1.1 -->`. They record which objective or research finding each section rests on, and the checks rely on them.

Google Docs drops these notes, so Training Studio keeps them back when it sends and puts each one back under its heading when it pulls. Renumbering a heading is fine. If someone renames or deletes a heading in the Doc, the note that belonged under it has nowhere to go. Your assistant tells you which one, and adds it back where it now belongs.

## Limits

- **Formatting can shift.** Google rewrites markdown when it hands a Doc back. A pulled file can use different list markers, spacing or emphasis from the file you sent, even where the words are the same. Run the checks after a pull; your assistant does this for you.
- **Comments and suggestions are not read.** Only the Doc's actual text comes back.
- **Other hidden notes are not carried across.** Only the `covers` and `findings` notes are kept back and restored.
- **Nothing is deleted or shared for you.** Training Studio never deletes a Doc and never changes who can see it.
- **Not yet checked against a live Google account.** The automated tests use a stand-in for Google. Expect rough edges on a first real run, and please report them.

## For the curious

The link between a file and its Doc is in `.training-studio/google.json` in your training folder: the Doc's ID and address, and a fingerprint of each side as it was when they last matched. Comparing today's file and today's Doc against those fingerprints is how Training Studio knows which side changed. The fingerprint of the Doc is taken from what Google hands back straight after a send, so Google's own reformatting is never mistaken for someone's edit.

The commands your assistant runs are listed in the [Google Docs reference](../skills/training-studio/references/google.md).
