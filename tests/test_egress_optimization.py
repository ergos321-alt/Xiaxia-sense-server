import json
from unittest.mock import patch

import pytest

import app as app_module


AUTH_HEADERS = {
    "Authorization": "Bearer egress-test-token",
}


class FakeResult:
    def __init__(self, rows=None):
        self.rows = rows or []

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class CountingDatabase:
    def __init__(self):
        self.counts = {
            "connections": 0,
            "select": 0,
            "insert": 0,
            "update": 0,
            "delete": 0,
            "ddl": 0,
            "commit": 0,
        }
        self.sensors = {}
        self.spatial = []
        self.raw_messages = []

    def connect(self):
        self.counts["connections"] += 1
        return CountingConnection(self)


class CountingConnection:
    def __init__(self, database):
        self.database = database

    def execute(self, query, params=None):
        normalized = " ".join(query.split()).upper()
        params = params or ()

        if normalized.startswith("SELECT"):
            self.database.counts["select"] += 1
        elif normalized.startswith("INSERT"):
            self.database.counts["insert"] += 1
        elif normalized.startswith("UPDATE"):
            self.database.counts["update"] += 1
        elif normalized.startswith("DELETE"):
            self.database.counts["delete"] += 1
        elif normalized.startswith("CREATE"):
            self.database.counts["ddl"] += 1

        if "FROM SENSOR_LATEST" in normalized:
            rows = [
                {
                    "sensor_name": name,
                    "sensor_time_ns": row["sensor_time_ns"],
                    "values_json": row["values_json"],
                    "updated_at": row["updated_at"],
                }
                for name, row in sorted(self.database.sensors.items())
            ]
            return FakeResult(rows)

        if normalized.startswith("INSERT INTO SENSOR_LATEST"):
            for offset in range(0, len(params), 7):
                values = params[offset:offset + 7]
                name = values[0]
                current = self.database.sensors.get(name)

                if (
                    current is None
                    or values[1] > current["sensor_time_ns"]
                ):
                    self.database.sensors[name] = {
                        "sensor_time_ns": values[1],
                        "values_json": values[2],
                        "updated_at": values[6],
                    }

        if normalized.startswith("INSERT INTO MESSAGES"):
            self.database.raw_messages.append(params)

        if "FROM SPATIAL_HISTORY" in normalized:
            rows = self.database.spatial[-1:]
            return FakeResult(rows)

        if normalized.startswith("INSERT INTO SPATIAL_HISTORY"):
            for offset in range(0, len(params), 6):
                values = params[offset:offset + 6]
                self.database.spatial.append({
                    "latitude": values[0],
                    "longitude": values[1],
                    "accuracy_m": values[2],
                    "speed_m_s": values[3],
                    "recorded_at": values[4],
                    "received_at": values[5],
                })

        return FakeResult()

    def commit(self):
        self.database.counts["commit"] += 1

    def rollback(self):
        pass

    def close(self):
        pass


def reset_sensor_state():
    with app_module._sensor_cache_lock:
        if app_module._sensor_flush_timer is not None:
            app_module._sensor_flush_timer.cancel()

        app_module._sensor_flush_timer = None
        app_module._sensor_latest_cache.clear()
        app_module._sensor_dirty_names.clear()
        app_module._pending_spatial_samples.clear()
        app_module._pending_raw_message = None
        app_module._last_sensor_flush_monotonic = 0.0


@pytest.fixture()
def egress_client():
    previous_token = app_module.SENSE_TOKEN
    previous_interval = app_module.SENSOR_FLUSH_INTERVAL_SECONDS
    previous_housekeeping = app_module._last_housekeeping_epoch
    app_module.SENSE_TOKEN = "egress-test-token"
    app_module.SENSOR_FLUSH_INTERVAL_SECONDS = 60
    app_module._last_housekeeping_epoch = 0
    app_module.app.config["TESTING"] = True
    reset_sensor_state()
    database = CountingDatabase()

    with (
        patch.object(app_module, "get_db", side_effect=database.connect),
        app_module.app.test_client() as client,
    ):
        yield client, database

    reset_sensor_state()
    app_module.SENSE_TOKEN = previous_token
    app_module.SENSOR_FLUSH_INTERVAL_SECONDS = previous_interval
    app_module._last_housekeeping_epoch = previous_housekeeping


def sensor_frame(sequence):
    return {
        "messageId": sequence,
        "sessionId": "session-1",
        "deviceId": "phone-1",
        "payload": [
            {
                "name": "light",
                "time": sequence,
                "values": {"lux": sequence},
            },
            {
                "name": "battery",
                "time": sequence,
                "values": {"level": sequence},
            },
        ],
    }


