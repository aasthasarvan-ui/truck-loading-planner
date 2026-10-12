import streamlit as st
import pandas as pd
import numpy as np
import math
import io
import re
from PIL import Image
import easyocr

st.set_page_config(page_title="Truck Loading Planner", layout="wide")
st.title("🚚 Truck Loading Sequence Planner")

# 1. Gaadi Inputs (Khali placeholders)
col1, col2 = st.columns(2)
with col1:
    capacity = st.number_input("Gaadi Ki Total Capacity (Bags):", min_value=1, value=None, placeholder="Total Bags dalein...")
with col2:
    num_lines = st.number_input("Gaadi Me Total Lines/Bays:", min_value=1, value=None, placeholder="Total Lines dalein...")

upload_mode = st.radio("Demand Upload Ka Tareeka Chunein:", ["📄 Excel / CSV Upload", "📸 Image Upload (Photo To Table)"], horizontal=True)

df = None

# OCR Reader ko cache karein taki bar-bar load na ho
@st.cache_resource
def load_ocr_reader():
    return easyocr.Reader(['en'], gpu=False)

# --- METHOD 1: EXCEL / CSV ---
if upload_mode == "📄 Excel / CSV Upload":
    uploaded_file = st.file_uploader("Demand Excel/CSV File Upload Karein", type=["xlsx", "xls", "csv"])
    if uploaded_file:
        df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith(('.xlsx', '.xls')) else pd.read_csv(uploaded_file)

# --- METHOD 2: IMAGE UPLOAD (EXACT IMAGE DATA EXTRACTION) ---
else:
    img_file = st.file_uploader("Demand Photo Upload Karein", type=["png", "jpg", "jpeg"])
    
    if img_file:
        image = Image.open(img_file)
        st.image(image, caption="Uploaded Demand Sheet", use_container_width=True)
        
        if st.button("⚡ Image Se Table Generate Karein", type="primary"):
            with st.spinner("Photo se exact text aur table scan ho raha hai..."):
                reader = load_ocr_reader()
                img_bytes = io.BytesIO()
                image.save(img_bytes, format='PNG')
                ocr_results = reader.readtext(img_bytes.getvalue())
                
                # Bounding box sorting (Row-wise alignment)
                # Box format: [[x1, y1], [x2, y1], [x2, y2], [x1, y2]], text, confidence
                parsed_boxes = []
                for box, text, conf in ocr_results:
                    y_center = (box[0][1] + box[2][1]) / 2
                    x_center = (box[0][0] + box[1][0]) / 2
                    parsed_boxes.append({"text": text.strip(), "x": x_center, "y": y_center})
                
                # Y-coordinate se line cluster banana
                parsed_boxes = sorted(parsed_boxes, key=lambda b: b["y"])
                lines = []
                current_line = []
                last_y = None
                
                for b in parsed_boxes:
                    if last_y is None or abs(b["y"] - last_y) < 18:
                        current_line.append(b)
                        last_y = b["y"]
                    else:
                        current_line = sorted(current_line, key=lambda b: b["x"])
                        lines.append([item["text"] for item in current_line])
                        current_line = [b]
                        last_y = b["y"]
                if current_line:
                    current_line = sorted(current_line, key=lambda b: b["x"])
                    lines.append([item["text"] for item in current_line])
                
                # Standard Material columns list
                known_materials = ["MS18 P", "MS30", "MSSP+", "HC", "TF", "CB", "PC-60", "C/G", "SHAKTI MSH", "BC-30", "MS-55", "PS"]
                
                # Detect Party / POS rows
                rows_data = []
                for ln in lines:
                    joined = " ".join(ln)
                    # Check for POS code or DR code
                    pos_match = re.search(r'(POS\d+|DR\d+|DR\s*\d+|POS\s*\d+)', joined, re.IGNORECASE)
                    if pos_match:
                        pos_name = pos_match.group(0).replace(" ", "")
                        
                        # Extract all numbers in this line
                        numbers = [int(num) for num in re.findall(r'\b\d+\b', joined) if int(num) <= 500]
                        # Remove the digits inside pos code itself
                        pos_digits = re.findall(r'\d+', pos_name)
                        if pos_digits and int(pos_digits[0]) in numbers:
                            numbers.remove(int(pos_digits[0]))
                            
                        rows_data.append({"POS_Party": pos_name, "raw_numbers": numbers})

                # Table construct karna
                if rows_data:
                    final_rows = []
                    for r in rows_data:
                        row_dict = {"POS_Party": r["POS_Party"]}
                        for m in known_materials:
                            row_dict[m] = 0
                            
                        # Material counts assign
                        nums = r["raw_numbers"]
                        # Agar numbers mile hain toh map karein
                        for idx, val in enumerate(nums):
                            if idx < len(known_materials):
                                row_dict[known_materials[idx]] = val
                        final_rows.append(row_dict)
                        
                    detected_df = pd.DataFrame(final_rows)
                    st.session_state["extracted_df"] = detected_df
                    st.success("Image ka table extract ho gaya!")
                else:
                    st.warning("Automatic POS detect nahi ho paya, kripya check karein.")

    # Image se nikla hua dynamic data yahan load hoga
    if "extracted_df" in st.session_state and upload_mode == "📸 Image Upload (Photo To Table)":
        st.subheader("📋 Image Se Extract Hua Real Data (Editable Grid)")
        st.caption("Aap uploaded sheet ke hisab se kisi bhi cell ko yahan click karke theek kar sakte hain:")
        edited_df = st.data_editor(st.session_state["extracted_df"], num_rows="dynamic", use_container_width=True)
        df = edited_df

# --- CORE LOGIC & LOADING SEQUENCE GENERATION ---
if df is not None:
    st.markdown("---")
    st.subheader("📋 Final Confirmed Demand Data")
    st.dataframe(df, use_container_width=True)
    
    party_col = st.selectbox("POS / Party Column Chunein:", df.columns, index=0)
    numeric_cols = [c for c in df.columns if c != party_col and pd.api.types.is_numeric_dtype(df[c])]
    material_cols = [c for c in numeric_cols if not str(c).lower().startswith('total')]
    
    parties = df[party_col].astype(str).unique().tolist()
    
    # --- HAR PARTY KI POSITION SET KARNE KA OPTION ---
    st.markdown("---")
    st.subheader("📍 Delivery & Gaadi Me Position Set Karein")
    
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

    position_mode = st.radio("Kaunse tareeqe se sequence banayein?", ["Delivery Sequence (Drop Order Wise)", "Zone Wise (Cabin/Gate Selection)"], horizontal=True)

    if st.button("🚀 Generate Final Loading Plan", type="primary"):
        if not capacity or not num_lines:
            st.error("Kripya upar Gaadi Ki Capacity aur Total Lines dalein.")
        else:
            capacity = int(capacity)
            num_lines = int(num_lines)
            
            if position_mode == "Delivery Sequence (Drop Order Wise)":
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
                            
                            # Clean quantity values inside cell (Zero Strings, Only numbers)
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
