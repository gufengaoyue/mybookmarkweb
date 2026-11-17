# -*- coding: utf-8 -*-
"""
坚果云 WebDAV 同步模块（仅使用 Python 标准库，无需 pip 安装）

功能：
  - 坚果云 WebDAV 登录（邮箱 + 应用密码），凭据保存在项目根目录 sync_config.json
  - 读取/创建云端固定文件夹 bookmark_api（内含 links.json 与 icon/ 目录）
  - 本地 static/api 与云端双向同步，冲突检测（由调用方/前端决定保留哪一边）
  - 强制上传、强制下载（下载前自动备份本地）、本地时间戳备份

同步状态文件 .sync_state.json 记录上次同步时各文件的本地哈希与云端 ETag。
"""

import base64
import hashlib
import io
import json
import os
import random
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime

# ---------------------------------------------------------------- 常量配置

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_API_DIR = os.path.join(BASE_DIR, 'static', 'api')
LOCAL_ICON_DIR = os.path.join(LOCAL_API_DIR, 'icon')

CONFIG_FILE = os.path.join(BASE_DIR, 'sync_config.json')
STATE_FILE = os.path.join(BASE_DIR, '.sync_state.json')
BACKUP_DIR = os.path.join(BASE_DIR, 'backups')

WEBDAV_ROOT = 'https://dav.jianguoyun.com/dav/'
REMOTE_DIR = 'bookmark_api'          # 云端固定文件夹名
REMOTE_ICON_DIR = REMOTE_DIR + '/icon'
REMOTE_BUNDLE = 'icons.zip'          # 图标打包文件：一次 PUT 传完全部图标，避免几百次请求触发限流
REMOTE_GROUPS = 'groups.json'        # 分组名单（含空分组），体积很小，单独一个小文件
LOCAL_GROUPS = os.path.join(LOCAL_API_DIR, 'groups.json')
_ZIP_CACHE = {'key': None, 'bytes': None}


def _icons_fingerprint():
    """图标目录的轻量指纹（文件数、总字节、最后修改时间），用于判断是否需要重打包。"""
    count = total = 0
    newest = 0.0
    if not os.path.isdir(LOCAL_ICON_DIR):
        return (0, 0, 0.0)
    for name in os.listdir(LOCAL_ICON_DIR):
        p = os.path.join(LOCAL_ICON_DIR, name)
        if not os.path.isfile(p):
            continue
        st = os.stat(p)
        count += 1
        total += st.st_size
        newest = max(newest, st.st_mtime)
    return (count, total, round(newest, 3))


def icons_zip_bytes():
    """把本地 icon 目录打包成 zip（内容确定，时间戳固定，便于用哈希比较）。"""
    key = _icons_fingerprint()
    if _ZIP_CACHE['key'] == key and _ZIP_CACHE['bytes'] is not None:
        return _ZIP_CACHE['bytes']
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in sorted(os.listdir(LOCAL_ICON_DIR)) if os.path.isdir(LOCAL_ICON_DIR) else []:
            p = os.path.join(LOCAL_ICON_DIR, name)
            if not os.path.isfile(p):
                continue
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            with open(p, 'rb') as f:
                z.writestr(info, f.read())
    data = buf.getvalue()
    _ZIP_CACHE['key'] = key
    _ZIP_CACHE['bytes'] = data
    return data


def extract_icons_zip(data):
    """解包图标 zip 到本地 icon 目录，返回写入的文件数。"""
    os.makedirs(LOCAL_ICON_DIR, exist_ok=True)
    written = 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if not name or name.endswith('/'):
                continue
            # 防目录穿越
            base = os.path.basename(name)
            if not base:
                continue
            with z.open(name) as src, open(os.path.join(LOCAL_ICON_DIR, base), 'wb') as dst:
                dst.write(src.read())
            written += 1
    _ZIP_CACHE['key'] = None
    return written

DAV_NS = {'D': 'DAV:'}

# 坚果云对频繁请求会返回 503 BlockedTemporarily（Too many requests），
# 这些状态码需要退避重试，而不是直接失败。
TRANSIENT_STATUS = (429, 502, 503, 504)
MAX_RETRY = 5
# 连续请求之间的最小间隔（秒），避免触发限流（坚果云免费版对请求频率很敏感）
MIN_REQUEST_INTERVAL = 0.5

PROPFIND_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<D:propfind xmlns:D="DAV:">'
    '<D:prop><D:resourcetype/><D:getetag/>'
    '<D:getlastmodified/><D:getcontentlength/></D:prop>'
    '</D:propfind>'
).encode('utf-8')


# ---------------------------------------------------------------- 工具函数

def _sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _now_str():
    return datetime.now().strftime('%Y%m%d_%H%M%S')


