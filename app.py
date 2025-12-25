import streamlit as st
import os
import shutil
from processor import PDFProcessor, UsageTracker
from utils import create_zip_archive

st.set_page_config(page_title="PDF to Markdown Converter", layout="wide")

st.title("PDF to Markdown Converter")
st.markdown("""
Convert your PDF files to Markdown with high-quality structure preservation.
**(Daily Limit: 3000 pages per user)**
""")

# Initialize Processor
if 'processor' not in st.session_state:
    st.session_state.processor = PDFProcessor()

tracker = st.session_state.processor.tracker

# Sidebar for usage stats
st.sidebar.header("Usage Stats")
usage = tracker.get_todays_usage()
st.sidebar.markdown(f"**Today's Usage:** {usage} / 3000 pages")
st.sidebar.progress(min(usage / 3000, 1.0))

if usage >= 3000:
    st.error("You have reached your daily limit of 3000 pages. Please try again tomorrow.")
    st.stop()

uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")

if uploaded_file is not None:
    # Read file info
    file_bytes = uploaded_file.read()
    file_size_mb = len(file_bytes) / (1024 * 1024)
    
    st.info(f"File Size: {file_size_mb:.2f} MB")
    
    # Analyze PDF
    try:
        # We split just to count pages and preview
        chunks, total_pages = st.session_state.processor.split_pdf(file_bytes)
        st.write(f"**Total Pages:** {total_pages}")
        
        processing_pages = total_pages
            
        st.write(f"**Processing Pages:** {processing_pages}")
        st.write(f"**Estimated Chunks:** {len(chunks)}")
        
        if st.button("Start Conversion"):
            # Progress bar
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            def update_progress(progress):
                progress_bar.progress(progress)
                status_text.text(f"Processing... {int(progress * 100)}%")

            try:
                start_time = os.times().elapsed
                markdown_content, images_map = st.session_state.processor.process_pdf(file_bytes, progress_callback=update_progress)
                
                status_text.text("Processing Complete! Preparing download...")
                
                # Create Zip
                output_zip = create_zip_archive(markdown_content, images_map, "output.zip")
                
                # Read zip for download
                with open(output_zip, "rb") as f:
                    zip_data = f.read()
                
                st.success("Conversion Successful!")
                
                col1, col2 = st.columns(2)
                with col1:
                    st.download_button(
                        label="Download Markdown (Zip)",
                        data=zip_data,
                        file_name="converted_document.zip",
                        mime="application/zip"
                    )
                
                # Cleanup
                os.remove(output_zip)
                
                # Preview (First 500 chars)
                with st.expander("Preview Markdown Content"):
                    st.text_area("Preview", markdown_content[:2000] + "...", height=300)

            except Exception as e:
                st.error(f"Error during processing: {str(e)}")

    except Exception as e:
        st.error(f"Failed to read PDF: {str(e)}")
