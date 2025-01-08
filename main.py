import os
import sys
import io
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import Literal
import firebase_admin
from firebase_admin import credentials
from firebase_admin import db
import logging
from functools import wraps
import time
from datetime import datetime, timedelta

# إعداد ترميز UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# إعداد التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# تهيئة تطبيق FastAPI
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

# تهيئة Firebase Admin SDK
try:
    # تحميل ملف credentials.json
    cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "birth-2bd8b-firebase-adminsdk-mpypb-3b85b9dc48.json")
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://birth-2bd8b-default-rtdb.firebaseio.com'
    })
    logger.info("تم تهيئة Firebase بنجاح.")
except Exception as e:
    logger.error(f"فشل في تهيئة Firebase: {str(e)}")
    raise RuntimeError(f"فشل في تهيئة Firebase: {str(e)}")

# نموذج البيانات مع التحقق
class BirthData(BaseModel):
    father_id_type: Literal["رقم الموحدة", "رقم هوية الأحوال"]
    father_id: int = Field(..., description="رقم الأب")
    mother_id_type: Literal["رقم الموحدة", "رقم هوية الأحوال"]
    mother_id: int = Field(..., description="رقم الأم")
    mother_name: str = Field(..., min_length=2, max_length=100, description="اسم الأم")
    hospital_name: str = Field(..., min_length=2, max_length=100, description="اسم المستشفى")
    birth_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="تاريخ الميلاد (YYYY-MM-DD)")

    @validator('birth_date')
    def validate_birth_date(cls, value):
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise ValueError("تاريخ الميلاد غير صالح. يجب أن يكون بالصيغة YYYY-MM-DD.")
        return value

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

@app.get("/")
@rate_limit(calls=100, period=60)
async def read_root():
    return {"message": "مرحبًا بك في نظام تسجيل المواليد!"}

@app.post("/save-data/")
@rate_limit(calls=10, period=60)
async def save_data(data: BirthData):
    try:
        ref = db.reference("births")

        # التحقق من وجود البيانات مسبقاً
        existing_data = ref.order_by_child("father_id").equal_to(data.father_id).get()
        for key, value in existing_data.items():
            if value.get("mother_id") == data.mother_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"تم إدخال هذه البيانات بالفعل في مستشفى {value.get('hospital_name')}"
                )

        # إدخال البيانات الجديدة
        birth_entry = {
            "father_id": data.father_id,
            "father_id_type": data.father_id_type,
            "mother_id": data.mother_id,
            "mother_id_type": data.mother_id_type,
            "mother_name": data.mother_name,
            "hospital_name": data.hospital_name,
            "birth_date": data.birth_date,
            "created_at": datetime.now().isoformat()
        }

        ref.push(birth_entry)
        logger.info(f"تم حفظ بيانات جديدة: {data.mother_name}")
        return {"message": "تم حفظ البيانات بنجاح"}

    except Exception as e:
        logger.error(f"خطأ في حفظ البيانات: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/search/")
@rate_limit(calls=20, period=60)
async def search_data(father_id: int, mother_id: int):
    try:
        ref = db.reference("births")
        results = ref.order_by_child("father_id").equal_to(father_id).get()

        data = []
        for key, value in results.items():
            if value.get("mother_id") == mother_id:
                data.append(value)

        if not data:
            raise HTTPException(status_code=404, detail="لم يتم العثور على بيانات.")

        return {"data": data}

    except Exception as e:
        logger.error(f"خطأ في البحث عن البيانات: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/delete-old-entries/")
@rate_limit(calls=5, period=3600)  # 5 calls per hour
async def delete_old_entries():
    try:
        ref = db.reference("births")
        all_data = ref.get()

        if not all_data:
            return {"message": "لا توجد بيانات لحذفها"}

        cutoff_time = datetime.now() - timedelta(days=30)
        deleted_count = 0

        for key, value in all_data.items():
            created_at = datetime.fromisoformat(value.get("created_at"))
            if created_at < cutoff_time:
                ref.child(key).delete()
                deleted_count += 1

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
