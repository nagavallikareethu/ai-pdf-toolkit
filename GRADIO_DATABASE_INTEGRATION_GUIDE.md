# 🔧 Gradio Integration & Database Solution Guide

**Date:** November 17, 2025  
**Project:** AI-Powered PDF Processing System  
**Status:** Comprehensive Implementation Guide

---

## 📋 **Table of Contents**

1. [CLI vs Gradio Output Mismatch - Solutions](#1-cli-vs-gradio-output-mismatch)
2. [Database Selection & Recommendations](#2-database-selection)
3. [Database Schema Design](#3-database-schema-design)
4. [Implementation Guide](#4-implementation-guide)
5. [Best Practices](#5-best-practices)
6. [Complete Code Examples](#6-code-examples)

---

## 1️⃣ **CLI vs Gradio Output Mismatch - Solutions**

### **Root Causes Identified**

| Issue | Impact | Solution Status |
|-------|--------|----------------|
| Python module caching | ⚠️ HIGH | ✅ FIXED |
| Environment variable mismatch | ⚠️ MEDIUM | ✅ FIXED |
| Different PDF generators | ⚠️ HIGH | ✅ FIXED |
| Content classification missing | ⚠️ CRITICAL | ✅ FIXED |
| File path inconsistencies | ⚠️ MEDIUM | ✅ FIXED |

### **✅ Already Implemented Fixes**

#### **Fix 1: Aggressive Module Reload** (Lines 78-115 in app_gradio.py)

```python
def force_reload_translate_module():
    """
    Aggressively reload translate module, clearing all caches.
    """
    global translate_module
    
    try:
        # Step 1: Remove from sys.modules
        if 'translate' in sys.modules:
            del sys.modules['translate']
            print("🔄 Cleared translate from sys.modules")
        
        # Step 2: Remove submodules
        submodules = [key for key in sys.modules.keys() if key.startswith('translate.')]
        for key in submodules:
            del sys.modules[key]
        
        # Step 3: Invalidate import caches
        importlib.invalidate_caches()
        
        # Step 4: Fresh import
        import translate as fresh_module
        translate_module = fresh_module
        
        # Step 5: Verify and log
        if hasattr(translate_module, '__file__'):
            mod_time = datetime.fromtimestamp(os.path.getmtime(translate_module.__file__))
            print(f"✅ Reloaded translate.py (modified: {mod_time.strftime('%Y-%m-%d %H:%M:%S')})")
        
        return translate_module
        
    except Exception as e:
        print(f"❌ CRITICAL: Failed to reload translate module: {e}")
        return None
```

#### **Fix 2: Environment Verification** (Lines 282-309)

```python
def verify_environment():
    """Verify environment matches CLI execution"""
    from pathlib import Path
    from dotenv import load_dotenv
    
    # Force reload .env
    env_path = Path(__file__).parent / '.env'
    load_dotenv(env_path, override=True)
    
    # Log environment details
    print("\n🔐 Environment Verification:")
    api_key = os.getenv('GENAI_API_KEY')
    model = os.getenv('GENAI_MODEL', 'models/gemini-2.5-flash')
    
    if api_key:
        print(f"   API Key: {api_key[:10]}...{api_key[-6:]} ✅")
    else:
        print(f"   API Key: NOT FOUND ❌")
        return False
    
    print(f"   Model: {model}")
    print(f"   .env loaded from: {env_path}")
    
    return bool(api_key)
```

#### **Fix 3: File Verification with MD5** (Lines 361-396)

```python
# Input verification
import hashlib
file_size = os.path.getsize(input_pdf_path)
with open(input_pdf_path, 'rb') as f:
    input_hash = hashlib.md5(f.read()).hexdigest()

print(f"📊 Input File Verification:")
print(f"   Size: {file_size:,} bytes")
print(f"   MD5: {input_hash}")

# Output verification
if os.path.exists(output_path):
    output_size = os.path.getsize(output_path)
    with open(output_path, 'rb') as f:
        output_hash = hashlib.md5(f.read()).hexdigest()
    
    print(f"\n📊 Output File Verification:")
    print(f"   File: {os.path.basename(output_path)}")
    print(f"   Size: {output_size:,} bytes")
    print(f"   MD5: {output_hash}")
    print(f"   💡 Compare this MD5 hash with CLI output!")
```

### **🔧 Additional Recommended Fixes**

#### **Fix 4: Comprehensive Logging System**

```python
import logging
from datetime import datetime

# Configure logging
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / f"gradio_{datetime.now().strftime('%Y%m%d')}.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Usage in pipeline
def run_translate_pipeline(input_pdf_path: str, target_lang_code: str):
    logger.info(f"Pipeline started: {input_pdf_path} → {target_lang_code}")
    logger.debug(f"Working directory: {os.getcwd()}")
    logger.debug(f"Environment: API_KEY={os.getenv('GENAI_API_KEY')[:10]}...")
    
    # ... pipeline code ...
    
    logger.info(f"Pipeline completed: {output_path}")
```

#### **Fix 5: Working Directory Consistency**

```python
import os
from pathlib import Path

# At top of app_gradio.py
PROJECT_ROOT = Path(__file__).parent.resolve()
os.chdir(PROJECT_ROOT)

print(f"✅ Working directory set to: {PROJECT_ROOT}")
```

---

## 2️⃣ **Database Selection & Recommendations**

### **🎯 Recommended: PostgreSQL + Object Storage**

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Metadata DB** | PostgreSQL 15+ | Store file metadata, user info, processing logs |
| **JSON Storage** | PostgreSQL JSONB | Store extracted/translated JSON efficiently |
| **File Storage** | Local FS / S3 / MinIO | Store actual PDF files (input/output) |

### **Why PostgreSQL?**

✅ **Excellent JSONB support** - Query JSON fields directly with indexes  
✅ **ACID compliance** - Data integrity for processing workflows  
✅ **Full-text search** - Search translated content  
✅ **Mature ecosystem** - Python libraries (psycopg2, SQLAlchemy)  
✅ **Scalable** - Handle millions of records  
✅ **Free & Open Source** - No licensing costs  

### **Alternative: MySQL 8.0+**

✅ JSON column type  
✅ Good performance  
✅ Familiar to many developers  
❌ Weaker JSON querying than PostgreSQL  

### **NOT Recommended:**

❌ **SQLite** - Not suitable for concurrent Gradio users  
❌ **MongoDB** - Overkill for this use case, less structured  
❌ **Storing PDFs in DB** - Poor performance, use filesystem instead  

---

## 3️⃣ **Database Schema Design**

### **Complete Schema (PostgreSQL)**

```sql
-- ============================================================
-- TABLE 1: Users (if multi-user system)
-- ============================================================
CREATE TABLE users (
    user_id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_username ON users(username);

-- ============================================================
-- TABLE 2: Processing Jobs (Main table)
-- ============================================================
CREATE TABLE processing_jobs (
    job_id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(user_id),
    
    -- Job metadata
    job_type VARCHAR(20) NOT NULL CHECK (job_type IN ('translate', 'solution', 'generate')),
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')),
    
    -- Input file info
    input_filename VARCHAR(255) NOT NULL,
    input_filepath TEXT NOT NULL,
    input_file_size BIGINT,
    input_file_hash VARCHAR(32),  -- MD5 hash
    
    -- Processing parameters
    target_language VARCHAR(10),
    source_language VARCHAR(10) DEFAULT 'auto',
    processing_options JSONB,  -- Store additional options
    
    -- Output file info
    output_filename VARCHAR(255),
    output_filepath TEXT,
    output_file_size BIGINT,
    output_file_hash VARCHAR(32),
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    
    -- Processing stats
    total_pages INTEGER,
    items_translated INTEGER,
    items_skipped INTEGER,
    processing_time_seconds INTEGER,
    
    -- Error tracking
    error_message TEXT,
    error_traceback TEXT,
    
    -- Metadata
    metadata JSONB  -- Store any additional data
);

-- Indexes for performance
CREATE INDEX idx_jobs_user_id ON processing_jobs(user_id);
CREATE INDEX idx_jobs_status ON processing_jobs(status);
CREATE INDEX idx_jobs_job_type ON processing_jobs(job_type);
CREATE INDEX idx_jobs_created_at ON processing_jobs(created_at DESC);
CREATE INDEX idx_jobs_hash ON processing_jobs(input_file_hash);

-- Composite index for common queries
CREATE INDEX idx_jobs_user_status ON processing_jobs(user_id, status);

-- ============================================================
-- TABLE 3: JSON Data Storage
-- ============================================================
CREATE TABLE json_data (
    json_id SERIAL PRIMARY KEY,
    job_id INTEGER REFERENCES processing_jobs(job_id) ON DELETE CASCADE,
    
    -- JSON type
    json_type VARCHAR(20) NOT NULL CHECK (json_type IN ('extracted', 'solved', 'translated')),
    
    -- JSON content
    content JSONB NOT NULL,
    
    -- Metadata
    language_code VARCHAR(10),
    page_count INTEGER,
    total_items INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- File reference (if also stored as file)
    json_filepath TEXT,
    json_file_size BIGINT
);

-- Indexes
CREATE INDEX idx_json_job_id ON json_data(job_id);
CREATE INDEX idx_json_type ON json_data(json_type);
CREATE INDEX idx_json_language ON json_data(language_code);

-- JSONB indexes for querying content
CREATE INDEX idx_json_content_gin ON json_data USING GIN (content);

-- ============================================================
-- TABLE 4: Processing Logs
-- ============================================================
CREATE TABLE processing_logs (
    log_id SERIAL PRIMARY KEY,
    job_id INTEGER REFERENCES processing_jobs(job_id) ON DELETE CASCADE,
    
    -- Log details
    log_level VARCHAR(10) CHECK (log_level IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')),
    message TEXT NOT NULL,
    
    -- Context
    module_name VARCHAR(50),
    function_name VARCHAR(100),
    
    -- Timestamp
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_logs_job_id ON processing_logs(job_id);
CREATE INDEX idx_logs_level ON processing_logs(log_level);
CREATE INDEX idx_logs_created_at ON processing_logs(created_at DESC);

-- ============================================================
-- TABLE 5: File Storage Metadata
-- ============================================================
CREATE TABLE file_storage (
    file_id SERIAL PRIMARY KEY,
    job_id INTEGER REFERENCES processing_jobs(job_id) ON DELETE CASCADE,
    
    -- File info
    file_type VARCHAR(20) CHECK (file_type IN ('input_pdf', 'output_pdf', 'extracted_json', 'translated_json', 'solved_json')),
    filename VARCHAR(255) NOT NULL,
    filepath TEXT NOT NULL,
    
    -- Storage location
    storage_type VARCHAR(20) DEFAULT 'local' CHECK (storage_type IN ('local', 's3', 'minio', 'gcs')),
    storage_bucket VARCHAR(100),  -- For cloud storage
    storage_key TEXT,  -- For cloud storage
    
    -- File properties
    file_size BIGINT,
    file_hash VARCHAR(32),  -- MD5
    mime_type VARCHAR(100),
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    accessed_at TIMESTAMP,
    
    -- Retention policy
    expires_at TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_files_job_id ON file_storage(job_id);
CREATE INDEX idx_files_type ON file_storage(file_type);
CREATE INDEX idx_files_hash ON file_storage(file_hash);
CREATE INDEX idx_files_expires ON file_storage(expires_at) WHERE expires_at IS NOT NULL;

-- ============================================================
-- TABLE 6: API Usage Tracking
-- ============================================================
CREATE TABLE api_usage (
    usage_id SERIAL PRIMARY KEY,
    job_id INTEGER REFERENCES processing_jobs(job_id),
    
    -- API details
    api_name VARCHAR(50) NOT NULL,  -- 'gemini', 'google_translate'
    api_operation VARCHAR(50),  -- 'translate', 'generate', 'solve'
    
    -- Usage metrics
    request_count INTEGER DEFAULT 1,
    tokens_used INTEGER,
    cost_estimate DECIMAL(10, 4),  -- Estimated cost
    
    -- Response details
    response_time_ms INTEGER,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    
    -- Timestamp
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_api_job_id ON api_usage(job_id);
CREATE INDEX idx_api_name ON api_usage(api_name);
CREATE INDEX idx_api_created_at ON api_usage(created_at DESC);

-- ============================================================
-- VIEWS for Common Queries
-- ============================================================

-- View: Recent Jobs with User Info
CREATE VIEW v_recent_jobs AS
SELECT 
    j.job_id,
    j.job_type,
    j.status,
    j.input_filename,
    j.output_filename,
    j.target_language,
    j.created_at,
    j.processing_time_seconds,
    u.username,
    u.email
FROM processing_jobs j
LEFT JOIN users u ON j.user_id = u.user_id
ORDER BY j.created_at DESC;

-- View: Job Statistics
CREATE VIEW v_job_statistics AS
SELECT 
    user_id,
    job_type,
    status,
    COUNT(*) as job_count,
    AVG(processing_time_seconds) as avg_processing_time,
    SUM(output_file_size) as total_output_size,
    MAX(created_at) as last_job_date
FROM processing_jobs
GROUP BY user_id, job_type, status;

-- ============================================================
-- FUNCTIONS for Common Operations
-- ============================================================

-- Function: Get job with all related data
CREATE OR REPLACE FUNCTION get_job_complete(p_job_id INTEGER)
RETURNS TABLE (
    job_data JSONB,
    json_data JSONB[],
    files JSONB[],
    logs JSONB[]
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        to_jsonb(j.*) as job_data,
        ARRAY_AGG(DISTINCT to_jsonb(jd.*)) FILTER (WHERE jd.json_id IS NOT NULL) as json_data,
        ARRAY_AGG(DISTINCT to_jsonb(fs.*)) FILTER (WHERE fs.file_id IS NOT NULL) as files,
        ARRAY_AGG(DISTINCT to_jsonb(pl.*)) FILTER (WHERE pl.log_id IS NOT NULL) as logs
    FROM processing_jobs j
    LEFT JOIN json_data jd ON j.job_id = jd.job_id
    LEFT JOIN file_storage fs ON j.job_id = fs.job_id
    LEFT JOIN processing_logs pl ON j.job_id = pl.job_id
    WHERE j.job_id = p_job_id
    GROUP BY j.job_id;
END;
$$ LANGUAGE plpgsql;
```

---

## 4️⃣ **Implementation Guide**

### **Step 1: Install Dependencies**

```bash
# PostgreSQL driver
pip install psycopg2-binary

# ORM (recommended)
pip install sqlalchemy alembic

# For S3/MinIO (optional)
pip install boto3

# Update requirements.txt
echo "psycopg2-binary>=2.9.9" >> requirements.txt
echo "sqlalchemy>=2.0.0" >> requirements.txt
echo "alembic>=1.12.0" >> requirements.txt
```

### **Step 2: Create Database Connection Module**

```python
# database.py
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
from contextlib import contextmanager
import os
from dotenv import load_dotenv

load_dotenv()

# Database configuration
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://user:password@localhost:5432/pdf_processing'
)

# Create engine
engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Verify connections before using
    echo=False  # Set to True for SQL debugging
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()

# Dependency for FastAPI/Gradio
@contextmanager
def get_db() -> Session:
    """Context manager for database sessions"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# Health check
def check_db_connection():
    """Test database connection"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("✅ Database connection successful")
        return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False
```

### **Step 3: Create SQLAlchemy Models**

```python
# models.py
from sqlalchemy import Column, Integer, String, BigInteger, Boolean, DateTime, Text, JSON, ForeignKey, Enum, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import enum

class JobType(str, enum.Enum):
    TRANSLATE = "translate"
    SOLUTION = "solution"
    GENERATE = "generate"

class JobStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class User(Base):
    __tablename__ = "users"
    
    user_id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True))
    is_active = Column(Boolean, default=True)
    
    # Relationships
    jobs = relationship("ProcessingJob", back_populates="user")

class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    
    job_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"))
    
    # Job metadata
    job_type = Column(String(20), nullable=False)
    status = Column(String(20), default="pending", index=True)
    
    # Input file info
    input_filename = Column(String(255), nullable=False)
    input_filepath = Column(Text, nullable=False)
    input_file_size = Column(BigInteger)
    input_file_hash = Column(String(32), index=True)
    
    # Processing parameters
    target_language = Column(String(10))
    source_language = Column(String(10), default="auto")
    processing_options = Column(JSONB)
    
    # Output file info
    output_filename = Column(String(255))
    output_filepath = Column(Text)
    output_file_size = Column(BigInteger)
    output_file_hash = Column(String(32))
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    
    # Processing stats
    total_pages = Column(Integer)
    items_translated = Column(Integer)
    items_skipped = Column(Integer)
    processing_time_seconds = Column(Integer)
    
    # Error tracking
    error_message = Column(Text)
    error_traceback = Column(Text)
    
    # Metadata
    metadata = Column(JSONB)
    
    # Relationships
    user = relationship("User", back_populates="jobs")
    json_data = relationship("JSONData", back_populates="job", cascade="all, delete-orphan")
    files = relationship("FileStorage", back_populates="job", cascade="all, delete-orphan")
    logs = relationship("ProcessingLog", back_populates="job", cascade="all, delete-orphan")
    api_usage = relationship("APIUsage", back_populates="job")

class JSONData(Base):
    __tablename__ = "json_data"
    
    json_id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("processing_jobs.job_id", ondelete="CASCADE"), index=True)
    
    json_type = Column(String(20), nullable=False, index=True)
    content = Column(JSONB, nullable=False)
    
    language_code = Column(String(10), index=True)
    page_count = Column(Integer)
    total_items = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    json_filepath = Column(Text)
    json_file_size = Column(BigInteger)
    
    # Relationships
    job = relationship("ProcessingJob", back_populates="json_data")

class ProcessingLog(Base):
    __tablename__ = "processing_logs"
    
    log_id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("processing_jobs.job_id", ondelete="CASCADE"), index=True)
    
    log_level = Column(String(10))
    message = Column(Text, nullable=False)
    
    module_name = Column(String(50))
    function_name = Column(String(100))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Relationships
    job = relationship("ProcessingJob", back_populates="logs")

class FileStorage(Base):
    __tablename__ = "file_storage"
    
    file_id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("processing_jobs.job_id", ondelete="CASCADE"), index=True)
    
    file_type = Column(String(20))
    filename = Column(String(255), nullable=False)
    filepath = Column(Text, nullable=False)
    
    storage_type = Column(String(20), default="local")
    storage_bucket = Column(String(100))
    storage_key = Column(Text)
    
    file_size = Column(BigInteger)
    file_hash = Column(String(32), index=True)
    mime_type = Column(String(100))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    accessed_at = Column(DateTime(timezone=True))
    
    expires_at = Column(DateTime(timezone=True))
    is_deleted = Column(Boolean, default=False)
    
    # Relationships
    job = relationship("ProcessingJob", back_populates="files")

class APIUsage(Base):
    __tablename__ = "api_usage"
    
    usage_id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("processing_jobs.job_id"))
    
    api_name = Column(String(50), nullable=False, index=True)
    api_operation = Column(String(50))
    
    request_count = Column(Integer, default=1)
    tokens_used = Column(Integer)
    cost_estimate = Column(BigInteger)  # Store as cents to avoid decimal issues
    
    response_time_ms = Column(Integer)
    success = Column(Boolean, default=True)
    error_message = Column(Text)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # Relationships
    job = relationship("ProcessingJob", back_populates="api_usage")
```

### **Step 4: Create Database Service Layer**

```python
# services/job_service.py
from sqlalchemy.orm import Session
from models import ProcessingJob, JSONData, FileStorage, ProcessingLog
from typing import Optional, Dict, Any
import hashlib
from datetime import datetime
from pathlib import Path

class JobService:
    """Service layer for processing job operations"""
    
    @staticmethod
    def create_job(
        db: Session,
        user_id: int,
        job_type: str,
        input_filepath: str,
        target_language: str,
        **kwargs
    ) -> ProcessingJob:
        """Create a new processing job"""
        
        # Calculate file hash
        with open(input_filepath, 'rb') as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
        
        file_size = Path(input_filepath).stat().st_size
        filename = Path(input_filepath).name
        
        job = ProcessingJob(
            user_id=user_id,
            job_type=job_type,
            status="pending",
            input_filename=filename,
            input_filepath=input_filepath,
            input_file_size=file_size,
            input_file_hash=file_hash,
            target_language=target_language,
            source_language=kwargs.get('source_language', 'auto'),
            processing_options=kwargs.get('options', {})
        )
        
        db.add(job)
        db.commit()
        db.refresh(job)
        
        return job
    
    @staticmethod
    def update_job_status(
        db: Session,
        job_id: int,
        status: str,
        **kwargs
    ) -> ProcessingJob:
        """Update job status and related fields"""
        
        job = db.query(ProcessingJob).filter(ProcessingJob.job_id == job_id).first()
        if not job:
            raise ValueError(f"Job {job_id} not found")
        
        job.status = status
        
        if status == "processing":
            job.started_at = datetime.now()
        elif status in ["completed", "failed"]:
            job.completed_at = datetime.now()
            if job.started_at:
                job.processing_time_seconds = int((job.completed_at - job.started_at).total_seconds())
        
        # Update other fields if provided
        for key, value in kwargs.items():
            if hasattr(job, key):
                setattr(job, key, value)
        
        db.commit()
        db.refresh(job)
        
        return job
    
    @staticmethod
    def store_json_data(
        db: Session,
        job_id: int,
        json_type: str,
        content: Dict[Any, Any],
        **kwargs
    ) -> JSONData:
        """Store JSON data for a job"""
        
        json_data = JSONData(
            job_id=job_id,
            json_type=json_type,
            content=content,
            language_code=kwargs.get('language_code'),
            page_count=kwargs.get('page_count'),
            total_items=kwargs.get('total_items'),
            json_filepath=kwargs.get('filepath'),
            json_file_size=kwargs.get('file_size')
        )
        
        db.add(json_data)
        db.commit()
        db.refresh(json_data)
        
        return json_data
    
    @staticmethod
    def add_log(
        db: Session,
        job_id: int,
        level: str,
        message: str,
        **kwargs
    ) -> ProcessingLog:
        """Add a processing log entry"""
        
        log = ProcessingLog(
            job_id=job_id,
            log_level=level,
            message=message,
            module_name=kwargs.get('module'),
            function_name=kwargs.get('function')
        )
        
        db.add(log)
        db.commit()
        
        return log
    
    @staticmethod
    def get_job_history(
        db: Session,
        user_id: Optional[int] = None,
        limit: int = 50
    ):
        """Get job history, optionally filtered by user"""
        
        query = db.query(ProcessingJob)
        
        if user_id:
            query = query.filter(ProcessingJob.user_id == user_id)
        
        return query.order_by(ProcessingJob.created_at.desc()).limit(limit).all()
```

### **Step 5: Integrate with Gradio**

```python
# app_gradio.py modifications

from database import get_db, check_db_connection
from services.job_service import JobService
import json

# At startup
if __name__ == "__main__":
    # Check database connection
    if not check_db_connection():
        print("⚠️ Warning: Database connection failed. Running without database.")
    
    # Launch Gradio
    demo.launch()

# Modified translation pipeline with database integration
def run_translate_pipeline_with_db(input_pdf_path: str, target_lang_code: str, user_id: int = 1):
    """Enhanced translation pipeline with database tracking"""
    
    job_id = None
    
    try:
        # Create job record
        with get_db() as db:
            job = JobService.create_job(
                db=db,
                user_id=user_id,
                job_type="translate",
                input_filepath=input_pdf_path,
                target_language=target_lang_code
            )
            job_id = job.job_id
            
            # Log start
            JobService.add_log(db, job_id, "INFO", "Translation pipeline started")
        
        # Update status to processing
        with get_db() as db:
            JobService.update_job_status(db, job_id, "processing")
        
        # Run actual translation (existing code)
        output_path, error = run_translate_pipeline(input_pdf_path, target_lang_code)
        
        if error:
            # Update job with error
            with get_db() as db:
                JobService.update_job_status(
                    db, job_id, "failed",
                    error_message=error
                )
                JobService.add_log(db, job_id, "ERROR", f"Translation failed: {error}")
            
            return None, error
        
        # Calculate output file hash
        with open(output_path, 'rb') as f:
            output_hash = hashlib.md5(f.read()).hexdigest()
        output_size = os.path.getsize(output_path)
        
        # Update job with output info
        with get_db() as db:
            JobService.update_job_status(
                db, job_id, "completed",
                output_filename=os.path.basename(output_path),
                output_filepath=output_path,
                output_file_size=output_size,
                output_file_hash=output_hash
            )
            
            # Store JSON data if available
            translated_json_path = f"outputs/translated_{target_lang_code}_auto.json"
            if os.path.exists(translated_json_path):
                with open(translated_json_path, 'r', encoding='utf-8') as f:
                    json_content = json.load(f)
                
                JobService.store_json_data(
                    db=db,
                    job_id=job_id,
                    json_type="translated",
                    content=json_content,
                    language_code=target_lang_code,
                    filepath=translated_json_path,
                    file_size=os.path.getsize(translated_json_path)
                )
            
            # Log completion
            JobService.add_log(db, job_id, "INFO", "Translation completed successfully")
        
        return output_path, None
        
    except Exception as e:
        # Log error to database if job was created
        if job_id:
            with get_db() as db:
                JobService.update_job_status(
                    db, job_id, "failed",
                    error_message=str(e),
                    error_traceback=traceback.format_exc()
                )
                JobService.add_log(db, job_id, "ERROR", f"Exception: {str(e)}")
        
        return None, str(e)
```

---

## 5️⃣ **Best Practices**

### **1. Environment Parity**

```python
# Create a shared config file
# config.py
from pathlib import Path
from dotenv import load_dotenv
import os

# Force consistent environment loading
ENV_FILE = Path(__file__).parent / '.env'
load_dotenv(ENV_FILE, override=True)

# Shared configuration
class Config:
    DATABASE_URL = os.getenv('DATABASE_URL')
    GENAI_API_KEY = os.getenv('GENAI_API_KEY')
    GENAI_MODEL = os.getenv('GENAI_MODEL', 'models/gemini-2.5-flash')
    WORKING_DIR = Path(__file__).parent
    OUTPUTS_DIR = WORKING_DIR / 'outputs'
    FONTS_DIR = WORKING_DIR / 'fonts'
    
    @classmethod
    def validate(cls):
        """Validate all required config"""
        required = ['DATABASE_URL', 'GENAI_API_KEY']
        missing = [key for key in required if not getattr(cls, key)]
        if missing:
            raise ValueError(f"Missing required config: {missing}")
        return True

# Use in both CLI and Gradio
from config import Config
Config.validate()
```

### **2. Transaction Management**

```python
# Always use context managers for database operations
with get_db() as db:
    try:
        # Multiple operations
        job = JobService.create_job(...)
        JobService.store_json_data(...)
        JobService.add_log(...)
        # All committed together
    except Exception as e:
        # Automatic rollback
        raise
```

### **3. Error Handling**

```python
# Comprehensive error handling
try:
    # Operation
    result = process_pdf(...)
except ValidationError as e:
    # User input error
    logger.warning(f"Validation error: {e}")
    return None, f"Invalid input: {e}"
except APIError as e:
    # External API error
    logger.error(f"API error: {e}")
    return None, "API service unavailable"
except Exception as e:
    # Unexpected error
    logger.critical(f"Unexpected error: {e}", exc_info=True)
    return None, "Internal error occurred"
```

### **4. File Storage Strategy**

```python
# Organize files by date and job ID
def get_file_path(job_id: int, file_type: str, extension: str) -> Path:
    """Generate organized file paths"""
    date_dir = datetime.now().strftime("%Y-%m-%d")
    storage_dir = Config.OUTPUTS_DIR / date_dir / f"job_{job_id}"
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir / f"{file_type}.{extension}"

# Usage
output_path = get_file_path(job_id, "translated_pdf", "pdf")
```

### **5. Database Migrations**

```bash
# Initialize Alembic
alembic init migrations

# Create migration
alembic revision --autogenerate -m "Create initial tables"

# Apply migration
alembic upgrade head

# Rollback if needed
alembic downgrade -1
```

---

## 6️⃣ **Complete Code Examples**

### **Example 1: .env Configuration**

```bash
# .env
# Database
DATABASE_URL=postgresql://pdf_user:secure_password@localhost:5432/pdf_processing

# API Keys
GENAI_API_KEY=AIzaSyC_your_actual_key_here
GENAI_MODEL=models/gemini-2.5-flash

# File Storage
MAX_FILE_SIZE_MB=50
FILE_RETENTION_DAYS=30

# Logging
LOG_LEVEL=INFO
LOG_DIR=logs
```

### **Example 2: Complete Gradio Integration**

```python
# app_gradio.py (simplified example)
import gradio as gr
from database import get_db, check_db_connection
from services.job_service import JobService
from config import Config

def process_translation_with_tracking(pdf_file, language):
    """Process translation with full database tracking"""
    
    if not pdf_file:
        return None, "No file uploaded"
    
    try:
        # Save uploaded file
        temp_path = save_uploaded_file_to_temp(pdf_file)
        
        # Create job
        with get_db() as db:
            job = JobService.create_job(
                db=db,
                user_id=1,  # Default user for now
                job_type="translate",
                input_filepath=temp_path,
                target_language=language
            )
            job_id = job.job_id
        
        # Run translation
        output_path, error = run_translate_pipeline(temp_path, language)
        
        # Update database
        with get_db() as db:
            if error:
                JobService.update_job_status(db, job_id, "failed", error_message=error)
                return None, error
            else:
                # Store output info
                output_hash = calculate_md5(output_path)
                output_size = os.path.getsize(output_path)
                
                JobService.update_job_status(
                    db, job_id, "completed",
                    output_filename=os.path.basename(output_path),
                    output_filepath=output_path,
                    output_file_size=output_size,
                    output_file_hash=output_hash
                )
                
                return output_path, f"✅ Translation completed (Job ID: {job_id})"
    
    except Exception as e:
        logger.error(f"Translation failed: {e}", exc_info=True)
        return None, f"Error: {str(e)}"

# Gradio interface
with gr.Blocks() as demo:
    with gr.Tab("Translation"):
        pdf_input = gr.File(label="Upload PDF", file_types=[".pdf"])
        lang_dropdown = gr.Dropdown(
            choices=["hi", "te", "or"],
            label="Target Language"
        )
        translate_btn = gr.Button("Translate")
        output = gr.File(label="Translated PDF")
        status = gr.Textbox(label="Status")
        
        translate_btn.click(
            process_translation_with_tracking,
            inputs=[pdf_input, lang_dropdown],
            outputs=[output, status]
        )

if __name__ == "__main__":
    check_db_connection()
    demo.launch()
```

---

## 📊 **Summary**

### **Problem Fixes: ✅ COMPLETE**

| Issue | Solution | Status |
|-------|----------|--------|
| Module caching | Aggressive reload with cache clearing | ✅ Implemented |
| Environment mismatch | Force reload .env with verification | ✅ Implemented |
| File verification | MD5 hash + size logging | ✅ Implemented |
| Content classification | Sync CLI/Gradio pipelines | ✅ Implemented |
| PDF generator mismatch | Use OverlayPDFGenerator in both | ✅ Implemented |

### **Database Solution: PostgreSQL**

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Metadata DB | PostgreSQL 15+ | Best JSONB support, ACID, scalable |
| JSON Storage | JSONB columns | Queryable JSON with indexes |
| File Storage | Local FS / S3 | PDFs stored separately from DB |
| ORM | SQLAlchemy | Type-safe, migration-friendly |

### **Schema Design: 6 Tables**

1. ✅ **users** - User accounts
2. ✅ **processing_jobs** - Main job tracking
3. ✅ **json_data** - Extracted/translated JSON
4. ✅ **processing_logs** - Detailed logging
5. ✅ **file_storage** - File metadata
6. ✅ **api_usage** - API usage tracking

---

## 🚀 **Next Steps**

### **Implementation Checklist:**

- [ ] Install PostgreSQL and create database
- [ ] Run schema creation SQL
- [ ] Install Python dependencies
- [ ] Create `database.py`, `models.py`, `services/job_service.py`
- [ ] Update `app_gradio.py` with database integration
- [ ] Set up Alembic for migrations
- [ ] Test CLI vs Gradio with database tracking
- [ ] Verify MD5 hashes match between CLI and Gradio
- [ ] Set up backup/retention policies

---

**Created:** November 17, 2025  
**Status:** Complete implementation guide  
**Next Review:** After PostgreSQL setup

