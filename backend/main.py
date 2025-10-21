import time
import sys
import subprocess
from fastapi import BackgroundTasks
import os
# from dotenv import load_dotenv # <-- DIHAPUS/KOMENTARI
import psycopg2
import psycopg2.extensions
import numpy as np
import shutil
import uuid

# load_dotenv() # <-- DIHAPUS/KOMENTARI

from pathlib import Path
from datetime import date, timedelta, datetime
import io
# import webbrowser # <-- DIHAPUS/KOMENTARI
from typing import List, Optional, Dict

import pytz # <<< KRITIS: Import Pytz untuk Zona Waktu

# --- IMPORTS SCHEDULER ---
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
# ---

# Import gTTS library for automatic Text-to-Speech generation
try:
    from gtts import gTTS
except ImportError:
    print("WARNING: gTTS library not found. Audio generation might fail.")

    # DEFINE MOCK CLASS DAN FUNGSI DUMMY DI SINI DENGAN INDENTASI YANG BENAR
    class MockTTS:
        """Kelas dummy untuk menggantikan gTTS jika tidak ada."""
        def __init__(self, text, lang):
            self.text = text
            self.lang = lang

        def save(self, path):
            print(f"Mock TTS save: (No TTS library installed) Text: {self.text}")

    # Fungsi gTTS dummy yang mengembalikan MockTTS (Perbaikan Pylance)
    def gTTS(text, lang='id'):
        return MockTTS(text, lang)

# Import library FastAPI
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.staticfiles import StaticFiles
from starlette.status import HTTP_302_FOUND
from starlette.responses import RedirectResponse, JSONResponse

# Import DeepFace (pastikan sudah terinstal: pip install deepface)
try:
    from deepface import DeepFace
except ImportError:
    print("WARNING: DeepFace library not found. Registration API might fail.")
    DeepFace = None

# --- PATH & KONFIGURASI ---
# Asumsi struktur: Root/backend/main.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Impor fungsi dan konfigurasi dari file lain (asumsi ada di backend/utils.py)
try:
    # Coba import absolut dulu (umumnya lebih baik)
    from backend.utils import extract_face_features, DISTANCE_THRESHOLD
except ImportError:
    try:
         # Fallback ke import relatif jika dijalankan sebagai modul
        from .utils import extract_face_features, DISTANCE_THRESHOLD
    except ImportError:
         # Fallback terakhir jika utils.py tidak ditemukan
        print("⚠️ Peringatan: Gagal mengimpor utilitas (utils.py). Pastikan file ini ada di backend/utils.py.")
        def extract_face_features(image_bytes): return []
        DISTANCE_THRESHOLD = 0.5

# --- KONFIGURASI DB (DIBACA DARI ENV YANG DISUNTIK DOCKER) ---
DB_HOST = os.getenv("DB_HOST", "localhost") # Akan menjadi 'postgres' di Docker
DB_PORT = os.getenv("DB_PORT", "5432") # Akan menjadi '5432' di Docker
DB_NAME = os.getenv("DB_NAME", "intern_attendance_db")
DB_USER = os.getenv("DB_USER", "macbookpro")
DB_PASSWORD = os.getenv("DB_PASSWORD", "deepfacepass")

# FOLDER UNTUK GAMBAR
CAPTURED_IMAGES_DIR = PROJECT_ROOT / "backend" / "captured_images"
FACES_DIR = PROJECT_ROOT / "data" / "dataset" # KRITIS: Path Dataset
FRONTEND_STATIC_DIR = PROJECT_ROOT / "frontend"
AUDIO_FILES_DIR = PROJECT_ROOT / "backend" / "generated_audio"

# --- KONFIGURASI ZONA WAKTU ---
local_tz = pytz.timezone('Asia/Jakarta') # <<< TAMBAH: Global Timezone (WIB)

