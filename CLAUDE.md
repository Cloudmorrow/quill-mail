# Working on this Quill

This repository is a Cloudmorrow **Quill**: a package that adds data, screens
and what can be done with them to somebody's own cloud. It is TOML and
Python and nothing else: `quill.toml` declares everything the Quill is and
does, and `quill.py`, once it needs code, holds what its views, actions,
hooks, jobs, webhooks, APIs and machine handlers run. Cloudmorrow draws every screen, on
the phone, the web app and the terminal — there is no HTML, CSS or
JavaScript here, and there must never be.

The skills in `.claude/skills/` cover each part in depth: **quill-screens**
(kit screens and views), **quill-actions**, **quill-data**,
**quill-automation** (hooks, jobs, webhooks, APIs, fetch, secrets),
**quill-machine**, **quill-testing** and **quill-publish**. Use them.

When asked to change or extend it:

1. Read `quill.toml`, `quill.py`, `datamodels/` and the reference below.
2. Declare first: a kit screen, a datamodel field, a declarative job or
   webhook needs no code. Prefer extending a foundational datamodel over
   introducing a new one.
3. Then Python, for what cannot be declared: every handler is named in
   `quill.toml` and registered in `quill.py` with a decorator.
4. Write or change a test in `tests/` for it (the quill-testing skill).
5. Run `cm quill check`, then `cm quill test`, then `cm quill test --sandbox`,
   and fix everything they say until they pass. `cm quill preview <view>`
   draws a view as text; read it.
6. For the person to look at it: `cm quill dev --local` (a throwaway server
   on this machine), or `cm quill dev` (their own server).
7. Keep README.md's "What it adds" table true.

The first time, `uv sync` makes `.venv` with Cloudmorrow and pytest in it.

# Writing a Quill

A Quill is a Cloudmorrow software package: one folder (one repository) with a
`quill.toml` at its root, and a `quill.py` when it has code. The manifest
declares data, screens and what can be done; the Python does what cannot be
declared, in a sandbox, through the same gate as everybody. The same Quill
is drawn on the phone, the full web app and the terminal, is a `cm <quill>`
command, and is tools for an assistant. You never write UI code: screens
are kit elements, or views built from primitives every surface draws.

## The loop

1. `cm quill check` — validate the manifest against the datamodels, and see a
   text preview of each screen. Fix what it says; it says it plainly.
2. `cm quill test` — `tests/` with pytest, against the real record store and
   gate (`cloudmorrow.quill.testing.Harness`); `--sandbox` runs `quill.py` in
   the sandbox, as a server does.
3. `cm quill preview <view>` draws a view as text; `cm quill dev --local` is a
   throwaway server on this machine, reinstalled as you save; `cm quill dev`
   installs this folder on your own server as a development Quill.
4. Tag a release (`v1.0.0`); the first time, open a pull request on
   `Cloudmorrow/quill-catalog` adding the Quill to `catalog.toml`; after
   that the catalog follows your releases by itself.

Over MCP an assistant has the first loop: `quill_schema`, `quill_check`,
`quill_dev_install`. An administrator's assistant builds the server's
Quill; anybody else's builds one of their own — on their shelf alone, over
their own data, run as them — which may add no fields to shared datamodels,
run no services, and keep personal records only (its own datamodels are
named after them on the server; the code uses the names written here).
`quill_share` offers it to people; `quill_request` asks an administrator for
a Quill, or for one of theirs to be promoted for everyone.

## quill.toml

```toml
[quill]
id = "plants"                      # lowercase, 2-32 of a-z 0-9 _
name = "Plants"
version = "1.0.0"                  # major.minor.patch
summary = "Your plants, and when you last watered each."
category = "home"                  # home, personal, business, developer, …
icon = "plants"                    # from the icon library (cloudmorrow.com/resources/icons), or the app's own
publisher = "you"
license = "MIT"
features = ["One line per thing it does, for the catalog"]

[uses]
datamodels = ["task"]              # foundational datamodels, by id

[[extends]]                        # your own fields on a foundational datamodel
model = "task"
[extends.fields]
room = { kind = "string", indexed = true }      # stored as "plants.room"

[[grants]]                         # anything else you read or write, with a reason
model = "contact"
access = "read"                    # read or write
why = "to show who looks after each plant"

[[screens]]                        # the Quill is one tab, on every surface; its screens are the items under it
id = "plants"
kit = "list"                       # list, board, detail, form, calendar, grid, editor, sheet, thread, timeline
label = "Plants"
icon = "plant-pot"                 # the item's own mark, from the library: no two screens look alike
model = "plants.plant"
title = "name"
subtitle = "last_watered"
tick = "healthy"                   # a bool field: a circle on each row

[[jobs]]                           # work the core does for you
id = "forget-dead"
action = "expire"                  # delete records whose `field` is older than `after`
model = "plants.plant"
field = "died_at"
after = "30d"
every = "1d"

[[datasets]]                       # records that come with the Quill
id = "first-plant"
model = "plants.plant"
seed = "per-owner"                 # once for each person who has none; "once" for the
                                   # server; "per-space" in every space with none
records = [{ name = "{owner}'s first plant" }]
# or: file = "datasets/plants.csv"  (CSV with a header row, or TOML [[records]])
```

