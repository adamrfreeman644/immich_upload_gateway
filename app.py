import html, io, json, os, secrets, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
import httpx, qrcode
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

VERSION='0.2.1'
CFG=Path('/config/config.json')
ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD','')
_session_secret_env=os.getenv('SESSION_SECRET','').strip()
SESSION_SECRET_FILE=Path('/config/session_secret')
def _session_secret():
    if _session_secret_env and _session_secret_env != 'CHANGE_ME': return _session_secret_env
    SESSION_SECRET_FILE.parent.mkdir(parents=True,exist_ok=True)
    if SESSION_SECRET_FILE.exists():
        v=SESSION_SECRET_FILE.read_text(encoding='utf-8').strip()
        if v: return v
    v=secrets.token_urlsafe(48)
    SESSION_SECRET_FILE.write_text(v,encoding='utf-8')
    os.chmod(SESSION_SECRET_FILE,0o600)
    return v
SESSION_SECRET=_session_secret()
COOKIE_SECURE=os.getenv('COOKIE_SECURE','false').lower() in ('1','true','yes')
MAX_FILE_MB=int(os.getenv('MAX_FILE_MB','5000'))
ALLOWED={'.jpg','.jpeg','.png','.webp','.heic','.heif','.gif','.tif','.tiff','.dng','.nef','.cr2','.cr3','.arw','.raf','.avif','.mp4','.mov','.m4v','.3gp','.webm','.mkv','.avi'}
ser=URLSafeTimedSerializer(SESSION_SECRET,salt='admin')
app=FastAPI(title='Immich Upload Gateway')
DEFAULT={'immich_url':'http://192.168.1.187:8080','public_base_url':'http://192.168.1.187:8092','portals':{
'work':{'enabled':True,'name':'Work Photo Upload','subtitle':'Upload original project photos and videos.','design':'industrial','accent':'#f97316','api_key':'','upload_token':secrets.token_urlsafe(24),'fallback_dir':'/fallback/work'},
'personal':{'enabled':True,'name':'Personal Upload','subtitle':'Share original photos and videos.','design':'friendly','accent':'#7c3aed','api_key':'','upload_token':secrets.token_urlsafe(24),'fallback_dir':'/fallback/personal'}}}

def save(c):
    CFG.parent.mkdir(parents=True,exist_ok=True)
    t=CFG.with_suffix('.tmp')
    with open(t,'w',encoding='utf-8') as h: json.dump(c,h,indent=2)
    os.chmod(t,0o600); os.replace(t,CFG)

def load():
    CFG.parent.mkdir(parents=True,exist_ok=True)
    if not CFG.exists(): save(DEFAULT)
    return json.load(open(CFG,encoding='utf-8'))

def admin_ok(r):
    try: ser.loads(r.cookies.get('admin_session',''),max_age=43200); return True
    except (BadSignature,SignatureExpired): return False

def get_portal(slug,token):
    c=load(); p=c['portals'].get(slug)
    if not p or not p.get('enabled'): raise HTTPException(404,'Portal not found')
    if not token or not secrets.compare_digest(token,p.get('upload_token','')): raise HTTPException(403,'Invalid upload link')
    return c,p

def unique(folder,name):
    d=Path(folder); d.mkdir(parents=True,exist_ok=True); out=d/Path(name).name; n=1
    while out.exists(): out=d/f'{Path(name).stem}_{n}{Path(name).suffix}'; n+=1
    return out

BASE='''*{box-sizing:border-box}body{margin:0;min-height:100vh;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#f3f4f6;color:#111827}.wrap{width:min(92vw,680px);margin:auto;padding:7vh 0}.card{background:#fff;padding:28px;box-shadow:0 14px 40px #0002}h1{margin:0 0 7px}.muted{color:#6b7280}input[type=file]{width:100%;padding:20px;border:2px dashed #9ca3af;background:#fafafa}.btn{width:100%;border:0;padding:15px;margin-top:14px;font-weight:800;color:white;cursor:pointer}.progress{height:11px;background:#e5e7eb;border-radius:999px;overflow:hidden;margin-top:18px}.fill{height:100%;width:0}.status{white-space:pre-wrap;margin-top:13px;font-weight:700}.ok{color:#15803d}.warn{color:#b45309}.bad{color:#b91c1c}@media(prefers-color-scheme:dark){body{background:#0b1017;color:#f8fafc}.card{background:#141b25}.muted{color:#9ca3af}input[type=file]{background:#0d141e;color:#fff;border-color:#475569}.progress{background:#334155}}'''

