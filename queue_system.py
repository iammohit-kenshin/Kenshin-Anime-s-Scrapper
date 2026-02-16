import redis
import json
import asyncio
import time
from typing import Dict, List, Optional
import os

class QueueManager:
    def __init__(self):
        # Redis for queue (temporary, auto-expires)
        self.redis = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            password=os.getenv('REDIS_PASSWORD', ''),
            decode_responses=True,
            socket_connect_timeout=5
        )
        
        self.queue_key = "manga:queue"
        self.jobs_key = "manga:jobs"
        self.user_jobs_key = "manga:user:{}"
    
    async def add_job(self, user_id: int, manga: Dict, chapter: int, settings: Dict) -> str:
        """Add job to queue"""
        job_id = f"{user_id}_{int(time.time())}_{chapter}"
        
        job_data = {
            'job_id': job_id,
            'user_id': user_id,
            'manga': manga,
            'chapter': chapter,
            'settings': settings,
            'status': 'queued',
            'created_at': time.time(),
            'updated_at': time.time()
        }
        
        # Store job data (expires in 1 hour)
        self.redis.setex(
            f"{self.jobs_key}:{job_id}",
            3600,
            json.dumps(job_data)
        )
        
        # Add to queue
        self.redis.rpush(self.queue_key, job_id)
        
        # Add to user's jobs list
        self.redis.rpush(
            self.user_jobs_key.format(user_id),
            job_id
        )
        self.redis.expire(self.user_jobs_key.format(user_id), 3600)
        
        return job_id
    
    async def get_next_job(self) -> Optional[Dict]:
        """Get next job from queue"""
        job_id = self.redis.lpop(self.queue_key)
        if not job_id:
            return None
        
        job_data = self.redis.get(f"{self.jobs_key}:{job_id}")
        if not job_data:
            return None
        
        return json.loads(job_data)
    
    async def update_job(self, job_id: str, status: str, **kwargs):
        """Update job status"""
        job_data = self.redis.get(f"{self.jobs_key}:{job_id}")
        if job_data:
            job = json.loads(job_data)
            job['status'] = status
            job['updated_at'] = time.time()
            job.update(kwargs)
            
            self.redis.setex(
                f"{self.jobs_key}:{job_id}",
                3600,
                json.dumps(job)
            )
    
    async def get_job(self, job_id: str) -> Optional[Dict]:
        """Get job details"""
        job_data = self.redis.get(f"{self.jobs_key}:{job_id}")
        if job_data:
            return json.loads(job_data)
        return None
    
    async def get_user_jobs(self, user_id: int) -> List[Dict]:
        """Get all jobs for user"""
        job_ids = self.redis.lrange(
            self.user_jobs_key.format(user_id),
            0,
            -1
        )
        
        jobs = []
        for job_id in job_ids:
            job = await self.get_job(job_id)
            if job:
                jobs.append(job)
        
        return jobs
    
    async def cleanup_old_jobs(self):
        """Remove completed/failed jobs older than 1 hour"""
        # Redis handles this with EXPIRE
        pass
