"""Weather for the home-screen widget, from Open-Meteo (free, no key).

The *service* calls out, never the browser, and only when a weather widget has a
city: the request carries a place name (geocoding) or coordinates (forecast) and
nothing else. See rules/local-first.md, case 9."""
from __future__ import annotations

import time

import httpx

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_S = 600.0

# WMO weather interpretation codes -> short label
_WMO = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Heavy showers", 85: "Snow showers", 86: "Snow showers",
    95: "Thunderstorm", 96: "Thunderstorm, hail", 99: "Thunderstorm, hail",
}


def weather_label(code) -> str:
    return _WMO.get(code, "Unknown")


def http_get(url: str, params: dict) -> dict:
    r = httpx.get(url, params=params, timeout=8.0)
    r.raise_for_status()
    return r.json()


def search_city(q: str, fetch=http_get) -> list[dict]:
    if not q.strip():
        return []
    data = fetch(GEO_URL, {"name": q.strip(), "count": 5, "language": "en", "format": "json"})
    out = []
    for r in data.get("results") or []:
        parts = [r.get("name"), r.get("admin1"), r.get("country")]
        out.append({
            "name": r.get("name"), "admin1": r.get("admin1"), "country": r.get("country"),
            "lat": r["latitude"], "lon": r["longitude"],
            "label": ", ".join(p for p in parts if p),
        })
    return out


class WeatherClient:
    def __init__(self, fetch=http_get, clock=time.monotonic):
        self._fetch = fetch
        self._clock = clock
        self._cache: dict[tuple[float, float], tuple[float, dict]] = {}

    def search(self, q: str) -> list[dict]:
        return search_city(q, self._fetch)

    def forecast(self, lat: float, lon: float) -> dict:
        key = (round(lat, 2), round(lon, 2))
        hit = self._cache.get(key)
        if hit and self._clock() - hit[0] < CACHE_S:
            return hit[1]
        data = self._fetch(FORECAST_URL, {
            "latitude": key[0], "longitude": key[1], "timezone": "auto", "forecast_days": 3,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
        })
        cur, daily = data["current"], data["daily"]
        out = {
            "temp_c": round(cur["temperature_2m"]), "feels_c": round(cur["apparent_temperature"]),
            "wind_kph": round(cur["wind_speed_10m"]),
            "code": cur["weather_code"], "label": weather_label(cur["weather_code"]),
            "hi_c": round(daily["temperature_2m_max"][0]), "lo_c": round(daily["temperature_2m_min"][0]),
            "daily": [{"date": d, "code": c, "label": weather_label(c),
                       "hi_c": round(hi), "lo_c": round(lo)}
                      for d, c, hi, lo in zip(daily["time"], daily["weather_code"],
                                              daily["temperature_2m_max"], daily["temperature_2m_min"])],
            "fetched_at": time.time(),
        }
        self._cache[key] = (self._clock(), out)
        return out
