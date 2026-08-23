import json
import math
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


AMAP_KEY = os.environ.get("AMAP_KEY", "").strip()
AMAP_BASE = "https://restapi.amap.com"


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

    p1 = math.radians(lat1)
    p2 = math.radians(lat2)

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

    return radius * c


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

    p1 = math.radians(lat1)
    p2 = math.radians(lat2)

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
            "info": data.get(
                "info"
            ),
            "infocode": data.get(
                "infocode"
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

    roads = regeocode.get(
        "roads",
        []
    )

    if not isinstance(
        roads,
        list
    ):
        roads = []

    pois = regeocode.get(
        "pois",
        []
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
            "id": poi.get(
                "id"
            ),
            "name": poi.get(
                "name"
            ),
            "type": poi.get(
                "type"
            ),
            "typecode": poi.get(
                "typecode"
            ),
            "address": poi.get(
                "address"
            ),
            "direction": poi.get(
                "direction"
            ),
            "distance_m": (
                _safe_float(
                    poi.get(
                        "distance"
                    )
                )
            ),
            "location": poi.get(
                "location"
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
            "id": poi.get(
                "id"
            ),
            "name": poi.get(
                "name"
            ),
            "type": poi.get(
                "type"
            ),
            "typecode": poi.get(
                "typecode"
            ),
            "address": poi.get(
                "address"
            ),
            "distance_m": (
                _safe_float(
                    poi.get(
                        "distance"
                    )
                )
            ),
            "location": poi.get(
                "location"
            ),
            "province": poi.get(
                "pname"
            ),
            "city": poi.get(
                "cityname"
            ),
            "district": poi.get(
                "adname"
            )
        })

    return {
        "available": True,
        "provider": "amap",
        "count": len(
            pois
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

    path = path_map.get(
        mode
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

    data = result.get(
        "data",
        {}
    )

    route = data.get(
        "route",
        {}
    )

    if not isinstance(
        route,
        dict
    ):
        return {
            "available": False,
            "provider": "amap",
            "reason": (
                "missing_route"
            )
        }

    paths = route.get(
        "paths",
        []
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

        cost = item.get(
            "cost"
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

        "paths": normalized
    }


# =========================
# 路线规划
#
# 输入为 GPS/WGS84
# 内部转换为高德坐标
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
# 空间场景分类
# =========================

def classify_scene(
    nearby_pois
):
    if not isinstance(
        nearby_pois,
        list
    ):
        return None

    text = " ".join(
        str(
            item.get(
                "type",
                ""
            )
        )
        for item in nearby_pois
        if isinstance(
            item,
            dict
        )
    )

    rules = [
        (
            "transport_hub",
            (
                "交通设施",
                "火车站",
                "机场",
                "长途汽车站",
                "地铁站"
            )
        ),

        (
            "park_or_scenic",
            (
                "风景名胜",
                "公园广场",
                "公园"
            )
        ),

        (
            "education",
            (
                "科教文化",
                "学校"
            )
        ),

        (
            "medical",
            (
                "医疗保健",
                "医院"
            )
        ),

        (
            "commercial",
            (
                "购物服务",
                "餐饮服务",
                "生活服务"
            )
        ),

        (
            "residential",
            (
                "商务住宅",
                "住宅区"
            )
        )
    ]

    for (
        scene,
        keywords
    ) in rules:

        if any(
            keyword in text
            for keyword
            in keywords
        ):
            return scene

    return None


# =========================
# 人类可读空间描述
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

    scene_map = {
        "transport_hub": (
            "周边具有明显的交通枢纽特征"
        ),
        "park_or_scenic": (
            "周边以公园或景点设施为显著特征"
        ),
        "education": (
            "周边教育文化设施较明显"
        ),
        "medical": (
            "周边医疗设施较明显"
        ),
        "commercial": (
            "周边商业与生活服务设施较多"
        ),
        "residential": (
            "周边具有明显的住宅生活区特征"
        )
    }

    if scene in scene_map:
        parts.append(
            scene_map[
                scene
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
