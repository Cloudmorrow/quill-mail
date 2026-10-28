"""The server's own domain, through Cloudflare: set up by an administrator under
Settings, mail in through the Worker and the pull job, mail out through Cloudflare's
Email Service. Cloudflare is a stub: what `ctx.fetch` gets is put in each test.
"""

import base64
import datetime
import email.utils
import json

import pytest
from cloudmorrow.quill.testing import Harness

ACCOUNT, THREAD, MESSAGE, DOMAIN = (
    "mail.account",
    "mail.thread",
    "mail.message",
    "mail.domain",
)
CF = "https://api.cloudflare.com/client/v4"
ZONE, ACCT, NS = "z1", "a1", "ns1"


@pytest.fixture()
def q():
    with Harness(".") as harness:
        harness.as_user("sam")
        harness.as_user("kim")
        yield harness


def ok(result=None, **more):
    return {"success": True, "errors": [], "result": result, **more}


def connect(q):
    q.fetch.add(f"{CF}/user/tokens/verify", json=ok({"status": "active"}))
    q.fetch.add(
        f"{CF}/zones?per_page=50",
        json=ok(
            [
                {
                    "id": ZONE,
                    "name": "example.org",
                    "status": "active",
                    "account": {"id": ACCT, "name": "Jimmi"},
                }
            ]
        ),
    )
    done = q.act("connect", token="cf-token-1")
    assert done.ok, done
    return done


def set_up(q):
    connect(q)
    q.fetch.add(
        f"{CF}/zones/{ZONE}",
        json=ok({"id": ZONE, "name": "example.org", "account": {"id": ACCT}}),
    )
    q.fetch.add(
        f"{CF}/zones/{ZONE}/email/routing",
        json=ok({"enabled": False, "status": "unconfigured"}),
    )
    q.fetch.add(
        f"{CF}/zones/{ZONE}/email/routing/enable",
        method="POST",
        json=ok({"enabled": True}),
    )
    q.fetch.add(
        f"{CF}/accounts/{ACCT}/storage/kv/namespaces",
        method="POST",
        json=ok({"id": NS}),
    )
    q.fetch.add(
        f"{CF}/accounts/{ACCT}/workers/scripts/cloudmorrow-mail",
        method="PUT",
        json=ok({"id": "x"}),
    )
    q.fetch.add(
        f"{CF}/zones/{ZONE}/email/routing/rules/catch_all",
        method="PUT",
        json=ok({"enabled": True}),
    )
    done = q.act("use-domain", zone=ZONE)
    assert done.ok, done
    return done


def a_mail(
    frm, to, subject, body, message_id="<m1@example.net>", cc="", in_reply_to=""
):
    lines = [
        f"From: {frm}",
        f"To: {to}",
        f"Subject: {subject}",
        f"Message-ID: {message_id}",
    ]
    if cc:
        lines.append(f"Cc: {cc}")
    if in_reply_to:
        lines.append(f"In-Reply-To: {in_reply_to}")
    # A mail that arrives is dated after whatever was written here before it.
    when = email.utils.format_datetime(
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
    )
    lines += [
        f"Date: {when}",
        "Content-Type: text/plain; charset=utf-8",
        "",
        body,
    ]
    raw = "\r\n".join(lines).encode()
    return {
        "from": frm.split("<")[-1].rstrip(">"),
        "to": to,
        "size": len(raw),
        "cut": False,
        "received": "2026-10-28T13:00:01Z",
        "raw": base64.b64encode(raw).decode(),
    }


def in_the_box(q, key, kept):
    q.fetch.add(
        f"{CF}/accounts/{ACCT}/storage/kv/namespaces/{NS}/keys?limit=25",
        json=ok([{"name": key}]),
    )
    q.fetch.add(
        f"{CF}/accounts/{ACCT}/storage/kv/namespaces/{NS}/values/{key}",
        text=json.dumps(kept),
    )
    q.fetch.add(
        f"{CF}/accounts/{ACCT}/storage/kv/namespaces/{NS}/values/{key}",
        method="DELETE",
        json=ok(),
    )