def portal_page(slug,p):
    friendly=p['design']=='friendly'; accent=p['accent']
    name=html.escape(str(p.get('name','')))
    subtitle=html.escape(str(p.get('subtitle','')))
    extra='.card{border-radius:28px}.box{border-radius:22px;padding:20px;background:#f8fafc}' if friendly else '.card{border-radius:8px}.box{border:1px solid #d1d5db;padding:20px}'
    if friendly: extra+='body{background:linear-gradient(150deg,#fff7ed,#f5f3ff,#eff6ff)}@media(prefers-color-scheme:dark){body{background:linear-gradient(150deg,#201611,#171426,#0d1726)}.box{background:#101722}}'
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="{accent}"><title>{name}</title><style>{BASE}{extra}.btn,.fill{{background:{accent}}}</style></head><body><main class="wrap"><section class="card"><h1>{name}</h1><p class="muted">{subtitle}</p><div class="box"><input id="f" type="file" multiple accept="image/*,video/*,.dng,.nef,.cr2,.cr3,.arw,.raf,.mkv,.avi"><button id="b" class="btn">Upload files</button><div id="pr" class="progress" style="display:none"><div id="fi" class="fill"></div></div><div id="s" class="status"></div></div><p class="muted" style="font-size:.85rem">Original files are uploaded without recompression.</p></section></main><script>
const slug={json.dumps(slug)},tok={json.dumps(p['upload_token'])};const f=document.getElementById('f'),b=document.getElementById('b'),s=document.getElementById('s'),pr=document.getElementById('pr'),fi=document.getElementById('fi');
b.onclick=async()=>{{let a=[...f.files];if(!a.length){{s.textContent='Choose at least one file.';s.className='status bad';return}}b.disabled=true;pr.style.display='block';let u=0,x=0,e=0,d=0;for(const z of a){{s.textContent=`Uploading ${{d+1}} of ${{a.length}}: ${{z.name}}`;let fd=new FormData();fd.append('file',z,z.name);fd.append('last_modified',new Date(z.lastModified).toISOString());try{{let r=await fetch(`/api/upload/${{slug}}?t=${{encodeURIComponent(tok)}}`,{{method:'POST',body:fd}}),j=await r.json();if(r.ok&&j.status==='uploaded')u++;else if(r.ok&&j.status==='fallback')x++;else e++}}catch(q){{e++}}d++;fi.style.width=`${{Math.round(d/a.length*100)}}%`}}s.textContent=`Complete\n${{u}} uploaded to Immich`+(x?`\n${{x}} saved to fallback`:'')+(e?`\n${{e}} failed`:'');s.className='status '+(e?'bad':x?'warn':'ok');b.disabled=false;if(!e)f.value=''}};
</script></body></html>'''

ACSS='''*{box-sizing:border-box}body{margin:0;background:#0b1017;color:#e5e7eb;font-family:system-ui}.shell{max-width:1050px;margin:auto;padding:24px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:17px}.panel{background:#121a25;border:1px solid #273244;border-radius:15px;padding:20px}.full{grid-column:1/-1}label{display:block;margin:11px 0 5px;color:#cbd5e1;font-size:.85rem}input,select{width:100%;padding:10px;background:#0b111a;color:white;border:1px solid #334155;border-radius:9px}button{border:0;border-radius:9px;padding:11px 14px;font-weight:800;cursor:pointer}.muted{color:#94a3b8}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}.ok{color:#86efac}.bad{color:#fca5a5}@media(max-width:760px){.grid{grid-template-columns:1fr}.full{grid-column:auto}}'''

def admin_page(c,msg=''):
    e=lambda v: html.escape(str(v),quote=True)
    cards=''
    for slug,p in c['portals'].items():
        cards+=f'''<section class="panel"><h2>{slug.title()} portal</h2><label><input style="width:auto" type="checkbox" name="{slug}_enabled" {'checked' if p['enabled'] else ''}> Enabled</label><label>Name</label><input name="{slug}_name" value="{e(p['name'])}"><label>Subtitle</label><input name="{slug}_subtitle" value="{e(p['subtitle'])}"><label>Design</label><select name="{slug}_design"><option value="industrial" {'selected' if p['design']=='industrial' else ''}>Industrial</option><option value="friendly" {'selected' if p['design']=='friendly' else ''}>Friendly</option></select><label>Accent</label><input type="color" name="{slug}_accent" value="{e(p['accent'])}"><label>Immich API key (leave blank to keep current)</label><input type="password" name="{slug}_api_key" placeholder="Current key is hidden"><label>Upload token</label><input name="{slug}_upload_token" value="{e(p['upload_token'])}"><label>Fallback path</label><input name="{slug}_fallback_dir" value="{e(p['fallback_dir'])}"><div class="actions"><button type="button" onclick="regen('{slug}')">New token</button><a target="_blank" href="/{slug}?t={quote(p['upload_token'])}"><button type="button">Open portal</button></a><a target="_blank" href="/admin/qr/{slug}"><button type="button">QR code</button></a></div></section>'''
    return f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>{ACSS}</style></head><body><main class="shell"><h1>Immich Upload Gateway</h1><p class="muted">v{VERSION} · private admin</p>{f'<p class="ok">{msg}</p>' if msg else ''}<form method="post" action="/admin/save"><div class="grid"><section class="panel full"><h2>Global</h2><label>Immich URL</label><input name="immich_url" value="{e(c['immich_url'])}"><label>Public gateway URL (for QR codes)</label><input name="public_base_url" value="{e(c['public_base_url'])}"></section>{cards}<section class="panel full"><button>Save settings</button> <a href="/admin/logout">Log out</a></section></div></form><script>function regen(s){{let a=new Uint8Array(24);crypto.getRandomValues(a);document.querySelector(`[name="${{s}}_upload_token"]`).value=[...a].map(x=>x.toString(16).padStart(2,'0')).join('')}}</script></main></body></html>'''

LOGIN=f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>{ACSS}</style></head><body><main class="shell" style="max-width:430px;padding-top:12vh"><section class="panel"><h1>Admin login</h1><form method="post" action="/admin/login"><label>Password</label><input type="password" name="password"><button style="width:100%;margin-top:14px">Sign in</button></form></section></main></body></html>'''

@app.get('/health')
def health(): return {'status':'ok','service':'immich-upload-gateway','version':VERSION}
@app.get('/api/info')
def info(): return {'service':'immich-upload-gateway','version':VERSION}
@app.get('/')
def home(): return HTMLResponse("<h2 style='font-family:system-ui'>Use the private upload link or QR code you were given.</h2>")
@app.get('/work')
def work(t:str=''): c,p=get_portal('work',t); return HTMLResponse(portal_page('work',p))
@app.get('/personal')
def personal(t:str=''): c,p=get_portal('personal',t); return HTMLResponse(portal_page('personal',p))

@app.post('/api/upload/{slug}')
async def upload(slug:str,file:UploadFile=File(...),last_modified:str=Form(''),t:str=''):
    c,p=get_portal(slug,t); key=p.get('api_key','').strip()
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
            dest=unique(p['fallback_dir'],name); os.replace(tmp,dest); tmp=None; return {'status':'fallback','filename':dest.name}
        dt=last_modified or datetime.now(timezone.utc).isoformat(); headers={'x-api-key':key,'Accept':'application/json'}; data={'fileCreatedAt':dt,'fileModifiedAt':dt,'isFavorite':'false'}
        base=c['immich_url'].rstrip('/'); base=base if base.endswith('/api') else base+'/api'
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30,read=3600,write=3600)) as client:
                with open(tmp,'rb') as h:
                    r=await client.post(base+'/assets',headers=headers,data=data,files={'assetData':(name,h,file.content_type or 'application/octet-stream')})
        except httpx.HTTPError as exc:
            dest=unique(p['fallback_dir'],name); os.replace(tmp,dest); tmp=None
            return JSONResponse({'status':'fallback','filename':dest.name,'reason':f'Immich connection failed: {exc.__class__.__name__}'},status_code=202)
        if r.status_code>=400:
            dest=unique(p['fallback_dir'],name); os.replace(tmp,dest); tmp=None
            return JSONResponse({'status':'fallback','filename':dest.name,'reason':f'Immich HTTP {r.status_code}'},status_code=202)
        return {'status':'uploaded','filename':name}
    finally:
        if tmp and os.path.exists(tmp): os.unlink(tmp)

