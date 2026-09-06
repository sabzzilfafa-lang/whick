"""곡 가사(한글/영어) 헬퍼."""

from app.models import Song


def lyrics_ko_text(song: Song) -> str | None:
    return song.lyrics_ko or song.lyrics


def lyrics_en_text(song: Song) -> str | None:
    return song.lyrics_en


def primary_lyrics(song: Song) -> str | None:
    return lyrics_ko_text(song) or lyrics_en_text(song)


def set_lyrics(song: Song, content: str, language: str = "ko") -> None:
    if language == "en":
        song.lyrics_en = content
    else:
        song.lyrics_ko = content
        song.lyrics = content