# --- KONFIGURASI SCHEDULER ---
scheduler = None
DAILY_RESET_HOUR = 00 # Pukul 00:00
DAILY_RESET_MINUTE = 00
# ---

# --- INISIALISASI APLIKASI ---
app = FastAPI(title="DeepFace Absensi API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount folder audio, images, dan faces
app.mount("/audio", StaticFiles(directory=str(AUDIO_FILES_DIR), check_dir=True), name="generated_audio")
app.mount("/images", StaticFiles(directory=str(CAPTURED_IMAGES_DIR), check_dir=True), name="captured_images")
app.mount("/faces", StaticFiles(directory=str(FACES_DIR), check_dir=True), name="faces")


# --- FUNGSI UTILITY ---

def get_current_wib_datetime() -> datetime:
    """Mengembalikan objek datetime saat ini dengan zona waktu Asia/Jakarta."""
    return datetime.now(local_tz)

def format_time_to_hms(time_obj) -> str:
    """
    Mengubah objek datetime, date, atau string ISO 8601 menjadi string HH:MM:SS.
    """
    if not time_obj:
        return "N/A"

    if isinstance(time_obj, datetime):
        # Jika time_obj memiliki timezone, konversi ke waktu lokal dan format.
        if time_obj.tzinfo is not None and time_obj.tzinfo.utcoffset(time_obj) is not None:
             time_obj = time_obj.astimezone(local_tz)

        return time_obj.strftime("%H:%M:%S")
    elif isinstance(time_obj, str):
        try:
            # Asumsi string yang masuk adalah ISO 8601 dari DB (misal: "2025-10-16T18:01:29")
            dt = datetime.fromisoformat(time_obj)
            # Jika tidak ada timezone, anggap UTC dan konversi ke WIB
            if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                 dt = pytz.utc.localize(dt).astimezone(local_tz)
            else:
                 dt = dt.astimezone(local_tz) # Konversi jika sudah ada timezone
            return dt.strftime("%H:%M:%S")
        except ValueError:
            # Jika gagal parse, kembalikan string aslinya
            return str(time_obj)
    else:
        # Untuk objek time/date lain, coba konversi ke string
        try:
            return time_obj.strftime("%H:%M:%S")
        except AttributeError:
             return str(time_obj)

def generate_audio_file(filename: str, text: str):
    """Menghasilkan dan menyimpan file audio MP3 menggunakan gTTS jika belum ada."""
    audio_path = AUDIO_FILES_DIR / filename
    os.makedirs(AUDIO_FILES_DIR, exist_ok=True)

    if audio_path.exists():
        return

    try:
        print(f"   -> 🔊 Generating TTS file: {filename} for text: '{text}'...")
        tts = gTTS(text=text, lang='id')
        tts.save(str(audio_path))
    except Exception as e:
        print(f"❌ ERROR: Gagal generate file audio {filename}. Pastikan Anda memiliki koneksi internet: {e}")

# --- LOGIKA VALIDASI ABSENSI KRITIS (Waktu WIB) ---

# Definisikan Aturan Jam Kerja
JADWAL_KERJA = {
    "Mahasiswa Internship": {"MASUK_PALING_LAMBAT": "09:00:00", "PULANG_PALING_CEPAT": "15:00:00"},
    "Staff": {"MASUK_PALING_LAMBAT": "08:30:00", "PULANG_PALING_CEPAT": "17:30:00"},
    "General Manager": {"MASUK_PALING_LAMBAT": "08:30:00", "PULANG_PALING_CEPAT": "17:30:00"},
    "Siswa Magang": {"MASUK_PALING_LAMBAT": "09:00:00", "PULANG_PALING_CEPAT": "15:00:00"}, # Tambahkan Siswa Magang
    "DEFAULT": {"MASUK_PALING_LAMBAT": "09:00:00", "PULANG_PALING_CEPAT": "15:00:00"}
}

def check_attendance_status(kategori: str, type_absensi: str, log_time: datetime) -> str:
    """Menentukan status absensi (Tepat Waktu/Terlambat/Pulang Cepat) berdasarkan kategori dan waktu log."""
    aturan = JADWAL_KERJA.get(kategori, JADWAL_KERJA["DEFAULT"])
    current_time_str = log_time.strftime("%H:%M:%S")

    if type_absensi == 'IN':
        target_time = aturan["MASUK_PALING_LAMBAT"]
        return "Tepat Waktu" if current_time_str <= target_time else "Terlambat"
    elif type_absensi == 'OUT':
        target_time = aturan["PULANG_PALING_CEPAT"]
        return "Tepat Waktu" if current_time_str >= target_time else "Pulang Cepat"
    return "N/A"

# --- FUNGSI DATABASE HELPERS (POSTGRESQL) ---

def connect_db():
    """Membuat koneksi ke Database Vektor/Log (PostgreSQL) dan mendaftarkan tipe vector."""
    conn = None
    try:
        conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASSWORD, port=DB_PORT)
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            conn.commit()
            cur.execute("SELECT oid FROM pg_type WHERE typname = 'vector'")
            row = cur.fetchone()
            if not row:
                raise Exception("❌ Ekstensi pgvector belum aktif di database.")
            vector_oid = row[0]

        def cast_vector(data, cur):
            if data is None: return None
            cleaned_data = data.strip('{}[]')
            return np.array([float(x.strip()) for x in cleaned_data.split(',')])

        psycopg2.extensions.register_type(
            psycopg2.extensions.new_type((vector_oid,), 'vector', cast_vector),
            conn
        )
        return conn
    except psycopg2.Error as e:
        print(f"❌ Gagal koneksi ke Database PostgreSQL: {e}")
        print(f"   -> Mencoba terhubung ke {DB_HOST}:{DB_PORT}")
        if conn: conn.close()
        raise Exception("Database PostgreSQL tidak terhubung/konfigurasi salah.")

