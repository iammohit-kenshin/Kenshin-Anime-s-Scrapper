"""
MANGA VERSE BOT - Single File Version
10th Class Python Project
Ethical Purpose Only
"""

import os
import logging
import asyncio
import time
import uuid
import aiohttp
import aiofiles
import img2pdf
from bs4 import BeautifulSoup
from PIL import Image
from typing import List, Dict, Optional
from collections import defaultdict
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    filters, ContextTypes, CallbackQueryHandler
)
from telegram.constants import ParseMode
from dotenv import load_dotenv

# ==================== CONFIGURATION ====================
load_dotenv()

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    TEMP_DIR = "temp"
    RATE_LIMIT = 5  # requests per minute
    MAX_CONCURRENT = 3  # max jobs per user
    MAX_CHAPTERS = 20  # max chapters at once
    
    @classmethod
    def validate(cls):
        if not cls.BOT_TOKEN:
            raise ValueError("❌ BOT_TOKEN environment variable not set!")
        return True

# ==================== FILE MANAGER ====================
class FileManager:
    def __init__(self, temp_dir="temp"):
        self.temp_dir = temp_dir
        os.makedirs(temp_dir, exist_ok=True)
        print(f"📁 Temp directory: {temp_dir}")
    
    def get_temp_path(self, job_id: str, filename: str) -> str:
        job_dir = os.path.join(self.temp_dir, job_id)
        os.makedirs(job_dir, exist_ok=True)
        return os.path.join(job_dir, filename)
    
    async def download_image(self, url: str, path: str) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as response:
                    if response.status == 200:
                        async with aiofiles.open(path, 'wb') as f:
                            await f.write(await response.read())
                        return True
            return False
        except Exception as e:
            print(f"Download error: {e}")
            return False
    
    def cleanup(self, job_id: str):
        try:
            job_dir = os.path.join(self.temp_dir, job_id)
            if os.path.exists(job_dir):
                import shutil
                shutil.rmtree(job_dir)
        except Exception as e:
            print(f"Cleanup error: {e}")

# ==================== MANGA SEARCHER ====================
class MangaSearcher:
    def __init__(self):
        self.sites = {
            'mangabuddy': {
                'search_url': 'https://mangabuddy.com/search?q={}',
                'base_url': 'https://mangabuddy.com'
            },
            'elftoon': {
                'search_url': 'https://elftoon.com/search?q={}',
                'base_url': 'https://elftoon.com'
            }
        }
        self.session = None
    
    async def get_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def search_all_sites(self, query: str) -> List[Dict]:
        tasks = []
        for site_name, site_config in self.sites.items():
            tasks.append(self.search_site(site_name, site_config, query))
        
        results = await asyncio.gather(*tasks)
        all_results = []
        for site_results in results:
            all_results.extend(site_results)
        return all_results[:15]
    
    async def search_site(self, site_name: str, config: Dict, query: str) -> List[Dict]:
        try:
            session = await self.get_session()
            search_url = config['search_url'].format(query.replace(' ', '+'))
            
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            
            async with session.get(search_url, headers=headers, timeout=10) as response:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                results = []
                
                if site_name == 'mangabuddy':
                    items = soup.select('.book-item')
                    for item in items[:10]:
                        title_elem = item.select_one('.book-title a')
                        if title_elem:
                            results.append({
                                'title': title_elem.text.strip(),
                                'url': title_elem['href'] if title_elem['href'].startswith('http') else config['base_url'] + title_elem['href'],
                                'site': 'MangaBuddy'
                            })
                
                elif site_name == 'elftoon':
                    items = soup.select('.manga-item, .page-item-detail')
                    for item in items[:10]:
                        title_elem = item.select_one('h3 a, .manga-title a')
                        if title_elem:
                            results.append({
                                'title': title_elem.text.strip(),
                                'url': title_elem['href'] if title_elem['href'].startswith('http') else 'https://elftoon.com' + title_elem['href'],
                                'site': 'Elftoon'
                            })
                
                return results
        except Exception as e:
            print(f"Error searching {site_name}: {e}")
            return []
    
    async def get_manga_chapters(self, manga: Dict) -> List[Dict]:
        try:
            session = await self.get_session()
            headers = {'User-Agent': 'Mozilla/5.0'}
            
            async with session.get(manga['url'], headers=headers, timeout=10) as response:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                chapters = []
                
                if manga['site'] == 'MangaBuddy':
                    items = soup.select('.chapter-list a, ul.chapter-list li a')
                    for i, item in enumerate(items[:200], 1):
                        chapters.append({
                            'number': i,
                            'title': item.text.strip() or f"Chapter {i}",
                            'url': item['href'] if item['href'].startswith('http') else 'https://mangabuddy.com' + item['href']
                        })
                
                elif manga['site'] == 'Elftoon':
                    items = soup.select('.wp-manga-chapter a, .chapter-item a')
                    for i, item in enumerate(reversed(items[:200]), 1):
                        chapters.append({
                            'number': i,
                            'title': item.text.strip() or f"Chapter {i}",
                            'url': item['href'] if item['href'].startswith('http') else 'https://elftoon.com' + item['href']
                        })
                
                return chapters
        except Exception as e:
            print(f"Error getting chapters: {e}")
            return []
    
    async def get_chapter_images(self, chapter_url: str) -> List[str]:
        try:
            session = await self.get_session()
            headers = {'User-Agent': 'Mozilla/5.0'}
            
            async with session.get(chapter_url, headers=headers, timeout=10) as response:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                images = []
                img_selectors = [
                    '.reading-content img',
                    '.chapter-content img',
                    '.manga-reading img',
                    'img[data-src]',
                    '.page-break img'
                ]
                
                for selector in img_selectors:
                    imgs = soup.select(selector)
                    for img in imgs:
                        src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                        if src and src not in images:
                            if src.startswith('http'):
                                images.append(src)
                            else:
                                images.append('https:' + src if src.startswith('//') else src)
                    
                    if images:
                        break
                
                return images[:50]
        except Exception as e:
            print(f"Error getting images: {e}")
            return []
    
    async def close(self):
        if self.session:
            await self.session.close()

