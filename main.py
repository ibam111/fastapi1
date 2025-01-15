from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime, timedelta
import sqlite3
from contextlib import contextmanager
import re

app = FastAPI(title="نظام تسجيل المواليد")

# نموذج البيانات
class BirthData(BaseModel):
    father_id: str = Field(..., pattern=r'^\d{8,12}$', description="رقم هوية الأب")
    father_id_type: str = Field(..., description="نوع مستمسك الأب")
    father_full_name: str = Field(..., min_length=2, max_length=100, description="اسم الأب الرباعي")
    mother_id: str = Field(..., description="رقم هوية الأم", pattern=r'^\d{8,12}$')
    mother_id_type: str = Field(..., description="نوع مستمسك الأم")
    mother_name: str = Field(..., min_length=2, max_length=100, description="اسم الأم")
    hospital_name: str = Field(..., min_length=2, max_length=100, description="اسم المستشفى")
    birth_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="تاريخ الميلاد (YYYY-MM-DD)")

    @validator('father_id')
    def validate_father_id(cls, v, values):
        if not v.isdigit():
            raise ValueError("يجب أن يحتوي رقم الهوية على أرقام فقط")
        if values.get('father_id_type') == "موحدة" and len(v) != 12:
            raise ValueError("رقم الموحدة للأب يجب أن يكون 12 رقم")
        elif values.get('father_id_type') == "هوية_احوال" and len(v) != 8:
            raise ValueError("رقم هوية الأحوال للأب يجب أن يكون 8 أرقام")
        return v

    @validator('mother_id')
    def validate_mother_id(cls, v, values):
        if not v.isdigit():
            raise ValueError("يجب أن يحتوي رقم الهوية على أرقام فقط")
        if values.get('mother_id_type') == "موحدة" and len(v) != 12:
            raise ValueError("رقم الموحدة للأم يجب أن يكون 12 رقم")
        elif values.get('mother_id_type') == "هوية_احوال" and len(v) != 8:
            raise ValueError("رقم هوية الأحوال للأم يجب أن يكون 8 أرقام")
        return v

    @validator('father_full_name', 'mother_name', 'hospital_name')
    def validate_arabic_name(cls, v):
        if not re.match(r'^[\u0600-\u06FF\s]{2,100}$', v):
            raise ValueError("يجب أن يحتوي الاسم على حروف عربية فقط")
        return v

    @validator('birth_date')
    def validate_birth_date(cls, v):
        try:
            date = datetime.strptime(v, "%Y-%m-%d")
            today = datetime.now()
            if date > today:
                raise ValueError("لا يمكن أن يكون تاريخ الميلاد في المستقبل")
            if date.year < 1900:
                raise ValueError("تاريخ الميلاد غير صالح")
            if (today - date).days > 45:  # التحقق من أن التاريخ ليس قديماً جداً
                raise ValueError("لا يمكن تسجيل مواليد بعد 45 يوم من الولادة")
            return v
        except ValueError as e:
            raise ValueError(str(e))

    @validator('father_id_type', 'mother_id_type')
    def validate_id_type(cls, v):
        valid_types = ['موحدة', 'هوية_احوال']
        if v not in valid_types:
            raise ValueError(f"نوع الهوية يجب أن يكون أحد القيم التالية: {', '.join(valid_types)}")
        return v

# إدارة قاعدة البيانات
class DatabaseManager:
    def __init__(self, db_name="births.db"):
        self.db_name = "sqlite:///./births.db"
        self.init_db()

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # تنفيذ الأوامر بشكل منفصل
            cursor.execute("DROP TABLE IF EXISTS births")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS births (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                father_id TEXT NOT NULL,
                father_id_type TEXT NOT NULL CHECK (father_id_type IN ('موحدة', 'هوية_احوال')),
                father_full_name TEXT NOT NULL,
                mother_id TEXT NOT NULL,
                mother_id_type TEXT NOT NULL CHECK (mother_id_type IN ('موحدة', 'هوية_احوال')),
                mother_name TEXT NOT NULL,
                hospital_name TEXT NOT NULL,
                birth_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(father_id, mother_id)
            )""")
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
        # التحقق من التاريخ
        birth_date = datetime.strptime(data.birth_date, "%Y-%m-%d")
        if (datetime.now() - birth_date).days > 45:
            raise HTTPException(
                status_code=400, 
                detail="لا يمكن تسجيل مواليد بعد 45 يوم من الولادة"
            )

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
            return {"results": [{"mother_name": r[0], "father_full_name": r[1], "hospital_name": r[2], 
                               "birth_date": r[3], "father_id_type": r[4], "mother_id_type": r[5]} for r in results]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/delete-old-entries/")
async def delete_old_entries():
    try:
        cutoff_date = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d")
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM births WHERE birth_date < ?", (cutoff_date,))
            conn.commit()
            return {"message": "تم حذف السجلات القديمة بنجاح"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    return {"status": "online", "message": "نظام تسجيل المواليد يعمل"}