def initialize_db():
    """Memastikan tabel ada saat startup (SKEMA BENAR)."""
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS interns (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                instansi TEXT,
                kategori TEXT
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance_logs (
                log_id SERIAL PRIMARY KEY,
                intern_id INTEGER REFERENCES interns(id),
                intern_name TEXT NOT NULL,
                instansi TEXT,
                kategori TEXT,
                image_url TEXT,
                absent_at TIMESTAMP WITHOUT TIME ZONE,
                type TEXT NOT NULL DEFAULT 'IN'
            );
        """)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS intern_embeddings (
                id SERIAL PRIMARY KEY,
                intern_id INTEGER REFERENCES interns(id),
                name TEXT NOT NULL,
                instansi TEXT,
                kategori TEXT,
                embedding VECTOR({EMBEDDING_DIM}) NOT NULL,
                file_path TEXT NOT NULL
            );
        """)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS intern_centroids (
                id SERIAL PRIMARY KEY,
                intern_id INTEGER UNIQUE REFERENCES interns(id),
                name TEXT NOT NULL UNIQUE,
                instansi TEXT,
                kategori TEXT,
                embedding VECTOR({EMBEDDING_DIM}) NOT NULL
            );
        """)

        # Memasukkan data awal interns (jika belum ada)
        initial_interns = [
            ('Said', 'Universitas Muhammadiyah Surabaya', 'Mahasiswa Internship'),
            ('Muarif', 'Universitas Muhammadiyah Surabaya', 'Mahasiswa Internship'),
            ('Nani', 'Universitas Muhammadiyah Surabaya', 'Mahasiswa Internship'),
            ('Vinda', 'Universitas Muhammadiyah Surabaya', 'Mahasiswa Internship'),
            ('Harun', 'Universitas Pakuan Bogor', 'Mahasiswa Internship'),
            ('Pak Nugroho', 'IT Planning', 'General Manager'), # Update kategori
            # Tambahkan intern lain dari CSV jika perlu
            ('A\'yun', 'Universitas Muhammadiyah Surabaya', 'Mahasiswa Internship'),
            ('Isra', 'Universitas Pakuan Bogor', 'Mahasiswa Internship'),
            # ... (Lanjutkan sesuai interns.csv Anda)
        ]
        cursor.executemany("""
            INSERT INTO interns (name, instansi, kategori)
            VALUES (%s, %s, %s)
            ON CONFLICT (name) DO NOTHING;
        """, initial_interns)

        conn.commit()
        print(f"✅ PostgreSQL Database berhasil diinisialisasi.")

        os.makedirs(CAPTURED_IMAGES_DIR, exist_ok=True)
        os.makedirs(FACES_DIR, exist_ok=True)
        os.makedirs(AUDIO_FILES_DIR, exist_ok=True)
        print(f"✅ Folder gambar siap.")

    except psycopg2.Error as e:
        print(f"❌ KRITIS: Gagal menginisialisasi tabel PostgreSQL: {e}")
        if conn: conn.rollback()
        raise Exception(f"Gagal inisialisasi database PostgreSQL: {e}")
    finally:
        if conn: conn.close()

def get_or_create_intern(name: str, instansi: str = "Intern", kategori: str = "Unknown"):
    """Mendapatkan ID intern yang sudah ada atau membuat entri baru di PostgreSQL."""
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, instansi, kategori FROM interns WHERE name = %s", (name,))
        result = cursor.fetchone()
        if result:
            return result[0], result[1], result[2]
        else:
            cursor.execute(
                "INSERT INTO interns (name, instansi, kategori) VALUES (%s, %s, %s) RETURNING id",
                (name, instansi, kategori)
            )
            intern_id = cursor.fetchone()[0]
            conn.commit()
            return intern_id, instansi, kategori
    except Exception as e:
        print(f"❌ Gagal mendapatkan/membuat entri intern di PostgreSQL: {e}")
        if conn: conn.rollback()
        raise Exception(f"Gagal mengelola data intern: {e}")
    finally:
        if conn: conn.close()

def get_latest_attendance(intern_name: str) -> Optional[Dict[str, str]]:
    """Mendapatkan log absensi terakhir untuk intern hari ini (IN/OUT)."""
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT intern_name, type, absent_at
            FROM attendance_logs
            WHERE intern_name = %s AND absent_at::date = CURRENT_DATE
            ORDER BY absent_at DESC
            LIMIT 1
            """,
            (intern_name,)
        )
        result = cursor.fetchone()
        if result:
            return {"name": result[0], "type": result[1], "absent_at": result[2].isoformat()}
        return None
    except Exception as e:
        print(f"❌ Gagal memeriksa log absensi terakhir: {e}")
        return None
    finally:
        if conn: conn.close()


