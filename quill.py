"""Mail: the code behind the Mail and Accounts screens and their buttons.

Run in the sandbox as whoever is looking. A conversation is a thread, a
space: one between people on the server is shared with them, and what is
written in it reaches them through the core (a push, an unread count), so
there is no delivery here, only writing. An outside account is read and
written through its provider's JMAP API with `ctx.fetch`, as the person who
added it; nothing else leaves the server, and nothing runs beside it.
"""

import datetime as dt
import json
import re

from cloudmorrow.quill import Invalid, NotFound, Refused, action, error, go, toast, ui, view

ACCOUNT, THREAD, MESSAGE, STATE = "mail.account", "mail.thread", "mail.message", "mail.state"
FOLDERS = [("inbox", "Inbox"), ("sent", "Sent"), ("archive", "Archive"), ("trash", "Trash")]
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
        when = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
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
        return where == "inbox" and (thread["kind"] == "external" or any(m["sender"] != me for m in lines))
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


def listed(ctx, folder, notes):
    me = ctx.user.username
    now = ctx.now()
    filed = filings(ctx)
    by_thread = messages_by_thread(ctx)
    threads = ctx.records.list(THREAD)
    rows, counts = [], dict.fromkeys(dict(FOLDERS), 0)
    for thread in threads:
        lines = by_thread.get(thread.id, [])
        where = folder_of(thread, filed, lines, me)
        for name in counts:
            if in_folder(name, thread, lines, me, where):
                counts[name] += 1
        if not in_folder(folder, thread, lines, me, where):
            continue
        unread = thread.unread > 0
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
        bar.append(ui.button(f"{name} · {counts[key]}" if counts[key] else name, go="mail", params={"folder": key}))
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
    lines = sorted(ctx.records.list(MESSAGE, thread=thread.id), key=sent_at)
    where = folder_of(thread, filings(ctx), lines, me)
    ctx.records.seen(THREAD, thread.id)
    if thread["kind"] == "external":
        account = account_of(ctx, thread)
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
            parts.append(ui.badge(f"Not sent: {m.get('note') or 'the provider refused it'}", tone="bad"))
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
            buttons.append(ui.button("Delete for good", action="delete-forever", record=thread, tone="danger"))
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
        return error(f"Nobody here is called {', '.join(unknown)}; a name on this server, or an email address")
    if not users and not addresses:
        return error("Who is it to? A name on this server, or an email address")
    account = None
    if addresses:
        accounts = ctx.records.list(ACCOUNT)
        if not accounts:
            return error("Mail to an outside address goes through an account of yours: add one under Accounts")
        account = accounts[0]
    me = ctx.user.username
    fields = {"subject": str(subject).strip(), "kind": "external" if addresses else "internal"}
    if account is not None:
        fields["account"] = account.id
        fields["addresses"] = ", ".join(addresses)
    thread = ctx.records.create(THREAD, fields, scope="shared" if users else "personal", members=users, announce=False)
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
    if account is not None:
        send_out(ctx, account, thread, message, addresses)
    return go("mail", thread=thread.id, folder="sent")


@action("reply")
def reply(ctx, thread, body):
    me = ctx.user.username
    message = ctx.records.create(
        MESSAGE, thread=thread.id, sender=me, to=others_in(thread, me), body=str(body), sent_at=ctx.now().isoformat()
    )
    if thread["kind"] == "external":
        account = account_of(ctx, thread)
        if account is None:
            ctx.records.patch(MESSAGE, message.id, status="failed", note="the account it came through is gone")
        else:
            send_out(ctx, account, thread, message, names_in(thread.get("addresses")))
    # Answering a thread brings it back to my inbox when I had archived it.
    if filings(ctx).get(thread.id) is not None:
        file_thread(ctx, thread.id, "inbox")
    return go("mail", thread=thread.id)


@action("archive")
def archive(ctx, thread):
    file_thread(ctx, thread.id, "archive")
    return go("mail", folder="inbox")


@action("trash")
def trash(ctx, thread):
    file_thread(ctx, thread.id, "trash")
    return go("mail", folder="inbox")


@action("restore")
def restore(ctx, thread):
    file_thread(ctx, thread.id, "inbox")
    return go("mail", folder="inbox")


@action("delete_forever")
def delete_forever(ctx, thread):
    if thread.owner != ctx.user.username:
        return error("A thread somebody else started is theirs to delete; yours is in your Trash only")
    ctx.records.delete(THREAD, thread.id)
    for state in ctx.records.list(STATE, thread=thread.id):
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
            "Integrations. Its inbox is fetched when you open Mail, and mail to an outside address is "
            "sent through the first account here.",
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
        ACCOUNT, name=str(name).strip(), address=str(address).strip().lower(), server=str(server).strip(), token=token
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
        raise MailError(f"Mail may not reach {host_of(url)}; only the servers its manifest names") from None
    except (Invalid, OSError, ValueError) as exc:
        raise MailError(f"{host_of(url)} could not be reached: {exc}") from None


