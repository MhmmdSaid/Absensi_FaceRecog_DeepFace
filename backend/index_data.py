import os
import csv
import sys
from pathlib import Path
from deepface import DeepFace
import numpy as np
import psycopg2
import psycopg2.extensions

# --- KONFIGURASI DAN IMPORT DENGAN KOREKSI PATH ---
try:
    file_path = Path(__file__).resolve()
    if file_path.parent.name == 'backend':
        PROJECT_ROOT = file_path.parent.parent
        sys.path.insert(0, str(PROJECT_ROOT))
    else:
        PROJECT_ROOT = file_path.parent

    # Coba import absolut dulu
    try:
         from backend.utils import MODEL_NAME, EMBEDDING_DIM
    except ImportError:
         # Fallback ke import relatif jika dijalankan sebagai modul
         from .utils import MODEL_NAME, EMBEDDING_DIM

except ImportError as e:
    print(f"❌ FATAL ERROR: Gagal mengimpor utilitas atau menentukan root: {e}")
    MODEL_NAME = "VGG-Face"
    EMBEDDING_DIM = 512
    print(f"   -> Menggunakan fallback: MODEL_NAME='{MODEL_NAME}', EMBEDDING_DIM={EMBEDDING_DIM}")

# --- KONFIGURASI PROYEK ---
CSV_MASTER_PATH = PROJECT_ROOT / "interns.csv"
DATASET_PATH = PROJECT_ROOT / "data" / "dataset"

# --- KONFIGURASI DATABASE VEKTOR (MEMBACA DARI ENV) ---
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "intern_attendance_db")
DB_USER = os.getenv("DB_USER", "macbookpro")
DB_PASSWORD = os.getenv("DB_PASSWORD", "deepfacepass")
# --------------------------------------------------------

DB_TABLE_INTERNS = "interns"
DB_TABLE_EMBEDDINGS = "intern_embeddings"
DB_TABLE_CENTROIDS = "intern_centroids"


# --- FUNGSI UTILITY DATABASE ---

