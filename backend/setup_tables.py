# Awal Proyek untuk Reset, dalam kasus penambahan anak magang baru.
# Setelah itu Jalankan Script : index_data.py

import psycopg2
import sys
from pathlib import Path

# --- KONFIGURASI DAN IMPORT ---
try:
    # Memastikan path modul backend/utils dapat ditemukan untuk import EMBEDDING_DIM
    PROJECT_ROOT = Path(__file__).resolve().parent
    sys.path.insert(0, str(PROJECT_ROOT)) 
    from backend.utils import EMBEDDING_DIM 
except ImportError as e:
    print(f"❌ FATAL ERROR: Gagal mengimpor utilitas: {e}")
    sys.exit(1)

# --- KONFIGURASI DATABASE VEKTOR (PostgreSQL + pgvector) ---
DB_CONFIG = {
    "host": "localhost",
    "database": "intern_attendance_db",
    "user": "macbookpro",
    "password": "deepfacepass",
    "port": "5432"
}
DB_TABLE_INTERNS = "interns" 
DB_TABLE_LOGS = "attendance_logs"
DB_TABLE_EMBEDDINGS = "intern_embeddings"
DB_TABLE_CENTROIDS = "intern_centroids"


def connect_db():
    """Membuat koneksi ke Database."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except psycopg2.Error as e:
        print(f"❌ FATAL: Gagal koneksi ke Database: {e}")
        print("   -> Pastikan PostgreSQL server (Docker) berjalan.")
        sys.exit(1)

def setup_database():
    conn = connect_db()
    cur = conn.cursor()
    
    print("==================================================")
    print("🛠️ SCRIPT SETUP AWAL DATABASE (DROP & CREATE ALL)")
    print("==================================================")
    
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;") 
        conn.commit()
        
        # --- 1. DROP TABEL ANAK (LOGS, EMBEDDINGS, CENTROIDS) TERLEBIH DAHULU ---
        print("   -> Menghapus tabel anak...")
        cur.execute(f"DROP TABLE IF EXISTS {DB_TABLE_LOGS};")
        cur.execute(f"DROP TABLE IF EXISTS {DB_TABLE_EMBEDDINGS};")
        cur.execute(f"DROP TABLE IF EXISTS {DB_TABLE_CENTROIDS};")
        conn.commit()
        
        # --- 2. DROP TABEL INDUK (INTERNS) ---
        print("   -> Menghapus tabel induk...")
        cur.execute(f"DROP TABLE IF EXISTS {DB_TABLE_INTERNS};")
        conn.commit()

        # --- 3. BUAT ULANG TABEL INDUK (interns) ---
        print("   -> Membuat ulang tabel induk...")
        cur.execute(f"""
            CREATE TABLE {DB_TABLE_INTERNS} (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                instansi TEXT,
                kategori TEXT
            );
        """)
        conn.commit()
        print(f"✅ Tabel '{DB_TABLE_INTERNS}' berhasil dibuat.")
        
        # --- 4. BUAT ULANG TABEL ANAK (attendance_logs) ---
        print("   -> Membuat ulang tabel attendance_logs...")
        cur.execute(f"""
            CREATE TABLE {DB_TABLE_LOGS} (
                log_id SERIAL PRIMARY KEY,
                intern_id INTEGER REFERENCES {DB_TABLE_INTERNS}(id),
                intern_name TEXT NOT NULL,
                instansi TEXT,
                kategori TEXT,  
                image_url TEXT, 
                absent_at TIMESTAMP WITHOUT TIME ZONE DEFAULT LOCALTIMESTAMP,
                type TEXT NOT NULL DEFAULT 'IN'
            );
        """)
        conn.commit()
        print(f"✅ Tabel '{DB_TABLE_LOGS}' berhasil dibuat.")
        
        # --- 5. BUAT ULANG TABEL ANAK (intern_embeddings) ---
        print("   -> Membuat ulang tabel intern_embeddings...")
        cur.execute(f"""
            CREATE TABLE {DB_TABLE_EMBEDDINGS} (
                id SERIAL PRIMARY KEY,
                intern_id INTEGER REFERENCES {DB_TABLE_INTERNS}(id), 
                name VARCHAR(100) NOT NULL,
                instansi VARCHAR(100),
                kategori VARCHAR(100),
                image_path VARCHAR(255) NOT NULL,
                embedding vector({EMBEDDING_DIM}) NOT NULL
            );
        """)
        conn.commit()
        print(f"✅ Tabel '{DB_TABLE_EMBEDDINGS}' berhasil dibuat (vector size: {EMBEDDING_DIM}).")

        # --- 6. BUAT ULANG TABEL ANAK (intern_centroids) ---
        print("   -> Membuat ulang tabel intern_centroids...")
        cur.execute(f"""
            CREATE TABLE {DB_TABLE_CENTROIDS} (
                id SERIAL PRIMARY KEY,
                intern_id INTEGER REFERENCES {DB_TABLE_INTERNS}(id) UNIQUE, 
                name TEXT NOT NULL UNIQUE,
                instansi TEXT,
                kategori TEXT,
                embedding vector({EMBEDDING_DIM}) NOT NULL
            );
        """)
        conn.commit()
        print(f"✅ Tabel '{DB_TABLE_CENTROIDS}' berhasil dibuat.")

    except Exception as e:
        print(f"❌ ERROR FATAL: Gagal membuat/memperbarui tabel database: {e}")
        sys.exit(1)
        
    finally:
        cur.close()
        conn.close()
        print("\n🎉 SETUP DATABASE LENGKAP!")


if __name__ == "__main__":
    setup_database()