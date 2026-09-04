#!/usr/bin/env python3
"""설치 장애 → 고객용 안내 (코드·해결 방법). 한글 위 · 영어 아래."""
from __future__ import annotations

from i18n_msg import bi

_GUIDES: dict[str, dict] = {
    "network": {
        "error_code": "network",
        "error_title": bi("인터넷 연결 문제", "Internet connection problem"),
        "error_message": bi(
            "미니PC가 인터넷에 연결되지 않았습니다.",
            "The mini PC is not connected to the Internet.",
        ),
        "error_steps": [
            bi(
                "유선 사용 시: 인터넷 선이 미니PC와 공유기에 잘 꽂혀 있는지 확인해 주세요.",
                "Wired: Make sure the LAN cable is firmly plugged into the mini PC and the router.",
            ),
            bi(
                "무선 사용 시: Wi-Fi 이름과 비밀번호를 다시 확인해 주세요.",
                "Wireless: Double-check the Wi-Fi name (SSID) and password.",
            ),
            bi(
                "공유기 전원을 껐다 켠 뒤, USB로 미니PC를 다시 부팅해 주세요.",
                "Power-cycle the router, then reboot the mini PC from the install USB.",
            ),
        ],
    },
    "wifi_auth": {
        "error_code": "wifi_auth",
        "error_title": bi("Wi-Fi 연결 문제", "Wi-Fi connection problem"),
        "error_message": bi(
            "Wi-Fi 이름 또는 비밀번호가 맞지 않습니다.",
            "The Wi-Fi name or password is incorrect.",
        ),
        "error_steps": [
            bi(
                "Wi-Fi 이름(SSID)과 비밀번호를 다시 확인해 주세요.",
                "Recheck the Wi-Fi SSID and password.",
            ),
            bi(
                "대·소문자와 특수문자를 정확히 입력했는지 확인해 주세요.",
                "Check uppercase/lowercase letters and special characters carefully.",
            ),
            bi(
                "공유기에 5GHz 전용 Wi-Fi만 있는 경우, 2.4GHz Wi-Fi를 사용해 주세요.",
                "If your router only has a 5 GHz network, try a 2.4 GHz Wi-Fi network.",
            ),
            bi(
                "다시 입력 후 「Wi-Fi 연결」을 눌러 주세요.",
                "Enter them again, then tap “Connect Wi-Fi”.",
            ),
        ],
    },
    "wifi_failed": {
        "error_code": "wifi_failed",
        "error_title": bi("Wi-Fi 연결 문제", "Wi-Fi connection problem"),
        "error_message": bi(
            "미니PC가 Wi-Fi에 연결되지 않았습니다.",
            "The mini PC could not connect to Wi-Fi.",
        ),
        "error_steps": [
            bi(
                "Wi-Fi 이름·비밀번호를 확인하고 다시 시도해 주세요.",
                "Check the Wi-Fi name and password, then try again.",
            ),
            bi(
                "공유기와 미니PC 사이 거리를 가깝게 해 주세요.",
                "Move the mini PC closer to the router.",
            ),
            bi(
                "유선 인터넷 연결이 가능하면 유선 사용을 권장합니다.",
                "If possible, use a wired LAN connection instead.",
            ),
        ],
    },
    "wifi_provision": {
        "error_code": "wifi_provision",
        "error_title": bi("무선 USB Wi-Fi 설정", "Wireless USB Wi-Fi setup"),
        "error_message": bi(
            "사전 등록 Wi-Fi에 연결하지 못했습니다.",
            "Could not connect to the pre-registered Wi-Fi.",
        ),
        "error_steps": [
            bi(
                "whick.org 다운로드 메뉴에서 Wi-Fi SSID·비밀번호가 맞는지 확인하세요.",
                "On whick.org Downloads, confirm the Wi-Fi SSID and password.",
            ),
            bi(
                "「전용 설치 파일」을 다시 받아 USB Maker로 USB를 다시 만드세요.",
                "Download a new custom install file and rebuild the USB with USB Maker.",
            ),
            bi(
                "계정 고유 접속 주소에서 설치 안내를 따르세요.",
                "Follow the install guide at your account’s personal install URL.",
            ),
        ],
    },
    "phone_wifi": {
        "error_code": "phone_wifi",
        "error_title": bi("스마트폰 Wi-Fi 확인", "Check phone Wi-Fi"),
        "error_message": bi(
            "스마트폰이 미니PC와 같은 Wi-Fi에 연결되어 있지 않습니다.",
            "Your phone is not on the same Wi-Fi as the mini PC.",
        ),
        "error_steps": [
            bi(
                "스마트폰 설정 → Wi-Fi에서 집·매장 Wi-Fi를 선택해 주세요.",
                "On your phone: Settings → Wi-Fi, then select your home/shop Wi-Fi.",
            ),
            bi(
                "미니PC와 같은 공유기 Wi-Fi에 연결되어야 합니다.",
                "It must be the same router Wi-Fi as the mini PC.",
            ),
            bi(
                "연결 후 「설치 계속하기」를 다시 눌러 주세요.",
                "After connecting, tap “Continue install” again.",
            ),
        ],
    },
    "server_unreachable": {
        "error_code": "server_unreachable",
        "error_title": bi("Whick 연결 문제", "Whick connection problem"),
        "error_message": bi(
            "Whick 서버에 연결하지 못했습니다.",
            "Could not connect to the Whick server.",
        ),
        "error_steps": [
            bi(
                "인터넷이 정상인지 확인해 주세요. (다른 기기에서 웹 접속 테스트)",
                "Check that the Internet works (try opening a website on another device).",
            ),
            bi(
                "잠시 후 「다시 시도」를 눌러 주세요.",
                "Wait a moment, then tap “Try again”.",
            ),
            bi(
                "같은 문제가 반복되면 whick.org 고객센터로 문의해 주세요.",
                "If it keeps failing, contact support on whick.org.",
            ),
        ],
    },
    "server_register": {
        "error_code": "server_register",
        "error_title": bi("Whick 등록 문제", "Whick registration problem"),
        "error_message": bi(
            "미니PC를 Whick에 등록하지 못했습니다.",
            "Could not register the mini PC with Whick.",
        ),
        "error_steps": [
            bi(
                "USB를 뽑지 말고 「다시 시도」를 눌러 주세요.",
                "Do not remove the USB — tap “Try again”.",
            ),
            bi(
                "같은 문제가 반복되면 USB를 뽑고 다시 부팅해 주세요.",
                "If it keeps failing, remove the USB and reboot, then try again.",
            ),
            bi(
                "whick.org 고객센터로 문의해 주세요.",
                "Contact support on whick.org.",
            ),
        ],
    },
    "cc_install_failed": {
        "error_code": "cc_install_failed",
        "error_title": bi("원격 설치 중단", "Remote install interrupted"),
        "error_message": bi(
            "Whick 서버에서 원격 설치가 완료되지 않았습니다.",
            "Remote install from the Whick server did not finish.",
        ),
        "error_steps": [
            bi(
                "USB를 뽑고 미니PC를 다시 부팅해 주세요.",
                "Remove the USB and reboot the mini PC.",
            ),
            bi(
                "인터넷 연결(유선 또는 Wi-Fi)을 확인한 뒤 처음부터 다시 진행해 주세요.",
                "Check Internet (wired or Wi-Fi), then start the install from the beginning.",
            ),
            bi(
                "같은 문제가 반복되면 whick.org 고객센터로 문의해 주세요.",
                "If it keeps failing, contact support on whick.org.",
            ),
        ],
    },
    "hw_identity": {
        "error_code": "hw_identity",
        "error_title": bi("장비 정보 확인 중", "Checking device identity"),
        "error_message": bi(
            "미니PC 장비 정보를 읽는 중 문제가 있었습니다. 자동으로 다른 방법을 시도합니다.",
            "There was a problem reading the mini PC hardware ID. Trying another method automatically.",
        ),
        "error_steps": [
            bi("「다시 시도」를 눌러 주세요.", "Tap “Try again”."),
            bi(
                "USB를 뽑지 말고 잠시 후 다시 시도해 주세요.",
                "Do not remove the USB — wait a moment and try again.",
            ),
            bi(
                "같은 문제가 반복되면 USB를 뽑고 다시 부팅해 주세요.",
                "If it keeps failing, remove the USB and reboot.",
            ),
        ],
    },
    "install_complete": {
        "error_code": "install_complete",
        "error_title": bi("설치가 이미 완료됨", "Install already complete"),
        "error_message": bi(
            "이미 Whick 설치·등록이 완료된 계정입니다.",
            "This account already has a completed Whick install/registration.",
        ),
        "error_steps": [
            bi(
                "whick.org 에 로그인해 설치 상태를 확인해 주세요.",
                "Log in to whick.org and check your install status.",
            ),
            bi(
                "새 미니PC 설치가 필요하면 다운로드 메뉴 또는 고객센터로 문의해 주세요.",
                "For a new mini PC, use Downloads or contact support.",
            ),
        ],
    },
    "hw_report_pending": {
        "error_code": "hw_report_pending",
        "error_title": bi("장비 정보 전송 중", "Sending device info"),
        "error_message": bi(
            "Whick 서버 연결은 완료되었습니다. 장비 정보를 보내는 중입니다.",
            "Connected to Whick. Sending device information…",
        ),
        "error_steps": [
            bi(
                "USB를 뽑지 말고 1~2분 기다려 주세요.",
                "Do not remove the USB — wait 1–2 minutes.",
            ),
            bi("「다시 시도」를 눌러도 됩니다.", "You may also tap “Try again”."),
        ],
    },
    "hw_not_authorized": {
        "error_code": "hw_not_authorized",
        "error_title": bi("등록되지 않은 미니PC", "Unauthorized mini PC"),
        "error_message": bi(
            "인증되지 않은 미니PC에서 설치가 제한됩니다. 최초 설치한 미니PC로만 설치할 수 있습니다.",
            "Install is limited to the originally registered mini PC.",
        ),
        "error_steps": [
            bi(
                "처음 설치·등록했던 미니PC에서 USB 설치를 진행해 주세요.",
                "Run USB install on the mini PC that was first registered.",
            ),
            bi(
                "다른 미니PC로 설치하려면 다운로드 메뉴 또는 고객센터로 문의해 주세요.",
                "To install on another mini PC, use Downloads or contact support.",
            ),
            bi(
                "제한 안내 메일이 발송되었는지 받은편지함·스팸함을 확인해 주세요.",
                "Check inbox/spam for a restriction notice email.",
            ),
        ],
    },
    "ap_failed": {
        "error_code": "ap_failed",
        "error_title": bi("스마트폰 연결 문제", "Phone connection problem"),
        "error_message": bi(
            "미니PC와 스마트폰을 같은 네트워크에서 연결할 수 없습니다.",
            "The mini PC and phone could not join the same network.",
        ),
        "error_steps": [
            bi(
                "미니PC에 유선 인터넷(또는 USB-LAN)을 연결해 주세요.",
                "Connect wired Internet (or a USB-LAN adapter) to the mini PC.",
            ),
            bi(
                "무선 USB는 다운로드에서 입력한 Wi-Fi에 자동 연결됩니다.",
                "Wireless USB auto-connects to the Wi-Fi you entered on Downloads.",
            ),
            bi(
                "스마트폰을 같은 집·매장 Wi-Fi에 연결한 뒤, 고유 접속 주소(또는 LAN URL)를 열어 주세요.",
                "Connect your phone to the same Wi-Fi, then open your personal install URL (or LAN URL).",
            ),
            bi("USB를 뽑고 다시 부팅해 주세요.", "Remove the USB and reboot."),
        ],
    },
    "unknown": {
        "error_code": "unknown",
        "error_title": bi("설치 중 문제 발생", "Problem during install"),
        "error_message": bi(
            "예상치 못한 문제가 발생했습니다.",
            "An unexpected problem occurred.",
        ),
        "error_steps": [
            bi(
                "USB를 뽑지 말고 「다시 시도」를 눌러 주세요.",
                "Do not remove the USB — tap “Try again”.",
            ),
            bi(
                "공유기 전원을 재시작한 뒤 USB로 다시 부팅해 주세요.",
                "Power-cycle the router, then reboot from the install USB.",
            ),
            bi(
                "whick.org 고객센터로 문의해 주세요.",
                "Contact support on whick.org.",
            ),
        ],
    },
}


