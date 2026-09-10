from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx
from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

import app as legacy
import secure_app as secured

app = secured.app


# Replace the legacy upload route. The old handler considered every <400
# response from Immich a success without checking that an asset actually
# existed. This handler requires a real asset id and verifies it with Immich
# before the browser is allowed to show a green success state.
for route in list(app.routes):
    if getattr(route, "path", None) == "/api/upload/{slug}" and "POST" in getattr(route, "methods", set()):
        app.routes.remove(route)


_original_portal_page = legacy.portal_page


def portal_page_with_verification(slug, portal):
    page = _original_portal_page(slug, portal)
    page = page.replace(
        "item.reason.className='file-reason '+(state==='failed'?'bad':'warn');",
        "item.reason.className='file-reason '+(state==='failed'?'bad':state==='uploaded'?'ok':'warn');",
    )
    page = page.replace(
        "if(xhr.status>=200&&xhr.status<300&&data&&data.status==='uploaded')setItem(item,'uploaded','Uploaded',100);",
        "if(xhr.status>=200&&xhr.status<300&&data&&data.status==='uploaded')setItem(item,'uploaded',data.verified?'Verified':'Uploaded',100,data.asset_id?`Immich asset: ${data.asset_id}`:'');",
    )
    return page


legacy.portal_page = portal_page_with_verification


async def _save_to_fallback(portal, tmp, name, reason, status_code=202):
    dest = legacy.unique(portal['fallback_dir'], name)
    legacy.move_file(tmp, dest)
    return JSONResponse(
        {'status': 'fallback', 'filename': dest.name, 'reason': reason},
        status_code=status_code,
    )


async def _verify_asset(client: httpx.AsyncClient, base: str, headers: dict, asset_id: str):
    last_status = None
    for attempt in range(3):
        try:
            verify = await client.get(f"{base}/assets/{asset_id}", headers=headers)
            last_status = verify.status_code
            if verify.status_code == 200:
                try:
                    payload = verify.json()
                except ValueError:
                    payload = {}
                returned_id = str(payload.get('id') or '')
                if not returned_id or returned_id == asset_id:
                    return True, payload, 200
            if verify.status_code not in (404, 409, 425, 429, 503):
                break
        except httpx.HTTPError:
            pass
        if attempt < 2:
            await asyncio.sleep(0.35 * (attempt + 1))
    return False, {}, last_status


@app.post('/api/upload/{slug}')
async def verified_upload(
    slug: str,
    r: Request,
    file: UploadFile = File(...),
    last_modified: str = Form(''),
    t: str = '',
):
    c, portal = legacy.get_portal(slug, t, legacy.host_without_port(r))
    key = portal.get('api_key', '').strip()
    if not key:
        raise HTTPException(503, 'No API key configured for this portal')

    name = Path(file.filename or 'upload.bin').name
    ext = Path(name).suffix.lower()
    tmp = None
    size = 0

    try:
        with legacy.tempfile.NamedTemporaryFile(delete=False, suffix=ext or '.bin') as handle:
            tmp = handle.name
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > legacy.MAX_FILE_MB * 1024 * 1024:
                    raise HTTPException(413, 'File too large')
                handle.write(chunk)

        if ext not in legacy.ALLOWED:
            response = await _save_to_fallback(portal, tmp, name, 'File type is not supported by this gateway')
            tmp = None
            return response

        # These API timestamps are transport metadata only. The original file is
        # uploaded byte-for-byte; EXIF/XMP/GPS/camera metadata inside it is not
        # rewritten, stripped or recompressed and remains available to Immich's
        # normal metadata extraction jobs.
        dt = last_modified or legacy.datetime.now(legacy.timezone.utc).isoformat()
        headers = {'x-api-key': key, 'Accept': 'application/json'}
        data = {'fileCreatedAt': dt, 'fileModifiedAt': dt, 'isFavorite': 'false'}
        base = c['immich_url'].rstrip('/')
        base = base if base.endswith('/api') else base + '/api'

        timeout = httpx.Timeout(30, read=3600, write=3600)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                with open(tmp, 'rb') as handle:
                    create = await client.post(
                        base + '/assets',
                        headers=headers,
                        data=data,
                        files={'assetData': (name, handle, file.content_type or 'application/octet-stream')},
                    )

                if create.status_code >= 400:
                    reason = f'Immich HTTP {create.status_code}'
                    try:
                        detail = create.json()
                        message = detail.get('message') or detail.get('error') or detail.get('detail')
                        if message:
                            reason += f': {message}'
                    except ValueError:
                        pass
                    response = await _save_to_fallback(portal, tmp, name, reason)
                    tmp = None
                    return response

                try:
                    created = create.json()
                except ValueError:
                    created = {}

                asset_id = str(created.get('id') or created.get('assetId') or '').strip()
                if not asset_id:
                    response = await _save_to_fallback(
                        portal,
                        tmp,
                        name,
                        f'Immich HTTP {create.status_code} did not return an asset ID; upload not marked as verified',
                    )
                    tmp = None
                    return response

                verified, asset, verify_status = await _verify_asset(client, base, headers, asset_id)
                if not verified:
                    suffix = f' (verification HTTP {verify_status})' if verify_status else ''
                    response = await _save_to_fallback(
                        portal,
                        tmp,
                        name,
                        f'Immich returned asset {asset_id}, but the gateway could not verify that it exists{suffix}',
                    )
                    tmp = None
                    return response

                return {
                    'status': 'uploaded',
                    'filename': name,
                    'asset_id': asset_id,
                    'verified': True,
                    'duplicate': bool(created.get('duplicate', False)),
                    'immich_type': asset.get('type'),
                    'immich_original_filename': asset.get('originalFileName') or asset.get('originalFilename'),
                }

        except httpx.HTTPError as exc:
            response = await _save_to_fallback(
                portal,
                tmp,
                name,
                f'Immich connection failed: {exc.__class__.__name__}',
            )
            tmp = None
            return response
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
