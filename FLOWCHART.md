# AURA2 Strong Flowchart (Autonomous Version)

**Goal:** High-quality interior content → Instagram traffic → Real qualified leads for Design Infra.

**Revenue source:** Qualified leads (≈ ₹2,000 each). Same market as the "100-200 leads/month" ads we saw.

## High-Level Flow (Simple)

```
1. Content Generation (Department AI)
   ↓
2. Multi-AI Scoring & Filtering (score must ≥ 7)
   ↓
3. Dashboard Shortlist (only ≥7 appear)
   ↓
4. Vicky Approves (one click)
   ↓
5. Instant Instagram Publish
   ↓
6. Traffic → WhatsApp / Email Leads
   ↓
7. Vicky closes the lead
```

## Detailed Daily Autonomous Flow

```
[Department AI Runner starts daily]
        |
        v
+---------------------------+
| 1. Generate 10 candidate  |
|    interior posts/reels   |
|    (images + caption + CTA)|
+---------------------------+
        |
        v
+---------------------------+
| 2. Multi-AI Quality Gate  |
|    - Image quality check  |
|    - Content rules check  |
|    - DeepSeek / Gemini    |
|      business score       |
|    Only keep score ≥ 7    |
+---------------------------+
        |
        v
+---------------------------+
| 3. Push shortlist to      |
|    Dashboard              |
|    (rejected never appear)|
+---------------------------+
        |
        v
+---------------------------+
| 4. Vicky reviews on       |
|    dashboard              |
|    Approve = publish now  |
|    Reject  = hide forever |
+---------------------------+
        |
        v
+---------------------------+
| 5. Instant IG Publish     |
|    (GitHub Action / script)|
+---------------------------+
        |
        v
+---------------------------+
| 6. Monitor leads          |
|    WhatsApp 8287900789    |
|    Email + leads.html     |
+---------------------------+
        |
        v
+---------------------------+
| 7. Daily Report to Victor |
|    - Posts published      |
|    - Scores               |
|    - Errors fixed         |
|    - Lead count           |
+---------------------------+
```

## Error Handling & Troubleshooting (Department AI responsibility)

- If generation fails → retry with different prompt / model
- If scoring API down → use backup model (Groq/Cerebras)
- If publish fails → log error + notify Victor
- If no posts reach ≥7 → generate more candidates
- Daily health check before ending shift

## Victor (Grok) Role after setup
- Only **manager**
- Sees daily report
- Escalates only if Department AI cannot fix
- Does **not** run daily generation, scoring, or troubleshooting

## Success Metrics (RED if zero)
- Real qualified leads (name + phone + city + intent)
- Consistent 10 candidates → high % ≥7
- Instant publish working
- Zero unhandled errors for 7+ days
