    // 表单提交处理

let server = 'http://localhost:3000/api/links';

// ---------- 分组 / 筛选状态 ----------
let allData = [];
let activeGroup = '首页';
let filterText = '';
let expanded = new Set();
// 拖拽状态：卡片拖到左侧分组上 = 改所属分组
let draggingCardId = null;
let groupDropDone = false;

// ---------- 图标自动探测 ----------
function updateIconPreview() {
  const el = document.getElementById('collectIcon');
  const img = document.getElementById('iconPreview');
  if (!el || !img) return;
  const v = (el.value || '').trim();
  if (!v) { img.style.display = 'none'; img.removeAttribute('src'); return; }
  if (/^https?:\/\//i.test(v) || v.startsWith('data:')) {
    img.src = v;
  } else if (/^[A-Za-z]:[\\/]/.test(v) || v.startsWith('\\\\')) {
    // 本地路径：浏览器读不到 D:\，走后端预览
    img.src = '/api/links/icon-preview?path=' + encodeURIComponent(v) + '&t=' + Date.now();
  } else if (v.startsWith('static/')) {
    img.src = v;
  } else {
    img.style.display = 'none';
    return;
  }
  img.style.display = 'block';
  img.onerror = () => { img.style.display = 'none'; };
}

// 轻提示，优先用同步模块自绘的 toast（避免浏览器原生弹框）
function tip(msg, type) {
  if (window.JGY && typeof window.JGY.toast === 'function') {
    window.JGY.toast(msg, type || 'info');
  } else {
    console.log(msg);
  }
}

async function autoFetchIcon(e) {
  if (e) e.preventDefault();
  const urlEl = document.getElementById('collectUrl');
  const iconEl = document.getElementById('collectIcon');
  const btn = e && e.target ? e.target : null;
  const url = (urlEl.value || '').trim();
  if (!url) { tip('请先填写网站地址', 'warn'); urlEl.focus(); return; }
  const oldText = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = '探测中…'; }
  try {
    const r = await fetch('/api/links/favicon?url=' + encodeURIComponent(url));
    const data = await r.json();
    if (!r.ok || !data.icon) throw new Error(data.error || '未找到图标');
    // 只回填图标链接，保存时才下载到本地 icon 目录
    iconEl.value = data.icon;
    autoIconValue = data.icon;
    updateIconPreview();
    tip('已找到网站图标，保存时会自动下载到本地', 'success');
  } catch (err) {
    tip('没找到该网站的图标，可手动填写或留空', 'warn');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = oldText; }
  }
}

// 网址失焦时，如果图标为空（或当前图标是自动探测来的），自动探测一次
let autoIconTried = '';
let autoIconValue = '';
function maybeAutoIcon() {
  const url = (document.getElementById('collectUrl').value || '').trim();
  const icon = (document.getElementById('collectIcon').value || '').trim();
  const isAuto = icon && icon === autoIconValue;
  if (!url || url === autoIconTried || (icon && !isAuto)) return;
  autoIconTried = url;
  autoFetchIcon();
}

// ---------- 读取已打开的网页 ----------
// 只列标题（不切换标签页、不闪动）；用户点中某一条时，才去读那一个标签的网址
async function pickOpenTab(e) {
  if (e) e.preventDefault();
  const box = document.getElementById('tabPicker');
  if (box.style.display === 'block') { box.style.display = 'none'; return; }
  box.style.display = 'block';
  box.innerHTML = '<div class="tab-picker-tip">正在读取已打开的网页…</div>';
  try {
    const r = await fetch('/api/tabs');
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || '读取失败');
    const tabs = data.tabs || [];
    if (!tabs.length) {
      box.innerHTML = '<div class="tab-picker-tip">没有读取到已打开的网页（仅支持 Edge / Chrome）</div>';
      return;
    }
    box.innerHTML = '<div class="tab-picker-tip">点一条即可填入（选中的那条会短暂切过去读地址再切回）</div>' +
      tabs.map((t, i) => `
      <div class="tab-item" data-idx="${i}">
        <div class="tab-item-title">${escapeHtml(t.title || '(无标题)')}</div>
        <div class="tab-item-url">${escapeHtml(t.browser || '')} · 标签 ${t.index + 1}</div>
      </div>`).join('');
    box.querySelectorAll('.tab-item').forEach(el => {
      el.onclick = async () => {
        const t = tabs[Number(el.dataset.idx)];
        el.classList.add('loading');
        const tf = el.querySelector('.tab-item-url');
        tf.textContent = '读取网址中…';
        try {
          const resp = await fetch('/api/tabs/url?win=' + t.win + '&idx=' + t.index);
          const d = await resp.json();
          if (!d.url) throw new Error(d.error || '没读到网址');
          document.getElementById('collectUrl').value = d.url;
          tf.textContent = d.url;
          const nameEl = document.getElementById('collectName');
          if (!(nameEl.value || '').trim()) nameEl.value = t.title || '';
          // 换了网址，旧的自动图标不再适用
          const iconEl = document.getElementById('collectIcon');
          if ((iconEl.value || '').trim() === autoIconValue) {
            iconEl.value = '';
            autoIconValue = '';
            updateIconPreview();
          }
          box.style.display = 'none';
          autoIconTried = '';
          autoFetchIcon();
        } catch (err) {
          tf.textContent = '读取失败：' + err.message;
        }
      };
    });
  } catch (err) {
    box.innerHTML = '<div class="tab-picker-tip">读取失败：' + escapeHtml(String(err.message)) + '</div>';
  }
}

