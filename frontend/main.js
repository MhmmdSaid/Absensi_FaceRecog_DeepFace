const API_BASE_URL = "http://127.0.0.1:8000"; // Pastikan IP/Port sesuai
const videoElement = document.getElementById("videoElement");
const canvasElement = document.getElementById("canvasElement"); // Untuk snapshot
const overlayCanvas = document.getElementById("overlayCanvas"); // Untuk MediaPipe
const overlayCtx = overlayCanvas.getContext("2d");
const statusArea = document.getElementById("statusArea");
const absenMasukBtn = document.getElementById("absenMasukBtn");
const absenPulangBtn = document.getElementById("absenPulangBtn");
const resultCard = document.getElementById("resultCard");
const resultTitle = document.getElementById("resultTitle");
const resultCardBody = document.getElementById("resultCardBody");

let stream = null;
let isProcessing = false; // Mencegah klik ganda

// --- Variabel untuk Liveness Detection ---
let faceMesh = null;
let livenessCheckActive = false; // Status apakah kita sedang mencari kedipan
let livenessCheckType = null; // Menyimpan 'IN' atau 'OUT'

// --- PENGATURAN KEDIPAN ---
let blinkCounter = 0; // Penghitung kedipan
const REQUIRED_BLINKS = 2; // <<< PERUBAHAN: Target 2 kedipan
const BLINK_THRESHOLD = 0.28; // Sensitivitas EAR
const EYE_CLOSED_FRAMES = 0; // Cukup 1 frame tertutup
let closedFramesCounter = 0;
// ---------------------------------

function updateStatus(message, type = "info") {
  const map = {
    success: "status-area bg-green-100 text-green-700",
    error: "status-area bg-red-100 text-red-700",
    loading: "status-area bg-blue-100 text-blue-700",
    info: "status-area bg-gray-100 text-gray-700",
    liveness: "status-area bg-yellow-100 text-yellow-700",
  };
  statusArea.className = map[type] || "status-area";
  statusArea.innerHTML = message;
}

function initializeMediaPipe() {
  faceMesh = new FaceMesh({
    locateFile: (file) => {
      return `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${file}`;
    },
  });

  faceMesh.setOptions({
    maxNumFaces: 1,
    refineLandmarks: true,
    minDetectionConfidence: 0.5,
    minTrackingConfidence: 0.5,
  });

  faceMesh.onResults(onFaceMeshResults);
}

async function startCamera() {
  try {
    const constraints = {
      video: {
        width: { ideal: 640 },
        height: { ideal: 480 },
        facingMode: "user",
      },
    };
    stream = await navigator.mediaDevices.getUserMedia(constraints);
    videoElement.srcObject = stream;

    videoElement.onloadedmetadata = () => {
      overlayCanvas.width = videoElement.videoWidth;
      overlayCanvas.height = videoElement.videoHeight;
      canvasElement.width = videoElement.videoWidth;
      canvasElement.height = videoElement.videoHeight;

      const camera = new Camera(videoElement, {
        onFrame: async () => {
          await faceMesh.send({ image: videoElement });
        },
        width: 640,
        height: 480,
      });
      camera.start();
    };

    updateStatus("Kamera aktif. Silakan lakukan absensi.", "success");
  } catch (err) {
    console.error("Error mengakses kamera:", err);
    updateStatus(
      "Gagal mengakses kamera. Pastikan izin kamera diberikan.",
      "error"
    );
  }
}

function stopCamera() {
  if (stream) {
    stream.getTracks().forEach((track) => track.stop());
    stream = null;
  }
}

function getEAR(landmarks, eyeIndices) {
  const v1 = getDistance(landmarks[eyeIndices[1]], landmarks[eyeIndices[5]]);
  const v2 = getDistance(landmarks[eyeIndices[2]], landmarks[eyeIndices[4]]);
  const h = getDistance(landmarks[eyeIndices[0]], landmarks[eyeIndices[3]]);
  const ear = (v1 + v2) / (2.0 * h);
  return ear;
}

function getDistance(p1, p2) {
  return Math.sqrt(Math.pow(p1.x - p2.x, 2) + Math.pow(p1.y - p2.y, 2));
}

const LEFT_EYE_INDICES = [33, 160, 158, 133, 153, 144];
const RIGHT_EYE_INDICES = [362, 385, 387, 263, 373, 380];

