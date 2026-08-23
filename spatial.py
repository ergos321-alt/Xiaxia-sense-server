import json
import math
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


AMAP_KEY = os.environ.get(
    "AMAP_KEY",
    ""
).strip()

AMAP_BASE = (
    "https://restapi.amap.com"
)


# =========================
# 基础工具
# =========================

def _safe_float(value):
    try:
        if value is None:
            return None

        return float(value)

    except Exception:
        return None


def haversine_m(
    lat1,
    lon1,
    lat2,
    lon2
):
    lat1 = _safe_float(lat1)
    lon1 = _safe_float(lon1)

    lat2 = _safe_float(lat2)
    lon2 = _safe_float(lon2)

    if None in (
        lat1,
        lon1,
        lat2,
        lon2
    ):
        return None

    radius = 6371008.8

    p1 = math.radians(
        lat1
    )

    p2 = math.radians(
        lat2
    )

    dlat = math.radians(
        lat2 - lat1
    )

    dlon = math.radians(
        lon2 - lon1
    )

    a = (
        math.sin(
            dlat / 2
        ) ** 2
        + math.cos(p1)
        * math.cos(p2)
        * math.sin(
            dlon / 2
        ) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(
            1 - a
        )
    )

    return (
        radius * c
    )


def bearing_deg(
    lat1,
    lon1,
    lat2,
    lon2
):
    lat1 = _safe_float(lat1)
    lon1 = _safe_float(lon1)

    lat2 = _safe_float(lat2)
    lon2 = _safe_float(lon2)

    if None in (
        lat1,
        lon1,
        lat2,
        lon2
    ):
        return None

    p1 = math.radians(
        lat1
    )

    p2 = math.radians(
        lat2
    )

    dlon = math.radians(
        lon2 - lon1
    )

    y = (
        math.sin(dlon)
        * math.cos(p2)
    )

    x = (
        math.cos(p1)
        * math.sin(p2)
        - math.sin(p1)
        * math.cos(p2)
        * math.cos(dlon)
    )

    degree = (
        math.degrees(
            math.atan2(
                y,
                x
            )
        )
        + 360
    ) % 360

    return round(
        degree,
        1
    )


def bearing_label(
    degree
):
    if not isinstance(
        degree,
        (int, float)
    ):
        return None

    labels = [
        "north",
        "northeast",
        "east",
        "southeast",
        "south",
        "southwest",
        "west",
        "northwest"
    ]

    index = int(
        (
            degree + 22.5
        )
        // 45
    ) % 8

    return labels[index]


# =========================
# GPS 数据质量
# =========================

def location_quality_from_accuracy(
    accuracy_m
):
    accuracy_m = _safe_float(
        accuracy_m
    )

    if accuracy_m is None:
        return "unknown"

    if accuracy_m <= 25:
        return "good"

    if accuracy_m <= 60:
        return "usable"

    if accuracy_m <= 100:
        return "approximate"

    return "poor"


def segment_uncertainty_m(
    first_accuracy,
    second_accuracy
):
    first_accuracy = _safe_float(
        first_accuracy
    )

    second_accuracy = _safe_float(
        second_accuracy
    )

    accuracies = [
        value
        for value in (
            first_accuracy,
            second_accuracy
        )
        if value is not None
    ]

    if not accuracies:
        return 30.0

    average_accuracy = (
        sum(accuracies)
        / len(accuracies)
    )

    return max(
        25.0,
        average_accuracy * 1.15
    )


# =========================
# 高德请求基础层
# =========================

def _amap_get(
    path,
    params,
    timeout=8
):
    if not AMAP_KEY:
        return {
            "available": False,
            "provider": "amap",
            "reason": (
                "amap_key_not_configured"
            )
        }

    query = dict(
        params or {}
    )

    query["key"] = (
        AMAP_KEY
    )

    query["output"] = (
        "JSON"
    )

    url = (
        AMAP_BASE
        + path
        + "?"
        + urlencode(
            query
        )
    )

    request = Request(
        url,
        headers={
            "User-Agent": (
                "Xiaxia-Sense-Server/1.0"
            )
        }
    )

    try:
        with urlopen(
            request,
            timeout=timeout
        ) as response:

            raw = (
                response.read()
                .decode(
                    "utf-8"
                )
            )

        data = json.loads(
            raw
        )

    except (
        HTTPError,
        URLError,
        TimeoutError,
        ValueError
    ) as exc:

        return {
            "available": False,
            "provider": "amap",
            "reason": (
                "provider_request_failed"
            ),
            "detail": str(exc)
        }

    if not isinstance(
        data,
        dict
    ):
        return {
            "available": False,
            "provider": "amap",
            "reason": (
                "invalid_provider_response"
            )
        }

    if str(
        data.get(
            "status"
        )
    ) != "1":

        return {
            "available": False,
            "provider": "amap",
            "reason": (
                "provider_error"
            ),
            "info": (
                data.get(
                    "info"
                )
            ),
            "infocode": (
                data.get(
                    "infocode"
                )
            )
        }

    return {
        "available": True,
        "provider": "amap",
        "data": data
    }


