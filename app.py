import streamlit as st
import pandas as pd
import numpy as np
import math
import json
import io
import time
from PIL import Image
from google import genai
from google.genai import types

st.set_page_config(page_title="Truck Loading Planner", layout="wide")
st.title("🚚 Truck Loading Sequence Planner (Latest Gemini AI)")

# Sidebar Settings
st.sidebar.header("⚙️ Settings & API")
api_key = st.sidebar.text_input("Gemini API Key:", type="password")
if not api_key:
    import os
    api_key = os.environ.get("GEMINI_API_KEY", "")

# Inputs (Blank placeholders, no pre-filled defaults)
col1, col2 = st.columns(2)
with col1:
    capacity = st.number_input("Gaadi Ki Total Capacity (Bags):", min_value=1, value=None, placeholder="Total Bags dalein...")
with col2:
    num_lines = st.number_input("Gaadi Me Total Lines/Bays:", min_value=1, value=None, placeholder="Total Lines dalein...")

upload_mode = st.radio("Demand Upload Ka Tareeka Chunein:", ["📸 Image Upload (AI Auto-Scan)", "📄 Excel / CSV Upload"], horizontal=True)

df = None

# Fast Image Preprocessing
def prepare_fast_image(uploaded_img):
    img = Image.open(uploaded_img)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    max_dimension = 1600
    if max(img.size) > max_dimension:
        img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85, optimize=True)
    buffer.seek(0)
    return Image.open(buffer)

# --- METHOD 1: EXCEL / CSV ---
if upload_mode == "📄 Excel / CSV Upload":
    uploaded_file = st.file_uploader("Demand Excel/CSV File Upload Karein", type=["xlsx", "xls", "csv"])
    if uploaded_file:
        df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith(('.xlsx', '.xls')) else pd.read_csv(uploaded_file)

# --- METHOD 2: IMAGE UPLOAD (LATEST GEMINI 2.5 FLASH ONLY) ---
else:
    img_file = st.file_uploader("Demand Photo / Screenshot Upload Karein", type=["png", "jpg", "jpeg"])
    
    if img_file:
        processed_img = prepare_fast_image(img_file)
        st.image(processed_img, caption="Uploaded Demand Sheet", use_container_width=True)
        
        if st.button("⚡ Image Se Table Generate Karein", type="primary"):
            if not api_key:
                st.error("Kripya sidebar me Gemini API Key dalein.")
            else:
                with st.spinner("Latest Gemini AI table scan kar raha hai..."):
                    client = genai.Client(api_key=api_key)
                    prompt = """
                    You are an expert tabular demand data parser.
                    Extract customer rows from this demand sheet.
                    
                    Headers in the sheet typically include:
                    - Customer details / POS / DR code
                    - Material columns: MS10 M, MS10 P, MS18 M, MS18 P, MS30, BC10, BC18, MSSP+, HC, TF, CB, PC-60, C/G, SHAKTI MSH, BC-30, MS-55, PS, etc.
                    
                    Instructions:
                    1. Ignore summary rows like 'DHULE' or 'TOTAL'.
                    2. For each party row:
                       - 'POS_Party': Extract customer name or DR/POS code (e.g. 'DR19172', 'DR17032', 'POS4146').
                       - Map numeric bags under their respective material header keys (only values > 0).
                    3. Return ONLY a valid JSON array of objects.
                    """
                    
                    response = None
                    last_err = None
                    
                    for attempt in range(3):
                        try:
                            response = client.models.generate_content(
                                model="gemini-3.8-flash",
                                contents=[prompt, processed_img],
                                config=types.GenerateContentConfig(response_mime_type="application/json")
                            )
                            if response and response.text:
                                break
                        except Exception as ex:
                            last_err = ex
                            time.sleep(2)

                    if response and response.text:
                        try:
                            clean_text = response.text.strip()
                            if clean_text.startswith("```json"):
                                clean_text = clean_text[7:-3].strip()
                            elif clean_text.startswith("```"):
                                clean_text = clean_text[3:-3].strip()
                                
                            parsed_json = json.loads(clean_text)
                            extracted_df = pd.DataFrame(parsed_json).fillna(0)
                            st.session_state["extracted_df"] = extracted_df
                            st.success("Table extract ho gaya!")
                        except Exception as pe:
                            st.error(f"JSON Parse Error: {pe}")
                    else:
                        st.error(f"Error: {last_err}")

    if "extracted_df" in st.session_state and upload_mode == "📸 Image Upload (AI Auto-Scan)":
        st.subheader("📋 Image Se Auto-Extract Hua Data (Editable)")
        st.caption("Aap kisi bhi cell ki quantity ko click karke direct verify ya theek kar sakte hain:")
        edited_df = st.data_editor(st.session_state["extracted_df"], num_rows="dynamic", use_container_width=True)
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
    
    # --- HAR PARTY KI GAADI ME POSITION SETTING ---
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
                    row_dict[m] = 0
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
                            
                            # DIRECT NUMERIC ADDITION: 42 + 30 text ke badle direct sum 72 banega
                            plan_rows[curr_line][m] += fill
                                
                            plan_rows[curr_line]["Total Bags"] += fill
                            curr_filled += fill
                            qty -= fill
                            
            result_df = pd.DataFrame(plan_rows)
            
            # --- NICHE TOTAL ROW BANANA ---
            total_row = {"Line No.": "TOTAL", "Position": "All Lines"}
            for m in material_cols:
                total_row[m] = int(result_df[m].sum())
            total_row["Total Bags"] = int(result_df["Total Bags"].sum())
            
            # 0 values ko table display me blank dikhana (clean look)
            display_df = result_df.copy()
            for m in material_cols:
                display_df[m] = display_df[m].apply(lambda x: int(x) if x > 0 else "")
                
            display_total_row = total_row.copy()
            for m in material_cols:
                display_total_row[m] = int(display_total_row[m]) if display_total_row[m] > 0 else ""
                
            # Append total row to display table
            final_table = pd.concat([display_df, pd.DataFrame([display_total_row])], ignore_index=True)
            
            # Party Position Summary Table
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

            # Final Clean Loading Chart with Bottom Total
            st.markdown("---")
            st.subheader("🚛 Final Line-Wise Loading Chart")
            st.dataframe(final_table, use_container_width=True)
            
            csv = final_table.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Loading Plan (CSV)", csv, "Loading_Plan.csv", "text/csv")
