---
name: aion-architecture
description: Guide architecture and component reuse when developing Aion, the personal AI product. Use for Aion features, integrations, refactors, and architecture decisions; not for unrelated projects.
---

# Aion Architecture

Use alongside project-builder when developing Aion: project-builder guides delivery and teaching; this skill defines Aion-specific architecture preferences.

## Aion Architecture Boundaries

- Aion is a personal AI product, not a new general-purpose agent framework.
- OpenAI Agents SDK is the primary harness/runtime unless a concrete technical reason justifies changing this.
- DeepSeek is currently the primary LLM provider, but keep Aion provider-agnostic where practical.

## Responsibility Split

OpenAI Agents SDK should normally handle generic agent infrastructure:

- Agent execution loop
- Tool orchestration
- Session primitives
- Handoffs
- Guardrails
- Tracing/runtime primitives

Aion should own:

- Personal context
- Private memory
- User-specific permissions
- Learning workflows
- Project state
- Gmail / Calendar / WeChat / macOS integrations
- Local/private data handling
- Aion-specific UX and future UI

These are responsibility boundaries, not a requirement to enable every SDK feature. Check compatibility with the active provider before using a feature.

## Using Hermes and Other External Agent Projects

Treat Hermes Agent and similar projects primarily as architecture references, not templates to mirror.

Before borrowing a component, classify it as:

- `Use SDK`: the SDK adequately addresses the current need.
- `Reimplement for Aion`: implement the needed behavior within Aion's own boundaries.
- `Adapt small component`: reuse a limited, suitable piece of external code.
- `Ignore for now`: the current milestone does not need it.

For every candidate component, ask:

1. What user problem does this solve?
2. Does Aion need it now?
3. Does OpenAI Agents SDK already solve it adequately?
4. Is the external implementation tightly coupled to its own framework?
5. Would adapting it introduce unnecessary dependencies or maintenance?
6. Can Aion solve the current need with a smaller implementation?

Do not copy entire subsystems merely because Aion has a similar requirement.

When adapting external code:

- Verify the license first.
- Preserve required attribution and notices.
- Document the source when appropriate.
- Adapt the implementation to Aion's architecture instead of preserving unnecessary upstream structure.

## Development Philosophy

- Prefer real-user-driven additions over speculative framework-building.
- Prefer small, testable milestones.
- Do not silently replace large parts of Aion.
- If an external architecture is clearly better, explain the difference and propose a migration path first.
- Preserve legacy behavior/data unless the migration explicitly requires changing it.
- Current user instructions override stored architecture preferences.
