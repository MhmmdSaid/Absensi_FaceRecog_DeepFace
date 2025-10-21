import psycopg2
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# --- KONFIGURASI DAN IMPORT ---
try:
    PROJECT_ROOT = Path(__file__).resolve().parent
    # Tambahkan PROJECT_ROOT/backend ke sys.path agar bisa import utils
    sys.path.insert(0, str(PROJECT_ROOT))
    # Coba import absolut
    try:
        from backend.utils import EMBEDDING_DIM
    except ImportError:
         # Fallback ke import relatif jika dijalankan sebagai modul
         from .utils import EMBEDDING_DIM

except ImportError as e:
    print(f"❌ FATAL ERROR: Gagal mengimpor utilitas: {e}")
    print("   -> Pastikan file utils.py ada di backend/utils.py")
    sys.exit(1)

# --- KONFIGURASI DATABASE VEKTOR (MEMBACA DARI ENV) ---
# Memuat .env untuk eksekusi LOKAL (dari Mac)
env_path = PROJECT_ROOT.parent / '.env'  # .env ada di level atas (PROJECT_ROOT)
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    print(f"   -> Memuat konfigurasi dari {env_path}")
else:
    print(f"   ⚠️ PERINGATAN: File .env tidak ditemukan di {env_path}, menggunakan fallback.")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")  # Akan diambil dari .env (5435)
DB_NAME = os.getenv("DB_NAME", "intern_attendance_db")
DB_USER = os.getenv("DB_USER", "macbookpro")
DB_PASSWORD = os.getenv("DB_PASSWORD", "deepfacepass")
# --------------------------------------------------------

DB_TABLE_INTERNS = "interns"
DB_TABLE_LOGS = "attendance_logs"
DB_TABLE_EMBEDDINGS = "intern_embeddings"
DB_TABLE_CENTROIDS = "intern_centroids"


def connect_db():
    """Membuat koneksi ke Database."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            port=DB_PORT
        )
        return conn
    except psycopg2.Error as e:
        print(f"❌ FATAL: Gagal koneksi ke Database: {e}")
        print(f"   -> Mencoba terhubung ke {DB_HOST}:{DB_PORT}...")
        print("   -> Pastikan .env Anda benar (DB_PORT=5435) dan Docker berjalan.")
        sys.exit(1)


def setup_database():
    conn = connect_db()
    cur = conn.cursor()

    print("==================================================")
    print("🛠️ SCRIPT SETUP AWAL DATABASE (DROP & CREATE ALL)")
    print("==================================================")

    try:
        print("   -> Memastikan ekstensi 'vector' aktif...")
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        conn.commit()
        print("✅ Ekstensi 'vector' aktif.")

        print("   -> Menghapus tabel anak (jika ada)...")
        cur.execute(f"DROP TABLE IF EXISTS {DB_TABLE_LOGS} CASCADE;") # Gunakan CASCADE
        cur.execute(f"DROP TABLE IF EXISTS {DB_TABLE_EMBEDDINGS} CASCADE;")
        cur.execute(f"DROP TABLE IF EXISTS {DB_TABLE_CENTROIDS} CASCADE;")
        conn.commit()
        print("✅ Tabel anak dihapus.")

        print("   -> Menghapus tabel induk (jika ada)...")
        cur.execute(f"DROP TABLE IF EXISTS {DB_TABLE_INTERNS} CASCADE;")
        conn.commit()
        print("✅ Tabel induk dihapus.")

        print("\n   -> Membuat ulang tabel induk 'interns'...")
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

        print("   -> Membuat ulang tabel 'attendance_logs'...")
        cur.execute(f"""
            CREATE TABLE {DB_TABLE_LOGS} (
                log_id SERIAL PRIMARY KEY,
                intern_id INTEGER REFERENCES {DB_TABLE_INTERNS}(id) ON DELETE CASCADE, -- Tambah ON DELETE CASCADE
                intern_name TEXT NOT NULL,
                instansi TEXT,
                kategori TEXT,
                image_url TEXT,
                absent_at TIMESTAMP WITHOUT TIME ZONE, -- Hapus DEFAULT LOCALTIMESTAMP
                type TEXT NOT NULL DEFAULT 'IN'
            );
        """)
        conn.commit()
        print(f"✅ Tabel '{DB_TABLE_LOGS}' berhasil dibuat.")

        print("   -> Membuat ulang tabel 'intern_embeddings'...")
        cur.execute(f"""
            CREATE TABLE {DB_TABLE_EMBEDDINGS} (
                id SERIAL PRIMARY KEY,
                intern_id INTEGER REFERENCES {DB_TABLE_INTERNS}(id) ON DELETE CASCADE, -- Tambah ON DELETE CASCADE
                name VARCHAR(100) NOT NULL,
                instansi VARCHAR(100),
                kategori VARCHAR(100),
                file_path TEXT NOT NULL UNIQUE, -- Tambah UNIQUE constraint? Atau hapus jika path bisa sama?
                embedding vector({EMBEDDING_DIM}) NOT NULL
            );
        """)
        conn.commit()
        print(f"✅ Tabel '{DB_TABLE_EMBEDDINGS}' berhasil dibuat (vector size: {EMBEDDING_DIM}).")

        print("   -> Membuat ulang tabel 'intern_centroids'...")
        cur.execute(f"""
            CREATE TABLE {DB_TABLE_CENTROIDS} (
                id SERIAL PRIMARY KEY,
                intern_id INTEGER REFERENCES {DB_TABLE_INTERNS}(id) ON DELETE CASCADE UNIQUE, -- Tambah ON DELETE CASCADE
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
        conn.rollback() # Rollback jika ada error
        sys.exit(1)

    finally:
        cur.close()
        conn.close()
        print("\n🎉 SETUP DATABASE LENGKAP!")


if __name__ == "__main__":
    setup_database()