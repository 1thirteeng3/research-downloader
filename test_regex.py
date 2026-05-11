import re

with open('/home/.z/chat-uploads/links_arxiv-b79ad50f4b4d.txt', 'r') as f:
    lines = f.read().splitlines()

# pattern to extract arxiv ID
pattern = r'(?:arxiv\.org/(?:abs|pdf|PS_cache/[a-z-]+/pdf)/|arXiv:)([a-z\-]+/\d+(?:v\d+)?|\d{4}\.\d{4,5}(?:v\d+)?)'

matched = 0
for line in lines:
    m = re.search(pattern, line, re.IGNORECASE)
    if m:
        matched += 1
    else:
        print("Unmatched:", line)

print(f"Matched {matched} out of {len(lines)}")
