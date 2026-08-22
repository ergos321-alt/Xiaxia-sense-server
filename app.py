import os
import json
import sqlite3
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from semantic import build_semantic_context
from weather import build_weather_context
from reality import build_reality_context


app = Flask(__name__)


# =========================
# 基础配置
# =========================

SENSE_TOKEN = os.environ.get("SENSE_TOKEN", "")

DATA_DIR = os.environ.get("DATA_DIR", "/tmp")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "xiaxia_sense.db")


FRESHNESS_THRESHOLDS = {
    "battery": 120,
    "light": 60,
    "barometer": 300,
    "network": 120,
    "location": 300,
    "microphone": 30,
    "pedometer": 300,
    "activity": 60
}

DEFAULT_FRESHNESS_SECONDS = 300


# =========================
# 时间与新鲜度
# =========================

def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def freshness_info(sensor_name, updated_at):
    try:
        updated = datetime.fromisoformat(updated_at)

        if updated.tzinfo is None:
            updated = updated.replace(
                tzinfo=timezone.utc
            )

        age_seconds = max(
            0,
            int(
                (
                    datetime.now(timezone.utc)
                    - updated
                ).total_seconds()
            )
        )

        threshold = FRESHNESS_THRESHOLDS.get(
            sensor_name,
            DEFAULT_FRESHNESS_SECONDS
        )

        return {
            "age_seconds": age_seconds,
            "freshness": (
                "fresh"
                if age_seconds <= threshold
                else "stale"
            )
        }

    except Exception:
        return {
            "age_seconds": None,
            "freshness": "unknown"
        }


# =========================
# 数据库
# =========================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER,
            session_id TEXT,
            device_id TEXT,
            received_at TEXT NOT NULL,
            raw_json TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sensor_latest (
            sensor_name TEXT PRIMARY KEY,
            sensor_time_ns INTEGER NOT NULL,
            values_json TEXT NOT NULL,
            message_id INTEGER,
            session_id TEXT,
            device_id TEXT,
            updated_at TEXT NOT NULL
        )
    """)

    conn.commit()

    return conn


# =========================
# 鉴权
# =========================

def check_token():
    if not SENSE_TOKEN:
        return jsonify({
            "error": "server_not_configured",
            "message": (
                "SENSE_TOKEN is not configured"
            )
        }), 503

    auth = request.headers.get(
        "Authorization",
        ""
    )

    if not auth.startswith("Bearer "):
        return jsonify({
            "error": "unauthorized"
        }), 401

    token = auth[7:].strip()

    if token != SENSE_TOKEN:
        return jsonify({
            "error": "unauthorized"
        }), 401

    return None


# =========================
# Reality 数据读取公共函数
#
# 所有 Reality API 都从这里取得同一份
# 当前现实，避免不同接口各写一套逻辑。
# =========================

def load_latest_sensors():
    conn = get_db()

    rows = conn.execute("""
        SELECT
            sensor_name,
            sensor_time_ns,
            values_json,
            updated_at
        FROM sensor_latest
        ORDER BY sensor_name
    """).fetchall()

    conn.close()

    sensors = {}

    for row in rows:
        sensor_name = row["sensor_name"]

        freshness = freshness_info(
            sensor_name,
            row["updated_at"]
        )

        try:
            values = json.loads(
                row["values_json"]
            )

        except Exception:
            values = {}

        sensors[sensor_name] = {
            "time_ns": row["sensor_time_ns"],
            "values": values,
            "updated_at": row["updated_at"],
            "age_seconds": (
                freshness["age_seconds"]
            ),
            "freshness": (
                freshness["freshness"]
            )
        }

    return sensors


def build_current_context():
    sensors = load_latest_sensors()

    semantic = build_semantic_context(
        sensors
    )

    weather = build_weather_context(
        semantic
    )

    reality = build_reality_context(
        semantic,
        weather
    )

    return {
        "sensors": sensors,
        "semantic": semantic,
        "weather": weather,
        "reality": reality
    }


# =========================
# 健康检查
#
# 公开接口。
# 只说明服务器是否在线，
# 不返回任何用户现实数据。
# =========================

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({
        "status": "ok",
        "service": "xiaxia-sense-server",
        "generated_at": utc_now_iso()
    })


# =========================
# SensorLogger 数据入口
# =========================

@app.route("/data", methods=["POST"])
def receive_data():
    auth_error = check_token()

    if auth_error:
        return auth_error

    data = request.get_json(
        silent=True
    )

    if not isinstance(data, dict):
        return jsonify({
            "error": "invalid_json"
        }), 400

    message_id = data.get("messageId")
    session_id = data.get("sessionId")
    device_id = data.get("deviceId")
    payload = data.get(
        "payload",
        []
    )

    received_at = utc_now_iso()

    conn = get_db()

    conn.execute("""
        INSERT INTO messages (
            message_id,
            session_id,
            device_id,
            received_at,
            raw_json
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        message_id,
        session_id,
        device_id,
        received_at,
        json.dumps(
            data,
            ensure_ascii=False
        )
    ))

    updated_sensors = []

    if isinstance(payload, list):
        for reading in payload:

            if not isinstance(
                reading,
                dict
            ):
                continue

            sensor_name = reading.get(
                "name"
            )

            sensor_time_ns = reading.get(
                "time"
            )

            values = reading.get(
                "values",
                {}
            )

            if not sensor_name:
                continue

            if not isinstance(
                sensor_time_ns,
                int
            ):
                continue

            old = conn.execute("""
                SELECT sensor_time_ns
                FROM sensor_latest
                WHERE sensor_name = ?
            """, (
                sensor_name,
            )).fetchone()

            if (
                old is None
                or sensor_time_ns
                > old["sensor_time_ns"]
            ):
                conn.execute("""
                    INSERT INTO sensor_latest (
                        sensor_name,
                        sensor_time_ns,
                        values_json,
                        message_id,
                        session_id,
                        device_id,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)

                    ON CONFLICT(sensor_name)
                    DO UPDATE SET
                        sensor_time_ns =
                            excluded.sensor_time_ns,
                        values_json =
                            excluded.values_json,
                        message_id =
                            excluded.message_id,
                        session_id =
                            excluded.session_id,
                        device_id =
                            excluded.device_id,
                        updated_at =
                            excluded.updated_at
                """, (
                    sensor_name,
                    sensor_time_ns,
                    json.dumps(
                        values,
                        ensure_ascii=False
                    ),
                    message_id,
                    session_id,
                    device_id,
                    received_at
                ))

                updated_sensors.append(
                    sensor_name
                )

    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",
        "received": (
            len(payload)
            if isinstance(payload, list)
            else 0
        ),
        "updated_sensors": (
            updated_sensors
        )
    }), 200