/**
 * 同步 API 调用
 */
async function post(path, body) {
  const r = await fetch(server + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {})
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || '请求失败');
  return data;
}

function handleSubmit(e) {
  e.preventDefault();

  const newItem = {
    name: document.getElementById('name').value.trim(),
    url: document.getElementById('url').value,
    icon: document.getElementById('icon').value.trim() || null,
    id: Date.now()
  };

  if (!validateItem(newItem)) {
    alert('请输入有效的名称和URL');
    return false;
  }

  addLink(newItem);
  // 清空表单
  document.getElementById('addForm').reset();
  return false;
}

async function loadData() {
    try {
      const response = await fetch(server);
      allData = await response.json();
      // 默认全部收起子分组，只显示一级分组；选中分组时会自动展开其父链
      ensureExpanded(activeGroup);
      renderGroups();
      renderCards();
      clearAutofill();
    } catch (error) {
      console.error('加载失败:', error);
    };
  }

// 浏览器自动填充可能污染筛选框，这里主动清掉（仅首次）
let autofillCleared = false;
let userTypedFilter = false;
function clearAutofill() {
  if (autofillCleared) return;
  autofillCleared = true;
  const f = document.getElementById('filter-input');
  const wipe = () => {
    if (f && !userTypedFilter && f.value && !filterText) {
      f.value = '';
    }
  };
  wipe();
  // 部分浏览器会在渲染后异步回填，延迟再清一次
  setTimeout(wipe, 600);
}

function validateItem(item) {
    try {
        var url = new URL(item.url); // 使用URL对象验证
       return !!item.name?.trim();
    } catch {
        return false;
    }
}

// ---------- 分组 ----------
function normalizeGroup(g) {
  return (g || '').trim() || '首页';
}

function groupSort(a, b) {
  if (a === '首页') return -1;
  if (b === '首页') return 1;
  return a.localeCompare(b, 'zh-CN');
}

function getGroupList() {
  const map = {};
  allData.forEach(item => {
    const g = normalizeGroup(item.group);
    map[g] = (map[g] || 0) + 1;
  });
  return Object.keys(map).sort(groupSort).map(name => ({ name, count: map[name] }));
}

function buildGroupTree() {
  const counts = {};
  allData.forEach(item => {
    const g = normalizeGroup(item.group);
    counts[g] = (counts[g] || 0) + 1;
  });
  const root = { children: {} };
  Object.keys(counts).sort(groupSort).forEach(path => {
    const parts = path.split('/').filter(Boolean);
    let node = root, acc = '';
    parts.forEach((p, i) => {
      acc = i === 0 ? p : acc + '/' + p;
      if (!node.children[p]) node.children[p] = { name: p, path: acc, count: 0, children: {} };
      node = node.children[p];
      if (i === parts.length - 1) node.count = counts[path];
    });
  });
  return root;
}

function ensureExpanded(path) {
  const parts = path.split('/').filter(Boolean);
  for (let i = 1; i < parts.length; i++) {
    expanded.add(parts.slice(0, i).join('/'));
  }
}

