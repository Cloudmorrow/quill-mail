---
name: quill-actions
description: Add or change something a person can do in a Quill — an [[actions]] entry with its form, and the Python that runs when it is pressed, with its toast, open, go, confirm and error effects. Use for any button, command or "when I click X" behaviour.
---

# Actions: what happens when somebody presses something

One declaration is a button on every surface, a `cm <quill> <action>`
command and a tool for the person's assistant.

```toml
[[actions]]
id = "log-service"             # lowercase and -; also its cm command
label = "Log a service"        # what the button says
on = "vehicle"                 # optional: done to one record of this datamodel
tone = "primary"               # neutral (default), primary, danger
confirm = "Log it?"            # optional: asked before it runs
description = "…"              # optional: more words, for the assistant's tool
assistant = true               # false keeps it from assistants
[actions.fields]               # its form: the same field kinds as a datamodel's
date = { kind = "date", required = true }
km = { kind = "int", required = true }
note = "text"                  # shorthand for { kind = "text" }
```

The handler is `id` with `-` as `_`, unless `handler = "…"` says otherwise:

```python
from cloudmorrow.quill import action, toast, error, open, go, confirm


@action("log_service")
def log_service(ctx, vehicle, date, km, note=None):
    if km < (vehicle.get("fleet.odometer") or 0):
        return error("That is fewer kilometres than it has done already")
    ctx.records.create("fleet.visit", vehicle=vehicle.id, date=date, km=km, note=note or "")
    return toast(f"Logged {vehicle['name']} at {km} km")
```

- An action `on` a datamodel gets that record first (a `Record`: fields by
  `record["name"]` or `.get()`, and `.id`, `.rev`, `.model`), then its form's
  fields as keyword arguments. Without `on`, only the fields.
- The form is checked before your code runs: required fields, kinds, enum
  values, links to records the person can see. Give optional fields a default.
- It runs as the person who pressed it. What they may not do, the gate
  refuses (`ctx.records…` raises `Refused`); you do not need to check.

## Effects: what happens next

Return nothing (the screen is drawn again), one effect, or a list:

| effect | does |
| --- | --- |
| `toast("Saved")` | a line that goes away |
| `open(record)` | the record's sheet |
| `go("garage", van=van.id)` | another screen of this Quill, with `ctx.params` |
| `confirm("Delete all?", then="clear-all", keep=True)` | ask, then press another action with those fields |
| `error("That van is sold")` | the form stays open with this under it |

## Test it

```python
def test_logging(q):
    van = q.seed("vehicle", name="Van")
    done = q.act("log-service", van, date="2026-09-28", km=1200)
    assert done.ok and done.toast == "Logged Van at 1200 km"
    assert q.act("log-service", van, date="2026-09-28").error == "Km is needed"
    assert q.as_user("sam", circles=["Kids"]).act("log-service", van, date="2026-09-28", km=1).refused
```

On the command line: `cm fleet log-service Transit date=2026-09-28 km=1200`.
