import os
import platform
import sys
import time
import tempfile
import subprocess

# ============ TORCH DLL FIX (Windows) ============
if platform.system() == "Windows":
    try:
        from importlib.util import find_spec
        spec = find_spec("torch")
        if spec and spec.origin:
            torch_lib_dir = os.path.join(os.path.dirname(spec.origin), "lib")
            if os.path.exists(torch_lib_dir):
                os.add_dll_directory(torch_lib_dir)
                print(f"✅ Added torch DLL directory: {torch_lib_dir}")
    except Exception as e:
        print(f"⚠️ Torch DLL fix failed: {e}")

import yt_dlp
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchaudio
import soundfile as sf
import numpy as np
import requests
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from dotenv import load_dotenv
from supabase import create_client, Client
from transformers import AutoModel, Wav2Vec2FeatureExtractor

# ============ SETUP ============
load_dotenv()

DEVICE = "cpu"
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

# ⭐ HTTP/1.1 client for Supabase (fixes connection pool "Server disconnected" errors)
_http_client = httpx.Client(
    http2=False,
    timeout=httpx.Timeout(30.0, connect=10.0),
    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# Override HTTP client inside Supabase
try:
    supabase.postgrest.session = _http_client
    print("✅ Supabase HTTP/1.1 client set")
except Exception as e:
    print(f"⚠️ Could not override HTTP client: {e}")


app = FastAPI(title="Melody API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ SUPABASE RETRY HELPER ============
def supabase_retry(fn, max_retries=3, delay=3):
    """Retry Supabase with longer delays (respects rate limits)"""
    last_err = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            if any(x in err_str for x in ["disconnect", "timeout", "connection", "protocol", "remote", "pool"]):
                wait = delay * (attempt + 1)
                print(f"⚠️ Supabase retry {attempt+1}/{max_retries} in {wait}s...")
                time.sleep(wait)
                continue
            else:
                raise
    raise last_err


# ============ LOAD MODELS ============
print("📥 Loading MERT backbone...")
MERT_ID = "m-a-p/MERT-v1-330M"

processor = Wav2Vec2FeatureExtractor.from_pretrained(
    MERT_ID, trust_remote_code=True
)
mert = AutoModel.from_pretrained(
    MERT_ID, trust_remote_code=True
).to(DEVICE).eval()
print("✅ MERT loaded")


class ProjectionHead(nn.Module):
    def __init__(self, in_dim=5120, hidden_dim=512, out_dim=128):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.ReLU(inplace=True),
            nn.Linear(hidden_dim, out_dim, bias=False),
        )

    def forward(self, x):
        return F.normalize(self.net(x), dim=-1)


def load_head(path):
    ckpt = torch.load(path, map_location=DEVICE, weights_only=True)
    head = ProjectionHead(ckpt["in_dim"], ckpt["hidden_dim"], ckpt["out_dim"])
    head.load_state_dict(ckpt["state_dict"])
    return head.to(DEVICE).eval()


print("📥 Loading MERIT heads...")
head_mel = load_head("models/head_mel/best_head.pt")
head_rhy = load_head("models/head_rhy/best_head.pt")
head_tim = load_head("models/head_tim/best_head.pt")
print("✅ MERIT heads loaded")


# ============ YOUTUBE HELPERS ============
def search_youtube(query: str):
    """Search YouTube — only returns videos that ALLOW embedding"""
    cached = supabase_retry(
        lambda: supabase.table("youtube_cache").select("*").eq("song_name", query).execute()
    )
    if cached.data:
        return cached.data[0]

    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": 10,
        "videoEmbeddable": "true",
        "videoSyndicated": "true",
        "key": YOUTUBE_API_KEY,
    }
    r = requests.get(url, params=params).json()

    if not r.get("items"):
        raise HTTPException(404, f"No embeddable YouTube video for: {query}")

    # Prefer Topic channels (auto-generated, always embeddable)
    items = r["items"]
    best = None
    for item in items:
        channel = item["snippet"]["channelTitle"]
        if "Topic" in channel:
            best = item
            break
    if best is None:
        best = items[0]

    item = best
    result = {
        "song_name": query,
        "video_id": item["id"]["videoId"],
        "title": item["snippet"]["title"],
        "thumbnail": item["snippet"]["thumbnails"]["medium"]["url"],
        "channel": item["snippet"]["channelTitle"],
    }

    supabase_retry(lambda: supabase.table("youtube_cache").upsert(result).execute())
    return result


# ============ DEEZER PREVIEW ============
def search_deezer(query: str):
    try:
        r = requests.get(
            "https://api.deezer.com/search",
            params={"q": query, "limit": 10},
            timeout=10,
        ).json()

        if r.get("data"):
            tracks = [t for t in r["data"] if t.get("preview")]
            if tracks:
                track = tracks[0]
                return {
                    "preview_url": track["preview"],
                    "title": track.get("title"),
                    "artist": track["artist"]["name"],
                    "cover": track["album"]["cover_medium"],
                }
    except Exception as e:
        print(f"❌ Deezer error: {e}")
    return None


