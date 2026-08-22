# AURA2 Content and Quality Rules

## Hard visual gate

Gemini Vision must inspect the actual downloaded image. Reject unrelated stock, animals, wildlife,
outdoor landscape without an interior, roads/railways, food-only lifestyle, children, memes,
watermarks, severe blur, or an image unsuitable for a premium interiors brand.

Allowed categories are living, kitchen, bedroom, bathroom, dining, wardrobe/storage, lighting,
false ceiling, and home/office interiors.

## Independent business gate

DeepSeek must verify all of the following:

| Check | Requirement |
|---|---|
| Image/caption match | Caption must match the room detected by vision |
| Conversion signal | Price band, timeline, process, or inclusions |
| CTA | Consultation, official website, or link in bio |
| Brand fit | Turnkey interiors and relevant geography |
| Honesty | No fake project, testimonial, warranty, or result claim |
| Final result | pass=true and score at least 7 |

## Disclosure

- AI-generated image: label it Concept visualisation.
- Stock/reference image: label it Inspiration reference; not a completed Design Infra project.
- Completed-project claim: use only verified Design Infra project media.

## Queue and publishing

- Dashboard reads the current calendar dynamically.
- Rejected and published items do not appear.
- Queue maximum is twenty.
- Approval is valid only when created by the repository owner.
- The approval validator repeats all gate checks server-side.
- GitHub Actions never receives Instagram credentials or posts externally during the pilot.
- Founder publishes manually and records the verified Instagram media reference afterward.

## Daily publishing policy

Generate ten candidates to create choice. Normally publish only the best one or two. Never publish
ten average posts merely to satisfy volume.
