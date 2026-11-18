# -*- coding: utf-8 -*-
import time

from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import os
import re
import unicodedata
from urllib.parse import urlparse, urljoin


# app = Flask(__name__)
app = Flask(__name__)
CORS(app)  # 允许跨域请求

import webdav_sync  # 坚果云 WebDAV 同步模块

DATA_FILE = 'static/api/links.json'


# 添加入口路由，返回到网页导航.html页面
@app.route('/')
def index():
    try:
        return app.send_static_file('网页导航.html')
    except Exception as e:
        return jsonify({'error': '网页导航.html文件不存在'}), 404


# css和js文件
@app.route('/<path:filename>')
def static_files(filename):
    try:
        return app.send_static_file(filename)
    except Exception as e:
        print(e)
        return jsonify({'error': f'{filename}文件不存在'}), 404


def load_data():
    """加载JSON数据（UTF-8）"""
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False)
    with open(DATA_FILE, encoding='utf-8') as f:
        return json.load(f)


def _backup_data_file(max_keep=20):
    """写盘前先把现有 links.json 复制一份到 backups/，只保留最近 max_keep 份。"""
    try:
        if not os.path.exists(DATA_FILE):
            return None
        backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        stamp = time.strftime('%Y%m%d_%H%M%S')
        dst = os.path.join(backup_dir, 'links_auto_%s.json' % stamp)
        if not os.path.exists(dst):
            with open(DATA_FILE, encoding='utf-8') as src, open(dst, 'w', encoding='utf-8') as out:
                out.write(src.read())
        autos = sorted(name for name in os.listdir(backup_dir) if name.startswith('links_auto_'))
        for old in autos[:-max_keep]:
            try:
                os.remove(os.path.join(backup_dir, old))
            except OSError:
                pass
        return dst
    except Exception:
        return None


# 从飞书/微信等处复制标题时会带上一串看不见的格式字符（Unicode Cf 类：U+202C、U+200B、U+2060、U+FEFF…），
# 这些字符宽度为 0，会让前端的“截断 20 字”变成空白，看起来像没有名称。
_INVISIBLE_RE = re.compile('[\u00ad\u115f\u1160\u3164\uffa0]')


def clean_text(value):
    """去掉不可见格式字符（Cf 类 + 特殊空白填充符），折叠多余空白，返回干净文本。"""
    s = ''.join(ch for ch in str(value or '') if unicodedata.category(ch) != 'Cf')
    s = _INVISIBLE_RE.sub('', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _name_fallback(item):
    """名称被清空时用域名兜底，避免出现无名书签。"""
    try:
        host = urlparse(item.get('url') or '').netloc
    except Exception:
        host = ''
    return host or '未命名书签'


def save_data(data):
    """保存数据到JSON文件（UTF-8，保留中文）。
    先写临时文件再原子替换，避免写一半留下坏文件；写之前自动备份。
    落盘前统一清洗名称/分组里的不可见字符。"""
    for item in data or []:
        if isinstance(item, dict):
            if 'name' in item:
                cleaned = clean_text(item.get('name'))
                item['name'] = cleaned or _name_fallback(item)
            if 'group' in item and isinstance(item.get('group'), str):
                item['group'] = clean_text(item.get('group'))
    _backup_data_file()
    tmp = DATA_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, DATA_FILE)


# ---------------- 分组注册表（让空分组也能存在、能显示、能改名） ----------------
GROUPS_FILE = 'static/api/groups.json'


def load_groups():
    """读取分组注册表（只存分组名，含空分组）"""
    try:
        if not os.path.exists(GROUPS_FILE):
            return []
        with open(GROUPS_FILE, encoding='utf-8') as f:
            raw = json.load(f)
        return [g.strip() for g in raw if isinstance(g, str) and g.strip()]
    except Exception:
        return []


