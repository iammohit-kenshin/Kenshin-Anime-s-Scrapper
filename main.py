import os
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from scraper import get_chapters, download_chapter

# --- RENDER PORT BINDING FIX ---
# Render "Web Service" ko port chahiye hota hai, ye dummy server usse satisfy karega.
class DummyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is Running!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyServer)
    server.serve_forever()

# Background mein server chalao
threading.Thread(target=run_dummy_server, daemon=True).start()

# --- BOT CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "your_hash")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_token")

app = Client("manga_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.private & filters.text)
async def handle_url(client, message):
    url = message.text
    if "mangabuddy.com" in url or "elftoon.com" in url:
        status = await message.reply("⏳ Chapters fetch kar raha hoon...")
        chapters = get_chapters(url)
        if not chapters:
            await status.edit("❌ Chapters nahi mile!")
            return
        
        buttons = []
        # Pehle 20 chapters dikhate hain
        for c in chapters[:20]:
            buttons.append([InlineKeyboardButton(c['name'], callback_data=f"dl|{c['url']}|{c['name']}")])
        
        buttons.insert(0, [InlineKeyboardButton("📥 Download All", callback_data=f"all|{url}")])
        await status.edit("Chapters Choose Karo:", reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await message.reply("Bhai, sirf MangaBuddy ya Elftoon link bhejo.")

@app.on_callback_query()
async def callback_handler(client, query):
    if query.data.startswith("dl|"):
        _, url, name = query.data.split("|")
        await query.answer(f"Downloading {name}...")
        status = await query.message.reply(f"🚀 {name} download ho raha hai...")
        
        pdf = download_chapter(url, name)
        if pdf:
            await client.send_document(query.message.chat.id, pdf)
            if os.path.exists(pdf): os.remove(pdf)
            await status.delete()
        else:
            await status.edit("❌ Failed! Images nahi mili.")
            
    elif query.data.startswith("all|"):
        url = query.data.split("|")[1]
        await query.answer("Sequence download shuru...")
        chapters = get_chapters(url)
        for c in chapters:
            msg = await query.message.reply(f"🔄 Sequence: {c['name']}")
            pdf = download_chapter(c['url'], c['name'])
            if pdf:
                await client.send_document(query.message.chat.id, pdf)
                if os.path.exists(pdf): os.remove(pdf)
            await msg.delete()

# --- ASYNC RUNNER FIX ---
# Python 3.11+ ke liye loop fix
async def main():
    async with app:
        print("✅ Bot successfully started on Render!")
        await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
