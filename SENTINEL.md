# SENTINEL — Independent Business Gate

**AI:** DeepSeek  
**Input prerequisite:** Gemini Vision must have inspected the actual image.

SENTINEL judges conversion signal, CTA, caption-to-room match, Design Infra brand fit, and honesty.
It does not approve an image based only on a URL or user-provided tag.

Output is stored in data/gate_results.json. A dashboard candidate and approval validator both require:

- visual_ok=true
- pass=true
- score at least 7

SENTINEL does not generate the content, publish to Instagram, or replace Founder approval.
