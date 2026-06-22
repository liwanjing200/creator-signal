# Creator Signal

一个只供个人使用的 Creator Intelligence Hub。网页部署在 Vercel，结构化数据与登录放在 Supabase；后续采集与转写只在自己的 Apple Silicon Mac 上运行。

本项目只借鉴 `dragon-hh/ai-boshu-crawler` 的“创作者 → 最新视频 → 评论/字幕 → 任务记录”工作流边界，代码和数据模型均为独立实现。项目不使用飞书、lark-cli、Airtable、Docker、CUDA，也不建设长期云端视频仓库。

## 已实现能力

- Supabase 完整业务表、索引、触发器和单用户 RLS
- 邮箱密码登录，无公开注册入口
- 仪表盘统计与最近任务
- 博主新增、编辑、启用/停用与筛选
- 视频手工录入、搜索、筛选、排序与详情页
- 任务日志列表与筛选
- 视频详情中的评论、字幕、时间戳、内容参考和任务区域
- B站最近视频、分 P、互动快照、公开章节与去重更新
- X 官方 API 最近 Posts、媒体元数据、互动快照与去重更新
- B站代表性根评论，可选少量回复、限制、延迟与失败重试
- 抖音本地 Chrome CDP 主页/视频页采集、公开评论片段与页面章节
- 平台字幕优先；没有字幕时才临时读取媒体音频并转写
- Apple Silicon 使用 MLX/Metal；也兼容 `whisper.cpp`，默认 small，可选 medium
- 原始字幕、清洗字幕、时间戳段落、TXT/SRT/JSON、本地参考摘要与候选关键句
- 网页“评论/转写/重新转写”按钮写入任务队列，由 Mac 本地 worker 执行
- 转写成功后自动清理临时媒体；标记保留的原文件只留在 Mac 或外接硬盘

## 本地运行

在 Mac 上安装本地依赖：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-local.txt
```

在仅保存在本机的 `.env.local` 中设置 `NEXT_PUBLIC_SUPABASE_URL` 和
`SUPABASE_SERVICE_ROLE_KEY`，然后运行：

常用命令：

```bash
# B站最近视频与互动数据
.venv/bin/python scripts/creator_signal.py bilibili --max-videos 3

# B站代表性评论
.venv/bin/python scripts/creator_signal.py bilibili-comments --max-videos 10 --limit 30

# 单视频字幕读取/转录
.venv/bin/python scripts/creator_signal.py transcribe --video-id VIDEO_UUID --model small

# 处理网页按钮加入的任务；保持此命令运行即可从网页操作 Mac
.venv/bin/python scripts/creator_signal.py worker

# 抖音（先在 Chrome 打开并登录抖音，再开启 CDP）
.venv/bin/python scripts/creator_signal.py douyin --max-videos 3

# X 最近 Posts（X_BEARER_TOKEN 只保存在本机）
.venv/bin/python scripts/creator_signal.py x --max-videos 10

# 三个平台一次运行
.venv/bin/python scripts/creator_signal.py all --max-videos 3
```

采集命令支持 `--dry-run`、`--force`、`--max-creators`、`--max-videos` 和 `--retries`。
评论命令还支持 `--include-replies`、`--limit` 和 `--delay`。每次任务都会写入
`crawl_jobs`，并在 `local-data/manifests` 保存 JSON 调试记录。

首次本地转录可运行 `scripts/setup_whisper_mac.sh small`。有 Homebrew 时使用
`whisper.cpp`；没有 Homebrew 的 Apple Silicon Mac 使用 MLX/Metal。medium 模型只在手工
重新转录重要视频时下载。模型和媒体都不会上传到 Supabase。

抖音使用已登录的本地 Chrome 页面状态。请在 `chrome://inspect/#remote-debugging`
开启远程调试；程序只读取主页和视频页可见内容。抖音评论始终写入
`is_partial_public_sample=true`，网页明确显示“不是完整评论 API 数据”。

## 目录结构

```text
Creator Signal/
├── app/
│   ├── (dashboard)/
│   │   ├── creators/              # 博主列表、详情、编辑
│   │   ├── videos/                # 视频列表、详情、手工录入
│   │   ├── jobs/                  # 任务日志
│   │   ├── layout.tsx             # 登录后的侧边栏框架
│   │   └── page.tsx               # 仪表盘
│   ├── login/                     # 单用户登录
│   ├── actions.ts                 # 受 Auth/RLS 保护的写操作
│   ├── globals.css
│   └── layout.tsx
├── components/                    # 徽标、空状态、提示等通用 UI
├── lib/
│   ├── supabase/                  # 浏览器、服务端与会话刷新客户端
│   ├── format.ts
│   └── types.ts
├── supabase/
│   ├── migrations/
│   │   └── 0001_initial_schema.sql
│   └── seed.sql                   # 可选的手工测试数据
├── .env.example
├── .gitignore
├── proxy.ts                       # Next.js 16 登录保护
└── package.json
```

