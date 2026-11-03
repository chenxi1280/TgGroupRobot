from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parents[3] / "miniapp" / "dist"
router = APIRouter()


@router.get("/miniapp/")
async def mini_app_index():
    path = STATIC_DIR / "index.html"
    if not path.is_file():
        raise HTTPException(status_code=503, detail="小程序页面尚未构建")
    return FileResponse(path, headers={"Cache-Control": "no-store"})


def mount_assets(app):
    app.mount("/miniapp/assets", StaticFiles(directory=STATIC_DIR / "assets", check_dir=False), name="miniapp-assets")
