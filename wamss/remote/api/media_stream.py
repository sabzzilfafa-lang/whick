"""HTML5 <audio> 친화 미디어 응답 — inline + Accept-Ranges + HTTP 206."""
from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import Response, StreamingResponse
from starlette.responses import FileResponse


def _parse_byte_range(range_header: str, size: int) -> tuple[int, int] | None:
    raw = (range_header or "").strip()
    if not raw.lower().startswith("bytes="):
        return None
    spec = raw.split("=", 1)[1].split(",", 1)[0].strip()
    if "-" not in spec:
        return None
    start_s, end_s = spec.split("-", 1)
    try:
        if start_s == "":
            # bytes=-N → last N bytes
            suffix = int(end_s)
            if suffix <= 0:
                return None
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
    except ValueError:
        return None
    if start < 0 or start >= size:
        return None
    end = min(end, size - 1)
    if end < start:
        return None
    return start, end


def media_file_response(request: Request, path: Path, media_type: str) -> Response:
    """
    게스트·미리듣기용 파일 응답.
    - Content-Disposition: inline (attachment 이면 모바일 <audio> 재생 실패)
    - Accept-Ranges + 206 Partial Content (Starlette 0.37 FileResponse는 Range 미지원)
    """
    file_path = Path(path)
    size = file_path.stat().st_size
    base_headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": "inline",
        "Cache-Control": "private, max-age=0, no-cache",
    }

    range_hdr = request.headers.get("range") or request.headers.get("Range")
    if range_hdr:
        parsed = _parse_byte_range(range_hdr, size)
        if parsed is None:
            return Response(
                status_code=416,
                headers={**base_headers, "Content-Range": f"bytes */{size}"},
            )
        start, end = parsed
        length = end - start + 1

        def iter_range():
            with open(file_path, "rb") as fh:
                fh.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = fh.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            iter_range(),
            status_code=206,
            media_type=media_type,
            headers={
                **base_headers,
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Content-Length": str(length),
            },
        )

    # 전체 파일 — filename 미지정으로 attachment 방지
    return FileResponse(
        file_path,
        media_type=media_type,
        headers=base_headers,
    )
