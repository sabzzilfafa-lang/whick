# Whick 오디오 재생 업그레이드 설계 — Bit-Perfect · Hi-Res · 경쟁사 동등

**상태:** Phase 1–4 + DSD DoP · DAC 자동감지 · SR 페이드 완료 (2026-07-06) — 집 DAC 실측만 남음  
**SSOT 연계:** [REMOTE-DESIGN.md](REMOTE-DESIGN.md) · [EXTERNAL-PROVIDERS-DESIGN.md](EXTERNAL-PROVIDERS-DESIGN.md) §6  
**목표:** 최초 제품 의도(무손실·원본 해상도 DAC 직출) 복원 + Roon / JRiver / Audirvana / Plexamp 급 포맷·해상도 커버

---

## 0. 문제 정의 (현재 = 다운그레이드)

### 현재 경로 (PoC 고정)

```
소스 (FLAC 24/192, WAV, …)
  → MPD pipe  format "44100:16:2"     ← gen_mpd_conf.py 고정
  → camilla-pipe.sh: ffmpeg s16le@44100 → f32le@48000
  → CamillaDSP (EQ · room PEQ · DAC preprocess 기본 ON)
  → ffmpeg aresample → ALSA @ WHICK_DAC_ALSA_RATE (기본 48000)
```

| 항목 | 파일 메타 | 실제 DAC 입력 | 비고 |
|------|-----------|---------------|------|
| 24/96 FLAC | 24bit · 96kHz | **16bit · 48kHz** (또는 44.1k 중간) | 이중 리샘플 |
| DSP 전부 OFF | — | 여전히 ffmpeg 2단 | `# whick passthrough` ≠ bit-perfect |
| room 보정 적용됨 | — | PEQ 항상 가능 | `roomPeaking`이 `peaking`에 merge |
| DSD / AIFF / ALAC | 스캔 제외 | 재생 불가 | `AUDIO_EXTS` 화이트리스트 |
| UI `quality` | DB 메타 표시 | **실제 출력과 불일치** | 고객 신뢰 이슈 |

**결론:** 리모컨에 "24/96 FLAC"이 떠도 DAC에는 16/48k가 들어간다. 제품 카피·체험 스펙의 "무손실 그대로"와 모순.

### 경쟁사 기준선 (2026)

| 제품 | 포맷 (대표) | PCM 상한 (마케팅/스펙) | DSD | Bit-perfect 모드 |
|------|-------------|------------------------|-----|------------------|
| Roon | FLAC WAV ALAC AIFF DSD… | 768kHz · 32bit | DSD512 | RAAT / 코어 비트퍼펙트 |
| JRiver | + APE WV WMA… | 768kHz · 32bit | Native/DoP | DSP off 시 직출 |
| Audirvana | 유사 | 384kHz+ | DSD256+ | Bit-perfect 토글 |
| Plexamp | 광범위 | DAC 한도 | 제한적 | Direct play |

**Whick 목표 (1차 GA):** PCM **원본 rate/bit → DAC** (DSP OFF) · 포맷 **FLAC WAV AIFF ALAC + 손실** · Hi-Res **최소 24/192 실재생** · DAC 스펙 **768k/32bit 경로 설계** (실기 검증은 DAC별).

---

## 1. 설계 원칙

1. **두 갈래 재생 (Dual Path)** — DSP가 필요할 때만 가공; 아니면 MPD→ALSA 직결.
2. **메타 = 출력** — `state.quality`는 **실제 재생 경로** 기준 (`24/96 → DAC` vs `24/96 → DSP 48k`).
3. **포맷은 스캔=재생** — 라이브러리에 들어온 파일은 재생 가능 (화이트리스트 확장).
4. **레이트 스위치 허용** — 곡 간 ALSA rate 변경은 **정상 동작**으로 설계 (클릭·뮤트는 완화 정책).
5. **하위 호환** — `WHICK_PLAYBACK_MODE=legacy` 로 기존 44.1k pipe 유지 (lab·회귀용).

---

## 2. 목표 아키텍처

### 2.1 모드 개요

