# 🔥 douyin-fire-keeper

用 Playwright 模拟浏览器登录抖音网页版，每天给指定好友发送一条消息，保持聊天火花不断。

- **无需服务器**：用 GitHub Actions 定时运行，电脑不用一直开机
- **支持多好友**：`friends` 填几个就依次发几个，每个好友独立记录结果
- **支持原生表情**：除文字外，可随机发送抖音表情面板里的原生表情
- **结果可通知**：支持钉钉机器人、飞书/企业微信/Slack 等通用 Webhook
- **先验证再发送**：内置 Dry Run，只检查登录态和好友定位，不真正发消息
- **失败可诊断**：自动保存日志、截图和 `result.json`，随 Actions Artifact 一起下载
- **选择器可校准**：所有页面选择器集中在一个文件，并提供 `--diagnose` 一键体检
- **凭证只走 Secrets**：Cookie 不写进仓库、不进日志

> 本项目为独立实现，MIT 协议开源：`https://github.com/<你的用户名>/douyin-fire-keeper`

---

## 工作原理

```text
Cookie（登录态） + 配置（好友/消息）
        ↓
Playwright 启动 Chromium → 打开 https://www.douyin.com/chat
        ↓
搜索好友 → 打开聊天 → 写入文字/选择原生表情 → 发送 → 确认消息出现在聊天记录
        ↓
artifacts/run.log + result.json + 失败截图
```

它不做接口逆向，也不调用私有 API，完全是「模拟一个真人打开网页发消息」。

---

## 目录结构

```text
douyin-fire-keeper/
├─ run.py                     # 命令行入口
├─ keeper/
│  ├─ config.py               # 配置读取与校验
│  ├─ cookies.py              # Cookie-Editor JSON → Playwright 格式
│  ├─ douyin.py               # 登录检查、好友定位、文字与表情发送（选择器都在这）
│  ├─ notifier.py             # 钉钉 / 通用 Webhook 通知
│  └─ runner.py               # 任务编排、截图、结果输出
├─ config.example.json        # 配置模板
├─ .github/workflows/send.yml # Actions 定时任务
├─ requirements.txt
└─ LICENSE
```

---

## 方式一：GitHub Actions 部署（推荐）

### 1. 准备工作

1. 一个 GitHub 账号（免费即可）
2. 电脑上的 Chrome 或 Edge
3. 手机抖音 App，用于扫码登录

### 2. 登录抖音网页版

1. 打开 **https://www.douyin.com/**
2. 点右上角「登录」，用手机抖音 App 扫码
3. 登录后打开 **https://www.douyin.com/chat**，确认能看到私信列表和搜索框

### 3. 导出 Cookie

1. 安装扩展 **Cookie-Editor**：
   **https://chromewebstore.google.com/detail/hlkenndednhfkekhgcdicdfddnkalmdm**
2. 回到抖音私信页面，点开 Cookie-Editor
3. 点 **Export** → 选择 **JSON** → **Copy**
4. 得到的是一整段 `[ { ... }, { ... } ]`

> ⚠️ Cookie 等于账号登录凭证。不要发给任何人，不要贴到 Issue、聊天记录或截图里。

程序会自动检查 Cookie 是否包含 `sessionid`，没有会直接报错，避免白跑一次。

### 4. 生成发送配置

复制 [`config.example.json`](config.example.json)，把 `friends` 和 `messages` 改成你自己的：

```json
{
  "friends": ["好友昵称"],
  "messages": ["续火花"],
  "send_interval_seconds": { "min": 3, "max": 8 },
  "target_open_retries": 1,
  "target_open_timeout_seconds": 15
}
```

要点：

- `friends` 里的昵称必须和**抖音私信列表里显示的完全一致**，包括表情、空格、符号
- `friends` 可以填多个，程序会依次打开每个好友的聊天并各自记录结果
- `messages` 可以写多条，每次随机选一条发送
- 第一次建议只配 **1 个好友 + 1 条消息**

`messages` 支持两种写法：

