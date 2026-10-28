"""Mail: the code behind the Mail and Accounts screens and their buttons.

Run in the sandbox as whoever is looking. A conversation is a thread, a
space: one between people on the server is shared with them, and what is
written in it reaches them through the core (a push, an unread count), so
there is no delivery here, only writing. An outside account is read and
written through its provider's JMAP API with `ctx.fetch`, as the person who
added it; nothing else leaves the server, and nothing runs beside it.
"""

import base64
import datetime as dt
import email
import email.policy
import email.utils
import html
import json
import pathlib
import re

from cloudmorrow.quill import (
    Invalid,
    NotFound,
    Refused,
    action,
    error,
    go,
    job,
    toast,
    ui,
    view,
)

ACCOUNT, THREAD, MESSAGE, STATE = (
    "mail.account",
    "mail.thread",
    "mail.message",
    "mail.state",
)
DOMAIN = "mail.domain"
# Cloudflare's API, the Worker's name in the account, and how many mails one pull takes.
CF = "https://api.cloudflare.com/client/v4"
WORKER = "cloudmorrow-mail"
PULL_PAGE = 25
FOLDERS = [
    ("inbox", "Inbox"),
    ("sent", "Sent"),
    ("archive", "Archive"),
    ("trash", "Trash"),
]
# How old an account's last fetch may be before opening Mail fetches again.
FETCH_EVERY = dt.timedelta(minutes=2)
# How many of an inbox's newest mails a fetch reads.
PAGE = 50
# A body is read whole up to this many bytes; the provider cuts it there.
BODY_BYTES = 200_000

CORE, MAILCAP, SUBMISSION = (
    "urn:ietf:params:jmap:core",
    "urn:ietf:params:jmap:mail",
    "urn:ietf:params:jmap:submission",
)
SPLIT = re.compile(r"[,;\s]+")


# -- small things ----------------------------------------------------------------------
def names_in(text):
    """The names or addresses in what somebody typed, in order, once each."""
    seen, out = set(), []
    for part in SPLIT.split(str(text or "")):
        key = part.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def plural(count, one, many=None):
    return f"{count} {one if count == 1 else many or one + 's'}"


def moment(value):
    """An ISO stamp as an aware datetime, UTC when it carries no zone; None for nothing."""
    if not value:
        return None
    try:
        when = dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.UTC)


def said_when(value, now):
    """A time as a list says it: 14:02 today, Yesterday, 27 Oct, 27 Oct 2025."""
    when = moment(value)
    if when is None:
        return ""
    day, today = when.date(), now.date()
    if day == today:
        return when.strftime("%H:%M")
    if day == today - dt.timedelta(days=1):
        return "Yesterday"
    if day.year == today.year:
        return f"{day.day} {day.strftime('%b')}"
    return f"{day.day} {day.strftime('%b %Y')}"


def sent_at(message):
    return str(message.get("sent_at") or message.created_at or "")


# -- what is where -----------------------------------------------------------------------
def filings(ctx):
    """Where this person filed each thread, by the thread's id."""
    return {str(s["thread"]): s for s in ctx.records.list(STATE)}


def file_thread(ctx, thread_id, folder):
    """File a thread in one of this person's folders, remembering its newest message."""
    lines = sorted(ctx.records.list(MESSAGE, thread=thread_id), key=sent_at)
    fields = {"folder": folder, "last": lines[-1].id if lines else ""}
    found = filings(ctx).get(thread_id)
    if found is None:
        ctx.records.create(STATE, dict(fields, thread=thread_id))
    else:
        ctx.records.patch(STATE, found.id, fields)


def messages_by_thread(ctx):
    """Every message this person may see, by thread, oldest first."""
    by = {}
    for m in ctx.records.list(MESSAGE):
        by.setdefault(str(m["thread"]), []).append(m)
    for lines in by.values():
        lines.sort(key=sent_at)
    return by


def folder_of(thread, filed, lines, me):
    """Which of this person's folders a thread is in: its filing, unless somebody
    has written in it since they archived it — then it is back in the inbox."""
    state = filed.get(thread.id)
    folder = str(state["folder"]) if state else "inbox"
    if folder == "archive" and lines and lines[-1].id != str(state.get("last") or ""):
        return "inbox"
    return folder


def in_folder(folder, thread, lines, me, where):
    """Whether a thread belongs in *folder* for this person."""
    if folder == "sent":
        return where != "trash" and any(m["sender"] == me for m in lines)
    if folder == "inbox":
        # What somebody else wrote to me; what I started and nobody answered is in Sent.
        return where == "inbox" and any(m["sender"] != me for m in lines)
    return where == folder


def others_in(thread, me):
    """Who else is in the thread, as a list says it."""
    if thread["kind"] == "external":
        return str(thread.get("addresses") or "")
    people = [thread.owner, *thread.members]
    return ", ".join(p for p in dict.fromkeys(people) if p and p != me) or "me"


def newest(thread, lines):
    if lines:
        return sent_at(lines[-1])
    last = thread.last or {}
    return str(last.get("when") or thread.created_at or "")


# -- the mail ----------------------------------------------------------------------------
@view("mail")
def mail(ctx):
    folder = str(ctx.params.get("folder") or "inbox")
    if folder not in dict(FOLDERS):
        folder = "inbox"
    notes = fetch_due(ctx)
    opened = str(ctx.params.get("thread") or "")
    if opened:
        return one_thread(ctx, opened, folder, notes)
    return listed(ctx, folder, notes)