def log_attendance(intern_name: str, instansi: str, kategori: str, image_url: str, type_absensi: str):
    """Mencatat log absensi ke database PostgreSQL (dengan jenis 'IN' atau 'OUT')."""
    conn = None
    try:
        intern_id, _, _ = get_or_create_intern(intern_name, instansi, kategori)
        conn = connect_db()
        cursor = conn.cursor()
        wib_time = get_current_wib_datetime().replace(tzinfo=None)
        cursor.execute(
            "INSERT INTO attendance_logs (intern_id, intern_name, instansi, kategori, image_url, absent_at, type) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (intern_id, intern_name, instansi, kategori, image_url, wib_time, type_absensi)
        )
        conn.commit()
        return intern_id
    except Exception as e:
        print(f"❌ Gagal mencatat log absensi: {e}")
        if conn: conn.rollback()
        return None
    finally:
        if conn: conn.close()

def reset_attendance_logs():
    """Menghapus SEMUA log absensi HARI INI dari tabel attendance_logs."""
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM attendance_logs WHERE absent_at::date = CURRENT_DATE")
        deleted_count = cursor.rowcount
        conn.commit()
        print(f"✅ [SCHEDULER] RESET ABSENSI BERHASIL: {deleted_count} log hari ini dihapus.")
        return deleted_count
    except Exception as e:
        print(f"❌ Gagal mereset log absensi PostgreSQL: {e}")
    finally:
        if conn: conn.close()

