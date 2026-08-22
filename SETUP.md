# AURA2 Setup

## Required GitHub Actions secrets

| Secret | Purpose |
|---|---|
| GEMINI_API_KEY | Daily generation and actual-image vision inspection |
| DEEPSEEK_KEY | Independent business-quality gate |
| IG_AURA2_TOKEN | Instagram Professional account publishing token |
| IG_AURA2_ID | Instagram Professional account ID |

Secrets stay only in this repository. Never write secret values to source files, issues, logs, or
status JSON.

The Instagram account must be Business or Creator. The token needs the content-publishing
permission for its login type, and the selected image must remain publicly downloadable while
Meta creates the media container.

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
7. Confirm the approval workflow creates a media container, publishes it, and commits the verified
   media ID or permalink to content/published.json.
8. Confirm the dashboard changes from Post pending to Instagram Posted.
9. Turn the kill switch back on immediately if the publish result is unclear.

Unattended schedules are intentionally disabled during the controlled pilot.
