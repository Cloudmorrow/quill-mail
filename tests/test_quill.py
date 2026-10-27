"""Mail's tests: the real record store, its spaces and gate, and quill.py, on this machine.

`cm quill test` runs them; `cm quill test --sandbox` runs the same tests with
quill.py in the sandbox, as a server runs it. The provider is a stub: what
`ctx.fetch` gets is put in the test, and nothing reaches the network.
"""

import json
import time

import pytest
from cloudmorrow.quill.testing import Harness

ACCOUNT, THREAD, MESSAGE, STATE = "mail.account", "mail.thread", "mail.message", "mail.state"
SESSION = "https://api.fastmail.com/jmap/session"
API = "https://api.fastmail.com/jmap/api/"
MAILCAP = "urn:ietf:params:jmap:mail"


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
    return next(e for e in done.effects if e.get("effect") == "go" or e.get("kind") == "go")


# -- between people on the server ------------------------------------------------------------
def test_writing_to_somebody_by_name_puts_it_in_their_inbox_and_my_sent(q):
    sam, kim = q.as_user("sam"), q.as_user("kim")
    write(sam, "kim", subject="Lunch?")
    (thread,) = kim.list(THREAD)
    assert thread["subject"] == "Lunch?" and thread.scope == "shared" and thread["kind"] == "internal"
    assert [m["body"] for m in kim.list(MESSAGE, thread=thread.id)] == ["Noon at the usual place?"]
    assert subjects(kim) == ["● Lunch?"]  # unread, until opened
    assert subjects(sam) == [] and subjects(sam, "sent") == ["Lunch?"]
    assert q.list(THREAD) == []  # the administrator was not written to


def test_opening_a_thread_reads_it_and_an_answer_is_news_to_the_writer(q):
    sam, kim = q.as_user("sam"), q.as_user("kim")
    write(sam, f"kim, {q.user}", subject="Lunch?")
    (thread,) = kim.list(THREAD)
    opened = kim.view("mail", thread=thread.id)
    assert "Noon at the usual place?" in opened.text() and f"With sam, {q.user}" in opened.text()
    assert subjects(kim) == ["Lunch?"]
    time.sleep(1.1)  # what is written is news from the next second on
    assert kim.act("reply", thread, body="Yes!").ok
    assert subjects(sam) == ["● Lunch?"] and subjects(q) == ["● Lunch?"]
    assert [m["sender"] for m in sam.list(MESSAGE, thread=thread.id)] == ["sam", "kim"]
    assert subjects(kim, "sent") == ["Lunch?"] and subjects(kim) == ["Lunch?"]


def test_a_name_nobody_has_is_an_error_and_so_is_nobody_at_all(q):
    sam = q.as_user("sam")
    assert "Nobody here is called bob" in sam.act("write", to="bob", subject="Hi", body="x").error
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


def test_the_bar_counts_and_the_rows_go_to_the_thread(q):
    sam, kim = q.as_user("sam"), q.as_user("kim")
    write(sam, "kim", subject="One")
    write(sam, "kim", subject="Two")
    inbox = kim.view("mail")
    assert "Inbox · 2" in inbox.buttons and "Sent" in inbox.buttons and "Write" in inbox.buttons
    (table,) = inbox.find("table")
    assert table["go"] == "mail" and table["param"] == "thread" and table["params"] == {"folder": "inbox"}
    assert [r["with"] for r in rows(inbox)] == ["sam", "sam"]


# -- an account outside ----------------------------------------------------------------------
def session_answer():
    return {"apiUrl": API, "primaryAccounts": {MAILCAP: "acc1"}}


def email(id_, thread, subject, sender, body, when, to="me@fastmail.com"):
    return {
        "id": id_,
        "threadId": thread,
        "subject": subject,
        "from": [{"name": "", "email": sender}],
        "to": [{"email": to}],
        "cc": [],
        "receivedAt": when,
        "textBody": [{"partId": "1", "type": "text/plain"}],
        "bodyValues": {"1": {"value": body}},
    }


def api_answer(emails=(), submitted=True):
    """One answer for every POST: setup, a fetch and a send all find their call in it."""
    return {
        "methodResponses": [
            [
                "Mailbox/get",
                {
                    "list": [
                        {"id": "mb-in", "role": "inbox"},
                        {"id": "mb-sent", "role": "sent"},
                        {"id": "mb-drafts", "role": "drafts"},
                    ]
                },
                "m",
            ],
            ["Identity/get", {"list": [{"id": "id1", "email": "me@fastmail.com"}]}, "i"],
            ["Email/query", {"ids": [e["id"] for e in emails]}, "q"],
            ["Email/get", {"list": list(emails)}, "e"],
            ["Email/set", {"created": {"draft": {"id": "new1"}}}, "s"],
            [
                "EmailSubmission/set",
                {"created": {"sub": {"id": "sub1"}}}
                if submitted
                else {"notCreated": {"sub": {"type": "forbiddenFrom", "description": "not your address"}}},
                "u",
            ],
        ]
    }


def add_account(harness, emails=(), submitted=True):
    harness.fetch.add(SESSION, json=session_answer())
    harness.fetch.add(API, method="POST", json=api_answer(emails, submitted))
    done = harness.act("add-account", name="Fastmail", address="me@fastmail.com", server=SESSION, token="tok-1")
    assert done.ok, done
    return done