def _rel_posix(rel):
    """统一使用正斜杠作为文件相对路径（如 icon/xx.png）。"""
    return rel.replace('\\', '/')


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, encoding='utf-8') as f:
            cfg = json.load(f)
        if cfg.get('password'):
            cfg['password'] = base64.b64decode(cfg['password'].encode()).decode()
        return cfg
    except Exception:
        return {}


def save_config(email, password):
    cfg = {
        'email': email,
        # 仅做简单编码避免明文直显，并非加密；文件位于项目根目录、不在 static 下
        'password': base64.b64encode(password.encode()).decode(),
        'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def clear_config():
    if os.path.exists(CONFIG_FILE):
        os.remove(CONFIG_FILE)
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)


def load_state():
    if not os.path.exists(STATE_FILE):
        return {'files': {}}
    try:
        with open(STATE_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'files': {}}


def save_state(state):
    state['last_sync'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- WebDAV 客户端

class WebDAVError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class WebDAVRateLimit(WebDAVError):
    """坚果云限流（BlockedTemporarily）。命中后进入冷却期，本轮不再重试。"""


# 命中限流后的冷却时间（秒），期间所有请求直接拒绝，避免越试越黑
BLOCK_COOLDOWN = 600
_rate_state = {'blocked_until': 0.0, 'interval': MIN_REQUEST_INTERVAL}

# 后台任务进度（供前端轮询）
PROGRESS = {'running': False, 'total': 0, 'done': 0, 'uploaded': 0,
            'failed': [], 'message': '', 'error': None}


def _reset_progress():
    PROGRESS.update({'running': False, 'total': 0, 'done': 0,
                     'uploaded': 0, 'failed': [], 'message': '', 'error': None})


def rate_limit_remaining():
    """冷却期内返回剩余秒数，否则 0。"""
    return max(0, int(_rate_state['blocked_until'] - time.time()))


class WebDAVClient:
    def __init__(self, email, password, timeout=30):
        self.email = email
        self.password = password
        self.timeout = timeout
        token = base64.b64encode(f'{email}:{password}'.encode()).decode()
        self.auth = 'Basic ' + token
        self._last_request_at = 0.0

    def _url(self, rel_path, as_dir=False):
        rel_path = rel_path.strip('/')
        if not rel_path:
            return WEBDAV_ROOT
        url = WEBDAV_ROOT + urllib.parse.quote(rel_path)
        # 目录（MKCOL/PROPFIND）以 / 结尾；文件（PUT/GET）不能带斜杠，
        # 否则坚果云会把文件当作集合资源，返回 403 OperationNotAllowed
        return url + '/' if as_dir else url

    def _throttle(self):
        """控制最小请求间隔，避免批量上传触发限流。"""
        remain = rate_limit_remaining()
        if remain:
            raise WebDAVRateLimit(
                f'坚果云限流冷却中，请约 {max(1, remain // 60)} 分钟后再试', 503)
        gap = time.time() - self._last_request_at
        interval = _rate_state['interval']
        if gap < interval:
            time.sleep(interval - gap)
        self._last_request_at = time.time()

    def _request(self, rel_path, method='GET', data=None, extra_headers=None,
                 as_dir=False):
        """发起请求；对限流/临时故障自动退避重试。"""
        attempt = 0
        while True:
            self._throttle()
            req = urllib.request.Request(self._url(rel_path, as_dir), data=data, method=method)
            req.add_header('Authorization', self.auth)
            if extra_headers:
                for k, v in extra_headers.items():
                    req.add_header(k, v)
            try:
                return urllib.request.urlopen(req, timeout=self.timeout)
            except urllib.error.HTTPError as e:
                try:
                    body = e.read().decode('utf-8', 'ignore')
                except Exception:
                    body = ''
                # 坚果云明确限流：不要再顶着重试，直接进入冷却期
                if 'BlockedTemporarily' in body or 'Too many requests' in body or e.code == 429:
                    _rate_state['blocked_until'] = time.time() + BLOCK_COOLDOWN
                    # 之后放慢节奏，逐步恢复
                    _rate_state['interval'] = min(_rate_state['interval'] * 2, 1.5)
                    err = WebDAVRateLimit(
                        f'坚果云限流（{e.code}），已暂停 {BLOCK_COOLDOWN // 60} 分钟后再试', e.code)
                    err.body = body
                    raise err
                if e.code in TRANSIENT_STATUS and attempt < MAX_RETRY:
                    # 优先遵循服务端 Retry-After，否则指数退避 + 随机抖动
                    delay = 0.0
                    try:
                        delay = float(e.headers.get('Retry-After') or 0)
                    except Exception:
                        delay = 0.0
                    if not delay:
                        delay = min(2 ** attempt + random.uniform(0, 0.5), 20)
                    time.sleep(delay)
                    attempt += 1
                    continue
                err = WebDAVError(f'HTTP {e.code}: {e.reason} {body[:200]}', e.code)
                err.body = body
                raise err
            except urllib.error.URLError as e:
                if attempt < MAX_RETRY:
                    time.sleep(min(2 ** attempt + random.uniform(0, 0.5), 20))
                    attempt += 1
                    continue
                raise WebDAVError(f'网络错误: {e.reason}')

    # ---- 基础操作 ----

    def test_login(self):
        """PROPFIND 根目录，成功即凭据有效。"""
        resp = self._request('', method='PROPFIND', data=PROPFIND_BODY,
                             extra_headers={'Depth': '0',
                                            'Content-Type': 'application/xml; charset=utf-8'},
                             as_dir=True)
        resp.read()
        return True

    def exists(self, rel_path):
        try:
            resp = self._request(rel_path, method='PROPFIND', data=PROPFIND_BODY,
                                 extra_headers={'Depth': '0',
                                                'Content-Type': 'application/xml; charset=utf-8'},
                                 as_dir=True)
            resp.read()
            return True
        except WebDAVError as e:
            if e.status == 404:
                return False
            raise

    def mkcol(self, rel_path):
        try:
            resp = self._request(rel_path, method='MKCOL', as_dir=True)
            resp.read()
        except WebDAVError as e:
            # 405 已存在视为成功
            if e.status != 405:
                raise

    def ensure_dir(self, rel_path):
        """递归创建目录。"""
        parts = [p for p in rel_path.strip('/').split('/') if p]
        cur = ''
        for p in parts:
            cur = cur + '/' + p if cur else p
            self.mkcol(cur)

    def list_dir(self, rel_path):
        """列出目录，返回 (dirs, files)；files: [{name, rel, etag, lastmodified}]。"""
        resp = self._request(rel_path, method='PROPFIND', data=PROPFIND_BODY,
                             extra_headers={'Depth': '1',
                                            'Content-Type': 'application/xml; charset=utf-8'},
                             as_dir=True)
        xml_data = resp.read()
        root = ET.fromstring(xml_data)
        dirs, files = [], []
        base_path = urllib.parse.urlparse(self._url(rel_path, as_dir=True)).path
        for response in root.findall('D:response', DAV_NS):
            href = urllib.parse.unquote(response.findtext('D:href', namespaces=DAV_NS) or '')
            href_path = urllib.parse.urlparse(href).path
            if href_path.rstrip('/') == base_path.rstrip('/'):
                continue  # 跳过目录自身
            name = href.rstrip('/').split('/')[-1]
            is_dir = response.find('.//D:resourcetype/D:collection', DAV_NS) is not None
            etag = response.findtext('.//D:getetag', namespaces=DAV_NS)
            lastmod = response.findtext('.//D:getlastmodified', namespaces=DAV_NS)
            size_raw = response.findtext('.//D:getcontentlength', namespaces=DAV_NS)
            try:
                size = int(size_raw) if size_raw is not None else None
            except (TypeError, ValueError):
                size = None
            if is_dir:
                dirs.append(name)
            else:
                files.append({
                    'name': name,
                    'rel': (rel_path + '/' + name).strip('/'),
                    'etag': (etag or '').strip('"'),
                    'lastmodified': lastmod or '',
                    'size': size,
                })
        return dirs, files

    def list_files_recursive(self, rel_path):
        """递归列出目录下全部文件。"""
        result = []
        dirs, files = self.list_dir(rel_path)
        result.extend(files)
        for d in dirs:
            sub = (rel_path + '/' + d).strip('/')
            result.extend(self.list_files_recursive(sub))
        return result

    def upload_bytes(self, rel_path, data):
        resp = self._request(rel_path, method='PUT', data=data,
                             extra_headers={'Content-Type': 'application/octet-stream'})
        resp.read()
        etag = resp.headers.get('ETag', '')
        return etag.strip('"') if etag else ''

    def upload_file(self, local_path, rel_path):
        with open(local_path, 'rb') as f:
            return self.upload_bytes(rel_path, f.read())

    def download_bytes(self, rel_path):
        resp = self._request(rel_path, method='GET')
        return resp.read()

    def head_etag(self, rel_path):
        """HEAD 请求，返回版本标识（优先 ETag，其次 Last-Modified），几乎无流量。
        坚果云 HEAD 不返回 ETag，所以用 Last-Modified 兜底。
        文件不存在返回 None。"""
        try:
            resp = self._request(rel_path, method='HEAD')
            resp.read()
            etag = resp.headers.get('ETag')
            if etag:
                return etag.strip('"')
            last_mod = resp.headers.get('Last-Modified')
            if last_mod:
                return 'LM:' + last_mod.strip()
            return ''
        except WebDAVError as e:
            if e.status == 404:
                return None
            raise

    def download_file(self, rel_path, local_path):
        data = self.download_bytes(rel_path)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, 'wb') as f:
            f.write(data)
        return len(data)


