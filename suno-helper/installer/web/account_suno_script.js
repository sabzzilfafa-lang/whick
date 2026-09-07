  // ===== Suno Helper PC 등록 =====
  var sunoStatusEl = document.getElementById('sunoStatus'),
      sunoErrEl = document.getElementById('sunoErr'),
      sunoOut = document.getElementById('sunoTokenOut'),
      sunoTokenEl = document.getElementById('sunoToken'),
      sunoPcBox = document.getElementById('sunoPcBox');
  function sunoShowErr(m) { sunoErrEl.textContent = m; sunoErrEl.hidden = false; }
  async function sunoLoad() {
    if (!token) return;
    try {
      var r = await fetch('/api/suno/status', { headers: { Authorization: 'Bearer ' + token } });
      var j = await r.json();
      if (!j.ok) throw 0;
      var lic = j.data.license;
      if (lic) {
        var d = new Date(lic.renewed_at);
        d.setMonth(d.getMonth() + 1);
        sunoStatusEl.innerHTML = '<strong style="color:#2fbf71;">등록됨</strong> &mdash; 기기 <code>' +
          String(lic.machine_hash).slice(0, 8) + '</code> &middot; 갱신 ' + d.toLocaleDateString();
        document.getElementById('btnSunoDeactivate').style.display = '';
      } else {
        sunoStatusEl.textContent = '등록된 PC가 없습니다. 아래 버튼으로 토큰을 발급하세요.';
        document.getElementById('btnSunoDeactivate').style.display = 'none';
      }
      sunoPcBox.hidden = false;
    } catch (e) { sunoPcBox.hidden = true; }
  }
  document.getElementById('btnSunoToken').addEventListener('click', async function () {
    sunoErrEl.hidden = true; sunoOut.style.display = 'none';
    this.disabled = true;
    try {
      var r = await fetch('/api/suno/token/new', { method: 'POST', headers: { Authorization: 'Bearer ' + token } });
      var j = await r.json();
      if (!j.ok) throw new Error((j.error && j.error.message) || '발급 실패');
      sunoTokenEl.value = j.data.token;
      sunoOut.style.display = '';
    } catch (e) { sunoShowErr(e.message || '발급 실패'); }
    finally { this.disabled = false; }
  });
  document.getElementById('btnSunoCopy').addEventListener('click', function () {
    navigator.clipboard.writeText(sunoTokenEl.value).then(function () {
      document.getElementById('btnSunoCopy').textContent = '복사됨!';
      setTimeout(function () { document.getElementById('btnSunoCopy').textContent = '복사'; }, 1500);
    });
  });
  document.getElementById('btnSunoDeactivate').addEventListener('click', async function () {
    if (!confirm('등록된 PC를 해지하면 그 PC에서 새 작업을 만들 수 없습니다. 해지하시겠습니까?')) return;
    try {
      var r = await fetch('/api/suno/deactivate', { method: 'POST', headers: { Authorization: 'Bearer ' + token } });
      var j = await r.json();
      if (!j.ok) throw new Error('해지 실패');
      sunoLoad();
    } catch (e) { sunoShowErr(e.message || '해지 실패'); }
  });
