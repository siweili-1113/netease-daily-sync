#!/usr/bin/env python3
"""
网易云每日推荐自动归档工具
- 拉取每日推荐、私人雷达、欧美私人订制等多个来源
- 去重后自动写入对应的网易云歌单
- LX Music 可直接播放网易云歌单，无需手动导入
- GitHub Actions 每天自动运行

来源配置见 config.json
"""
import requests
import json
import base64
import gzip
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend


# ═══════════════════════════════════════════════════════
#  网易云 weapi 加密
# ═══════════════════════════════════════════════════════

MODULUS = (
    '00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725'
    '152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312'
    'ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b42'
    '4d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7'
)
NONCE = '0CoJUm6Qyw8W8jud'
PUBKEY = '010001'
IV = '0102030405060708'


def aes_encrypt(text, key):
    pad_len = 16 - len(text) % 16
    text += chr(pad_len) * pad_len
    cipher = Cipher(algorithms.AES(key.encode()), modes.CBC(IV.encode()), backend=default_backend())
    enc = cipher.encryptor()
    return base64.b64encode(enc.update(text.encode()) + enc.finalize()).decode()


def rsa_encrypt(text, pubkey, modulus):
    text_int = int.from_bytes(text[::-1].encode(), 'big')
    result = pow(text_int, int(pubkey, 16), int(modulus, 16))
    return format(result, 'x').zfill(256)


def weapi_encrypt(params):
    sec_key = ''.join(chr(ord('a') + (b % 26)) for b in os.urandom(16))
    enc_text = aes_encrypt(json.dumps(params), NONCE)
    enc_text = aes_encrypt(enc_text, sec_key)
    enc_key = rsa_encrypt(sec_key, PUBKEY, MODULUS)
    return {'params': enc_text, 'encSecKey': enc_key}


# ═══════════════════════════════════════════════════════
#  网易云 API 客户端
# ═══════════════════════════════════════════════════════

