import time
import sys
import os
import psycopg2
import shutil 
import uuid 
from pathlib import Path
from datetime import date, timedelta 
import io
import webbrowser 
from typing import List, Optional, Dict 

# --- IMPORTS SCHEDULER ---
from apscheduler.schedulers.asyncio import AsyncIOScheduler 
from apscheduler.triggers.cron import CronTrigger
# ---

# Import gTTS library for automatic Text-to-Speech generation
from gtts import gTTS 
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
PROJECT_ROOT = Path(__file__).resolve().parent.parent 
sys.path.insert(0, str(PROJECT_ROOT))

# Impor fungsi dan konfigurasi dari file lain
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
DB_HOST = "localhost" 
DB_NAME = "vector_db"
DB_USER = "macbookpro" 
DB_PASSWORD = "deepfacepass" 

# FOLDER UNTUK GAMBAR
CAPTURED_IMAGES_DIR = PROJECT_ROOT / "backend" / "captured_images" 
FACES_DIR = PROJECT_ROOT / "data" / "dataset" 
FRONTEND_STATIC_DIR = PROJECT_ROOT / "frontend" 
AUDIO_FILES_DIR = PROJECT_ROOT / "backend" / "generated_audio"

# --- KONFIGURASI SCHEDULER ---
scheduler = None 
DAILY_RESET_HOUR = 17 # Pukul 17 (5 sore) - Waktu custom untuk reset harian
DAILY_RESET_MINUTE = 0 
# ---

# --- INISIALISASI APLIKASI ---
app = FastAPI(title="DeepFace Absensi API")

# Mount folder audio, images, dan faces
app.mount("/audio", StaticFiles(directory=str(AUDIO_FILES_DIR), check_dir=True), name="generated_audio")
app.mount("/images", StaticFiles(directory=str(CAPTURED_IMAGES_DIR), check_dir=True), name="captured_images")
app.mount("/faces", StaticFiles(directory=str(FACES_DIR), check_dir=True), name="faces")


# --- FUNGSI AUDIO GENERATION ---

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
        
# --- FUNGSI DATABASE HELPERS (POSTGRESQL) ---

def connect_db():
    """Membuat koneksi ke Database Vektor/Log (PostgreSQL)."""
    try:
        # Menghubungkan ke PostgreSQL
        return psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASSWORD)
    except psycopg2.Error as e:
        print(f"❌ Gagal koneksi ke Database PostgreSQL: {e}")
        # Mengubah Exception untuk penanganan startup
        raise Exception("Database PostgreSQL tidak terhubung/konfigurasi salah.")