def conversations(threads):
    """Threads as conversations: an outside thread and every other with the same
    `remote` key are one — a mail delivered to the server's domain is a thread of
    its own each time, since the postman cannot see what you already have."""
    groups, order = {}, []
    for thread in threads:
        key = (
            thread.id
            if thread["kind"] != "external" or not thread.get("remote")
            else f"r:{thread['remote']}"
        )
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(thread)
    return [groups[key] for key in order]


def listed(ctx, folder, notes):
    me = ctx.user.username
    now = ctx.now()
    filed = filings(ctx)
    by_thread = messages_by_thread(ctx)
    rows, counts = [], dict.fromkeys(dict(FOLDERS), 0)
    for group in conversations(ctx.records.list(THREAD)):
        lines = sorted((m for t in group for m in by_thread.get(t.id, [])), key=sent_at)
        thread = max(group, key=lambda t: newest(t, by_thread.get(t.id, [])))
        where = folder_of(thread, filed, lines, me)
        for name in counts:
            if in_folder(name, thread, lines, me, where):
                counts[name] += 1
        if not in_folder(folder, thread, lines, me, where):
            continue
        unread = any(t.unread > 0 for t in group)
        rows.append(
            (
                newest(thread, lines),
                {
                    "id": thread.id,
                    "model": THREAD,
                    "fields": {
                        "subject": ("● " if unread else "") + str(thread["subject"]),
                        "with": others_in(thread, me),
                        "when": said_when(newest(thread, lines), now),
                    },
                },
            )
        )
    rows.sort(key=lambda pair: pair[0], reverse=True)
    label = dict(FOLDERS)[folder]
    bar = [ui.button("Write", action="write", tone="primary")]
    for key, name in FOLDERS:
        bar.append(
            ui.button(
                f"{name} · {counts[key]}" if counts[key] else name,
                go="mail",
                params={"folder": key},
            )
        )
    return ui.stack(
        ui.row(*bar),
        [ui.text(note, style="muted") for note in notes],
        ui.table(
            [row for _, row in rows],
            columns=[("Subject", "subject"), ("With", "with"), ("When", "when")],
            go="mail",
            param="thread",
            params={"folder": folder},
            empty=EMPTY.get(folder, f"Nothing in {label}."),
        ),
    )


EMPTY = {
    "inbox": "Nothing new. Write to somebody on the server by name, or add an account to read mail from outside.",
    "sent": "Nothing sent yet.",
}


def one_thread(ctx, thread_id, folder, notes):
    me = ctx.user.username
    now = ctx.now()
    try:
        thread = ctx.records.get(THREAD, thread_id)
    except (NotFound, Refused, Invalid):
        return ui.stack(
            ui.empty("That thread is gone, or was never yours to read."),
            ui.button("Back", go="mail", params={"folder": folder}),
        )
    group = siblings_of(ctx, thread)
    lines = sorted(
        (m for t in group for m in ctx.records.list(MESSAGE, thread=t.id)), key=sent_at
    )
    where = folder_of(thread, filings(ctx), lines, me)
    for t in group:
        ctx.records.seen(THREAD, t.id)
    if thread["kind"] == "external":
        account = account_of(ctx, thread)
        if thread.get("address"):
            through = f"Outside, from {thread['address']}"
        else:
            through = f"Outside, through {account['name']}" if account else "Outside"
    else:
        through = "On this server"
    parts = [
        ui.text(str(thread["subject"]), style="title"),
        ui.text(f"With {others_in(thread, me)} · {through}", style="muted"),
    ]
    for m in lines:
        head = f"{m['sender']} · {said_when(sent_at(m), now)}"
        if m.get("to"):
            head += f" · to {m['to']}"
        if m.get("cc"):
            head += f" · cc {m['cc']}"
        parts.append(ui.divider())
        parts.append(ui.text(head, style="small"))
        if m.get("status") == "failed":
            parts.append(
                ui.badge(
                    f"Not sent: {m.get('note') or 'the provider refused it'}",
                    tone="bad",
                )
            )
        parts.append(ui.markdown(str(m["body"])))
    buttons = [ui.button("Reply", action="reply", record=thread, tone="primary")]
    if where == "inbox":
        buttons += [
            ui.button("Archive", action="archive", record=thread),
            ui.button("Delete", action="trash", record=thread, tone="danger"),
        ]
    elif where == "archive":
        buttons += [
            ui.button("Move to inbox", action="restore", record=thread),
            ui.button("Delete", action="trash", record=thread, tone="danger"),
        ]
    else:
        buttons.append(ui.button("Move to inbox", action="restore", record=thread))
        if thread.owner == me:
            buttons.append(
                ui.button(
                    "Delete for good",
                    action="delete-forever",
                    record=thread,
                    tone="danger",
                )
            )
    buttons.append(ui.button("Back", go="mail", params={"folder": folder}))
    return ui.stack(
        [ui.text(note, style="muted") for note in notes],
        *parts,
        ui.divider(),
        ui.row(*buttons),
    )


# -- writing -----------------------------------------------------------------------------
def sort_out(ctx, *texts):
    """Who a mail goes to: names on the server, outside addresses, and names nobody has."""
    me = ctx.user.username
    people = set(ctx.people())
    users, addresses, unknown = [], [], []
    for text in texts:
        for name in names_in(text):
            if name == me:
                continue
            if name in people:
                users.append(name)
            elif "@" in name and "." in name.rsplit("@", 1)[-1]:
                addresses.append(name)
            else:
                unknown.append(name)
    return users, addresses, unknown


