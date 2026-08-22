import os
import json
import sqlite3
from datetime import datetime, timezone

from flask import Flask, request, jsonify


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


def freshness_info(sensor_name, updated_at):
    try:
        updated = datetime.fromisoformat(updated_at)

        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)

        age_seconds = max(
            0,
            int((datetime.now(timezone.utc) - updated).total_seconds())
        )

        threshold = FRESHNESS_THRESHOLDS.get(
            sensor_name,
            DEFAULT_FRESHNESS_SECONDS
        )

        return {
            "age_seconds": age_seconds,
            "freshness": "fresh" if age_seconds <= threshold else "stale"
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

    # 保存每一次 SensorLogger 上传的原始消息
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

    # 每种传感器只保存“目前最新的一条”
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
    """
    /data 和 /context 都需要 Bearer Token。
    正式部署时必须设置 SENSE_TOKEN 环境变量。
    """

    if not SENSE_TOKEN:
        return jsonify({
            "error": "server_not_configured",
            "message": "SENSE_TOKEN is not configured"
        }), 503

    auth = request.headers.get("Authorization", "")

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
# 健康检查
# =========================

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({
        "status": "ok",
        "service": "xiaxia-sense-server"
    })


# =========================
# SensorLogger 数据入口
# =========================

@app.route("/data", methods=["POST"])
def receive_data():
    auth_error = check_token()
    if auth_error:
        return auth_error

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "error": "invalid_json"
        }), 400

    message_id = data.get("messageId")
    session_id = data.get("sessionId")
    device_id = data.get("deviceId")
    payload = data.get("payload", [])

    received_at = datetime.now(timezone.utc).isoformat()

    conn = get_db()

    # 1. 保存完整原始消息
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
        json.dumps(data, ensure_ascii=False)
    ))

    updated_sensors = []

    # 2. 拆开 payload，把每种传感器最新状态保存下来
    if isinstance(payload, list):
        for reading in payload:

            if not isinstance(reading, dict):
                continue

            sensor_name = reading.get("name")
            sensor_time_ns = reading.get("time")
            values = reading.get("values", {})

            if not sensor_name:
                continue

            if not isinstance(sensor_time_ns, int):
                continue

            old = conn.execute("""
                SELECT sensor_time_ns
                FROM sensor_latest
                WHERE sensor_name = ?
            """, (sensor_name,)).fetchone()

            # SensorLogger 消息可能乱序到达。
            # 只有这条数据真的比数据库里的更新，才覆盖。
            if old is None or sensor_time_ns > old["sensor_time_ns"]:

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

                    ON CONFLICT(sensor_name) DO UPDATE SET
                        sensor_time_ns = excluded.sensor_time_ns,
                        values_json = excluded.values_json,
                        message_id = excluded.message_id,
                        session_id = excluded.session_id,
                        device_id = excluded.device_id,
                        updated_at = excluded.updated_at
                """, (
                    sensor_name,
                    sensor_time_ns,
                    json.dumps(values, ensure_ascii=False),
                    message_id,
                    session_id,
                    device_id,
                    received_at
                ))

                updated_sensors.append(sensor_name)

    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",
        "received": len(payload) if isinstance(payload, list) else 0,
        "updated_sensors": updated_sensors
    }), 200


# =========================
# 给林知夏读取的统一现实上下文
# =========================

@app.route("/context", methods=["GET"])
def context():
    auth_error = check_token()
    if auth_error:
        return auth_error

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

        sensors[sensor_name] = {
            "time_ns": row["sensor_time_ns"],
            "values": json.loads(row["values_json"]),
            "updated_at": row["updated_at"],
            "age_seconds": freshness["age_seconds"],
            "freshness": freshness["freshness"]
        }

    return jsonify({
        "status": "ok",
        "sensors": sensors
    })


# =========================
# 浏览器人工检查页面
# =========================

@app.route("/context-check", methods=["GET", "POST"])
def context_check():
    if request.method == "GET":
        return """
        <!doctype html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Xiaxia Sense Context Check</title>
        </head>
        <body style="font-family: sans-serif; max-width: 700px; margin: 40px auto;">
            <h2>👁 Xiaxia Sense Context Check</h2>
            <p>Enter SENSE_TOKEN to inspect the latest sensor data.</p>

            <form method="post">
                <input
                    type="password"
                    name="token"
                    placeholder="SENSE_TOKEN"
                    style="width: 100%; padding: 10px; box-sizing: border-box;"
                    required
                >
                <br><br>
                <button type="submit" style="padding: 10px 18px;">
                    Read Context
                </button>
            </form>
        </body>
        </html>
        """

    token = request.form.get("token", "")

    if not SENSE_TOKEN or token != SENSE_TOKEN:
        return jsonify({
            "error": "unauthorized"
        }), 401

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

        sensors[sensor_name] = {
            "time_ns": row["sensor_time_ns"],
            "values": json.loads(row["values_json"]),
            "updated_at": row["updated_at"],
            "age_seconds": freshness["age_seconds"],
            "freshness": freshness["freshness"]
        }

    return jsonify({
        "status": "ok",
        "sensors": sensors
    })


# =========================
# 本地运行
# =========================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(
        host="0.0.0.0",
        port=port
    )
