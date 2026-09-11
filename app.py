import errno, html, io, json, os, re, secrets, shutil, tempfile, time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx, qrcode
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

ROOT=Path(__file__).resolve().parent
VERSION_FILE=ROOT/'VERSION'
try:
    VERSION=VERSION_FILE.read_text(encoding='utf-8').strip() or '0.0.0'
except Exception:
    VERSION=os.getenv('APP_VERSION','0.0.0')

CFG=Path('/config/config.json')
ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD','')
_session_secret_env=os.getenv('SESSION_SECRET','').strip()
SESSION_SECRET_FILE=Path('/config/session_secret')
COOKIE_SECURE=os.getenv('COOKIE_SECURE','false').lower() in ('1','true','yes')
MAX_FILE_MB=int(os.getenv('MAX_FILE_MB','5000'))
UPDATER_URL=os.getenv('UPDATER_URL','http://immich-gateway-updater:8093').rstrip('/')
PORTAL_ALBUM_NAME='Uploaded though Portal'
ALLOWED={'.jpg','.jpeg','.png','.webp','.heic','.heif','.gif','.tif','.tiff','.dng','.nef','.cr2','.cr3','.arw','.raf','.avif','.mp4','.mov','.m4v','.3gp','.webm','.mkv','.avi'}
SLUG_RE=re.compile(r'^[a-z0-9][a-z0-9-]{0,62}$')


def _session_secret():
    if _session_secret_env and _session_secret_env != 'CHANGE_ME':
        return _session_secret_env
    SESSION_SECRET_FILE.parent.mkdir(parents=True,exist_ok=True)
    if SESSION_SECRET_FILE.exists():
        v=SESSION_SECRET_FILE.read_text(encoding='utf-8').strip()
        if v:
            return v
    v=secrets.token_urlsafe(48)
    SESSION_SECRET_FILE.write_text(v,encoding='utf-8')
    os.chmod(SESSION_SECRET_FILE,0o600)
    return v

SESSION_SECRET=_session_secret()
ser=URLSafeTimedSerializer(SESSION_SECRET,salt='admin')
app=FastAPI(title='Immich Upload Gateway')

DEFAULT={
    'schema_version':2,
    'immich_url':'http://192.168.1.187:8080',
    'public_base_url':'http://192.168.1.187:8092',
    'portals':{
        'work':{
            'enabled':True,'name':'Work Photo Upload','subtitle':'Upload original project photos and videos.',
            'design':'industrial','accent':'#f97316','api_key':'','upload_token':secrets.token_urlsafe(24),
            'fallback_dir':'/fallback/work','domains':[]
        },
        'personal':{
            'enabled':True,'name':'Personal Upload','subtitle':'Share original photos and videos.',
            'design':'friendly','accent':'#7c3aed','api_key':'','upload_token':secrets.token_urlsafe(24),
            'fallback_dir':'/fallback/personal','domains':[]
        }
    }
}


def save(c):
    CFG.parent.mkdir(parents=True,exist_ok=True)
    t=CFG.with_suffix('.tmp')
    with open(t,'w',encoding='utf-8') as h:
        json.dump(c,h,indent=2)
    os.chmod(t,0o600)
    os.replace(t,CFG)


def normalise_domain(v):
    v=str(v or '').strip().lower()
    v=v.removeprefix('https://').removeprefix('http://').split('/')[0].strip('.')
    if ':' in v:
        v=v.split(':',1)[0]
    return v


def migrate(c):
    changed=False
    if not isinstance(c,dict):
        return deepcopy(DEFAULT),True
    if 'immich_url' not in c:
        c['immich_url']=DEFAULT['immich_url']; changed=True
    if 'public_base_url' not in c:
        c['public_base_url']=DEFAULT['public_base_url']; changed=True
    if not isinstance(c.get('portals'),dict):
        c['portals']={}; changed=True
    for slug,p in list(c['portals'].items()):
        if not isinstance(p,dict):
            p={}; c['portals'][slug]=p; changed=True
        defaults=DEFAULT['portals'].get(slug,{
            'enabled':True,'name':slug.replace('-',' ').title(),'subtitle':'Upload original photos and videos.',
            'design':'friendly','accent':'#7c3aed','api_key':'','upload_token':secrets.token_urlsafe(24),
            'fallback_dir':f'/fallback/portals/{slug}','domains':[]
        })
        for k,v in defaults.items():
            if k not in p:
                p[k]=deepcopy(v); changed=True
        if not isinstance(p.get('domains'),list):
            old=p.get('domain','')
            p['domains']=[normalise_domain(old)] if normalise_domain(old) else []
            changed=True
        cleaned=[]
        for d in p.get('domains',[]):
            d=normalise_domain(d)
            if d and d not in cleaned:
                cleaned.append(d)
        if cleaned!=p.get('domains',[]):
            p['domains']=cleaned; changed=True
    if c.get('schema_version')!=2:
        c['schema_version']=2; changed=True
    return c,changed


