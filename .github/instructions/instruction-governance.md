# Instruction Governance (Phase 5)

## Quality Checklist
- Every scoped instruction file has a clear `description` with trigger phrases.
- Every scoped instruction file uses narrow `applyTo` patterns.
- Rules are contract-focused and not implementation-noise heavy.
- No duplicate/conflicting rules across scoped files.
- Changes include at least one validation prompt/check in review.

## Update Criteria
- Add or modify scoped instructions only when domain behavior/contracts change.
- Keep placeholders empty until that domain is actively codified.
- If a rule becomes cross-cutting, move it to `.github/copilot-instructions.md`.

## Review Expectations
- Confirm scope accuracy.
- Confirm no overlap conflict.
- Confirm wording is actionable and testable.

## Conformance Audit Gate (Phase 6)

## Required Manual Audit
- Verify each changed instruction has a clear trigger-oriented `description`.
- Verify `applyTo` is the narrowest practical scope for the intended domain.
- Verify no rule duplicates or semantic conflicts were introduced.
- Verify at least one concrete validation check is recorded for the change set.

## Validation Evidence
- Include a short audit summary with findings ordered by severity.
- If no findings are present, state that explicitly.
- Record any residual risk or deferred follow-up item.

## Exit Criteria
- Phase 5 checklist passes.
- Phase 6 manual audit is complete and documented.
- Any audit findings are fixed before closing the change.
