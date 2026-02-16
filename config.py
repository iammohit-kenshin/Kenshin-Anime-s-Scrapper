import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Telegram Bot Token (required)
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    
    # Temporary directory - auto cleanup
    TEMP_DIR = os.getenv("TEMP_DIR", "temp")
    
    # Default banners (optional)
    DEFAULT_BANNER1 = os.getenv("DEFAULT_BANNER1", "banners/default_banner1.jpg")
    DEFAULT_BANNER2 = os.getenv("DEFAULT_BANNER2", "banners/default_banner2.jpg")
    
    # Rate limiting (requests per minute per user)
    RATE_LIMIT = int(os.getenv("RATE_LIMIT", 5))
    
    # Max concurrent jobs per user
    MAX_CONCURRENT = 3
    
    @classmethod
    def validate(cls):
        if not cls.BOT_TOKEN:
            raise ValueError("BOT_TOKEN environment variable not set!")
        return True