# ============ ITUNES PREVIEW ============
def search_itunes(query: str):
    try:
        r = requests.get(
            "https://itunes.apple.com/search",
            params={
                "term": query,
                "media": "music",
                "entity": "song",
                "limit": 5,
            },
            timeout=10,
        ).json()

        if r.get("results"):
            for track in r["results"]:
                if track.get("previewUrl"):
                    return {
                        "preview_url": track["previewUrl"],
                        "title": track.get("trackName"),
                        "artist": track.get("artistName"),
                        "cover": track.get("artworkUrl100", "").replace("100x100", "300x300"),
                    }
    except Exception as e:
        print(f"❌ iTunes error: {e}")
    return None


# ============ AUDIO DOWNLOAD ============
CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)

AUDIO_CACHE_DIR = "cache/audio"
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)


def download_audio(video_id: str) -> str:
    output_path = f"{CACHE_DIR}/{video_id}.wav"
    if os.path.exists(output_path):
        return output_path

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": f"{CACHE_DIR}/{video_id}.%(ext)s",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
        }],
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

    return output_path


# ============ EMBEDDING EXTRACTION ============
def get_embedding(audio_path: str):
    data, sr = sf.read(audio_path)
    waveform = torch.from_numpy(data).float()

    if waveform.dim() == 1:
        waveform = waveform.unsqueeze(0)
    else:
        waveform = waveform.T
        waveform = waveform.mean(dim=0, keepdim=True)

    if sr != 24000:
        waveform = torchaudio.functional.resample(waveform, sr, 24000)

    waveform = waveform[:, :24000 * 30]

    inputs = processor(
        waveform.squeeze(0).numpy(),
        sampling_rate=24000,
        return_tensors="pt",
    ).to(DEVICE)

    with torch.no_grad():
        try:
            outputs = mert(**inputs, output_hidden_states=True)
            hidden_states = getattr(outputs, "hidden_states", None)
        except Exception:
            hidden_states = None

        if hidden_states is not None:
            last5 = hidden_states[-5:]
            pooled = [h.mean(dim=1) for h in last5]
            hidden = torch.cat(pooled, dim=-1)
        else:
            print("⚠️  Using fallback pooling")
            outputs = mert(**inputs)
            last = getattr(outputs, "last_hidden_state", None)
            if last is None:
                last = outputs[0]

            pooled = [
                last.mean(dim=1),
                last.max(dim=1).values,
                last.min(dim=1).values,
                last[:, :1, :].squeeze(1),
                last[:, -1:, :].squeeze(1),
            ]
            hidden = torch.cat(pooled, dim=-1)

        hidden = hidden.detach().float()

        melody = head_mel(hidden).squeeze(0).detach().cpu().numpy().tolist()
        rhythm = head_rhy(hidden).squeeze(0).detach().cpu().numpy().tolist()
        timbre = head_tim(hidden).squeeze(0).detach().cpu().numpy().tolist()

    return melody, rhythm, timbre


# ============ VECTOR PARSER ============
def parse_vector(v):
    if isinstance(v, str):
        v = v.strip("[]").split(",")
        return np.array([float(x) for x in v], dtype=np.float32)
    return np.array(v, dtype=np.float32)


# ============ REQUEST MODELS ============
class IngestRequest(BaseModel):
    song_name: str


class RecommendRequest(BaseModel):
    song_name: str
    top_k: int = 10


# ============ ROUTES ============
@app.get("/")
def root():
    return {"status": "ok", "app": "Melody", "device": DEVICE}


