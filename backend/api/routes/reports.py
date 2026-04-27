"""
/reports 與 /users 路由：案件與使用者 CRUD。
"""

from typing import List

from fastapi import APIRouter, HTTPException
from psycopg2.extras import RealDictCursor

from backend.db.postgres import (
    build_user_item,
    ensure_db_available,
    find_existing_user_id,
    get_db,
    make_id,
    now_str,
)
from backend.models import ReportCreate, ReportItem, UserCreate, UserItem

router = APIRouter()


# ======================
# Reports
# ======================

@router.get("/reports", response_model=List[ReportItem])
def list_reports():
    ensure_db_available()
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT * FROM case_records ORDER BY created_at DESC LIMIT 200;"
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [ReportItem(**dict(row)) for row in rows]
    except Exception as e:
        print(f"❌ list_reports 失敗：{e}")
        raise HTTPException(status_code=500, detail=f"資料庫查詢失敗：{str(e)}")


@router.post("/reports", response_model=ReportItem)
def create_report(payload: ReportCreate):
    ensure_db_available()
    rid = make_id("A")
    item = ReportItem(
        id=rid,
        title=payload.title,
        category=payload.category,
        location=payload.location,
        status="處理中",
        created_at=now_str(),
        risk_level=payload.risk_level,
        risk_score=payload.risk_score,
        description=payload.description,
    )
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO case_records
                (id, title, category, location, status, created_at, risk_level, risk_score, description)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                item.id, item.title, item.category, item.location,
                item.status, item.created_at, item.risk_level,
                item.risk_score, item.description,
            )
        )
        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ 案件寫入 PostgreSQL：{item.id}")
        return item
    except Exception as e:
        print(f"❌ create_report 失敗：{e}")
        raise HTTPException(status_code=500, detail=f"資料庫寫入失敗：{str(e)}")


# ======================
# Users
# ======================

@router.get("/users", response_model=List[UserItem])
def list_users():
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM ecare_user ORDER BY created_at DESC;")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [build_user_item(row) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查詢失敗：{str(e)}")


@router.post("/users", response_model=UserItem)
def create_user(payload: UserCreate):
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        existing_user_id = find_existing_user_id(cur, payload)
        if existing_user_id is not None:
            cur.execute("""
                UPDATE ecare_user
                SET
                    name = %s,
                    phone = %s,
                    gender = %s,
                    age = %s,
                    emergency_name = %s,
                    emergency_phone = %s,
                    relationship = %s,
                    address = %s,
                    notes = %s
                WHERE id = %s
                RETURNING *;
            """, (
                payload.name, payload.phone, payload.gender, payload.age,
                payload.emergency_name, payload.emergency_phone,
                payload.relationship, payload.address, payload.notes,
                existing_user_id,
            ))
        else:
            cur.execute("""
                INSERT INTO ecare_user
                    (name, phone, gender, age, emergency_name, emergency_phone, relationship, address, notes)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *;
            """, (
                payload.name, payload.phone, payload.gender, payload.age,
                payload.emergency_name, payload.emergency_phone,
                payload.relationship, payload.address, payload.notes
            ))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return build_user_item(row)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"新增失敗：{str(e)}")


@router.put("/users/{user_id}", response_model=UserItem)
def update_user(user_id: int, payload: UserCreate):
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            UPDATE ecare_user
            SET
                name = %s,
                phone = %s,
                gender = %s,
                age = %s,
                emergency_name = %s,
                emergency_phone = %s,
                relationship = %s,
                address = %s,
                notes = %s
            WHERE id = %s
            RETURNING *;
        """, (
            payload.name, payload.phone, payload.gender, payload.age,
            payload.emergency_name, payload.emergency_phone,
            payload.relationship, payload.address, payload.notes,
            user_id,
        ))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="找不到此使用者")
        return build_user_item(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新失敗：{str(e)}")


@router.get("/users/{user_id}", response_model=UserItem)
def get_user(user_id: int):
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM ecare_user WHERE id = %s;", (user_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="找不到此使用者")
        return build_user_item(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查詢失敗：{str(e)}")