```text
scripts/
├── creator_signal.py              # bili / douyin / comments / transcribe / worker / all
├── pipeline.py                    # 评论、字幕、Metal 转录、清洗和任务执行
├── douyin_cdp.mjs                 # 本地 Chrome CDP 页面读取
└── setup_whisper_mac.sh           # Apple Silicon 转录环境

local-data/                        # 永远忽略：manifest、日志、临时媒体、字幕
```

## Supabase SQL

完整 SQL 位于 [`supabase/migrations/0001_initial_schema.sql`](supabase/migrations/0001_initial_schema.sql)，包含：

- `creators`
- `videos`
- `comments`
- `transcripts`
- `transcript_segments`
- `creator_metrics_snapshots`
- `video_metrics_snapshots`
- `crawl_jobs`
- `saved_files`
- `app_users` 单用户访问白名单

视频使用 `(platform, platform_video_id)` 唯一约束去重。所有业务表均启用 RLS，未进入 `app_users` 的账号即使通过 Supabase Auth 登录，也无法读写任何业务数据。`service_role` 只留给未来的本地脚本。

## 阶段 1 实施步骤

### 1. 创建 Supabase 项目

1. 新建 Supabase 项目，记下 Project URL、anon key 和 service role key。
2. 在 Authentication 的 Providers 中启用 Email。
3. 关闭公开注册（Allow new users to sign up），因为这是单用户应用。
4. 在 Authentication → Users 中手工创建自己的邮箱密码账号。
5. 打开 SQL Editor，执行 `supabase/migrations/0001_initial_schema.sql`。
6. 再执行下面这段，把自己的 Auth 用户加入唯一访问白名单：

```sql
insert into public.app_users (user_id)
select id from auth.users where email = '你的邮箱'
on conflict do nothing;
```

可选：执行 `supabase/seed.sql` 添加两位假博主。也可以登录网页后手工添加。

### 2. 配置本地网页

```bash
cp .env.example .env.local
npm install
npm run dev
```

在 `.env.local` 中填写：

```dotenv
NEXT_PUBLIC_SUPABASE_URL=你的项目地址
NEXT_PUBLIC_SUPABASE_ANON_KEY=你的anon密钥
```

网页永远不需要 `SUPABASE_SERVICE_ROLE_KEY`。不要把它加到 Vercel；此密钥只供 Mac 本地脚本使用。

### 3. 验收阶段 1

1. 用自己的账号登录。
2. 新增一位 B站和一位抖音博主，并验证编辑、停用和筛选。
3. 在视频页添加测试视频，验证重复平台视频 ID 会被拒绝。
4. 检查仪表盘统计和视频详情页。
5. 使用另一个测试 Auth 用户登录，确认看不到数据；测试后删除该用户。

### 4. 保存到 GitHub Private

在 GitHub 创建 **Private** 仓库后，再把当前目录连接并推送。提交前先运行 `git status`，确认没有 `.env.local`、媒体、Cookie、浏览器 Profile、字幕或日志。

### 5. 部署 Vercel

1. 在 Vercel 导入该 GitHub Private 仓库。
2. 添加且只添加 `NEXT_PUBLIC_SUPABASE_URL` 和 `NEXT_PUBLIC_SUPABASE_ANON_KEY`。
3. 部署后，在 Supabase Auth 的 URL Configuration 中把 Vercel 正式域名设为 Site URL。
4. 登录并重复本地验收步骤。

## 安全边界

- 前端只使用 Supabase anon key，真实权限由 RLS 决定。
- service role key 只放未来 Mac 本地脚本的 `.env`，绝不进入 Vercel。
- `.gitignore` 已覆盖环境文件、Cookie、Chrome Profile、媒体、字幕、manifest 和日志。
- 数据库存本地文件路径只是为了追踪状态，不会把 Mac 文件上传到 Supabase。
- 没有公开注册、多人协作、付费、发布 X 或固定模板式“洞察”。
- `reference_summary` 和 `candidate_quotes` 只是本地规则抽取，明确不冒充深度 AI 分析。
