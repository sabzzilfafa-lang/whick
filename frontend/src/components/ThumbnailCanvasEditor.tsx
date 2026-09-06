import { useCallback, useEffect, useRef, useState } from "react";

export const THUMB_W = 1280;
export const THUMB_H = 720;

export type ThumbBox = {
  id: string;
  text: string;
  x: number;
  y: number;
  w: number;
  h: number;
  font_size: number;
  bold: boolean;
  color: string;
  align: "left" | "center" | "right";
  fill?: string;
};

export type ThumbBackground = {
  image: string;
  mode: string;
  dim: number;
};

export type ThumbCanvasState = {
  layout: "canvas";
  template_id?: string;
  background: ThumbBackground;
  boxes: ThumbBox[];
  title?: string;
  subtitle?: string;
};

type ImageOption = { path: string; name: string; label?: string; rel?: string };

type Props = {
  canvas: ThumbCanvasState;
  imageOptions: ImageOption[];
  mediaUrl: (path: string) => string;
  selectedId: string | null;
  onSelectId: (id: string | null) => void;
  onChange: (canvas: ThumbCanvasState) => void;
};

type ResizeCorner = "nw" | "ne" | "sw" | "se";
type DragMode =
  | { kind: "move"; id: string }
  | { kind: "resize"; id: string; corner: ResizeCorner }
  | null;

export function newTextBox(x = 400, y = 280): ThumbBox {
  return {
    id: `box_${Math.random().toString(36).slice(2, 9)}`,
    text: "텍스트",
    x,
    y,
    w: 320,
    h: 90,
    font_size: 32,
    bold: true,
    color: "#FFFFFF",
    align: "left",
  };
}

