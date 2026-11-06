"""Shared fail-closed release checks; this module never creates a social post."""
from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PROOFS: dict[str, dict] = {}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
CERTIFICATE_PATH = 'certification/evidence/live-certification.json'
RELEASE_FILES = (
    'scripts/release_guard.py', 'scripts/publish_instagram.py',
    'scripts/approve_manual.py', 'scripts/certify_live.py',
    'governance/authority_policy.json', 'governance/publishing_target.json',
    '.github/workflows/aura3-instagram-publish.yml',
    '.github/workflows/aura3-founder-approval.yml',
    'governance/image_validation_rulebook.json', 'runtime/guarded_execution.py',
    'scripts/score_with_deepseek.py', 'scripts/run_deepseek_primary.py',
    'scripts/aura3_resilient_queue.py', 'scripts/aura3_nova_runtime.py',
)
CERTIFICATE_CHECKS = {'required_files', 'constitutional_contract', 'public_action_gate', 'heartbeat_policy', 'heartbeat_runtime', 'provider_qualification', 'capability_qualification', 'victor_scope', 'runtime_constitutional_binding', 'production_activation_gate'}
CERTIFICATE_CHECKS.update({'heartbeat_evidence_fresh', 'provider_evidence_fresh', 'capability_evidence_fresh'})


class ReleaseRefused(ValueError):
    """A static, safe-to-log refusal reason."""


