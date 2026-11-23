// ============ STATE ============
let allSongs = [];
let currentRecommendations = [];
let lastRecs = [];
let currentSliders = { energy: 50, dance: 50, mood: 50, texture: 50 };
let favorites = JSON.parse(localStorage.getItem("melody_favs") || "[]");
let searchDebounce = null;

// ============ DOM ============
const songGrid = document.getElementById("songGrid");
const recsSection = document.getElementById("recsSection");
const recsGrid = document.getElementById("recsGrid");
const recsTitle = document.getElementById("recsTitle");
const recsSubtitle = document.getElementById("recsSubtitle");
const songCount = document.getElementById("songCount");
const favSection = document.getElementById("favSection");
const favGrid = document.getElementById("favGrid");
const favCount = document.getElementById("favCount");

// ============ INIT ============
document.addEventListener("DOMContentLoaded", () => {
  loadSongs();
  renderFavorites();
  setupEventListeners();
});

async function loadSongs() {
  try {
    const data = await api.getSongs();
    allSongs = data.songs || [];
    songCount.textContent = `${allSongs.length} songs`;
    renderSongs(allSongs, songGrid);
  } catch (err) {
    console.error(err);
    songGrid.innerHTML = `<div class="empty">❌ Failed to load songs. Is the backend running?</div>`;
  }
}

// ============ FAVORITES ============
function isFavorite(songId) {
  return favorites.includes(songId);
}

function toggleFavorite(songId) {
  if (isFavorite(songId)) {
    favorites = favorites.filter(id => id !== songId);
    showToast("Removed from favorites", "info");
  } else {
    favorites.push(songId);
    showToast("Added to favorites ❤️", "success");
  }
  localStorage.setItem("melody_favs", JSON.stringify(favorites));
  renderFavorites();
  refreshHeartIcons();
}

function refreshHeartIcons() {
  document.querySelectorAll(".song-card").forEach(card => {
    const id = card.dataset.id;
    const heartBtn = card.querySelector(".heart-btn");
    if (heartBtn) {
      if (isFavorite(id)) {
        heartBtn.classList.add("active");
        heartBtn.textContent = "♥";
      } else {
        heartBtn.classList.remove("active");
        heartBtn.textContent = "♡";
      }
    }
  });
  // Also update player fav button
  const playerFavBtn = document.getElementById("favPlayerBtn");
  if (playerFavBtn && player.currentSongId) {
    if (isFavorite(player.currentSongId)) {
      playerFavBtn.classList.add("active");
      playerFavBtn.textContent = "♥";
    } else {
      playerFavBtn.classList.remove("active");
      playerFavBtn.textContent = "♡";
    }
  }
}

function renderFavorites() {
  if (favorites.length === 0) {
    favSection.classList.add("hidden");
    return;
  }
  const favSongs = allSongs.filter(s => favorites.includes(s.id));
  if (favSongs.length === 0) {
    favSection.classList.add("hidden");
    return;
  }
  favSection.classList.remove("hidden");
  favCount.textContent = `${favSongs.length} songs`;
  renderSongs(favSongs, favGrid);
}

// ============ RENDER SONGS ============
function renderSongs(songs, container, showMatch = false) {
  if (!songs || songs.length === 0) {
    container.innerHTML = `<div class="empty">No songs found.</div>`;
    return;
  }

  container.innerHTML = songs
    .map((song, idx) => {
      const matchBadge = showMatch && song.score
        ? `<div class="match-badge">${Math.round(song.score * 100)}% match</div>`
        : "";

      const matchDetails = showMatch && song.match_melody
        ? `
          <div class="match-details">
            <span class="match-detail">🎼 <strong>${Math.round(song.match_melody * 100)}%</strong></span>
            <span class="match-detail">🥁 <strong>${Math.round(song.match_rhythm * 100)}%</strong></span>
            <span class="match-detail">🎸 <strong>${Math.round(song.match_timbre * 100)}%</strong></span>
          </div>`
        : "";

      const thumb = song.thumbnail
        ? `<img src="${song.thumbnail}" alt="" onerror="this.style.display='none'" />`
        : "";

      const favClass = isFavorite(song.id) ? "active" : "";
      const favIcon = isFavorite(song.id) ? "♥" : "♡";

      return `
        <div class="song-card" data-id="${song.id}" data-name="${escapeHtml(song.name)}" style="animation-delay: ${idx * 40}ms">
          <div class="song-thumb">
            ${thumb}
            <div class="play-overlay">
              <div class="play-btn-circle"></div>
            </div>
            <button class="heart-btn ${favClass}" data-fav-id="${song.id}" title="Favorite">${favIcon}</button>
          </div>
          ${matchBadge}
          <div class="song-name">${escapeHtml(song.name)}</div>
          <div class="song-meta">${escapeHtml(song.artist || "YouTube")}</div>
          ${matchDetails}
        </div>
      `;
    })
    .join("");

  // Attach click handlers
  container.querySelectorAll(".song-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      if (e.target.classList.contains("heart-btn")) return;
      handleSongClick(card);
    });
  });

  container.querySelectorAll(".heart-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleFavorite(btn.dataset.favId);
    });
  });
}

