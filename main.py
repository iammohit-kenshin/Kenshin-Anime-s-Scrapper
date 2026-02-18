import os
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from scraper import get_chapters, download_chapter

# Railway Variables
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
            os.remove(pdf)
            await status.delete()
        else: await status.edit("❌ Failed!")
    elif query.data.startswith("all|"):
        url = query.data.split("|")[1]
        await query.answer("All chapters sequence mein aayenge.")
        chapters = get_chapters(url)
        for c in chapters:
            msg = await query.message.reply(f"🔄 Sequence: {c['name']}")
            pdf = download_chapter(c['url'], c['name'])
            if pdf:
                await client.send_document(query.message.chat.id, pdf)
                os.remove(pdf)
            await msg.delete()

app.run()
