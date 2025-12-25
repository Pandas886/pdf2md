import os
import json
import time
import hashlib
import shutil
import base64
import requests
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date
from io import BytesIO
from typing import List, Dict, Tuple, Optional
from pypdf import PdfReader, PdfWriter

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class UsageTracker:
    def __init__(self, token: str):
        # Create a unique filename based on the token
        token_hash = hashlib.md5(token.encode()).hexdigest()[:8]
        self.filename = f"usage_tracking_{token_hash}.json"
        
        self.limit = 3000
        self._load()

    def _load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f:
                    self.data = json.load(f)
            except json.JSONDecodeError:
                self.data = {}
        else:
            self.data = {}

    def _save(self):
        with open(self.filename, 'w') as f:
            json.dump(self.data, f)

    def get_todays_usage(self) -> int:
        today_str = date.today().isoformat()
        return self.data.get(today_str, 0)

    def add_usage(self, pages: int):
        today_str = date.today().isoformat()
        current = self.data.get(today_str, 0)
        self.data[today_str] = current + pages
        self._save()

    def check_limit(self, pages_to_add: int) -> bool:
        return (self.get_todays_usage() + pages_to_add) <= self.limit

class APIClient:
    def __init__(self, token: str):
        self.token = token
        self.primary_url = "https://dfk6l7c2y4o54057.aistudio-app.com/layout-parsing"
        self.secondary_url = "https://adc092i3obx2l114.aistudio-app.com/layout-parsing"
        self.headers = {
            "Authorization": f"token {self.token}",
            "Content-Type": "application/json"
        }



    def process_chunk(self, file_bytes: bytes, chunk_index: int, pdf_hash: str, tracker: 'UsageTracker') -> Dict:
        """
        Process a single PDF chunk with caching and failover.
        """
        # Ensure cache directory exists
        cache_dir = os.path.join("cache", pdf_hash)
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, f"chunk_{chunk_index}.json")

        # Check cache
        if os.path.exists(cache_file):
            logger.info(f"Chunk {chunk_index} found in cache. Skipping API call.")
            with open(cache_file, 'r') as f:
                return json.load(f)

        file_data = base64.b64encode(file_bytes).decode("ascii")
        payload = {
            "file": file_data,
            "fileType": 0, # PDF
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useChartRecognition": False,
        }

        urls = [self.primary_url, self.secondary_url]
        
        for url in urls:
            try:
                logger.info(f"Processing chunk {chunk_index} with URL: {url}")
                response = requests.post(url, json=payload, headers=self.headers, timeout=300)
                
                if response.status_code == 200:
                    result = response.json()
                    # Basic validation of response structure
                    if "result" in result and "layoutParsingResults" in result["result"]:
                        # Save to cache
                        with open(cache_file, 'w') as f:
                            json.dump(result["result"], f)
                        
                        # Immediate usage update (10 pages per chunk)
                        # Note: This tracks *requests* made. If a chunk has <10 pages, it still counts as a chunk of work, 
                        # but strictly we should count actual pages. 
                        # However, for simplicity and safety, we can update by 10 or calculate exact page count of this chunk if needed.
                        # Given the split logic, most chunks are 10 pages. usage tracker updates total, let's allow passing chunk size.
                        # But here we don't have chunk size easily without parsing PDF bytes again. 
                        # Let's trust the Caller to handle total usage checks, BUT the requirement is "Timely update".
                        # So we should update here.
                        
                        # Better approach: We passed 'tracker' to this method.
                        # We know chunk size is roughly 10. Let's be conservative and say we update 10?
                        # Or better, just update based on the config. 
                        tracker.add_usage(10) 
                        
                        return result["result"]
                    else:
                        logger.warning(f"Unexpected response structure from {url}: {result}")
                else:
                    logger.warning(f"API {url} returned status {response.status_code}: {response.text}")
                    
            except Exception as e:
                logger.error(f"Error calling {url}: {str(e)}")
            
            # If we are here, the current URL failed. Proceed to the next one properly
            logger.info(f"Retrying with next available API endpoint...")
            time.sleep(1) # Small delay before retry

        raise Exception("All API endpoints failed.")

