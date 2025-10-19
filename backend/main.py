import time
import sys
import os
import psycopg2
import psycopg2.extensions 
import numpy as np
import shutil 
import uuid 
from pathlib import Path
from datetime import date, timedelta, datetime
import io
import webbrowser 
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
    from utils import extract_face_features, DISTANCE_THRESHOLD 
except ImportError:
    try:
        from .utils import extract_face_features, DISTANCE_THRESHOLD
    except ImportError:
        print("⚠️ Peringatan: Gagal mengimpor utilitas (utils.py). Pastikan file ini ada.")
        def extract_face_features(image_bytes): return []
        DISTANCE_THRESHOLD = 0.5

# Konfigurasi DB PostgreSQL
# KRITIS: Ubah "localhost" menjadi nama service DB (misalnya, "db") jika di Docker Compose
DB_HOST = os.getenv("DB_HOST", "localhost") 
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
DAILY_RESET_HOUR = 00 # Pukul 18 (6 sore) - Waktu custom untuk reset harian
DAILY_RESET_MINUTE = 00 
# ---

# --- INISIALISASI APLIKASI ---
app = FastAPI(title="DeepFace Absensi API")

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

# Definisikan Aturan Jam Kerja dari GM IT
JADWAL_KERJA = {
    # Menggunakan "Mahasiswa Internship" untuk kategori PKL/Program
    "Mahasiswa Internship": { 
        "MASUK_PALING_LAMBAT": "09:00:00", # Pkl dr jam 9
        "PULANG_PALING_CEPAT": "15:00:00"  # sd 15.00
    },
    # Kategori Staff (Pak Nugroho) atau Karyawan
    "Staff": { 
        "MASUK_PALING_LAMBAT": "08:30:00", # 8.30 sd 17.30 (mengambil yang paling ketat)
        "PULANG_PALING_CEPAT": "17:30:00"
    },
    "General Manager": { # Jika ada kategori GM (seperti Pak Nugroho)
        "MASUK_PALING_LAMBAT": "08:30:00",
        "PULANG_PALING_CEPAT": "17:30:00"
    },
    # Default untuk kategori lain yang tidak terdefinisi
    "DEFAULT": {
        "MASUK_PALING_LAMBAT": "09:00:00",
        "PULANG_PALING_CEPAT": "15:00:00"
    }
}

def check_attendance_status(kategori: str, type_absensi: str, log_time: datetime) -> str:
    """Menentukan status absensi (Tepat Waktu/Terlambat/Pulang Cepat) berdasarkan kategori dan waktu log."""
    
    # Ambil aturan berdasarkan kategori, fallback ke DEFAULT
    aturan = JADWAL_KERJA.get(kategori, JADWAL_KERJA.get(kategori.replace(' ', '_'), JADWAL_KERJA["DEFAULT"]))
    
    # Ambil waktu jam-menit-detik saat ini dalam format string HH:MM:SS
    # Karena log_time adalah objek datetime yang sadar WIB, ini aman
    current_time_str = log_time.strftime("%H:%M:%S")

    if type_absensi == 'IN':
        target_time = aturan["MASUK_PALING_LAMBAT"]
        
        # Jika waktu saat ini SAMA DENGAN atau LEBIH AWAL dari batas
        if current_time_str <= target_time:
            return "Tepat Waktu"
        else:
            return "Terlambat" # Diatas Jam pulang tsb kategori terlambat
            
    elif type_absensi == 'OUT':
        target_time = aturan["PULANG_PALING_CEPAT"]
        
        # Jika waktu saat ini SAMA DENGAN atau LEBIH AKHIR dari batas
        if current_time_str >= target_time:
            return "Tepat Waktu"
        else:
            return "Pulang Cepat"
            
    return "N/A"
        
# --- FUNGSI DATABASE HELPERS (POSTGRESQL) ---