def sent_through_cloudflare(q):
    return [
        json.loads(s["body"])
        for s in q.fetch.sent
        if s["url"].endswith("/email/sending/send")
    ]


def subjects(harness, folder="inbox"):
    (table,) = harness.view("mail", folder=folder).find("table")
    return [r["fields"]["subject"] for r in table["records"]]


# -- setting it up, as an administrator ------------------------------------------------------
def test_settings_is_the_administrators_alone_and_asks_for_cloudflare_first(q):
    assert "Connect Cloudflare" in q.view("settings").buttons
    with pytest.raises(AssertionError, match="for an administrator"):
        q.as_user("sam").view("settings")
    assert (
        q.as_user("sam").act("connect", token="x").error
        == "Settings is for an administrator"
    )


def test_connecting_keeps_the_token_sealed_and_lists_the_zones(q):
    connect(q)
    (domain,) = q.list(DOMAIN)
    assert domain.scope == "public" and domain["token"] is None  # never in a listing
    assert q.get(DOMAIN, domain.id)["token"] == "cf-token-1"
    settings = q.view("settings")
    assert "example.org" in settings.text() and "Use this domain" in settings.buttons
    # Everybody sees that there is a domain coming; nobody but the code reads the token.
    assert q.as_user("sam").list(DOMAIN)[0]["token"] is None


def test_a_token_cloudflare_refuses_is_said(q):
    q.fetch.add(
        f"{CF}/user/tokens/verify",
        status=401,
        json={"success": False, "errors": [{"message": "Invalid token"}]},
    )
    assert "Invalid token" in q.act("connect", token="bad").error


def test_using_a_domain_turns_routing_on_and_puts_the_worker_in_place(q):
    set_up(q)
    (domain,) = q.list(DOMAIN)
    assert (
        domain["domain"],
        domain["zone"],
        domain["account"],
        domain["namespace"],
    ) == ("example.org", ZONE, ACCT, NS)
    assert domain["routing"] == "on" and domain["worker"] == "cloudmorrow-mail"
    upload = next(
        s
        for s in q.fetch.sent
        if s["url"].endswith("/workers/scripts/cloudmorrow-mail")
    )
    assert (
        b"env.MAIL.put" in upload["body"] and b'"namespace_id": "ns1"' in upload["body"]
    )
    rule = next(s for s in q.fetch.sent if s["url"].endswith("/rules/catch_all"))
    assert json.loads(rule["body"])["actions"] == [
        {"type": "worker", "value": ["cloudmorrow-mail"]}
    ]
    text = q.view("settings").text()
    assert (
        "example.org" in text
        and f"{q.user}@example.org" in text
        and "sam@example.org" in text
    )


def test_disconnecting_forgets_the_domain(q):
    set_up(q)
    assert q.act("disconnect").ok
    assert q.list(DOMAIN) == [] and "Connect Cloudflare" in q.view("settings").buttons


# -- mail in -------------------------------------------------------------------------------
def test_the_pull_delivers_a_mail_to_whoever_it_is_for_unread_and_the_administrator_sees_nothing(
    q,
):
    set_up(q)
    in_the_box(
        q, "k1", a_mail("Ada <ada@example.net>", "sam@example.org", "Lunch?", "Noon?")
    )
    q.run_job("pull")
    sam = q.as_user("sam")
    (thread,) = sam.list(THREAD)
    assert (
        thread.owner == "sam"
        and thread.scope == "personal"
        and thread["kind"] == "external"
    )
    assert (
        thread["address"] == "sam@example.org"
        and thread["addresses"] == "ada@example.net"
    )
    (message,) = sam.list(MESSAGE, thread=thread.id)
    assert (
        message["sender"] == "ada@example.net"
        and message["body"] == "Noon?"
        and message["remote"] == "<m1@example.net>"
    )
    assert subjects(sam) == ["● Lunch?"]
    assert q.list(THREAD) == [] and q.list(MESSAGE) == []
    (domain,) = q.list(DOMAIN)
    assert domain["received"] == 1 and domain["status"].startswith("Delivered 1")
    assert any(
        s["method"] == "DELETE" and s["url"].endswith("/values/k1")
        for s in q.fetch.sent
    )