def load():
    CFG.parent.mkdir(parents=True,exist_ok=True)
    if not CFG.exists():
        c=deepcopy(DEFAULT); save(c); return c
    try:
        with open(CFG,encoding='utf-8') as h:
            c=json.load(h)
    except Exception:
        raise HTTPException(500,'Configuration file is invalid JSON')
    c,changed=migrate(c)
    if changed:
        save(c)
    return c


def admin_ok(r):
    try:
        ser.loads(r.cookies.get('admin_session',''),max_age=43200)
        return True
    except (BadSignature,SignatureExpired):
        return False


def host_without_port(r):
    forwarded=(r.headers.get('x-forwarded-host') or '').split(',')[0].strip()
    host=forwarded or r.headers.get('host','')
    return normalise_domain(host)


def portal_for_host(c,host):
    host=normalise_domain(host)
    if not host:
        return None,None
    for slug,p in c.get('portals',{}).items():
        if p.get('enabled') and host in [normalise_domain(x) for x in p.get('domains',[])]:
            return slug,p
    return None,None


def get_portal(slug,token='',host=''):
    c=load(); p=c['portals'].get(slug)
    if not p or not p.get('enabled'):
        raise HTTPException(404,'Portal not found')
    host_match=normalise_domain(host) in [normalise_domain(x) for x in p.get('domains',[])] if host else False
    token_ok=bool(token and secrets.compare_digest(token,p.get('upload_token','')))
    if not host_match and not token_ok:
        raise HTTPException(403,'Invalid upload link')
    return c,p


def unique(folder,name):
    d=Path(folder); d.mkdir(parents=True,exist_ok=True)
    out=d/Path(name).name; n=1
    while out.exists():
        out=d/f'{Path(name).stem}_{n}{Path(name).suffix}'; n+=1
    return out


def move_file(source,destination):
    try:
        os.replace(source,destination)
    except OSError as exc:
        if exc.errno!=errno.EXDEV:
            raise
        shutil.move(source,destination)


async def add_to_portal_album(client,base,headers,asset_id):
    """Add an uploaded asset to the shared portal album, creating it when needed."""
    albums_response=await client.get(base+'/albums',headers=headers)
    albums_response.raise_for_status()
    albums=albums_response.json()
    album=next((item for item in albums if item.get('albumName')==PORTAL_ALBUM_NAME),None)
    if album:
        add_response=await client.put(
            base+f"/albums/{album['id']}/assets",
            headers=headers,
            json={'ids':[asset_id]},
        )
    else:
        add_response=await client.post(
            base+'/albums',
            headers=headers,
            json={'albumName':PORTAL_ALBUM_NAME,'assetIds':[asset_id]},
        )
    add_response.raise_for_status()


def portal_public_url(c,slug,p):
    domains=[normalise_domain(x) for x in p.get('domains',[]) if normalise_domain(x)]
    if domains:
        return f'https://{domains[0]}/'
    return f"{c.get('public_base_url','').rstrip('/')}/{slug}?t={quote(p.get('upload_token',''))}"

