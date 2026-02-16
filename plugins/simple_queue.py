import time
import uuid
from typing import Dict, List, Optional
from collections import defaultdict

class SimpleQueue:
    def __init__(self, expiry=3600):
        self.jobs = {}
        self.user_jobs = defaultdict(list)
        self.processing = set()
        self.expiry = expiry
    
    def add_job(self, user_id: int, manga: Dict, chapter: int, settings: Dict) -> str:
        """Add job to queue"""
        # Check active jobs
        active = self.get_user_active_count(user_id)
        if active >= 5:
            return None
        
        job_id = str(uuid.uuid4())[:8]
        
        job_data = {
            'job_id': job_id,
            'user_id': user_id,
            'manga': manga,
            'chapter': chapter,
            'chapter_url': manga['chapters'][chapter-1]['url'] if manga.get('chapters') else None,
            'settings': settings.copy() if settings else {},
            'status': 'queued',
            'created_at': time.time(),
            'updated_at': time.time(),
            'progress': 0
        }
        
        self.jobs[job_id] = job_data
        self.user_jobs[user_id].append(job_id)
        
        return job_id
    
    def get_next_job(self) -> Optional[Dict]:
        """Get next job from queue"""
        for job_id, job in self.jobs.items():
            if job['status'] == 'queued' and job_id not in self.processing:
                self.processing.add(job_id)
                job['status'] = 'processing'
                job['updated_at'] = time.time()
                return job.copy()
        return None
    
    def update_job(self, job_id: str, status: str, **kwargs):
        """Update job status"""
        if job_id in self.jobs:
            self.jobs[job_id]['status'] = status
            self.jobs[job_id]['updated_at'] = time.time()
            self.jobs[job_id].update(kwargs)
            
            if status in ['completed', 'failed', 'cancelled']:
                if job_id in self.processing:
                    self.processing.remove(job_id)
    
    def get_job(self, job_id: str) -> Optional[Dict]:
        """Get job details"""
        return self.jobs.get(job_id)
    
    def get_user_jobs(self, user_id: int) -> List[Dict]:
        """Get all jobs for user"""
        job_ids = self.user_jobs.get(user_id, [])
        jobs = []
        for job_id in job_ids:
            if job_id in self.jobs:
                jobs.append(self.jobs[job_id])
        return jobs
    
    def get_user_active_count(self, user_id: int) -> int:
        """Count active jobs for user"""
        count = 0
        for job_id in self.user_jobs.get(user_id, []):
            if job_id in self.jobs and self.jobs[job_id]['status'] in ['queued', 'processing']:
                count += 1
        return count
    
    def cancel_job(self, user_id: int, job_id: str) -> bool:
        """Cancel a job"""
        if job_id in self.jobs and self.jobs[job_id]['user_id'] == user_id:
            if self.jobs[job_id]['status'] in ['queued', 'processing']:
                self.update_job(job_id, 'cancelled')
                return True
        return False
