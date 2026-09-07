#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build git-home/suno.html — ASCII-only output (Korean via \\u escapes, symbols via entities).

Place on whick-server: /data/whick-ai/2_control_center/git-home/suno.html
"""
import json
from pathlib import Path

OUT = Path(__file__).parent / "suno.html"

CAT = {
    "en": {
        "suno.nav.intro": "Intro", "suno.nav.features": "Features",
        "suno.nav.license": "License", "suno.nav.manual": "Guide",
        "suno.nav.mypage": "Register My PC",
        "suno.hero.title": "Creator automation for AI music",
        "suno.hero.sub": "Suno Helper is a desktop app that runs on your PC — Korean/English lyrics with natural paraphrasing, Suno prompts, instrument settings, subtitle-synced video rendering and private YouTube uploads, all in one place. Your data never leaves your PC.",
        "suno.hero.b1": "Windows 10/11", "suno.hero.b2": "Runs locally", "suno.hero.b3": "1 PC per account",
        "suno.intro.title": "What is Suno Helper?",
        "suno.intro.p1": "Turn playlist ideas into finished music videos: write lyrics in Korean or English and the other language is auto-paraphrased naturally. Suno-ready prompts, instrument settings and final video rendering are all processed offline on your machine.",
        "suno.intro.p2": "Upload to YouTube as unlisted with your channel branding, review, then publish.",
        "suno.features.title": "Key features",
        "suno.f1t": "Bilingual lyrics",
        "suno.f1d": "Write in one language — the other is generated as a natural paraphrase that keeps section tags and line counts.",
        "suno.f2t": "Suno prompt builder",
        "suno.f2d": "Auto-completes a 1,000-character prompt tuned to track length, mood and instruments.",
        "suno.f3t": "Instrument settings",
        "suno.f3d": "Preset-based arrangements with BPM suggestions, adjustable per track.",
        "suno.f4t": "Video production",
        "suno.f4d": "Remastering, lyric subtitle sync, thumbnails and EQ spectrum — encoded automatically (NVIDIA/AMD/Intel).",
        "suno.f5t": "YouTube auto-publish",
        "suno.f5d": "Builds title, description and tags, then uploads as unlisted with channel branding.",
        "suno.f6t": "Your data stays local",
        "suno.f6d": "Audio, video and settings are stored only on your PC. Nothing is sent to our servers.",
        "suno.license.title": "About the license (certificate)",
        "suno.license.lead": "One whick.org account activates one PC.",
        "suno.ls1": "Sign in at whick.org, open My Account and click 'Register My PC'",
        "suno.ls2": "Issue an activation token (starts with sh_)",
        "suno.ls3": "In the app: Settings > License > paste and activate",
        "suno.ls4": "Renews automatically once a month while online",
        "suno.ls5": "Changing PC? Unregister the device on My Account, then register again",
        "suno.license.note": "The license is bound to your device only. Your content is never uploaded or collected.",
        "suno.manual.title": "How to use",
        "suno.manual.req": "Requirements: Windows 10/11, Python 3.11+, ffmpeg (guided during install)",
        "suno.ms1": "Install: unzip and run install.bat — desktop shortcuts are created",
        "suno.ms2": "Start: launch 'Suno Helper' — your browser opens automatically (127.0.0.1:8765)",
        "suno.ms3": "Work: create an album, generate lyrics / prompt / instruments, render video, review",
        "suno.ms4": "Exit: closing the browser tab stops the app automatically (or use the Stop shortcut)",
        "suno.manual.data": "Where data lives: install-folder\\data (settings & DB) + your work root folder (audio & video)",
        "suno.dl.title": "Download & register",
        "suno.dl.note": "Launch is just around the corner. Register your PC now and you are ready the moment it ships.",
        "suno.dl.btn": "Go to My Account",
        "suno.dl.soon": "(The installer will appear here on release day)",
        "suno.open": "Open preview",
    },
    "ko": {
        "suno.nav.intro": "소개", "suno.nav.features": "주요 기능",
        "suno.nav.license": "인증서", "suno.nav.manual": "사용 설명",
        "suno.nav.mypage": "내 PC 등록",
        "suno.hero.title": "음악 제작을 위한 크리에이터 자동화",
        "suno.hero.sub": "Suno Helper는 내 PC에서 실행되는 데스크톱 앱입니다. 한글·영어 가사 작성과 자연스러운 상호 의역, Suno 프롬프트, 악기 세팅, 자막 싱크 영상 렌더링, 유튜브 비공개 업로드까지 한 번에. 데이터는 내 PC에만 저장됩니다.",
        "suno.hero.b1": "Windows 10/11", "suno.hero.b2": "로컬 실행", "suno.hero.b3": "계정당 1PC",
        "suno.intro.title": "Suno Helper란?",
        "suno.intro.p1": "플레이리스트 아이디어를 완성된 음악 영상으로. 한글 또는 영어로 가사를 쓰면 다른 언어는 자동으로 자연스럽게 의역하고, Suno용 프롬프트와 악기 세팅, 최종 영상 렌더링까지 오프라인으로 처리합니다.",
        "suno.intro.p2": "채널 브랜딩을 적용해 유튜브에 비공개로 업로드하고, 검수 후 공개하세요.",
        "suno.features.title": "주요 기능",
        "suno.f1t": "한·영 가사 생성",
        "suno.f1d": "한 언어로 쓰면 다른 언어는 섹션 태그와 줄 수를 지켜 자연스럽게 의역합니다.",
        "suno.f2t": "Suno 프롬프트",
        "suno.f2d": "곡 길이·분위기·악기에 맞춘 1,000자 프롬프트를 자동 완성합니다.",
        "suno.f3t": "악기 세팅",
        "suno.f3d": "프리셋 기반 편성과 BPM 제안, 곡별 미세 조정.",
        "suno.f4t": "영상 제작",
        "suno.f4d": "리마스터·가사 자막 싱크·썸네일·EQ 스펙트럼까지 자동 인코딩 (NVIDIA/AMD/Intel).",
        "suno.f5t": "유튜브 자동 업로드",
        "suno.f5d": "제목·설명·태그를 구성해 채널 브랜딩과 함께 비공개 업로드합니다.",
        "suno.f6t": "내 PC 보관",
        "suno.f6d": "음원·영상·설정은 모두 내 PC에만 저장되며 서버로 전송되지 않습니다.",
        "suno.license.title": "인증서(라이선스) 안내",
        "suno.license.lead": "whick.org 계정 하나로 한 대의 PC에 활성화됩니다.",
        "suno.ls1": "whick.org 로그인 → 마이페이지 \"내 PC 등록\"",
        "suno.ls2": "활성화 토큰 발급 (sh_ 로 시작)",
        "suno.ls3": "앱 실행 → 설정 → 라이선스에 붙여넣고 활성화",
        "suno.ls4": "온라인 상태면 매월 자동 갱신",
        "suno.ls5": "PC 교체 시 마이페이지에서 기기 해지 후 재등록",
        "suno.license.note": "라이선스는 기기에만 묶입니다. 콘텐츠는 업로드·수집되지 않습니다.",
        "suno.manual.title": "사용 설명",
        "suno.manual.req": "요구 사항: Windows 10/11 · Python 3.11+ · ffmpeg (설치 중 안내)",
        "suno.ms1": "설치: 압축 해제 후 install.bat 실행 — 바탕화면 바로가기 생성",
        "suno.ms2": "시작: \"Suno Helper\" 실행 → 브라우저 자동 오픈 (127.0.0.1:8765)",
        "suno.ms3": "작업: 앨범 만들기 → 가사·프롬프트·악기 → 영상 제작 → 검수",
        "suno.ms4": "종료: 브라우저 탭을 닫으면 자동 종료 (또는 Stop 바로가기)",
        "suno.manual.data": "데이터 위치: 설치폴더\\data (설정·DB) + 작업 루트 폴더 (음원·영상)",
        "suno.dl.title": "다운로드 · 내 PC 등록",
        "suno.dl.note": "출시를 앞두고 있습니다. 미리 내 PC 등록을 해두면 출시 즉시 사용할 수 있습니다.",
        "suno.dl.btn": "내 PC 등록 바로가기",
        "suno.dl.soon": "(설치 파일은 출시 후 이곳에 제공됩니다)",
        "suno.open": "미리 보기 열기",
    },
    "ja": {
        "suno.nav.intro": "概要", "suno.nav.features": "主な機能",
        "suno.nav.license": "ライセンス", "suno.nav.manual": "使い方",
        "suno.nav.mypage": "マイPC登録",
        "suno.hero.title": "音楽制作のためのクリエイター自動化",
        "suno.hero.sub": "Suno Helper は PC 上で動くデスクトップアプリ。韓国語・英語の歌詞を自然に相互言い換えし、Suno プロンプト・楽器設定・字幕同期の動画レンダリング・YouTube 限定公開まで一気に。データは PC の外に出ません。",
        "suno.hero.b1": "Windows 10/11", "suno.hero.b2": "ローカル実行", "suno.hero.b3": "1アカウント1台",
        "suno.intro.title": "Suno Helper とは？",
        "suno.intro.p1": "プレイリストのアイデアを完成したミュージックビデオに。韓国語または英語で歌詞を書くと、もう一方の言語は自然に言い換えられ、Suno 用プロンプト・楽器設定・最終レンダリングまでオフラインで処理します。",
        "suno.intro.p2": "チャンネルブランディングを適用して YouTube へ限定公開し、確認後に公開できます。",
        "suno.features.title": "主な機能",
        "suno.f1t": "韓・英歌詞生成",
        "suno.f1d": "片方の言語で書くと、もう片方はセクションと行数を保ったまま自然に言い換えます。",
        "suno.f2t": "Suno プロンプト",
        "suno.f2d": "曲の長さ・雰囲気・楽器に合わせた 1,000 字のプロンプトを自動作成。",
        "suno.f3t": "楽器設定",
        "suno.f3d": "プリセット基準の編成と BPM 提案、曲ごとの調整。",
        "suno.f4t": "動画制作",
        "suno.f4d": "リマスター・歌詞字幕同期・サムネイル・EQ スペクトラムまで自動エンコード。",
        "suno.f5t": "YouTube 自動アップロード",
        "suno.f5d": "タイトル・説明・タグを構成し、ブランディング付きで限定公開します。",
        "suno.f6t": "データは PC 内",
        "suno.f6d": "音源・動画・設定はすべて PC のみに保存。サーバー送信はありません。",
        "suno.license.title": "ライセンス（認証書）について",
        "suno.license.lead": "1 つの whick.org アカウントで 1 台の PC を認証します。",
        "suno.ls1": "whick.org にログイン → マイページ「マイPC登録」",
        "suno.ls2": "アクティベーショントークンを発行（sh_ で開始）",
        "suno.ls3": "アプリの設定 → ライセンスに貼り付けて認証",
        "suno.ls4": "オンラインなら毎月自動更新",
        "suno.ls5": "PC 変更時はマイページでデバイス解除 → 再登録",
        "suno.license.note": "ライセンスはデバイスのみに紐づきます。コンテンツは収集されません。",
        "suno.manual.title": "使い方",
        "suno.manual.req": "要件: Windows 10/11 · Python 3.11+ · ffmpeg（インストール時に案内）",
        "suno.ms1": "インストール: 解凍して install.bat を実行 — デスクトップにショートカット作成",
        "suno.ms2": "起動: 「Suno Helper」でブラウザが自動オープン (127.0.0.1:8765)",
        "suno.ms3": "制作: アルバム作成 → 歌詞・プロンプト・楽器 → 動画 → チェック",
        "suno.ms4": "終了: ブラウザのタブを閉じると自動終了（または Stop ショートカット）",
        "suno.manual.data": "データ場所: インストールフォルダ\\data（設定・DB）＋作業ルート（音源・動画）",
        "suno.dl.title": "ダウンロード · マイPC登録",
        "suno.dl.note": "リリース直前です。先にマイPC登録しておけば、公開即日に使えます。",
        "suno.dl.btn": "マイPC登録へ",
        "suno.dl.soon": "（インストーラーは公開日にここに追加されます）",
        "suno.open": "プレビューを開く",
    },
    "zh": {
        "suno.nav.intro": "简介", "suno.nav.features": "主要功能",
        "suno.nav.license": "许可证", "suno.nav.manual": "使用指南",
        "suno.nav.mypage": "注册我的电脑",
        "suno.hero.title": "面向音乐创作的创作者自动化",
        "suno.hero.sub": "Suno Helper 是在您电脑上运行的桌面应用：韩/英歌词互译、Suno 提示词、乐器配置、字幕同步视频渲染、YouTube 私享上传，一站完成。数据只保存在您的电脑上。",
        "suno.hero.b1": "Windows 10/11", "suno.hero.b2": "本地运行", "suno.hero.b3": "每账户 1 台",
        "suno.intro.title": "Suno Helper 是什么？",
        "suno.intro.p1": "把播放列表的灵感变成完整的音乐视频：先用韩语或英语写词，另一种语言自动自然意译；Suno 提示词、乐器配置到最终渲染全程离线完成。",
        "suno.intro.p2": "自动应用频道品牌，先以私享方式上传 YouTube，审核后再公开。",
        "suno.features.title": "主要功能",
        "suno.f1t": "韩·英歌词生成",
        "suno.f1d": "用一种语言写词，另一种语言会在保持段落与行数的前提下自然意译。",
        "suno.f2t": "Suno 提示词",
        "suno.f2d": "根据曲目长度、情绪与乐器自动生成 1000 字提示词。",
        "suno.f3t": "乐器配置",
        "suno.f3d": "基于预设的编制与 BPM 建议，可按曲目微调。",
        "suno.f4t": "视频制作",
        "suno.f4d": "重灌录、歌词字幕同步、封面、EQ 频谱，自动编码。",
        "suno.f5t": "YouTube 自动上传",
        "suno.f5d": "组好标题、描述与标签，带品牌信息私享上传。",
        "suno.f6t": "数据留在本地",
        "suno.f6d": "音频、视频与设置只存于您的电脑，不上传服务器。",
        "suno.license.title": "关于许可证（证书）",
        "suno.license.lead": "一个 whick.org 账户激活一台电脑。",
        "suno.ls1": "登录 whick.org → 我的账户 →「注册我的电脑」",
        "suno.ls2": "签发激活令牌（以 sh_ 开头）",
        "suno.ls3": "应用内：设置 → 许可证 → 粘贴并激活",
        "suno.ls4": "在线时每月自动续期",
        "suno.ls5": "更换电脑：在“我的账户”解除设备后重新注册",
        "suno.license.note": "许可证仅绑定设备，内容不会被上传或收集。",
        "suno.manual.title": "使用指南",
        "suno.manual.req": "系统要求：Windows 10/11 · Python 3.11+ · ffmpeg（安装时引导）",
        "suno.ms1": "安装：解压后运行 install.bat — 自动创建桌面快捷方式",
        "suno.ms2": "启动：运行「Suno Helper」→ 浏览器自动打开 (127.0.0.1:8765)",
        "suno.ms3": "创作：新建专辑 → 歌词·提示词·乐器 → 视频 → 审核",
        "suno.ms4": "退出：关闭浏览器标签页即自动停止（或使用 Stop 快捷方式）",
        "suno.manual.data": "数据位置：安装目录\\data（设置与数据库）＋工作根目录（音频与视频）",
        "suno.dl.title": "下载 · 注册我的电脑",
        "suno.dl.note": "即将发布。先注册电脑，发布当天即可使用。",
        "suno.dl.btn": "前往我的账户",
        "suno.dl.soon": "（安装包将在发布日提供于此）",
        "suno.open": "打开预览",
    },
    # 나머지 7개 언어: 네비+CTA만 제공, 본문은 영어 기본값으로 폴백
    "es": {"suno.nav.intro": "Introducción", "suno.nav.features": "Funciones", "suno.nav.license": "Licencia", "suno.nav.manual": "Guía", "suno.nav.mypage": "Registrar mi PC", "suno.open": "Abrir vista previa", "suno.dl.btn": "Ir a Mi cuenta"},
    "fr": {"suno.nav.intro": "Présentation", "suno.nav.features": "Fonctionnalités", "suno.nav.license": "Licence", "suno.nav.manual": "Guide", "suno.nav.mypage": "Enregistrer mon PC", "suno.open": "Ouvrir l'aperçu", "suno.dl.btn": "Aller à Mon compte"},
    "de": {"suno.nav.intro": "Überblick", "suno.nav.features": "Funktionen", "suno.nav.license": "Lizenz", "suno.nav.manual": "Anleitung", "suno.nav.mypage": "PC registrieren", "suno.open": "Vorschau öffnen", "suno.dl.btn": "Zu Mein Konto"},
    "pt": {"suno.nav.intro": "Introdução", "suno.nav.features": "Recursos", "suno.nav.license": "Licença", "suno.nav.manual": "Guia", "suno.nav.mypage": "Registrar meu PC", "suno.open": "Abrir pré-visualização", "suno.dl.btn": "Ir para Minha conta"},
    "ru": {"suno.nav.intro": "Обзор", "suno.nav.features": "Возможности", "suno.nav.license": "Лицензия", "suno.nav.manual": "Руководство", "suno.nav.mypage": "Регистрация ПК", "suno.open": "Открыть предпросмотр", "suno.dl.btn": "Перейти в Мой аккаунт"},
    "hi": {"suno.nav.intro": "परिचय", "suno.nav.features": "विशेषताएँ", "suno.nav.license": "लाइसेंस", "suno.nav.manual": "उपयोग गाइड", "suno.nav.mypage": "मेरा PC पंजीकृत करें", "suno.open": "पूर्वावलोकन खोलें", "suno.dl.btn": "मेरे खाते पर जाएँ"},
    "id": {"suno.nav.intro": "Ikhtisar", "suno.nav.features": "Fitur", "suno.nav.license": "Lisensi", "suno.nav.manual": "Panduan", "suno.nav.mypage": "Daftarkan PC Saya", "suno.open": "Buka pratinjau", "suno.dl.btn": "Buka Akun Saya"},
}

EXTRA_JS = json.dumps(CAT, ensure_ascii=True, separators=(",", ":"))

LANG_OPTIONS = [
    ("en", "English"), ("ko", "&#54620;&#44397;&#50612;"), ("ja", "&#26085;&#26412;&#35486;"),
    ("zh", "&#20013;&#25991;"), ("es", "Espa&ntilde;ol"), ("fr", "Fran&ccedil;ais"),
    ("de", "Deutsch"), ("pt", "Portugu&ecirc;s"), ("ru", "&#1056;&#1091;&#1089;&#1089;&#1082;&#1080;&#1081;"),
    ("hi", "&#2361;&#2367;&#2344;&#2381;&#2342;&#2368;"), ("id", "Bahasa Indonesia"),
]
OPT_HTML = "\n            ".join(
    f'<option value="{code}">{label}</option>' for code, label in LANG_OPTIONS
)

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Suno Helper &mdash; Whick</title>
<link rel="stylesheet" href="/css/site.css">
<style>
  body { margin:0; background:var(--bg); color:var(--tx); font-family:inherit; }
  .sh-top { position:sticky; top:0; z-index:50; display:flex; align-items:center; gap:14px;
            padding:10px 18px; background:rgba(13,17,23,.92); backdrop-filter:blur(8px);
            border-bottom:1px solid var(--line); }
  .sh-brand { display:flex; align-items:center; gap:8px; font-size:1.02rem; white-space:nowrap; }
  .sh-brand .sh-by { color:var(--tx2); font-size:.75rem; }
  .sh-nav { display:flex; gap:4px; margin-left:8px; flex:1; flex-wrap:wrap; }
  .sh-nav a { color:var(--tx2); text-decoration:none; font-size:.86rem; padding:6px 10px; border-radius:8px; }
  .sh-nav a:hover { color:var(--tx); background:var(--card); }
  .sh-right { display:flex; align-items:center; gap:10px; }
  .lang-pick { background:var(--card); color:var(--tx); border:1px solid var(--line);
               border-radius:8px; padding:5px 8px; font-size:.8rem; }
  main { max-width:920px; margin:0 auto; padding:0 18px 48px; }
  .sh-hero { padding:44px 0 26px; text-align:center; }
  .sh-hero h1 { font-size:1.7rem; margin:14px 0 10px; line-height:1.3; }
  .sh-hero p { color:var(--tx2); font-size:.95rem; max-width:640px; margin:0 auto; line-height:1.65; }
  .sh-badges { display:flex; gap:8px; justify-content:center; margin-top:18px; flex-wrap:wrap; }
  .sh-badge { border:1px solid var(--line); background:var(--card); color:var(--tx2);
              border-radius:999px; padding:5px 12px; font-size:.78rem; }
  section { padding:30px 0; border-top:1px solid var(--line); }
  section h2 { font-size:1.18rem; margin:0 0 14px; }
  section p.lead { color:var(--tx2); margin:0 0 14px; line-height:1.7; font-size:.92rem; }
  .sh-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:12px; }
  .sh-card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
  .sh-card h3 { margin:0 0 6px; font-size:.95rem; }
  .sh-card p { margin:0; color:var(--tx2); font-size:.84rem; line-height:1.6; }
  ol.sh-steps { margin:0; padding-left:20px; color:var(--tx); font-size:.9rem; line-height:2; }
  .sh-note { margin-top:14px; color:var(--tx2); font-size:.8rem; line-height:1.6; }
  .sh-cta-sec { text-align:center; padding:38px 0 10px; }
  .sh-cta-sec .btn { font-size:.95rem; padding:11px 22px; }
  .sh-foot { border-top:1px solid var(--line); color:var(--tx2); font-size:.78rem;
             text-align:center; padding:18px 0 26px; }
  .sh-foot a { color:var(--tx2); }
  @media (max-width:720px){ .sh-nav { display:none; } }
</style>
</head>
<body>
<header class="sh-top">
  <div class="sh-brand">&#127925; <strong>Suno Helper</strong> <span class="sh-by">by Whick</span></div>
  <nav class="sh-nav">
    <a href="#intro" data-i18n="suno.nav.intro">Intro</a>
    <a href="#features" data-i18n="suno.nav.features">Features</a>
    <a href="#license" data-i18n="suno.nav.license">License</a>
    <a href="#manual" data-i18n="suno.nav.manual">Guide</a>
  </nav>
  <div class="sh-right">
    <select id="langSel" class="lang-pick" aria-label="Language">
            __OPTS__
    </select>
    <a class="btn btn-primary" style="text-decoration:none;font-size:.85rem;padding:8px 14px;"
       href="/account.html#sunoPcBox" target="_blank" rel="noopener"
       data-i18n="suno.nav.mypage">Register My PC</a>
  </div>
</header>

<main>
  <section class="sh-hero" style="border-top:none;">
    <span class="card-badge badge-soon" data-i18n="prod.soon">Coming soon</span>
    <h1 data-i18n="suno.hero.title">Creator automation for AI music</h1>
    <p data-i18n="suno.hero.sub">Suno Helper is a desktop app that runs on your PC.</p>
    <div class="sh-badges">
      <span class="sh-badge" data-i18n="suno.hero.b1">Windows 10/11</span>
      <span class="sh-badge" data-i18n="suno.hero.b2">Runs locally</span>
      <span class="sh-badge" data-i18n="suno.hero.b3">1 PC per account</span>
    </div>
  </section>

  <section id="intro">
    <h2 data-i18n="suno.intro.title">What is Suno Helper?</h2>
    <p class="lead" data-i18n="suno.intro.p1"></p>
    <p class="lead" data-i18n="suno.intro.p2"></p>
  </section>

  <section id="features">
    <h2 data-i18n="suno.features.title">Key features</h2>
    <div class="sh-grid">
      <div class="sh-card"><h3 data-i18n="suno.f1t"></h3><p data-i18n="suno.f1d"></p></div>
      <div class="sh-card"><h3 data-i18n="suno.f2t"></h3><p data-i18n="suno.f2d"></p></div>
      <div class="sh-card"><h3 data-i18n="suno.f3t"></h3><p data-i18n="suno.f3d"></p></div>
      <div class="sh-card"><h3 data-i18n="suno.f4t"></h3><p data-i18n="suno.f4d"></p></div>
      <div class="sh-card"><h3 data-i18n="suno.f5t"></h3><p data-i18n="suno.f5d"></p></div>
      <div class="sh-card"><h3 data-i18n="suno.f6t"></h3><p data-i18n="suno.f6d"></p></div>
    </div>
  </section>

  <section id="license">
    <h2 data-i18n="suno.license.title">About the license</h2>
    <p class="lead" data-i18n="suno.license.lead"></p>
    <ol class="sh-steps">
      <li data-i18n="suno.ls1"></li>
      <li data-i18n="suno.ls2"></li>
      <li data-i18n="suno.ls3"></li>
      <li data-i18n="suno.ls4"></li>
      <li data-i18n="suno.ls5"></li>
    </ol>
    <p class="sh-note" data-i18n="suno.license.note"></p>
  </section>

  <section id="manual">
    <h2 data-i18n="suno.manual.title">How to use</h2>
    <p class="lead" data-i18n="suno.manual.req"></p>
    <ol class="sh-steps">
      <li data-i18n="suno.ms1"></li>
      <li data-i18n="suno.ms2"></li>
      <li data-i18n="suno.ms3"></li>
      <li data-i18n="suno.ms4"></li>
    </ol>
    <p class="sh-note" data-i18n="suno.manual.data"></p>
  </section>

  <section id="download" class="sh-cta-sec" style="border-top:1px solid var(--line);">
    <h2 data-i18n="suno.dl.title">Download &amp; register</h2>
    <p class="lead" data-i18n="suno.dl.note"></p>
    <a class="btn btn-primary" style="text-decoration:none;"
       href="/account.html#sunoPcBox" target="_blank" rel="noopener"
       data-i18n="suno.dl.btn">Go to My Account</a>
    <p class="sh-note" data-i18n="suno.dl.soon"></p>
  </section>
</main>

<footer class="sh-foot">
  &copy; 2026 <a href="/" target="_blank" rel="noopener">whick.org</a> &mdash; Suno Helper runs and stores everything on your PC.
</footer>

<script src="/js/i18n-cats.js?v=20260902-1016"></script>
<script>
  /* merge AFTER cats (cats overwrites WAMSS_I18N), BEFORE i18n.js init */
  window.SUNO_I18N_EXTRA = __EXTRA__;
  window.WAMSS_I18N = window.WAMSS_I18N || {};
  for (var lang in window.SUNO_I18N_EXTRA) {
    if (!window.WAMSS_I18N[lang]) window.WAMSS_I18N[lang] = {};
    for (var k in window.SUNO_I18N_EXTRA[lang]) window.WAMSS_I18N[lang][k] = window.SUNO_I18N_EXTRA[lang][k];
  }
</script>
<script src="/js/i18n.js?v=20260902-1016"></script>
</body>
</html>
"""

html = HTML.replace("__OPTS__", OPT_HTML).replace("__EXTRA__", EXTRA_JS)
# ASCII 안전성 검증 — 전송·인코딩 문제 원천 차단
html.encode("ascii")
OUT.write_text(html, encoding="ascii", newline="\n")
print(f"OK {OUT.name}: {len(html)} bytes, ascii-only")