# ---------------------------------------------------------------- 本地文件枚举

def list_local_files():
    """返回需要同步的本地文件相对路径列表：links.json + icon/ 下全部文件。"""
    result = []
    links = os.path.join(LOCAL_API_DIR, 'links.json')
    if os.path.exists(links):
        result.append('links.json')
    if os.path.isdir(LOCAL_ICON_DIR):
        for name in os.listdir(LOCAL_ICON_DIR):
            p = os.path.join(LOCAL_ICON_DIR, name)
            if os.path.isfile(p):
                result.append(_rel_posix('icon/' + name))
    return result


def _local_path(rel):
    return os.path.join(LOCAL_API_DIR, *_rel_posix(rel).split('/'))


def _remote_rel(rel):
    return REMOTE_DIR + '/' + _rel_posix(rel)


# ---------------------------------------------------------------- 分组名单（groups.json）

def _read_local_groups():
    """读本地 groups.json，返回分组名集合（文件不存在/损坏都返回空集合）"""
    try:
        if not os.path.exists(LOCAL_GROUPS):
            return set()
        with open(LOCAL_GROUPS, encoding='utf-8') as f:
            raw = json.load(f)
        return {str(g).strip().strip('/') for g in raw if str(g).strip().strip('/')}
    except Exception:
        return set()