def test_a_mail_for_nobody_here_is_dropped_and_said(q):
    set_up(q)
    in_the_box(q, "k2", a_mail("ada@example.net", "nobody@example.org", "Hi", "?"))
    q.run_job("pull")
    assert q.as_user("sam").list(THREAD) == []
    assert "nobody@example.org" in q.list(DOMAIN)[0]["status"]
    assert any(
        s["method"] == "DELETE" and s["url"].endswith("/values/k2")
        for s in q.fetch.sent
    )


def test_an_answer_lands_in_the_conversation_and_a_reply_goes_out_from_my_address(q):
    set_up(q)
    sam = q.as_user("sam")
    q.fetch.add(
        f"{CF}/accounts/{ACCT}/email/sending/send",
        method="POST",
        json=ok({"delivered": ["ada@example.net"]}),
    )
    done = sam.act("write", to="ada@example.net", subject="Lunch?", body="Noon?")
    assert done.ok, done
    (mine,) = sam.list(THREAD)
    assert (
        mine["address"] == "sam@example.org"
        and mine["kind"] == "external"
        and mine.get("account") is None
    )
    (sent,) = sent_through_cloudflare(q)
    assert sent["from"]["address"] == "sam@example.org" and sent["to"] == [
        "ada@example.net"
    ]
    assert sent["subject"] == "Lunch?" and sent["text"] == "Noon?"
    assert subjects(sam, "sent") == ["Lunch?"] and subjects(sam) == []
    # Ada answers: the postman makes a thread of its own, and Mail draws the two as one.
    in_the_box(
        q, "k3", a_mail("ada@example.net", "sam@example.org", "Re: Lunch?", "Yes!")
    )
    q.run_job("pull")
    assert len(sam.list(THREAD)) == 2 and subjects(sam) == ["● Re: Lunch?"]
    opened = sam.view("mail", thread=sam.list(THREAD)[-1].id)
    assert (
        "Noon?" in opened.text()
        and "Yes!" in opened.text()
        and "from sam@example.org" in opened.text()
    )
    assert subjects(sam) == ["Re: Lunch?"]
    # Replying goes out from the same address, and archiving puts the whole conversation away.
    assert sam.act("reply", sam.list(THREAD)[-1], body="See you").ok
    assert sent_through_cloudflare(q)[-1]["to"] == ["ada@example.net"]
    assert sam.act("archive", sam.list(THREAD)[-1]).ok
    assert subjects(sam) == [] and subjects(sam, "archive") == ["Re: Lunch?"]


def test_a_refusal_from_cloudflare_is_kept_on_the_message(q):
    set_up(q)
    sam = q.as_user("sam")
    q.fetch.add(
        f"{CF}/accounts/{ACCT}/email/sending/send",
        method="POST",
        status=403,
        json={
            "success": False,
            "errors": [{"message": "domain not onboarded for sending"}],
        },
    )
    assert sam.act("write", to="ada@example.net", subject="Hi", body="?").ok
    (message,) = sam.list(MESSAGE)
    assert message["status"] == "failed" and "not onboarded" in message["note"]


def test_with_no_domain_mail_out_still_goes_through_your_own_account(q):
    sam = q.as_user("sam")
    done = sam.act("write", to="ada@example.net", subject="Hi", body="?")
    assert not done.ok and "add one under Accounts" in done.error


def test_a_test_mail_goes_from_my_address_to_itself(q):
    set_up(q)
    q.fetch.add(
        f"{CF}/accounts/{ACCT}/email/sending/send",
        method="POST",
        json=ok({"delivered": [f"{q.user}@example.org"]}),
    )
    done = q.act("test-mail")
    assert done.ok and "within two minutes" in done.toast
    (sent,) = sent_through_cloudflare(q)
    assert (
        sent["to"] == [f"{q.user}@example.org"]
        and sent["from"]["address"] == f"{q.user}@example.org"
    )
