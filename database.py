"""
Database Connection and Session Management
------------------------------------------
Provides database connection, session management, and utilities
for the PDF processing system.

Uses SQLAlchemy ORM with PostgreSQL.
"""

from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.pool import Pool
from contextlib import contextmanager
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
ENV_FILE = Path(__file__).parent / '.env'
if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=True)

# Configure logging
logger = logging.getLogger(__name__)

# ============================================================
# DATABASE CONFIGURATION
# ============================================================

# Get database URL from environment
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://pdf_user:pdf_password@localhost:5432/pdf_processing'
)

# Connection pool settings
POOL_SIZE = int(os.getenv('DB_POOL_SIZE', '10'))
MAX_OVERFLOW = int(os.getenv('DB_MAX_OVERFLOW', '20'))
POOL_TIMEOUT = int(os.getenv('DB_POOL_TIMEOUT', '30'))
POOL_RECYCLE = int(os.getenv('DB_POOL_RECYCLE', '3600'))  # 1 hour

# SQL echo for debugging (set to True to see all SQL queries)
SQL_ECHO = os.getenv('SQL_ECHO', 'false').lower() == 'true'

# ============================================================
# ENGINE CREATION
# ============================================================

# Create database engine
engine = create_engine(
    DATABASE_URL,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=POOL_TIMEOUT,
    pool_recycle=POOL_RECYCLE,
    pool_pre_ping=True,  # Verify connections before using
    echo=SQL_ECHO,  # Log SQL queries if enabled
    future=True  # Use SQLAlchemy 2.0 style
)

# ============================================================
# SESSION FACTORY
# ============================================================

# Create session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False
)

# Base class for all ORM models
Base = declarative_base()

# ============================================================
# CONNECTION UTILITIES
# ============================================================

@contextmanager
def get_db() -> Session:
    """
    Context manager for database sessions.
    
    Usage:
        with get_db() as db:
            user = db.query(User).first()
            # ... operations ...
            # Auto-commit on success, auto-rollback on error
    
    Yields:
        Session: Database session
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        db.close()


def get_db_session() -> Session:
    """
    Get a database session (for manual management).
    
    Note: You must call session.close() when done.
    Prefer using get_db() context manager instead.
    
    Returns:
        Session: Database session
    """
    return SessionLocal()


def check_db_connection() -> bool:
    """
    Test database connection and return status.
    
    Returns:
        bool: True if connection successful, False otherwise
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
        
        logger.info("✅ Database connection successful")
        print("✅ Database connection successful")
        return True
        
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        print(f"❌ Database connection failed: {e}")
        return False


def get_db_info() -> dict:
    """
    Get database connection information.
    
    Returns:
        dict: Database configuration details
    """
    # Parse DATABASE_URL to get components (safely)
    from urllib.parse import urlparse
    
    try:
        parsed = urlparse(DATABASE_URL)
        
        info = {
            "driver": parsed.scheme,
            "host": parsed.hostname,
            "port": parsed.port,
            "database": parsed.path.lstrip('/'),
            "username": parsed.username,
            "pool_size": POOL_SIZE,
            "max_overflow": MAX_OVERFLOW,
            "pool_timeout": POOL_TIMEOUT,
            "connected": False
        }
        
        # Test connection
        info["connected"] = check_db_connection()
        
        return info
        
    except Exception as e:
        logger.error(f"Error getting database info: {e}")
        return {
            "error": str(e),
            "connected": False
        }


def create_all_tables():
    """
    Create all database tables defined in models.
    
    Note: This should only be used for initial setup or testing.
    For production, use Alembic migrations instead.
    """
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("✅ All database tables created successfully")
        print("✅ All database tables created successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Error creating tables: {e}")
        print(f"❌ Error creating tables: {e}")
        return False