## Code: quill.py

When declaring is not enough, the manifest names Python functions, and
`quill.py` (or a `quill/` package) has them, each registered with a
decorator from the SDK, `cloudmorrow.quill`. The server runs them in a
sandbox — CPython compiled to WebAssembly: no files, no sockets, no
processes, only the standard library and the SDK — and every record they
touch goes through the gate, as the principal the table says:

| declared as | written as | runs as | returns |
| --- | --- | --- | --- |
| `[[screens]] view = "garage"` | `@view("garage") def garage(ctx)` | the person looking | a tree of primitives |
| `[[actions]]` | `@action("log_service") def log_service(ctx, [record,] **fields)` | the person pressing | effects |
| `[[hooks]] on, when, handler` | `@hook def h(ctx, change)` | whoever made the change | nothing |
| `[[jobs]] action = "call", handler, every` | `@job def j(ctx)` | the installing administrator | nothing |
| `[[webhooks]] handler` | `@webhook def w(ctx, request)` | the installing administrator | `respond(...)` or a dict |
| `[[apis]] handler, prefix` | `@api def a(ctx, request)` | the installing administrator | `respond(...)` or a dict |
| `[[machine]]` | `@machine def m(ctx)` | the machine's owner, on their machine | JSON |

```toml
[quill]
code = "quill.py"                  # needed as soon as anything names a handler

[[screens]]
id = "garage"
label = "Garage"
view = "garage"                    # instead of kit = …
model = "vehicle"                  # optional: circles fit it by this

[[actions]]
id = "log-service"                 # its button, `cm fleet log-service`, and an assistant's tool
label = "Log a service"
on = "vehicle"                     # optional: done to one record; the handler gets it first
confirm = "Log it?"                # optional; tone = "primary" | "danger"; assistant = false
[actions.fields]                   # its form, checked before the code runs
date = { kind = "date", required = true }
km = "int"

[[hooks]]
on = "fleet.visit"
when = ["created"]                 # created, changed, deleted
fields = ["km"]                    # optional: for changed, only these
handler = "visit_logged"

[[fetch]]                          # https hosts ctx.fetch may reach
host = "api.example.com"
why = "…"

[[secrets]]                        # keys ctx.secret may read from the person's vault
key = "TRACKER_KEY"
why = "…"

[[machine]]                        # runs on a person's machine, once they switch it on there
id = "import"
why = "…"
every = "15m"
[machine.needs]
folders = [{ name = "exports", access = "read" }]
# run = ["lp"]                     # programs already there it may start, if the machine allows them
# runtimes = ["ffmpeg"]            # programs the agent fetches for it on that machine, from the catalog
```

```python
from cloudmorrow.quill import action, hook, view, ui, toast, error, open, go, confirm, respond


@view("garage")
def garage(ctx):
    vans = ctx.records.list("vehicle")
    return ui.stack(
        ui.row(ui.stat("Vans", len(vans))),
        ui.table(vans, columns=["name", ("Odometer", "fleet.odometer")], actions=["log-service"]),
        ui.button("Add a van", action="add-van", tone="primary"),
    )


@action("log_service")
def log_service(ctx, vehicle, date, km):
    ctx.records.create("fleet.visit", vehicle=vehicle.id, date=date, km=km)
    return toast(f"Logged {vehicle['name']} at {km} km")
```

