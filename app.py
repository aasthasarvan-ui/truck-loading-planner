import streamlit as st
import pandas as pd
import math
import json
from PIL import Image
from google import genai
from google.genai import types

st.set_page_config(page_title="Truck Loading Planner & OCR", layout="wide")
st.title("🚚 Truck Loading Sequence Planner (Image & Excel)")

# Sidebar Settings
st.sidebar.header("⚙️ Settings & API")
api_key = st.sidebar.text_input("Gemini API Key (Image scan ke liye):", type="password")
if not api_key:
    # Environment variable check
    import os
    api_key = os.environ.get("GEMINI_API_KEY", "")

col1, col2 = st.columns(2)
with col1:
    capacity = st.number_input("Gaadi Ki Total Capacity (Bags):", min_value=10, value=610, step=10)
with col2:
    num_lines = st.number_input("Gaadi Me Total Lines/Bays:", min_value=1, value=10, step=1)

upload_mode = st.radio("Demand Upload Ka Tareeka Chunein:", ["📄 Excel / CSV Upload", "📸 Image Upload (Photo/Screenshot)"], horizontal=True)

df = None

# --- METHOD 1: EXCEL / CSV ---
if upload_mode == "📄 Excel / CSV Upload":
    uploaded_file = st.file_uploader("Demand Excel/CSV File Upload Karein", type=["xlsx", "xls", "csv"])
    if uploaded_file:
        df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith(('.xlsx', '.xls')) else pd.read_csv(uploaded_file)

# --- METHOD 2: IMAGE UPLOAD (OCR) ---
else:
    img_file = st.file_uploader("Demand Ki Photo/Image Upload Karein", type=["png", "jpg", "jpeg"])
    if img_file:
        image = Image.open(img_file)
        st.image(image, caption="Uploaded Demand Image", use_column_width=True)
        
        if st.button("🔍 Scan & Extract Data From Image"):
            if not api_key:
                st.error("Kripya sidebar me Gemini API Key dalein.")
            else:
                with st.spinner("AI photo se table extract kar raha hai..."):
                    try:
                        client = genai.Client(api_key=api_key)
                        prompt = """
                        Extract the tabular demand data from this image.
                        Return ONLY a valid JSON array of objects representing rows.
                        Each object must have:
                        - 'POS_Party': Name or code of the POS/Customer (e.g. 'POS4146', 'DR17032')
                        - Material keys with their numeric integer bag count (only positive counts).
                        Do not include total rows or empty materials.
                        Example JSON format:
                        [
                          {"POS_Party": "DR17032", "MS30": 115, "TF": 25, "PC-60": 10},
                          {"POS_Party": "POS4146", "MS18 P": 10, "HC": 25, "TF": 30, "CB": 20, "PC-60": 15, "C/G": 10}
                        ]
                        """
                        response = client.models.generate_content(
                            model="gemini-3.8-flash",
                            contents=[prompt, image],
                            config=types.GenerateContentConfig(response_mime_type="application/json")
                        )
                        parsed_json = json.loads(response.text)
                        df = pd.DataFrame(parsed_json).fillna(0)
                        st.session_state["extracted_df"] = df
                        st.success("Table extract ho gaya!")
                    except Exception as e:
                        st.error(f"Image extract karne me error aaya: {e}")

if "extracted_df" in st.session_state and upload_mode == "📸 Image Upload (Photo/Screenshot)":
    df = st.session_state["extracted_df"]

# --- CORE LOGIC & LOADING SEQUENCE GENERATION ---
if df is not None:
    st.markdown("---")
    st.subheader("📋 Demand Table Preview")
    st.dataframe(df, use_container_width=True)
    
    # Identify Party column and material columns
    party_col = st.selectbox("POS / Party Column Chunein:", df.columns, index=0)
    numeric_cols = [c for c in df.columns if c != party_col and pd.api.types.is_numeric_dtype(df[c])]
    material_cols = [c for c in numeric_cols if not str(c).lower().startswith('total')]
    
    parties = df[party_col].astype(str).unique().tolist()
    
    st.markdown("---")
    st.subheader("📍 Unloading Route / Sequence (Drop Order)")
    st.write("Gaadi se **Drop 1 (sabse pehle)** se lekar **aakhri drop** tak sequence select karein:")
    
    delivery_order = st.multiselect(
        "Delivery / Unload Order (First to Last Drop):",
        options=parties,
        default=parties
    )
    
    if st.button("🚀 Generate Loading Plan", type="primary"):
        if len(delivery_order) != len(parties):
            st.warning("Sabhi parties ka sequence select karein.")
        else:
            # LIFO: Aakhri drop Cabin me (Line 1), Pehla drop Gate pe (Last line)
            loading_order = list(reversed(delivery_order))
            target_per_line = math.ceil(capacity / num_lines)
            
            # Helper: Line positions label
            def get_position_label(line_idx, total):
                if line_idx == 1:
                    return "Line 1 (Cabin Front)"
                elif line_idx == total:
                    return f"Line {total} (Dala / Gate End)"
                elif line_idx <= math.ceil(total * 0.35):
                    return f"Line {line_idx} (Cabin Side)"
                elif line_idx >= math.floor(total * 0.7):
                    return f"Line {line_idx} (Gate Side)"
                else:
                    return f"Line {line_idx} (Middle Body)"

            plan_rows = []
            for line_idx in range(1, num_lines + 1):
                row_dict = {
                    "Line No.": f"Line {line_idx}",
                    "Position In Truck": get_position_label(line_idx, num_lines)
                }
                for m in material_cols:
                    row_dict[m] = ""
                row_dict["Total Bags"] = 0
                plan_rows.append(row_dict)
                
            curr_line = 0
            curr_filled = 0
            party_positions = {}  # Tracks which lines each POS occupies

            for p in loading_order:
                p_rows = df[df[party_col].astype(str) == p]
                party_positions[p] = set()
                
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
                            party_positions[p].add(curr_line + 1)
                            entry = f"{fill} ({p})"
                            existing = plan_rows[curr_line][m]
                            plan_rows[curr_line][m] = f"{existing} + {entry}" if existing else entry
                            plan_rows[curr_line]["Total Bags"] += fill
                            curr_filled += fill
                            qty -= fill
                            
            result_df = pd.DataFrame(plan_rows)
            
            # --- SUMMARY OF POS LOCATIONS ---
            st.markdown("---")
            st.subheader("📌 Party / POS Wise Gaadi Me Location Summary")
            
            summary_cards = []
            for idx, p in enumerate(delivery_order):
                lines_occupied = sorted(list(party_positions.get(p, [])))
                lines_str = ", ".join([f"Line {l}" for l in lines_occupied])
                
                # Tagging side
                if all(l <= 3 for l in lines_occupied):
                    side = "Cabin Side (Peeche)"
                elif all(l >= num_lines - 2 for l in lines_occupied):
                    side = "Gate Side (Dala ke Paas)"
                else:
                    side = "Middle / Center"
                    
                summary_cards.append({
                    "Drop No.": f"Drop {idx + 1}",
                    "POS / Party Name": p,
                    "Gaadi Me Location": side,
                    "Loading Lines": lines_str
                })
                
            st.dataframe(pd.DataFrame(summary_cards), use_container_width=True)

            # --- DETAILED 10-LINE TABLE ---
            st.markdown("---")
            st.subheader("🚛 Final Line-Wise & Material-Wise Loading Chart")
            st.dataframe(result_df, use_container_width=True)
            
            csv = result_df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Loading Plan (CSV)", csv, "Loading_Plan.csv", "text/csv")
