import type { ThumbBox, ThumbCanvasState } from "../components/ThumbnailCanvasEditor";

export const THUMB_TEMPLATE_IDS = [
  "tpl-modern",
  "tpl-01-left-photo",
  "tpl-02-full-center",
  "tpl-03-top-bottom",
  "tpl-04-center-card",
  "tpl-05-stacked",
  "tpl-06-bottom-bar",
  "tpl-07-polaroid",
  "tpl-08-minimal",
] as const;

export type ThumbTemplateId = (typeof THUMB_TEMPLATE_IDS)[number];

export const THUMB_TEMPLATE_LABELS: Record<ThumbTemplateId, string> = {
  "tpl-modern": "기본 · 전체 블러 + 좌측 앨범 + 우측 타이포",
  "tpl-01-left-photo": "① 좌측 사진 + 우측 타이포",
  "tpl-02-full-center": "② 사진 전체 + 중앙 대형 타이틀",
  "tpl-03-top-bottom": "③ 좌상단 소제목 + 하단 대형 제목",
  "tpl-04-center-card": "④ 중앙 세로 박스형",
  "tpl-05-stacked": "⑤ 대형 제목 겹침",
  "tpl-06-bottom-bar": "⑥ 사진 + 하단 흰색 타이틀",
  "tpl-07-polaroid": "⑦ 폴라로이드 / 사진첩",
  "tpl-08-minimal": "⑧ 미니멀 타이포",
};

const DIMS: Record<ThumbTemplateId, number> = {
  "tpl-modern": 0,
  "tpl-01-left-photo": 0.15,
  "tpl-02-full-center": 0.45,
  "tpl-03-top-bottom": 0.3,
  "tpl-04-center-card": 0.5,
  "tpl-05-stacked": 0.35,
  "tpl-06-bottom-bar": 0,
  "tpl-07-polaroid": 0.2,
  "tpl-08-minimal": 0.65,
};

function bgModeForTemplate(templateId: ThumbTemplateId): string {
  return templateId === "tpl-modern" ? "modern" : templateId;
}

function metaText(trackCount: number, durationLabel?: string) {
  const parts = ["가사 EN + KO", `${Math.max(1, trackCount)}곡`];
  if (durationLabel) parts.push(durationLabel);
  return parts.join("  ·  ");
}

/** 폴더명 "01 Smiled..." → "Smiled..." */
export function cleanTrackName(folderOrTitle: string): string {
  return folderOrTitle.replace(/^\d+[\s._-]+/, "").trim() || folderOrTitle;
}

export function trackNamesFromPaths(paths: string[]): string[] {
  return paths.map((p) => {
    const name = p.split(/[/\\]/).pop() || p;
    return cleanTrackName(name);
  });
}

