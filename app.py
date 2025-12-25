import streamlit as st
import os
import shutil
from processor import PDFProcessor, UsageTracker
from utils import create_zip_archive

st.set_page_config(page_title="PDF 转 Markdown 转换器", layout="wide")

st.title("PDF 转 Markdown 转换器")
st.markdown("""
将您的 PDF 文件转换为 Markdown，完美保留文档结构。
**(每日限额：每位用户 3000 页)**
""")

# Initialize Processor
# Get Token from URL or Sidebar
query_params = st.query_params
url_token = query_params.get("token", None)

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

tracker = st.session_state.processor.tracker

# Sidebar for usage stats
st.sidebar.header("使用统计")
usage = tracker.get_todays_usage()
st.sidebar.markdown(f"**今日已用：** {usage} / 3000 页")
st.sidebar.progress(min(usage / 3000, 1.0))

if usage >= 3000:
    st.error("您已达到今日 3000 页的限额，请明天再试。")
    st.stop()

uploaded_file = st.file_uploader("选择 PDF 文件", type="pdf")

if uploaded_file is not None:
    # Read file info
    file_bytes = uploaded_file.read()
    file_size_mb = len(file_bytes) / (1024 * 1024)
    
    st.info(f"文件大小: {file_size_mb:.2f} MB")
    
    # Analyze PDF
    try:
        # We split just to count pages and preview
        chunks, total_pages = st.session_state.processor.split_pdf(file_bytes)
        st.write(f"**总页数:** {total_pages}")
        
        processing_pages = total_pages
            
        st.write(f"**处理页数:** {processing_pages}")
        st.write(f"**预计切片数:** {len(chunks)}")
        
        if st.button("开始转换"):
            # Progress bar
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            def update_progress(progress):
                progress_bar.progress(progress)
                status_text.text(f"正在处理... {int(progress * 100)}%")

            try:
                start_time = os.times().elapsed
                markdown_content, images_map = st.session_state.processor.process_pdf(file_bytes, progress_callback=update_progress)
                
                status_text.text("处理完成！正在准备下载...")
                
                # Create Zip
                output_zip = create_zip_archive(markdown_content, images_map, "output.zip")
                
                # Read zip for download
                with open(output_zip, "rb") as f:
                    zip_data = f.read()
                
                st.success("转换成功！")
                
                col1, col2 = st.columns(2)
                with col1:
                    st.download_button(
                        label="下载 Markdown (Zip)",
                        data=zip_data,
                        file_name="converted_document.zip",
                        mime="application/zip"
                    )
                
                # Cleanup
                os.remove(output_zip)
                
                # Preview (First 500 chars)
                with st.expander("预览 Markdown 内容"):
                    st.text_area("预览", markdown_content[:2000] + "...", height=300)

            except Exception as e:
                st.error(f"处理过程中出错: {str(e)}")

    except Exception as e:
        st.error(f"读取 PDF 失败: {str(e)}")