```json
{
  "friends": ["好友A", "好友B"],
  "messages": [
    "续火花",
    { "type": "text", "value": "今天也要开心" },
    { "type": "sticker", "value": "比心" }
  ],
  "stickers": {
    "比心": { "label": "比心", "category": "常用", "fallback_index": 3 }
  },
  "send_interval_seconds": { "min": 3, "max": 8 },
  "target_open_retries": 1,
  "target_open_timeout_seconds": 15
}
```

- 普通字符串等价于 `{ "type": "text", "value": "..." }`
- `sticker` 的 `value` 是自定义名字，必须在 `stickers` 里有对应条目
- `label` 是表情的可见名称/title，`category` 是面板顶部的分类名，`fallback_index` 是按名称匹配失败时点击第几个表情（从 0 开始）
- **原生表情依赖页面结构，属于实验功能**：第一次使用建议本地 `--show` 观察一次，确认面板能被点开、表情能被选中

### 5. 创建仓库并上传代码

1. 在 GitHub 新建一个 **Public** 仓库，名字建议 `douyin-fire-keeper`
2. 把本项目文件全部上传（不要上传 `cookies.json`、`config.json`）
3. 打开仓库的 **Actions** 标签页
4. 如果出现「Workflows aren't being run on this repository」，点 **I understand my workflows, go ahead and enable them**

### 6. 添加两个 Secrets

进入仓库：

```text
Settings → Secrets and variables → Actions → New repository secret
```

| Name | Value |
| --- | --- |
| `DOUYIN_COOKIE` | 第 3 步复制的完整 Cookie JSON |
| `DOUYIN_CONFIG` | 第 4 步改好的完整配置 JSON |

保存后页面不会再次显示内容，这是正常的。**不要**把 Cookie 写进 `cookies.json` 再提交。

通知是可选的，想收到运行结果再加：

| Name | 说明 |
| --- | --- |
| `DINGTALK_WEBHOOK` | 钉钉群机器人 Webhook 地址 |
| `DINGTALK_SECRET` | 钉钉机器人「加签」密钥（安全设置选加签时填写） |
| `WEBHOOK_URL` | 通用 Webhook 地址（飞书、企业微信、Slack、Discord 均可） |
| `WEBHOOK_TEMPLATE` | 可选，自定义 JSON 模板，支持 `{status}` `{success_count}` `{failed_count}` `{timestamp}` 等占位符 |
| `WEBHOOK_HEADERS` | 可选，自定义请求头 JSON，如 `{"Authorization":"Bearer xxx"}` |

各平台默认消息格式适配：

- 飞书：`msg_type=text`
- 企业微信 / 钉钉：`msgtype=text`
- 其他（Slack、Discord、自建服务）：`{"text": "..."}`

飞书自定义机器人默认走 `{"text": ...}` 即可，不需要改模板。

### 7. 先跑 Dry Run

```text
Actions → Send Douyin Fire Messages → Run workflow
```

`dry_run` 保持 **true**，点绿色 **Run workflow**。

运行结束后：

- 绿色 ✓：Cookie 有效、好友能定位，属于成功
- 红色 ✗：点进这次运行，展开 **send → Run** 查看真正的报错（不要只看最后一行 exit code 1）

### 8. 正式发送

再运行一次，把 `dry_run` 改成 **false**。它会真的发一条消息给配置里的好友。

确认好友收到消息后，就可以开始依赖定时任务。

### 9. 定时任务

工作流已经内置每天 **08:30（北京时间）** 运行：

```yaml
on:
  schedule:
    - cron: "30 8 * * *"
      timezone: "Asia/Shanghai"
```

- 想改时间，编辑 `.github/workflows/send.yml` 里的 `cron`（时分）即可
- GitHub 的定时任务可能延迟几分钟到几十分钟，属于正常现象
- 定时任务只会从默认分支（`main`）触发
- 如果 `timezone` 不生效（旧环境），改成 UTC 写法：`cron: "30 0 * * *"`（= 北京 08:30）

> 定时触发会按「正式发送」执行；`dry_run` 只影响手动触发。

---

## 方式二：本地运行

需要 Python 3.11+。

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

# 准备凭证
copy config.example.json config.json   # Windows
# 把 Cookie JSON 保存为 cookies.json

# 体检页面结构
python run.py --diagnose