def save_groups(groups):
    """写分组注册表：去重去空，UTF-8，先写临时文件再替换"""
    seen, cleaned = set(), []
    for g in groups or []:
        g = clean_text(g).strip('/')
        if not g or g in seen:
            continue
        seen.add(g)
        cleaned.append(g)
    tmp = GROUPS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cleaned, f, indent=2, ensure_ascii=False)
    os.replace(tmp, GROUPS_FILE)
    return cleaned


def group_names_from_links(data):
    """links.json 里出现过的分组（空值归到首页）"""
    names = set()
    for item in data or []:
        g = (item.get('group') or '').strip() or '首页'
        names.add(g)
    return names


@app.route('/api/groups', methods=['GET'])
def list_groups():
    """返回全部分组名（注册表 + links.json 里实际用到的）"""
    try:
        names = group_names_from_links(load_data()) | set(load_groups())
        return jsonify(sorted(names))
    except Exception as e:
        return jsonify({'error': '读取分组失败', 'detail': str(e)}), 500


@app.route('/api/groups', methods=['POST'])
def create_group():
    """新建（空白）分组"""
    try:
        name = ((request.json or {}).get('name') or '').strip().strip('/')
        if not name:
            return jsonify({'error': '分组名称不能为空'}), 400
        if len(name) > 60:
            return jsonify({'error': '分组名称太长'}), 400
        data = load_data()
        existing = group_names_from_links(data) | set(load_groups())
        if name in existing:
            return jsonify({'error': '分组已存在', 'groups': sorted(existing)}), 409
        groups = save_groups(list(load_groups()) + [name])
        return jsonify({'success': True, 'groups': sorted(set(groups) | group_names_from_links(data))})
    except Exception as e:
        return jsonify({'error': '新建分组失败', 'detail': str(e)}), 500


@app.route('/api/groups/rename', methods=['POST'])
def rename_group():
    """分组改名：同步改掉所有条目，子分组（父/子）一起改"""
    try:
        body = request.json or {}
        old = (body.get('from') or '').strip().strip('/')
        new = (body.get('to') or '').strip().strip('/')
        if not old or not new:
            return jsonify({'error': '分组名称不能为空'}), 400
        if old == '首页':
            return jsonify({'error': '「首页」是保留分组，不能重命名'}), 400
        if new == '首页':
            return jsonify({'error': '不能把分组改成「首页」，该名称是保留分组'}), 400
        if new == old:
            return jsonify({'success': True, 'renamed': 0})
        if len(new) > 60:
            return jsonify({'error': '分组名称太长'}), 400

        data = load_data()
        old_set = group_names_from_links(data) | set(load_groups())
        if old not in old_set:
            return jsonify({'error': '分组不存在'}), 404
        if new in old_set:
            return jsonify({'error': '目标分组已存在'}), 409

        renamed = 0
        for item in data:
            g = (item.get('group') or '').strip() or '首页'
            if g == old:
                item['group'] = new
                renamed += 1
            elif g.startswith(old + '/'):
                item['group'] = new + g[len(old):]
                renamed += 1

        # 注册表里的父分组与子分组一起改名
        groups = []
        for g in load_groups():
            if g == old:
                groups.append(new)
            elif g.startswith(old + '/'):
                groups.append(new + g[len(old):])
            else:
                groups.append(g)

        save_data(data)
        save_groups(groups + [new] + [x['group'] for x in data])
        return jsonify({'success': True, 'renamed': renamed})
    except Exception as e:
        return jsonify({'error': '重命名失败', 'detail': str(e)}), 500


