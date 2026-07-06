# netease-daily-sync

网易云每日推荐自动归档工具。每天自动拉取 5 个推荐来源，去重后写入对应的网易云歌单，LX Music 打开即听。

## 工作原理

```
GitHub Actions (每天 06:30 云端运行)
  ├─ 每日推荐 → ClaudeCode_自动加入_每日推荐
  ├─ 欧美私人订制 → ClaudeCode_自动加入_欧美私人订制
  ├─ 私人雷达 → ClaudeCode_自动加入_私人雷达
  ├─ 时光雷达 → ClaudeCode_自动加入_时光雷达
  └─ 宝藏雷达 → ClaudeCode_自动加入_宝藏雷达

你的 LX Music → 网易云歌单 → 直接播放
不需要电脑开机、不需要 VPN、不需要手动操作
```

## 快速开始

### 1. Fork 本仓库

### 2. 安装依赖

```bash
pip install cryptography requests
```

### 3. 登录网易云

```bash
python sync.py login 你的手机号
```

输入验证码后，脚本会输出 Cookie 字符串。

### 4. 配置 GitHub Secrets

1. 打开仓库 Settings → Secrets and variables → Actions
2. 点击 **New repository secret**
3. Name：`NCM_COOKIE`
4. Value：粘贴上一步输出的 Cookie 字符串
5. 点击 **Add secret**

### 5. 手动运行一次

打开仓库 Actions → Daily Sync → **Run workflow**

### 6. 验证

打开网易云 App，搜索 `ClaudeCode_自动加入`，应该能看到 5 个歌单。

---

## Cookie 更新教程

Cookie 有效期约 **14 天**。过期后 GitHub Actions 会失败，你会收到邮件通知。

### 更新步骤（< 2 分钟）

**第 1 步**：打开终端，进入项目目录，重新登录

```bash
cd netease-daily-sync
python sync.py login 你的手机号
# 输入收到的验证码
```

登录成功后脚本会自动打印新 Cookie 和操作指引。

**第 2 步**：复制打印出的 Cookie 字符串

**第 3 步**：更新 GitHub Secret

打开 https://github.com/<你的用户名>/netease-daily-sync/settings/secrets/actions

找到 `NCM_COOKIE` → 点击编辑（铅笔图标）→ 粘贴新 Cookie → 保存

**第 4 步**：抢救今天的日推

打开 https://github.com/<你的用户名>/netease-daily-sync/actions

点击 **Daily Sync** → **Run workflow** → **Run workflow**

当天日推就会自动补上。

---

## 命令参考

```bash
python sync.py sync              # 拉取全部来源，同步到网易云歌单
python sync.py sync --dry-run    # 预览模式，不实际写入
python sync.py like              # 反向同步喜欢到网易云红心
python sync.py login <手机号>     # 发送验证码
python sync.py login <手机号> <验证码>  # 登录获取 Cookie
python sync.py check             # 检查登录状态
```

## 订阅来源

| 网易云歌单 | 来源 | 更新频率 | 数量 |
|-----------|------|:--:|:--:|
| ClaudeCode_自动加入_每日推荐 | 每日推荐 | 每天 | ~30 |
| ClaudeCode_自动加入_欧美私人订制 | 欧美私人订制 | 每天 | ~35 |
| ClaudeCode_自动加入_私人雷达 | 私人雷达 | 每天 | ~35 |
| ClaudeCode_自动加入_时光雷达 | 时光雷达 | 每天 | ~30 |
| ClaudeCode_自动加入_宝藏雷达 | 宝藏雷达 | 每天 | ~30 |

> 自动去重：同一首歌不会重复加入歌单。

## 依赖

- `cryptography` — weapi 加密
- `requests` — HTTP 请求

纯 Python，不依赖 Node.js 或 Docker。
