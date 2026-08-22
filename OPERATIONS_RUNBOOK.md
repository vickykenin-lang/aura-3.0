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
6. Confirm the same Action creates the media container and publishes it to Instagram.
7. Confirm the verified Instagram media ID or URL is committed to content/published.json.
8. Confirm the dashboard changes to Instagram Posted, then log genuine inquiries and their source.

## Dashboard post status

- `pending`: show Approve and Reject controls.
- `approved_manual`: keep the card visible as `Approved` with `Post pending`.
- A verified Instagram ID, URL, or timestamp in `content/published.json`: show
  `Instagram Posted` and remove approval controls.
- The dashboard refreshes these states automatically every 30 seconds.

## Emergency stop

Set kill_switch to true in data/control.json. Founder approval handoff and Instagram publishing
then fail closed. Rotate the Instagram token if credential exposure is suspected.

## Empty dashboard

- Check that content/calendar.json contains today's ten posts.
- Check that data/gate_results.json has the same IDs.
- Open the gate Action logs for missing keys, image-download problems, or model errors.
- Do not insert manual scores to make cards appear.

## Automatic publish failure

- Confirm the candidate is approved_manual and still has no published reference.
- Check the Instagram app permissions, Professional account ID, public JPEG URL, caption length,
  media-container status, and account publishing limit.
- If the API returned a media ID but the repository update failed, check Instagram before retrying
  to prevent a duplicate post.
- Fix the cause, then retry the same approved candidate once only when Instagram has no post.
- Do not create a new ID to conceal the failure.

After success, the workflow adds a published record containing the verified Instagram media ID or
URL and timestamp. Never store an access token.

## Unauthorized issue

The job must be skipped because the author is not the repository owner. Close the issue as spam.
If any unauthorized job runs, enable the kill switch, rotate the Instagram token, and inspect
workflow history immediately.

## Pilot report

Record date, candidates generated, visual passes, business passes, approved posts, Instagram media
IDs, inquiries, qualified leads, errors, fixes, and next action.
