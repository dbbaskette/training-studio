## The deck's pictures and icons

The slides tool keeps a record of every picture and icon this deck may use, each under an asset ID, with what it shows and where it came from. Your brief names the ones your slides use.

- `list_assets` lists what is recorded: each asset's ID, its kind, what it shows, and whether its file is as it was recorded.
- Place a recorded picture by its asset ID, never by a file: `{"type": "image", "id": "<your ID>", "asset": "<asset ID>"}`. Place an icon as your brief gives it.
- For a slide whose visual is `generated-art`, ask for the picture with `request_asset`: its asset ID, the slide, a brief for the picture, and what it shows. Write the brief from the slide's claim and design. Ask once, and only for an asset your brief names; each request costs money. If the tool cannot make it, draw the rest of the slide and say why when you hand in.
- `request_asset` with an icon's library ID records a brand icon under a new asset ID, for a thing the design does not name.

You cannot add a picture of your own. A picture that is missing is the person's to supply.
