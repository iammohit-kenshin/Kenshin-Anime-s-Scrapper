import requests
from bs4 import BeautifulSoup
import os
import img2pdf
import shutil
import re

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'}

def get_chapters(url):
    try:
        r = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(r.content, 'html.parser')
        chapters = []
        if "mangabuddy.com" in url:
            items = soup.find_all('li', class_=re.compile(r'chapter-item|list-item'))
            for li in items:
                a = li.find('a')
                if a:
                    name = a.find('strong').text.strip() if a.find('strong') else a.text.strip()
                    chapters.append({"name": name, "url": "https://mangabuddy.com" + a.get('href')})
        elif "elftoon.com" in url:
            listing = soup.find_all('li', class_='wp-manga-chapter')
            for li in listing:
                a = li.find('a')
                if a: chapters.append({"name": a.text.strip(), "url": a.get('href')})
        return chapters[::-1]
    except: return []

def download_chapter(url, chapter_name):
    try:
        r = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(r.content, 'html.parser')
        folder = f"temp_{re.sub(r'\W+', '', chapter_name)}"
        os.makedirs(folder, exist_ok=True)
        image_paths = []
        img_tags = soup.find_all('img', class_=re.compile(r'wp-manga-chapter-img|img-responsive'))
        for i, img in enumerate(img_tags):
            img_url = img.get('data-src') or img.get('data-lazy-src') or img.get('src')
            if img_url:
                img_url = img_url.strip()
                if img_url.startswith('//'): img_url = 'https:' + img_url
                img_data = requests.get(img_url, headers=HEADERS, timeout=10).content
                path = f"{folder}/{i:03d}.jpg"
                with open(path, 'wb') as f: f.write(img_data)
                image_paths.append(path)
        if not image_paths: return None
        pdf_path = f"{chapter_name}.pdf"
        with open(pdf_path, "wb") as f: f.write(img2pdf.convert(sorted(image_paths)))
        shutil.rmtree(folder)
        return pdf_path
    except: return None
