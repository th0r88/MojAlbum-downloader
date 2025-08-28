#!/usr/bin/env python3
"""
MojAlbum Photo Downloader
Downloads all photos from a mojalbum.com album with pagination support
Handles both photos with and without descriptions

Requirements: pip install requests beautifulsoup4
"""

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as e:
    print("Missing required packages. Please install them:")
    print("pip install requests beautifulsoup4")
    print("\nOr if using a virtual environment:")
    print("python3 -m venv mojalbum_env")
    print("source mojalbum_env/bin/activate")
    print("pip install requests beautifulsoup4")
    exit(1)

import re
import os
from urllib.parse import urljoin, urlparse
import time
from pathlib import Path

class MojAlbumDownloader:
    def __init__(self, album_url, download_dir=None):
        self.album_url = album_url.rstrip('/')  # Remove trailing slash
        
        # Extract album info from URL for folder naming
        album_info = self.extract_album_info(album_url)
        if download_dir is None:
            download_dir = f"{album_info['user']}_{album_info['album']}_photos"
        
        self.download_dir = Path(download_dir)
        self.album_info = album_info
        self.session = requests.Session()
        # Add headers to mimic a real browser
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # Create download directory
        self.download_dir.mkdir(exist_ok=True)
    
    def extract_album_info(self, url):
        """Extract user and album name from URL"""
        # URL format: https://mojalbum.com/user/album
        parts = url.rstrip('/').split('/')
        if len(parts) >= 4:
            user = parts[-2]
            album = parts[-1]
            return {'user': user, 'album': album}
        else:
            return {'user': 'unknown', 'album': 'album'}
    
    def detect_album_pattern(self, soup):
        """Detect the URL pattern for this specific album"""
        # Find any thumbnail image to extract the pattern
        for img in soup.find_all('img', src=True):
            src = img['src']
            if '_t.jpg' in src and 'mojalbum.com' in src:
                # Extract the pattern: https://s6.mojalbum.com/5372926_5372935_PHOTOID/album/PHOTOID_t.jpg
                pattern_regex = r'https://s(\d+)\.mojalbum\.com/([^/]+)/([^/]+)/([^/]+)_t\.jpg'
                match = re.search(pattern_regex, src)
                if match:
                    server_num = match.group(1)
                    middle_part = match.group(2).rsplit('_', 1)[0]  # Remove the photo ID from the end
                    album_path = match.group(3)
                    return {
                        'server': server_num,
                        'middle_part': middle_part,
                        'album_path': album_path
                    }
        return None
    
    def construct_direct_url(self, photo_info, pattern):
        """Construct direct photo URL using detected pattern"""
        photo_id = photo_info['id']
        server = pattern['server']
        middle = pattern['middle_part']
        album = pattern['album_path']
        
        if photo_info['has_description']:
            # For photos with descriptions: .../MIDDLE_ID/album/description.jpg
            description = photo_info['description']
            return f"https://s{server}.mojalbum.com/{middle}_{photo_id}/{album}/{description}.jpg"
        else:
            # For photos without descriptions: .../MIDDLE_ID/album/ID.jpg
            return f"https://s{server}.mojalbum.com/{middle}_{photo_id}/{album}/{photo_id}.jpg"
    
    def get_photo_ids(self):
        """Extract all photo IDs by finding thumbnail images across all pages"""
        photo_ids = []
        page = 1
        max_pages = 20  # Increased safety limit
        url_pattern = None
        
        while page <= max_pages:
            # Construct page URL
            if page == 1:
                page_url = self.album_url
            else:
                page_url = f"{self.album_url}/{page}"
            
            print(f"Fetching page {page}: {page_url}")
            
            try:
                response = self.session.get(page_url)
                response.raise_for_status()
            except requests.RequestException as e:
                print(f"Error fetching page {page}: {e}")
                break
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Detect URL pattern from first page
            if page == 1:
                url_pattern = self.detect_album_pattern(soup)
                if not url_pattern:
                    print("Could not detect album URL pattern!")
                    return [], None
                print(f"Detected pattern: server s{url_pattern['server']}, album path: {url_pattern['album_path']}")
            
            page_photo_ids = []
            
            # Find thumbnail images on this page, but exclude "podobni oglasi" section
            for img in soup.find_all('img', src=True):
                src = img['src']
                # Look for thumbnail pattern - any image with _t.jpg that matches our album
                if '_t.jpg' in src and 'mojalbum.com' in src:
                    # Check if this image is inside the "podobni oglasi" section
                    # Look for parent with id="ClassifiedRecommendationsInner"
                    parent_element = img
                    is_similar_ad = False
                    
                    # Traverse up the DOM tree to check for ClassifiedRecommendationsInner
                    for _ in range(15):  # Check up to 15 levels up
                        parent_element = parent_element.parent
                        if parent_element is None:
                            break
                        
                        # Check if this parent has the ClassifiedRecommendationsInner id
                        if parent_element.get('id') == 'ClassifiedRecommendationsInner':
                            is_similar_ad = True
                            break
                    
                    # Skip if this is in similar ads section
                    if is_similar_ad:
                        continue
                    
                    # Extract information from the thumbnail URL
                    # Pattern: https://s1.mojalbum.com/17375821_18344670_25430895/zimsko-za-deklico-bunde-skornji-50/filename_t.jpg
                    # Two cases:
                    # 1. filename is just ID: "25425283_t.jpg" -> photo ID is 25425283
                    # 2. filename has description: "crane-dekliska-smucarska-ocala-8-eur_t.jpg" -> extract ID from URL path
                    
                    # First try to get photo ID from filename
                    filename_pattern = r'/(\d+)_t\.jpg$'
                    id_from_filename = re.search(filename_pattern, src)
                    if id_from_filename:
                        photo_id = id_from_filename.group(1)
                        photo_info = {'id': photo_id, 'has_description': False}
                        page_photo_ids.append(photo_info)
                    else:
                        # If filename doesn't contain ID, extract from URL path
                        # URL structure: .../MIDDLE_PART_ID/album-path/description_t.jpg
                        url_parts_pattern = r'/([^/]+_\d+)/[^/]+/([^/]+)_t\.jpg$'
                        url_parts_match = re.search(url_parts_pattern, src)
                        if url_parts_match:
                            middle_part_with_id = url_parts_match.group(1)
                            description = url_parts_match.group(2)
                            # Extract ID from the middle part (last number after underscore)
                            id_pattern = r'_(\d+)$'
                            id_match = re.search(id_pattern, middle_part_with_id)
                            if id_match:
                                photo_id = id_match.group(1)
                                photo_info = {'id': photo_id, 'has_description': True, 'description': description}
                                page_photo_ids.append(photo_info)
            
            if not page_photo_ids:
                print(f"No photos found on page {page}, stopping pagination")
                break
            
            print(f"Found {len(page_photo_ids)} photos on page {page}")
            photo_ids.extend(page_photo_ids)
            
            page += 1
            
            # Add a small delay between page requests
            time.sleep(0.5)
        
        print(f"Total photos found across all pages: {len(photo_ids)}")
        return photo_ids, url_pattern
    
    def download_photo(self, photo_url, photo_id):
        """Download a single photo"""
        try:
            print(f"Downloading photo {photo_id}...")
            response = self.session.get(photo_url)
            response.raise_for_status()
            
            filename = f"{photo_id}.jpg"
            filepath = self.download_dir / filename
            
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            print(f"✓ Downloaded: {filename}")
            return True
            
        except requests.RequestException as e:
            print(f"✗ Failed to download {photo_id}: {e}")
            return False
    
    def download_all(self, delay=1):
        """Download all photos from the album"""
        result = self.get_photo_ids()
        if len(result) == 2:
            photo_ids, url_pattern = result
        else:
            print("Failed to get photo information")
            return
        
        if not photo_ids or not url_pattern:
            print("No photos found!")
            return
        
        successful_downloads = 0
        failed_downloads = 0
        
        print(f"\n=== Starting Downloads ===")
        print(f"Album: {self.album_info['user']}/{self.album_info['album']}")
        print(f"Total photos to download: {len(photo_ids)}")
        print(f"Download folder: {self.download_dir.absolute()}")
        print()
        
        for i, photo_info in enumerate(photo_ids, 1):
            photo_id = photo_info['id']
            has_description = photo_info.get('has_description', False)
            description_text = f" ({photo_info.get('description', 'no description')})" if has_description else ""
            
            print(f"Processing photo {i}/{len(photo_ids)} (ID: {photo_id}){description_text}")
            
            # Check if file already exists
            filename = f"{photo_id}.jpg"
            filepath = self.download_dir / filename
            if filepath.exists():
                print(f"Skipping {filename} (already exists)")
                continue
            
            direct_url = self.construct_direct_url(photo_info, url_pattern)
            
            if self.download_photo(direct_url, photo_id):
                successful_downloads += 1
            else:
                failed_downloads += 1
            
            # Be polite to the server
            if delay > 0 and i < len(photo_ids):
                time.sleep(delay)
        
        print(f"\n=== Download Summary ===")
        print(f"Successful: {successful_downloads}")
        print(f"Failed: {failed_downloads}")
        print(f"Total: {len(photo_ids)}")
        print(f"Photos saved to: {self.download_dir.absolute()}")


