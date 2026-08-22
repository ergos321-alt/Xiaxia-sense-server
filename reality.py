def build_reality_context(semantic, weather):
    """
    Build a compact, stable reality layer for Xiaxia.

    Structure:
    - user_state / device / environment / network / location / weather:
      Direct interpreted facts.
    - summary:
      Higher-level deterministic descriptions derived from facts.
    - inferences:
      Conservative contextual guesses with explicit confidence.

    This layer does not generate dialogue or personality.
    It describes reality. Xiaxia decides how, when, or whether
    to respond to that reality.
    """

    reality = {
        "user_state": {},
        "device": {},
        "environment": {},
        "network": {},
        "location": {},
        "weather": {},
        "summary": {},
        "inferences": {}
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
    # 高层摘要：移动状态
    # =========================

    activity_state = reality["user_state"].get("activity")

    mobility_map = {
        "stationary": "not_moving",
        "walking": "moving_on_foot",
        "running": "moving_on_foot_fast",
        "cycling": "cycling",
        "in_vehicle": "in_vehicle"
    }

    if activity_state in mobility_map:
        reality["summary"]["mobility"] = mobility_map[
            activity_state
        ]

    # =========================
    # 高层摘要：天气体感
    # =========================

    weather_data = reality.get("weather", {})

    if weather_data.get("available") is True:
        feels_like = weather_data.get("feels_like_c")

        if isinstance(feels_like, (int, float)):
            if feels_like >= 38:
                thermal_state = "extremely_hot"
            elif feels_like >= 35:
                thermal_state = "very_hot"
            elif feels_like >= 30:
                thermal_state = "hot"
            elif feels_like >= 24:
                thermal_state = "warm"
            elif feels_like >= 16:
                thermal_state = "comfortable"
            elif feels_like >= 8:
                thermal_state = "cool"
            elif feels_like >= 0:
                thermal_state = "cold"
            else:
                thermal_state = "very_cold"

            reality["summary"]["thermal_feel"] = thermal_state

    # =========================
    # 高层摘要：降水
    # =========================

    if weather_data.get("available") is True:
        condition = weather_data.get("condition")
        precipitation = weather_data.get("precipitation_mm")

        rain_state = None

        if isinstance(condition, str):
            condition_lower = condition.lower()

            if (
                "drizzle" in condition_lower
                or "rain" in condition_lower
                or "shower" in condition_lower
            ):
                if isinstance(precipitation, (int, float)):
                    if precipitation <= 0.5:
                        rain_state = "light_rain"
                    elif precipitation <= 4:
                        rain_state = "rain"
                    else:
                        rain_state = "heavy_rain"
                else:
                    rain_state = "rain"

        if rain_state is not None:
            reality["summary"]["precipitation"] = rain_state
        elif (
            isinstance(precipitation, (int, float))
            and precipitation <= 0
        ):
            reality["summary"]["precipitation"] = "none"

    # =========================
    # 高层摘要：设备电量
    # =========================

    device = reality.get("device", {})

    battery_percent = device.get("battery_percent")
    charging = device.get("charging")

    if isinstance(battery_percent, (int, float)):
        if charging is True:
            power_state = "charging"
        elif battery_percent <= 10:
            power_state = "critical"
        elif battery_percent <= 20:
            power_state = "low"
        elif battery_percent >= 80:
            power_state = "high"
        else:
            power_state = "normal"

        reality["summary"]["device_power"] = power_state

    # =========================
    # 高层摘要：网络
    # =========================

    network_data = reality.get("network", {})

    network_state = network_data.get("state")

    if network_state == "offline":
        reality["summary"]["connectivity"] = "offline"

    elif network_state == "online":
        quality = network_data.get("quality")

        if quality == "weak":
            reality["summary"]["connectivity"] = "online_weak"
        elif quality == "medium":
            reality["summary"]["connectivity"] = "online_normal"
        elif quality == "strong":
            reality["summary"]["connectivity"] = "online_strong"
        else:
            reality["summary"]["connectivity"] = "online"

    # =========================
    # 高层摘要：周围光线
    # =========================

    environment = reality.get("environment", {})
    light_data = environment.get("light", {})

    if isinstance(light_data, dict):
        light_state = light_data.get("state")

        if light_state is not None:
            reality["summary"]["ambient_light"] = light_state

    # =========================
    # 高层摘要：周围声音
    # =========================

    sound_data = environment.get("sound", {})

    if isinstance(sound_data, dict):
        sound_state = sound_data.get("state")

        if sound_state is not None:
            reality["summary"]["ambient_sound"] = sound_state

    # =========================
    # 保守情境推断
    #
    # 注意：
    # inference 不是事实。
    # 只有多个独立信号互相支持时才生成。
    # =========================

    mobility = reality["summary"].get("mobility")
    ambient_light = reality["summary"].get("ambient_light")
    ambient_sound = reality["summary"].get("ambient_sound")

    # 静止 + 黑暗 + 安静
    # 可能处于休息环境，但不能推断“正在睡觉”
    if (
        mobility == "not_moving"
        and ambient_light in ("dark", "dim")
        and ambient_sound in ("very_quiet", "quiet")
    ):
        reality["inferences"]["possible_context"] = {
            "value": "resting_environment",
            "confidence": "medium",
            "basis": [
                "not_moving",
                ambient_light,
                ambient_sound
            ]
        }

    # 明亮 + 较吵 + 静止
    # 可能处于活跃的公共/工作环境
    elif (
        mobility == "not_moving"
        and ambient_light in ("bright", "very_bright")
        and ambient_sound in ("moderate", "loud")
    ):
        reality["inferences"]["possible_context"] = {
            "value": "active_environment",
            "confidence": "low",
            "basis": [
                "not_moving",
                ambient_light,
                ambient_sound
            ]
        }

    # =========================
    # 数据质量提示
    # =========================

    location_data = reality.get("location", {})

    accuracy = location_data.get("accuracy_m")

    if isinstance(accuracy, (int, float)):
        if accuracy <= 25:
            location_quality = "good"
        elif accuracy <= 100:
            location_quality = "approximate"
        else:
            location_quality = "poor"

        reality["summary"]["location_quality"] = location_quality

    # =========================
    # 清理空值
    # =========================

    cleaned_reality = {}

    for key, value in reality.items():

        if not value:
            continue

        if isinstance(value, dict):
            cleaned_value = {
                sub_key: sub_value
                for sub_key, sub_value in value.items()
                if sub_value is not None
            }

            if cleaned_value:
                cleaned_reality[key] = cleaned_value

        else:
            cleaned_reality[key] = value

    return cleaned_reality
