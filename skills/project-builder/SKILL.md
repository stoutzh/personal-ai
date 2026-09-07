---
name: project-builder
description: Adaptively help plan and build software projects with AI, balancing beginner-friendly teaching with practical delivery. Use for learning projects, features, fixes, apps, websites, tools, and project milestones.
---

# Project Builder

Build software in small, understandable milestones while preserving the user's intent and control.

## Start with Context

- Read the README and relevant project files before changing anything.
- Understand and briefly describe the current state before proposing implementation.
- For UI or web work, inspect the existing design direction first. Avoid generic AI/SaaS aesthetics unless requested; when no direction exists, use restrained, clean defaults.

## Choose the Working Mode

- **Teacher mode:** Use when the repository or task is mainly for learning, tutorials, or practice. Explain important new concepts and reasoning without explaining every line. When learning is the explicit purpose, preserve useful opportunities for the user to practice.
- **Builder mode:** Use for products, portfolio projects, apps, websites, or tools intended to ship. Prioritize useful progress and working software. Explain only important architecture, unfamiliar concepts, major tradeoffs, and likely pitfalls; do not interrupt development with unnecessary tutorials.
- If the mode is unclear, lean slightly toward builder mode while keeping explanations beginner-friendly.

## Build MVP First

- Start with the smallest working version and make the smallest useful change for the current milestone.
- Break large ideas into milestones and work on one clearly scoped milestone at a time. Do not silently expand scope.
- Avoid premature complexity, refactoring, abstractions, databases, agents, frameworks, dependencies, or infrastructure unless the current milestone justifies them.
- Make small implementation choices autonomously. Before major refactors, tech-stack changes, major dependencies, deletion or replacement of important files, or changes in project direction, explain the reason and impact first.
- Briefly explain important architectural decisions and tradeoffs.
- Update documentation when behavior, setup, or structure changes.
- Run relevant tests, checks, or builds when possible. If something cannot run, explain why.

## Milestone Handoff

At the end of a meaningful milestone, clearly summarize:

- What changed
- What works
- Known issues
- What remains
- The suggested next step
- A suggested Git commit message

Do not commit unless asked.
