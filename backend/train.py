import os
import csv 
import sys
import psycopg2
from pathlib import Path
from deepface import DeepFace
# from datetime import date # Tidak digunakan, dapat dihapus

# Pastikan DeepFace sudah terinstal: pip install deepface
# Pastikan psycopg2 sudah terinstal: pip install psycopg2-binary
# Pastikan pgvector sudah diaktifkan di PostgreSQL server Anda

# --- KONFIGURASI PROYEK ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Path ke file CSV Master di root proyek
CSV_MASTER_PATH = PROJECT_ROOT / "interns.csv" 
# Path ke folder dataset Anda (ASUMSI STRUKTUR: data/dataset/<Nama Intern>/<Gambar>.jpg)
DATASET_PATH = PROJECT_ROOT / "data" / "dataset"
# Model yang digunakan (Misalnya: ArcFace, VGG-Face, dll.)
MODEL = "ArcFace" 

# --- KONFIGURASI DATABASE VEKTOR (PostgreSQL + pgvector) ---
DB_HOST = "localhost"
DB_NAME = "vector_db"
DB_USER = "macbookpro"
DB_PASSWORD = "deepfacepass" 
DB_TABLE_EMBEDDINGS = "intern_embeddings"

# --- FUNGSI DATABASE VEKTOR ---

def connect_vector_db():
    """Membuat koneksi ke Database Vektor (PostgreSQL)."""
    try:
        conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASSWORD)
        # KRITIS: Pastikan ekstensi vector aktif sebelum digunakan
        conn.cursor().execute("CREATE EXTENSION IF NOT EXISTS vector;") 
        conn.commit()
        return conn
    except psycopg2.Error as e:
        print(f"❌ FATAL: Gagal koneksi ke Database Vektor: {e}")
        print("   -> Pastikan PostgreSQL server berjalan, database 'vector_db' ada, dan pgvector diaktifkan.")
        sys.exit(1)

def create_embeddings_table(conn):
    """Memastikan tabel intern_embeddings ada dan skemanya benar (termasuk FK intern_id)."""
    try:
        cur = conn.cursor()
        print("    -> Memastikan skema database: Menghapus tabel lama jika ada...")
        # Hapus tabel lama, ini akan menghapus semua data 
        cur.execute(f"DROP TABLE IF EXISTS {DB_TABLE_EMBEDDINGS};")
        conn.commit()
        
        # KRITIS: Menambahkan kolom intern_id INTEGER REFERENCES interns(id)
        cur.execute(f"""
            CREATE TABLE {DB_TABLE_EMBEDDINGS} (
                id SERIAL PRIMARY KEY,
                intern_id INTEGER REFERENCES interns(id), 
                name VARCHAR(100) NOT NULL,
                instansi VARCHAR(100),
                kategori VARCHAR(100),
                image_path VARCHAR(255) NOT NULL,
                embedding vector(512) NOT NULL
            );
        """)
        conn.commit()
        print("    -> Tabel 'intern_embeddings' berhasil dibuat/dibuat ulang dengan Foreign Key.")
    except Exception as e:
        print(f"❌ ERROR: Gagal membuat/memperbarui tabel database: {e}")
        sys.exit(1)