# =========================
# GPS → 高德坐标
# =========================

def convert_gps_to_amap(
    latitude,
    longitude
):
    latitude = _safe_float(
        latitude
    )

    longitude = _safe_float(
        longitude
    )

    if (
        latitude is None
        or longitude is None
    ):
        return {
            "available": False,
            "reason": (
                "invalid_coordinates"
            )
        }

    result = _amap_get(
        "/v3/assistant/coordinate/convert",
        {
            "locations": (
                f"{longitude:.6f},"
                f"{latitude:.6f}"
            ),
            "coordsys": "gps"
        }
    )

    if not result.get(
        "available"
    ):
        return result

    location_string = (
        result.get(
            "data",
            {}
        ).get(
            "locations"
        )
    )

    if not isinstance(
        location_string,
        str
    ):
        return {
            "available": False,
            "provider": "amap",
            "reason": (
                "missing_converted_coordinates"
            )
        }

    first = (
        location_string
        .split(";")[0]
    )

    try:
        (
            lon_text,
            lat_text
        ) = first.split(
            ",",
            1
        )

        amap_lon = float(
            lon_text
        )

        amap_lat = float(
            lat_text
        )

    except Exception:
        return {
            "available": False,
            "provider": "amap",
            "reason": (
                "invalid_converted_coordinates"
            )
        }

    return {
        "available": True,
        "provider": "amap",
        "coordinate_system": (
            "gcj02"
        ),
        "latitude": (
            amap_lat
        ),
        "longitude": (
            amap_lon
        )
    }


# =========================
# 逆地理编码
# =========================

def reverse_geocode(
    latitude,
    longitude,
    radius_m=1000
):
    latitude = _safe_float(
        latitude
    )

    longitude = _safe_float(
        longitude
    )

    if (
        latitude is None
        or longitude is None
    ):
        return {
            "available": False,
            "reason": (
                "invalid_coordinates"
            )
        }

    radius_m = max(
        0,
        min(
            int(radius_m),
            3000
        )
    )

    result = _amap_get(
        "/v3/geocode/regeo",
        {
            "location": (
                f"{longitude:.6f},"
                f"{latitude:.6f}"
            ),
            "radius": (
                radius_m
            ),
            "extensions": "all",
            "roadlevel": 0
        }
    )

    if not result.get(
        "available"
    ):
        return result

    regeocode = (
        result.get(
            "data",
            {}
        ).get(
            "regeocode",
            {}
        )
    )

    if not isinstance(
        regeocode,
        dict
    ):
        return {
            "available": False,
            "provider": "amap",
            "reason": (
                "missing_regeocode"
            )
        }

    component = (
        regeocode.get(
            "addressComponent",
            {}
        )
    )

    if not isinstance(
        component,
        dict
    ):
        component = {}

    street_number = (
        component.get(
            "streetNumber",
            {}
        )
    )

    if not isinstance(
        street_number,
        dict
    ):
        street_number = {}

    roads = (
        regeocode.get(
            "roads",
            []
        )
    )

    if not isinstance(
        roads,
        list
    ):
        roads = []

    pois = (
        regeocode.get(
            "pois",
            []
        )
    )

    if not isinstance(
        pois,
        list
    ):
        pois = []

    normalized_pois = []

    for poi in pois[:20]:

        if not isinstance(
            poi,
            dict
        ):
            continue

        normalized_pois.append({
            "id": (
                poi.get(
                    "id"
                )
            ),
            "name": (
                poi.get(
                    "name"
                )
            ),
            "type": (
                poi.get(
                    "type"
                )
            ),
            "typecode": (
                poi.get(
                    "typecode"
                )
            ),
            "address": (
                poi.get(
                    "address"
                )
            ),
            "direction": (
                poi.get(
                    "direction"
                )
            ),
            "distance_m": (
                _safe_float(
                    poi.get(
                        "distance"
                    )
                )
            ),
            "location": (
                poi.get(
                    "location"
                )
            )
        })

    nearest_road = None

    if roads:
        first_road = (
            roads[0]
        )

        if isinstance(
            first_road,
            dict
        ):
            nearest_road = {
                "name": (
                    first_road.get(
                        "name"
                    )
                ),
                "distance_m": (
                    _safe_float(
                        first_road.get(
                            "distance"
                        )
                    )
                ),
                "direction": (
                    first_road.get(
                        "direction"
                    )
                )
            }

    return {
        "available": True,
        "provider": "amap",

        "formatted_address": (
            regeocode.get(
                "formatted_address"
            )
        ),

        "country": (
            component.get(
                "country"
            )
        ),

        "province": (
            component.get(
                "province"
            )
        ),

        "city": (
            component.get(
                "city"
            )
        ),

        "citycode": (
            component.get(
                "citycode"
            )
        ),

        "district": (
            component.get(
                "district"
            )
        ),

        "adcode": (
            component.get(
                "adcode"
            )
        ),

        "township": (
            component.get(
                "township"
            )
        ),

        "towncode": (
            component.get(
                "towncode"
            )
        ),

        "street": (
            street_number.get(
                "street"
            )
        ),

        "street_number": (
            street_number.get(
                "number"
            )
        ),

        "nearest_road": (
            nearest_road
        ),

        "nearby_pois": (
            normalized_pois
        )
    }


