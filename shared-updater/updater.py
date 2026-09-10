import base64
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.getenv("UPDATER_PORT", "8093"))
CONFIG = Path(os.getenv("UPDATER_CONFIG", "/config/apps.json"))
STATE_DIR = Path(os.getenv("UPDATER_STATE_DIR", "/state"))
DEFAULT_APP_ID = os.getenv("DEFAULT_APP_ID", "").strip()
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOCKS = {}
LOCKS_GUARD = threading.Lock()


def load_config():
    with CONFIG.open(encoding="utf-8") as f:
        data = json.load(f)
    result = {}
    for app in data.get("apps", []):
        app_id = str(app.get("id", "")).strip()
        if app_id:
            result[app_id] = app
    return result


def get_app(app_id):
    apps = load_config()
    if app_id not in apps:
        raise KeyError(f"Unknown app: {app_id}")
    return apps[app_id]


def app_lock(app_id):
    with LOCKS_GUARD:
        return LOCKS.setdefault(app_id, threading.Lock())


def state_path(app_id):
    return STATE_DIR / f"{app_id}.json"


def read_state(app_id):
    try:
        return json.loads(state_path(app_id).read_text(encoding="utf-8"))
    except Exception:
        return {"running": False, "last_result": "", "last_log": ""}


def write_state(app_id, **updates):
    state = read_state(app_id)
    state.update(updates)
    tmp = state_path(app_id).with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, state_path(app_id))


def github_token(app):
    token = str(app.get("github_token", "")).strip()
    token_file = str(app.get("github_token_file", "")).strip()
    if not token and token_file:
        try:
            token = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
    return token