@app.route('/api/groups/delete', methods=['POST'])
def delete_group():
    """删除分组：组内书签全部转到「未分组」（没有就自动建）。
    有子分组时先拒绝，避免误删整棵树。"""
    try:
        name = (((request.json or {}).get('name')) or '').strip().strip('/')
        if not name:
            return jsonify({'error': '分组名称不能为空'}), 400
        if name in ('首页', '未分组'):
            return jsonify({'error': f'「{name}」是保留分组，不能删除'}), 400

        data = load_data()
        groups = group_names_from_links(data) | set(load_groups())
        if name not in groups:
            return jsonify({'error': '分组不存在'}), 404

        children = sorted(g for g in groups if g.startswith(name + '/'))
        if children:
            return jsonify({'error': f'「{name}」下还有 {len(children)} 个子分组，请先删除子分组',
                            'children': children}), 409

        target = '未分组'
        moved = 0
        for item in data:
            g = (item.get('group') or '').strip() or '首页'
            if g == name:
                item['group'] = target
                moved += 1

        groups.discard(name)
        groups.add(target)
        save_data(data)
        save_groups(list(groups) + [x['group'] for x in data])
        return jsonify({'success': True, 'moved': moved, 'target': target})
    except Exception as e:
        return jsonify({'error': '删除分组失败', 'detail': str(e)}), 500





@app.route('/api/links/save', methods=['POST'])
def save_links():
    try:
        data = request.json
        save_data(data)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': '保存失败'}), 500


def normalize_group(item):
    """分组字段规整：去空白，空值归到「首页」。"""
    g = (item.get('group') or '').strip()
    item['group'] = g or '首页'


def validate_item(item):
    """验证数据项有效性"""
    try:
        # 验证URL格式
        parsed = urlparse(item['url'])
        if not all([parsed.scheme, parsed.netloc]):
            return False
        # 验证名称非空
        return bool(item.get('name', '').strip())
    except:
        return False


# RESTful API Endpoints
@app.route('/api/links', methods=['GET'])
def get_links():
    try:
        data = load_data()
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': '读取数据失败'}), 500


# 判断是否为本地绝对路径（如 D:\xxx.png 或 C:/xxx.jpg）
def _is_local_path(p):
    return (len(p) >= 3 and p[0].isalpha() and p[1] == ':'
            and p[2] in '\\/')


APP_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_DIR = os.path.join(APP_DIR, 'static', 'api', 'icon')
_ICON_EXTS = {'png', 'jpg', 'jpeg', 'gif', 'ico', 'svg', 'webp', 'bmp'}


def _icon_rel_path(filename):
    """返回给前端用的相对路径（static/api/icon/xxx）"""
    return 'static/api/icon/' + filename


def _safe_icon_stem(name, url):
    """用网站名称生成安全的文件名：去掉 Windows 非法字符，附短哈希防重名。"""
    import hashlib
    import re
    base = re.sub(r'[\\/:*?"<>|\r\n\t]', '', str(name or '')).strip()[:40] or 'icon'
    if base in ('.', '..'):
        base = 'icon'
    h = hashlib.md5(str(url or '').encode('utf-8')).hexdigest()[:6]
    return f'{base}_{h}'


# 下载网络资源 / 复制本地图标到 icon 目录
def download_link(url, name):
    """把网络图标或本地图标统一落到 static/api/icon 下，返回相对路径。
    失败时原样返回（条目照样保存，只是没有本地图标）。"""
    import shutil
    try:
        os.makedirs(ICON_DIR, exist_ok=True)
    except Exception:
        pass
    try:
        if url.startswith('http'):
            # 网络图标：下载到本地 icon 目录
            import requests
            response = requests.get(url, timeout=8)  # 加超时，避免外网不可达时长时间阻塞
            if response.status_code != 200 or not response.content:
                return url
            ctype = (response.headers.get('Content-Type') or '').split(';')[0].strip().lower()
            ext = _ICON_MIME_EXT.get(ctype)
            if not ext:
                # 从 URL 路径取扩展名（去掉 ?query 与 #hash）
                path_part = urlparse(url).path
                ext = os.path.splitext(path_part)[1].lstrip('.').lower()
            if ext not in _ICON_EXTS:
                ext = 'png'
            filename = _safe_icon_stem(name, url) + '.' + ext
            with open(os.path.join(ICON_DIR, filename), 'wb') as f:
                f.write(response.content)
            response.close()
            return _icon_rel_path(filename)

        elif _is_local_path(url) and os.path.isfile(url):
            # 本地图标：复制到 icon 目录（浏览器无法直接加载 D:\ 这类本地路径）
            ext = os.path.splitext(url)[1].lstrip('.').lower()
            if ext not in _ICON_EXTS:
                ext = 'png'
            filename = _safe_icon_stem(name, url) + '.' + ext
            shutil.copyfile(url, os.path.join(ICON_DIR, filename))
            return _icon_rel_path(filename)
        else:
            return url
    except Exception as e:
        print('图标保存失败：', e)
        return url
    except Exception as e:
        return url