BASE='''*{box-sizing:border-box}body{margin:0;min-height:100vh;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#f3f4f6;color:#111827}.wrap{width:min(92vw,680px);margin:auto;padding:7vh 0}.card{background:#fff;padding:28px;box-shadow:0 14px 40px #0002}h1{margin:0 0 7px}.muted{color:#6b7280}input[type=file]{width:100%;padding:20px;border:2px dashed #9ca3af;background:#fafafa}.btn{width:100%;border:0;padding:15px;margin-top:14px;font-weight:800;color:white;cursor:pointer}.btn:disabled{cursor:not-allowed;opacity:.6}.status{white-space:pre-wrap;margin-top:13px;font-weight:700}.ok{color:#15803d}.warn{color:#b45309}.bad{color:#b91c1c}.file-list{display:grid;gap:10px;margin-top:16px}.file-row{display:grid;grid-template-columns:58px minmax(0,1fr);gap:12px;padding:12px;border:1px solid #d1d5db;border-radius:10px;background:#fff}.file-thumb{width:58px;height:58px;border-radius:8px;object-fit:cover;background:#e5e7eb;display:block}.file-thumb-placeholder{width:58px;height:58px;border-radius:8px;background:#e5e7eb;display:grid;place-items:center;font-size:1.4rem}.file-body{min-width:0}.file-head{display:flex;align-items:flex-start;gap:10px}.file-name{min-width:0;flex:1;font-weight:700;overflow-wrap:anywhere}.file-state{flex:none;font-size:.82rem;font-weight:800}.file-progress{height:9px;background:#e5e7eb;border-radius:999px;overflow:hidden;margin-top:9px}.file-fill{height:100%;width:0;transition:width .15s ease}.file-reason{display:none;margin:8px 0 0;font-size:.85rem;overflow-wrap:anywhere}.retry{display:none;border:0;border-radius:7px;padding:7px 11px;margin-top:9px;font-weight:800;color:#fff;background:#b91c1c;cursor:pointer}@media(prefers-color-scheme:dark){body{background:#0b1017;color:#f8fafc}.card{background:#141b25}.muted{color:#9ca3af}input[type=file]{background:#0d141e;color:#fff;border-color:#475569}.file-row{background:#0d141e;border-color:#334155}.file-thumb,.file-thumb-placeholder,.file-progress{background:#334155}}'''


