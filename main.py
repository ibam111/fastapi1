from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import sqlite3
from contextlib import contextmanager

app = FastAPI(title="نظام تسجيل المواليد")

# نموذج البيانات
class BirthData(BaseModel):
    father_id: int = Field(..., ge=10000000, le=999999999999, description="رقم هوية الأب")
    father_id_type: str = Field(..., description="نوع مستمسك الأب")
    father_full_name: str = Field(..., min_length=2, max_length=100, description="اسم الأب الرباعي")
    mother_id: int = Field(..., ge=10000000, le=999999999999, description="رقم هوية الأم")
    mother_id_type: str = Field(..., description="نوع مستمسك الأم")
    mother_name: str = Field(..., min_length=2, max_length=100, description="اسم الأم")
    hospital_name: str = Field(..., min_length=2, max_length=100, description="اسم المستشفى")
    birth_date: str = Field(..., regex=r"^\d{4}-\d{2}-\d{2}$", description="تاريخ الميلاد (YYYY-MM-DD)")

# إدارة قاعدة البيانات
class DatabaseManager:
    def __init__(self, db_name="births.db"):
        self.db_name = db_name
        self.init_db()

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS births (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                father_id INTEGER,
                father_id_type TEXT,
                father_full_name TEXT,
                mother_id INTEGER,
                mother_id_type TEXT,
                mother_name TEXT,
                hospital_name TEXT,
                birth_date TEXT,
                created_at TEXT
            )
            """)
            conn.commit()

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_name)
        try:
            yield conn
        finally:
            conn.close()

# تهيئة قاعدة البيانات
db_manager = DatabaseManager()

@app.post("/save-data/")
async def save_data(data: BirthData):
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT hospital_name FROM births 
            WHERE father_id = ? AND mother_id = ?
            """, (data.father_id, data.mother_id))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="تم إدخال هذه البيانات مسبقاً.")
            
            created_at = datetime.now().isoformat()
            cursor.execute("""
            INSERT INTO births (father_id, father_id_type, father_full_name, mother_id, mother_id_type, mother_name, hospital_name, birth_date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (data.father_id, data.father_id_type, data.father_full_name, data.mother_id, data.mother_id_type, data.mother_name, data.hospital_name, data.birth_date, created_at))
            conn.commit()
        return {"message": "تم حفظ البيانات بنجاح"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/search/{search_id}")
async def search_data(search_id: str):
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT mother_name, father_full_name, hospital_name, birth_date, father_id_type, mother_id_type 
            FROM births 
            WHERE father_id = ? OR mother_id = ?
            """, (search_id, search_id))
            results = cursor.fetchall()
            if not results:
                raise HTTPException(status_code=404, detail="لم يتم العثور على نتائج")
            return {"results": [{"mother_name": r[0], "father_full_name": r[1], "hospital_name": r[2], "birth_date": r[3], "father_id_type": r[4], "mother_id_type": r[5]} for r in results]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
