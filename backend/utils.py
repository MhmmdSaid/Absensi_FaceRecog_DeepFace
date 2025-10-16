import numpy as np
import cv2 
from deepface import DeepFace
import os
# import psycopg2 # Hapus import yang tidak digunakan jika koneksi DB di handle di file lain

# --- KONFIGURASI KRITIS (Sumber Tunggal) ---

# Nama model DeepFace yang digunakan (Harus konsisten di seluruh proyek: indexing & real-time)
MODEL_NAME = "ArcFace" 
# Dimensi vektor yang dihasilkan oleh ArcFace. HARUS SAMA dengan vector(512) di tabel DB.
EMBEDDING_DIM = 512 
# Batas ambang jarak kosinus (Cosine Distance) untuk penentuan wajah dikenali
# Wajah dikenali jika jarak <= DISTANCE_THRESHOLD
DISTANCE_THRESHOLD = 0.40 


# --- FUNGSI EKSTRAKSI FITUR ---

def extract_face_features(image_bytes: bytes):
    """
    Ekstraksi fitur wajah (embedding) menggunakan model DeepFace dari data bytes gambar.
    Menggunakan MODEL_NAME yang didefinisikan secara global di utils.py.
    
    Args:
        image_bytes (bytes): Data gambar yang diunggah dari frontend.
        
    Returns:
        list of list[float]: List dari embedding wajah yang terdeteksi. 
                             Mengembalikan list kosong ([]) jika tidak ada wajah.
    """
    
    try:
        # 1. Konversi bytes (dari upload FastAPI) ke array numpy mentah
        np_array = np.frombuffer(image_bytes, np.uint8)
        # 2. Decode array bytes menjadi array gambar yang dapat dibaca OpenCV (cv2.imdecode)
        img_array = cv2.imdecode(np_array, cv2.IMREAD_COLOR)

        if img_array is None:
             print("❌ Gagal membaca bytes gambar. Mungkin format file tidak didukung.")
             return []

        # 3. DeepFace.represent: menerima numpy array (img_array)
        results = DeepFace.represent(
            img_path=img_array, # Menerima NumPy array, bukan path file
            model_name=MODEL_NAME, # Menggunakan konstanta global
            enforce_detection=True, 
            detector_backend='opencv' 
        )
    except ValueError as ve:
        # Menangani kesalahan DeepFace saat wajah tidak ditemukan
        if 'Face could not be detected' in str(ve):
             print(f"⚠️ Peringatan: Tidak ada wajah terdeteksi pada input.")
        else:
             print(f"⚠️ Peringatan: DeepFace gagal memproses gambar. Detail: {ve}")
        return []
    except Exception as e:
        # Menangani error umum lainnya
        print(f"❌ ERROR Ekstraksi Fitur: {e}")
        return []


    if not results:
        return []

    # Ambil embedding dari semua wajah yang dideteksi
    embeddings_list = [res["embedding"] for res in results]
    
    # Periksa dimensi sebagai validasi tambahan (meskipun deepface harus benar)
    if embeddings_list and len(embeddings_list[0]) != EMBEDDING_DIM:
         print(f"❌ ERROR: Dimensi embedding ({len(embeddings_list[0])}) tidak cocok dengan EMBEDDING_DIM ({EMBEDDING_DIM})")
         return []
         
    return embeddings_list