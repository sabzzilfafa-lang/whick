import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, LicenseStatus } from "../api";

const STATE_BADGE: Record<string, string> = {
  valid: "badge badge-ok",
  grace: "badge badge-warn",
  expired: "badge badge-danger",
  mismatch: "badge badge-danger",
  none: "badge",
};

export function LicenseSettingsTab({ notify }: { notify: (msg: string, isErr?: boolean) => void }) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<LicenseStatus | null>(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    api
      .getLicenseStatus()
      .then(setStatus)
      .catch((e) => notify(String(e), true));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    refresh();
  }, [refresh]);

  const activate = async () => {
    if (!token.trim()) {
      notify(t("license.token_required"), true);
      return;
    }
    setBusy(true);
    try {
      const st = await api.activateLicense(token.trim());
      setStatus(st);
      setToken("");
      notify(t("license.activated"));
    } catch (e) {
      notify(String(e), true);
    } finally {
      setBusy(false);
    }
  };

  const renew = async () => {
    setBusy(true);
    try {
      const st = await api.renewLicense();
      setStatus(st);
      notify(t("license.renewed"));
    } catch (e) {
      notify(String(e), true);
    } finally {
      setBusy(false);
    }
  };

  if (!status) return <div className="loading">{t("license.loading")}</div>;

  return (
    <div className="card" style={{ marginBottom: "1.5rem" }}>
      <div className="card-title">{t("license.title")}</div>
      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
        <span className={STATE_BADGE[status.state] || STATE_BADGE.none}>
          {t(`license.state.${status.state}`)}
        </span>
        {status.email && <span className="meta">{status.email}</span>}
        {status.plan && <span className="meta">{status.plan}</span>}
        {status.expires_at && (
          <span className="meta">
            {t("license.expires", { date: status.expires_at })}
            {status.state === "grace" && status.grace_until
              ? ` (${t("license.grace_until", { date: status.grace_until })})`
              : ""}
          </span>
        )}
      </div>

      <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem", flexWrap: "wrap" }}>
        <button
          className="btn btn-secondary btn-sm"
          onClick={renew}
          disabled={busy || status.state === "none"}
        >
          {t("license.renew_now")}
        </button>
      </div>

      <div style={{ marginTop: "1.25rem" }}>
        <label className="field-label">{t("license.token_label")}</label>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <input
            type="text"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder={t("license.token_placeholder")}
            style={{ flex: 1 }}
          />
          <button className="btn btn-primary btn-sm" onClick={activate} disabled={busy}>
            {t("license.activate")}
          </button>
        </div>
        <p style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: "0.5rem" }}>
          {t("license.hint")}
        </p>
      </div>
    </div>
  );
}
