# End-to-end smoke test (against a real Nextcloud Talk instance)

This walks the bridge from zero to a verified round-trip on a live Talk server,
testing the riskiest, least-mockable paths first. Budget ~20 minutes.

Everything before this has only been tested against mocks and a local
`opencode serve` — this checklist is what turns "works in theory" into "works".

---

## 0. Prerequisites & the one non-obvious gotcha

**You need two distinct Talk users:**

- a **bot account** → goes in `NC_USER` / `NC_APP_PASSWORD`. The bridge logs in as
  this account, polls, and posts replies.
- **your controlling account** → goes in `ALLOWED_USERS`. This is who types commands.

They **must be different**. The bridge ignores its own messages (loop
prevention), so if `NC_USER` == the account you type from, nothing will ever
respond. A dedicated bot/functional account is ideal; otherwise use a colleague's
account or any second login. Both accounts must be participants in the same
conversation.

Also needed:
- A running `opencode serve` (see step 3).
- `opencode-talk-bridge` installed (`uv tool install …` or from source).

## 1. Gather the three Talk facts

1. **App password** for the bot account: Nextcloud → Settings → Security →
   "Devices & sessions" → *Create new app password*. Copy it now (shown once).
   Use this, **not** the login password.
2. **Conversation token**: open the control conversation in the Talk web UI; the
   URL is `…/call/<TOKEN>` (e.g. `…/call/a1b2c3d4`). The token is `a1b2c3d4`.
   Add the bot account as a participant in that conversation.
3. **Your user ID**: the stable login of your controlling account (e.g. `pleiverkus`),
   **not** the display name. This is what goes in `ALLOWED_USERS`.

## 2. Create the config

```bash
opencode-talk-bridge --init
```

Or write `.env` by hand:

```ini
NC_URL=https://cloud.uni-oldenburg.de
NC_USER=opencode-bot                 # the BOT account
NC_APP_PASSWORD=xxxxx-xxxxx-xxxxx-xxxxx-xxxxx
TALK_CONVERSATIONS=a1b2c3d4          # the conversation token from step 1
ALLOWED_USERS=pleiverkus             # YOUR login, not the bot's
OPENCODE_URL=http://127.0.0.1:4096
OPENCODE_DIRECTORY=/Users/you/path/to/your/project   # makes /sessions match desktop
```

## 3. Start OpenCode

```bash
cd /path/to/your/project
opencode serve --port 4096 --hostname 127.0.0.1
```

(If you secure it, set `OPENCODE_SERVER_PASSWORD` on the server and
`OPENCODE_USERNAME`/`OPENCODE_PASSWORD` in `.env`.)

## 4. Pre-flight: config + health

```bash
opencode-talk-bridge --check
```

Expect: `config OK; OpenCode at http://127.0.0.1:4096: healthy`.
- `configuration error: …` → fix `.env` (missing/empty required key).
- `UNREACHABLE` → OpenCode isn't running or the URL/port is wrong.

## 5. ⭐ Riskiest test first: allowlist + actor identity

This is the single most important check, because the allowlist depends on Talk
returning a stable `actorId` per message — a detail that was never verifiable
without a live server.

1. Run the bridge with debug logging: `LOG_LEVEL=DEBUG opencode-talk-bridge`.
2. From **your** account, post `hi` in the conversation.
3. **Expect:** the bridge reacts (a `🔧 …` / streamed reply appears).
   - If it logs `ignoring message from <id> (<type>)` for *your* message, the
     `actorId` the server returns doesn't match `ALLOWED_USERS` — copy the exact
     id from the log into `ALLOWED_USERS` and restart. (This is the value to trust.)
4. From a **different, non-allowlisted** account (or ask a colleague), post a
   message. **Expect:** it is silently ignored (logged, no reply).

✅ If allowlisted messages act and others are ignored, the security model works
on this instance — the rest is downhill.

## 6. Core round-trip + streaming

From your account: `Reply with exactly the word PONG.`
- **Expect:** a `🔧 OpenCode arbeitet …` message that then **edits in place** to the
  answer (live streaming). If editing fails on your Talk version, you'll instead
  get separate messages — note it; set `RESPONSE_STREAMING=false` as a fallback.

## 7. Commands & pickers

| Send | Expect |
|---|---|
| `/help` | command list |
| `/status` | OpenCode ✅, session id, model, agent |
| `/sessions` | numbered list of **your project's** sessions (matches OpenCode desktop) |
| `/projects` | numbered list of all projects; pick one → "Projekt gewechselt" |
| `/model` | numbered model list (or the `/model providerID/modelID` hint if none) |
| `/new` then a prompt | a fresh session id in `/status` |

Reply to any picker with the **number** (Talk has no buttons).

## 8. ⭐ Permission flow (the safety-critical path)

Send a prompt that writes a file, e.g. `Create a file hello.txt with "hi".`
- **Expect:** a `🔐 OpenCode möchte … ausführen` prompt.
- Reply `nein` → the action is rejected. Then try again and reply `ja` → it
  proceeds. Confirm a denied action really does **not** happen.

## 9. Agent questions

Trigger an agent question (e.g. a task where the agent asks you to choose).
- **Expect:** a `❓` prompt with numbered options; reply with a number (or free
  text if it allows custom). Verify the answer reaches the agent.

## 10. File attachment output

Ask for a lot of code: `Write a 200-line Python script and show it.`
- **Expect:** if `SHARE_WEBDAV_DIR` is set, the answer arrives as a **shared file**;
  otherwise as text. (If you set `SHARE_WEBDAV_DIR`, verify the file actually
  appears in that Nextcloud folder and the share isn't "not found".)

## 11. Optional subsystems (only if configured)

- **File input:** attach an image/PDF to a message with a question about it →
  the agent should receive the file.
- **Voice (STT):** with `STT_*` set, send a voice note → it's transcribed and used
  as the prompt.
- **TTS:** `/tts` to enable (needs `TTS_*` + `SHARE_WEBDAV_DIR`) → the next answer
  also arrives as an audio file.
- **Scheduler:** `/task 1 say hi` → after ~1 minute, a prompt fires automatically;
  `/tasklist` shows it (for recurring) or it's gone (one-shot).

## 12. Persistence & shutdown

1. `Ctrl-C` the bridge (clean shutdown; `status.json` → `stopped`).
2. Restart it. **Expect:** it does **not** replay old messages (the
   `last_known_message_id` cursor survived), and `/session` still shows the bound
   session.

---

## Diagnostics

- **Logs:** run with `LOG_LEVEL=DEBUG`. The poll loop, allowlist decisions, and
  errors are logged per conversation token.
- **Status file:** `cat status.json` → `{state, opencode_healthy, last_error, …}`.
- **Nothing responds at all:** almost always the two-accounts gotcha (§0) or the
  `actorId` mismatch (§5). Check the debug log for `ignoring message from …`.
- **HTTP 401 from Talk:** wrong `NC_APP_PASSWORD` or `NC_USER` (use the app
  password, not the login password).
- **`opencode_down`:** OpenCode server not reachable; re-check step 3/4.
- **Permission/question never appears:** the bridge only routes asks for sessions
  it created/owns; make sure the prompt actually triggered a tool that needs
  approval (file write / shell), and that streaming/SSE is reaching the bridge
  (you'd see tool `💻` notices for an active turn).

When all of §5, §6, §8 pass against your real instance, the bridge has crossed
from "mock-tested" to "verified in practice."