def guide_by_code(code: str) -> dict | None:
    g = _GUIDES.get(code)
    return dict(g) if g else None


def classify_install_error(raw: str = "", data: dict | None = None) -> dict:
    data = data or {}
    raw_l = (raw or "").lower()
    code = str(data.get("error_code") or "")
    profile = str(data.get("net_profile") or "").strip().lower()

    if code in _GUIDES:
        guide = dict(_GUIDES[code])
        if profile == "wireless" and code in ("wifi_auth", "wifi_failed"):
            guide["error_steps"] = list(_GUIDES["wifi_provision"]["error_steps"])
            if code == "wifi_auth":
                guide["error_message"] = bi(
                    "사전 등록 Wi-Fi 이름 또는 비밀번호가 맞지 않습니다.",
                    "The pre-registered Wi-Fi name or password is incorrect.",
                )
        return guide

    api_code = str(data.get("api_error_code") or "")
    if api_code == "INSTALL_ALREADY_COMPLETE" or code == "install_complete":
        return dict(_GUIDES["install_complete"])

    if code == "hw_identity" or "motherboard identity" in raw_l:
        return dict(_GUIDES["hw_identity"])

    if raw == "network" or data.get("error") == "network":
        return dict(_GUIDES["network"])
    if raw_l.startswith("health:") or (not data.get("health_ok") and raw_l.startswith("health")):
        return dict(_GUIDES["server_unreachable"])
    if raw_l.startswith("session:") or (not data.get("session_ok") and raw_l.startswith("session")):
        return dict(_GUIDES["server_register"])
    if raw_l.startswith("link:"):
        return dict(_GUIDES["server_register"])
    if data.get("error_code") == "hw_not_authorized" or code == "hw_not_authorized":
        return dict(_GUIDES["hw_not_authorized"])
    if not data.get("hw_report_ok") and "hw-report" in raw_l:
        if data.get("error_code") == "hw_not_authorized":
            return dict(_GUIDES["hw_not_authorized"])
        return dict(_GUIDES["server_register"])
    if "이름·비밀번호" in raw or "password" in raw_l or "비밀번호" in raw:
        return dict(_GUIDES["wifi_auth"])
    if "wi-fi" in raw_l or "wifi" in raw_l or "와이파이" in raw:
        return dict(_GUIDES["wifi_failed"])
    if "network" in raw_l or "인터넷" in raw or "internet" in raw_l:
        return dict(_GUIDES["network"])
    if raw_l.startswith("health") or "unreachable" in raw_l or "timed out" in raw_l:
        return dict(_GUIDES["server_unreachable"])
    if "ap" in raw_l or "hostapd" in raw_l or "whick-setup" in raw_l:
        return dict(_GUIDES["ap_failed"])

    g = dict(_GUIDES["unknown"])
    if raw and raw not in ("Whick 연결 실패", "Whick connection failed"):
        # 이미 이국어면 유지, 아니면 원문만 (영어 부가 없음)
        g["error_message"] = raw if "\n" in raw else bi(raw, raw)
    return g


def guide_for_wifi_exception(msg: str) -> dict:
    return classify_install_error(msg)
