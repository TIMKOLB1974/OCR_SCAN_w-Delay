import streamlit as st
import anthropic
import os
import base64
import json
import logging
import zipfile
import io
import tempfile
import time #edit made by Nick 9/3/25
from pathlib import Path
from dotenv import load_dotenv


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Set page config
st.set_page_config(
    page_title="PDF Job Traveler Processor",
    page_icon="📄",
    layout="wide"
)

# App title and description
st.title("PDF Job Traveler Processor")
st.write("""
This application processes job traveler PDF documents, extracts key information (Customer, Part Number, Description),
and renames the files accordingly. Upload your PDFs and get a zip file with the renamed documents.
""")

# Function to process a single PDF with Claude
def prompt_claude(pdf_file, api_key):
    """Get data from Claude for a single PDF."""
    try:
        pdf_bytes = pdf_file.read()
        pdf_data = base64.b64encode(pdf_bytes).decode("utf-8")
        
        # Reset file pointer for future use
        pdf_file.seek(0)
    except Exception as e:
        st.error(f"Error reading PDF file: {e}")
        logger.error(f"Error reading PDF file: {e}")
        return {}
    
    prompt = """
    I will provide you with a PDF file. This file has a job traveler document. I want you to extract only the following entities from the document:
    1. Customer
    2. Part Number
    3. Description
    I want you to return the extracted data in a JSON format. The JSON should have the following structure:
    {
        "Customer": "customer_name",
        "Part Number": "part_number",
        "Description": "description"
    }
    The values should be the actual values extracted from the document. Just return the JSON object without any additional text or explanation.
    If you cannot find any of the entities, return an empty string for that entity.
    """
    
    try:
        client = anthropic.Client(api_key=api_key)
        logger.debug("Sending request to Claude API")
        
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_data
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ],
        )
        
        try:
            result = json.loads(message.content[0].text)
            logger.info(f"Successfully extracted data: {result}")
            return result
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON from Claude's response: {e}")
            logger.error(f"Claude's raw response: {message.content[0].text}")
            return {}
            
    except Exception as e:
        logger.error(f"Error calling Claude API: {e}")
        st.error(f"Error calling Claude API: {e}")
        return {}

def sanitize_filename(filename):
    """Remove invalid characters from filename."""
    # List of characters not allowed in filenames
    invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
    
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    # Truncate filename if it's too long (Windows has a 255 character limit)
    if len(filename) > 240:  # Leave some room for the extension
        filename = filename[:240]
        
    return filename

