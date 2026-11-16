"""Serves the spike page and the media with HTTP Range support (needed for seeking).
usage: python serve.py <media-dir> [port]"""
import sys
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

media = Path(sys.argv[1]).resolve()
port = int(sys.argv[2]) if len(sys.argv) > 2 else 8899
here = Path(__file__).parent
app = Starlette(routes=[Mount("/media", StaticFiles(directory=media)), Mount("/", StaticFiles(directory=here, html=True))])
uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