```
┌─────────────────────────────────────────────────────────────────┐
│                     Whick Playback Router                        │
│  playback_mode: bitperfect | dsp | legacy (PoC)                    │
└─────────────────────────────────────────────────────────────────┘
         │                              │
         │ bitperfect                   │ dsp (EQ · room · DAC prep)
         ▼                              ▼
┌─────────────────────┐      ┌──────────────────────────────────────┐
│ MPD audio_output    │      │ MPD pipe → whick-dsp-pipe.sh         │
│   type: alsa        │      │   native s32le OR s24le (가변 rate)  │
│   device: hw:X,Y    │      │   → CamillaDSP @ track_rate or 48k   │
│   mixer: software   │      │   → ALSA (rate negotiate)            │
│   (no forced fmt)   │      └──────────────────────────────────────┘
│ auto_resample: no   │
└─────────────────────┘
         │
         ▼
    DAC (native PCM)
```

**모드 선택 규칙 (자동):**

| 조건 | 경로 |
|------|------|
| `dacPreprocessEnabled=false` AND EQ off AND room bypass AND swap off | **bitperfect** |
| room 보정 ON 또는 EQ ON 또는 DAC preprocess ON | **dsp** |
| `WHICK_PLAYBACK_MODE=legacy` | 기존 44100:16 pipe |

리모컨 **「음질」탭**에 `Bit-Perfect` / `DSP 처리` 배지 + 토글(고급: room만 유지 등은 2차).

### 2.2 MPD 설정 (`gen_mpd_conf.py` 개편)

```python
# 의사코드
def render(*, mode: str):
    if mode == "bitperfect":
        audio_output { type alsa; device $WHICK_ALSA_DEVICE; mixer_type software }
        # format 지정 없음 → 디코드 네이티브
        # 전역: auto_resample "no"  (bit-perfect)
    elif mode == "dsp":
        audio_output { type pipe; command whick-dsp-pipe.sh; format "?:?:2" }
        # MPD 0.23+: decoder pass-through; 미지원 시 트랙별 fifo + player wrapper
    # 공통: spectrum tap (별도 fifo, 48k downmix — 메인 경로 무관)
```

**MPD 제약 대응:**

- Pipe `format`은 정적 → **DSP 경로만 pipe**, bit-perfect는 **ALSA 직출**.
- 곡 전환 시 rate 변경: `alsa` output + `whick-alsa-rate.sh` (재생 시작 시 `aplay`/`amixer`로 hw_params 설정, 실패 시 한 단계 폴백 리샘플).

### 2.3 DSP 파이프 (`whick-dsp-pipe.sh` — `camilla-pipe.sh` 대체)

```
stdin: MPD pipe PCM (목표: s32le · native rate · stereo)
  → [optional] ffmpeg only if Camilla stdin rate ≠ MPD rate
  → camilladsp (devices.samplerate = 동적)
  → ALSA (dac_rate = min(native_os_rate, DAC max))
```

**Camilla yaml (`camilla_yaml.py`):**

- `BASE_RATE` 고정 48000 → **`playback_rate` 동적** (트랙 SR 또는 48k 정책).
- `dac_preprocess_enabled` 시 oversample 기준도 **입력 SR**에서 계산.
- Room PEQ: bitperfect 모드에서는 **pipeline에서 제외** (`roomBypass: true` 또는 별도 플래그).

### 2.4 Spectrum / VU (부가 경로)

- 기존 fifo `44100:16:2` 유지하되 **MPD duplicate output**으로만 사용.
- Bit-perfect 메인과 분리 → 스펙트럼용 다운믹스는 품질에 영향 없음.
- WS `spectrum` 밴드는 48k 기준 로그 스케일 유지.

### 2.5 스트리밍 · librespot

| 소스 | 1차 | 2차 |
|------|-----|-----|
| 로컬 라이브러리 | Dual path | DSD |
| 라디오 (MPD) | dsp 또는 bitperfect (스트림 SR 그대로) | — |
| Spotify Connect | librespot → **동일 router** | 320kbps 한계 명시 |
| Tidal lab | MPD 경로 | MQA 정책 별도 |

`librespot-camilla.sh`: 고정 44100 제거 → librespot `--format` / pipe rate 동기화.

---

## 3. 포맷 확장 (라이브러리 = 재생)

### Phase F1 — 무손실 PCM 확장 (우선)