def connect_db():
    """Membuat koneksi ke Database Vektor/Log (PostgreSQL) dan mendaftarkan tipe vector."""
    conn = None
    try:
        # Menghubungkan ke PostgreSQL
        conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASSWORD)
        
        # 1. Cari OID tipe 'vector'
        with conn.cursor() as cur:
            cur.execute("SELECT oid FROM pg_type WHERE typname = 'vector'")
            vector_oid = cur.fetchone()[0]
        
        # 2. Buat fungsi konversi (membersihkan kurung siku atau kurung kurawal)
        def cast_vector(data, cur):
            if data is None:
                return None
            # Membersihkan kurung kurawal {} atau kurung siku []
            cleaned_data = data.strip('{}[]')
            return np.array([float(x.strip()) for x in cleaned_data.split(',')])
        
        # 3. Daftarkan tipe data vector ke koneksi ini
        psycopg2.extensions.register_type(
            psycopg2.extensions.new_type((vector_oid,), 'vector', cast_vector), 
            conn
        )
        # --- END REGISTRASI KRITIS ---
        
        return conn
    except psycopg2.Error as e:
        print(f"❌ Gagal koneksi ke Database PostgreSQL: {e}")
        if conn:
            conn.close()
        # Mengubah Exception untuk penanganan startup
        raise Exception("Database PostgreSQL tidak terhubung/konfigurasi salah.")

def initialize_db():
    """Memastikan tabel interns, attendance_logs, intern_embeddings, dan intern_centroids ada."""
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        
        # Pastikan ekstensi vector ada
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;") 
        
        # 1. Buat Tabel interns
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS interns (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                instansi TEXT,
                kategori TEXT
            );
        """)
        
        # 2. Buat Tabel attendance_logs
        # KRITIS: absent_at sekarang diisi eksplisit dengan waktu WIB dari Python
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance_logs (
                log_id SERIAL PRIMARY KEY,
                intern_id INTEGER REFERENCES interns(id),
                intern_name TEXT NOT NULL,
                instansi TEXT,
                kategori TEXT,  
                image_url TEXT, 
                absent_at TIMESTAMP WITHOUT TIME ZONE,
                type TEXT NOT NULL DEFAULT 'IN' -- Kolom Baru untuk IN/OUT
            );
        """)
        
        # 3. Buat Tabel intern_embeddings (Data Vektor Mentah)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS intern_embeddings (
                id SERIAL PRIMARY KEY,
                intern_id INTEGER REFERENCES interns(id),
                name TEXT NOT NULL,
                instansi TEXT,
                kategori TEXT,
                embedding VECTOR(512) NOT NULL,
                file_path TEXT
            );
        """)
        
        # 4. Buat Tabel intern_centroids (Data Vektor Rata-Rata)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS intern_centroids (
                id SERIAL PRIMARY KEY,
                intern_id INTEGER UNIQUE REFERENCES interns(id),
                name TEXT NOT NULL UNIQUE,
                instansi TEXT,
                kategori TEXT,
                embedding VECTOR(512) NOT NULL 
            );
        """)
        
        # 5. DATA MASSAL 31 INTERNS (Hanya memastikan nama interns sudah ada)
        all_interns_data = [
            (1, 'Said', 'Universitas Muhammadiyah Surabaya', 'Mahasiswa Internship'),
            (2, 'Muarif', 'Universitas Muhammadiyah Surabaya', 'Mahasiswa Internship'),
            (3, 'Nani', 'Universitas Muhammadiyah Surabaya', 'Mahasiswa Internship'),
            (4, 'Vinda', 'Universitas Muhammadiyah Surabaya', 'Mahasiswa Internship'),
            (5, 'Harun', 'Universitas Pakuan Bogor', 'Mahasiswa Internship'),
            (31, 'Pak Nugroho', 'General Manager', 'Staff'), # Kategori 'General Manager'
        ]
        
        data_to_insert = [(item[1], item[2], item[3]) for item in all_interns_data]
        
        # Gunakan ON CONFLICT DO NOTHING 
        cursor.executemany("""
            INSERT INTO interns (name, instansi, kategori) 
            VALUES (%s, %s, %s)
            ON CONFLICT (name) DO NOTHING;
        """, data_to_insert)

        conn.commit()
        print(f"✅ PostgreSQL Database berhasil diinisialisasi. {len(all_interns_data)} entri interns dicek/ditambahkan.")
        
        os.makedirs(CAPTURED_IMAGES_DIR, exist_ok=True)
        os.makedirs(FACES_DIR, exist_ok=True) 
        os.makedirs(AUDIO_FILES_DIR, exist_ok=True)
        print(f"✅ Folder gambar absensi ({CAPTURED_IMAGES_DIR}) dan wajah ({FACES_DIR}) siap.")
        
    except psycopg2.Error as e:
        print(f"❌ KRITIS: Gagal menginisialisasi tabel PostgreSQL: {e}")
        if conn:
            conn.rollback()
        raise Exception(f"Gagal inisialisasi database PostgreSQL: {e}")
    finally:
        if conn:
            conn.close()

