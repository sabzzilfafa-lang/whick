import { useEffect, useState } from "react";
import { api, AIProvider, AIModelOption, AppSettings, YoutubeStatus, licenseApi } from "../api";
import { getFallbackModels, mergeModels, VALUE_MODELS, VALUE_TEMPERATURES } from "../lib/aiModels";
import { BrandSettingsTab, DescBlocksSettingsTab } from "../components/BrandSettings";
import { useLang, LangSelect } from "../lib/i18n";

const TASK_CONFIG = [
  { key: "lyrics" as const, label: "가사 생성" },
  { key: "prompt" as const, label: "Suno 프롬프트" },
  { key: "instruments" as const, label: "악기 세팅" },
  { key: "analyze" as const, label: "취향 곡 분석" },
];

type TaskKey =
  | (typeof TASK_CONFIG)[number]["key"]
  | "thumbnail";

/** 썸네일 3종 생성 AI 지정 (2026-09-10): 이미지 생성 제공업체는 google(제미나이)·openai(gpt-image) 2종 */
const IMAGE_PROVIDERS = [
  { id: "google", name: "Google Gemini (이미지)" },
  { id: "openai", name: "OpenAI (gpt-image-1)" },
] as const;

function CreativitySlider({
  value,
  onChange,
}: {
  value: string;
  onChange: (next: string) => void;
}) {
  const { t } = useLang();
  const step = Math.round(Math.min(1, Math.max(0, parseFloat(value) || 0)) * 10);
  const display = (step / 10).toFixed(1);

  return (
    <div className="creativity-control">
      <span className="creativity-edge">0</span>
      <input
        type="range"
        className="creativity-slider"
        min={0}
        max={10}
        step={1}
        value={step}
        onChange={(e) => onChange((parseInt(e.target.value, 10) / 10).toFixed(1))}
        aria-valuemin={0}
        aria-valuemax={1}
        aria-valuenow={step / 10}
        aria-label={`${t("창의성")} ${display}`}
      />
      <span className="creativity-edge">1</span>
      <span className="creativity-value">{display}</span>
    </div>
  );
}

const CUSTOM_MODEL = "__custom__";