@action("write")
def write(ctx, to, subject, body, cc=""):
    users, addresses, unknown = sort_out(ctx, to, cc)
    if unknown:
        return error(
            f"Nobody here is called {', '.join(unknown)}; a name on this server, or an email address"
        )
    if not users and not addresses:
        return error("Who is it to? A name on this server, or an email address")
    account = domain = None
    if addresses:
        domain = the_domain(ctx)
        if domain is None:
            accounts = ctx.records.list(ACCOUNT)
            if not accounts:
                return error(
                    "Mail to an outside address goes through an account of yours: add one under Accounts"
                )
            account = accounts[0]
    me = ctx.user.username
    fields = {
        "subject": str(subject).strip(),
        "kind": "external" if addresses else "internal",
    }
    if addresses:
        fields["addresses"] = ", ".join(addresses)
    if account is not None:
        fields["account"] = account.id
    if domain is not None:
        fields["address"] = my_address(ctx, domain)
        fields["remote"] = conversation_key(fields["subject"], addresses[0])
    thread = ctx.records.create(
        THREAD,
        fields,
        scope="shared" if users else "personal",
        members=users,
        announce=False,
    )
    cc_users, cc_addresses, _ = sort_out(ctx, cc)
    message = ctx.records.create(
        MESSAGE,
        thread=thread.id,
        sender=me,
        to=", ".join(n for n in users + addresses if n not in cc_users + cc_addresses),
        cc=", ".join(cc_users + cc_addresses),
        body=str(body),
        sent_at=ctx.now().isoformat(),
    )
    if domain is not None:
        send_domain(ctx, domain, thread, message, addresses)
    elif account is not None:
        send_out(ctx, account, thread, message, addresses)
    return go("mail", thread=thread.id, folder="sent")


@action("reply")
def reply(ctx, thread, body):
    me = ctx.user.username
    message = ctx.records.create(
        MESSAGE,
        thread=thread.id,
        sender=me,
        to=others_in(thread, me),
        body=str(body),
        sent_at=ctx.now().isoformat(),
    )
    if thread["kind"] == "external" and thread.get("address"):
        domain = the_domain(ctx)
        if domain is None:
            ctx.records.patch(
                MESSAGE,
                message.id,
                status="failed",
                note="the server has no mail domain any more",
            )
        else:
            send_domain(ctx, domain, thread, message, names_in(thread.get("addresses")))
    elif thread["kind"] == "external":
        account = account_of(ctx, thread)
        if account is None:
            ctx.records.patch(
                MESSAGE,
                message.id,
                status="failed",
                note="the account it came through is gone",
            )
        else:
            send_out(ctx, account, thread, message, names_in(thread.get("addresses")))
    # Answering a thread brings it back to my inbox when I had archived it.
    if filings(ctx).get(thread.id) is not None:
        file_thread(ctx, thread.id, "inbox")
    return go("mail", thread=thread.id)


@action("archive")
def archive(ctx, thread):
    for t in siblings_of(ctx, thread):
        file_thread(ctx, t.id, "archive")
    return go("mail", folder="inbox")


@action("trash")
def trash(ctx, thread):
    for t in siblings_of(ctx, thread):
        file_thread(ctx, t.id, "trash")
    return go("mail", folder="inbox")


@action("restore")
def restore(ctx, thread):
    for t in siblings_of(ctx, thread):
        file_thread(ctx, t.id, "inbox")
    return go("mail", folder="inbox")


@action("delete_forever")
def delete_forever(ctx, thread):
    if thread.owner != ctx.user.username:
        return error(
            "A thread somebody else started is theirs to delete; yours is in your Trash only"
        )
    for t in siblings_of(ctx, thread):
        ctx.records.delete(THREAD, t.id)
        for state in ctx.records.list(STATE, thread=t.id):
            ctx.records.delete(STATE, state.id)
    return go("mail", folder="trash")


# -- accounts ----------------------------------------------------------------------------
@view("accounts")
def accounts(ctx):
    found = ctx.records.list(ACCOUNT)
    return ui.stack(
        ui.text(
            "An account outside the server, read and written through its provider's JMAP API, as you. "
            "Fastmail is one: make an API token with mail access under Settings › Privacy & Security › "
            "Integrations. Its inbox is fetched when you open Mail. Mail to an outside address goes from "
            "your address on the server's own domain when the server has one, else through the first "
            "account here.",
            style="muted",
        ),
        ui.table(
            found,
            columns=["name", "address", "status", ("Last fetched", "fetched_at")],
            actions=["fetch", "remove-account"],
            empty="No account yet. Mail between people on this server needs none.",
        ),
        ui.button("Add an account", action="add-account", tone="primary"),
    )


@action("add_account")
def add_account(ctx, name, address, server, token):
    made = ctx.records.create(
        ACCOUNT,
        name=str(name).strip(),
        address=str(address).strip().lower(),
        server=str(server).strip(),
        token=token,
    )
    return toast(f"Added {made['name']}. {fetch_account(ctx, made)}")


@action("fetch")
def fetch(ctx, account):
    return toast(fetch_account(ctx, account))


@action("remove_account")
def remove_account(ctx, account):
    ctx.records.delete(ACCOUNT, account.id)
    return toast(f"Removed {account['name']} and what was fetched from it")


def account_of(ctx, thread):
    if not thread.get("account"):
        return None
    try:
        return ctx.records.get(ACCOUNT, str(thread["account"]))
    except (NotFound, Refused, Invalid):
        return None


