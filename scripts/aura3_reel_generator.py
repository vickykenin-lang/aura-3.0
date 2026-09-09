#!/usr/bin/env python3
from __future__ import annotations
import json, os, subprocess, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; API='https://api.dev.runwayml.com/v1'; API_VERSION='2024-11-06'; MODEL=os.environ.get('AURA3_REEL_MODEL','h3_max'); DURATION=int(os.environ.get('AURA3_REEL_DURATION','8')); RATIO=os.environ.get('AURA3_REEL_RATIO','768:1280'); JOBS=ROOT/'data/reel_generation_jobs.json'; OUT=ROOT/'reels/generated'
PROMPT='''You are an expert interior 3D reconstruction designer and cinematic virtual cinematographer. Reconstruct the exact room shown in the reference image and preserve architecture, wall and ceiling finishes, floor, furniture layout and proportions, fabrics, wood, stone, metal, glass, lighting fixtures, decor, plants, window positions, visible exterior view, colors, time of day, and lighting style. Do not add, remove, rearrange, redesign, beautify, modernize, recolor, or restyle anything. One continuous first-person Steadicam shot at approximately 1.55m eye height. Start from the natural foreground/entrance implied by the reference. Slowly move forward at about 0.3 m/s, then only if spatially safe make a gentle 12-18 degree orbit around the main focal furniture and settle on a closer hero frame. Strong natural parallax. If unseen geometry is uncertain, stay close to the original camera axis and use a simpler slow forward push instead of a large orbit. Luxury real-estate slow motion, ultra smooth and stable. No cuts, transitions, Ken Burns, flat 2D pan, zoom-only movement, morphing, jitter, warped walls, bending ceilings, drifting floor lines, sliding or melting furniture, stretching windows, duplicated or disappearing objects, texture crawling, geometry breathing, or unstable reflections. Photoreal, filmic, 24-35mm lens feel, controlled depth of field, accurate reflections and contact shadows, preserve reference lighting exactly. Empty room. No people, pets, text, logos, watermark, or UI. Vertical mobile composition; keep main furniture inside the center 70% safe area. Reference fidelity is always more important than cinematic movement.'''
def load(p,d):
 try:return json.loads(p.read_text(encoding='utf-8'))
 except:return d
def savejob(j):
 d=load(JOBS,{'schema_version':1,'jobs':[]}); a=[x for x in d.get('jobs',[]) if x.get('reel_id')!=j.get('reel_id')]; a.append(j); d['jobs']=a[-100:]; JOBS.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def req(url,method='GET',payload=None,timeout=90):
 s=(os.environ.get('RUNWAYML_API_SECRET') or '').strip()
 if not s: raise RuntimeError('RUNWAYML_API_SECRET unavailable')
 r=urllib.request.Request(url,data=(json.dumps(payload).encode() if payload is not None else None),method=method,headers={'Authorization':'Bearer '+s,'Content-Type':'application/json','X-Runway-Version':API_VERSION,'User-Agent':'AURA3-Reel-Generator/1.0'})
 with urllib.request.urlopen(r,timeout=timeout) as h:return json.loads(h.read().decode())
def main():
 pid=(os.environ.get('POST_ID') or '').strip(); cal=load(ROOT/'content/calendar.json',{'days':[]}); gates=load(ROOT/'data/gate_results.json',{'posts':{}}); post=next((p for p in cal.get('days',[]) if p.get('id')==pid),None)
 if not post: raise SystemExit('Unknown post id')
 g=(gates.get('posts') or {}).get(pid) or {}
 if not(g.get('pass') and g.get('visual_ok') and float(g.get('score') or 0)>=7): raise SystemExit('REFUSED: source post is not strict-gate-passed')
 image=str(post.get('image') or '').strip()
 if not image.startswith('https://'): raise SystemExit('REFUSED: source image must be HTTPS')
 rid=f"{pid}-reel-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"; j={'reel_id':rid,'post_id':pid,'source_image':image,'status':'GENERATING','requested_by':os.environ.get('GITHUB_ACTOR','Founder'),'requested_at':datetime.now(timezone.utc).isoformat(),'provider':'runway','model':MODEL,'target':{'ratio':'9:16','width':1080,'height':1920,'duration_seconds':8,'fps':24},'prompt_profile':'INTERIOR_REFERENCE_FIDELITY_WALKTHROUGH_V1','truth_note':'Founder-triggered Reel generation is independent from static-post approval and does not publish automatically.'}; savejob(j)
 try:
  t=req(API+'/image_to_video','POST',{'model':MODEL,'promptImage':image,'promptText':PROMPT,'ratio':RATIO,'duration':DURATION},120); tid=str(t.get('id') or '')
  if not tid: raise RuntimeError('No task id'); j['provider_task_id']=tid; savejob(j)
  outurl=None
  for _ in range(40):
   t=req(API+'/tasks/'+tid,timeout=60); st=str(t.get('status') or '').upper()
   if st=='SUCCEEDED':
    o=t.get('output') or []; outurl=str(o[0]) if o else None; break
   if st in {'FAILED','CANCELED','CANCELLED'}: raise RuntimeError('Runway task '+st)
   time.sleep(15)
  if not outurl: raise TimeoutError('Runway video timeout')
  OUT.mkdir(parents=True,exist_ok=True); raw=OUT/(rid+'.raw.mp4'); final=OUT/(rid+'.mp4')
  with urllib.request.urlopen(urllib.request.Request(outurl,headers={'User-Agent':'AURA3-Reel-Generator/1.0'}),timeout=180) as h: raw.write_bytes(h.read())
  subprocess.run(['ffmpeg','-y','-i',str(raw),'-t','8','-vf','scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=24','-an','-c:v','libx264','-preset','medium','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',str(final)],check=True); raw.unlink(missing_ok=True)
  q=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height,r_frame_rate:format=duration','-of','json',str(final)],text=True)); s=(q.get('streams') or [{}])[0]; dur=float((q.get('format') or {}).get('duration') or 0); tech={'width':int(s.get('width') or 0),'height':int(s.get('height') or 0),'fps':str(s.get('r_frame_rate') or ''),'duration_seconds':round(dur,2)}; ok=tech['width']==1080 and tech['height']==1920 and 7<=dur<=8.2
  j.update({'status':'READY_FOR_FOUNDER_REVIEW' if ok else 'TECHNICAL_REJECT','video_path':final.relative_to(ROOT).as_posix(),'technical':tech,'technical_pass':ok,'completed_at':datetime.now(timezone.utc).isoformat()}); savejob(j); print(json.dumps({'reel_generation':j['status'],'reel_id':rid,'technical':tech})); return 0 if ok else 2
 except Exception as e:
  j.update({'status':'FAILED','error_type':type(e).__name__,'completed_at':datetime.now(timezone.utc).isoformat()}); savejob(j); print(json.dumps({'reel_generation':'FAILED','reel_id':rid,'error_type':type(e).__name__})); return 1
if __name__=='__main__': raise SystemExit(main())
