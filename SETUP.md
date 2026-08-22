# AURA2 Setup

## Required GitHub Actions secrets

| Secret | Purpose |
|---|---|
| GEMINI_API_KEY | Daily generation and actual-image vision inspection |
| DEEPSEEK_KEY | Independent business-quality gate |

Secrets stay only in this repository. Never write secret values to source files, issues, logs, or
status JSON.

Instagram credentials are intentionally not used by GitHub Actions during the controlled pilot.

## Optional repository variables

| Variable | Default |
|---|---|
| GEMINI_MODEL | gemini-3.7-flash |
| DEEPSEEK_MODEL | deepseek-v4-flash |

Leave a variable unset to use the code default.

## GitHub settings

1. Keep Pages deployed from main and root.
2. Keep Actions enabled.
3. Protect main after the pilot, while allowing the approved Actions workflows to update data files.
4. Restrict issue-based publication to the workflow's repository-owner check; do not remove it.

## First controlled test

1. Set data/control.json kill_switch to true.
2. Run AURA2 Daily Content Generator manually.
3. Run AURA2 Dual Quality Gate manually after generation succeeds.
4. Confirm rejected and low-score posts are absent from the dashboard.
5. Turn kill_switch off.
6. Approve one test candidate as the repository owner.
7. Publish the approved candidate manually on Instagram.
8. Record the verified media ID or URL in content/published.json.
9. Turn the kill switch back on if any result is unclear.

Unattended schedules are intentionally disabled during the controlled pilot.
