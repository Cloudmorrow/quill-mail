"""Mail: the code behind the Mail screen, its buttons, and the server's domain.

Run in the sandbox as whoever is looking. A conversation is a thread, a
space: one between people on the server is shared with them, and what is
written in it reaches them through the core (a push, an unread count), so
there is no delivery here, only writing. Everybody has an address on the
cloud itself, name@the-cloud, which never leaves the server; when an
administrator has given the server a domain through Cloudflare, everybody
is name@that-domain to the outside world as well, mail to it is pulled in
by the `pull` job and mail out goes through Cloudflare, as the person
writing. Nothing else leaves the server, and nothing runs beside it.
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
    redraw,
    toast,
    ui,
    view,
)

THREAD, MESSAGE, STATE, DOMAIN = (
    "mail.thread",
    "mail.message",
    "mail.state",
    "mail.domain",
)
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
# Where an administrator finds the Quill's settings, for a word to everybody else.
SETTINGS_ARE = "Administration › Quills › Mail"
# What the Cloudflare token must be allowed, said on the settings page and on the
# form that takes it: each right, and what Mail does with it.
TOKEN_RIGHTS = """\
At Cloudflare: *My Profile › API Tokens › Create Token › Custom token*, with these permissions and nothing more:

- **Zone › Zone › Read** — to list your domains and pick one
- **Zone › Email Routing Rules › Edit** — to turn Email Routing on and point the catch-all at the Worker
- **Account › Workers Scripts › Edit** — to put the small Worker that takes the mail in into your account
- **Account › Workers KV Storage › Edit** — to make the namespace the Worker puts mail in, and to read and clear it every minute
- **Account › Email Sending › Edit** — to send mail from the domain

Zone Resources: the zone of the domain (or all zones). Account Resources: the account it is in. Copy the token when it is shown; it is shown once, and kept here sealed."""
SPLIT = re.compile(r"[,;\s]+")
# How much of a mail's first line a row of the list shows.
PREVIEW = 60


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


def preview_of(message):
    """The first line of a mail, cut short, for a row of the list."""
    line = next(
        (ln.strip() for ln in str(message["body"]).splitlines() if ln.strip()), ""
    )
    return line if len(line) <= PREVIEW else line[: PREVIEW - 1].rstrip() + "…"


# -- addresses ---------------------------------------------------------------------------
# Everybody on the server is name@the-cloud: the cloud's name, as an address
# can carry it. With a domain set up, they are name@the-domain too, to the
# world outside; the cloud address still reaches them from inside.
def cloud_host(ctx):
    host = re.sub(r"[^a-z0-9.-]+", "-", str(ctx.cloud or "").strip().lower()).strip(
        "-."
    )
    return host or "cloud"


def the_domain(ctx):
    """The server's domain, ready for mail, or None. The token is not in a listing."""
    for found in ctx.records.list(DOMAIN):
        if found.get("zone") and found.get("namespace"):
            return found
    return None


def any_domain(ctx):
    found = ctx.records.list(DOMAIN)
    return found[0] if found else None


def address_of(ctx, name, domain=None):
    """Somebody's address: on the domain when the server has one, else on the cloud."""
    if domain is not None and domain.get("domain"):
        return f"{name}@{domain['domain']}"
    return f"{name}@{cloud_host(ctx)}"


def my_address(ctx, domain):
    return address_of(ctx, ctx.user.username, domain)


def said_sender(ctx, sender, domain):
    """A message's sender as the inbox says it: a name here with its address, an outside address as it is."""
    sender = str(sender or "")
    return sender if "@" in sender else address_of(ctx, sender, domain)


def sort_out(ctx, *texts):
    """Who a mail goes to: names on the server (typed as names, or as their
    address on the cloud or the domain), outside addresses, and names nobody has."""
    me = ctx.user.username
    people = set(ctx.people())
    domain = the_domain(ctx)
    ours = {cloud_host(ctx)}
    if domain is not None and domain.get("domain"):
        ours.add(str(domain["domain"]).lower())
    users, addresses, unknown = [], [], []
    for text in texts:
        for name in names_in(text):
            local, at, host = name.partition("@")
            if at and host in ours:
                name = local
            if name == me:
                continue
            if name in people:
                if name not in users:
                    users.append(name)
            elif at and host not in ours and "." in host:
                if name not in addresses:
                    addresses.append(name)
            else:
                unknown.append(name)
    return users, addresses, unknown


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


