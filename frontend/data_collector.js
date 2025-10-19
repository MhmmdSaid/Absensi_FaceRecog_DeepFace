const API_BASE = "http://127.0.0.1:8000";
const video = document.getElementById("video");
const canvas = document.getElementById("canvas");
const captureBtn = document.getElementById("captureBtn");
const finishBtn = document.getElementById("finishBtn");
const personName = document.getElementById("personName");
const statusArea = document.getElementById("statusArea");
const TARGET_COUNT = 10;
let capturedCount = 0;
let stream = null;

function updateStatus(msg, type = "info") {
  const map = {
    success: "status-area bg-green-100 text-green-700",
    error: "status-area bg-red-100 text-red-700",
    warning: "status-area bg-yellow-100 text-yellow-700",
    info: "status-area bg-gray-100 text-gray-700",
  };
  statusArea.className = map[type] || "status-area";
  statusArea.innerHTML = msg;
}

async function initCamera() {
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: true });
    video.srcObject = stream;
    captureBtn.disabled = false;
    updateStatus("Kamera siap digunakan.", "info");
  } catch (err) {
    updateStatus("Gagal mengakses kamera: " + err.message, "error");
  }
}

async function uploadImage(blob) {
  const formData = new FormData();
  formData.append("name", personName.value);
  formData.append("file", blob, `${capturedCount + 1}.jpg`);

  const res = await fetch(`${API_BASE}/upload_dataset`, {
    method: "POST",
    body: formData,
  });

  return await res.json();
}

async function captureFrame() {
  if (!personName.value.trim()) {
    updateStatus("Masukkan nama terlebih dahulu!", "warning");
    return;
  }

  const ctx = canvas.getContext("2d");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

  canvas.toBlob(async (blob) => {
    const res = await uploadImage(blob);
    capturedCount++;
    updateStatus(
      `Gambar ke-${capturedCount} tersimpan (${res.message})`,
      "success"
    );

    if (capturedCount >= TARGET_COUNT) {
      updateStatus("Pengambilan selesai! Klik tombol selesai.", "success");
      captureBtn.disabled = true;
      finishBtn.disabled = false;
    }
  }, "image/jpeg", 0.9);
}

captureBtn.addEventListener("click", captureFrame);
finishBtn.addEventListener("click", () => {
  alert(
    `Selesai! Total ${capturedCount} gambar diambil untuk ${personName.value}.`
  );
  window.location.href = "main.html";
});

window.onload = initCamera;