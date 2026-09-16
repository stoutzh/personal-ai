# Aion next milestones

Updated: 2026-09-16. Plans below are not registered runtime capabilities.

## Current product

Independent OpenAI Agents SDK runtime using a configurable Chat Completions provider (currently DeepSeek), local read-only file tools, separate SQLite Sessions, and runtime-generated capability facts. School mail is the primary email use case; read-only unread metadata has passed a scoped live test. Legacy v0.3 remains intact.

## Next: Apple Reminders

Use a small local adapter backed by Apple's EventKit. Aion keeps user-facing tools and permissions; EventKit handles system reminder storage and access. Start with listing explicitly selected reminder lists and incomplete reminders, then add creation in a dedicated Aion list after the read path works. Completion, deletion and other mutations need separate explicit scopes. Do not assume macOS full-access authorization grants the model every action.

An experimental read-only Swift/EventKit helper and SDK adapter are implemented. Offline tests, native compilation, system authorization and a bounded local read passed. Sending real reminder contents to the model remains separately authorized and has not yet been validated. Do not transmit existing reminder contents to a model without an explicit data scope.

References:
- https://developer.apple.com/documentation/eventkit/ekeventstore/requestfullaccesstoreminders(completion:)
- https://developer.apple.com/documentation/eventkit/creating-events-and-reminders

## Later: assisted capability installation

Reuse the SDK for execution, tool orchestration and sessions. Aion owns a small catalog of integrations and their source, version, license, dependencies, configuration, tool declarations and permission scopes. Start with mail and reminders before generalizing.

A requested feature should lead to: inspect existing capabilities → identify a suitable official API, local adapter or vetted component → review source/license/dependencies → install in isolation → configure credentials outside model context → run scoped tests → enable explicitly authorized tools → update runtime facts. Provide disable/rollback paths. New data destinations or permissions require explicit scope; known authorized steps can proceed automatically.

A skill teaches how to use available capabilities; it does not install executable code, grant permissions or prove successful integration. A plugin can package an adapter, tools and skills. Avoid silently exposing arbitrary shell or installing unreviewed remote code to imitate another agent framework.