| 확장자 | 디코더 | 스캔 | 비고 |
|--------|--------|------|------|
| `.aiff` `.aif` | ffmpeg / mutagen | O | |
| `.alac` (m4a 컨테이너는 기존) | ffmpeg | O | pure `.alac` rare |
| `.ape` `.wv` | ffmpeg | O | CPU 부담 → hires 플래그만 |
| `.wma` | ffmpeg | O | 손실·손실less 혼재, 메타 표시 |

`library_scanner.py` `AUDIO_EXTS` · `music_api.py` `_TRACK_MEDIA` · trial `LIB_LOSSLESS` · monitor `metrics.mjs` 동기화.

### Phase F2 — DSD

| 항목 | 내용 |
|------|------|
| 확장자 | `.dsf` `.dff` |
| 메타 | ffprobe `codec_name=dff/dsf`, DSD rate = 64/128/… |
| 재생 | **DoP** (PCM 176.4k/24 wrapper) 기본 · DAC capability DB |
| DSP | DSD 구간은 **bitperfect only** (Camilla DSD 미지원) |
| Hi-Res 규칙 | `WHICK_HIRES_DSD_MIN=64` 등 env |

### Phase F3 — 컨테이너·비표준

- `.m4a` ALAC vs AAC 구분 (기존 mutagen 보강)
- CUE sheet (JRiver급) — **후순위**

---

## 4. API · 상태 · UI

### 4.1 새 필드

**`GET /api/state` · WS `state`:**

```json
{
  "quality": "24/96 FLAC",
  "playback": {
    "mode": "bitperfect",
    "source_format": "flac",
    "source_bit_depth": 24,
    "source_sample_rate": 96000,
    "output_bit_depth": 24,
    "output_sample_rate": 96000,
    "dsp_active": false,
    "resampled": false
  }
}
```

**`GET /api/dsp/pipeline`:** `playback_mode`, `alsa_device`, `dac_max_rate`, `last_hw_params`.

### 4.2 리모컨 / 체험

- Now Playing: `24/96 → DAC` vs `24/96 → DSP 48k` 구분 표시.
- DSP 화면: 「원본 그대로 재생」마스터 스위치 → bitperfect 강제.
- `/pages/trial` 스펙 테이블: **구현 후** 실측 경로와 일치하도록 수정.

### 4.3 DAC capability (미니PC)

```json
// /var/lib/whick/dac-capability.json (setup 또는 EDID/USB descriptor 캐시)
{
  "pcm_max_sample_rate": 384000,
  "pcm_max_bit_depth": 32,
  "dsd_native": ["DSD64", "DSD128"],
  "dop": true
}
```

초기값: 보수적 192k/24 · OTA로 제품별 프로필.

---

## 5. 구현 단계 (권장 순서)

### Phase 1 — Bit-Perfect PCM (2~3주) ★ 최우선

| # | 작업 | 파일 |
|---|------|------|
| 1.1 | `WHICK_PLAYBACK_MODE` · router | `audio_pipeline.py` (신규 `playback_router.py`) |
| 1.2 | MPD dual conf 생성 | `gen_mpd_conf.py` |
| 1.3 | ALSA 직출 + `auto_resample no` | mpd.conf template · `whick-alsa-rate.sh` |
| 1.4 | DSP 모드 시에만 pipe | `whick-dsp-pipe.sh` |
| 1.5 | 프로필 변경 → MPD reload output | `music_api.py` · `dsp_store.py` |
| 1.6 | room/EQ off 시 진짜 passthrough | `camilla_yaml.py` · `dsp_store.py` |
| 1.7 | state.playback 실측 | `music_api.py` (hw_params or ffprobe log) |
| 1.8 | 회귀: `legacy` 모드 | env |

**완료 기준:** 24/96 FLAC 재생 시 DAC LED/측정기 **96kHz** (또는 DAC max), `resampled: false`.

### Phase 2 — 포맷 확장 (1주)

- F1 확장자 + 스캔·스트림·체험 시드 동기화.
- Hi-Res 배지 로직 유지 (`library_scanner.evaluate_hires`).

### Phase 3 — DSP Hi-Res (1~2주)

- Camilla 가변 SR · DAC preprocess 96k/192k base.
- 곡 간 rate switch 최소화 (같은 앨범 SR 유지 큐 옵션 — 2차).

### Phase 4 — DSD (2주+)

