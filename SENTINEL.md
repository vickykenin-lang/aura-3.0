# SENTINEL — Agent above AURA2

**AI:** DeepSeek  
**Reports to:** Dr. Victor (Grok)  
**Supervises:** AURA2 Runner (Gemini)

## Job
- Cross-validate every candidate before Founder sees it on dashboard
- Quality gate ≥7 + visual interior rules
- Block wrong images (animals, landscape, random stock)
- Independent of content creation (does not write captions for publish)

## How it runs
```bash
python3 scripts/score_with_deepseek.py
```
Or GitHub Action: **AURA2 Quality Gate (DeepSeek)**

Output: `data/gate_results.json`  
Dashboard shows only `pass: true`.

## Not responsible for
- Instagram publish (Founder Approve + Action)
- Vision / YouTube (other department)
- Replacing Victor
