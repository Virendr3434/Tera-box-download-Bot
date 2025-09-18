# FINAL: Terabox Telegram Bot (Direct download + send video)
# Paste this into main.py on Replit (or any VPS). Set ENV secrets: API_ID, API_HASH, BOT_TOKEN

import os
import time
import requests
import tempfile
from bs4 import BeautifulSoup
from pyrogram import Client, filters
from pyrogram.errors import UserNotParticipant, FloodWait, RPCError

# ---------- CONFIG ----------
API_ID = int(os.getenv("API_ID") or 0)
API_HASH = os.getenv("API_HASH") or ""
BOT_TOKEN = os.getenv("BOT_TOKEN") or ""

# Channels to require (use username or chat id). You provided:
# @instagamov  and invite link t.me/+tZvUvt1zp1w0ZDU1
# For invite-link/private channel, get_chat_member may fail if bot isn't admin/member.
# We will try with whatever identifier you put in CHANNELS.
CHANNELS = ["instagamov", "tZvUvt1zp1w0ZDU1"]  # keep as provided (second may be invite-token)

# Max allowed file size to send (bytes). Keep slightly below Telegram limit (2GB).
MAX_SEND_SIZE = 1900 * 1024 * 1024  # ~1.9 GB

# Optional: Example API endpoint if you have one. If you don't have, leave as None.
TERABOX_API_ENDPOINT = None
# e.g. TERABOX_API_ENDPOINT = "https://teraboxdownloader.com/api"