def fetch_due(ctx):
    """Fetch every account whose last fetch is old enough; what each said when it went wrong."""
    notes = []
    now = ctx.now()
    for account in ctx.records.list(ACCOUNT):
        last = moment(account.get("fetched_at"))
        if last is not None and now - last < FETCH_EVERY:
            continue
        said = fetch_account(ctx, account)
        if not said.startswith("Fetched"):
            notes.append(f"{account['name']}: {said}")
    return notes


# -- JMAP ---------------------------------------------------------------------------------
class MailError(Exception):
    """What the provider, or the way to it, said."""


def host_of(url):
    return url.split("/")[2] if "//" in url else url


def reach(ctx, url, **how):
    """`ctx.fetch`, with a refusal or a failure said in words."""
    try:
        return ctx.fetch(url, **how)
    except Refused:
        raise MailError(
            f"Mail may not reach {host_of(url)}; only the servers its manifest names"
        ) from None
    except (Invalid, OSError, ValueError) as exc:
        raise MailError(f"{host_of(url)} could not be reached: {exc}") from None


def jmap(ctx, account, calls, token):
    """One JMAP request: the responses by the call id each was given."""
    setup = account.get("setup") or {}
    response = reach(
        ctx,
        setup["apiUrl"],
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        body=json.dumps({"using": [CORE, MAILCAP, SUBMISSION], "methodCalls": calls}),
    )
    if response.status in (401, 403):
        raise MailError(
            "the token was refused; make a new one and add the account again"
        )
    if not response.ok:
        raise MailError(f"the provider answered {response.status}")
    try:
        answered = response.json()["methodResponses"]
    except (ValueError, KeyError, TypeError):
        raise MailError("the provider's answer was not JMAP") from None
    out = {}
    for name, result, call_id in answered:
        out[str(call_id)] = (str(name), result if isinstance(result, dict) else {})
    return out


def session(ctx, account, token):
    """Where the account's API is, which account it is, and its mailboxes and identity — kept on the record."""
    response = reach(
        ctx, str(account["server"]), headers={"Authorization": f"Bearer {token}"}
    )
    if response.status in (401, 403):
        raise MailError(
            "the token was refused; make a new one and add the account again"
        )
    if not response.ok:
        raise MailError(f"{account['server']} answered {response.status}")
    try:
        data = response.json()
        setup = {
            "apiUrl": str(data["apiUrl"]),
            "accountId": str(data["primaryAccounts"][MAILCAP]),
        }
    except (ValueError, KeyError, TypeError):
        raise MailError(
            f"{account['server']} is not a JMAP session with mail in it"
        ) from None
    if not setup["apiUrl"].startswith("https://"):
        raise MailError("the provider's API is not https")
    account = ctx.records.patch(ACCOUNT, account.id, setup=setup)
    answered = jmap(
        ctx,
        account,
        [
            [
                "Mailbox/get",
                {
                    "accountId": setup["accountId"],
                    "ids": None,
                    "properties": ["id", "role", "name"],
                },
                "m",
            ],
            ["Identity/get", {"accountId": setup["accountId"], "ids": None}, "i"],
        ],
        token,
    )
    boxes = {}
    for box in answered.get("m", ("", {}))[1].get("list") or []:
        role = str(box.get("role") or "")
        if role in ("inbox", "sent", "drafts") and role not in boxes:
            boxes[role] = str(box["id"])
    if "inbox" not in boxes:
        raise MailError("the account has no inbox")
    identities = answered.get("i", ("", {}))[1].get("list") or []
    mine = [
        i
        for i in identities
        if str(i.get("email") or "").lower() == str(account["address"]).lower()
    ]
    setup["mailboxes"] = boxes
    setup["identityId"] = str((mine or identities or [{}])[0].get("id") or "")
    return ctx.records.patch(ACCOUNT, account.id, setup=setup)


def ready(ctx, account):
    """The account with its setup on it, and the token: read from the one record, as its owner."""
    account = ctx.records.get(ACCOUNT, account.id)
    token = str(account.get("token") or "")
    if not token:
        raise MailError("the account has no token")
    setup = account.get("setup") or {}
    if not setup.get("mailboxes"):
        account = session(ctx, account, token)
    return account, token


def fetch_account(ctx, account):
    """Read the account's inbox into threads and messages; what it said, for a toast."""
    try:
        account, token = ready(ctx, account)
        setup = account["setup"]
        answered = jmap(
            ctx,
            account,
            [
                [
                    "Email/query",
                    {
                        "accountId": setup["accountId"],
                        "filter": {"inMailbox": setup["mailboxes"]["inbox"]},
                        "sort": [{"property": "receivedAt", "isAscending": False}],
                        "limit": PAGE,
                    },
                    "q",
                ],
                [
                    "Email/get",
                    {
                        "accountId": setup["accountId"],
                        "#ids": {
                            "resultOf": "q",
                            "name": "Email/query",
                            "path": "/ids",
                        },
                        "properties": [
                            "id",
                            "threadId",
                            "subject",
                            "from",
                            "to",
                            "cc",
                            "receivedAt",
                            "textBody",
                            "bodyValues",
                        ],
                        "fetchTextBodyValues": True,
                        "maxBodyValueBytes": BODY_BYTES,
                    },
                    "e",
                ],
            ],
            token,
        )
        name, result = answered.get("e", ("", {}))
        if name != "Email/get":
            raise MailError(
                f"the provider said {result.get('type') or name or 'nothing'}"
            )
        made = keep(ctx, account, result.get("list") or [])
    except MailError as exc:
        said = f"Not fetched: {exc}"
        ctx.records.patch(ACCOUNT, account.id, status=said)
        return said
    said = (
        f"Fetched {plural(made, 'new mail', 'new mails')}"
        if made
        else "Fetched: nothing new"
    )
    ctx.records.patch(
        ACCOUNT, account.id, status=said, fetched_at=ctx.now().isoformat()
    )
    return said