def github_request(app, url):
    headers = {
        "User-Agent": "ad53-shared-updater",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = github_token(app)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def local_version(app):
    try:
        return (Path(app["app_dir"]) / app.get("version_file", "VERSION")).read_text(encoding="utf-8").strip()
    except Exception:
        return "unknown"


def latest_version(app):
    repo = app["repo"]
    branch = app.get("branch", "main")
    version_file = app.get("version_file", "VERSION")
    url = f"https://api.github.com/repos/{repo}/contents/{version_file}?ref={branch}"
    with urllib.request.urlopen(github_request(app, url), timeout=20) as response:
        payload = json.loads(response.read().decode())
    return base64.b64decode(payload["content"]).decode().strip()


def running_version(app):
    url = str(app.get("health_url", "")).strip()
    if not url:
        return local_version(app)
    try:
        with urllib.request.urlopen(url, timeout=8) as response:
            payload = json.loads(response.read().decode())
        field = app.get("health_version_field", "version")
        return str(payload.get(field) or "").strip() or "unknown"
    except Exception:
        return "unknown"


def log_append(lines, text):
    lines.append(text)
    print(f"[shared-updater] {text}", flush=True)


def run_checked(cmd, cwd, lines, timeout=1800):
    log_append(lines, "$ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, timeout=timeout)
    if proc.stdout:
        lines.append(proc.stdout.rstrip())
    if proc.stderr:
        lines.append(proc.stderr.rstrip())
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")


def wait_for_health(app, expected, lines):
    url = str(app.get("health_url", "")).strip()
    if not url:
        return True
    deadline = time.time() + int(app.get("health_timeout_seconds", 90))
    while time.time() < deadline:
        current = running_version(app)
        if current == expected:
            log_append(lines, f"Health/version check passed: {current}")
            return True
        time.sleep(2)
    log_append(lines, f"Health/version check failed; expected {expected}, got {running_version(app)}")
    return False


def compose_command(app, action):
    app_dir = Path(app["app_dir"])
    compose_file = app.get("compose_file", "docker-compose.yml")
    service = app["compose_service"]
    base = ["docker", "compose", "-f", str(app_dir / compose_file)]
    if action == "build":
        return base + ["build", "--pull", service]
    if action == "up":
        return base + ["up", "-d", "--no-deps", service]
    raise ValueError(action)


def copy_item(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def restore_backup(app, backup, lines):
    app_dir = Path(app["app_dir"])
    managed = app.get("managed_files", [])
    log_append(lines, "Restoring previous files…")
    for rel in managed:
        src = backup / rel
        dst = app_dir / rel
        if src.exists():
            copy_item(src, dst)
        elif dst.exists():
            if dst.is_file() or dst.is_symlink():
                dst.unlink()
            else:
                shutil.rmtree(dst)
    run_checked(compose_command(app, "build"), app_dir, lines)
    run_checked(compose_command(app, "up"), app_dir, lines)


def download_source(app, archive):
    repo = app["repo"]
    branch = app.get("branch", "main")
    url = f"https://api.github.com/repos/{repo}/zipball/{branch}"
    with urllib.request.urlopen(github_request(app, url), timeout=120) as response, archive.open("wb") as out:
        shutil.copyfileobj(response, out)


def perform_update(app_id):
    lock = app_lock(app_id)
    if not lock.acquire(blocking=False):
        return
    lines = []
    try:
        app = get_app(app_id)
        app_dir = Path(app["app_dir"])
        source_version = local_version(app)
        target_version = latest_version(app)
        write_state(app_id, running=True, last_result="running", started_at=time.time(), last_log="Starting update…")
        log_append(lines, f"{app.get('name', app_id)}: {source_version} -> {target_version}")

        if source_version == target_version and running_version(app) == target_version:
            log_append(lines, "Already current.")
            write_state(app_id, running=False, last_result="success", finished_at=time.time(), last_log="\n".join(lines)[-30000:])
            return

        backup_root = STATE_DIR / "backups" / app_id / time.strftime("%Y%m%d-%H%M%S")
        backup_root.mkdir(parents=True, exist_ok=True)
        for rel in app.get("managed_files", []):
            src = app_dir / rel
            if src.exists():
                copy_item(src, backup_root / rel)
        log_append(lines, f"Backup created: {backup_root}")

        with tempfile.TemporaryDirectory(prefix=f"update-{app_id}-") as temp_dir:
            temp = Path(temp_dir)
            archive = temp / "source.zip"
            log_append(lines, f"Downloading {app['repo']}@{app.get('branch', 'main')}")
            download_source(app, archive)
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(temp / "src")
            roots = [p for p in (temp / "src").iterdir() if p.is_dir()]
            if len(roots) != 1:
                raise RuntimeError("Downloaded archive has an unexpected layout")
            staged = roots[0]
            staged_version = (staged / app.get("version_file", "VERSION")).read_text(encoding="utf-8").strip()
            if staged_version != target_version:
                raise RuntimeError(f"Archive version {staged_version!r} does not match latest {target_version!r}")

            for cmd in app.get("preflight", []):
                run_checked([str(x) for x in cmd], staged, lines, timeout=300)

            for rel in app.get("managed_files", []):
                src = staged / rel
                if src.exists():
                    copy_item(src, app_dir / rel)

        try:
            run_checked(compose_command(app, "build"), app_dir, lines)
            run_checked(compose_command(app, "up"), app_dir, lines)
            if not wait_for_health(app, target_version, lines):
                raise RuntimeError("New version failed health/version validation")
        except Exception:
            restore_backup(app, backup_root, lines)
            wait_for_health(app, source_version, lines)
            raise

        write_state(app_id, running=False, last_result="success", finished_at=time.time(), last_log="\n".join(lines)[-30000:])
    except Exception as exc:
        log_append(lines, f"FAILED: {type(exc).__name__}: {exc}")
        write_state(app_id, running=False, last_result="failed", finished_at=time.time(), last_log="\n".join(lines)[-30000:])
    finally:
        lock.release()


def app_status(app_id):
    app = get_app(app_id)
    error = ""
    try:
        latest = latest_version(app)
    except Exception as exc:
        latest = ""
        error = str(exc)
    current = running_version(app)
    source = local_version(app)
    return {
        "id": app_id,
        "name": app.get("name", app_id),
        "current": current,
        "source": source,
        "latest": latest,
        "update_available": bool(latest and latest != current),
        "error": error,
        **read_state(app_id),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def json_response(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def parse_app_path(self):
        parts = self.path.split("?", 1)[0].strip("/").split("/")
        if len(parts) == 3 and parts[0] == "apps":
            return parts[1], parts[2]
        return None, None

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/health":
            return self.json_response({"status": "ok", "service": "ad53-shared-updater"})
        if path == "/apps":
            try:
                return self.json_response({"apps": [app_status(app_id) for app_id in load_config()]})
            except Exception as exc:
                return self.json_response({"error": str(exc)}, 500)
        if path == "/status" and DEFAULT_APP_ID:
            try:
                return self.json_response(app_status(DEFAULT_APP_ID))
            except KeyError as exc:
                return self.json_response({"error": str(exc)}, 404)
        app_id, action = self.parse_app_path()
        if action == "status":
            try:
                return self.json_response(app_status(app_id))
            except KeyError as exc:
                return self.json_response({"error": str(exc)}, 404)
            except Exception as exc:
                return self.json_response({"error": str(exc)}, 500)
        return self.json_response({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/install" and DEFAULT_APP_ID:
            app_id, action = DEFAULT_APP_ID, "install"
        else:
            app_id, action = self.parse_app_path()
        if action != "install":
            return self.json_response({"error": "not found"}, 404)
        try:
            get_app(app_id)
        except KeyError as exc:
            return self.json_response({"error": str(exc)}, 404)
        state = read_state(app_id)
        if state.get("running") or app_lock(app_id).locked():
            return self.json_response({"ok": False, "message": "Update already running"}, 409)
        threading.Thread(target=perform_update, args=(app_id,), daemon=True).start()
        return self.json_response({"ok": True, "message": f"Update started for {app_id}"}, 202)


ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