# ==================== PDF ENGINE ====================
class PDFEngine:
    async def create_pdf(self, image_paths: List[str], output_path: str) -> bool:
        try:
            with open(output_path, "wb") as f:
                f.write(img2pdf.convert(image_paths))
            return True
        except Exception as e:
            print(f"PDF creation error: {e}")
            return False

# ==================== SIMPLE QUEUE ====================
class SimpleQueue:
    def __init__(self, expiry=3600):
        self.jobs = {}
        self.user_jobs = defaultdict(list)
        self.processing = set()
        self.expiry = expiry
    
    def add_job(self, user_id: int, manga: Dict, chapter: int, chapter_url: str) -> Optional[str]:
        active = self.get_user_active_count(user_id)
        if active >= 5:
            return None
        
        job_id = str(uuid.uuid4())[:8]
        
        job_data = {
            'job_id': job_id,
            'user_id': user_id,
            'manga': manga,
            'chapter': chapter,
            'chapter_url': chapter_url,
            'status': 'queued',
            'created_at': time.time(),
            'updated_at': time.time(),
            'progress': 0
        }
        
        self.jobs[job_id] = job_data
        self.user_jobs[user_id].append(job_id)
        return job_id
    
    def get_next_job(self) -> Optional[Dict]:
        for job_id, job in self.jobs.items():
            if job['status'] == 'queued' and job_id not in self.processing:
                self.processing.add(job_id)
                job['status'] = 'processing'
                job['updated_at'] = time.time()
                return job.copy()
        return None
    
    def update_job(self, job_id: str, status: str, **kwargs):
        if job_id in self.jobs:
            self.jobs[job_id]['status'] = status
            self.jobs[job_id]['updated_at'] = time.time()
            self.jobs[job_id].update(kwargs)
            
            if status in ['completed', 'failed', 'cancelled']:
                if job_id in self.processing:
                    self.processing.remove(job_id)
    
    def get_user_jobs(self, user_id: int) -> List[Dict]:
        job_ids = self.user_jobs.get(user_id, [])
        jobs = []
        for job_id in job_ids:
            if job_id in self.jobs:
                jobs.append(self.jobs[job_id])
        return jobs
    
    def get_user_active_count(self, user_id: int) -> int:
        count = 0
        for job_id in self.user_jobs.get(user_id, []):
            if job_id in self.jobs and self.jobs[job_id]['status'] in ['queued', 'processing']:
                count += 1
        return count

