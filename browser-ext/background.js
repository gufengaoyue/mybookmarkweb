// 书签导航 · 标签页桥
// 作用：用 chrome.tabs 读取全部标签页的标题与网址，定时/变更时 POST 给本地服务
//      http://127.0.0.1:<port>/api/tabs/push
// 这样页面就能拿到带网址的标签列表，且完全不需要切换标签（零闪烁）。
//
// 端口：优先用上次成功的端口，其次依次试 DEFAULT_PORTS；
//      想固定端口可在扩展里改 storage 的 port（chrome.storage.local）。

const DEFAULT_PORTS = [3000, 3001, 8080, 8000];

const skipPrefixes = [
  'chrome://', 'edge://', 'chrome-extension://', 'edge-extension://',
  'devtools://', 'about:', 'chrome-search://', 'view-source:'
];

let lastPushAt = 0;
let pending = null;

async function resolvePorts() {
  let stored = null;
  try {
    const v = await chrome.storage.local.get('port');
    stored = v && v.port;
  } catch (e) { /* ignore */ }
  const list = [];
  if (stored) list.push(stored);
  DEFAULT_PORTS.forEach(p => { if (!list.includes(p)) list.push(p); });
  return list;
}

async function collectTabs() {
  const tabs = await chrome.tabs.query({});
  const browser = navigator.userAgent.includes('Edg') ? 'edge' : 'chrome';
  return tabs
    .filter(t => t.url && !skipPrefixes.some(p => t.url.startsWith(p)))
    .map(t => ({
      title: t.title || '',
      url: t.url,
      active: !!t.active,
      browser,
      windowId: t.windowId,
      index: t.index
    }));
}

async function pushOnce() {
  const tabs = await collectTabs();
  const ports = await resolvePorts();
  for (const port of ports) {
    try {
      const resp = await fetch('http://127.0.0.1:' + port + '/api/tabs/push', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tabs })
      });
      if (resp.ok) {
        lastPushAt = Date.now();
        try { await chrome.storage.local.set({ port, lastPush: lastPushAt }); } catch (e) { /* ignore */ }
        return true;
      }
    } catch (e) {
      // 这个端口没开服务，试下一个
    }
  }
  return false;
}

// 300ms 防抖：连续事件只推一次
function schedulePush(delay = 300) {
  if (pending) clearTimeout(pending);
  pending = setTimeout(() => {
    pending = null;
    pushOnce().catch(() => {});
  }, delay);
}

// ---- 触发点 ----
chrome.runtime.onInstalled.addListener(() => schedulePush(0));
chrome.runtime.onStartup.addListener(() => schedulePush(0));
chrome.tabs.onCreated.addListener(() => schedulePush());
chrome.tabs.onRemoved.addListener(() => schedulePush());
chrome.tabs.onMoved.addListener(() => schedulePush());
chrome.tabs.onActivated.addListener(() => schedulePush());
chrome.tabs.onUpdated.addListener((id, info) => {
  if (info.status === 'complete' || info.url || info.title) schedulePush();
});

// ---- 心跳：MV3 的 service worker 会休眠，用 alarm 每 30 秒唤醒一次 ----
chrome.alarms.create('tabs-heartbeat', { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === 'tabs-heartbeat') schedulePush(0);
});

// service worker 启动时先推一次
schedulePush(0);
