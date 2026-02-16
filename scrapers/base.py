from abc import ABC, abstractmethod

class BaseScraper(ABC):
    @abstractmethod
    async def search(self, query):
        pass
    
    @abstractmethod
    async def get_chapters(self, url):
        pass
    
    @abstractmethod
    async def get_images(self, url):
        pass