def test_an_account_is_set_up_from_its_session_and_its_inbox_fetched(q):
    sam = q.as_user("sam")
    done = add_account(
        sam,
        [
            email("e1", "t1", "Invoice", "shop@example.com", "Your invoice is attached.", "2026-10-26T09:00:00Z"),
            email("e2", "t1", "Re: Invoice", "shop@example.com", "Paid, thanks.", "2026-10-27T09:00:00Z"),
            email("e3", "t2", "Hello", "ada@example.org", "Long time!", "2026-10-25T09:00:00Z"),
        ],
    )
    assert done.toast == "Added Fastmail. Fetched 3 new mails"
    (account,) = sam.list(ACCOUNT)
    assert account["setup"]["mailboxes"] == {"inbox": "mb-in", "sent": "mb-sent", "drafts": "mb-drafts"}
    assert account["setup"]["identityId"] == "id1" and account["token"] is None  # a secret is never listed
    assert account["status"] == "Fetched 3 new mails"
    threads = {t["subject"]: t for t in sam.list(THREAD)}
    assert set(threads) == {"Invoice", "Hello"}
    assert threads["Invoice"]["kind"] == "external" and threads["Invoice"]["addresses"] == "shop@example.com"
    assert threads["Invoice"].scope == "personal"
    assert [m["body"] for m in sam.list(MESSAGE, thread=threads["Invoice"].id)] == [
        "Your invoice is attached.",
        "Paid, thanks.",
    ]
    assert subjects(sam) == ["Invoice", "Hello"]  # newest first
    # Fetched again, nothing is doubled.
    assert sam.act("fetch", account).toast == "Fetched: nothing new"
    assert len(sam.list(MESSAGE)) == 3
    assert [f["headers"]["Authorization"] for f in sam.fetch.sent] == ["Bearer tok-1"] * 4
    # Nobody else sees any of it.
    assert q.as_user("kim").list(THREAD) == []
    # And the account goes with everything fetched through it.
    assert sam.act("remove-account", account).ok
    assert sam.list(THREAD) == [] and sam.list(MESSAGE) == []


def test_mail_to_an_outside_address_goes_through_the_account(q):
    sam = q.as_user("sam")
    assert "add one under Accounts" in sam.act("write", to="ada@example.org", subject="Hi", body="x").error
    add_account(sam)
    sam.fetch.sent.clear()
    write(sam, "ada@example.org, kim", subject="Plans", body="Saturday?", cc="bob@example.org")
    (thread,) = sam.list(THREAD)
    assert thread["kind"] == "external" and thread.scope == "shared"
    assert thread["addresses"] == "ada@example.org, bob@example.org"
    (message,) = sam.list(MESSAGE)
    assert (
        message["status"] == "sent" and message["to"] == "kim, ada@example.org" and message["cc"] == "bob@example.org"
    )
    (sent,) = sam.fetch.sent
    body = json.loads(sent["body"])
    calls = {name: args for name, args, _ in body["methodCalls"]}
    draft = calls["Email/set"]["create"]["draft"]
    assert draft["to"] == [{"email": "ada@example.org"}] and draft["cc"] == [{"email": "bob@example.org"}]
    assert draft["subject"] == "Plans" and draft["bodyValues"]["t"]["value"] == "Saturday?"
    assert draft["mailboxIds"] == {"mb-drafts": True}
    assert calls["EmailSubmission/set"]["create"]["sub"] == {"emailId": "#draft", "identityId": "id1"}
    moved = calls["EmailSubmission/set"]["onSuccessUpdateEmail"]["#sub"]
    assert moved["mailboxIds/mb-sent"] is True and moved["mailboxIds/mb-drafts"] is None
    # kim, on the server, reads it too, and a reply goes out the same way.
    kim = q.as_user("kim")
    assert subjects(kim) == ["● Plans"]
    assert sam.act("reply", thread, body="Or Sunday").ok
    assert [m["status"] for m in sam.list(MESSAGE, thread=thread.id)] == ["sent", "sent"]


def test_what_the_provider_refuses_stays_in_the_thread_and_says_why(q):
    sam = q.as_user("sam")
    add_account(sam, submitted=False)
    write(sam, "ada@example.org", subject="Hi", body="x")
    (message,) = sam.list(MESSAGE)
    assert message["status"] == "failed" and message["note"] == "not your address"
    (thread,) = sam.list(THREAD)
    assert "Not sent: not your address" in sam.view("mail", thread=thread.id).text()


def test_a_server_the_manifest_does_not_name_is_said_so(q):
    sam = q.as_user("sam")
    done = sam.act(
        "add-account", name="Other", address="me@other.example", server="https://jmap.other.example/session", token="t"
    )
    assert done.ok and "may not reach jmap.other.example" in done.toast
    (account,) = sam.list(ACCOUNT)
    assert account["status"].startswith("Not fetched: Mail may not reach")
    assert any("Other: Not fetched" in line for line in sam.view("mail").text().splitlines())


def test_a_refused_token_is_said_so(q):
    sam = q.as_user("sam")
    sam.fetch.add(SESSION, status=401, text="no")
    done = sam.act("add-account", name="Fastmail", address="me@fastmail.com", server=SESSION, token="bad")
    assert "token was refused" in done.toast
