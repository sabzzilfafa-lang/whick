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
        "output_bitrate": "192k",
    },
    "video": {
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "encoder": "auto",
        "crf": 23,
        "amf_quality": "balanced",
        "fade_in_sec": 0.4,
        "image_duration_sec": 8,
    },
    "subtitle": {
        "font_name": "Noto Serif CJK KR",
        "track_style": {
            "font_size": 64,
            "alignment": 2,
            "margin_l": 60,
            "margin_r": 60,
            "margin_v": 200,
            "outline": 3,
            "shadow": 1,
        },
        "lyrics_style": {
            "font_size": 54,
            "alignment": 2,
            "margin_l": 60,
            "margin_r": 60,
            "margin_v": 150,
            "outline": 3,
            "shadow": 1,
        },
    },
    "overlay": {
        "eq_bar_enabled": True,
        "eq_bar_x": 460,
        "eq_bar_y": 980,
    },
}


def get_default_config() -> dict:
    return deepcopy(DEFAULT_PIPELINE_CONFIG)