# --- FUNGSI SUBPROCESS YANG DIPERBAIKI (SANGAT KRITIS) ---

def run_indexing_subprocess():
    """
    Fungsi wrapper yang akan dijalankan oleh Background Task.
    Meneruskan env var yang benar ke subprocess.
    """
    print("🚀 [Background Task] Memulai subprocess index_data.py...")
    try:
        command = [sys.executable, "-u", "-m", "backend.index_data"]

        # --- PERUBAHAN KRITIS: Teruskan Environment Variables ---
        current_env = os.environ.copy()
        current_env["DB_HOST"] = DB_HOST
        current_env["DB_PORT"] = DB_PORT
        current_env["DB_NAME"] = DB_NAME
        current_env["DB_USER"] = DB_USER
        current_env["DB_PASSWORD"] = DB_PASSWORD
        # Juga teruskan PYTHONPATH jika ada, penting untuk import
        if 'PYTHONPATH' in os.environ:
             current_env['PYTHONPATH'] = os.environ['PYTHONPATH']
        # ----------------------------------------------------

        process = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True,
            env=current_env  # <<< Menggunakan env yang dimodifikasi
        )

        print("✅ [Background Task] Indexing Selesai.")
        print(process.stdout)

    except subprocess.CalledProcessError as e:
        print(f"❌ [Background Task] Indexing Gagal (Error Subprocess):")
        print("================== STANDARD ERROR (stderr) ==================")
        print(e.stderr)
        print("================== STANDARD OUTPUT (stdout) ==================")
        print(e.stdout)
        print("===========================================================")

    except Exception as e:
        print(f"❌ [Background Task] Gagal menjalankan subprocess: {e}")

# --- STARTUP EVENT (VERSI DEPLOY) ---

@app.on_event("startup")
async def startup_event():
    """Melakukan inisialisasi DB dan menjadwalkan reset saat startup."""
    try:
        initialize_db()
    except Exception as e:
        print(f"❌ Gagal menjalankan aplikasi karena inisialisasi DB gagal: {e}")
        sys.exit(1)

    # --- LOGIKA PENJADWALAN ---
    global scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        reset_attendance_logs,
        CronTrigger(hour=DAILY_RESET_HOUR, minute=DAILY_RESET_MINUTE, timezone=str(local_tz)), # Tambahkan timezone
        id='daily_attendance_reset',
        name='Daily Absensi Log Reset'
    )
    scheduler.start()
    print(f"✅ Penjadwalan reset absensi harian ({DAILY_RESET_HOUR}:{DAILY_RESET_MINUTE} WIB) aktif.")
    print("✅ Startup event selesai. Server siap menerima koneksi.")


# --- ENDPOINTS DATA COLLECTOR ---

