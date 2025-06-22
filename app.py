import streamlit as st
import requests
import pandas as pd
from urllib.parse import urlparse

# Page configuration
st.set_page_config(
    page_title="XPath Extractor",
    page_icon="🔍",
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

def call_xpath_api(url):
    """Call the FastAPI backend to extract XPaths"""
    try:
        response = requests.post(
            f"{API_BASE_URL}/extract-xpaths",
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

def main():
    # Simple header
    st.title("🔍 XPath Extractor")
    st.write("Enter a website URL to extract all XPaths from the page.")
    
    # URL input
    url = st.text_input("Website URL:", placeholder="https://example.com")
    
    # Extract button
    if st.button("Extract XPaths", type="primary"):
        if not url:
            st.error("Please enter a URL")
        elif not is_valid_url(url):
            st.error("Please enter a valid URL")
        else:
            with st.spinner("Extracting XPaths..."):
                result, error = call_xpath_api(url)
            
            if error:
                st.error(error)
            else:
                st.success(f"Found {len(result['xpaths'])} XPaths")
                
                # Display XPaths in a simple list
                st.subheader("XPaths:")
                for i, xpath in enumerate(result['xpaths'], 1):
                    st.code(xpath)
                
                # Simple download button
                if result['xpaths']:
                    df = pd.DataFrame({'xpath': result['xpaths']})
                    csv = df.to_csv(index=False)
                    st.download_button(
                        label="Download as CSV",
                        data=csv,
                        file_name="xpaths.csv",
                        mime="text/csv"
                    )

if __name__ == "__main__":
    main()