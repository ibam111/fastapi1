from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timedelta
import sqlite3
from contextlib import contextmanager
import logging
from functools import wraps
import time

# إعداد التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# تهيئة التطبيق
app = FastAPI(
    title="نظام تسجيل المواليد",
    description="نظام لتسجيل وإدارة بيانات المواليد",
    version="1.0.0"
)

# إعداد CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# نموذج البيانات مع التحقق
class BirthData(BaseModel):
    father_id: int = Field(..., ge=1000000000, le=9999999999, description="رقم هوية الأب")
    father_id_type: str = Field(..., description="نوع مستمسك الأب")
    father_full_name: str = Field(..., min_length=2, max_length=100, description="اسم الأب الرباعي")
    mother_id: int = Field(..., ge=1000000000, le=9999999999, description="رقم هوية الأم")
    mother_id_type: str = Field(..., description="نوع مستمسك الأم")
    mother_name: str = Field(..., min_length=2, max_length=100, description="اسم الأم")
    hospital_name: str = Field(..., min_length=2, max_length=100, description="اسم المستشفى")
    birth_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="تاريخ الميلاد (YYYY-MM-DD)")

    def __init__(self, **data):
        super().__init__(**data)
        # Validate ID types
        valid_types = ["هوية_احوال", "موحدة"]
        if self.father_id_type not in valid_types:
            raise ValueError("نوع مستمسك الأب غير صالح")
        if self.mother_id_type not in valid_types:
            raise ValueError("نوع مستمسك الأم غير صالح")

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

# تهيئة مدير قاعدة البيانات
db_manager = DatabaseManager()

# مزخرف للتحكم في معدل الطلبات
def rate_limit(calls: int, period: int):
    def decorator(func):
        last_reset = {}
        call_count = {}
        
        @wraps(func)
        async def wrapper(*args, **kwargs):
            now = time.time()
            if func.__name__ not in last_reset:
                last_reset[func.__name__] = now
                call_count[func.__name__] = 0
            
            if now - last_reset[func.__name__] >= period:
                last_reset[func.__name__] = now
                call_count[func.__name__] = 0
            
            if call_count[func.__name__] >= calls:
                raise HTTPException(
                    status_code=429,
                    detail="تم تجاوز الحد المسموح به من الطلبات. الرجاء المحاولة لاحقاً."
                )
            
            call_count[func.__name__] += 1
            return await func(*args, **kwargs)
        return wrapper
    return decorator

@app.get("/", response_class=JSONResponse)
@rate_limit(calls=100, period=60)
async def read_root():
    return {"message": "مرحباً"}

@app.post("/save-data/")
@rate_limit(calls=10, period=60)
async def save_data(data: BirthData):
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # التحقق من وجود البيانات مسبقاً
            cursor.execute("""
            SELECT hospital_name FROM births 
            WHERE father_id = ? AND mother_id = ?
            """, (data.father_id, data.mother_id))
            result = cursor.fetchone()

            if result:
                raise HTTPException(
                    status_code=400,
                    detail=f"تم إدخال هذه البيانات بالفعل في مستشفى {result[0]}"
                )

            # إدخال البيانات الجديدة
            created_at = datetime.now().isoformat()
            cursor.execute("""
            INSERT INTO births (father_id, father_full_name, mother_id, mother_name, hospital_name, birth_date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (data.father_id, data.father_full_name, data.mother_id, data.mother_name, data.hospital_name, data.birth_date, created_at))
            conn.commit()

            logger.info(f"تم حفظ بيانات جديدة: {data.mother_name}")
            return {"message": "تم حفظ البيانات بنجاح"}

    except Exception as e:
        logger.error(f"خطأ في حفظ البيانات: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/search/{search_id}")
async def search_data(search_id: str):
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    mother_name, 
                    father_full_name, 
                    hospital_name, 
                    birth_date,
                    father_id_type,
                    mother_id_type
                FROM births 
                WHERE father_id = ? OR mother_id = ?
            """, (search_id, search_id))
            results = cursor.fetchall()
            
            if not results:
                raise HTTPException(status_code=404, detail="لم يتم العثور على نتائج")
            
            formatted_results = []
            for result in results:
                formatted_results.append({
                    "mother_name": result[0],
                    "father_full_name": result[1],
                    "hospital_name": result[2],
                    "birth_date": result[3],
                    "father_id_type": result[4],
                    "mother_id_type": result[5]
                })
            
            return {"results": formatted_results}

    except Exception as e:
        logger.error(f"خطأ في البحث: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/delete-old-entries/")
@rate_limit(calls=5, period=3600)  # 5 calls per hour
async def delete_old_entries():
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cutoff_time = (datetime.now() - timedelta(days=46)).isoformat()
            
            cursor.execute("""
            DELETE FROM births 
            WHERE created_at < ?
            """, (cutoff_time,))
            
            deleted_count = cursor.rowcount
            conn.commit()
            
            logger.info(f"تم حذف {deleted_count} سجلات قديمة")
            return {
                "message": f"تم حذف {deleted_count} إدخالات قديمة",
                "details": {"deleted_count": deleted_count}
            }

    except Exception as e:
        logger.error(f"خطأ في حذف السجلات القديمة: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    logger.info("بدء تشغيل التطبيق...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
