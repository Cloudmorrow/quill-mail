# Mail

Email for everybody on your server: an inbox each, `name@your-cloud`
between you, and `name@your-own-domain` to the world outside once an
administrator has set the domain up. A
[Quill](https://github.com/Cloudmorrow/cloudmorrow/blob/main/docs/QUILLS.md)
for Cloudmorrow, drawn on the phone, in the web app, in the terminal and on
the command line by Cloudmorrow itself.

## How it works

1. **Everybody has an address.** On a cloud called Bramcloud, Sam is
   `sam@bramcloud`: the inbox says so at the top. Mail to it never leaves
   the server. Nobody chooses anything; there is nothing to set up.
2. **New mail** — the pen beside the title, as Notes and Tasks have it — opens the form: To, with the people on the server offered
   as you type (an address outside the server is taken too, with a word of
   warning under the field), **Cc, Bcc** behind one link when you want
   them, the subject and the text; then **Send**. It is a thread the
   people in it share, they get a push, and it is counted as unread until
   they open it. Somebody in Bcc gets a copy of their own that names
   nobody else. What you sent is in your **Sent**; it lands in your
   **Inbox** when somebody answers.
3. The inbox is a list on the left — the subject, who, when, the first
   line; a dot on what you have not read, and the count of it on the
   folder — and the open mail on the right, lit in the list. On a phone
   it is the list, then the mail. Answer in the **Reply** box under the
   last message: the answer stays with what it answers, for everybody in
   the thread.
4. **Archive** takes a thread out of your inbox alone, and it comes back the
   moment somebody writes in it again. **Delete** moves it to your Trash.
   Whoever started a thread can delete it for good, from Trash, for
   everybody in it; nobody else's copy moves when you file yours.
5. **Your own domain, for everybody.** An administrator connects the
   server's Cloudflare account on Mail's sheet under **Administration ›
   Quills** and picks a domain; from then on every person is
   `name@that-domain` to the outside world as well, mail to it lands in
   their inbox, and what they write to an outside address goes out from it.
   How to set it up is below. Until then, mail to an outside address is
   refused with a word about where the setting is.

Everything happens through the record API, as the person using it: an
administrator's mail is theirs, and the server has no mailbox of its own.
There is no program beside the server, no IMAP, no SMTP, and no accounts
of anybody's own to connect: every setting is the administrator's, in the
one place settings are.

## Your own domain, through Cloudflare

Mail for `name@your-domain` reaches the server, and goes out from it, with
nothing but your Cloudflare account between: no mail server to run, no
port to open, no address from outside. Cloudmorrow runs none of it and
holds none of it; the domain, the account and the token are yours. Once
set up, every person on the server has an address on the domain, and
anybody added later has one the moment they are.

**What it costs.** Receiving is free. Sending needs Cloudflare's Workers
Paid plan, five dollars a month, which includes three thousand mails;
Email Sending is in beta at Cloudflare. Without the paid plan mail comes
in; what goes out is refused by Cloudflare and the thread says so.

**Before you start.** The domain is on Cloudflare: its nameservers are
Cloudflare's. That is all receiving needs; Mail turns Email Routing on
for you. Sending needs two more things, both in the Cloudflare dashboard
under *Compute › Email Service › Email Sending*, and both can be done
after connecting:

- **Enable Email Sending** on the account (the Workers Paid plan).
- **Onboard the domain**: press *Onboard Domain*, pick the domain, *Done*.
  Cloudflare puts MX, SPF and DKIM records on `cf-bounce.your-domain` and a
  DMARC record on `_dmarc`, and they are live within fifteen minutes.
  Enabling the feature alone is not enough: until the domain is onboarded
  Cloudflare refuses every send with "sending disabled for this zone".

**The token.** At Cloudflare, *My Profile › API Tokens › Create Token ›
Custom token*. Under Permissions, add these five rows; under Resources,
*All accounts* and *All zones* is simplest:

| where | permission | what Mail does with it |
| --- | --- | --- |
| Account | Workers Scripts · Edit | the small Worker that takes the mail in |
| Account | Workers KV Storage · Edit | the namespace the Worker puts mail in, read and cleared every minute |
| Account | Email Sending · Edit | mail out from the domain |
| Zone | Zone · Read | to list your domains |
| Zone | Email Routing Rules · Edit | Email Routing on, the catch-all at the Worker |

If getting the five right is a fight, a token allowed more works just as
well: Mail only ever does these five things with it. It can do more in
your account if it leaks, so keep it to the five when you can. The Global
API Key is not a token and does not work. Copy the token when it is shown:
it is shown once, and Mail keeps it sealed.

**Under Administration › Quills, on Mail's sheet** (an administrator sees
it; nobody else does; the gear on Mail's row in the list opens it, and in
the terminal `s` on Mail does):

