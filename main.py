from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
from typing import List, Optional
import os
from urllib.parse import urljoin, urlparse
import re
import asyncio
import time
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
    timeout: Optional[int] = 30  # Allow client to specify timeout

class XPathResponse(BaseModel):
    url: str
    xpaths: List[str]
    html_content: str
    status: str
    processing_time: float

# Store for async processing
processing_results = {}

def clean_html(html_content: str) -> str:
    """Clean and minimize HTML content for better processing"""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remove script and style elements
    for script in soup(["script", "style"]):
        script.decompose()
    
    # Remove comments
    for comment in soup.find_all(string=lambda text: isinstance(text, str) and text.strip().startswith('<!--')):
        comment.extract()
    
    # Get text and clean it
    text = soup.get_text()
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = ' '.join(chunk for chunk in chunks if chunk)
    
    return str(soup)

def extract_html_from_url(url: str) -> str:
    """Extract HTML content from given URL with optimized settings"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        # Reduced timeout for URL fetching
        response = requests.get(url, headers=headers, timeout=8)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {str(e)}")

async def get_xpaths_from_gemini_async(html_content: str, url: str) -> List[str]:
    """Async wrapper for Gemini API call with timeout"""
    
    def _sync_gemini_call():
        # Reduce HTML content more aggressively for faster processing
        if len(html_content) > 30000:
            html_content_truncated = html_content[:30000] + "..."
        else:
            html_content_truncated = html_content
        
        prompt = f"""
        Analyze this HTML from {url} and extract the most important XPaths.
        
        Focus on these priority elements:
        1. Form inputs (input, button, textarea, select)
        2. Navigation links (a, nav elements)
        3. Main content containers (main, article, section)
        4. Interactive elements (buttons, clickable divs)
        
        Provide concise, practical XPaths only. Maximum 20 XPaths.
        
        HTML Content:
        {html_content_truncated}
        
        Return only XPaths, one per line:
        """
        
        try:
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            raise Exception(f"Gemini API error: {str(e)}")
    
    # Run the sync function in a thread pool with timeout
    try:
        loop = asyncio.get_event_loop()
        # 25 second timeout for Gemini API
        xpaths_text = await asyncio.wait_for(
            loop.run_in_executor(None, _sync_gemini_call), 
            timeout=25.0
        )
        
        # Parse XPaths from response
        xpath_lines = [line.strip() for line in xpaths_text.split('\n') if line.strip()]
        
        # Filter valid XPaths
        valid_xpaths = []
        for line in xpath_lines:
            cleaned_line = re.sub(r'^\d+\.\s*', '', line)
            cleaned_line = re.sub(r'^[-*]\s*', '', cleaned_line)
            cleaned_line = cleaned_line.strip('`')
            
            if (cleaned_line.startswith('/') or 
                cleaned_line.startswith('//') or 
                'xpath' in cleaned_line.lower() or
                cleaned_line.startswith('.')):
                valid_xpaths.append(cleaned_line)
        
        return valid_xpaths if valid_xpaths else ["//body", "//html"]
        
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="AI processing timed out. Try with a simpler page.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini API error: {str(e)}")

@app.get("/")
async def root():
    return {"message": "XPath Extractor API is running"}

@app.post("/extract-xpaths", response_model=XPathResponse)
async def extract_xpaths(request: URLRequest):
    """Extract XPaths from a given URL with timeout handling"""
    
    url = str(request.url)
    start_time = time.time()
    
    try:
        # Step 1: Extract HTML from URL (quick)
        html_content = extract_html_from_url(url)
        
        # Step 2: Clean HTML for better processing (quick)
        cleaned_html = clean_html(html_content)
        
        # Step 3: Get XPaths from Gemini with timeout
        xpaths = await get_xpaths_from_gemini_async(cleaned_html, url)
        
        processing_time = time.time() - start_time
        
        return XPathResponse(
            url=url,
            xpaths=xpaths,
            html_content=cleaned_html[:3000] + "..." if len(cleaned_html) > 3000 else cleaned_html,
            status="success",
            processing_time=round(processing_time, 2)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = time.time() - start_time
        print(f"Error after {processing_time:.2f}s: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.post("/extract-xpaths-fast")
async def extract_xpaths_fast(request: URLRequest):
    """Fast extraction with basic XPaths - no AI processing"""
    
    url = str(request.url)
    start_time = time.time()
    
    try:
        html_content = extract_html_from_url(url)
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Extract basic XPaths using BeautifulSoup
        xpaths = []
        
        # Common form elements
        for tag in ['input', 'button', 'textarea', 'select']:
            elements = soup.find_all(tag)
            for i, elem in enumerate(elements):
                if elem.get('id'):
                    xpaths.append(f"//{tag}[@id='{elem['id']}']")
                elif elem.get('name'):
                    xpaths.append(f"//{tag}[@name='{elem['name']}']")
                else:
                    xpaths.append(f"(//{tag})[{i+1}]")
        
        # Links
        links = soup.find_all('a', href=True)
        for i, link in enumerate(links):
            if link.get('id'):
                xpaths.append(f"//a[@id='{link['id']}']")
            else:
                xpaths.append(f"(//a)[{i+1}]")
        
        # Headers
        for tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            headers = soup.find_all(tag)
            for i, header in enumerate(headers):
                xpaths.append(f"(//{tag})[{i+1}]")
        
        processing_time = time.time() - start_time
        
        return XPathResponse(
            url=url,
            xpaths=xpaths[:50],  # Limit results
            html_content=html_content[:3000] + "..." if len(html_content) > 3000 else html_content,
            status="success",
            processing_time=round(processing_time, 2)
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "xpath-extractor"}

# Add timeout configuration for uvicorn
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8000,
        timeout_keep_alive=60,  # Keep connections alive longer
        timeout_graceful_shutdown=30
    )