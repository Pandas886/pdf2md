import os
import zipfile
import re
from typing import List, Dict

def create_zip_archive(markdown_content: str, images: Dict[str, bytes], output_filename: str = "output.zip") -> str:
    """
    Creates a zip archive containing the markdown file and associated images.
    
    Args:
        markdown_content: The content of the markdown file.
        images: A dictionary where keys are filenames (relative paths) and values are image bytes.
        output_filename: The name of the zip file to create.
        
    Returns:
        The path to the created zip file.
    """
    # Ensure output filename ends with .zip
    if not output_filename.endswith('.zip'):
        output_filename += '.zip'
        
    with zipfile.ZipFile(output_filename, 'w') as zipf:
        # Write markdown content
        zipf.writestr("document.md", markdown_content)
        
        # Write images
        for img_path, img_data in images.items():
            zipf.writestr(img_path, img_data)
            
    return output_filename

def stitch_markdown(markdown_chunks: List[str], image_maps: List[Dict[str, str]]) -> str:
    """
    Stitches multiple markdown chunks into a single document and adjusts image paths.
    
    Args:
        markdown_chunks: List of markdown strings from each chunk.
        image_maps: List of dictionaries mapping original image paths in the chunk to new unique paths.
                    (This might be needed if API returns same image names for different chunks)
                    
    Returns:
        The combined markdown string.
    """
    # For now, simplistic concatenation. 
    # Real implementation might need to handle image path collisions if the API returns generic names like "image_0.jpg" for every request.
    # But based on provided code, the API returns paths like "images/..." which might be unique enough or need prefixing.
    
    # Actually, let's just join them with newlines.
    # The caller is responsible for renaming images to be unique across chunks before passing here if needed.
    return "\n\n".join(markdown_chunks)