// ============ SONG CLICK ============
async function handleSongClick(card) {
  const songId = card.dataset.id;
  const songName = card.dataset.name;

  let song = allSongs.find((s) => s.id === songId);
  if (!song) song = currentRecommendations.find((s) => s.id === songId);
  if (!song) song = { id: songId, name: songName, youtube_id: songId, artist: "", thumbnail: "" };

  document.querySelectorAll(".song-card.playing").forEach(c => c.classList.remove("playing"));
  card.classList.add("playing");

  const queue = [...allSongs, ...currentRecommendations];
  const startIdx = queue.findIndex(s => s.id === songId);
  player.setQueue(queue, startIdx >= 0 ? startIdx : 0);

  player.play(song.id, song.youtube_id || song.id, song.name, song.artist, song.thumbnail);
  refreshHeartIcons();

  showToast("Finding similar songs...");
  try {
    const data = await api.recommend(songName, 6);
    currentRecommendations = data.recommendations || [];
    lastRecs = [...currentRecommendations];

    applyMoodFilter();

    recsTitle.textContent = `✨ Similar to "${truncate(songName, 40)}"`;
    recsSubtitle.textContent = `${currentRecommendations.length} songs · Melody 40% · Rhythm 30% · Timbre 30%`;
    recsSection.classList.remove("hidden");
    recsSection.scrollIntoView({ behavior: "smooth", block: "start" });

    showToast(`${currentRecommendations.length} similar songs found`, "success");
  } catch (err) {
    console.error("Recommend error:", err);
    showToast("Failed to get recommendations", "error");
  }
}

// ============ SEARCH ============
async function handleSearch() {
  const q = document.getElementById("searchInput").value.trim();
  if (!q) {
    loadSongs();
    return;
  }

  const btn = document.getElementById("searchBtn");
  const btnText = document.getElementById("searchBtnText");
  btn.disabled = true;
  btn.classList.add("loading");
  btnText.textContent = "Searching...";

  try {
    const local = await api.search(q);
    if (local.songs && local.songs.length > 0) {
      songCount.textContent = `${local.songs.length} results`;
      renderSongs(local.songs, songGrid);
      showToast(`Found ${local.songs.length} songs`, "success");
      return;
    }

    showToast("New song! Adding to library (2-3 min)...");
    btnText.textContent = "Adding...";
    const result = await api.ingest(q);

    if (result.success) {
      showToast("Song added! Loading...", "success");
      await loadSongs();
    } else {
      showToast("Failed to add song", "error");
    }
  } catch (err) {
    console.error(err);
    showToast("Search failed. Please try again.", "error");
  } finally {
    btn.disabled = false;
    btn.classList.remove("loading");
    btnText.textContent = "Search";
  }
}

// ============ MOOD SLIDERS ============
function applyMoodFilter() {
  if (!lastRecs || lastRecs.length === 0) return;

  const { energy, dance, mood, texture } = currentSliders;

  const energyW = 0.2 + (energy / 100) * 0.6;
  const danceW = 0.2 + (dance / 100) * 0.6;
  const moodW = 0.2 + (mood / 100) * 0.6;
  const textureW = 0.2 + (texture / 100) * 0.6;

  const totalMelodyW = moodW;
  const totalRhythmW = (energyW + danceW) / 2;
  const totalTimbreW = textureW;

  const reranked = lastRecs.map((song) => {
    const m = song.match_melody || 0;
    const r = song.match_rhythm || 0;
    const t = song.match_timbre || 0;
    const newScore = m * totalMelodyW + r * totalRhythmW + t * totalTimbreW;
    return { ...song, score: newScore };
  });

  reranked.sort((a, b) => b.score - a.score);
  currentRecommendations = reranked;

  showMoodStatus();
  renderSongs(reranked, recsGrid, true);
}

