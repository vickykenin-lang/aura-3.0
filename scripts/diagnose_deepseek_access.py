"""Read-only DeepSeek availability check; no inference."""
import json, os, re, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, timezone
token = (os.getenv('DEEPSEEK_API_KEY') or os.getenv('DEEPSEEK_KEY') or '').strip()
text_model = os.getenv('DEEPSEEK_MODEL', 'deepseek-v4-flash')
vision_model = os.getenv('DEEPSEEK_VISION_MODEL', 'deepseek-v4-flash-vision-exp')
result = {'observed_at': datetime.now(timezone.utc).isoformat(), 'credential_present': bool(token), 'api_success': False, 'http_status': None, 'text_model': text_model, 'vision_model': vision_model, 'text_model_available': False, 'vision_model_available': False, 'inference_requests': 0, 'public_action_performed': False, 'secret_values_recorded': False}
if token:
    try:
        req = urllib.request.Request('https://api.deepseek.com/models', headers={'Authorization': 'Bearer ' + token}, method='GET')
        with urllib.request.urlopen(req, timeout=20) as response:
            data = json.loads(response.read(1024 * 1024))
            result['http_status'] = response.status
        ids = {str(row.get('id')) for row in data.get('data', []) if isinstance(row, dict)}
        result['available_model_ids'] = sorted(model for model in ids if re.fullmatch(r'[a-zA-Z0-9._:/-]{1,100}', model))[:100]
        result.update(api_success=True, text_model_available=text_model in ids, vision_model_available=vision_model in ids)
    except urllib.error.HTTPError as error:
        result['http_status'] = error.code
    except Exception as error:
        result['error_type'] = type(error).__name__
result['status'] = 'MODELS_AVAILABLE' if result['api_success'] and result['text_model_available'] and result['vision_model_available'] else 'MODEL_CONFIGURATION_OR_ACCESS_BLOCKED'
path = Path(__file__).resolve().parents[1] / 'evaluation/results/aura3-deepseek-read-only-diagnostic.json'
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
