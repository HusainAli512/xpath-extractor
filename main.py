from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
from typing import List, Optional, Dict, Any
import os
from urllib.parse import urljoin, urlparse
import re
import asyncio
import time
from dotenv import load_dotenv
import hashlib
import json

load_dotenv()

app = FastAPI(title="Website Chat API", version="1.0.0")

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

# In-memory storage for website content and chat history
website_cache = {}
chat_sessions = {}

class URLRequest(BaseModel):
    url: HttpUrl

class ChatRequest(BaseModel):
    session_id: str
    message: str

class WebsiteResponse(BaseModel):
    session_id: str
    url: str
    title: str
    content_preview: str
    word_count: int
    status: str
    processing_time: float

class ChatResponse(BaseModel):
    session_id: str
    user_message: str
    ai_response: str
    timestamp: float

class ChatHistoryResponse(BaseModel):
    session_id: str
    history: List[Dict[str, Any]]
    website_info: Dict[str, Any]

def generate_session_id(url: str) -> str:
    """Generate a unique session ID based on URL and timestamp"""
    unique_string = f"{url}_{int(time.time())}"
    return hashlib.md5(unique_string.encode()).hexdigest()[:12]

def clean_and_extract_text(html_content: str) -> tuple[str, str]:
    """Extract clean text and title from HTML"""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract title
    title_tag = soup.find('title')
    title = title_tag.get_text().strip() if title_tag else "Untitled Page"
    
    # Remove script, style, and other non-content elements
    for element in soup(["script", "style", "nav", "header", "footer", "aside", "noscript"]):
        element.decompose()
    
    # Remove comments
    for comment in soup.find_all(string=lambda text: isinstance(text, str) and text.strip().startswith('<!--')):
        comment.extract()
    
    # Extract main content areas preferentially
    main_content = soup.find('main') or soup.find('article') or soup.find('div', class_=re.compile(r'content|main|body'))
    
    if main_content:
        text = main_content.get_text()
    else:
        text = soup.get_text()
    
    # Clean the text
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    clean_text = ' '.join(chunk for chunk in chunks if chunk)
    
    # Remove excessive whitespace
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    
    return clean_text, title

def extract_website_content(url: str) -> tuple[str, str]:
    """Extract content from website URL"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        content, title = clean_and_extract_text(response.text)
        return content, title
        
    except requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {str(e)}")

async def get_ai_response(message: str, website_content: str, chat_history: List[Dict]) -> str:
    """Get AI response based on user message, website content, and chat history"""
    
    def _sync_ai_call():
        # Build context from chat history
        history_context = ""
        if chat_history:
            recent_history = chat_history[-5:]  # Last 5 exchanges
            for chat in recent_history:
                history_context += f"User: {chat['user_message']}\nAI: {chat['ai_response']}\n\n"
        
        # Limit website content for better processing
        content_limit = 15000
        if len(website_content) > content_limit:
            website_content_truncated = website_content[:content_limit] + "... [content truncated]"
        else:
            website_content_truncated = website_content
        
        prompt = f"""
        You are a helpful AI assistant that can answer questions about website content. 
        
        Website Content:
        {website_content_truncated}
        
        Previous Conversation:
        {history_context}
        
        User's Current Question: {message}
        
        Instructions:
        - Answer based on the website content provided
        - If the question is about summarization, provide a clear and concise summary
        - If asked specific questions, find relevant information from the content
        - If the information isn't in the content, politely say so
        - Keep responses conversational and helpful
        - Reference specific parts of the content when relevant
        
        Response:
        """
        
        try:
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            raise Exception(f"AI API error: {str(e)}")
    
    try:
        loop = asyncio.get_event_loop()
        ai_response = await asyncio.wait_for(
            loop.run_in_executor(None, _sync_ai_call), 
            timeout=30.0
        )
        return ai_response
        
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="AI processing timed out. Please try again.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI error: {str(e)}")

@app.get("/")
async def root():
    return {"message": "Website Chat API is running"}

@app.post("/extract-website", response_model=WebsiteResponse)
async def extract_website(request: URLRequest):
    """Extract and process website content"""
    
    url = str(request.url)
    start_time = time.time()
    
    try:
        # Extract content from website
        content, title = extract_website_content(url)
        
        # Generate session ID
        session_id = generate_session_id(url)
        
        # Store in cache
        website_cache[session_id] = {
            "url": url,
            "title": title,
            "content": content,
            "timestamp": time.time()
        }
        
        # Initialize chat session
        chat_sessions[session_id] = []
        
        processing_time = time.time() - start_time
        word_count = len(content.split())
        
        return WebsiteResponse(
            session_id=session_id,
            url=url,
            title=title,
            content_preview=content[:500] + "..." if len(content) > 500 else content,
            word_count=word_count,
            status="success",
            processing_time=round(processing_time, 2)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        processing_time = time.time() - start_time
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.post("/chat", response_model=ChatResponse)
async def chat_with_content(request: ChatRequest):
    """Chat with the extracted website content"""
    
    # Check if session exists
    if request.session_id not in website_cache:
        raise HTTPException(status_code=404, detail="Session not found. Please extract website content first.")
    
    if request.session_id not in chat_sessions:
        chat_sessions[request.session_id] = []
    
    try:
        website_data = website_cache[request.session_id]
        chat_history = chat_sessions[request.session_id]
        
        # Get AI response
        ai_response = await get_ai_response(
            request.message, 
            website_data["content"], 
            chat_history
        )
        
        # Store chat exchange
        chat_exchange = {
            "user_message": request.message,
            "ai_response": ai_response,
            "timestamp": time.time()
        }
        
        chat_sessions[request.session_id].append(chat_exchange)
        
        return ChatResponse(
            session_id=request.session_id,
            user_message=request.message,
            ai_response=ai_response,
            timestamp=chat_exchange["timestamp"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")

@app.get("/chat-history/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(session_id: str):
    """Get chat history for a session"""
    
    if session_id not in website_cache:
        raise HTTPException(status_code=404, detail="Session not found.")
    
    return ChatHistoryResponse(
        session_id=session_id,
        history=chat_sessions.get(session_id, []),
        website_info={
            "url": website_cache[session_id]["url"],
            "title": website_cache[session_id]["title"],
            "word_count": len(website_cache[session_id]["content"].split())
        }
    )

@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    """Clear a chat session"""
    
    if session_id in website_cache:
        del website_cache[session_id]
    
    if session_id in chat_sessions:
        del chat_sessions[session_id]
    
    return {"message": "Session cleared successfully"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "website-chat"}

# Cleanup old sessions (run periodically)
@app.on_event("startup")
async def startup_event():
    """Clean up old sessions on startup"""
    pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8000,
        timeout_keep_alive=60,
        timeout_graceful_shutdown=30
    )