def process_pdfs(uploaded_files, api_key):
    """Process multiple PDF files and create a zip archive."""
    if not uploaded_files:
        st.warning("Please upload at least one PDF file.")
        return None
    
    # Create a temporary directory to store renamed files
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create a memory file for the zip
        zip_buffer = io.BytesIO()
        
        # Create a zip file
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Set up progress bar
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Process each file with progress updates
            results = []
            for i, uploaded_file in enumerate(uploaded_files):
                # Update progress
                progress = (i) / len(uploaded_files)
                progress_bar.progress(progress)
                status_text.text(f"Processing {uploaded_file.name}... ({i+1}/{len(uploaded_files)})")
                
                # Save the uploaded file to the temp directory
                temp_file_path = temp_path / uploaded_file.name
                with open(temp_file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                # Extract entities from PDF
                extracted_data = prompt_claude(uploaded_file, api_key)

                # Wait 2 seconds before the next file (adjust as needed) (edit made by Nick 9/3/25)
                time.sleep(4)

                result_info = {
                    "original_name": uploaded_file.name,
                    "extracted_data": extracted_data,
                    "new_name": ""
                }
                
                if not extracted_data:
                    result_info["status"] = "Error: No data extracted"
                    results.append(result_info)
                    continue
                
                # Check if required fields exist
                required_fields = ["Customer", "Part Number", "Description"]
                missing_fields = [field for field in required_fields if field not in extracted_data or not extracted_data[field]]
                
                if missing_fields:
                    logger.warning(f"Missing fields in extracted data for {uploaded_file.name}: {missing_fields}.")
                    # Use empty strings for missing fields
                    for field in missing_fields:
                        extracted_data[field] = "Unknown"
                
                # Create new filename
                new_filename = f"{extracted_data['Part Number']} {extracted_data['Customer']} {extracted_data['Description']}.pdf"
                # Sanitize the filename
                new_filename = sanitize_filename(new_filename)
                new_filepath = temp_path / new_filename
                
                # Rename the file
                temp_file_path.rename(new_filepath)
                logger.info(f"Successfully renamed: {uploaded_file.name} → {new_filename}")
                
                # Add renamed file to zip
                zip_file.write(new_filepath, arcname=new_filename)
                
                # Store result for display
                result_info["status"] = "Success" if not missing_fields else f"Partial success (missing: {', '.join(missing_fields)})"
                result_info["new_name"] = new_filename
                results.append(result_info)
            
            # Complete progress bar
            progress_bar.progress(1.0)
            status_text.text("Processing complete!")
            
        # Return both the zip buffer and processing results
        zip_buffer.seek(0)
        return zip_buffer, results

# Define tabs for the application
tab1, tab2, tab3 = st.tabs(["Process PDFs", "About", "Settings"])

# Tab 1: Main processing tab
with tab1:
    # API key management - hierarchy of sources: manual entry > secrets > .env
    col1, col2 = st.columns([3, 1])
    with col1:
        api_key = st.text_input("Anthropic API Key (optional if configured in secrets)", 
                               type="password", 
                               help="Enter your Anthropic API key here or configure it in secrets")
    
    with col2:
        st.write("")
        st.write("")
        show_api_status = st.checkbox("Show API key status", value=False)
    
    # Try various methods to get the API key if not manually entered
    if not api_key:
        # Try Streamlit secrets first (deployment)
        if "ANTHROPIC_API_KEY" in st.secrets:
            api_key = st.secrets["ANTHROPIC_API_KEY"]
            if show_api_status:
                st.success("✅ API key loaded from Streamlit secrets")
        
        # Then try environment variables (local development)
        if not api_key:
            load_dotenv()
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if api_key and show_api_status:
                st.success("✅ API key loaded from environment variables")
    
    if show_api_status and not api_key:
        st.error("❌ No API key found. Please enter an API key above or configure it in secrets.")
        
    # File uploader with enhanced UI
    st.subheader("Upload PDF Files")
    uploaded_files = st.file_uploader("Select job traveler PDF files", 
                                     type=["pdf"], 
                                     accept_multiple_files=True,
                                     help="You can select multiple files at once")
    
    col1, col2 = st.columns(2)
    with col1:
        if uploaded_files:
            st.info(f"📁 {len(uploaded_files)} files selected for processing")
    
    with col2:
        # Process button with dynamic state
        process_button = st.button("🔄 Process Files", 
                                  disabled=not api_key or not uploaded_files,
                                  help="Extract information and rename PDF files",
                                  use_container_width=True)
    
    # Process files when button is clicked
    if process_button:
        with st.spinner("Processing PDF files..."):
            try:
                # Process the files
                result = process_pdfs(uploaded_files, api_key)
                
                if result:
                    zip_buffer, processing_results = result
                    
                    # Create download button for zip file
                    st.success("✅ Processing complete! You can now download the renamed files.")
                    st.download_button(
                        label="📥 Download Renamed PDFs as ZIP",
                        data=zip_buffer,
                        file_name="renamed_pdfs.zip",
                        mime="application/zip",
                        use_container_width=True
                    )
                    
                    # Display processing results
                    st.subheader("Processing Results")
                    
                    # Create a dataframe for results
                    results_data = []
                    for result in processing_results:
                        results_data.append({
                            "Original Filename": result["original_name"],
                            "New Filename": result["new_name"] or "N/A",
                            "Status": result["status"],
                            "Customer": result["extracted_data"].get("Customer", ""),
                            "Part Number": result["extracted_data"].get("Part Number", ""),
                            "Description": result["extracted_data"].get("Description", "")
                        })
                    
                    # Show results table
                    st.dataframe(results_data, use_container_width=True)
                    
            except Exception as e:
                st.error(f"An error occurred during processing: {str(e)}")
                logger.error(f"Processing error: {e}", exc_info=True)

# Tab 2: About tab
with tab2:
    st.header("About this Application")
    st.write("""
    This application uses Claude AI to extract information from job traveler PDF documents and rename them
    according to a standardized format: "Part Number Customer Description.pdf".
    
    ### Features
    - Upload multiple PDF files at once
    - Extract Customer, Part Number, and Description from each document
    - Rename files using the extracted information
    - Download a zip file containing all renamed documents
    - View detailed processing results
    
    ### How It Works
    1. Upload your PDF files
    2. Provide your Anthropic API key (or configure it in secrets)
    3. Click "Process Files"
    4. The app will extract information from each PDF using Claude AI
    5. Files will be renamed based on the extracted information
    6. Download the resulting zip file containing all renamed PDFs
    
    ### Requirements
    - A valid Anthropic API key
    - PDF files containing job traveler documents
    """)

    st.info("""
    Note: Your API key is used only for processing your documents and is not stored permanently.
    All files are processed temporarily and are not stored after you close this application.
    """)

# Tab 3: Settings tab
with tab3:
    st.header("Settings & Configuration")
    
    st.subheader("API Key Configuration")
    st.write("""
    There are three ways to configure your Anthropic API key:
    
    1. **Manual Entry (least secure)**: Enter the API key in the text field on the main tab
    2. **Environment Variables (development)**: Create a `.env` file with `ANTHROPIC_API_KEY=your-key-here`
    3. **Streamlit Secrets (most secure)**: For deployment, use Streamlit's secrets management
    """)
    
    st.code("""
    # Example .streamlit/secrets.toml file
    ANTHROPIC_API_KEY = "your-api-key-here"
    """, language="toml")
    
    st.write("""
    For Streamlit Cloud deployment:
    1. Go to your app settings
    2. Click on "Secrets"
    3. Add your API key as shown above
    """)
    
    st.divider()
    
    st.subheader("Deployment Instructions")
    with st.expander("How to deploy on Streamlit Cloud"):
        st.write("""
        1. Create a GitHub repository with your app code
        2. Include `requirements.txt` with the following dependencies:
           - streamlit>=1.25.0
           - anthropic>=0.8.0
           - python-dotenv>=1.0.0
        3. Go to [share.streamlit.io](https://share.streamlit.io/)
        4. Connect to your GitHub repository
        5. Configure your API key in the Secrets section
        6. Deploy your app
        """)
    
    with st.expander("Development Setup"):
        st.write("""
        For local development:
        
        1. Clone your repository
        2. Create a virtual environment: `python -m venv venv`
        3. Activate the environment: 
           - Windows: `venv\\Scripts\\activate`
           - Unix/Mac: `source venv/bin/activate`
        4. Install dependencies: `pip install -r requirements.txt`
        5. Create a `.env` file with your API key
        6. Run the app: `streamlit run app.py`
        """)