def jmap(ctx, account, calls, token):
    """One JMAP request: the responses by the call id each was given."""
    setup = account.get("setup") or {}
    response = reach(
        ctx,
        setup["apiUrl"],
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        body=json.dumps({"using": [CORE, MAILCAP, SUBMISSION], "methodCalls": calls}),
    )
    if response.status in (401, 403):
        raise MailError("the token was refused; make a new one and add the account again")
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
    response = reach(ctx, str(account["server"]), headers={"Authorization": f"Bearer {token}"})
    if response.status in (401, 403):
        raise MailError("the token was refused; make a new one and add the account again")
    if not response.ok:
        raise MailError(f"{account['server']} answered {response.status}")
    try:
        data = response.json()
        setup = {"apiUrl": str(data["apiUrl"]), "accountId": str(data["primaryAccounts"][MAILCAP])}
    except (ValueError, KeyError, TypeError):
        raise MailError(f"{account['server']} is not a JMAP session with mail in it") from None
    if not setup["apiUrl"].startswith("https://"):
        raise MailError("the provider's API is not https")
    account = ctx.records.patch(ACCOUNT, account.id, setup=setup)
    answered = jmap(
        ctx,
        account,
        [
            ["Mailbox/get", {"accountId": setup["accountId"], "ids": None, "properties": ["id", "role", "name"]}, "m"],
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
    mine = [i for i in identities if str(i.get("email") or "").lower() == str(account["address"]).lower()]
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
                        "#ids": {"resultOf": "q", "name": "Email/query", "path": "/ids"},
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
            raise MailError(f"the provider said {result.get('type') or name or 'nothing'}")
        made = keep(ctx, account, result.get("list") or [])
    except MailError as exc:
        said = f"Not fetched: {exc}"
        ctx.records.patch(ACCOUNT, account.id, status=said)
        return said
    said = f"Fetched {plural(made, 'new mail', 'new mails')}" if made else "Fetched: nothing new"
    ctx.records.patch(ACCOUNT, account.id, status=said, fetched_at=ctx.now().isoformat())
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
    threads = {str(t["remote"]): t for t in ctx.records.list(THREAD, account=account.id) if t.get("remote")}
    mine = str(account["address"]).lower()
    made = 0
    for email in sorted(emails, key=lambda e: str(e.get("receivedAt") or "")):
        remote = str(email.get("id") or "")
        if not remote or remote in known:
            continue
        people = [address_of(p) for p in (email.get("from") or []) + (email.get("to") or []) + (email.get("cc") or [])]
        others = [p for p in dict.fromkeys(people) if p and p != mine]
        thread_key = str(email.get("threadId") or remote)
        thread = threads.get(thread_key)
        if thread is None:
            thread = ctx.records.create(
                THREAD,
                scope="personal",
                subject=str(email.get("subject") or "(no subject)"),
                kind="external",
                account=account.id,
                addresses=", ".join(others),
                remote=thread_key,
            )
            threads[thread_key] = thread
        elif others and set(others) - set(names_in(thread.get("addresses"))):
            joined = list(dict.fromkeys(names_in(thread.get("addresses")) + others))
            threads[thread_key] = ctx.records.patch(THREAD, thread.id, addresses=", ".join(joined))
        sender = addresses_said(email.get("from")) or "unknown"
        ctx.records.create(
            MESSAGE,
            thread=thread.id,
            sender=mine if sender == mine else sender,
            to=addresses_said(email.get("to")),
            cc=addresses_said(email.get("cc")),
            body=body_of(email) or "(no text)",
            sent_at=str(email.get("receivedAt") or ctx.now().isoformat()),
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
        after = {"keywords/$draft": None, f"mailboxIds/{boxes.get('drafts') or boxes['inbox']}": None}
        if boxes.get("sent"):
            after[f"mailboxIds/{boxes['sent']}"] = True
        answered = jmap(
            ctx,
            account,
            [
                ["Email/set", {"accountId": setup["accountId"], "create": {"draft": draft}}, "s"],
                [
                    "EmailSubmission/set",
                    {
                        "accountId": setup["accountId"],
                        "create": {"sub": {"emailId": "#draft", "identityId": setup["identityId"]}},
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
                str(refused.get("description") or refused.get("type") or name or "the provider said nothing")
            )
    except MailError as exc:
        ctx.records.patch(MESSAGE, message.id, status="failed", note=str(exc))
        return False
    return True