- DoP · capability · UI DSD 배지.
- 전용 테스트 DAC (iFi · Topping · RME).

### Phase 5 — 문서·마케팅 정합

- encyclopedia Whick Musicserver · trial spec · REMOTE-DESIGN §재생 엔진 문구 업데이트.

---

## 6. 환경 변수 (신규·변경)

| 변수 | 기본 | 설명 |
|------|------|------|
| `WHICK_PLAYBACK_MODE` | `auto` | `auto` \| `bitperfect` \| `dsp` \| `legacy` |
| `WHICK_ALSA_DEVICE` | `default` | Bit-perfect ALSA device |
| `WHICK_MPD_AUTO_RESAMPLE` | `no` | Bit-perfect 시 MPD 리샘플 금지 |
| `WHICK_DSP_WORKING_RATE` | `48000` | DSP 내부 기준 (가변 전환 시) |
| `WHICK_DAC_MAX_SAMPLE_RATE` | `384000` | capability fallback |
| `WHICK_ROOM_BYPASS_FOR_BITPERFECT` | `1` | room PEQ 자동 우회 |
| `WHICK_MPD_PIPE_RATE` | *(deprecated)* | legacy only |

---

## 7. 리스크 · 완화

| 리스크 | 완화 |
|--------|------|
| 곡 간 SR 변경 클릭 | ALSA pause · 짧은 fade · 동일 SR 큐 정렬 (2차) |
| DAC가 96k 미지원 | capability + **한 번만** 리샘플 + UI `→ 48k (DAC 한도)` |
| Docker lab 무음 | null sink + spectrum만 · bitperfect는 hw loopback |
| CPU (24/192 + DSP) | DSP on 시에만 heavy path · 기본 bitperfect |
| 메타/출력 불일치 재발 | `playback.resampled` 필수 · E2E 테스트 |
| MPD pipe 가변 format | 검증: MPD 버전; 불가 시 `ffmpeg` single adapter |

---

## 8. 테스트 매트릭스

| 케이스 | 입력 | 모드 | 기대 출력 |
|--------|------|------|-----------|
| T1 | 16/44.1 FLAC | bitperfect | 16/44.1 |
| T2 | 24/96 FLAC | bitperfect | 24/96 |
| T3 | 24/192 FLAC | bitperfect | 24/192 (DAC 허용 시) |
| T4 | T3 | dsp+EQ | 32/48 float internal → DAC rate |
| T5 | MP3 320 | bitperfect | 16/44.1 (decode) |
| T6 | room ON | auto | dsp path |
| T7 | legacy env | legacy | 16/48 (회귀) |

측정: `cat /proc/asound/card0/pcm0p/sub0/hw_params` · `aplay -v` · optional USB analyzer.

---

## 9. 경쟁사 대비 목표 포지션 (GA 후)

| 항목 | Whick (목표) | 비고 |
|------|--------------|------|
| 로컬 PCM bit-perfect | ✅ | DSP off |
| 24/192 실재생 | ✅ | Phase 1 |
| AIFF ALAC APE WV | ✅ | Phase 2 |
| DSD DoP | ✅ | Phase 4 |
| 768k/32 PCM | 경로 설계 | DAC별 |
| Room EQ + bit-perfect 동시 | ❌ | 의도적 분리 |
| Spotify 무손실 | ❌ | 공급자 한계 |
| RAAT / AirPlay | ❌ | 제품 범위 외 |

---

## 10. 즉시 하지 않을 것

- 메뉴·홈페이지 네비 변경 (무관)
- Navidrome 등 OSS 서버 비교 항목 추가
- 전체 플레이어를 GStreamer로 교체 (MPD 유지, 출력만 분기)

---

## 11. 다음 액션 (파파님 확인 후)

1. **Phase 1 착수 승인** — 기본 모드 `auto` (DSP off → bitperfect).
2. **DAC capability** — 미니PC + 파파님 DAC 1종 실측으로 `dac-capability.json` 시드.
3. **legacy 유지 기간** — OTA 1회 전까지 `WHICK_PLAYBACK_MODE=legacy` fallback.

**예상 일정:** Phase 1+2 완료 시 **경쟁사 실사용 수준(로컬 PCM)** 도달 · DSD는 Phase 4.