def get_user_input():
    """Get album URL from user with validation"""
    print("MojAlbum Photo Downloader")
    print("=" * 40)
    print("⚠️  POMEMBNO: Mojalbum bo 24. oktobra 2025 prenehal z delovanjem!")
    print("   Uporabite to orodje za varnostno kopiranje vaših foto albumov, preden jih izgubite.")
    print()
    
    while True:
        album_url = input("Vnesite URL vašega MojAlbuma (npr. https://mojalbum.com/uporabnik/album): ").strip()
        
        if not album_url:
            print("Prosimo, vnesite URL.")
            continue
            
        # Add https:// if missing
        if not album_url.startswith('http'):
            album_url = 'https://' + album_url
        
        # Validate URL format
        if 'mojalbum.com' not in album_url:
            print("Prosimo, vnesite veljaven MojAlbum URL.")
            continue
            
        # Remove any page numbers from URL
        page_pattern = r'/\d+$'
        album_url = re.sub(page_pattern, '', album_url)
        
        print(f"URL albuma: {album_url}")
        confirm = input("Je to pravilno? (d/n): ").strip().lower()
        
        if confirm in ['d', 'da', 'y', 'yes', '']:
            return album_url

def main():
    try:
        album_url = get_user_input()
        
        print(f"\nInicializacija prenašalca za: {album_url}")
        downloader = MojAlbumDownloader(album_url)
        
        # Ask about download delay
        print(f"\nPriporočena zakasnitev med prenosi: 1 sekunda (da smo spoštljivi do strežnika)")
        delay_input = input("Vnesite zakasnitev v sekundah (pritisnite Enter za 1 sekundo): ").strip()
        
        try:
            delay = float(delay_input) if delay_input else 1.0
        except ValueError:
            delay = 1.0
            print("Neveljavni vnos, uporabljam 1 sekundo zakasnitve")
        
        print(f"Uporabljam {delay} sekund zakasnitve med prenosi")
        
        downloader.download_all(delay=delay)
        
    except KeyboardInterrupt:
        print("\n\nPrenos preklican s strani uporabnika.")
    except Exception as e:
        print(f"\nPrišlo je do napake: {e}")
        print("Prosimo, poskusite znova ali prijavite to težavo.")


if __name__ == "__main__":
    main()
