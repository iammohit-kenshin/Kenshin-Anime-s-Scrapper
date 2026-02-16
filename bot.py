"""
MANGA VERSE BOT - FIXED VERSION
10th Class Python Project
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
from typing import List, Dict, Optional
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    filters, ContextTypes, CallbackQueryHandler
)
from telegram.constants import ParseMode
from dotenv import load_dotenv

# ==================== CONFIG ====================
load_dotenv()

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    TEMP_DIR = "temp"
    RATE_LIMIT = 10  # Increased from 5 to 10
    MAX_CONCURRENT = 3
    MAX_CHAPTERS = 10  # Reduced from 20
    
    @classmethod
    def validate(cls):
        if not cls.BOT_TOKEN:
            raise ValueError("❌ BOT_TOKEN not set!")
        return True

# ==================== FILE MANAGER ====================
class FileManager:
    def __init__(self, temp_dir="temp"):
        self.temp_dir = temp_dir
        os.makedirs(temp_dir, exist_ok=True)
    
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

# ==================== MANGA SEARCHER - FIXED ====================
class MangaSearcher:
    def __init__(self):
        self.session = None
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
    
    async def get_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession(headers=self.headers)
        return self.session
    
    async def search_elftoon(self, query: str) -> List[Dict]:
        """Direct search on Elftoon with multiple methods"""
        try:
            session = await self.get_session()
            results = []
            
            # Method 1: Direct search
            search_url = f"https://elftoon.com/search?q={query.replace(' ', '+')}"
            print(f"🔍 Searching: {search_url}")
            
            async with session.get(search_url, timeout=15) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Try different selectors
                    items = soup.select('.page-item-detail, .manga-item, .c-tabs-item__content')
                    
                    for item in items:
                        title_elem = item.select_one('h3 a, .manga-title a, .post-title a')
                        if title_elem:
                            title = title_elem.text.strip()
                            url = title_elem.get('href')
                            if url and not url.startswith('http'):
                                url = 'https://elftoon.com' + url
                            
                            results.append({
                                'title': title,
                                'url': url,
                                'site': 'Elftoon'
                            })
            
            # Method 2: If no results, try direct manga page with keywords
            if not results:
                # Try to find by partial match
                base_url = "https://elftoon.com/manga/"
                keywords = query.lower().replace(' ', '-')
                possible_url = f"{base_url}{keywords}"
                
                async with session.get(possible_url, timeout=10) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        title_elem = soup.select_one('.post-title h1, .manga-title h1')
                        if title_elem:
                            results.append({
                                'title': title_elem.text.strip(),
                                'url': possible_url,
                                'site': 'Elftoon'
                            })
            
            return results[:10]
            
        except Exception as e:
            print(f"Elftoon search error: {e}")
            return []
    
    async def search_mangabuddy(self, query: str) -> List[Dict]:
        """Search on MangaBuddy"""
        try:
            session = await self.get_session()
            search_url = f"https://mangabuddy.com/search?q={query.replace(' ', '+')}"
            
            async with session.get(search_url, timeout=15) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    results = []
                    items = soup.select('.book-item')
                    
                    for item in items[:10]:
                        title_elem = item.select_one('.book-title a')
                        if title_elem:
                            title = title_elem.text.strip()
                            url = title_elem.get('href')
                            if url and not url.startswith('http'):
                                url = 'https://mangabuddy.com' + url
                            
                            results.append({
                                'title': title,
                                'url': url,
                                'site': 'MangaBuddy'
                            })
                    
                    return results
            return []
        except Exception as e:
            print(f"Mangabuddy error: {e}")
            return []
    
    async def search_all_sites(self, query: str) -> List[Dict]:
        """Search on all sites"""
        # Clean query
        query = query.strip()
        
        # Search both sites
        elftoon_results = await self.search_elftoon(query)
        mangabuddy_results = await self.search_mangabuddy(query)
        
        # Combine results
        all_results = elftoon_results + mangabuddy_results
        
        # If no results, try with simplified query (remove special chars)
        if not all_results:
            simplified = ''.join(e for e in query if e.isalnum() or e.isspace())
            if simplified != query:
                elftoon_results = await self.search_elftoon(simplified)
                mangabuddy_results = await self.search_mangabuddy(simplified)
                all_results = elftoon_results + mangabuddy_results
        
        return all_results[:15]
    
    async def get_manga_chapters(self, manga: Dict) -> List[Dict]:
        """Get all chapters for selected manga"""
        try:
            session = await self.get_session()
            print(f"📖 Fetching chapters from: {manga['url']}")
            
            async with session.get(manga['url'], timeout=15) as response:
                if response.status != 200:
                    return []
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                chapters = []
                
                if manga['site'] == 'Elftoon':
                    # Try different selectors for Elftoon
                    chapter_items = soup.select('.wp-manga-chapter a, .chapter-item a, ul.chapter-list li a')
                    
                    for item in chapter_items:
                        chap_url = item.get('href')
                        if chap_url:
                            chap_title = item.text.strip() or "Chapter"
                            chapters.append({
                                'title': chap_title,
                                'url': chap_url if chap_url.startswith('http') else 'https://elftoon.com' + chap_url
                            })
                    
                    # Reverse to get ascending order
                    chapters = chapters[::-1]
                    
                elif manga['site'] == 'MangaBuddy':
                    chapter_items = soup.select('.chapter-list a, ul.chapter-list li a')
                    
                    for item in chapter_items:
                        chap_url = item.get('href')
                        if chap_url:
                            chap_title = item.text.strip() or "Chapter"
                            chapters.append({
                                'title': chap_title,
                                'url': chap_url if chap_url.startswith('http') else 'https://mangabuddy.com' + chap_url
                            })
                
                # Add numbers to chapters
                for i, chap in enumerate(chapters, 1):
                    chap['number'] = i
                
                return chapters[:200]  # Max 200 chapters
                
        except Exception as e:
            print(f"Error getting chapters: {e}")
            return []
    
    async def get_chapter_images(self, chapter_url: str) -> List[str]:
        """Get all images for a chapter"""
        try:
            session = await self.get_session()
            print(f"🖼️ Getting images from: {chapter_url}")
            
            async with session.get(chapter_url, timeout=15) as response:
                if response.status != 200:
                    return []
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                images = []
                
                # Try multiple selectors for images
                selectors = [
                    '.reading-content img',
                    '.chapter-content img',
                    '.manga-reading img',
                    'img[data-src]',
                    '.page-break img',
                    '.wp-manga-chapter-img',
                    'div.reading-content p img',
                    'img.wp-manga-chapter-img'
                ]
                
                for selector in selectors:
                    imgs = soup.select(selector)
                    for img in imgs:
                        src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                        if src:
                            # Clean URL
                            if src.startswith('//'):
                                src = 'https:' + src
                            elif src.startswith('/'):
                                src = 'https://elftoon.com' + src
                            
                            if src not in images and ('jpg' in src or 'jpeg' in src or 'png' in src or 'webp' in src):
                                images.append(src)
                    
                    if images:
                        break
                
                # If still no images, try to find any image in the content
                if not images:
                    all_imgs = soup.find_all('img')
                    for img in all_imgs:
                        src = img.get('src') or img.get('data-src')
                        if src and 'http' in src and ('jpg' in src or 'jpeg' in src or 'png' in src):
                            images.append(src)
                
                print(f"📸 Found {len(images)} images")
                return images[:50]  # Max 50 pages
                
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
            print(f"PDF error: {e}")
            return False

# ==================== SIMPLE QUEUE ====================
class SimpleQueue:
    def __init__(self, expiry=3600):
        self.jobs = {}
        self.user_jobs = defaultdict(list)
        self.processing = set()
    
    def add_job(self, user_id: int, manga: Dict, chapter: Dict, settings: Dict = None) -> Optional[str]:
        # Count active jobs
        active = sum(1 for j in self.user_jobs[user_id] 
                    if j in self.jobs and self.jobs[j]['status'] in ['queued', 'processing'])
        
        if active >= Config.MAX_CONCURRENT:
            return None
        
        job_id = str(uuid.uuid4())[:8]
        
        job_data = {
            'job_id': job_id,
            'user_id': user_id,
            'manga': manga,
            'chapter': chapter,
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
        return [self.jobs[jid] for jid in self.user_jobs[user_id] if jid in self.jobs]
    
    def get_user_active_count(self, user_id: int) -> int:
        return sum(1 for j in self.user_jobs[user_id] 
                  if j in self.jobs and self.jobs[j]['status'] in ['queued', 'processing'])

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
        print("✅ Bot initialized!")
    
    def check_rate_limit(self, user_id: int) -> bool:
        now = time.time()
        if user_id in self.last_request:
            if now - self.last_request[user_id] < 2:  # 2 seconds between requests
                return False
        self.last_request[user_id] = now
        return True
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        await update.message.reply_text(
            f"👋 **Namaste {user.first_name}!**\n\n"
            f"Main Manga Verse Bot hoon. Bas manga ka naam bhejo, "
            f"main dhundh kar PDF bhej dunga!\n\n"
            f"**Example:** 'Global Superpowers' ya 'Solo Leveling'\n\n"
            f"**Commands:**\n"
            f"/queue - Check queue\n"
            f"/cancel - Cancel current",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_manga_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if not self.check_rate_limit(user_id):
            await update.message.reply_text("⏳ Thoda ruko... 2 second wait karo!")
            return
        
        query = update.message.text
        if query.startswith('/'):
            return
        
        status_msg = await update.message.reply_text(f"🔍 Searching for: **{query}**", parse_mode=ParseMode.MARKDOWN)
        
        try:
            results = await self.searcher.search_all_sites(query)
            
            if not results:
                # Try with direct URL
                if 'elftoon.com' in query or 'mangabuddy.com' in query:
                    # User ne direct URL diya hai
                    site = 'Elftoon' if 'elftoon' in query else 'MangaBuddy'
                    results = [{
                        'title': 'Direct Link',
                        'url': query,
                        'site': site
                    }]
                else:
                    await status_msg.edit_text(
                        "❌ Kuch nahi mila!\n\n"
                        "Tips:\n"
                        "• Exact naam likho\n"
                        "• Direct URL bhejo\n"
                        "• Different spelling try karo"
                    )
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
                keyboard.append([InlineKeyboardButton(f"{i+1}. {title}", callback_data=f"manga_{i}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await status_msg.edit_text(
                f"📚 Found {len(results)} results:\nSelect one:",
                reply_markup=reply_markup
            )
            
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
                await query.edit_message_text(
                    f"❌ No chapters found!\n\n"
                    f"URL: {selected['url']}\n"
                    f"Site: {selected['site']}"
                )
                return
            
            session['chapters'] = chapters
            
            # Show first 10 chapters
            keyboard = []
            row = []
            for i, chap in enumerate(chapters[:5], 1):
                row.append(InlineKeyboardButton(str(i), callback_data=f"chap_{i-1}"))
            keyboard.append(row)
            
            if len(chapters) > 5:
                row2 = []
                for i, chap in enumerate(chapters[5:10], 6):
                    row2.append(InlineKeyboardButton(str(i), callback_data=f"chap_{i-1}"))
                keyboard.append(row2)
            
            keyboard.append([InlineKeyboardButton("📦 Download All", callback_data="chap_all")])
            keyboard.append([InlineKeyboardButton("📊 Queue Status", callback_data="queue_status")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"📚 *{selected['title']}*\nTotal: {len(chapters)} chapters\n\nSelect chapter:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
        
        elif data.startswith('chap_'):
            if data == 'chap_all':
                await self.queue_all(query, session)
            else:
                chap_index = int(data.split('_')[1])
                await self.add_to_queue(query, session, chap_index)
        
        elif data == 'queue_status':
            jobs = self.queue.get_user_jobs(user_id)
            if not jobs:
                await query.edit_message_text("📪 Queue empty!")
                return
            
            text = "**📊 Your Queue:**\n\n"
            for job in jobs[-5:]:
                emoji = {'queued': '⏳', 'processing': '🔄', 'completed': '✅', 'failed': '❌'}.get(job['status'], '📌')
                text += f"{emoji} Ch.{job['chapter']['number']} - {job['status']}\n"
                if job['status'] == 'processing' and job.get('progress'):
                    text += f"   Progress: {job['progress']}%\n"
            
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    
    async def add_to_queue(self, query, session, chap_index):
        user_id = query.from_user.id
        chapter = session['chapters'][chap_index]
        
        if self.queue.get_user_active_count(user_id) >= Config.MAX_CONCURRENT:
            await query.edit_message_text(f"⚠️ Already {Config.MAX_CONCURRENT} jobs running!")
            return
        
        job_id = self.queue.add_job(user_id, session['selected'], chapter)
        
        if not job_id:
            await query.edit_message_text("❌ Too many jobs!")
            return
        
        await query.edit_message_text(
            f"✅ Chapter {chapter['number']} added to queue!\n"
            f"Job ID: `{job_id}`\n\n"
            f"Use /queue to check status",
            parse_mode=ParseMode.MARKDOWN
        )
        
        asyncio.create_task(self.process_queue())
    
    async def queue_all(self, query, session):
        user_id = query.from_user.id
        chapters = session['chapters']
        
        if len(chapters) > Config.MAX_CHAPTERS:
            await query.edit_message_text(f"⚠️ Max {Config.MAX_CHAPTERS} chapters at a time!")
            return
        
        await query.edit_message_text(f"📦 Adding {len(chapters)} chapters to queue...")
        
        added = 0
        for chapter in chapters[:Config.MAX_CHAPTERS]:
            if self.queue.get_user_active_count(user_id) >= Config.MAX_CONCURRENT:
                break
            
            job_id = self.queue.add_job(user_id, session['selected'], chapter)
            if job_id:
                added += 1
                asyncio.create_task(self.process_queue())
            
            await asyncio.sleep(0.5)
        
        await query.edit_message_text(f"✅ {added} chapters queued!\nUse /queue to check status")
    
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
        
        try:
            self.queue.update_job(job_id, 'processing', progress=10)
            
            # Get images
            images = await self.searcher.get_chapter_images(job['chapter']['url'])
            
            if not images:
                self.queue.update_job(job_id, 'failed')
                return
            
            self.queue.update_job(job_id, 'processing', progress=30)
            
            # Download images
            downloaded = []
            for i, img_url in enumerate(images[:30]):  # Max 30 pages for speed
                path = self.file_manager.get_temp_path(job_id, f"page_{i:03d}.jpg")
                success = await self.file_manager.download_image(img_url, path)
                if success:
                    downloaded.append(path)
                
                if i % 5 == 0:
                    progress = 30 + int((i+1)/len(images)*40)
                    self.queue.update_job(job_id, 'processing', progress=progress)
            
            if not downloaded:
                self.queue.update_job(job_id, 'failed')
                self.file_manager.cleanup(job_id)
                return
            
            self.queue.update_job(job_id, 'processing', progress=70)
            
            # Create PDF
            pdf_path = self.file_manager.get_temp_path(job_id, "output.pdf")
            success = await self.pdf_engine.create_pdf(downloaded, pdf_path)
            
            if not success:
                self.queue.update_job(job_id, 'failed')
                self.file_manager.cleanup(job_id)
                return
            
            self.queue.update_job(job_id, 'completed', progress=100)
            print(f"✅ Job {job_id} completed")
            
            # Cleanup
            self.file_manager.cleanup(job_id)
            
        except Exception as e:
            print(f"Job error: {e}")
            self.queue.update_job(job_id, 'failed')
            self.file_manager.cleanup(job_id)
    
    async def queue_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        jobs = self.queue.get_user_jobs(user_id)
        
        if not jobs:
            await update.message.reply_text("📪 Queue empty!")
            return
        
        text = "**📊 Your Queue:**\n\n"
        for job in jobs[-5:]:
            emoji = {'queued': '⏳', 'processing': '🔄', 'completed': '✅', 'failed': '❌'}.get(job['status'], '📌')
            text += f"{emoji} Ch.{job['chapter']['number']} - {job['status']}\n"
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        self.user_sessions.pop(user_id, None)
        await update.message.reply_text("✅ Cancelled!")

# ==================== MAIN ====================
def main():
    print("🚀 Starting Manga Verse Bot...")
    Config.validate()
    
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