def _groups_hash(groups):
    """分组名的稳定指纹（排序后算 sha256，不受文件排版影响）"""
    payload = json.dumps(sorted(groups), ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def _groups_bytes(groups):
    return json.dumps(sorted(groups), ensure_ascii=False, indent=2).encode('utf-8')


def _write_local_groups(groups):
    """写本地 groups.json（原子替换），尽量不影响文件已存在时的内容顺序"""
    os.makedirs(LOCAL_API_DIR, exist_ok=True)
    tmp = LOCAL_GROUPS + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(_groups_bytes(groups))
    os.replace(tmp, LOCAL_GROUPS)


# ---------------------------------------------------------------- 备份

def backup_local(tag='backup'):
    """把 links.json 与 icon/ 备份到 backups/<tag>_<时间戳>/，返回备份目录。"""
    stamp = _now_str()
    dest = os.path.join(BACKUP_DIR, f'{tag}_{stamp}')
    os.makedirs(os.path.join(dest, 'icon'), exist_ok=True)
    links = os.path.join(LOCAL_API_DIR, 'links.json')
    if os.path.exists(links):
        shutil.copy2(links, os.path.join(dest, 'links.json'))
    if os.path.exists(LOCAL_GROUPS):
        shutil.copy2(LOCAL_GROUPS, os.path.join(dest, 'groups.json'))
    if os.path.isdir(LOCAL_ICON_DIR):
        for name in os.listdir(LOCAL_ICON_DIR):
            p = os.path.join(LOCAL_ICON_DIR, name)
            if os.path.isfile(p):
                shutil.copy2(p, os.path.join(dest, 'icon', name))
    return dest


def _backup_tree(subdir, tag='backup'):
    """把 static/api/<subdir> 打包成 backups/<tag>_<时间戳>.zip（单文件，省空间）。"""
    if subdir != 'icon':
        return ''
    os.makedirs(BACKUP_DIR, exist_ok=True)
    dest = os.path.join(BACKUP_DIR, f'{tag}_{_now_str()}.zip')
    with open(dest, 'wb') as f:
        f.write(icons_zip_bytes())
    return dest


def _backup_file(rel, data_bytes, tag='conflict'):
    """把单个文件的指定内容存为备份副本。"""
    stamp = _now_str()
    safe_name = _rel_posix(rel).replace('/', '__')
    dest_dir = os.path.join(BACKUP_DIR, f'{tag}_{stamp}')
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, safe_name)
    with open(dest, 'wb') as f:
        f.write(data_bytes)
    return dest


# ---------------------------------------------------------------- 同步计划

def _get_client():
    cfg = load_config()
    if not cfg.get('email') or not cfg.get('password'):
        raise WebDAVError('未登录坚果云')
    return WebDAVClient(cfg['email'], cfg['password'])


def _entry_sig(e):
    """条目内容签名（用于判断两端同一 id 的条目是否一致）。"""
    return json.dumps(e, sort_keys=True, ensure_ascii=False)


def _referenced_icon_rels(entries):
    """从条目集合中提取被引用的图标相对路径（icon/xxx.png）。"""
    rels = set()
    for e in entries:
        ic = (e.get('icon') or '').replace('\\', '/')
        if ic.startswith('static/api/icon/'):
            rels.add(ic[len('static/api/icon/'):])
        elif ic.startswith('icon/'):
            rels.add(ic[len('icon/'):])
    return rels


