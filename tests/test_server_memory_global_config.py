"""验证服务端全局记忆配置的读取、展示和写回。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def server_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    home = tmp_path / "minibot_home"
    workdir = tmp_path / "workdir"
    config_dir = home / "config"
    config_dir.mkdir(parents=True)
    # 避免把开发者的项目模板复制到测试目录。
    (config_dir / "default.yaml").write_text("{}\n", encoding="utf-8")
    workdir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MINIBOT_HOME", str(home))
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    for key in (
        "ALL_PROXY",
        "all_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "NO_PROXY",
        "no_proxy",
    ):
        monkeypatch.delenv(key, raising=False)
    return {"home": home, "workdir": workdir}


@pytest.fixture()
def client(server_env: dict[str, Path]) -> TestClient:
    from src.minibot.server.app import create_app

    return TestClient(create_app(workdir=server_env["workdir"]))


def test_global_config_snapshot_exposes_memory_backend_and_url_state(client: TestClient) -> None:
    data = client.get("/api/config").json()
    assert data["memory_backend"] == "sqlite"
    assert data["memory_database_url_configured"] is False
    assert data["memory_database_url_value"] is None


@pytest.mark.parametrize(
    ("backend", "database_url"),
    [
        ("postgres", "postgresql://writer:secret@localhost:5432/minibot_memory"),
        ("mysql", "mysql://writer:secret@localhost:3306/minibot_memory"),
    ],
)
def test_updating_global_config_persists_memory_backend_and_env_url(
    client: TestClient,
    server_env: dict[str, Path],
    backend: str,
    database_url: str,
) -> None:
    put = client.put(
        "/api/config",
        json={
            "memory_backend": backend,
            "memory_database_url_value": database_url,
        },
    )
    assert put.status_code == 200, put.text

    config_yaml = (server_env["home"] / "config" / "default.yaml").read_text(encoding="utf-8")
    dotenv_text = (server_env["home"] / ".env").read_text(encoding="utf-8")

    assert f"backend: {backend}" in config_yaml
    assert "${MEMORY_DATABASE_URL}" in config_yaml
    assert database_url not in config_yaml
    assert database_url in dotenv_text

    snapshot = client.get("/api/config").json()
    assert snapshot["memory_backend"] == backend
    assert snapshot["memory_database_url_value"] == database_url


@pytest.mark.parametrize(
    "database_url",
    [None, "mysql://localhost", "postgresql://localhost/memory", "mysql://localhost/db\nOTHER=value"],
)
def test_global_config_rejects_invalid_mysql_url(client: TestClient, database_url: str | None) -> None:
    response = client.put(
        "/api/config",
        json={"memory_backend": "mysql", "memory_database_url_value": database_url},
    )

    assert response.status_code == 400
    assert client.get("/api/config").json()["memory_backend"] == "sqlite"
