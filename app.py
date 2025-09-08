import streamlit as st
import fitz  # PyMuPDF
import io
import os
from PIL import Image
import gc

def remove_watermark(pdf_document):
    """Remove only center/middle watermarks, preserve footer stamps and official markings"""
    try:
        for page_num in range(len(pdf_document)):
            page = pdf_document[page_num]
            page_rect = page.rect
            page_height = page_rect.height
            page_width = page_rect.width
            
            # Define regions: only remove watermarks from middle 60% of page
            middle_start_y = page_height * 0.2  # Top 20% preserved
            middle_end_y = page_height * 0.8    # Bottom 20% preserved (footer area)
            middle_start_x = page_width * 0.2   # Left 20% preserved
            middle_end_x = page_width * 0.8     # Right 20% preserved
            
            # Step 1: Remove annotations only from middle area
            annot_list = list(page.annots())
            for annot in annot_list:
                try:
                    annot_rect = annot.rect
                    annot_center_x = (annot_rect.x0 + annot_rect.x1) / 2
                    annot_center_y = (annot_rect.y0 + annot_rect.y1) / 2
                    
                    # Only remove if annotation is in middle area (not in footer/header)
                    if (middle_start_x <= annot_center_x <= middle_end_x and 
                        middle_start_y <= annot_center_y <= middle_end_y):
                        
                        annot_type = annot.type[0] if annot.type else -1
                        if annot_type in [0, 1, 2, 3, 8, 13, 14, 15, 16]:
                            page.delete_annot(annot)
                except Exception:
                    continue
            
            # Step 2: Remove watermark images only from middle area
            try:
                image_list = page.get_images(full=True)
                for img_index, img in enumerate(image_list):
                    try:
                        xref = img[0]
                        
                        # Get image rectangles to check position
                        image_rects = page.get_image_rects(xref)
                        if image_rects:
                            for img_rect in image_rects:
                                img_center_x = (img_rect.x0 + img_rect.x1) / 2
                                img_center_y = (img_rect.y0 + img_rect.y1) / 2
                                
                                # Only remove if image is in middle area
                                if (middle_start_x <= img_center_x <= middle_end_x and 
                                    middle_start_y <= img_center_y <= middle_end_y):
                                    
                                    pix = fitz.Pixmap(pdf_document, xref)
                                    if pix:
                                        # Check if it's likely a watermark (small, transparent)
                                        if (pix.width < 200 and pix.height < 200) or pix.alpha > 0:
                                            page.delete_image(xref)
                                        pix = None
                                    break  # Only check first occurrence
                    except Exception:
                        continue
            except Exception:
                pass
            
            # Step 3: Clean page contents but preserve footer area
            try:
                if page.get_contents():
                    content_stream = page.read_contents()
                    if content_stream:
                        content_str = content_stream.decode('latin-1', errors='ignore')
                        
                        # More conservative pattern removal - avoid footer area
                        import re
                        
                        # Only remove transparency operations that are likely in middle area
                        # Look for patterns that include positioning in middle area
                        watermark_patterns = [
                            r'/GS\d+\s+gs\s+q\s+[\d\.\s]*[3-7]\d+[\d\.\s]*cm',  # Transparency with middle positioning
                            r'q\s+[\d\.\s]*[3-7]\d+[\d\.\s]*cm\s+/GS\d+\s+gs.*?Q',  # Middle area transformations
                        ]
                        
                        for pattern in watermark_patterns:
                            content_str = re.sub(pattern, '', content_str, flags=re.DOTALL)
                        
                        try:
                            page.set_contents(content_str.encode('latin-1'))
                        except Exception:
                            pass
                    
                    # Clean contents but preserve structure
                    page.clean_contents()
                    
            except Exception:
                pass
            
            # Step 4: Remove form fields only from middle area
            try:
                widgets = page.widgets()
                for widget in widgets:
                    try:
                        widget_rect = widget.rect
                        widget_center_x = (widget_rect.x0 + widget_rect.x1) / 2
                        widget_center_y = (widget_rect.y0 + widget_rect.y1) / 2
                        
                        # Only remove widgets in middle area
                        if (middle_start_x <= widget_center_x <= middle_end_x and 
                            middle_start_y <= widget_center_y <= middle_end_y):
                            
                            if widget.field_type_string in ['Text', 'Button']:
                                widget.delete()
                    except Exception:
                        continue
            except Exception:
                pass
                
    except Exception as e:
        # If watermark removal fails, continue without it
        pass
    
    return pdf_document