def make_plan(resolutions=None, mode='sync'):
    """
    生成同步计划（条目级合并 + 图标增量）。
    mode:
      'sync'    双向合并 + 删除传播
      'upload'  本地为准：final = 本地条目（本地删了就推到云端）
      'download' 云端为准：final = 云端条目（本地删了就从云端恢复）
    """
    resolutions = resolutions or {}
    client = _get_client()
    remote_exists = client.exists(REMOTE_DIR)

    # ---------- links.json：按 id 合并 ----------
    local_links_path = os.path.join(LOCAL_API_DIR, 'links.json')
    with open(local_links_path, 'rb') as f:
        local_links_bytes = f.read()
    local_links_hash = hashlib.sha256(local_links_bytes).hexdigest()
    local_entries = json.loads(local_links_bytes.decode('utf-8'))
    local_map = {str(e.get('id')): e for e in local_entries if e.get('id') is not None}

    # 先用 HEAD 拿云端 ETag，若两端都和上次同步时一致，直接跳过下载（省流量）
    links_cache = load_state().get('links', {})
    remote_etag = client.head_etag(_remote_rel('links.json')) if remote_exists else None
    links_unchanged = (
        remote_exists and bool(remote_etag) and
        links_cache.get('local') == local_links_hash and
        links_cache.get('remote') == remote_etag
    )

    remote_entries, remote_links_bytes = [], None
    remote_map = {}
    if links_unchanged:
        # 两端都没变，远程内容等价于本地
        remote_entries = local_entries
        remote_map = dict(local_map)
    elif remote_exists:
        try:
            remote_links_bytes = client.download_bytes(_remote_rel('links.json'))
            remote_entries = json.loads(remote_links_bytes.decode('utf-8'))
            remote_map = {str(e.get('id')): e for e in remote_entries if e.get('id') is not None}
        except WebDAVError as e:
            if e.status != 404:
                raise

    final_map = {}
    conflicts = []  # links 条目冲突
    for key in set(local_map) | set(remote_map):
        le, re_ = local_map.get(key), remote_map.get(key)
        if le is None:
            final_map[key] = re_
        elif re_ is None:
            final_map[key] = le
        elif _entry_sig(le) == _entry_sig(re_):
            final_map[key] = le
        else:
            choice = resolutions.get('links:' + key)
            final_map[key] = re_ if choice == 'remote' else le
            conflicts.append({
                'key': 'links:' + key,
                'kind': 'links',
                'label': f"书签「{le.get('name', key)}」",
                'local': le, 'remote': re_,
            })

    # ---- 删除传播：依据上次同步时的 id 基线判断谁删了什么 ----
    baseline_ids = set(load_state().get('links_ids', []))
    local_ids = set(local_map)
    remote_ids = set(remote_map)
    # 基线有、本地没了、远端还有 → 本地删除，从结果中移除（执行时推送云端）
    for key in list(remote_ids - local_ids):
        if key in baseline_ids:
            final_map.pop(key, None)
    # 基线有、远端没了、本地还有 → 远端删除，从结果中移除（执行时下载云端结果）
    for key in list(local_ids - remote_ids):
        if key in baseline_ids:
            final_map.pop(key, None)

    # 保持本地原有顺序，再追加仅在远端的新条目（已被删除传播剔除的不再追加）
    final_entries = []
    seen = set()
    for e in local_entries:
        k = str(e.get('id'))
        if k in final_map and k not in seen:
            final_entries.append(final_map[k])
            seen.add(k)
    for e in remote_entries:
        k = str(e.get('id'))
        if k in final_map and k not in seen:
            final_entries.append(e)
            seen.add(k)

    # 按模式覆盖最终结果：upload=本地为准，download=云端为准
    if mode == 'upload':
        final_entries = local_entries
        conflicts = []  # 本地优先，不弹冲突
    elif mode == 'download':
        final_entries = remote_entries
        conflicts = []

    # links.json 该如何处理（按条目语义比较，不比较字节格式差异）
    local_same = final_entries == local_entries
    remote_same = final_entries == remote_entries
    if remote_same and local_same:
        links_action = 'none'
    elif remote_same:
        # 合并结果与云端一致，本地落后 → 用云端覆盖本地
        links_action = 'download'
    elif local_same:
        # 合并结果与本地一致，本地有新增/修改 → 上传到云端
        links_action = 'upload'
    else:
        # 双方各自新增、互不冲突 → 写本地并上传合并结果
        links_action = 'merge'

    # ---------- groups.json：分组名单（含空分组），按集合处理 ----------
    local_groups = _read_local_groups()
    remote_groups = set()
    remote_groups_etag = client.head_etag(_remote_rel(REMOTE_GROUPS)) if remote_exists else None
    remote_has_groups = bool(remote_groups_etag)
    groups_cache = load_state().get('groups', {})

    if remote_has_groups:
        if (groups_cache.get('local') == _groups_hash(local_groups)
                and groups_cache.get('remote') == remote_groups_etag):
            remote_groups = set(local_groups)      # 两端都没变，省一次 GET
        else:
            try:
                raw = client.download_bytes(_remote_rel(REMOTE_GROUPS))
                remote_groups = {str(g).strip() for g in json.loads(raw.decode('utf-8')) if str(g).strip()}
            except WebDAVError as e:
                if e.status != 404:
                    raise

    groups_final, groups_action = set(local_groups), 'none'
    if mode == 'upload':
        groups_final = set(local_groups)
        if not remote_has_groups or groups_final != remote_groups:
            groups_action = 'upload'
    elif mode == 'download':
        # 云端有这份文件才以云端为准；云端没有就保留本地，避免把空分组名单误清空
        if remote_has_groups:
            groups_final = set(remote_groups)
            if groups_final != local_groups:
                groups_action = 'download'
        else:
            groups_final = set(local_groups)
    else:  # sync：并集合并 + 删除传播（界面删掉的分组不再被云端复活）
        baseline_groups = set(load_state().get('groups_ids', []))
        merged = set(local_groups) | set(remote_groups)
        merged -= (baseline_groups - set(local_groups))    # 本地删掉的
        merged -= (baseline_groups - set(remote_groups))   # 云端删掉的
        groups_final = merged
        if not remote_has_groups:
            groups_action = 'upload' if groups_final else 'none'
        elif groups_final != remote_groups:
            groups_action = 'upload'
        elif groups_final != local_groups:
            groups_action = 'download'

    # ---------- 图标：整体打成一个 zip，一次 PUT 传完 ----------
    # 云端 icon/ 目录里逐个文件 PUT 会产生几百次请求，坚果云必然限流。
    # 这里改成：本地先打包 icons.zip，只上传这一个文件；下载也只需一次 GET。
    bundle_state = load_state().get('bundle', {})
    local_zip = icons_zip_bytes()
    local_zip_hash = hashlib.sha256(local_zip).hexdigest()
    remote_zip_etag = client.head_etag(_remote_rel(REMOTE_BUNDLE)) if remote_exists else None
    remote_has_zip = bool(remote_zip_etag)

    l_changed = (not bundle_state.get('local')) or bundle_state['local'] != local_zip_hash
    r_changed = remote_has_zip and (
        (not bundle_state.get('remote')) or bundle_state['remote'] != remote_zip_etag)

    bundle_action = 'none'
    if mode == 'upload':
        # 本地为准：只要任一端与基线不同，就用本地这份覆盖云端
        if not remote_has_zip or l_changed or r_changed:
            bundle_action = 'upload'
    elif mode == 'download':
        if remote_has_zip and (l_changed or r_changed):
            bundle_action = 'download'
    else:  # sync
        if not remote_has_zip:
            bundle_action = 'upload' if local_zip else 'none'
        elif l_changed and r_changed:
            bundle_action = 'conflict'
        elif l_changed:
            bundle_action = 'upload'
        elif r_changed:
            bundle_action = 'download'

    if bundle_action == 'conflict':
        conflicts.append({
            'key': 'icons.zip',
            'kind': 'icons',
            'label': f'图标包（本地 {len(os.listdir(LOCAL_ICON_DIR)) if os.path.isdir(LOCAL_ICON_DIR) else 0} 个）',
        })

    # 云端还没有图标包时的兜底：只补下本地缺失的图标（通常一个都不差）
    missing_icons = []
    if mode != 'upload' and not remote_has_zip and remote_exists:
        icon_files = {}
        for info in client.list_files_recursive(REMOTE_ICON_DIR):
            rel = info['rel'][len(REMOTE_ICON_DIR):].lstrip('/')
            icon_files[rel] = info
        for rel in sorted(_referenced_icon_rels(final_entries)):
            if not os.path.exists(_local_path('icon/' + rel)) and rel in icon_files:
                missing_icons.append(rel)

    return {
        'links_action': links_action,
        'final_entries': final_entries,
        'groups_action': groups_action,
        'groups_final': sorted(groups_final),
        'groups_remote_exists': remote_has_groups,
        'bundle_action': bundle_action,
        'icons_zip': local_zip,
        'icons_count': len(os.listdir(LOCAL_ICON_DIR)) if os.path.isdir(LOCAL_ICON_DIR) else 0,
        'missing_icons': missing_icons,
        'icon_actions': [],
        'conflicts': conflicts,
        'remote_exists': remote_exists,
    }


