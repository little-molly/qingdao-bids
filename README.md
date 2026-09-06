# 青岛招标商机监控 · 云端版

每天北京时间 08:00 由 GitHub Actions 自动抓取三个招标来源（青岛政府采购网 / 青岛公共资源交易网 / 军队采购网），按 15 个监控/安防关键词过滤，去重后把日报摘要**推送到手机**。电脑关机也照常运行。

## 运行架构

```
GitHub Actions (ubuntu runner, 免费额度)
  └─ 每天 UTC 00:00（北京 08:00，实际触发可能延迟 5~30 分钟）
       ├─ python3 fetch_and_report.py
       │    ├─ 抓取三来源（35 个请求，约 1-2 分钟）
       │    ├─ 关键词过滤 + 近 48h 窗口 + state.json 去重
       │    ├─ 生成日报 YYYY-MM-DD.md
       │    └─ 推送摘要到手机（Bark / ntfy / 企业微信，配哪个用哪个）
       └─ git commit state.json + 日报回仓库（去重基线跨天持久化）
```

## 首次部署（3 步）

**1. 在 GitHub 创建一个空的私有仓库**，名字如 `qingdao-bid-monitor`（不要勾选任何初始化选项）。

**2. 推送本目录：**

```bash
cd ~/.openclaw-autoclaw/workspace/qingdao-bids/github-actions
git init -b main
git add -A
git commit -m "init: qingdao bid monitor"
git remote add origin https://github.com/<你的GitHub用户名>/qingdao-bid-monitor.git
git push -u origin main
```

> push 时若提示登录：用户名填 GitHub 用户名，密码填 **Personal Access Token**（GitHub → Settings → Developer settings → Personal access tokens → Fine-grained，勾选该仓库的 Contents 读写权限）。

**3. 配置手机推送（Settings → Secrets and variables → Actions → New repository secret），三选一：**

| 你的手机 | 装/用什么 | Secret 名称 | 值的示例 |
|---|---|---|---|
| iOS | App Store 装「Bark」，打开 App 复制示例 URL 里的 key | `BARK_URL` | `https://api.day.app/你的key` |
| iOS/安卓 | 装「ntfy」App，订阅一个随机 topic（如 `qd-bid-x7k9`） | `NTFY_URL` | `https://ntfy.sh/qd-bid-x7k9` |
| 微信办公 | 企业微信群 → 添加群机器人 → 复制 webhook | `WECOM_WEBHOOK` | `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx` |

**4. 手动跑一次验证：** 仓库页 → Actions → 「青岛招标每日监控」→ Run workflow。约 2 分钟后看运行日志末尾的 JSON 输出（含 push 结果）和手机通知。

## 注意事项

- **军采网境外访问风险**：GitHub 执行机在美国，军队网站可能限制境外 IP。第一次运行后看日志里 `plap` 条数——如果为 0 且 errors 里出现军采相关异常，说明被封，届时改用国内云函数（腾讯云 SCF）部署同一脚本即可，找我拿方案。
- **定时延迟**：GitHub schedule 是"尽力而为"，实际触发比 08:00 晚 5~30 分钟属正常；对招标监控无实质影响。
- **免费额度**：私有仓库每月 2000 分钟，本任务每天约 2 分钟，绰绰有余。
- **改关键词/窗口**：直接编辑 `fetch_and_report.py` 顶部的 `KEYWORDS` / `WINDOW_HOURS`，commit 即生效。
- **本地 Mac 上的同名定时任务**：云端跑通后建议关闭（App「定时」面板里停用），避免重复；没关也不冲突（本地那份不推手机）。