@app.get("/api/proxy_audio")
def proxy_audio(url: str):
    """Download audio, convert to MP3, serve (100% browser compatible)"""
    import hashlib

    try:
        cache_key = hashlib.md5(url.encode()).hexdigest()
        cached_file = f"{AUDIO_CACHE_DIR}/{cache_key}.mp3"

        if os.path.exists(cached_file):
            print(f"✅ Cache hit: {cache_key}")
            with open(cached_file, "rb") as f:
                return Response(content=f.read(), media_type="audio/mpeg")

        print(f"📥 Proxy download: {url[:80]}...")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "*/*",
        }
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()

        ext = ".mp3" if ".mp3" in url.lower() else ".m4a"
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as f:
            f.write(r.content)
            temp_input = f.name

        if ext == ".mp3":
            with open(temp_input, "rb") as f:
                audio_data = f.read()
            with open(cached_file, "wb") as f:
                f.write(audio_data)
            os.unlink(temp_input)
            print(f"✅ Served MP3 directly ({len(audio_data)} bytes)")
            return Response(content=audio_data, media_type="audio/mpeg")

        temp_output = temp_input.replace(".m4a", ".mp3")
        print(f"🎵 Converting to MP3 with FFmpeg...")

        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", temp_input, "-codec:a", "libmp3lame",
                 "-b:a", "128k", "-f", "mp3", temp_output],
                capture_output=True,
                timeout=30,
            )

            if result.returncode != 0:
                print(f"❌ FFmpeg error: {result.stderr.decode()[:300]}")
                with open(temp_input, "rb") as f:
                    audio_data = f.read()
                os.unlink(temp_input)
                return Response(content=audio_data, media_type="audio/mp4")

            with open(temp_output, "rb") as f:
                mp3_data = f.read()

            with open(cached_file, "wb") as f:
                f.write(mp3_data)

            try:
                os.unlink(temp_input)
                os.unlink(temp_output)
            except:
                pass

            print(f"✅ Converted to MP3 ({len(mp3_data)} bytes)")
            return Response(content=mp3_data, media_type="audio/mpeg")

        except FileNotFoundError:
            print(f"❌ FFmpeg not found!")
            with open(temp_input, "rb") as f:
                audio_data = f.read()
            os.unlink(temp_input)
            return Response(content=audio_data, media_type="audio/mp4")

        except subprocess.TimeoutExpired:
            raise HTTPException(500, "Audio conversion timed out")

    except Exception as e:
        print(f"❌ Proxy error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Proxy error: {str(e)}")


@app.post("/api/ingest")
def ingest_song(req: IngestRequest):
    try:
        print(f"🔍 Searching: {req.song_name}")
        yt = search_youtube(req.song_name)
        video_id = yt["video_id"]
        print(f"✅ Found: {yt['title']} ({video_id})")

        print(f"📥 Downloading audio...")
        audio_path = download_audio(video_id)
        print(f"✅ Downloaded: {audio_path}")

        print(f"🧠 Extracting embeddings (this may take 30-60s)...")
        melody, rhythm, timbre = get_embedding(audio_path)
        print(f"✅ Embeddings extracted")

        song_id = video_id

        # Small delay to avoid connection pool exhaustion
        time.sleep(0.5)

        # Save song with retry
        supabase_retry(lambda: supabase.table("songs").upsert({
            "id": song_id,
            "name": yt["title"],
            "artist": req.song_name.split("-")[-1].strip() if "-" in req.song_name else "",
            "youtube_id": video_id,
            "thumbnail": yt["thumbnail"],
        }).execute())

        # Small delay between two saves
        time.sleep(0.5)

        # Save embedding with retry
        supabase_retry(lambda: supabase.table("embeddings").upsert({
            "song_id": song_id,
            "melody": melody,
            "rhythm": rhythm,
            "timbre": timbre,
        }).execute())

        print(f"💾 Saved to Supabase")

        return {
            "success": True,
            "song_id": song_id,
            "title": yt["title"],
            "video_id": video_id,
            "thumbnail": yt["thumbnail"],
        }
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, str(e))


@app.post("/api/recommend")
def recommend(req: RecommendRequest):
    try:
        source = supabase_retry(
            lambda: supabase.table("songs").select("*").ilike(
                "name", f"%{req.song_name}%"
            ).limit(1).execute()
        )

        if not source.data:
            print(f"⚠️  Song not in DB, ingesting first...")
            ingest_result = ingest_song(IngestRequest(song_name=req.song_name))
            source_id = ingest_result["song_id"]
            source_data = supabase_retry(
                lambda: supabase.table("songs").select("*").eq("id", source_id).execute()
            ).data[0]
        else:
            source_id = source.data[0]["id"]
            source_data = source.data[0]

        source_emb_result = supabase_retry(
            lambda: supabase.table("embeddings").select("*").eq("song_id", source_id).execute()
        )

        if not source_emb_result.data:
            raise HTTPException(404, "Source embedding not found")

        source_emb = source_emb_result.data[0]
        all_embs = supabase_retry(
            lambda: supabase.table("embeddings").select("*").execute()
        ).data

        if len(all_embs) < 2:
            return {
                "source": source_data,
                "recommendations": [],
                "message": "Need at least 2 songs. Ingest more songs first.",
            }

        src_mel = parse_vector(source_emb["melody"])
        src_rhy = parse_vector(source_emb["rhythm"])
        src_tim = parse_vector(source_emb["timbre"])

        scores = []
        for emb in all_embs:
            if emb["song_id"] == source_id:
                continue
            em = parse_vector(emb["melody"])
            er = parse_vector(emb["rhythm"])
            et = parse_vector(emb["timbre"])
            m = float(np.dot(src_mel, em))
            r = float(np.dot(src_rhy, er))
            t = float(np.dot(src_tim, et))
            score = 0.4 * m + 0.3 * r + 0.3 * t
            scores.append({
                "song_id": emb["song_id"],
                "score": score,
                "melody_score": m,
                "rhythm_score": r,
                "timbre_score": t,
            })

        scores.sort(key=lambda x: -x["score"])
        top = scores[:req.top_k]

        song_ids = [s["song_id"] for s in top]
        songs_data = supabase_retry(
            lambda: supabase.table("songs").select("*").in_("id", song_ids).execute()
        ).data

        song_map = {s["id"]: s for s in songs_data}
        results = []
        for s in top:
            song = song_map.get(s["song_id"], {})
            results.append({
                **song,
                "score": round(s["score"], 4),
                "match_melody": round(s["melody_score"], 4),
                "match_rhythm": round(s["rhythm_score"], 4),
                "match_timbre": round(s["timbre_score"], 4),
            })

        return {
            "source": source_data,
            "recommendations": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, str(e))