@app.route('/api/links', methods=['POST'])
def create_link():
    try:
        new_item = request.json
        if not validate_item(new_item):
            return jsonify({'error': '无效数据格式'}), 400

        new_item['id'] = new_item.get('id') or int(time.time() * 1000)
        new_item['name'] = clean_text(new_item.get('name')) or _name_fallback(new_item)
        normalize_group(new_item)
        if new_item.get('icon') and (new_item.get('icon').startswith('http')
                                     or _is_local_path(new_item.get('icon'))):
            new_item['icon'] = download_link(new_item.get('icon'), new_item.get('name'))
        data = load_data()
        data.append(new_item)
        save_data(data)
        return jsonify(new_item), 201
    except Exception as e:
        return jsonify({'error': '创建失败'}), 500


@app.route('/api/links/<int:id>', methods=['PUT'])
def update_link(id):
    try:
        data = load_data()
        index = next((i for i, item in enumerate(data) if item['id'] == id), -1)

        if index == -1:
            return jsonify({'error': '条目不存在'}), 404

        if not validate_item(request.json):
            return jsonify({'error': '无效数据格式'}), 400

        new_item = request.json
        new_item['name'] = clean_text(new_item.get('name')) or _name_fallback(new_item)
        normalize_group(new_item)
        if new_item.get('icon') and (new_item.get('icon').startswith('http')
                                     or _is_local_path(new_item.get('icon'))):
            new_item['icon'] = download_link(new_item.get('icon'), new_item.get('name'))

        data[index].update(new_item)
        save_data(data)
        return jsonify(data[index])
    except Exception as e:
        return jsonify({'error': '更新失败'}), 500


@app.route('/api/links/<int:id>', methods=['DELETE'])
def delete_link(id):
    try:
        data = load_data()
        new_data = [item for item in data if item['id'] != id]

        if len(new_data) == len(data):
            return jsonify({'error': '条目不存在'}), 404

        save_data(new_data)
        return '', 204
    except Exception as e:
        return jsonify({'error': '删除失败'}), 500


# ==================== 书签辅助：图标探测 / 已打开网页 ====================

def _same_origin_only():
    """只允许同源页面调用这些敏感接口，防止其他网站跨站读取本机信息。"""
    origin = request.headers.get('Origin') or ''
    if not origin:
        return True
    try:
        from urllib.parse import urlparse as _up
        return _up(origin).netloc == request.host
    except Exception:
        return False


_ICON_MIME_EXT = {
    'image/png': 'png', 'image/x-icon': 'ico', 'image/vnd.microsoft.icon': 'ico',
    'image/jpeg': 'jpg', 'image/gif': 'gif', 'image/svg+xml': 'svg',
    'image/webp': 'webp', 'image/bmp': 'bmp', 'image/vnd.microsoft.icon': 'ico',
}

_LINK_TAG_RE = None


