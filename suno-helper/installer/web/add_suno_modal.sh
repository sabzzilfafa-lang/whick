#!/bin/bash
# index.html: Suno Helper 제품 카드 → iframe 모달로 suno.html 열기
set -e
HTML=/data/whick-ai/2_control_center/git-home/index.html
cp "$HTML" "${HTML}.bak-suno-modal"

python3 - <<'PY'
import re
from pathlib import Path

p = Path("/data/whick-ai/2_control_center/git-home/index.html")
src = p.read_text(encoding="utf-8", errors="replace")

# 1) 모달 CSS/HTML/JS 가 이미 있는지
if "sunoModal" in src:
    print("modal already present")
else:
    # 2) 카드 href="#suno" → href="#sunoModal-open" (JS에서 가로챔). 그대로 둬도 JS가 막으므로 유지.
    # 3) </body> 직전에 모달 마크업+스크립트 삽입
    modal = """
<!-- Suno Helper preview modal (opens suno.html in iframe) -->
<div id="sunoModal" style="display:none;position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,.72);" role="dialog" aria-modal="true">
  <div id="sunoModalBox" style="position:absolute;top:4vh;left:50%;transform:translateX(-50%);width:min(1080px,94vw);height:92vh;background:var(--bg,#0d1117);border:1px solid var(--line,#2d333b);border-radius:14px;overflow:hidden;box-shadow:0 18px 60px rgba(0,0,0,.55);">
    <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;border-bottom:1px solid var(--line,#2d333b);background:var(--card,#1c2129);">
      <strong style="font-size:.9rem;">&#127925; Suno Helper <span style="color:var(--tx2,#9aa4b2);font-weight:400;">by Whick</span></strong>
      <div style="display:flex;gap:8px;">
        <a id="sunoModalFull" href="/suno.html" target="_blank" rel="noopener" style="font-size:.8rem;color:var(--tx2,#9aa4b2);text-decoration:none;align-self:center;">&#8599; full page</a>
        <button id="sunoModalClose" class="btn btn-secondary" style="font-size:.8rem;padding:4px 10px;">&#10005;</button>
      </div>
    </div>
    <iframe id="sunoModalFrame" src="about:blank" title="Suno Helper" style="width:100%;height:calc(100% - 42px);border:0;display:block;background:var(--bg,#0d1117);"></iframe>
  </div>
</div>
<script>
(function () {
  'use strict';
  var modal = document.getElementById('sunoModal'),
      frame = document.getElementById('sunoModalFrame'),
      closeBtn = document.getElementById('sunoModalClose');

  function openSunoModal(e) {
    if (e) e.preventDefault();
    frame.src = '/suno.html';
    modal.style.display = 'block';
    document.body.style.overflow = 'hidden';
    history.replaceState(null, '', '#suno');
  }
  function closeSunoModal() {
    modal.style.display = 'none';
    frame.src = 'about:blank';
    document.body.style.overflow = '';
    history.replaceState(null, '', location.pathname + location.search);
  }

  // 제품 카드(Suno)와 #suno 앵커 링크 → 모달로
  document.addEventListener('click', function (ev) {
    var a = ev.target.closest ? ev.target.closest('a[href="#suno"], a[href$="#suno"]') : null;
    if (!a) return;
    ev.preventDefault();
    openSunoModal();
  });
  closeBtn.addEventListener('click', closeSunoModal);
  modal.addEventListener('click', function (ev) { if (ev.target === modal) closeSunoModal(); });
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && modal.style.display !== 'none') closeSunoModal();
  });
  // URL에 #suno 로 직접 진입한 경우에도 모달 오픈
  if (location.hash === '#suno') openSunoModal();
})();
</script>
"""
    idx = src.rfind("</body>")
    assert idx > 0, "no </body>"
    src = src[:idx] + modal + "\n" + src[idx:]
    p.write_bytes(src.encode("utf-8"))
    print("modal injected into index.html")

# 4) 검증: 스크립트 블록 문법
import subprocess, tempfile, os
scripts = re.findall(r"<script>(.*?)</script>", src, re.S)
code = "\n;\n".join(scripts)
Path("/tmp/idx_chk.js").write_text(code, encoding="utf-8")
r = subprocess.run(["node", "--check", "/tmp/idx_chk.js"], capture_output=True, text=True)
print("syntax:", "OK" if r.returncode == 0 else r.stderr[:300])
PY

echo "==== 서빙 확인 ===="
curl -s https://whick.org/index.html | grep -c sunoModal || true
curl -s -o /dev/null -w "suno.html HTTP %{http_code}\n" https://whick.org/suno.html
curl -s https://whick.org/suno.html | grep -c "data-i18n" || true
echo MODAL_DONE
