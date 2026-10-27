---
name: quill-testing
description: Test a Quill on this machine — pytest with cloudmorrow.quill.testing.Harness against the real record store and gate, cm quill test (and --sandbox), cm quill preview, and cm quill dev --local. Use after every change to quill.toml or quill.py, and when something does not work.
---

# Testing a Quill

The loop, after every change:

1. `cm quill check` — the manifest as a server would install it. Fix what it says.
2. `cm quill test` — `tests/` with pytest, quill.py in plain Python (tracebacks, a debugger).
3. `cm quill test --sandbox` — the same tests with quill.py in the sandbox, as
   a server runs it. Catches an import the sandbox does not have.
4. `cm quill preview <view>` — a view drawn as text.
5. `cm quill dev --local` — a throwaway server here, reinstalled as you save,
   with two people (you, and sam in a read-only circle). Open the address it
   prints in a browser and on a phone; `cm` with the printed CLOUDMORROW_CONFIG_DIR.

First time: `uv sync` in the Quill's folder (makes .venv with Cloudmorrow and pytest).

## The harness

```python
import pytest
from cloudmorrow.quill.testing import Harness


@pytest.fixture()
def q():
    with Harness(".", circles={"Kids": {"vehicle": "read"}}) as harness:
        yield harness


def test_it(q):
    van = q.seed("vehicle", name="Van")  # a record, made as the person (hooks run)
    done = q.act("log-service", van, date="2026-09-28", km=5)
    assert done.ok and done.toast == "…"  # also .error, .refused, .opened, .effects
    assert q.get("vehicle", van.id)["fleet.odometer"] == 5
    assert "Van" in q.view("garage").text()  # also .find("table"), .buttons, .tree
    kid = q.as_user("sam", circles=["Kids"])  # somebody else, in only these circles
    assert kid.act("log-service", van, date="2026-09-28", km=1).refused
```

Also: `q.list(model, **where)`, `q.change(model, id, **fields)`, `q.delete`,
`q.secret(key, value)`, `q.fetch.add(url, json=…)`, `q.run_job(id)`,
`q.webhook(id, json=…)`, `q.api(path)`, `q.machine(id, folders={…})`, `q.log`.

Code that raises fails the test with `HandlerFailed` and the Quill's own
traceback. A refusal by the gate is not a failure: it is `result.refused`.

## What to test

- Each action: the happy path, a form it must refuse, and somebody who may not.
- Each view: with nothing in it, and with some records — what the person should see.
- Each hook and job: the records after.
- Anything it fetches: with `q.fetch.add(...)` answers, including a failure status.

## When something is wrong

- `q.log` (and `cm quill logs <quill> code` on a server) has what the code printed.
- `Refused … did not ask for contact`: add it to `[uses]` or `[[grants]]`.
- A button "runs X, which the manifest does not declare": declare the action or fix the id.