def _parse_icon_candidates(html_text, base_url):
    """从网页 HTML 中挑出候选图标地址，按优先级排序。"""
    import re
    cands = []
    for tag in re.findall(r'<link\b[^>]*>', html_text, re.I):
        rel_m = re.search(r'rel\s*=\s*["\']([^"\']*)["\']', tag, re.I)
        href_m = re.search(r'href\s*=\s*["\']([^"\']+)["\']', tag, re.I)
        if not rel_m or not href_m:
            continue
        rel = rel_m.group(1).lower()
        if 'icon' not in rel:
            continue
        if 'mask-icon' in rel:          # 单色遮罩图标，不能当网站图标用
            continue
        href = href_m.group(1).strip()
        if href.startswith('data:'):
            continue
        score = 0
        if 'apple-touch-icon' in rel:
            score = 180
        else:
            size_m = re.search(r'sizes\s*=\s*["\']([^"\']+)["\']', tag, re.I)
            if size_m:
                for token in size_m.group(1).lower().split():
                    m = re.match(r'(\d+)x(\d+)', token)
                    if m:
                        score = max(score, int(m.group(1)))
            if not score:
                score = 5 if href.lower().endswith('.svg') else 32
        cands.append((score, urljoin(base_url, href)))
    cands.sort(key=lambda x: -x[0])
    # 去重保序
    seen, out = set(), []
    for score, u in cands:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


@app.route('/api/links/favicon', methods=['GET'])
def probe_favicon():
    """探测指定网页的站点图标，下载到本地 icon 目录并返回本地路径。"""
    import hashlib
    import re
    import requests

    raw = (request.args.get('url') or '').strip()
    if not raw:
        return jsonify({'error': '缺少 url 参数'}), 400
    if not re.match(r'^https?://', raw, re.I):
        raw = 'http://' + raw

    headers = {
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/120.0 Safari/537.36'),
        'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
    }
    html_text, final_url = '', raw
    try:
        r = requests.get(raw, headers=headers, timeout=8, allow_redirects=True)
        final_url = r.url or raw
        ctype = (r.headers.get('Content-Type') or '').lower()
        if 'html' in ctype or not ctype:
            html_text = r.text[:300000]
        else:
            html_text = ''
    except Exception:
        html_text = ''

    candidates = _parse_icon_candidates(html_text, final_url) if html_text else []
    candidates.append(urljoin(final_url, '/favicon.ico'))

    # 只返回图标的网络地址，不落盘：真正保存到 icon 目录发生在「保存」时，
    # 避免每次探测都在本地留下一堆临时文件。
    last_err = ''
    for cand in candidates[:6]:
        try:
            resp = requests.get(cand, headers={'User-Agent': headers['User-Agent']},
                                timeout=8, allow_redirects=True)
            if resp.status_code != 200 or not resp.content:
                last_err = f'HTTP {resp.status_code}'
                continue
            if len(resp.content) > 2 * 1024 * 1024:
                last_err = '图标过大'
                continue
            ctype = (resp.headers.get('Content-Type') or '').split(';')[0].strip().lower()
            if ctype and not ctype.startswith('image/'):
                last_err = f'不是图片：{ctype}'
                continue
            return jsonify({'icon': cand, 'source': cand, 'temporary': True})
        except Exception as e:
            last_err = str(e)
            continue

    return jsonify({'error': '没有找到可用的网站图标', 'detail': last_err}), 404


@app.route('/api/links/icon-preview', methods=['GET'])
def icon_preview():
    """预览本地图标文件（仅限图片扩展名），用于弹窗里的缩略图。"""
    if not _same_origin_only():
        return jsonify({'error': 'forbidden'}), 403
    p = (request.args.get('path') or '').strip()
    if not p:
        return jsonify({'error': '缺少 path 参数'}), 400
    ext = os.path.splitext(p)[1].lstrip('.').lower()
    if ext not in ('png', 'jpg', 'jpeg', 'gif', 'ico', 'svg', 'webp', 'bmp'):
        return jsonify({'error': '不支持的文件类型'}), 400
    if not (os.path.isabs(p) and os.path.isfile(p)):
        return jsonify({'error': '文件不存在'}), 404
    from flask import send_file
    return send_file(p, max_age=60)


