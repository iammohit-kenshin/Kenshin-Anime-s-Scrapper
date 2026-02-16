import os
import shutil
import asyncio
import time
from pathlib import Path
import aiofiles
import aiohttp

class FileManager:
    def __init__(self, temp_dir="temp"):
        self.temp_dir = temp_dir
        os.makedirs(temp_dir, exist_ok=True)
        print(f"📁 Temp directory: {temp_dir}")
    
    def get_temp_path(self, job_id: str, filename: str) -> str:
        """Get temporary file path"""
        job_dir = Path(f"{self.temp_dir}/{job_id}")
        job_dir.mkdir(exist_ok=True)
        return str(job_dir / filename)
    
    async def download_image(self, url: str, path: str) -> bool:
        """Download image from URL"""
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
        """Clean up files for specific job"""
        try:
            job_dir = Path(f"{self.temp_dir}/{job_id}")
            if job_dir.exists():
                shutil.rmtree(job_dir)
                print(f"🧹 Cleaned up: {job_id}")
        except Exception as e:
            print(f"Cleanup error: {e}")
    
    def cleanup_old_files(self, max_age=3600):
        """Remove files older than max_age seconds"""
        try:
            now = time.time()
            for item in Path(self.temp_dir).iterdir():
                if item.is_dir():
                    if now - item.stat().st_mtime > max_age:
                        shutil.rmtree(item)
                        print(f"🧹 Removed old dir: {item}")
        except Exception as e:
            print(f"Cleanup error: {e}")
    
    async def periodic_cleanup(self):
        """Run cleanup periodically"""
        while True:
            await asyncio.sleep(1800)  # Every 30 minutes
            self.cleanup_old_files()