# ---------------------------------------------------------------- 执行操作

def _rebuild_state(client):
    """同步完成后重建基线：图标包哈希/ETag、links.json 的 id 集合与哈希/ETag。"""
    local_links_path = os.path.join(LOCAL_API_DIR, 'links.json')
    links_ids = []
    links_cache = {}
    bundle_cache = {}
    if os.path.exists(local_links_path):
        with open(local_links_path, 'rb') as f:
            raw = f.read()
        links_cache = {
            'local': hashlib.sha256(raw).hexdigest(),
            'remote': client.head_etag(_remote_rel('links.json')) or '',
        }
        links_ids = [str(e.get('id')) for e in json.loads(raw.decode('utf-8'))]

    try:
        bundle_cache = {
            'local': hashlib.sha256(icons_zip_bytes()).hexdigest(),
            'remote': client.head_etag(_remote_rel(REMOTE_BUNDLE)) or '',
        }
    except Exception:
        bundle_cache = {}

    groups_cache = {}
    groups_ids = []
    try:
        local_groups = _read_local_groups()
        groups_ids = sorted(local_groups)
        etag = client.head_etag(_remote_rel(REMOTE_GROUPS)) or ''
        if local_groups or etag:
            groups_cache = {'local': _groups_hash(local_groups), 'remote': etag}
    except Exception:
        groups_cache = {}

    save_state({'files': {}, 'links_ids': links_ids, 'links': links_cache,
                'bundle': bundle_cache, 'groups': groups_cache, 'groups_ids': groups_ids})


