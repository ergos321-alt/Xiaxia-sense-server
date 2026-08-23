import os
import json
from datetime import datetime, timezone, timedelta

import psycopg
from psycopg.rows import dict_row

from flask import Flask, request, jsonify

from semantic import build_semantic_context
from weather import build_weather_context
from reality import build_reality_context

from spatial import (
    haversine_m,
    convert_gps_to_amap,
    reverse_geocode,
    nearby_search,
    route as amap_route,
    classify_scene,
    build_spatial_description,
    analyze_movement
)


app = Flask(__name__)


# =========================
# 基础配置
# =========================

SENSE_TOKEN = os.environ.get(
    "SENSE_TOKEN",
    ""
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    ""
)

AMAP_KEY = os.environ.get(
    "AMAP_KEY",
    ""
).strip()


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
# Housekeeping
# =========================

MESSAGE_RETENTION_SECONDS = (
    6 * 60 * 60
)

PHONE_EVENT_RETENTION_SECONDS = (
    48 * 60 * 60
)

SPATIAL_HISTORY_RETENTION_SECONDS = (
    48 * 60 * 60
)

HOUSEKEEPING_INTERVAL_SECONDS = (
    10 * 60
)

SPATIAL_SAMPLE_MIN_INTERVAL_SECONDS = 60
SPATIAL_SAMPLE_MIN_DISTANCE_M = 30

_last_housekeeping_epoch = 0


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
# PostgreSQL 包装
# =========================

class DatabaseConnection:

    def __init__(
        self,
        connection
    ):
        self.connection = connection

    def execute(
        self,
        query,
        params=None
    ):
        postgres_query = (
            query.replace(
                "?",
                "%s"
            )
        )

        if params is None:
            params = ()

        return self.connection.execute(
            postgres_query,
            params
        )

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


# =========================
# 数据库
# =========================

