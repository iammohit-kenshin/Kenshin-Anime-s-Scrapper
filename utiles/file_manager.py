import os
import shutil
import asyncio
import time
from pathlib import Path

class FileManager:
    def __init__(self, temp_dir="temp"):
        self.temp_dir = temp_dir
        os.makedirs(temp_dir, exist_ok=True)
        
        # Start cleanup task
        asyncio.create_task(self.periodic_cleanup())
    
    def cleanup(self, job_id: str):
        """Clean up files for specific job"""
        job_dir = Path(f"{self.temp_dir}/{job_id}")
        if job_dir.exists():
            shutil.rmtree(job_dir)
    
    async def periodic_cleanup(self):
        """Clean up old files every hour"""
        while True:
            await asyncio.sleep(3600)  # 1 hour
            self.cleanup_old_files()
    
    def cleanup_old_files(self, max_age=3600):
        """Remove files older than max_age seconds"""
        now = time.time()
        
        for item in Path(self.temp_dir).iterdir():
            if item.is_file():
                # Check file age
                if now - item.stat().st_mtime > max_age:
                    item.unlink()
            elif item.is_dir():
                # Check directory age
                if now - item.stat().st_mtime > max_age:
                    shutil.rmtree(item)
    
    def get_temp_path(self, job_id: str, filename: str) -> str:
        """Get temporary file path"""
        job_dir = Path(f"{self.temp_dir}/{job_id}")
        job_dir.mkdir(exist_ok=True)
        return str(job_dir / filename)