# =========================
# 周边 POI 搜索
# =========================

def nearby_search(
    latitude,
    longitude,
    keywords=None,
    types=None,
    radius_m=1000,
    page_size=20
):
    latitude = _safe_float(
        latitude
    )

    longitude = _safe_float(
        longitude
    )

    if (
        latitude is None
        or longitude is None
    ):
        return {
            "available": False,
            "reason": (
                "invalid_coordinates"
            )
        }

    radius_m = max(
        0,
        min(
            int(radius_m),
            50000
        )
    )

    page_size = max(
        1,
        min(
            int(page_size),
            25
        )
    )

    params = {
        "location": (
            f"{longitude:.6f},"
            f"{latitude:.6f}"
        ),
        "radius": (
            radius_m
        ),
        "sortrule": (
            "distance"
        ),
        "page_size": (
            page_size
        )
    }

    if keywords:
        params[
            "keywords"
        ] = keywords

    if types:
        params[
            "types"
        ] = types

    result = _amap_get(
        "/v5/place/around",
        params
    )

    if not result.get(
        "available"
    ):
        return result

    raw_pois = (
        result.get(
            "data",
            {}
        ).get(
            "pois",
            []
        )
    )

    if not isinstance(
        raw_pois,
        list
    ):
        raw_pois = []

    pois = []

    for poi in raw_pois:

        if not isinstance(
            poi,
            dict
        ):
            continue

        pois.append({
            "id": (
                poi.get(
                    "id"
                )
            ),
            "name": (
                poi.get(
                    "name"
                )
            ),
            "type": (
                poi.get(
                    "type"
                )
            ),
            "typecode": (
                poi.get(
                    "typecode"
                )
            ),
            "address": (
                poi.get(
                    "address"
                )
            ),
            "distance_m": (
                _safe_float(
                    poi.get(
                        "distance"
                    )
                )
            ),
            "location": (
                poi.get(
                    "location"
                )
            ),
            "province": (
                poi.get(
                    "pname"
                )
            ),
            "city": (
                poi.get(
                    "cityname"
                )
            ),
            "district": (
                poi.get(
                    "adname"
                )
            )
        })

    return {
        "available": True,
        "provider": "amap",
        "count": (
            len(
                pois
            )
        ),
        "pois": pois
    }


# =========================
# 路线规划底层
# =========================

