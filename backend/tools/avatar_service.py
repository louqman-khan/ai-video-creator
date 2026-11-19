"""Reference server for the `remote` avatar renderer (AVATAR_RENDERER=remote, AVATAR_URL=http://host:9000).

Run:  AVATAR_SERVICE_TOKEN=secret python backend/tools/avatar_service.py --port 9000

It implements the protocol with the cartoon renderer, so the whole chain can be tried on any computer. For real lip-sync put a GPU model behind the same
three endpoints (MuseTalk, LatentSync, Wav2Lip ...): replace `render()` below with code that takes a face image per avatar id and the audio and returns an
mp4 of the face speaking it, on the key-colour background (#00ff00) or with the person on any background if the editor's green screen key is turned off.
Protocol:   GET /avatars -> [{"id","name"}]   GET /avatars/{id}/thumb -> PNG   POST /render (form: avatar, file: audio) -> mp4 bytes
Authentication: `Authorization: Bearer <token>` when AVATAR_SERVICE_TOKEN is set.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Response, UploadFile  # noqa: E402

from app.providers.avatar_renderer import AvatarUnavailable  # noqa: E402
from app.providers.avatar_renderer.simple import SimpleAvatars  # noqa: E402

engine = SimpleAvatars()
app = FastAPI(title="avatar service")
TOKEN = os.environ.get("AVATAR_SERVICE_TOKEN", "")


def auth(authorization: str = Header("")) -> None:
    if TOKEN and authorization != f"Bearer {TOKEN}":
        raise HTTPException(401, "bad token")


@app.get("/avatars", dependencies=[Depends(auth)])
def avatars() -> list[dict]:
    return [{"id": a.id, "name": a.name} for a in engine.avatars()]


@app.get("/avatars/{avatar_id}/thumb", dependencies=[Depends(auth)])
def thumb(avatar_id: str) -> Response:
    try:
        return Response(engine.thumbnail(avatar_id), media_type="image/png")
    except AvatarUnavailable as e:
        raise HTTPException(404, str(e)) from None


@app.post("/render", dependencies=[Depends(auth)])
async def render(avatar: str = Form(...), audio: UploadFile = File(...)) -> Response:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "audio"
        src.write_bytes(await audio.read())
        try:
            out = engine.render(avatar, src, Path(tmp) / "out.mp4")
        except AvatarUnavailable as e:
            raise HTTPException(422, str(e)) from None
        return Response(out.read_bytes(), media_type="video/mp4")


if __name__ == "__main__":
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9000)
    a = ap.parse_args()
    uvicorn.run(app, host=a.host, port=a.port)