def get_or_create_intern(name: str, instansi: str = "Intern", kategori: str = "Unknown"):
    """Mendapatkan ID intern yang sudah ada atau membuat entri baru di PostgreSQL."""
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, instansi, kategori FROM interns WHERE name = %s", (name,))
        result = cursor.fetchone()
        
        if result:
            intern_id = result[0]
            instansi_registered = result[1]
            kategori_registered = result[2]
            return intern_id, instansi_registered, kategori_registered 
        else:
            # Jika nama baru, instansi dan kategori diisi dengan default "Intern"/"Unknown"
            cursor.execute(
                "INSERT INTO interns (name, instansi, kategori) VALUES (%s, %s, %s) RETURNING id",
                (name, instansi, kategori)
            )
            intern_id = cursor.fetchone()[0]
            conn.commit()
            return intern_id, instansi, kategori
            
    except Exception as e:
        print(f"❌ Gagal mendapatkan/membuat entri intern di PostgreSQL: {e}")
        if conn:
            conn.rollback()
        raise Exception(f"Gagal mengelola data intern: {e}")
    finally:
        if conn:
            conn.close()

def get_latest_attendance(intern_name: str) -> Optional[Dict[str, str]]:
    """Mendapatkan log absensi terakhir untuk intern hari ini (IN/OUT)."""
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        # Query untuk mendapatkan log absensi terakhir hari ini
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
            # Mengembalikan absent_at sebagai ISO format string (biar bisa di-parse di format_time_to_hms)
            return {"name": result[0], "type": result[1], "absent_at": result[2].isoformat()}
        return None
    except Exception as e:
        print(f"❌ Gagal memeriksa log absensi terakhir: {e}")
        return None
    finally:
        if conn:
            conn.close()


def log_attendance(intern_name: str, instansi: str, kategori: str, image_url: str, type_absensi: str):
    """Mencatat log absensi ke database PostgreSQL (dengan jenis 'IN' atau 'OUT')."""
    conn = None
    try:
        intern_id, _, _ = get_or_create_intern(intern_name, instansi, kategori)
        
        conn = connect_db()
        cursor = conn.cursor()
        
        # <<< PERUBAHAN KRITIS: Menggunakan waktu WIB eksplisit dari Python >>>
        # Kita menggunakan replace(tzinfo=None) agar sesuai dengan kolom TIMESTAMP WITHOUT TIME ZONE
        wib_time = get_current_wib_datetime().replace(tzinfo=None) 
        
        # Mencatat log dengan kolom type
        cursor.execute(
            "INSERT INTO attendance_logs (intern_id, intern_name, instansi, kategori, image_url, absent_at, type) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (intern_id, intern_name, instansi, kategori, image_url, wib_time, type_absensi) # Mengganti LOCALTIMESTAMP dengan wib_time
        )
        conn.commit()
        return intern_id
            
    except Exception as e:
        print(f"❌ Gagal mencatat log absensi: {e}")
        if conn:
            conn.rollback()
        return None
    finally:
        if conn:
            conn.close()