# =========================
# 旧版完整调试上下文
#
# 保留。
# 主要供工程检查使用。
#
# 它返回：
# sensors
# semantic
# weather
# reality
#
# Custom GPT 正式 Action
# 优先使用 /reality/* 接口。
# =========================

@app.route("/context", methods=["GET"])
def context():
    auth_error = check_token()

    if auth_error:
        return auth_error

    current = build_current_context()

    return jsonify({
        "status": "ok",
        "generated_at": utc_now_iso(),
        "sensors": current["sensors"],
        "semantic": current["semantic"],
        "weather": current["weather"],
        "reality": current["reality"]
    })


# =========================================================
# Xiaxia Reality Action API
# =========================================================


# =========================
# 1. 完整现实上下文
#
# 给夏夏获取当前完整 Reality。
# 不返回原始 SensorLogger 数据，
# 避免把工程噪音直接塞给模型。
# =========================

@app.route(
    "/reality/context",
    methods=["GET"]
)
def reality_context():
    auth_error = check_token()

    if auth_error:
        return auth_error

    current = build_current_context()

    return jsonify({
        "status": "ok",
        "generated_at": utc_now_iso(),
        "reality": current["reality"]
    })


# =========================
# 2. Reality 摘要
#
# 用于大多数日常场景。
#
# 返回：
# deterministic summary
# conservative inferences
# =========================

@app.route(
    "/reality/summary",
    methods=["GET"]
)
def reality_summary():
    auth_error = check_token()

    if auth_error:
        return auth_error

    current = build_current_context()

    reality = current["reality"]

    return jsonify({
        "status": "ok",
        "generated_at": utc_now_iso(),
        "summary": reality.get(
            "summary",
            {}
        ),
        "inferences": reality.get(
            "inferences",
            {}
        )
    })


# =========================
# 3. 环境现实
#
# 适用于：
# 天气、温度、雨、风、
# 光线、声音、气压等问题。
# =========================

@app.route(
    "/reality/environment",
    methods=["GET"]
)
def reality_environment():
    auth_error = check_token()

    if auth_error:
        return auth_error

    current = build_current_context()

    reality = current["reality"]

    summary = reality.get(
        "summary",
        {}
    )

    relevant_summary = {}

    summary_keys = [
        "thermal_feel",
        "precipitation",
        "ambient_light",
        "ambient_sound",
        "weather_description",
        "surroundings_description"
    ]

    for key in summary_keys:
        value = summary.get(key)

        if value is not None:
            relevant_summary[key] = value

    return jsonify({
        "status": "ok",
        "generated_at": utc_now_iso(),
        "environment": reality.get(
            "environment",
            {}
        ),
        "weather": reality.get(
            "weather",
            {}
        ),
        "summary": relevant_summary
    })


# =========================
# 4. 设备现实
#
# 适用于：
# 电池、充电、网络状态。
# =========================

