const API_BASE_URL = "http://127.0.0.1:8000";
const statusArea = document.getElementById("statusArea");
const facesTableBody = document.getElementById("facesTableBody");
const reloadButton = document.getElementById("reloadButton");

function updateStatus(message, type = "info") {
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
  try {
    const res = await fetch(`${API_BASE_URL}/reload_db`, { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    updateStatus(
      `Sinkronisasi Berhasil! Total ${data.total_faces} wajah unik terindeks.`,
      "success"
    );
    fetchRegisteredFaces();
  } catch (error) {
    updateStatus(`Gagal sinkronisasi DB: ${error.message}`, "error");
  }
}

async function fetchRegisteredFaces() {
  updateStatus("Memuat daftar wajah...");
  facesTableBody.innerHTML = '<tr><td colspan="4">Memuat...</td></tr>';

  try {
    const response = await fetch(`${API_BASE_URL}/list_faces`);
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

    const data = await response.json();
    renderTable(data.faces);
    updateStatus(
      `Total ${data.faces.length} wajah unik terdaftar. (Ini adalah daftar intern yang sudah memiliki gambar dataset)`,
      "info"
    );
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
    fetchRegisteredFaces(); // Muat ulang daftar
  } catch (error) {
    updateStatus(`Gagal menghapus wajah: ${error.message}`, "error");
  }
}

function renderTable(faces) {
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

window.onload = () => {
  fetchRegisteredFaces();
  reloadButton.addEventListener("click", reloadDB);
};