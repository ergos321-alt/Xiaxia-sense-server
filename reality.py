def build_reality_context(
    semantic,
    weather,
    spatial=None
):
    """
    Build a compact, stable reality layer for Xiaxia.

    Structure:

    Direct interpreted facts:
    - user_state
    - device
    - environment
    - network
    - location
    - weather
    - spatial

    summary:
    - deterministic descriptions
    - stable human-readable reality summaries

    inferences:
    - conservative contextual guesses
    - explicit confidence
    - no inference about emotion, intention, desire or need

    Reality describes the world.
    Xiaxia decides how to respond to it.
    """

    reality = {
        "user_state": {},
        "device": {},
        "environment": {},
        "network": {},
        "location": {},
        "weather": {},
        "spatial": {},
        "summary": {},
        "inferences": {}
    }

    # =========================
    # 用户状态
    # =========================

    activity = semantic.get(
        "activity"
    )

    if isinstance(
        activity,
        dict
    ):
        state = (
            activity.get(
                "state"
            )
        )

        if state is not None:
            reality[
                "user_state"
            ][
                "activity"
            ] = state

    pedometer = semantic.get(
        "pedometer"
    )

    if isinstance(
        pedometer,
        dict
    ):
        steps = (
            pedometer.get(
                "steps"
            )
        )

        if steps is not None:
            reality[
                "user_state"
            ][
                "steps"
            ] = steps

    # =========================
    # 设备状态
    # =========================

    battery = semantic.get(
        "battery"
    )

    if isinstance(
        battery,
        dict
    ):
        reality[
            "device"
        ] = {
            "battery_percent": (
                battery.get(
                    "level_percent"
                )
            ),

            "battery_state": (
                battery.get(
                    "state"
                )
            ),

            "charging": (
                battery.get(
                    "charging"
                )
            ),

            "low_power_mode": (
                battery.get(
                    "low_power_mode"
                )
            )
        }

    # =========================
    # 周围环境
    # =========================

    light = semantic.get(
        "light"
    )

    if isinstance(
        light,
        dict
    ):
        reality[
            "environment"
        ][
            "light"
        ] = {
            "state": (
                light.get(
                    "state"
                )
            ),

            "lux": (
                light.get(
                    "lux"
                )
            )
        }

    microphone = semantic.get(
        "microphone"
    )

    if isinstance(
        microphone,
        dict
    ):
        reality[
            "environment"
        ][
            "sound"
        ] = {
            "state": (
                microphone.get(
                    "relative_sound_level"
                )
            ),

            "dbfs": (
                microphone.get(
                    "dbfs"
                )
            )
        }

    barometer = semantic.get(
        "barometer"
    )

    if isinstance(
        barometer,
        dict
    ):
        reality[
            "environment"
        ][
            "barometer"
        ] = {
            "pressure_hpa": (
                barometer.get(
                    "pressure_hpa"
                )
            ),

            "relative_altitude_m": (
                barometer.get(
                    "relative_altitude_m"
                )
            )
        }

    # =========================
    # 网络
    # =========================

    network = semantic.get(
        "network"
    )

    if isinstance(
        network,
        dict
    ):
        reality[
            "network"
        ] = {
            "state": (
                network.get(
                    "state"
                )
            ),

            "type": (
                network.get(
                    "type"
                )
            ),

            "quality": (
                network.get(
                    "quality"
                )
            ),

            "strength": (
                network.get(
                    "strength"
                )
            ),

            "ssid": (
                network.get(
                    "ssid"
                )
            )
        }

    # =========================
    # 原始位置事实
    # =========================

    location = semantic.get(
        "location"
    )

    if isinstance(
        location,
        dict
    ):
        reality[
            "location"
        ] = {
            "available": (
                location.get(
                    "available"
                )
            ),

            "latitude": (
                location.get(
                    "latitude"
                )
            ),

            "longitude": (
                location.get(
                    "longitude"
                )
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

    # =========================
    # 天气
    # =========================

    if (
        isinstance(
            weather,
            dict
        )
        and weather.get(
            "available"
        ) is True
    ):
        reality[
            "weather"
        ] = {
            "available": True,

            "condition": (
                weather.get(
                    "condition"
                )
            ),

            "temperature_c": (
                weather.get(
                    "temperature_c"
                )
            ),

            "feels_like_c": (
                weather.get(
                    "apparent_temperature_c"
                )
            ),

            "humidity_percent": (
                weather.get(
                    "humidity_percent"
                )
            ),

            "precipitation_mm": (
                weather.get(
                    "precipitation_mm"
                )
            ),

            "cloud_cover_percent": (
                weather.get(
                    "cloud_cover_percent"
                )
            ),

            "wind_speed_kmh": (
                weather.get(
                    "wind_speed_kmh"
                )
            ),

            "wind_direction_deg": (
                weather.get(
                    "wind_direction_deg"
                )
            ),

            "pressure_hpa": (
                weather.get(
                    "surface_pressure_hpa"
                )
            ),

            "timezone": (
                weather.get(
                    "timezone"
                )
            ),

            "observed_at": (
                weather.get(
                    "time"
                )
            )
        }

    elif isinstance(
        weather,
        dict
    ):
        reality[
            "weather"
        ] = weather

    # =========================
    # Spatial Reality
    # =========================

    if isinstance(
        spatial,
        dict
    ):
        reality[
            "spatial"
        ] = spatial

    # =========================
    # 基础移动状态
    #
    # 这一层只翻译 Activity。
    # 后面会用 Spatial movement
    # 做融合后的最终移动摘要。
    # =========================

    activity_state = (
        reality[
            "user_state"
        ].get(
            "activity"
        )
    )

    mobility_map = {
        "stationary": (
            "not_moving"
        ),

        "walking": (
            "moving_on_foot"
        ),

        "running": (
            "moving_on_foot_fast"
        ),

        "cycling": (
            "cycling"
        ),

        "in_vehicle": (
            "in_vehicle"
        )
    }

    activity_mobility = (
        mobility_map.get(
            activity_state
        )
    )

    if activity_mobility:
        reality[
            "summary"
        ][
            "activity_mobility"
        ] = activity_mobility

    # =========================
    # Spatial 移动融合
    # =========================

    spatial_data = reality.get(
        "spatial",
        {}
    )

    spatial_movement = {}

    if isinstance(
        spatial_data,
        dict
    ):
        possible_movement = (
            spatial_data.get(
                "movement"
            )
        )

        if isinstance(
            possible_movement,
            dict
        ):
            spatial_movement = (
                possible_movement
            )

    spatial_trend = (
        spatial_movement.get(
            "trend"
        )
    )

    spatial_confidence = (
        spatial_movement.get(
            "confidence"
        )
    )

    # =========================
    # 最终 Mobility
    #
    # 优先级：
    #
    # 1. Spatial 高/中置信融合结果
    # 2. Activity
    # 3. uncertain
    #
    # Spatial 已经融合了 GPS accuracy
    # 和 Activity，因此它更适合作为最终结论。
    # =========================

    final_mobility = None
    final_mobility_confidence = None

    if (
        spatial_trend == "stable"
        and spatial_confidence
        in (
            "high",
            "medium"
        )
    ):
        final_mobility = (
            "not_moving"
        )

        final_mobility_confidence = (
            spatial_confidence
        )

    elif (
        spatial_trend == "moving"
        and spatial_confidence
        in (
            "high",
            "medium"
        )
    ):
        if activity_state == "walking":
            final_mobility = (
                "moving_on_foot"
            )

        elif activity_state == "running":
            final_mobility = (
                "moving_on_foot_fast"
            )

        elif activity_state == "cycling":
            final_mobility = (
                "cycling"
            )

        elif activity_state == "in_vehicle":
            final_mobility = (
                "in_vehicle"
            )

        else:
            final_mobility = (
                "moving"
            )

        final_mobility_confidence = (
            spatial_confidence
        )

    elif (
        spatial_trend
        in (
            "uncertain",
            "insufficient_history"
        )
    ):
        if activity_mobility:
            final_mobility = (
                activity_mobility
            )

            final_mobility_confidence = (
                "medium"
                if spatial_trend
                == "insufficient_history"
                else "low"
            )

    elif activity_mobility:
        final_mobility = (
            activity_mobility
        )

        final_mobility_confidence = (
            "medium"
        )

    if final_mobility:
        reality[
            "summary"
        ][
            "mobility"
        ] = final_mobility

        reality[
            "summary"
        ][
            "mobility_confidence"
        ] = final_mobility_confidence

    # =========================
    # 天气体感
    # =========================

    weather_data = reality.get(
        "weather",
        {}
    )

    if (
        weather_data.get(
            "available"
        ) is True
    ):
        feels_like = (
            weather_data.get(
                "feels_like_c"
            )
        )

        if isinstance(
            feels_like,
            (int, float)
        ):
            if feels_like >= 38:
                thermal_state = (
                    "extremely_hot"
                )

            elif feels_like >= 35:
                thermal_state = (
                    "very_hot"
                )

            elif feels_like >= 30:
                thermal_state = (
                    "hot"
                )

            elif feels_like >= 24:
                thermal_state = (
                    "warm"
                )

            elif feels_like >= 16:
                thermal_state = (
                    "comfortable"
                )

            elif feels_like >= 8:
                thermal_state = (
                    "cool"
                )

            elif feels_like >= 0:
                thermal_state = (
                    "cold"
                )

            else:
                thermal_state = (
                    "very_cold"
                )

            reality[
                "summary"
            ][
                "thermal_feel"
            ] = thermal_state

    # =========================
    # 降水
    # =========================

    if (
        weather_data.get(
            "available"
        ) is True
    ):
        condition = (
            weather_data.get(
                "condition"
            )
        )

        precipitation = (
            weather_data.get(
                "precipitation_mm"
            )
        )

        rain_state = None

        if isinstance(
            condition,
            str
        ):
            condition_lower = (
                condition.lower()
            )

            if (
                "drizzle"
                in condition_lower
                or "rain"
                in condition_lower
                or "shower"
                in condition_lower
            ):
                if isinstance(
                    precipitation,
                    (int, float)
                ):
                    if (
                        precipitation
                        <= 0.5
                    ):
                        rain_state = (
                            "light_rain"
                        )

                    elif (
                        precipitation
                        <= 4
                    ):
                        rain_state = (
                            "rain"
                        )

                    else:
                        rain_state = (
                            "heavy_rain"
                        )

                else:
                    rain_state = (
                        "rain"
                    )

        if rain_state is not None:
            reality[
                "summary"
            ][
                "precipitation"
            ] = rain_state

        elif (
            isinstance(
                precipitation,
                (int, float)
            )
            and precipitation <= 0
        ):
            reality[
                "summary"
            ][
                "precipitation"
            ] = "none"

    # =========================
    # 设备电量
    # =========================

    device = reality.get(
        "device",
        {}
    )

    battery_percent = (
        device.get(
            "battery_percent"
        )
    )

    charging = (
        device.get(
            "charging"
        )
    )

    if isinstance(
        battery_percent,
        (int, float)
    ):
        if charging is True:
            power_state = (
                "charging"
            )

        elif battery_percent <= 10:
            power_state = (
                "critical"
            )

        elif battery_percent <= 20:
            power_state = (
                "low"
            )

        elif battery_percent >= 80:
            power_state = (
                "high"
            )

        else:
            power_state = (
                "normal"
            )

        reality[
            "summary"
        ][
            "device_power"
        ] = power_state

    # =========================
    # 网络
    # =========================

    network_data = reality.get(
        "network",
        {}
    )

    network_state = (
        network_data.get(
            "state"
        )
    )

    if network_state == "offline":
        reality[
            "summary"
        ][
            "connectivity"
        ] = "offline"

    elif network_state == "online":
        quality = (
            network_data.get(
                "quality"
            )
        )

        if quality == "weak":
            connectivity_value = (
                "online_weak"
            )

        elif quality == "medium":
            connectivity_value = (
                "online_normal"
            )

        elif quality == "strong":
            connectivity_value = (
                "online_strong"
            )

        else:
            connectivity_value = (
                "online"
            )

        reality[
            "summary"
        ][
            "connectivity"
        ] = connectivity_value

    # =========================
    # 光线
    # =========================

    environment = reality.get(
        "environment",
        {}
    )

    light_data = (
        environment.get(
            "light",
            {}
        )
    )

    if isinstance(
        light_data,
        dict
    ):
        light_state = (
            light_data.get(
                "state"
            )
        )

        if light_state is not None:
            reality[
                "summary"
            ][
                "ambient_light"
            ] = light_state

    # =========================
    # 声音
    # =========================

    sound_data = (
        environment.get(
            "sound",
            {}
        )
    )

    if isinstance(
        sound_data,
        dict
    ):
        sound_state = (
            sound_data.get(
                "state"
            )
        )

        if sound_state is not None:
            reality[
                "summary"
            ][
                "ambient_sound"
            ] = sound_state

    # =========================
    # Spatial 场景
    # =========================

    scene_data = (
        spatial_data.get(
            "scene"
        )
        if isinstance(
            spatial_data,
            dict
        )
        else None
    )

    if isinstance(
        scene_data,
        dict
    ):
        primary_scene = (
            scene_data.get(
                "primary_scene"
            )
        )

        secondary_scenes = (
            scene_data.get(
                "secondary_scenes",
                []
            )
        )

        scene_confidence = (
            scene_data.get(
                "confidence"
            )
        )

        if primary_scene:
            reality[
                "summary"
            ][
                "spatial_scene"
            ] = primary_scene

        if secondary_scenes:
            reality[
                "summary"
            ][
                "spatial_secondary_scenes"
            ] = secondary_scenes

        if scene_confidence:
            reality[
                "summary"
            ][
                "spatial_scene_confidence"
            ] = scene_confidence

    # =========================
    # Spatial 描述
    # =========================

    if isinstance(
        spatial_data,
        dict
    ):
        spatial_description = (
            spatial_data.get(
                "description"
            )
        )

        if spatial_description:
            reality[
                "summary"
            ][
                "spatial_description"
            ] = spatial_description

    # =========================
    # Spatial movement 摘要
    # =========================

    if spatial_movement:
        spatial_movement_summary = {
            "trend": (
                spatial_movement.get(
                    "trend"
                )
            ),

            "confidence": (
                spatial_movement.get(
                    "confidence"
                )
            ),

            "location_quality": (
                spatial_movement.get(
                    "location_quality"
                )
            ),

            "filtered_path_distance_m": (
                spatial_movement.get(
                    "filtered_path_distance_m"
                )
            ),

            "effective_net_displacement_m": (
                spatial_movement.get(
                    "effective_net_displacement_m"
                )
            ),

            "direction": (
                spatial_movement.get(
                    "direction"
                )
            )
        }

        reality[
            "summary"
        ][
            "spatial_movement"
        ] = {
            key: value
            for (
                key,
                value
            ) in spatial_movement_summary.items()
            if value is not None
        }

    # =========================
    # 最近个人地点
    # =========================

    nearest_place = None

    if isinstance(
        spatial_data,
        dict
    ):
        nearest_place = (
            spatial_data.get(
                "nearest_personal_place"
            )
        )

    if isinstance(
        nearest_place,
        dict
    ):
        nearest_place_summary = {
            "name": (
                nearest_place.get(
                    "name"
                )
            ),

            "kind": (
                nearest_place.get(
                    "kind"
                )
            ),

            "distance_m": (
                nearest_place.get(
                    "distance_m"
                )
            ),

            "inside": (
                nearest_place.get(
                    "inside"
                )
            )
        }

        reality[
            "summary"
        ][
            "nearest_personal_place"
        ] = {
            key: value
            for (
                key,
                value
            ) in nearest_place_summary.items()
            if value is not None
        }

    # =========================
    # 个人地点趋势
    # =========================

    if isinstance(
        spatial_data,
        dict
    ):
        place_trends = (
            spatial_data.get(
                "personal_place_trends"
            )
        )

        if isinstance(
            place_trends,
            list
        ):
            meaningful_trends = []

            for item in place_trends:
                if not isinstance(
                    item,
                    dict
                ):
                    continue

                trend = (
                    item.get(
                        "trend"
                    )
                )

                if trend not in (
                    "approaching",
                    "moving_away"
                ):
                    continue

                meaningful_trends.append(
                    item
                )

            if meaningful_trends:
                reality[
                    "summary"
                ][
                    "personal_place_trends"
                ] = meaningful_trends[
                    :5
                ]

    # =========================
    # 人类可理解的现实描述
    # =========================

    descriptions = []

    # ---------- 天气 ----------

    weather_parts = []

    thermal_feel = (
        reality[
            "summary"
        ].get(
            "thermal_feel"
        )
    )

    thermal_description_map = {
        "extremely_hot": (
            "体感非常炎热"
        ),

        "very_hot": (
            "体感很热"
        ),

        "hot": (
            "体感偏热"
        ),

        "warm": (
            "体感温暖"
        ),

        "comfortable": (
            "体感比较舒适"
        ),

        "cool": (
            "体感偏凉"
        ),

        "cold": (
            "体感寒冷"
        ),

        "very_cold": (
            "体感非常寒冷"
        )
    }

    if (
        thermal_feel
        in thermal_description_map
    ):
        weather_parts.append(
            thermal_description_map[
                thermal_feel
            ]
        )

    precipitation_state = (
        reality[
            "summary"
        ].get(
            "precipitation"
        )
    )

    precipitation_description_map = {
        "light_rain": (
            "正在下小雨"
        ),

        "rain": (
            "正在下雨"
        ),

        "heavy_rain": (
            "正在下较大的雨"
        ),

        "none": (
            "目前没有降水"
        )
    }

    if (
        precipitation_state
        in precipitation_description_map
    ):
        weather_parts.append(
            precipitation_description_map[
                precipitation_state
            ]
        )

    humidity = (
        weather_data.get(
            "humidity_percent"
        )
    )

    if isinstance(
        humidity,
        (int, float)
    ):
        if humidity >= 80:
            weather_parts.append(
                "空气湿度很高"
            )

        elif humidity >= 70:
            weather_parts.append(
                "空气比较潮湿"
            )

        elif humidity <= 30:
            weather_parts.append(
                "空气比较干燥"
            )

    wind_speed = (
        weather_data.get(
            "wind_speed_kmh"
        )
    )

    if isinstance(
        wind_speed,
        (int, float)
    ):
        if wind_speed >= 50:
            weather_parts.append(
                "风很强"
            )

        elif wind_speed >= 30:
            weather_parts.append(
                "风比较大"
            )

        elif wind_speed >= 15:
            weather_parts.append(
                "有比较明显的风"
            )

    if weather_parts:
        weather_description = (
            "，".join(
                weather_parts
            )
            + "。"
        )

        reality[
            "summary"
        ][
            "weather_description"
        ] = weather_description

        descriptions.append(
            weather_description.rstrip(
                "。"
            )
        )

    # ---------- 周围环境 ----------

    surroundings_parts = []

    ambient_light = (
        reality[
            "summary"
        ].get(
            "ambient_light"
        )
    )

    light_description_map = {
        "dark": (
            "周围很暗"
        ),

        "dim": (
            "周围光线较暗"
        ),

        "normal": (
            "周围光线正常"
        ),

        "bright": (
            "周围比较明亮"
        ),

        "very_bright": (
            "周围光线很强"
        )
    }

    if (
        ambient_light
        in light_description_map
    ):
        surroundings_parts.append(
            light_description_map[
                ambient_light
            ]
        )

    ambient_sound = (
        reality[
            "summary"
        ].get(
            "ambient_sound"
        )
    )

    sound_description_map = {
        "very_quiet": (
            "环境非常安静"
        ),

        "quiet": (
            "环境比较安静"
        ),

        "moderate": (
            "周围有一些环境声音"
        ),

        "loud": (
            "周围比较吵"
        ),

        "very_loud": (
            "周围非常吵"
        )
    }

    if (
        ambient_sound
        in sound_description_map
    ):
        surroundings_parts.append(
            sound_description_map[
                ambient_sound
            ]
        )

    if surroundings_parts:
        surroundings_description = (
            "，".join(
                surroundings_parts
            )
            + "。"
        )

        reality[
            "summary"
        ][
            "surroundings_description"
        ] = surroundings_description

        descriptions.append(
            surroundings_description.rstrip(
                "。"
            )
        )

    # ---------- 融合后的移动描述 ----------

    mobility = (
        reality[
            "summary"
        ].get(
            "mobility"
        )
    )

    mobility_confidence = (
        reality[
            "summary"
        ].get(
            "mobility_confidence"
        )
    )

    mobility_description_map = {
        "not_moving": (
            "手机目前没有可靠证据显示正在移动"
        ),

        "moving": (
            "手机当前存在可靠的空间移动"
        ),

        "moving_on_foot": (
            "手机正在随步行移动"
        ),

        "moving_on_foot_fast": (
            "手机正在随快速步行或跑动移动"
        ),

        "cycling": (
            "手机正在随骑行移动"
        ),

        "in_vehicle": (
            "手机正在随交通工具移动"
        )
    }

    if (
        mobility
        in mobility_description_map
    ):
        mobility_description = (
            mobility_description_map[
                mobility
            ]
            + "。"
        )

        reality[
            "summary"
        ][
            "mobility_description"
        ] = mobility_description

        descriptions.append(
            mobility_description.rstrip(
                "。"
            )
        )

    # ---------- 设备 ----------

    device_parts = []

    device_power = (
        reality[
            "summary"
        ].get(
            "device_power"
        )
    )

    power_description_map = {
        "charging": (
            "手机正在充电"
        ),

        "critical": (
            "手机电量已经非常低"
        ),

        "low": (
            "手机电量较低"
        ),

        "high": (
            "手机电量充足"
        )
    }

    if (
        device_power
        in power_description_map
    ):
        device_parts.append(
            power_description_map[
                device_power
            ]
        )

    if (
        device.get(
            "low_power_mode"
        )
        is True
    ):
        device_parts.append(
            "手机开启了低电量模式"
        )

    if device_parts:
        device_description = (
            "，".join(
                device_parts
            )
            + "。"
        )

        reality[
            "summary"
        ][
            "device_description"
        ] = device_description

        descriptions.append(
            device_description.rstrip(
                "。"
            )
        )

    # ---------- 网络 ----------

    connectivity = (
        reality[
            "summary"
        ].get(
            "connectivity"
        )
    )

    connectivity_description_map = {
        "offline": (
            "手机当前没有网络连接"
        ),

        "online_weak": (
            "手机已联网，但网络信号较弱"
        ),

        "online_normal": (
            "手机网络连接正常"
        ),

        "online_strong": (
            "手机网络连接良好"
        ),

        "online": (
            "手机当前已联网"
        )
    }

    if (
        connectivity
        in connectivity_description_map
    ):
        connectivity_description = (
            connectivity_description_map[
                connectivity
            ]
            + "。"
        )

        reality[
            "summary"
        ][
            "connectivity_description"
        ] = connectivity_description

        descriptions.append(
            connectivity_description.rstrip(
                "。"
            )
        )

    # ---------- Spatial ----------

    spatial_description = (
        reality[
            "summary"
        ].get(
            "spatial_description"
        )
    )

    if spatial_description:
        descriptions.append(
            spatial_description.rstrip(
                "。"
            )
        )

    # ---------- 综合 ----------

    if descriptions:
        reality[
            "summary"
        ][
            "overall_description"
        ] = (
            "；".join(
                descriptions
            )
            + "。"
        )

    # =========================
    # 保守情境推断
    # =========================

    inference_contexts = []

    ambient_light = (
        reality[
            "summary"
        ].get(
            "ambient_light"
        )
    )

    ambient_sound = (
        reality[
            "summary"
        ].get(
            "ambient_sound"
        )
    )

    thermal_feel = (
        reality[
            "summary"
        ].get(
            "thermal_feel"
        )
    )

    precipitation = (
        reality[
            "summary"
        ].get(
            "precipitation"
        )
    )

    # ---------- 可能的休息环境 ----------

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
            "value": (
                "resting_environment"
            ),

            "confidence": (
                "medium"
            ),

            "basis": [
                "not_moving",
                ambient_light,
                ambient_sound
            ]
        })

    # ---------- 可能的移动环境 ----------

    location_data = reality.get(
        "location",
        {}
    )

    if (
        mobility in (
            "moving",
            "moving_on_foot",
            "moving_on_foot_fast",
            "cycling",
            "in_vehicle"
        )
        and location_data.get(
            "available"
        ) is True
    ):
        inference_contexts.append({
            "value": (
                "moving_environment"
            ),

            "confidence": (
                mobility_confidence
                if mobility_confidence
                in (
                    "high",
                    "medium"
                )
                else "medium"
            ),

            "basis": [
                mobility,
                "location_available"
            ]
        })

    # ---------- 炎热环境 ----------

    if thermal_feel in (
        "very_hot",
        "extremely_hot"
    ):
        inference_contexts.append({
            "value": (
                "hot_environment"
            ),

            "confidence": (
                "high"
            ),

            "basis": [
                thermal_feel
            ]
        })

    # ---------- 雨天环境 ----------

    if precipitation in (
        "light_rain",
        "rain",
        "heavy_rain"
    ):
        inference_contexts.append({
            "value": (
                "rainy_environment"
            ),

            "confidence": (
                "high"
            ),

            "basis": [
                precipitation
            ]
        })

    # ---------- 空间环境 ----------
    #
    # 这是对 POI 分布的空间描述，
    # 不是对用户行为的推断。
    # ----------

    primary_scene = (
        reality[
            "summary"
        ].get(
            "spatial_scene"
        )
    )

    scene_confidence = (
        reality[
            "summary"
        ].get(
            "spatial_scene_confidence"
        )
    )

    if (
        primary_scene
        and scene_confidence
        in (
            "high",
            "medium"
        )
    ):
        inference_contexts.append({
            "value": (
                f"{primary_scene}_environment"
            ),

            "confidence": (
                scene_confidence
            ),

            "basis": [
                "nearby_poi_distribution"
            ]
        })

    if inference_contexts:
        reality[
            "inferences"
        ][
            "contexts"
        ] = inference_contexts

    # =========================
    # 位置数据质量
    # =========================

    accuracy = (
        location_data.get(
            "accuracy_m"
        )
    )

    if isinstance(
        accuracy,
        (int, float)
    ):
        if accuracy <= 25:
            location_quality = (
                "good"
            )

        elif accuracy <= 60:
            location_quality = (
                "usable"
            )

        elif accuracy <= 100:
            location_quality = (
                "approximate"
            )

        else:
            location_quality = (
                "poor"
            )

        reality[
            "summary"
        ][
            "location_quality"
        ] = location_quality

    # =========================
    # 清理空值
    # =========================

    cleaned_reality = {}

    for (
        key,
        value
    ) in reality.items():

        if not value:
            continue

        if isinstance(
            value,
            dict
        ):
            cleaned_value = {
                sub_key: sub_value
                for (
                    sub_key,
                    sub_value
                ) in value.items()
                if sub_value is not None
            }

            if cleaned_value:
                cleaned_reality[
                    key
                ] = cleaned_value

        else:
            cleaned_reality[
                key
            ] = value

    return cleaned_reality
