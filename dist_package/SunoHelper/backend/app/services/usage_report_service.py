"""사용량 리포트 — CC(whick.org)에 기능별 사용량 fire-and-forget 리포트 (2026-09-11)

설계 원칙 (서비스 무영향 최우선):
- fire-and-forget: 백그라운드 태스크로 던지고 결과를 기다리지 않음 (생성 응답 지연 0)
- 실패해도 조용히 스킵 — 로컬 기능·UX에 어떤 영향도 없음
- API 키 보관 시에만 전송 (키 없는 사용자는 리포트 자체 안 함)
- 1회 재시도, 무한 큐 없음 (과금 집계 데이터 — 소량 누락 감수)

서버 측 수신: POST /api/products/verify-key (X-API-Key 헤더)
  { product: "suno", metric: "lyrics|prompt|album_thumbnail|track_thumbnail", quantity: N }
  → cc_core.cc_api_usage 기록 (일별·키별·메트릭별 upsert)
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

from app.services.license_service import _load_saved

logger = logging.getLogger("suno.usage_report")

PRODUCTS_VERIFY_URL = os.environ.get(
    "SUNO_PRODUCTS_VERIFY_URL", "https://whick.org/api/products/verify-key"
)

_REPORT_TIMEOUT = 8.0
_MAX_PENDING_TASKS = 64  # 백그라운드 태스크 유실 방지 상한

# 백그라운드 태스크 보관 컨테이너 (모듈 레벨)
_tasks: set[asyncio.Task] = set()


async def _send_report(metric: str, quantity: int) -> None:
    """실제 전송 — 실패해도 로그만 남기고 끝 (재시도 1회)."""
    saved = _load_saved()
    key = (saved.get("api_key") or "").strip()
    if not key:
        return  # 키 없는 사용자 → 리포트 대상 아님 (조용히 스킵)

    payload = {"product": "suno", "metric": str(metric)[:32], "quantity": max(1, int(quantity))}
    headers = {"X-API-Key": key}

    for attempt in (1, 2):
        try:
            async with httpx.AsyncClient(timeout=_REPORT_TIMEOUT) as client:
                r = await client.post(PRODUCTS_VERIFY_URL, json=payload, headers=headers)
            if r.status_code == 200:
                return  # 성공
            # 401 등 명확한 실패는 재시도 불필요
            if r.status_code in (400, 401, 403):
                logger.info("[usage-report] skipped (%s): %s", r.status_code, r.text[:80])
                return
            logger.warning("[usage-report] http %s (attempt %s)", r.status_code, attempt)
        except Exception as e:  # 네트워크 오류만 재시도
            logger.warning("[usage-report] send failed (attempt %s): %s", attempt, e)
        await asyncio.sleep(1.0 * attempt)
    # 최종 실패 — 그냥 포기 (서비스 영향 없음)


def report_usage(metric: str, quantity: int = 1) -> None:
    """호출 지점에서 비동기 리포트 예약 — 즉시 반환, 응답 대기 없음.

    사용법: 어떤 async 컨텍스트에서든 `report_usage("lyrics", 15)` 한 줄.
    실행 루프가 없는 동기 컨텍스트에서도 안전 (태스크 스케줄 실패 시 무시).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 실행 루프 없음 — 동기 컨텍스트. 백그라운드 스레드로는 과함 → 스킵
        logger.debug("[usage-report] no running loop, skip %s", metric)
        return

    tasks = _tasks
    if len(tasks) >= _MAX_PENDING_TASKS:
        logger.warning("[usage-report] too many pending, drop %s", metric)
        return

    task = loop.create_task(_send_report(metric, quantity))
    tasks.add(task)
    task.add_done_callback(tasks.discard)


def report_usage_sync(metric: str, quantity: int = 1) -> None:
    """동기 컨텍스트용 — 별도 스레드에서 짧게 전송 (블록 최소화, 실패 무시)."""
    try:
        saved = _load_saved()
        key = (saved.get("api_key") or "").strip()
        if not key:
            return
        headers = {"X-API-Key": key}
        payload = {"product": "suno", "metric": str(metric)[:32], "quantity": max(1, int(quantity))}
        with httpx.Client(timeout=_REPORT_TIMEOUT) as client:
            client.post(PRODUCTS_VERIFY_URL, json=payload, headers=headers)
    except Exception as e:
        logger.info("[usage-report-sync] failed: %s", e)


__all__ = ["report_usage", "report_usage_sync"]