def address_of(part):
    return str((part or {}).get("email") or "").strip().lower()


def addresses_said(parts):
    return ", ".join(a for a in (address_of(p) for p in parts or []) if a)


def body_of(email):
    values = email.get("bodyValues") or {}
    for part in email.get("textBody") or []:
        found = values.get(str(part.get("partId")))
        if found and found.get("value") is not None:
            return str(found["value"])
    return ""


def keep(ctx, account, emails):
    """New messages as records, in threads by the provider's own threading; how many were new."""
    known = {str(m["remote"]) for m in ctx.records.list(MESSAGE) if m.get("remote")}
    threads = {
        str(t["remote"]): t
        for t in ctx.records.list(THREAD, account=account.id)
        if t.get("remote")
    }
    mine = str(account["address"]).lower()
    made = 0
    for mail in sorted(emails, key=lambda e: str(e.get("receivedAt") or "")):
        remote = str(mail.get("id") or "")
        if not remote or remote in known:
            continue
        people = [
            address_of(p)
            for p in (mail.get("from") or [])
            + (mail.get("to") or [])
            + (mail.get("cc") or [])
        ]
        others = [p for p in dict.fromkeys(people) if p and p != mine]
        thread_key = str(mail.get("threadId") or remote)
        thread = threads.get(thread_key)
        if thread is None:
            thread = ctx.records.create(
                THREAD,
                scope="personal",
                subject=str(mail.get("subject") or "(no subject)"),
                kind="external",
                account=account.id,
                addresses=", ".join(others),
                remote=thread_key,
            )
            threads[thread_key] = thread
        elif others and set(others) - set(names_in(thread.get("addresses"))):
            joined = list(dict.fromkeys(names_in(thread.get("addresses")) + others))
            threads[thread_key] = ctx.records.patch(
                THREAD, thread.id, addresses=", ".join(joined)
            )
        sender = addresses_said(mail.get("from")) or "unknown"
        ctx.records.create(
            MESSAGE,
            thread=thread.id,
            sender=mine if sender == mine else sender,
            to=addresses_said(mail.get("to")),
            cc=addresses_said(mail.get("cc")),
            body=body_of(mail) or "(no text)",
            sent_at=str(mail.get("receivedAt") or ctx.now().isoformat()),
            remote=remote,
        )
        known.add(remote)
        made += 1
    return made


def send_out(ctx, account, thread, message, addresses):
    """Send a message through the account: True when the provider took it, else the
    message says what went wrong and the thread keeps it."""
    try:
        account, token = ready(ctx, account)
        setup = account["setup"]
        boxes = setup["mailboxes"]
        if not setup.get("identityId"):
            raise MailError("the account has no identity to send as")
        cc = [a for a in names_in(message.get("cc")) if "@" in a]
        to = [a for a in addresses if a not in cc]
        draft = {
            "mailboxIds": {boxes.get("drafts") or boxes["inbox"]: True},
            "keywords": {"$draft": True, "$seen": True},
            "from": [{"email": str(account["address"])}],
            "to": [{"email": a} for a in to],
            "cc": [{"email": a} for a in cc],
            "subject": str(thread["subject"]),
            "textBody": [{"partId": "t", "type": "text/plain"}],
            "bodyValues": {"t": {"value": str(message["body"])}},
        }
        after = {
            "keywords/$draft": None,
            f"mailboxIds/{boxes.get('drafts') or boxes['inbox']}": None,
        }
        if boxes.get("sent"):
            after[f"mailboxIds/{boxes['sent']}"] = True
        answered = jmap(
            ctx,
            account,
            [
                [
                    "Email/set",
                    {"accountId": setup["accountId"], "create": {"draft": draft}},
                    "s",
                ],
                [
                    "EmailSubmission/set",
                    {
                        "accountId": setup["accountId"],
                        "create": {
                            "sub": {
                                "emailId": "#draft",
                                "identityId": setup["identityId"],
                            }
                        },
                        "onSuccessUpdateEmail": {"#sub": after},
                    },
                    "u",
                ],
            ],
            token,
        )
        name, result = answered.get("u", ("", {}))
        if name != "EmailSubmission/set" or "sub" not in (result.get("created") or {}):
            refused = (result.get("notCreated") or {}).get("sub") or {}
            made = answered.get("s", ("", {}))[1]
            refused = refused or (made.get("notCreated") or {}).get("draft") or {}
            raise MailError(
                str(
                    refused.get("description")
                    or refused.get("type")
                    or name
                    or "the provider said nothing"
                )
            )
    except MailError as exc:
        ctx.records.patch(MESSAGE, message.id, status="failed", note=str(exc))
        return False
    return True


# -- the server's own domain, through Cloudflare ---------------------------------------------
# One record of `mail.domain`, a public space: everybody's code reads it (the
# domain, to say their address; the token, sealed, to send as them) and an
# administrator alone changes it. The postman is the `pull` job: every minute,
# as the administrator who installed Mail, it takes what the Worker put in the
# KV namespace and delivers each mail to the person it is for — a thread and a
# message of theirs, news to them — and sees nothing of it afterwards.
def the_domain(ctx):
    """The server's domain, ready for mail, or None. The token is not in a listing."""
    for found in ctx.records.list(DOMAIN):
        if found.get("zone") and found.get("namespace"):
            return found
    return None