function renderTreeNode(node) {
  return Object.values(node.children)
    .sort((a, b) => groupSort(a.name, b.name))
    .map(child => {
      const hasChildren = Object.keys(child.children).length > 0;
      const open = expanded.has(child.path);
      const active = child.path === activeGroup ? ' active' : '';
      // SVG 折角箭头：收起时朝右，展开时朝下，旋转有过渡
      const arrow = hasChildren
        ? `<span class="tree-arrow${open ? ' open' : ''}" title="${open ? '收起' : '展开'}">
             <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 9l7 7 7-7"/></svg>
           </span>`
        : '<span class="tree-arrow empty"></span>';
      const kids = (hasChildren && open)
        ? `<div class="group-children">${renderTreeNode(child)}</div>` : '';
      return `<div class="group-node${active}" data-path="${escapeAttr(child.path)}">
        ${arrow}<span class="group-label" title="${escapeAttr(child.path)}">${escapeHtml(child.name)}</span>
        <span class="group-count">${child.count}</span>
      </div>${kids}`;
    }).join('');
}

function renderGroups() {
  const nav = document.getElementById('group-nav');
  nav.innerHTML = renderTreeNode(buildGroupTree());
  nav.querySelectorAll('.group-node').forEach(el => {
    el.onclick = () => setActiveGroup(el.dataset.path);

    // 把卡片拖到分组上 → 改变所属分组
    el.addEventListener('dragover', e => {
      if (!draggingCardId) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      if (typeof aimFollow === 'function' && dragCtx) aimFollow(e);  // 卡片继续跟着鼠标走
      el.classList.add('drop-target');
    });
    el.addEventListener('dragleave', () => el.classList.remove('drop-target'));
    el.addEventListener('drop', async e => {
      e.preventDefault();
      e.stopPropagation();
      el.classList.remove('drop-target');
      const id = draggingCardId || e.dataTransfer.getData('text/plain');
      const target = el.dataset.path;
      if (!id || !target) return;
      await moveCardToGroup(id, target);
    });
  });
  nav.querySelectorAll('.tree-arrow').forEach(el => {
    if (el.classList.contains('empty')) return; // 无子分组：不需要箭头点击
    el.onclick = (e) => {
      e.stopPropagation();   // 只折叠/展开，不切换当前分组
      const node = el.closest('.group-node');
      if (!node) return;
      const p = node.dataset.path;
      const nowOpen = !expanded.has(p);
      if (nowOpen) expanded.add(p); else expanded.delete(p);
      // 先让箭头转动，再重建子列表，视觉上更连贯
      el.classList.toggle('open', nowOpen);
      el.title = nowOpen ? '收起' : '展开';
      setTimeout(renderGroups, 170);
    };
  });
  refreshGroupOptions();
}

// 拖拽卡片到左侧分组：把这条书签改到目标分组
async function moveCardToGroup(cardId, targetGroup) {
  const item = allData.find(x => String(x.id) === String(cardId));
  if (!item) return;
  const from = normalizeGroup(item.group);
  const to = normalizeGroup(targetGroup);
  if (from === to) { groupDropDone = false; return; }

  groupDropDone = true;   // 告诉 dragend 不要再保存顺序
  try {
    const r = await fetch(server + '/' + cardId, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...item, group: to })
    });
    if (!r.ok) throw new Error('移动失败');
    tip(`「${item.name}」已移到「${to}」`, 'success');
    await loadData();
  } catch (err) {
    groupDropDone = false;
    tip('移动分组失败，请重试', 'error');
  }
}

function setActiveGroup(name) {
  activeGroup = normalizeGroup(name);
  ensureExpanded(activeGroup);
  renderGroups();
  renderCards();
}

function onFilterInput() {
  userTypedFilter = true;
  filterText = document.getElementById('filter-input').value.trim().toLowerCase();
  renderCards();
}