@app.route('/api/tabs', methods=['GET'])
def list_open_tabs():
    """列出本机已打开浏览器的标签页标题（不切换标签页，无闪动）。"""
    if not _same_origin_only():
        return jsonify({'error': 'forbidden'}), 403
    try:
        data = _run_tabs_script(['-Mode', 'titles'])
        return jsonify({'tabs': data if isinstance(data, list) else [data]})
    except Exception as e:
        return jsonify({'error': str(e), 'tabs': []}), 500


@app.route('/api/tabs/url', methods=['GET'])
def read_tab_url():
    """读取某一个标签页的网址：只切换这一个标签，读完立刻切回。"""
    if not _same_origin_only():
        return jsonify({'error': 'forbidden'}), 403
    win = request.args.get('win', type=int)
    idx = request.args.get('idx', type=int)
    if win is None or idx is None or idx < 0:
        return jsonify({'error': '缺少 win / idx 参数'}), 400
    try:
        data = _run_tabs_script(['-Mode', 'url', '-Win', str(win), '-Index', str(idx)])
        url = data.get('url', '') if isinstance(data, dict) else ''
        return jsonify({'url': url})
    except Exception as e:
        return jsonify({'error': str(e), 'url': ''}), 500


def _run_tabs_script(args):
    """调用 browser_tabs.ps1，返回解析后的 JSON（列表或字典）。"""
    import subprocess
    script = os.path.join(APP_DIR, 'browser_tabs.ps1')
    if not os.path.exists(script):
        raise RuntimeError('缺少 browser_tabs.ps1')

    creationflags = 0x08000000 if os.name == 'nt' else 0  # CREATE_NO_WINDOW
    proc = subprocess.run(
        ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script] + args,
        capture_output=True, timeout=45, creationflags=creationflags)
    out = (proc.stdout or b'').decode('utf-8', 'ignore').strip()
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith('[') or line.startswith('{'):
            return json.loads(line)
    return []


@app.route('/api/links/order', methods=['POST'])
def update_order():
    """调整顺序。只做重排，绝不删除条目：
    把传来的 id 按新顺序填回它们原本占用的位置，没传到的条目位置不动。"""
    try:
        body = request.json or {}
        new_order = body.get('nod') or []
        if not isinstance(new_order, list) or not new_order:
            # 空列表直接返回当前数据，避免把 links.json 清空
            return jsonify(load_data())

        data = load_data()
        by_id = {str(x.get('id')): x for x in data}

        # 去重 + 只保留真实存在的 id（前端可能传来重复或过期的 id）
        wanted, seen = [], set()
        for key in new_order:
            key = str(key)
            if key in by_id and key not in seen:
                seen.add(key)
                wanted.append(key)

        slots = [i for i, x in enumerate(data) if str(x.get('id')) in seen]
        rebuilt = [None] * len(data)
        for slot, key in zip(slots, wanted):
            rebuilt[slot] = by_id[key]
        rest = iter([x for x in data if str(x.get('id')) not in seen])
        for i in range(len(rebuilt)):
            if rebuilt[i] is None:
                rebuilt[i] = next(rest, None)
        ordered = [x for x in rebuilt if x is not None]

        # 硬保护：条数只许多不许少，一旦算错就放弃写盘，避免再次丢数据
        if len(ordered) != len(data):
            return jsonify({'error': '顺序计算结果条数异常，已放弃写入',
                            'expected': len(data), 'got': len(ordered)}), 500

        save_data(ordered)
        return jsonify(ordered)
    except Exception as e:
        return jsonify({'error': '顺序更新失败', 'detail': str(e)}), 500


@app.route('/api/links/<id>', methods=['GET'])
def get_link(id):
    try:
        data = load_data()
        item = next((i for i in data if str(i['id']) == id), None)

        if not item:
            return jsonify({"error": "条目不存在"}), 404

        return jsonify(item)
    except Exception as error:
        return jsonify({"error": "服务器内部错误", "detail": str(error)}), 500


