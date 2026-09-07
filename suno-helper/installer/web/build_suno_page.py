#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build git-home/suno.html (shell: fixed header + iframe) and git-home/suno-app.html
(dashboard: install/run + docs). ASCII-only output — Korean via \\u escapes in JS catalog.

Place on whick-server: /data/whick-ai/2_control_center/git-home/
"""
import json
from pathlib import Path

OUT_DIR = Path(__file__).parent

CAT = {
    "en": {
        "suno.nav.dash": "Dashboard", "suno.nav.intro": "Intro", "suno.nav.features": "Features",
        "suno.nav.license": "License", "suno.nav.manual": "Guide",
        "suno.nav.mypage": "Register My PC",
        "suno.hero.title": "Creator automation for AI music",
        "suno.hero.sub": "Suno Helper is a desktop app that runs on your PC \u2014 Korean/English lyrics with natural paraphrasing, Suno prompts, instrument settings, subtitle-synced video rendering and private YouTube uploads, all in one place. Your data never leaves your PC.",
        "suno.hero.b1": "Windows 10/11", "suno.hero.b2": "Runs locally", "suno.hero.b3": "1 PC per account",
        "suno.dash.title": "Get started now",
        "suno.dash.checking": "Checking your PC...",
        "suno.dash.notInstalled": "Not installed on this PC",
        "suno.dash.legacy": "An older install was detected \u2014 run Install again",
        "suno.dash.installed": "Installed", "suno.dash.ready": "ready to run",
        "suno.dash.btn.signin": "Sign in to install",
        "suno.dash.btn.install": "Install",
        "suno.dash.btn.run": "Run",
        "suno.dash.starting": "Starting the app... (up to 45 s)",
        "suno.dash.startFail": "Could not start. Please run Install again, then retry.",
        "suno.dash.step1": "Download Setup.bat \u2192 double-click it in your Downloads folder",
        "suno.dash.step2": "The rest is automatic \u2014 when you come back here, the button turns into Run",
        "suno.dash.note": "Browser policy allows one double-click \u2014 everything after that (Python setup, app files, launcher registration) runs automatically.",
        "suno.intro.title": "What is Suno Helper?",
        "suno.intro.p1": "Turn playlist ideas into finished music videos: write lyrics in Korean or English and the other language is auto-paraphrased naturally. Suno-ready prompts, instrument settings and final video rendering are all processed offline on your machine.",
        "suno.intro.p2": "Upload to YouTube as unlisted with your channel branding, review, then publish.",
        "suno.features.title": "Key features",
        "suno.f1t": "Bilingual lyrics",
        "suno.f1d": "Write in one language \u2014 the other is generated as a natural paraphrase that keeps section tags and line counts.",
        "suno.f2t": "Suno prompt builder",
        "suno.f2d": "Auto-completes a 1,000-character prompt tuned to track length, mood and instruments.",
        "suno.f3t": "Instrument settings",
        "suno.f3d": "Preset-based arrangements with BPM suggestions, adjustable per track.",
        "suno.f4t": "Video production",
        "suno.f4d": "Remastering, lyric subtitle sync, thumbnails and EQ spectrum \u2014 encoded automatically (NVIDIA/AMD/Intel).",
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
        "suno.ms1": "Install: click the Install button above \u2192 double-click the downloaded Setup.bat (the rest is automatic)",
        "suno.ms2": "Run: click the Run button on this page \u2014 the app opens in a new tab (127.0.0.1:8765)",
        "suno.ms3": "Work: create an album, generate lyrics / prompt / instruments, render video, review",
        "suno.ms4": "Exit: closing the app tab stops the app automatically",
        "suno.manual.data": "Where data lives: install-folder\\data (settings & DB) + your work root folder (audio & video)",
        "suno.dl.title": "Download & register",
        "suno.dl.note": "Register your PC first \u2014 issue your activation token on My Account before first launch.",
        "suno.dl.btn": "Go to My Account",
        "suno.dl.soon": "(The installer will appear here on release day)",
    },
    "ko": {
        "suno.nav.dash": "대시보드", "suno.nav.intro": "소개", "suno.nav.features": "주요 기능",
        "suno.nav.license": "인증서", "suno.nav.manual": "사용 설명",
        "suno.nav.mypage": "내 PC 등록",
        "suno.hero.title": "음악 제작을 위한 크리에이터 자동화",
        "suno.hero.sub": "Suno Helper는 내 PC에서 실행되는 데스크톱 앱입니다. 한글·영어 가사 작성과 자연스러운 상호 의역, Suno 프롬프트, 악기 세팅, 자막 싱크 영상 렌더링, 유튜브 비공개 업로드까지 한 번에. 데이터는 내 PC에만 저장됩니다.",
        "suno.hero.b1": "Windows 10/11", "suno.hero.b2": "로컬 실행", "suno.hero.b3": "계정당 1PC",
        "suno.dash.title": "지금 바로 시작",
        "suno.dash.checking": "PC 상태 확인 중...",
        "suno.dash.notInstalled": "이 PC에 아직 설치되어 있지 않습니다",
        "suno.dash.legacy": "이전 버전이 감지되었습니다 — 설치를 다시 실행해 주세요",
        "suno.dash.installed": "설치됨", "suno.dash.ready": "실행 준비 완료",
        "suno.dash.btn.signin": "로그인 후 설치",
        "suno.dash.btn.install": "설치",
        "suno.dash.btn.run": "실행",
        "suno.dash.starting": "앱 기동 중... (최대 45초)",
        "suno.dash.startFail": "기동에 실패했습니다. 설치를 다시 실행한 후 재시도해 주세요.",
        "suno.dash.step1": "Setup.bat 다운로드 → 다운로드 폴더에서 더블클릭",
        "suno.dash.step2": "나머지는 전부 자동 — 이 페이지로 돌아오면 버튼이 [실행]으로 바뀝니다",
        "suno.dash.note": "브라우저 정책상 더블클릭 한 번만 가능합니다. 그 이후(파이썬 설치·앱 파일·실행 등록)는 전부 자동으로 진행됩니다.",
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
        "suno.ms1": "설치: 위의 [설치] 버튼 클릭 → 다운로드된 Setup.bat 더블클릭 (나머지는 자동)",
        "suno.ms2": "실행: 이 페이지의 [실행] 버튼 → 앱이 새 탭에서 열립니다 (127.0.0.1:8765)",
        "suno.ms3": "작업: 앨범 만들기 → 가사·프롬프트·악기 → 영상 제작 → 검수",
        "suno.ms4": "종료: 앱 탭을 닫으면 자동 종료",
        "suno.manual.data": "데이터 위치: 설치폴더\\data (설정·DB) + 작업 루트 폴더 (음원·영상)",
        "suno.dl.title": "다운로드 · 내 PC 등록",
        "suno.dl.note": "먼저 내 PC 등록을 하세요 — 첫 실행 전에 마이페이지에서 활성화 토큰을 발급받습니다.",
        "suno.dl.btn": "내 PC 등록 바로가기",
        "suno.dl.soon": "(설치 파일은 출시 후 이곳에 제공됩니다)",
    },
    "ja": {
        "suno.nav.dash": "ダッシュボード", "suno.nav.intro": "概要", "suno.nav.features": "主な機能",
        "suno.nav.license": "ライセンス", "suno.nav.manual": "使い方",
        "suno.nav.mypage": "マイPC登録",
        "suno.hero.title": "音楽制作のためのクリエイター自動化",
        "suno.hero.sub": "Suno Helper は PC 上で動くデスクトップアプリ。韓国語・英語の歌詞を自然に相互言い換えし、Suno プロンプト・楽器設定・字幕同期の動画レンダリング・YouTube 限定公開まで一気に。データは PC の外に出ません。",
        "suno.hero.b1": "Windows 10/11", "suno.hero.b2": "ローカル実行", "suno.hero.b3": "1アカウント1台",
        "suno.dash.title": "今すぐ始める",
        "suno.dash.checking": "PC の状態を確認中...",
        "suno.dash.notInstalled": "この PC には未インストールです",
        "suno.dash.legacy": "旧バージョンを検出 — インストールを再実行してください",
        "suno.dash.installed": "インストール済み", "suno.dash.ready": "実行準備完了",
        "suno.dash.btn.signin": "ログインしてインストール",
        "suno.dash.btn.install": "インストール",
        "suno.dash.btn.run": "実行",
        "suno.dash.starting": "アプリ起動中... (最大 45 秒)",
        "suno.dash.startFail": "起動に失敗しました。インストールを再実行してお試しください。",
        "suno.dash.step1": "Setup.bat をダウンロード → ダウンロードフォルダでダブルクリック",
        "suno.dash.step2": "残りはすべて自動 — このページに戻るとボタンが [実行] に変わります",
        "suno.dash.note": "ブラウザの仕様上、ダブルクリックは 1 回のみ。以降（Python セットアップ・アプリファイル・起動登録）はすべて自動です。",
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
        "suno.ms1": "インストール: 上の [インストール] をクリック → ダウンロードした Setup.bat をダブルクリック（残りは自動）",
        "suno.ms2": "実行: このページの [実行] ボタン → 新しいタブでアプリが開きます (127.0.0.1:8765)",
        "suno.ms3": "制作: アルバム作成 → 歌詞・プロンプト・楽器 → 動画 → チェック",
        "suno.ms4": "終了: アプリのタブを閉じると自動終了",
        "suno.manual.data": "データ場所: インストールフォルダ\\data（設定・DB）＋作業ルート（音源・動画）",
        "suno.dl.title": "ダウンロード · マイPC登録",
        "suno.dl.note": "先にマイPC登録を — 初回起動前にマイページでアクティベーショントークンを発行します。",
        "suno.dl.btn": "マイPC登録へ",
        "suno.dl.soon": "（インストーラーは公開日にここに追加されます）",
    },
    "zh": {
        "suno.nav.dash": "控制台", "suno.nav.intro": "简介", "suno.nav.features": "主要功能",
        "suno.nav.license": "许可证", "suno.nav.manual": "使用指南",
        "suno.nav.mypage": "注册我的电脑",
        "suno.hero.title": "面向音乐创作的创作者自动化",
        "suno.hero.sub": "Suno Helper 是在您电脑上运行的桌面应用：韩/英歌词互译、Suno 提示词、乐器配置、字幕同步视频渲染、YouTube 私享上传，一站完成。数据只保存在您的电脑上。",
        "suno.hero.b1": "Windows 10/11", "suno.hero.b2": "本地运行", "suno.hero.b3": "每账户 1 台",
        "suno.dash.title": "立即开始",
        "suno.dash.checking": "正在检查您的电脑...",
        "suno.dash.notInstalled": "此电脑尚未安装",
        "suno.dash.legacy": "检测到旧版本 — 请重新运行安装",
        "suno.dash.installed": "已安装", "suno.dash.ready": "可以运行",
        "suno.dash.btn.signin": "登录后安装",
        "suno.dash.btn.install": "安装",
        "suno.dash.btn.run": "运行",
        "suno.dash.starting": "应用启动中...（最多 45 秒）",
        "suno.dash.startFail": "启动失败。请重新运行安装后再试。",
        "suno.dash.step1": "下载 Setup.bat → 在下载文件夹中双击",
        "suno.dash.step2": "其余全自动 — 回到本页后按钮会变为 [运行]",
        "suno.dash.note": "浏览器策略只允许一次双击。之后（Python 环境、应用文件、启动注册）都会自动完成。",
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
        "suno.ls5": "更换电脑：在\u201c我的账户\u201d解除设备后重新注册",
        "suno.license.note": "许可证仅绑定设备，内容不会被上传或收集。",
        "suno.manual.title": "使用指南",
        "suno.manual.req": "系统要求：Windows 10/11 · Python 3.11+ · ffmpeg（安装时引导）",
        "suno.ms1": "安装：点击上方 [安装] → 双击下载的 Setup.bat（其余自动）",
        "suno.ms2": "运行：点击本页 [运行] 按钮 → 应用在新标签页打开 (127.0.0.1:8765)",
        "suno.ms3": "创作：新建专辑 → 歌词·提示词·乐器 → 视频 → 审核",
        "suno.ms4": "退出：关闭应用标签页即自动停止",
        "suno.manual.data": "数据位置：安装目录\\data（设置与数据库）＋工作根目录（音频与视频）",
        "suno.dl.title": "下载 · 注册我的电脑",
        "suno.dl.note": "请先注册电脑 — 首次启动前在\u201c我的账户\u201d签发激活令牌。",
        "suno.dl.btn": "前往我的账户",
        "suno.dl.soon": "（安装包将在发布日提供于此）",
    },
    # 부분 번역 — 본문은 영어 폴백
    "es": {"suno.nav.dash": "Panel", "suno.nav.intro": "Introducción", "suno.nav.features": "Funciones", "suno.nav.license": "Licencia", "suno.nav.manual": "Guía", "suno.nav.mypage": "Registrar mi PC", "suno.dash.btn.signin": "Inicia sesión para instalar", "suno.dash.btn.install": "Instalar", "suno.dash.btn.run": "Ejecutar", "suno.dl.btn": "Ir a Mi cuenta"},
    "fr": {"suno.nav.dash": "Tableau de bord", "suno.nav.intro": "Présentation", "suno.nav.features": "Fonctionnalités", "suno.nav.license": "Licence", "suno.nav.manual": "Guide", "suno.nav.mypage": "Enregistrer mon PC", "suno.dash.btn.signin": "Connectez-vous pour installer", "suno.dash.btn.install": "Installer", "suno.dash.btn.run": "Exécuter", "suno.dl.btn": "Aller à Mon compte"},
    "de": {"suno.nav.dash": "Übersicht", "suno.nav.intro": "Überblick", "suno.nav.features": "Funktionen", "suno.nav.license": "Lizenz", "suno.nav.manual": "Anleitung", "suno.nav.mypage": "PC registrieren", "suno.dash.btn.signin": "Zum Installieren anmelden", "suno.dash.btn.install": "Installieren", "suno.dash.btn.run": "Ausführen", "suno.dl.btn": "Zu Mein Konto"},
    "pt": {"suno.nav.dash": "Painel", "suno.nav.intro": "Introdução", "suno.nav.features": "Recursos", "suno.nav.license": "Licença", "suno.nav.manual": "Guia", "suno.nav.mypage": "Registrar meu PC", "suno.dash.btn.signin": "Entre para instalar", "suno.dash.btn.install": "Instalar", "suno.dash.btn.run": "Executar", "suno.dl.btn": "Ir para Minha conta"},
    "ru": {"suno.nav.dash": "Панель", "suno.nav.intro": "Обзор", "suno.nav.features": "Возможности", "suno.nav.license": "Лицензия", "suno.nav.manual": "Руководство", "suno.nav.mypage": "Регистрация ПК", "suno.dash.btn.signin": "Войдите, чтобы установить", "suno.dash.btn.install": "Установить", "suno.dash.btn.run": "Запустить", "suno.dl.btn": "Перейти в Мой аккаунт"},
    "hi": {"suno.nav.dash": "डैशबोर्ड", "suno.nav.intro": "परिचय", "suno.nav.features": "विशेषताएँ", "suno.nav.license": "लाइसेंस", "suno.nav.manual": "उपयोग गाइड", "suno.nav.mypage": "मेरा PC पंजीकृत करें", "suno.dash.btn.signin": "इंस्टॉल के लिए साइन इन करें", "suno.dash.btn.install": "इंस्टॉल करें", "suno.dash.btn.run": "चलाएँ", "suno.dl.btn": "मेरे खाते पर जाएँ"},
    "id": {"suno.nav.dash": "Dasbor", "suno.nav.intro": "Ikhtisar", "suno.nav.features": "Fitur", "suno.nav.license": "Lisensi", "suno.nav.manual": "Panduan", "suno.nav.mypage": "Daftarkan PC Saya", "suno.dash.btn.signin": "Masuk untuk memasang", "suno.dash.btn.install": "Pasang", "suno.dash.btn.run": "Jalankan", "suno.dl.btn": "Buka Akun Saya"},
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

I18N_MERGE = """<script src="/js/i18n-cats.js?v=20260902-1016"></script>
<script>
  /* merge AFTER cats (cats overwrites WAMSS_I18N), BEFORE i18n.js init */
  window.SUNO_I18N_EXTRA = __EXTRA__;
  window.WAMSS_I18N = window.WAMSS_I18N || {};
  for (var lang in window.SUNO_I18N_EXTRA) {
    if (!window.WAMSS_I18N[lang]) window.WAMSS_I18N[lang] = {};
    for (var k in window.SUNO_I18N_EXTRA[lang]) window.WAMSS_I18N[lang][k] = window.SUNO_I18N_EXTRA[lang][k];
  }
