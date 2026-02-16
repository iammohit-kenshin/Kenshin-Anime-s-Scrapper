import os
import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    filters, ContextTypes, CallbackQueryHandler
)
from telegram.constants import ParseMode
import uuid
import time

from config import Config
from plugins.search import MangaSearcher
from plugins.pdf_engine import PDFEngine
from plugins.simple_queue import SimpleQueue  # 👈 Redis nahi, ye use karo
from utils.file_manager import FileManager

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class MangaVerseBot:
    def __init__(self):
        self.searcher = MangaSearcher()
        self.pdf_engine = PDFEngine()
        # 👇 Simple in-memory queue - no Redis!
        self.queue = SimpleQueue(expiry=3600)  
        self.file_manager = FileManager()
        
        # User sessions (temporary, auto-clean)
        self.user_sessions = {}
        self.last_request = {}  # For rate limiting
    
    def check_rate_limit(self, user_id: int) -> bool:
        """Simple rate limiting"""
        now = time.time()
        if user_id in self.last_request:
            if now - self.last_request[user_id] < (60 / Config.RATE_LIMIT):
                return False
        self.last_request[user_id] = now
        return True
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command"""
        user = update.effective_user
        await update.message.reply_text(
            f"👋 Namaste {user.first_name}!\n\n"
            f"Main Manga Bot hoon. Bas manga ka naam bhejo, "
            f"main dhundh kar PDF bhej dunga!\n\n"
            f"Example: 'One Piece' ya 'Solo Leveling'"
        )
    
    async def handle_manga_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Search manga by name"""
        user_id = update.effective_user.id
        
        # Rate limiting check
        if not self.check_rate_limit(user_id):
            await update.message.reply_text("⏳ Thoda ruko... Request limit hit!")
            return
        
        query = update.message.text
        
        # Ignore commands
        if query.startswith('/'):
            return
        
        # Search karo
        status_msg = await update.message.reply_text(f"🔍 Searching for: {query}")
        
        try:
            results = await self.searcher.search_all_sites(query)
            
            if not results:
                await status_msg.edit_text("❌ Kuch nahi mila! Different spelling try karo.")
                return
            
            # Store in session
            session_id = str(uuid.uuid4())
            self.user_sessions[user_id] = {
                'session_id': session_id,
                'results': results,
                'created_at': time.time()
            }
            
            # Show results
            keyboard = []
            for i, manga in enumerate(results[:10]):  # Max 10 results
                title = manga['title'][:35] + "..." if len(manga['title']) > 35 else manga['title']
                keyboard.append([
                    InlineKeyboardButton(
                        f"{i+1}. {title} ({manga['site']})",
                        callback_data=f"manga_{i}"
                    )
                ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await status_msg.edit_text(
                f"📚 Found {len(results)} results:\nSelect one:",
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            await status_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button clicks"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        data = query.data
        
        # Check session
        if user_id not in self.user_sessions:
            await query.edit_message_text("Session expired! Send manga name again.")
            return
        
        session = self.user_sessions[user_id]
        
        if data.startswith('manga_'):
            index = int(data.split('_')[1])
            selected = session['results'][index]
            
            session['selected'] = selected
            session['step'] = 'chapters'
            
            # Fetch chapters
            await query.edit_message_text(f"📖 Fetching chapters for: {selected['title']}")
            
            chapters = await self.searcher.get_manga_chapters(selected)
            
            if not chapters:
                await query.edit_message_text("❌ No chapters found!")
                return
            
            session['chapters'] = chapters
            session['total'] = len(chapters)
            
            # Show chapter options
            await self.show_chapters(query, session)
        
        elif data.startswith('chap_'):
            if data == 'chap_all':
                await self.queue_all(query, session)
            else:
                chap_num = int(data.split('_')[1])
                await self.add_to_queue(query, session, chap_num)
        
        elif data == 'queue_status':
            await self.show_queue(query, user_id)
        
        elif data == 'cancel':
            self.user_sessions.pop(user_id, None)
            await query.edit_message_text("Cancelled! Send manga name to start fresh.")
    
    async def show_chapters(self, query, session):
        """Show chapter selection"""
        keyboard = []
        
        # First 5 chapters
        row = []
        for i in range(1, min(6, session['total']+1)):
            row.append(InlineKeyboardButton(str(i), callback_data=f"chap_{i}"))
        keyboard.append(row)
        
        # More options
        keyboard.extend([
            [InlineKeyboardButton("📦 Download All", callback_data="chap_all")],
            [InlineKeyboardButton("📊 Queue Status", callback_data="queue_status"),
             InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"📚 {session['selected']['title']}\n"
            f"Total: {session['total']} chapters\n\n"
            f"Select chapter:",
            reply_markup=reply_markup
        )
    
    async def add_to_queue(self, query, session, chapter_num):
        """Add single chapter to queue"""
        user_id = query.from_user.id
        
        # Check user limit
        if self.queue.get_user_active_count(user_id) >= Config.MAX_CONCURRENT:
            await query.edit_message_text(
                f"⚠️ Already {Config.MAX_CONCURRENT} jobs running!\n"
                f"Wait for some to complete or use /queue"
            )
            return
        
        job_id = self.queue.add_job(
            user_id=user_id,
            manga=session['selected'],
            chapter=chapter_num,
            settings={}  # Add settings if needed
        )
        
        if not job_id:
            await query.edit_message_text("❌ Too many jobs! Wait for some to complete.")
            return
        
        await query.edit_message_text(
            f"✅ Chapter {chapter_num} added to queue!\n"
            f"Job ID: `{job_id}`\n\n"
            f"Use /queue to check status",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Start processing in background
        asyncio.create_task(self.process_queue())
    
    async def queue_all(self, query, session):
        """Queue all chapters"""
        user_id = query.from_user.id
        total = session['total']
        
        # Check limit
        if total > 20:  # Max 20 chapters at once
            await query.edit_message_text("⚠️ Max 20 chapters at a time! Use range selection.")
            return
        
        status_msg = await query.edit_message_text(f"📦 Adding {total} chapters to queue...")
        
        added = 0
        for i in range(1, total + 1):
            if self.queue.get_user_active_count(user_id) >= Config.MAX_CONCURRENT:
                break
            
            job_id = self.queue.add_job(
                user_id=user_id,
                manga=session['selected'],
                chapter=i,
                settings={}
            )
            
            if job_id:
                added += 1
                asyncio.create_task(self.process_queue())
            
            await asyncio.sleep(0.1)  # Small delay
        
        await status_msg.edit_text(
            f"✅ {added}/{total} chapters queued!\n"
            f"Use /queue to check status"
        )
    
    async def process_queue(self):
        """Process jobs from queue"""
        while True:
            job = self.queue.get_next_job()
            if not job:
                break
            
            try:
                await self.process_job(job)
            except Exception as e:
                logger.error(f"Job failed: {e}")
                self.queue.update_job(job['job_id'], 'failed', error=str(e))
    
    async def process_job(self, job):
        """Process single job"""
        job_id = job['job_id']
        user_id = job['user_id']
        
        try:
            # Get chapter images
            chapter_url = job['manga']['chapters'][job['chapter']-1]['url']
            images = await self.searcher.get_chapter_images(chapter_url)
            
            if not images:
                self.queue.update_job(job_id, 'failed', error="No images found")
                return
            
            # Download images
            downloaded = []
            for i, img_url in enumerate(images[:50]):  # Max 50 pages
                path = self.file_manager.get_temp_path(job_id, f"page_{i}.jpg")
                await self.downloader.download_image(img_url, path)
                downloaded.append(path)
                
                # Update progress
                if i % 10 == 0:
                    self.queue.update_job(job_id, 'processing', progress=int((i+1)/len(images)*50))
            
            # Create PDF
            pdf_path = self.file_manager.get_temp_path(job_id, "output.pdf")
            await self.pdf_engine.create_pdf(downloaded, pdf_path)
            
            # Send to user
            # ... (sending code)
            
            # Cleanup
            self.file_manager.cleanup(job_id)
            self.queue.update_job(job_id, 'completed')
            
        except Exception as e:
            self.queue.update_job(job_id, 'failed', error=str(e))
            self.file_manager.cleanup(job_id)
    
    async def show_queue(self, query, user_id):
        """Show user's queue"""
        jobs = self.queue.get_user_jobs(user_id)
        
        if not jobs:
            await query.edit_message_text("📪 Queue empty! Send manga name to start.")
            return
        
        text = "**📊 Your Queue:**\n\n"
        for job in jobs[-10:]:  # Last 10
            status_emoji = {
                'queued': '⏳',
                'processing': '🔄',
                'completed': '✅',
                'failed': '❌',
                'cancelled': '🚫'
            }.get(job['status'], '📌')
            
            text += f"{status_emoji} {job['manga']['title'][:20]} Ch.{job['chapter']}\n"
            if job['status'] == 'processing' and job.get('progress'):
                text += f"   Progress: {job['progress']}%\n"
            text += f"   ID: `{job['job_id']}`\n\n"
        
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)

def main():
    """Main function"""
    Config.validate()
    
    bot = MangaVerseBot()
    app = Application.builder().token(Config.BOT_TOKEN).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("queue", bot.show_queue))
    app.add_handler(CommandHandler("cancel", bot.cancel_job))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_manga_search))
    app.add_handler(CallbackQueryHandler(bot.handle_callback))
    
    print("🤖 Bot running... (No Redis, pure RAM)")
    app.run_polling()

if __name__ == "__main__":
    main()
