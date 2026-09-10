import { useEffect, useState } from "react";

import { api, QueueJob } from "../api";
import { useLang } from "../lib/i18n";

function jobTitle(job: QueueJob, t: (ko: string) => string): string {
  if (job.job_type === "pipeline") return t("영상 파이프라인");
  if (job.job_type === "playlist") return t("합본 플레이리스트");
  if (job.job_type === "album_tracks") return t("앨범 트랙 일괄 등록");
  return t("백그라운드 작업");
}

export default function QueueBanner() {
  const [jobs, setJobs] = useState<QueueJob[]>([]);
  const [closing, setClosing] = useState<number | null>(null);
  const { t } = useLang();

  useEffect(() => {
    const poll = () => {
      api.listQueue().then((list) => {
        const active = list.filter((j) => j.status === "running" || j.status === "pending");
        setJobs(active);
      });
    };
    poll();
    const interval = setInterval(poll, 3000);
    return () => clearInterval(interval);
  }, []);

  const dismiss = async (id: number) => {
    setClosing(id);
    try {
      await api.cancelQueueJob(id);
      setJobs((prev) => prev.filter((j) => j.id !== id));
    } catch {
      /* keep row */
    } finally {
      setClosing(null);
    }
  };

  if (jobs.length === 0) return null;

  return (
    <div className="queue-banner">
      {jobs.map((job) => (
        <div key={job.id} className="queue-item">
          <div className="queue-info">
            <strong>{jobTitle(job, t)}</strong>
            <span>
              {job.message || `${job.progress}/${job.total}`}
              {job.total > 0 ? ` · ${job.progress}/${job.total}` : ""}
            </span>
            <button
              type="button"
              className="queue-dismiss"
              disabled={closing === job.id}
              onClick={() => dismiss(job.id)}
            >
              {t("끄기")}
            </button>
          </div>
          <div className="queue-bar">
            <div
              className="queue-bar-fill"
              style={{
                width: job.total ? `${(job.progress / job.total) * 100}%` : "0%",
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
