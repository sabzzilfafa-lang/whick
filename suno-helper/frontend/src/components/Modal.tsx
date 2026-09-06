import { useEffect, useRef } from "react";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  /** true면 오버레이 클릭으로 닫지 않음 (실수 방지) */
  disableOverlayClose?: boolean;
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
    // number 등도 글자 삭제는 허용
    return true;
  }
  if (target.isContentEditable) return true;
  return Boolean(target.closest("input, textarea, select, [contenteditable='true']"));
}

export default function Modal({
  open,
  onClose,
  title,
  children,
  disableOverlayClose = false,
}: ModalProps) {
  // 입력란에서 드래그하다 오버레이에서 mouseup 되면 click이 떠 모달이 닫히는 것 방지
  const overlayMouseDownRef = useRef(false);

  useEffect(() => {
    if (!open) return;

    const onKeyDown = (e: KeyboardEvent) => {
      // 입력란 밖에서 Backspace → 브라우저/앱 뒤로가기 차단
      if (e.key !== "Backspace") return;
      if (isEditableTarget(e.target)) return;
      e.preventDefault();
      e.stopPropagation();
    };

    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [open]);

  useEffect(() => {
    if (!open) overlayMouseDownRef.current = false;
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        overlayMouseDownRef.current = e.target === e.currentTarget;
      }}
      onClick={(e) => {
        if (disableOverlayClose) return;
        // 오버레이에서 mousedown → mouseup(click)한 경우에만 닫기
        if (e.target === e.currentTarget && overlayMouseDownRef.current) {
          onClose();
        }
        overlayMouseDownRef.current = false;
      }}
    >
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>{title}</h3>
        {children}
      </div>
    </div>
  );
}