def _route_path(
    origin_latitude,
    origin_longitude,
    destination_latitude,
    destination_longitude,
    mode
):
    origin_latitude = (
        _safe_float(
            origin_latitude
        )
    )

    origin_longitude = (
        _safe_float(
            origin_longitude
        )
    )

    destination_latitude = (
        _safe_float(
            destination_latitude
        )
    )

    destination_longitude = (
        _safe_float(
            destination_longitude
        )
    )

    if None in (
        origin_latitude,
        origin_longitude,
        destination_latitude,
        destination_longitude
    ):
        return {
            "available": False,
            "reason": (
                "invalid_coordinates"
            )
        }

    path_map = {
        "walking": (
            "/v5/direction/walking"
        ),

        "driving": (
            "/v5/direction/driving"
        ),

        "cycling": (
            "/v5/direction/bicycling"
        ),

        "electrobike": (
            "/v5/direction/electrobike"
        )
    }

    path = (
        path_map.get(
            mode
        )
    )

    if path is None:
        return {
            "available": False,

            "reason": (
                "unsupported_route_mode"
            ),

            "supported_modes": [
                "walking",
                "driving",
                "cycling",
                "electrobike"
            ]
        }

    result = _amap_get(
        path,
        {
            "origin": (
                f"{origin_longitude:.6f},"
                f"{origin_latitude:.6f}"
            ),

            "destination": (
                f"{destination_longitude:.6f},"
                f"{destination_latitude:.6f}"
            )
        }
    )

    if not result.get(
        "available"
    ):
        return result

    data = (
        result.get(
            "data",
            {}
        )
    )

    route_data = (
        data.get(
            "route",
            {}
        )
    )

    if not isinstance(
        route_data,
        dict
    ):
        return {
            "available": False,
            "provider": "amap",
            "reason": (
                "missing_route"
            )
        }

    paths = (
        route_data.get(
            "paths",
            []
        )
    )

    if not isinstance(
        paths,
        list
    ):
        paths = []

    normalized = []

    for item in paths[:3]:

        if not isinstance(
            item,
            dict
        ):
            continue

        distance_m = (
            _safe_float(
                item.get(
                    "distance"
                )
            )
        )

        cost = (
            item.get(
                "cost"
            )
        )

        duration_s = None

        if isinstance(
            cost,
            dict
        ):
            duration_s = (
                _safe_float(
                    cost.get(
                        "duration"
                    )
                )
            )

        if duration_s is None:
            duration_s = (
                _safe_float(
                    item.get(
                        "duration"
                    )
                )
            )

        normalized.append({
            "distance_m": (
                round(
                    distance_m
                )
                if distance_m
                is not None
                else None
            ),

            "duration_seconds": (
                round(
                    duration_s
                )
                if duration_s
                is not None
                else None
            ),

            "duration_minutes": (
                round(
                    duration_s
                    / 60
                )
                if duration_s
                is not None
                else None
            )
        })

    return {
        "available": True,
        "provider": "amap",
        "mode": mode,

        "origin": {
            "latitude": (
                origin_latitude
            ),
            "longitude": (
                origin_longitude
            )
        },

        "destination": {
            "latitude": (
                destination_latitude
            ),
            "longitude": (
                destination_longitude
            )
        },

        "paths": (
            normalized
        )
    }


# =========================
# 路线规划
# =========================

def route(
    origin_latitude,
    origin_longitude,
    destination_latitude,
    destination_longitude,
    mode="walking"
):
    origin_conversion = (
        convert_gps_to_amap(
            origin_latitude,
            origin_longitude
        )
    )

    destination_conversion = (
        convert_gps_to_amap(
            destination_latitude,
            destination_longitude
        )
    )

    if not origin_conversion.get(
        "available"
    ):
        return origin_conversion

    if not destination_conversion.get(
        "available"
    ):
        return destination_conversion

    return _route_path(
        origin_conversion[
            "latitude"
        ],
        origin_conversion[
            "longitude"
        ],
        destination_conversion[
            "latitude"
        ],
        destination_conversion[
            "longitude"
        ],
        mode
    )


# =========================
# POI 场景分类
#
# 不再使用“命中第一个类型”
# 改为：
#
# POI 类型权重
# ×
# 距离权重
#
# 最终产生主场景 + 次级场景
# =========================