</script>"""

# ---------------------------------------------------------------------------
# suno.html — shell: fixed header + iframe
# ---------------------------------------------------------------------------
SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Suno Helper &mdash; Whick</title>
<link rel="icon" href="/img/favicon.png">
<link rel="stylesheet" href="/css/site.css?v=20260907-1">
<style>
  html, body { height:100%; }
  body { margin:0; display:flex; flex-direction:column; background:var(--bg); color:var(--tx); }
  .sh-top { flex:0 0 auto; display:flex; align-items:center; gap:14px; padding:10px 18px;
            background:rgba(13,17,23,.96); border-bottom:1px solid var(--line);
            position:sticky; top:0; z-index:50; }
  .sh-brand { display:flex; align-items:center; gap:8px; font-size:1.02rem; white-space:nowrap;
              color:var(--tx); text-decoration:none; }
  .sh-brand .sh-by { color:var(--tx2); font-size:.75rem; }
  .sh-nav { display:flex; gap:4px; margin-left:8px; flex:1; flex-wrap:wrap; }
  .sh-nav a { color:var(--tx2); text-decoration:none; font-size:.86rem; padding:6px 10px; border-radius:8px; }
  .sh-nav a:hover { color:var(--tx); background:var(--card); }
  .sh-right { display:flex; align-items:center; gap:10px; }
  .sh-right a.sh-auth { color:var(--acc); font-size:.85rem; font-weight:600; text-decoration:none; }
  .lang-pick { background:var(--card); color:var(--tx); border:1px solid var(--line);
               border-radius:8px; padding:5px 8px; font-size:.8rem; }
  #sunoFrame { flex:1 1 auto; width:100%; border:0; display:block; background:var(--bg); }
  @media (max-width:720px){ .sh-nav { display:none; } }
</style>
</head>
<body>
<header class="sh-top">
  <a class="sh-brand" href="/" target="_top">&#127925; <strong>Suno Helper</strong> <span class="sh-by">by Whick</span></a>
  <nav class="sh-nav">
    <a href="#" data-scroll="dashboard" data-i18n="suno.nav.dash">Dashboard</a>
    <a href="#" data-scroll="intro" data-i18n="suno.nav.intro">Intro</a>
    <a href="#" data-scroll="features" data-i18n="suno.nav.features">Features</a>
    <a href="#" data-scroll="license" data-i18n="suno.nav.license">License</a>
    <a href="#" data-scroll="manual" data-i18n="suno.nav.manual">Guide</a>
    <a href="/#products" target="_top" data-i18n="nav.products">Products</a>
    <a href="https://community.whick.org/" target="_blank" rel="noopener" data-i18n="nav.community">Community &rarr;</a>
  </nav>
  <div class="sh-right">
    <select id="langSel" class="lang-pick" aria-label="Language">
            __OPTS__
    </select>
    <a id="shAuth" class="sh-auth" href="/auth.html" data-i18n="nav.signin">Sign in</a>
    <a class="btn btn-primary" style="text-decoration:none;font-size:.85rem;padding:8px 14px;"
       href="/account.html#sunoPcBox" target="_blank" rel="noopener"
       data-i18n="suno.nav.mypage">Register My PC</a>
  </div>
</header>
<iframe id="sunoFrame" src="/suno-app.html" title="Suno Helper"></iframe>

__I18N_MERGE__
<script src="/js/i18n.js?v=20260902-1016"></script>
<script>
(function () {
  'use strict';
  var frame = document.getElementById('sunoFrame');
  // nav anchors scroll inside the iframe
  document.querySelectorAll('[data-scroll]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      e.preventDefault();
      try { frame.contentWindow.location.hash = '#' + a.getAttribute('data-scroll'); } catch (err) {}
    });
  });
  // sign in / my account
  var tok = null;
  try { tok = localStorage.getItem('wamss_git_token'); } catch (e) {}
  if (tok) {
    var a = document.getElementById('shAuth');
    a.setAttribute('href', '/account.html');
    a.setAttribute('data-i18n', 'acc.title');
    a.textContent = 'My Account';
  }
  // language change -> i18n.js stores it, then reload iframe to retranslate body
  var sel = document.getElementById('langSel');
  sel.addEventListener('change', function () {
    setTimeout(function () {
      try { frame.contentWindow.location.reload(); } catch (e) { frame.src = frame.src; }
    }, 60);
  });
})();
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# suno-app.html — dashboard + docs (iframe body)
# ---------------------------------------------------------------------------
APP = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Suno Helper</title>
<link rel="stylesheet" href="/css/site.css?v=20260907-1">
<style>
  body { margin:0; background:var(--bg); color:var(--tx); }
  main { max-width:920px; margin:0 auto; padding:0 18px 48px; }
  .sh-hero { padding:38px 0 24px; text-align:center; }
  .sh-hero h1 { font-size:1.6rem; margin:14px 0 10px; line-height:1.3; }
  .sh-hero p { color:var(--tx2); font-size:.95rem; max-width:640px; margin:0 auto; line-height:1.65; }
  .sh-badges { display:flex; gap:8px; justify-content:center; margin-top:16px; flex-wrap:wrap; }
  .sh-badge { border:1px solid var(--line); background:var(--card); color:var(--tx2);
              border-radius:999px; padding:5px 12px; font-size:.78rem; }
  .sh-dash { border:1px solid var(--line); background:var(--card); border-radius:14px;
             padding:22px 20px; text-align:center; margin:6px 0 10px; }
  .sh-dash h2 { margin:0 0 8px; font-size:1.2rem; }
  .sh-dash-status { color:var(--tx2); font-size:.88rem; margin-bottom:14px; min-height:1.2em; }
  .sh-dash-status.ok { color:#4ade80; }
  .sh-dash-status.err { color:#f87171; }
  .sh-dash-btn { font-size:1rem; padding:11px 26px; text-decoration:none; display:inline-block; cursor:pointer; }
  .sh-dash-btn.run { background:#16a34a; border-color:#16a34a; }
  .sh-dash-steps { margin-top:14px; text-align:left; display:inline-block; color:var(--tx2); font-size:.86rem; line-height:1.9; }
  .sh-note { margin-top:12px; color:var(--tx2); font-size:.78rem; line-height:1.6; }
  section { padding:30px 0; border-top:1px solid var(--line); }
  section h2 { font-size:1.18rem; margin:0 0 14px; }
  section p.lead { color:var(--tx2); margin:0 0 14px; line-height:1.7; font-size:.92rem; }
  .sh-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:12px; }
  .sh-card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
  .sh-card h3 { margin:0 0 6px; font-size:.95rem; }
  .sh-card p { margin:0; color:var(--tx2); font-size:.84rem; line-height:1.6; }
  ol.sh-steps { margin:0; padding-left:20px; color:var(--tx); font-size:.9rem; line-height:2; }
  .sh-cta-sec { text-align:center; padding:38px 0 10px; }
  .sh-cta-sec .btn { font-size:.95rem; padding:11px 22px; }
</style>
</head>
<body>
<main>
  <section class="sh-hero" style="border-top:none;">
    <h1 data-i18n="suno.hero.title">Creator automation for AI music</h1>
    <p data-i18n="suno.hero.sub"></p>
    <div class="sh-badges">
      <span class="sh-badge" data-i18n="suno.hero.b1"></span>
      <span class="sh-badge" data-i18n="suno.hero.b2"></span>
      <span class="sh-badge" data-i18n="suno.hero.b3"></span>
    </div>
  </section>

  <section id="dashboard" class="sh-dash" style="border-top:1px solid var(--line);">
    <h2 data-i18n="suno.dash.title">Get started now</h2>
    <div id="dashStatus" class="sh-dash-status" data-i18n="suno.dash.checking">Checking your PC...</div>
    <a id="dashBtn" class="btn btn-primary sh-dash-btn" href="#" data-i18n="suno.dash.btn.signin">Sign in to install</a>
    <div id="dashSteps" class="sh-dash-steps" hidden>
      <ol>
        <li data-i18n="suno.dash.step1"></li>
        <li data-i18n="suno.dash.step2"></li>
      </ol>
    </div>
    <p class="sh-note" data-i18n="suno.dash.note"></p>
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

  <section id="download" class="sh-cta-sec">
    <h2 data-i18n="suno.dl.title">Download &amp; register</h2>
    <p class="lead" data-i18n="suno.dl.note"></p>
    <a class="btn btn-primary" style="text-decoration:none;"
       href="/account.html#sunoPcBox" target="_blank" rel="noopener"
       data-i18n="suno.dl.btn">Go to My Account</a>
    <p class="sh-note" data-i18n="suno.dl.soon"></p>
  </section>
</main>

__I18N_MERGE__
<script src="/js/i18n.js?v=20260902-1016"></script>
<script>
(function () {
  'use strict';
  var LOCAL = 'http://127.0.0.1:8765';
  var SETUP_URL = '/dl/suno-helper/Setup.bat';
  var AUTH_URL = '/auth.html';

  function t(key) {
    var lang = document.documentElement.lang || 'en';
    var cats = window.WAMSS_I18N || {};
    var v = (cats[lang] || {})[key];
    if (typeof v !== 'string') v = (cats.en || {})[key];
    return typeof v === 'string' ? v : key;
  }
  function getToken() {
    try { return localStorage.getItem('wamss_git_token') || ''; } catch (e) { return ''; }
  }
  function fetchLocal(path, ms) {
    return new Promise(function (resolve) {
      var ctrl = ('AbortController' in window) ? new AbortController() : null;
      var done = false;
      var timer = setTimeout(function () {
        if (done) return; done = true;
        if (ctrl) ctrl.abort();
        resolve(null);
      }, ms || 2500);
      fetch(LOCAL + path, { cache: 'no-store', signal: ctrl ? ctrl.signal : undefined })
        .then(function (r) {
          if (done) return; done = true; clearTimeout(timer);
          resolve(r.ok ? r.json() : null);
        })
        .catch(function () {
          if (done) return; done = true; clearTimeout(timer);
          resolve(null);
        });
    });
  }
  function setStatus(msg, cls) {
    var el = document.getElementById('dashStatus');
    el.textContent = msg;
    el.className = 'sh-dash-status' + (cls ? ' ' + cls : '');
  }
  function setBtn(label, onclick) {
    var b = document.getElementById('dashBtn');
    b.textContent = label;
    b.onclick = onclick || null;
    if (onclick) { b.removeAttribute('href'); }
    else { b.setAttribute('href', '#'); }
    return b;
  }

  function install() {
    document.getElementById('dashSteps').hidden = false;
    // trigger browser download of Setup.bat
    var a = document.createElement('a');
    a.href = SETUP_URL;
    a.download = '';
    document.body.appendChild(a); a.click(); a.remove();
    // poll: after user runs Setup.bat the flag flips -> auto-switch to Run
    var tries = 0;
    var timer = setInterval(function () {
      tries++;
      fetchLocal('/api/local/status', 2500).then(function (d) {
        if (d && d.web_launch) { clearInterval(timer); render(); }
      });
      if (tries > 40) clearInterval(timer);
    }, 3000);
  }

  function run() {
    setStatus(t('suno.dash.starting'), '');
    try { location.href = 'suno-helper://launch'; } catch (e) {}
    var tries = 0;
    var timer = setInterval(function () {
      tries++;
      fetchLocal('/api/local/status', 2500).then(function (d) {
        if (d) {
          clearInterval(timer);
          window.open(LOCAL + '/?launch=web', '_blank', 'noopener');
          setTimeout(render, 800);
        }
      });
      if (tries > 30) { clearInterval(timer); setStatus(t('suno.dash.startFail'), 'err'); }
    }, 1500);
  }

  function render() {
    var token = getToken();
    fetchLocal('/api/local/status', 2500).then(function (d) {
      if (d && d.web_launch) {
        setStatus(t('suno.dash.installed') + ' v' + d.version + ' \\u00b7 ' + t('suno.dash.ready'), 'ok');
        var b = setBtn(t('suno.dash.btn.run'), run);
        b.classList.add('run');
      } else if (d && !d.web_launch) {
        setStatus(t('suno.dash.legacy'), 'err');
        setBtn(t('suno.dash.btn.install'), install);
      } else if (!token) {
        setStatus(t('suno.dash.notInstalled'), '');
        setBtn(t('suno.dash.btn.signin'), null).setAttribute('href', AUTH_URL);
      } else {
        setStatus(t('suno.dash.notInstalled'), '');
        setBtn(t('suno.dash.btn.install'), install);
      }
    });
  }

  render();
})();
</script>
</body>
</html>
"""

shell = SHELL.replace("__OPTS__", OPT_HTML).replace("__EXTRA__", EXTRA_JS).replace("__I18N_MERGE__", I18N_MERGE)
app = APP.replace("__EXTRA__", EXTRA_JS).replace("__I18N_MERGE__", I18N_MERGE)
for name, content in (("suno.html", shell), ("suno-app.html", app)):
    content.encode("ascii")  # 전송·인코딩 문제 원천 차단
    (OUT_DIR / name).write_text(content, encoding="ascii", newline="\n")
    print(f"OK {name}: {len(content)} bytes, ascii-only")
