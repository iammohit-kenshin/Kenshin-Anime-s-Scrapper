import aiohttp
from bs4 import BeautifulSoup
import asyncio
from typing import List, Dict
import re

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
        """Search on all supported sites"""
        tasks = []
        for site_name, site_config in self.sites.items():
            tasks.append(self.search_site(site_name, site_config, query))
        
        results = await asyncio.gather(*tasks)
        
        # Flatten and sort by relevance
        all_results = []
        for site_results in results:
            all_results.extend(site_results)
        
        return all_results
    
    async def search_site(self, site_name: str, config: Dict, query: str) -> List[Dict]:
        """Search on specific site"""
        try:
            session = await self.get_session()
            search_url = config['search_url'].format(query.replace(' ', '+'))
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            async with session.get(search_url, headers=headers) as response:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                results = []
                
                if site_name == 'mangabuddy':
                    # Parse MangaBuddy results
                    items = soup.select('.book-item')
                    for item in items[:20]:
                        title_elem = item.select_one('.book-title a')
                        if title_elem:
                            results.append({
                                'title': title_elem.text.strip(),
                                'url': config['base_url'] + title_elem['href'],
                                'site': 'MangaBuddy',
                                'thumbnail': item.select_one('img')['src'] if item.select_one('img') else None
                            })
                
                elif site_name == 'elftoon':
                    # Parse Elftoon results
                    items = soup.select('.manga-item')
                    for item in items[:20]:
                        title_elem = item.select_one('.manga-title a')
                        if title_elem:
                            results.append({
                                'title': title_elem.text.strip(),
                                'url': title_elem['href'],
                                'site': 'Elftoon',
                                'thumbnail': item.select_one('img')['src'] if item.select_one('img') else None
                            })
                
                return results
                
        except Exception as e:
            print(f"Error searching {site_name}: {e}")
            return []
    
    async def get_manga_chapters(self, manga: Dict) -> List[Dict]:
        """Get all chapters for selected manga"""
        try:
            session = await self.get_session()
            
            headers = {'User-Agent': 'Mozilla/5.0'}
            async with session.get(manga['url'], headers=headers) as response:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                chapters = []
                
                if manga['site'] == 'MangaBuddy':
                    # Parse MangaBuddy chapters
                    items = soup.select('.chapter-list a')
                    for i, item in enumerate(items, 1):
                        chapters.append({
                            'number': i,
                            'title': item.text.strip() or f"Chapter {i}",
                            'url': item['href']
                        })
                
                elif manga['site'] == 'Elftoon':
                    # Parse Elftoon chapters
                    items = soup.select('.chapter-item a')
                    for i, item in enumerate(reversed(items), 1):
                        chapters.append({
                            'number': i,
                            'title': item.text.strip() or f"Chapter {i}",
                            'url': item['href']
                        })
                
                # Reverse to get ascending order
                return chapters[::-1]
                
        except Exception as e:
            print(f"Error getting chapters: {e}")
            return []
    
    async def get_chapter_images(self, chapter_url: str) -> List[str]:
        """Get all images for a chapter"""
        try:
            session = await self.get_session()
            headers = {'User-Agent': 'Mozilla/5.0'}
            
            async with session.get(chapter_url, headers=headers) as response:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                images = []
                
                # Try different selectors
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
                        src = img.get('src') or img.get('data-src')
                        if src and src not in images:
                            images.append(src)
                    
                    if images:
                        break
                
                return images
                
        except Exception as e:
            print(f"Error getting images: {e}")
            return []
