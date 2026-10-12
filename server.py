# -*- coding: utf-8 -*-
import time

from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import os
from urllib.parse import urlparse


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
    """加载JSON数据"""
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w') as f:
            json.dump([], f)
    with open(DATA_FILE) as f:
        return json.load(f)


def save_data(data):
    """保存数据到JSON文件"""
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)


@app.route('/api/links/save', methods=['POST'])
def save_links():
    try:
        data = request.json
        save_data(data)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': '保存失败'}), 500


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


# 下载网络资源 / 复制本地图标到 icon 目录
def download_link(url, name):
    os.makedirs('static/api/icon/', exist_ok=True)
    try:
        if url.startswith('http'):
            # 网络图标：下载到本地 icon 目录
            import requests
            response = requests.get(url, timeout=8)  # 加超时，避免外网不可达时长时间阻塞
            if response.status_code != 200:
                return url
            ext = url.split('.')[-1]
            icon_path = f'static/api/icon/{name}.{ext}'
            with open(icon_path, 'wb') as f:
                f.write(response.content)
            response.close()
            return icon_path
        elif _is_local_path(url) and os.path.exists(url):
            # 本地图标：复制到 icon 目录（浏览器无法直接加载 D:\ 这类本地路径）
            import shutil
            ext = os.path.splitext(url)[1].lstrip('.') or 'png'
            icon_path = f'static/api/icon/{name}.{ext}'
            shutil.copyfile(url, icon_path)
            return icon_path
        else:
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


@app.route('/api/links/order', methods=['POST'])
def update_order():
    try:
        new_order = request.json.get('nod', [])
        data = load_data()

        # 重新排序数据
        ordered_data = []
        for item_id in new_order:
            item = next((x for x in data if str(x['id']) == str(item_id)), None)
            if item:
                ordered_data.append(item)

        save_data(ordered_data)
        return jsonify(ordered_data)
    except Exception as e:
        return jsonify({'error': '顺序更新失败'}), 500


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
    try:
        uploaded = webdav_sync.force_upload()
        return jsonify({'success': True, 'result': uploaded})
    except Exception as e:
        return _sync_error(e)


@app.route('/api/sync/download', methods=['POST'])
def sync_download():
    try:
        result = webdav_sync.force_download()
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