SCENE_RULES = {
    "residential": {
        "base_weight": 2.4,
        "keywords": (
            "商务住宅",
            "住宅区",
            "住宅小区",
            "别墅"
        )
    },

    "commercial": {
        "base_weight": 1.4,
        "keywords": (
            "购物服务",
            "餐饮服务",
            "生活服务",
            "商业"
        )
    },

    "park_or_scenic": {
        "base_weight": 1.3,
        "keywords": (
            "风景名胜",
            "公园广场",
            "公园",
            "景点"
        )
    },

    "education": {
        "base_weight": 1.2,
        "keywords": (
            "科教文化服务",
            "学校",
            "幼儿园",
            "大学",
            "中学",
            "小学"
        )
    },

    "medical": {
        "base_weight": 1.2,
        "keywords": (
            "医疗保健服务",
            "医院",
            "诊所"
        )
    },

    "transport_hub": {
        "base_weight": 1.7,
        "keywords": (
            "交通设施服务",
            "火车站",
            "机场",
            "汽车站",
            "地铁站",
            "公交车站"
        )
    },

    "lodging": {
        "base_weight": 1.0,
        "keywords": (
            "住宿服务",
            "宾馆酒店",
            "酒店",
            "旅馆"
        )
    }
}


def poi_distance_weight(
    distance_m
):
    distance_m = _safe_float(
        distance_m
    )

    if distance_m is None:
        return 0.5

    if distance_m <= 100:
        return 1.0

    if distance_m <= 250:
        return 0.8

    if distance_m <= 500:
        return 0.6

    if distance_m <= 1000:
        return 0.4

    return 0.2


def classify_scene(
    nearby_pois
):
    if not isinstance(
        nearby_pois,
        list
    ):
        return {
            "primary_scene": None,
            "secondary_scenes": [],
            "scores": {}
        }

    scores = {
        scene: 0.0
        for scene
        in SCENE_RULES
    }

    evidence_count = {
        scene: 0
        for scene
        in SCENE_RULES
    }

    for poi in nearby_pois:

        if not isinstance(
            poi,
            dict
        ):
            continue

        poi_type = str(
            poi.get(
                "type",
                ""
            )
        )

        distance_weight = (
            poi_distance_weight(
                poi.get(
                    "distance_m"
                )
            )
        )

        for (
            scene,
            rule
        ) in SCENE_RULES.items():

            if any(
                keyword in poi_type
                for keyword
                in rule[
                    "keywords"
                ]
            ):
                score = (
                    rule[
                        "base_weight"
                    ]
                    * distance_weight
                )

                scores[
                    scene
                ] += score

                evidence_count[
                    scene
                ] += 1

    ranked = sorted(
        scores.items(),
        key=lambda item: (
            item[1]
        ),
        reverse=True
    )

    if (
        not ranked
        or ranked[0][1] <= 0
    ):
        return {
            "primary_scene": None,
            "secondary_scenes": [],
            "scores": {},
            "evidence_count": {}
        }

    primary_scene = (
        ranked[0][0]
    )

    primary_score = (
        ranked[0][1]
    )

    secondary_scenes = []

    for (
        scene,
        score
    ) in ranked[1:]:

        if score <= 0:
            continue

        if (
            score
            >= primary_score * 0.35
        ):
            secondary_scenes.append(
                scene
            )

    positive_scores = {
        scene: round(
            score,
            2
        )
        for (
            scene,
            score
        ) in ranked
        if score > 0
    }

    positive_evidence = {
        scene: count
        for (
            scene,
            count
        ) in evidence_count.items()
        if count > 0
    }

    if (
        primary_score >= 4
        and (
            len(ranked) < 2
            or ranked[1][1]
            <= primary_score * 0.5
        )
    ):
        confidence = "high"

    elif primary_score >= 2:
        confidence = "medium"

    else:
        confidence = "low"

    return {
        "primary_scene": (
            primary_scene
        ),

        "secondary_scenes": (
            secondary_scenes[:3]
        ),

        "confidence": (
            confidence
        ),

        "scores": (
            positive_scores
        ),

        "evidence_count": (
            positive_evidence
        )
    }


# =========================
# GPS 运动分析
#
# 核心原则：
#
# 1. GPS 点之间的距离必须先扣除
#    定位精度造成的不确定区间。
#
# 2. Activity=stationary 时，
#    GPS 必须提供更强证据才能宣布移动。
#
# 3. GPS 精度很差时，
#    宁愿输出 uncertain，
#    也不制造虚假移动。
# =========================