def get_intern_id_by_name(conn, name: str) -> int:
    """Mencari ID di tabel interns berdasarkan nama."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM interns WHERE name = %s", (name,))
        result = cur.fetchone()
        if result:
            return result[0]
        else:
            raise ValueError(f"ID untuk nama '{name}' tidak ditemukan di tabel interns. Silakan jalankan main.py terlebih dahulu.")
    except Exception as e:
        # Pengecualian hanya diangkat ke level atas (index_dataset)
        raise
    finally:
        cur.close()

# --- FUNGSI MEMBACA DATA CSV ---

def load_master_data():
    """Memuat interns.csv Master Data (Nama, Instansi, dan Kategori) ke dalam dictionary."""
    master_data = {}
    try:
        with open(CSV_MASTER_PATH, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                # Kunci dictionary adalah kolom 'Name' di CSV (cocok dengan nama folder)
                master_data[row['Name']] = {
                    'instansi': row['Instansi'], 
                    'kategori': row['Kategori']
                }
        print("    -> Master data interns.csv berhasil dimuat.")
        return master_data
    except FileNotFoundError:
        print(f"❌ ERROR: File Master CSV tidak ditemukan di: {CSV_MASTER_PATH}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ ERROR: Gagal memproses CSV: {e}")
        sys.exit(1)


# --- FUNGSI UTAMA INDEXING ---

def index_dataset():
    conn = connect_vector_db()
    
    # 1. Pastikan tabel siap
    create_embeddings_table(conn) 
    cur = conn.cursor()
    
    master_data = load_master_data() 
    
    print("\n🧠 Memulai proses indexing fitur (DeepFace/{})...".format(MODEL))
    
    total_indexed_count = 0
    
    for person_name in os.listdir(DATASET_PATH):
        person_dir = DATASET_PATH / person_name
        if not os.path.isdir(person_dir) or person_name.startswith('.'):
            continue
            
        if person_name not in master_data:
            print(f"   ⚠️ PERINGATAN: Nama folder '{person_name}' tidak ditemukan di interns.csv. Folder diabaikan.")
            continue
            
        try:
            # KRITIS: Ambil ID dari tabel interns
            intern_id = get_intern_id_by_name(conn, person_name)
        except ValueError as e:
            print(f"   ❌ Gagal memproses {person_name}: {e}")
            continue # Lanjut ke orang berikutnya
        except Exception as e:
             print(f"❌ FATAL ERROR DB: Gagal memproses {person_name} karena error database saat mengambil ID: {e}")
             continue

        instansi_value = master_data[person_name]['instansi']
        kategori_value = master_data[person_name]['kategori'] 

        print(f"\n   -> Memproses {person_name} (ID: {intern_id})...")
        
        embeddings_to_insert = []
        person_success_count = 0

        for filename in sorted(os.listdir(person_dir)):
            if not filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                continue
                
            filepath = str(person_dir / filename)
            
            try:
                # 1. GENERASI EMBEDDING WAJAH
                print(f"   -> Memproses {person_name} ({filename})...")
                
                representations = DeepFace.represent(
                    img_path=filepath, 
                    model_name=MODEL,
                    enforce_detection=False 
                )
                
                if representations:
                    embedding_vector = representations[0]["embedding"]
                    vector_string = "[" + ",".join(map(str, embedding_vector)) + "]"
                    
                    # KRITIS: Urutan dan jumlah kolom harus sesuai (intern_id, name, instansi, kategori, image_path, vector)
                    embeddings_to_insert.append((intern_id, person_name, instansi_value, kategori_value, filepath, vector_string)) 
                    person_success_count += 1
                else:
                    print(f"   ⚠️ PERINGATAN: Tidak ada representasi yang dibuat untuk {filename}. Gambar diabaikan.")
                    
            except Exception as e:
                if 'Face could not be detected' in str(e):
                    print(f"   ⚠️ PERINGATAN: Wajah tidak terdeteksi di {filename}. Gambar diabaikan.")
                else:
                    print(f"   ❌ Gagal memproses {filename}. Detail: {e}")

        # 2. INSERT BATCH KE DATABASE
        if embeddings_to_insert:
            # KRITIS: Sesuaikan Query untuk 6 kolom
            insert_query = f"INSERT INTO {DB_TABLE_EMBEDDINGS} (intern_id, name, instansi, kategori, image_path, embedding) VALUES (%s, %s, %s, %s, %s, %s::vector)"
            
            try:
                cur.executemany(insert_query, embeddings_to_insert)
                conn.commit()
                total_indexed_count += person_success_count
                print(f"✅ Selesai indexing {person_name}. Total {person_success_count} embeddings disimpan.")
            except Exception as db_e:
                conn.rollback()
                print(f"❌ FATAL ERROR DB: Gagal menyimpan data untuk {person_name}. Detail: {db_e}")
                
        else:
            print(f"✅ Selesai indexing {person_name}. Total 0 embeddings disimpan.")
            
    conn.close()
    
    print("\n" + "="*50)
    if total_indexed_count > 0:
        print(f"🎉 INDEXING LENGKAP! Total {total_indexed_count} wajah berhasil disimpan.")
    else:
        print("⚠️ INDEXING SELESAI, tetapi tidak ada wajah yang berhasil di-index.")
    print("="*50)

if __name__ == "__main__":
    print("="*50)
    print("🤖 SCRIPT INDEXING WAJAH")
    print("="*50)
    index_dataset()