def any_domain(ctx):
    found = ctx.records.list(DOMAIN)
    return found[0] if found else None


def token_of(ctx, domain):
    """The sealed token, read from the one record: how a secret field is asked for."""
    token = str(ctx.records.get(DOMAIN, domain.id).get("token") or "")
    if not token:
        raise MailError("the domain has no token; connect Cloudflare again")
    return token


def my_address(ctx, domain):
    return f"{ctx.user.username}@{domain['domain']}"


def administrators_only(ctx):
    return None if ctx.user.admin else error("Settings is for an administrator")


def conversation_key(subject, address):
    """What makes two outside mails one conversation: the subject with its Re: and
    Fwd: peeled off, and the outside address. A reply keeps both; the postman,
    who cannot see what you already have, can still name the conversation."""
    bare = str(subject or "").strip().lower()
    while True:
        peeled = re.sub(r"^(re|fwd?|sv|aw|vs)\s*(\[\d+\])?\s*:\s*", "", bare)
        if peeled == bare:
            break
        bare = peeled
    return f"{re.sub(r'\s+', ' ', bare)}|{str(address or '').strip().lower()}"


def siblings_of(ctx, thread):
    """Every thread of this conversation, the opened one included."""
    if thread["kind"] != "external" or not thread.get("remote"):
        return [thread]
    found = ctx.records.list(THREAD, remote=str(thread["remote"]))
    return found or [thread]


# -- Cloudflare's API -----------------------------------------------------------------------
def cf(
    ctx,
    token,
    path,
    *,
    method="GET",
    json_body=None,
    body=None,
    content_type=None,
    raw=False,
):
    """One call to Cloudflare's API: its `result`, or what it said went wrong.
    With *raw*, the body as text (a KV value is not wrapped)."""
    headers = {"Authorization": f"Bearer {token}"}
    if content_type:
        headers["Content-Type"] = content_type
    elif json_body is not None:
        headers["Content-Type"] = "application/json"
    response = reach(
        ctx,
        CF + path,
        method=method,
        headers=headers,
        body=json.dumps(json_body) if json_body is not None else body,
    )
    if raw and response.ok:
        return response.text
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok or not data.get("success", response.ok):
        errors = data.get("errors") or []
        said = (
            "; ".join(str(e.get("message") or e) for e in errors if e)
            or f"Cloudflare answered {response.status}"
        )
        if response.status in (401, 403) and not errors:
            said = "the token was refused"
        raise MailError(said)
    return data.get("result")


def worker_source():
    return (pathlib.Path(__file__).parent / "worker.js").read_text(encoding="utf-8")


def multipart(parts):
    """A multipart/form-data body: (name, filename, content type, text) each."""
    boundary = "cloudmorrow-" + base64.b16encode(b"mail-worker").decode().lower()
    out = []
    for name, filename, kind, text in parts:
        out.append(f"--{boundary}\r\n")
        out.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
        )
        out.append(f"Content-Type: {kind}\r\n\r\n{text}\r\n")
    out.append(f"--{boundary}--\r\n")
    return "".join(out), f"multipart/form-data; boundary={boundary}"


@view("settings")
def settings(ctx):
    if not ctx.user.admin:
        return ui.empty("Settings is for an administrator.")
    domain = any_domain(ctx)
    if domain is None:
        return ui.stack(
            ui.text(
                "Your own domain for everybody on this server, through your Cloudflare account: name@your-domain "
                "for each person, mail in through Email Routing and a Worker, mail out through Cloudflare's "
                "Email Service. Nothing runs anywhere but in your account; Cloudmorrow holds none of it.",
                style="muted",
            ),
            ui.text(
                "First, at Cloudflare: the domain is on Cloudflare, and under Compute › Email Service › Email "
                "Sending it is onboarded for sending (that needs the Workers Paid plan; receiving is free). Then "
                "an API token with Zone Read, Email Routing Rules Edit, Workers Scripts Edit, Workers KV Storage "
                "Edit and Email Sending Edit. The catalog page has the steps.",
                style="muted",
            ),
            ui.button("Connect Cloudflare", action="connect", tone="primary"),
        )
    if not domain.get("zone"):
        try:
            zones = cf(ctx, token_of(ctx, domain), "/zones?per_page=50") or []
        except MailError as exc:
            zones, said = [], str(exc)
        else:
            said = (
                ""
                if zones
                else "The token sees no domain: give it Zone Read on the domain's zone."
            )
        rows = []
        for zone in zones:
            name = str(zone.get("name") or "")
            rows.append(
                ui.row(
                    ui.text(name),
                    ui.text(str(zone.get("status") or ""), style="muted"),
                    ui.button(
                        "Use this domain",
                        action="use-domain",
                        args={"zone": str(zone.get("id") or "")},
                    ),
                )
            )
        return ui.stack(
            ui.text(
                "Connected to Cloudflare. Which domain is the server's?", style="title"
            ),
            [ui.text(said, style="muted")] if said else [],
            *rows,
            ui.divider(),
            ui.button("Disconnect", action="disconnect", tone="danger"),
        )
    me = ctx.user.username
    people = sorted({me, *ctx.people()})
    return ui.stack(
        ui.text(str(domain["domain"]), style="title"),
        ui.row(
            ui.stat("Email Routing", "On" if domain.get("routing") == "on" else "Off"),
            ui.stat("Worker", str(domain.get("worker") or "")),
            ui.stat("Delivered", str(domain.get("received") or 0)),
            ui.stat(
                "Last pull",
                said_when(str(domain.get("pulled_at") or ""), ctx.now())
                if domain.get("pulled_at")
                else "not yet",
            ),
        ),
        ui.text(str(domain.get("status") or ""), style="muted"),
        ui.text(
            "Everybody here has an address on it; mail to it lands in their inbox within a minute, and what they "
            "write to an outside address goes from it. "
            + ", ".join(f"{who}@{domain['domain']}" for who in people),
            style="muted",
        ),
        ui.row(
            ui.button("Send a test mail to me", action="test-mail", tone="primary"),
            ui.button(
                "Set the domain up again",
                action="use-domain",
                args={"zone": str(domain["zone"])},
            ),
            ui.button("Disconnect", action="disconnect", tone="danger"),
        ),
    )