async function onFaceMeshResults(results) {
  overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);

  if (results.multiFaceLandmarks && results.multiFaceLandmarks.length > 0) {
    const landmarks = results.multiFaceLandmarks[0];

    if (livenessCheckActive) {
      const leftEAR = getEAR(landmarks, LEFT_EYE_INDICES);
      const rightEAR = getEAR(landmarks, RIGHT_EYE_INDICES);
      const avgEAR = (leftEAR + rightEAR) / 2.0;

      // --- LOGIKA 2 KEDIPAN ---
      if (avgEAR < BLINK_THRESHOLD) {
        closedFramesCounter++;
      } else {
        if (closedFramesCounter > EYE_CLOSED_FRAMES) {
          // Mata baru saja terbuka dari kedipan
          blinkCounter++; // <<< PERUBAHAN: Tambah hitungan kedipan
          console.log(`BLINK ${blinkCounter} DETECTED!`);

          if (blinkCounter >= REQUIRED_BLINKS) {
            // --- SUDAH MENCAPAI TARGET 2 KEDIPAN ---
            livenessCheckActive = false;
            isProcessing = true;
            await performAbsensi(livenessCheckType); // Jalankan absensi
          } else {
            // --- BELUM MENCAPAI TARGET ---
            updateStatus(
              `Bagus! Kedipan ${blinkCounter} dari ${REQUIRED_BLINKS}. Silakan berkedip lagi.`,
              "liveness"
            );
          }
        }
        closedFramesCounter = 0;
      }
      // --- AKHIR LOGIKA 2 KEDIPAN ---
    }
  } else {
    if (livenessCheckActive) {
      updateStatus(
        "Wajah tidak terdeteksi. Posisikan wajah Anda di depan kamera.",
        "liveness"
      );
    }
  }
}

function captureImage() {
  if (!stream) {
    updateStatus("Kamera tidak aktif.", "error");
    return null;
  }
  const context = canvasElement.getContext("2d");
  context.translate(canvasElement.width, 0);
  context.scale(-1, 1);
  context.drawImage(videoElement, 0, 0, canvasElement.width, canvasElement.height);
  context.setTransform(1, 0, 0, 1, 0, 0);
  return new Promise((resolve, reject) => {
    canvasElement.toBlob(
      (blob) => {
        if (blob) {
          resolve(blob);
        } else {
          reject(new Error("Gagal membuat Blob dari Canvas."));
        }
      },
      "image/jpeg",
      0.9
    );
  });
}

