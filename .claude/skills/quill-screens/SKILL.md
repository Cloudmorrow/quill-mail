---
name: quill-screens
description: Build or change a Quill's interface — a kit screen in quill.toml, or a view drawn by quill.py from Cloudmorrow's primitives (stack, table, cards, lanes, stat, button, form…). Use whenever the task is about what a screen shows, how it is laid out, or what can be pressed on it.
---

# Building a Quill's screens

A Quill never ships HTML, CSS, JavaScript or terminal code. Every screen is
drawn by Cloudmorrow on the phone, the web app and the terminal, and printed
by `cm <quill>`. You choose *what* is drawn; each surface decides *how*.

## First: kit screen or view?

Prefer a **kit screen** — pure TOML, no code, and the richest widget on every
surface. Reach for a **view** only when no kit element says it.

| the person needs | use |
| --- | --- |
| a list to tick off, grouped by something | `kit = "list"` (`tick`, `group`, `subgroup`) |
| cards moved between columns | `kit = "board"` (`lane`, `group`, `subtitle`) |
| columns people add, rename and reorder (a pipeline's stages) | `kit = "board"` with `lane` a **link** to the records that are the columns |
| things on days | `kit = "calendar"` |
| a conversation | `kit = "thread"` |
| a team's conversation: threads, @mentions, reactions, pinned lines | `kit = "thread"` with `reply_to`, `mentions`, `reactions`, `pinned` |
| pages of Markdown in folders | `kit = "editor"` |
| a small spreadsheet: cells, numbers, formulas, with Excel files read and written | `kit = "sheet"` over the `.cell` and `.xlsx` files in a folder of the drive (`suffix = [".cell", ".xlsx"]`), as an editor is over `.md` files; Open from anywhere and Export as Excel, PDF or CSV come with it (docs/CELLS.md in the Cloudmorrow repository) |
| documents: a basic Word, with Word files read and written | `kit = "document"` over the `.docs` and `.docx` files in a folder of the drive (`suffix = [".docs", ".docx"]`); Open from anywhere and Export as Word, PDF or Markdown come with it (docs/DOCS.md in the Cloudmorrow repository) |
| files | `kit = "grid"` |
| editing video: clips on video and audio tracks, cut, moved, blurred, exported | `kit = "timeline"` (docs/TIMELINE.md in the Cloudmorrow repository) |
| a summary, a dashboard, numbers, a mix of the above, a record's own page | a **view** |

The kit's bindings are in CLAUDE.md ("The kit"). Every kit screen already
opens a record sheet, with every field editable and every action on that
datamodel as a button.

## A view

Declare it, then write the function it names:

```toml
[[screens]]
id = "garage"
label = "Garage"
view = "garage"         # a @view in quill.py
model = "vehicle"       # what it is about: someone whose circles hide vehicles never sees it
```

```python
from cloudmorrow.quill import ui, view


@view("garage")
def garage(ctx):
    vans = ctx.records.list("vehicle")
    due = [v for v in vans if (v.get("fleet.odometer") or 0) > 30000]
    return ui.stack(
        ui.row(ui.stat("Vans", len(vans)), ui.stat("Due a service", len(due), tone="warn")),
        ui.table(vans, columns=["name", ("Odometer", "fleet.odometer")], actions=["log-service"], empty="No vans yet."),
        ui.button("Add a van", action="add-van", tone="primary"),
    )
```

A view is called every time it is shown, and again after every action
pressed on it, as the person looking — so it only ever sees their records.
Keep it quick: list what you need, filter on indexed fields
(`ctx.records.list("task", lane="doing")`), and compute the rest in Python.

## The primitives (`cloudmorrow.quill.ui`)

| primitive | for |
| --- | --- |
| `stack(*children)` / `row(*children)` / `columns(*children)` | one under another / side by side, wrapping / columns that stack on a phone |
| `tabs(("Open", tree), ("Done", tree))` | a few trees behind tabs |
| `text(s, style=)` | `body`, `title`, `subtitle`, `muted`, `small`, `mono` |
| `markdown(s)` | formatted text |
| `stat(label, value, hint=, tone=)` | a number worth a glance |
| `badge(s, tone=)` | a status word |
| `empty(s, action=, label=)` | what a list says when there is nothing, and what to do |
| `divider()` | a line |
| `image(record=…)` or `image("https://…")` | a picture: a file record, or an https address |
| `table(records, columns=[…], actions=[…], open=True)` | records, a row each; `actions` are action ids pressed per row |
| `cards(records, title=, subtitle=, body=, badge=)` | records, a card each (field names) |
| `gallery(records, title=, subtitle=, badge=, stars=, rate=, actions=[…])` | files as picture tiles (a video's picture is a frame of it); `stars` names a 0–5 field drawn as stars, and pressing one runs the `rate` action with `stars=` |
| `lanes(records, field=, title=)` | cards in columns by an enum field; dragging moves them |
| `month(records, date=, title=)` | records on a month |
| `field(record, name, edit=True)` | one field of one record, editable in place |
| `form(action, values=…)` | an action's form, drawn in place |
| `button(label, action=… \| open=record \| go=screen, tone=)` | does one thing |
| `menu(label, *buttons)` | several things behind one button |

Tones: `neutral`, `info`, `good`, `warn`, `bad`, `primary`, `danger`. Use
`primary` for the one thing most people come to do, and only once per view.

`None` and `False` children are dropped, so `cond and ui.text(...)` reads
naturally. A plain string child is `ui.text(string)`.

## What can be pressed

Everything that does something runs an **action** the manifest declares
(see the quill-actions skill), opens a record, or goes to another screen of
this Quill (`go="detail", params={"van": van.id}`; the other view reads
`ctx.params.van`). A button naming an action or screen that is not declared
is refused when the view is drawn — so the manifest stays the whole list of
what a Quill can do.

A view opened on one record (from `go`, or a record's sheet) has it in
`ctx.params.record`.

## Check it

- `cm quill check` — the manifest, and a sketch of every screen.
- `cm quill preview garage` — the view drawn as text, with the Quill's datasets.
- `cm quill dev --local` — the real thing in a browser, on the phone and in `cm`.
- In a test: `q.view("garage").text()`, `.find("stat")`, `.buttons`.

## Don't

- Don't build HTML or ASCII art in `text()`; compose primitives.
- Don't draw a screen per record type when a kit list would do.
- Don't hide an action only in a view: declare it `on` its datamodel and it
  is on the record's sheet everywhere, on the command line and for the assistant too.
