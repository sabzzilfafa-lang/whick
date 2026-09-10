"""WHICK 서버 파이프라인과 동일한 기본 설정."""

from copy import deepcopy

DEFAULT_WORK_ROOT = r"D:\YouTubeMusic"

WORKFLOW_STAGES = [
    {
        "id": "music",
        "folder": "01_음악작업",
        "label": "음악 작업",
        "description": "Suno 음원·가사·썸네일·프롬프트 (스튜디오로 보내기)",
    },
    {
        "id": "review",
        "folder": "02_검수대기",
        "label": "검수 대기",
        "description": "영상·자막·리마스터 완료본 — 업로드 전 검수",
    },
]

# 예전 7단계 폴더 → 새 2단계로 옮길 때 사용
LEGACY_STAGE_FOLDERS: dict[str, str] = {
    "01_기획": "music",
    "02_수노원본": "music",
    "03_선곡완료": "music",
    "04_VIP검수대기": "review",
    "05_수정요청": "review",
    "06_유튜브비공개": "review",
    "07_유튜브공개완료": "review",
}

DEFAULT_PIPELINE_CONFIG = {
    "work_root": DEFAULT_WORK_ROOT,
    "audio": {
        "master_chain": (
            "highpass=f=30,"
            "equalizer=f=300:t=q:w=1:g=-2,"
            "equalizer=f=3500:t=q:w=0.5:g=-1,"
            "acompressor=threshold=0.1:ratio=2:attack=20:release=250:makeup=1,"
            "alimiter=limit=0.891,"
            "loudnorm=I=-14:TP=-1:LRA=11"
        ),
        "output_codec": "aac",
        "output_bitrate": "320k",
    },
    "video": {
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "encoder": "auto",
        "crf": 17,
        "preset": "slow",
        "amf_quality": "quality",
        "nvenc_preset": "p7",
        "fade_in_sec": 0.4,
        "image_duration_sec": 8,
    },
    "subtitle": {
        # WHICK run_music_share_album.py ASS SSOT (PlayRes 2560×1440)
        "play_res_x": 2560,
        "play_res_y": 1440,
        # 빈 값 = font_resolver가 환경에 맞는 폰트 선택 (Windows 맑은고딕 / 번들 Noto Sans KR)
        "font_name": "",
        "font_title": 42,
        "font_lyrics": 68,
        "lyrics_outline": 3,
        "margin_lr": 80,
        "margin_v_title": 70,
        "margin_v_lyrics_en": 182,
        "margin_v_lyrics_ko": 100,
        "title_intro_sec": 6.0,
        "track_header_enabled": True,
        "title_color": "#FFFFFF",
    },
    "overlay": {
        "eq_bar_enabled": False,
        "eq_bar_style": "none",
        "eq_bar_x": 460,
        "eq_bar_y": 980,
        "eq_bar_w": 1000,
        "eq_bar_h": 80,
        "eq_bar_color": "#FFFFFF",
        "eq_bar_align": "bottom_center",
    },
}


def get_default_config() -> dict:
    return deepcopy(DEFAULT_PIPELINE_CONFIG)
