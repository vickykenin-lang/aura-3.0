#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, subprocess, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'data/video_generation_config.json'
JOBS = ROOT / 'data/video_jobs.json'
CALENDAR = ROOT / 'content/calendar.json'
GATES = ROOT / 'data/gate_results.json'
OUTDIR = ROOT / 'videos/generated'
API = 'https://api.dev.runwayml.com/v1'
API_VERSION = '2024-11-06'


def load(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return default


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def now():
    return datetime.now(timezone.utc).isoformat()


def get_post(post_id):
    cal = load(CALENDAR, {'days': []})
    for p in cal.get('days', []):
        if str(p.get('id')) == post_id:
            return p
    raise SystemExit(f'Unknown post id: {post_id}')


def validate(post_id):
    p = get_post(post_id)
    g = (load(GATES, {'posts': {}}).get('posts') or {}).get(post_id) or {}
    if not (g.get('pass') and g.get('visual_ok') and float(g.get('score') or 0) >= 7):
        raise SystemExit('REFUSED: post is not currently strict-gate eligible')
    image = str(p.get('image') or '').strip()
    if not image.startswith('https://'):
        raise SystemExit('REFUSED: source image must be HTTPS')
    return p, g, image


def prepare(post_id):
    p, g, image = validate(post_id)
    data = load(JOBS, {'schema_version': 1, 'department_id': 'aura3', 'jobs': {}})
    jobs = data.setdefault('jobs', {})
    prior = jobs.get(post_id) or {}
    if prior.get('status') in {'RENDERING', 'READY_FOR_FOUNDER_REVIEW'}:
        raise SystemExit(f'REFUSED: video job already {prior.get("status")}')
    jobs[post_id] = {
        'post_id': post_id,
        'status': 'RENDERING',
        'requested_at': now(),
        'requested_by': os.getenv('GITHUB_ACTOR', ''),
        'source_image': image,
        'hook': (p.get('ig') or {}).get('hook_en') or post_id,
        'business_score': g.get('score'),
        'provider': 'runway',
        'provider_task_id': None,
        'video_path': None,
        'technical_status': 'PENDING',
        'truth_note': 'Founder requested video generation; no publish authority is implied.'
    }
    save(JOBS, data)
    print(json.dumps({'video_job': 'PREPARED', 'post_id': post_id, 'status': 'RENDERING'}))


def request_json(url, method='GET', payload=None, timeout=90):
    secret = (os.getenv('RUNWAYML_API_SECRET') or '').strip()
    if not secret:
        raise RuntimeError('RUNWAYML_API_SECRET is required')
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8') if payload is not None else None,
        method=method,
        headers={
            'Authorization': f'Bearer {secret}',
            'Content-Type': 'application/json',
            'X-Runway-Version': API_VERSION,
            'User-Agent': 'AURA3-Founder-Video/1.0'
        }
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode('utf-8')
    out = json.loads(body or '{}')
    if not isinstance(out, dict):
        raise RuntimeError('Runway returned non-object JSON')
    return out


def render(post_id):
    _, _, image = validate(post_id)
    cfg = load(CONFIG, {})
    payload = {
        'promptImage': image,
        'promptText': cfg['prompt'],
        'model': cfg.get('model', 'gen4.5'),
        'ratio': cfg.get('source_ratio', '720:1280'),
        'duration': int(cfg.get('duration_seconds', 8)),
    }
    created = request_json(f'{API}/image_to_video', method='POST', payload=payload)
    task_id = str(created.get('id') or '').strip()
    if not task_id:
        raise RuntimeError('Runway did not return a task id')
    data = load(JOBS, {'schema_version': 1, 'department_id': 'aura3', 'jobs': {}})
    data['jobs'][post_id]['provider_task_id'] = task_id
    save(JOBS, data)
    print(json.dumps({'video_job': 'RUNWAY_TASK_CREATED', 'post_id': post_id, 'task_id_recorded': True}))

    output_url = None
    for _ in range(60):
        task = request_json(f'{API}/tasks/{task_id}', timeout=45)
        status = str(task.get('status') or '').upper()
        if status == 'SUCCEEDED':
            outputs = task.get('output') or []
            if isinstance(outputs, list) and outputs and str(outputs[0]).startswith('https://'):
                output_url = str(outputs[0])
                break
            raise RuntimeError('Runway task succeeded without video output')
        if status in {'FAILED', 'CANCELED', 'CANCELLED'}:
            raise RuntimeError(f'Runway task ended with {status}')
        time.sleep(10)
    if not output_url:
        raise TimeoutError('Runway video task timed out')

    OUTDIR.mkdir(parents=True, exist_ok=True)
    source = OUTDIR / f'{post_id}.source.mp4'
    req = urllib.request.Request(output_url, headers={'User-Agent': 'AURA3-Founder-Video/1.0'})
    with urllib.request.urlopen(req, timeout=180) as r:
        source.write_bytes(r.read())
    if source.stat().st_size < 1024:
        raise RuntimeError('Downloaded video output is unexpectedly small')
    print(json.dumps({'video_job': 'SOURCE_DOWNLOADED', 'post_id': post_id, 'bytes': source.stat().st_size}))


def finalize(post_id):
    cfg = load(CONFIG, {})
    OUTDIR.mkdir(parents=True, exist_ok=True)
    source = OUTDIR / f'{post_id}.source.mp4'
    final = OUTDIR / f'{post_id}.mp4'
    if not source.exists():
        raise SystemExit('Missing source render')
    w, h, fps, dur = int(cfg.get('final_width',1080)), int(cfg.get('final_height',1920)), int(cfg.get('final_fps',24)), int(cfg.get('duration_seconds',8))
    subprocess.run([
        'ffmpeg','-y','-i',str(source),'-t',str(dur),'-vf',f'scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps}',
        '-an','-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(final)
    ], check=True)
    probe = subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height,r_frame_rate','-show_entries','format=duration','-of','json',str(final)], text=True)
    meta = json.loads(probe)
    stream = (meta.get('streams') or [{}])[0]
    width, height = int(stream.get('width') or 0), int(stream.get('height') or 0)
    duration = float((meta.get('format') or {}).get('duration') or 0)
    technical = width == w and height == h and duration <= dur + 0.25
    data = load(JOBS, {'schema_version': 1, 'department_id': 'aura3', 'jobs': {}})
    job = data['jobs'][post_id]
    job.update({
        'status': 'READY_FOR_FOUNDER_REVIEW' if technical else 'TECHNICAL_REJECT',
        'completed_at': now(),
        'video_path': f'videos/generated/{post_id}.mp4' if technical else None,
        'technical_status': 'PASS' if technical else 'FAIL',
        'technical': {'width': width, 'height': height, 'fps_target': fps, 'duration_seconds': round(duration, 3)},
        'truth_note': 'Video generation completed for Founder review only. No Instagram publish action was performed.'
    })
    save(JOBS, data)
    source.unlink(missing_ok=True)
    print(json.dumps({'video_job': job['status'], 'post_id': post_id, 'technical': job['technical']}))
    if not technical:
        raise SystemExit(2)


def fail(post_id, reason):
    data = load(JOBS, {'schema_version': 1, 'department_id': 'aura3', 'jobs': {}})
    job = data.setdefault('jobs', {}).setdefault(post_id, {'post_id': post_id})
    job.update({'status':'FAILED','failed_at':now(),'technical_status':'FAIL','error_code':str(reason)[:120]})
    save(JOBS, data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('action', choices=['prepare','render','finalize','fail'])
    ap.add_argument('post_id')
    ap.add_argument('--reason', default='runtime_failure')
    a = ap.parse_args()
    {'prepare':prepare,'render':render,'finalize':finalize}.get(a.action, lambda x: fail(x,a.reason))(a.post_id)

if __name__ == '__main__':
    main()
