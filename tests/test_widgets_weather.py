import httpx
import pytest
from fastapi.testclient import TestClient

from io_assistant.service.app import create_app
from io_assistant.widgets.weather import WeatherClient, search_city, weather_label

GEO = {"results": [
    {"name": "Lahore", "latitude": 31.55, "longitude": 74.34, "country": "Pakistan",
     "admin1": "Punjab"},
    {"name": "Lahore", "latitude": 30.0, "longitude": 70.0, "country": "Pakistan"}]}
FORECAST = {
    "current": {"temperature_2m": 31.6, "apparent_temperature": 35.2, "weather_code": 2,
                "wind_speed_10m": 12.4},
    "daily": {"time": ["2026-09-22", "2026-09-23", "2026-09-24"],
              "weather_code": [2, 61, 0],
              "temperature_2m_max": [34.1, 30.2, 33.9],
              "temperature_2m_min": [24.6, 23.1, 24.0]}}


def test_weather_labels():
    assert weather_label(0) == "Clear"
    assert weather_label(61) == "Light rain"
    assert weather_label(999) == "Unknown"


def test_search_city_parses_and_labels_results():
    seen = []
    res = search_city("Lahore", lambda url, params: seen.append(params) or GEO)
    assert seen[0]["name"] == "Lahore"
    assert res[0] == {"name": "Lahore", "admin1": "Punjab", "country": "Pakistan",
                      "lat": 31.55, "lon": 74.34, "label": "Lahore, Punjab, Pakistan"}
    assert res[1]["label"] == "Lahore, Pakistan"          # no admin1


def test_blank_search_makes_no_request():
    def boom(url, params):
        raise AssertionError("must not fetch")
    assert search_city("   ", boom) == []


def test_forecast_is_parsed_and_rounded():
    w = WeatherClient(lambda url, params: FORECAST, clock=lambda: 0.0).forecast(31.55, 74.34)
    assert (w["temp_c"], w["feels_c"], w["wind_kph"]) == (32, 35, 12)
    assert w["label"] == "Partly cloudy" and (w["hi_c"], w["lo_c"]) == (34, 25)
    assert [d["label"] for d in w["daily"]] == ["Partly cloudy", "Light rain", "Clear"]
    assert w["daily"][1]["date"] == "2026-09-23"


def test_forecasts_are_cached_for_ten_minutes():
    calls, now = [], [0.0]
    c = WeatherClient(lambda url, params: calls.append(1) or FORECAST, clock=lambda: now[0])
    c.forecast(31.55, 74.34)
    c.forecast(31.551, 74.339)                 # same place at 2 dp
    assert len(calls) == 1
    now[0] = 601.0
    c.forecast(31.55, 74.34)
    assert len(calls) == 2


def _client(config, fetch):
    app = create_app(config, orchestrator=object(), engine=object(),
                     conversations=object(), voice=object())
    app.state.weather = WeatherClient(fetch)
    return TestClient(app)


def test_endpoints(config):
    def fetch(url, params):
        return GEO if "geocoding" in url else FORECAST
    with _client(config, fetch) as c:
        assert c.get("/weather/search", params={"q": "Lahore"}).json()[0]["name"] == "Lahore"
        assert c.get("/weather/search", params={"q": ""}).json() == []
        assert c.get("/weather", params={"lat": 31.55, "lon": 74.34}).json()["temp_c"] == 32
        assert c.get("/weather", params={"lat": 91, "lon": 0}).status_code == 422


def test_upstream_failure_is_a_readable_502(config):
    def fetch(url, params):
        raise httpx.ConnectError("no network")
    with _client(config, fetch) as c:
        r = c.get("/weather", params={"lat": 1, "lon": 2})
    assert r.status_code == 502 and "weather" in r.json()["detail"].lower()