@pytest.mark.parametrize("push_count", [60, 300])
def test_high_frequency_pushes_are_batched(egress_client, push_count):
    client, database = egress_client

    for sequence in range(1, push_count + 1):
        response = client.post(
            "/data",
            headers=AUTH_HEADERS,
            json=sensor_frame(sequence),
        )
        assert response.status_code == 200

    # Simulate the end-of-window/process-exit flush so the final frame is also
    # durable; the query count remains independent of the HTTP push count.
    app_module.flush_sensor_cache(force=True)

    assert database.counts == {
        "connections": 2,
        "select": 0,
        "insert": 4,
        "update": 0,
        "delete": 3,
        "ddl": 0,
        "commit": 2,
    }
    assert len(database.raw_messages) == 2
    assert database.sensors["light"]["sensor_time_ns"] == push_count


class ManualTimer:
    def __init__(self, delay, function):
        self.delay = delay
        self.function = function
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        assert self.started
        assert not self.cancelled
        self.function()


def test_dirty_cache_flushes_after_interval_without_another_request(
    egress_client,
):
    client, database = egress_client
    timers = []

    def create_timer(delay, function):
        timer = ManualTimer(delay, function)
        timers.append(timer)
        return timer

    with patch.object(
        app_module.threading,
        "Timer",
        side_effect=create_timer,
    ):
        first = client.post(
            "/data",
            headers=AUTH_HEADERS,
            json=sensor_frame(1),
        )

        assert first.status_code == 200
        assert database.sensors["light"]["sensor_time_ns"] == 1
        assert timers[0].cancelled is True

        second = client.post(
            "/data",
            headers=AUTH_HEADERS,
            json=sensor_frame(2),
        )

        assert second.status_code == 200
        assert database.sensors["light"]["sensor_time_ns"] == 1
        assert len(timers) == 2
        assert app_module._sensor_flush_timer is timers[1]

        # No further /data request: firing the one pending interval timer must
        # make the second frame durable by itself.
        timers[1].fire()

    assert database.sensors["light"]["sensor_time_ns"] == 2
    assert database.counts["connections"] == 2
    assert database.counts["select"] == 0
    assert database.counts["insert"] == 4
    assert app_module._sensor_flush_timer is None
    assert app_module._sensor_dirty_names == set()


def test_reality_reads_newest_unflushed_sensor_state(egress_client):
    client, database = egress_client

    client.post(
        "/data",
        headers=AUTH_HEADERS,
        json=sensor_frame(100),
    )
    client.post(
        "/data",
        headers=AUTH_HEADERS,
        json=sensor_frame(200),
    )

    sensors = app_module.load_latest_sensors()

    assert database.sensors["light"]["sensor_time_ns"] == 100
    assert sensors["light"]["time_ns"] == 200
    assert sensors["light"]["values"] == {"lux": 200}
    assert sensors["light"]["age_seconds"] <= 1

    app_module.flush_sensor_cache(force=True)
    assert database.sensors["light"]["sensor_time_ns"] == 200


def test_empty_cache_falls_back_to_database(egress_client):
    _, database = egress_client
    database.sensors["light"] = {
        "sensor_time_ns": 42,
        "values_json": json.dumps({"lux": 7}),
        "updated_at": app_module.utc_now_iso(),
    }

    sensors = app_module.load_latest_sensors()

    assert sensors["light"]["time_ns"] == 42
    assert sensors["light"]["values"] == {"lux": 7}


def test_spatial_history_keeps_time_distance_sampling_and_batches_writes(
    egress_client,
):
    client, database = egress_client

    def location_frame(sequence, latitude):
        return {
            "messageId": sequence,
            "payload": [{
                "name": "location",
                "time": sequence,
                "values": {
                    "latitude": latitude,
                    "longitude": 113.3,
                },
            }],
        }

    client.post(
        "/data",
        headers=AUTH_HEADERS,
        json=location_frame(1, 23.10000),
    )
    client.post(
        "/data",
        headers=AUTH_HEADERS,
        json=location_frame(2, 23.10005),
    )
    client.post(
        "/data",
        headers=AUTH_HEADERS,
        json=location_frame(3, 23.10100),
    )
    app_module.flush_sensor_cache(force=True)

    assert len(database.spatial) == 2
    assert database.counts["connections"] == 2
    assert database.counts["select"] == 2
    assert database.counts["insert"] == 6


class RawSchemaConnection:
    def __init__(self, calls):
        self.calls = calls

    def execute(self, query, params=()):
        self.calls.append(" ".join(query.split()).upper())
        return FakeResult()

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def test_schema_initialization_runs_once_per_worker():
    calls = []
    connect_count = 0

    def fake_connect(*args, **kwargs):
        nonlocal connect_count
        connect_count += 1
        return RawSchemaConnection(calls)

    previous_url = app_module.DATABASE_URL
    app_module.DATABASE_URL = "postgresql://example.invalid/db"
    app_module._schema_initialized = False

    try:
        with patch.object(app_module.psycopg, "connect", side_effect=fake_connect):
            first = app_module.get_db()
            second = app_module.get_db()
            first.close()
            second.close()
    finally:
        app_module.DATABASE_URL = previous_url
        app_module._schema_initialized = False

    assert connect_count == 2
    assert len([call for call in calls if call.startswith("CREATE")]) == 12
