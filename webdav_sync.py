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
import json
import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
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

DAV_NS = {'D': 'DAV:'}

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


class WebDAVClient:
    def __init__(self, email, password, timeout=30):
        self.email = email
        self.password = password
        self.timeout = timeout
        token = base64.b64encode(f'{email}:{password}'.encode()).decode()
        self.auth = 'Basic ' + token

    def _url(self, rel_path, as_dir=False):
        rel_path = rel_path.strip('/')
        if not rel_path:
            return WEBDAV_ROOT
        url = WEBDAV_ROOT + urllib.parse.quote(rel_path)
        # 目录（MKCOL/PROPFIND）以 / 结尾；文件（PUT/GET）不能带斜杠，
        # 否则坚果云会把文件当作集合资源，返回 403 OperationNotAllowed
        return url + '/' if as_dir else url

    def _request(self, rel_path, method='GET', data=None, extra_headers=None,
                 as_dir=False):
        req = urllib.request.Request(self._url(rel_path, as_dir), data=data, method=method)
        req.add_header('Authorization', self.auth)
        if extra_headers:
            for k, v in extra_headers.items():
                req.add_header(k, v)
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            # 404 等情况把响应体读出便于上层判断
            try:
                body = e.read().decode('utf-8', 'ignore')
            except Exception:
                body = ''
            err = WebDAVError(f'HTTP {e.code}: {e.reason} {body[:200]}', e.code)
            err.body = body
            raise err
        except urllib.error.URLError as e:
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
            if is_dir:
                dirs.append(name)
            else:
                files.append({
                    'name': name,
                    'rel': (rel_path + '/' + name).strip('/'),
                    'etag': (etag or '').strip('"'),
                    'lastmodified': lastmod or '',
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
        """HEAD 请求，只返回 ETag（不下载文件体，几乎无流量）。
        文件不存在返回 None。"""
        try:
            resp = self._request(rel_path, method='HEAD')
            resp.read()
            return resp.headers.get('ETag') or ''
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


# ---------------------------------------------------------------- 备份

def backup_local(tag='backup'):
    """把 links.json 与 icon/ 备份到 backups/<tag>_<时间戳>/，返回备份目录。"""
    stamp = _now_str()
    dest = os.path.join(BACKUP_DIR, f'{tag}_{stamp}')
    os.makedirs(os.path.join(dest, 'icon'), exist_ok=True)
    links = os.path.join(LOCAL_API_DIR, 'links.json')
    if os.path.exists(links):
        shutil.copy2(links, os.path.join(dest, 'links.json'))
    if os.path.isdir(LOCAL_ICON_DIR):
        for name in os.listdir(LOCAL_ICON_DIR):
            p = os.path.join(LOCAL_ICON_DIR, name)
            if os.path.isfile(p):
                shutil.copy2(p, os.path.join(dest, 'icon', name))
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
        remote_exists and remote_etag is not None and
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

    # ---------- 图标：只看最终引用到的文件，逐文件增量比对 ----------
    state = load_state().get('files', {})
    remote_files = {}
    if remote_exists:
        for info in client.list_files_recursive(REMOTE_DIR):
            rel = info['rel'][len(REMOTE_DIR):].lstrip('/')
            remote_files[rel] = info

    icon_actions = []
    for rel in sorted(_referenced_icon_rels(final_entries)):
        l_path = _local_path('icon/' + rel)
        l_hash = _sha256_of_file(l_path) if os.path.exists(l_path) else None
        r_info = remote_files.get('icon/' + rel)
        base = state.get('icon/' + rel, {})

        if l_hash and r_info:
            l_changed = (not base.get('local')) or l_hash != base.get('local')
            r_changed = (not base.get('remote')) or r_info['etag'] != base.get('remote')
            if not base and (l_changed or r_changed):
                # 无基线时直接下载内容比对，相同则跳过并在执行时建立基线
                if hashlib.sha256(client.download_bytes(r_info['rel'])).hexdigest() == l_hash:
                    continue
                l_changed = r_changed = True
            if not l_changed and not r_changed:
                continue
            action = 'upload' if l_changed and not r_changed else \
                     'download' if r_changed and not l_changed else 'conflict'
        elif l_hash:
            action = 'upload'
        else:
            action = 'download' if r_info else 'none'

        icon_actions.append({'path': 'icon/' + rel, 'action': action})
        if action == 'conflict':
            conflicts.append({
                'key': 'icon/' + rel,
                'kind': 'icon',
                'label': '图标 icon/' + rel,
            })

    return {
        'links_action': links_action,
        'final_entries': final_entries,
        'icon_actions': icon_actions,
        'conflicts': conflicts,
        'remote_exists': remote_exists,
    }


# ---------------------------------------------------------------- 执行操作

def _rebuild_state(client):
    """同步完成后，用实际本地哈希 + 云端最新 ETag 重建基线。"""
    state_files = {}
    remote = {}
    if client.exists(REMOTE_DIR):
        for info in client.list_files_recursive(REMOTE_DIR):
            rel = info['rel'][len(REMOTE_DIR):].lstrip('/')
            remote[rel] = info['etag']
    for rel in list_local_files():
        state_files[rel] = {
            'local': _sha256_of_file(_local_path(rel)),
            'remote': remote.get(rel, ''),
        }
    # 记录当前 links.json 的 id 集合 + 本地哈希/云端ETag，用于下次同步
    local_links_path = os.path.join(LOCAL_API_DIR, 'links.json')
    links_ids = []
    links_cache = {}
    if os.path.exists(local_links_path):
        with open(local_links_path, 'rb') as f:
            raw = f.read()
        links_cache = {
            'local': hashlib.sha256(raw).hexdigest(),
            'remote': client.head_etag(_remote_rel('links.json')) or '',
        }
        links_ids = [str(e.get('id')) for e in json.loads(raw.decode('utf-8'))]
    save_state({'files': state_files, 'links_ids': links_ids, 'links': links_cache})


def _execute_plan(plan, resolutions, mode):
    """
    执行计划。
    mode:
      'sync'    双向，按 resolutions 处理冲突
      'upload'  本地优先：冲突一律保留本地，且不执行任何下载
      'download' 云端优先：冲突一律使用云端，且不执行任何上传
    """
    resolutions = resolutions or {}
    done = {'uploaded': [], 'downloaded': [], 'backups': []}

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

    # ---------- 图标 ----------
    for act in plan['icon_actions']:
        rel, action = act['path'], act['action']
        local_path = _local_path(rel)
        remote_rel = _remote_rel(rel)

        if action == 'upload' or (action == 'conflict' and mode == 'upload'):
            if mode != 'download':
                client.upload_file(local_path, remote_rel)
                done['uploaded'].append(rel)

        elif action == 'download' or (action == 'conflict' and mode == 'download'):
            if mode != 'upload':
                # 覆盖前备份本地
                if os.path.exists(local_path):
                    with open(local_path, 'rb') as f:
                        done['backups'].append(
                            _backup_file(rel, f.read(), '本地版本备份'))
                client.download_file(remote_rel, local_path)
                done['downloaded'].append(rel)

        elif action == 'conflict' and mode == 'sync':
            choice = resolutions.get(rel)
            if choice == 'local':
                remote_bytes = client.download_bytes(remote_rel)
                done['backups'].append(_backup_file(rel, remote_bytes, '云端版本备份'))
                client.upload_file(local_path, remote_rel)
                done['uploaded'].append(rel)
            else:
                if os.path.exists(local_path):
                    with open(local_path, 'rb') as f:
                        done['backups'].append(
                            _backup_file(rel, f.read(), '本地版本备份'))
                client.download_file(remote_rel, local_path)
                done['downloaded'].append(rel)

    _rebuild_state(client)
    done['remote_exists'] = True
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
        if cfg.get('email') and cfg.get('password'):
            client = WebDAVClient(cfg['email'], cfg['password'])
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
        pass

    return {
        'logged_in': bool(cfg.get('email')),
        'email': cfg.get('email', ''),
        'saved_at': cfg.get('saved_at', ''),
        'last_sync': st.get('last_sync', ''),
        'local_count': local_count,
        'remote_count': remote_count,
    }