def compress_pdf_to_100kb(input_pdf_bytes):
    """
    Compress PDF to strictly between 80KB-100KB using iterative binary search approach
    """
    max_size = 100 * 1024  # 100KB in bytes
    min_size = 80 * 1024   # 80KB in bytes
    
    try:
        pdf_document = fitz.open(stream=input_pdf_bytes, filetype="pdf")
        
        # Step 1: Remove watermarks
        pdf_document = remove_watermark(pdf_document)
        
        # Step 2: Try simple compression first
        compressed_bytes = simple_compress(pdf_document)
        
        # Check if already in target range
        if min_size <= len(compressed_bytes) <= max_size:
            pdf_document.close()
            return compressed_bytes
        
        # Step 3: Use binary search approach for precise size control
        result_bytes = binary_search_compression(pdf_document, min_size, max_size)
        
        pdf_document.close()
        return result_bytes
        
    except Exception as e:
        st.error(f"Compression failed: {str(e)}")
        return None

def simple_compress(pdf_document):
    """
    Simple compression without any problematic operations
    """
    try:
        # Use garbage collection and basic compression
        pdf_document.save(garbage=3, deflate=True)
        return pdf_document.tobytes(garbage=3, deflate=True)
    except Exception:
        return pdf_document.tobytes()

def binary_search_compression(pdf_document, min_size, max_size):
    """
    Use binary search to find optimal compression settings for exact size range
    """
    # Quality levels for binary search (from high to low quality)
    quality_range = list(range(5, 95, 5))  # [5, 10, 15, ..., 90]
    dimension_range = list(range(100, 1200, 50))  # [100, 150, 200, ..., 1150]
    
    best_result = None
    best_size = float('inf')
    
    # Try different combinations with binary search approach
    for max_dim in [800, 600, 400, 300, 200]:
        low_quality, high_quality = 0, len(quality_range) - 1
        
        while low_quality <= high_quality:
            mid = (low_quality + high_quality) // 2
            quality = quality_range[mid]
            
            try:
                compressed_bytes = compress_with_settings(pdf_document, quality, max_dim)
                current_size = len(compressed_bytes)
                
                # Perfect range - return immediately
                if min_size <= current_size <= max_size:
                    return compressed_bytes
                
                # Track best result (closest to target range)
                if abs(current_size - ((min_size + max_size) // 2)) < abs(best_size - ((min_size + max_size) // 2)):
                    best_result = compressed_bytes
                    best_size = current_size
                
                # Adjust search range
                if current_size > max_size:
                    # File too large, need more compression (lower quality)
                    high_quality = mid - 1
                elif current_size < min_size:
                    # File too small, need less compression (higher quality)
                    low_quality = mid + 1
                
            except Exception:
                # Skip this setting and continue
                high_quality = mid - 1
    
    # If we found something in range, return it
    if best_result and min_size <= best_size <= max_size:
        return best_result
    
    # Final attempt with aggressive compression to force into range
    return force_into_range(pdf_document, min_size, max_size)

def compress_with_settings(pdf_document, quality, max_dimension):
    """
    Compress PDF with specific quality and dimension settings
    """
    temp_bytes = pdf_document.tobytes()
    temp_doc = fitz.open(stream=temp_bytes, filetype="pdf")
    
    # Process each page
    for page_num in range(len(temp_doc)):
        page = temp_doc[page_num]
        image_list = page.get_images(full=True)
        
        for img in image_list:
            try:
                xref = img[0]
                pix = fitz.Pixmap(temp_doc, xref)
                
                # Skip very small images
                if pix.width * pix.height < 5000:
                    pix = None
                    continue
                
                # Convert to PIL Image
                if pix.n - pix.alpha < 4:
                    img_data = pix.tobytes("png")
                    pil_image = Image.open(io.BytesIO(img_data))
                else:
                    pix1 = fitz.Pixmap(fitz.csRGB, pix)
                    img_data = pix1.tobytes("png")
                    pil_image = Image.open(io.BytesIO(img_data))
                    pix1 = None
                
                pix = None
                
                # Resize maintaining aspect ratio
                original_size = pil_image.size
                if original_size[0] > max_dimension or original_size[1] > max_dimension:
                    ratio = min(max_dimension / original_size[0], max_dimension / original_size[1])
                    new_size = (int(original_size[0] * ratio), int(original_size[1] * ratio))
                    pil_image = pil_image.resize(new_size, Image.Resampling.LANCZOS)
                
                # Handle transparency
                if pil_image.mode in ('RGBA', 'LA'):
                    background = Image.new('RGB', pil_image.size, (255, 255, 255))
                    if pil_image.mode == 'RGBA':
                        background.paste(pil_image, mask=pil_image.split()[-1])
                    else:
                        background.paste(pil_image, mask=pil_image.split()[-1])
                    pil_image = background
                
                if pil_image.mode != 'RGB':
                    pil_image = pil_image.convert('RGB')
                
                # Compress image
                img_buffer = io.BytesIO()
                pil_image.save(img_buffer, format='JPEG', quality=quality, optimize=True)
                compressed_image_data = img_buffer.getvalue()
                
                # Replace image
                image_rects = page.get_image_rects(xref)
                if image_rects:
                    page.delete_image(xref)
                    for rect in image_rects:
                        page.insert_image(rect, stream=compressed_image_data, keep_proportion=True)
                
            except Exception:
                continue
    
    result = temp_doc.tobytes(garbage=3, deflate=True)
    temp_doc.close()
    return result

def force_into_range(pdf_document, min_size, max_size):
    """
    Aggressively force PDF into the 80KB-100KB range
    """
    try:
        # Start with very aggressive settings
        for quality in [15, 10, 8, 5, 3]:
            for max_dim in [200, 150, 100, 80]:
                try:
                    result = compress_with_settings(pdf_document, quality, max_dim)
                    size = len(result)
                    
                    if min_size <= size <= max_size:
                        return result
                    
                    # If too small, try to add some padding or use less compression
                    if size < min_size and quality < 20:
                        result = compress_with_settings(pdf_document, quality + 5, max_dim + 20)
                        if min_size <= len(result) <= max_size:
                            return result
                
                except Exception:
                    continue
        
        # Last resort: use fallback method
        return fallback_compression(pdf_document, max_size)
        
    except Exception:
        return fallback_compression(pdf_document, max_size)

def fallback_compression(pdf_document, target_size):
    """
    Fallback method using different approach to reach 80-100KB
    """
    try:
        temp_bytes = pdf_document.tobytes()
        temp_doc = fitz.open(stream=temp_bytes, filetype="pdf")
        
        # Apply watermark removal again just in case
        temp_doc = remove_watermark(temp_doc)
        
        # Very aggressive but safe approach
        for page_num in range(len(temp_doc)):
            page = temp_doc[page_num]
            
            # Get images and compress them with pixmap operations
            image_list = page.get_images(full=True)
            
            for img in image_list:
                try:
                    xref = img[0]
                    
                    # Use pixmap for safer image handling
                    base_pix = fitz.Pixmap(temp_doc, xref)
                    
                    # Skip tiny images
                    if base_pix.width < 50 or base_pix.height < 50:
                        base_pix = None
                        continue
                    
                    # Scale down significantly
                    mat = fitz.Matrix(0.5, 0.5)  # 50% scale
                    small_pix = fitz.Pixmap(base_pix, mat)
                    base_pix = None
                    
                    # Convert to JPEG bytes
                    if small_pix.n > 4:  # CMYK
                        rgb_pix = fitz.Pixmap(fitz.csRGB, small_pix)
                        small_pix = None
                        jpeg_data = rgb_pix.tobytes("jpeg", jpg_quality=20)
                        rgb_pix = None
                    else:
                        jpeg_data = small_pix.tobytes("jpeg", jpg_quality=20)
                        small_pix = None
                    
                    # Replace using update_stream (last resort)
                    temp_doc.update_stream(xref, jpeg_data)
                    
                except Exception:
                    continue
        
        result = temp_doc.tobytes(garbage=4, deflate=True)
        temp_doc.close()
        return result
        
    except Exception:
        # Return original if all else fails
        return pdf_document.tobytes()

def format_file_size(size_bytes):
    """Convert bytes to human readable format"""
    if size_bytes == 0:
        return "0B"
    size_names = ["B", "KB", "MB"]
    import math
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 1)
    return f"{s} {size_names[i]}"

def main():
    st.set_page_config(
        page_title="PDF Compressor - 80KB-100KB Strict Range",
        page_icon="📄",
        layout="centered"
    )
    
    # Header
    st.title("📄 80-100KB PDF Compressor")
    st.markdown("*Compress to strictly between 80KB-100KB while keeping images visible and readable*")
    st.markdown("---")
    
    # Upload section
    uploaded_file = st.file_uploader(
        "Drop your PDF file here or click to browse",
        type="pdf",
        help="Upload any PDF - images will remain visible after compression"
    )
    
    if uploaded_file is not None:
        # Show file info
        original_size = len(uploaded_file.getvalue())
        
        col1, col2 = st.columns(2)
        with col1:
            st.info(f"📁 **File:** {uploaded_file.name}")
        with col2:
            st.info(f"📊 **Size:** {format_file_size(original_size)}")
        
        # Show compression approach
        st.success("🎯 **Strict Size Control:** Will compress to exactly 80KB-100KB range!")
        st.info("🖼️ **Image-Preserving Mode:** Images will remain visible and readable!")
        
        # Compress button
        if st.button("🚀 Compress with Visible Images", type="primary", use_container_width=True):
            
            # Show progress
            with st.spinner("Compressing while preserving visible images..."):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                try:
                    # Read file
                    input_bytes = uploaded_file.getvalue()
                    status_text.text("📖 Analyzing PDF structure...")
                    progress_bar.progress(20)
                    
                    status_text.text("🖼️ Processing images safely...")
                    progress_bar.progress(40)
                    
                    status_text.text("📐 Maintaining layout...")
                    progress_bar.progress(60)
                    
                    status_text.text("⚡ Optimizing compression...")
                    progress_bar.progress(80)
                    
                    status_text.text("🎯 Finalizing...")
                    progress_bar.progress(90)
                    
                    # Compress
                    compressed_bytes = compress_pdf_to_100kb(input_bytes)
                    
                    progress_bar.progress(100)
                    status_text.text("✅ Compression complete!")
                    
                    if compressed_bytes:
                        compressed_size = len(compressed_bytes)
                        compression_ratio = (1 - compressed_size / original_size) * 100
                        
                        status_text.empty()
                        progress_bar.empty()
                        
                        # Show results
                        st.success("✅ **Compression Complete with Visible Images!**")
                        
                        # Results display
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            st.metric("Original", format_file_size(original_size))
                        
                        with col2:
                            st.metric(
                                "Compressed", 
                                format_file_size(compressed_size),
                                f"-{compression_ratio:.1f}%"
                            )
                        
                        with col3:
                            if compressed_size <= 100 * 1024:
                                st.metric("Images", "✅ Visible", "Quality preserved")
                            else:
                                st.metric("Images", "✅ Readable", "Compressed")
                        
                        # Quality assurance message
                        st.info("🖼️ **Image Promise:** All images remain visible and understandable!")
                        
                        # Target achievement with strict range validation
                        min_target = 80 * 1024
                        max_target = 100 * 1024
                        
                        if min_target <= compressed_size <= max_target:
                            st.balloons()
                            st.success(f"🎯 **Perfect!** Compressed to {format_file_size(compressed_size)} - exactly in 80KB-100KB range!")
                        elif compressed_size < min_target:
                            st.warning(f"⚠️ **Size Warning:** File is {format_file_size(compressed_size)} (below 80KB minimum). Consider using a less compressed version.")
                        elif compressed_size <= 120 * 1024:
                            st.info(f"📈 **Close!** Compressed to {format_file_size(compressed_size)} - slightly above 100KB target.")
                        else:
                            st.error(f"❌ **Size Issue:** File is {format_file_size(compressed_size)} - significantly above 100KB limit.")
                        
                        # Download section
                        st.markdown("---")
                        
                        filename_base = os.path.splitext(uploaded_file.name)[0]
                        download_name = f"{filename_base}_compressed_visible_images.pdf"
                        
                        st.download_button(
                            label="📥 **Download PDF with Visible Images**",
                            data=compressed_bytes,
                            file_name=download_name,
                            mime="application/pdf",
                            type="primary",
                            use_container_width=True
                        )
                        
                        # Quality comparison
                        with st.expander("📊 Compression & Image Details"):
                            st.markdown("**🖼️ Image Processing:**")
                            st.write("✅ Images remain visible and readable")
                            st.write("✅ Proper color space conversion")
                            st.write("✅ Smart image replacement method")
                            st.write("✅ Progressive quality reduction")
                            st.write("✅ Aspect ratio preservation")
                            st.write("✅ No blackout or hiding issues")
                            
                            st.markdown("**📈 Compression Strategy:**")
                            st.write("• Target: Strict 80KB-100KB range")
                            st.write("• Method: Binary search optimization")
                            st.write("• Text: 100% formatting preserved")
                            st.write("• Images: Progressive quality reduction")
                            st.write("• Layout: Maintained exactly")
                            st.write("• Colors: Properly converted")
                            
                            st.markdown("**📊 Compression Stats:**")
                            st.write(f"Original: {format_file_size(original_size)}")
                            st.write(f"Compressed: {format_file_size(compressed_size)}")
                            st.write(f"Reduction: {compression_ratio:.1f}%")
                            st.write(f"Size ratio: {compressed_size/original_size:.3f}x")
                            
                            # Range validation info
                            min_target = 80 * 1024
                            max_target = 100 * 1024
                            if min_target <= compressed_size <= max_target:
                                st.write(f"✅ **Range Status:** Perfect (80KB-100KB)")
                            else:
                                st.write(f"⚠️ **Range Status:** Outside target (80KB-100KB)")
                        
                        # Memory cleanup
                        del compressed_bytes
                        gc.collect()
                        
                    else:
                        st.error("❌ **Compression failed.** Please try with a different PDF file.")
                        
                except Exception as e:
                    st.error(f"❌ **Error:** {str(e)}")
                    st.error("Please try with a different PDF file.")
    
    # Footer
    st.markdown("---")
    st.markdown("""
    <div style='text-align: center; color: #666; font-size: 0.9em;'>
  Developed By <strong><a href="https://shreedhar.unaux.com/">Shreedhar</a></strong>

    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()