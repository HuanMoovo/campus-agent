"""Campus connector contracts, credential isolation, and bounded outbound requests."""
import json
import socket
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

PUBLIC_IP = "8.8.8.8"
SOURCE_URL = "https://school.example.edu/grades?semester=fall"
GRADES = [{"course": "高等数学", "score": 88, "credits": 4, "semester": "秋"}]


def dns(address=PUBLIC_IP):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (address, 443))]


@pytest.fixture(autouse=True)
def isolated_sources(monkeypatch, tmp_path):
    # Import after collection so test_api's process configuration is initialized.
    global campus_data, services
    from app import campus_data, services
    monkeypatch.setattr(campus_data, "get_settings", lambda: SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr(campus_data.socket, "getaddrinfo", Mock(return_value=dns()))


def configure(kind="grades", **fields):
    return campus_data.configure_source(kind, {"url": SOURCE_URL, **fields})


def mock_transport(monkeypatch, body, status=200):
    response = MagicMock()
    response.status_code = status
    response.iter_bytes.return_value = iter(body)
    if status >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "failed with sensitive upstream details", request=httpx.Request("GET", SOURCE_URL),
            response=httpx.Response(status),
        )
    stream = MagicMock()
    stream.__enter__.return_value = response
    client = MagicMock()
    client.stream.return_value = stream
    context = MagicMock()
    context.__enter__.return_value = client
    factory = Mock(return_value=context)
    monkeypatch.setattr(campus_data.httpx, "Client", factory)
    return factory, client, response


def as_json(value):
    return [json.dumps(value, ensure_ascii=False).encode("utf-8")]


def test_saved_token_is_encrypted_and_never_returned():
    result = configure(token="top-secret-key")
    raw = campus_data._path().read_text(encoding="utf-8")
    assert "top-secret-key" not in raw
    stored = json.loads(raw)["grades"]["token"]
    assert campus_data._decrypt(stored) == "top-secret-key"
    assert result["has_token"] is True
    assert "token" not in result
    assert "top-secret-key" not in json.dumps(campus_data.list_sources())
    assert campus_data.configure_source("grades", {"result_path": "data.items"})["has_token"] is True
    assert campus_data.configure_source("grades", {"clear_token": True})["has_token"] is False


def test_old_token_is_cleared_when_destination_host_changes():
    configure(token="old-host-secret")
    result = campus_data.configure_source("grades", {"url": "https://other.example.edu/grades"})
    assert result["has_token"] is False
    result = campus_data.configure_source("grades", {"url": SOURCE_URL, "token": "new-host-secret"})
    assert result["has_token"] is True
    assert campus_data._decrypt(campus_data._load()["grades"]["token"]) == "new-host-secret"


@pytest.mark.parametrize("fields", [
    {"extra": "field"}, {"url": None}, {"url": ""}, {"result_path": []},
    {"result_path": "data..items"}, {"result_path": "data[0]"},
    {"token": ""}, {"token": "a\nb"}, {"token": "a\tb"}, {"token": "令牌"},
    {"clear_token": "false"}, {"clear_token": True, "token": "value"},
])
def test_invalid_configuration_does_not_replace_existing_values(fields):
    configure(token="existing-secret")
    previous = campus_data._path().read_bytes()
    with pytest.raises(HTTPException) as error:
        campus_data.configure_source("grades", fields)
    assert error.value.status_code == 422
    assert campus_data._path().read_bytes() == previous


@pytest.mark.parametrize("url", [
    "http://school.example.edu/grades", "https://user:password@school.example.edu/grades",
    "https://school.example.edu:8443/grades", "https://school.example.edu:invalid/grades",
    "https://school.example.edu/grades#fragment", "https://school.example.edu/\nsecret",
    "https://school.example.edu\\@127.0.0.1/", "https://school.example.edu/\x7f",
])
def test_invalid_urls_are_rejected_before_dns(url):
    with pytest.raises(HTTPException) as error:
        campus_data._validated_target(url)
    assert error.value.status_code == 422
    campus_data.socket.getaddrinfo.assert_not_called()


@pytest.mark.parametrize("addresses", [
    [], dns("127.0.0.1"), dns("10.0.0.1"), dns("169.254.169.254"),
    dns("::1"), dns("fe80::1"), dns("224.0.0.1"), dns("ff02::1"),
    dns("::ffff:127.0.0.1"), dns() + dns("192.168.1.1"),
])
def test_nonpublic_or_mixed_dns_answers_are_rejected(monkeypatch, addresses):
    monkeypatch.setattr(campus_data.socket, "getaddrinfo", Mock(return_value=addresses))
    with pytest.raises(HTTPException) as error:
        configure()
    assert error.value.status_code == 422
    assert not campus_data._path().exists()


