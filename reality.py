def build_reality_context(semantic, weather):
    """
    Build a compact, stable reality layer for Xiaxia.

    This layer does not generate dialogue or personality.
    It only reorganizes interpreted sensor/weather information
    into a structure that is easy for an AI assistant to consume.
    """

    reality = {
        "user_state": {},
        "device": {},
        "environment": {},
        "network": {},
        "location": {},
        "weather": {}
    }

    # =========================
    # 用户状态
    # =========================

    activity = semantic.get("activity")

    if isinstance(activity, dict):
        state = activity.get("state")

        if state is not None:
            reality["user_state"]["activity"] = state

    pedometer = semantic.get("pedometer")

    if isinstance(pedometer, dict):
        steps = pedometer.get("steps")

        if steps is not None:
            reality["user_state"]["steps"] = steps

    # =========================
    # 设备状态
    # =========================

    battery = semantic.get("battery")

    if isinstance(battery, dict):
        reality["device"] = {
            "battery_percent": battery.get("level_percent"),
            "battery_state": battery.get("state"),
            "charging": battery.get("charging"),
            "low_power_mode": battery.get("low_power_mode")
        }

    # =========================
    # 周围环境
    # =========================

    light = semantic.get("light")

    if isinstance(light, dict):
        reality["environment"]["light"] = {
            "state": light.get("state"),
            "lux": light.get("lux")
        }

    microphone = semantic.get("microphone")

    if isinstance(microphone, dict):
        reality["environment"]["sound"] = {
            "state": microphone.get("relative_sound_level"),
            "dbfs": microphone.get("dbfs")
        }

    barometer = semantic.get("barometer")

    if isinstance(barometer, dict):
        reality["environment"]["barometer"] = {
            "pressure_hpa": barometer.get("pressure_hpa"),
            "relative_altitude_m": barometer.get("relative_altitude_m")
        }

    # =========================
    # 网络
    # =========================

    network = semantic.get("network")

    if isinstance(network, dict):
        reality["network"] = {
            "state": network.get("state"),
            "type": network.get("type"),
            "quality": network.get("quality"),
            "strength": network.get("strength"),
            "ssid": network.get("ssid")
        }

    # =========================
    # 位置
    # =========================

    location = semantic.get("location")

    if isinstance(location, dict):
        reality["location"] = {
            "available": location.get("available"),
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "accuracy_m": location.get("accuracy_m"),
            "speed_m_s": location.get("speed_m_s")
        }

    # =========================
    # 天气
    # =========================

    if isinstance(weather, dict) and weather.get("available") is True:
        reality["weather"] = {
            "available": True,
            "condition": weather.get("condition"),
            "temperature_c": weather.get("temperature_c"),
            "feels_like_c": weather.get("apparent_temperature_c"),
            "humidity_percent": weather.get("humidity_percent"),
            "precipitation_mm": weather.get("precipitation_mm"),
            "cloud_cover_percent": weather.get("cloud_cover_percent"),
            "wind_speed_kmh": weather.get("wind_speed_kmh"),
            "wind_direction_deg": weather.get("wind_direction_deg"),
            "pressure_hpa": weather.get("surface_pressure_hpa"),
            "timezone": weather.get("timezone"),
            "observed_at": weather.get("time")
        }

    elif isinstance(weather, dict):
        reality["weather"] = weather

    # =========================
    # 清理完全为空的分组
    # =========================

    reality = {
        key: value
        for key, value in reality.items()
        if value
    }

    return reality