def analyze_movement(
    history,
    activity_state=None
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
        return {
            "available": False,
            "trend": (
                "insufficient_history"
            )
        }

    raw_path_distance = 0.0
    filtered_path_distance = 0.0
    ignored_drift_distance = 0.0

    valid_segment_count = 0
    ignored_segment_count = 0

    for (
        first,
        second
    ) in zip(
        history,
        history[1:]
    ):

        segment = (
            haversine_m(
                first.get(
                    "latitude"
                ),
                first.get(
                    "longitude"
                ),
                second.get(
                    "latitude"
                ),
                second.get(
                    "longitude"
                )
            )
        )

        if segment is None:
            continue

        raw_path_distance += (
            segment
        )

        uncertainty = (
            segment_uncertainty_m(
                first.get(
                    "accuracy_m"
                ),
                second.get(
                    "accuracy_m"
                )
            )
        )

        if segment <= uncertainty:
            ignored_drift_distance += (
                segment
            )

            ignored_segment_count += 1

            continue

        effective_distance = max(
            0.0,
            segment - uncertainty
        )

        if effective_distance <= 10:
            ignored_drift_distance += (
                segment
            )

            ignored_segment_count += 1

            continue

        filtered_path_distance += (
            effective_distance
        )

        valid_segment_count += 1

    first = (
        history[0]
    )

    last = (
        history[-1]
    )

    raw_net_displacement = (
        haversine_m(
            first.get(
                "latitude"
            ),
            first.get(
                "longitude"
            ),
            last.get(
                "latitude"
            ),
            last.get(
                "longitude"
            )
        )
    )

    first_accuracy = (
        _safe_float(
            first.get(
                "accuracy_m"
            )
        )
    )

    last_accuracy = (
        _safe_float(
            last.get(
                "accuracy_m"
            )
        )
    )

    endpoint_uncertainty = (
        segment_uncertainty_m(
            first_accuracy,
            last_accuracy
        )
    )

    if raw_net_displacement is None:
        effective_net_displacement = (
            None
        )

    else:
        effective_net_displacement = max(
            0.0,
            raw_net_displacement
            - endpoint_uncertainty
        )

    duration_seconds = max(
        0,
        last.get(
            "recorded_at",
            0
        )
        - first.get(
            "recorded_at",
            0
        )
    )

    bearing = None

    if (
        effective_net_displacement
        is not None
        and effective_net_displacement
        >= 30
    ):
        bearing = (
            bearing_deg(
                first.get(
                    "latitude"
                ),
                first.get(
                    "longitude"
                ),
                last.get(
                    "latitude"
                ),
                last.get(
                    "longitude"
                )
            )
        )

    accuracy_values = [
        _safe_float(
            point.get(
                "accuracy_m"
            )
        )
        for point in history
    ]

    accuracy_values = [
        value
        for value
        in accuracy_values
        if value is not None
    ]

    average_accuracy = None

    if accuracy_values:
        average_accuracy = (
            sum(
                accuracy_values
            )
            / len(
                accuracy_values
            )
        )

    location_quality = (
        location_quality_from_accuracy(
            average_accuracy
        )
    )

    activity_moving_states = (
        "walking",
        "running",
        "cycling",
        "in_vehicle"
    )

    activity_says_moving = (
        activity_state
        in activity_moving_states
    )

    activity_says_stationary = (
        activity_state
        == "stationary"
    )

    # =========================
    # 融合判定
    # =========================

    movement_evidence_strong = (
        filtered_path_distance
        >= 150
        or (
            effective_net_displacement
            is not None
            and effective_net_displacement
            >= 100
        )
    )

    movement_evidence_medium = (
        filtered_path_distance
        >= 60
        or (
            effective_net_displacement
            is not None
            and effective_net_displacement
            >= 50
        )
    )

    if activity_says_stationary:

        if (
            location_quality == "poor"
            and not movement_evidence_strong
        ):
            trend = "stable"
            confidence = "medium"

        elif movement_evidence_strong:
            trend = "moving"
            confidence = "medium"

        else:
            trend = "stable"
            confidence = "high"

    elif activity_says_moving:

        if movement_evidence_medium:
            trend = "moving"
            confidence = "high"

        elif location_quality == "poor":
            trend = "moving"
            confidence = "medium"

        else:
            trend = "moving"
            confidence = "medium"

    else:

        if movement_evidence_strong:
            trend = "moving"
            confidence = "high"

        elif movement_evidence_medium:
            trend = "moving"
            confidence = "medium"

        elif location_quality == "poor":
            trend = "uncertain"
            confidence = "low"

        else:
            trend = "stable"
            confidence = "medium"

    return {
        "available": True,

        "trend": (
            trend
        ),

        "confidence": (
            confidence
        ),

        "activity_state": (
            activity_state
        ),

        "sample_count": (
            len(
                history
            )
        ),

        "valid_segment_count": (
            valid_segment_count
        ),

        "ignored_segment_count": (
            ignored_segment_count
        ),

        "window_seconds": (
            duration_seconds
        ),

        "location_quality": (
            location_quality
        ),

        "average_accuracy_m": (
            round(
                average_accuracy,
                1
            )
            if average_accuracy
            is not None
            else None
        ),

        "raw_path_distance_m": (
            round(
                raw_path_distance,
                1
            )
        ),

        "filtered_path_distance_m": (
            round(
                filtered_path_distance,
                1
            )
        ),

        "ignored_drift_distance_m": (
            round(
                ignored_drift_distance,
                1
            )
        ),

        "raw_net_displacement_m": (
            round(
                raw_net_displacement,
                1
            )
            if raw_net_displacement
            is not None
            else None
        ),

        "effective_net_displacement_m": (
            round(
                effective_net_displacement,
                1
            )
            if effective_net_displacement
            is not None
            else None
        ),

        "bearing_deg": (
            bearing
        ),

        "direction": (
            bearing_label(
                bearing
            )
        )
    }


# =========================
# 与个人地点关系
# =========================

def build_spatial_description(
    address,
    scene,
    nearest_place
):
    parts = []

    if isinstance(
        address,
        dict
    ):
        formatted = (
            address.get(
                "formatted_address"
            )
        )

        if formatted:
            parts.append(
                f"当前位置约在{formatted}"
            )

    primary_scene = None
    secondary_scenes = []

    if isinstance(
        scene,
        dict
    ):
        primary_scene = (
            scene.get(
                "primary_scene"
            )
        )

        secondary_scenes = (
            scene.get(
                "secondary_scenes",
                []
            )
        )

    elif isinstance(
        scene,
        str
    ):
        primary_scene = (
            scene
        )

    scene_map = {
        "transport_hub": (
            "周边具有明显的交通设施特征"
        ),

        "park_or_scenic": (
            "周边公园或景观设施较明显"
        ),

        "education": (
            "周边教育文化设施较明显"
        ),

        "medical": (
            "周边医疗设施较明显"
        ),

        "commercial": (
            "周边商业与生活服务设施较明显"
        ),

        "residential": (
            "周边以住宅生活区为主要空间特征"
        ),

        "lodging": (
            "周边住宿设施较明显"
        )
    }

    if primary_scene in scene_map:
        parts.append(
            scene_map[
                primary_scene
            ]
        )

    secondary_map = {
        "commercial": (
            "同时有一定商业生活设施"
        ),

        "park_or_scenic": (
            "附近也有公园或景观设施"
        ),

        "education": (
            "附近也有教育设施"
        ),

        "medical": (
            "附近也有医疗设施"
        ),

        "transport_hub": (
            "附近也有交通设施"
        ),

        "lodging": (
            "附近也有住宿设施"
        ),

        "residential": (
            "附近也有住宅设施"
        )
    }

    if secondary_scenes:
        secondary = (
            secondary_scenes[0]
        )

        if secondary in secondary_map:
            parts.append(
                secondary_map[
                    secondary
                ]
            )

    if isinstance(
        nearest_place,
        dict
    ):
        name = (
            nearest_place.get(
                "name"
            )
        )

        distance = (
            nearest_place.get(
                "distance_m"
            )
        )

        inside = (
            nearest_place.get(
                "inside"
            )
        )

        if name:

            if inside:
                parts.append(
                    f"目前位于个人地点“{name}”范围内"
                )

            elif isinstance(
                distance,
                (int, float)
            ):
                parts.append(
                    f"距离个人地点“{name}”约"
                    f"{round(distance)}米"
                )

    if not parts:
        return None

    return (
        "；".join(
            parts
        )
        + "。"
    )