@action("connect")
def connect(ctx, token):
    if (refused := administrators_only(ctx)) is not None:
        return refused
    token = str(token).strip()
    try:
        verified = cf(ctx, token, "/user/tokens/verify") or {}
        if str(verified.get("status") or "") != "active":
            raise MailError(f"the token is {verified.get('status') or 'not active'}")
        zones = cf(ctx, token, "/zones?per_page=50") or []
    except MailError as exc:
        return error(f"Cloudflare did not take the token: {exc}")
    found = any_domain(ctx)
    status = (
        f"Connected; {plural(len(zones), 'domain')} to choose from"
        if zones
        else "Connected; the token sees no domain"
    )
    if found is None:
        ctx.records.create(DOMAIN, scope="public", token=token, status=status)
    else:
        ctx.records.patch(DOMAIN, found.id, token=token, status=status)
    return go("settings")


@action("use_domain")
def use_domain(ctx, zone):
    if (refused := administrators_only(ctx)) is not None:
        return refused
    domain = any_domain(ctx)
    if domain is None:
        return error("Connect Cloudflare first")
    zone = str(zone).strip()
    try:
        token = token_of(ctx, domain)
        found = cf(ctx, token, f"/zones/{zone}") or {}
        name = str(found.get("name") or "")
        account = str((found.get("account") or {}).get("id") or "")
        if not name or not account:
            raise MailError("the zone has no name or no account that the token may see")
        routing = cf(ctx, token, f"/zones/{zone}/email/routing") or {}
        if not routing.get("enabled"):
            cf(
                ctx,
                token,
                f"/zones/{zone}/email/routing/enable",
                method="POST",
                json_body={},
            )
        namespace = (
            str(domain.get("namespace") or "")
            if domain.get("account") == account
            else ""
        )
        if not namespace:
            made = cf(
                ctx,
                token,
                f"/accounts/{account}/storage/kv/namespaces",
                method="POST",
                json_body={"title": WORKER},
            )
            namespace = str((made or {}).get("id") or "")
            if not namespace:
                raise MailError("Cloudflare made no KV namespace")
        metadata = {
            "main_module": "worker.js",
            "compatibility_date": "2025-09-01",
            "bindings": [
                {"type": "kv_namespace", "name": "MAIL", "namespace_id": namespace}
            ],
        }
        body, kind = multipart(
            [
                (
                    "metadata",
                    "metadata.json",
                    "application/json",
                    json.dumps(metadata, indent=1),
                ),
                (
                    "worker.js",
                    "worker.js",
                    "application/javascript+module",
                    worker_source(),
                ),
            ]
        )
        cf(
            ctx,
            token,
            f"/accounts/{account}/workers/scripts/{WORKER}",
            method="PUT",
            body=body,
            content_type=kind,
        )
        cf(
            ctx,
            token,
            f"/zones/{zone}/email/routing/rules/catch_all",
            method="PUT",
            json_body={
                "name": "Cloudmorrow: every mail to the server",
                "enabled": True,
                "matchers": [{"type": "all"}],
                "actions": [{"type": "worker", "value": [WORKER]}],
            },
        )
    except MailError as exc:
        ctx.records.patch(DOMAIN, domain.id, status=f"Not set up: {exc}")
        return error(f"Not set up: {exc}")
    ctx.records.patch(
        DOMAIN,
        domain.id,
        domain=name,
        zone=zone,
        account=account,
        namespace=namespace,
        worker=WORKER,
        routing="on",
        status="Ready: Email Routing is on and the Worker is in place",
    )
    return go("settings")


@action("test_mail")
def test_mail(ctx):
    if (refused := administrators_only(ctx)) is not None:
        return refused
    domain = the_domain(ctx)
    if domain is None:
        return error("Choose a domain first")
    mine = my_address(ctx, domain)
    try:
        send(
            ctx,
            domain,
            mine,
            [mine],
            [],
            "A test mail from Cloudmorrow",
            "If you can read this, mail goes out through Cloudflare and comes back in through the Worker.",
        )
    except MailError as exc:
        return error(f"Not sent: {exc}")
    return toast(f"Sent to {mine}; it should be in your inbox within two minutes")


@action("disconnect")
def disconnect(ctx):
    if (refused := administrators_only(ctx)) is not None:
        return refused
    for found in ctx.records.list(DOMAIN):
        ctx.records.delete(DOMAIN, found.id)
    return toast(
        "Disconnected. The Worker, the namespace and the routing rule are still in your Cloudflare account."
    )


# -- mail out ---------------------------------------------------------------------------------
def send(ctx, domain, sender, to, cc, subject, text):
    """One mail through Cloudflare's Email Service; what went wrong is a MailError."""
    token = token_of(ctx, domain)
    message = {
        "from": {"address": sender, "name": str(ctx.user.name or ctx.user.username)},
        "to": list(to),
        "subject": str(subject),
        "text": str(text),
    }
    if cc:
        message["cc"] = list(cc)
    cf(
        ctx,
        token,
        f"/accounts/{domain['account']}/email/sending/send",
        method="POST",
        json_body=message,
    )