function boxesForTemplate(
  templateId: ThumbTemplateId,
  title: string,
  subtitle: string,
  trackCount: number,
  trackNames: string[] = [],
  durationLabel?: string,
  footerText?: string,
): ThumbBox[] {
  const t = title || "Title";
  const s = subtitle || "";
  const meta = metaText(trackCount, durationLabel);
  const footer = footerText || "© My Channel";

  switch (templateId) {
    case "tpl-modern":
      return [
        { id: "tag", text: "FULL ALBUM", x: 636, y: 168, w: 596, h: 36, font_size: 24, bold: true, color: "#FFFFFF", align: "left" },
        { id: "title", text: t, x: 636, y: 216, w: 596, h: 72, font_size: 52, bold: true, color: "#FFFFFF", align: "left" },
        { id: "sub", text: s, x: 636, y: 280, w: 596, h: 56, font_size: 30, bold: true, color: "#FFFFFF", align: "left" },
        { id: "meta", text: meta, x: 636, y: 338, w: 596, h: 40, font_size: 22, bold: false, color: "#D2D2DA", align: "left" },
        { id: "footer", text: footer, x: 440, y: 678, w: 400, h: 28, font_size: 14, bold: false, color: "#A0A0A8", align: "center" },
      ];
    case "tpl-01-left-photo":
      return [
        { id: "title", text: t, x: 660, y: 190, w: 580, h: 200, font_size: 56, bold: true, color: "#FFFFFF", align: "left" },
        { id: "sub", text: s || "autumn pop\nplaylist", x: 660, y: 400, w: 580, h: 100, font_size: 30, bold: false, color: "#E8E0D4", align: "left" },
      ];
    case "tpl-02-full-center":
      return [
        { id: "title", text: t, x: 140, y: 250, w: 1000, h: 120, font_size: 64, bold: true, color: "#FFFFFF", align: "center" },
        { id: "line", text: "───────────────", x: 140, y: 370, w: 1000, h: 36, font_size: 22, bold: false, color: "#D8C8A8", align: "center" },
        { id: "sub", text: (s || "AUTUMN PLAYLIST").toUpperCase(), x: 140, y: 410, w: 1000, h: 60, font_size: 30, bold: false, color: "#F0EDE8", align: "center" },
      ];
    case "tpl-03-top-bottom":
      return [
        { id: "tag", text: (s || "AUTUMN PLAYLIST").toUpperCase(), x: 56, y: 44, w: 560, h: 44, font_size: 26, bold: true, color: "#FFFFFF", align: "left" },
        { id: "title", text: t, x: 56, y: 500, w: 760, h: 180, font_size: 58, bold: true, color: "#FFFFFF", align: "left" },
      ];
    case "tpl-04-center-card":
      return [
        { id: "card", text: "", x: 380, y: 175, w: 520, h: 370, font_size: 1, bold: false, color: "#FFFFFF", align: "center", fill: "rgba(0,0,0,0.58)" },
        { id: "title", text: t, x: 410, y: 230, w: 460, h: 140, font_size: 50, bold: true, color: "#FFFFFF", align: "center" },
        { id: "sub", text: (s || "AUTUMN POP").toUpperCase(), x: 410, y: 390, w: 460, h: 80, font_size: 28, bold: false, color: "#E0D8CC", align: "center" },
      ];
    case "tpl-05-stacked":
      return [
        { id: "title", text: t, x: 40, y: 260, w: 620, h: 320, font_size: 76, bold: true, color: "#FFFFFF", align: "left" },
        { id: "meta", text: trackCount > 1 ? meta : (s || "AUTUMN 2026").toUpperCase(), x: 640, y: 620, w: 600, h: 56, font_size: 30, bold: false, color: "#F5F0E8", align: "right" },
      ];
    case "tpl-06-bottom-bar":
      return [
        { id: "title", text: t, x: 48, y: 548, w: 1184, h: 72, font_size: 46, bold: true, color: "#1A1A1E", align: "left" },
        { id: "meta", text: s || meta, x: 48, y: 628, w: 1184, h: 48, font_size: 24, bold: false, color: "#4A4A52", align: "left" },
      ];
    case "tpl-07-polaroid":
      return [
        { id: "title", text: t, x: 160, y: 510, w: 960, h: 80, font_size: 44, bold: true, color: "#FFFFFF", align: "center" },
        { id: "sub", text: s || "autumn playlist", x: 160, y: 595, w: 960, h: 50, font_size: 28, bold: false, color: "#E8E4DC", align: "center" },
      ];
    case "tpl-08-minimal":
      return [
        { id: "title", text: t, x: 420, y: 200, w: 440, h: 210, font_size: 54, bold: true, color: "#FFFFFF", align: "center" },
        { id: "line", text: "─────", x: 420, y: 420, w: 440, h: 32, font_size: 20, bold: false, color: "#C8B890", align: "center" },
        { id: "sub", text: (s || "AUTUMN\nPLAYLIST").toUpperCase(), x: 420, y: 460, w: 440, h: 110, font_size: 32, bold: false, color: "#D8D4CC", align: "center" },
      ];
    default:
      return boxesForTemplate("tpl-modern", title, subtitle, trackCount, trackNames, durationLabel);
  }
}

export function buildTemplateCanvas(
  templateId: ThumbTemplateId,
  title: string,
  subtitle: string,
  imageName: string,
  trackCount = 1,
  trackNames: string[] = [],
  durationLabel?: string,
  footerText?: string,
): ThumbCanvasState & { template_id: ThumbTemplateId } {
  const n = trackNames.length || trackCount;
  return {
    layout: "canvas",
    template_id: templateId,
    title,
    subtitle,
    background: { image: imageName, mode: bgModeForTemplate(templateId), dim: DIMS[templateId] },
    boxes: boxesForTemplate(templateId, title, subtitle, n, trackNames, durationLabel, footerText),
  };
}

export function applyTemplate(
  canvas: ThumbCanvasState & { template_id?: string },
  templateId: ThumbTemplateId,
  trackCount = 1,
  trackNames: string[] = [],
  durationLabel?: string,
  footerText?: string,
): ThumbCanvasState & { template_id: ThumbTemplateId } {
  let title = canvas.title || "";
  let subtitle = canvas.subtitle || "";
  for (const b of canvas.boxes) {
    if (b.id === "title" && b.text) title = b.text;
    if ((b.id === "sub" || b.id === "subtitle") && b.text) subtitle = b.text;
  }
  // 여러 곡이면 앨범명을 제목으로 (제목이 첫 곡명이면 유지하되 tracklist는 채움)
  const imageName = canvas.background.image || "";
  const out = buildTemplateCanvas(
    templateId,
    title,
    subtitle,
    imageName,
    trackCount,
    trackNames,
    durationLabel,
    footerText,
  );
  out.title = title;
  out.subtitle = subtitle;
  return out;
}

export function currentTemplateId(canvas: { template_id?: string; background?: { mode?: string } }): ThumbTemplateId {
  const id = canvas.template_id || canvas.background?.mode;
  if (id === "modern") return "tpl-modern";
  if (id && THUMB_TEMPLATE_IDS.includes(id as ThumbTemplateId)) return id as ThumbTemplateId;
  return "tpl-modern";
}
