FROM python:3.9-slim-bullseye

RUN apt-get update && apt-get install -y \
    libgl1 libglib2.0-0 libsm6 libxrender1 libxext6 \
    && pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir numpy==1.21.6 opencv-python-headless==4.5.5.64

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