def send_domain(ctx, domain, thread, message, addresses):
    """Send a message from the person's address on the server's domain: True when
    Cloudflare took it, else the message says what went wrong."""
    cc = [a for a in names_in(message.get("cc")) if "@" in a]
    to = [a for a in addresses if a not in cc]
    try:
        send(
            ctx,
            domain,
            my_address(ctx, domain),
            to,
            cc,
            thread["subject"],
            message["body"],
        )
    except MailError as exc:
        ctx.records.patch(MESSAGE, message.id, status="failed", note=str(exc))
        return False
    return True


# -- mail in: the postman ---------------------------------------------------------------------
@job
def pull(ctx):
    """What the Worker put in the namespace, delivered; then taken out of it."""
    domain = the_domain(ctx)
    if domain is None:
        return
    delivered, dropped, notes = 0, [], []
    try:
        token = token_of(ctx, domain)
        account, namespace = domain["account"], domain["namespace"]
        keys = (
            cf(
                ctx,
                token,
                f"/accounts/{account}/storage/kv/namespaces/{namespace}/keys?limit={PULL_PAGE}",
            )
            or []
        )
        for key in keys:
            name = str(key.get("name") or "")
            if not name:
                continue
            text = cf(
                ctx,
                token,
                f"/accounts/{account}/storage/kv/namespaces/{namespace}/values/{name}",
                raw=True,
            )
            try:
                kept = json.loads(text or "{}")
                who = deliver(ctx, domain, kept)
            except (ValueError, KeyError, TypeError) as exc:
                notes.append(f"one mail could not be read: {exc}")
                who = ""
            if who:
                delivered += 1
            elif kept.get("to"):
                dropped.append(str(kept["to"]))
            cf(
                ctx,
                token,
                f"/accounts/{account}/storage/kv/namespaces/{namespace}/values/{name}",
                method="DELETE",
            )
    except MailError as exc:
        notes.append(f"the pull stopped: {exc}")
    said = f"Delivered {delivered}" if delivered or not (dropped or notes) else ""
    if dropped:
        said += f"{'; ' if said else ''}dropped, for nobody here: {', '.join(sorted(set(dropped)))}"
    if notes:
        said += f"{'; ' if said else ''}{'; '.join(notes)}"
    ctx.records.patch(
        DOMAIN,
        domain.id,
        status=said,
        pulled_at=ctx.now().isoformat(),
        received=int(domain.get("received") or 0) + delivered,
    )


def deliver(ctx, domain, kept):
    """One mail as the Worker kept it, delivered to the person it is addressed to:
    their username, or "" when nobody here has that address."""
    envelope = str(kept.get("to") or "").strip().lower()
    local, _, at = envelope.partition("@")
    if at != str(domain["domain"]).lower() or not local:
        return ""
    people = {ctx.user.username, *ctx.people()}
    if local not in people:
        return ""
    raw = base64.b64decode(str(kept.get("raw") or ""))
    parsed = email.message_from_bytes(raw, policy=email.policy.default)
    subject = str(parsed.get("Subject") or "(no subject)").strip() or "(no subject)"
    sender = (
        address_in(parsed.get("From"))
        or str(kept.get("from") or "").strip().lower()
        or "unknown"
    )
    to = addresses_in(parsed.get_all("To") or [])
    cc = addresses_in(parsed.get_all("Cc") or [])
    others = [a for a in dict.fromkeys([sender, *to, *cc]) if a and a != envelope]
    when = parsed.get("Date")
    try:
        sent = email.utils.parsedate_to_datetime(str(when)).isoformat() if when else ""
    except (TypeError, ValueError):
        sent = ""
    thread = ctx.records.create(
        THREAD,
        owner=local,
        scope="personal",
        subject=subject,
        kind="external",
        addresses=", ".join(others),
        remote=conversation_key(subject, sender),
        address=envelope,
    )
    ctx.records.create(
        MESSAGE,
        owner=local,
        by=sender,
        thread=thread.id,
        sender=sender,
        to=", ".join(to),
        cc=", ".join(cc),
        body=text_of(parsed, kept) or "(no text)",
        sent_at=sent or str(kept.get("received") or ctx.now().isoformat()),
        remote=str(parsed.get("Message-ID") or "").strip(),
    )
    return local


def address_in(header):
    _, address = email.utils.parseaddr(str(header or ""))
    return address.strip().lower()


def addresses_in(headers):
    return [
        a.strip().lower()
        for _, a in email.utils.getaddresses([str(h) for h in headers])
        if a
    ]


def text_of(parsed, kept):
    """The mail's text: its plain part, else its HTML with the tags taken out."""
    try:
        part = parsed.get_body(preferencelist=("plain", "html"))
    except Exception:  # noqa: BLE001 - a mail is anybody's bytes
        part = None
    if part is None:
        return ""
    try:
        text = part.get_content()
    except Exception:  # noqa: BLE001
        text = part.get_payload(decode=True) or b""
        text = text.decode("utf-8", "replace") if isinstance(text, bytes) else str(text)
    if part.get_content_type() == "text/html":
        text = re.sub(r"(?is)<(script|style).*?</\1>", "", str(text))
        text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", text)
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = str(text).replace("\r\n", "\n").strip()
    if kept.get("cut"):
        text += "\n\n(The mail was larger than 1.5 MB and was cut there.)"
    return text
