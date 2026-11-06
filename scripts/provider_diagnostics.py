"""Extract bounded failure metadata without logging exception text or credentials."""
import re


def safe_failure(error, stage):
    chain, seen = [], set()
    while error is not None and id(error) not in seen and len(chain) < 5:
        seen.add(id(error))
        chain.append(error)
        error = error.__cause__ or error.__context__
    status = next((getattr(e, 'code', None) for e in chain if isinstance(getattr(e, 'code', None), int)), None)
    text = ' '.join(str(e) for e in chain).lower()
    if status is None:
        found = re.search(r'\bhttp\s*([1-5][0-9]{2})\b', text)
        status = int(found.group(1)) if found else None
    category = 'PROVIDER_OR_RUNTIME'
    if 'dunning' in text or 'billing' in text:
        category = 'BILLING'
    elif status in {401, 403}:
        category = 'AUTH_OR_ACCESS'
    elif status == 429:
        category = 'RATE_LIMIT'
    elif any(isinstance(e, (TimeoutError, ConnectionError)) for e in chain):
        category = 'NETWORK'
    return {'stage': stage, 'error_type': type(chain[0]).__name__, 'http_status': status, 'category': category, 'raw_exception_recorded': False}


def advertised_model_id(model):
    # Official legacy aliases route to the current Flash model but are not catalog IDs.
    return 'deepseek-flash' if model in {'deepseek-v4-flash', 'deepseek-v4-flash-vision-exp'} else model
