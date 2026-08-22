def build_reality_context(semantic, weather):
    """
    Build a compact, stable reality layer for Xiaxia.

    Structure:
    - user_state / device / environment / network / location / weather:
      Direct interpreted facts.
    - summary:
      Higher-level deterministic descriptions derived from facts,
      including stable human-readable descriptions.
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
    # 人类可理解的现实描述
    #
    # 这里只翻译已经确定的事实/摘要。
    # 不生成对用户行为、情绪或意图的猜测。
    # =========================

    descriptions = []

    # ---------- 天气描述 ----------

    weather_parts = []

    thermal_feel = reality["summary"].get("thermal_feel")

    thermal_description_map = {
        "extremely_hot": "体感非常炎热",
        "very_hot": "体感很热",
        "hot": "体感偏热",
        "warm": "体感温暖",
        "comfortable": "体感比较舒适",
        "cool": "体感偏凉",
        "cold": "体感寒冷",
        "very_cold": "体感非常寒冷"
    }

    if thermal_feel in thermal_description_map:
        weather_parts.append(
            thermal_description_map[thermal_feel]
        )

    precipitation_state = reality["summary"].get(
        "precipitation"
    )

    precipitation_description_map = {
        "light_rain": "正在下小雨",
        "rain": "正在下雨",
        "heavy_rain": "正在下较大的雨",
        "none": "目前没有降水"
    }

    if precipitation_state in precipitation_description_map:
        weather_parts.append(
            precipitation_description_map[
                precipitation_state
            ]
        )

    humidity = weather_data.get("humidity_percent")

    if isinstance(humidity, (int, float)):
        if humidity >= 80:
            weather_parts.append("空气湿度很高")
        elif humidity >= 70:
            weather_parts.append("空气比较潮湿")
        elif humidity <= 30:
            weather_parts.append("空气比较干燥")

    wind_speed = weather_data.get("wind_speed_kmh")

    if isinstance(wind_speed, (int, float)):
        if wind_speed >= 50:
            weather_parts.append("风很强")
        elif wind_speed >= 30:
            weather_parts.append("风比较大")
        elif wind_speed >= 15:
            weather_parts.append("有比较明显的风")

    if weather_parts:
        weather_description = "，".join(weather_parts) + "。"

        reality["summary"][
            "weather_description"
        ] = weather_description

        descriptions.append(
            weather_description.rstrip("。")
        )

    # ---------- 周围环境描述 ----------

    surroundings_parts = []

    ambient_light = reality["summary"].get(
        "ambient_light"
    )

    light_description_map = {
        "dark": "周围很暗",
        "dim": "周围光线较暗",
        "normal": "周围光线正常",
        "bright": "周围比较明亮",
        "very_bright": "周围光线很强"
    }

    if ambient_light in light_description_map:
        surroundings_parts.append(
            light_description_map[ambient_light]
        )

    ambient_sound = reality["summary"].get(
        "ambient_sound"
    )

    sound_description_map = {
        "very_quiet": "环境非常安静",
        "quiet": "环境比较安静",
        "moderate": "周围有一些环境声音",
        "loud": "周围比较吵",
        "very_loud": "周围非常吵"
    }

    if ambient_sound in sound_description_map:
        surroundings_parts.append(
            sound_description_map[ambient_sound]
        )

    if surroundings_parts:
        surroundings_description = (
            "，".join(surroundings_parts) + "。"
        )

        reality["summary"][
            "surroundings_description"
        ] = surroundings_description

        descriptions.append(
            surroundings_description.rstrip("。")
        )

    # ---------- 移动状态描述 ----------

    mobility = reality["summary"].get("mobility")

    mobility_description_map = {
        "not_moving": "手机目前没有明显移动",
        "moving_on_foot": "手机正在随步行移动",
        "moving_on_foot_fast": "手机正在快速移动，可能伴随跑动",
        "cycling": "手机正在随骑行移动",
        "in_vehicle": "手机正在随交通工具移动"
    }

    if mobility in mobility_description_map:
        mobility_description = (
            mobility_description_map[mobility] + "。"
        )

        reality["summary"][
            "mobility_description"
        ] = mobility_description

        descriptions.append(
            mobility_description.rstrip("。")
        )

    # ---------- 设备状态描述 ----------

    device_parts = []

    device_power = reality["summary"].get(
        "device_power"
    )

    power_description_map = {
        "charging": "手机正在充电",
        "critical": "手机电量已经非常低",
        "low": "手机电量较低",
        "high": "手机电量充足"
    }

    if device_power in power_description_map:
        device_parts.append(
            power_description_map[device_power]
        )

    low_power_mode = device.get("low_power_mode")

    if low_power_mode is True:
        device_parts.append("手机开启了低电量模式")

    if device_parts:
        device_description = (
            "，".join(device_parts) + "。"
        )

        reality["summary"][
            "device_description"
        ] = device_description

        descriptions.append(
            device_description.rstrip("。")
        )

    # ---------- 网络状态描述 ----------

    connectivity = reality["summary"].get(
        "connectivity"
    )

    connectivity_description_map = {
        "offline": "手机当前没有网络连接",
        "online_weak": "手机已联网，但网络信号较弱",
        "online_normal": "手机网络连接正常",
        "online_strong": "手机网络连接良好",
        "online": "手机当前已联网"
    }

    if connectivity in connectivity_description_map:
        connectivity_description = (
            connectivity_description_map[
                connectivity
            ] + "。"
        )

        reality["summary"][
            "connectivity_description"
        ] = connectivity_description

        descriptions.append(
            connectivity_description.rstrip("。")
        )

    # ---------- 综合现实描述 ----------

    if descriptions:
        reality["summary"]["overall_description"] = (
            "；".join(descriptions) + "。"
        )

    # =========================
    # 保守情境推断
    #
    # inference 不是事实。
    # 多个可能情境可以同时成立，因此使用 contexts 数组。
    #
    # Reality 只描述：
    # “这些信号可能指向什么环境”
    #
    # 不描述：
    # “用户正在想什么”
    # “用户需要什么”
    # =========================

    inference_contexts = []

    mobility = reality["summary"].get("mobility")
    ambient_light = reality["summary"].get(
        "ambient_light"
    )
    ambient_sound = reality["summary"].get(
        "ambient_sound"
    )
    thermal_feel = reality["summary"].get(
        "thermal_feel"
    )
    precipitation = reality["summary"].get(
        "precipitation"
    )

    # ---------- 可能的休息环境 ----------
    #
    # 静止 + 暗光 + 安静
    #
    # 不推断“正在睡觉”。
    # 也不直接断言一定在室内。
    # ----------

    if (
        mobility == "not_moving"
        and ambient_light in (
            "dark",
            "dim"
        )
        and ambient_sound in (
            "very_quiet",
            "quiet"
        )
    ):
        inference_contexts.append({
            "value": "resting_environment",
            "confidence": "medium",
            "basis": [
                "not_moving",
                ambient_light,
                ambient_sound
            ]
        })

    # ---------- 可能的移动环境 ----------
    #
    # Activity 显示持续移动，
    # 且当前位置数据可用。
    #
    # GPS 可用不能证明用户一定在户外，
    # 因此这里只推断 moving_environment。
    # ----------

    location_data = reality.get("location", {})

    if (
        mobility in (
            "moving_on_foot",
            "moving_on_foot_fast",
            "cycling",
            "in_vehicle"
        )
        and location_data.get("available") is True
    ):
        inference_contexts.append({
            "value": "moving_environment",
            "confidence": "medium",
            "basis": [
                mobility,
                "location_available"
            ]
        })

    # ---------- 炎热环境 ----------
    #
    # 这是基于天气体感数据的环境判断。
    # ----------

    if thermal_feel in (
        "very_hot",
        "extremely_hot"
    ):
        inference_contexts.append({
            "value": "hot_environment",
            "confidence": "high",
            "basis": [
                thermal_feel
            ]
        })

    # ---------- 雨天环境 ----------
    #
    # 基于天气服务确认的降水状态。
    # ----------

    if precipitation in (
        "light_rain",
        "rain",
        "heavy_rain"
    ):
        inference_contexts.append({
            "value": "rainy_environment",
            "confidence": "high",
            "basis": [
                precipitation
            ]
        })

    # 只有真的存在推断时才输出 contexts。
    if inference_contexts:
        reality["inferences"]["contexts"] = (
            inference_contexts
        )

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

        reality["summary"][
            "location_quality"
        ] = location_quality

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