def reset_attendance_logs():
    """Menghapus SEMUA log absensi HARI INI dari tabel attendance_logs di PostgreSQL."""
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        
        # Menghapus semua baris dari tabel attendance_logs HARI INI (PostgreSQL)
        cursor.execute("DELETE FROM attendance_logs WHERE absent_at::date = CURRENT_DATE")

        deleted_count = cursor.rowcount
        conn.commit()
        
        print(f"✅ [SCHEDULER] RESET ABSENSI BERHASIL: {deleted_count} log absensi hari ini dihapus dari PostgreSQL.")
        
        return deleted_count
        
    except Exception as e:
        print(f"❌ Gagal mereset log absensi PostgreSQL: {e}")
    finally:
        if conn:
            conn.close()


# --- HOOK UNTUK MEMBUKA BROWSER OTOMATIS & SCHEDULING (PERMINTAAN USER) ---

@app.on_event("startup") 
async def startup_event():
    """Melakukan inisialisasi DB, menjadwalkan reset, dan membuka browser saat startup."""
    try:
        initialize_db() 
    except Exception as e:
        print(f"❌ Gagal menjalankan aplikasi karena inisialisasi DB gagal: {e}")
        sys.exit(1)

    # --- LOGIKA PENJADWALAN ---
    global scheduler
    scheduler = AsyncIOScheduler()
    
    # Tambahkan tugas reset harian pada jam 17:00 (Sesuai permintaan user)
    scheduler.add_job(
        reset_attendance_logs, 
        CronTrigger(hour=DAILY_RESET_HOUR, minute=DAILY_RESET_MINUTE),
        id='daily_attendance_reset',
        name='Daily Absensi Log Reset'
    )
    
    # Mulai Scheduler
    scheduler.start()
    print(f"✅ Penjadwalan reset absensi harian ({DAILY_RESET_HOUR}:{DAILY_RESET_MINUTE}) berhasil diaktifkan.")
    
    # --- LOGIKA BUKA BROWSER OTOMATIS ---
    try:
        time.sleep(1) 
        webbrowser.open_new_tab('http://127.0.0.1:8000/main.html') 
        print("✅ Browser berhasil dibuka secara otomatis.")
    except Exception as e:
        print(f"⚠️ Peringatan: Gagal membuka browser otomatis: {e}")


# --- ENDPOINTS DATA COLLECTOR ---