class PDFProcessor:
    def __init__(self, token: str):
        self.tracker = UsageTracker(token)
        self.api_client = APIClient(token)
        self.chunk_size = 10 # Pages per chunk

    def split_pdf(self, file_bytes: bytes) -> List[Tuple[int, bytes]]:
        """
        Splits PDF into chunks of `self.chunk_size` pages.
        Returns a list of (start_page_index, chunk_bytes).
        If > 100 pages, only takes the first 100.
        """
        reader = PdfReader(BytesIO(file_bytes))
        total_pages = len(reader.pages)
        
        # Cap at 100 pages if needed, as per user requirement to avoid timeouts
        # "若超过100页，API只解析前100页，后续页将被忽略。"
        # User updated requirement: Limit removed as chunking handles performance.
        pages_to_process = total_pages
        
        chunks = []
        for i in range(0, pages_to_process, self.chunk_size):
            writer = PdfWriter()
            # Calculate end page (exclusive)
            end = min(i + self.chunk_size, pages_to_process)
            
            for page_num in range(i, end):
                writer.add_page(reader.pages[page_num])
            
            out_stream = BytesIO()
            writer.write(out_stream)
            out_stream.seek(0)
            chunks.append((i, out_stream.read()))
            
        return chunks, total_pages

    def process_pdf(self, file_bytes: bytes, progress_callback=None):
        chunks, total_pages_in_pdf = self.split_pdf(file_bytes)
        
        # Calculate actual pages to be processed
        actual_pages = total_pages_in_pdf
        
        # Calculate hash for caching
        pdf_hash = hashlib.md5(file_bytes).hexdigest()

        # Check quota is effectively checked in loop or pre-check.
        # But for pre-check we still want to block if totally out.
        if not self.tracker.check_limit(0): # Just check if already over limit
             raise Exception(f"Daily limit reached. Usage: {self.tracker.get_todays_usage()}/3000")

        # Process chunks in parallel
        results = [None] * len(chunks)
        images_map = {} # path -> bytes
        
        markdown_sections = []

        # Reduced concurrency to 2 to avoid 429s and improve stability
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_to_index = {
                executor.submit(self.api_client.process_chunk, chunk_bytes, i, pdf_hash, self.tracker): i 
                for i, (start_page, chunk_bytes) in enumerate(chunks)
            }
            
            completed_count = 0
            for future in as_completed(future_to_index):
                i = future_to_index[future]
                try:
                    res = future.result()
                    results[i] = res
                except Exception as e:
                    logger.error(f"Chunk {i} failed: {e}")
                    # We continue other chunks? Or fail hard?
                    # If we fail hard, user can retry and resume from cache.
                    # Let's fail hard so user knows something is wrong.
                    raise e
                
                completed_count += 1
                if progress_callback:
                    progress_callback(completed_count / len(chunks))

        # Merge results
        # Result structure: {'layoutParsingResults': [{'markdown': {'text': '...', 'images': {'...': 'url'}}}]}
        # We need to stitch markdown and download images.
        
        final_markdown = ""
        
        for i, res in enumerate(results):
            if not res:
                continue
                
            chunk_markdown = ""
            for page_res in res["layoutParsingResults"]:
                text = page_res["markdown"]["text"]
                
                # Handle images
                page_images = page_res["markdown"]["images"] # path -> url
                
                for relative_path, img_url in page_images.items():
                    # Make path unique: images/img_0.jpg -> images/chunk_0_img_0.jpg
                    filename = os.path.basename(relative_path)
                    new_filename = f"chunk_{i}_{filename}"
                    new_path = os.path.join("images", new_filename)
                    
                    # Replace in text
                    text = text.replace(relative_path, new_path)
                    
                    # Download image
                    try:
                        img_data = requests.get(img_url).content
                        images_map[new_path] = img_data
                    except Exception as e:
                        logger.error(f"Failed to download image {img_url}: {e}")

                chunk_markdown += text + "\n\n"
            
            final_markdown += chunk_markdown

        # Update usage (removed bulk update since we update incrementally)
        # self.tracker.add_usage(actual_pages) 
        
        return final_markdown, images_map
