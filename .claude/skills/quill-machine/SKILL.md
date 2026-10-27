---
name: quill-machine
description: Run part of a Quill on a person's own computer — a [[machine]] handler that reads or writes a folder they choose, or starts a program they allow, and writes records back. Use for importing files, local backups, printing, or talking to desktop software.
---

# Code on a person's machine

A machine handler runs in the Cloudmorrow agent on somebody's own computer,
in the same sandbox as on the server — but only after that person switches
it on *on that machine*, and picks the folders it may see.

```toml
[[machine]]
id = "import-exports"
why = "to read the tracker's CSV exports into your vans"   # shown when they switch it on
every = "15m"                # optional; without it, it runs when asked
[machine.needs]
folders = [{ name = "exports", access = "read" }]          # read, or write
run = []                     # programs already on the machine it may start, e.g. ["lp"]; empty is best
runtimes = []                # programs the agent fetches for it there, e.g. ["ffmpeg"]; from the catalog
```

```python
import csv
from cloudmorrow.quill import machine


@machine
def import_exports(ctx):
    made = 0
    for path in sorted(ctx.folder("exports").glob("*.csv")):
        with open(path, newline="") as handle:
            for row in csv.DictReader(handle):
                vans = ctx.records.list("vehicle", registration=row["registration"])
                if vans:
                    ctx.records.create("fleet.visit", vehicle=vans[0].id, date=row["date"], km=int(row["km"]))
                    made += 1
    return {"made": made}  # anything JSON; shown by `cm quill machine run`
```

- `ctx.folder(name)` is the folder the person picked, and the only part of
  their disk the code can see. Write only if the manifest asked for `write`.
- `ctx.records` goes to their server and acts as them, through the gate.
- `ctx.run(["lp", path])` starts a program only if it is in `needs.run` *and*
  the machine allows it (`quill_programs` in its agent.toml). Avoid it when
  you can: it is outside the sandbox.
- A program the machine is unlikely to have (ffmpeg, say) goes in
  `needs.runtimes` instead: the agent fetches the catalog's build for that
  machine when the person switches the handler on, tells them its size
  first, and `ctx.run(["ffmpeg", ...])` then finds it with nothing in
  `quill_programs`. Never tell anybody to install something by hand. A
  runtime the catalog lacks is a pull request to Cloudmorrow/quill-catalog.

The person does:

```
cm quill machine list
cm quill machine enable fleet import-exports --folder exports=~/Tracker
cm quill machine run fleet import-exports
```

## Test it

```python
def test_import(q, tmp_path):
    q.seed("vehicle", name="Van", registration="AB 1")
    (tmp_path / "a.csv").write_text("registration,date,km\nAB 1,2026-09-01,10\n")
    assert q.machine("import-exports", folders={"exports": tmp_path}) == {"made": 1}
```
