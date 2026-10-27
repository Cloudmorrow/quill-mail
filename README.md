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
4. Under **Accounts**, add an account outside the server: a Fastmail
   account with an API token (Settings › Privacy & Security › Integrations
   › API tokens, with mail access). Its inbox is fetched when you open Mail
   — the newest fifty, threaded as the provider threads them — and **Fetch
   now** reads it at once. Mail to an outside address, `ada@example.org`,
   is sent through it, from its address; a mail to `ada@example.org, kim`
   reaches both.
5. The token is a secret: sealed at rest, listed to nobody, read only by
   Mail's own code, as you, from the sandbox. Mail reaches Fastmail's API
   and nothing else; another JMAP server is a line in the manifest and a
   release.

Everything happens through the record API, as the person using it: an
administrator's mail is theirs, and the server has no mailbox of its own.
There is no program beside the server, no IMAP, no SMTP: a provider with an
HTTPS API is the one kind of outside account that fits a Quill's code.

## What it adds to your Cloudmorrow

| | |
| --- | --- |
| Datamodels | introduces `mail.thread` (a conversation: a space the people in it share, or its owner's own when it came from outside), `mail.message` (one mail in a thread: from, to, cc, the text, when; a push to everybody in the thread, counted as unread), `mail.state` (where you filed a thread: inbox, archive, trash) and `mail.account` (an outside account: its JMAP session and a token, sealed) |
| Screens | Mail (a view: a folder's threads, or one thread with its messages and the reply box) and Accounts — on the phone, the web app, the terminal, `cm mail`, and to your assistant |
| Actions | Write; on a thread: Reply, Archive, Delete, Move to inbox, Delete for good; Add an account; on an account: Fetch now, Remove |
| Code | `quill.py`, in the sandbox, as whoever uses it; reaches `api.fastmail.com` and nothing else |

Mail needs no other Quill and no runtime. It needs the core's SDK from
v0.57.0 (`ctx.records.create` with `scope` and `members`, `ctx.records.seen`,
`ctx.people()`, and a table whose rows go to a screen).

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
