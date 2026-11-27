import base64
import json
import os
import subprocess
import time

ADB = r"L:\tools\android-sdk\platform-tools\adb.exe"

def run_adb(args):
    cmd = [ADB] + args
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return res.stdout.strip()

def send_js(js_code):
    b64 = base64.b64encode(js_code.encode("utf-8")).decode("ascii")
    # Send both as broadcast and as intent to active activity
    run_adb(["shell", "am", "broadcast", "-a", "dev.sherlock.clipifyai.ACTION_CMD", "--es", "eval_b64", b64])
    run_adb(["shell", "am", "start", "-n", "dev.sherlock.clipifyai/.MainActivity", "--es", "eval_b64", b64])

print("[Test] Setting up reverse port forward...")
run_adb(["reverse", "tcp:5000", "tcp:5000"])

print("[Test] Bringing Clipify AI to foreground...")
run_adb(["shell", "am", "start", "-n", "dev.sherlock.clipifyai/.MainActivity"])
time.sleep(2)

# TEST 1: Normal Trending Video
test_vid_url = "https://www.youtube.com/watch?v=CuR16jMhdkQ"
test_vid_title = "Son of Thanjai - Gameplay Trailer"
print(f"\n==========================================")
print(f"[Test 1] Clipping Trending Video: {test_vid_title}")
print(f"URL: {test_vid_url}")
print(f"==========================================")

js_vid = f"""
(function() {{
  console.log('[EVAL] Triggering clipTrendingVideo for: {test_vid_url}');
  if (typeof window.clipTrendingVideo === 'function') {{
    window.clipTrendingVideo('{test_vid_url}', '{test_vid_title}', false);
  }} else {{
    var ytInput = document.getElementById('mobileYtUrl');
    if (ytInput) ytInput.value = '{test_vid_url}';
    if (window.mobileStudioState) {{
      window.mobileStudioState.selectedUri = '{test_vid_url}';
      window.mobileStudioState.selectedFileName = '{test_vid_title}';
    }}
  }}
  setTimeout(function() {{
    var btn = document.getElementById('mobileGenerateBtn');
    if (btn) {{
      btn.disabled = false;
      btn.click();
      console.log('[EVAL] mobileGenerateBtn clicked!');
    }}
  }}, 600);
}})();
"""

send_js(js_vid)
print("[Test 1] Sent trigger JS to mobile. Monitoring progress...")

# Poll for rendered output
start_t = time.time()
found_file = None
while time.time() - start_t < 90:
    time.sleep(3)
    files = run_adb(["shell", "ls", "-t", "/sdcard/Movies/ClipifyAI/*.mp4"]).splitlines()
    files = [f.strip() for f in files if f.strip() and "No such file" not in f and not f.endswith("cannot access")]
    if files:
        latest = files[0]
        # Check size > 1MB
        size_str = run_adb(["shell", "stat", "-c", "%s", latest])
        try:
            sz = int(size_str.strip())
            if sz > 200000:
                print(f"[Test 1] Render completed: {latest} ({sz / (1024*1024):.2f} MB)")
                found_file = latest
                break
        except Exception:
            pass

if found_file:
    # Pull file to inspect duration
    local_dest = r"L:\ClipifyAI\trending_video_clip.mp4"
    run_adb(["pull", found_file, local_dest])
    if os.path.exists(local_dest):
        # Probe duration using ffprobe
        ffprobe = r"C:\Users\Dell\AppData\Local\Programs\ClipifyAI\ffmpeg\ffprobe.exe"
        if not os.path.exists(ffprobe):
            ffprobe = "ffprobe"
        res = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration,size,bit_rate", "-of", "json", local_dest],
            capture_output=True, text=True
        )
        print(f"[Test 1 FFprobe Result]:\n{res.stdout}")
else:
    print("[Test 1 Warning]: File not finished within timeout, checking active instant jobs on backend...")
    res = subprocess.run(["powershell", "-Command", "Invoke-RestMethod -Uri 'http://127.0.0.1:5000/api/diagnostic'"], capture_output=True, text=True)
    print(res.stdout[:500])

