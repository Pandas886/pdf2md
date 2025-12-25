import streamlit as st
import os
import shutil
import zipfile
from io import BytesIO
from processor import PDFProcessor, InvalidTokenError
from utils import create_zip_archive

st.set_page_config(
    page_title="PDF 转 Markdown 转换器", 
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("PDF 转 Markdown 转换器")
st.markdown("""
将您的 PDF 文件转换为 Markdown，完美保留文档结构。
""")

# Initialize Processor
# Get Token from URL or Sidebar
query_params = st.query_params
url_token = query_params.get("token", None)

# Feature Highlights in Sidebar
st.sidebar.divider()
st.sidebar.markdown("### 🌟 核心优势")
st.sidebar.markdown("""
- **高保真解析**：深度还原文档结构，表格、公式精准识别。
- **自动拆分**：按 10 页自动切片，降低单次解析压力，支持分段恢复。
- **智能并发**：多线程并行处理，大文件转换速度飞快。
- **断点续传**：内置缓存机制，中断后可秒级恢复，拒绝从头再来。
- **批量处理**：支持多文件同时上传，自动排队处理。
- **安全隐私**：Token 本地校验，支持 URL 动态传递。
""")
st.sidebar.info("💡 **提示**：首次使用请准备好 API Token，不同文件的解析可以并行排队。")

if url_token:
    api_token = url_token
    st.sidebar.success("已检测到 URL Token")
else:
    api_token = st.sidebar.text_input("请输入 API Token", type="password", help="请在 URL 中添加 ?token=... 或在此处输入")

if not api_token:
    st.warning("请提供 API Token 以继续。")
    st.stop()

if 'processor' not in st.session_state or st.session_state.get('current_token') != api_token:
    st.session_state.processor = PDFProcessor(token=api_token)
    st.session_state.current_token = api_token

uploaded_files = st.file_uploader("选择 PDF 文件 (支持多选)", type="pdf", accept_multiple_files=True)

if uploaded_files:
    # Summary of selected files
    total_size_mb = sum([file.size for file in uploaded_files]) / (1024 * 1024)
    st.info(f"已选择 {len(uploaded_files)} 个文件，总大小: {total_size_mb:.2f} MB")
    
    # Initialize state
    if 'processing' not in st.session_state:
        st.session_state.processing = False
    if 'results' not in st.session_state:
        st.session_state.results = []
    
    # Start Button is disabled during processing
    start_button = st.button("开始批量转换", disabled=st.session_state.processing)
    
    if start_button:
        st.session_state.processing = True
        st.session_state.results = [] # Clear previous results
        st.rerun()

    # Processing Phase
    if st.session_state.processing:
        st.divider()
        st.write("### ⏳ 正在处理...")
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for idx, uploaded_file in enumerate(uploaded_files):
            status_text.text(f"正在处理第 {idx+1}/{len(uploaded_files)} 个文件: {uploaded_file.name}")
            
            try:
                file_bytes = uploaded_file.getvalue()
                
                # Update progress callback
                def update_progress(progress):
                    # Combine overall progress with chunk progress could be complex, 
                    # simple approach: just show chunk progress for current file in the main bar, 
                    # or update text. Let's keep it simple.
                    progress_bar.progress(progress)
                
                # Process
                markdown_content, images_map = st.session_state.processor.process_pdf(file_bytes, progress_callback=update_progress)
                
                # Create Zip
                original_name = os.path.splitext(uploaded_file.name)[0]
                download_filename = f"{original_name}.zip"
                output_zip = create_zip_archive(markdown_content, images_map, f"output_{idx}.zip")
                
                with open(output_zip, "rb") as f:
                    zip_data = f.read()
                
                os.remove(output_zip)
                
                # Store result in session state
                st.session_state.results.append({
                    "name": uploaded_file.name,
                    "zip_data": zip_data,
                    "download_name": download_filename,
                    "preview": markdown_content[:1000]
                })
                
            except InvalidTokenError as e:
                st.error(f"🚫 **鉴权失败**: {str(e)}")
                st.error("请检查您的 Token 是否正确，或是否已过期。处理已停止。")
                st.session_state.processing = False
                break # Stop processing subsequent files

            except Exception as e:
                st.error(f"❌ 文件 `{uploaded_file.name}` 处理出错: {str(e)}")
        
        # Processing Complete (only if not aborted)
        if st.session_state.processing:
            st.session_state.processing = False
            st.rerun()

    # Result Display Phase (Persistent)
    if st.session_state.results:
        st.divider()
        st.write("### ✅ 处理完成")
        
        # Download All Button
        if len(st.session_state.results) > 1:
            # Create a master zip in memory
            master_zip_buffer = BytesIO()
            with zipfile.ZipFile(master_zip_buffer, "w") as master_zip:
                for res in st.session_state.results:
                    master_zip.writestr(res['download_name'], res['zip_data'])
            
            master_zip_buffer.seek(0)
            
            st.download_button(
                label="📦 一键下载所有文件",
                data=master_zip_buffer,
                file_name="all_converted_files.zip",
                mime="application/zip",
                key="dl_all_top"
            )
            st.divider()
        
        for idx, res in enumerate(st.session_state.results):
            with st.container():
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"📄 **{res['name']}**")
                    with st.expander("预览内容"):
                        st.text_area("Preview", res['preview'], height=150, key=f"prev_{idx}")
                with col2:
                    st.download_button(
                        label="⬇️ 下载 ZIP",
                        data=res['zip_data'],
                        file_name=res['download_name'],
                        mime="application/zip",
                        key=f"dl_{idx}"  # Unique key ensures button works independently
                    )
                st.divider()