def _execute_plan(plan, resolutions, mode):
    """
    执行计划。
    mode:
      'sync'    双向，按 resolutions 处理冲突
      'upload'  本地优先：冲突一律保留本地，且不执行任何下载
      'download' 云端优先：冲突一律使用云端，且不执行任何上传
    """
    resolutions = resolutions or {}
    done = {'uploaded': [], 'downloaded': [], 'backups': [], 'failed': []}

    client = _get_client()
    client.ensure_dir(REMOTE_DIR)
    client.ensure_dir(REMOTE_ICON_DIR)

    # ---------- links.json ----------
    la = plan['links_action']
    local_links_path = os.path.join(LOCAL_API_DIR, 'links.json')
    # upload/sync 模式：final 与本地不同则写本地并上传；download 模式：final 与本地不同则下载覆盖
    if mode != 'download' and la in ('upload', 'merge'):
        # 写入本地（若内容与最终结果不同）并上传
        final_bytes = json.dumps(plan['final_entries'], ensure_ascii=False, indent=2).encode('utf-8')
        if os.path.exists(local_links_path):
            with open(local_links_path, 'rb') as f:
                local_bytes = f.read()
        else:
            local_bytes = b'[]'
        if hashlib.sha256(final_bytes).hexdigest() != hashlib.sha256(local_bytes).hexdigest():
            with open(local_links_path, 'wb') as f:
                f.write(final_bytes)
            done['downloaded'].append('links.json(本地已合并更新)')
        client.upload_bytes(_remote_rel('links.json'), final_bytes)
        done['uploaded'].append('links.json')
    elif mode != 'upload' and la == 'download':
        remote_bytes = client.download_bytes(_remote_rel('links.json'))
        with open(local_links_path, 'wb') as f:
            f.write(remote_bytes)
        done['downloaded'].append('links.json')

    # ---------- groups.json（空分组名单，很小，有变化才传/取） ----------
    ga = plan.get('groups_action', 'none')
    groups_final = set(plan.get('groups_final') or [])
    if ga == 'upload' and mode != 'download':
        try:
            _write_local_groups(groups_final)
            client.upload_bytes(_remote_rel(REMOTE_GROUPS), _groups_bytes(groups_final))
            done['uploaded'].append('groups.json')
        except WebDAVError as e:
            done['failed'].append({'path': REMOTE_GROUPS, 'error': str(e)})
    elif ga == 'download' and mode != 'upload':
        try:
            raw = client.download_bytes(_remote_rel(REMOTE_GROUPS))
            remote_set = {str(g).strip() for g in json.loads(raw.decode('utf-8')) if str(g).strip()}
            _write_local_groups(remote_set)
            done['downloaded'].append('groups.json')
        except WebDAVError as e:
            done['failed'].append({'path': REMOTE_GROUPS, 'error': str(e)})

    # ---------- 图标（整包一次传/一次拉） ----------
    bundle_action = plan.get('bundle_action', 'none')
    if bundle_action == 'conflict' and mode == 'sync':
        bundle_action = 'upload' if resolutions.get('icons.zip') == 'local' else 'download'

    PROGRESS.update({'running': True, 'total': 1 if bundle_action in ('upload', 'download') else 0,
                     'done': 0,
                     'message': '图标包已是最新，无需处理' if bundle_action == 'none' else '正在处理图标包…'})
    rate_limited = None

    if bundle_action == 'upload' and mode != 'download':
        try:
            PROGRESS['message'] = f"正在上传图标包（{plan.get('icons_count', 0)} 个图标）…"
            client.upload_bytes(_remote_rel(REMOTE_BUNDLE), plan['icons_zip'])
            done['uploaded'].append(f"icons.zip({plan.get('icons_count', 0)} 个图标)")
            PROGRESS['done'] = 1
        except WebDAVRateLimit as e:
            rate_limited = e
            PROGRESS['message'] = str(e)
        except WebDAVError as e:
            done['failed'].append({'path': REMOTE_BUNDLE, 'error': str(e)})

    elif bundle_action == 'download' and mode != 'upload':
        try:
            PROGRESS['message'] = '正在下载图标包…'
            bundle = client.download_bytes(_remote_rel(REMOTE_BUNDLE))
            # 覆盖本地图标目录前先整目录备份
            done['backups'].append(_backup_tree('icon', '图标目录备份'))
            count = extract_icons_zip(bundle)
            done['downloaded'].append(f'icons.zip({count} 个图标)')
            PROGRESS['done'] = 1
        except WebDAVRateLimit as e:
            rate_limited = e
            PROGRESS['message'] = str(e)
        except WebDAVError as e:
            done['failed'].append({'path': REMOTE_BUNDLE, 'error': str(e)})

    # 云端还没有图标包时，补下本地缺失的少量图标
    for rel in plan.get('missing_icons', []):
        if rate_limited:
            break
        try:
            client.download_file(_remote_rel('icon/' + rel), _local_path('icon/' + rel))
            done['downloaded'].append('icon/' + rel)
        except WebDAVRateLimit as e:
            rate_limited = e
            PROGRESS['message'] = str(e)
            break
        except WebDAVError:
            continue

    if rate_limited:
        done['rate_limited'] = str(rate_limited)
        done['remaining'] = 0
        PROGRESS['running'] = False
        PROGRESS['message'] = str(rate_limited)
        return done

    _rebuild_state(client)
    done['remote_exists'] = True
    PROGRESS['running'] = False
    PROGRESS['done'] = PROGRESS['total']
    if not done['uploaded'] and not done['downloaded']:
        PROGRESS['message'] = '已是最新，无需上传/下载'
    else:
        PROGRESS['message'] = {'upload': '上传完成',
                               'download': '下载完成'}.get(mode, '同步完成')
    return done


