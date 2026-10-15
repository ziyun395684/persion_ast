# AI 女友兼助手 Agent

这是一个基于 FastAPI + LangGraph 的多用户 AI 女友兼助手。当前已包含真实模型调用、L1/L2/L3 记忆链路、Milvus 适配、todo/note/time/web 工具、JWT 登录、人格模板和按用户隔离的聊天前端。

## 运行

使用 Conda 环境 `fund_p312`：

```bash
conda activate fund_p312
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8111 --reload
```

启动后可访问：

- `http://127.0.0.1:8111/docs`：Swagger API 文档
- `http://127.0.0.1:8111/health`：服务健康检查
- `http://127.0.0.1:8111/health/live`：轻量存活检查
- `http://127.0.0.1:8111/health/ready`：依赖就绪检查
- `http://127.0.0.1:8111/`：聊天前端

所有 HTTP 响应都会返回 `X-Request-ID`。客户端可以透传该请求 ID，服务端会记录方法、路径、状态码和耗时，便于定位超时与连接问题。

`POST /chat/stream` 会优先使用 Ollama 或 Qwen 的上游流式接口，将模型产生的
delta 直接通过 SSE 转发到前端；工具调用和模型降级时仍会使用本地分块兜底。
后端日志中的 `chat_stage` 记录 flush、意图识别、提示词组装、模型调用和消息
落库等阶段耗时，`chat_total` 记录整轮耗时。

## 验证

保持服务运行，在另一个终端执行：

```bash
bash scripts/smoke_test.sh

# 完整本地 API 验收（会调用真实 /chat，请确认模型服务可用）
python scripts/acceptance_check.py

# 上线前依赖检查，不打印密钥
python scripts/preflight.py
```

`acceptance_check.py` 会检查 `/health`、真实 `/chat` 和 `/assistant/query`，不会打印密钥。

运行自动化测试：

```bash
pytest -q
```

## 数据库备份

备份脚本会根据 SQLAlchemy 数据库 URL 自动选择 SQLite 文件备份或 MySQL
`mysqldump` 备份。默认输出到 `backups/`，也可以显式指定目录和文件名：

```powershell
# 使用 .env 中的 APP_DATABASE_URL 或 DB_* 配置
C:\Users\Windows\anaconda3\envs\fund_p312\python.exe -m scripts.backup_database

# 指定输出文件
C:\Users\Windows\anaconda3\envs\fund_p312\python.exe -m scripts.backup_database `
  --output-dir backups --filename database-20261001.sql
```

当数据库为 MySQL 时，机器上必须能找到 `mysqldump`；可以用 `--mysqldump`
传入它的完整路径。数据库密码通过子进程环境变量 `MYSQL_PWD` 传递，不会
出现在命令行参数或脚本输出中。恢复前请先停止写入流量并确认备份文件，
MySQL 可使用 `mysql` 导入 SQL，SQLite 则应在应用停止后替换数据库文件。

编译检查：

```bash
python -m compileall -q main.py app frontend tests scripts
```

生产部署和恢复检查见 `deploy/README.md`。SQLite 备份可以使用
`scripts.verify_backup` 执行完整性检查；MySQL 需要在临时数据库执行真实导入演练。

## Hindsight 联调

Hindsight 默认关闭，不需要 Docker 也不影响主系统。配置远程 Hindsight 后，可设置：

```bash
HINDSIGHT_ENABLED=true
HINDSIGHT_URL=https://api.hindsight.vectorize.io
HINDSIGHT_API_KEY=your-key
HINDSIGHT_BANK_ID=main
```

依赖已包含在根目录 `requirements.txt` 中。配置后运行：

```bash
python scripts/check_hindsight.py
python scripts/init_mental_models.py
```

检查脚本会验证健康状态、retain、recall 和 Mental Models，不会打印密钥。
当前项目使用远程 Hindsight 时不需要 Docker；只有计划自行部署 Hindsight 服务时才需要 Docker。

## 目录结构

```text
app/
  api/              # FastAPI 路由
  prompts/          # L0/L1/L3 prompt 常量
  services/         # 消息、记忆、编排、模型、向量和 Hindsight 服务
  config.py         # Settings 与 CFG 单例
  db.py             # SQLAlchemy engine 与 session
  models.py         # ORM 模型
main.py             # FastAPI 入口
scripts/            # smoke 和调试脚本
tests/              # 自动化测试
```
## 多用户登录

当前服务支持用户名密码注册和 JWT 登录。配置 `APP_AUTH_SECRET` 后启动服务，访问前端后先注册或登录；聊天、历史消息和人格配置均按用户隔离。历史单用户数据属于 `legacy_user`。

认证安全规则：密码至少 8 位，且必须同时包含字母和数字；登录失败会按用户名和来源地址限流。生产环境应设置强随机的 `APP_AUTH_SECRET`，并按部署规模配置 `APP_AUTH_LOGIN_MAX_ATTEMPTS` 与 `APP_AUTH_LOGIN_WINDOW_SEC`。

会话删除提供两种方式：

- `DELETE /conversations/{conversation_id}`：删除会话和聊天消息，保留长期记忆。
- `DELETE /conversations/{conversation_id}/forget`：删除会话、聊天消息和能明确追溯到该会话的本地/Milvus 记忆；外部 Hindsight 无法取得可删除节点标识时会通过 `warnings` 返回提醒。

会话人格支持临时覆盖：

- `GET/PUT /conversations/{conversation_id}/persona`：设置当前会话的风格、沟通模式、称呼和临时指令。
- 会话覆盖只影响当前会话，不会改变注册时确定的用户基底人格或其他会话。
- 将覆盖字段传为 `null` 可恢复对应的用户默认值。

长期记忆管理接口：

- `GET /memory/events`：查看当前用户的长期记忆。
- `PATCH /memory/events/{event_id}`：编辑记忆内容、重要性和发生日期。
- `DELETE /memory/events/{event_id}`：删除单条记忆，并尽力清理 Milvus/Hindsight 对应数据。

账号数据生命周期：

- `GET /auth/export`：导出当前用户的聊天、会话、人格、记忆、待办和笔记数据，不包含密码哈希。
- `DELETE /auth/account`：删除当前用户数据并停用账号；已有 JWT 会立即失效。

语音接口是可选能力：

- `POST /voice/transcribe`：上传 16kHz、16bit、单声道 WAV 音频转文字。
- `POST /voice/synthesize`：文字转 MP3 音频。
- `POST /voice/chat`：语音输入、文字回复并尽力返回语音。

Flet 移动端客户端位于 `mobile/app/main.py`，支持登录、文字聊天、本地历史、API 地址配置和豆包语音按钮。移动端依赖已包含在根目录 `requirements.txt` 中；可先用桌面模式运行，再使用根目录 `pyproject.toml` 配置打包 APK。

未安装语音依赖时，语音接口会返回明确的降级错误，不影响文字聊天。

迁移现有 MySQL 数据：

```powershell
C:\Users\Windows\anaconda3\envs\fund_p312\python.exe -m scripts.migrate_to_multi_user
```
