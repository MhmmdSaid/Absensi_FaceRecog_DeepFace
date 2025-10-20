# 1. Mulai dari image Python 3.9 yang ringan
FROM python:3.9-slim-bullseye

# 2. Instal library sistem yang dibutuhkan oleh OpenCV
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6

# 3. Tetapkan folder kerja di dalam container
WORKDIR /app

# 4. Salin daftar requirements dan instal
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Salin seluruh kode proyek Anda
COPY . .

# --- PERUBAHAN: JALANKAN PRE-LOADING MODEL ---
# Ini akan mengunduh model saat proses build, bukan saat runtime
RUN python backend/prestart.py
# ---------------------------------------------

# 6. Perintah untuk menjalankan server saat container dinyalakan
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
