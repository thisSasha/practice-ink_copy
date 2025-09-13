import os
from bs4 import BeautifulSoup

def process_index_html():
    # Read the original index.html
    with open("./about/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")

    # 1. Remove all <script> tags
    for script in soup.find_all("script"):
        script.decompose()

    # 2. For <style> tags with content > 1000 chars, replace with empty class definitions
    for style in soup.find_all("style"):
        if style.string and len(style.string) > 1000:
            # Find all class selectors in the style content
            import re
            classes = set(re.findall(r'\.([a-zA-Z0-9_-]+)\s*[{,]', style.string))
            # Build empty class definitions
            empty_css = "\n".join([f".{cls} {{}}" for cls in classes])
            style.string.replace_with(empty_css)

    # 3. Empty all <svg> tags
    for svg in soup.find_all("svg"):
        svg.clear()

    # Write to a new file (e.g., index_clean.html)
    with open("index_clean.html", "w", encoding="utf-8") as f:
        f.write(str(soup))

if __name__ == "__main__":
    process_index_html()