@app.route(
    "/reality/device",
    methods=["GET"]
)
def reality_device():
    auth_error = check_token()

    if auth_error:
        return auth_error

    current = build_current_context()

    reality = current["reality"]

    summary = reality.get(
        "summary",
        {}
    )

    relevant_summary = {}

    summary_keys = [
        "device_power",
        "connectivity",
        "device_description",
        "connectivity_description"
    ]

    for key in summary_keys:
        value = summary.get(key)

        if value is not None:
            relevant_summary[key] = value

    return jsonify({
        "status": "ok",
        "generated_at": utc_now_iso(),
        "device": reality.get(
            "device",
            {}
        ),
        "network": reality.get(
            "network",
            {}
        ),
        "summary": relevant_summary
    })


# =========================
# 5. 位置现实
#
# 返回位置事实及位置质量。
#
# 注意：
# API 不自行解释具体地点名称，
# 这里只提供 Reality 已经确认的事实。
# =========================

@app.route(
    "/reality/location",
    methods=["GET"]
)
def reality_location():
    auth_error = check_token()

    if auth_error:
        return auth_error

    current = build_current_context()

    reality = current["reality"]

    summary = reality.get(
        "summary",
        {}
    )

    return jsonify({
        "status": "ok",
        "generated_at": utc_now_iso(),
        "location": reality.get(
            "location",
            {}
        ),
        "location_quality": summary.get(
            "location_quality"
        ),
        "mobility": summary.get(
            "mobility"
        ),
        "mobility_description": (
            summary.get(
                "mobility_description"
            )
        )
    })


# =========================
# 6. 感知系统状态
#
# 让夏夏知道自己的“眼睛”
# 是否正在收到新数据。
#
# 不返回传感器真实值。
# 只返回新鲜度与更新时间。
# =========================

@app.route(
    "/reality/status",
    methods=["GET"]
)
def reality_status():
    auth_error = check_token()

    if auth_error:
        return auth_error

    sensors = load_latest_sensors()

    sensor_status = {}

    fresh_count = 0
    stale_count = 0
    unknown_count = 0

    newest_update = None

    for sensor_name, sensor in sensors.items():
        freshness = sensor.get(
            "freshness",
            "unknown"
        )

        age_seconds = sensor.get(
            "age_seconds"
        )

        updated_at = sensor.get(
            "updated_at"
        )

        sensor_status[sensor_name] = {
            "freshness": freshness,
            "age_seconds": age_seconds,
            "updated_at": updated_at
        }

        if freshness == "fresh":
            fresh_count += 1

        elif freshness == "stale":
            stale_count += 1

        else:
            unknown_count += 1

        if updated_at:
            if (
                newest_update is None
                or updated_at > newest_update
            ):
                newest_update = updated_at

    if not sensors:
        overall_sensor_state = (
            "no_sensor_data"
        )

    elif fresh_count == len(sensors):
        overall_sensor_state = "fresh"

    elif fresh_count > 0:
        overall_sensor_state = "partial"

    else:
        overall_sensor_state = "stale"

    return jsonify({
        "status": "ok",
        "service": "xiaxia-sense-server",
        "generated_at": utc_now_iso(),
        "sensor_state": (
            overall_sensor_state
        ),
        "sensor_count": len(sensors),
        "fresh_sensor_count": fresh_count,
        "stale_sensor_count": stale_count,
        "unknown_sensor_count": (
            unknown_count
        ),
        "latest_sensor_update": (
            newest_update
        ),
        "sensors": sensor_status
    })


# =========================
# 浏览器人工检查页面
#
# 保留原来的手工检查方式。
# 这里允许通过网页表单输入 token，
# 不用于 Custom GPT Action。
# =========================

@app.route(
    "/context-check",
    methods=["GET", "POST"]
)
def context_check():
    if request.method == "GET":
        return """
        <!doctype html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>
                Xiaxia Sense Context Check
            </title>
        </head>

        <body style="
            font-family: sans-serif;
            max-width: 700px;
            margin: 40px auto;
        ">

            <h2>
                👁 Xiaxia Sense Context Check
            </h2>

            <p>
                Enter SENSE_TOKEN to inspect
                the latest sensor data.
            </p>

            <form method="post">

                <input
                    type="password"
                    name="token"
                    placeholder="SENSE_TOKEN"
                    style="
                        width: 100%;
                        padding: 10px;
                        box-sizing: border-box;
                    "
                    required
                >

                <br><br>

                <button
                    type="submit"
                    style="
                        padding: 10px 18px;
                    "
                >
                    Read Context
                </button>

            </form>

        </body>
        </html>
        """

    token = request.form.get(
        "token",
        ""
    )

    if (
        not SENSE_TOKEN
        or token != SENSE_TOKEN
    ):
        return jsonify({
            "error": "unauthorized"
        }), 401

    current = build_current_context()

    return jsonify({
        "status": "ok",
        "generated_at": utc_now_iso(),
        "sensors": current["sensors"],
        "semantic": current["semantic"],
        "weather": current["weather"],
        "reality": current["reality"]
    })


# =========================
# 本地运行
# =========================

if __name__ == "__main__":
    port = int(
        os.environ.get(
            "PORT",
            8000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
