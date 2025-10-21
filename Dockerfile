# Gunakan image penuh agar TensorFlow bisa ter-install
FROM python:3.9-bullseye

# Instal dependensi sistem (OpenCV, BLAS, compiler)
RUN apt-get update && apt-get install -y \
    libgl1 libglib2.0-0 libsm6 libxrender1 libxext6 \
    build-essential gfortran \
    && pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir \
    numpy==1.21.6 \
    opencv-python-headless==4.5.5.64 \
    tensorflow==2.10.1 \
    keras==2.10.0 \
    deepface==0.0.75 \
    uvicorn==0.37.0

# Tetapkan folder kerja
WORKDIR /app

# Salin requirements tambahan (jika ada)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Salin semua file project
COPY . .

# Jalankan aplikasi FastAPI
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
