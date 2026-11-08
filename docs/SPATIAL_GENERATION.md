# Automated layout and bird-view pilot

The Founder requested two views of the existing warm modern living-dining concept.
The workflow uses Runway's existing department credential, Seedream 5.0 Pro with
the original image as a reference, and the configured Amazon Nova route for
source analysis and comparison of each actual generated image.

Run **AURA3 Layout and Bird View**. The current request is in
operations/spatial_generation_request.json. Results and blockers are written
to data/spatial_jobs.json; native output images go to assets/spatial/<job>/.
The review page is spatial.html. This workflow cannot publish to Instagram.

## Boundaries and recovery

- Two image task attempts, one image per task, 2048 square output requested.
- Maximum estimated image budget: 18 Runway credits total, using the documented
  API rate of 9 credits per 2K Seedream Pro image. No purchase or automatic recharge.
- Up to three Nova calls: source analysis and a separate comparison for each view.
- Generation intent and call reservation must be durably persisted before calls.
- A lost submission response is not retried. Known task IDs may be polled again
  after a polling timeout, without creating a replacement.
- A credit/authentication blocker with zero inference can be rechecked by rerunning
  the same workflow after the Founder resolves account access or credits.
- Completed and QA-rejected views are not regenerated on rerun. Changed input
  or prompts require a new job ID and a new explicit budget.
- Provider output URLs are temporary and are not saved. Files are downloaded,
  hashed and compared with the exact reference. Failed comparisons remain
  reviewable and never receive a silent PASS.
- Input is a generated campaign concept. Outputs are inferred layouts, not measured
  plans. No dimensions, extra rooms, style numbers or BHK markings are requested.
- Existing publication approvals, posting requests, certificates and control flags
  are not changed by this pilot.

API documentation checked on 2026-11-08:
[Runway API](https://docs.dev.runwayml.com/api/),
[Seedream Pro support](https://docs.dev.runwayml.com/api-details/api_changelog/),
[API pricing](https://docs.dev.runwayml.com/guides/pricing/).
