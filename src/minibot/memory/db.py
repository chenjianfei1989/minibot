"""初始化仅用于记忆的 SQLModel 引擎和会话。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel, Session, create_engine

from ..config.schema import MemoryConfig
from . import db_models as _db_models  # noqa: F401


@dataclass
class MemoryDatabase:
    engine: object
    session_factory: sessionmaker
    database_path: Path | None


_MEMORY_DB_CACHE: dict[tuple[str, str | URL], MemoryDatabase] = {}
_MEMORY_DB_CACHE_LOCK = Lock()


def _resolve_memory_dir(memory_dir: str, *, app_home: Path) -> Path:
    """解析记忆存储目录，并展开用户主目录。"""
    path = Path(memory_dir).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (app_home / path).resolve()


def _normalize_postgres_database_url(database_url: str) -> str:
    """将 PostgreSQL 连接地址转换为当前驱动使用的格式。"""
    if database_url.startswith("postgresql+"):
        return database_url
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    return database_url


def normalize_mysql_database_url(database_url: str) -> URL:
    """校验 MySQL 数据库地址，并补齐驱动及 Unicode 字符集。"""
    if "\r" in database_url or "\n" in database_url:
        raise ValueError("memory.database_url must be a single-line MySQL URL")
    try:
        url = make_url(database_url)
    except (ArgumentError, ValueError):
        raise ValueError("memory.database_url must be a valid MySQL URL") from None
    if url.drivername not in {"mysql", "mysql+pymysql"} or not url.database:
        raise ValueError("memory.database_url must use mysql:// or mysql+pymysql:// and name a database")
    return url.set(drivername="mysql+pymysql").update_query_dict(
        {"charset": url.query.get("charset", "utf8mb4")}
    )


def _clear_memory_db_cache() -> None:
    """在缓存锁保护下清空记忆数据库实例缓存。"""
    with _MEMORY_DB_CACHE_LOCK:
        _MEMORY_DB_CACHE.clear()


def create_memory_db(config: MemoryConfig, *, app_home: Path) -> MemoryDatabase:
    """根据后端配置获取或初始化记忆数据库及会话工厂。"""
    backend = (config.backend or "sqlite").strip().lower()

    if backend == "sqlite":
        memory_dir = _resolve_memory_dir(config.memory_dir, app_home=app_home)
        memory_dir.mkdir(parents=True, exist_ok=True)
        database_path = memory_dir / "memory_v2.sqlite3"
        cache_key = ("sqlite", str(database_path.resolve()))

        with _MEMORY_DB_CACHE_LOCK:
            cached = _MEMORY_DB_CACHE.get(cache_key)
            if cached is not None:
                return cached

            engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False})
            SQLModel.metadata.create_all(engine)
            database = MemoryDatabase(
                engine=engine,
                session_factory=sessionmaker(bind=engine, class_=Session, expire_on_commit=False),
                database_path=database_path,
            )
            _MEMORY_DB_CACHE[cache_key] = database
            return database
    elif backend in {"postgres", "mysql"}:
        if not config.database_url:
            raise ValueError(f"memory.database_url is required for {backend} backend")
        if backend == "mysql":
            database_url = normalize_mysql_database_url(config.database_url)
        else:
            database_url = _normalize_postgres_database_url(config.database_url)
        cache_key = (backend, database_url)

        with _MEMORY_DB_CACHE_LOCK:
            cached = _MEMORY_DB_CACHE.get(cache_key)
            if cached is not None:
                return cached

            engine_options = {"pool_pre_ping": True} if backend == "mysql" else {}
            engine = create_engine(database_url, **engine_options)
            SQLModel.metadata.create_all(engine)
            database = MemoryDatabase(
                engine=engine,
                session_factory=sessionmaker(bind=engine, class_=Session, expire_on_commit=False),
                database_path=None,
            )
            _MEMORY_DB_CACHE[cache_key] = database
            return database
    else:
        raise ValueError(f"Unsupported memory backend: {config.backend}")
