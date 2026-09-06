import json, os, subprocess, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_DIR=Path(os.getenv('APP_DIR','/appsrc'))
REPO=os.getenv('REPO','adamrfreeman644/immich_upload_gateway')
BRANCH=os.getenv('BRANCH','main')
PORT=int(os.getenv('UPDATER_PORT','8093'))
STATE=Path('/tmp/immich-gateway-updater.json')
LOCK=threading.Lock()

def version_local():
    try: return (APP_DIR/'VERSION').read_text().strip()
    except Exception: return 'unknown'

def version_latest():
    url=f'https://raw.githubusercontent.com/{REPO}/{BRANCH}/VERSION'
    with urllib.request.urlopen(url,timeout=15) as r:
        return r.read().decode().strip()

def read_state():
    try: return json.loads(STATE.read_text())
    except Exception: return {'running':False,'last_result':'','last_log':''}

def write_state(**kw):
    s=read_state(); s.update(kw); STATE.write_text(json.dumps(s))

def run_update():
    with LOCK:
        write_state(running=True,last_result='running',last_log='Starting update…',started_at=time.time())
        try:
            p=subprocess.run(['/bin/bash',str(APP_DIR/'gateway-updater.sh')],cwd=str(APP_DIR),text=True,capture_output=True,timeout=1800)
            log=(p.stdout or '')+(('\n'+p.stderr) if p.stderr else '')
            write_state(running=False,last_result='success' if p.returncode==0 else 'failed',last_log=log[-20000:],finished_at=time.time())
        except Exception as exc:
            write_state(running=False,last_result='failed',last_log=f'{type(exc).__name__}: {exc}',finished_at=time.time())

class H(BaseHTTPRequestHandler):
    def sendj(self,obj,status=200):
        b=json.dumps(obj).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self,*a): pass
    def do_GET(self):
        if self.path!='/status': return self.sendj({'error':'not found'},404)
        s=read_state(); current=version_local()
        try: latest=version_latest(); err=''
        except Exception as exc: latest=''; err=str(exc)
        self.sendj({'current':current,'latest':latest,'update_available':bool(latest and latest!=current),'error':err,**s})
    def do_POST(self):
        if self.path!='/install': return self.sendj({'error':'not found'},404)
        s=read_state()
        if s.get('running'): return self.sendj({'ok':False,'message':'Update already running'},409)
        threading.Thread(target=run_update,daemon=True).start(); self.sendj({'ok':True,'message':'Update started'},202)

ThreadingHTTPServer(('0.0.0.0',PORT),H).serve_forever()
