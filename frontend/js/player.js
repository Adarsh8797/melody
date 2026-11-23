// ============ PLAYER (Audio + YouTube IFrame API) ============
const player = {
  audio: null,
  ytFrame: null,
  currentSongId: null,
  currentVideoId: null,
  isPlaying: false,
  queue: [],
  currentIndex: -1,
  autoPlayNext: true,

  setQueue(songs, startIndex = 0) {
    this.queue = songs || [];
    this.currentIndex = startIndex;
  },

  async play(songId, videoId, title, artist, thumbnail, autoplay = true) {
    this.currentSongId = songId;
    this.currentVideoId = videoId;

    document.getElementById("playerTitle").textContent = title;
    document.getElementById("playerArtist").textContent = artist || "—";
    document.getElementById("playerThumb").src = thumbnail || "";
    document.getElementById("player").classList.remove("hidden");
    document.getElementById("youtubePlayerWrap").innerHTML = "";
    document.getElementById("youtubePlayerWrap").classList.remove("visible");

    // Update favorite button state
    this._updateFavButton();

    // Stop previous audio
    if (this.audio) {
      try {
        this.audio.pause();
        this.audio.src = "";
      } catch (e) {}
      this.audio = null;
    }

    // Destroy previous iframe
    if (this.ytFrame) {
      try { this.ytFrame.src = ""; } catch (e) {}
      this.ytFrame = null;
    }

    this.isPlaying = false;
    this._updatePlayButton(false);

    showToast("Loading...");

    try {
      const res = await fetch(`http://localhost:8000/api/preview/${songId}`);
      const data = await res.json();

      // Priority 1: Audio preview (iTunes/Deezer)
      if (data.preview_url) {
        if (data.title && data.artist) {
          document.getElementById("playerTitle").textContent = data.title;
          document.getElementById("playerArtist").textContent = data.artist;
        }
        if (data.cover) {
          document.getElementById("playerThumb").src = data.cover;
        }

        const audio = new Audio(data.preview_url);
        audio.volume = 1.0;

        audio.onplay = () => this._updatePlayButton(true);
        audio.onpause = () => this._updatePlayButton(false);
        audio.onended = () => {
          this._updatePlayButton(false);
          if (this.autoPlayNext) setTimeout(() => this._tryNext(), 1500);
        };
        audio.onerror = () => {
          console.error("Audio error");
          this._showYouTubeFallback(data.youtube_id);
        };

        this.audio = audio;

        if (autoplay) {
          try {
            await audio.play();
            this._updatePlayButton(true);
            showToast(`Playing 30-second preview (${data.source})`, "success");
          } catch (playErr) {
            console.error("Play rejected:", playErr);
            showToast("Click play button to start", "info");
          }
        }
        return;
      }

      // Priority 2: YouTube embed
      if (data.youtube_embed || data.youtube_id) {
        this._showYouTubeFallback(data.youtube_id);
      } else {
        showToast("No preview available", "error");
        this._tryNext();
      }
    } catch (err) {
      console.error("Preview error:", err);
      showToast("Failed to load preview", "error");
    }
  },

  _showYouTubeFallback(videoId) {
    if (!videoId) {
      showToast("No preview found", "error");
      return;
    }
    const wrap = document.getElementById("youtubePlayerWrap");
    wrap.classList.add("visible");
    wrap.innerHTML = `
      <div class="yt-mini">
        <iframe
          id="ytFrame"
          src="https://www.youtube.com/embed/${videoId}?autoplay=1&enablejsapi=1&origin=${window.location.origin}"
          frameborder="0"
          allow="autoplay; encrypted-media; picture-in-picture"
          allowfullscreen
        ></iframe>
        <div class="yt-mini-footer">
          <span>Playing on YouTube</span>
          <a href="https://www.youtube.com/watch?v=${videoId}" target="_blank">Open ↗</a>
        </div>
      </div>
    `;

    this.ytFrame = document.getElementById("ytFrame");
    this.isPlaying = true;
    this._updatePlayButton(true);
    showToast("Playing full song from YouTube", "success");
  },

  // MAIN TOGGLE - Works for both audio and YouTube iframe
  toggle() {
    // Case 1: Audio element
    if (this.audio) {
      if (this.audio.paused) {
        this.audio.play().catch(e => console.error(e));
        this._updatePlayButton(true);
      } else {
        this.audio.pause();
        this._updatePlayButton(false);
      }
      return;
    }

    // Case 2: YouTube iframe
    if (this.ytFrame && this.ytFrame.contentWindow) {
      if (this.isPlaying) {
        this.ytFrame.contentWindow.postMessage(
          JSON.stringify({ event: "command", func: "pauseVideo", args: [] }),
          "*"
        );
        this._updatePlayButton(false);
      } else {
        this.ytFrame.contentWindow.postMessage(
          JSON.stringify({ event: "command", func: "playVideo", args: [] }),
          "*"
        );
        this._updatePlayButton(true);
      }
      return;
    }

    console.log("Nothing to toggle");
  },

  _tryNext() {
    if (!this.queue || this.queue.length === 0) return;
    this.currentIndex = (this.currentIndex + 1) % this.queue.length;
    const next = this.queue[this.currentIndex];
    if (next) {
      this.play(next.id, next.youtube_id || next.id, next.name, next.artist, next.thumbnail);
    }
  },

  playNext() {
    this._tryNext();
  },

  playPrev() {
    if (!this.queue || this.queue.length === 0) return;
    this.currentIndex = (this.currentIndex - 1 + this.queue.length) % this.queue.length;
    const prev = this.queue[this.currentIndex];
    if (prev) {
      this.play(prev.id, prev.youtube_id || prev.id, prev.name, prev.artist, prev.thumbnail);
    }
  },

  _updatePlayButton(playing) {
    this.isPlaying = playing;
    const btn = document.getElementById("playPauseBtn");
    if (btn) {
      btn.textContent = playing ? "❚❚" : "▶";
    }
  },

  _updateFavButton() {
    const favBtn = document.getElementById("favPlayerBtn");
    if (!favBtn || !this.currentSongId) return;

    // Check favorites from localStorage
    const favs = JSON.parse(localStorage.getItem("melody_favs") || "[]");
    const isFav = favs.includes(this.currentSongId);

    if (isFav) {
      favBtn.classList.add("active");
      favBtn.textContent = "♥";
    } else {
      favBtn.classList.remove("active");
      favBtn.textContent = "♡";
    }
  },

  close() {
    if (this.audio) {
      try {
        this.audio.pause();
        this.audio.src = "";
      } catch (e) {}
      this.audio = null;
    }
    if (this.ytFrame) {
      try { this.ytFrame.src = ""; } catch (e) {}
      this.ytFrame = null;
    }
    this.isPlaying = false;
    document.getElementById("player").classList.add("hidden");
    document.getElementById("youtubePlayerWrap").innerHTML = "";
    document.getElementById("youtubePlayerWrap").classList.remove("visible");
    this.currentSongId = null;
    this.currentVideoId = null;
  },
};