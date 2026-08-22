# AURA2 Operations Runbook

## Mobile-friendly combined pilot command

1. Sign in as the repository owner.
2. Open a GitHub issue with the exact title `RUN AURA2 PILOT`.
3. The Founder Pilot Run workflow generates ten candidates and immediately applies the Gemini
   Vision plus DeepSeek business gate.
4. A successful run commits the results and closes the command issue automatically.
5. Review the dashboard. No candidate is approved or published by this command.

Only an issue created by the repository owner can start this workflow. An issue with a different
title or from another GitHub user is ignored.

## Normal daily check

1. Open Actions and confirm Daily Content Generator succeeded.
2. Confirm Dual Quality Gate succeeded.
3. Open the dashboard and review only dual-pass cards.
4. Approve at most one or two best candidates.
5. Confirm the Founder Approval Action succeeded.
6. Publish the approved candidate manually on Instagram.
7. Record the verified Instagram media ID or URL in content/published.json.
8. Log genuine inquiries and their source.

## Emergency stop

Set kill_switch to true in data/control.json. Founder approval handoff then fails closed. Instagram
credentials are not present in Actions.

## Empty dashboard

- Check that content/calendar.json contains today's ten posts.
- Check that data/gate_results.json has the same IDs.
- Open the gate Action logs for missing keys, image-download problems, or model errors.
- Do not insert manual scores to make cards appear.

## Manual publish failure

- Confirm the candidate is approved_manual and still has no published reference.
- Check the Instagram app, image format, caption length, and account status manually.
- Fix the cause, then retry the same approved candidate once.
- Do not create a new ID to conceal the failure.

After success, add a published record containing the verified Instagram media ID or URL and
timestamp. Never store an access token.

## Unauthorized issue

The job must be skipped because the author is not the repository owner. Close the issue as spam.
If any unauthorized job runs, enable the kill switch, rotate the Instagram token, and inspect
workflow history immediately.

## Pilot report

Record date, candidates generated, visual passes, business passes, approved posts, Instagram media
IDs, inquiries, qualified leads, errors, fixes, and next action.
