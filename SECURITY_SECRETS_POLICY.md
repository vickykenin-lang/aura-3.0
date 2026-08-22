# Security and Secrets Policy

- AURA2 secrets remain only in design-infra-aura2.
- Never copy them to Vision or another department.
- Never store a secret value or token-presence claim in a public JSON file.
- Only repository-owner commands may reach the approval job.
- The approval validator must check current calendar membership, permanent rejection, dual-gate
  pass, and kill switch.
- Automated Instagram posting may run only after a repository-owner approval command, current
  dual-gate revalidation, and a kill-switch check.
- `IG_AURA2_TOKEN` and `IG_AURA2_ID` must remain in GitHub Actions Secrets. Tokens must never be
  printed, committed, copied into issues, or written to publication records.
- Workflow write permissions must remain limited to contents/issues required by that workflow.
- Rotate the Instagram token after suspected exposure and stop publication with the kill switch.

Repository visibility is public. Personal or direct business phone/email details must not be stored
in public source files. Secret values must exist only in GitHub Actions Secrets.
