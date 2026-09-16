# Aion Progress

Last updated: 2026-09-15. Milestone snapshot, not a live view of files. The launch entry and current runtime facts determine which capabilities are active.

## Current Development: SDK Runtime (independent prototype)

- Entry: `prototype/.venv/bin/python prototype/sdk_demo.py`, branch `prototype/agents-sdk`. OpenAI Agents SDK 0.22.2 with an explicit Chat Completions compatible client; provider settings remain in `aion.json`, currently DeepSeek. No OpenAI hosted-only tools; tracing disabled; no OpenAI key required.
- Reuses the existing allowlisted startup background loader and `FileTools` for `list_directory` and `read_text_file`. No replacement of legacy chat loop or automatic context edits.
- User confirmed real DeepSeek Agent execution, directory listing, two-turn Session recall, README reading, and ordinary chat. These milestones are complete; do not repeatedly ask to redo them.
- SDK persistence now uses SDK SQLiteSession under `.aion/sdk-sessions/`, separate from legacy JSON snapshots. Normal launch starts a new session; `--resume` restores the most recently successfully saved SDK session, or `--resume ID` restores that specific SDK session. Continuing appends to the same session database.
- `--no-save`, `--smoke`, and `--smoke-files` use memory only and do not change the latest persistent session. They cannot be combined with `--resume`.
- Startup background is freshly loaded on each launch and is not restored as old system instructions. Historical tool results are historical evidence; current file state requires a new tool read.
- Each Runner.run permits at most 4 model calls. The legacy total limit of 8 tool calls and its per-turn time/fact injection are NOT implemented in this SDK runtime.

## Persistence Verification

- Offline integration verified two separate processes: chat and real local file tool execution → exit → restart with --resume → restored user/assistant/tool history → continued reply persisted to the same SQLite database.
- The model API was mocked in that test; SQLite, Runner, tool execution, process restart, and updated startup background were real. Do not describe this as a live DeepSeek restart test.
- Also checked new-session isolation, no-save behavior, credential redaction, restrictive filesystem permissions, missing/corrupt sessions, links, concurrent access rejection, and unchanged legacy fixtures.
- User confirmed live DeepSeek exit → restart with --resume → same session ID and 2 restored messages → correct recall of a test phrase → continued reply reported saved. Live persistence and first restoration are verified; no need to repeat the initial test. A second restart after the continued reply was not shown.
- Observed wording bug: model incorrectly denied persistence because its tools are read-only, despite successful program-managed SQLite saving/restoration. Runtime instructions now explicitly separate tool permissions, automatic Session persistence, new sessions, and --resume, and include actual restore status. The initial wording fix also passed a real DeepSeek test with synthetic background: the model correctly explained that read-only tools do not prevent automatic Session persistence and that --resume restores the same session. Subsequent capability-facts verification is recorded below; model adherence still requires observation during use.

- Codex verified the saved macOS Keychain credential could be read automatically, without asking for or printing the key.
- A subsequent real DeepSeek test used only generated disposable files/background and isolated SQLite storage. Three independent processes verified file tools → exit → restore 7 history items and recall the file marker → continue and exit → restore 9 items and recall the newly added marker; the final session contained 11 items. The existing personal session databases and latest pointer were not used or changed.
- This synthetic live test completes the second-restart/continued-persistence check. It does not claim to have rerun the full personal startup background or actual project README test.

## Runtime Capability Facts

- Implemented in `prototype/sdk_capabilities.py`: the SDK instructions callback generates current facts from registered tool objects, their capability metadata, allowed paths, and Session state. `run_agent` counts history before the current input is added.
- Facts distinguish history availability and program-managed persistence from filesystem write permission. They enumerate enabled tools and file/mail actions; unregistered capabilities must not be claimed. Facts are not written into historical Session messages.
- Earlier live DeepSeek verification with the full startup background correctly distinguished memory from file writes. This is an observed successful test, not a guarantee of all future model responses.

