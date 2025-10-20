# 1. Mulai dari image Python 3.9 yang ringan
FROM python:3.9-slim-bullseye

# 2. Instal library sistem yang dibutuhkan oleh OpenCV (komponen DeepFace)
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6

# 3. Tetapkan folder kerja di dalam container
WORKDIR /app

# 4. Salin daftar belanjaan (requirements.txt) dan instal
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Salin seluruh kode proyek Anda ke dalam container
COPY . .

# 6. Perintah untuk menjalankan server saat container dinyalakan
#    --host 0.0.0.0 sangat penting agar bisa diakses
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]