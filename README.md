# Creator Signal

一个只供个人使用的 Creator Intelligence Hub。网页部署在 Vercel，结构化数据与登录放在 Supabase；后续采集与转写只在自己的 Apple Silicon Mac 上运行。

本项目只借鉴 `dragon-hh/ai-boshu-crawler` 的“创作者 → 最新视频 → 评论/字幕 → 任务记录”工作流边界，代码和数据模型均为独立实现。项目不使用飞书、lark-cli、Airtable、Docker、CUDA，也不建设长期云端视频仓库。

## 当前阶段

阶段 1 已实现：

- Supabase 完整业务表、索引、触发器和单用户 RLS
- 邮箱密码登录，无公开注册入口
- 仪表盘统计与最近任务
- 博主新增、编辑、启用/停用与筛选
- 视频手工录入、搜索、筛选、排序与详情页
- 任务日志列表与筛选
- 视频详情中的评论、字幕、时间戳、内容参考和任务区域
- “保留原文件”标记（只记录策略，不上传文件）

B站最新视频采集已加入；评论抓取、抖音采集和本地 Whisper 尚未加入。页面中相关按钮会明确显示后续阶段，不会假装任务已经执行。

## 本地 B站采集（阶段 2）

在 Mac 上安装本地依赖：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-local.txt
```

在仅保存在本机的 `.env.local` 中设置 `NEXT_PUBLIC_SUPABASE_URL` 和
`SUPABASE_SERVICE_ROLE_KEY`，然后运行：

```bash
.venv/bin/python scripts/creator_signal.py bilibili --max-videos 3
```

支持 `--dry-run`、`--force`、`--max-creators`、`--max-videos` 和 `--retries`。
采集器只读取公开元数据，不下载视频；每次运行会写入 `crawl_jobs`，并在
`local-data/manifests` 保存 JSON 调试记录。

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

后续阶段计划增加以下本地目录；阶段 1 不创建空壳自动化：

```text
local/
├── creator_hub/                   # Supabase 客户端、采集、转写、清洗
├── commands/                      # bili / douyin / comments / transcribe / all
├── tests/
└── pyproject.toml

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

阶段 1 网页不需要 `SUPABASE_SERVICE_ROLE_KEY`。不要把它加到 Vercel。

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
- 第一版没有公开注册、多人协作、付费、发布 X 或固定模板式“洞察”。

## 后续阶段边界

- 阶段 2：B站最近视频、互动快照、去重 upsert、JSON manifest。
- 阶段 3：B站代表性评论；Chrome CDP 抖音主页/视频页和少量公开评论。
- 阶段 4：平台字幕优先，必要时临时下载；`ffmpeg` 16kHz 单声道；`whisper.cpp` Metal，默认 small，可手工 medium；成功写库后清理临时媒体。
