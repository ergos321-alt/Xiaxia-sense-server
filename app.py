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

DB_PATH = os.path.join(
    DATA_DIR,
    "xiaxia_sense.db"
)


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

PHONE_ACTIVITY_FRESH_SECONDS = 43200


# =========================
# 时间工具
# =========================

def utc_now_iso():
    return datetime.now(
        timezone.utc
    ).isoformat()


def utc_now_epoch():
    return int(
        datetime.now(
            timezone.utc
        ).timestamp()
    )


def epoch_to_iso(epoch_value):
    if not isinstance(
        epoch_value,
        int
    ):
        return None

    try:
        return datetime.fromtimestamp(
            epoch_value,
            tz=timezone.utc
        ).isoformat()

    except Exception:
        return None


# =========================
# 新鲜度
# =========================

def freshness_info(
    sensor_name,
    updated_at
):
    try:
        updated = datetime.fromisoformat(
            updated_at
        )

        if updated.tzinfo is None:
            updated = updated.replace(
                tzinfo=timezone.utc
            )

        age_seconds = max(
            0,
            int(
                (
                    datetime.now(
                        timezone.utc
                    )
                    - updated
                ).total_seconds()
            )
        )

        threshold = (
            FRESHNESS_THRESHOLDS.get(
                sensor_name,
                DEFAULT_FRESHNESS_SECONDS
            )
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


def phone_freshness_info(
    updated_at
):
    try:
        updated = datetime.fromisoformat(
            updated_at
        )

        if updated.tzinfo is None:
            updated = updated.replace(
                tzinfo=timezone.utc
            )

        age_seconds = max(
            0,
            int(
                (
                    datetime.now(
                        timezone.utc
                    )
                    - updated
                ).total_seconds()
            )
        )

        return {
            "age_seconds": age_seconds,
            "freshness": (
                "fresh"
                if age_seconds
                <= PHONE_ACTIVITY_FRESH_SECONDS
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
    conn = sqlite3.connect(
        DB_PATH
    )

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

    conn.execute("""
        CREATE TABLE IF NOT EXISTS phone_activity_latest (
            id INTEGER PRIMARY KEY
                CHECK (id = 1),

            screen TEXT,
            locked TEXT,

            last_interaction INTEGER,

            app_name TEXT,
            app_package TEXT,
            app_since INTEGER,

            updated_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS phone_activity_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            event_type TEXT NOT NULL,

            screen TEXT,
            locked TEXT,

            app_name TEXT,
            app_package TEXT,

            event_time INTEGER NOT NULL,
            received_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_phone_activity_events_time

        ON phone_activity_events (
            event_time
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

    if not auth.startswith(
        "Bearer "
    ):
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
# Sensor 数据读取
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
        sensor_name = (
            row["sensor_name"]
        )

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
            "time_ns": (
                row["sensor_time_ns"]
            ),
            "values": values,
            "updated_at": (
                row["updated_at"]
            ),
            "age_seconds": (
                freshness[
                    "age_seconds"
                ]
            ),
            "freshness": (
                freshness[
                    "freshness"
                ]
            )
        }

    return sensors


# =========================
# Phone Activity
# 事件读取
# =========================

def load_recent_phone_events(
    minutes=60,
    limit=100
):
    now_epoch = utc_now_epoch()

    cutoff = (
        now_epoch
        - minutes * 60
    )

    conn = get_db()

    rows = conn.execute("""
        SELECT
            event_type,
            screen,
            locked,
            app_name,
            app_package,
            event_time,
            received_at

        FROM phone_activity_events

        WHERE event_time >= ?

        ORDER BY event_time DESC

        LIMIT ?
    """, (
        cutoff,
        limit
    )).fetchall()

    conn.close()

    events = []

    for row in rows:
        locked_value = (
            row["locked"]
        )

        if locked_value == "true":
            locked = True

        elif locked_value == "false":
            locked = False

        else:
            locked = None

        events.append({
            "event_type": (
                row["event_type"]
            ),
            "screen": (
                row["screen"]
            ),
            "locked": locked,
            "app_name": (
                row["app_name"]
            ),
            "app_package": (
                row["app_package"]
            ),
            "event_time": (
                row["event_time"]
            ),
            "event_at": (
                epoch_to_iso(
                    row["event_time"]
                )
            ),
            "received_at": (
                row["received_at"]
            )
        })

    return events


# =========================
# 当前屏幕状态持续时间
# =========================

def get_screen_state_duration(
    current_screen
):
    if current_screen not in (
        "on",
        "off"
    ):
        return {
            "seconds": None,
            "minutes": None
        }

    conn = get_db()

    event_type = (
        "screen_on"
        if current_screen == "on"
        else "screen_off"
    )

    row = conn.execute("""
        SELECT event_time

        FROM phone_activity_events

        WHERE event_type = ?

        ORDER BY event_time DESC

        LIMIT 1
    """, (
        event_type,
    )).fetchone()

    conn.close()

    if row is None:
        return {
            "seconds": None,
            "minutes": None
        }

    seconds = max(
        0,
        utc_now_epoch()
        - row["event_time"]
    )

    return {
        "seconds": seconds,
        "minutes": seconds // 60
    }


# =========================
# Timeline 整理
# =========================

def build_phone_timeline(
    minutes=60,
    limit=20
):
    raw_events = (
        load_recent_phone_events(
            minutes=minutes,
            limit=100
        )
    )

    timeline = []

    for event in reversed(
        raw_events
    ):
        event_type = event.get(
            "event_type"
        )

        item = {
            "event": event_type,
            "at": event.get(
                "event_at"
            )
        }

        if event_type == "app_changed":
            item["app_name"] = (
                event.get(
                    "app_name"
                )
            )

            item["package_name"] = (
                event.get(
                    "app_package"
                )
            )

        elif event_type in (
            "screen_on",
            "screen_off",
            "unlock",
            "lock"
        ):
            item["screen"] = (
                event.get(
                    "screen"
                )
            )

            item["locked"] = (
                event.get(
                    "locked"
                )
            )

        timeline.append(
            item
        )

    return timeline[
        -limit:
    ]


# =========================
# 最近使用过的 App
#
# 这里只做简短列表。
# V1 不做完整使用时长统计。
# =========================

def build_recent_apps(
    minutes=60,
    limit=5
):
    events = (
        load_recent_phone_events(
            minutes=minutes,
            limit=100
        )
    )

    seen = set()
    recent_apps = []

    for event in events:
        if (
            event.get(
                "event_type"
            )
            != "app_changed"
        ):
            continue

        package_name = event.get(
            "app_package"
        )

        app_name = event.get(
            "app_name"
        )

        if not package_name:
            continue

        if package_name in seen:
            continue

        seen.add(
            package_name
        )

        recent_apps.append({
            "app_name": app_name,
            "package_name": (
                package_name
            ),
            "last_seen_at": (
                event.get(
                    "event_at"
                )
            )
        })

        if (
            len(recent_apps)
            >= limit
        ):
            break

    return recent_apps


# =========================
# Phone Activity Summary
#
# 这里只总结手机事实状态。
# 不判断用户：
# 睡着 / 偷懒 / 工作 /
# 撒谎 / 需要什么。
# =========================

def build_phone_activity_summary(
    phone_activity
):
    if not phone_activity:
        return {
            "state": "unknown",
            "description": (
                "当前没有可用的手机活动数据。"
            ),
            "confidence": "low"
        }

    screen = phone_activity.get(
        "screen"
    )

    locked = phone_activity.get(
        "locked"
    )

    inactive_minutes = (
        phone_activity.get(
            "inactive_for_minutes"
        )
    )

    app_name = (
        phone_activity.get(
            "current_app",
            {}
        ).get(
            "app_name"
        )
    )

    app_duration = (
        phone_activity.get(
            "current_app",
            {}
        ).get(
            "duration_minutes"
        )
    )

    freshness = (
        phone_activity.get(
            "freshness"
        )
    )

    if freshness != "fresh":
        return {
            "state": "unknown",
            "description": (
                "手机活动数据已经过期，"
                "无法可靠描述当前状态。"
            ),
            "confidence": "low"
        }

    if (
        screen == "off"
        and locked is True
    ):
        if inactive_minutes is not None:
            description = (
                f"手机已锁屏，"
                f"最近一次交互约在"
                f"{inactive_minutes}分钟前。"
            )

        else:
            description = (
                "手机当前已锁屏。"
            )

        return {
            "state": "inactive",
            "description": description,
            "confidence": "high"
        }

    if (
        screen == "on"
        and locked is True
    ):
        return {
            "state": "screen_on_locked",
            "description": (
                "手机屏幕已亮起，"
                "但设备当前仍处于锁定状态。"
            ),
            "confidence": "high"
        }

    if (
        screen == "on"
        and locked is False
    ):
        if app_name:
            if (
                app_duration
                is not None
            ):
                description = (
                    f"手机当前处于解锁状态，"
                    f"前台应用为 {app_name}，"
                    f"已持续约 {app_duration} 分钟。"
                )

            else:
                description = (
                    f"手机当前处于解锁状态，"
                    f"前台应用为 {app_name}。"
                )

        else:
            description = (
                "手机当前处于解锁并活跃状态。"
            )

        return {
            "state": "active",
            "description": description,
            "confidence": "high"
        }

    return {
        "state": "unknown",
        "description": (
            "手机状态信息不完整。"
        ),
        "confidence": "medium"
    }


# =========================
# Phone Activity 当前状态
# =========================

def load_phone_activity():
    conn = get_db()

    row = conn.execute("""
        SELECT
            screen,
            locked,
            last_interaction,
            app_name,
            app_package,
            app_since,
            updated_at

        FROM phone_activity_latest

        WHERE id = 1
    """).fetchone()

    conn.close()

    if row is None:
        return {}

    freshness = (
        phone_freshness_info(
            row["updated_at"]
        )
    )

    now_epoch = utc_now_epoch()

    last_interaction = (
        row["last_interaction"]
    )

    app_since = row["app_since"]

    inactive_for_seconds = None
    inactive_for_minutes = None

    if isinstance(
        last_interaction,
        int
    ):
        inactive_for_seconds = max(
            0,
            now_epoch
            - last_interaction
        )

        inactive_for_minutes = (
            inactive_for_seconds
            // 60
        )

    app_duration_seconds = None
    app_duration_minutes = None

    if isinstance(
        app_since,
        int
    ):
        app_duration_seconds = max(
            0,
            now_epoch
            - app_since
        )

        app_duration_minutes = (
            app_duration_seconds
            // 60
        )

    locked_value = row["locked"]

    if locked_value == "true":
        locked = True

    elif locked_value == "false":
        locked = False

    else:
        locked = None

    screen_duration = (
        get_screen_state_duration(
            row["screen"]
        )
    )

    current_app = None

    if (
        row["screen"] == "on"
        and locked is False
        and row["app_name"]
    ):
        current_app = {
            "app_name": (
                row["app_name"]
            ),

            "package_name": (
                row["app_package"]
            ),

            "started_at": (
                epoch_to_iso(
                    app_since
                )
            ),

            "duration_seconds": (
                app_duration_seconds
            ),

            "duration_minutes": (
                app_duration_minutes
            )
        }

    return {
        "screen": row["screen"],

        "locked": locked,

        "screen_state_duration_seconds": (
            screen_duration[
                "seconds"
            ]
        ),

        "screen_state_duration_minutes": (
            screen_duration[
                "minutes"
            ]
        ),

        "last_interaction": (
            last_interaction
        ),

        "last_interaction_at": (
            epoch_to_iso(
                last_interaction
            )
        ),

        "inactive_for_seconds": (
            inactive_for_seconds
        ),

        "inactive_for_minutes": (
            inactive_for_minutes
        ),

        "current_app": (
            current_app
        ),

        "recent_apps": (
            build_recent_apps(
                minutes=60,
                limit=5
            )
        ),

        "recent_timeline": (
            build_phone_timeline(
                minutes=60,
                limit=20
            )
        ),

        "last_updated": (
            row["updated_at"]
        ),

        "age_seconds": (
            freshness[
                "age_seconds"
            ]
        ),

        "freshness": (
            freshness[
                "freshness"
            ]
        )
    }


# =========================
# 当前完整上下文
# =========================

def build_current_context():
    sensors = load_latest_sensors()

    semantic = (
        build_semantic_context(
            sensors
        )
    )

    weather = (
        build_weather_context(
            semantic
        )
    )

    reality = (
        build_reality_context(
            semantic,
            weather
        )
    )

    phone_activity = (
        load_phone_activity()
    )

    phone_activity_summary = (
        build_phone_activity_summary(
            phone_activity
        )
    )

    return {
        "sensors": sensors,
        "semantic": semantic,
        "weather": weather,
        "reality": reality,
        "phone_activity": (
            phone_activity
        ),
        "phone_activity_summary": (
            phone_activity_summary
        )
    }


# =========================
# 健康检查
# =========================

@app.route(
    "/ping",
    methods=["GET"]
)
def ping():
    return jsonify({
        "status": "ok",
        "service": (
            "xiaxia-sense-server"
        ),
        "generated_at": (
            utc_now_iso()
        )
    })


# =========================
# SensorLogger 数据入口
# =========================

@app.route(
    "/data",
    methods=["POST"]
)
def receive_data():
    auth_error = check_token()

    if auth_error:
        return auth_error

    data = request.get_json(
        silent=True
    )

    if not isinstance(
        data,
        dict
    ):
        return jsonify({
            "error": "invalid_json"
        }), 400

    message_id = data.get(
        "messageId"
    )

    session_id = data.get(
        "sessionId"
    )

    device_id = data.get(
        "deviceId"
    )

    payload = data.get(
        "payload",
        []
    )

    received_at = (
        utc_now_iso()
    )

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

    if isinstance(
        payload,
        list
    ):
        for reading in payload:

            if not isinstance(
                reading,
                dict
            ):
                continue

            sensor_name = (
                reading.get(
                    "name"
                )
            )

            sensor_time_ns = (
                reading.get(
                    "time"
                )
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
                > old[
                    "sensor_time_ns"
                ]
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

                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?
                    )

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
            if isinstance(
                payload,
                list
            )
            else 0
        ),

        "updated_sensors": (
            updated_sensors
        )
    }), 200


# =========================
# Tasker Phone Activity 数据入口
# =========================

@app.route(
    "/phone/activity",
    methods=["POST"]
)
def receive_phone_activity():
    auth_error = check_token()

    if auth_error:
        return auth_error

    data = request.get_json(
        silent=True
    )

    if not isinstance(
        data,
        dict
    ):
        return jsonify({
            "error": "invalid_json"
        }), 400

    screen = data.get(
        "screen"
    )

    locked = data.get(
        "locked"
    )

    last_interaction = (
        data.get(
            "last_interaction"
        )
    )

    app_name = data.get(
        "app_name"
    )

    app_package = data.get(
        "app_package"
    )

    app_since = data.get(
        "app_since"
    )

    if screen not in (
        "on",
        "off"
    ):
        screen = None

    if isinstance(
        locked,
        bool
    ):
        locked = (
            "true"
            if locked
            else "false"
        )

    elif isinstance(
        locked,
        str
    ):
        locked = (
            locked
            .strip()
            .lower()
        )

        if locked not in (
            "true",
            "false"
        ):
            locked = None

    else:
        locked = None

    try:
        last_interaction = int(
            last_interaction
        )

    except Exception:
        last_interaction = None

    try:
        app_since = int(
            app_since
        )

    except Exception:
        app_since = None

    received_at = (
        utc_now_iso()
    )

    event_time = (
        utc_now_epoch()
    )

    conn = get_db()

    old = conn.execute("""
        SELECT
            screen,
            locked,
            last_interaction,
            app_name,
            app_package,
            app_since

        FROM phone_activity_latest

        WHERE id = 1
    """).fetchone()

    event_type = "update"

    if old is None:
        event_type = "initial"

    elif (
        old["screen"]
        != screen
    ):
        if screen == "on":
            event_type = (
                "screen_on"
            )

        elif screen == "off":
            event_type = (
                "screen_off"
            )

    elif (
        old["locked"]
        != locked
    ):
        if locked == "false":
            event_type = "unlock"

        elif locked == "true":
            event_type = "lock"

    elif (
        old["app_package"]
        != app_package
    ):
        event_type = (
            "app_changed"
        )

    elif (
        old["last_interaction"]
        != last_interaction
    ):
        event_type = (
            "interaction"
        )

    conn.execute("""
        INSERT INTO
        phone_activity_latest (
            id,
            screen,
            locked,
            last_interaction,
            app_name,
            app_package,
            app_since,
            updated_at
        )

        VALUES (
            1,
            ?, ?, ?, ?, ?, ?, ?
        )

        ON CONFLICT(id)

        DO UPDATE SET
            screen =
                excluded.screen,

            locked =
                excluded.locked,

            last_interaction =
                excluded.last_interaction,

            app_name =
                excluded.app_name,

            app_package =
                excluded.app_package,

            app_since =
                excluded.app_since,

            updated_at =
                excluded.updated_at
    """, (
        screen,
        locked,
        last_interaction,
        app_name,
        app_package,
        app_since,
        received_at
    ))

    if event_type != "update":
        conn.execute("""
            INSERT INTO
            phone_activity_events (
                event_type,
                screen,
                locked,
                app_name,
                app_package,
                event_time,
                received_at
            )

            VALUES (
                ?, ?, ?, ?, ?, ?, ?
            )
        """, (
            event_type,
            screen,
            locked,
            app_name,
            app_package,
            event_time,
            received_at
        ))

    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",
        "event_type": (
            event_type
        ),
        "received_at": (
            received_at
        )
    }), 200


# =========================
# 完整调试 Context
# =========================

@app.route(
    "/context",
    methods=["GET"]
)
def context():
    auth_error = check_token()

    if auth_error:
        return auth_error

    current = (
        build_current_context()
    )

    return jsonify({
        "status": "ok",

        "generated_at": (
            utc_now_iso()
        ),

        "sensors": (
            current["sensors"]
        ),

        "semantic": (
            current["semantic"]
        ),

        "weather": (
            current["weather"]
        ),

        "reality": (
            current["reality"]
        ),

        "phone_activity": (
            current[
                "phone_activity"
            ]
        ),

        "phone_activity_summary": (
            current[
                "phone_activity_summary"
            ]
        )
    })


# =========================
# Reality Context
# =========================

@app.route(
    "/reality/context",
    methods=["GET"]
)
def reality_context():
    auth_error = check_token()

    if auth_error:
        return auth_error

    current = (
        build_current_context()
    )

    return jsonify({
        "status": "ok",

        "generated_at": (
            utc_now_iso()
        ),

        "reality": (
            current["reality"]
        ),

        "phone_activity": (
            current[
                "phone_activity"
            ]
        ),

        "phone_activity_summary": (
            current[
                "phone_activity_summary"
            ]
        )
    })


# =========================
# Reality Summary
# =========================

@app.route(
    "/reality/summary",
    methods=["GET"]
)
def reality_summary():
    auth_error = check_token()

    if auth_error:
        return auth_error

    current = (
        build_current_context()
    )

    reality = current[
        "reality"
    ]

    return jsonify({
        "status": "ok",

        "generated_at": (
            utc_now_iso()
        ),

        "summary": (
            reality.get(
                "summary",
                {}
            )
        ),

        "inferences": (
            reality.get(
                "inferences",
                {}
            )
        ),

        "phone_activity_summary": (
            current[
                "phone_activity_summary"
            ]
        )
    })


# =========================
# 环境 Reality
# =========================

@app.route(
    "/reality/environment",
    methods=["GET"]
)
def reality_environment():
    auth_error = check_token()

    if auth_error:
        return auth_error

    current = (
        build_current_context()
    )

    reality = current[
        "reality"
    ]

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
        value = summary.get(
            key
        )

        if value is not None:
            relevant_summary[
                key
            ] = value

    return jsonify({
        "status": "ok",

        "generated_at": (
            utc_now_iso()
        ),

        "environment": (
            reality.get(
                "environment",
                {}
            )
        ),

        "weather": (
            reality.get(
                "weather",
                {}
            )
        ),

        "summary": (
            relevant_summary
        )
    })


# =========================
# Device Reality
# =========================

@app.route(
    "/reality/device",
    methods=["GET"]
)
def reality_device():
    auth_error = check_token()

    if auth_error:
        return auth_error

    current = (
        build_current_context()
    )

    reality = current[
        "reality"
    ]

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
        value = summary.get(
            key
        )

        if value is not None:
            relevant_summary[
                key
            ] = value

    return jsonify({
        "status": "ok",

        "generated_at": (
            utc_now_iso()
        ),

        "device": (
            reality.get(
                "device",
                {}
            )
        ),

        "network": (
            reality.get(
                "network",
                {}
            )
        ),

        "summary": (
            relevant_summary
        )
    })


# =========================
# Location Reality
# =========================

@app.route(
    "/reality/location",
    methods=["GET"]
)
def reality_location():
    auth_error = check_token()

    if auth_error:
        return auth_error

    current = (
        build_current_context()
    )

    reality = current[
        "reality"
    ]

    summary = reality.get(
        "summary",
        {}
    )

    return jsonify({
        "status": "ok",

        "generated_at": (
            utc_now_iso()
        ),

        "location": (
            reality.get(
                "location",
                {}
            )
        ),

        "location_quality": (
            summary.get(
                "location_quality"
            )
        ),

        "mobility": (
            summary.get(
                "mobility"
            )
        ),

        "mobility_description": (
            summary.get(
                "mobility_description"
            )
        )
    })


# =========================
# Phone Activity Reality
# =========================

@app.route(
    "/reality/phone",
    methods=["GET"]
)
def reality_phone():
    auth_error = check_token()

    if auth_error:
        return auth_error

    current = (
        build_current_context()
    )

    return jsonify({
        "status": "ok",

        "generated_at": (
            utc_now_iso()
        ),

        "phone_activity": (
            current[
                "phone_activity"
            ]
        ),

        "phone_activity_summary": (
            current[
                "phone_activity_summary"
            ]
        )
    })


# =========================
# Phone Activity Timeline
# =========================

@app.route(
    "/reality/phone/timeline",
    methods=["GET"]
)
def reality_phone_timeline():
    auth_error = check_token()

    if auth_error:
        return auth_error

    try:
        minutes = int(
            request.args.get(
                "minutes",
                60
            )
        )

    except Exception:
        minutes = 60

    minutes = max(
        1,
        min(
            minutes,
            1440
        )
    )

    timeline = (
        build_phone_timeline(
            minutes=minutes,
            limit=100
        )
    )

    return jsonify({
        "status": "ok",

        "generated_at": (
            utc_now_iso()
        ),

        "window_minutes": (
            minutes
        ),

        "event_count": (
            len(timeline)
        ),

        "timeline": (
            timeline
        )
    })


# =========================
# Reality Status
# =========================

@app.route(
    "/reality/status",
    methods=["GET"]
)
def reality_status():
    auth_error = check_token()

    if auth_error:
        return auth_error

    sensors = (
        load_latest_sensors()
    )

    sensor_status = {}

    fresh_count = 0
    stale_count = 0
    unknown_count = 0

    newest_update = None

    for (
        sensor_name,
        sensor
    ) in sensors.items():

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

        sensor_status[
            sensor_name
        ] = {
            "freshness": (
                freshness
            ),
            "age_seconds": (
                age_seconds
            ),
            "updated_at": (
                updated_at
            )
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
                or updated_at
                > newest_update
            ):
                newest_update = (
                    updated_at
                )

    if not sensors:
        overall_sensor_state = (
            "no_sensor_data"
        )

    elif (
        fresh_count
        == len(sensors)
    ):
        overall_sensor_state = (
            "fresh"
        )

    elif fresh_count > 0:
        overall_sensor_state = (
            "partial"
        )

    else:
        overall_sensor_state = (
            "stale"
        )

    phone_activity = (
        load_phone_activity()
    )

    return jsonify({
        "status": "ok",

        "service": (
            "xiaxia-sense-server"
        ),

        "generated_at": (
            utc_now_iso()
        ),

        "sensor_state": (
            overall_sensor_state
        ),

        "sensor_count": (
            len(sensors)
        ),

        "fresh_sensor_count": (
            fresh_count
        ),

        "stale_sensor_count": (
            stale_count
        ),

        "unknown_sensor_count": (
            unknown_count
        ),

        "latest_sensor_update": (
            newest_update
        ),

        "sensors": (
            sensor_status
        ),

        "phone_activity_status": {
            "available": bool(
                phone_activity
            ),

            "freshness": (
                phone_activity.get(
                    "freshness"
                )
                if phone_activity
                else "unknown"
            ),

            "age_seconds": (
                phone_activity.get(
                    "age_seconds"
                )
                if phone_activity
                else None
            ),

            "updated_at": (
                phone_activity.get(
                    "last_updated"
                )
                if phone_activity
                else None
            )
        }
    })


# =========================
# Context 浏览器检查
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
                the latest Reality and
                Phone Activity data.
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

    current = (
        build_current_context()
    )

    return jsonify({
        "status": "ok",

        "generated_at": (
            utc_now_iso()
        ),

        "sensors": (
            current["sensors"]
        ),

        "semantic": (
            current["semantic"]
        ),

        "weather": (
            current["weather"]
        ),

        "reality": (
            current["reality"]
        ),

        "phone_activity": (
            current[
                "phone_activity"
            ]
        ),

        "phone_activity_summary": (
            current[
                "phone_activity_summary"
            ]
        )
    })


# =========================
# Timeline 浏览器检查
# =========================

@app.route(
    "/phone-timeline-check",
    methods=["GET", "POST"]
)
def phone_timeline_check():
    if request.method == "GET":
        return """
        <!doctype html>
        <html>

        <head>
            <meta charset="utf-8">

            <title>
                Xiaxia Phone Timeline Check
            </title>
        </head>

        <body style="
            font-family: sans-serif;
            max-width: 700px;
            margin: 40px auto;
        ">

            <h2>
                📱 Xiaxia Phone Timeline Check
            </h2>

            <p>
                Enter SENSE_TOKEN to inspect
                recent phone activity.
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

                <label>
                    Minutes:
                </label>

                <input
                    type="number"
                    name="minutes"
                    value="10"
                    min="1"
                    max="1440"
                    style="
                        width: 100%;
                        padding: 10px;
                        box-sizing: border-box;
                    "
                >

                <br><br>

                <button
                    type="submit"
                    style="
                        padding: 10px 18px;
                    "
                >
                    Read Timeline
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

    try:
        minutes = int(
            request.form.get(
                "minutes",
                10
            )
        )

    except Exception:
        minutes = 10

    minutes = max(
        1,
        min(
            minutes,
            1440
        )
    )

    timeline = (
        build_phone_timeline(
            minutes=minutes,
            limit=100
        )
    )

    return jsonify({
        "status": "ok",

        "generated_at": (
            utc_now_iso()
        ),

        "window_minutes": (
            minutes
        ),

        "event_count": (
            len(timeline)
        ),

        "timeline": (
            timeline
        )
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
