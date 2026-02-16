"""
MANGA VERSE BOT - FIXED VERSION WITH MULTI-SOURCE
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
import re
import json
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
    RATE_LIMIT = 15
    MAX_CONCURRENT = 3
    MAX_CHAPTERS = 10
    
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

# ==================== MULTI-SOURCE MANGA SEARCHER ====================
class MangaSearcher:
    def __init__(self):
        self.session = None
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
    
    async def get_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession(headers=self.headers)
        return self.session
    
    async def search_elftoon_direct(self, url: str) -> Dict:
        """Direct manga info from URL"""
        try:
            session = await self.get_session()
            print(f"🔍 Direct URL: {url}")
            
            async with session.get(url, timeout=15, allow_redirects=True) as response:
                if response.status != 200:
                    return None
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Get title
                title_elem = soup.select_one('.post-title h1, .manga-title h1, h1.entry-title')
                title = title_elem.text.strip() if title_elem else "Unknown Title"
                
                # Get chapters - MULTIPLE METHODS
                chapters = []
                
                # METHOD 1: Look for JSON data in script tags
                scripts = soup.find_all('script')
                for script in scripts:
                    if script.string and 'wp-manga' in str(script.string):
                        # Try to extract chapter data
                        matches = re.findall(r'https?://[^\s"\']+\.(?:jpg|jpeg|png|webp)', str(script.string))
                        if matches:
                            print(f"Found {len(matches)} image URLs in script")
                
                # METHOD 2: Look for chapter list in HTML
                chapter_selectors = [
                    '.wp-manga-chapter a',
                    '.chapter-list a',
                    'li.wp-manga-chapter a',
                    '.reading-manga-chapter a',
                    'ul.main-chapter a',
                    '.chapter-item a'
                ]
                
                for selector in chapter_selectors:
                    chapter_links = soup.select(selector)
                    if chapter_links:
                        for link in chapter_links:
                            chap_url = link.get('href')
                            chap_title = link.text.strip()
                            if chap_url:
                                chapters.append({
                                    'title': chap_title or f"Chapter {len(chapters)+1}",
                                    'url': chap_url if chap_url.startswith('http') else 'https://elftoon.com' + chap_url
                                })
                        if chapters:
                            break
                
                # METHOD 3: Try to find hidden chapter data
                if not chapters:
                    # Look for any links containing 'chapter' in URL
                    all_links = soup.find_all('a', href=True)
                    for link in all_links:
                        href = link['href']
                        if 'chapter' in href.lower() or 'chapitre' in href.lower():
                            if href not in [c['url'] for c in chapters]:
                                chapters.append({
                                    'title': link.text.strip() or f"Chapter",
                                    'url': href if href.startswith('http') else 'https://elftoon.com' + href
                                })
                
                # Reverse to get ascending order
                chapters = chapters[::-1]
                
                # Add numbers
                for i, chap in enumerate(chapters, 1):
                    chap['number'] = i
                
                print(f"📚 Found {len(chapters)} chapters for {title}")
                
                return {
                    'title': title,
                    'url': url,
                    'site': 'Elftoon',
                    'chapters': chapters[:200]
                }
                
        except Exception as e:
            print(f"Direct URL error: {e}")
            return None
    
    async def search_alternative_sources(self, query: str) -> List[Dict]:
        """Search on multiple manga sites"""
        results = []
        
        # Source 1: Comix (from your screenshot)
        try:
            session = await self.get_session()
            comix_url = f"https://comix.{'com'}/search?q={query.replace(' ', '+')}"
            async with session.get(comix_url, timeout=10) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    # Parse Comix results
                    items = soup.select('.manga-item, .book-item')
                    for item in items[:5]:
                        title = item.select_one('h3 a, .title a')
                        if title:
                            results.append({
                                'title': title.text.strip(),
                                'url': title.get('href'),
                                'site': 'Comix'
                            })
        except:
            pass
        
        # Source 2: MangaBuddy (working)
        try:
            session = await self.get_session()
            mb_url = f"https://mangabuddy.com/search?q={query.replace(' ', '+')}"
            async with session.get(mb_url, timeout=10) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    items = soup.select('.book-item')
                    for item in items[:5]:
                        title = item.select_one('.book-title a')
                        if title:
                            results.append({
                                'title': title.text.strip(),
                                'url': title.get('href'),
                                'site': 'MangaBuddy'
                            })
        except:
            pass
        
        return results
    
    async def get_chapter_images_enhanced(self, chapter_url: str) -> List[str]:
        """Enhanced image extraction with multiple methods"""
        try:
            session = await self.get_session()
            print(f"🖼️ Getting images from: {chapter_url}")
            
            async with session.get(chapter_url, timeout=15) as response:
                if response.status != 200:
                    return []
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                images = []
                
                # METHOD 1: Look for JSON image data
                scripts = soup.find_all('script')
                for script in scripts:
                    if script.string:
                        # Look for image arrays in JavaScript
                        img_pattern = r'https?://[^\s"\']+\.(?:jpg|jpeg|png|webp)[^\s"\']*'
                        found_imgs = re.findall(img_pattern, str(script.string))
                        for img in found_imgs:
                            if img not in images and 'cover' not in img.lower():
                                images.append(img)
                
                # METHOD 2: Standard image selectors
                selectors = [
                    '.reading-content img',
                    '.chapter-content img',
                    '.manga-reading img',
                    'img[data-src]',
                    '.page-break img',
                    '.wp-manga-chapter-img',
                    'div.reading-content img',
                    'div.text-center img',
                    'img.wp-manga-chapter-img'
                ]
                
                for selector in selectors:
                    imgs = soup.select(selector)
                    for img in imgs:
                        src = img.get('src') or img.get('data-src') or img.get('data-lazy-src') or img.get('data-original')
                        if src:
                            # Clean URL
                            if src.startswith('//'):
                                src = 'https:' + src
                            elif src.startswith('/'):
                                src = 'https://elftoon.com' + src
                            
                            if src not in images and any(ext in src.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                                images.append(src)
                    
                    if images:
                        break
                
                # METHOD 3: Any image in the main content
                if not images:
                    content_div = soup.select_one('.reading-content, .chapter-content, .entry-content')
                    if content_div:
                        all_imgs = content_div.find_all('img')
                        for img in all_imgs:
                            src = img.get('src') or img.get('data-src')
                            if src and 'http' in src:
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
    
    def add_job(self, user_id: int, manga: Dict, chapter: Dict) -> Optional[str]:
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
            if now - self.last_request[user_id] < 2:
                return False
        self.last_request[user_id] = now
        return True
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        await update.message.reply_text(
            f"👋 **Namaste {user.first_name}!**\n\n"
            f"Main Manga Verse Bot hoon.\n\n"
            f"**Send:**\n"
            f"• Manga Name (e.g., 'Global Superpowers')\n"
            f"• Direct URL (e.g., elftoon.com/manga/...)\n\n"
            f"**Commands:**\n"
            f"/queue - Check queue\n"
            f"/cancel - Cancel current",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_manga_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        query = update.message.text.strip()
        
        if not self.check_rate_limit(user_id):
            await update.message.reply_text("⏳ Thoda ruko... 2 second wait karo!")
            return
        
        if query.startswith('/'):
            return
        
        status_msg = await update.message.reply_text(f"🔍 Processing: **{query}**", parse_mode=ParseMode.MARKDOWN)
        
        try:
            results = []
            
            # Check if it's a direct URL
            if 'elftoon.com' in query or 'mangabuddy.com' in query:
                manga_info = await self.searcher.search_elftoon_direct(query)
                if manga_info:
                    results = [manga_info]
            
            # If not URL or no results, search by name
            if not results:
                # Try alternative sources
                alt_results = await self.searcher.search_alternative_sources(query)
                results.extend(alt_results)
            
            if not results:
                await status_msg.edit_text(
                    "❌ Kuch nahi mila!\n\n"
                    "Try:\n"
                    "• Exact manga name\n"
                    "• Direct URL from elftoon.com\n"
                    "• Different spelling"
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
                site = manga.get('site', 'Unknown')
                keyboard.append([InlineKeyboardButton(f"{i+1}. {title} ({site})", callback_data=f"manga_{i}")])
            
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
            
            await query.edit_message_text(f"📖 Fetching details for: **{selected['title']}**", parse_mode=ParseMode.MARKDOWN)
            
            # If it's from direct URL, we already have chapters
            if 'chapters' in selected:
                chapters = selected['chapters']
            else:
                # Fetch chapters
                manga_info = await self.searcher.search_elftoon_direct(selected['url'])
                chapters = manga_info['chapters'] if manga_info else []
            
            if not chapters:
                await query.edit_message_text(
                    f"❌ No chapters found!\n\n"
                    f"URL: {selected['url']}\n"
                    f"This site might have anti-bot protection."
                )
                return
            
            session['selected'] = selected
            session['chapters'] = chapters
            
            # Show first 10 chapters
            keyboard = []
            
            # First row (chapters 1-5)
            row1 = []
            for chap in chapters[:5]:
                row1.append(InlineKeyboardButton(str(chap['number']), callback_data=f"chap_{chap['number']-1}"))
            keyboard.append(row1)
            
            # Second row (chapters 6-10)
            if len(chapters) > 5:
                row2 = []
                for chap in chapters[5:10]:
                    row2.append(InlineKeyboardButton(str(chap['number']), callback_data=f"chap_{chap['number']-1}"))
                keyboard.append(row2)
            
            # Options
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
            
            # Get images with enhanced method
            images = await self.searcher.get_chapter_images_enhanced(job['chapter']['url'])
            
            if not images:
                self.queue.update_job(job_id, 'failed')
                return
            
            self.queue.update_job(job_id, 'processing', progress=30)
            
            # Download images
            downloaded = []
            for i, img_url in enumerate(images[:30]):
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