export default function ThumbnailCanvasEditor({
  canvas,
  imageOptions,
  mediaUrl,
  selectedId,
  onSelectId,
  onChange,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.5);
  const [drag, setDrag] = useState<DragMode>(null);
  const dragStart = useRef({ mx: 0, my: 0, box: null as ThumbBox | null });

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const w = el.clientWidth;
      setScale(Math.max(0.2, Math.min(1, w / THUMB_W)));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const updateBox = useCallback(
    (id: string, patch: Partial<ThumbBox>) => {
      onChange({
        ...canvas,
        boxes: canvas.boxes.map((b) => (b.id === id ? { ...b, ...patch } : b)),
      });
    },
    [canvas, onChange]
  );

  const startMove = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const box = canvas.boxes.find((b) => b.id === id);
    if (!box) return;
    onSelectId(id);
    dragStart.current = { mx: e.clientX, my: e.clientY, box: { ...box } };
    setDrag({ kind: "move", id });
  };

  const startResize = (id: string, corner: ResizeCorner, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const box = canvas.boxes.find((b) => b.id === id);
    if (!box) return;
    onSelectId(id);
    dragStart.current = { mx: e.clientX, my: e.clientY, box: { ...box } };
    setDrag({ kind: "resize", id, corner });
  };

  useEffect(() => {
    if (!drag) return;
    const onMove = (e: MouseEvent) => {
      const start = dragStart.current.box;
      if (!start) return;
      const dx = (e.clientX - dragStart.current.mx) / scale;
      const dy = (e.clientY - dragStart.current.my) / scale;
      if (drag.kind === "move") {
        updateBox(drag.id, {
          x: Math.round(Math.max(0, Math.min(THUMB_W - start.w, start.x + dx))),
          y: Math.round(Math.max(0, Math.min(THUMB_H - start.h, start.y + dy))),
        });
      } else {
        const minW = 80;
        const minH = 36;
        let { x, y, w, h } = start;
        const right = start.x + start.w;
        const bottom = start.y + start.h;
        if (drag.corner.includes("e")) {
          w = Math.round(Math.max(minW, Math.min(THUMB_W - start.x, start.w + dx)));
        }
        if (drag.corner.includes("s")) {
          h = Math.round(Math.max(minH, Math.min(THUMB_H - start.y, start.h + dy)));
        }
        if (drag.corner.includes("w")) {
          const nx = Math.round(Math.max(0, Math.min(right - minW, start.x + dx)));
          w = right - nx;
          x = nx;
        }
        if (drag.corner.includes("n")) {
          const ny = Math.round(Math.max(0, Math.min(bottom - minH, start.y + dy)));
          h = bottom - ny;
          y = ny;
        }
        updateBox(drag.id, { x, y, w, h });
      }
    };
    const onUp = () => setDrag(null);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [drag, scale, updateBox]);

  const bgKey = (canvas.background.image || "").replace(/\\/g, "/").toLowerCase();
  const bgOption =
    imageOptions.find((o) => {
      const path = (o.path || "").replace(/\\/g, "/").toLowerCase();
      const rel = (o.rel || "").replace(/\\/g, "/").toLowerCase();
      return path === bgKey || rel === bgKey || o.name.toLowerCase() === bgKey || o.name === canvas.background.image;
    }) || imageOptions[0];
  const bgUrl = bgOption ? mediaUrl(bgOption.path) : "";
  const mode = canvas.background.mode || "fill";
  const modeClass = `ppt-canvas-mode-${mode.replace(/[^a-z0-9-]/g, "")}`;

  return (
    <div
      className="ppt-canvas-wrap"
      ref={wrapRef}
      onClick={() => onSelectId(null)}
    >
      <div
        className={`ppt-canvas ${modeClass}`}
        style={{ width: THUMB_W * scale, height: THUMB_H * scale }}
      >
        {bgUrl && (
          <>
            {(mode === "tpl-01-left-photo") && (
              <>
                <img src={bgUrl} alt="" className="ppt-canvas-bg ppt-bg-left" draggable={false} />
                <img src={bgUrl} alt="" className="ppt-canvas-bg ppt-bg-right" draggable={false} />
              </>
            )}
            {(mode === "modern" || mode === "tpl-modern") && (
              <>
                <img src={bgUrl} alt="" className="ppt-canvas-bg ppt-bg-blur" draggable={false} />
                <div className="ppt-canvas-album-frame">
                  <img src={bgUrl} alt="" draggable={false} />
                </div>
              </>
            )}
            {mode !== "tpl-01-left-photo" && mode !== "modern" && mode !== "tpl-modern" && (
              <img
                src={bgUrl}
                alt=""
                className="ppt-canvas-bg"
                draggable={false}
                style={{ opacity: mode === "tpl-08-minimal" ? 0.35 : 1 }}
              />
            )}
          </>
        )}
        {mode === "tpl-06-bottom-bar" && <div className="ppt-canvas-bottom-bar" />}
        {mode === "tpl-07-polaroid" && bgUrl && (
          <div className="ppt-canvas-polaroid">
            <img src={bgUrl} alt="" draggable={false} />
          </div>
        )}
        <div
          className="ppt-canvas-dim"
          style={{
            opacity:
              mode === "tpl-06-bottom-bar" || mode === "tpl-08-minimal" || mode === "modern" || mode === "tpl-modern"
                ? 0
                : canvas.background.dim,
          }}
        />

        {canvas.boxes.map((box) => {
          const selected = box.id === selectedId;
          const isPanel = Boolean(box.fill) && !box.text.trim();
          const textStyle = {
            fontSize: box.font_size * scale,
            fontWeight: box.bold ? 700 : 400,
            color: box.color,
            textAlign: box.align as "left" | "center" | "right",
            whiteSpace: "pre-wrap" as const,
          };
          return (
            <div
              key={box.id}
              className={`ppt-box ${selected ? "selected" : ""} ${isPanel ? "ppt-box-panel" : ""}`}
              style={{
                left: box.x * scale,
                top: box.y * scale,
                width: box.w * scale,
                height: box.h * scale,
                background: box.fill || undefined,
              }}
              onClick={(e) => {
                e.stopPropagation();
                onSelectId(box.id);
              }}
              onMouseDown={(e) => {
                if (selected && (e.target as HTMLElement).closest("textarea")) return;
                startMove(box.id, e);
              }}
            >
              {isPanel ? (
                <div className="ppt-box-panel-handle" title="패널 이동" />
              ) : selected ? (
                <textarea
                  className="ppt-box-text"
                  value={box.text}
                  onChange={(e) => updateBox(box.id, { text: e.target.value })}
                  onMouseDown={(e) => e.stopPropagation()}
                  style={textStyle}
                  placeholder="Enter로 줄바꿈"
                />
              ) : (
                <div className="ppt-box-text ppt-box-preview" style={textStyle}>
                  {box.text || "\u00a0"}
                </div>
              )}
              {selected &&
                (["nw", "ne", "sw", "se"] as const).map((corner) => (
                  <div
                    key={corner}
                    className={`ppt-box-handle ppt-box-handle-${corner}`}
                    onMouseDown={(e) => startResize(box.id, corner, e)}
                    title="크기 조절"
                  />
                ))}
            </div>
          );
        })}
      </div>
      <p className="editor-hint ppt-hint">
        글상자 클릭 → 텍스트 편집 · 박스 드래그로 이동 · 네 꼭짓점으로 크기 조절
      </p>
    </div>
  );
}
