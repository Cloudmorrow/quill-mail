---
name: quill-data
description: Decide and change what data a Quill keeps — using, extending or introducing datamodels, fields and their kinds, indexed fields, spaces and scopes, grants, and datasets. Use before adding any new kind of record or field.
---

# A Quill's data

Records belong to the person, never to a Quill. A contact is a contact
whichever Quill made it. So, in this order:

1. **Use** a foundational datamodel if one fits: `[uses] datamodels = ["task"]`.
   `cm quill check` lists them; they come from Cloudmorrow/datamodels.
2. **Extend** it with fields of your own when it almost fits:
   ```toml
   [[extends]]
   model = "vehicle"
   [extends.fields]
   odometer = { kind = "int", indexed = true }    # stored as "fleet.odometer"
   ```
   Extension fields are never required; in code they are `record.get("fleet.odometer")`
   and are written with a dict: `ctx.records.patch("vehicle", id, {"fleet.odometer": 1200})`.
3. **Introduce** a new datamodel only for something that is truly new: a file
   in `datamodels/`, with an id under the Quill's (`fleet.visit`).
4. **Ask** for anybody else's data with a grant, and say why:
   `[[grants]] model = "contact"  access = "read"  why = "…"`.

## Fields

Kinds: `string`, `text`, `markdown`, `bool`, `int`, `decimal`, `date`,
`datetime`, `enum` (`values`, `labels`), `email`, `phone`, `url`, `link`
(`to`, `on_delete = "cascade" | "clear"`), `json`.

- `indexed = true` keeps a field plain so the server can filter and sort by it
  (`ctx.records.list("task", lane="done")`, `due__gte="2026-10-01"`).
  Everything else is encrypted at rest. Links are always indexed.
- A `datetime` without a zone is the wall clock, kept as typed; a bare date is a whole day.
- `stamp = { field = "lane", value = "done" }` sets a datetime when another field takes a value.
- `secret = true` on a string keeps it out of every listing, hidden until asked.
- `ordered_within = ["board", "lane"]` keeps a position per group (a board needs it).

## Sharing

A datamodel with `space = true` is a container people share (a calendar, a
channel): `scopes = ["personal", "shared", "public"]`. Things in it say
`in_space = "<link field>"`. See CLAUDE.md, "Spaces". Left empty, that
link keeps the record out of any space: its writer's own, as a personal
record is. A space link is `on_delete = "cascade"`, never `clear`.

## Datasets

Records that come with the Quill: reference data, or a first record per person.

```toml
[[datasets]]
id = "first-list"
model = "shop.list"
seed = "per-owner"          # or "once", for the whole server
records = [{ name = "{owner}'s list" }]
```

`seed = "per-space"`, on a datamodel in a space, writes the records into
every space that has none of them yet — each new book's pipeline stages:

```toml
[[datasets]]
id = "pipeline"
model = "stage"
seed = "per-space"
records = [{ name = "Lead" }, { name = "Won", outcome = "won" }]
```

## Remember

- Uninstalling never deletes records; changing a datamodel later must keep old records readable.
- Everything the code reads or writes must be in `[uses]`, `[[extends]]`, a
  datamodel it introduces, or `[[grants]]` — the gate refuses the rest.