class NeteaseClient:
    HEADERS = {
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
        'Referer': 'https://music.163.com/',
        'Origin': 'https://music.163.com',
        'Content-Type': 'application/x-www-form-urlencoded',
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def _post(self, endpoint, params=None):
        url = f'https://music.163.com/weapi{endpoint}'
        params = params or {}
        params['csrf_token'] = self.session.cookies.get('__csrf', '')
        resp = self.session.post(url, data=weapi_encrypt(params), timeout=15)
        resp.raise_for_status()
        return resp.json()

    # ── 认证 ──

    def send_captcha(self, phone):
        result = self._post('/sms/captcha/sent', {'cellphone': phone, 'ctcode': '86'})
        return result.get('code') == 200

    def login(self, phone, captcha):
        result = self._post('/login/cellphone', {
            'phone': phone, 'captcha': captcha,
            'countrycode': '86', 'rememberLogin': 'true'
        })
        if result.get('code') == 200:
            nickname = result.get('profile', {}).get('nickname', '用户')
            print(f'[登录] 成功，欢迎 {nickname}')
            return True
        print(f'[登录] 失败: {result.get("message", "未知错误")}')
        return False

    def load_cookies(self, cookie_str):
        for item in cookie_str.split(';'):
            item = item.strip()
            if '=' in item:
                k, v = item.split('=', 1)
                self.session.cookies.set(k.strip(), v.strip())

    def load_cookies_from_file(self, path):
        with open(path, 'r') as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k, v in data.items():
                self.session.cookies.set(k, v)
        return True

    def export_cookies(self):
        return '; '.join(f'{c.name}={c.value}' for c in self.session.cookies)

    def check_login(self):
        result = self._post('/w/nuser/account/get')
        return result.get('code') == 200 and result.get('account') is not None

    # ── 每日推荐 ──

    def get_daily_recommend(self):
        result = self._post('/v3/discovery/recommend/songs', {
            'limit': 30, 'offset': 0, 'total': True
        })
        if result.get('code') == 200:
            return result.get('data', {}).get('dailySongs', [])
        return []

    # ── 歌单全量获取 ──

    def get_playlist_all_tracks(self, playlist_id):
        """获取歌单全部歌曲（用 trackIds + song/detail 绕过 20 首限制）"""
        result = self._post('/v6/playlist/detail', {'id': playlist_id, 'n': 1, 's': 0})
        if result.get('code') != 200:
            return []
        track_ids = result.get('playlist', {}).get('trackIds', [])
        if not track_ids:
            return []
        all_ids = [t['id'] for t in track_ids]
        c = json.dumps([{"id": str(x)} for x in all_ids])
        song_result = self._post('/v3/song/detail', {'c': c})
        return song_result.get('songs', []) if song_result.get('code') == 200 else []

    # ── 歌单操作 ──

    def create_playlist(self, name):
        result = self._post('/playlist/create', {'name': name, 'privacy': 0})
        if result.get('code') == 200:
            return result.get('id') or result.get('playlist', {}).get('id')
        return None

    def get_user_playlists(self):
        """获取用户自己的歌单列表"""
        result = self._post('/user/playlist', {'uid': self._get_uid(), 'limit': 100, 'offset': 0})
        return result.get('playlist', []) if result.get('code') == 200 else []

    def _get_uid(self):
        result = self._post('/w/nuser/account/get')
        return result.get('account', {}).get('id') if result.get('code') == 200 else None

    def add_tracks_to_playlist(self, playlist_id, track_ids):
        if not track_ids:
            return True
        result = self._post('/playlist/manipulate/tracks', {
            'op': 'add',
            'pid': str(playlist_id),
            'trackIds': json.dumps(track_ids),
            'imme': 'true'
        })
        code = result.get('code')
        if code in (200, 502):
            return True
        print(f'[歌单] 添加失败: {result}')
        return False

    def delete_playlist(self, playlist_id):
        result = self._post('/playlist/delete', {
            'ids': f'[{playlist_id}]',
            'pid': str(playlist_id),
        })
        return result.get('code') == 200

    # ── 红心 ──

    def like_song(self, song_id, like=True):
        result = self._post('/song/like', {
            'trackId': str(song_id),
            'like': str(like).lower(),
            'alg': 'itembased',
            'time': '3'
        })
        return result.get('code') == 200


# ═══════════════════════════════════════════════════════
#  数据管理
# ═══════════════════════════════════════════════════════

ROOT = Path(__file__).parent


def parse_song(song):
    artists = song.get('ar', song.get('artists', []))
    artist = ' / '.join(a.get('name', '') for a in artists[:3] if a.get('name'))
    album = (song.get('al') or song.get('album') or {}).get('name', '')
    dur_ms = song.get('dt', song.get('duration', 0))
    dur_str = f'{dur_ms // 60000}:{(dur_ms // 1000) % 60:02d}' if dur_ms else ''
    return {
        'id': song.get('id'),
        'name': song.get('name', ''),
        'artist': artist,
        'album': album,
        'duration': dur_str,
        'reason': song.get('reason', ''),
    }


def load_state():
    """加载同步状态（歌单 ID 映射等）"""
    path = ROOT / 'data' / 'state.json'
    if path.exists():
        with open(path, 'r') as f:
            return json.load(f)
    return {}


def save_state(state):
    path = ROOT / 'data' / 'state.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_history():
    path = ROOT / 'data' / 'history.json'
    if path.exists():
        with open(path, 'r') as f:
            return json.load(f)
    return {}


def save_history(history):
    path = ROOT / 'data' / 'history.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def load_config():
    path = ROOT / 'config.json'
    if path.exists():
        with open(path, 'r') as f:
            return json.load(f)
    return {}


# ═══════════════════════════════════════════════════════
#  歌单来源定义
# ═══════════════════════════════════════════════════════

SOURCES = [
    {'key': 'daily',        'name': 'ClaudeCode_自动加入_每日推荐',    'type': 'daily',  'pid': None},
    {'key': 'eu_radio',     'name': 'ClaudeCode_自动加入_欧美私人订制', 'type': 'playlist', 'pid': '2829816518'},
    {'key': 'personal',     'name': 'ClaudeCode_自动加入_私人雷达',     'type': 'playlist', 'pid': '3136952023'},
    {'key': 'time_capsule', 'name': 'ClaudeCode_自动加入_时光雷达',     'type': 'playlist', 'pid': '5320167908'},
    {'key': 'treasure',     'name': 'ClaudeCode_自动加入_宝藏雷达',     'type': 'playlist', 'pid': '5362359247'},
]


def fetch_songs(client, source):
    """根据来源类型获取歌曲列表"""
    if source['type'] == 'daily':
        raw = client.get_daily_recommend()
        return [parse_song(s) for s in raw], len(raw)

    elif source['type'] == 'playlist':
        tracks = client.get_playlist_all_tracks(source['pid'])
        count = len(tracks)
        songs = [parse_song(t) for t in tracks]
        return songs, count

    return [], 0


def get_or_create_playlist(client, name):
    """
    查找用户是否已有同名歌单，没有则创建。
    返回 playlist_id。
    """
    playlists = client.get_user_playlists()
    for pl in playlists:
        if pl.get('name') == name:
            print(f'  找到已有歌单: {name} (id={pl["id"]})')
            return str(pl['id'])

    pid = client.create_playlist(name)
    print(f'  创建新歌单: {name} (id={pid})')
    return str(pid) if pid else None


def get_playlist_existing_ids(client, playlist_id):
    """获取歌单中已有的歌曲 ID 集合（用于去重）"""
    tracks = client.get_playlist_all_tracks(playlist_id)
    return {t.get('id') for t in tracks if t.get('id')}


# ═══════════════════════════════════════════════════════
#  输出生成
# ═══════════════════════════════════════════════════════

def generate_today_md(results, date_str):
    """生成每日汇总 Markdown"""
    lines = [
        f'# 每日归档 {date_str}',
        '',
    ]
    total_new = 0

    for r in results:
        if r['new_count'] > 0:
            total_new += r['new_count']
            lines.append(f'## {r["name"]} — {r["new_count"]} 首')
            lines.append('')
            lines.append('| # | 歌名 | 歌手 | 时长 |')
            lines.append('|---|------|------|------|')
            for i, s in enumerate(r['songs'], 1):
                name_link = f'[{s["name"]}](https://music.163.com/song?id={s["id"]})'
                lines.append(f'| {i} | {name_link} | {s["artist"]} | {s["duration"]} |')
            lines.append('')

    if total_new == 0:
        lines.append('> 今日无新歌')
    else:
        lines.append(f'> 今日共新增 {total_new} 首')

    lines.append('')
    lines.append(f'---')
    lines.append(f'自动生成于 {datetime.now().strftime("%Y-%m-%d %H:%M")} · netease-daily-sync')
    return '\n'.join(lines)


def generate_lxmc(songs, date_str):
    """生成 LX Music .lxmc 歌单文件"""
    playlist = {
        "type": "playListPart_v2",
        "data": {
            "id": f"netease-daily-{date_str}",
            "name": f"每日归档 {date_str}",
            "list": []
        }
    }
    for s in songs:
        playlist["data"]["list"].append({
            "id": f"wy_{s['id']}",
            "name": s["name"],
            "singer": s["artist"],
            "source": "wy",
            "interval": s["duration"] if s["duration"] else "00:00",
            "meta": {
                "songId": s["id"],
                "albumName": s["album"],
                "qualitys": [
                    {"type": "128k", "size": None},
                    {"type": "320k", "size": None},
                ]
            }
        })
    json_bytes = json.dumps(playlist, ensure_ascii=False, indent=2).encode('utf-8')
    path = ROOT / 'today.lxmc'
    with gzip.open(path, 'wb') as f:
        f.write(json_bytes)
    return path


# ═══════════════════════════════════════════════════════
#  反向同步喜欢
# ═══════════════════════════════════════════════════════

def parse_liked_from_md(md_path):
    if not Path(md_path).exists():
        return []
    liked_ids = []
    with open(md_path, 'r', encoding='utf-8') as f:
        for line in f:
            if '| [x] |' in line or '| [X] |' in line:
                if 'song?id=' in line:
                    start = line.index('song?id=') + 8
                    end = line.index(')', start)
                    liked_ids.append(int(line[start:end]))
    return liked_ids


# ═══════════════════════════════════════════════════════
#  主命令
# ═══════════════════════════════════════════════════════

def cmd_sync(client, dry_run=False):
    print(f'[sync] {datetime.now().strftime("%Y-%m-%d %H:%M")} 开始同步')
    print()

    date_str = datetime.now().strftime('%Y-%m-%d')
    state = load_state()
    results = []
    all_new_songs = []

    for src in SOURCES:
        print(f'📡 {src["name"]}')
        time.sleep(0.5)

        # 获取歌曲
        songs, raw_count = fetch_songs(client, src)
        print(f'   获取到 {raw_count} 首')

        if not songs:
            results.append({'name': src['name'], 'songs': [], 'new_count': 0, 'added': 0})
            continue

        if dry_run:
            results.append({'name': src['name'], 'songs': songs, 'new_count': len(songs), 'added': 0})
            continue

        # 获取或创建目标歌单
        playlist_id = state.get(src['key'])
        if not playlist_id:
            playlist_id = get_or_create_playlist(client, src['name'])
            if not playlist_id:
                print(f'   ❌ 创建歌单失败')
                results.append({'name': src['name'], 'songs': [], 'new_count': 0, 'added': 0})
                continue
            state[src['key']] = playlist_id
            save_state(state)

        # 去重：对比歌单已有歌曲
        existing_ids = get_playlist_existing_ids(client, playlist_id)
        print(f'   歌单已有 {len(existing_ids)} 首')

        new_songs = [s for s in songs if s['id'] not in existing_ids]
        print(f'   新歌 {len(new_songs)} 首，跳过 {len(songs) - len(new_songs)} 首')

        if new_songs:
            new_ids = [s['id'] for s in new_songs]
            for i in range(0, len(new_ids), 50):
                batch = new_ids[i:i + 50]
                client.add_tracks_to_playlist(playlist_id, batch)
                time.sleep(1)
            print(f'   ✅ 已添加 {len(new_ids)} 首')
        else:
            print(f'   ⏭️ 无新歌，跳过')

        results.append({
            'name': src['name'],
            'songs': new_songs,
            'new_count': len(new_songs),
            'added': len(new_songs),
        })
        all_new_songs.extend(new_songs)

    # 更新历史记录
    history = load_history()
    today_key = date_str
    if today_key not in history:
        history[today_key] = {'total_new': 0}
    history[today_key]['total_new'] = len(all_new_songs)
    history.setdefault('total_archived', 0)
    history['total_archived'] += len(all_new_songs)
    history['last_sync'] = date_str
    save_history(history)

    # 生成 Markdown
    today_md = generate_today_md(results, date_str)
    (ROOT / 'today.md').write_text(today_md, encoding='utf-8')

    # 生成 LX Music 歌单
    if all_new_songs:
        generate_lxmc(all_new_songs, date_str)

    # 汇总
    print()
    print(f'{"="*50}')
    total_new = sum(r['new_count'] for r in results)
    print(f'📊 今日共新增 {total_new} 首')
    for r in results:
        if r['new_count'] > 0:
            print(f'   {r["name"]}: +{r["new_count"]} 首')
    print(f'{"="*50}')


def cmd_like(client):
    print('[like] 开始反向同步喜欢...')
    today_path = ROOT / 'today.md'
    liked_ids = parse_liked_from_md(today_path)

    if not liked_ids:
        print('[like] 没有标记喜欢的歌曲')
        return

    history = load_history()
    already_liked = set(history.get('liked_ids', []))
    new_likes = [sid for sid in liked_ids if sid not in already_liked]

    if not new_likes:
        print('[like] 所有标记的歌曲已同步过')
        return

    print(f'[like] 待同步 {len(new_likes)} 首')
    success = 0
    for sid in new_likes:
        if client.like_song(sid):
            success += 1
            print(f'  [ok] {sid}')
        else:
            print(f'  [fail] {sid}')
        time.sleep(2)

    history.setdefault('liked_ids', []).extend(new_likes)
    save_history(history)
    print(f'[like] 完成，成功 {success}/{len(new_likes)}')


def cmd_login(phone, captcha=None):
    client = NeteaseClient()
    if captcha is None:
        if client.send_captcha(phone):
            print(f'验证码已发送到 {phone}')
            print(f'收到后运行: python sync.py login {phone} <验证码>')
        return

    if client.login(phone, captcha):
        cookie_str = client.export_cookies()

        # 保存到本地
        cookies_path = ROOT / 'data' / 'cookies.json'
        cookies_path.parent.mkdir(parents=True, exist_ok=True)
        cookie_dict = {}
        for c in client.session.cookies:
            cookie_dict[c.name] = c.value
        with open(cookies_path, 'w') as f:
            json.dump(cookie_dict, f, ensure_ascii=False, indent=2)

        print()
        print('═' * 60)
        print('  ✅ 登录成功！Cookie 已保存到本地')
        print()
        print('  📋 接下来两步：')
        print()
        print('  1️⃣  复制下面这行 Cookie：')
        print('  ─' * 60)
        print(f'  {cookie_str}')
        print('  ─' * 60)
        print()
        print('  2️⃣  更新 GitHub Secrets：')
        print('      打开 https://github.com/siweili-1113/netease-daily-sync/settings/secrets/actions')
        print('      找到 NCM_COOKIE → 编辑 → 粘贴上面的 Cookie → 保存')
        print()
        print('  ⚡ 完成后，到 Actions 页面手动点一下 Run workflow')
        print('     https://github.com/siweili-1113/netease-daily-sync/actions')
        print('     今天的日推就能抢救回来 ✅')
        print('═' * 60)


def init_client(graceful=False):
    """
    初始化客户端。
    graceful=True 时不退出，返回 None 让调用方自行处理。
    """
    client = NeteaseClient()

    cookie_env = os.environ.get('NCM_COOKIE', '')
    if cookie_env:
        client.load_cookies(cookie_env)
        if client.check_login():
            print('[auth] Cookie 有效（环境变量）')
            return client
        print('[auth] Cookie 已过期（环境变量）')
        if not graceful:
            sys.exit(1)
        return None

    cookie_file = ROOT / 'data' / 'cookies.json'
    if cookie_file.exists():
        client.load_cookies_from_file(cookie_file)
        if client.check_login():
            print('[auth] Cookie 有效（本地文件）')
            return client
        print('[auth] 本地 Cookie 已过期')
        if not graceful:
            print('请重新登录: python sync.py login <手机号>')
            sys.exit(1)
        return None

    print('[auth] 未找到 Cookie')
    if not graceful:
        print('请先登录: python sync.py login <手机号>')
        sys.exit(1)
    return None


def main():
    if len(sys.argv) < 2:
        print('用法:')
        print('  python sync.py sync [--dry-run]    拉取全部来源并同步到网易云歌单')
        print('  python sync.py like                反向同步喜欢到网易云')
        print('  python sync.py login <手机号>       发送验证码')
        print('  python sync.py login <手机号> <验证码>  登录')
        print('  python sync.py check               检查登录状态')
        return

    cmd = sys.argv[1]

    if cmd == 'login':
        if len(sys.argv) < 3:
            print('请提供手机号: python sync.py login <手机号>')
            return
        phone = sys.argv[2]
        captcha = sys.argv[3] if len(sys.argv) > 3 else None
        cmd_login(phone, captcha)

    elif cmd == 'check':
        client = init_client()
        if client:
            print('[check] 登录状态正常')

    elif cmd == 'sync':
        client = init_client(graceful=True)
        if client is None:
            print('[sync] Cookie 已过期，请更新后重试')
            print('  python sync.py login <手机号>')
            sys.exit(1)
        dry_run = '--dry-run' in sys.argv
        cmd_sync(client, dry_run=dry_run)

    elif cmd == 'like':
        client = init_client()
        if client:
            cmd_like(client)

    else:
        print(f'未知命令: {cmd}')
        sys.exit(1)


if __name__ == '__main__':
    main()