# ==================== 坚果云同步相关接口 ====================

def _sync_error(e, code=500):
    """统一处理同步模块异常；冲突返回 409。"""
    conflicts = getattr(e, 'conflicts', None)
    if conflicts is not None:
        return jsonify({'error': str(e), 'conflicts': conflicts}), 409
    return jsonify({'error': str(e)}), code


@app.route('/api/sync/status', methods=['GET'])
def sync_status():
    try:
        return jsonify(webdav_sync.status())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/sync/login', methods=['POST'])
def sync_login():
    try:
        body = request.json or {}
        email = (body.get('email') or '').strip()
        password = body.get('password') or ''
        if not email or not password:
            return jsonify({'error': '请输入坚果云邮箱和WebDAV应用密码'}), 400
        webdav_sync.login(email, password)
        return jsonify({'success': True, **webdav_sync.status()})
    except Exception as e:
        return _sync_error(e, 401)


@app.route('/api/sync/logout', methods=['POST'])
def sync_logout():
    try:
        webdav_sync.clear_config()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/sync/sync', methods=['POST'])
def sync_run():
    try:
        body = request.json or {}
        result = webdav_sync.sync(body.get('resolutions') or {})
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        return _sync_error(e)


@app.route('/api/sync/upload', methods=['POST'])
def sync_upload():
    """上传到云端：改到后台线程执行，前端轮询 /api/sync/progress 看进度。
    600+ 个图标逐个上传要好几分钟，同步阻塞请求容易超时。"""
    import threading
    body = request.json or {}

    if webdav_sync.PROGRESS.get('running'):
        return jsonify({'success': False, 'running': True,
                        'error': '上一个上传任务还在进行中，请等它结束'}), 409

    remain = webdav_sync.rate_limit_remaining()
    if remain:
        return jsonify({'success': False, 'rate_limited': True, 'wait_seconds': remain,
                        'error': f'坚果云正在限流，请约 {max(1, remain // 60)} 分钟后再点上传'}), 429

    if not body.get('background'):
        # 兼容直接调用的场景：同步执行
        try:
            uploaded = webdav_sync.force_upload(full=bool(body.get('full')))
            return jsonify({'success': True, 'result': uploaded})
        except Exception as e:
            return _sync_error(e)

    webdav_sync._reset_progress()
    full = bool(body.get('full'))

    def _worker():
        try:
            webdav_sync.PROGRESS['result'] = webdav_sync.force_upload(full=full)
        except Exception as e:
            webdav_sync.PROGRESS['error'] = str(e)
        finally:
            webdav_sync.PROGRESS['running'] = False

    webdav_sync.PROGRESS['running'] = True
    webdav_sync.PROGRESS['message'] = '正在准备…'
    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({'success': True, 'started': True})


@app.route('/api/sync/progress', methods=['GET'])
def sync_progress():
    p = dict(webdav_sync.PROGRESS)
    p['wait_seconds'] = webdav_sync.rate_limit_remaining()
    return jsonify(p)


@app.route('/api/sync/download', methods=['POST'])
def sync_download():
    try:
        body = request.json or {}
        result = webdav_sync.force_download(full=bool(body.get('full')))
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        return _sync_error(e)


@app.route('/api/sync/backup', methods=['POST'])
def sync_backup():
    try:
        path = webdav_sync.backup_local('手动备份')
        return jsonify({'success': True, 'backup': path})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    # 获取本机IP地址
    from socket import gethostbyname, gethostname

    host = gethostbyname(gethostname())
    port = 3000

    print(f"服务运行在 http://{host}:{port}")
    print(f"局域网访问地址: http://{host}:{port}")

    # threaded=True 支持并发请求；debug=False 关闭自动重载，
    # 避免 pythonw 后台运行时重载器在请求过程中杀死子进程导致 “Failed to fetch”
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
