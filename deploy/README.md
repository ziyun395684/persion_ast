# 生产部署检查清单

## 启动

生产环境不要使用 `--reload`，并保持单 worker，避免内存中的 Laya、向量
降级后端和后台任务重复运行：

```powershell
$env:APP_HOST = "127.0.0.1"
$env:APP_PORT = "8111"
C:\Users\Windows\anaconda3\envs\fund_p312\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8111
```

外部访问应放在 Nginx、Caddy 或 Tailscale 等受控入口后面，不建议直接把
`8111` 暴露到公网。代理需要允许长连接和 SSE：

- `proxy_buffering off`
- `proxy_read_timeout` 至少 120 秒
- 转发 `Authorization` 和 `X-Request-ID`

## 上线前检查

```powershell
C:\Users\Windows\anaconda3\envs\fund_p312\python.exe scripts/preflight.py
C:\Users\Windows\anaconda3\envs\fund_p312\python.exe -m scripts.backup_database --output-dir backups
C:\Users\Windows\anaconda3\envs\fund_p312\python.exe -m scripts.verify_backup sqlite:///./backups/database-YYYYMMDD-HHMMSS.db
```

MySQL 部署必须另外确认：

1. `mysqldump` 和 `mysql` 在 PATH 中。
2. 使用独立应用账号，不授予不必要的管理权限。
3. 在临时 MySQL 数据库执行一次导入，再运行 `preflight.py` 和 API 验收。
4. 备份密码通过环境变量或系统密钥存储注入，不写入脚本参数。

## Windows 运行

使用任务计划程序配置：

- 程序：`C:\Users\Windows\anaconda3\envs\fund_p312\python.exe`
- 参数：`-m uvicorn main:app --host 127.0.0.1 --port 8111`
- 工作目录：项目根目录
- 失败后重试：1 分钟后重试 3 次

另建每天运行的备份任务，并保留最近 7 到 30 天的备份。上线后观察：

- `/health/ready`
- `chat_total` 和 `chat_stage` 日志
- HTTP 5xx、模型超时、Milvus/Hindsight 降级日志

账号注销和数据导出接口：

- `GET /auth/export`
- `DELETE /auth/account`

注销前应先按合规要求保存用户主动导出的数据；注销会立即停用账号并删除应用数据库中的用户数据。