def test_fetch_revalidates_dns_before_decrypting_or_sending_token(monkeypatch):
    configure(token="sensitive-token")
    monkeypatch.setattr(campus_data.socket, "getaddrinfo", Mock(return_value=dns("127.0.0.1")))
    factory = Mock()
    decrypt = Mock()
    monkeypatch.setattr(campus_data.httpx, "Client", factory)
    monkeypatch.setattr(campus_data, "_decrypt", decrypt)
    with pytest.raises(HTTPException) as error:
        campus_data.fetch_source("grades")
    assert error.value.status_code == 422
    factory.assert_not_called()
    decrypt.assert_not_called()


@pytest.mark.parametrize("address, authority", [(PUBLIC_IP, PUBLIC_IP), ("2606:4700:4700::1111", "[2606:4700:4700::1111]")])
def test_requests_pin_address_preserving_host_tls_and_query(monkeypatch, address, authority):
    configure(token="access-token", result_path="data.items")
    resolve = Mock(return_value=dns(address))
    monkeypatch.setattr(campus_data.socket, "getaddrinfo", resolve)
    factory, client, _ = mock_transport(monkeypatch, as_json({"data": {"items": GRADES}}))
    assert campus_data.fetch_source("grades") == {"demo": False, "items": GRADES}
    resolve.assert_called_once_with("school.example.edu", 443, type=socket.SOCK_STREAM)
    assert factory.call_args.kwargs == {"timeout": 12, "follow_redirects": False, "trust_env": False}
    args, kwargs = client.stream.call_args
    assert args == ("GET", f"https://{authority}/grades?semester=fall")
    assert kwargs["headers"]["Host"] == "school.example.edu"
    assert kwargs["headers"]["Authorization"] == "Bearer access-token"
    assert kwargs["extensions"]["sni_hostname"] == "school.example.edu"
    assert kwargs["json"] is None


@pytest.mark.parametrize("body,status,expected", [
    ([b"{}"], 302, 502), ([b"sensitive upstream failure"], 401, 502),
    ([b"<html>login</html>"], 200, 502), ([b"{\"items\":[],\"x\":NaN}"], 200, 502),
    ([b"{\"items\":[],\"x\":1e309}"], 200, 502), ([b"[" * 1500], 200, 502),
    ([b"x" * 1_000_000, b"y" * 1_000_001], 200, 413),
])
def test_redirects_invalid_json_and_limits_fail_safely(monkeypatch, body, status, expected):
    configure(token="private-token")
    _, client, _ = mock_transport(monkeypatch, body, status)
    with pytest.raises(HTTPException) as error:
        campus_data.fetch_source("grades")
    assert error.value.status_code == expected
    assert "private-token" not in error.value.detail
    assert "sensitive upstream" not in error.value.detail
    assert client.stream.call_count == 1


def test_missing_result_path_is_an_upstream_error(monkeypatch):
    configure(result_path="data.items")
    mock_transport(monkeypatch, as_json({"results": GRADES}))
    with pytest.raises(HTTPException) as error:
        campus_data.fetch_source("grades")
    assert error.value.status_code == 502


@pytest.mark.parametrize("kind,value", [
    ("grades", {}), ("grades", {"items": ["invalid"]}), ("grades", [{"course": "A"}]),
    ("grades", [{"course": "A", "score": True}]), ("grades", [{"course": "A", "score": 90, "credits": -1}]),
    ("schedule", [{"course": "A", "time": "08:00"}]),
    ("classrooms", [{"building": "A", "room": "1", "seats": True}]),
    ("classrooms", [{"building": "A", "room": "1", "seats": 30, "available": "false"}]),
    ("credits", {"required": 120}), ("credits", {"required": 120, "earned": True}),
    ("credits", {"required": 120, "earned": float("inf")}),
    ("credits", {"required": float("nan"), "earned": 0}),
    ("repairs", []),
])
def test_invalid_service_schema_is_reported_as_upstream_failure(kind, value):
    with pytest.raises(HTTPException) as error:
        campus_data._normalize_result(kind, value)
    assert error.value.status_code == 502


@pytest.mark.parametrize("kind,value,expected", [
    ("grades", GRADES, {"items": GRADES}),
    ("grades", [{"course": "体育", "score": "通过"}], {"items": [{"course": "体育", "score": "通过"}]}),
    ("schedule", {"items": [{"course": "A", "weekday": "周一", "time": "08:00", "room": "A101"}]},
     {"items": [{"course": "A", "weekday": "周一", "time": "08:00", "room": "A101"}]}),
    ("credits", {"required": 160, "earned": 42.5, "demo": True}, {"required": 160, "earned": 42.5}),
    ("classrooms", [], {"items": []}),
    ("repairs", {"id": "r1", "status": "pending"}, {"result": {"id": "r1", "status": "pending"}}),
    ("notices", [{"title": "开学通知", "body": "新学期安排"}], {"items": [{"title": "开学通知", "body": "新学期安排"}]}),
    ("library", [], {"items": []}), ("dining", [], {"items": []}), ("shuttle", [], {"items": []}),
])
def test_valid_service_schemas_preserve_data_and_set_real_origin(kind, value, expected):
    assert campus_data._normalize_result(kind, value) == {"demo": False, **expected}


