import json

import pytest

from jarvis.tools.web import WebClient, WebError, _check_public_url, format_results, format_weather, html_to_text


def test_html_to_text_drops_scripts():
    text = html_to_text("<html><head><title>t</title></head><body><script>evil()</script>"
                        "<h1>Hello</h1><p>World &amp; more</p><style>x{}</style></body></html>")
    assert text == "Hello\nWorld & more"


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost:8080/", "http://10.0.0.5/",
                                 "http://192.168.1.1/admin", "file:///etc/passwd", "ftp://example.com/"])
def test_private_and_non_http_blocked(url):
    with pytest.raises(WebError):
        _check_public_url(url)


def test_tavily_request_and_errors():
    seen = {}

    def t(method, url, headers, body):
        seen.update(method=method, url=url, auth=headers["Authorization"], body=json.loads(body))
        return 200, json.dumps({"results": [{"title": "T", "url": "https://x.example", "content": "C",
                                             "score": 0.9}]}).encode()

    res = WebClient(transport=t).tavily_search("tvly-test", "cricket score", topic="news")
    assert seen["method"] == "POST" and seen["url"] == "https://api.tavily.com/search"
    assert seen["auth"] == "Bearer tvly-test"
    assert seen["body"] == {"query": "cricket score", "search_depth": "basic", "max_results": 5, "topic": "news"}
    assert res[0]["title"] == "T"
    with pytest.raises(WebError, match="monthly limit"):
        WebClient(transport=lambda *a: (432, b"{}")).tavily_search("k", "q")


def test_results_marked_untrusted_and_secrets_redacted():
    text = format_results([{"title": "A", "url": "https://a.example", "content": "token sk-ant-abcdefghijkl here",
                            "published_date": ""}])
    assert text.startswith("UNTRUSTED WEB DATA") and "sk-ant" not in text


def test_weather_via_open_meteo():
    def t(method, url, headers, body):
        if "geocoding" in url:
            return 200, json.dumps({"results": [{"name": "Pune", "admin1": "Maharashtra", "country": "India",
                                                 "latitude": 18.5, "longitude": 73.8}]}).encode()
        assert "latitude=18.5" in url and "timezone=auto" in url
        return 200, json.dumps({
            "current": {"temperature_2m": 27.1, "apparent_temperature": 29.0, "weather_code": 2, "wind_speed_10m": 9},
            "daily": {"time": ["2026-10-10"], "temperature_2m_min": [21.0], "temperature_2m_max": [30.0],
                      "weather_code": [61], "precipitation_probability_max": [70]}}).encode()

    text = format_weather(WebClient(transport=t).weather("Pune", 1))
    assert "Pune, Maharashtra, India" in text and "27.1°C" in text and "partly cloudy" in text
    assert "light rain, rain chance 70%" in text


def test_tavily_extract_request_and_response():
    seen = {}

    def t(method, url, headers, body):
        seen.update(method=method, url=url, auth=headers["Authorization"], body=json.loads(body))
        return 200, json.dumps({"results": [{"url": "https://shop.example/a", "raw_content": "Price Rs 10",
                                             "images": []}],
                                "failed_results": [{"url": "https://shop.example/b", "error": "timeout"}],
                                "response_time": 1.2, "request_id": "r1"}).encode()

    res = WebClient(transport=t).tavily_extract("tvly-test", ["https://shop.example/a", "https://shop.example/b"],
                                                query="price", depth="advanced")
    assert seen["method"] == "POST" and seen["url"] == "https://api.tavily.com/extract"
    assert seen["auth"] == "Bearer tvly-test"
    assert seen["body"]["urls"] == ["https://shop.example/a", "https://shop.example/b"]
    assert seen["body"]["extract_depth"] == "advanced" and seen["body"]["query"] == "price"
    assert seen["body"]["chunks_per_source"] == 3 and seen["body"]["timeout"] < 20
    assert res == {"results": [{"url": "https://shop.example/a", "raw_content": "Price Rs 10"}],
                   "failed_results": [{"url": "https://shop.example/b", "error": "timeout"}]}
    with pytest.raises(WebError, match="key missing"):
        WebClient(transport=lambda *a: (401, b"{}")).tavily_extract("k", ["https://shop.example/a"])
    with pytest.raises(WebError, match="1 to 20"):
        WebClient(transport=t).tavily_extract("k", [])
    with pytest.raises(WebError, match="depth"):
        WebClient(transport=t).tavily_extract("k", ["https://shop.example/a"], depth="deep")