@app.get('/admin')
def admin(r:Request,saved:int=0): return HTMLResponse(admin_page(load(),'Settings saved.') if admin_ok(r) and saved else admin_page(load()) if admin_ok(r) else LOGIN)
@app.post('/admin/login')
def login(password:str=Form(...)):
    if not ADMIN_PASSWORD: raise HTTPException(503,'ADMIN_PASSWORD is not configured')
    if not secrets.compare_digest(password,ADMIN_PASSWORD): return HTMLResponse(LOGIN.replace('</form>',"<p class='bad'>Incorrect password</p></form>"),status_code=401)
    resp=RedirectResponse('/admin',303); resp.set_cookie('admin_session',ser.dumps({'t':time.time()}),httponly=True,samesite='strict',secure=COOKIE_SECURE,max_age=43200); return resp
@app.get('/admin/logout')
def logout():
    r=RedirectResponse('/admin',303); r.delete_cookie('admin_session'); return r
@app.post('/admin/save')
async def admin_save(r:Request):
    if not admin_ok(r): raise HTTPException(401)
    f=await r.form(); c=load(); c['immich_url']=str(f.get('immich_url','')).strip(); c['public_base_url']=str(f.get('public_base_url','')).strip().rstrip('/')
    for slug,p in c['portals'].items():
        p['enabled']=f.get(slug+'_enabled') is not None
        for k in ('name','subtitle','design','accent','upload_token','fallback_dir'): p[k]=str(f.get(f'{slug}_{k}',p[k])).strip()
        k=str(f.get(f'{slug}_api_key','')).strip()
        if k: p['api_key']=k
    save(c); return RedirectResponse('/admin?saved=1',303)
@app.get('/admin/qr/{slug}')
def qr(slug:str,r:Request):
    if not admin_ok(r): raise HTTPException(401)
    c=load(); p=c['portals'].get(slug)
    if not p: raise HTTPException(404)
    url=f"{c['public_base_url'].rstrip('/')}/{slug}?t={quote(p['upload_token'])}"
    im=qrcode.make(url); b=io.BytesIO(); im.save(b,format='PNG'); return Response(b.getvalue(),media_type='image/png')