function getVisibleItems() {
  const kw = filterText;
  return allData.filter(item => {
    if (kw) {
      const name = (item.name || '').toLowerCase();
      const url = (item.url || '').toLowerCase();
      return name.includes(kw) || url.includes(kw);
    }
    return normalizeGroup(item.group) === activeGroup;
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function escapeAttr(s) { return escapeHtml(s); }

function renderCards() {
    const container = document.getElementById('cards');
    const items = getVisibleItems();
    const totalEl = document.getElementById('group-total');
    if (totalEl) totalEl.textContent = `${getGroupList().length} 组 · ${allData.length} 条`;

    if (!items.length) {
      container.innerHTML = '<div class="empty-tip">暂无匹配书签</div>';
      return;
    }
    container.innerHTML = items.map(item => {
      const url = item.url || '';
      const shortUrl = url.replace(/^https?:\/\//i, '');
      return `
            <div class="card" data-id="${item.id}" draggable="true">
                <a href="${url}" target="_blank" class="card-link"
                   title="${escapeHtml(item.name)}\n${escapeHtml(url)}">
                    <img src="${item.icon}" class="card-icon" onerror="this.style.display='none'" onload="this.style.display='block'">
                    <div class="card-content">
                        <h3 class="card-title">${escapeHtml(item.name)}</h3>
                        <div class="card-url">${escapeHtml(shortUrl)}</div>
                    </div>
                </a>
                <div class="action-buttons">
                    <button class="edit-btn" onclick="editLink(${item.id})">✏️</button>
                    <button class="delete-btn" onclick="deleteLink(${item.id})">🗑️</button>
                </div>
       </div>`;
    }).join('');
    initDragAndDrop();   // 每次重新渲染卡片都重新绑定拖拽（否则切分组/搜索后拖拽失效）
}

// ==================== 拖拽：自定义拖拽影像 + FLIP 让位动画 ====================
let dragCtx = null;      // { card, grabDX, grabDY }
let follow = null;       // { raf, curX, curY, tx, ty }

// 浏览器要求 setDragImage 的节点必须在文档里，这里放一个屏幕外的透明 1px 方块
function dragGhostElement() {
  let el = document.getElementById('drag-ghost');
  if (!el) {
    el = document.createElement('div');
    el.id = 'drag-ghost';
    el.style.cssText = 'position:fixed;top:-1000px;left:-1000px;width:1px;height:1px;opacity:0;pointer-events:none;';
    document.body.appendChild(el);
  }
  return el;
}

function initDragAndDrop() {
  const wrap = document.getElementById('cards');
  if (!wrap) return;

  wrap.querySelectorAll('.card').forEach(card => {
    card.draggable = true;
    card.addEventListener('dragstart', onCardDragStart);
    card.addEventListener('dragend', onCardDragEnd);
  });

  // 容器级监听（用属性赋值，避免重复绑定）
  wrap.ondragover = onCardsDragOver;
  wrap.ondrop = e => { e.preventDefault(); };
}

function onCardDragStart(e) {
  const card = e.currentTarget;
  const rect = card.getBoundingClientRect();
  dragCtx = { card, grabDX: e.clientX - rect.left, grabDY: e.clientY - rect.top };
  follow = { raf: null, curX: 0, curY: 0, tx: 0, ty: 0 };
  draggingCardId = card.dataset.id;
  groupDropDone = false;

  card.classList.add('dragging');
  card.style.transition = 'none';
  card.style.transform = 'translate3d(0, 0, 0) scale(1.03)';
  document.body.classList.add('dragging-active');

  // 关掉浏览器默认那个糊图影子，改成卡片本体跟着鼠标走
  e.dataTransfer.setDragImage(dragGhostElement(), 0, 0);
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', card.dataset.id);
}

function onCardsDragOver(e) {
  if (!dragCtx) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';

  aimFollow(e);
  if (filterText) return;          // 搜索结果不参与重排
  applyInsertion(e);
}

// 记录“应该贴到哪儿”，由 rAF 缓动追上去（dragover 触发频率低，直接跟会发涩）
function aimFollow(e) {
  const card = dragCtx.card;
  const r = card.getBoundingClientRect();
  const baseLeft = r.left - follow.curX;    // 去掉当前位移后的原始布局位置
  const baseTop = r.top - follow.curY;
  follow.tx = e.clientX - dragCtx.grabDX - baseLeft;
  follow.ty = e.clientY - dragCtx.grabDY - baseTop;
  if (!follow.raf) follow.raf = requestAnimationFrame(stepFollow);
}

function stepFollow() {
  if (!dragCtx || !follow) return;
  follow.curX += (follow.tx - follow.curX) * 0.22;
  follow.curY += (follow.ty - follow.curY) * 0.22;
  dragCtx.card.style.transform =
    `translate3d(${follow.curX.toFixed(2)}px, ${follow.curY.toFixed(2)}px, 0) scale(1.03)`;

  // 已经很接近目标就停，省电
  if (Math.abs(follow.tx - follow.curX) < 0.4 && Math.abs(follow.ty - follow.curY) < 0.4) {
    follow.curX = follow.tx; follow.curY = follow.ty;
    dragCtx.card.style.transform =
      `translate3d(${follow.curX.toFixed(2)}px, ${follow.curY.toFixed(2)}px, 0) scale(1.03)`;
    follow.raf = null;
    return;
  }
  follow.raf = requestAnimationFrame(stepFollow);
}

// 计算应该插到第几个位置（卡片是网格排列，先比行、再比列）
function computeInsertIndex(e) {
  const wrap = dragCtx.card.parentNode;
  const others = Array.from(wrap.querySelectorAll('.card')).filter(c => c !== dragCtx.card);
  for (let i = 0; i < others.length; i++) {
    const r = others[i].getBoundingClientRect();
    if (r.bottom < e.clientY - r.height * 0.15) continue;      // 整行都在鼠标上方
    if (e.clientY < r.top) return { idx: i, node: others[i] };  // 插在这一行前面
    if (e.clientY <= r.bottom && e.clientX < r.left + r.width / 2) {
      return { idx: i, node: others[i] };                       // 同一行，插在左半边卡片前
    }
  }
  return { idx: others.length, node: null };
}

function applyInsertion(e) {
  const wrap = dragCtx.card.parentNode;
  const { idx, node } = computeInsertIndex(e);
  const currentIdx = Array.from(wrap.children).indexOf(dragCtx.card);
  if (currentIdx === idx) return;

  // FLIP：先记录其它卡片的旧位置，动完 DOM 后再从旧位置滑到新位置
  const cards = Array.from(wrap.querySelectorAll('.card')).filter(c => c !== dragCtx.card);
  const firstRects = new Map(cards.map(c => [c, c.getBoundingClientRect()]));

  if (node) wrap.insertBefore(dragCtx.card, node);
  else wrap.appendChild(dragCtx.card);

  cards.forEach(c => {
    const before = firstRects.get(c);
    const after = c.getBoundingClientRect();
    const dx = before.left - after.left;
    const dy = before.top - after.top;
    if (!dx && !dy) return;
    c.style.transition = 'none';
    c.style.transform = `translate3d(${dx}px, ${dy}px, 0)`;
    c.style.zIndex = '1';
    requestAnimationFrame(() => {
      c.style.transition = 'transform 0.26s cubic-bezier(0.22, 0.75, 0.25, 1)';
      c.style.transform = '';
      c.style.zIndex = '';
    });
  });

  aimFollow(e);   // DOM 变了，重新贴合鼠标目标
}

function onCardDragEnd() {
  if (!dragCtx) return;
  const card = dragCtx.card;
  if (follow && follow.raf) cancelAnimationFrame(follow.raf);

  // 从“跟随位置”滑回它在网格里的真实位置
  card.classList.remove('dragging');
  document.body.classList.remove('dragging-active');
  card.style.transition = 'transform 0.24s cubic-bezier(0.22, 0.75, 0.25, 1)';
  card.style.transform = 'translate3d(0, 0, 0) scale(1)';
  setTimeout(() => {
    card.style.transition = '';
    card.style.transform = '';
  }, 260);

  const dropped = groupDropDone;
  dragCtx = null;
  follow = null;
  draggingCardId = null;
  groupDropDone = false;
  // 拖到分组上已经改成“换分组”了，就不要再重排顺序
  if (!dropped) saveNewOrder();
}

// 保存新顺序到服务器（只重排，服务端不会再删掉没传到的条目）
async function saveNewOrder() {
  if (filterText) return;   // 搜索结果是跨分组的混合列表，重排没有意义
  const visibleIds = Array.from(document.querySelectorAll('.card')).map(c => c.dataset.id);
  let k = 0;
  const fullIds = allData.map(item => {
    if (normalizeGroup(item.group) === activeGroup) {
      return visibleIds[k++] || String(item.id);
    }
    return String(item.id);
  });

  try {
    const response = await fetch(server + '/order', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nod: fullIds })
    });
    if (!response.ok) throw new Error('保存失败');
    loadData();
  } catch (error) {
    console.error('保存顺序失败:', error);
    tip('顺序保存失败，请重试', 'error');
  }
}

// ---------- 分组下拉选项 ----------
function refreshGroupOptions(selected) {
  const select = document.getElementById('collectGroup');
  if (!select) return;
  const groups = getGroupList().map(g => g.name);
  if (!groups.includes('首页')) groups.unshift('首页');
  const options = groups.map(g =>
    `<option value="${escapeAttr(g)}" ${g === selected ? 'selected' : ''}>${escapeHtml(g)}</option>`
  ).join('');
  select.innerHTML = options + '<option value="__new__">＋ 新建分组…</option>';
  select.value = groups.includes(selected) ? selected : '__new__';
  toggleNewGroupInput(select.value === '__new__');
}

function toggleNewGroupInput(show) {
  const input = document.getElementById('newGroup');
  input.style.display = show ? 'block' : 'none';
  if (show) input.focus();
}

function resolveGroup() {
  const select = document.getElementById('collectGroup');
  if (select.value === '__new__') {
    return document.getElementById('newGroup').value.trim() || '首页';
  }
  return select.value || '首页';
}

async function addLink(newItem) {
try {
  const response = await fetch(server, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(newItem)
  });

  if (!response.ok) throw new Error('保存失败');
  loadData(); // 刷新列表
} catch (error) {
  alert(error.message);
}
}

