# backend/prestart.py
from deepface import DeepFace

def preload_models():
    """
    Fungsi ini akan memaksa DeepFace untuk mengunduh model-model
    yang diperlukan saat Docker image dibangun.
    """
    print("Pre-loading DeepFace models...")
    try:
        # Memuat model yang digunakan untuk representasi (Facenet512)
        DeepFace.represent(img_path=".", model_name='Facenet512', enforce_detection=False)
        print(" -> Facenet512 model pre-loaded.")
        
        # Anda bisa menambahkan model lain di sini jika perlu
        # Contoh: DeepFace.detectFace(".", detector_backend='opencv')

    except Exception as e:
        # Jika folder kosong, DeepFace akan error. Kita tangkap saja.
        print(f"Finished pre-loading models (ignoring error: {e})")

if __name__ == "__main__":
    preload_models()
