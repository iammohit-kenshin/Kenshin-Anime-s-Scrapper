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
import aiofiles
import uuid

from config import Config
from plugins.search import MangaSearcher
from plugins.downloader import DownloadManager
from plugins.pdf_engine import PDFEngine
from plugins.queue_system import QueueManager
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
        self.downloader = DownloadManager()
        self.pdf_engine = PDFEngine()
        self.queue = QueueManager()
        self.file_manager = FileManager()
        
        # User session data (temporary, no database)
        self.user_sessions = {}
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """/start command with fancy welcome"""
        user = update.effective_user
        welcome_msg = f"""
🌟 **MANWHA VERSE BOT** 🌟

Hello {user.first_name}! 

Main aapka personal manga/manwha assistant hoon. 
Bas manga ka naam bhejo, main dhundh ke la dunga!

**Features:**
🔍 Multi-site Search (MangaBuddy, Elftoon)
📚 Chapter-wise PDF
🎨 Custom Banner (1st & Last Page)
🖼️ Custom Thumbnail
📦 Batch Download (All Chapters)
⚡ Queue System
🗑️ Auto-Delete after sending

**Commands:**
/start - Welcome
/queue - Check your queue status
/cancel - Cancel current download
/settings - Customize settings
/help - Help

**Example:** "One Piece" ya "Solo Leveling"
        """
        
        # Settings button
        keyboard = [
            [
                InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
                InlineKeyboardButton("📚 Queue", callback_data="queue")
            ],
            [
                InlineKeyboardButton("📖 How to Use", callback_data="help"),
                InlineKeyboardButton("🌟 Support", url="t.me/yourchannel")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            welcome_msg,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def handle_manga_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User ne manga naam diya - search karo"""
        query = update.message.text
        user_id = update.effective_user.id
        
        # Ignore commands
        if query.startswith('/'):
            return
        
        # Processing message
        status_msg = await update.message.reply_text(
            f"🔍 Searching for: **{query}**\n\n"
            f"Checking MangaBuddy and Elftoon...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        try:
            # Multi-site search
            results = await self.searcher.search_all_sites(query)
            
            if not results:
                await status_msg.edit_text(
                    f"❌ No results found for '{query}'\n\n"
                    f"Try different spelling or check /help"
                )
                return
            
            # Store in session
            session_id = str(uuid.uuid4())
            self.user_sessions[user_id] = {
                'session_id': session_id,
                'results': results,
                'step': 'select_manga'
            }
            
            # Show results with buttons
            keyboard = []
            for i, manga in enumerate(results[:15]):  # Max 15 results
                title = manga['title'][:40] + "..." if len(manga['title']) > 40 else manga['title']
                keyboard.append([
                    InlineKeyboardButton(
                        f"{i+1}. {title} ({manga['site']})",
                        callback_data=f"manga_{i}"
                    )
                ])
            
            # Next page button if more results
            if len(results) > 15:
                keyboard.append([InlineKeyboardButton("➡️ Next Page", callback_data="manga_next")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await status_msg.edit_text(
                f"📚 Found {len(results)} results for '{query}':\n\n"
                f"Select your manga:",
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            await status_msg.edit_text(
                f"❌ Error searching: {str(e)}\n"
                f"Please try again later."
            )
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all button clicks"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        data = query.data
        
        # Check user session
        if user_id not in self.user_sessions:
            await query.edit_message_text(
                "⚠️ Session expired! Please send manga name again."
            )
            return
        
        session = self.user_sessions[user_id]
        
        if data.startswith('manga_'):
            # Manga selection
            if data == 'manga_next':
                # Handle next page
                pass
            else:
                index = int(data.split('_')[1])
                selected_manga = session['results'][index]
                
                # Store selected manga
                session['selected_manga'] = selected_manga
                session['step'] = 'select_chapters'
                
                # Fetch chapters
                await query.edit_message_text(
                    f"📖 Fetching chapters for:\n"
                    f"**{selected_manga['title']}**\n\n"
                    f"Please wait...",
                    parse_mode=ParseMode.MARKDOWN
                )
                
                # Get chapters
                chapters = await self.searcher.get_manga_chapters(selected_manga)
                
                if not chapters:
                    await query.edit_message_text(
                        "❌ No chapters found!"
                    )
                    return
                
                session['chapters'] = chapters
                session['total_chapters'] = len(chapters)
                
                # Show chapter options
                await self.show_chapter_options(query, session)
        
        elif data.startswith('chap_'):
            # Chapter selection
            if data == 'chap_all':
                # Download all chapters
                await self.queue_all_chapters(query, session)
            elif data == 'chap_range':
                # Ask for range
                await query.edit_message_text(
                    "📝 Send chapter range (e.g., 1-50 or 5,10,15):\n"
                    "Or /cancel to go back"
                )
                session['step'] = 'waiting_range'
            else:
                # Single chapter
                chap_num = int(data.split('_')[1])
                await self.process_chapter(query, session, chap_num)
        
        elif data.startswith('settings_'):
            # Settings menu
            await self.show_settings(query, session)
        
        elif data.startswith('banner_'):
            # Banner settings
            if data == 'banner_custom':
                await query.edit_message_text(
                    "🖼️ Send me your banner image for FIRST page.\n"
                    "It will be added at the beginning of PDF."
                )
                session['step'] = 'waiting_banner1'
            elif data == 'banner_default':
                session['banner1'] = 'default'
                await query.edit_message_text(
                    "✅ Default banner set for first page!\n"
                    "Now send banner for LAST page or /skip"
                )
                session['step'] = 'waiting_banner2'
        
        elif data.startswith('thumb_'):
            # Thumbnail settings
            if data == 'thumb_custom':
                await query.edit_message_text(
                    "🖼️ Send me the image you want as PDF thumbnail."
                )
                session['step'] = 'waiting_thumbnail'
            elif data == 'thumb_default':
                session['thumbnail'] = 'default'
                await query.edit_message_text(
                    "✅ Default thumbnail set!"
                )
        
        elif data == 'queue':
            # Show queue status
            await self.show_queue_status(query, user_id)
        
        elif data == 'cancel':
            # Cancel current operation
            self.user_sessions.pop(user_id, None)
            await query.edit_message_text(
                "❌ Operation cancelled!\n"
                "Send manga name to start fresh."
            )
    
    async def show_chapter_options(self, query, session):
        """Show chapter selection menu"""
        total = session['total_chapters']
        
        # Create chapter selection keyboard
        keyboard = []
        
        # Quick select buttons
        row = []
        for i in range(1, min(6, total+1)):
            row.append(InlineKeyboardButton(
                str(i), callback_data=f"chap_{i}"
            ))
        keyboard.append(row)
        
        # More options
        keyboard.extend([
            [
                InlineKeyboardButton("📦 Download All", callback_data="chap_all"),
                InlineKeyboardButton("🔢 Select Range", callback_data="chap_range")
            ],
            [
                InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel")
            ]
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        manga = session['selected_manga']
        await query.edit_message_text(
            f"📚 **{manga['title']}**\n"
            f"Total Chapters: {total}\n\n"
            f"Select chapter number or option:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def show_settings(self, query, session):
        """Show settings menu"""
        keyboard = [
            [
                InlineKeyboardButton("🎨 Banner", callback_data="settings_banner"),
                InlineKeyboardButton("🖼️ Thumbnail", callback_data="settings_thumb")
            ],
            [
                InlineKeyboardButton("📝 Caption", callback_data="settings_caption"),
                InlineKeyboardButton("🗜️ Compress", callback_data="settings_compress")
            ],
            [
                InlineKeyboardButton("🔙 Back", callback_data="back"),
                InlineKeyboardButton("✅ Done", callback_data="settings_done")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        current = session.get('settings', {})
        await query.edit_message_text(
            f"⚙️ **Settings**\n\n"
            f"Current Settings:\n"
            f"• Banner: {current.get('banner', 'Default')}\n"
            f"• Thumbnail: {current.get('thumb', 'Default')}\n"
            f"• Compress: {current.get('compress', 'No')}\n\n"
            f"Choose option:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def process_chapter(self, query, session, chapter_num):
        """Process single chapter download"""
        user_id = query.from_user.id
        
        # Add to queue
        job_id = await self.queue.add_job(
            user_id=user_id,
            manga=session['selected_manga'],
            chapter=chapter_num,
            settings=session.get('settings', {})
        )
        
        await query.edit_message_text(
            f"✅ Chapter {chapter_num} added to queue!\n"
            f"Job ID: `{job_id}`\n\n"
            f"Use /queue to check status\n"
            f"Use /cancel {job_id} to cancel",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Start processing in background
        asyncio.create_task(self.process_job(job_id, query))
    
    async def queue_all_chapters(self, query, session):
        """Queue all chapters for download"""
        user_id = query.from_user.id
        total = session['total_chapters']
        
        status_msg = await query.edit_message_text(
            f"📦 Adding {total} chapters to queue...\n"
            f"Progress: 0/{total}"
        )
        
        job_ids = []
        for i in range(1, total + 1):
            job_id = await self.queue.add_job(
                user_id=user_id,
                manga=session['selected_manga'],
                chapter=i,
                settings=session.get('settings', {})
            )
            job_ids.append(job_id)
            
            if i % 10 == 0:
                await status_msg.edit_text(
                    f"📦 Adding chapters to queue...\n"
                    f"Progress: {i}/{total}"
                )
        
        await status_msg.edit_text(
            f"✅ All {total} chapters queued!\n"
            f"Job IDs: `{job_ids[0]}` ... `{job_ids[-1]}`\n\n"
            f"Use /queue to check status"
        )
        
        # Start processing
        for job_id in job_ids:
            asyncio.create_task(self.process_job(job_id, query))
            await asyncio.sleep(0.5)  # Rate limiting
    
    async def process_job(self, job_id, query):
        """Process a single download job"""
        try:
            # Get job details
            job = await self.queue.get_job(job_id)
            if not job:
                return
            
            user_id = job['user_id']
            manga = job['manga']
            chapter = job['chapter']
            settings = job['settings']
            
            # Update status
            await self.queue.update_job(job_id, 'downloading')
            
            # Send processing message to user
            progress_msg = await query.message.reply_text(
                f"🔄 Processing {manga['title']} Chapter {chapter}...\n"
                f"Step: Downloading images"
            )
            
            # Get chapter images
            chapter_url = manga['chapters'][chapter-1]['url']
            images = await self.searcher.get_chapter_images(chapter_url)
            
            if not images:
                await progress_msg.edit_text(
                    f"❌ No images found for Chapter {chapter}"
                )
                await self.queue.update_job(job_id, 'failed')
                return
            
            # Download images with progress
            downloaded = []
            for i, img_url in enumerate(images):
                path = await self.downloader.download_image(img_url, f"temp/{job_id}_{i}.jpg")
                downloaded.append(path)
                
                if i % 5 == 0:
                    percent = int((i+1)/len(images)*30)  # 30% for download
                    await progress_msg.edit_text(
                        f"🔄 Processing {manga['title']} Chapter {chapter}...\n"
                        f"Download: {percent}%"
                    )
            
            # Apply banners if provided
            await self.queue.update_job(job_id, 'converting')
            await progress_msg.edit_text(
                f"🔄 Creating PDF...\n"
                f"Step: Adding banners"
            )
            
            banner1 = settings.get('banner1')
            banner2 = settings.get('banner2')
            
            pdf_path = await self.pdf_engine.create_pdf(
                images=downloaded,
                banner1=banner1,
                banner2=banner2,
                job_id=job_id
            )
            
            # Apply thumbnail
            if settings.get('thumbnail'):
                await self.pdf_engine.set_thumbnail(
                    pdf_path, 
                    settings['thumbnail']
                )
            
            # Compress if needed
            if settings.get('compress'):
                await progress_msg.edit_text(
                    f"🔄 Compressing PDF..."
                )
                pdf_path = await self.pdf_engine.compress_pdf(pdf_path)
            
            # Generate filename
            filename = f"[Chapter-{chapter}] {manga['title']}.pdf"
            if settings.get('file_pattern'):
                filename = settings['file_pattern'].format(
                    chapter_num=chapter,
                    manga_title=manga['title']
                )
            
            # Send to user
            await self.queue.update_job(job_id, 'uploading')
            await progress_msg.edit_text(
                f"📤 Uploading Chapter {chapter}..."
            )
            
            with open(pdf_path, 'rb') as f:
                caption = self.generate_caption(job, settings)
                await query.message.reply_document(
                    document=f,
                    filename=filename,
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN
                )
            
            # Cleanup
            self.file_manager.cleanup(job_id)
            await progress_msg.delete()
            
            # Update queue status
            await self.queue.update_job(job_id, 'completed')
            
        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}")
            await self.queue.update_job(job_id, 'failed')
            await query.message.reply_text(
                f"❌ Job {job_id} failed: {str(e)}"
            )
    
    def generate_caption(self, job, settings):
        """Generate dynamic caption"""
        default = (
            f"📖 **{job['manga']['title']}**\n"
            f"📚 Chapter: {job['chapter']}\n\n"
            f"Powered by @ManwhaVerse"
        )
        
        pattern = settings.get('caption_pattern')
        if pattern:
            try:
                return pattern.format(
                    chapter_num=job['chapter'],
                    manga_title=job['manga']['title']
                )
            except:
                return default
        
        return default
    
    async def show_queue_status(self, query, user_id):
        """Show user's queue status"""
        jobs = await self.queue.get_user_jobs(user_id)
        
        if not jobs:
            await query.edit_message_text(
                "📪 Your queue is empty!\n"
                "Send manga name to start downloading."
            )
            return
        
        status_text = "**📊 Your Queue Status:**\n\n"
        for job in jobs[:10]:  # Show last 10
            status_text += (
                f"• {job['manga']['title'][:30]} Ch.{job['chapter']}\n"
                f"  Status: {job['status'].upper()}\n"
                f"  ID: `{job['job_id'][:8]}...`\n\n"
            )
        
        if len(jobs) > 10:
            status_text += f"\n... and {len(jobs)-10} more"
        
        await query.edit_message_text(
            status_text,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle user uploaded photos (banners/thumbnails)"""
        user_id = update.effective_user.id
        
        if user_id not in self.user_sessions:
            await update.message.reply_text(
                "Please send manga name first!"
            )
            return
        
        session = self.user_sessions[user_id]
        step = session.get('step')
        
        if step in ['waiting_banner1', 'waiting_banner2', 'waiting_thumbnail']:
            # Download photo
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            
            # Save with unique name
            ext = 'jpg'
            filename = f"temp/{user_id}_{step}_{uuid.uuid4()}.{ext}"
            await file.download_to_drive(filename)
            
            if step == 'waiting_banner1':
                session['banner1'] = filename
                session['step'] = 'waiting_banner2'
                await update.message.reply_text(
                    "✅ Banner 1 saved!\n"
                    "Now send banner for LAST page or /skip"
                )
            
            elif step == 'waiting_banner2':
                session['banner2'] = filename
                session['step'] = 'select_chapters'
                await update.message.reply_text(
                    "✅ Both banners saved!\n"
                    "Now select chapters:"
                )
                # Show chapter options again
                await self.show_chapter_options(
                    update, session
                )
            
            elif step == 'waiting_thumbnail':
                session['thumbnail'] = filename
                session['step'] = 'select_chapters'
                await update.message.reply_text(
                    "✅ Thumbnail saved!\n"
                    "Now select chapters:"
                )

async def main():
    """Main function to run bot"""
    # Create bot instance
    bot = MangaVerseBot()
    
    # Create application
    app = Application.builder().token(Config.BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("queue", bot.show_queue_status))
    app.add_handler(CommandHandler("cancel", bot.cancel_job))
    app.add_handler(CommandHandler("settings", bot.show_settings))
    
    # Message handlers
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, 
        bot.handle_manga_search
    ))
    app.add_handler(MessageHandler(
        filters.PHOTO, 
        bot.handle_photo
    ))
    
    # Callback handler
    app.add_handler(CallbackQueryHandler(bot.handle_callback))
    
    # Start bot
    print("🤖 Manwha Verse Bot is running...")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