@app.post("/upload_dataset")
async def upload_dataset(name: str = Form(...), instansi: str = Form("Intern"), kategori: str = Form("Unknown"), file: UploadFile = File(...)):
    """Menerima file gambar, menyimpan di folder dataset, dan mendaftarkan intern jika belum ada."""
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Nama tidak boleh kosong.")
    try:
        intern_id, instansi_reg, kategori_reg = get_or_create_intern(clean_name, instansi, kategori)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal memproses intern ID: {e}")

    face_folder = FACES_DIR / clean_name
    os.makedirs(face_folder, exist_ok=True)
    file_path = face_folder / file.filename
    try:
        image_bytes = await file.read()
        with open(file_path, "wb") as f:
            f.write(image_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal menyimpan file gambar: {e}")
    print(f"✅ FILE DATASET TERSIMPAN: {clean_name} - {file.filename}")
    return {"status": "success", "message": f"Gambar tersimpan di folder {clean_name}."}


# --- ENDPOINTS ABSENSI ---

@app.post("/recognize")
async def recognize_face(file: UploadFile = File(...), type_absensi: str = Form(...)):
    """Endpoint utama untuk deteksi wajah dan pencocokan cepat."""
    start_time = time.time()
    image_bytes = await file.read()
    type_absensi = type_absensi.upper()
    image_url_for_db = ""

    if type_absensi not in ['IN', 'OUT']:
        generate_audio_file("S005.mp3", "Kesalahan tipe absensi.")
        raise HTTPException(status_code=400, detail="Invalid type_absensi.")

    emb_list = extract_face_features(image_bytes)
    if not emb_list:
        generate_audio_file("S002.mp3", "Wajah tidak terdeteksi.")
        return {"status": "error", "message": "Wajah tidak terdeteksi.", "track_id": "S002.mp3", "image_url": image_url_for_db}
    new_embedding = emb_list[0]

    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        vector_string = "[" + ",".join(map(str, new_embedding)) + "]"
        cursor.execute(f"""
            SELECT name, instansi, kategori, embedding <=> '{vector_string}'::vector AS distance
            FROM intern_centroids
            ORDER BY distance ASC
            LIMIT 1
        """)
        result = cursor.fetchone()

        if result:
            name, instansi, kategori, distance = result
            elapsed_time = time.time() - start_time

            if distance <= DISTANCE_THRESHOLD:
                latest_log = get_latest_attendance(name)
                if latest_log and latest_log['type'] == type_absensi:
                    print(f"✅ DUPLIKAT ABSENSI: {name} | Sudah Absen {type_absensi}.")
                    audio_filename = f"duplicate_{type_absensi.lower()}_{name.replace(' ', '_')}.mp3"
                    message_text = f"{name}, Anda sudah Absen Masuk hari ini." if type_absensi == 'IN' else f"Absensi Pulang {name} sudah dicatat."
                    generate_audio_file(audio_filename, message_text)
                    log_time_display = format_time_to_hms(latest_log['absent_at'])
                    return {"status": "duplicate", "name": name, "instansi": instansi, "kategori": kategori, "distance": f"{distance:.4f}", "latency": f"{elapsed_time:.2f}s", "track_id": audio_filename, "type": type_absensi, "log_time": log_time_display}

                timestamp = get_current_wib_datetime().strftime("%Y%m%d_%H%M%S") # Gunakan WIB
                clean_name = name.strip().replace(' ', '_').replace('.', '').replace('/', '_').replace('\\', '_').lower()
                image_filename = f"{timestamp}_{clean_name}_{type_absensi}.jpg"
                image_path = CAPTURED_IMAGES_DIR / image_filename
                temp_image_url = ""
                try:
                    with open(image_path, "wb") as f: f.write(image_bytes)
                    temp_image_url = f"/images/{image_filename}"
                except Exception as file_error:
                    print(f"   ❌ GAGAL SIMPAN GAMBAR: {name}. Error: {file_error}")
                image_url_for_db = temp_image_url

                log_attendance(name, instansi, kategori, image_url_for_db, type_absensi)
                current_log_time = get_current_wib_datetime()
                log_time_display = format_time_to_hms(current_log_time)
                attendance_status_result = check_attendance_status(kategori, type_absensi, current_log_time)

                if type_absensi == 'IN':
                    message_text = f"Selamat datang, {name}." if attendance_status_result != "Terlambat" else f"Maaf, {name}. Absensi masuk Anda terlambat."
                else:
                    message_text = f"Terima kasih, {name}." if attendance_status_result != "Pulang Cepat" else f"Peringatan, {name}. Anda Pulang Cepat."

                print(f"✅ DETEKSI BERHASIL: {name} ({type_absensi}) | Status: {attendance_status_result} | Jarak: {distance:.4f} | Latensi: {elapsed_time:.2f}s")
                audio_filename = f"log_{clean_name}_{type_absensi.lower()}.mp3"
                generate_audio_file(audio_filename, message_text)

                return {"status": "success", "name": name, "instansi": instansi, "kategori": kategori, "distance": f"{distance:.4f}", "latency": f"{elapsed_time:.2f}s", "track_id": audio_filename, "type": type_absensi, "image_url": image_url_for_db, "log_time": log_time_display, "attendance_status": attendance_status_result}
            else:
                print(f"❌ DETEKSI GAGAL: Jarak Terlalu Jauh ({distance:.4f}) | Latensi: {elapsed_time:.2f}s")
                generate_audio_file("S003.mp3", "Wajah Anda belum terdaftar.")
                return {"status": "unrecognized", "message": "Wajah Anda Belum Terdaftar", "track_id": "S003.mp3", "image_url": image_url_for_db}
        else:
            generate_audio_file("S003.mp3", "Wajah Anda belum terdaftar.")
            return {"status": "error", "message": "Sistem kosong, lakukan indexing.", "track_id": "S003.mp3", "image_url": image_url_for_db}
    except Exception as e:
        print(f"❌ ERROR PENCARIAN/ABSENSI: {e}")
        generate_audio_file("S004.mp3", "Kesalahan server terjadi.")
        return {"status": "error", "message": f"Kesalahan server: {str(e)}", "track_id": "S004.mp3", "image_url": image_url_for_db}
    finally:
        if conn: conn.close()

# --- ENDPOINTS DATA (data.html) ---

@app.get("/attendance/today")
async def get_today_attendance():
    """Mendapatkan daftar log absensi unik terakhir hari ini."""
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute("""
            WITH LatestAttendance AS (
                SELECT
                    log_id, intern_name, instansi, kategori, image_url, absent_at, type,
                    ROW_NUMBER() OVER(PARTITION BY intern_name ORDER BY absent_at DESC) as rn
                FROM attendance_logs
                WHERE absent_at::date = CURRENT_DATE
            )
            SELECT intern_name, instansi, kategori, absent_at, image_url, type
            FROM LatestAttendance
            WHERE rn = 1
            ORDER BY absent_at DESC;
        """)
        results = cursor.fetchall()
        attendance_list = []
        for name, instansi, kategori, time_obj, image_url, log_type in results:
            log_datetime_wib = time_obj # Asumsi DB menyimpan UTC atau tanpa TZ
            # Jika DB menyimpan tanpa TZ, kita anggap itu UTC lalu konversi ke WIB
            # Jika sudah ada TZ, astimezone akan menanganinya
            if time_obj.tzinfo is None or time_obj.tzinfo.utcoffset(time_obj) is None:
                log_datetime_wib = pytz.utc.localize(time_obj).astimezone(local_tz)
            else:
                log_datetime_wib = time_obj.astimezone(local_tz)

            status_kepatuhan = check_attendance_status(kategori, log_type, log_datetime_wib)
            status_display = f"MASUK ({status_kepatuhan})" if log_type == 'IN' else f"PULANG ({status_kepatuhan})"
            attendance_list.append({
                "name": name,
                "instansi": instansi,
                "kategori": kategori,
                "status": status_display,
                "timestamp": format_time_to_hms(log_datetime_wib), # Gunakan WIB yang sudah dikonversi
                "distance": 0.0000,
                "image_path": image_url
            })
        return attendance_list
    except Exception as e:
        print(f"❌ Error mengambil daftar absensi hari ini: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

# --- ENDPOINTS PENGATURAN (settings.html) ---

@app.post("/reset_absensi")
async def reset_daily_attendance():
    """Menghapus semua log absensi hari ini (Manual Trigger)."""
    try:
        deleted_count = reset_attendance_logs()
        return JSONResponse(content={
            "status": "success",
            "message": f"Berhasil mereset log absensi hari ini. {deleted_count} log dihapus.",
            "deleted_count": deleted_count
        })
    except Exception as e:
        print(f"❌ Error saat mereset absensi: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/delete_face/{name}")
async def delete_face(name: str):
    """Menghapus data wajah dari database dan file dari disk."""
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        # Dapatkan intern_id sebelum menghapus
        cursor.execute("SELECT id FROM interns WHERE name = %s", (name,))
        result = cursor.fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Intern tidak ditemukan.")
        intern_id = result[0]

        # Hapus dari tabel anak dulu
        cursor.execute("DELETE FROM intern_centroids WHERE intern_id = %s", (intern_id,))
        cursor.execute("DELETE FROM intern_embeddings WHERE intern_id = %s", (intern_id,))
        deleted_vectors = cursor.rowcount
        # Hapus log absensi? (Opsional, mungkin ingin disimpan)
        # cursor.execute("DELETE FROM attendance_logs WHERE intern_id = %s", (intern_id,))

        # Hapus dari tabel induk
        cursor.execute("DELETE FROM interns WHERE id = %s", (intern_id,))
        conn.commit()

        # Hapus folder gambar
        face_folder = FACES_DIR / name
        file_deleted = False
        if face_folder.exists() and face_folder.is_dir():
            try:
                shutil.rmtree(face_folder)
                file_deleted = True
            except Exception as e:
                print(f"❌ Gagal menghapus folder file wajah {name}: {e}")

        print(f"✅ Hapus Wajah Berhasil: {name}. Vektor dihapus: {deleted_vectors}. File dihapus: {file_deleted}")
        return {"status": "success", "message": f"Data wajah '{name}' berhasil dihapus."}

    except HTTPException as http_exc:
        raise http_exc # Re-raise HTTPException
    except Exception as e:
        print(f"❌ Error menghapus data wajah {name}: {e}")
        if conn: conn.rollback()
        raise HTTPException(status_code=500, detail=f"Gagal menghapus data wajah: {e}")
    finally:
        if conn: conn.close()

# --- ENDPOINTS LAINNYA ---
@app.post("/run_indexing")
async def run_indexing_endpoint(background_tasks: BackgroundTasks):
    """Memicu proses indexing di background."""
    try:
        background_tasks.add_task(run_indexing_subprocess)
        print("✅ [API] Proses indexing telah di-antrekan (queued)...")
        return {"status": "queued", "message": "Proses indexing telah dimulai di background."}
    except Exception as e:
        print(f"❌ [API] Gagal memulai background task: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal memulai indexing task: {e}")

@app.post("/reload_db")
async def reload_db():
    """Simulasi muat ulang/sinkronisasi DB."""
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT name) FROM intern_centroids")
        total_unique_faces = cursor.fetchone()[0]
        print(f"✅ RELOAD SIMULASI BERHASIL. Total {total_unique_faces} wajah unik terindeks.")
        return {"status": "success", "message": "Sinkronisasi berhasil (Simulasi)", "total_faces": total_unique_faces}
    except Exception as e:
        print(f"❌ Error saat simulasi reload database: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal reload database: {e}")
    finally:
        if conn: conn.close()

@app.get("/list_faces")
async def list_registered_faces():
    """Mengambil daftar nama dan jumlah gambar."""
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, COUNT(*)
            FROM intern_embeddings
            GROUP BY name
            ORDER BY name ASC
        """)
        results = cursor.fetchall()
        faces_list = [{"name": name, "count": count} for name, count in results]
        return {"status": "success", "faces": faces_list}
    except Exception as e:
        print(f"❌ Error mengambil daftar wajah terdaftar: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal mengambil daftar wajah: {e}")
    finally:
        if conn: conn.close()

# --- APP.MOUNT INI HARUS DI POSISI TERAKHIR (FALLBACK) ---
app.mount("/", StaticFiles(directory=str(FRONTEND_STATIC_DIR), html=True), name="frontend") # Tambahkan html=True