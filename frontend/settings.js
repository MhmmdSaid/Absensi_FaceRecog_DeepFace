// settings.js (Versi Perbaikan)

const API_BASE_URL = "http://127.0.0.1:8000";

// --- DEKLARASI FUNGSI ---
// Kita biarkan fungsi-fungsi ini di luar agar 'window.onload' rapi.
// Kita juga butuh 'deleteFace' ada di global scope agar bisa dibaca 'onclick' di HTML.

// Fungsi updateStatus harus didefinisikan di sini agar bisa diakses global
function updateStatus(message, type = "info") {
  const statusArea = document.getElementById("statusArea");
  if (!statusArea) return; // Pengaman jika elemen tidak ada
  
  const map = {
    success: "status-area bg-green-100 text-green-700",
    error: "status-area bg-red-100 text-red-700",
    warning: "status-area bg-yellow-100 text-yellow-700",
    info: "status-area bg-gray-100 text-gray-700",
  };
  statusArea.className = map[type] || "status-area";
  statusArea.innerHTML = message;
}

async function reloadDB() {
  updateStatus("Melakukan sinkronisasi database...");
  const facesTableBody = document.getElementById("facesTableBody"); // Ambil ulang
  
  try {
    const res = await fetch(`${API_BASE_URL}/reload_db`, { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    updateStatus(
      `Sinkronisasi Berhasil! Total ${data.total_faces} wajah unik terindeks.`,
      "success"
    );
    // Muat ulang tabel setelah sinkronisasi berhasil
    await fetchRegisteredFaces(facesTableBody); // Kirim elemen tabel
  } catch (error) {
    updateStatus(`Gagal sinkronisasi DB: ${error.message}`, "error");
  }
}

async function fetchRegisteredFaces(facesTableBody) {
  if (!facesTableBody) {
    console.error("fetchRegisteredFaces: Elemen facesTableBody tidak ditemukan.");
    return;
  }
  updateStatus("Memuat daftar wajah...");
  facesTableBody.innerHTML = '<tr><td colspan="4">Memuat...</td></tr>';

  try {
    const response = await fetch(`${API_BASE_URL}/list_faces`);
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

    const data = await response.json();
    
    if (data.status === "success" && data.faces) {
      renderTable(data.faces, facesTableBody); // Kirim elemen tabel
      updateStatus(
        `Total ${data.faces.length} wajah unik terdaftar. (Ini adalah daftar intern yang sudah memiliki gambar dataset)`,
        "info"
      );
    } else {
      throw new Error(data.message || "Format data tidak valid");
    }

  } catch (error) {
    console.error("Error:", error);
    updateStatus(`Gagal terhubung ke server API: ${error.message}`, "error");
    facesTableBody.innerHTML =
      '<tr><td colspan="4" class="text-red-500">Gagal memuat data.</td></tr>';
  }
}

async function deleteFace(name) {
  if (
    !confirm(
      `Anda yakin ingin menghapus data wajah untuk ${name} secara permanen? Menghapus akan menghapus semua file gambar dan vektor dari database.`
    )
  )
    return;

  updateStatus(`Menghapus data wajah untuk ${name}...`, "warning");

  try {
    const res = await fetch(`${API_BASE_URL}/delete_face/${name}`, {
      method: "DELETE",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json();
    updateStatus(data.message, data.status === "success" ? "success" : "error");
    
    // Panggil ulang fetchRegisteredFaces
    const facesTableBody = document.getElementById("facesTableBody");
    await fetchRegisteredFaces(facesTableBody); // Muat ulang daftar
    
  } catch (error) {
    updateStatus(`Gagal menghapus wajah: ${error.message}`, "error");
  }
}

function renderTable(faces, facesTableBody) {
  if (!facesTableBody) return;

  if (faces.length === 0) {
     facesTableBody.innerHTML = '<tr><td colspan="4">Belum ada wajah yang terdaftar. Silakan jalankan indexing.</td></tr>';
     return;
  }
  
  facesTableBody.innerHTML = faces
    .map(
      (item, i) => `
          <tr>
            <td>${i + 1}</td>
            <td>${item.name}</td>
            <td>${item.count} Gambar</td>
            <td>
              <button onclick="deleteFace('${item.name}')" class="text-red-500 hover:text-red-700 font-medium text-sm">Hapus Permanen</button>
            </td>
          </tr>`
    )
    .join("");
}

async function runIndexing(indexingButton) { // Terima tombol sebagai argumen
  if (!indexingButton) return;

  if (
    !confirm(
      "Ini akan memindai semua folder data dan menghitung ulang centroid. Proses ini mungkin memakan waktu beberapa menit. Lanjutkan?"
    )
  ) {
    return;
  }

  const originalButtonText = indexingButton.textContent;
  indexingButton.disabled = true;
  indexingButton.textContent = "Sedang Memproses...";
  updateStatus("Mengirim permintaan indexing ke server...", "warning");

  try {
    const res = await fetch(`${API_BASE_URL}/run_indexing`, { method: "POST" });

    if (!res.ok) {
      const errData = await res.json();
      throw new Error(errData.detail || `HTTP Error ${res.status}`);
    }

    const data = await res.json();

    updateStatus(
      data.message +
        " Silakan tunggu beberapa menit, lalu klik 'Sinkronisasi Database' untuk memuat hasil baru.",
      "success"
    );
  } catch (error) {
    console.error("Error starting indexing:", error);
    updateStatus(`Gagal memulai indexing: ${error.message}`, "error");
  } finally {
    indexingButton.disabled = false;
    indexingButton.textContent = originalButtonText;
  }
}

// --- EKSEKUSI UTAMA (SETELAH HALAMAN SIAP) ---
window.onload = () => {
  // 1. Ambil semua elemen penting SEKARANG (setelah HTML ada)
  const facesTableBody = document.getElementById("facesTableBody");
  const reloadButton = document.getElementById("reloadButton");
  const indexingButton = document.getElementById("startIndexingButton");

  // 2. Cek apakah elemen ada
  if (!facesTableBody || !reloadButton || !indexingButton) {
      console.error("FATAL: Satu atau lebih elemen UI penting tidak ditemukan. Cek ID HTML Anda.");
      updateStatus("Error Kritis: Elemen UI halaman tidak ditemukan.", "error");
      return;
  }

  // 3. Pasang Event Listeners
  reloadButton.addEventListener("click", reloadDB);
  
  // Kirim elemen tombol ke fungsi runIndexing saat di-klik
  indexingButton.addEventListener("click", () => runIndexing(indexingButton));

  // 4. Muat data awal
  fetchRegisteredFaces(facesTableBody);
};

// 5. Pastikan deleteFace() bisa diakses secara global oleh 'onclick'
// (Ini diperlukan karena kita memanggilnya dari string HTML)
window.deleteFace = deleteFace;