## Mail Prototype: Gmail Live Round Trip Verified; Reliability Pending

- `prototype/sdk_mail.py` wraps Himalaya with fixed arguments, account/limit validation, bounded output and execution time, and normalized errors. It exposes only unread envelope ID, sender, subject and date; no body, attachments, sending or mailbox modifications.
- Default launch does not register the mail tool. Explicit `--mail gmail` (or an explicit list of supported accounts) registers `list_unread` only for selected accounts and allows returned metadata to reach the configured model. Bare `--mail` is rejected. Restoring old history can still include previously saved mail results even without this flag.
- Capability facts separately describe mail and filesystem actions. Existing DeepSeek compatibility and legacy runtime remain unchanged.
- Offline fixtures and mocked SDK tool calls pass, including error and subprocess timeout handling. Gmail account access, real CLI JSON parsing, and a complete live Aion round trip were subsequently verified (see latest verification below). Other accounts and sustained reliability remain unverified.
- 2026-09-15 local verification: 47 SDK tests and 20 legacy tests passed. This run made no live model or mailbox requests.

## Legacy v0.3 (retained)

- Entry: `python3 aion.py`. Standard-library implementation with its own chat loop and provider adapter.
- JSON snapshots remain in `.aion/sessions/`. Legacy --resume loads the latest saved legacy session and creates a new snapshot file; --no-save disables writing. SDK runtime never reads, overwrites, or migrates these snapshots.
- Legacy implements per-request time and current-turn tool facts, at most 4 tool rounds and 8 tool calls. These are legacy behavior, not guarantees about SDK runtime.
- v0.1 real chat and v0.2 tools were user verified; legacy v0.3 persistence was tested offline. Do not infer legacy live persistence success from SDK tests.

## Shared Limits and Next Step

- Model tools are read-only; no shell, write/delete tools, background monitoring, or automatic personal-context updates.
- SQLite conversations and legacy JSON are local plaintext, not general long-term memory. SDK storage is Git-ignored and access restricted. Current key and common sk- strings are redacted before SDK persistence; this is not general secret detection or encryption.
- Restoring and continuing sends saved conversation/tool content to the currently configured provider, including if the provider changed. API credentials and provider configuration are not serialized into the Session.
- Next: use the verified Gmail metadata path within authorized scope and investigate safely captured failures if they recur; other accounts and broader mail features need separate validation. Review local mail changes and sanitize development documents before publishing them. Do not rebuild working Session persistence. Current user instructions override this snapshot.

## 2026-09-15 Mail Integration Follow-up

- Added aion-architecture to configured startup background; project-builder remains generic. Unread queries now explicitly sort by Date descending before applying the limit, using syntax verified against installed Himalaya v2 help. No Hermes source code was copied.
- Offline validation after these changes: 47 SDK and 20 legacy tests passed.
- User authorized a Gmail-only test of up to 3 unread envelopes (ID, sender, subject, date) sent to the configured DeepSeek official endpoint, without bodies or saved sessions. A temporary Python guard restricted the account, limit and number of mail calls.
- Live test reached the real list_unread tool, but Himalaya exceeded the existing 10-second timeout. No successful list was returned. DeepSeek reported the failure accurately and correctly denied body-reading, sending and filesystem-write capabilities. This verifies tool dispatch and error handling, not successful mailbox retrieval.
- An initial temporary test had a cleanup error (awaiting synchronous SQLiteSession.close), masking its original failure. The corrected retry produced the timeout result above. Production Session code was not changed.

## Gmail Reliability Follow-up

