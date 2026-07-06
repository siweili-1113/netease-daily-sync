# netease-daily-sync

网易云每日推荐自动归档工具。每天自动拉取网易云日推，去重后归档到 GitHub 仓库，方便在 LX Music 等播放器中查阅和播放。

## 工作流

```
网易云推荐算法 → GitHub Actions 自动拉取 → 归档到仓库 → 你在 LX Music 听歌
                                                    ↑
                                        （可选）标记喜欢 → 反向同步到网易云红心 → 优化算法
```

## 快速开始

### 1. 安装依赖

```bash
pip install cryptography requests
```

### 2. 登录网易云

```bash
# 发送验证码
python sync.py login 13800138000

# 用验证码登录
python sync.py login 13800138000 1234
```

登录成功后会输出 Cookie 字符串，复制它。

### 3. 配置 GitHub

1. Fork 本仓库
2. 进入仓库 Settings → Secrets and variables → Actions
3. 添加 Secret：`NCM_COOKIE`，值为上一步复制的 Cookie
4. （可选）在网易云创建一个空歌单，将歌单 ID 填入 `config.json` 的 `playlist_id`

### 4. 开始使用

GitHub Actions 会在每天早上 06:30（北京时间）自动运行，你也可以手动触发。

运行后仓库会更新：
- `today.md` — 今日推荐歌曲列表
- `archive/YYYY-MM.md` — 按月归档
- `data/history.json` — 去重历史

## 训练推荐算法（可选）

在 `today.md` 中把喜欢的歌打勾：

```diff
- | 1 | 海底 | 一支榴莲 | 海底 | 3:42 | [ ] |
+ | 1 | 海底 | 一支榴莲 | 海底 | 3:42 | [x] |
```

Commit push 后，每晚 21:00 的 Actions 会自动把打勾的歌在网易云上点红心，训练推荐算法。

## 命令参考

```bash
python sync.py sync              # 拉取日推并归档
python sync.py sync --dry-run    # 预览模式，不修改任何文件
python sync.py like              # 反向同步喜欢到网易云
python sync.py login <手机号>     # 发送验证码
python sync.py login <手机号> <验证码>  # 登录
python sync.py check             # 检查登录状态
```

## Cookie 过期

网易云 Cookie 通常有效 1-3 个月。过期后 Actions 会失败并发送邮件通知，届时重新执行 `python sync.py login` 更新 Secret 即可。

## 依赖

- `cryptography` — weapi 加密
- `requests` — HTTP 请求

仅两个依赖，纯 Python 实现，不需要 Node.js 或 Docker。