`ctx`: `ctx.user` (`.username`, `.name`, `.admin`, `.circles`), `ctx.params`
(a view's; `.record` when opened on one), `ctx.records` (`list(model, q=,
**where)`, `get`, `create(model, fields=None, **values)`, `patch(model, id,
fields)`, `move`, `delete` — each a `Record`: fields by `record["name"]`,
envelope as `.id`, `.rev`, `.model`), `ctx.fetch(url, method=, headers=,
json=)`, `ctx.secret(key)`, `ctx.now()`, `ctx.log(...)`, and on a machine
`ctx.records.create(..., scope=, members=)` makes a space, shared with its
members; `ctx.records.seen(model, id)` is the person having looked in one;
`ctx.people()` is everybody on the server but them. `ctx.folder(name)` and
`ctx.run([...])` (a program in `needs.run` the machine
allows, or one of a runtime in `needs.runtimes`). A refusal raises `Refused`,
`NotFound`, `Invalid` or `Conflict`. `print` goes to the Quill's log
(`cm quill logs <quill> code`).

Primitives (`ui.`): `stack`, `row`, `columns`, `tabs`, `text(style=)`,
`markdown`, `image`, `badge`, `stat`, `empty`, `divider`, `field(record,
name, edit=)`, `form(action)`, `button(label, action= | open= | go=)`,
`menu`, `table(records, columns=, actions=, go=, param=)`, `cards(records,
title=, …, go=, param=)` (a row or a card opens its sheet, or with `go` a
screen of the Quill's own, the record's id as `param`),
`gallery(records, title=, subtitle=, badge=, stars=, rate=, actions=)` (files
as picture tiles with five stars; a star runs `rate` with `stars=`),
`lanes(records, field=, title=)`, `month(records, date=, title=)`. Every
button runs a declared action, opens a record, or goes to a declared screen.

Effects: `toast(text)`, `open(record)`, `go(screen, **params)`,
`confirm(text, then=action, **fields)`, `error(text)`; an API or webhook
returns `respond(json=… | text=…, status=)`.

Tests: `from cloudmorrow.quill.testing import Harness`; `q = Harness(".")`;
`q.seed(model, **fields)`, `q.act(action, record, **fields)` (→ `.ok`,
`.toast`, `.error`, `.refused`), `q.view(screen).text()`,
`q.as_user(name, circles=[...])`, `q.run_job`, `q.webhook`, `q.api`,
`q.machine(id, folders=)`, `q.fetch.add(url, json=)`, `q.secret(key, value)`.

## Services: a program of its own

The last resort, for what the sandbox cannot do: hold a connection open,
run all the time, use a package with C in it. The server runs it outside
the sandbox, as the administrator who installed the Quill, and it reaches
only what the Quill declared:

```toml
[[services]]                       # a program the core starts and keeps running
id = "sync"
command = ["python", "services/sync.py"]   # "python" is the server's own Python
always = true                      # started again if it exits (with backoff)

[[jobs]]                           # or: run a service now and then, never twice at once
id = "nightly"
action = "run"
service = "sync"                   # a service a job names is only started by the job
every = "1d"

[[webhooks]]                       # POST /hooks/<quill>/<path>, with the webhook's secret
id = "inbound"
path = "inbound"
model = "plants.plant"             # the JSON body becomes a record…
map = { name = "$.plant.name" }    # field = a path into the body: $.a.b[0].c
# forward = "sync"                 # …or the request goes to a service instead
# signature = "X-Hub-Signature-256"  # also accept a GitHub-style HMAC of the body

[[apis]]                           # /api/q/<quill>/… proxied to a service (or handler = …)
id = "public"
service = "sync"
# prefix = "v1"                    # only paths under /api/q/<quill>/v1/

[requires]                         # a program a service needs that the server may not have
runtimes = ["ffmpeg"]              # an id from the catalog's [runtimes]; the install fetches
                                   # a checked static build and puts it first on the services' PATH
quills = ["media"]                 # other Quills it works with: installed first, from the catalog,
                                   # and kept while this one is here
```

A runtime is for the services (and ffmpeg also gives every video file a
thumbnail, so a Quill that only shows videos may require it without a
service); it is named on the install sheet with its size before the yes, and is
offered for removal with the last Quill that needs it. Never tell anybody to
`apt install` something: name it in `[requires]` instead, and if the catalog
has no entry for it yet, that is a pull request to Cloudmorrow/quill-catalog
adding `[runtimes.<id>]` with a build per OS and architecture and its SHA-256.

A service is started in the Quill's folder with only these in its
environment — nothing of the server's:

| variable | what |
| --- | --- |
| `CLOUDMORROW_URL` | the server, on loopback |
| `CLOUDMORROW_TOKEN` | the Quill's own token: the record API, its declared datamodels only |
| `CLOUDMORROW_QUILL`, `CLOUDMORROW_SERVICE` | its id, and which service this is |
| `PORT` | a free loopback port to serve on, for an API or a forwarded webhook |
| `HOME` | a folder of its own that survives updates |
| `PATH`, `LANG`, `PYTHONUNBUFFERED` | so programs are found (its runtimes first) and output is logged as it comes |

It uses the record API like any client: `GET/POST /api/records/<model>`,
`GET/PATCH/DELETE /api/records/<model>/<id>`, `POST …/<id>/move`. An API
request arrives at `/<path>` with `X-Cloudmorrow-User: <who is asking>` (never
their token); a forwarded webhook arrives as `POST /hooks/<path>` with
`X-Cloudmorrow-Webhook: <id>`, its secret already checked. What it prints goes
to its log (`cm quill logs <quill> <service>`). Only the standard library is
certain to be there. A whole service, `services/sync.py`:

```python
import json, os, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

