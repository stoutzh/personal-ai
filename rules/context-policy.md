# Personal Context Policy

## Purpose and Authority

- Personal Context in `context/` is persistent user state, not ordinary project documentation.
- Current explicit instructions always override stored context.
- Context should guide agents, not define the user's identity or restrict future choices.

## Reading and Privacy

- Read only context relevant to the current task and only when it improves the work.
- Avoid storing sensitive or deeply private information in this public repository.
- Useful but private information should eventually belong in a private memory layer, not public `context/`.

## Updating Context

Do not modify `context/` by default. Update it only when:

- The user explicitly asks for a context update.
- The current task is specifically about maintaining Personal Context.
- An agent proposes a specific update and the user explicitly approves it.

Do not turn temporary thoughts, moods, experiments, or one-off preferences into persistent context. Prefer information that is:

- Likely to remain useful over time.
- Relevant to future AI assistance.
- Specific enough to improve future decisions or behavior.

When updating context:

- Modify the smallest relevant file.
- Avoid duplicating information across files.
- Remove or revise stale information when appropriate.
- Preserve clear, concise wording.
