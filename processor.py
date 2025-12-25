import os
import json
import time
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
    def __init__(self, filename="usage_tracking.json"):
        self.filename = filename
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
    def __init__(self):
        self.token = "token"
        self.primary_url = "https://dfk6l7c2y4o54057.aistudio-app.com/layout-parsing"
        self.secondary_url = "https://adc092i3obx2l114.aistudio-app.com/layout-parsing"
        self.headers = {
            "Authorization": f"token {self.token}",
            "Content-Type": "application/json"
        }

    def process_chunk(self, file_bytes: bytes, chunk_index: int) -> Dict:
        """
        Process a single PDF chunk. Tries primary URL first, then secondary on failure.
        """
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
                response = requests.post(url, json=payload, headers=self.headers, timeout=120)
                
                if response.status_code == 200:
                    result = response.json()
                    # Basic validation of response structure
                    if "result" in result and "layoutParsingResults" in result["result"]:
                        return result["result"]
                    else:
                        logger.warning(f"Unexpected response structure from {url}: {result}")
                else:
                    logger.warning(f"API {url} returned status {response.status_code}: {response.text}")
                    
            except Exception as e:
                logger.error(f"Error calling {url}: {str(e)}")
            
            # If we are here, the current URL failed. Proceed to the next one properly
            logger.info(f"Retrying with next available API endpoint...")

        raise Exception("All API endpoints failed.")

class PDFProcessor:
    def __init__(self):
        self.tracker = UsageTracker()
        self.api_client = APIClient()
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

        # Check quota
        if not self.tracker.check_limit(actual_pages):
            raise Exception(f"Daily limit reached. Usage: {self.tracker.get_todays_usage()}/3000")

        # Process chunks in parallel
        results = [None] * len(chunks)
        images_map = {} # path -> bytes
        
        markdown_sections = []

        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_index = {
                executor.submit(self.api_client.process_chunk, chunk_bytes, i): i 
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

        # Update usage
        self.tracker.add_usage(actual_pages)
        
        return final_markdown, images_map