URL, TOKEN = os.environ["CLOUDMORROW_URL"], os.environ["CLOUDMORROW_TOKEN"]


def records(method, path, body=None):
    request = urllib.request.Request(
        URL + "/api/records/" + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as answer:
        return json.loads(answer.read() or b"null")


class Api(BaseHTTPRequestHandler):
    def do_GET(self):  # GET /api/q/plants/count
        who = self.headers["X-Cloudmorrow-User"]
        body = json.dumps({"asked_by": who, "plants": len(records("GET", "plants.plant"))})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())


print("up", flush=True)  # into its log
ThreadingHTTPServer(("127.0.0.1", int(os.environ["PORT"])), Api).serve_forever()
```

The records it reads and writes are the installing administrator's; a service
per person is not there yet.

## Datamodels you introduce

One TOML file each, in `datamodels/`, with an id under your Quill's. The
full contract for data — field kinds, versions, extension fields, spaces,
who may see and change what — is `docs/DATAMODELS.md` in the Cloudmorrow
repository; the foundational datamodels are at cloudmorrow.com/datamodels.

```toml
[datamodel]
id = "plants.plant"
version = 1
label = "Plant"
description = "A plant you look after."
scopes = ["personal"]              # personal only, for now
title = "name"                     # what a record is called in a list
# ordered_within = ["room"]        # keep a position inside each group (boards need it)