def get_db():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not configured"
        )

    raw_conn = psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        sslmode="require",
        connect_timeout=10
    )

    conn = DatabaseConnection(
        raw_conn
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id BIGSERIAL PRIMARY KEY,
            message_id BIGINT,
            session_id TEXT,
            device_id TEXT,
            received_at TEXT NOT NULL,
            raw_json TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_messages_received_at
        ON messages (received_at)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sensor_latest (
            sensor_name TEXT PRIMARY KEY,
            sensor_time_ns BIGINT NOT NULL,
            values_json TEXT NOT NULL,
            message_id BIGINT,
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

            last_interaction BIGINT,

            app_name TEXT,
            app_package TEXT,
            app_since BIGINT,

            updated_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS phone_activity_events (
            id BIGSERIAL PRIMARY KEY,

            event_type TEXT NOT NULL,

            screen TEXT,
            locked TEXT,

            app_name TEXT,
            app_package TEXT,

            event_time BIGINT NOT NULL,
            received_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_phone_activity_events_time
        ON phone_activity_events (event_time)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS spatial_history (
            id BIGSERIAL PRIMARY KEY,

            latitude DOUBLE PRECISION NOT NULL,
            longitude DOUBLE PRECISION NOT NULL,

            accuracy_m DOUBLE PRECISION,
            speed_m_s DOUBLE PRECISION,

            recorded_at BIGINT NOT NULL,
            received_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_spatial_history_recorded_at
        ON spatial_history (recorded_at)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS personal_places (
            id BIGSERIAL PRIMARY KEY,

            name TEXT UNIQUE NOT NULL,
            kind TEXT,

            latitude DOUBLE PRECISION NOT NULL,
            longitude DOUBLE PRECISION NOT NULL,

            radius_m DOUBLE PRECISION NOT NULL
                DEFAULT 150,

            note TEXT,

            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    conn.commit()

    return conn


# =========================
# Housekeeping
# =========================

def run_housekeeping(
    conn,
    force=False
):
    global _last_housekeeping_epoch

    now_epoch = utc_now_epoch()

    if (
        not force
        and _last_housekeeping_epoch
        and (
            now_epoch
            - _last_housekeeping_epoch
        ) < HOUSEKEEPING_INTERVAL_SECONDS
    ):
        return

    message_cutoff = (
        datetime.now(
            timezone.utc
        )
        - timedelta(
            seconds=
            MESSAGE_RETENTION_SECONDS
        )
    ).isoformat()

    phone_event_cutoff = (
        now_epoch
        - PHONE_EVENT_RETENTION_SECONDS
    )

    spatial_cutoff = (
        now_epoch
        - SPATIAL_HISTORY_RETENTION_SECONDS
    )

    conn.execute("""
        DELETE FROM messages
        WHERE received_at < ?
    """, (
        message_cutoff,
    ))

    conn.execute("""
        DELETE FROM phone_activity_events
        WHERE event_time < ?
    """, (
        phone_event_cutoff,
    ))

    conn.execute("""
        DELETE FROM spatial_history
        WHERE recorded_at < ?
    """, (
        spatial_cutoff,
    ))

    _last_housekeeping_epoch = (
        now_epoch
    )


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

        sensors[
            sensor_name
        ] = {
            "time_ns": (
                row[
                    "sensor_time_ns"
                ]
            ),
            "values": values,
            "updated_at": (
                row[
                    "updated_at"
                ]
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
        "minutes": (
            seconds // 60
        )
    }


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
            "event": (
                event_type
            ),
            "at": (
                event.get(
                    "event_at"
                )
            )
        }

        if event_type == (
            "app_changed"
        ):
            item[
                "app_name"
            ] = event.get(
                "app_name"
            )

            item[
                "package_name"
            ] = event.get(
                "app_package"
            )

        elif event_type in (
            "screen_on",
            "screen_off",
            "unlock",
            "lock"
        ):
            item[
                "screen"
            ] = event.get(
                "screen"
            )

            item[
                "locked"
            ] = event.get(
                "locked"
            )

        timeline.append(
            item
        )

    return timeline[
        -limit:
    ]


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

        package_name = (
            event.get(
                "app_package"
            )
        )

        app_name = (
            event.get(
                "app_name"
            )
        )

        if not package_name:
            continue

        if package_name in seen:
            continue

        seen.add(
            package_name
        )

        recent_apps.append({
            "app_name": (
                app_name
            ),
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
            len(
                recent_apps
            )
            >= limit
        ):
            break

    return recent_apps


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

    screen = (
        phone_activity.get(
            "screen"
        )
    )

    locked = (
        phone_activity.get(
            "locked"
        )
    )

    inactive_minutes = (
        phone_activity.get(
            "inactive_for_minutes"
        )
    )

    current_app = (
        phone_activity.get(
            "current_app"
        )
        or {}
    )

    app_name = (
        current_app.get(
            "app_name"
        )
    )

    app_duration = (
        current_app.get(
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
        if (
            inactive_minutes
            is not None
        ):
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
            "state": (
                "screen_on_locked"
            ),
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

    now_epoch = (
        utc_now_epoch()
    )

    last_interaction = (
        row[
            "last_interaction"
        ]
    )

    app_since = (
        row[
            "app_since"
        ]
    )

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

    locked_value = (
        row["locked"]
    )

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
        "screen": (
            row["screen"]
        ),

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

        "current_app": current_app,

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
# Spatial Reality
# =========================

def latest_location_from_semantic(
    semantic
):
    location = (
        semantic.get(
            "location"
        )
    )

    if not isinstance(
        location,
        dict
    ):
        return None

    latitude = (
        location.get(
            "latitude"
        )
    )

    longitude = (
        location.get(
            "longitude"
        )
    )

    if not isinstance(
        latitude,
        (int, float)
    ):
        return None

    if not isinstance(
        longitude,
        (int, float)
    ):
        return None

    return {
        "latitude": float(
            latitude
        ),
        "longitude": float(
            longitude
        ),
        "accuracy_m": (
            location.get(
                "accuracy_m"
            )
        ),
        "speed_m_s": (
            location.get(
                "speed_m_s"
            )
        )
    }


def get_activity_state(
    semantic
):
    activity = (
        semantic.get(
            "activity"
        )
    )

    if not isinstance(
        activity,
        dict
    ):
        return None

    return activity.get(
        "state"
    )


def record_spatial_sample(
    conn,
    latitude,
    longitude,
    accuracy_m=None,
    speed_m_s=None,
    recorded_at=None,
    received_at=None
):
    if recorded_at is None:
        recorded_at = (
            utc_now_epoch()
        )

    if received_at is None:
        received_at = (
            utc_now_iso()
        )

    last = conn.execute("""
        SELECT
            latitude,
            longitude,
            recorded_at

        FROM spatial_history

        ORDER BY recorded_at DESC

        LIMIT 1
    """).fetchone()

    should_insert = True

    if last is not None:
        time_gap = max(
            0,
            recorded_at
            - last[
                "recorded_at"
            ]
        )

        distance = (
            haversine_m(
                last[
                    "latitude"
                ],
                last[
                    "longitude"
                ],
                latitude,
                longitude
            )
        )

        if (
            time_gap
            < SPATIAL_SAMPLE_MIN_INTERVAL_SECONDS
            and isinstance(
                distance,
                (int, float)
            )
            and distance
            < SPATIAL_SAMPLE_MIN_DISTANCE_M
        ):
            should_insert = False

    if should_insert:
        conn.execute("""
            INSERT INTO spatial_history (
                latitude,
                longitude,
                accuracy_m,
                speed_m_s,
                recorded_at,
                received_at
            )

            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            latitude,
            longitude,
            accuracy_m,
            speed_m_s,
            recorded_at,
            received_at
        ))

    return should_insert


def load_spatial_history(
    minutes=30,
    limit=200
):
    now_epoch = (
        utc_now_epoch()
    )

    cutoff = (
        now_epoch
        - minutes * 60
    )

    conn = get_db()

    rows = conn.execute("""
        SELECT
            latitude,
            longitude,
            accuracy_m,
            speed_m_s,
            recorded_at,
            received_at

        FROM spatial_history

        WHERE recorded_at >= ?

        ORDER BY recorded_at ASC

        LIMIT ?
    """, (
        cutoff,
        limit
    )).fetchall()

    conn.close()

    history = []

    for row in rows:
        history.append({
            "latitude": (
                row[
                    "latitude"
                ]
            ),

            "longitude": (
                row[
                    "longitude"
                ]
            ),

            "accuracy_m": (
                row[
                    "accuracy_m"
                ]
            ),

            "speed_m_s": (
                row[
                    "speed_m_s"
                ]
            ),

            "recorded_at": (
                row[
                    "recorded_at"
                ]
            ),

            "recorded_at_iso": (
                epoch_to_iso(
                    row[
                        "recorded_at"
                    ]
                )
            )
        })

    return history


def load_personal_places():
    conn = get_db()

    rows = conn.execute("""
        SELECT
            name,
            kind,
            latitude,
            longitude,
            radius_m,
            note,
            created_at,
            updated_at

        FROM personal_places

        ORDER BY name
    """).fetchall()

    conn.close()

    return [
        dict(row)
        for row in rows
    ]


def find_personal_place(
    name
):
    conn = get_db()

    row = conn.execute("""
        SELECT
            name,
            kind,
            latitude,
            longitude,
            radius_m,
            note,
            created_at,
            updated_at

        FROM personal_places

        WHERE lower(name)
            = lower(?)

        LIMIT 1
    """, (
        name,
    )).fetchone()

    conn.close()

    if row is None:
        return None

    return dict(row)


def build_place_relations(
    latitude,
    longitude,
    places
):
    relations = []

    for place in places:
        if not isinstance(
            place,
            dict
        ):
            continue

        distance = (
            haversine_m(
                latitude,
                longitude,
                place.get(
                    "latitude"
                ),
                place.get(
                    "longitude"
                )
            )
        )

        if distance is None:
            continue

        radius_m = (
            place.get(
                "radius_m"
            )
        )

        if not isinstance(
            radius_m,
            (int, float)
        ):
            radius_m = 150

        relations.append({
            "name": (
                place.get(
                    "name"
                )
            ),

            "kind": (
                place.get(
                    "kind"
                )
            ),

            "distance_m": (
                round(
                    distance,
                    1
                )
            ),

            "radius_m": (
                radius_m
            ),

            "inside": (
                distance
                <= radius_m
            )
        })

    relations.sort(
        key=lambda item: (
            item.get(
                "distance_m",
                float("inf")
            )
        )
    )

    return relations


def build_place_trends(
    history,
    places
):
    if (
        not isinstance(
            history,
            list
        )
        or len(
            history
        ) < 2
    ):
        return []

    start = history[0]
    end = history[-1]

    trends = []

    for place in places:
        start_distance = (
            haversine_m(
                start.get(
                    "latitude"
                ),
                start.get(
                    "longitude"
                ),
                place.get(
                    "latitude"
                ),
                place.get(
                    "longitude"
                )
            )
        )

        end_distance = (
            haversine_m(
                end.get(
                    "latitude"
                ),
                end.get(
                    "longitude"
                ),
                place.get(
                    "latitude"
                ),
                place.get(
                    "longitude"
                )
            )
        )

        if (
            start_distance is None
            or end_distance is None
        ):
            continue

        delta = (
            end_distance
            - start_distance
        )

        if delta <= -100:
            trend = (
                "approaching"
            )

        elif delta >= 100:
            trend = (
                "moving_away"
            )

        else:
            trend = (
                "roughly_stable"
            )

        trends.append({
            "name": (
                place.get(
                    "name"
                )
            ),

            "kind": (
                place.get(
                    "kind"
                )
            ),

            "trend": trend,

            "start_distance_m": (
                round(
                    start_distance,
                    1
                )
            ),

            "current_distance_m": (
                round(
                    end_distance,
                    1
                )
            ),

            "distance_change_m": (
                round(
                    delta,
                    1
                )
            )
        })

    trends.sort(
        key=lambda item: abs(
            item.get(
                "distance_change_m",
                0
            )
        ),
        reverse=True
    )

    return trends


def build_spatial_context(
    semantic,
    history_minutes=30
):
    current = (
        latest_location_from_semantic(
            semantic
        )
    )

    if current is None:
        return {
            "available": False,

            "reason": (
                "no_fresh_location"
            ),

            "provider": {
                "name": "amap",
                "available": bool(
                    AMAP_KEY
                )
            }
        }

    latitude = (
        current[
            "latitude"
        ]
    )

    longitude = (
        current[
            "longitude"
        ]
    )

    activity_state = (
        get_activity_state(
            semantic
        )
    )

    places = (
        load_personal_places()
    )

    relations = (
        build_place_relations(
            latitude,
            longitude,
            places
        )
    )

    history = (
        load_spatial_history(
            minutes=history_minutes,
            limit=200
        )
    )

    movement = (
        analyze_movement(
            history,
            activity_state=activity_state
        )
    )

    place_trends = (
        build_place_trends(
            history,
            places
        )
    )

    spatial = {
        "available": True,

        "current": {
            "coordinate_system": (
                "wgs84"
            ),

            "latitude": (
                latitude
            ),

            "longitude": (
                longitude
            ),

            "accuracy_m": (
                current.get(
                    "accuracy_m"
                )
            ),

            "speed_m_s": (
                current.get(
                    "speed_m_s"
                )
            )
        },

        "provider": {
            "name": "amap",
            "available": bool(
                AMAP_KEY
            )
        },

        "movement": (
            movement
        ),

        "personal_place_relations": (
            relations[:10]
        ),

        "personal_place_trends": (
            place_trends[:10]
        )
    }

    if relations:
        spatial[
            "nearest_personal_place"
        ] = relations[0]

    converted = (
        convert_gps_to_amap(
            latitude,
            longitude
        )
    )

    if converted.get(
        "available"
    ):
        spatial[
            "amap_coordinate"
        ] = {
            "coordinate_system": (
                "gcj02"
            ),

            "latitude": (
                converted[
                    "latitude"
                ]
            ),

            "longitude": (
                converted[
                    "longitude"
                ]
            )
        }

        address = (
            reverse_geocode(
                converted[
                    "latitude"
                ],
                converted[
                    "longitude"
                ],
                radius_m=1000
            )
        )

        if address.get(
            "available"
        ):
            spatial[
                "address"
            ] = {
                key: value
                for (
                    key,
                    value
                ) in address.items()
                if key not in (
                    "available",
                    "provider",
                    "nearby_pois"
                )
            }

            nearby_pois = (
                address.get(
                    "nearby_pois",
                    []
                )
            )

            spatial[
                "nearby_pois"
            ] = nearby_pois[
                :12
            ]

            scene = (
                classify_scene(
                    nearby_pois
                )
            )

            if (
                isinstance(
                    scene,
                    dict
                )
                and scene.get(
                    "primary_scene"
                )
            ):
                spatial[
                    "scene"
                ] = scene

        else:
            spatial[
                "provider_status"
            ] = address

    else:
        spatial[
            "provider_status"
        ] = converted

    description = (
        build_spatial_description(
            spatial.get(
                "address"
            ),
            spatial.get(
                "scene"
            ),
            spatial.get(
                "nearest_personal_place"
            )
        )
    )

    if description:
        spatial[
            "description"
        ] = description

    return spatial


# =========================
# 当前完整 Context
# =========================

def build_current_context():
    sensors = (
        load_latest_sensors()
    )

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

    spatial = (
        build_spatial_context(
            semantic
        )
    )

    reality = (
        build_reality_context(
            semantic,
            weather,
            spatial
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

        "spatial": spatial,

        "reality": reality,

        "phone_activity": (
            phone_activity
        ),

        "phone_activity_summary": (
            phone_activity_summary
        )
    }


# =========================
# Ping
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
        ),

        "spatial_provider": {
            "name": "amap",

            "configured": bool(
                AMAP_KEY
            )
        }
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

    message_id = (
        data.get(
            "messageId"
        )
    )

    session_id = (
        data.get(
            "sessionId"
        )
    )

    device_id = (
        data.get(
            "deviceId"
        )
    )

    payload = (
        data.get(
            "payload",
            []
        )
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
    location_sample = None

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

            values = (
                reading.get(
                    "values",
                    {}
                )
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

                if (
                    sensor_name
                    == "location"
                    and isinstance(
                        values,
                        dict
                    )
                ):
                    latitude = (
                        values.get(
                            "latitude"
                        )
                    )

                    longitude = (
                        values.get(
                            "longitude"
                        )
                    )

                    if (
                        isinstance(
                            latitude,
                            (int, float)
                        )
                        and isinstance(
                            longitude,
                            (int, float)
                        )
                    ):
                        location_sample = {
                            "latitude": (
                                float(
                                    latitude
                                )
                            ),

                            "longitude": (
                                float(
                                    longitude
                                )
                            ),

                            "accuracy_m": (
                                values.get(
                                    "horizontalAccuracy"
                                )
                            ),

                            "speed_m_s": (
                                values.get(
                                    "speed"
                                )
                            )
                        }

    if location_sample:
        record_spatial_sample(
            conn,

            location_sample[
                "latitude"
            ],

            location_sample[
                "longitude"
            ],

            accuracy_m=(
                location_sample.get(
                    "accuracy_m"
                )
            ),

            speed_m_s=(
                location_sample.get(
                    "speed_m_s"
                )
            ),

            received_at=(
                received_at
            )
        )

    run_housekeeping(
        conn
    )

    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",

        "received": (
            len(
                payload
            )
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
# Tasker Phone Activity
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

    screen = (
        data.get(
            "screen"
        )
    )

    locked = (
        data.get(
            "locked"
        )
    )

    last_interaction = (
        data.get(
            "last_interaction"
        )
    )

    app_name = (
        data.get(
            "app_name"
        )
    )

    app_package = (
        data.get(
            "app_package"
        )
    )

    app_since = (
        data.get(
            "app_since"
        )
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
            event_type = (
                "unlock"
            )

        elif locked == "true":
            event_type = (
                "lock"
            )

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

    run_housekeeping(
        conn
    )

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
# Context
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
            current[
                "sensors"
            ]
        ),

        "semantic": (
            current[
                "semantic"
            ]
        ),

        "weather": (
            current[
                "weather"
            ]
        ),

        "spatial": (
            current[
                "spatial"
            ]
        ),

        "reality": (
            current[
                "reality"
            ]
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
            current[
                "reality"
            ]
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

    reality = (
        current[
            "reality"
        ]
    )

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
# Environment Reality
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

    reality = (
        current[
            "reality"
        ]
    )

    summary = (
        reality.get(
            "summary",
            {}
        )
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
        value = (
            summary.get(
                key
            )
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

    reality = (
        current[
            "reality"
        ]
    )

    summary = (
        reality.get(
            "summary",
            {}
        )
    )

    relevant_summary = {}

    summary_keys = [
        "device_power",
        "connectivity",
        "device_description",
        "connectivity_description"
    ]

    for key in summary_keys:
        value = (
            summary.get(
                key
            )
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

    reality = (
        current[
            "reality"
        ]
    )

    summary = (
        reality.get(
            "summary",
            {}
        )
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

        "spatial": (
            reality.get(
                "spatial",
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
# Phone Reality
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
# Phone Timeline
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
            len(
                timeline
            )
        ),

        "timeline": timeline
    })


# =========================
# Spatial Reality
# =========================

@app.route(
    "/reality/spatial",
    methods=["GET"]
)
def reality_spatial():
    auth_error = check_token()

    if auth_error:
        return auth_error

    sensors = (
        load_latest_sensors()
    )

    semantic = (
        build_semantic_context(
            sensors
        )
    )

    spatial = (
        build_spatial_context(
            semantic
        )
    )

    return jsonify({
        "status": "ok",

        "generated_at": (
            utc_now_iso()
        ),

        "spatial": spatial
    })


# =========================
# Spatial History
# =========================

@app.route(
    "/reality/spatial/history",
    methods=["GET"]
)
def reality_spatial_history():
    auth_error = check_token()

    if auth_error:
        return auth_error

    try:
        minutes = int(
            request.args.get(
                "minutes",
                30
            )
        )

    except Exception:
        minutes = 30

    minutes = max(
        1,
        min(
            minutes,
            2880
        )
    )

    history = (
        load_spatial_history(
            minutes=minutes,
            limit=500
        )
    )

    sensors = (
        load_latest_sensors()
    )

    semantic = (
        build_semantic_context(
            sensors
        )
    )

    activity_state = (
        get_activity_state(
            semantic
        )
    )

    movement = (
        analyze_movement(
            history,
            activity_state=activity_state
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

        "point_count": (
            len(
                history
            )
        ),

        "movement": movement,

        "history": history
    })


# =========================
# Personal Places
# =========================

@app.route(
    "/reality/spatial/places",
    methods=[
        "GET",
        "POST"
    ]
)
def reality_spatial_places():
    auth_error = check_token()

    if auth_error:
        return auth_error

    if request.method == "GET":
        places = (
            load_personal_places()
        )

        return jsonify({
            "status": "ok",

            "generated_at": (
                utc_now_iso()
            ),

            "places": places
        })

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

    name = str(
        data.get(
            "name",
            ""
        )
    ).strip()

    kind = (
        data.get(
            "kind"
        )
    )

    latitude = (
        data.get(
            "latitude"
        )
    )

    longitude = (
        data.get(
            "longitude"
        )
    )

    radius_m = (
        data.get(
            "radius_m",
            150
        )
    )

    note = (
        data.get(
            "note"
        )
    )

    if not name:
        return jsonify({
            "error": (
                "name_required"
            )
        }), 400

    try:
        latitude = float(
            latitude
        )

        longitude = float(
            longitude
        )

        radius_m = float(
            radius_m
        )

    except Exception:
        return jsonify({
            "error": (
                "invalid_place_coordinates"
            )
        }), 400

    if not (
        -90 <= latitude <= 90
        and -180 <= longitude <= 180
    ):
        return jsonify({
            "error": (
                "coordinates_out_of_range"
            )
        }), 400

    radius_m = max(
        20,
        min(
            radius_m,
            5000
        )
    )

    now = (
        utc_now_iso()
    )

    conn = get_db()

    conn.execute("""
        INSERT INTO personal_places (
            name,
            kind,
            latitude,
            longitude,
            radius_m,
            note,
            created_at,
            updated_at
        )

        VALUES (?, ?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(name)

        DO UPDATE SET
            kind =
                excluded.kind,

            latitude =
                excluded.latitude,

            longitude =
                excluded.longitude,

            radius_m =
                excluded.radius_m,

            note =
                excluded.note,

            updated_at =
                excluded.updated_at
    """, (
        name,
        kind,
        latitude,
        longitude,
        radius_m,
        note,
        now,
        now
    ))

    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",

        "place": {
            "name": name,
            "kind": kind,
            "latitude": latitude,
            "longitude": longitude,
            "radius_m": radius_m,
            "note": note
        }
    }), 200


# =========================
# 删除 Personal Place
# =========================

@app.route(
    "/reality/spatial/places/<name>",
    methods=["DELETE"]
)
def reality_spatial_delete_place(
    name
):
    auth_error = check_token()

    if auth_error:
        return auth_error

    conn = get_db()

    result = conn.execute("""
        DELETE FROM personal_places

        WHERE lower(name)
            = lower(?)
    """, (
        name,
    ))

    deleted = (
        result.rowcount
        if result.rowcount
        is not None
        else 0
    )

    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",

        "deleted": (
            deleted > 0
        ),

        "name": name
    })


# =========================
# Nearby POI
# =========================

@app.route(
    "/reality/spatial/nearby",
    methods=["GET"]
)
def reality_spatial_nearby():
    auth_error = check_token()

    if auth_error:
        return auth_error

    sensors = (
        load_latest_sensors()
    )

    semantic = (
        build_semantic_context(
            sensors
        )
    )

    current = (
        latest_location_from_semantic(
            semantic
        )
    )

    if current is None:
        return jsonify({
            "status": "ok",

            "nearby": {
                "available": False,
                "reason": (
                    "no_fresh_location"
                )
            }
        })

    converted = (
        convert_gps_to_amap(
            current[
                "latitude"
            ],
            current[
                "longitude"
            ]
        )
    )

    if not converted.get(
        "available"
    ):
        return jsonify({
            "status": "ok",
            "nearby": converted
        })

    keywords = (
        request.args.get(
            "keywords"
        )
    )

    types = (
        request.args.get(
            "types"
        )
    )

    try:
        radius_m = int(
            request.args.get(
                "radius",
                1000
            )
        )

    except Exception:
        radius_m = 1000

    nearby = (
        nearby_search(
            converted[
                "latitude"
            ],
            converted[
                "longitude"
            ],
            keywords=keywords,
            types=types,
            radius_m=radius_m,
            page_size=20
        )
    )

    return jsonify({
        "status": "ok",

        "generated_at": (
            utc_now_iso()
        ),

        "nearby": nearby
    })


# =========================
# Route
# =========================

@app.route(
    "/reality/spatial/route",
    methods=["GET"]
)
def reality_spatial_route():
    auth_error = check_token()

    if auth_error:
        return auth_error

    sensors = (
        load_latest_sensors()
    )

    semantic = (
        build_semantic_context(
            sensors
        )
    )

    current = (
        latest_location_from_semantic(
            semantic
        )
    )

    if current is None:
        return jsonify({
            "status": "ok",

            "route": {
                "available": False,
                "reason": (
                    "no_fresh_location"
                )
            }
        })

    mode = (
        request.args.get(
            "mode",
            "walking"
        )
        .strip()
        .lower()
    )

    place_name = (
        request.args.get(
            "place"
        )
    )

    destination_latitude = None
    destination_longitude = None
    destination_name = None

    if place_name:
        place = (
            find_personal_place(
                place_name
            )
        )

        if place is None:
            return jsonify({
                "error": (
                    "personal_place_not_found"
                ),

                "place": place_name
            }), 404

        destination_latitude = (
            place[
                "latitude"
            ]
        )

        destination_longitude = (
            place[
                "longitude"
            ]
        )

        destination_name = (
            place[
                "name"
            ]
        )

    else:
        try:
            destination_latitude = float(
                request.args.get(
                    "latitude"
                )
            )

            destination_longitude = float(
                request.args.get(
                    "longitude"
                )
            )

        except Exception:
            return jsonify({
                "error": (
                    "destination_required"
                ),

                "message": (
                    "Use ?place=NAME or provide "
                    "latitude and longitude."
                )
            }), 400

    route_result = (
        amap_route(
            current[
                "latitude"
            ],

            current[
                "longitude"
            ],

            destination_latitude,
            destination_longitude,

            mode=mode
        )
    )

    if destination_name:
        route_result[
            "destination_name"
        ] = destination_name

    straight_distance = (
        haversine_m(
            current[
                "latitude"
            ],

            current[
                "longitude"
            ],

            destination_latitude,
            destination_longitude
        )
    )

    route_result[
        "straight_line_distance_m"
    ] = (
        round(
            straight_distance,
            1
        )
        if straight_distance
        is not None
        else None
    )

    return jsonify({
        "status": "ok",

        "generated_at": (
            utc_now_iso()
        ),

        "route": route_result
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

        freshness = (
            sensor.get(
                "freshness",
                "unknown"
            )
        )

        age_seconds = (
            sensor.get(
                "age_seconds"
            )
        )

        updated_at = (
            sensor.get(
                "updated_at"
            )
        )

        sensor_status[
            sensor_name
        ] = {
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
        == len(
            sensors
        )
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
            len(
                sensors
            )
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

        "spatial_provider": {
            "name": "amap",

            "configured": bool(
                AMAP_KEY
            )
        },

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
# Context Browser Check
# =========================

@app.route(
    "/context-check",
    methods=[
        "GET",
        "POST"
    ]
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
                Reality, Spatial Reality and
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

    token = (
        request.form.get(
            "token",
            ""
        )
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
            current[
                "sensors"
            ]
        ),

        "semantic": (
            current[
                "semantic"
            ]
        ),

        "weather": (
            current[
                "weather"
            ]
        ),

        "spatial": (
            current[
                "spatial"
            ]
        ),

        "reality": (
            current[
                "reality"
            ]
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
# Phone Timeline Browser Check
# =========================

@app.route(
    "/phone-timeline-check",
    methods=[
        "GET",
        "POST"
    ]
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

    token = (
        request.form.get(
            "token",
            ""
        )
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
            len(
                timeline
            )
        ),

        "timeline": timeline
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
