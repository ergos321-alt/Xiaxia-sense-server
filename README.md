# Xiaxia Reality Server + Xiaxia Hand V1

林知夏的 Reality Sense 服务端。当前稳定能力保持不变，并增量加入 Xiaxia Hand V1：Custom GPT 创建语义化手机动作，服务端持久化并管理状态，Tasker 轮询领取后在 Android 端执行，再把结果回传服务端。

服务端不会直接控制手机；Tasker 是唯一执行端。

## Existing Reality capabilities

- Environment Reality
- Device / Network
- Phone Activity、Timeline、Short-term History
- GPS / Location、Amap Reverse Geocode、Nearby POI
- Spatial Reality、Personal Places、Route
- Supabase PostgreSQL 持久化
- Custom GPT Actions

## Runtime

- Python 3.11+
- Flask + Gunicorn
- PostgreSQL（生产环境使用 Supabase）

环境变量：

- `DATABASE_URL`：Supabase PostgreSQL 连接字符串
- `SENSE_TOKEN`：既有 Bearer Token；Reality、Phone、Spatial、Hand 共用
- `AMAP_KEY`：既有高德 Web 服务 Key
- `PORT`：本地运行端口，可选，默认 `8000`

启动：

```bash
pip install -r requirements.txt
gunicorn app:app
```

健康检查沿用稳定版接口：

```http
GET /ping
```

## Database migration

部署前可在 Supabase SQL Editor 执行：

```text
migrations/20260824_001_create_hand_commands.sql
```

该 migration 只新增 `hand_commands` 表和索引，不修改任何既有表。应用的 `get_db()` 也会执行同一组 `CREATE TABLE/INDEX IF NOT EXISTS`，确保新部署首次连接时可安全初始化；命令持久化于 PostgreSQL，Render 重启不会丢失。

## Xiaxia Hand V1 actions

仅允许以下白名单；服务器保存语义，不保存或执行任意 Tasker 脚本。

| action | parameters |
| --- | --- |
| `flashlight` | `state`: `on` / `off` |
| `volume` | `stream`: 仅 `media`; `level`: 0–100 整数 |
| `open_app` | `app`: Tasker 侧识别的应用语义名称 |
| `timer` | `duration_seconds`: 1–604800; `label` 可选 |
| `alarm` | `time`: 手机本地时间 `HH:MM`; `label` 可选 |
| `do_not_disturb` | `state`: `on` / `off` |
| `battery_saver` | `state`: `on` / `off` |
| `navigation` | 必填 `destination`; 可选 `latitude`、`longitude`、`place_id`、`travel_mode` |

`navigation.travel_mode` 与既有 Spatial Route 保持一致：`walking`、`driving`、`cycling`、`electrobike`。Hand 只传递导航意图，不重新实现地图或路线计算。

## Hand API

所有接口都必须携带：

```http
Authorization: Bearer <SENSE_TOKEN>
Content-Type: application/json
```

### Create a command

```http
POST /hand/commands
```

```json
{
  "action": "flashlight",
  "parameters": {
    "state": "on"
  }
}
```

成功返回 `201`：

```json
{
  "command_id": "7ddfdcbd-05c7-4a24-8240-a6473c1042fd",
  "status": "pending"
}
```

非法 action、缺失参数、越界参数及额外字段返回 `400`。

### Claim the next command

```http
GET /hand/commands/next
```

存在任务时，服务端原子领取最早的 `pending` 命令并立即改为 `delivered`：

```json
{
  "status": "delivered",
  "command": {
    "command_id": "7ddfdcbd-05c7-4a24-8240-a6473c1042fd",
    "action": "flashlight",
    "parameters": {
      "state": "on"
    },
    "status": "delivered",
    "created_at": "2026-08-24T12:00:00+00:00",
    "delivered_at": "2026-08-24T12:00:02+00:00",
    "executed_at": null,
    "expires_at": "2026-08-25T12:00:00+00:00",
    "result": null,
    "error": null
  }
}
```