def others_in(ctx, thread, me, domain):
    """Who else is in the thread, as the inbox says it: their addresses."""
    if thread["kind"] == "external":
        return str(thread.get("addresses") or "")
    people = [thread.owner, *thread.members]
    named = [p for p in dict.fromkeys(people) if p and p != me]
    return ", ".join(address_of(ctx, p, domain) for p in named) or "me"


def newest(thread, lines):
    if lines:
        return sent_at(lines[-1])
    last = thread.last or {}
    return str(last.get("when") or thread.created_at or "")


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


def siblings_of(ctx, thread):
    """Every thread of this conversation, the opened one included."""
    if thread["kind"] != "external" or not thread.get("remote"):
        return [thread]
    found = ctx.records.list(THREAD, remote=str(thread["remote"]))
    return found or [thread]


# -- the inbox ---------------------------------------------------------------------------
@view("mail")
def mail(ctx):
    """An inbox: the list on the left, the open mail on the right; on a phone
    the list, then the mail once one is chosen."""
    folder = str(ctx.params.get("folder") or "inbox")
    if folder not in dict(FOLDERS):
        folder = "inbox"
    opened = str(ctx.params.get("thread") or "")
    side = listed(ctx, folder, opened)
    if opened:
        main = one_thread(ctx, opened, folder)
    else:
        main = ui.empty("Choose a mail on the left, or send a new one.")
    return ui.split(side, main, show="main" if opened else "side")


def whoami(ctx, domain):
    """The line over the inbox: your address, and where mail from outside stands."""
    mine = f"You are {my_address(ctx, None)}"
    if domain is not None:
        return f"{mine}, and {my_address(ctx, domain)} to the world outside."
    if ctx.user.admin:
        return f"{mine}. Mail stays on this server until you give it a domain under {SETTINGS_ARE}."
    return f"{mine}. Mail stays on this server; an administrator can give it a domain."


def listed(ctx, folder, opened=""):
    """The list: New mail, the folders with what is unread counted, your
    address, and a card per conversation — who, the subject, the first line."""
    me = ctx.user.username
    now = ctx.now()
    domain = the_domain(ctx)
    filed = filings(ctx)
    by_thread = messages_by_thread(ctx)
    rows, unread_in = [], dict.fromkeys(dict(FOLDERS), 0)
    for group in conversations(ctx.records.list(THREAD)):
        lines = sorted((m for t in group for m in by_thread.get(t.id, [])), key=sent_at)
        thread = max(group, key=lambda t: newest(t, by_thread.get(t.id, [])))
        where = folder_of(thread, filed, lines, me)
        unread = any(t.unread > 0 for t in group)
        if unread:
            # The count on a folder is what is unread in it; Sent carries none,
            # as an inbox has it: what you wrote is not news to you.
            for name in unread_in:
                if name != "sent" and in_folder(name, thread, lines, me, where):
                    unread_in[name] += 1
        if not in_folder(folder, thread, lines, me, where):
            continue
        last = lines[-1] if lines else None
        if folder == "sent":
            who = others_in(ctx, thread, me, domain)
        elif last is not None:
            who = said_sender(ctx, last["sender"], domain)
        else:
            who = others_in(ctx, thread, me, domain)
        when = said_when(newest(thread, lines), now)
        rows.append(
            (
                newest(thread, lines),
                {
                    "id": thread.id,
                    "model": THREAD,
                    "fields": {
                        "subject": ("● " if unread else "") + str(thread["subject"]),
                        "who": f"{who} · {when}" if when else who,
                        "preview": preview_of(last) if last is not None else "",
                    },
                },
            )
        )
    rows.sort(key=lambda pair: pair[0], reverse=True)
    bar = []
    for key, name in FOLDERS:
        bar.append(
            ui.button(
                f"{name} · {unread_in[key]}" if unread_in[key] else name,
                go="mail",
                params={"folder": key},
            )
        )
    return ui.stack(
        ui.button("New mail", action="send", tone="primary"),
        ui.row(*bar),
        ui.text(whoami(ctx, domain), style="small"),
        ui.cards(
            [row for _, row in rows],
            title="subject",
            subtitle="who",
            body="preview",
            go="mail",
            param="thread",
            params={"folder": folder},
            current=opened,
            empty=EMPTY.get(folder, f"Nothing in {dict(FOLDERS)[folder]}."),
        ),
    )


