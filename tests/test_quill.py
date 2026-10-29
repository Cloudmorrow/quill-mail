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
        harness.as_user("ada")
        yield harness


def rows(view):
    (cards,) = view.find("cards")
    return [r["fields"] for r in cards["records"]]


def subjects(harness, folder="inbox"):
    return [r["subject"] for r in rows(harness.view("mail", folder=folder))]


def write(harness, to, subject="Lunch?", body="Noon at the usual place?", **more):
    done = harness.act("send", to=to, subject=subject, body=body, **more)
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
        in sam.act("send", to="bob", subject="Hi", body="x").error
    )
    assert "Who is it to" in sam.act("send", to="sam", subject="Hi", body="x").error
    assert sam.act("send", to="kim", subject="Hi").error == "Body is needed"


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


def test_the_inbox_is_a_list_beside_the_open_mail_and_counts_what_is_unread(q):
    sam, kim = q.as_user("sam"), q.as_user("kim")
    write(sam, "kim", subject="One", body="First line\nSecond line")
    write(sam, "kim", subject="Two")
    inbox = kim.view("mail")
    (split,) = inbox.find("split")
    assert split["show"] == "side"
    assert (
        "Inbox · 2" in inbox.buttons
        and "Sent" in inbox.buttons
        and "New mail" in inbox.buttons
    )
    assert f"You are kim@{CLOUD}" in inbox.text()
    (cards,) = inbox.find("cards")
    assert (
        cards["go"] == "mail"
        and cards["param"] == "thread"
        and cards["params"] == {"folder": "inbox"}
        and cards["title"] == "subject"
        and cards["subtitle"] == "who"
        and cards["body"] == "preview"
        and cards.get("current") is None
    )
    assert [r["who"].split(" · ")[0] for r in rows(inbox)] == [f"sam@{CLOUD}"] * 2
    assert all(r["subject"].startswith("● ") for r in rows(inbox))
    assert sorted(r["preview"] for r in rows(inbox)) == [
        "First line",
        "Noon at the usual place?",
    ]
    # Open, the mail is on the right, its card lit, and the count goes.
    first = kim.list(THREAD)[0]
    opened = kim.view("mail", thread=first.id)
    (split,) = opened.find("split")
    assert split["show"] == "main" and opened.find("cards")[0]["current"] == first.id
    assert "Inbox · 1" in kim.view("mail").buttons
    # Sent says who it went to.
    assert [
        r["who"].split(" · ")[0] for r in rows(sam.view("mail", folder="sent"))
    ] == [f"kim@{CLOUD}"] * 2


def test_cc_and_bcc(q):
    sam, kim, ada = q.as_user("sam"), q.as_user("kim"), q.as_user("ada")
    done = sam.act("send", to="kim", cc=q.user, bcc="ada", subject="Quiet", body="Shh")
    assert done.ok, done
    # Kim and the administrator share the thread and see each other; Ada is in it to nobody.
    (shared,) = kim.list(THREAD)
    assert sorted(shared.members) == sorted(["kim", q.user])
    (message,) = kim.list(MESSAGE)
    assert message["to"] == f"kim@{CLOUD}" and message["cc"] == f"{q.user}@{CLOUD}"
    assert "ada" not in kim.view("mail", thread=shared.id).text()
    # Ada has a copy of her own, with the same To and Cc, shared with nobody else.
    (copy,) = ada.list(THREAD)
    assert copy.id != shared.id and copy.members == ["ada"]
    assert ada.list(MESSAGE)[0]["to"] == f"kim@{CLOUD}"
    assert subjects(ada) == ["● Quiet"] and subjects(sam, "sent") == ["Quiet", "Quiet"]


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
    done = sam.act("send", to="ada@example.net", subject="Hi", body="?")
    assert not done.ok and "Administration › Quills › Mail" in done.error
    assert sam.list(THREAD) == []
    # And a name on no host at all is nobody here.
    assert (
        "Nobody here is called kim@elsewhere"
        in sam.act("send", to="kim@elsewhere", subject="Hi", body="?").error
    )
    # Ordinary people are told the server has no domain; an administrator, where to set it up.
    assert "an administrator can give it a domain" in sam.view("mail").text()
    assert "Administration › Quills › Mail" in q.view("mail").text()
