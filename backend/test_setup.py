import os
import torch
from dotenv import load_dotenv

print("=" * 50)
print("🧪 Testing Setup")
print("=" * 50)

# 1. .env load test
print("\n1️⃣ Loading .env...")
load_dotenv()

api_key = os.getenv("YOUTUBE_API_KEY")
supabase_url = os.getenv("SUPABASE_URL")
supabase_anon = os.getenv("SUPABASE_ANON_KEY")

if api_key and len(api_key) > 20 and "yahan" not in api_key:
    print(f"   ✅ YOUTUBE_API_KEY loaded (starts with: {api_key[:8]}...)")
else:
    print(f"   ⚠️  YOUTUBE_API_KEY not set or placeholder")

if supabase_url and "xxxxx" not in supabase_url:
    print(f"   ✅ SUPABASE_URL: {supabase_url[:35]}...")
else:
    print(f"   ⚠️  SUPABASE_URL not set or placeholder")

if supabase_anon and "yahan" not in supabase_anon:
    print(f"   ✅ SUPABASE_ANON_KEY loaded (length: {len(supabase_anon)})")
else:
    print(f"   ⚠️  SUPABASE_ANON_KEY not set")

# 2. Torch test
print("\n2️⃣ Testing PyTorch...")
print(f"   ✅ Torch version: {torch.__version__}")
print(f"   Device: {'CUDA' if torch.cuda.is_available() else 'CPU'}")

# 3. MERIT heads test
print("\n3️⃣ Testing MERIT heads...")
all_ok = True
for head_name in ["head_mel", "head_rhy", "head_tim"]:
    path = f"models/{head_name}/best_head.pt"
    if os.path.exists(path):
        size_mb = os.path.getsize(path) / (1024 * 1024)
        print(f"   ✅ {head_name}: {size_mb:.1f} MB")
    else:
        print(f"   ❌ {head_name}: NOT FOUND at {path}")
        all_ok = False

# 4. yt-dlp test
print("\n4️⃣ Testing yt-dlp...")
try:
    import yt_dlp
    print(f"   ✅ yt-dlp: {yt_dlp.version.__version__}")
except ImportError:
    print(f"   ❌ yt-dlp not installed")
    all_ok = False

print("\n" + "=" * 50)
if all_ok:
    print("🎉 Setup complete! Ready to build!")
else:
    print("⚠️  Some things missing. Check above.")
print("=" * 50)