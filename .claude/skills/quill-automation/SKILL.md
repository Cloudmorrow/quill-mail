---
name: quill-automation
description: Make a Quill do things by itself — hooks when records change, jobs on a clock, webhooks from outside services, APIs for other programs, fetching from the internet and reading the person's secrets. Use for "when X happens, do Y", "every night", "when Stripe calls", "call this API".
---

# Code that runs by itself

All of it is declared in quill.toml and written in quill.py, and all of it
runs in the sandbox, reaching only what the manifest declares.

## Hooks: when a record changes

```toml
[[hooks]]
on = "fleet.visit"
when = "created"            # created, changed, deleted, or a list; all three by default
fields = ["km"]             # optional, for "changed": only when one of these changed
handler = "visit_logged"
```

```python
@hook
def visit_logged(ctx, change):
    visit = change.record  # change.action, change.before (old fields), change.changed
    van = ctx.records.get("vehicle", visit["vehicle"])
    ctx.records.patch("vehicle", van.id, {"fleet.odometer": visit["km"]})
```

A hook runs as whoever made the change, shortly after it, never in the way
of the write. It is not told about what its own hooks wrote, and chains stop
three deep: do not build ping-pong between two Quills.

## Asking somebody responsible: roles and approvals

Say which role the Quill expects, and the server makes it, empty, at install;
an administrator picks who holds it (docs/FLOWS.md):

```toml
[[roles]]
id = "team_lead"
label = "Team lead"
why = "to approve or decline time off"
```

```python
@action
def request(ctx, what):
    leave = ctx.records.create("leave", what=what, ...)
    asked = ctx.approvals.ask(leave, role="team_lead", question=f"Approve {what}?")
    return [toast("Asked the team lead"), result(leave=leave.id, approval=asked.id)]
```

Whoever holds the role finds it under *Waiting for you* and answers; the
answer is a change to the `approval` record, heard as a hook (list
`approval` in `[uses]` to read it; asking needs nothing declared):

```toml
[[hooks]]
on = "approval"
when = "changed"
fields = ["status"]
handler = "answered"
```

`ctx.people(role="team_lead")` is who holds it; `ctx.user.roles` what the
person the code runs for holds. `result(**values)` from an action is for
a *flow* that pressed it — a procedure a person builds on a screen out of
Quill actions, approvals and record changes, with no code of its own.

## Jobs: on a clock

```toml
[[jobs]]
id = "nightly"
action = "call"
handler = "nightly"
every = "1d"                # 15m, 1h, 1d, 2w
```

A `call` job runs as the administrator who installed the Quill, never twice at once.
For plain expiry use the declarative `action = "expire"` instead — no code.

## A program the server does not have

A `[[services]]` program that needs ffmpeg, or any other binary, names it and
the install brings it — nobody runs `apt` on the server, and the server
cannot either:

```toml
[requires]
runtimes = ["ffmpeg"]       # ids from the catalog's [runtimes]; first on the service's PATH
```

The install sheet says *Adds to this server: ffmpeg 7.1.5 · 119 MB* before
the yes; removing the last Quill that needs it asks whether it goes too. A
runtime the catalog does not list is a pull request to Cloudmorrow/quill-catalog
with a build per OS and architecture and its SHA-256. In the service, call
the program by name (`shutil.which("ffmpeg")` finds it) and still say
something sensible on a clip when it is missing. With ffmpeg on the server,
a video file has a thumbnail too (`ui.image(record=…)`, `ui.gallery`), so a
Quill that only shows videos may require it without a service.

## Another Quill it works with

A Quill built on top of another one — an editor for what a library holds —
names it, and installing it installs that one first, from the catalog:

```toml
[requires]
quills = ["media"]          # Quill ids; installed with it, kept while it is here
```

The install sheet says *Installs with it: Media*. The other one cannot be
removed while this one is here; it does not know about this one, and works
alone. Each Quill still declares the datamodels it uses in `[uses]`.

## Webhooks: something outside tells you something

```toml
[[webhooks]]
id = "stripe"
handler = "stripe_paid"     # or `model` + `map` to make a record with no code at all
signature = "Stripe-Signature"   # optional: an HMAC of the body instead of the token
```

```python
@webhook
def stripe_paid(ctx, request):  # request.json(), .text, .headers, .query
    ...
    return respond(json={"ok": True})  # or nothing: 204
```

It is at `POST /hooks/<quill>/<path>` with the webhook's secret, which an
administrator copies from Administration → Quills.

## APIs: for other programs

```toml
[[apis]]
id = "summary"
handler = "summary"         # GET/POST/… /api/q/<quill>/<path>, for anybody signed in
```

```python
@api
def summary(ctx, request):  # request.method, .path, .user (who asked)
    return {"vans": len(ctx.records.list("vehicle"))}  # a dict is sent as JSON
```

## The internet, and secrets

```toml
[[fetch]]
host = "api.example-tracker.com"        # or *.example.com; https only
why = "to read each van's odometer"

[[secrets]]
key = "TRACKER_KEY"
why = "to sign in to the tracker"
```

```python
answer = ctx.fetch(
    "https://api.example-tracker.com/vans", headers={"Authorization": "Bearer " + ctx.secret("TRACKER_KEY")}
)
if answer.ok:
    data = answer.json()
```

A secret comes from the person's own vault (`cm secret set TRACKER_KEY`),
and never when an assistant pressed the action.

## Test it

`q.run_job("nightly")`, `q.webhook("stripe", json={...})`, `q.api("summary")`,
`q.fetch.add("https://api.example-tracker.com/vans", json=[...])`, `q.secret("TRACKER_KEY", "x")`,
and `q.log` for what the code printed. A hook runs by itself in the harness
when a record changes (`q.seed`, `q.change`, `q.act`).
