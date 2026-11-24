"""验证记忆数据库的初始化、连接配置和会话工厂。"""

import pytest
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlmodel import SQLModel

from src.minibot.config.schema import MemoryConfig
from src.minibot.memory import db as memory_db
from src.minibot.memory.db import create_memory_db


def test_sqlmodel_db_helper_bootstraps_sqlite_memory_tables(tmp_path):
    db = create_memory_db(
        MemoryConfig(enabled=True, memory_dir=str(tmp_path / "memory"), backend="sqlite"),
        app_home=tmp_path / ".minibot",
    )

    assert db.database_path is not None
    assert db.database_path.name == "memory_v2.sqlite3"
    assert db.database_path.exists()
    assert db.engine is not None


def test_postgres_backend_requires_database_url(tmp_path):
    with pytest.raises(ValueError):
        create_memory_db(
            MemoryConfig(
                enabled=True,
                memory_dir=str(tmp_path / "memory"),
                backend="postgres",
                database_url=None,
            ),
            app_home=tmp_path / ".minibot",
        )


def test_postgres_backend_defaults_plain_postgresql_urls_to_psycopg(tmp_path, monkeypatch):
    captured: dict[str, str] = {}

    def fake_create_engine(url: str, *args, **kwargs):
        captured["url"] = url
        return object()

    monkeypatch.setattr("src.minibot.memory.db.create_engine", fake_create_engine)
    monkeypatch.setattr(SQLModel.metadata, "create_all", lambda engine: None)

    create_memory_db(
        MemoryConfig(
            enabled=True,
            memory_dir=str(tmp_path / "memory"),
            backend="postgres",
            database_url="postgresql://writer:secret@localhost:5432/minibot_memory",
        ),
        app_home=tmp_path / ".minibot",
    )

    assert captured["url"] == "postgresql+psycopg://writer:secret@localhost:5432/minibot_memory"


def test_create_memory_db_reuses_cached_postgres_engine_for_same_url(tmp_path, monkeypatch):
    created_urls: list[str] = []
    create_all_calls: list[object] = []

    def fake_create_engine(url: str, *args, **kwargs):
        engine = object()
        created_urls.append(url)
        return engine

    monkeypatch.setattr("src.minibot.memory.db.create_engine", fake_create_engine)
    monkeypatch.setattr(SQLModel.metadata, "create_all", lambda engine: create_all_calls.append(engine))
    if hasattr(memory_db, "_clear_memory_db_cache"):
        memory_db._clear_memory_db_cache()

    config = MemoryConfig(
        enabled=True,
        memory_dir=str(tmp_path / "memory"),
        backend="postgres",
        database_url="postgresql://writer:secret@localhost:5432/minibot_memory",
    )

    first = create_memory_db(config, app_home=tmp_path / ".minibot")
    second = create_memory_db(config, app_home=tmp_path / ".minibot")

    assert first is second
    assert created_urls == ["postgresql+psycopg://writer:secret@localhost:5432/minibot_memory"]
    assert create_all_calls == [first.engine]


@pytest.mark.parametrize("database_url", [None, "mysql://localhost", "postgresql://localhost/memory"])
def test_mysql_backend_requires_mysql_database_url(tmp_path, database_url):
    config = MemoryConfig(backend="mysql", database_url=database_url)

    with pytest.raises(ValueError, match=r"memory\.database_url"):
        create_memory_db(config, app_home=tmp_path)


def test_mysql_backend_reuses_engine_for_equivalent_urls(tmp_path, monkeypatch):
    engine_calls = []
    create_all_calls = []

    def fake_create_engine(url, **options):
        engine_calls.append((url, options))
        return object()

    monkeypatch.setattr(memory_db, "create_engine", fake_create_engine)
    monkeypatch.setattr(SQLModel.metadata, "create_all", create_all_calls.append)
    monkeypatch.setattr(memory_db, "_MEMORY_DB_CACHE", {})
    config = MemoryConfig(
        backend="mysql",
        database_url="mysql://writer:test%40password@localhost:3306/memory?connect_timeout=5",
    )

    first = create_memory_db(config, app_home=tmp_path)
    config.database_url = config.database_url.replace("mysql://", "mysql+pymysql://") + "&charset=utf8mb4"
    second = create_memory_db(config, app_home=tmp_path)

    assert first is second
    assert first.database_path is None
    assert create_all_calls == [first.engine]
    [(url, options)] = engine_calls
    assert url.drivername == "mysql+pymysql"
    assert url.password == "test@password"
    assert dict(url.query) == {"charset": "utf8mb4", "connect_timeout": "5"}
    assert options == {"pool_pre_ping": True}


def test_mysql_memory_schema_supports_long_text_and_indexes_uri_by_prefix():
    table = SQLModel.metadata.tables["memory_nodes"]
    uri_index = next(index for index in table.indexes if index.name == "idx_memory_nodes_namespace_uri")

    mysql_ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
    assert "content LONGTEXT" in mysql_ddl
    assert "uri LONGTEXT" in mysql_ddl
    assert "utf8mb4" in mysql_ddl
    assert "(namespace_id, uri(255))" in str(CreateIndex(uri_index).compile(dialect=mysql.dialect()))
    assert "content VARCHAR" in str(CreateTable(table).compile(dialect=sqlite.dialect()))


@pytest.mark.parametrize(
    ("table_name", "description"),
    [
        ("memory_namespaces", "记忆命名空间"),
        ("memory_nodes", "记忆节点"),
        ("memory_node_versions", "历史版本"),
        ("memory_triggers", "记忆触发词"),
        ("memory_search_documents", "检索文档"),
    ],
)
def test_mysql_memory_table_ddl_includes_chinese_comment(table_name, description):
    table = SQLModel.metadata.tables[table_name]

    assert description in table.comment
    mysql_ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
    assert f"COMMENT='{table.comment}'" in mysql_ddl
