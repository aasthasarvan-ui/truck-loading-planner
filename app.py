import streamlit as st
import pandas as pd
import math
import io
from PIL import Image

st.set_page_config(page_title="Truck Loading Planner", layout="wide")
st.title("🚚 Truck Loading Sequence Planner (No API / Offline)")

# 1. Gaadi Inputs (No pre-filled defaults)
col1, col2 = st.columns(2)
with col1:
    capacity = st.number_input("Gaadi Ki Total Capacity (Bags):", min_value=1, value=None, placeholder="Total Bags dalein...")
with col2:
    num_lines = st.number_input("Gaadi Me Total Lines/Bays:", min_value=1, value=None, placeholder="Total Lines dalein...")

upload_mode = st.radio("Demand Upload Ka Tareeka Chunein:", ["📄 Excel / CSV Upload", "📸 Image / Direct Demand Entry"], horizontal=True)

df = None

# --- METHOD 1: EXCEL / CSV ---
if upload_mode == "📄 Excel / CSV Upload":
    uploaded_file = st.file_uploader("Demand Excel/CSV File Upload Karein", type=["xlsx", "xls", "csv"])
    if uploaded_file:
        df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith(('.xlsx', '.xls')) else pd.read_csv(uploaded_file)

# --- METHOD 2: DIRECT / IMAGE ENTRY (100% NO GEMINI / NO API) ---
else:
    st.info("💡 Photo dekh kar direct quantity bharein ya neeche photo upload karke side-by-side verify karein.")
    img_file = st.file_uploader("Reference Demand Photo Upload Karein (Optional)", type=["png", "jpg", "jpeg"])
    
    col_img, col_table = st.columns([1, 1.2])
    
    if img_file:
        with col_img:
            image = Image.open(img_file)
            st.image(image, caption="Uploaded Demand Reference", use_container_width=True)
            
    with col_table:
        st.subheader("Demand Entry Grid")
        st.caption("Aap row add/delete kar sakte hain aur material bag quantities direct edit kar sakte hain:")
        
        # Pre-structured columns matching standard cattle feed products
        default_data = {
            "POS_Party": ["DR17032", "POS4146", "POS4083", "POS4179"],
            "MS18 P": [0, 10, 0, 10],
            "MS30": [115, 0, 100, 45],
            "MSSP+": [0, 0, 0, 55],
            "HC": [0, 25, 0, 30],
            "TF": [25, 30, 50, 30],
            "CB": [0, 20, 0, 0],
            "PC-60": [10, 15, 0, 10],
            "C/G": [0, 10, 0, 20]
        }
        
        # Interactive Streamlit Data Editor (No API needed, instant & fast)
        edited_df = st.data_editor(
            pd.DataFrame(default_data), 
            num_rows="dynamic",
            use_container_width=True
        )
        if st.button("Confirm & Use This Demand Data"):
            st.session_state["manual_df"] = edited_df
            st.success("Demand data set ho gaya!")

if "manual_df" in st.session_state and upload_mode == "📸 Image / Direct Demand Entry":
    df = st.session_state["manual_df"]

# --- CORE LOGIC & LOADING SEQUENCE GENERATION ---
if df is not None:
    st.markdown("---")
    st.subheader("📋 Active Demand Table")
    st.dataframe(df, use_container_width=True)
    
    party_col = st.selectbox("POS / Party Column Chunein:", df.columns, index=0)
    numeric_cols = [c for c in df.columns if c != party_col and pd.api.types.is_numeric_dtype(df[c])]
    material_cols = [c for c in numeric_cols if not str(c).lower().startswith('total')]
    
    parties = df[party_col].astype(str).unique().tolist()
    
    st.markdown("---")
    st.subheader("🎯 Har Party Ki Gaadi Me Position Set Karein")
    
    party_zone_selection = {}
    cols_grid = st.columns(2)
    
    for i, p in enumerate(parties):
        with cols_grid[i % 2]:
            zone = st.selectbox(
                f"**{p}**:",
                options=["Gate Side (Dala - Pehle Utregi)", "Middle (Beech Me)", "Cabin Side (Peeche - Last Me Utregi)"],
                index=0,
                key=f"zone_{p}"
            )
            party_zone_selection[p] = zone

    if st.button("🚀 Generate Final Loading Plan", type="primary"):
        if not capacity or not num_lines:
            st.error("Kripya upar Gaadi Ki Capacity aur Total Lines dalein.")
        else:
            capacity = int(capacity)
            num_lines = int(num_lines)
            
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
            
            # Party Position Summary Table
            st.markdown("---")
            st.subheader("📌 Party Wise Gaadi Me Location")
            summary_data = []
            for p in parties:
                lines_list = sorted(list(allocated_lines.get(p, [])))
                lines_str = ", ".join([f"Line {l}" for l in lines_list])
                summary_data.append({
                    "POS / Party": p,
                    "Selected Area": party_zone_selection[p],
                    "Allotted Lines": lines_str
                })
            st.dataframe(pd.DataFrame(summary_data), use_container_width=True)

            # Final Clean Loading Chart
            st.markdown("---")
            st.subheader("🚛 Final Line-Wise Loading Chart")
            st.dataframe(result_df, use_container_width=True)
            
            csv = result_df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Loading Plan (CSV)", csv, "Loading_Plan.csv", "text/csv")