def load(root, path):
    try:
        value = json.loads((Path(root) / path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ReleaseRefused('missing or invalid release record: ' + path) from None
    if not isinstance(value, dict):
        raise ReleaseRefused('release record must be an object: ' + path)
    return value


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def caption(post):
    ig = post.get('ig') or {}
    parts = [ig.get('hook_en', ''), ig.get('caption_hi', ''), post.get('disclosure', ''), ig.get('hashtags', '')]
    if any(not isinstance(part, str) for part in parts):
        raise ReleaseRefused('caption fields must be strings')
    text = '\n\n'.join(part.strip() for part in parts if part.strip())
    if not text or len(text) > 2200:
        raise ReleaseRefused('caption must contain 1 to 2200 characters')
    return text


def target(root=ROOT):
    value = load(root, 'governance/publishing_target.json')
    username = value.get('instagram_username')
    if not isinstance(username, str) or not username or username != username.strip().lower():
        raise ReleaseRefused('confirmed Instagram target is missing or invalid')
    if any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789._' for c in username):
        raise ReleaseRefused('confirmed Instagram target is invalid')
    return username


def release_code_sha256(root=ROOT):
    try:
        return sha({p: hashlib.sha256((Path(root) / p).read_bytes()).hexdigest() for p in RELEASE_FILES})
    except OSError:
        raise ReleaseRefused('release implementation files are incomplete') from None


def ensure_controls(root=ROOT, now=None):
    c = load(root, 'state/control.json')
    if c.get('kill_switch') is not False or c.get('external_execution_enabled') is not True:
        raise ReleaseRefused('canonical control disables external publishing')
    if c.get('business_execution_enabled') is not True or c.get('certification_status') != 'VERIFIED':
        raise ReleaseRefused('canonical activation and certification are not verified')
    legacy = load(root, 'data/control.json')
    if legacy.get('kill_switch') is not False:
        raise ReleaseRefused('legacy kill switch blocks publishing')
    policy = load(root, 'governance/authority_policy.json')
    if (policy.get('rules') or {}).get('instagram_publish') != 'FOUNDER_ONLY':
        raise ReleaseRefused('Founder publishing authority is not intact')
    cert = load(root, CERTIFICATE_PATH)
    checks = cert.get('checks')
    if cert.get('department_id') != 'aura3' or cert.get('certification') != 'VERIFIED' or cert.get('live') is not True:
        raise ReleaseRefused('current standalone certification is not verified')
    if not isinstance(checks, list) or not checks or any(not isinstance(x, dict) or x.get('pass') is not True for x in checks):
        raise ReleaseRefused('certification checks are incomplete')
    if not CERTIFICATE_CHECKS.issubset({x.get('check') for x in checks}):
        raise ReleaseRefused('required certification checks are missing')
    try:
        observed = datetime.fromisoformat(cert['observed_at'].replace('Z', '+00:00'))
        if observed.tzinfo is None:
            raise ValueError()
        age = ((now or datetime.now(timezone.utc)) - observed).total_seconds()
    except (KeyError, TypeError, ValueError):
        raise ReleaseRefused('certification timestamp is invalid') from None
    if not -300 <= age <= 86400:
        raise ReleaseRefused('standalone certification is stale')
    if cert.get('release_code_sha256') != release_code_sha256(root):
        raise ReleaseRefused('release code changed since certification')


def record_image_proof(url, mime, data):
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
    except (OSError, ValueError):
        raise ReleaseRefused('source image is not decodable') from None
    proof = {'sha256': hashlib.sha256(data).hexdigest(), 'width': width, 'height': height, 'mime': mime}
    SOURCE_PROOFS[url] = proof
    return proof


def fetch_image_proof(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ReleaseRefused('source image must use an HTTPS URL without credentials')
    try:
        request = Request(url, headers={'User-Agent': 'AURA3-Release-Verification/1.0'})
        with urlopen(request, timeout=45) as response:
            if urlsplit(response.geturl()).scheme != 'https':
                raise ReleaseRefused('source image redirected away from HTTPS')
            mime = response.headers.get_content_type()
            if mime not in {'image/jpeg', 'image/png', 'image/webp'}:
                raise ReleaseRefused('unsupported source image type')
            data = response.read(MAX_IMAGE_BYTES + 1)
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise ReleaseRefused('source image is empty or exceeds 8 MB')
        return record_image_proof(url, mime, data)
    except ReleaseRefused:
        raise
    except Exception:
        raise ReleaseRefused('source image could not be verified') from None


def manifest(post, proof, root=ROOT):
    quality = load(root, 'governance/image_validation_rulebook.json').get('quality') or {}
    if int(proof.get('width', 0)) < int(quality['minimum_source_width']) or int(proof.get('height', 0)) < int(quality['minimum_source_height']):
        raise ReleaseRefused('source resolution is below the existing rulebook minimum')
    image_hash = proof.get('sha256')
    if not isinstance(image_hash, str) or len(image_hash) != 64 or any(c not in '0123456789abcdef' for c in image_hash):
        raise ReleaseRefused('source image hash is missing')
    image_url = str(post.get('image', ''))
    if not image_url.startswith('https://'):
        raise ReleaseRefused('source image must use HTTPS')
    return {'schema_version': 1, 'post_id': str(post.get('id', '')), 'format': 'single_image', 'image_url': image_url, 'image_sha256': image_hash, 'source_width': proof['width'], 'source_height': proof['height'], 'caption_sha256': hashlib.sha256(caption(post).encode()).hexdigest(), 'platform': 'instagram', 'target_username': target(root)}


def bind_qualified_gate(post, gate, root=ROOT):
    """Bind real QA to bytes captured by the image downloader in this process."""
    for key in ('release_manifest', 'release_manifest_sha256', 'release_binding_error'):
        gate.pop(key, None)
    if gate.get('pass') is not True or gate.get('visual_ok') is not True:
        return gate
    proof = SOURCE_PROOFS.get(post.get('image'))
    try:
        if not proof:
            raise ReleaseRefused('fresh source-image QA proof is missing')
        value = manifest(post, proof, root)
        gate['release_manifest'] = value
        gate['release_manifest_sha256'] = sha(value)
    except ReleaseRefused as error:
        gate['release_binding_error'] = str(error)
    return gate


def qualified_manifest(post, gates, root=ROOT):
    gate = (gates.get('posts') or {}).get(str(post.get('id'))) or {}
    if gates.get('batch_complete') is not True or gate.get('pass') is not True or gate.get('visual_ok') is not True or int(gate.get('score', 0)) < 7:
        raise ReleaseRefused('post does not pass the current strict dual gate')
    old = gate.get('release_manifest')
    if not isinstance(old, dict):
        raise ReleaseRefused('QA requires a fresh content-bound review')
    proof = {'sha256': old.get('image_sha256'), 'width': old.get('source_width', 0), 'height': old.get('source_height', 0)}
    current = manifest(post, proof, root)
    if old != current or gate.get('release_manifest_sha256') != sha(current):
        raise ReleaseRefused('content or target changed after QA')
    return current


def verify_source(value):
    proof = fetch_image_proof(value['image_url'])
    if proof['sha256'] != value['image_sha256'] or proof['width'] != value['source_width'] or proof['height'] != value['source_height']:
        raise ReleaseRefused('source image changed after QA and approval')


def prepare_release(root, post_id, verify_image=True):
    published = load(root, 'content/published.json')
    if (published.get(post_id) or {}).get('instagram', {}).get('id'):
        return None  # Pure idempotent no-op; no network, credentials or state mutation.
    ensure_controls(root)
    calendar = load(root, 'content/calendar.json')
    post = next((p for p in calendar.get('days', []) if p.get('id') == post_id), None)
    if not post:
        raise ReleaseRefused('post is not in the current calendar')
    if load(root, 'data/approvals.json').get(post_id) != 'approved_manual':
        raise ReleaseRefused('post is not Founder-approved')
    value = qualified_manifest(post, load(root, 'data/gate_results.json'), root)
    approved = load(root, 'data/approval_manifests.json').get(post_id) or {}
    if approved.get('manifest') != value or approved.get('manifest_sha256') != sha(value):
        raise ReleaseRefused('exact content and target need fresh Founder approval')
    if verify_image:
        verify_source(value)
    return post