# 只验证，不发送
python run.py --dry-run

# 正式发送（--show 会显示浏览器窗口，方便观察）
python run.py --show
```

也可以不落盘 Cookie，改用环境变量：

```bash
# PowerShell
$env:DOUYIN_COOKIE = Get-Content cookies.json -Raw
$env:DOUYIN_CONFIG = Get-Content config.json -Raw
python run.py --dry-run
```

---

## 查看日志与排障

### 在哪里看日志

```text
仓库 → Actions → 点进某一次运行 → send → Run
```

`artifacts/` 会随运行上传，包含：

| 文件 | 用途 |
| --- | --- |
| `run.log` | 完整运行日志 |
| `result.json` | 每个好友的成功/失败结果 |
| `screenshots/` | 失败时的页面截图 |

运行页面底部 **Artifacts** 区可下载 `douyin-run-<run_id>.zip`，保留 7 天。

### 常见错误对照

| 日志现象 | 原因 | 处理 |
| --- | --- | --- |
| `Cookie 已失效：页面要求重新登录` | 登录态过期 | 重新扫码登录，导出 Cookie，更新 Secret |
| `触发安全验证` | 抖音风控 | 本机浏览器手动完成验证后重新导出 Cookie；或换网络环境重试 |
| `找不到好友「xxx」` | 昵称不一致 / 搜不到 | 复制私信列表里的昵称原文（含表情）；确认好友在私信列表里 |
| `找不到消息输入框` | 页面改版 | 运行 `--diagnose`，更新 `keeper/douyin.py` 里的选择器 |
| `页面出现「发送失败」` | 消息被拦截 | 打开截图查看；换文案、降低频率、确认账号未被限制 |
| `没有在聊天记录里看到刚发送的消息` | 发送确认超时 | 打开截图确认是否真的发出；必要时多跑一次 Dry Run |
| `找不到私信搜索框` | 登录态无效或页面结构变化 | 先 `--diagnose`，再重新导出 Cookie |
| `找不到表情按钮` / `面板没有打开` | 表情入口改版 | `--diagnose` 看「表情按钮」是否命中，更新 `STICKER_BUTTONS` |
| `表情面板里找不到「xxx」` | 表情名称或下标不对 | 本地 `--show` 观察面板，调整 `label` / `category` / `fallback_index` |

### 页面改版后怎么校准

1. 本地运行 `python run.py --diagnose`
2. 查看输出的每一项后面命中了哪些选择器
3. 有 `[]`（空数组）的那一项，就是需要更新的
4. 打开抖音私信页面，用浏览器开发者工具找到新的 class 特征
5. 只改 `keeper/douyin.py` 顶部对应的选择器元组即可，逻辑不用动

> `--diagnose` 会保存一张 `artifacts/diagnose.png`，截图里能看到当前页面状态。

### Cookie 过期怎么更新

Cookie 一般能撑几周到几个月。出现登录失效时：

1. 电脑浏览器打开 **https://www.douyin.com/**，重新扫码登录
2. Cookie-Editor → **Export → JSON → Copy**
3. 仓库 → `Settings → Secrets and variables → Actions`
4. 点 `DOUYIN_COOKIE` 右侧的 **Update**
5. 粘贴新 Cookie 保存
6. 手动跑一次 `dry_run = true` 验证

验证通过后定时任务会自动恢复，不需要改代码。

---

## 安全与合规

- Cookie、`cookies.json`、`config.json` 都在 `.gitignore` 里，**不要强制提交**
- 不要把这个仓库设为 Private 后放 Cookie —— Secrets 才是正确位置
- 截图和日志可能包含聊天内容，下载后不要公开传播
- 自动化操作可能违反平台用户协议，并触发安全验证或账号限制，请自行评估风险，建议先用小号验证
- 同一个账号不要同时跑多份自动发送任务，容易重复发送
- 本项目仅供个人学习与自用，请勿用于群发、营销或骚扰

---

## 致谢

页面结构调研阶段参考了 [unmev/douyin-auto-fire](https://github.com/unmev/douyin-auto-fire) 的公开文档与踩坑记录，本项目为独立实现。

## License

[MIT](LICENSE)