无任务时明确返回：

```json
{
  "status": "empty",
  "command": null
}
```

领取使用 PostgreSQL `FOR UPDATE SKIP LOCKED` 和单条 `UPDATE ... RETURNING`；多个轮询请求不会领取同一条命令。已变为 `delivered` 的命令不会再次发放。

### Report a result

```http
POST /hand/commands/{command_id}/result
```

成功：

```json
{
  "status": "executed",
  "result": {}
}
```

失败：

```json
{
  "status": "failed",
  "result": {},
  "error": "permission denied"
}
```

仅 `delivered` 可转为 `executed` 或 `failed`。重复上报相同终态是幂等的；冲突终态返回 `409`。

### Query command status

```http
GET /hand/commands/{command_id}
```

返回完整命令、时间戳、结果和错误。不存在的命令返回 `404`。

## Xiaxia Hand V1 Tasker Integration

### Recommended polling

1. 建立一个 Tasker 定时 Profile，建议前台使用期望的较短轮询周期；后台轮询周期需结合 Android 电池限制实机调整。
2. 使用 HTTP Request 调用 `GET /hand/commands/next`。
3. Header 设置 `Authorization: Bearer %SENSE_TOKEN`。
4. 若响应 `status=empty`，结束本轮任务。
5. 若响应 `status=delivered`，读取 `command.command_id`、`command.action` 与 `command.parameters`。
6. 使用 `If / Else If` 按 8 个白名单 action 分派到明确的 Tasker Task。
7. Android 动作执行结束后，无论成功或失败都调用 result 接口。

不要在服务端建立 Android package 映射。`open_app.parameters.app` 到 package/Tasker App 动作的映射保留在手机端，便于适配实际安装应用。

### Tasker state flow

```text
pending -> delivered -> executed
                     -> failed
pending/delivered -> expired
```

命令创建后 24 小时仍未完成会在后续领取或查询时标记为 `expired`。为了防止重复执行，Tasker 不应自行重放 `delivered` 命令；网络超时后应先通过查询接口确认状态。

### Tasker JSON paths

- `%http_data.status`
- `%http_data.command.command_id`
- `%http_data.command.action`
- `%http_data.command.parameters.state`
- `%http_data.command.parameters.level`
- `%http_data.command.parameters.app`
- `%http_data.command.parameters.duration_seconds`
- `%http_data.command.parameters.time`
- `%http_data.command.parameters.destination`

具体 JSON 变量语法会随 Tasker 版本和结构化输出设置不同，请以真机版本为准。本项目不生成复杂 Tasker XML。

## Custom GPT Action schema

Action Schema 位于 `openapi.yaml`，保留 Reality、Phone、Spatial 的已有读取/管理接口并新增 Hand 接口。所有 operationId 唯一，Hand 的 `action` 和参数均设置白名单/enum；不存在 `execute_anything` 或 `run_tasker_command`。

Schema 只向 Custom GPT 暴露 `POST /hand/commands` 与 `GET /hand/commands/{command_id}`。Tasker 专用的领取和结果回传接口不会暴露给 GPT，避免 GPT 误领命令或伪造 Android 执行结果；Tasker 按上文直接调用服务端接口。

输入代码包未包含当前 Render 公网域名，因此 Schema 不伪造服务器 URL。导入 Custom GPT Action 前，请把真实 HTTPS Render 根地址添加为 OpenAPI 顶层 `servers[0].url`；不要添加路径后缀，也不要把 Token 写入 Schema。随后在 Authentication 中选择 API Key、Bearer，并填写现有 `SENSE_TOKEN`。

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

测试覆盖 Hand 白名单参数、创建、领取、空队列、状态变化、结果回写、查询、鉴权、幂等性，以及稳定版 Reality / Phone / Spatial 主要接口的隔离回归。