EMPTY = {
    "inbox": "Nothing new. Send a mail to somebody on this server by name, or by their address.",
    "sent": "Nothing sent yet.",
}


def one_thread(ctx, thread_id, folder):
    me = ctx.user.username
    now = ctx.now()
    domain = the_domain(ctx)
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
        through = f"Outside, from {thread.get('address') or my_address(ctx, domain)}"
    else:
        through = "On this server"
    parts = [
        ui.text(str(thread["subject"]), style="title"),
        ui.text(
            f"With {others_in(ctx, thread, me, domain)} · {through}", style="muted"
        ),
    ]
    for m in lines:
        head = f"From {said_sender(ctx, m['sender'], domain)} · {said_when(sent_at(m), now)}"
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
    buttons = []
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
        *parts,
        ui.divider(),
        ui.text("Reply", style="subtitle"),
        ui.form("reply", record=thread, submit="Send"),
        ui.row(*buttons),
    )


# -- writing -----------------------------------------------------------------------------
def to_said(ctx, users, addresses, domain):
    """Who a mail went to, as the message keeps it: everybody's address."""
    return ", ".join([address_of(ctx, u, domain) for u in users] + list(addresses))


@action("send")
def send_mail(ctx, to, subject, body, cc="", bcc=""):
    users, addresses, unknown = sort_out(ctx, to, cc, bcc)
    if unknown:
        return error(
            f"Nobody here is called {', '.join(unknown)}; a name on this server, or an email address"
        )
    if not users and not addresses:
        return error("Who is it to? A name on this server, or an email address")
    domain = the_domain(ctx)
    if addresses and domain is None:
        return error(
            "Mail to an address outside this server needs the server's own domain, "
            f"which an administrator sets up under {SETTINGS_ARE}"
        )
    me = ctx.user.username
    cc_users, cc_addresses, _ = sort_out(ctx, cc)
    bcc_users, bcc_addresses, _ = sort_out(ctx, bcc)
    to_users = [u for u in users if u not in cc_users and u not in bcc_users]
    to_addresses = [
        a for a in addresses if a not in cc_addresses and a not in bcc_addresses
    ]
    open_users = to_users + [u for u in cc_users if u not in bcc_users]
    fields = {
        "subject": str(subject).strip(),
        "kind": "external" if addresses else "internal",
    }
    if addresses:
        fields["addresses"] = ", ".join(a for a in addresses if a not in bcc_addresses)
        fields["address"] = my_address(ctx, domain)
        fields["remote"] = conversation_key(
            fields["subject"], (to_addresses or addresses)[0]
        )
    said_to = to_said(ctx, to_users, to_addresses, domain)
    said_cc = to_said(ctx, cc_users, cc_addresses, domain)
    thread = ctx.records.create(
        THREAD,
        fields,
        scope="shared" if open_users else "personal",
        members=open_users,
        announce=False,
    )
    message = ctx.records.create(
        MESSAGE,
        thread=thread.id,
        sender=me,
        to=said_to,
        cc=said_cc,
        body=str(body),
        sent_at=ctx.now().isoformat(),
    )
    # Somebody in Bcc gets a copy of their own, shared with nobody else: the
    # thread the others are in never names them, and they never see each other.
    for who in bcc_users:
        if who in open_users:
            continue
        copy = ctx.records.create(
            THREAD,
            {"subject": fields["subject"], "kind": "internal"},
            scope="shared",
            members=[who],
            announce=False,
        )
        ctx.records.create(
            MESSAGE,
            thread=copy.id,
            sender=me,
            to=said_to,
            cc=said_cc,
            body=str(body),
            sent_at=ctx.now().isoformat(),
        )
    if addresses:
        send_domain(
            ctx, domain, thread, message, to_addresses + cc_addresses, bcc=bcc_addresses
        )
    return go("mail", thread=thread.id, folder="sent")