@app.post("/upload_dataset")
async def upload_dataset(name: str = Form(...), instansi: str = Form("Intern"), kategori: str = Form("Unknown"), file: UploadFile = File(...)):
    """Menerima file gambar, menyimpan di folder dataset, dan mendaftarkan intern jika belum ada."""
    
    # 1. Validasi Input dan Pembersihan Nama
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Nama tidak boleh kosong.")
    
    # 2. Dapatkan atau Buat Intern ID
    try:
        intern_id, instansi_reg, kategori_reg = get_or_create_intern(clean_name, instansi, kategori)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal memproses intern ID: {e}")

    # 3. Simpan File Gambar ke Folder Dataset (FACES_DIR / NAMA INTERN)
    face_folder = FACES_DIR / clean_name
    os.makedirs(face_folder, exist_ok=True)
    
    # Gunakan nama file yang dikirim dari frontend (misal: 1.jpg)
    file_path = face_folder / file.filename 
    
    try:
        image_bytes = await file.read()
        with open(file_path, "wb") as f:
            f.write(image_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal menyimpan file gambar: {e}")

    print(f"✅ FILE DATASET TERSIMPAN: {clean_name} - {file.filename} di {file_path}")
    
    return {"status": "success", "message": f"Gambar tersimpan di folder {clean_name}."}


# --- ENDPOINTS ABSENSI ---

@app.post("/recognize")
async def recognize_face(file: UploadFile = File(...), type_absensi: str = Form(...)): 
    """Endpoint utama untuk deteksi wajah dan pencocokan cepat, menerima jenis absensi eksplisit."""
    start_time = time.time()
    image_bytes = await file.read() 
    
    type_absensi = type_absensi.upper()
    image_url_for_db = ""
    
    # Validasi Tipe Absensi yang diterima 
    if type_absensi not in ['IN', 'OUT']:
        generate_audio_file("S005.mp3", "Kesalahan tipe absensi. Mohon hubungi admin.")
        raise HTTPException(status_code=400, detail="Invalid type_absensi. Must be 'IN' or 'OUT'.")

    # 1. EKSTRAKSI VEKTOR WAJAH BARU
    emb_list = extract_face_features(image_bytes) 
    
    if not emb_list:
        generate_audio_file("S002.mp3", "Wajah tidak terdeteksi. Silakan coba lagi.")
        return {"status": "error", "message": "Wajah tidak terdeteksi.", "track_id": "S002.mp3", "image_url": image_url_for_db}
    
    new_embedding = emb_list[0] 

    # 2. PENCARIAN VEKTOR DI DATABASE CENTROID (POSTGRESQL)
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        
        # Pastikan format vektor menggunakan kurung siku []
        vector_string = "[" + ",".join(map(str, new_embedding)) + "]"

        # KRITIS: Menggunakan intern_centroids
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
            
            # 3. VERIFIKASI AMBANG BATAS AKURASI
            if distance <= DISTANCE_THRESHOLD:
                
                # --- LOGIKA PENGECEKAN DUPLIKAT KHUSUS ---
                latest_log = get_latest_attendance(name) # Mengembalikan 'absent_at' sebagai ISO string
                
                if latest_log and latest_log['type'] == type_absensi:
                    # Absensi Duplikat
                    print(f"✅ DUPLIKAT ABSENSI: {name} | Sudah Absen {type_absensi} Hari Ini.")
                    
                    audio_filename = f"duplicate_{type_absensi.lower()}_{name.replace(' ', '_')}.mp3"
                    
                    if type_absensi == 'IN':
                        message_text = f"{name}, Anda sudah Absen Masuk hari ini."
                    else: 
                        message_text = f"Absensi Pulang Anda sudah dicatat hari ini. Sampai jumpa besok."
                        
                    generate_audio_file(audio_filename, message_text)
                    
                    # Mengambil waktu log terakhir
                    log_time_display = format_time_to_hms(latest_log['absent_at']) 
                    
                    # Logika Duplikat TIDAK perlu status absensi, karena hanya mengulang info sebelumnya
                    return {"status": "duplicate", "name": name, "instansi": instansi, "kategori": kategori, "distance": f"{distance:.4f}", "latency": f"{elapsed_time:.2f}s", "track_id": audio_filename, "type": type_absensi, "log_time": log_time_display} 
                
                # --- LOGIKA PENYIMPANAN GAMBAR ABSENSI ---
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                clean_name = name.strip().replace(' ', '_').replace('.', '').replace('/', '_').replace('\\', '_').lower()
                image_filename = f"{timestamp}_{clean_name}_{type_absensi}.jpg"
                image_path = CAPTURED_IMAGES_DIR / image_filename
                
                temp_image_url = ""
                try:
                    with open(image_path, "wb") as f:
                        f.write(image_bytes)
                    temp_image_url = f"/images/{image_filename}"
                except Exception as file_error:
                    print(f"   ❌ KRITIS: Gagal menyimpan gambar absensi untuk {name}. Error: {file_error}")
                    
                image_url_for_db = temp_image_url
                # --- END LOGIKA PENYIMPANAN GAMBAR ABSENSI ---
                
                # Absensi Berhasil: Catat ke DB
                log_attendance(name, instansi, kategori, image_url_for_db, type_absensi) 
                
                # Waktu Absensi saat ini untuk respons (WIB)
                current_log_time = get_current_wib_datetime() 
                log_time_display = format_time_to_hms(current_log_time) 
                
                # <<< TAMBAH: Menentukan Status Absensi >>>
                attendance_status_result = check_attendance_status(kategori, type_absensi, current_log_time) 
                # ----------------------------------------
                
                if type_absensi == 'IN':
                    if attendance_status_result == "Terlambat":
                        message_text = f"Maaf, {name}. Absensi masuk Anda dicatat sebagai Terlambat."
                    else:
                        message_text = f"Selamat datang, {name}. Absensi masuk berhasil dicatat."
                else: 
                    if attendance_status_result == "Pulang Cepat":
                        message_text = f"Peringatan, {name}. Absensi keluar Anda dicatat sebagai Pulang Cepat."
                    else:
                        message_text = f"Terima kasih, {name}. Absensi keluar berhasil dicatat. Sampai jumpa besok."
                    
                print(f"✅ DETEKSI BERHASIL: {name} ({type_absensi}) | Status: {attendance_status_result} | Jarak: {distance:.4f} | Latensi: {elapsed_time:.2f}s")
                
                audio_filename = f"log_{clean_name}_{type_absensi.lower()}.mp3"
                generate_audio_file(audio_filename, message_text)
                
                return {"status": "success", "name": name, "instansi": instansi, "kategori": kategori, "distance": f"{distance:.4f}", "latency": f"{elapsed_time:.2f}s", "track_id": audio_filename, "type": type_absensi, "image_url": image_url_for_db, "log_time": log_time_display, "attendance_status": attendance_status_result} # <<< BARU: attendance_status
            else:
                # ⚠️ Tidak Dikenali (Jarak Terlalu Jauh)
                print(f"❌ DETEKSI GAGAL: Jarak Terlalu Jauh ({distance:.4f}) | Latensi: {elapsed_time:.2f}s")
                generate_audio_file("S003.mp3", "Data wajah Anda belum terdaftar di sistem. Mohon hubungi admin.")
                return {"status": "unrecognized", "message": "Data Wajah Anda Belum Terdaftar Di Sistem", "track_id": "S003.mp3", "image_url": image_url_for_db}

        else:
            # Database Vektor kosong (intern_centroids)
            generate_audio_file("S003.mp3", "Data wajah Anda belum terdaftar di sistem. Mohon hubungi admin.")
            return {"status": "error", "message": "Sistem kosong, lakukan indexing.", "track_id": "S003.mp3", "image_url": image_url_for_db}

    except Exception as e:
        print(f"❌ ERROR PENCARIAN/ABSENSI: {e}")
        generate_audio_file("S004.mp3", "Kesalahan server terjadi. Mohon hubungi admin.")
        return {"status": "error", "message": f"Kesalahan server: {str(e)}", "track_id": "S004.mp3", "image_url": image_url_for_db}
    finally:
        if conn:
            conn.close()

# --- ENDPOINTS DATA (data.html) ---

@app.get("/attendance/today") 
async def get_today_attendance():
    """Mendapatkan daftar log absensi unik terakhir hari ini (untuk data.html) dari PostgreSQL."""
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        
        # Query PostgreSQL untuk mendapatkan log absensi TERAKHIR setiap intern hari ini
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
            
            # Mengambil waktu objek asli (yang sudah dalam WIB)
            log_datetime_wib = time_obj 
            
            # Tentukan status Kepatuhan Waktu
            status_kepatuhan = check_attendance_status(kategori, log_type, log_datetime_wib) 
            
            # Tentukan status display di tabel
            if log_type == 'IN':
                status_display = f"MASUK ({status_kepatuhan})"
            elif log_type == 'OUT':
                status_display = f"PULANG ({status_kepatuhan})"
            else:
                status_display = "N/A" 

            attendance_list.append({
                "name": name,
                "instansi": instansi,
                "kategori": kategori,
                "status": status_display, # <<< PERUBAHAN: Status sekarang berisi kepatuhan waktu
                "timestamp": format_time_to_hms(time_obj), 
                "distance": 0.0000, 
                "image_path": image_url 
            })
            
        return attendance_list 

    except Exception as e:
        print(f"❌ Error mengambil daftar absensi hari ini dari PostgreSQL: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()

# --- ENDPOINTS PENGATURAN (settings.html) ---

@app.post("/reset_absensi") 
async def reset_daily_attendance():
    """Menghapus semua log absensi yang tercatat untuk hari ini (Manual Trigger)."""
    try:
        deleted_count = reset_attendance_logs()
        
        print(f"✅ RESET ABSENSI MANUAL BERHASIL: {deleted_count} log absensi hari ini dihapus dari PostgreSQL.")
        
        return JSONResponse(content={
            "status": "success", 
            "message": f"Berhasil mereset log absensi hari ini. Total {deleted_count} log dihapus.",
            "deleted_count": deleted_count
        })

    except Exception as e:
        print(f"❌ Error saat mereset absensi PostgreSQL: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/delete_face/{name}") 
async def delete_face(name: str):
    """Menghapus data wajah dari database vektor dan file dari disk."""
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        
        # 1. Hapus dari Centroid
        cursor.execute("DELETE FROM intern_centroids WHERE name = %s", (name,))
        
        # 2. Hapus dari Database Vektor Mentah
        cursor.execute("DELETE FROM intern_embeddings WHERE name = %s", (name,))
        deleted_count = cursor.rowcount
        conn.commit()

        # 3. Hapus file gambar dari folder FACES_DIR
        face_folder = FACES_DIR / name
        file_deleted = False
        if face_folder.exists() and face_folder.is_dir():
            try:
                shutil.rmtree(face_folder) 
                file_deleted = True
            except Exception as e:
                print(f"❌ Gagal menghapus folder file wajah: {e}")
        
        if deleted_count > 0 or file_deleted:
            print(f"✅ Hapus Wajah Berhasil: {name}. Vektor dihapus: {deleted_count}. File dihapus: {file_deleted}")
            
            return {"status": "success", "message": f"Data wajah '{name}' berhasil dihapus. Vektor: {deleted_count} dihapus."}
        else:
            return {"status": "error", "message": f"Data wajah '{name}' tidak ditemukan di database atau folder file."}

    except Exception as e:
        print(f"❌ Error menghapus data wajah: {e}")
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Gagal menghapus data wajah: {e}")
    finally:
        if conn:
            conn.close()

# --- ENDPOINTS LAINNYA ---
@app.post("/reload_db") 
async def reload_db():
    """Simulasi muat ulang/sinkronisasi DB (Asumsi bahwa proses indexing dilakukan di script terpisah)."""
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        # Menggunakan intern_centroids untuk hitungan karena ini yang digunakan untuk pencarian
        cursor.execute("SELECT COUNT(DISTINCT name) FROM intern_centroids")
        total_unique_faces = cursor.fetchone()[0]
        
        print(f"✅ RELOAD SIMULASI BERHASIL. Total {total_unique_faces} wajah unik terindeks.")

        return {"status": "success", "message": "Database wajah berhasil dimuat ulang/disinkronisasi (Simulasi)", "total_faces": total_unique_faces}

    except Exception as e:
        print(f"❌ Error saat simulasi reload database: {e}")
        raise HTTPException(status_code=500, detail=f"Gagal reload database: {e}")
    finally:
        if conn:
            conn.close()

@app.get("/list_faces") 
async def list_registered_faces():
    """Mengambil daftar nama dan jumlah gambar yang sudah terdaftar."""
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        
        # Menggunakan intern_embeddings untuk menghitung total gambar per wajah
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
        if conn:
            conn.close()
            
# --- APP.MOUNT INI HARUS DI POSISI TERAKHIR (FALLBACK) ---
app.mount("/", StaticFiles(directory=str(FRONTEND_STATIC_DIR)), name="frontend")