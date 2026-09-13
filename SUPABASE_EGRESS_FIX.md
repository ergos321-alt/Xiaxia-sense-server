# Supabase Egress 最小修复报告

## 结论

本轮只修改了 SensorLogger `/data` 直接触发的 PostgreSQL 高频访问链路。代码验收已通过；生产 Egress 验收必须在 Render 部署后观察 Supabase Shared Pooler Egress，当前不能以本地测试替代或宣布 Production PASS。

## 已证实根因

原 `POST /data` 的每一次合法请求都会：

1. 调用 `get_db()`，新建 1 个 Supabase PostgreSQL 连接。
2. 在该连接上重复执行 12 条 `CREATE TABLE/INDEX IF NOT EXISTS`，然后 commit。
3. 向 `messages` 写入 1 份完整 raw JSON。
4. 对 payload 中每个合法 sensor 先执行 1 次 `SELECT sensor_time_ns`；较新时再执行 1 次 UPSERT。
5. 若包含较新的 location，再对 `spatial_history` 执行 1 次 SELECT，并按原采样规则可能 INSERT 1 行。
6. 每个 worker 每 10 分钟首次触发时，再执行 3 次 retention DELETE。
7. commit 并关闭连接。

因此，在没有 location、每帧含 N 个持续变新的 sensor 时，单次 warm `/data` 固定为：1 connection、N SELECT、1+N INSERT/UPSERT、12 DDL；每 10 分钟另有 3 DELETE。以上是直接位于同步请求路径中的确定行为，不是推测。

全仓搜索确认 `messages` 只有 `/data` 写入和 housekeeping 删除，没有任何 API、Reality、History、debug 或 Hand 读取它。它不承载当前生产功能语义，可以安全改为随 flush 采样保存最新一帧，而无需删除表或改变 retention。

## 最小修改

- `/data` 在 Render 进程内按 `sensor_name` 合并 latest state，HTTP path、鉴权、请求和响应 schema 保持不变。
- 默认每 60 秒（可用 `SENSOR_FLUSH_INTERVAL_SECONDS` 调整）才建立一次数据库连接。
- 一个 flush 内所有 dirty sensors 由单条多行 UPSERT 持久化；数据库端的 timestamp 条件防止旧帧覆盖新值。
- `messages` 每个 flush 窗口仅保留最新一份 raw JSON。
- Reality 读取仍从数据库 fallback，并用 timestamp 更高的内存 latest state 覆盖，因此 flush 间隔不会令实时 Reality 变旧，`updated_at`、`age_seconds` 和 freshness 仍基于真实接收时间。
- spatial history 仍使用原有“间隔至少 60 秒，或移动至少 30 米”规则；同一窗口只做一次 baseline SELECT，并把被选中的历史点合为一条多行 INSERT。
- schema initialization 保留，但每个服务 worker 只在第一次数据库连接执行一次，后续 runtime connection 不再重复 DDL。
- process exit 注册 best-effort 强制 flush；数据库不可用或强制终止时，Supabase 中上一份周期快照仍是 fallback。

## 修改前后调用链

### 修改前

`POST /data → get_db → connect → 12 DDL → commit → INSERT messages → [每 sensor: SELECT + UPSERT] → [location: SELECT + optional INSERT] → [间歇性 3 DELETE] → commit → close`

### 修改后（flush 未到期）

`POST /data → merge process-local latest/raw/spatial candidates → return`，数据库调用为 0。

### 修改后（flush 到期）

`POST /data → merge cache → get_db/connect → sampled INSERT messages → one batched sensor UPSERT → [location window: one SELECT + optional one batched INSERT] → [间歇性 3 DELETE] → commit → close`

新 worker 的第一次数据库连接会在上述业务 SQL 前额外执行一次 12 条 schema DDL；同一 worker 后续不再执行。

## 高频 instrumentation 结果

自动测试使用每帧 2 个持续变新的 latest sensors、不含 location、60 秒窗口内连续请求。计数按 SQL statement 统计；批量 UPSERT 虽可包含多行，只算 1 条 INSERT/UPSERT。

| 场景 | HTTP Push | DB connection | SELECT | INSERT/UPSERT | UPDATE | retention DELETE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 修改前（由原同步调用链确定） | 60 | 60 | 120 | 180 | 0 | 3 |
| 修改后（自动 instrumentation，含末尾强制 flush） | 60 | 2 | 0 | 4 | 0 | 3 |
| 修改前（由原同步调用链确定） | 300 | 300 | 600 | 900 | 0 | 3 |
| 修改后（自动 instrumentation，含末尾强制 flush） | 300 | 2 | 0 | 4 | 0 | 3 |

