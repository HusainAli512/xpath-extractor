import streamlit as st
import requests
import time
from urllib.parse import urlparse

# Page configuration
st.set_page_config(
    page_title="Website Chat",
    page_icon="💬",
    layout="centered"
)

# API Configuration
API_BASE_URL = "http://localhost:8000"

def is_valid_url(url):
    """Validate URL format"""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

def extract_website_content(url):
    """Call API to extract website content"""
    try:
        response = requests.post(
            f"{API_BASE_URL}/extract-website",
            json={"url": url},
            timeout=30
        )
        
        if response.status_code == 200:
            return response.json(), None
        else:
            error_detail = response.json().get("detail", "Unknown error")
            return None, f"Error: {error_detail}"
            
    except requests.exceptions.ConnectionError:
        return None, "Cannot connect to API. Make sure the FastAPI server is running."
    except requests.exceptions.Timeout:
        return None, "Request timed out."
    except Exception as e:
        return None, f"Error: {str(e)}"

def get_website_summary(session_id):
    """Get summary of the website content"""
    try:
        response = requests.post(
            f"{API_BASE_URL}/chat",
            json={
                "session_id": session_id, 
                "message": "Please provide a comprehensive summary of this website's content, including its main purpose, key topics, and important information."
            },
            timeout=45
        )
        
        if response.status_code == 200:
            return response.json().get('ai_response'), None
        else:
            error_detail = response.json().get("detail", "Unknown error")
            return None, f"Error getting summary: {error_detail}"
            
    except requests.exceptions.Timeout:
        return None, "Summary request timed out. Please try again."
    except Exception as e:
        return None, f"Error getting summary: {str(e)}"

def send_chat_message(session_id, message):
    """Send chat message to API"""
    try:
        response = requests.post(
            f"{API_BASE_URL}/chat",
            json={"session_id": session_id, "message": message},
            timeout=45
        )
        
        if response.status_code == 200:
            return response.json(), None
        else:
            error_detail = response.json().get("detail", "Unknown error")
            return None, f"Error: {error_detail}"
            
    except requests.exceptions.Timeout:
        return None, "AI response timed out. Please try again."
    except Exception as e:
        return None, f"Error: {str(e)}"

def main():
    st.title("💬 Website Chat")
    
    # Initialize session state
    if "session_id" not in st.session_state:
        st.session_state.session_id = None
    if "website_loaded" not in st.session_state:
        st.session_state.website_loaded = False
    if "website_summary" not in st.session_state:
        st.session_state.website_summary = None
    if "website_title" not in st.session_state:
        st.session_state.website_title = None
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "processing" not in st.session_state:
        st.session_state.processing = False
    if "summary_generated" not in st.session_state:
        st.session_state.summary_generated = False
    
    # URL input
    url = st.text_input("Enter website URL:", placeholder="https://example.com")
    
    # Load website button
    if st.button("Load Website", type="primary", disabled=st.session_state.processing):
        if not url:
            st.error("Please enter a URL")
        elif not is_valid_url(url):
            st.error("Please enter a valid URL")
        else:
            st.session_state.processing = True
            with st.spinner("Loading website..."):
                result, error = extract_website_content(url)
            
            if error:
                st.error(error)
                st.session_state.processing = False
            else:
                st.session_state.session_id = result['session_id']
                st.session_state.website_title = result['title']
                st.session_state.website_loaded = True
                st.session_state.chat_history = []
                st.session_state.summary_generated = False
                st.session_state.website_summary = None
                st.success(f"Website loaded: {result['title']}")
                
                # Generate summary automatically
                with st.spinner("Generating website summary..."):
                    summary, summary_error = get_website_summary(st.session_state.session_id)
                
                if summary_error:
                    st.error(f"Could not generate summary: {summary_error}")
                else:
                    st.session_state.website_summary = summary
                    st.session_state.summary_generated = True
            
            st.session_state.processing = False
    
    # Display website summary
    if st.session_state.website_loaded and st.session_state.summary_generated:
        st.divider()
        
        # Website title
        if st.session_state.website_title:
            st.subheader(f"📄 {st.session_state.website_title}")
        
        # Summary section
        st.markdown("### 📋 Website Summary")
        if st.session_state.website_summary:
            st.markdown(st.session_state.website_summary)
        
        st.divider()
        st.markdown("### 💬 Chat with the Website")
        st.caption("Ask questions about the website content below:")
        
        # Display chat history
        for chat in st.session_state.chat_history:
            with st.chat_message("user"):
                st.write(chat['user_message'])
            with st.chat_message("assistant"):
                st.write(chat['ai_response'])
        
        # Chat input
        user_input = st.chat_input("Ask something about the website...")
        
        # Process user input
        if user_input and not st.session_state.processing:
            # Add user message immediately
            st.session_state.chat_history.append({
                'user_message': user_input,
                'ai_response': "Thinking...",
                'timestamp': time.time()
            })
            st.rerun()
        
        # Process AI response if there's a pending message
        if (st.session_state.chat_history and 
            st.session_state.chat_history[-1]['ai_response'] == "Thinking..." and 
            not st.session_state.processing):
            
            st.session_state.processing = True
            user_msg = st.session_state.chat_history[-1]['user_message']
            
            with st.spinner("AI is thinking..."):
                result, error = send_chat_message(st.session_state.session_id, user_msg)
            
            if error:
                st.session_state.chat_history[-1]['ai_response'] = f"Sorry, there was an error: {error}"
            else:
                st.session_state.chat_history[-1]['ai_response'] = result['ai_response']
            
            st.session_state.processing = False
            st.rerun()
    
    elif st.session_state.website_loaded and not st.session_state.summary_generated:
        st.info("Generating website summary...")
    else:
        st.info("Enter a website URL above to start. You'll see a summary of the website first, then you can chat with its content!")

if __name__ == "__main__":
    main()