def initialize_db():
    """Memastikan tabel interns, attendance_logs, dan intern_embeddings ada di PostgreSQL."""
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        
        # 1. Buat Tabel interns
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS interns (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                instansi TEXT,
                kategori TEXT
            );
        """)
        
        # 2. Buat Tabel attendance_logs (PERUBAHAN SKEMA: Tambah kolom TYPE)
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;") 
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance_logs (
                log_id SERIAL PRIMARY KEY,
                intern_id INTEGER REFERENCES interns(id),
                intern_name TEXT NOT NULL,
                instansi TEXT,
                kategori TEXT,  
                image_url TEXT, 
                absent_at TIMESTAMP WITHOUT TIME ZONE DEFAULT LOCALTIMESTAMP,
                type TEXT NOT NULL DEFAULT 'IN' -- Kolom Baru untuk IN/OUT
            );
        """)
        
        # 3. Buat Tabel intern_embeddings
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
        
        # 4. DATA MASSAL 31 INTERNS (Sama seperti sebelumnya)
        all_interns_data = [
            (1, 'Said', 'Universitas Muhammadiyah Surabaya', 'Mahasiswa Internship'),
            (2, 'Muarif', 'Universitas Muhammadiyah Surabaya', 'Mahasiswa Internship'),
            (3, 'Nani', 'Universitas Muhammadiyah Surabaya', 'Mahasiswa Internship'),
            (4, 'Vinda', 'Universitas Muhammadiyah Surabaya', 'Mahasiswa Internship'),
            (5, 'Harun', 'Universitas Pakuan Bogor', 'Mahasiswa Internship'),
            (6, 'Isra', 'Universitas Pakuan Bogor', 'Mahasiswa Internship'),
            (7, 'Ikhsan', 'Universitas Pakuan Bogor', 'Mahasiswa Internship'),
            (8, 'Nabila', 'Politeknik Negeri Malang', 'Mahasiswa Internship'),
            (9, 'Shandy', 'Politeknik Negeri Malang', 'Mahasiswa Internship'),
            (10, 'Athallah', 'Politeknik Negeri Malang', 'Mahasiswa Internship'),
            (11, 'Lilla', 'Politeknik Negeri Malang', 'Mahasiswa Internship'),
            (12, 'Raffy Jo', 'Politeknik Negeri Malang', 'Mahasiswa Internship'),
            (13, 'Tia', 'Politeknik Negeri Malang', 'Mahasiswa Internship'),
            (14, 'Ferin', 'Politeknik Negeri Malang', 'Mahasiswa Internship'),
            (15, 'Akmal', 'Politeknik Negeri Jakarta', 'Mahasiswa Internship'),
            (16, 'Iwan', 'Politeknik Negeri Jakarta', 'Mahasiswa Internship'),
            (17, 'Aditya', 'Politeknik Negeri Jakarta', 'Mahasiswa Internship'),
            (18, 'Nayla', 'Politeknik Negeri Jakarta', 'Mahasiswa Internship'),
            (19, 'Rafa', 'Politeknik Negeri Jakarta', 'Mahasiswa Internship'),
            (20, 'Rahma', 'Politeknik Negeri Jakarta', 'Mahasiswa Internship'),
            (21, 'Thalia', 'Politeknik Negeri Jakarta', 'Mahasiswa Internship'),
            (22, 'Aufar', 'Institut Pertanian Bogor', 'Mahasiswa Internship'),
            (23, 'Adan', 'Institut Pertanian Bogor', 'Mahasiswa Internship'),
            (24, 'Abdul', 'Institut Pertanian Bogor', 'Mahasiswa Internship'),
            (25, 'Oktori', 'Institut Pertanian Bogor', 'Mahasiswa Internship'),
            (26, 'Sandi', 'Institut Pertanian Bogor', 'Mahasiswa Internship'),
            (27, 'Marsya', 'Institut Pertanian Bogor', 'Mahasiswa Internship'),
            (28, 'Capriandika', 'Institut Pertanian Bogor', 'Mahasiswa Internship'),
            (29, 'Radit', 'SMK INFOKOM', 'Siswa Magang'),
            (30, 'Ryu', 'SMK INFOKOM', 'Siswa Magang'),
            (31, 'Pak Nugroho', 'General Manager', 'Staff'),
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
            # Mengembalikan absent_at sebagai ISO format string
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
        
        # Mencatat log dengan kolom type
        cursor.execute(
            "INSERT INTO attendance_logs (intern_id, intern_name, instansi, kategori, image_url, absent_at, type) VALUES (%s, %s, %s, %s, %s, LOCALTIMESTAMP, %s)",
            (intern_id, intern_name, instansi, kategori, image_url, type_absensi)
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


# --- HOOK UNTUK MEMBUKA BROWSER OTOMATIS & SCHEDULING ---

@app.on_event("startup")
async def startup_event():
    """Melakukan inisialisasi DB, menjadwalkan reset, dan membuka browser saat startup."""
    try:
        initialize_db() # Inisialisasi DB PostgreSQL
    except Exception as e:
        print(f"❌ Gagal menjalankan aplikasi karena inisialisasi DB gagal: {e}")
        sys.exit(1)

    # --- LOGIKA PENJADWALAN ---
    global scheduler
    scheduler = AsyncIOScheduler()
    
    # Tambahkan tugas reset harian pada jam 17:00
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


# --- ENDPOINTS ABSENSI ---

@app.post("/recognize")
# KRITIS: Sekarang menerima parameter type_absensi dari Form ('IN' atau 'OUT')
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

    # 2. PENCARIAN VEKTOR DI DATABASE VEKTOR (POSTGRESQL)
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        
        vector_string = "[" + ",".join(map(str, new_embedding)) + "]"

        cursor.execute(f"""
            SELECT name, instansi, kategori, embedding <=> '{vector_string}'::vector AS distance
            FROM intern_embeddings
            ORDER BY distance ASC
            LIMIT 1
        """)
        
        result = cursor.fetchone()

        if result:
            name, instansi, kategori, distance = result
            elapsed_time = time.time() - start_time
            
            # 3. VERIFIKASI AMBANG BATAS AKURASI
            if distance <= DISTANCE_THRESHOLD:
                
                # --- LOGIKA PENGECEKAN DUPLIKAT KHUSUS (Berdasarkan Tipe yang Dikirim) ---
                latest_log = get_latest_attendance(name)
                
                if latest_log and latest_log['type'] == type_absensi:
                    # Jika log terakhir (apapun jamnya) sama dengan type absensi yang dikirim (misal: IN vs IN)
                    print(f"✅ DUPLIKAT ABSENSI: {name} | Sudah Absen {type_absensi} Hari Ini.")
                    
                    audio_filename = f"duplicate_{type_absensi.lower()}_{name.replace(' ', '_')}.mp3"
                    
                    if type_absensi == 'IN':
                        message_text = f"{name}, Anda sudah Absen Masuk hari ini."
                    else: # 'OUT'
                        message_text = f"{name}, Anda sudah Absen Pulang hari ini. Sampai jumpa besok."
                        
                    generate_audio_file(audio_filename, message_text)
                    
                    # Mengambil waktu log terakhir
                    log_time_display = latest_log['absent_at'].split('T')[-1].split('+')[0]
                    
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
                
                # Absensi Berhasil: Catat ke DB (menggunakan type_absensi yang diterima dari frontend)
                log_attendance(name, instansi, kategori, image_url_for_db, type_absensi) 
                
                if type_absensi == 'IN':
                    message_text = f"Selamat datang, {name}. Absensi masuk berhasil dicatat."
                else: # 'OUT'
                    message_text = f"Terima kasih, {name}. Absensi keluar berhasil dicatat. Sampai jumpa besok."
                    
                print(f"✅ DETEKSI BERHASIL: {name} ({type_absensi}) | Jarak: {distance:.4f} | Latensi: {elapsed_time:.2f}s")
                
                audio_filename = f"log_{clean_name}_{type_absensi.lower()}.mp3"
                generate_audio_file(audio_filename, message_text)
                
                return {"status": "success", "name": name, "instansi": instansi, "kategori": kategori, "distance": f"{distance:.4f}", "latency": f"{elapsed_time:.2f}s", "track_id": audio_filename, "type": type_absensi, "image_url": image_url_for_db}
            else:
                # ⚠️ Tidak Dikenali (Jarak Terlalu Jauh)
                print(f"❌ DETEKSI GAGAL: Jarak Terlalu Jauh ({distance:.4f}) | Latensi: {elapsed_time:.2f}s")
                generate_audio_file("S003.mp3", "Data wajah Anda belum terdaftar di sistem. Mohon hubungi admin.")
                return {"status": "unrecognized", "message": "Data Wajah Anda Belum Terdaftar Di Sistem", "track_id": "S003.mp3", "image_url": image_url_for_db}

        else:
            # Database Vektor kosong
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

@app.get("/attendance/today") # Digunakan oleh data.html
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
            
            # Tentukan status berdasarkan log_type
            if log_type == 'IN':
                status_display = "MASUK"
            elif log_type == 'OUT':
                status_display = "PULANG"
            else:
                status_display = "N/A" # Seharusnya tidak terjadi

            attendance_list.append({
                "name": name,
                "instansi": instansi,
                "kategori": kategori,
                "status": status_display, # Kolom status baru
                "timestamp": time_obj.isoformat(), 
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
    """Menghapus semua log absensi yang tercatat untuk hari ini (Manual Trigger) dari PostgreSQL."""
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
        
        # 1. Hapus dari Database Vektor
        cursor.execute("DELETE FROM intern_embeddings WHERE name = %s", (name,))
        deleted_count = cursor.rowcount
        conn.commit()

        # 2. Hapus file gambar dari folder FACES_DIR
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
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT name) FROM intern_embeddings")
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
        if conn:
            conn.close()
            
# --- KRITIS: APP.MOUNT INI HARUS DI POSISI TERAKHIR (FALLBACK) ---
app.mount("/", StaticFiles(directory=str(FRONTEND_STATIC_DIR)), name="frontend")