1. **Connect Cloudflare** with the token. It is kept sealed, listed to
   nobody, read only by Mail's own code. A token that sees one domain
   sets that domain up at once; with more, the domains are listed and
   **Use this domain** picks one. Mail then turns Email Routing on for the
   zone, makes a KV namespace called `cloudmorrow-mail` in the account (or
   finds the one it made before), puts a small Worker of the same name
   there (`worker.js` in this repository: it takes every mail for the
   domain and puts it in the namespace, as it came), and points the zone's
   catch-all rule at the Worker. Everything is in your account, under
   those names, where you can read and remove it.
2. From then on the server pulls the namespace once a minute and delivers
   each mail to the person it is addressed to: a thread of their own,
   unread, with a push. A mail to an address nobody has is dropped and
   said on the sheet. The postman — the job, run as the administrator —
   sees nothing of anybody's mail once delivered.
3. **Send a test mail to me**: out through Cloudflare, back in through the
   Worker, in your inbox within two minutes if everything is in place. How
   it went stays under the button until the next one: *Sent*, with the
   time; or *Not sent*, with Cloudflare's refusal read for you — the
   domain not onboarded yet, the account not entitled, sending paused —
   and what to do. If it is sent and never arrives, Email Routing's log
   at Cloudflare says where it went.
4. **Set the domain up again** redoes the routing, the Worker and the
   catch-all, and stamps the status with the time. It has nothing to do
   with sending.

**What everybody gets.** Their address is `username@the-domain`, said at
the top of their inbox beside their address on the cloud, and on their
outside threads as *Outside, from name@domain*. Mail to a person by either
address stays on the server. A reply from outside is drawn in the
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
| Datamodels | introduces `mail.thread` (a conversation: a space the people in it share, or its owner's own when it is with the world outside), `mail.message` (one mail in a thread: from, to, cc, the text, when; a push to everybody in the thread, counted as unread), `mail.state` (where you filed a thread: inbox, archive, trash) and `mail.domain` (the server's domain on Cloudflare: one public record, changed by an administrator, its token sealed) |
| Screens | Mail (a view: a folder's conversations on the left, the open one with its messages and the reply box on the right) — on the phone, the web app, the terminal, `cm mail`, and to your assistant; and Mail domain, an administrator's alone, drawn on Mail's sheet under Administration › Quills |
| Actions | Send (To with the server's people offered, Cc and Bcc behind a link, a warning for an address outside); on a thread: Reply, Archive, Delete, Move to inbox, Delete for good; for an administrator: Connect Cloudflare, Use this domain, Send a test mail to me, Disconnect |
| Jobs | `pull`, every minute, as the administrator who installed Mail: what the Worker took in, delivered to whoever it is for |
| Code | `quill.py`, in the sandbox, as whoever uses it; reaches `api.cloudflare.com` and nothing else |

Mail needs no other Quill and no runtime. It needs the core from v0.70.0 (a view's `compose`), and from v0.69.0:
the `split` layout, `cards(current=)`, a form field with `suggest =
"people"`, `outside` and `extra`, besides v0.67.0's `ctx.cloud` (the
cloud's name, for everybody's address) and a screen marked `admin = true`
drawn under Administration › Quills, and
v0.65.0's job delivery (`ctx.records.create(..., owner=, by=)`) and
v0.60.0's spaces SDK.

## Working on it

```
uv sync                  # .venv with Cloudmorrow and pytest
cm quill check           # the manifest, as a server would install it
cm quill test            # tests/, against the real record store and gate
cm quill test --sandbox  # the same, with quill.py in the sandbox
cm quill dev --local     # a throwaway server here, reinstalled as you save
```

The tests stand in for Cloudflare: what `ctx.fetch` gets is put in the
test (`q.fetch.add`), and nothing reaches the network.