function ModelSelect({
  providerId,
  value,
  models,
  loading,
  onChange,
}: {
  providerId: string;
  value: string;
  models: AIModelOption[];
  loading: boolean;
  onChange: (modelId: string) => void;
}) {
  const { t } = useLang();
  const inList = models.some((m) => m.id === value);
  const selectValue = inList || !value ? value : CUSTOM_MODEL;

  return (
    <div className="model-select-wrap">
      <select
        value={selectValue}
        onChange={(e) => {
          const v = e.target.value;
          if (v === CUSTOM_MODEL) {
            onChange(value && !inList ? value : "");
          } else {
            onChange(v);
          }
        }}
        disabled={loading}
        title={value}
      >
        {loading && <option value="">{t("모델 불러오는 중...")}</option>}
        {!loading &&
          models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        {!loading && models.length === 0 && (
          <option value="" disabled>
            {t("목록을 불러올 수 없습니다")}
          </option>
        )}
        <option value={CUSTOM_MODEL}>{t("직접 입력...")}</option>
      </select>
      {(selectValue === CUSTOM_MODEL || (!inList && value)) && (
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={t("모델 ID 직접 입력")}
          className="model-custom-input"
        />
      )}
      {!loading && providerId === "openrouter" && models.length > 7 && (
        <span className="model-hint">{t("OpenRouter 전체 모델 목록")}</span>
      )}
    </div>
  );
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [modelsByProvider, setModelsByProvider] = useState<Record<string, AIModelOption[]>>({});
  const [loadingModels, setLoadingModels] = useState<Record<string, boolean>>({});
  const [apiKeys, setApiKeys] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [youtube, setYoutube] = useState<YoutubeStatus | null>(null);
  const [ytClientId, setYtClientId] = useState("");
  const [ytClientSecret, setYtClientSecret] = useState("");
  const [ytRedirectHost, setYtRedirectHost] = useState<"localhost" | "127.0.0.1">("127.0.0.1");
  const [ytConnecting, setYtConnecting] = useState(false);
  const [ytSaving, setYtSaving] = useState(false);
  const [tab, setTab] = useState<"api" | "youtube" | "desc" | "backup">("api");

  // Whick 라이선스·API키 (2026-09-08 API키 전환)
  const [licenseState, setLicenseState] = useState<string>("none");
  const [licenseEmail, setLicenseEmail] = useState("");
  const [hasApiKey, setHasApiKey] = useState(false);
  const [whickKeyInput, setWhickKeyInput] = useState("");
  const [whickKeyBusy, setWhickKeyBusy] = useState(false);

  const { t } = useLang();

  const loadModelsForProvider = async (
    providerId: string,
    providerList: AIProvider[],
    force = false,
  ) => {
    const provider = providerList.find((p) => p.id === providerId);
    const fallback = getFallbackModels(provider, providerId);

    if (!force && modelsByProvider[providerId]?.length) return;

    setLoadingModels((prev) => ({ ...prev, [providerId]: true }));
    setModelsByProvider((prev) => ({ ...prev, [providerId]: fallback }));

    try {
      const result = await api.listProviderModels(providerId);
      const loaded = result.models?.length ? result.models : fallback;
      setModelsByProvider((prev) => ({ ...prev, [providerId]: loaded }));
    } catch {
      setModelsByProvider((prev) => ({ ...prev, [providerId]: fallback }));
    } finally {
      setLoadingModels((prev) => ({ ...prev, [providerId]: false }));
    }
  };

  useEffect(() => {
    (async () => {
      try {
        const [s, p] = await Promise.all([api.getSettings(), api.listProviders()]);
        setSettings(s);
        setProviders(p);
        const used = new Set([
          s.provider_lyrics,
          s.provider_prompt,
          s.provider_instruments,
          s.provider_analyze,
          s.provider_thumbnail || "openrouter",
        ]);
        used.forEach((pid) => loadModelsForProvider(pid, p));
      } catch (e) {
        setError(e instanceof Error ? e.message : "설정을 불러오지 못했습니다");
      } finally {
        setLoading(false);
      }

      api.getYoutubeStatus()
        .then((yt) => {
          setYoutube(yt);
          setYtClientId(yt.client_id || "");
          if (yt.redirect_host === "localhost" || yt.redirect_host === "127.0.0.1") {
            setYtRedirectHost(yt.redirect_host);
          }
        })
        .catch(() => setYoutube(null));

      licenseApi
        .status()
        .then((lic) => {
          setLicenseState(String(lic.state || "none"));
          setLicenseEmail(String(lic.email || ""));
          setHasApiKey(Boolean(lic.has_api_key));
        })
        .catch(() => {
          setLicenseState("none");
        });
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** whick_ API키 활성화 — CC 검증 후 로컬 보관 (2026-09-08 API키 전환) */
  const handleWhickKeyActivate = async () => {
    const key = whickKeyInput.trim();
    if (!key) {
      setError(t("whick.org 내 계정에서 발급한 API 키를 입력하세요"));
      return;
    }
    setWhickKeyBusy(true);
    setError("");
    setMessage("");
    try {
      const lic = await licenseApi.activateWithApiKey(key);
      setLicenseState(String(lic.state || "valid"));
      setLicenseEmail(String(lic.email || ""));
      setHasApiKey(true);
      setWhickKeyInput("");
      setMessage(t("API 키가 확인되어 활성화되었습니다"));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("API 키 활성화에 실패했습니다"));
    } finally {
      setWhickKeyBusy(false);
    }
  };

  const handleSave = async () => {
    if (!settings) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const payload: Record<string, string> = {
        provider_lyrics: settings.provider_lyrics,
        provider_prompt: settings.provider_prompt,
        provider_instruments: settings.provider_instruments,
        provider_analyze: settings.provider_analyze,
        model_lyrics: settings.model_lyrics,
        model_prompt: settings.model_prompt,
        model_instruments: settings.model_instruments,
        model_analyze: settings.model_analyze,
        temperature_lyrics: settings.temperature_lyrics,
        temperature_prompt: settings.temperature_prompt,
        temperature_instruments: settings.temperature_instruments,
        temperature_analyze: settings.temperature_analyze,
        provider_thumbnail: settings.provider_thumbnail || "openrouter",
        model_thumbnail: settings.model_thumbnail || "",
        image_provider: settings.image_provider || "google",
      };
      for (const [field, value] of Object.entries(apiKeys)) {
        if (value.trim()) payload[field] = value.trim();
      }
      const updated = await api.updateSettings(payload);
      setSettings(updated);
      setApiKeys({});
      setMessage(t("설정이 저장되었습니다."));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("저장 실패"));
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async (providerId: string, keyField: string) => {
    setTesting(providerId);
    setError("");
    setMessage("");
    try {
      const newKey = apiKeys[keyField]?.trim();
      if (newKey) {
        await api.updateSettings({ [keyField]: newKey });
      }
      const result = await api.testProviderApi(providerId);
      setMessage(
        `${providers.find((p) => p.id === providerId)?.name} ${t("연결 성공")} (${result.model_count} ${t("개 모델")})`
      );
      const updated = await api.getSettings();
      setSettings(updated);
      setApiKeys((prev) => ({ ...prev, [keyField]: "" }));
      await loadModelsForProvider(providerId, providers, true);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("테스트 실패"));
    } finally {
      setTesting(null);
    }
  };

  const setTaskProvider = async (task: TaskKey, providerId: string) => {
    if (!settings) return;
    const provider = providers.find((p) => p.id === providerId);
    const defaultModel = provider?.default_models[task] || "";
    setSettings({
      ...settings,
      [`provider_${task}`]: providerId,
      [`model_${task}`]: defaultModel,
    } as AppSettings);
    await loadModelsForProvider(providerId, providers);
  };

  const applyRecommendedModels = () => {
    if (!settings) return;
    setSettings({
      ...settings,
      provider_lyrics: "openrouter",
      provider_prompt: "openrouter",
      provider_instruments: "openrouter",
      provider_analyze: "openrouter",
      model_lyrics: VALUE_MODELS.lyrics,
      model_prompt: VALUE_MODELS.prompt,
      model_instruments: VALUE_MODELS.instruments,
      model_analyze: VALUE_MODELS.analyze,
      temperature_lyrics: VALUE_TEMPERATURES.lyrics,
      temperature_prompt: VALUE_TEMPERATURES.prompt,
      temperature_instruments: VALUE_TEMPERATURES.instruments,
      temperature_analyze: VALUE_TEMPERATURES.analyze,
    });
    setMessage(t("가성비 권장 모델·창의성이 선택되었습니다. 「설정 저장」을 눌러 적용하세요."));
    setError("");
  };

  const handleYoutubeSave = async () => {
    if (!ytClientId.trim()) {
      setError(t("OAuth 클라이언트 ID를 입력하세요."));
      return;
    }
    if (!ytClientSecret.trim() && !youtube?.client_secret_set) {
      setError(t("OAuth 클라이언트 보안 비밀을 입력하세요."));
      return;
    }
    setYtSaving(true);
    setError("");
    setMessage("");
    try {
      const updated = await api.saveYoutubeCredentials({
        youtube_client_id: ytClientId.trim(),
        youtube_client_secret: ytClientSecret.trim() || undefined,
        redirect_host: ytRedirectHost,
      });
      setYoutube(updated);
      setYtClientSecret("");
      setMessage(t("YouTube OAuth 설정이 저장되었습니다."));
    } catch (e) {
      setError(formatYoutubeError(e));
    } finally {
      setYtSaving(false);
    }
  };

  const formatYoutubeError = (e: unknown) => {
    const msg = e instanceof Error ? e.message : t("요청 실패");
    if (msg.includes("요청 실패") || msg.includes("Not Found")) {
      return t("YouTube API에 연결할 수 없습니다. stop.bat 실행 후 start.bat으로 백엔드를 다시 시작하세요.");
    }
    return msg;
  };

  const handleYoutubeConnect = async () => {
    if (!ytClientId.trim() && !youtube?.client_id) {
      setError(t("먼저 OAuth 클라이언트 ID와 보안 비밀을 입력하고 저장하세요."));
      return;
    }
    setYtConnecting(true);
    setError("");
    setMessage(t("Google 로그인 창을 여는 중..."));
    try {
      if (ytClientId.trim() || ytClientSecret.trim()) {
        await api.saveYoutubeCredentials({
          youtube_client_id: ytClientId.trim(),
          youtube_client_secret: ytClientSecret.trim() || undefined,
          redirect_host: ytRedirectHost,
        });
      }
      const { auth_url } = await api.getYoutubeAuthUrl();
      const popup = window.open(auth_url, "youtube-oauth", "width=520,height=720");
      if (!popup) {
        setMessage(t("팝업이 차단되었습니다. 같은 탭에서 Google 로그인 페이지로 이동합니다."));
        window.location.href = auth_url;
        return;
      }
      setMessage(t("Google 로그인 창에서 채널을 승인해 주세요."));
      const poll = setInterval(async () => {
        try {
          const st = await api.getYoutubeStatus();
          setYoutube(st);
          if (st.connected) {
            clearInterval(poll);
            setYtConnecting(false);
            setMessage(`${st.channel_title || t("채널")} ${t("연결 완료")}`);
            popup.close();
          }
        } catch {
          /* ignore */
        }
        if (popup.closed) {
          clearInterval(poll);
          setYtConnecting(false);
          try {
            const st = await api.getYoutubeStatus();
            setYoutube(st);
            if (st.connected) {
              setMessage(`${st.channel_title || t("채널")} ${t("연결 완료")}`);
            } else {
              setMessage(t("로그인 창이 닫혔습니다. 연결이 완료되지 않았으면 다시 시도하세요."));
            }
          } catch (e) {
            setError(formatYoutubeError(e));
          }
        }
      }, 2000);
    } catch (e) {
      setError(formatYoutubeError(e));
      setMessage("");
      setYtConnecting(false);
    }
  };

  const handleYoutubeDisconnect = async () => {
    if (!confirm(t("YouTube 채널 연결을 해제하시겠습니까?"))) return;
    await api.disconnectYoutube();
    const st = await api.getYoutubeStatus();
    setYoutube(st);
    setMessage(t("YouTube 연결이 해제되었습니다."));
  };

  const handleImportBackup = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const result = await api.importBackup(file);
      setMessage(result.message || t("백업 복원 완료"));
    } catch {
      setError(t("백업 복원 실패"));
    }
  };

  const formatMaskedSecret = (masked: string): string => {
    const value = masked.trim();
    if (!value) return "";
    if (value.length <= 8) return value;
    return `****${value.slice(-4)}`;
  };

  const getMasked = (field: string): string => {
    if (!settings) return "";
    const key = `${field}_masked` as keyof AppSettings;
    return formatMaskedSecret(String(settings[key] || ""));
  };

  const isKeySet = (field: string): boolean => {
    if (!settings) return false;
    const key = `${field}_set` as keyof AppSettings;
    return Boolean(settings[key]);
  };

  if (loading) return <div className="loading">{t("불러오는 중...")}</div>;
  if (!settings) {
    return (
      <div>
        <div className="error">
          {error || t("설정을 불러올 수 없습니다. 백엔드가 실행 중인지 확인하세요.")}
        </div>
      </div>
    );
  }

  const tabs = [
    { id: "api", label: t("API · 작업별 AI") },
    { id: "youtube", label: t("유튜브 자동 게시") },
    { id: "desc", label: t("유튜브 설명 위젯") },
    { id: "backup", label: t("백업 · 복원") },
  ] as const;

  const notify = (msg: string, isErr = false) => {
    setMessage(isErr ? "" : msg);
    setError(isErr ? msg : "");
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>{t("사용자 설정")}</h2>
          <p>{t("API 키·AI 모델, 유튜브 자동 게시, 설명 자동 구성, 백업을 한 곳에서 관리합니다")}</p>
        </div>
      </div>

      {/* 언어 선택 — 설정 안에도 노출 (2026-09-09 파파님 지시) */}
      <div className="card" style={{ marginBottom: "1.25rem" }}>
        <div className="card-title">{t("언어")}</div>
        <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "0.75rem" }}>
          {t("UI 표시 언어 — 이 기기에 저장됩니다")}
        </p>
        <LangSelect />
      </div>

      <div className="settings-tabs" role="tablist">
        {tabs.map((tb) => (
          <button
            key={tb.id}
            role="tab"
            aria-selected={tab === tb.id}
            className={`settings-tab${tab === tb.id ? " active" : ""}`}
            onClick={() => setTab(tb.id)}
          >
            {tb.label}
          </button>
        ))}
      </div>

      {error && <div className="error">{error}</div>}
      {message && <div className="success-banner">{message}</div>}

      {tab === "api" && (
        <>
          {/* Whick 라이선스·API키 — whick.org 계정 키로 실행 자격 획득 (2026-09-08) */}
          <div className="card" style={{ marginBottom: "1.5rem" }}>
            <div className="card-title">Whick API 키</div>
            {licenseState === "valid" || licenseState === "grace" ? (
              <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "0.75rem" }}>
                {t("활성화됨")}
                {licenseEmail ? ` — ${licenseEmail}` : ""}
                {licenseState === "grace" ? ` (${t("갱신 만료 임박 — 다음 작업 시 자동 갱신")})` : ""}
              </p>
            ) : (
              <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "0.75rem" }}>
                whick.org {t("에서 발급한 키를 입력하세요.")} <b>내 계정 → API 키</b>
                <br />
                {t("키가 있어야 작업(파이프라인)을 실행할 수 있습니다.")}
              </p>
            )}
            <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
              <input
                type="password"
                value={whickKeyInput}
                onChange={(e) => setWhickKeyInput(e.target.value)}
                placeholder={hasApiKey ? t("새 API 키로 교체 (whick_…)") : "whick_… API 키"}
                style={{ flex: "1 1 260px", minWidth: "220px" }}
                disabled={whickKeyBusy}
              />
              <button
                className="btn btn-primary"
                onClick={handleWhickKeyActivate}
                disabled={whickKeyBusy || !whickKeyInput.trim()}
              >
                {whickKeyBusy ? t("확인 중…") : hasApiKey ? t("키 교체") : t("활성화")}
              </button>
              <a
                href="https://whick.org/account.html#apiKeyBox"
                target="_blank"
                rel="noreferrer"
                style={{ fontSize: "0.8rem" }}
              >
                {t("API 키 발급 →")}
              </a>
            </div>
          </div>
          <div className="card" style={{ marginBottom: "1.5rem" }}>
            <div className="card-title">{t("AI 제공업체 API 키")}</div>
            <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "1rem" }}>
              {t("사용하는 서비스만 입력하면 됩니다. 연결 테스트 후 해당 서비스의 모델 목록이 자동으로 채워집니다.")}
            </p>
            <div className="provider-grid">
              {providers.map((p) => (
                <div key={p.id} className="provider-card">
                  <h4>{p.name}</h4>
                  <p>{p.description}</p>
                  <a href={p.key_url} target="_blank" rel="noreferrer" style={{ fontSize: "0.8rem" }}>
                    {t("API 키 발급 →")}
                  </a>
                  {isKeySet(p.key_field) && (
                    <p style={{ fontSize: "0.8rem", marginTop: "0.5rem" }}>
                      {t("등록됨:")} <code>{getMasked(p.key_field)}</code>
                    </p>
                  )}
                  <div className="form-group" style={{ marginTop: "0.75rem", marginBottom: "0.5rem" }}>
                    <input
                      type="password"
                      value={apiKeys[p.key_field] || ""}
                      onChange={(e) =>
                        setApiKeys({ ...apiKeys, [p.key_field]: e.target.value })
                      }
                      placeholder={isKeySet(p.key_field) ? t("변경 시에만 입력") : t("API 키 입력")}
                    />
                  </div>
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => handleTest(p.id, p.key_field)}
                    disabled={testing === p.id}
                  >
                    {testing === p.id ? t("확인 중...") : t("연결 테스트")}
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="card" style={{ marginBottom: "1.5rem" }}>
            <div className="card-title">{t("작업별 AI 설정")}</div>
            <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "0.75rem" }}>
              {t("제공업체를 바꾸면 해당 작업에 맞는 기본 모델이 자동 선택됩니다. 드롭다운에서 다른 모델을 고를 수 있습니다.")}
              <br />
              <span className="meta">
                {t("창의성(Temperature): 0에 가까울수록 안정·일관, 1에 가까울수록 자유롭고 독창적인 생성입니다.")}
                <br />
                {t("연결 테스트를 하면 OpenRouter 등에서 최신 모델 목록을 불러옵니다.")}
              </span>
            </p>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              style={{ marginBottom: "1rem" }}
              onClick={applyRecommendedModels}
            >
              {t("가성비 권장 설정 적용")}
            </button>
            <div className="task-config-header">
              <span>{t("작업")}</span>
              <span>{t("제공업체")}</span>
              <span>{t("모델")}</span>
              <span>{t("창의성")}</span>
            </div>
            {TASK_CONFIG.map((task) => {
              const providerKey = `provider_${task.key}` as keyof AppSettings;
              const modelKey = `model_${task.key}` as keyof AppSettings;
              const tempKey = `temperature_${task.key}` as keyof AppSettings;
              const providerId = String(settings[providerKey]);
              const currentModel = String(settings[modelKey]);
              const models = mergeModels(modelsByProvider[providerId] || [], currentModel);
              return (
                <div key={task.key} className="task-config-row">
                  <div className="task-config-label">{t(task.label)}</div>
                  <select
                    value={providerId}
                    onChange={(e) => setTaskProvider(task.key, e.target.value)}
                  >
                    {providers.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                  <ModelSelect
                    providerId={providerId}
                    value={String(settings[modelKey])}
                    models={models}
                    loading={!!loadingModels[providerId]}
                    onChange={(modelId) =>
                      setSettings({ ...settings, [modelKey]: modelId } as AppSettings)
                    }
                  />
                  <CreativitySlider
                    value={String(settings[tempKey])}
                    onChange={(next) =>
                      setSettings({ ...settings, [tempKey]: next } as AppSettings)
                    }
                  />
                </div>
              );
            })}
          </div>

          <div className="card" style={{ marginTop: "1.5rem" }}>
            <div className="card-title">{t("썸네일 생성 AI")}</div>
            <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "0.75rem" }}>
              {t("앨범 상세의 「AI 썸네일 3장 생성」에 사용됩니다. 첫 행은 이미지 프롬프트를 작성할 텍스트 AI, 두 번째는 실제 이미지를 그릴 AI입니다.")}
            </p>
            <div className="task-config-header">
              <span>{t("항목")}</span>
              <span>{t("제공업체")}</span>
              <span>{t("모델")}</span>
              <span />
            </div>
            <div className="task-config-row">
              <div className="task-config-label">{t("썸네일 프롬프트")}</div>
              <select
                value={String(settings.provider_thumbnail || "openrouter")}
                onChange={(e) => setTaskProvider("thumbnail", e.target.value)}
              >
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
              <ModelSelect
                providerId={String(settings.provider_thumbnail || "openrouter")}
                value={String(settings.model_thumbnail || "")}
                models={mergeModels(
                  modelsByProvider[String(settings.provider_thumbnail || "openrouter")] || [],
                  String(settings.model_thumbnail || "")
                )}
                loading={!!loadingModels[String(settings.provider_thumbnail || "openrouter")]}
                onChange={(modelId) =>
                  setSettings({ ...settings, model_thumbnail: modelId } as AppSettings)
                }
              />
              <span />
            </div>
            <div className="task-config-row">
              <div className="task-config-label">{t("이미지 생성 AI")}</div>
              <select
                value={String(settings.image_provider || "google")}
                onChange={(e) =>
                  setSettings({ ...settings, image_provider: e.target.value } as AppSettings)
                }
              >
                {IMAGE_PROVIDERS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
              <span className="meta" style={{ gridColumn: "span 2", alignSelf: "center" }}>
                {t("Google 선택 시 google_api_key, OpenAI 선택 시 openai_api_key가 사용됩니다.")}
              </span>
            </div>
          </div>
        </>
      )}

      {tab === "youtube" && (
        <>
          <BrandSettingsTab notify={notify} />
          <div className="card" style={{ marginTop: "1.5rem", marginBottom: "1.5rem" }}>
            <div className="card-title">{t("YouTube 채널 연결 (OAuth)")}</div>
            <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "1rem" }}>
              Google Cloud → API 및 서비스 → 라이브러리에서 <strong>YouTube Data API v3</strong>를 사용 설정한 다음,
              사용자 인증 정보 → OAuth 클라이언트 → <strong>웹 애플리케이션</strong>으로 만들고,
              아래 URI를 <strong>승인된 리디렉션 URI</strong>에 그대로 추가하세요. (localhost와 127.0.0.1은 다릅니다)
            </p>
            {youtube ? (
              <div style={{ fontSize: "0.8rem", marginBottom: "1rem" }}>
                <p style={{ marginBottom: "0.35rem" }}>{t("현재 앱이 사용하는 URI:")}</p>
                <code style={{ display: "block", marginBottom: "0.5rem" }}>{youtube.redirect_uri}</code>
                <p className="meta">{t("Google에 둘 다 등록해 두면 편합니다:")}</p>
                {(youtube.redirect_uris_hint || [youtube.redirect_uri]).map((uri) => (
                  <code key={uri} style={{ display: "block" }}>{uri}</code>
                ))}
              </div>
            ) : (
              <p style={{ fontSize: "0.8rem", color: "var(--warning)", marginBottom: "1rem" }}>
                {t("YouTube API를 사용하려면 백엔드를 재시작하세요 (start.bat → stop 후 다시 start).")}
              </p>
            )}
            <div className="form-group">
              <label>{t("리디렉션 호스트 (Google에 등록한 주소와 동일하게)")}</label>
              <select
                value={ytRedirectHost}
                onChange={(e) => setYtRedirectHost(e.target.value as "localhost" | "127.0.0.1")}
              >
                <option value="127.0.0.1">127.0.0.1</option>
                <option value="localhost">localhost</option>
              </select>
            </div>
            <div className="form-group">
              <label>{t("OAuth 클라이언트 ID")}</label>
              <input
                value={ytClientId}
                onChange={(e) => setYtClientId(e.target.value)}
                placeholder="xxxx.apps.googleusercontent.com"
              />
            </div>
            <div className="form-group">
              <label>{t("OAuth 클라이언트 보안 비밀")}</label>
              <input
                type="password"
                value={ytClientSecret}
                onChange={(e) => setYtClientSecret(e.target.value)}
                placeholder={youtube?.client_secret_set ? t("변경 시에만 입력") : t("클라이언트 보안 비밀")}
              />
              {youtube?.client_secret_set && (
                <span className="meta">{t("등록됨:")} {formatMaskedSecret(youtube.client_secret_masked)}</span>
              )}
            </div>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
              <button className="btn btn-secondary btn-sm" onClick={handleYoutubeSave} disabled={ytSaving}>
                {ytSaving ? t("저장 중...") : t("OAuth 저장")}
              </button>
              <button
                className="btn btn-primary btn-sm"
                onClick={handleYoutubeConnect}
                disabled={ytConnecting}
              >
                {ytConnecting ? t("연결 대기 중...") : t("YouTube 채널 연결")}
              </button>
              {youtube?.connected && (
                <>
                  <span className="badge badge-ok">{t("연결됨:")} {youtube.channel_title}</span>
                  <button className="btn btn-danger btn-sm" onClick={handleYoutubeDisconnect}>
                    {t("연결 해제")}
                  </button>
                </>
              )}
            </div>
            <p style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: "0.75rem" }}>
              {t("스튜디오에서 영상 생성 후 「유튜브 비공개 업로드」→ 검수 후 「유튜브 공개」 순서로 사용합니다.")}
            </p>
          </div>
        </>
      )}

      {tab === "desc" && <DescBlocksSettingsTab notify={notify} />}

      {tab === "backup" && (
        <div className="card" style={{ marginBottom: "1.5rem" }}>
          <div className="card-title">{t("백업 / 복원")}</div>
          <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "1rem" }}>
            {t("데이터베이스·채널 브랜드·스타일 프리셋·업로드 파일을 zip 하나로 백업하고, 다른 PC에서 그대로 복원할 수 있습니다.")}
          </p>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button className="btn btn-secondary" onClick={() => api.exportBackup()}>
              {t("백업 보내기")}
            </button>
            <label className="btn btn-secondary" style={{ cursor: "pointer" }}>
              {t("백업 가져오기")}
              <input type="file" accept=".zip" onChange={handleImportBackup} hidden />
            </label>
          </div>
        </div>
      )}

      {tab === "api" && (
        <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? t("저장 중...") : t("설정 저장")}
        </button>
      )}
    </div>
  );
}
