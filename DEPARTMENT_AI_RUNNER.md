# AURA2 Runner

The executable runner is scripts/generate_candidates.py and its manual pilot workflow is
.github/workflows/daily_content.yml. Unattended scheduling is intentionally disabled.

The runner creates copy for ten fixed, curated image slots. It does not invent image URLs and it
does not publish. Unique daily IDs use YYYYMMDD-NN format. Every candidate remains pending until
the separate dual quality gate passes and the Founder approves it.

The runner fails closed when the Gemini key is missing, the image pool has fewer than ten items,
Gemini returns the wrong number of slots, or required CTA/copy fields are missing.
