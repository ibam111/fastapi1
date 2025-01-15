from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime, timedelta
import mysql.connector
from mysql.connector import Error
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
    def __init__(self):
        self.config = {
            'host': 'localhost',
            'user': 'root',
            'password': 'Ib1234567am#',
            'charset': 'utf8mb4',
            'autocommit': True
        }
        self.database = 'births_db'
        self.create_database()
        self.config['database'] = self.database
        self.init_db()

    def create_database(self):
        try:
            conn = mysql.connector.connect(**self.config)
            cursor = conn.cursor()
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {self.database} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            conn.commit()
        except Error as e:
            print(f"Error creating database: {e}")
            raise HTTPException(
                status_code=500, 
                detail=f"خطأ في إنشاء قاعدة البيانات: {str(e)}"
            )
        finally:
            cursor.close()
            conn.close()

    def get_connection(self):
        try:
            conn = mysql.connector.connect(**self.config)
            return conn
        except Error as e:
            print(f"Error connecting to MySQL: {e}")
            raise HTTPException(
                status_code=500, 
                detail=f"خطأ في الاتصال بقاعدة البيانات: {str(e)}"
            )

    def init_db(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # إنشاء الجدول مع التأكد من عدم وجوده
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS births (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    father_id VARCHAR(12) NOT NULL,
                    father_id_type ENUM('موحدة', 'هوية_احوال') NOT NULL,
                    father_full_name VARCHAR(100) NOT NULL,
                    mother_id VARCHAR(12) NOT NULL,
                    mother_id_type ENUM('موحدة', 'هوية_احوال') NOT NULL,
                    mother_name VARCHAR(100) NOT NULL,
                    hospital_name VARCHAR(100) NOT NULL,
                    birth_date DATE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_parents (father_id, mother_id),
                    INDEX idx_father_id (father_id),
                    INDEX idx_mother_id (mother_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                conn.commit()
        except Error as e:
            print(f"Database initialization error: {e}")
            raise HTTPException(
                status_code=500, 
                detail=f"خطأ في تهيئة قاعدة البيانات: {str(e)}"
            )

    @contextmanager
    def get_connection_context(self):
        conn = self.get_connection()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def get_transaction(self):
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute_query(self, query, params=None):
        conn = None
        cursor = None
        try:
            conn = mysql.connector.connect(**self.config)
            cursor = conn.cursor()
            cursor.execute(query, params or ())
            return cursor
        except Error as e:
            if conn:
                conn.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"خطأ في تنفيذ الاستعلام: {str(e)}"
            )
        finally:
            if cursor:
                cursor.close()
            if conn:
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

        with db_manager.get_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT hospital_name FROM births 
            WHERE father_id = %s AND mother_id = %s
            """, (data.father_id, data.mother_id))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="تم إدخال هذه البيانات مسبقاً.")
            
            cursor.execute("""
            INSERT INTO births (father_id, father_id_type, father_full_name, mother_id, mother_id_type, mother_name, hospital_name, birth_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (data.father_id, data.father_id_type, data.father_full_name, data.mother_id, data.mother_id_type, data.mother_name, data.hospital_name, data.birth_date))
            conn.commit()
        return {"message": "تم حفظ البيانات بنجاح"}
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/search/{search_id}")
async def search_data(search_id: str):
    try:
        with db_manager.get_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT mother_name, father_full_name, hospital_name, birth_date, father_id_type, mother_id_type 
            FROM births 
            WHERE father_id = %s OR mother_id = %s
            """, (search_id, search_id))
            results = cursor.fetchall()
            if not results:
                raise HTTPException(status_code=404, detail="لم يتم العثور على نتائج")
            return {"results": [{"mother_name": r[0], "father_full_name": r[1], "hospital_name": r[2], 
                               "birth_date": r[3], "father_id_type": r[4], "mother_id_type": r[5]} for r in results]}
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/delete-old-entries/")
async def delete_old_entries():
    try:
        cutoff_date = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d")
        with db_manager.get_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM births WHERE birth_date < %s", (cutoff_date,))
            conn.commit()
            return {"message": "تم حذف السجلات القديمة بنجاح"}
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    return {"status": "online", "message": "نظام تسجيل المواليد يعمل"}
