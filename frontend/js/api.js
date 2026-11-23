// ============ API CONFIG ============
const API_BASE = "http://localhost:8000";

// ============ API CALLS ============
const api = {
  async getSongs() {
    const res = await fetch(`${API_BASE}/api/songs`);
    return res.json();
  },

  async search(q) {
    const res = await fetch(`${API_BASE}/api/search?q=${encodeURIComponent(q)}`);
    return res.json();
  },

  async ingest(songName) {
    const res = await fetch(`${API_BASE}/api/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ song_name: songName }),
    });
    return res.json();
  },

  async recommend(songName, topK = 8) {
    const res = await fetch(`${API_BASE}/api/recommend`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ song_name: songName, top_k: topK }),
    });
    return res.json();
  },

  async getSong(id) {
    const res = await fetch(`${API_BASE}/api/song/${id}`);
    return res.json();
  },
};