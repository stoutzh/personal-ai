# Aion Progress

Last updated: 2026-09-09. This is a milestone snapshot, not a live view of files.

## Verified Milestones

- v0.1: user confirmed real DeepSeek chat with selected skills, context and rules.
- v0.2: user confirmed real `list_directory` followed by `read_text_file` for README. The tool records showed success and the model summarized the file.
- Remaining observed issues: model repeated stale README instructions to verify an already completed operation, used a template-like reply, and stated an incorrect directory count. These examples do not establish a general model ranking.

## Current Stage: v0.3

- Successful conversation turns and tool history are saved locally to Git-ignored `.aion/sessions/`. `--resume` restores the most recently started saved session; each launch writes a new session file. `--no-save` disables saving.
- Each model request gets transient runtime facts: process time, this turn's actual tool successes/failures and directory counts. Restored tool results remain historical; old snapshot text does not override current execution evidence.
- Offline tests cover persistence, restoration, protected paths, redaction, error handling, and current-turn facts. Live v0.3 conversation behavior is still pending user trial.

## Limits

- Model tools remain read-only. No shell, write/delete tool, automatic context editing, or continuous filesystem monitoring.
- Session snapshots are local plaintext, not general long-term memory. They can include file contents returned by tools; continued conversations send current history to the configured model service.
- Configuration and selected background are loaded at startup. Reading changed files does not rewrite startup rules.
- Provider settings remain separate from file tools and the conversation loop; only Chat Completions function-calling format is currently adapted.

## Next Milestone

Use Aion for a real task, then verify `--resume` continues that conversation. Assess whether it distinguishes current tool results from older notes. If the user supplies successful results, acknowledge those specific checks instead of reassigning them. A restart is needed only to load changed program/configuration, not as a repeated conversation ritual.

## Updating

Update this snapshot at meaningful milestones under `rules/context-policy.md`. Runtime facts and session storage do not grant permission to rewrite personal goals. Current user instructions take precedence.