async function deleteLink(id) {
  if (!confirm('确认删除此链接？')) return;

  try {
    const response = await fetch(server + '/' + id.toString(), {
      method: 'DELETE'
    });

    if (!response.ok) throw new Error('删除失败');
    loadData(); // 刷新列表
  } catch (error) {
    alert(error.message);
  }
}

// 使用百度搜索关键字，并打开新标签页
function handleSearch(e) {
    const keyword = document.getElementById('search-input').value.trim();
    if (!keyword) return;
    // 根据搜索引擎不同，使用不同的搜索语法
    const engine = document.getElementById('search-engine').value;
    let url = '';
    switch (engine) {
        case 'google':
            url = `https://www.google.com/search?q=${keyword}`;
            break;
        case 'bing':
            url = `https://www.bing.com/search?q=${keyword}`;
            break;
        case 'baidu':
            url = `https://www.baidu.com/s?wd=${keyword}`;
            break;
        case '360':
            url = `https://www.so.com/s?q=${keyword}`;
            break;
        default:
            url = `https://www.baidu.com/s?wd=${keyword}`;
            break;
    }
    window.open(url, '_blank');
    document.getElementById('search-input').value = '';
}


async function editLink(id) {
  // 获取原始数据
  const server_id = server + '/' + id.toString();
  const original = await fetch(server_id).then(r => r.json());

  const modal = document.getElementById("collectModal");
  modal.style.display = "block";

  const form = document.getElementById('collectForm');
  const textName = document.getElementById('collectName');
  const textUrl = document.getElementById('collectUrl');
  const textIcon = document.getElementById('collectIcon');
  const saveBtn = document.getElementById('saveBtn');
  textName.value = original.name;
  textUrl.value = original.url;
  textIcon.value = original.icon || '';
  refreshGroupOptions(normalizeGroup(original.group));

  // 修改表单提交逻辑
  saveBtn.onclick = async (e) => {
    e.preventDefault();
    const updatedItem = {
      name: textName.value,
      url: textUrl.value,
      icon: textIcon.value,
      group: resolveGroup(),
      id: original.id
    };
    try {
      const response = await fetch(server_id, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updatedItem)
      });

      if (!response.ok) throw new Error('更新失败!');
      loadData(); // 刷新列表
      textIcon.value = '';
      textName.value = '';
      textUrl.value = '';
      modal.style.display = "none";
      saveBtn.onclick = handleSubmitForFav;
    } catch (error) {
      alert(error.message);
    }
  };

  setTimeout(() => {textName.focus(); }, 300);

}

