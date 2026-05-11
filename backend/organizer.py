import os
import re
import shutil

BASE_DIR = "/home/workspace/SecondBrain/Literature"

def sanitize_filename(name):
    # Remove invalid filename characters
    return re.sub(r'[\\/*?:"<>|]', "", name)

def organize_paper(source_file, title, authors, year, source="General"):
    """
    Moves the downloaded paper into the structured SecondBrain Literature folder.
    Format: /home/workspace/SecondBrain/Literature/<Source>/<Year> - <Title>.pdf
    """
    if not os.path.exists(source_file):
        print(f"Error: Source file {source_file} not found.")
        return None

    # Sanitize metadata for filesystem
    safe_title = sanitize_filename(title)
    
    # Construct target directory
    target_dir = os.path.join(BASE_DIR, sanitize_filename(source))
    os.makedirs(target_dir, exist_ok=True)
    
    # Construct target filename
    target_filename = f"{year} - {safe_title}.pdf"
    target_path = os.path.join(target_dir, target_filename)
    
    print(f"Organizing paper: {title}")
    print(f"Moving to: {target_path}")
    
    shutil.move(source_file, target_path)
    return target_path
