"""Mail's tests: the real record store, its spaces and gate, and quill.py, on this machine.

`cm quill test` runs them; `cm quill test --sandbox` runs the same tests with
quill.py in the sandbox, as a server runs it. Nothing reaches the network:
the domain's tests (test_domain.py) stub Cloudflare.
"""

import time

import pytest
from cloudmorrow.quill.testing import Harness

THREAD, MESSAGE, STATE = ("mail.thread", "mail.message", "mail.state")
# The harness's server is called Cloudmorrow, so everybody is name@cloudmorrow.
CLOUD = "cloudmorrow"


@pytest.fixture()
def q():
    with Harness(".") as harness:
        harness.as_user("sam")
        harness.as_user("kim")
        yield harness


def rows(view):
    (table,) = view.find("table")
    return [r["fields"] for r in table["records"]]


def subjects(harness, folder="inbox"):
    return [r["subject"] for r in rows(harness.view("mail", folder=folder))]


def write(harness, to, subject="Lunch?", body="Noon at the usual place?", **more):
    done = harness.act("write", to=to, subject=subject, body=body, **more)
    assert done.ok, done
    return next(
        e for e in done.effects if e.get("effect") == "go" or e.get("kind") == "go"
    )


# -- between people on the server ------------------------------------------------------------
def test_writing_to_somebody_by_name_puts_it_in_their_inbox_and_my_sent(q):
    sam, kim = q.as_user("sam"), q.as_user("kim")
    write(sam, "kim", subject="Lunch?")
    (thread,) = kim.list(THREAD)
    assert (
        thread["subject"] == "Lunch?"
        and thread.scope == "shared"
        and thread["kind"] == "internal"
    )
    assert [m["body"] for m in kim.list(MESSAGE, thread=thread.id)] == [
        "Noon at the usual place?"
    ]
    assert subjects(kim) == ["● Lunch?"]  # unread, until opened
    assert subjects(sam) == [] and subjects(sam, "sent") == ["Lunch?"]
    assert q.list(THREAD) == []  # the administrator was not written to


def test_opening_a_thread_reads_it_and_an_answer_is_news_to_the_writer(q):
    sam, kim = q.as_user("sam"), q.as_user("kim")
    write(sam, f"kim, {q.user}", subject="Lunch?")
    (thread,) = kim.list(THREAD)
    opened = kim.view("mail", thread=thread.id)
    assert (
        "Noon at the usual place?" in opened.text()
        and f"With sam@{CLOUD}, {q.user}@{CLOUD}" in opened.text()
        and f"From sam@{CLOUD}" in opened.text()
    )
    # The reply box is under the messages, on the thread itself.
    (form,) = opened.find("form")
    assert form["action"] == "reply" and form["record"]["id"] == thread.id
    assert subjects(kim) == ["Lunch?"]
    time.sleep(1.1)  # what is written is news from the next second on
    assert kim.act("reply", thread, body="Yes!").ok
    assert subjects(sam) == ["● Lunch?"] and subjects(q) == ["● Lunch?"]
    assert [m["sender"] for m in sam.list(MESSAGE, thread=thread.id)] == ["sam", "kim"]
    assert subjects(kim, "sent") == ["Lunch?"] and subjects(kim) == ["Lunch?"]


def test_a_name_nobody_has_is_an_error_and_so_is_nobody_at_all(q):
    sam = q.as_user("sam")
    assert (
        "Nobody here is called bob"
        in sam.act("write", to="bob", subject="Hi", body="x").error
    )
    assert "Who is it to" in sam.act("write", to="sam", subject="Hi", body="x").error
    assert sam.act("write", to="kim", subject="Hi").error == "Body is needed"


def test_archive_trash_and_restore_are_each_persons_own(q):
    sam, kim = q.as_user("sam"), q.as_user("kim")
    write(sam, "kim")
    (thread,) = kim.list(THREAD)
    assert kim.act("archive", thread).ok
    assert subjects(kim) == [] and subjects(kim, "archive") == ["● Lunch?"]
    assert subjects(sam, "sent") == ["Lunch?"]  # sam's filing did not move
    # Somebody writing again brings it back.
    assert sam.act("reply", thread, body="Still on?").ok
    assert subjects(kim) == ["● Lunch?"] and subjects(kim, "archive") == []
    assert kim.act("trash", thread).ok
    assert subjects(kim, "trash") == ["● Lunch?"] and subjects(kim, "sent") == []
    assert kim.act("restore", thread).ok
    assert subjects(kim) == ["● Lunch?"]
    # Only whoever started it deletes it for everybody.
    assert "theirs to delete" in kim.act("delete-forever", thread).error
    assert sam.act("delete-forever", thread).ok
    assert kim.list(THREAD) == [] and sam.list(THREAD) == []


def test_the_inbox_counts_what_is_unread_and_its_rows_go_to_the_thread(q):
    sam, kim = q.as_user("sam"), q.as_user("kim")
    write(sam, "kim", subject="One", body="First line\nSecond line")
    write(sam, "kim", subject="Two")
    inbox = kim.view("mail")
    assert (
        "Inbox · 2" in inbox.buttons
        and "Sent" in inbox.buttons
        and "Write" in inbox.buttons
    )
    assert f"You are kim@{CLOUD}" in inbox.text()
    (table,) = inbox.find("table")
    assert (
        table["go"] == "mail"
        and table["param"] == "thread"
        and table["params"] == {"folder": "inbox"}
    )
    assert [c["label"] for c in table["columns"]] == [
        "From",
        "Subject",
        "Preview",
        "When",
    ]
    assert [r["from"] for r in rows(inbox)] == [f"● sam@{CLOUD}", f"● sam@{CLOUD}"]
    assert sorted(r["preview"] for r in rows(inbox)) == [
        "First line",
        "Noon at the usual place?",
    ]
    # Read, the count goes; Sent says who it went to.
    kim.view("mail", thread=kim.list(THREAD)[0].id)
    assert "Inbox · 1" in kim.view("mail").buttons
    (table,) = sam.view("mail", folder="sent").find("table")
    assert table["columns"][0]["label"] == "To"
    assert [r["from"] for r in rows(sam.view("mail", folder="sent"))] == [
        f"kim@{CLOUD}"
    ] * 2


# -- addresses ------------------------------------------------------------------------------
def test_everybody_is_name_at_the_cloud_and_mail_to_it_stays_here(q):
    sam, kim = q.as_user("sam"), q.as_user("kim")
    write(sam, f"Kim@{CLOUD}", subject="By address")
    (thread,) = kim.list(THREAD)
    assert thread["kind"] == "internal" and thread.scope == "shared"
    (message,) = kim.list(MESSAGE)
    assert message["to"] == f"kim@{CLOUD}"
    assert subjects(kim) == ["● By address"]


def test_mail_to_an_outside_address_needs_the_servers_domain(q):
    sam = q.as_user("sam")
    done = sam.act("write", to="ada@example.net", subject="Hi", body="?")
    assert not done.ok and "Administration › Quills › Mail" in done.error
    assert sam.list(THREAD) == []
    # And a name on no host at all is nobody here.
    assert (
        "Nobody here is called kim@elsewhere"
        in sam.act("write", to="kim@elsewhere", subject="Hi", body="?").error
    )
    # Ordinary people are told the server has no domain; an administrator, where to set it up.
    assert "an administrator can give it a domain" in sam.view("mail").text()
    assert "Administration › Quills › Mail" in q.view("mail").text()