async function performAbsensi(typeAbsensi) {
  resultCard.classList.add("hidden");
  absenMasukBtn.disabled = true;
  absenPulangBtn.disabled = true;

  const actionText = typeAbsensi === "IN" ? "Masuk" : "Pulang";
  updateStatus(
    `Liveness Terdeteksi! Memproses Absensi ${actionText}...`,
    "loading"
  );

  try {
    const imageBlob = await captureImage();
    if (!imageBlob) {
      throw new Error("Gagal mengambil gambar setelah liveness check.");
    }
    const formData = new FormData();
    formData.append("file", imageBlob, "capture.jpg");
    formData.append("type_absensi", typeAbsensi);

    const response = await fetch(`${API_BASE_URL}/recognize`, {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const data = await response.json();
    handleAbsensiResult(data);
  } catch (error) {
    console.error("Error Absensi:", error);
    updateStatus(`Gagal memproses absensi: ${error.message}`, "error");
  } finally {
    isProcessing = false;
    livenessCheckActive = false;
    livenessCheckType = null;
    blinkCounter = 0; // <<< PERUBAHAN: Reset hitungan kedipan
    absenMasukBtn.disabled = false;
    absenPulangBtn.disabled = false;
    setTimeout(() => {
      if (!isProcessing)
        updateStatus("Kamera aktif. Silakan lakukan absensi.", "success");
    }, 3000);
  }
}

function startLivenessCheck(typeAbsensi) {
  if (isProcessing || livenessCheckActive) return;

  livenessCheckType = typeAbsensi;
  livenessCheckActive = true;
  closedFramesCounter = 0;
  blinkCounter = 0; // <<< PERUBAHAN: Reset hitungan kedipan saat mulai

  absenMasukBtn.disabled = true;
  absenPulangBtn.disabled = true;
  resultCard.classList.add("hidden");

  // <<< PERUBAHAN: Minta 2 kedipan
  updateStatus(
    `Deteksi Liveness... SILAKAN BERKEDIP ${REQUIRED_BLINKS} KALI.`,
    "liveness"
  );

  // Set timeout pengaman (diberi waktu lebih lama, misal 10 detik)
  setTimeout(() => {
    if (livenessCheckActive) {
      livenessCheckActive = false;
      livenessCheckType = null;
      blinkCounter = 0; // Reset
      absenMasukBtn.disabled = false;
      absenPulangBtn.disabled = false;
      updateStatus(
        "Liveness Gagal: Tidak ada kedipan terdeteksi. Silakan coba lagi.",
        "error"
      );
    }
  }, 10000); // Waktu 10 detik untuk 2 kedipan
}

function handleAbsensiResult(data) {
  // (Fungsi ini sama persis seperti sebelumnya, tidak perlu diubah)
  const audioPlayer = new Audio();
  resultCard.classList.remove("hidden");
  resultCardBody.innerHTML = "";
  const typeDisplay = data.type === "IN" ? "MASUK" : "PULANG";
  if (data.status === "success") {
    const distanceDisplay = data.distance
      ? `(${data.distance} - Akurat)`
      : "N/A";
    const attendanceStatus = data.attendance_status;
    const statusClass =
      attendanceStatus === "Terlambat" || attendanceStatus === "Pulang Cepat"
        ? "text-red-600 font-bold"
        : "text-green-600 font-bold";
    resultTitle.textContent = `Absensi ${typeDisplay} Berhasil!`;
    resultTitle.className = "result-header text-green-700";
    updateStatus(
      `Absensi ${typeDisplay} Berhasil! Selamat ${data.name}.`,
      "success"
    );
    resultCardBody.innerHTML = `
            <tr><td>Nama</td><td>:</td><td class="font-semibold">${data.name}</td></tr>
            <tr><td>Instansi</td><td>:</td><td>${data.instansi}</td></tr>
            <tr><td>Kategori</td><td>:</td><td>${data.kategori}</td></tr>
            <tr><td>Waktu Absen</td><td>:</td><td>${data.log_time} WIB</td></tr>
            <tr><td>**Status Waktu**</td><td>:</td><td><span class="${statusClass}">${attendanceStatus}</span></td></tr>
            <tr><td>Jarak Vektor</td><td>:</td><td>${distanceDisplay}</td></tr>
            <tr><td>Latensi</td><td>:</td><td>${data.latency}</td></tr>
            ${
              data.image_url
                ? `<tr><td>Foto Log</td><td>:</td><td><a href="${API_BASE_URL}${data.image_url}" target="_blank" class="text-blue-500 hover:text-blue-700">Lihat Foto</a></td></tr>`
                : ""
            }
          `;
  } else if (data.status === "duplicate") {
    resultTitle.textContent = `Absensi ${typeDisplay} Duplikat`;
    resultTitle.className = "result-header text-yellow-700";
    updateStatus(
      `Absensi ${typeDisplay} Anda sudah tercatat hari ini.`,
      "info"
    );
    resultCardBody.innerHTML = `
            <tr><td>Nama</td><td>:</td><td class="font-semibold">${data.name}</td></tr>
            <tr><td>Waktu Log Terakhir</td><td>:</td><td>${data.log_time} WIB</td></tr>
            <tr><td>Pesan</td><td>:</td><td>Anda sudah Absen ${typeDisplay} hari ini.</td></tr>
          `;
  } else if (data.status === "unrecognized") {
    resultTitle.textContent = "Gagal: Wajah Tidak Dikenal";
    resultTitle.className = "result-header text-red-700";
    updateStatus(
      data.message || "Data Wajah Tidak Dikenal. Hubungi Admin.",
      "error"
    );
    resultCardBody.innerHTML = `
            <tr><td>Pesan Sistem</td><td>:</td><td>${
              data.message || "Wajah tidak cocok dengan data terdaftar."
            }</td></tr>
          `;
  } else {
    resultTitle.textContent = "Kesalahan Proses Absensi";
    resultTitle.className = "result-header text-red-700";
    updateStatus(data.message || "Kesalahan server terjadi.", "error");
  }
  if (data.track_id) {
    audioPlayer.src = `${API_BASE_URL}/audio/${data.track_id}`;
    audioPlayer.play().catch((e) => console.error("Gagal memutar audio:", e));
  }
}

window.onload = () => {
  initializeMediaPipe();
  startCamera();
  absenMasukBtn.addEventListener("click", () => startLivenessCheck("IN"));
  absenPulangBtn.addEventListener("click", () => startLivenessCheck("OUT"));
};

window.onbeforeunload = stopCamera;