function showMoodStatus() {
  const el = document.getElementById("moodStatus");
  const text = document.getElementById("moodStatusText");
  const active = Object.entries(currentSliders)
    .filter(([_, v]) => v !== 50)
    .map(([k, v]) => `${k} ${v > 50 ? "↑" : "↓"}`);

  if (active.length === 0) {
    el.classList.add("hidden");
    return;
  }

  text.textContent = `Re-ranking by: ${active.join(" · ")}`;
  el.classList.remove("hidden");

  clearTimeout(window._moodTimer);
  window._moodTimer = setTimeout(() => {
    el.classList.add("hidden");
  }, 2500);
}

// ============ EVENT LISTENERS ============
function setupEventListeners() {
  // Search
  document.getElementById("searchBtn").addEventListener("click", handleSearch);
  document.getElementById("searchInput").addEventListener("keypress", (e) => {
    if (e.key === "Enter") handleSearch();
  });

  // Clear search
  document.getElementById("clearSearch").addEventListener("click", () => {
    document.getElementById("searchInput").value = "";
    document.getElementById("clearSearch").classList.add("hidden");
    loadSongs();
  });

  document.getElementById("searchInput").addEventListener("input", (e) => {
    const clearBtn = document.getElementById("clearSearch");
    if (e.target.value.length > 0) clearBtn.classList.remove("hidden");
    else clearBtn.classList.add("hidden");
  });

  // Hint chips
  document.querySelectorAll(".hint-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const q = chip.dataset.query;
      document.getElementById("searchInput").value = q;
      document.getElementById("clearSearch").classList.remove("hidden");
      handleSearch();
    });
  });

  // About button scroll
  document.getElementById("aboutBtn").addEventListener("click", () => {
    document.getElementById("aboutSection").scrollIntoView({ behavior: "smooth" });
  });

  // Close recs
  document.getElementById("closeRecs").addEventListener("click", () => {
    recsSection.classList.add("hidden");
  });

  // Player controls
  document.getElementById("closePlayer").addEventListener("click", () => player.close());
  document.getElementById("playPauseBtn").addEventListener("click", () => player.toggle());
  document.getElementById("prevBtn").addEventListener("click", () => player.playPrev());
  document.getElementById("nextBtn").addEventListener("click", () => player.playNext());

  // Player favorite button
  document.getElementById("favPlayerBtn").addEventListener("click", () => {
    if (player.currentSongId) {
      toggleFavorite(player.currentSongId);
    }
  });

  // Sliders
  ["energy", "dance", "mood", "texture"].forEach((name) => {
    const slider = document.getElementById(`${name}Slider`);
    const valEl = document.getElementById(`${name}Val`);

    slider.addEventListener("input", () => {
      const val = parseInt(slider.value);
      currentSliders[name] = val;
      valEl.textContent = val;

      valEl.classList.add("changed");
      clearTimeout(valEl._t);
      valEl._t = setTimeout(() => valEl.classList.remove("changed"), 300);

      clearTimeout(searchDebounce);
      searchDebounce = setTimeout(() => applyMoodFilter(), 100);
    });
  });

  document.getElementById("resetMood").addEventListener("click", () => {
    ["energy", "dance", "mood", "texture"].forEach((name) => {
      document.getElementById(`${name}Slider`).value = 50;
      document.getElementById(`${name}Val`).textContent = "50";
      currentSliders[name] = 50;
    });
    applyMoodFilter();
    showToast("Sliders reset to neutral", "success");
  });
}

// ============ HELPERS ============
function escapeHtml(str) {
  if (!str) return "";
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function truncate(str, n) {
  return str.length > n ? str.slice(0, n) + "..." : str;
}

function showToast(msg, type = "info") {
  const container = document.getElementById("toastContainer");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = msg;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.animation = "toastOut 0.3s ease-out forwards";
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}