def force_upload():
    """本地为准：把本地内容（含本地删除）推到云端，只传有变化的部分。"""
    plan = make_plan(mode='upload')
    return _execute_plan(plan, {}, 'upload')


def force_download():
    """云端为准：用云端内容覆盖本地（本地删了就从云端恢复），只拉有变化的部分。"""
    plan = make_plan(mode='download')
    if not plan['remote_exists']:
        raise WebDAVError('云端不存在 bookmark_api 文件夹，无法下载')
    return _execute_plan(plan, {}, 'download')


def sync(resolutions=None):
    """
    双向智能同步：条目合并 + 删除传播。
    resolutions: {'links:<id>'|'icon/<路径>': 'local'|'remote'}
    若存在未解决冲突，抛出异常并附 conflicts 显示标签列表。
    """
    resolutions = resolutions or {}
    plan = make_plan(resolutions, mode='sync')
    unresolved = [{'key': c['key'], 'label': c['label']}
                  for c in plan['conflicts']
                  if resolutions.get(c['key']) not in ('local', 'remote')]
    if unresolved:
        err = WebDAVError('存在未解决的冲突')
        err.conflicts = unresolved
        raise err
    return _execute_plan(plan, resolutions, 'sync')


def login(email, password):
    """验证并保存凭据。"""
    client = WebDAVClient(email, password)
    client.test_login()
    save_config(email.strip(), password)
    return True


def status():
    cfg = load_config()
    st = load_state()
    # 本地收藏数
    local_count = 0
    local_links_path = os.path.join(LOCAL_API_DIR, 'links.json')
    if os.path.exists(local_links_path):
        with open(local_links_path, encoding='utf-8') as f:
            local_count = len(json.load(f))

    # 云端收藏数：先 HEAD 看 ETag，未变则用缓存（不产生正文流量）
    remote_count = None
    cache = st.get('remote_count_cache', {})
    try:
        if cfg.get('email') and cfg.get('password') and not rate_limit_remaining():
            # 状态查询要快：限流/网络异常时不拖住面板
            client = WebDAVClient(cfg['email'], cfg['password'], timeout=8)
            etag = client.head_etag(_remote_rel('links.json'))
            if etag is None:
                remote_count = 0
            elif cache.get('etag') == etag and 'count' in cache:
                remote_count = cache['count']
            else:
                data = client.download_bytes(_remote_rel('links.json'))
                remote_count = len(json.loads(data.decode('utf-8')))
                st['remote_count_cache'] = {'etag': etag, 'count': remote_count}
                save_state(st)
    except Exception:
        # 失败时退回上次缓存的数量，避免面板一片空白
        if 'count' in cache:
            remote_count = cache['count']

    return {
        'logged_in': bool(cfg.get('email')),
        'email': cfg.get('email', ''),
        'saved_at': cfg.get('saved_at', ''),
        'last_sync': st.get('last_sync', ''),
        'local_count': local_count,
        'remote_count': remote_count,
        'rate_limit_wait': rate_limit_remaining(),
    }