# ==================== MAIN BOT ====================
class MangaVerseBot:
    def __init__(self):
        print("🤖 Initializing Manga Verse Bot...")
        self.searcher = MangaSearcher()
        self.pdf_engine = PDFEngine()
        self.queue = SimpleQueue()
        self.file_manager = FileManager()
        self.user_sessions = {}
        self.last_request = {}
        print("✅ Bot initialized successfully!")
    
    def check_rate_limit(self, user_id: int) -> bool:
        now = time.time()
        if user_id in self.last_request:
            if now - self.last_request[user_id] < (60 / Config.RATE_LIMIT):
                return False
        self.last_request[user_id] = now
        return True
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        await update.message.reply_text(
            f"👋 **Namaste {user.first_name}!**\n\n"
            f"Main Manga Verse Bot hoon. Bas manga ka naam bhejo, "
            f"main dhundh kar PDF bhej dunga!\n\n"
            f"**Example:** 'One Piece' ya 'Solo Leveling'\n\n"
            f"**Commands:**\n"
            f"/queue - Check queue status\n"
            f"/cancel - Cancel current operation",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_manga_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if not self.check_rate_limit(user_id):
            await update.message.reply_text("⏳ Thoda ruko... Request limit hit!")
            return
        
        query = update.message.text
        if query.startswith('/'):
            return
        
        status_msg = await update.message.reply_text(f"🔍 Searching for: **{query}**", parse_mode=ParseMode.MARKDOWN)
        
        try:
            results = await self.searcher.search_all_sites(query)
            
            if not results:
                await status_msg.edit_text("❌ Kuch nahi mila! Different spelling try karo.")
                return
            
            session_id = str(uuid.uuid4())[:8]
            self.user_sessions[user_id] = {
                'session_id': session_id,
                'results': results,
                'created_at': time.time()
            }
            
            keyboard = []
            for i, manga in enumerate(results[:10]):
                title = manga['title'][:35] + "..." if len(manga['title']) > 35 else manga['title']
                keyboard.append([InlineKeyboardButton(f"{i+1}. {title} ({manga['site']})", callback_data=f"manga_{i}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await status_msg.edit_text(f"📚 Found {len(results)} results:\nSelect one:", reply_markup=reply_markup)
            
        except Exception as e:
            await status_msg.edit_text(f"❌ Error: {str(e)}")
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        data = query.data
        
        if user_id not in self.user_sessions:
            await query.edit_message_text("❌ Session expired! Send manga name again.")
            return
        
        session = self.user_sessions[user_id]
        
        if data.startswith('manga_'):
            index = int(data.split('_')[1])
            selected = session['results'][index]
            session['selected'] = selected
            
            await query.edit_message_text(f"📖 Fetching chapters for: **{selected['title']}**", parse_mode=ParseMode.MARKDOWN)
            
            chapters = await self.searcher.get_manga_chapters(selected)
            
            if not chapters:
                await query.edit_message_text("❌ No chapters found!")
                return
            
            session['chapters'] = chapters
            session['total'] = len(chapters)
            
            # Show chapter buttons
            keyboard = []
            row = []
            for i in range(1, min(6, session['total']+1)):
                row.append(InlineKeyboardButton(str(i), callback_data=f"chap_{i}"))
            keyboard.append(row)
            
            if session['total'] > 5:
                row2 = []
                for i in range(6, min(11, session['total']+1)):
                    row2.append(InlineKeyboardButton(str(i), callback_data=f"chap_{i}"))
                keyboard.append(row2)
            
            keyboard.append([InlineKeyboardButton("📦 Download All", callback_data="chap_all")])
            keyboard.append([InlineKeyboardButton("📊 Queue Status", callback_data="queue_status"),
                           InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"📚 *{session['selected']['title']}*\nTotal: {session['total']} chapters\n\nSelect chapter:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
        
        elif data.startswith('chap_'):
            if data == 'chap_all':
                await self.queue_all(query, session)
            else:
                chap_num = int(data.split('_')[1])
                await self.add_to_queue(query, session, chap_num)
        
        elif data == 'queue_status':
            jobs = self.queue.get_user_jobs(user_id)
            if not jobs:
                await query.edit_message_text("📪 Queue empty!")
                return
            
            text = "**📊 Your Queue:**\n\n"
            for job in jobs[-10:]:
                status_emoji = {'queued': '⏳', 'processing': '🔄', 'completed': '✅', 'failed': '❌'}.get(job['status'], '📌')
                text += f"{status_emoji} {job['manga']['title'][:20]} Ch.{job['chapter']} - {job['status']}\n"
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
        
        elif data == 'cancel':
            self.user_sessions.pop(user_id, None)
            await query.edit_message_text("✅ Cancelled! Send manga name to start fresh.")
    
    async def add_to_queue(self, query, session, chapter_num):
        user_id = query.from_user.id
        
        if self.queue.get_user_active_count(user_id) >= Config.MAX_CONCURRENT:
            await query.edit_message_text(f"⚠️ Already {Config.MAX_CONCURRENT} jobs running! Wait for some to complete.")
            return
        
        chapter_url = session['chapters'][chapter_num-1]['url']
        job_id = self.queue.add_job(user_id, session['selected'], chapter_num, chapter_url)
        
        if not job_id:
            await query.edit_message_text("❌ Too many jobs!")
            return
        
        await query.edit_message_text(
            f"✅ Chapter {chapter_num} added to queue!\nJob ID: `{job_id}`\n\nUse /queue to check status",
            parse_mode=ParseMode.MARKDOWN
        )
        
        asyncio.create_task(self.process_queue())
    
    async def queue_all(self, query, session):
        user_id = query.from_user.id
        total = session['total']
        
        if total > Config.MAX_CHAPTERS:
            await query.edit_message_text(f"⚠️ Max {Config.MAX_CHAPTERS} chapters at a time!")
            return
        
        status_msg = await query.edit_message_text(f"📦 Adding {total} chapters to queue...")
        
        added = 0
        for i in range(1, total + 1):
            if self.queue.get_user_active_count(user_id) >= Config.MAX_CONCURRENT:
                break
            
            chapter_url = session['chapters'][i-1]['url']
            job_id = self.queue.add_job(user_id, session['selected'], i, chapter_url)
            
            if job_id:
                added += 1
                asyncio.create_task(self.process_queue())
            
            await asyncio.sleep(0.1)
        
        await status_msg.edit_text(f"✅ {added}/{total} chapters queued!\nUse /queue to check status")
    
    async def process_queue(self):
        while True:
            job = self.queue.get_next_job()
            if not job:
                break
            
            try:
                await self.process_job(job)
            except Exception as e:
                self.queue.update_job(job['job_id'], 'failed', error=str(e))
    
    async def process_job(self, job):
        job_id = job['job_id']
        user_id = job['user_id']
        
        try:
            self.queue.update_job(job_id, 'processing', progress=10)
            
            images = await self.searcher.get_chapter_images(job['chapter_url'])
            
            if not images:
                self.queue.update_job(job_id, 'failed', error="No images")
                return
            
            self.queue.update_job(job_id, 'processing', progress=30)
            
            downloaded = []
            for i, img_url in enumerate(images[:50]):
                path = self.file_manager.get_temp_path(job_id, f"page_{i:03d}.jpg")
                success = await self.file_manager.download_image(img_url, path)
                if success:
                    downloaded.append(path)
                
                if i % 10 == 0:
                    progress = 30 + int((i+1)/len(images)*40)
                    self.queue.update_job(job_id, 'processing', progress=progress)
            
            if not downloaded:
                self.queue.update_job(job_id, 'failed', error="Download failed")
                self.file_manager.cleanup(job_id)
                return
            
            self.queue.update_job(job_id, 'processing', progress=70)
            
            pdf_path = self.file_manager.get_temp_path(job_id, "output.pdf")
            success = await self.pdf_engine.create_pdf(downloaded, pdf_path)
            
            if not success:
                self.queue.update_job(job_id, 'failed', error="PDF failed")
                self.file_manager.cleanup(job_id)
                return
            
            self.queue.update_job(job_id, 'completed', progress=100)
            print(f"✅ Job {job_id} completed")
            
            # Cleanup after success
            self.file_manager.cleanup(job_id)
            
        except Exception as e:
            self.queue.update_job(job_id, 'failed', error=str(e))
            self.file_manager.cleanup(job_id)
    
    async def queue_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        jobs = self.queue.get_user_jobs(user_id)
        
        if not jobs:
            await update.message.reply_text("📪 Queue empty!")
            return
        
        text = "**📊 Your Queue:**\n\n"
        for job in jobs[-10:]:
            status_emoji = {'queued': '⏳', 'processing': '🔄', 'completed': '✅', 'failed': '❌'}.get(job['status'], '📌')
            text += f"{status_emoji} {job['manga']['title'][:20]} Ch.{job['chapter']} - {job['status']}\n"
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        self.user_sessions.pop(user_id, None)
        await update.message.reply_text("✅ Current operation cancelled!")

# ==================== MAIN FUNCTION ====================
def main():
    print("🚀 Starting Manga Verse Bot...")
    
    Config.validate()
    print(f"✅ Bot token: {Config.BOT_TOKEN[:10]}...")
    
    bot = MangaVerseBot()
    app = Application.builder().token(Config.BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("queue", bot.queue_command))
    app.add_handler(CommandHandler("cancel", bot.cancel_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_manga_search))
    app.add_handler(CallbackQueryHandler(bot.handle_callback))
    
    print("🤖 Bot is running! Press Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    main()
