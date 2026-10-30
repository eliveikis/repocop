"""App shell: health check, static files, escaping, startup, and the entry point."""

import logging
import re
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient

import repocop
from repocop import __main__ as entrypoint
from repocop.config import Settings
from repocop.main import create_app


def test_healthz_reports_ok_and_version(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": repocop.__version__}


def test_pages_escape_untrusted_values(settings: Settings, tmp_path: Path) -> None:
    hostile = settings.model_copy(update={"repos_root": tmp_path / "<script>alert(1)</script>"})
    with TestClient(create_app(hostile)) as client:
        html = client.get("/").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_stylesheet_is_served(client: TestClient) -> None:
    response = client.get("/static/css/app.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]


def test_create_app_loads_settings_when_none_given() -> None:
    app = create_app()
    assert isinstance(app.state.settings, Settings)


def test_main_runs_uvicorn_with_configured_host_and_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append(kw))
    monkeypatch.setenv("REPOCOP_PORT", "9123")
    entrypoint.main()
    assert calls == [{"host": "127.0.0.1", "port": 9123}]


def test_main_exits_with_code_2_on_config_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: pytest.fail("must not start"))
    monkeypatch.setenv("REPOCOP_PORT", "not-a-port")
    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main()
    assert exc_info.value.code == 2
    assert "port" in caplog.text


def test_main_warns_when_binding_beyond_loopback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: None)
    monkeypatch.setenv("REPOCOP_HOST", "0.0.0.0")  # noqa: S104 - testing the warning
    with caplog.at_level(logging.WARNING):
        entrypoint.main()
    assert "no authentication" in caplog.text


# ---------------------------------------------------------------- requests from other sites

ANOTHER_SITE = [
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
    {"Origin": "https://example.com"},
    {"Origin": "http://testserver:8000"},
    {"Origin": "null"},
]
OWN_PAGE = [
    {},  # not a browser
    {"Sec-Fetch-Site": "same-origin"},
    {"Sec-Fetch-Site": "none"},
    {"Origin": "http://testserver"},
]


@pytest.mark.parametrize("headers", ANOTHER_SITE)
def test_a_post_sent_from_another_site_is_refused(
    client: TestClient, settings: Settings, remote_repo: Path, headers: dict[str, str]
) -> None:
    response = client.post("/repositories", data={"remote_url": str(remote_repo)}, headers=headers)
    assert response.status_code == 403
    assert "another site" in response.json()["detail"]
    assert not list(settings.repos_root.iterdir())


@pytest.mark.parametrize("headers", OWN_PAGE)
def test_a_post_sent_from_repocops_own_page_is_accepted(
    client: TestClient, settings: Settings, remote_repo: Path, headers: dict[str, str]
) -> None:
    response = client.post(
        "/repositories",
        data={"remote_url": str(remote_repo), "default_branch": "main"},
        headers=headers,
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert (settings.repos_root / "sample").is_dir()


def test_a_get_sent_from_another_site_is_served(client: TestClient) -> None:
    assert client.get("/", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


def test_every_route_that_changes_state_refuses_another_site(client: TestClient) -> None:
    changing = [
        (method.upper(), re.sub(r"{[^}]+}", "1", path))
        for path, operations in client.get("/openapi.json").json()["paths"].items()
        for method in operations
        if method not in ("get", "head", "options")
    ]
    assert ("POST", "/tasks/1/pull-request/1") in changing
    for method, path in changing:
        response = client.request(method, path, headers={"Sec-Fetch-Site": "cross-site"})
        assert response.status_code == 403, f"{method} {path}"