def drop_all_tables():
    """
    Drop all database tables.
    
    ⚠️ WARNING: This will delete ALL data! Use with caution!
    Only use for testing/development.
    """
    try:
        Base.metadata.drop_all(bind=engine)
        logger.warning("⚠️ All database tables dropped")
        print("⚠️ All database tables dropped")
        return True
    except Exception as e:
        logger.error(f"❌ Error dropping tables: {e}")
        print(f"❌ Error dropping tables: {e}")
        return False


# ============================================================
# CONNECTION POOL EVENTS
# ============================================================

@event.listens_for(Pool, "connect")
def set_postgres_pragma(dbapi_conn, connection_record):
    """Set PostgreSQL connection parameters on connect"""
    cursor = dbapi_conn.cursor()
    # Set timezone to UTC
    cursor.execute("SET timezone='UTC'")
    cursor.close()


@event.listens_for(Pool, "checkout")
def receive_checkout(dbapi_conn, connection_record, connection_proxy):
    """Log when a connection is checked out from the pool"""
    logger.debug("Connection checked out from pool")


# ============================================================
# HEALTH CHECK
# ============================================================

def health_check() -> dict:
    """
    Comprehensive database health check.
    
    Returns:
        dict: Health status with details
    """
    health = {
        "status": "unknown",
        "database_url": DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else "not configured",
        "connection": False,
        "pool_size": POOL_SIZE,
        "pool_checked_out": 0,
        "pool_overflow": 0,
        "pool_total": 0
    }
    
    try:
        # Test connection
        health["connection"] = check_db_connection()
        
        # Get pool stats
        pool = engine.pool
        health["pool_checked_out"] = pool.checkedout()
        health["pool_overflow"] = pool.overflow()
        health["pool_total"] = pool.size()
        
        # Determine overall status
        if health["connection"]:
            health["status"] = "healthy"
        else:
            health["status"] = "unhealthy"
        
    except Exception as e:
        health["status"] = "error"
        health["error"] = str(e)
        logger.error(f"Health check failed: {e}")
    
    return health


# ============================================================
# INITIALIZATION
# ============================================================

def initialize_database(create_tables: bool = False):
    """
    Initialize database connection and optionally create tables.
    
    Args:
        create_tables (bool): If True, create all tables
    
    Returns:
        bool: True if successful
    """
    try:
        # Check connection
        if not check_db_connection():
            logger.error("Failed to connect to database")
            return False
        
        # Create tables if requested
        if create_tables:
            logger.info("Creating database tables...")
            create_all_tables()
        
        # Print pool info
        logger.info(f"Database pool configured: size={POOL_SIZE}, max_overflow={MAX_OVERFLOW}")
        
        return True
        
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return False


# ============================================================
# EXAMPLE USAGE
# ============================================================

if __name__ == "__main__":
    """
    Test database connection when run directly
    """
    print("\n" + "="*70)
    print("DATABASE CONNECTION TEST")
    print("="*70)
    
    # Show configuration
    info = get_db_info()
    print(f"\n📊 Database Configuration:")
    print(f"   Driver: {info.get('driver', 'N/A')}")
    print(f"   Host: {info.get('host', 'N/A')}")
    print(f"   Port: {info.get('port', 'N/A')}")
    print(f"   Database: {info.get('database', 'N/A')}")
    print(f"   Username: {info.get('username', 'N/A')}")
    print(f"   Pool Size: {info.get('pool_size', 'N/A')}")
    
    # Test connection
    print(f"\n🔌 Testing connection...")
    if check_db_connection():
        print("\n✅ Database is ready!")
    else:
        print("\n❌ Database connection failed!")
        print("\nTroubleshooting:")
        print("1. Check DATABASE_URL in .env file")
        print("2. Ensure PostgreSQL is running")
        print("3. Verify username and password")
        print("4. Check if database exists")
    
    # Health check
    print(f"\n🏥 Health Check:")
    health = health_check()
    for key, value in health.items():
        print(f"   {key}: {value}")
    
    print("\n" + "="*70)