def test_repairs_post_only_the_explicit_payload(monkeypatch):
    configure("repairs")
    _, client, _ = mock_transport(monkeypatch, as_json({"id": "ticket-1", "status": "received"}))
    payload = {"location": "A101", "issue": "灯具无法正常开启", "contact": "user@example.edu"}
    result = campus_data.fetch_source("repairs", payload)
    assert result == {"demo": False, "result": {"id": "ticket-1", "status": "received"}}
    assert client.stream.call_args.args[0] == "POST"
    assert client.stream.call_args.kwargs["json"] == payload
    assert "Authorization" not in client.stream.call_args.kwargs["headers"]


def test_classroom_filters_real_data_and_excludes_occupied_rooms(monkeypatch):
    monkeypatch.setattr(campus_data, "configured", lambda kind: True)
    monkeypatch.setattr(campus_data, "fetch_source", lambda kind: {"demo": False, "items": [
        {"building": "教学楼 A", "room": "A101", "seats": 50, "available": False},
        {"building": "教学楼 A", "room": "A102", "seats": 20},
        {"building": "教学楼 A", "room": "A103", "seats": 60},
        {"building": "教学楼 B", "room": "B201", "seats": 60},
    ]})
    assert services.classrooms("教学楼\tA", 30) == {
        "demo": False, "items": [{"building": "教学楼 A", "room": "A103", "seats": 60}],
    }


def test_real_service_responses_never_claim_demo_data():
    from app.agent import respond
    for kind, result in [("grades", {"items": GRADES}), ("schedule", {"items": []}),
                         ("classrooms", {"items": []}), ("credits", {"required": 160, "earned": 40})]:
        response = respond({"intent": kind, "tool_result": {"demo": False, **result}})
        assert response["mode"] == "service"
        assert "学校接口" in response["answer"]
        assert "演示" not in response["answer"]


@pytest.mark.parametrize("contents", ["not json", "[]", '{"grades": []}', '{"grades":{"url":null}}'])
def test_corrupt_saved_configuration_returns_actionable_error(contents):
    campus_data._path().write_text(contents, encoding="utf-8")
    with pytest.raises(HTTPException) as error:
        campus_data.list_sources()
    assert error.value.status_code == 503


def test_unreadable_token_cannot_start_request(monkeypatch):
    configure(token="a-token")
    factory = Mock()
    monkeypatch.setattr(campus_data.httpx, "Client", factory)
    monkeypatch.setattr(campus_data, "_decrypt", Mock(side_effect=ValueError("private ciphertext")))
    with pytest.raises(HTTPException) as error:
        campus_data.fetch_source("grades")
    assert error.value.status_code == 503
    assert "private ciphertext" not in error.value.detail
    factory.assert_not_called()


def test_campus_configuration_api_requires_admin_and_hides_token(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(admin_token="admin-secret"))
    monkeypatch.setattr(main, "desktop_enabled", lambda: False)
    client = TestClient(main.app)
    body = {"url": SOURCE_URL, "token": "upstream-secret"}
    assert client.put("/api/campus-sources/grades", json=body).status_code == 401
    assert client.delete("/api/campus-sources/grades").status_code == 401
    headers = {"X-Admin-Token": "admin-secret"}
    created = client.put("/api/campus-sources/grades", json=body, headers=headers)
    assert created.status_code == 200
    assert created.json()["has_token"] is True
    listing = client.get("/api/campus-sources")
    assert listing.status_code == 200
    assert "upstream-secret" not in created.text + listing.text
    assert "dpapi:" not in created.text + listing.text
    assert client.get("/api/campus-data/repairs").status_code == 405
    assert client.get("/api/campus-data/unknown").status_code == 404
    assert client.delete("/api/campus-sources/grades", headers=headers).status_code == 200
    assert not campus_data.configured("grades")


def test_services_route_uses_configured_school_response(monkeypatch):
    from app import main
    configure()
    client = TestClient(main.app)
    mock_transport(monkeypatch, as_json(GRADES))
    result = client.get("/api/services/grades")
    assert result.status_code == 200
    assert result.json() == {"demo": False, "items": GRADES}