@app.get("/api/search")
def search(q: str, limit: int = 20):
    result = supabase_retry(
        lambda: supabase.table("songs").select("*").ilike("name", f"%{q}%").limit(limit).execute()
    )
    return {"songs": result.data}


@app.get("/api/songs")
def list_songs(limit: int = 50):
    result = supabase_retry(
        lambda: supabase.table("songs").select("*").limit(limit).execute()
    )
    return {"songs": result.data}


@app.get("/api/song/{song_id}")
def get_song(song_id: str):
    result = supabase_retry(
        lambda: supabase.table("songs").select("*").eq("id", song_id).execute()
    )
    if not result.data:
        raise HTTPException(404, "Song not found")
    return result.data[0]


@app.get("/api/preview/{song_id}")
def get_preview(song_id: str):
    """Get preview URL (Deezer → iTunes priority; YouTube embed fallback)"""
    song = supabase_retry(
        lambda: supabase.table("songs").select("*").eq("id", song_id).execute()
    )
    if not song.data:
        raise HTTPException(404, "Song not found")

    song_data = song.data[0]
    youtube_id = song_data.get("youtube_id")

    # Build clean queries for Deezer/iTunes
    queries = []
    title = song_data["name"]
    title = title.replace("&quot;", "").replace("&amp;", "&").replace("&#39;", "'")
    title_clean = title.split("|")[0].split("(")[0].strip()

    junk = ["Full Song", "Full Video", "Lyric Video", "Lyrics",
            "Official Video", "Official Music Video", "Official",
            "Music Video", "Audio", "4K", "HD", "1080p", "Video"]
    for j in junk:
        title_clean = title_clean.replace(j, "")

    title_clean = " ".join(title_clean.split())
    if title_clean:
        queries.append(title_clean)

    # Add original user query from cache
    if youtube_id:
        yt_cache = supabase_retry(
            lambda: supabase.table("youtube_cache").select("song_name").eq(
                "video_id", youtube_id
            ).execute()
        )
        if yt_cache.data:
            cached_query = yt_cache.data[0]["song_name"]
            cached_lower = cached_query.lower()
            if not any(j.lower() in cached_lower for j in junk):
                if cached_query not in queries:
                    queries.append(cached_query)

    print(f"🎵 Queries: {queries}")

    # Priority 1: Deezer
    for q in queries:
        result = search_deezer(q)
        if result:
            print(f"✅ Deezer: {result['title']} — {result['artist']}")
            proxy_url = f"http://localhost:8000/api/proxy_audio?url={requests.utils.quote(result['preview_url'], safe='')}"
            return {
                "preview_url": proxy_url,
                "original_url": result["preview_url"],
                "title": result["title"],
                "artist": result["artist"],
                "cover": result["cover"],
                "source": "deezer",
                "youtube_id": youtube_id,
            }

    # Priority 2: iTunes
    print("🎵 Trying iTunes...")
    for q in queries:
        result = search_itunes(q)
        if result:
            print(f"✅ iTunes: {result['title']} — {result['artist']}")
            proxy_url = f"http://localhost:8000/api/proxy_audio?url={requests.utils.quote(result['preview_url'], safe='')}"
            return {
                "preview_url": proxy_url,
                "original_url": result["preview_url"],
                "title": result["title"],
                "artist": result["artist"],
                "cover": result["cover"],
                "source": "itunes",
                "youtube_id": youtube_id,
            }

    # Priority 3: YouTube embed (only if no preview)
    if youtube_id:
        print(f"⚠️  No preview found, using YouTube embed")
        return {
            "preview_url": None,
            "youtube_id": youtube_id,
            "youtube_embed": f"https://www.youtube.com/embed/{youtube_id}",
            "source": "youtube_full",
            "title": song_data["name"],
            "artist": song_data.get("artist", ""),
            "cover": song_data.get("thumbnail", ""),
        }

    return {"preview_url": None, "youtube_id": youtube_id, "source": "none"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)