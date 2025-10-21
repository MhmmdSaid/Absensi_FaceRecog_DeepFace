import os
import csv 
import sys
from pathlib import Path
from deepface import DeepFace
import numpy as np
# --- IMPORT KRITIS UNTUK PSQL/PGVECTOR ---
import psycopg2
import psycopg2.extensions 

# --- KONFIGURASI DAN IMPORT DENGAN KOREKSI PATH ---
try:
    # 1. Tentukan path file yang sedang dieksekusi
    file_path = Path(__file__).resolve()
    
    # 2. Jika file berada di folder 'backend', naik satu level untuk menentukan PROJECT_ROOT
    if file_path.parent.name == 'backend':
        PROJECT_ROOT = file_path.parent.parent
        # Memastikan path modul backend dapat ditemukan (untuk import utils)
        sys.path.insert(0, str(PROJECT_ROOT)) 
    else:
        # Jika file ada di root (skenario ini jarang terjadi, tapi sebagai fallback)
        PROJECT_ROOT = file_path.parent
        
    # Import konstanta kritis dari utils.py (Asumsi: utils.py ada di backend/)
    from backend.utils import MODEL_NAME, EMBEDDING_DIM 
except ImportError as e:
    print(f"❌ FATAL ERROR: Gagal mengimpor utilitas atau menentukan root: {e}")
    print("   -> Pastikan file utils.py berada di backend/utils.py")
    # Fallback jika import utils gagal
    MODEL_NAME = "VGG-Face" 
    EMBEDDING_DIM = 512
    print(f"   -> Menggunakan fallback: MODEL_NAME='{MODEL_NAME}', EMBEDDING_DIM={EMBEDDING_DIM}")


# --- KONFIGURASI PROYEK ---
CSV_MASTER_PATH = PROJECT_ROOT / "interns.csv" 
DATASET_PATH = PROJECT_ROOT / "data" / "dataset"

# --- KONFIGURASI DATABASE VEKTOR ---
DB_CONFIG = {
    "host": "localhost",
    "database": "intern_attendance_db",
    "user": "macbookpro",
    "password": "deepfacepass",
    "port": "5432"
}
DB_TABLE_INTERNS = "interns" 
DB_TABLE_EMBEDDINGS = "intern_embeddings"
DB_TABLE_CENTROIDS = "intern_centroids"


# --- FUNGSI UTILITY DATABASE (PERBAIKAN FUNGSI CAST DI SINI) ---

def connect_db():
    """Membuat koneksi ke Database dan mendaftarkan tipe data vector untuk NumPy."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        
        # --- LANGKAH KRITIS: Mendaftarkan Tipe Vektor ---
        try:
            with conn.cursor() as cur:
                # 1. Cari OID tipe 'vector'
                cur.execute("SELECT oid FROM pg_type WHERE typname = 'vector'")
                vector_oid = cur.fetchone()[0]
            
            # 2. Buat fungsi konversi (Sekarang membersihkan {} dan [])
            def cast_vector(data, cur):
                if data is None:
                    return None
                
                # Menghapus kurung kurawal atau kurung siku di awal/akhir
                cleaned_data = data.strip('{}[]')
                
                return np.array([float(x.strip()) for x in cleaned_data.split(',')])
            
            # 3. Daftarkan tipe data vector
            psycopg2.extensions.register_type(
                psycopg2.extensions.new_type((vector_oid,), 'vector', cast_vector), 
                conn
            )
        except Exception as e:
             # Ini adalah fallback jika registrasi gagal
             print(f"   ⚠️ PERINGATAN: Gagal mendaftarkan tipe vector. Error: {e}")
             
        # ------------------------------------------------
        
        return conn
    except psycopg2.Error as e:
        print(f"❌ ERROR: Gagal koneksi ke Database: {e}")
        sys.exit(1)


def upsert_intern_and_get_id(conn, name: str, instansi: str, kategori: str) -> int:
    """Memastikan data intern ada di tabel 'interns' dan mengembalikan ID-nya (UPSERT)."""
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            INSERT INTO {DB_TABLE_INTERNS} (name, instansi, kategori) 
            VALUES (%s, %s, %s)
            ON CONFLICT (name) DO UPDATE SET
                instansi = EXCLUDED.instansi,
                kategori = EXCLUDED.kategori 
            RETURNING id;
            """,
            (name, instansi, kategori)
        )
        intern_id = cur.fetchone()[0]
        return intern_id
    except Exception as e:
        raise Exception(f"Gagal melakukan UPSERT intern {name}: {e}")
    finally:
        cur.close()