@action("reply")
def reply(ctx, thread, body):
    me = ctx.user.username
    domain = the_domain(ctx)
    message = ctx.records.create(
        MESSAGE,
        thread=thread.id,
        sender=me,
        to=others_in(ctx, thread, me, domain),
        body=str(body),
        sent_at=ctx.now().isoformat(),
    )
    if thread["kind"] == "external":
        if domain is None:
            ctx.records.patch(
                MESSAGE,
                message.id,
                status="failed",
                note="the server has no mail domain any more",
            )
        else:
            send_domain(ctx, domain, thread, message, names_in(thread.get("addresses")))
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


# -- reaching out ----------------------------------------------------------------------
class MailError(Exception):
    """What Cloudflare, or the way to it, said."""


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


# -- the server's own domain, through Cloudflare ---------------------------------------------
# One record of `mail.domain`, a public space: everybody's code reads it (the
# domain, to say their address; the token, sealed, to send as them) and an
# administrator alone changes it. The postman is the `pull` job: every minute,
# as the administrator who installed Mail, it takes what the Worker put in the
# KV namespace and delivers each mail to the person it is for — a thread and a
# message of theirs, news to them — and sees nothing of it afterwards.
def token_of(ctx, domain):
    """The sealed token, read from the one record: how a secret field is asked for."""
    token = str(ctx.records.get(DOMAIN, domain.id).get("token") or "")
    if not token:
        raise MailError("the domain has no token; connect Cloudflare again")
    return token


def administrators_only(ctx):
    return (
        None
        if ctx.user.admin
        else error("The mail domain is an administrator's to set up")
    )


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
    """The server's domain: drawn on Mail's sheet under Administration › Quills,
    for an administrator alone."""
    if not ctx.user.admin:
        return ui.empty("The mail domain is an administrator's to set up.")
    domain = any_domain(ctx)
    me = ctx.user.username
    people = sorted({me, *ctx.people()})
    if domain is None:
        return ui.stack(
            ui.text(
                f"Everybody on this server is name@{cloud_host(ctx)} already: "
                + ", ".join(address_of(ctx, who) for who in people)
                + ". That mail stays on the server.",
                style="muted",
            ),
            ui.text(
                "Your own domain for everybody, through your Cloudflare account: name@your-domain "
                "for each person, mail in through Email Routing and a Worker, mail out through Cloudflare's "
                "Email Service. Nothing runs anywhere but in your account; Cloudmorrow holds none of it.",
                style="muted",
            ),
            ui.text(
                "First, at Cloudflare: the domain is on Cloudflare, and under Compute › Email Service › Email "
                "Sending it is onboarded for sending (that needs the Workers Paid plan; receiving is free).",
                style="muted",
            ),
            ui.text("The token", style="subtitle"),
            ui.markdown(TOKEN_RIGHTS),
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
                "Connected to Cloudflare. Which domain is the server's?",
                style="subtitle",
            ),
            [ui.text(said, style="muted")] if said else [],
            *rows,
            ui.divider(),
            ui.button("Disconnect", action="disconnect", tone="danger"),
        )
    return ui.stack(
        ui.text(str(domain["domain"]), style="subtitle"),
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
            + ", ".join(address_of(ctx, who, domain) for who in people)
            + f". Inside the server they are still name@{cloud_host(ctx)}.",
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
    return redraw()


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
    return redraw()


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
def send(ctx, domain, sender, to, cc, subject, text, bcc=()):
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
    if bcc:
        message["bcc"] = list(bcc)
    cf(
        ctx,
        token,
        f"/accounts/{domain['account']}/email/sending/send",
        method="POST",
        json_body=message,
    )


def send_domain(ctx, domain, thread, message, addresses, bcc=()):
    """Send a message from the person's address on the server's domain: True when
    Cloudflare took it, else the message says what went wrong."""
    cc = [a for a in names_in(message.get("cc")) if "@" in a]
    to = [a for a in addresses if a not in cc and a not in bcc]
    try:
        send(
            ctx,
            domain,
            my_address(ctx, domain),
            to,
            cc,
            thread["subject"],
            message["body"],
            bcc=[a for a in bcc if "@" in a],
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
