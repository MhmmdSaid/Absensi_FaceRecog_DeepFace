const API_BASE_URL = "http://127.0.0.1:8000";
const statusArea = document.getElementById("statusArea");
const attendanceTableBody = document.getElementById("attendanceTableBody");
const refreshDataBtn = document.getElementById("refreshDataBtn");
const photoUrlInfo = document.getElementById("photoUrlInfo");

function updateStatus(message, type = "info") {
  const map = {
    success: "status-area bg-green-100 text-green-700",
    error: "status-area bg-red-100 text-red-700",
    loading: "status-area bg-blue-100 text-blue-700",
    info: "status-area bg-gray-100 text-gray-700",
  };
  statusArea.className = map[type] || "status-area";
  statusArea.innerHTML = message;
}

async function fetchAttendanceData() {
  updateStatus("Memuat data absensi terbaru...", "loading");
  attendanceTableBody.innerHTML = '<tr><td colspan="8">Memuat...</td></tr>';

  photoUrlInfo.classList.add("hidden");
  photoUrlInfo.innerHTML = '';

  try {
    const response = await fetch(`${API_BASE_URL}/attendance/today`);
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

    const data = await response.json();
    renderTable(data);

    if (data.length > 0) {
      updateStatus(`Berhasil memuat ${data.length} entri absensi hari ini.`, "success");

      const firstEntryUrl = data[0].image_path;
      if (firstEntryUrl) {
        photoUrlInfo.innerHTML = `URL Foto (Contoh): <a href="${firstEntryUrl}" target="_blank">${API_BASE_URL}${firstEntryUrl}</a>`;
        photoUrlInfo.classList.remove("hidden");
      }
    } else {
      updateStatus("Belum ada data absensi yang tercatat hari ini.", "info");
    }
  } catch (error) {
    console.error("Error:", error);
    updateStatus(`Gagal terhubung ke server API atau memuat data: ${error.message}`, "error");
    attendanceTableBody.innerHTML = '<tr><td colspan="8" class="text-red-500">Gagal memuat data.</td></tr>';
  }
}

function renderTable(attendanceData) {
  if (attendanceData.length === 0) {
    attendanceTableBody.innerHTML = '<tr><td colspan="8" class="text-center text-gray-500">Belum ada absensi hari ini.</td></tr>';
    return;
  }

  attendanceTableBody.innerHTML = attendanceData
    .map((item, i) => {
      // --- LOGIKA BARU UNTUK WARNA STATUS ---
      const statusText = item.status; // Contoh: "MASUK (Terlambat)"
      let statusClass = "text-gray-500";

      // Logika untuk menandai keterlambatan/pulang cepat
      if (statusText.includes("Terlambat") || statusText.includes("Cepat")) {
        statusClass = "text-red-600"; // Merah untuk masalah waktu
      } else if (statusText.includes("Tepat Waktu")) {
        statusClass = "text-green-600"; // Hijau untuk tepat waktu
      }
      // -------------------------------------

      const timeDisplay = item.timestamp;
      const photoUrl = item.image_path ? `${API_BASE_URL}${item.image_path}` : "#";

      return `
              <tr>
                <td>${i + 1}</td>
                <td>${item.name}</td>
                <td>${item.instansi}</td>
                <td>${item.kategori}</td>
                <td class="${statusClass} font-semibold">${statusText}</td>
                <td>${timeDisplay} WIB</td>
                <td>N/A</td>
                <td>
                  ${
                    item.image_path
                      ? `<a href="${photoUrl}" target="_blank" class="text-blue-500 hover:text-blue-700">Lihat</a>`
                      : "N/A"
                  }
                </td>
              </tr>`;
    })
    .join("");
}

window.onload = () => {
  fetchAttendanceData();
  refreshDataBtn.addEventListener("click", fetchAttendanceData);
};