def load_master_data():
    """Memuat interns.csv Master Data, menggunakan Image_Folder sebagai kunci."""
    master_data = {}
    try:
        with open(CSV_MASTER_PATH, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                folder_key = row['Image_Folder']
                
                master_data[folder_key] = {
                    'name_full': row['Name'],
                    'instansi': row.get('Instansi', 'N/A'), 
                    'kategori': row.get('Kategori', 'N/A')
                }
        return master_data
    except FileNotFoundError:
        print(f"❌ ERROR: File Master CSV tidak ditemukan di: {CSV_MASTER_PATH}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ ERROR: Gagal memproses CSV: {e}")
        sys.exit(1)

def get_existing_image_paths(conn, intern_id: int) -> set:
    """Mengambil semua path gambar yang sudah di-index untuk intern tertentu."""
    cur = conn.cursor()
    try:
        # --- UBAH BARIS INI ---
        cur.execute(f"SELECT file_path FROM {DB_TABLE_EMBEDDINGS} WHERE intern_id = %s", (intern_id,))
        # ---------------------
        return {row[0] for row in cur.fetchall()}
    finally:
        cur.close()


# --- FUNGSI UTAMA (INCREMENTAL INDEXING) ---

def index_data_incremental():
    conn = connect_db()
    cur = conn.cursor()
    
    try:
        master_data = load_master_data() 
    except SystemExit:
        conn.close()
        return

    
    print("==================================================")
    print(f"🧠 SCRIPT INDEXING INCREMENTAL (DeepFace/{MODEL_NAME} - {EMBEDDING_DIM}D)")
    print("==================================================")
    
    intern_ids_to_recalculate = set()
    total_new_embeddings = 0

    # 1. ITERASI DATASET DAN BUAT EMBEDDING BARU
    print("✅ Memastikan data interns.csv terdaftar dan memproses embeddings baru...")
    
    for folder_name in os.listdir(DATASET_PATH):
        person_dir = DATASET_PATH / folder_name
        
        if not os.path.isdir(person_dir) or folder_name.startswith('.'):
            continue
            
        if folder_name not in master_data:
            print(f"   ⚠️ PERINGATAN: Folder '{folder_name}' diabaikan (tidak ada di CSV).")
            continue
            
        metadata = master_data[folder_name]
        person_name = metadata['name_full']
        instansi_value = metadata['instansi']
        kategori_value = metadata['kategori'] 
        
        intern_id = None
        embeddings_to_insert = []
        person_new_count = 0

        try:
            # A. UPSERT INTERN 
            intern_id = upsert_intern_and_get_id(conn, person_name, instansi_value, kategori_value)
            intern_ids_to_recalculate.add(intern_id)
            
            # B. Ambil list gambar yang sudah ada di DB
            existing_paths = get_existing_image_paths(conn, intern_id)
            
            print(f"   -> Memproses {person_name} (ID: {intern_id})...")
            
            # C. Proses gambar baru saja
            for filename in sorted(os.listdir(person_dir)):
                filepath = str(person_dir / filename)
                
                if filepath in existing_paths:
                    continue 
                
                if not filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                    continue
                
                try:
                    representations = DeepFace.represent(
                        img_path=filepath, 
                        model_name=MODEL_NAME, 
                        enforce_detection=True 
                    )
                    
                    if representations:
                        embedding_vector = representations[0]["embedding"]
                        
                        # --- PERBAIKAN KRITIS: Menggunakan KURUNG SIKU [] ---
                        vector_string = "[" + ",".join(map(str, embedding_vector)) + "]" 
                        
                        embeddings_to_insert.append((intern_id, person_name, instansi_value, kategori_value, filepath, vector_string)) 
                        person_new_count += 1
                        
                except Exception as e:
                    if 'Face could not be detected' in str(e):
                        print(f"     [SKIP] Wajah tidak terdeteksi di {filename}.")
                    else:
                        print(f"     [ERROR] Gagal memproses {filename}. Detail: {e}")

        except Exception as e:
             conn.rollback()
             print(f"❌ FATAL ERROR: Gagal memproses intern {person_name}. Detail: {e}")
             continue 

        # D. INSERT BATCH EMBEDDING BARU
        if embeddings_to_insert:
            insert_query = f"INSERT INTO {DB_TABLE_EMBEDDINGS} (intern_id, name, instansi, kategori, file_path, embedding) VALUES (%s, %s, %s, %s, %s, %s::vector)"
            
            try:
                cur.executemany(insert_query, embeddings_to_insert)
                conn.commit()
                total_new_embeddings += person_new_count
                print(f"✅ Selesai: {person_new_count} embeddings BARU disimpan untuk {person_name}.")
            except Exception as db_e:
                conn.rollback()
                print(f"❌ FATAL ERROR DB: Gagal menyimpan embeddings untuk {person_name}. Detail: {db_e}")
                
        else:
            print(f"     [INFO] Tidak ada embeddings baru yang ditemukan untuk {person_name}.")

    # 2. HITUNG ULANG CENTROID UNTUK SEMUA YANG TERDAMPAK
    if not intern_ids_to_recalculate:
        print("\n⚠️ Tidak ada data baru yang diproses. Perhitungan Centroid dilewati.")
    else:
        print("\n==================================================")
        print("🧠 MEMULAI PERHITUNGAN CENTROID")
        print("==================================================")
        
        for intern_id in intern_ids_to_recalculate:
            cur.execute(f"""
                SELECT name, instansi, kategori, embedding 
                FROM {DB_TABLE_EMBEDDINGS} 
                WHERE intern_id = %s
            """, (intern_id,))
            
            results = cur.fetchall()
            
            if not results:
                continue

            name, instansi, kategori = results[0][0], results[0][1], results[0][2]
            
            # Res[3] sekarang adalah numpy array (karena registrasi tipe)
            try:
                embeddings_array = np.stack([res[3] for res in results]) 
            except Exception as e:
                print(f"   ❌ ERROR: Centroid {name} gagal dihitung. Error: {e}")
                continue


            centroid_vector = np.mean(embeddings_array, axis=0)
            
            # Normalisasi Centroid
            norm = np.linalg.norm(centroid_vector)
            if norm > 0:
                centroid_vector = centroid_vector / norm
            
            # --- PERBAIKAN KRITIS: Menggunakan KURUNG SIKU [] untuk Centroid ---
            centroid_str = "[" + ",".join(map(str, centroid_vector)) + "]"

            # UPSERT Centroid ke Tabel intern_centroids
            try:
                cur.execute(
                    f"""
                    INSERT INTO {DB_TABLE_CENTROIDS} (intern_id, name, instansi, kategori, embedding) 
                    VALUES (%s, %s, %s, %s, %s::vector)
                    ON CONFLICT (intern_id) DO UPDATE SET
                        embedding = EXCLUDED.embedding,
                        name = EXCLUDED.name,
                        instansi = EXCLUDED.instansi,
                        kategori = EXCLUDED.kategori;
                    """,
                    (intern_id, name, instansi, kategori, centroid_str)
                )
                conn.commit()
                print(f"✅ Centroid {name} berhasil diperbarui dari {len(results)} embeddings.")
            except Exception as e:
                conn.rollback()
                print(f"❌ ERROR: Gagal menyimpan centroid untuk {name}: {e}")

    conn.close()
    
    print("\n" + "="*50)
    print(f"🎉 ALUR KERJA LENGKAP! Total {total_new_embeddings} embedding baru berhasil ditambahkan.")
    print("="*50)

if __name__ == "__main__":
    index_data_incremental()