# ---------- APP ----------
app = Client("teraboxbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


# ---------- Helper: Extractors ----------
def extract_via_api(url):
    """Try third-party API (if configured). Return direct file URL or None."""
    if not TERABOX_API_ENDPOINT:
        return None
    try:
        r = requests.post(TERABOX_API_ENDPOINT, data={"url": url}, timeout=20)
        r.raise_for_status()
        j = r.json()
        # Try common keys
        for key in ("downloadUrl", "download_url", "url", "file"):
            if key in j and j[key]:
                return j[key]
        # if structure nested
        if isinstance(j, dict) and "data" in j and isinstance(j["data"], dict):
            for k in ("downloadUrl", "url", "file"):
                if k in j["data"]:
                    return j["data"][k]
    except Exception as e:
        print("API extractor error:", e)
    return None


def extract_via_html(url):
    """Parse terabox page to find direct video URL. Best-effort; may fail if site changes."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code != 200:
            return None
        text = r.text

        # 1) Look for JSON-like key "downloadUrl" in page source
        if "downloadUrl" in text:
            i = text.find("downloadUrl")
            # find first quote after :
            start = text.find(":", i)
            if start != -1:
                # skip possible spaces
                start = text.find('"', start)
                if start != -1:
                    start += 1
                    end = text.find('"', start)
                    if end != -1:
                        return text[start:end]

        # 2) Try to find <video src="...">
        soup = BeautifulSoup(text, "lxml")
        video = soup.find("video")
        if video and video.get("src"):
            return video.get("src")

        # 3) Sometimes link present in meta tags or link tags
        tag = soup.find("meta", {"property": "og:video"})
        if tag and tag.get("content"):
            return tag.get("content")

        # 4) Fallback: find any https link containing 'terabox' and file extensions
        for ext in [".mp4", ".mkv", ".mov", ".webm"]:
            idx = text.find(ext)
            if idx != -1:
                # find start of url
                start = text.rfind('"', 0, idx)
                if start != -1:
                    start += 1
                    end = idx + len(ext)
                    # extend until next quote or whitespace
                    while end < len(text) and text[end] not in ['"', "'", " ", ">"]:
                        end += 1
                    candidate = text[start:end]
                    if candidate.startswith("http"):
                        return candidate

    except Exception as e:
        print("HTML extractor error:", e)
    return None


def get_terabox_link(url):
    """Try API then HTML. Return direct download URL or None."""
    # Normalize short t.me links or user pasted extra text
    url = url.strip()
    # Try API first
    link = extract_via_api(url)
    if link:
        return link
    # Then HTML parsing
    link = extract_via_html(url)
    return link


# ---------- Helper: subscription check ----------
async def is_subscribed(client, user_id):
    """Return True if user is member of all CHANNELS. Best-effort."""
    for ch in CHANNELS:
        try:
            # Try get_chat_member. If channel is invite link token (starts with '+'), try to resolve:
            chat_identifier = ch
            if ch.startswith("+") or ch.startswith("t.me/+") or ch.startswith("https://t.me/+"):
                # remove possible prefixes
                chat_identifier = ch.split("/")[-1]
            member = await client.get_chat_member(chat_identifier, user_id)
            # statuses that indicate membership
            if member.status in ["left", "kicked"]:
                return False
        except UserNotParticipant:
            return False
        except RPCError as e:
            # Many RPCErrors mean we couldn't access the channel (private, bot not admin) -> treat as not subscribed
            print(f"Subscription check RPC error for {ch}: {e}")
            return False
        except Exception as e:
            print(f"Subscription check error for {ch}:", e)
            return False
    return True


# ---------- Helper: head request for file size ----------
def get_remote_filesize(url):
    try:
        h = requests.head(url, allow_redirects=True, timeout=15)
        if h.status_code == 200:
            size = h.headers.get("Content-Length")
            if size:
                return int(size)
    except Exception as e:
        print("HEAD request error:", e)
    return None


# ---------- BOT HANDLERS ----------
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    await message.reply(
        "👋 Welcome! Main TeraBox Downloader Bot hu.\n\n"
        "📥 Pehle dono channels join karo tabhi download milega:\n"
        "👉 https://t.me/instagamov\n"
        "👉 https://t.me/+tZvUvt1zp1w0ZDU1\n\n"
        "Phir mujhe koi bhi TeraBox share link bhejo."
    )


@app.on_message(filters.private & filters.text & ~filters.command("start"))
async def handle_link(client, message):
    user_id = message.from_user.id
    text = message.text.strip()

    # Force subscribe check
    if not await is_subscribed(client, user_id):
        await message.reply(
            "❌ Pehle hamare channels join karo:\n"
            "👉 https://t.me/instagamov\n"
            "👉 https://t.me/+tZvUvt1zp1w0ZDU1\n\n"
            "Join karne ke baad wapas link bhejo."
        )
        return

    # Validate TeraBox link roughly
    if "terabox" not in text and "teraboxshare" not in text:
        await message.reply("⚠️ Yeh TeraBox link nahi lag raha. Sahi link bhejo.")
        return

    status = await message.reply("⏳ Download link nikal raha hu... (API + HTML try karta hu)")

    dl = get_terabox_link(text)
    if not dl:
        await status.edit("❌ Sorry, download link extract nahi ho paaya. Link private ya expired ho sakta hai.")
        return

    # check remote filesize (if available)
    filesize = get_remote_filesize(dl)
    if filesize:
        if filesize > MAX_SEND_SIZE:
            await status.edit(
                "❌ File bahut badi hai (>{:.2f} GB). Main Telegram par bhej nahi sakta.".format(filesize / (1024**3))
            )
            return
    else:
        # if unknown, warn user but proceed attempt (we'll still stop if streaming grows too big)
        await status.edit("⬇️ File size unknown — download start karta hu (agar bahut bada hua to ruk jaayega).")

    # Download streaming to temporary file
    tmp_dir = tempfile.gettempdir()
    fname = f"terabox_{user_id}_{int(time.time())}.mp4"
    fpath = os.path.join(tmp_dir, fname)

    try:
        with requests.get(dl, stream=True, timeout=120) as r:
            r.raise_for_status()
            total = 0
            chunk_size = 1024 * 64  # 64KB
            with open(fpath, "wb") as f:
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        total += len(chunk)
                        # safety: stop if exceed MAX_SEND_SIZE
                        if total > MAX_SEND_SIZE:
                            f.close()
                            os.remove(fpath)
                            await status.edit("❌ Download ruk gaya: file Telegram limit se badi ho rahi hai.")
                            return

        await status.edit("⬆️ Video download ho gaya. Ab Telegram par bhej raha hu...")

        # Send video file (use send_video so it becomes playable)
        try:
            await client.send_video(
                chat_id=message.chat.id,
                video=fpath,
                caption="✅ Yeh lo tumhara video."
            )
            await status.delete()
        except FloodWait as fw:
            await status.edit(f"⏳ Flood wait: {fw.x} seconds. Trying again after wait.")
            time.sleep(fw.x + 1)
            await client.send_video(chat_id=message.chat.id, video=fpath, caption="✅ Yeh lo tumhara video.")
        except Exception as e:
            print("Send video error:", e)
            await status.edit("❌ Video bhejne me problem aayi (Telegram upload limit ya network issue).")

    except Exception as e:
        print("Download error:", e)
        await status.edit("❌ Download/Network error hua. Ho sakta hai link expire ho ya server block kar raha ho.")

    finally:
        # cleanup
        try:
            if os.path.exists(fpath):
                os.remove(fpath)
        except Exception:
            pass


# ---------- RUN ----------
if __name__ == "__main__":
    if not (API_ID and API_HASH and BOT_TOKEN):
        print("ERROR: Set API_ID, API_HASH and BOT_TOKEN environment variables.")
    else:
        print("Bot starting...")
        app.run()
