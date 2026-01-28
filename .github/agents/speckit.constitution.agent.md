---
description: Create or update the project constitution from interactive or provided principle inputs, ensuring all dependent templates stay in sync.
model: claude-opus-4-5
infer: true
handoffs: 
  - label: Build Specification
    agent: speckit.specify
    prompt: Implement the feature specification based on the updated constitution. I want to build...
---

## Output Language

**Default: Traditional Chinese (zh-TW)**. Keep technical terms in English (API, OAuth2, design tokens, etc.). See `copilot-instructions.md` Language Strategy for details.

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Outline

You are managing the **dual-layer constitution system**:
- **Studio Constitution** (`studio/constitution/constitution.md`): Highest authority, non-negotiable
- **Project Constitution** (`$PROJECT_ROOT/.specify/memory/constitution.md`): Optional, can only add stricter rules

This command operates on the PROJECT-LEVEL constitution only. Studio Constitution must NEVER be modified by this command.

Follow this execution flow:

1. Load the Studio Constitution at `studio/constitution/constitution.md` first - this is the baseline.
   - Extract all MUST/SHOULD rules as the non-negotiable foundation
   - Any project constitution rules MUST NOT conflict with Studio rules

2. If `$PROJECT_ROOT/.specify/memory/constitution.md` exists, load it.
   - Identify every placeholder token of the form `[ALL_CAPS_IDENTIFIER]`.
   - If it doesn't exist, create from template at `studio/templates/sdd-docs/constitution-template.md` (if available) or generate a minimal scaffold.
   **IMPORTANT**: The user might require less or more principles than the ones used in the template. If a number is specified, respect that - follow the general template. You will update the doc accordingly.

2. Collect/derive values for placeholders:
   - If user input (conversation) supplies a value, use it.
   - Otherwise infer from existing repo context (README, docs, prior constitution versions if embedded).
   - For governance dates: `RATIFICATION_DATE` is the original adoption date (if unknown ask or mark TODO), `LAST_AMENDED_DATE` is today if changes are made, otherwise keep previous.
   - `CONSTITUTION_VERSION` must increment according to semantic versioning rules:
     - MAJOR: Backward incompatible governance/principle removals or redefinitions.
     - MINOR: New principle/section added or materially expanded guidance.
     - PATCH: Clarifications, wording, typo fixes, non-semantic refinements.
   - If version bump type ambiguous, propose reasoning before finalizing.

3. Draft the updated constitution content:
   - Replace every placeholder with concrete text (no bracketed tokens left except intentionally retained template slots that the project has chosen not to define yet—explicitly justify any left).
   - Preserve heading hierarchy and comments can be removed once replaced unless they still add clarifying guidance.
   - Ensure each Principle section: succinct name line, paragraph (or bullet list) capturing non‑negotiable rules, explicit rationale if not obvious.
   - Ensure Governance section lists amendment procedure, versioning policy, and compliance review expectations.

4. Consistency propagation checklist (convert prior checklist into active validations):
   - **CRITICAL**: Verify no project rules conflict with Studio Constitution
   - Read `studio/templates/sdd-docs/plan-template.md` and ensure any "Constitution Check" or rules align with updated principles.
   - Read `studio/templates/sdd-docs/spec-template.md` for scope/requirements alignment—update if constitution adds/removes mandatory sections or constraints.
   - Read `studio/templates/sdd-docs/tasks-template.md` and ensure task categorization reflects new or removed principle-driven task types (e.g., observability, versioning, testing discipline).
   - Read any runtime guidance docs (e.g., `README.md`, `docs/quickstart.md`, or agent-specific guidance files if present). Update references to principles changed.

5. Produce a Sync Impact Report (prepend as an HTML comment at top of the constitution file after update):
   - Version change: old → new
   - List of modified principles (old title → new title if renamed)
   - Added sections
   - Removed sections
   - Templates requiring updates (✅ updated / ⚠ pending) with file paths
   - Follow-up TODOs if any placeholders intentionally deferred.

6. Validation before final output:
   - No remaining unexplained bracket tokens.
   - Version line matches report.
   - Dates ISO format YYYY-MM-DD.
   - Principles are declarative, testable, and free of vague language ("should" → replace with MUST/SHOULD rationale where appropriate).

7. Write the completed constitution back to `$PROJECT_ROOT/.specify/memory/constitution.md` (overwrite).
   - **NEVER** modify `studio/constitution/constitution.md`

8. Output a final summary to the user with:
   - New version and bump rationale.
   - Any files flagged for manual follow-up.
   - Suggested commit message (e.g., `docs: amend constitution to vX.Y.Z (principle additions + governance update)`).

Formatting & Style Requirements:

- Use Markdown headings exactly as in the template (do not demote/promote levels).
- Wrap long rationale lines to keep readability (<100 chars ideally) but do not hard enforce with awkward breaks.
- Keep a single blank line between sections.
- Avoid trailing whitespace.

If the user supplies partial updates (e.g., only one principle revision), still perform validation and version decision steps.

If critical info missing (e.g., ratification date truly unknown), insert `TODO(<FIELD_NAME>): explanation` and include in the Sync Impact Report under deferred items.

Do not create a new template; always operate on the existing project constitution file at `$PROJECT_ROOT/.specify/memory/constitution.md`.

**Remember**: Project constitution can only ADD stricter rules, NEVER relax Studio Constitution rules.
