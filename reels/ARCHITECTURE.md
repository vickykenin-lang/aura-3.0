# AURA3 Reels Division

## Objective
Create governed 5-10 second home-interior Reels inside AURA3 without changing the static-post division's authority, availability, or publishing path.

## Authority
Founder -> Dr. Victor -> AURA3 -> AURA3 Reels -> qualified capabilities -> qualified providers/executors.

AURA3 Reels is a division of AURA3, not a replacement for the existing static-post pipeline.

## Phase plan
0. Baseline audit and architecture lock.
1. Shadow source implementation: brief, asset, music, renderer and reel gate contracts. No public publishing.
2. Technical qualification: render 3-5 real 5-10 second MP4 samples in GitHub Actions and verify duration, 9:16 frame, readability, audio, file integrity and fail-closed behavior.
3. Founder dashboard integration: Reel preview, audio preview, gate evidence, Approve/Reject.
4. Controlled Instagram Reel publishing: separate video/reel publisher, media ID/permalink verification, no static-publisher regression.
5. Rolling Reel queue and trend scout: maintain a bounded approval queue; trend signals inform music style, but only commercially permitted licensed audio may be embedded.
6. Business outcome measurement: views, watch-through where available, engagement, enquiries and qualified leads; no causal revenue claim without evidence.

## Phase 1 target format
- MP4, H.264 + AAC.
- 1080x1920, 9:16.
- Duration 5-10 seconds.
- One unique interior visual per Reel in the first pilot.
- Slow pan/zoom/Ken Burns motion; no full generative video dependency in the first pilot.
- 2-4 concise text overlays plus CTA.
- Disclosure shown in metadata/UI exactly as: `Inspiration reference`.
- Background music optional at render time but expected for approval preview when a licensed candidate is available.

## Music and trend architecture
Pipeline: Trend Scout -> licensed candidate search -> License Gate -> audio normalization/mix -> Founder preview -> approval.

Trend Scout may identify current genre/mood/BPM/style signals. A trending copyrighted song is never automatically downloaded, copied or embedded. If a trend source points to a track without commercial-use rights, the system maps the trend to a commercially permitted royalty-free alternative.

Every embedded music candidate must retain:
- track title and creator;
- source URL/reference;
- license type and license evidence URL/reference;
- commercial_use_allowed=true;
- attribution requirement;
- retrieval/evidence timestamp;
- optional content-ID risk note.

No license evidence -> no music embedding.

## Isolation requirements
- Static content files and workflows remain authoritative for static posts.
- Reels use separate calendars, approvals, published registry, queue state and workflows.
- Reel failure cannot stop static post generation, approval or publishing.
- Existing Instagram static-image publisher remains unchanged during Phases 0-3.
- Reel publish authority remains false until Phase 4 controlled live verification.
- Credentials remain Founder-managed GitHub secrets; no secret values in repo or evidence.

## Quality gates
A Reel cannot enter Founder approval unless all required gates pass:
- 5.0 <= duration_seconds <= 10.0;
- 9:16 portrait output and expected dimensions;
- playable MP4 video stream;
- readable overlays inside safe margins;
- no unsupported ownership/project claim;
- CTA present;
- `Inspiration reference` disclosure retained;
- unique visual policy passed;
- music license passed when music is embedded;
- business-quality threshold passed.

## Truth states
SOURCE_IMPLEMENTED -> TEST_PASSED -> PRODUCTION_DEPLOYED -> LIVE_VERIFIED -> REAL_BUSINESS_OUTCOME_VERIFIED.

Workflow success alone does not prove a Reel was published or produced business outcomes.
