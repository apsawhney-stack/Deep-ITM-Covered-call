import sys
from bs4 import BeautifulSoup

def clean_html(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        html = f.read()
    
    # Extract the HTML part
    parts = html.split('---', 1)
    if len(parts) > 1:
        html_content = parts[1]
    else:
        html_content = html
        
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remove script and style elements
    for script in soup(["script", "style"]):
        script.extract()
        
    # Get the main content if possible
    content_div = soup.find(id="VPContent")
    if content_div:
        text = content_div.get_text(separator='\n')
    else:
        main = soup.find('main')
        if main:
            text = main.get_text(separator='\n')
        else:
            text = soup.get_text(separator='\n')
            
    # Clean up whitespace
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text_clean = '\n'.join(chunk for chunk in chunks if chunk)
    
    return text_clean

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python parse_html.py <path_to_html_file>")
        sys.exit(1)
        
    print(clean_html(sys.argv[1]))
