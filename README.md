# netease-daily-sync

网易云每日推荐自动归档工具。每天自动拉取网易云日推，去重后归档到 GitHub 仓库，同时生成 LX Music 可导入的歌单文件。

## 功能

- 用 Python 直接调用网易云 weapi，无需 Node.js
- 每天自动拉取每日推荐 30 首歌
- 去重后归档到 `today.md` 和按月归档文件
- 生成 `today.lxmc` 歌单文件，可直接导入 [LX Music](https://github.com/lyswhut/lx-music-desktop)
- 可选：在 `today.md` 里标记 `[x]` 喜欢的歌，自动反向同步到网易云红心训练算法
- GitHub Actions 每天 06:30 自动运行

## LX Music 导入

每天同步后，仓库根目录会生成 `today.lxmc` 文件：

1. 下载 `today.lxmc`
2. 打开 LX Music Desktop → 设置 → 备份与恢复 → 导入
3. 选择下载的 `.lxmc` 文件即可

> **注意**：LX Music 使用 "wy" 音源播放网易云歌曲，实际能否播放取决于音源可用性。

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

### 4. 开始使用

GitHub Actions 每天早上 06:30（北京时间）自动运行，你也可以手动触发。

运行后仓库会更新：
- `today.md` — 今日推荐歌曲列表
- `today.lxmc` — LX Music 歌单文件
- `archive/YYYY-MM.md` — 按月归档
- `data/history.json` — 去重历史

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

网易云 Cookie 通常有效 1-3 个月。过期后 Actions 会失败，届时重新执行 `python sync.py login` 更新 Secret 即可。

## 依赖

- `cryptography` — weapi 加密
- `requests` — HTTP 请求

纯 Python 实现，不依赖 Node.js 或 Docker。
