#!/usr/bin/env python3
"""
网易云每日推荐自动归档工具
- 拉取每日推荐并去重归档
- 同步到网易云歌单（云端备份）
- 输出 Markdown 歌曲列表（供 LX Music 查阅）
- 反向同步：读取用户标记的「喜欢」并在网易云点红心
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
#  网易云 weapi 加密（来自 netease-daily-v3）
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
    cipher = Cipher(
        algorithms.AES(key.encode()),
        modes.CBC(IV.encode()),
        backend=default_backend()
    )
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

    # ── 歌单操作 ──

    def create_playlist(self, name):
        result = self._post('/playlist/create', {'name': name, 'privacy': 0})
        if result.get('code') == 200:
            return result.get('id') or result.get('playlist', {}).get('id')
        return None

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
        if code == 200:
            return True
        if code == 502:
            print(f'[歌单] 部分歌曲已存在，跳过')
            return True
        print(f'[歌单] 添加失败: {result}')
        return False

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


def load_history():
    path = ROOT / 'data' / 'history.json'
    if path.exists():
        with open(path, 'r') as f:
            return json.load(f)
    return {'song_ids': [], 'liked_ids': []}


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


# ═══════════════════════════════════════════════════════
#  输出生成
# ═══════════════════════════════════════════════════════

def generate_today_md(songs, date_str, total_archived):
    lines = [
        f'# 每日推荐 {date_str}',
        '',
        f'> 今日新增 {len(songs)} 首（去重后），累计归档 {total_archived} 首',
        '',
        '| # | 歌名 | 歌手 | 专辑 | 时长 | 喜欢 |',
        '|---|------|------|------|------|------|',
    ]
    for i, s in enumerate(songs, 1):
        name_link = f'[{s["name"]}](https://music.163.com/song?id={s["id"]})'
        lines.append(
            f'| {i} | {name_link} | {s["artist"]} | {s["album"]} | {s["duration"]} | [ ] |'
        )
    lines.append('')
    lines.append(f'---')
    lines.append(f'自动生成于 {datetime.now().strftime("%Y-%m-%d %H:%M")} · [netease-daily-sync](https://github.com)')
    return '\n'.join(lines)


def append_to_archive(songs, date_str):
    month_str = date_str[:7]
    archive_dir = ROOT / 'archive'
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f'{month_str}.md'

    lines = []
    if not path.exists():
        lines.append(f'# 每日推荐归档 {month_str}')
        lines.append('')

    lines.append(f'## {date_str}')
    lines.append('')
    for s in songs:
        lines.append(f'- **{s["name"]}** — {s["artist"]}（{s["album"]}）')
    lines.append('')

    with open(path, 'a', encoding='utf-8') as f:
        f.write('\n'.join(lines))


# ═══════════════════════════════════════════════════════
#  LX Music 导出
# ═══════════════════════════════════════════════════════

def generate_lxmc(songs, date_str):
    """生成 LX Music .lxmc 歌单文件（gzip 压缩的 JSON）"""
    playlist = {
        "type": "playListPart_v2",
        "data": {
            "id": f"netease-daily-{date_str}",
            "name": f"每日推荐 {date_str}",
            "list": []
        }
    }

    for s in songs:
        track = {
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
        }
        playlist["data"]["list"].append(track)

    json_bytes = json.dumps(playlist, ensure_ascii=False, indent=2).encode('utf-8')
    path = ROOT / 'today.lxmc'
    with gzip.open(path, 'wb') as f:
        f.write(json_bytes)

    return path


# ═══════════════════════════════════════════════════════
#  反向同步：读取 today.md 中标记的喜欢
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
                    song_id = int(line[start:end])
                    liked_ids.append(song_id)
    return liked_ids


# ═══════════════════════════════════════════════════════
#  主命令
# ═══════════════════════════════════════════════════════

def cmd_sync(client, dry_run=False):
    print('[sync] 开始拉取每日推荐...')

    raw_songs = client.get_daily_recommend()
    if not raw_songs:
        print('[sync] 获取日推失败，请检查登录状态')
        sys.exit(1)
    print(f'[sync] 获取到 {len(raw_songs)} 首推荐')

    songs = [parse_song(s) for s in raw_songs]
    history = load_history()
    known_ids = set(history.get('song_ids', []))

    new_songs = [s for s in songs if s['id'] not in known_ids]
    skipped = len(songs) - len(new_songs)
    print(f'[sync] 新歌 {len(new_songs)} 首，跳过 {skipped} 首（已归档）')

    if not new_songs:
        print('[sync] 今天没有新歌，跳过')
        return

    date_str = datetime.now().strftime('%Y-%m-%d')
    total_archived = len(known_ids) + len(new_songs)

    if dry_run:
        print('[dry-run] 以下歌曲将被归档:')
        for s in new_songs:
            print(f'  - {s["name"]} — {s["artist"]}')
        return

    # 写入 today.md
    today_md = generate_today_md(new_songs, date_str, total_archived)
    (ROOT / 'today.md').write_text(today_md, encoding='utf-8')
    print(f'[sync] today.md 已更新')

    # 生成 LX Music 歌单
    lxmc_path = generate_lxmc(new_songs, date_str)
    print(f'[sync] {lxmc_path.name} 已生成')

    # 追加到月度归档
    append_to_archive(new_songs, date_str)
    print(f'[sync] 归档到 archive/{date_str[:7]}.md')

    # 同步到网易云歌单
    config = load_config()
    playlist_id = config.get('playlist_id')
    if playlist_id:
        new_ids = [s['id'] for s in new_songs]
        batch_size = 50
        for i in range(0, len(new_ids), batch_size):
            batch = new_ids[i:i + batch_size]
            client.add_tracks_to_playlist(playlist_id, batch)
            if i + batch_size < len(new_ids):
                time.sleep(1)
        print(f'[sync] 已添加 {len(new_ids)} 首到歌单 {playlist_id}')

    # 更新历史记录
    history['song_ids'] = list(known_ids | {s['id'] for s in new_songs})
    save_history(history)
    print(f'[sync] 历史记录已更新，共 {len(history["song_ids"])} 首')


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
            print(f'验证码已发送到 {phone}，请使用以下命令登录:')
            print(f'  python sync.py login {phone} <验证码>')
        return

    if client.login(phone, captcha):
        cookie_str = client.export_cookies()
        print(f'\n请将以下 Cookie 设置为 GitHub Secret NCM_COOKIE:')
        print(f'{cookie_str}')

        cookies_path = ROOT / 'data' / 'cookies.json'
        cookies_path.parent.mkdir(parents=True, exist_ok=True)
        cookie_dict = {}
        for c in client.session.cookies:
            cookie_dict[c.name] = c.value
        with open(cookies_path, 'w') as f:
            json.dump(cookie_dict, f, ensure_ascii=False, indent=2)
        print(f'\nCookie 也已保存到 {cookies_path}（本地使用）')


def init_client():
    client = NeteaseClient()

    cookie_env = os.environ.get('NCM_COOKIE', '')
    if cookie_env:
        client.load_cookies(cookie_env)
        if client.check_login():
            print('[auth] Cookie 有效（环境变量）')
            return client
        print('[auth] Cookie 已过期')
        sys.exit(1)

    cookie_file = ROOT / 'data' / 'cookies.json'
    if cookie_file.exists():
        client.load_cookies_from_file(cookie_file)
        if client.check_login():
            print('[auth] Cookie 有效（本地文件）')
            return client
        print('[auth] 本地 Cookie 已过期，请重新登录')
        sys.exit(1)

    print('[auth] 未找到 Cookie，请先登录:')
    print('  python sync.py login <手机号>')
    sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print('用法:')
        print('  python sync.py sync [--dry-run]    拉取日推并归档')
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
        print('[check] 登录状态正常')

    elif cmd == 'sync':
        client = init_client()
        dry_run = '--dry-run' in sys.argv
        cmd_sync(client, dry_run=dry_run)

    elif cmd == 'like':
        client = init_client()
        cmd_like(client)

    else:
        print(f'未知命令: {cmd}')
        sys.exit(1)


if __name__ == '__main__':
    main()