[fields]
name = { kind = "string", required = true }
room = { kind = "enum", values = ["kitchen", "bedroom"], labels = ["Kitchen", "Bedroom"], indexed = true }
healthy = { kind = "bool", default = true, indexed = true }
last_watered = { kind = "date", indexed = true }
died_at = { kind = "datetime", indexed = true, stamp = { field = "healthy", value = "false" } }
notes = { kind = "markdown" }
owner = { kind = "link", to = "contact", on_delete = "clear" }
```

Field kinds: string, text, markdown, bool, int, decimal, date, datetime, enum,
email, phone, url, link, json. `indexed` fields are plain on disk so the server
can filter and sort by them; everything else is encrypted at rest. Links are
record ids and are always indexed. `on_delete` is `cascade` or `clear`.
A datetime without a zone is the wall clock, kept as typed; a bare date is a
whole day. Filter a list with `?field=value`, or a range with `__lt`,
`__lte`, `__gt`, `__gte` on an indexed field.
`stamp` sets a datetime when another field takes a value and clears it when it
leaves. `secret = true` on a string or text field keeps it out of every listing
and has every surface draw it hidden until asked for.

## The kit

| kit | needs | draws |
| --- | --- | --- |
| list | model, title; optional subtitle, tick (bool), fields (the sheet's), group and subgroup (link, enum or indexed string); projects: vault (a string: the vault its secrets are in), repo (url) and env_files (json: which .env file each environment came from) | rows, a circle per row if tick; chips (phone, web) or a list and buttons (terminal) to pick the group and subgroup; a list of `secret` has Import .env and Export .env; a list of projects has their environments on the sheet, and init, update, clone in the terminal and on the command line |
| board | model, lane (in ordered_within: an enum, or a link to the records that are the lanes — in their order, and on a board with a group only those linking to it), title; optional group (link: chips), subtitle (a field, or a list of them, under a card's title), body (markdown), done (a lane value; for record lanes what the lane has: `{ outcome = "won" }`) | lanes; cards dragged between them |
| detail / form | model; optional fields = [...] | one record's fields, editable |
| calendar | model, starts, ends (indexed datetime/date), space (a link to a space datamodel); optional all_day (bool), colour (a field of the space), subtitle | every space's things at once: a month, a week, the day's list; the spaces and their people |
| editor | model, title, body (markdown); optional path (a string like folder/sub/title: the folders) | a tree of folders and records beside a page of Markdown; pictures where the backend keeps attachments |
| sheet | model (the foundational `file`), title, cells (the text field a `.cell` file's text is in: one JSON object, `{"cells": {"A1": "Rent", "B4": "=SUM(B1:B3)"}}`), path, and where and suffix as an editor's (`where = { share = "my-files", within = "Documents" }`, `suffix = [".cell", ".xlsx"]`: an Excel file is read and written as the same text) | a spreadsheet over the .cell (and Excel) files in a folder of the drive: the sheets, then one as a grid with a formula bar; Excel's formulas (SUM, IF, ROUND, …), worked out the same on every surface; Open from anywhere on the cloud, Export as Excel, PDF or CSV (docs/CELLS.md) |
| document | model (the foundational `file`), title, body (the text field a `.docs` file's text is in: one JSON object, `{"blocks": [{"kind": "heading", "level": 1, "runs": [{"text": "Hi"}]}]}`), path, and where and suffix as an editor's — suffix may be a list, `[".docs", ".docx"]`: a Word file is read and written as the same text | a page of words over the .docs (and Word) files in a folder of the drive: headings, paragraphs, lists, quotes, tables, bold/italic/underline/strike/links; the editor's list, a page with a bar of styles; Markdown in the terminal; Open from anywhere on the cloud, Export as Word, PDF or Markdown, import from Word (docs/DOCS.md) |
| grid | a model with bytes beside its fields (the foundational `file`); group (link: the places, picked first), folder (string), kind (an enum with "folder"); optional size, modified, mime, deleted and deleted_from (a datetime and a string: when a record went to the Trash and where from — Restore instead of Rename and Move, and Delete for good), group_subtitle, group_open and group_writes (fields of the group's model; group_open and group_writes are bools: false and the group is listed but not opened, or opened with nothing that writes) | the groups, then folders and tiles with pictures; put in, get, new folder, rename, move, delete (to the Trash), restore |
| thread | model (in a space), space (its link to the space), body; optional about (a field of the space), made_as; a team's: reply_to (a link of the model to itself: a reply, in a thread under its parent), pinned (a bool: kept at the top; `managed` in the datamodel lets the space's manager pin), reactions (a datamodel of the Quill's with a link to the model, an `emoji` string, authored: one per person per emoji per line, toggled), mentions = true (@name lights up and tells that person) | the spaces with unread counts, then a conversation: newest at the bottom, grouped by author and day, a box to write in; threads beside it, reactions under each line, pinned lines in the header |
| timeline | model (a project: width, height, fps, tracks; optional crop, status, message, output), pieces (a datamodel with one link to the project: track, source, name, start, offset, length; optional volume, muted), media (where the material is: `{ share = "my-files", within = "Videos" }`); optional effects (a datamodel with one link to the pieces: kind, label, keyframes; optional strength), frames (an `[[apis]]` id that draws frames), export (an action on the project) | a video editor: material from the drive, video and audio tracks with pieces to move, trim and split, blurs that move by keyframes, a crop, export; live with sound on the web, real frames in the terminal (docs/TIMELINE.md) |

A thread's `made_as` says what fields a space gets for how it is made — by
scope, or `direct`: a shared space found-or-made between you and the person
you pick, named for them (its fields must be indexed):

```toml
[screens.made_as]
public = { kind = "public" }
shared = { kind = "private" }
direct = { kind = "direct" }
```

A list that binds `vault` is projects on your machines: `cm <quill> init
[--path DIR]` makes a folder one and reads every `.env*` file into its
vault (`.env.prod` is `prod`, `.env` is `local`; examples and files git
tracks are left alone), `update [project]` pulls it and writes the files
back from the vault, `clone <project> [DIR]` puts it on a new machine, and
`secrets [import|export] [project] [-e ENV] [-f FILE]` moves one file or all.

On the command line a thread is `cm <quill> list` (the spaces, with unread),
`show <space>` and `say <space> "text"`; with the team's bindings also
`reply <space> <line> "text"`, `react <space> <line> 👍`, `pin <space> <line>`
and `show <space> --thread <line>`, a line named by the start of its id as
`show` prints it in the margin.

Every screen opens a record sheet when a row or card is chosen: every field,
with the widget for its kind, editable, with delete. An editor opens its page
instead. No other UI exists, on
purpose: what the kit cannot say, the kit grows to say, for every Quill at once.

## Rules

- Never ship UI code, HTML, CSS or JavaScript. Use the kit, or a view of primitives.
- Declare first; Python for what cannot be declared; a service last.
- Every handler is named in the manifest, and every button in a view runs a
  declared action or goes to a declared screen.
- Never invent a second kind of something that is already a datamodel; extend it.
- Extension fields cannot be required.
- Everything you read or write that you did not introduce is in `[uses]`,
  `[[extends]]` or `[[grants]]`.
- Uninstalling a Quill never deletes records.
- A Quill of one person's own: no `[[extends]]`, no `[[services]]`, and
  `scopes = ["personal"]` on what it introduces, which is never a space.
