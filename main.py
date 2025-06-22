from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
from typing import List
import os
from urllib.parse import urljoin, urlparse
import re
from dotenv import load_dotenv
load_dotenv()

app = FastAPI(title="XPath Extractor API", version="1.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure Gemini API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-2.0-flash')

class URLRequest(BaseModel):
    url: HttpUrl

class XPathResponse(BaseModel):
    url: str
    xpaths: List[str]
    html_content: str
    status: str

def clean_html(html_content: str) -> str:
    """Clean and minimize HTML content for better processing"""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remove script and style elements
    for script in soup(["script", "style"]):
        script.decompose()
    
    # Get text and clean it
    text = soup.get_text()
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = ' '.join(chunk for chunk in chunks if chunk)
    
    return str(soup)

def extract_html_from_url(url: str) -> str:
    """Extract HTML content from given URL"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {str(e)}")

def get_xpaths_from_gemini(html_content: str, url: str) -> List[str]:
    """Use Gemini API to extract XPaths from HTML content"""
    
    # Truncate HTML if too long (Gemini has token limits)
    if len(html_content) > 50000:
        html_content = html_content[:50000] + "..."
    
    prompt = f"""
    Analyze the following HTML content from the website: {url}
    
    Please extract ALL possible XPaths for various elements in this HTML. Focus on:
    1. All form elements (inputs, buttons, textareas, selects)
    2. All clickable elements (buttons, links, clickable divs)
    3. All text elements (headings, paragraphs, spans)
    4. All navigation elements
    5. All containers and divs with meaningful content
    6. All images and media elements
    7. All table elements if present
    8. All list elements
    
    For each element, provide the most specific and reliable XPath. Include both absolute and relative XPaths when useful.
    
    HTML Content:
    {html_content}
    
    Please respond with ONLY the XPaths, one per line, without any additional text or explanations. Format each XPath clearly.
    """
    
    try:
        response = model.generate_content(prompt)
        xpaths_text = response.text
        
        # Parse XPaths from response
        xpath_lines = [line.strip() for line in xpaths_text.split('\n') if line.strip()]
        
        # Filter valid XPaths (should start with / or // or contain xpath syntax)
        valid_xpaths = []
        for line in xpath_lines:
            # Remove any markdown formatting or numbering
            cleaned_line = re.sub(r'^\d+\.\s*', '', line)  # Remove numbering
            cleaned_line = re.sub(r'^[-*]\s*', '', cleaned_line)  # Remove bullet points
            cleaned_line = cleaned_line.strip('`')  # Remove backticks
            
            if (cleaned_line.startswith('/') or 
                cleaned_line.startswith('//') or 
                'xpath' in cleaned_line.lower() or
                cleaned_line.startswith('.')):
                valid_xpaths.append(cleaned_line)
        
        return valid_xpaths if valid_xpaths else ["//body", "//html"]
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini API error: {str(e)}")

@app.get("/")
async def root():
    return {"message": "XPath Extractor API is running"}

@app.post("/extract-xpaths", response_model=XPathResponse)
async def extract_xpaths(request: URLRequest):
    """Extract XPaths from a given URL"""
    
    url = str(request.url)
    
    try:
        # Step 1: Extract HTML from URL
        html_content = extract_html_from_url(url)
        
        # Step 2: Clean HTML for better processing
        cleaned_html = clean_html(html_content)
        
        # Step 3: Get XPaths from Gemini
        xpaths = get_xpaths_from_gemini(cleaned_html, url)
        
        return XPathResponse(
            url=url,
            xpaths=xpaths,
            html_content=cleaned_html[:5000] + "..." if len(cleaned_html) > 5000 else cleaned_html,
            status="success"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "xpath-extractor"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)