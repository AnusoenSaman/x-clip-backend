"""
Backend สำหรับดาวน์โหลดวิดีโอจาก X (Twitter)
ใช้ yt-dlp ดึงลิงก์ไฟล์วิดีโอคุณภาพสูงสุดที่มีอยู่จริงบนเซิร์ฟเวอร์ของ X
(ไม่มีการ upscale — ได้คุณภาพเท่าที่ต้นทางมีให้เท่านั้น)

รันด้วย:
    pip install fastapi uvicorn yt-dlp
    uvicorn app:app --host 0.0.0.0 --port 8000
"""

import os
import uuid
import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import yt_dlp

app = FastAPI(title="X Clip Downloader")

# เปิด CORS ให้หน้าเว็บ (index.html) เรียกใช้ได้จากทุกที่
# ใน production แนะนำให้จำกัด origin ให้เหลือแค่โดเมนของคุณ
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TMP_DIR = Path("tmp_downloads")
TMP_DIR.mkdir(exist_ok=True)


class InfoRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str
    format_id: str | None = None  # ถ้าไม่ระบุ = เลือกคุณภาพสูงสุดอัตโนมัติ


@app.post("/api/info")
def get_info(req: InfoRequest):
    """ดึงข้อมูลวิดีโอ + รายการความละเอียดที่มีให้เลือก"""
    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=False)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"ดึงข้อมูลไม่ได้: {e}")

    formats = []
    for f in info.get("formats", []):
        # เอาเฉพาะ format ที่มีทั้งวิดีโอ+เสียง หรือเป็นวิดีโอคุณภาพดี
        if f.get("vcodec") != "none":
            formats.append(
                {
                    "format_id": f.get("format_id"),
                    "resolution": f.get("format_note") or f"{f.get('width')}x{f.get('height')}",
                    "ext": f.get("ext"),
                    "filesize": f.get("filesize") or f.get("filesize_approx"),
                }
            )

    return {
        "title": info.get("title") or "x_video",
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "formats": formats,
    }


@app.post("/api/download")
def download(req: DownloadRequest):
    """ดาวน์โหลดวิดีโอจริงลงเซิร์ฟเวอร์ชั่วคราว แล้วส่งไฟล์กลับให้ผู้ใช้"""
    job_id = str(uuid.uuid4())
    out_template = str(TMP_DIR / f"{job_id}.%(ext)s")

    fmt = req.format_id if req.format_id else "bestvideo+bestaudio/best"

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "outtmpl": out_template,
        "format": fmt,
        "merge_output_format": "mp4",
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=True)
            filename = ydl.prepare_filename(info)
            # ถ้ามีการ merge เป็น mp4 นามสกุลไฟล์อาจเปลี่ยน
            if not os.path.exists(filename):
                filename = str(Path(filename).with_suffix(".mp4"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"ดาวน์โหลดไม่สำเร็จ: {e}")

    if not os.path.exists(filename):
        raise HTTPException(status_code=500, detail="ไม่พบไฟล์หลังดาวน์โหลด")

    safe_name = f"x_clip_{job_id[:8]}{Path(filename).suffix}"
    return FileResponse(
        path=filename,
        filename=safe_name,
        media_type="video/mp4",
        background=_cleanup_after_send(filename),
    )


def _cleanup_after_send(path: str):
    from starlette.background import BackgroundTask

    def _remove():
        try:
            os.remove(path)
        except OSError:
            pass

    return BackgroundTask(_remove)


@app.get("/api/health")
def health():
    return {"status": "ok"}
