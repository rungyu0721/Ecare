"""
PostgreSQL 資料庫操作：連線、初始化、CRUD。
"""

import time
from datetime import datetime
from typing import Any, Dict, Optional

import psycopg2
from fastapi import HTTPException
from psycopg2.extras import RealDictCursor

from backend.config import DB_CONFIG
from backend.models import UserCreate, UserItem

# 資料庫可用狀態
DB_AVAILABLE = False


# ======================
# 連線工具
# ======================

def get_db():
    return psycopg2.connect(**DB_CONFIG)


def describe_db_connection(conn) -> str:
    server_addr = None
    server_port = None
    database_name = DB_CONFIG["database"]
    current_user = DB_CONFIG["user"]

    cur = None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT
                inet_server_addr()::text AS server_addr,
                inet_server_port() AS server_port,
                current_database() AS database_name,
                current_user AS current_user
        """)
        row = cur.fetchone() or {}
        server_addr = row.get("server_addr") or server_addr
        server_port = row.get("server_port") or server_port
        database_name = row.get("database_name") or database_name
        current_user = row.get("current_user") or current_user
    except Exception:
        pass
    finally:
        if cur is not None:
            cur.close()

    return (
        f"host={DB_CONFIG['host']} "
        f"port={server_port or DB_CONFIG['port']} "
        f"db={database_name} "
        f"user={current_user} "
        f"server_addr={server_addr or DB_CONFIG['host']}"
    )


# ======================
# 初始化
# ======================

def init_db():
    global DB_AVAILABLE
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS case_records (
                id          VARCHAR(20) PRIMARY KEY,
                title       VARCHAR(200),
                category    VARCHAR(100),
                location    TEXT,
                latitude    DOUBLE PRECISION,
                longitude   DOUBLE PRECISION,
                status      VARCHAR(50) DEFAULT '處理中',
                created_at  VARCHAR(50),
                risk_level  VARCHAR(20),
                risk_score  FLOAT,
                description TEXT
            );
        """)
        cur.execute("""
            ALTER TABLE case_records
                ADD COLUMN IF NOT EXISTS latitude   DOUBLE PRECISION,
                ADD COLUMN IF NOT EXISTS longitude  DOUBLE PRECISION,
                ADD COLUMN IF NOT EXISTS updated_at VARCHAR(50);
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS incident_status_log (
                id          SERIAL PRIMARY KEY,
                report_id   VARCHAR(20) NOT NULL,
                status      VARCHAR(100) NOT NULL,
                note        TEXT,
                created_at  VARCHAR(50)
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ecare_user (
                id              SERIAL PRIMARY KEY,
                name            VARCHAR(100) NOT NULL,
                phone           VARCHAR(30),
                gender          VARCHAR(20),
                age             INTEGER,
                emergency_name  VARCHAR(100),
                emergency_phone VARCHAR(30),
                relationship    VARCHAR(50),
                address         TEXT,
                notes           TEXT,
                created_at      VARCHAR(50) DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY/MM/DD HH24:MI')
            );
        """)
        conn.commit()
        DB_AVAILABLE = True
        print(f"PostgreSQL 已連線：{describe_db_connection(conn)}")
    except Exception as e:
        DB_AVAILABLE = False
        print(f"⚠️ PostgreSQL 連線失敗，/reports 將暫時不可用：{e}")
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()


def ensure_db_available():
    if not DB_AVAILABLE:
        raise HTTPException(status_code=503, detail="資料庫目前不可用，請稍後再試")


# ======================
# 工具函式
# ======================

def now_str():
    return time.strftime("%Y/%m/%d %H:%M", time.localtime())


def make_id(prefix="A", cur=None):
    today = time.strftime("%Y%m%d", time.localtime())
    base = f"{prefix}{today}"

    if cur is None:
        return f"{base}0001"

    cur.execute(
        """
        SELECT id
        FROM case_records
        WHERE id LIKE %s
        ORDER BY id DESC
        LIMIT 1;
        """,
        (f"{base}%",),
    )
    row = cur.fetchone()
    latest_id = None
    if row:
        latest_id = row.get("id") if isinstance(row, dict) else row[0]

    next_number = 1
    if latest_id and len(latest_id) >= len(base) + 4:
        suffix = latest_id[len(base):]
        if suffix.isdigit():
            next_number = int(suffix) + 1

    return f"{base}{next_number:04d}"


def build_user_item(row: Dict[str, Any]) -> UserItem:
    data = dict(row)
    created_at = data.get("created_at")
    if isinstance(created_at, datetime):
        data["created_at"] = created_at.isoformat(sep=" ", timespec="seconds")
    elif created_at is not None:
        data["created_at"] = str(created_at)
    return UserItem(**data)


def find_existing_user_id(cur, payload: UserCreate) -> Optional[int]:
    name = payload.name.strip()
    phone = (payload.phone or "").strip()
    if not name or not phone:
        return None

    cur.execute(
        """
        SELECT id
        FROM ecare_user
        WHERE name = %s AND phone = %s
        ORDER BY id DESC
        LIMIT 1;
        """,
        (name, phone),
    )
    row = cur.fetchone()
    if not row:
        return None
    return row["id"]
