// 坚果云 WebDAV 云同步 —— 独立现代化 UI，不使用页面原有 .modal/.btn 等样式
// 对外暴露 window.JGY = { confirm, toast }

(function () {
  const SYNC_API = 'http://localhost:3000/api/sync';

  // ============================================================ 样式注入
  const css = `
  /* ---------- 遮罩 ---------- */
  .jgy-overlay {
    position: fixed; inset: 0; z-index: 10000;
    background: rgba(15, 23, 42, .46);
    backdrop-filter: blur(3px); -webkit-backdrop-filter: blur(3px);
    display: flex; align-items: center; justify-content: center;
    animation: jgy-fade .2s ease;
  }
  @keyframes jgy-fade { from { opacity: 0 } to { opacity: 1 } }
  @keyframes jgy-pop {
    from { opacity: 0; transform: translateY(14px) scale(.97) }
    to   { opacity: 1; transform: translateY(0) scale(1) }
  }

  /* ---------- 主面板 ---------- */
  .jgy-panel {
    width: 520px; max-width: 94vw; max-height: 92vh;
    background: #fff; border-radius: 18px; overflow: hidden;
    box-shadow: 0 24px 70px rgba(15, 23, 42, .28);
    display: flex; flex-direction: column;
    animation: jgy-pop .25s cubic-bezier(.21,1.02,.55,1);
  }
  .jgy-header {
    padding: 18px 20px; color: #fff; position: relative;
    background: linear-gradient(135deg, #4f46e5 0%, #2563eb 55%, #0ea5e9 100%);
  }
  .jgy-title { font-size: 17px; font-weight: 700; display:flex; align-items:center; gap:8px; }
  .jgy-subtitle { font-size: 12px; opacity: .85; margin-top: 3px; }
  .jgy-close {
    position: absolute; top: 14px; right: 14px;
    width: 30px; height: 30px; border-radius: 50%;
    background: rgba(255,255,255,.18) !important; color:#fff !important;
    font-size: 16px; line-height: 1; padding: 0 !important; min-width:0 !important;
    display:flex; align-items:center; justify-content:center;
    transition: background .2s;
  }
  .jgy-close:hover { background: rgba(255,255,255,.34) !important; }

  .jgy-body { padding: 18px 20px 6px; overflow-y: auto; }

  /* ---------- 状态条 ---------- */
  .jgy-status {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    background: #f1f5ff; border: 1px solid #e0e8ff;
    border-radius: 10px; padding: 9px 12px; font-size: 12.5px; color: #334155;
    margin-bottom: 14px;
  }
  .jgy-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
  .jgy-dot.on  { background: #22c55e; box-shadow: 0 0 0 3px rgba(34,197,94,.18) }
  .jgy-dot.off { background: #f43f5e; box-shadow: 0 0 0 3px rgba(244,63,94,.15) }
  .jgy-status .sep { color: #cbd5e1 }
  .jgy-status b { color: #1e293b }

  /* ---------- 输入框 ---------- */
  .jgy-field { position: relative; margin-bottom: 11px; }
  .jgy-field .ico {
    position: absolute; left: 11px; top: 50%; transform: translateY(-50%);
    font-size: 14px; opacity: .7; pointer-events:none;
  }
  .jgy-panel input.jgy-input {
    width: 100%; box-sizing: border-box; min-width: 0 !important;
    padding: 10px 12px 10px 34px; font-size: 13.5px;
    border: 1.5px solid #e2e8f0; border-radius: 10px; outline: none;
    background: #f8fafc; color: #1e293b; transition: all .18s;
  }
  .jgy-panel input.jgy-input:focus {
    border-color: #4f46e5; background: #fff;
    box-shadow: 0 0 0 3.5px rgba(79,70,229,.13);
  }

  /* ---------- 提示 callout ---------- */
  .jgy-hint {
    font-size: 12px; line-height: 1.65; color: #92400e;
    background: #fffbeb; border: 1px solid #fde68a; border-radius: 10px;
    padding: 9px 12px; margin-bottom: 13px;
  }
  .jgy-hint a { color: #2563eb; text-decoration: none; font-weight: 600 }

  /* ---------- 按钮 ---------- */
  .jgy-btn {
    border: none; border-radius: 10px; cursor: pointer;
    font-size: 13.5px; font-weight: 600; color: #fff;
    padding: 11px 14px !important; min-width: 0 !important;
    display: inline-flex; align-items: center; justify-content: center; gap: 7px;
    transition: transform .15s, box-shadow .15s, filter .15s;
  }
  .jgy-btn:hover { filter: brightness(1.06) }
  .jgy-btn:active { transform: scale(.98) }
  .jgy-btn:disabled { opacity: .55; cursor: not-allowed; filter: none }
  .jgy-btn.block { width: 100% }
  .jgy-btn.primary { background: linear-gradient(135deg,#4f46e5,#2563eb); box-shadow: 0 6px 16px rgba(37,99,235,.28) }
  .jgy-btn.ghost   { background: #f1f5f9 !important; color: #475569 !important }
  .jgy-btn.danger  { background: #fef2f2 !important; color: #e11d48 !important; border:1px solid #fecdd3 }

  /* ---------- 功能宫格 ---------- */
  .jgy-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px; }
  .jgy-tile {
    display: flex; align-items: center; gap: 11px; text-align: left;
    background: #fff !important; border: 1.5px solid #edf1f7; border-radius: 13px;
    padding: 12px !important; cursor: pointer; min-width: 0 !important;
    transition: all .18s;
  }
  .jgy-tile:hover { border-color: #c7d2fe; box-shadow: 0 8px 20px rgba(30,41,59,.09); transform: translateY(-2px) }
  .jgy-tile:disabled { opacity:.5; cursor:not-allowed; transform:none; box-shadow:none }
  .jgy-tile .badge {
    width: 38px; height: 38px; border-radius: 10px; flex: none;
    display:flex; align-items:center; justify-content:center; font-size: 18px;
  }
  .jgy-tile .t-name { font-size: 13.5px; font-weight: 700; color:#1e293b; line-height:1.3 }
  .jgy-tile .t-desc { font-size: 11px; color:#94a3b8; margin-top:2px }
  .b-sync  { background: #eef2ff } .b-sync .badge  { background: #4f46e5 }
  .b-up    { background: #ecfdf5 } .b-up .badge    { background: #10b981 }
  .b-down  { background: #fff7ed } .b-down .badge  { background: #f59e0b }
  .b-back  { background: #f8fafc } .b-back .badge  { background: #64748b }

  .jgy-logout-row { text-align:center; margin-bottom: 12px }

  /* ---------- 冲突卡片 ---------- */
  .jgy-conflict {
    border: 1.5px solid #fde68a; background: #fffbeb; border-radius: 12px;
    padding: 12px; margin-bottom: 11px;
  }
  .jgy-conflict .cf-title { font-size: 12.5px; color:#92400e; margin-bottom:9px; font-weight:600 }
  .jgy-conflict .cf-file {
    font-size: 12px; color:#475569; background:#fff; border:1px solid #f3e8c7;
    border-radius:7px; padding:5px 8px; margin-bottom:9px; word-break:break-all;
  }
  .jgy-conflict .cf-actions { display:flex; gap:8px }
  .jgy-conflict .cf-actions .jgy-btn { flex:1; padding:8px !important; font-size:12.5px }
  .jgy-btn.choose-local  { background:#4f46e5 }
  .jgy-btn.choose-remote { background:#f59e0b }

  /* ---------- 日志控制台 ---------- */
  .jgy-log-head {
    display:flex; align-items:center; justify-content:space-between;
    font-size: 12.5px; font-weight: 700; color:#475569; margin: 4px 0 7px;
  }
  .jgy-log-head button {
    background:#f1f5f9 !important; color:#64748b !important; border:none;
    border-radius:6px; padding:3px 10px !important; font-size:11.5px; cursor:pointer; min-width:0 !important;
  }
  .jgy-log {
    height: 145px; overflow:auto; background: #0f172a; border-radius: 11px;
    padding: 10px 12px; font-family: Consolas, "Courier New", monospace;
    font-size: 12px; line-height: 1.75; color:#cbd5e1; margin-bottom: 14px;
  }
  .jgy-log .lv { font-weight:700; margin-right:6px }
  .jgy-log .INFO { color:#7dd3fc } .jgy-log .OK { color:#86efac }
  .jgy-log .WARN { color:#fcd34d } .jgy-log .ERR  { color:#fda4af }

  .jgy-footer { padding: 0 20px 16px }

  /* ---------- 确认对话框 ---------- */
  .jgy-dialog {
    width: 390px; max-width: 92vw; background:#fff; border-radius: 16px;
    box-shadow: 0 24px 70px rgba(15,23,42,.3); overflow:hidden;
    animation: jgy-pop .22s cubic-bezier(.21,1.02,.55,1);
  }
  .jgy-dialog-body { padding: 22px 22px 8px; text-align:center }
  .jgy-dialog-icon {
    width: 52px; height: 52px; border-radius: 50%; margin: 0 auto 12px;
    display:flex; align-items:center; justify-content:center; font-size:26px;
  }
  .jgy-dialog-icon.warn { background:#fef3c7 } .jgy-dialog-icon.danger { background:#fee2e2 }
  .jgy-dialog-icon.info { background:#dbeafe }
  .jgy-dialog-title { font-size:16px; font-weight:700; color:#1e293b; margin-bottom:7px }
  .jgy-dialog-msg { font-size:13px; color:#64748b; line-height:1.65; word-break:break-word }
  .jgy-dialog-actions { display:flex; gap:10px; padding: 16px 22px 20px }
  .jgy-dialog-actions .jgy-btn { flex:1; padding:10px !important }
  .jgy-btn.cancel { background:#f1f5f9 !important; color:#475569 !important }
  .jgy-btn.confirm-warn { background: linear-gradient(135deg,#f59e0b,#ea580c) }
  .jgy-btn.confirm-danger { background: linear-gradient(135deg,#f43f5e,#e11d48) }
  .jgy-btn.confirm-info { background: linear-gradient(135deg,#4f46e5,#2563eb) }

  /* ---------- 输入框对话框（新建/重命名分组用） ---------- */
  .jgy-dialog-input { padding: 22px 22px 4px; text-align:left }
  .jgy-dialog-input .jgy-dialog-title { text-align:center; margin-bottom:14px }
  .jgy-dialog-input .jgy-dialog-msg { text-align:center; margin-bottom:14px; font-size:12.5px }
  .jgy-dialog-input input.jgy-input {
    width:100%; min-width:0; max-width:100%; box-sizing:border-box;
    padding: 11px 13px; border-radius: 10px;
    border:1px solid #dbe3ee; background:#f8fafd; font-size:14px; color:#1e293b;
    outline:none; transition: border-color .18s, box-shadow .18s, background .18s;
  }
  .jgy-dialog-input input.jgy-input:focus {
    border-color:#93b4f7; background:#fff;
    box-shadow: 0 0 0 3px rgba(59,130,246,.14);
  }
  .jgy-dialog-input .jgy-err {
    color:#e11d48; font-size:12px; min-height:16px; margin-top:6px;
  }

  /* ---------- Toast ---------- */
  .jgy-toast-wrap {
    position: fixed; top: 22px; left: 50%; transform: translateX(-50%);
    z-index: 10002; display:flex; flex-direction:column; align-items:center; gap:9px; pointer-events:none;
  }
  .jgy-toast {
    display:flex; align-items:center; gap:9px; padding: 10px 18px;
    border-radius: 999px; color:#fff; font-size:13px; font-weight:600;
    box-shadow: 0 10px 30px rgba(15,23,42,.25);
    animation: jgy-toast-in .28s cubic-bezier(.21,1.02,.55,1);
  }
  @keyframes jgy-toast-in {
    from { opacity:0; transform: translateY(-16px) }
    to   { opacity:1; transform: translateY(0) }
  }
  .jgy-toast.success { background: linear-gradient(135deg,#10b981,#059669) }
  .jgy-toast.error   { background: linear-gradient(135deg,#f43f5e,#e11d48) }
  .jgy-toast.warn    { background: linear-gradient(135deg,#f59e0b,#d97706) }
  .jgy-toast.info    { background: linear-gradient(135deg,#4f46e5,#2563eb) }
  `;
  const styleEl = document.createElement('style');
  styleEl.textContent = css;
  document.head.appendChild(styleEl);

  // ============================================================ 通用 UI 组件

  // ---------- Toast
  function toast(message, type = 'info', duration = 2800) {
    let wrap = document.querySelector('.jgy-toast-wrap');
    if (!wrap) {
      wrap = document.createElement('div');
      wrap.className = 'jgy-toast-wrap';
      document.body.appendChild(wrap);
    }
    const icons = { success: '✅', error: '⛔', warn: '⚠️', info: 'ℹ️' };
    const el = document.createElement('div');
    el.className = 'jgy-toast ' + type;
    el.innerHTML = `<span>${icons[type] || 'ℹ️'}</span><span></span>`;
    el.querySelector('span:last-child').textContent = message;
    wrap.appendChild(el);
    setTimeout(() => {
      el.style.transition = 'opacity .25s, transform .25s';
      el.style.opacity = '0';
      el.style.transform = 'translateY(-10px)';
      setTimeout(() => el.remove(), 260);
    }, duration);
  }

  // ---------- 自定义确认框（Promise）
  function confirmDialog(options) {
    const {
      title = '请确认', message = '',
      confirmText = '确定', cancelText = '取消',
      type = 'warn', // warn / danger / info
    } = options || {};
    return new Promise(resolve => {
      const overlay = document.createElement('div');
      overlay.className = 'jgy-overlay';
      const iconMap = { warn: '⚠️', danger: '🗑️', info: '❓' };
      overlay.innerHTML = `
        <div class="jgy-dialog">
          <div class="jgy-dialog-body">
            <div class="jgy-dialog-icon ${type}">${iconMap[type]}</div>
            <div class="jgy-dialog-title"></div>
            <div class="jgy-dialog-msg"></div>
          </div>
          <div class="jgy-dialog-actions">
            <button class="jgy-btn cancel">${cancelText}</button>
            <button class="jgy-btn confirm-${type}">${confirmText}</button>
          </div>
        </div>`;
      overlay.querySelector('.jgy-dialog-title').textContent = title;
      overlay.querySelector('.jgy-dialog-msg').textContent = message;
      document.body.appendChild(overlay);

      function close(val) {
        overlay.style.animation = 'jgy-fade .18s reverse';
        setTimeout(() => overlay.remove(), 160);
        resolve(val);
      }
      overlay.querySelector('.cancel').onclick = () => close(false);
      overlay.querySelector('.confirm-' + type).onclick = () => close(true);
    });
  }

  // ---------- 输入框对话框（Promise，返回输入的字符串或 null）
  function promptDialog(options) {
    const {
      title = '请输入', message = '', value = '',
      placeholder = '', confirmText = '确定', cancelText = '取消', type = 'info',
    } = options || {};
    return new Promise(resolve => {
      const overlay = document.createElement('div');
      overlay.className = 'jgy-overlay';
      overlay.innerHTML = `
        <div class="jgy-dialog">
          <div class="jgy-dialog-input">
            <div class="jgy-dialog-title"></div>
            <div class="jgy-dialog-msg"></div>
            <input type="text" class="jgy-input" spellcheck="false" autocomplete="off">
            <div class="jgy-err"></div>
          </div>
          <div class="jgy-dialog-actions">
            <button class="jgy-btn cancel">${cancelText}</button>
            <button class="jgy-btn confirm-${type}">${confirmText}</button>
          </div>
        </div>`;
      overlay.querySelector('.jgy-dialog-title').textContent = title;
      const msgEl = overlay.querySelector('.jgy-dialog-msg');
      if (message) msgEl.textContent = message; else msgEl.remove();
      const input = overlay.querySelector('input.jgy-input');
      input.placeholder = placeholder;
      input.value = value;
      document.body.appendChild(overlay);

      function close(val) {
        overlay.style.animation = 'jgy-fade .18s reverse';
        setTimeout(() => overlay.remove(), 160);
        resolve(val);
      }
      const submit = () => {
        const v = input.value.trim();
        if (!v) {
          overlay.querySelector('.jgy-err').textContent = '不能为空';
          input.focus();
          return;
        }
        close(v);
      };
      input.addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); submit(); }
        if (e.key === 'Escape') { e.preventDefault(); close(null); }
      });
      overlay.querySelector('.cancel').onclick = () => close(null);
      overlay.querySelector('.confirm-' + type).onclick = submit;
      setTimeout(() => { input.focus(); input.select(); }, 30);
    });
  }

  // ============================================================ 主弹窗

  let panelOverlay = null;

  function buildPanel() {
    panelOverlay = document.createElement('div');
    panelOverlay.className = 'jgy-overlay';
    panelOverlay.style.display = 'none';
    panelOverlay.innerHTML = `
      <div class="jgy-panel">
        <div class="jgy-header">
          <div class="jgy-title">☁️ 坚果云同步</div>
          <div class="jgy-subtitle">WebDAV 安全连接 · 书签与图标云端备份</div>
          <button class="jgy-close" title="关闭">✕</button>
        </div>

        <div class="jgy-body">
          <div class="jgy-status" id="jgyStatus"></div>

          <!-- 未登录 -->
          <div id="jgyLoginView">
            <form autocomplete="off" onsubmit="return false;">
            <div class="jgy-field">
              <span class="ico">✉️</span>
              <input class="jgy-input" id="jgyEmail" type="text" name="jgy-account"
                     placeholder="坚果云登录邮箱" autocomplete="off" spellcheck="false">
            </div>
            <div class="jgy-field">
              <span class="ico">🔑</span>
              <input class="jgy-input" id="jgyPassword" type="password" name="jgy-appsecret"
                     placeholder="WebDAV 应用密码（非登录密码）" autocomplete="new-password">
            </div>
            </form>
            <div class="jgy-hint">
              获取应用密码：登录
              <a href="https://www.jianguoyun.com/d/home#/security" target="_blank">坚果云网页端</a>
              → 右上角账户信息 → 安全选项 → 添加应用，把生成的密码粘贴到上方。
            </div>
            <button class="jgy-btn primary block" id="jgyBtnLogin">🔓 登录并连接</button>
          </div>

          <!-- 已登录 -->
          <div id="jgyActionView" style="display:none;">
            <div class="jgy-grid">
              <button class="jgy-tile b-sync" id="jgyBtnSync">
                <span class="badge">🔄</span>
                <span><div class="t-name">立即同步</div><div class="t-desc">智能双向合并</div></span>
              </button>
              <button class="jgy-tile b-up" id="jgyBtnUpload">
                <span class="badge">⬆️</span>
                <span><div class="t-name">上传到云端</div><div class="t-desc">只传新增/修改</div></span>
              </button>
              <button class="jgy-tile b-down" id="jgyBtnDownload">
                <span class="badge">⬇️</span>
                <span><div class="t-name">下载到本地</div><div class="t-desc">只拉新增/修改</div></span>
              </button>
              <button class="jgy-tile b-back" id="jgyBtnBackup">
                <span class="badge">💾</span>
                <span><div class="t-name">本地备份</div><div class="t-desc">时间戳快照</div></span>
              </button>
            </div>
            <div id="jgyConflictBox"></div>
            <div class="jgy-logout-row">
              <button class="jgy-btn danger" id="jgyBtnLogout">退出登录并清除凭据</button>
            </div>
          </div>

          <div class="jgy-log-head">
            <span>🖥️ 操作日志</span>
            <button id="jgyBtnClearLog">清空</button>
          </div>
          <div class="jgy-log" id="jgyLog"></div>
        </div>

        <div class="jgy-footer">
          <button class="jgy-btn ghost block" id="jgyBtnClose">关 闭</button>
        </div>
      </div>`;
    document.body.appendChild(panelOverlay);
    bindPanelEvents();
  }

  // ---------- 日志
  function log(message, level = 'INFO') {
    const box = document.getElementById('jgyLog');
    const time = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    const line = document.createElement('div');
    line.innerHTML = `<span class="lv ${level}">${level}</span><span class="msg"></span>`;
    line.querySelector('.msg').textContent = `${time}  ${message}`;
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
  }

  // ---------- 忙碌状态
  function setBusy(busy) {
    panelOverlay.querySelectorAll('button').forEach(b => b.disabled = busy);
  }

  // ---------- 状态刷新
  async function refreshStatus() {
    const el = document.getElementById('jgyStatus');
    try {
      const r = await fetch(SYNC_API + '/status');
      const s = await r.json();
      document.getElementById('jgyLoginView').style.display = s.logged_in ? 'none' : 'block';
      document.getElementById('jgyActionView').style.display = s.logged_in ? 'block' : 'none';
      const dot = s.logged_in ? '<span class="jgy-dot on"></span><b>已连接</b>'
                              : '<span class="jgy-dot off"></span><b>未连接</b>';
      const localN = typeof s.local_count === 'number' ? s.local_count : '—';
      const remoteN = typeof s.remote_count === 'number' ? s.remote_count : '—';
      el.innerHTML = dot +
        (s.logged_in
          ? `<span class="sep">|</span><span>${s.email}</span>` +
            `<span class="sep">|</span><span>本地收藏 <b>${localN}</b> 个</span>` +
            `<span class="sep">|</span><span>云端收藏 <b>${remoteN}</b> 个</span>` +
            (s.last_sync ? `<span class="sep">|</span><span>上次同步 ${s.last_sync}</span>` : '')
          : `<span class="sep">|</span><span>登录后可同步书签</span>`);
      return s;
    } catch (e) {
      el.innerHTML = '<span class="jgy-dot off"></span><b>状态获取失败</b>';
      return null;
    }
  }

  // ---------- 接口封装
  async function post(path, body) {
    const r = await fetch(SYNC_API + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const err = new Error(data.error || ('请求失败 ' + r.status));
      err.data = data;
      err.status = r.status;
      throw err;
    }
    return data;
  }

  // ---------- 冲突 UI
  function showConflicts(items, thenResolutions) {
    // items: [{key, label}]
    const box = document.getElementById('jgyConflictBox');
    box.innerHTML = '';
    const chosen = {};
    items.forEach(item => {
      const card = document.createElement('div');
      card.className = 'jgy-conflict';
      card.innerHTML = `
        <div class="cf-title">⚠️ 本地与云端均已修改：</div>
        <div class="cf-file"></div>
        <div class="cf-actions">
          <button class="jgy-btn choose-local">保留本地</button>
          <button class="jgy-btn choose-remote">使用云端</button>
        </div>`;
      card.querySelector('.cf-file').textContent = item.label;
      card.querySelector('.choose-local').onclick = () => {
        chosen[item.key] = 'local'; card.style.opacity = .45; tryFinish();
      };
      card.querySelector('.choose-remote').onclick = () => {
        chosen[item.key] = 'remote'; card.style.opacity = .45; tryFinish();
      };
      box.appendChild(card);
    });

    function tryFinish() {
      if (Object.keys(chosen).length === items.length) {
        box.innerHTML = '';
        thenResolutions(chosen);
      }
    }
  }

  // ---------- 同步结果处理
  function handleSyncResult(data) {
    const r = data.result || {};
    (r.uploaded || []).forEach(p => log('已上传：' + p, 'OK'));
    (r.downloaded || []).forEach(p => log('已下载：' + p, 'OK'));
    (r.backups || []).forEach(p => log('已备份：' + p, 'WARN'));
    const total = (r.uploaded || []).length + (r.downloaded || []).length;
    log(total === 0 ? '本地与云端已是最新，无需同步。' : '同步完成。', total ? 'OK' : 'INFO');
    if ((r.downloaded || []).length && typeof loadData === 'function') loadData();
    refreshStatus();
  }

  async function doSync() {
    setBusy(true);
    log('开始双向同步...');
    try {
      const data = await post('/sync', {});
      handleSyncResult(data);
    } catch (e) {
      if (e.status === 409 && e.data.conflicts && e.data.conflicts.length) {
        log(`检测到 ${e.data.conflicts.length} 个冲突，请逐个选择。`, 'WARN');
        showConflicts(e.data.conflicts, async resolutions => {
          setBusy(true);
          try {
            log('冲突已处理，继续同步...');
            const data = await post('/sync', { resolutions });
            handleSyncResult(data);
          } catch (e2) {
            log('同步失败：' + e2.message, 'ERR');
            toast('同步失败：' + e2.message, 'error');
            setBusy(false);
          }
        });
        setBusy(false);
        return;
      }
      log('同步失败：' + e.message, 'ERR');
      toast('同步失败', 'error');
    }
    setBusy(false);
  }

  // ---------- 事件绑定
  function bindPanelEvents() {
    const close = () => { panelOverlay.style.display = 'none'; };
    panelOverlay.querySelector('.jgy-close').onclick = close;
    document.getElementById('jgyBtnClose').onclick = close;
    panelOverlay.addEventListener('click', e => {
      if (e.target === panelOverlay) close();
    });

    document.getElementById('jgyBtnClearLog').onclick = () => {
      document.getElementById('jgyLog').innerHTML = '';
    };

    // 登录
    document.getElementById('jgyBtnLogin').onclick = async () => {
      const email = document.getElementById('jgyEmail').value.trim();
      const password = document.getElementById('jgyPassword').value.trim();
      if (!email || !password) { toast('请输入邮箱和应用密码', 'error'); return; }
      setBusy(true);
      try {
        await post('/login', { email, password });
        log('登录成功：' + email, 'OK');
        toast('登录成功', 'success');
        document.getElementById('jgyPassword').value = '';
        await refreshStatus();
      } catch (e) {
        log('登录失败：' + e.message, 'ERR');
        toast('登录失败：邮箱或应用密码错误', 'error');
      }
      setBusy(false);
    };

    // 退出
    document.getElementById('jgyBtnLogout').onclick = async () => {
      const ok = await confirmDialog({
        title: '退出坚果云登录？',
        message: '将清除本机保存的邮箱与应用密码，已同步的云端文件不受影响。',
        confirmText: '退出登录', type: 'danger'
      });
      if (!ok) return;
      setBusy(true);
      try {
        await post('/logout', {});
        log('已退出登录，凭据已清除。', 'WARN');
        toast('已退出登录', 'info');
        await refreshStatus();
      } catch (e) {
        log('退出失败：' + e.message, 'ERR');
      }
      setBusy(false);
    };

    // 同步
    document.getElementById('jgyBtnSync').onclick = doSync;

    // 强制上传（后台执行 + 轮询进度，图标多时要跑几分钟）
    document.getElementById('jgyBtnUpload').onclick = async () => {
      setBusy(true);
      log('开始上传（仅增量）...');
      try {
        const started = await post('/upload', { background: true });
        if (started && started.started === false && started.error) throw new Error(started.error);

        let lastMsg = '';
        const t0 = Date.now();
        while (true) {
          await new Promise(r => setTimeout(r, 1000));
          let prog;
          try {
            const resp = await fetch(SYNC_API + '/progress');
            prog = await resp.json();
          } catch (e) {
            continue;
          }
          if (prog.message && prog.message !== lastMsg) {
            lastMsg = prog.message;
            log(prog.message, 'INFO');
          }
          if (!prog.running) break;
          if (Date.now() - t0 > 15 * 60 * 1000) break;
        }

        const resp2 = await fetch(SYNC_API + '/progress');
        const p = await resp2.json();
        const r = p.result || {};
        const failed = (r.failed || []);
        failed.forEach(f => log('上传失败：' + f.path + '（' + f.error + '）', 'ERR'));

        if (p.error) {
          log('上传失败：' + p.error, 'ERR');
          toast(p.error, 'error');
          if (p.wait_seconds) {
            log(`坚果云正在限流，约 ${Math.max(1, Math.round(p.wait_seconds / 60))} 分钟后可再次点击上传。`, 'WARN');
          }
        } else if (r.rate_limited) {
          log(`已上传 ${(r.uploaded || []).length} 个，因限流暂停。剩余 ${r.remaining || 0} 个待续传。`, 'WARN');
          log('稍后再点一次「上传到云端」会自动续传，已传成功的不会重复上传。', 'WARN');
          toast(`限流暂停：已传 ${(r.uploaded || []).length} 个，${r.remaining || 0} 个待续传`, 'warn');
        } else {
          log(`上传完成，共 ${(r.uploaded || []).length} 个文件。`, 'OK');
          if (failed.length) {
            log(`有 ${failed.length} 个文件未传成功，稍后再点一次上传会自动续传。`, 'WARN');
            toast(`已传 ${(r.uploaded || []).length} 个，${failed.length} 个待续传`, 'warn');
          } else {
            toast('上传完成', 'success');
          }
        }
        refreshStatus();
      } catch (e) {
        log('上传失败：' + e.message, 'ERR');
        toast(e.message || '上传失败', 'error');
      }
      setBusy(false);
    };

    // 强制下载
    document.getElementById('jgyBtnDownload').onclick = async () => {
      const ok = await confirmDialog({
        title: '确认从云端下载覆盖本地？',
        message: '云端 bookmark_api 中的 links.json 与图标将覆盖本地，覆盖前会自动完整备份本地内容。',
        confirmText: '确认下载覆盖', type: 'warn'
      });
      if (!ok) return;
      setBusy(true);
      log('开始下载（仅增量）...');
      try {
        const data = await post('/download', {});
        const r = data.result || {};
        (r.downloaded || []).forEach(p => log('已下载：' + p, 'OK'));
        (r.backups || []).forEach(p => log('本地旧内容已备份：' + p, 'WARN'));
        log('下载完成，共 ' + (r.downloaded || []).length + ' 个文件。', 'OK');
        toast('下载完成', 'success');
        if (typeof loadData === 'function') loadData();
        refreshStatus();
      } catch (e) {
        log('下载失败：' + e.message, 'ERR');
        toast('下载失败', 'error');
      }
      setBusy(false);
    };

    // 本地备份
    document.getElementById('jgyBtnBackup').onclick = async () => {
      setBusy(true);
      try {
        const data = await post('/backup', {});
        log('已备份到：' + data.backup, 'OK');
        toast('备份完成', 'success');
      } catch (e) {
        log('备份失败：' + e.message, 'ERR');
        toast('备份失败', 'error');
      }
      setBusy(false);
    };
  }

  // ============================================================ 入口按钮

  function injectEntryButton() {
    const btn = document.createElement('button');
    btn.id = 'jgyEntryBtn';
    btn.type = 'button';
    btn.className = 'collect-btn';
    btn.style.marginLeft = '8px';
    btn.innerHTML = '☁️ 云同步';
    btn.onclick = () => {
      panelOverlay.style.display = 'flex';
      refreshStatus();
    };
    const anchor = document.getElementById('collectBtn');
    anchor.parentNode.insertBefore(btn, anchor.nextSibling);
  }

  window.addEventListener('DOMContentLoaded', () => {
    buildPanel();
    injectEntryButton();
  });

  // 对外暴露
  window.JGY = { confirm: confirmDialog, toast, prompt: promptDialog };
})();
