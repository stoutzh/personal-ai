# Aion Progress

Last updated: 2026-09-10. Milestone snapshot, not a live view of files. The launch entry and current runtime facts determine which capabilities are active.

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
- Observed wording bug: model incorrectly denied persistence because its tools are read-only, despite successful program-managed SQLite saving/restoration. Runtime instructions now explicitly separate tool permissions, automatic Session persistence, new sessions, and --resume, and include actual restore status. The wording fix also passed a real DeepSeek test with synthetic background: the model correctly explained that read-only tools do not prevent automatic Session persistence and that --resume restores the same session. Adherence with the full personal background remains a daily-use observation.

- Codex verified the saved macOS Keychain credential could be read automatically, without asking for or printing the key.
- A subsequent real DeepSeek test used only generated disposable files/background and isolated SQLite storage. Three independent processes verified file tools → exit → restore 7 history items and recall the file marker → continue and exit → restore 9 items and recall the newly added marker; the final session contained 11 items. The existing personal session databases and latest pointer were not used or changed.
- This synthetic live test completes the second-restart/continued-persistence check. It does not claim to have rerun the full personal startup background or actual project README test.

## Legacy v0.3 (retained)

- Entry: `python3 aion.py`. Standard-library implementation with its own chat loop and provider adapter.
- JSON snapshots remain in `.aion/sessions/`. Legacy --resume loads the latest saved legacy session and creates a new snapshot file; --no-save disables writing. SDK runtime never reads, overwrites, or migrates these snapshots.
- Legacy implements per-request time and current-turn tool facts, at most 4 tool rounds and 8 tool calls. These are legacy behavior, not guarantees about SDK runtime.
- v0.1 real chat and v0.2 tools were user verified; legacy v0.3 persistence was tested offline. Do not infer legacy live persistence success from SDK tests.

## Shared Limits and Next Step

- Model tools are read-only; no shell, write/delete tools, background monitoring, or automatic personal-context updates.
- SQLite conversations and legacy JSON are local plaintext, not general long-term memory. SDK storage is Git-ignored and access restricted. Current key and common sk- strings are redacted before SDK persistence; this is not general secret detection or encryption.
- Restoring and continuing sends saved conversation/tool content to the currently configured provider, including if the provider changed. API credentials and provider configuration are not serialized into the Session.
- Next: use the SDK runtime for ordinary tasks and observe whether it accurately describes program-managed persistence. Do not propose rebuilding working Session persistence. Current user instructions override this snapshot.