- An authorized standalone Gmail query returned 3 envelopes after 19 seconds and parsed successfully. Increased the bounded CLI timeout from 10 to 35 seconds; retained output limits and process cleanup.
- A subsequent SDK live test and standalone retry returned nonzero CLI exits. The exact cause is unconfirmed; successful end-to-end mail integration remains pending. Do not attribute every failure to timeout.
- The model described a failed lookup as zero messages. Error results now explicitly include unread_count=null and count_status=unknown_due_to_error; model adherence to this correction has not yet been verified live.
- Next: obtain a safely redacted local CLI diagnostic and identify the intermittent backend failure before considering another mail adapter. No external framework code was copied or new credentials introduced.

## Latest Gmail Verification (2026-09-15)

- A standalone real Gmail query again returned 3 envelopes successfully.
- A subsequent live DeepSeek → registered list_unread → Himalaya → DeepSeek round trip succeeded. The real tool returned 3 messages, and the model correctly reported 3 while denying body-reading, sending and filesystem-write capabilities.
- The temporary test guard allowed one Gmail tool invocation with limit <= 3; Session was in memory and closed without saving. No email fields or credentials were recorded in this log.
- This completes the first successful Gmail end-to-end metadata milestone and supersedes earlier statements that this path was still unverified. It does not establish sustained reliability: earlier nonzero CLI exits remain unexplained. No automatic retry or additional permission was introduced.
- Suggested next milestone: improve safe failure diagnostics and per-account opt-in before extending to other accounts or message bodies. Retain Himalaya for now; replacement is not justified by the evidence so far.

## Account Scope and Safe Errors (2026-09-15)

- Mail opt-in now requires explicit accounts: `--mail gmail`; default remains disabled. `build_agent` accepts `mail_accounts`, replacing the old blanket `mail_enabled` switch. Python rejects nonselected accounts before the backend runs, and runtime facts derive allowed_mail_accounts from registered tool metadata.
- Mail failures carry safe error codes and unknown counts without exposing raw CLI output. Process failures remain unclassified as to root cause; no automatic retries were added.
- Offline validation: 49 SDK and 20 legacy tests passed. No real mailbox calls this iteration. Prior Gmail live success remains historical verification, not a new live test of this change.
- Next: use the Gmail-only entry for authorized testing; investigate classified failures if they recur before extending email capabilities.

## School Mail Milestone (2026-09-15)

- School mail is the user's primary scenario. Added logical school → existing local Himalaya ucsb account binding; provider and credentials remain local configuration concerns. Inspection confirms the existing school backend is Google-hosted IMAP, separate from personal Gmail identity.
- Only explicit school opt-in authorizes this identity. Requests for gmail, 163 or even compatibility alias ucsb are rejected before backend access when only school is enabled. Current runtime facts enumerate authorized identities and read-only limits.
- Summaries use envelope metadata only; no body access, mailbox mutations, legacy data changes, or stored credentials were introduced.
- 51 SDK and 20 legacy offline tests passed, including school alias resolution, negative permissions, timeout, startup failure and raw process error redaction.
- School live test subsequently passed after explicit user consent naming DeepSeek as destination. The earlier approval rejection is resolved; see verification below.

## School Live Verification (2026-09-15)

- User explicitly authorized up to 3 school unread envelopes (sender, subject, date, ID) to the configured DeepSeek official endpoint. The school-only Agent performed one real list_unread call with limit=3 and returned 3 items; DeepSeek generated a brief metadata-based summary and attention items.
- A negative personal Gmail request against the same school-only tool was rejected with account_not_enabled before backend access. Runtime facts authorized only school; the live test guard prevented other accounts, limits above 3, or repeated mail retrieval.
- Only metadata was read. No bodies, attachments, mailbox mutations, stored test Session, credentials in logs, or legacy snapshot changes. No email content is included in this record.
- The last offline suite remains 51 SDK plus 20 legacy tests, all passing; this live check is additional validation. No commit or push performed.
- Attention-item suggestions are interpretations of metadata, not verified body content or deadlines. Keep school as the primary usage scenario; body access would require a separate read-only design and explicit data scope. Prior intermittent backend failures remain unresolved.