def portal_page(slug,p):
    friendly=p.get('design')=='friendly'; accent=p.get('accent','#7c3aed')
    name=html.escape(str(p.get('name','Upload')))
    subtitle=html.escape(str(p.get('subtitle','')))
    extra='.card{border-radius:28px}.box{border-radius:22px;padding:20px;background:#f8fafc}' if friendly else '.card{border-radius:8px}.box{border:1px solid #d1d5db;padding:20px}'
    if friendly:
        extra+='body{background:linear-gradient(150deg,#fff7ed,#f5f3ff,#eff6ff)}@media(prefers-color-scheme:dark){body{background:linear-gradient(150deg,#201611,#171426,#0d1726)}.box{background:#101722}}'
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="{accent}"><title>{name}</title><style>{BASE}{extra}.btn,.file-fill{{background:{accent}}}</style></head><body><main class="wrap"><section class="card"><h1>{name}</h1><p class="muted">{subtitle}</p><div class="box"><input id="f" type="file" multiple accept="image/*,video/*,.dng,.nef,.cr2,.cr3,.arw,.raf,.mkv,.avi"><button id="b" class="btn">Upload files</button><div id="files" class="file-list" aria-live="polite"></div><div id="s" class="status" aria-live="polite"></div></div><p class="muted" style="font-size:.85rem">Original files are uploaded without recompression.</p></section></main><script>
const slug={json.dumps(slug)},tok={json.dumps(p.get('upload_token',''))};const f=document.getElementById('f'),b=document.getElementById('b'),s=document.getElementById('s'),files=document.getElementById('files');let items=[],running=false;
function size(n){{if(n<1024)return `${{n}} B`;if(n<1048576)return `${{(n/1024).toFixed(1)}} KB`;return `${{(n/1048576).toFixed(1)}} MB`}}
function setItem(item,state,label,percent,reason=''){{item.status=state;item.state.textContent=label;item.state.className='file-state '+(state==='uploaded'?'ok':state==='fallback'?'warn':state==='failed'?'bad':'');item.fill.style.width=`${{percent}}%`;item.reason.textContent=reason;item.reason.style.display=reason?'block':'none';item.reason.className='file-reason '+(state==='failed'?'bad':'warn');item.retry.style.display=state==='failed'?'inline-block':'none';item.retry.disabled=false}}
function makeThumb(file){{let wrap=document.createElement('div');if(file.type.startsWith('image/')){{let img=document.createElement('img');img.className='file-thumb';img.alt='';let url=URL.createObjectURL(file);img.src=url;img.onload=()=>URL.revokeObjectURL(url);img.onerror=()=>{{URL.revokeObjectURL(url);img.replaceWith(placeholder('🖼️'))}};wrap.append(img)}}else if(file.type.startsWith('video/')){{let video=document.createElement('video');video.className='file-thumb';video.muted=true;video.playsInline=true;video.preload='metadata';let url=URL.createObjectURL(file);video.src=url;video.onloadeddata=()=>{{try{{video.currentTime=Math.min(.1,video.duration||.1)}}catch(_){{}}}};video.onseeked=()=>URL.revokeObjectURL(url);video.onerror=()=>{{URL.revokeObjectURL(url);video.replaceWith(placeholder('🎬'))}};wrap.append(video)}}else wrap.append(placeholder('📄'));return wrap}}
function placeholder(icon){{let el=document.createElement('div');el.className='file-thumb-placeholder';el.textContent=icon;return el}}
function renderFiles(){{files.replaceChildren();items=[...f.files].map(file=>{{let row=document.createElement('div');row.className='file-row';let thumb=makeThumb(file);let body=document.createElement('div');body.className='file-body';let head=document.createElement('div');head.className='file-head';let name=document.createElement('div');name.className='file-name';name.textContent=file.name;let state=document.createElement('span');state.className='file-state';state.textContent='Waiting';let meta=document.createElement('div');meta.className='muted';meta.style.fontSize='.8rem';meta.textContent=size(file.size);let progress=document.createElement('div');progress.className='file-progress';let fill=document.createElement('div');fill.className='file-fill';let reason=document.createElement('p');reason.className='file-reason';let retry=document.createElement('button');retry.type='button';retry.className='retry';retry.textContent='Retry';head.append(name,state);progress.append(fill);body.append(head,meta,progress,reason,retry);row.append(thumb,body);files.append(row);let item={{file,state,fill,reason,retry,status:'waiting'}};retry.onclick=async()=>{{retry.disabled=true;await uploadOne(item);summary()}};return item}});s.textContent=items.length?`${{items.length}} file${{items.length===1?'':'s'}} ready to upload.`:'';s.className='status'}}
function errorReason(xhr,data){{if(data&&typeof data==='object')return data.reason||data.detail||data.message||`Upload failed (HTTP ${{xhr.status}})`;let body=(xhr.responseText||'').trim();return body||`Upload failed (HTTP ${{xhr.status||'unknown'}})`}}
function uploadOne(item){{return new Promise(resolve=>{{setItem(item,'uploading','Uploading',0);let fd=new FormData();fd.append('file',item.file,item.file.name);fd.append('last_modified',new Date(item.file.lastModified).toISOString());let xhr=new XMLHttpRequest();xhr.open('POST',`/api/upload/${{slug}}?t=${{encodeURIComponent(tok)}}`);xhr.upload.onprogress=e=>{{if(e.lengthComputable){{let p=Math.min(99,Math.round(e.loaded/e.total*100));item.fill.style.width=`${{p}}%`;item.state.textContent=`${{p}}%`}}}};xhr.onload=()=>{{let data=null;try{{data=JSON.parse(xhr.responseText)}}catch(_){{}}if(xhr.status>=200&&xhr.status<300&&data&&data.status==='uploaded')setItem(item,'uploaded','Uploaded',100);else if(xhr.status>=200&&xhr.status<300&&data&&data.status==='fallback')setItem(item,'fallback','Saved safely',100,data.reason||'Immich was unavailable, so this file was saved to fallback storage.');else setItem(item,'failed','Failed',100,errorReason(xhr,data));resolve()}};xhr.onerror=()=>{{setItem(item,'failed','Failed',100,'Network error. Check your connection and try again.');resolve()}};xhr.onabort=()=>{{setItem(item,'failed','Failed',100,'Upload was cancelled.');resolve()}};xhr.send(fd)}})}}
function summary(){{let uploaded=items.filter(x=>x.status==='uploaded').length,fallback=items.filter(x=>x.status==='fallback').length,failed=items.filter(x=>x.status==='failed').length,waiting=items.filter(x=>x.status==='waiting'||x.status==='uploading').length;if(waiting){{s.textContent=`Uploading files… ${{uploaded+fallback+failed}} of ${{items.length}} complete`;s.className='status';return}}s.textContent=`Complete: ${{uploaded}} uploaded to Immich`+(fallback?`, ${{fallback}} saved to fallback`:'')+(failed?`, ${{failed}} failed`:'');s.className='status '+(failed?'bad':fallback?'warn':'ok')}}
f.addEventListener('change',renderFiles);b.onclick=async()=>{{if(running)return;if(!items.length){{s.textContent='Choose at least one file.';s.className='status bad';return}}running=true;b.disabled=true;f.disabled=true;for(const item of items){{if(item.status==='waiting'||item.status==='failed'){{await uploadOne(item);summary()}}}}running=false;b.disabled=false;f.disabled=false;summary();if(!items.some(x=>x.status==='failed'))f.value=''}};
</script></body></html>'''

ACSS='''*{box-sizing:border-box}body{margin:0;background:#0b1017;color:#e5e7eb;font-family:system-ui}.shell{max-width:1100px;margin:auto;padding:24px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:17px}.panel{background:#121a25;border:1px solid #273244;border-radius:15px;padding:20px}.full{grid-column:1/-1}label{display:block;margin:11px 0 5px;color:#cbd5e1;font-size:.85rem}input,select,textarea{width:100%;padding:10px;background:#0b111a;color:white;border:1px solid #334155;border-radius:9px}button,.button{display:inline-block;border:0;border-radius:9px;padding:11px 14px;font-weight:800;cursor:pointer;background:#e5e7eb;color:#111827;text-decoration:none}.muted{color:#94a3b8}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}.ok{color:#86efac}.bad{color:#fca5a5}.warn{color:#fde68a}.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.top h1{margin-right:auto}.danger{background:#991b1b;color:white}.primary{background:#2563eb;color:white}.code{font-family:ui-monospace,monospace;white-space:pre-wrap;background:#080c12;padding:12px;border-radius:9px;max-height:340px;overflow:auto}@media(max-width:760px){.grid{grid-template-columns:1fr}.full{grid-column:auto}}'''


def nav():
    return '<div class="actions"><a class="button" href="/admin">Portals</a><a class="button" href="/admin/updates">Updates</a><a class="button" href="/admin/logout">Log out</a></div>'


def admin_page(c,msg=''):
    e=lambda v: html.escape(str(v),quote=True)
    cards=''
    for slug,p in c['portals'].items():
        domains=', '.join(p.get('domains',[]))
        url=portal_public_url(c,slug,p)
        cards+=f'''<section class="panel"><h2>{e(p.get('name',slug))}</h2><p class="muted">/{e(slug)}</p><label><input style="width:auto" type="checkbox" name="{e(slug)}_enabled" {'checked' if p.get('enabled') else ''}> Enabled</label><label>Name</label><input name="{e(slug)}_name" value="{e(p.get('name',''))}"><label>Subtitle</label><input name="{e(slug)}_subtitle" value="{e(p.get('subtitle',''))}"><label>Custom domains <span class="muted">(comma separated, no https://)</span></label><input name="{e(slug)}_domains" value="{e(domains)}" placeholder="wedding.ad53app.com"><label>Design</label><select name="{e(slug)}_design"><option value="industrial" {'selected' if p.get('design')=='industrial' else ''}>Industrial</option><option value="friendly" {'selected' if p.get('design')=='friendly' else ''}>Friendly</option></select><label>Accent</label><input type="color" name="{e(slug)}_accent" value="{e(p.get('accent','#7c3aed'))}"><label>Immich API key <span class="muted">(leave blank to keep current)</span></label><input type="password" name="{e(slug)}_api_key" placeholder="Current key is hidden"><label>Upload token</label><input name="{e(slug)}_upload_token" value="{e(p.get('upload_token',''))}"><label>Fallback path</label><input name="{e(slug)}_fallback_dir" value="{e(p.get('fallback_dir',''))}"><p class="muted">Public URL: {e(url)}</p><div class="actions"><button type="button" onclick="regen('{e(slug)}')">New token</button><a class="button" target="_blank" href="{e(url)}">Open portal</a><a class="button" target="_blank" href="/admin/qr/{e(slug)}" onclick="qrLink(this,'{e(slug)}')">QR code</a><button class="danger" type="submit" form="delete-{e(slug)}">Delete</button></div></section>'''
        cards+=f'''<form id="delete-{e(slug)}" method="post" action="/admin/delete/{e(slug)}" onsubmit="return confirm('Delete portal {e(slug)}? Existing uploaded files are not deleted.')"></form>'''
    return f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>{ACSS}</style></head><body><main class="shell"><div class="top"><h1>Immich Upload Gateway</h1><span class="muted">v{VERSION}</span></div>{nav()}{f'<p class="ok">{e(msg)}</p>' if msg else ''}<form method="post" action="/admin/save"><div class="grid"><section class="panel full"><h2>Global</h2><label>Immich URL</label><input name="immich_url" value="{e(c.get('immich_url',''))}"><label>Fallback public gateway URL</label><input name="public_base_url" value="{e(c.get('public_base_url',''))}"><p class="muted">Custom portal domains override this URL for QR codes and portal links.</p></section>{cards}<section class="panel full"><button class="primary">Save settings</button></section></div></form><section class="panel" style="margin-top:17px"><h2>Add portal</h2><form method="post" action="/admin/add"><label>Portal ID</label><input name="slug" placeholder="smith-wedding" required><label>Name</label><input name="name" placeholder="Smith Wedding" required><label>Custom domain (optional)</label><input name="domain" placeholder="smith.ad53app.com"><button style="margin-top:12px">Add portal</button></form></section><script>function regen(s){{let a=new Uint8Array(24);crypto.getRandomValues(a);document.querySelector(`[name="${{s}}_upload_token"]`).value=[...a].map(x=>x.toString(16).padStart(2,'0')).join('')}}function qrLink(el,s){{let domain=document.querySelector(`[name="${{s}}_domains"]`).value.split(',')[0].trim();el.href=`/admin/qr/${{encodeURIComponent(s)}}${{domain?'?domain='+encodeURIComponent(domain):''}}`}}</script></main></body></html>'''

LOGIN=f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>{ACSS}</style></head><body><main class="shell" style="max-width:430px;padding-top:12vh"><section class="panel"><h1>Admin login</h1><form method="post" action="/admin/login"><label>Password</label><input type="password" name="password"><button style="width:100%;margin-top:14px">Sign in</button></form></section></main></body></html>'''


def updater_status():
    try:
        with httpx.Client(timeout=20) as client:
            r=client.get(UPDATER_URL+'/status'); r.raise_for_status(); return r.json()
    except Exception as exc:
        return {'current':VERSION,'latest':'','update_available':False,'running':False,'last_result':'','last_log':'','error':f'Updater unavailable: {exc}'}


def updates_page(status):
    e=lambda v: html.escape(str(v),quote=True)
    current=status.get('current') or VERSION; latest=status.get('latest') or 'Unknown'
    available=status.get('update_available',False); running=status.get('running',False)
    if running: state='<p class="warn">Update is currently running. This page will refresh automatically.</p>'
    elif available: state='<p class="warn">An update is available.</p>'
    else: state='<p class="ok">No update is currently required.</p>' if latest!='Unknown' else '<p class="bad">Could not check GitHub.</p>'
    button='<button class="primary" onclick="installUpdate()">Install update</button>' if available and not running else ''
    log=e(status.get('last_log',''))
    err=e(status.get('error',''))
    return f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>{ACSS}</style>{'<meta http-equiv="refresh" content="4">' if running else ''}</head><body><main class="shell"><div class="top"><h1>Updates</h1><span class="muted">Immich Upload Gateway</span></div>{nav()}<section class="panel"><h2>Gateway</h2><p>Installed: <strong>{e(current)}</strong><br>Latest on GitHub: <strong>{e(latest)}</strong></p>{state}{f'<p class="bad">{err}</p>' if err else ''}<div class="actions"><button onclick="location.reload()">Check for updates</button>{button}</div></section>{f'<section class="panel" style="margin-top:17px"><h2>Last updater log</h2><div class="code">{log}</div></section>' if log else ''}<script>async function installUpdate(){{if(!confirm('Install the latest Immich Upload Gateway update? Existing /config data will be preserved and the updater will roll back if the new gateway fails its health check.'))return;let r=await fetch('/admin/updates/install',{{method:'POST'}});let j=await r.json();alert(j.message||'Update started');location.reload();}}</script></main></body></html>'''

@app.get('/health')
def health():
    return {'status':'ok','service':'immich-upload-gateway','version':VERSION}

@app.get('/api/info')
def info():
    return {'service':'immich-upload-gateway','version':VERSION}

@app.get('/admin')
def admin(r:Request,saved:int=0,added:int=0):
    if not admin_ok(r):
        return HTMLResponse(LOGIN)
    msg='Settings saved.' if saved else 'Portal added.' if added else ''
    return HTMLResponse(admin_page(load(),msg))

@app.post('/admin/login')
def login(password:str=Form(...)):
    if not ADMIN_PASSWORD:
        raise HTTPException(503,'ADMIN_PASSWORD is not configured')
    if not secrets.compare_digest(password,ADMIN_PASSWORD):
        return HTMLResponse(LOGIN.replace('</form>',"<p class='bad'>Incorrect password</p></form>"),status_code=401)
    resp=RedirectResponse('/admin',303)
    resp.set_cookie('admin_session',ser.dumps({'t':time.time()}),httponly=True,samesite='strict',secure=COOKIE_SECURE,max_age=43200)
    return resp

@app.get('/admin/logout')
def logout():
    r=RedirectResponse('/admin',303); r.delete_cookie('admin_session'); return r

@app.post('/admin/save')
async def admin_save(r:Request):
    if not admin_ok(r): raise HTTPException(401)
    f=await r.form(); c=load()
    c['immich_url']=str(f.get('immich_url','')).strip()
    c['public_base_url']=str(f.get('public_base_url','')).strip().rstrip('/')
    for slug,p in c['portals'].items():
        p['enabled']=f.get(slug+'_enabled') is not None
        for k in ('name','subtitle','design','accent','upload_token','fallback_dir'):
            p[k]=str(f.get(f'{slug}_{k}',p.get(k,''))).strip()
        domains=[]
        for d in str(f.get(f'{slug}_domains','')).split(','):
            d=normalise_domain(d)
            if d and d not in domains: domains.append(d)
        p['domains']=domains
        key=str(f.get(f'{slug}_api_key','')).strip()
        if key: p['api_key']=key
    save(c)
    return RedirectResponse('/admin?saved=1',303)

@app.post('/admin/add')
async def admin_add(r:Request):
    if not admin_ok(r): raise HTTPException(401)
    f=await r.form(); slug=str(f.get('slug','')).strip().lower(); name=str(f.get('name','')).strip(); domain=normalise_domain(f.get('domain',''))
    if not SLUG_RE.match(slug): raise HTTPException(400,'Portal ID must contain lowercase letters, numbers and hyphens only')
    c=load()
    if slug in c['portals']: raise HTTPException(409,'Portal ID already exists')
    c['portals'][slug]={'enabled':True,'name':name or slug.title(),'subtitle':'Upload original photos and videos.','design':'friendly','accent':'#7c3aed','api_key':'','upload_token':secrets.token_urlsafe(24),'fallback_dir':f'/fallback/portals/{slug}','domains':[domain] if domain else []}
    save(c)
    return RedirectResponse('/admin?added=1',303)

@app.post('/admin/delete/{slug}')
def admin_delete(slug:str,r:Request):
    if not admin_ok(r): raise HTTPException(401)
    c=load()
    if slug not in c['portals']: raise HTTPException(404)
    del c['portals'][slug]; save(c)
    return RedirectResponse('/admin',303)

@app.get('/admin/qr/{slug}')
def qr(slug:str,r:Request,domain:str=''):
    if not admin_ok(r): raise HTTPException(401)
    c=load(); p=c['portals'].get(slug)
    if not p: raise HTTPException(404)
    custom_domain=normalise_domain(domain)
    url=f'https://{custom_domain}/' if custom_domain else portal_public_url(c,slug,p)
    im=qrcode.make(url); b=io.BytesIO(); im.save(b,format='PNG')
    return Response(b.getvalue(),media_type='image/png')

@app.get('/admin/updates')
def admin_updates(r:Request):
    if not admin_ok(r): raise HTTPException(401)
    return HTMLResponse(updates_page(updater_status()))

@app.get('/admin/updates/status')
def admin_updates_status(r:Request):
    if not admin_ok(r): raise HTTPException(401)
    return JSONResponse(updater_status())

@app.post('/admin/updates/install')
def admin_updates_install(r:Request):
    if not admin_ok(r): raise HTTPException(401)
    try:
        with httpx.Client(timeout=20) as client:
            rr=client.post(UPDATER_URL+'/install')
            data=rr.json()
            return JSONResponse(data,status_code=rr.status_code)
    except Exception as exc:
        return JSONResponse({'ok':False,'message':f'Updater unavailable: {exc}'},status_code=503)

@app.post('/api/upload/{slug}')
async def upload(slug:str,r:Request,file:UploadFile=File(...),last_modified:str=Form(''),t:str=''):
    c,p=get_portal(slug,t,host_without_port(r)); key=p.get('api_key','').strip()
    if not key: raise HTTPException(503,'No API key configured for this portal')
    name=Path(file.filename or 'upload.bin').name; ext=Path(name).suffix.lower(); tmp=None; size=0
    try:
        with tempfile.NamedTemporaryFile(delete=False,suffix=ext or '.bin') as h:
            tmp=h.name
            while chunk:=await file.read(1024*1024):
                size+=len(chunk)
                if size>MAX_FILE_MB*1024*1024: raise HTTPException(413,'File too large')
                h.write(chunk)
        if ext not in ALLOWED:
            dest=unique(p['fallback_dir'],name); move_file(tmp,dest); tmp=None
            return {'status':'fallback','filename':dest.name}
        dt=last_modified or datetime.now(timezone.utc).isoformat()
        headers={'x-api-key':key,'Accept':'application/json'}
        data={'fileCreatedAt':dt,'fileModifiedAt':dt,'isFavorite':'false'}
        base=c['immich_url'].rstrip('/'); base=base if base.endswith('/api') else base+'/api'
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30,read=3600,write=3600)) as client:
                with open(tmp,'rb') as h:
                    rr=await client.post(base+'/assets',headers=headers,data=data,files={'assetData':(name,h,file.content_type or 'application/octet-stream')})
        except httpx.HTTPError as exc:
            dest=unique(p['fallback_dir'],name); move_file(tmp,dest); tmp=None
            return JSONResponse({'status':'fallback','filename':dest.name,'reason':f'Immich connection failed: {exc.__class__.__name__}'},status_code=202)
        if rr.status_code>=400:
            dest=unique(p['fallback_dir'],name); move_file(tmp,dest); tmp=None
            return JSONResponse({'status':'fallback','filename':dest.name,'reason':f'Immich HTTP {rr.status_code}'},status_code=202)
        album_warning=''
        try:
            asset_id=rr.json().get('id')
            if not asset_id:
                raise ValueError('Immich upload response did not include an asset ID')
            async with httpx.AsyncClient(timeout=httpx.Timeout(30,read=3600,write=3600)) as client:
                await add_to_portal_album(client,base,headers,asset_id)
        except (httpx.HTTPError,ValueError,TypeError) as exc:
            album_warning=f'Uploaded to Immich, but could not add to {PORTAL_ALBUM_NAME}: {exc.__class__.__name__}'
        return {'status':'uploaded','filename':name,'album':PORTAL_ALBUM_NAME,'album_warning':album_warning}
    finally:
        if tmp and os.path.exists(tmp): os.unlink(tmp)

@app.get('/')
def home(r:Request):
    c=load(); slug,p=portal_for_host(c,host_without_port(r))
    if slug:
        return HTMLResponse(portal_page(slug,p))
    return HTMLResponse("<h2 style='font-family:system-ui'>Use the private upload link, custom portal domain or QR code you were given.</h2>")

@app.get('/{slug}')
def portal_by_slug(slug:str,r:Request,t:str=''):
    if slug in {'admin','api','health'}: raise HTTPException(404)
    c,p=get_portal(slug,t,host_without_port(r))
    return HTMLResponse(portal_page(slug,p))