修改前还分别包含 720 / 3600 条重复 DDL。修改后 cold worker 首次 flush 为 12 条 DDL，此后为 0；独立自动测试确认两个连续 `get_db()` 连接合计只运行一次 12 条 DDL。

说明：测试计数包含首帧立即 flush，以及为证明最终帧可持久化而执行的末尾强制 flush。若测试持续超过 60 秒，会按窗口增加 flush；稳定运行时连接与业务写入量约由“每个 Push 一轮”降为“每 60 秒一轮”。location 历史点仍按产品原规则保留，因此发生真实的 30 米以上移动时，历史行数不会被 latest-state 优化抹掉。

## 自动测试

- 高频 `/data`：60 与 300 次 Push 的 connection/SQL statement instrumentation。
- Reality freshness：数据库仍为上一快照时，读取返回最新未 flush 的内存帧。
- 重启/fallback：空 cache 时从 PostgreSQL 恢复 sensor latest。
- spatial history：时间/距离规则保留，并验证窗口批量写入。
- schema：每 worker 仅初始化一次且仍包含 12 条 DDL。
- 原有 Reality、phone timeline/history、spatial history/places/route 回归。
- 原有 Hand action whitelist、create、claim、result、status、幂等与状态机回归。
- OpenAPI YAML、operationId 唯一性及 Tasker-only path 隔离回归。

最终结果：`39 passed`。

## 明确未修改

- 所有 API path、HTTP method、鉴权方式、请求 payload、响应 schema。
- OpenAPI 文件及 operationId。
- Phone Activity latest、events、timeline、history 的读取和写入逻辑。
- Spatial Reality 的 reverse geocode、nearby POI、movement analysis、personal places、nearest place、route。
- Weather、semantic interpretation、environment/device/network context。
- Xiaxia Hand 白名单、数据库表、Tasker payload、claim/result 行为及 `pending → delivered → executed/failed` 状态机。
- Flask/Gunicorn 架构、数据库产品、Tasker 流程；未引入 Redis、Celery、queue、worker 或任何新云服务。

## 已知边界

- 当前 `Procfile` 的 Gunicorn 命令使用默认单 worker，符合单进程 cache 假设。将来若设置多 worker 或多 Render 实例，各进程 cache 独立，必须重新评估一致性和 Egress。
- Render 被强制终止、机器故障或 flush 时数据库不可用，最多可能丢失一个 flush 间隔内未持久化的 latest/raw 数据；Reality 在进程存活期间仍读取最新内存值。
- raw `messages` 已改为每窗口采样一帧；该表当前无读取依赖，但它不再是逐帧完整审计日志。

## 生产验收步骤

1. 记录部署前 Supabase Egress Breakdown 中 Shared Pooler Egress 的时间、累计值和观察窗口；尽量选择与验收相同的 SensorLogger 频率和传感器集合。
2. 部署本 ZIP，保持 `Procfile` 默认单 worker；先不要设置 `SENSOR_FLUSH_INTERVAL_SECONDS`，使用默认 60 秒。
3. 用现有 Tasker/SensorLogger payload 调用 `/data`，确认 200 响应的 `status`、`received`、`updated_sensors` 与旧客户端兼容。
4. 连续 Push 后立即调用现有 Reality endpoints，核对最新 sensor 值、`updated_at`、`age_seconds`、freshness、location/spatial 结果。
5. 保持 SensorLogger 实际运行至少 1–2 小时；同时抽查 phone timeline/history、spatial history、Personal Places、Weather 和 Hand create/claim/result/status。
6. 重启 Render，确认 cache 为空时 Reality 能从 Supabase 返回最后一次周期快照；可接受的持久化落后上限为 60 秒。
7. 在同等时长、同等 Push 频率下比较 Shared Pooler Egress 增量和增长斜率。预期 `/data` 主链路的连接频率从每 Push 一次降至约每分钟一次。
8. 只有真实 Shared Pooler Egress 增长速度显著下降且功能抽查通过，才标记 Production PASS。若没有明显下降，不继续叠补丁，应重新按 Supabase Breakdown、Render request log 和数据库 query 观测定位其他来源。
