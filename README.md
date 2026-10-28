# Mail

Email for everybody on your server, and your own accounts outside it. A
[Quill](https://github.com/Cloudmorrow/cloudmorrow/blob/main/docs/QUILLS.md)
for Cloudmorrow, drawn on the phone, in the web app, in the terminal and on
the command line by Cloudmorrow itself.

## How it works

1. **Write** to anybody on the server by name — `sam`, or `sam, kim` — with a
   subject and the text. The mail never leaves the server: it is a thread the
   people in it share, they get a push, and it is counted as unread until
   they open it. What you started is in your **Sent**; it lands in your
   **Inbox** when somebody answers.
2. Open a thread to read it, oldest first, and **Reply**: the answer stays
   with what it answers, for everybody in the thread.
3. **Archive** takes a thread out of your inbox alone, and it comes back the
   moment somebody writes in it again. **Delete** moves it to your Trash.
   Whoever started a thread can delete it for good, from Trash, for
   everybody in it; nobody else's copy moves when you file yours.
4. **Your own domain, for everybody.** An administrator connects the
   server's Cloudflare account under **Settings** and picks a domain; from
   then on every person is `name@that-domain`, mail to it lands in their
   inbox, and what they write to an outside address goes out from it. How
   to set it up is below.
5. Under **Accounts**, add an account outside the server: a Fastmail
   account with an API token (Settings › Privacy & Security › Integrations
   › API tokens, with mail access). Its inbox is fetched when you open Mail
   — the newest fifty, threaded as the provider threads them — and **Fetch
   now** reads it at once. Mail to an outside address, `ada@example.org`,
   is sent through it, from its address; a mail to `ada@example.org, kim`
   reaches both.
6. The token is a secret: sealed at rest, listed to nobody, read only by
   Mail's own code, as you, from the sandbox. Mail reaches Fastmail's API
   and nothing else; another JMAP server is a line in the manifest and a
   release.

Everything happens through the record API, as the person using it: an
administrator's mail is theirs, and the server has no mailbox of its own.
There is no program beside the server, no IMAP, no SMTP: a provider with an
HTTPS API is the one kind of outside account that fits a Quill's code, and
Cloudflare's is how the server's own domain works too.

## Your own domain, through Cloudflare

Mail for `name@your-domain` reaches the server, and goes out from it, with
nothing but your Cloudflare account between: no mail server to run, no
port to open, no address from outside. Cloudmorrow runs none of it and
holds none of it; the domain, the account and the token are yours. Once
set up, every person on the server has an address on the domain, and
anybody added later has one the moment they are.

**What it costs.** Receiving is free. Sending needs Cloudflare's Workers
Paid plan, five dollars a month, which includes three thousand mails;
Email Sending is in beta at Cloudflare. Without the paid plan everything
else works: mail comes in, and mail out goes through a person's own
account under Accounts when they have one.

**Before you start.** The domain is on Cloudflare: its nameservers are
Cloudflare's. Then, at Cloudflare under *Compute › Email Service › Email
Sending*, **onboard the domain**: Cloudflare adds the SPF, DKIM and DMARC
records itself. (Receiving needs no such step; Settings turns Email
Routing on for you.)

**The token.** At Cloudflare, *My Profile › API Tokens › Create Token ›
Custom token*, with these permissions:

| where | permission |
| --- | --- |
| Zone | Zone · Read |
| Zone | Email Routing Rules · Edit |
| Account | Workers Scripts · Edit |
| Account | Workers KV Storage · Edit |
| Account | Email Sending · Edit |

Zone Resources: the zone of the domain (or all zones). Account
Resources: the account it is in. Copy the token: it is shown once.

**In Mail › Settings** (an administrator sees it; nobody else does):

1. **Connect Cloudflare** with the token. It is kept sealed, listed to
   nobody, read only by Mail's own code.
2. The domains the token can see are listed. **Use this domain** on the
   one for mail. Mail then turns Email Routing on for the zone, makes a
   KV namespace called `cloudmorrow-mail` in the account, puts a small
   Worker of the same name there (`worker.js` in this repository: it takes
   every mail for the domain and puts it in the namespace, as it came),
   and points the zone's catch-all rule at the Worker. Everything is in
   your account, under those names, where you can read and remove it.
3. From then on the server pulls the namespace once a minute and delivers
   each mail to the person it is addressed to: a thread of their own,
   unread, with a push. A mail to an address nobody has is dropped and
   said on the Settings page. The postman — the job, run as the
   administrator — sees nothing of anybody's mail once delivered.
4. **Send a test mail to me**: out through Cloudflare, back in through the
   Worker, in your inbox within two minutes if everything is in place. If
   it is not sent, the reason is on the page; if it is sent and never
   arrives, Email Routing's log at Cloudflare says where it went.

**What everybody gets.** Their address is `username@the-domain`, shown on
their threads as *Outside, from name@domain*. A mail to an outside address
goes from it when the server has a domain, and through their own account
under Accounts otherwise; a thread that came through an account keeps
answering through that account. A reply from outside is drawn in the
conversation it answers.

**Limits, honestly.** Fifty recipients and five megabytes a mail, from
Cloudflare. Attachments are not kept yet: the text is. A mail larger than
1.5 MB is cut there. The Worker keeps a mail for two weeks if the server
is away. **Disconnect** forgets the domain and the token here; the Worker,
the namespace and the routing rule stay in your Cloudflare account, to
delete there or to use again.

## What it adds to your Cloudmorrow

| | |
| --- | --- |
| Datamodels | introduces `mail.thread` (a conversation: a space the people in it share, or its owner's own when it came from outside), `mail.message` (one mail in a thread: from, to, cc, the text, when; a push to everybody in the thread, counted as unread), `mail.state` (where you filed a thread: inbox, archive, trash), `mail.account` (an outside account: its JMAP session and a token, sealed) and `mail.domain` (the server's domain on Cloudflare: one public record, changed by an administrator, its token sealed) |
| Screens | Mail (a view: a folder's threads, or one thread with its messages and the reply box), Accounts, and Settings (administrators only: the server's domain) — on the phone, the web app, the terminal, `cm mail`, and to your assistant |
| Actions | Write; on a thread: Reply, Archive, Delete, Move to inbox, Delete for good; Add an account; on an account: Fetch now, Remove; for an administrator: Connect Cloudflare, Use this domain, Send a test mail to me, Disconnect |
| Jobs | `pull`, every minute, as the administrator who installed Mail: what the Worker took in, delivered to whoever it is for |
| Code | `quill.py`, in the sandbox, as whoever uses it; reaches `api.fastmail.com` and `api.cloudflare.com` and nothing else |

Mail needs no other Quill and no runtime. It needs the core from v0.65.0:
a screen marked `admin = true`, and a job delivering a record to somebody
(`ctx.records.create(..., owner=, by=)`), besides v0.60.0's spaces SDK.

## Working on it

```
uv sync                  # .venv with Cloudmorrow and pytest
cm quill check           # the manifest, as a server would install it
cm quill test            # tests/, against the real record store and gate
cm quill test --sandbox  # the same, with quill.py in the sandbox
cm quill dev --local     # a throwaway server here, reinstalled as you save
```

The tests stand in for the provider: what `ctx.fetch` gets is put in the
test (`q.fetch.add`), and nothing reaches the network.