def connect_db():
    """Membuat koneksi ke Database dan mendaftarkan tipe data vector untuk NumPy."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            port=DB_PORT
        )
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT oid FROM pg_type WHERE typname = 'vector'")
                vector_oid = cur.fetchone()[0]

            def cast_vector(data, cur):
                if data is None: return None
                cleaned_data = data.strip('{}[]')
                return np.array([float(x.strip()) for x in cleaned_data.split(',')])

            psycopg2.extensions.register_type(
                psycopg2.extensions.new_type((vector_oid,), 'vector', cast_vector),
                conn
            )
        except Exception as e:
             print(f"   ⚠️ PERINGATAN: Gagal mendaftarkan tipe vector. Error: {e}")

        return conn
    except psycopg2.Error as e:
        print(f"❌ ERROR: Gagal koneksi ke Database: {e}")
        print(f"   -> Mencoba terhubung ke {DB_HOST}:{DB_PORT}...")
        sys.exit(1) # Gagal keras agar subprocess mengembalikan error

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
        conn.commit() # Commit setelah UPSERT berhasil
        return intern_id
    except Exception as e:
        conn.rollback() # Rollback jika gagal
        raise Exception(f"Gagal melakukan UPSERT intern {name}: {e}")
    finally:
        cur.close()

def load_master_data():
    """Memuat interns.csv Master Data, menggunakan Image_Folder sebagai kunci."""
    master_data = {}
    if not CSV_MASTER_PATH.exists():
         print(f"❌ ERROR: File Master CSV tidak ditemukan di: {CSV_MASTER_PATH}")
         print("   -> Pastikan file interns.csv ada di root proyek.")
         sys.exit(1)
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
        print(f"✅ Berhasil memuat {len(master_data)} entri dari {CSV_MASTER_PATH}")
        return master_data
    except Exception as e:
        print(f"❌ ERROR: Gagal memproses CSV: {e}")
        sys.exit(1)

def get_existing_file_paths(conn, intern_id: int) -> set:
    """Mengambil semua path file yang sudah di-index untuk intern tertentu."""
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT file_path FROM {DB_TABLE_EMBEDDINGS} WHERE intern_id = %s", (intern_id,))
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
    print(f"   Dataset Path: {DATASET_PATH}")
    print("==================================================")

    intern_ids_to_recalculate = set()
    total_new_embeddings = 0

    # 1. ITERASI DATASET DAN BUAT EMBEDDING BARU
    print("✅ Memastikan data interns.csv terdaftar dan memproses embeddings baru...")

    if not DATASET_PATH.exists() or not DATASET_PATH.is_dir():
        print(f"❌ ERROR: Folder dataset tidak ditemukan di {DATASET_PATH}")
        conn.close()
        sys.exit(1)

    processed_folders = 0
    skipped_folders = 0
    for folder_name in os.listdir(DATASET_PATH):
        person_dir = DATASET_PATH / folder_name

        if not os.path.isdir(person_dir) or folder_name.startswith('.'):
            continue

        if folder_name not in master_data:
            print(f"   ⚠️ PERINGATAN: Folder '{folder_name}' diabaikan (tidak ada di CSV).")
            skipped_folders += 1
            continue

        processed_folders += 1
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
            intern_ids_to_recalculate.add(intern_id) # Tandai untuk hitung ulang centroid

            # B. Ambil list file yang sudah ada di DB
            existing_paths = get_existing_file_paths(conn, intern_id)
            print(f"\n   -> Memproses {person_name} (ID: {intern_id})... {len(existing_paths)} file sudah ada.")

            # C. Proses gambar baru saja
            image_files = [f for f in sorted(os.listdir(person_dir)) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            print(f"     Ditemukan {len(image_files)} file gambar.")

            for filename in image_files:
                # Gunakan path relatif dari PROJECT_ROOT untuk konsistensi
                relative_filepath = f"data/dataset/{folder_name}/{filename}"
                absolute_filepath = str(PROJECT_ROOT / relative_filepath) # Path absolut untuk DeepFace

                # Cek jika path RELATIF sudah ada
                if relative_filepath in existing_paths:
                    # print(f"     [SKIP] {filename} sudah di database.")
                    continue

                try:
                    # print(f"     [PROSES] {filename}")
                    representations = DeepFace.represent(
                        img_path=absolute_filepath,
                        model_name=MODEL_NAME,
                        enforce_detection=True,
                        detector_backend='retinaface' # Coba backend lain jika default gagal
                    )

                    if representations and len(representations) > 0 and "embedding" in representations[0]:
                        embedding_vector = representations[0]["embedding"]
                        vector_string = "[" + ",".join(map(str, embedding_vector)) + "]"
                        # Simpan path RELATIF ke DB
                        embeddings_to_insert.append((intern_id, person_name, instansi_value, kategori_value, relative_filepath, vector_string))
                        person_new_count += 1
                    else:
                         print(f"     [SKIP] Tidak ada embedding dihasilkan untuk {filename}.")


                except ValueError as ve:
                     if 'Face could not be detected' in str(ve):
                         print(f"     [SKIP] Wajah tidak terdeteksi di {filename}.")
                     else:
                         print(f"     [ERROR] Gagal memproses {filename}. Detail: {ve}")
                except Exception as e:
                    print(f"     [ERROR] Gagal memproses {filename}. Detail: {e}")

        except Exception as e:
             conn.rollback()
             print(f"❌ FATAL ERROR: Gagal memproses intern {person_name}. Detail: {e}")
             continue # Lanjut ke folder berikutnya

        # D. INSERT BATCH EMBEDDING BARU
        if embeddings_to_insert:
            insert_query = f"INSERT INTO {DB_TABLE_EMBEDDINGS} (intern_id, name, instansi, kategori, file_path, embedding) VALUES (%s, %s, %s, %s, %s, %s::vector)"
            try:
                cur.executemany(insert_query, embeddings_to_insert)
                conn.commit()
                total_new_embeddings += person_new_count
                print(f"   ✅ Selesai: {person_new_count} embeddings BARU disimpan untuk {person_name}.")
            except Exception as db_e:
                conn.rollback()
                print(f"❌ FATAL ERROR DB: Gagal menyimpan embeddings untuk {person_name}. Detail: {db_e}")
        else:
            if image_files: # Hanya cetak jika ada gambar tapi tidak ada yang baru
                 print(f"     [INFO] Tidak ada embeddings baru yang diproses untuk {person_name}.")
            else:
                 print(f"     [INFO] Tidak ada file gambar ditemukan untuk {person_name}.")


    print(f"\n✅ Selesai memproses {processed_folders} folder. {skipped_folders} folder diabaikan (tidak ada di CSV).")

    # 2. HITUNG ULANG CENTROID UNTUK SEMUA YANG TERDAMPAK
    if not intern_ids_to_recalculate:
        print("\n⚠️ Tidak ada data baru yang diproses atau intern yang terpengaruh. Perhitungan Centroid dilewati.")
    else:
        print("\n==================================================")
        print(f"🧠 MEMULAI PERHITUNGAN CENTROID ({len(intern_ids_to_recalculate)} intern)")
        print("==================================================")

        recalculated_count = 0
        for intern_id in intern_ids_to_recalculate:
            cur.execute(f"""
                SELECT name, instansi, kategori, embedding
                FROM {DB_TABLE_EMBEDDINGS}
                WHERE intern_id = %s
            """, (intern_id,))

            results = cur.fetchall()

            if not results:
                print(f"   ⚠️ Tidak ada embedding ditemukan untuk Intern ID {intern_id}. Centroid dilewati.")
                continue

            name, instansi, kategori = results[0][0], results[0][1], results[0][2]

            try:
                # results[i][3] sudah berupa numpy array karena registrasi tipe
                embeddings_array = np.stack([res[3] for res in results])
                if embeddings_array.ndim == 1: # Jika hanya 1 embedding
                    embeddings_array = embeddings_array.reshape(1, -1)
            except Exception as e:
                print(f"   ❌ ERROR: Gagal stack embeddings untuk {name}. Error: {e}")
                continue


            centroid_vector = np.mean(embeddings_array, axis=0)

            # Normalisasi Centroid (opsional tapi bagus untuk cosine distance)
            norm = np.linalg.norm(centroid_vector)
            if norm > 1e-6: # Hindari pembagian dengan nol
                centroid_vector = centroid_vector / norm
            else:
                print(f"   ⚠️ Peringatan: Centroid untuk {name} mendekati nol. Normalisasi dilewati.")

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
                print(f"   ✅ Centroid {name} berhasil diperbarui dari {len(results)} embeddings.")
                recalculated_count += 1
            except Exception as e:
                conn.rollback()
                print(f"   ❌ ERROR: Gagal menyimpan centroid untuk {name}: {e}")

    conn.close()

    print("\n" + "="*50)
    print(f"🎉 ALUR KERJA LENGKAP!")
    print(f"   Total {total_new_embeddings} embedding baru ditambahkan.")
    if intern_ids_to_recalculate:
        print(f"   Total {recalculated_count} centroid dihitung ulang/diperbarui.")
    print("="*50)

if __name__ == "__main__":
    index_data_incremental()