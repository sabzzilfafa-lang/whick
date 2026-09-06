"""라이선스 API — 상태·활성화·갱신 (설정 페이지에서 사용)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import license_service

router = APIRouter()


class LicenseActivateRequest(BaseModel):
    install_token: str


@router.get("/license/status")
async def api_license_status():
    return license_service.license_status()


@router.post("/license/activate")
async def api_license_activate(req: LicenseActivateRequest):
    try:
        return await license_service.activate(req.install_token)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/license/renew")
async def api_license_renew():
    try:
        return await license_service.renew()
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/license/deactivate")
async def api_license_deactivate():
    license_service.deactivate_local()
    return {"state": "none"}
