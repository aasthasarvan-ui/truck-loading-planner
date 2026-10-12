import streamlit as st
import pandas as pd
import numpy as np
import cv2
import math
import pytesseract
import re
from PIL import Image

st.set_page_config(page_title="Truck Loading Planner", layout="wide")
st.title("🚚 Truck Loading Sequence Planner")

# 1. Inputs (Khali placeholders)
col1, col2 = st.columns(2)
with col1:
    capacity = st.number_input("Gaadi Ki Total Capacity (Bags):", min_value=1, value=None, placeholder="Total Bags dalein...")
with col2:
    num_lines = st.number_input("Gaadi Me Total Lines/Bays:", min_value=1, value=None, placeholder="Total Lines dalein...")

upload_mode = st.radio("Demand Upload Ka Tareeka Chunein:", ["📸 Image Upload (Auto Table Conversion)", "📄 Excel / CSV Upload"], horizontal=True)

df = None

# --- OPENCV TABLE GRID & CELL EXTRACTION FUNCTION ---
def extract_table_from_image(pil_image):
    # Convert PIL Image to OpenCV Grayscale
    img = np.array(pil_image.convert('RGB'))
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    
    # Otsu thresholding for sharp grid lines
    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    
    # Horizontal & Vertical line kernels
    kernel_len = np.array(img).shape[1] // 40
    ver_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kernel_len))
    hor_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_len, 1))
    
    # Detect lines
    image_1 = cv2.erode(thresh, ver_kernel, iterations=3)
    vertical_lines = cv2.dilate(image_1, ver_kernel, iterations=3)
    
    image_2 = cv2.erode(thresh, hor_kernel, iterations=3)
    horizontal_lines = cv2.dilate(image_2, hor_kernel, iterations=3)
    
    # Combine lines to get grid intersections
    table_grid = cv2.addWeighted(vertical_lines, 0.5, horizontal_lines, 0.5, 0.0)
    _, table_grid = cv2.threshold(table_grid, 128, 255, cv2.THRESH_BINARY)
    
    # Find bounding boxes of all table cells
    contours, _ = cv2.findContours(table_grid, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    
    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w > 25 and h > 15:  # Cell size filter
            boxes.append((x, y, w, h))
            
    # Standard columns matching demand sheets
    known_columns = [
        "POS_Party", "MS10 M", "MS10 P", "MS18 M", "MS18 P", "MS30", 
        "BC10", "BC18", "MSSP+", "HC", "TF", "CB", "PC-60", "C/G", 
        "SHAKTI MSH", "BC-30", "MS-55", "PS"
    ]
    
    # Fallback / Direct OCR parsing if table grid contours are very faint
    custom_config = r'--oem 3 --psm 6'
    raw_ocr_text = pytesseract.image_to_string(gray, config=custom_config)
    
    extracted_rows = []
    for line in raw_ocr_text.splitlines():
        line_str = line.strip()
        if not line_str or "DHULE" in line_str.upper() or "TOTAL" in line_str.upper():
            continue
            
        # Match party / DR / POS pattern
        pos_match = re.search(r'(DR\s*\d+|POS\s*\d+|[A-Za-z\s]+(?:VPO|At-|Traders))', line_str, re.IGNORECASE)
        if pos_match:
            party_identifier = pos_match.group(0).strip()
            # Extract numbers in this row
            nums = [int(n) for n in re.findall(r'\b\d+\b', line_str) if int(n) <= 500]
            
            # Map numbers under columns
            row_dict = {"POS_Party": party_identifier}
            for col in known_columns[1:]:
                row_dict[col] = 0
                
            # Populate numbers
            for idx, val in enumerate(nums):
                if idx + 1 < len(known_columns):
                    row_dict[known_columns[idx + 1]] = val
                    
            extracted_rows.append(row_dict)
            
    if extracted_rows:
        return pd.DataFrame(extracted_rows)
    else:
        # Default empty template with zero values if image is completely unreadable
        return pd.DataFrame([{c: ("" if c == "POS_Party" else 0) for c in known_columns}])

# --- METHOD 1: EXCEL / CSV ---
if upload_mode == "📄 Excel / CSV Upload":
    uploaded_file = st.file_uploader("Demand Excel/CSV File Upload Karein", type=["xlsx", "xls", "csv"])
    if uploaded_file:
        df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith(('.xlsx', '.xls')) else pd.read_csv(uploaded_file)

# --- METHOD 2: AUTO IMAGE TO TABLE CONVERSION ---
else:
    img_file = st.file_uploader("Demand Photo Upload Karein", type=["png", "jpg", "jpeg"])
    
    if img_file:
        pil_img = Image.open(img_file)
        st.image(pil_img, caption="Uploaded Demand Sheet", use_container_width=True)
        
        if st.button("⚡ Image Se Table Auto-Convert Karein", type="primary"):
            with st.spinner("OpenCV Grid Detect karke table convert kar raha hai..."):
                converted_df = extract_table_from_image(pil_img)
                st.session_state["auto_table_df"] = converted_df
                st.success("Image table me convert ho gayi!")

    if "auto_table_df" in st.session_state and upload_mode == "📸 Image Upload (Auto Table Conversion)":
        st.subheader("📋 Image Se Auto-Convert Hua Data Table")
        st.caption("Aap kisi bhi cell ki quantity ko yahan click karke direct adjust/verify kar sakte hain:")
        edited_df = st.data_editor(st.session_state["auto_table_df"], num_rows="dynamic", use_container_width=True)
        df = edited_df

# --- CORE LOGIC & LOADING SEQUENCE GENERATION ---
if df is not None and not df.empty:
    st.markdown("---")
    st.subheader("📋 Confirmed Demand Table")
    st.dataframe(df, use_container_width=True)
    
    party_col = st.selectbox("POS / Party Column Chunein:", df.columns, index=0)
    numeric_cols = [c for c in df.columns if c != party_col and pd.api.types.is_numeric_dtype(df[c])]
    material_cols = [c for c in numeric_cols if not str(c).lower().startswith('total')]
    
    parties = df[party_col].astype(str).unique().tolist()
    
    # --- HAR PARTY KI GAADI ME POSITION SETTING (PREVIOUS OPTION) ---
    st.markdown("---")
    st.subheader("📍 Gaadi Me Party Ki Position Set Karein")
    
    tab1, tab2 = st.tabs(["1️⃣ Unloading Sequence (Drop Order)", "2️⃣ Direct Zone Allocation (Gate/Cabin/Middle)"])
    
    with tab1:
        st.write("Gaadi se **Drop 1 (sabse pehle utrega)** se lekar **aakhri drop** tak sequence chunein:")
        delivery_order = st.multiselect(
            "Delivery / Unloading Sequence (Pehle se Aakhri):",
            options=parties,
            default=parties
        )
        
    with tab2:
        st.write("Har party ka gaadi me specific area fix karein:")
        party_zone_selection = {}
        cols_grid = st.columns(2)
        for i, p in enumerate(parties):
            with cols_grid[i % 2]:
                zone = st.selectbox(
                    f"**{p}** Area:",
                    options=["Gate Side (Dala - Pehle Utregi)", "Middle (Beech Me)", "Cabin Side (Peeche - Last Me Utregi)"],
                    index=0,
                    key=f"zone_{p}"
                )
                party_zone_selection[p] = zone

    position_mode = st.radio("Kaunse tareeqe se loading banayein?", ["Delivery Sequence (Drop Order)", "Zone Wise (Cabin/Gate Selection)"], horizontal=True)

    if st.button("🚀 Generate Final Loading Plan", type="primary"):
        if not capacity or not num_lines:
            st.error("Kripya upar Gaadi Ki Capacity aur Total Lines dalein.")
        else:
            capacity = int(capacity)
            num_lines = int(num_lines)
            
            if position_mode == "Delivery Sequence (Drop Order)":
                # LIFO rule: Aakhri drop Cabin me (Line 1), Pehla drop Gate pe (Last line)
                loading_order = list(reversed(delivery_order))
            else:
                zone_priority = {
                    "Cabin Side (Peeche - Last Me Utregi)": 1,
                    "Middle (Beech Me)": 2,
                    "Gate Side (Dala - Pehle Utregi)": 3
                }
                loading_order = sorted(parties, key=lambda p: zone_priority[party_zone_selection[p]])

            target_per_line = math.ceil(capacity / num_lines)
            
            def get_line_label(l_idx, total):
                if l_idx == 1:
                    return "Cabin Side"
                elif l_idx == total:
                    return "Gate / Dala Side"
                elif l_idx <= math.ceil(total * 0.35):
                    return "Cabin Area"
                elif l_idx >= math.floor(total * 0.7):
                    return "Gate Area"
                else:
                    return "Middle"

            plan_rows = []
            for line_idx in range(1, num_lines + 1):
                row_dict = {
                    "Line No.": f"Line {line_idx}",
                    "Position": get_line_label(line_idx, num_lines)
                }
                for m in material_cols:
                    row_dict[m] = ""
                row_dict["Total Bags"] = 0
                plan_rows.append(row_dict)
                
            curr_line = 0
            curr_filled = 0
            allocated_lines = {}

            for p in loading_order:
                p_rows = df[df[party_col].astype(str) == p]
                allocated_lines[p] = set()
                
                for _, row in p_rows.iterrows():
                    for m in material_cols:
                        qty = row[m]
                        if pd.isna(qty) or qty <= 0:
                            continue
                        qty = int(qty)
                        
                        while qty > 0:
                            space = target_per_line - curr_filled
                            if space <= 0:
                                if curr_line < num_lines - 1:
                                    curr_line += 1
                                    curr_filled = 0
                                    space = target_per_line
                                else:
                                    space = qty
                                    
                            fill = min(qty, space)
                            allocated_lines[p].add(curr_line + 1)
                            
                            # Clean quantity values inside cell (Only numbers, No text)
                            existing = plan_rows[curr_line][m]
                            if existing:
                                plan_rows[curr_line][m] = f"{existing} + {fill}"
                            else:
                                plan_rows[curr_line][m] = str(fill)
                                
                            plan_rows[curr_line]["Total Bags"] += fill
                            curr_filled += fill
                            qty -= fill
                            
            result_df = pd.DataFrame(plan_rows)
            
            # Summary Table
            st.markdown("---")
            st.subheader("📌 Party Wise Gaadi Me Location")
            summary_data = []
            for p in parties:
                lines_list = sorted(list(allocated_lines.get(p, [])))
                lines_str = ", ".join([f"Line {l}" for l in lines_list])
                summary_data.append({
                    "POS / Party": p,
                    "Gaadi Me Allotted Lines": lines_str
                })
            st.dataframe(pd.DataFrame(summary_data), use_container_width=True)

            # Final Clean Loading Chart
            st.markdown("---")
            st.subheader("🚛 Final Line-Wise Loading Chart")
            st.dataframe(result_df, use_container_width=True)
            
            csv = result_df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Loading Plan (CSV)", csv, "Loading_Plan.csv", "text/csv")