async function handleSubmitForFav(e) {
      e.preventDefault();
      const newItem = {
        name: document.getElementById('collectName').value.trim(),
        url: document.getElementById('collectUrl').value.trim(),
        icon: document.getElementById('collectIcon').value.trim() || null,
        group: resolveGroup(),
        id: Date.now()
      };

      if(!newItem.name || !newItem.url) {
        alert('名称和网址为必填项');
        return false;
      }
    addLink(newItem);
      clearForm();
      return false;
}

function clearForm(){
      document.getElementById('collectName').value = '';
       document.getElementById('collectUrl').value = '';
       document.getElementById('collectIcon').value = '';
       document.getElementById('newGroup').value = '';
       const picker = document.getElementById('tabPicker');
       if (picker) { picker.style.display = 'none'; picker.innerHTML = ''; }
       const prev = document.getElementById('iconPreview');
       if (prev) { prev.style.display = 'none'; prev.removeAttribute('src'); }
       autoIconTried = '';
       autoIconValue = '';
       refreshGroupOptions('首页');
       document.getElementById("collectModal").style.display = "none";
}

function toggleModal(action) {
  const modal = document.getElementById("collectModal");
  modal.style.display = action;
  if (action === 'block') refreshGroupOptions(activeGroup);
}

// 按下ESC关闭弹窗
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' || e.code === 'Escape') {
    clearForm();
  }
});

// 点击弹窗外部关闭弹窗
window.onclick = (e) =>
 {
 const modal = document.getElementById("collectModal");
  if (e.target == modal) {
    clearForm();
  }
}
