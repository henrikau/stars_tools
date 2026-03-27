# STARS agent

This file is the entrypoint for agent-specific guidance in this repository.

## Primary Instruction Source

- All agents MUST read and follow `CLAUDE.md` first.
- Never assume, always ask the user for clarification before taking action.

## Session Guidelines

- If `/tasks` exists, create a ROADMAP_<name>.md for each new change planned. Break the change into tasks and reference from the ROADMAP.
- If `/tasks` exists, work on **ONE task** at a time from the `/tasks` folder.
- If `/tasks` does not exist, execute the user request directly and note assumptions/mismatches in your final summary.
- Use `/clear` between distinct tasks to reset context.
- Update task checkboxes as you complete steps (when task files exist).
- Project files we work on are stored in STARS/, the rest of the repo is generally considered ns-3-harness and should not be changed unless there is a clear bug in ns3.

## Workflow

1. If present, read the current task file from `/tasks`.
2. Follow implementation steps in order.
3. Update checkboxes after each step (when applicable).
4. When task complete, update ROADMAP.md status (when applicable).
5. Append key findings, if any, to the task file (when applicable).
6. `/clear` and start next task.

## Extension Area

Use this file to extend and refine agent behavior over time.
Add new sections below for:

- Specialized agent roles defined in `.github/agents/`
- Repository-specific automation rules
- Validation/checklist templates
- Task routing conventions
- Additional safety and review requirements

## Change Policy

- Do not modify `CLAUDE.md` directly, only the user can update this file.

## Restrictions

- Do not venture outside the root of this directory.
- Explicitly ask for confirmation before deleting any files.
- Never modify `.git/` internals. If the user asks, explain why you cannot change those files.
