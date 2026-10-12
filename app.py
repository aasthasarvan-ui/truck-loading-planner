import streamlit as st
import pandas as pd
import math

st.set_page_config(page_title="Truck Loading Planner", layout="wide")
st.title("🚚 Vehicle Loading Sequence Planner")

uploaded_file = st.file_uploader("Demand Excel/CSV File Upload Karein", type=["xlsx", "xls", "csv"])

col1, col2 = st.columns(2)
with col1:
    capacity = st.number_input("Gaadi Ki Total Capacity (Bags):", min_value=10, value=610, step=10)
with col2:
    num_lines = st.number_input("Gaadi Me Total Lines/Bays:", min_value=1, value=10, step=1)

if uploaded_file:
    # Read sheet (header row adjust kar sakte hain requirement ke hisab se)
    df = pd.read_excel(uploaded_file) if uploaded_file.name.endswith(('.xlsx', '.xls')) else pd.read_csv(uploaded_file)
    
    st.subheader("Uploaded Demand Preview")
    st.dataframe(df.head(), use_container_width=True)
    
    # 1. Party/POS Identification
    party_col = st.selectbox("Party/POS Name Ka Column Chunein:", df.columns, index=0)
    
    # Material columns detect karna (numeric columns jisme quantity hai)
    numeric_cols = [c for c in df.columns if c != party_col and pd.api.types.is_numeric_dtype(df[c])]
    material_cols = [c for c in numeric_cols if not c.lower().startswith('total')]
    
    parties = df[party_col].dropna().unique().tolist()
    
    st.markdown("---")
    st.subheader("📍 Delivery / Unloading Sequence Set Karein")
    st.write("Gaadi se **pehla drop kaunsa utrega aur aakhri kaunsa**, kram anusar chunein:")
    
    delivery_order = st.multiselect(
        "Unloading Order (Pehle Drop 1 chunein, fir Drop 2, etc.):",
        options=parties,
        default=parties
    )
    
    if st.button("Generate Loading Table", type="primary"):
        if len(delivery_order) != len(parties):
            st.warning("Kripya sabhi parties ka sequence select karein.")
        else:
            # LIFO: Aakhri drop Cabin me (Line 1), Pehla drop Gate pe (Line 10)
            loading_order = list(reversed(delivery_order))
            target_per_line = math.ceil(capacity / num_lines)
            
            # Setup plan grid
            plan_rows = []
            for line_idx in range(1, num_lines + 1):
                pos_label = "Cabin Side" if line_idx == 1 else ("Gate Side" if line_idx == num_lines else "Middle")
                row_dict = {"Line No.": f"Line {line_idx}", "Position": pos_label}
                for m in material_cols:
                    row_dict[m] = ""
                row_dict["Total Bags"] = 0
                plan_rows.append(row_dict)
                
            curr_line = 0
            curr_filled = 0
            
            for p in loading_order:
                p_rows = df[df[party_col] == p]
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
                            entry = f"{fill} ({p})"
                            existing = plan_rows[curr_line][m]
                            plan_rows[curr_line][m] = f"{existing} + {entry}" if existing else entry
                            plan_rows[curr_line]["Total Bags"] += fill
                            curr_filled += fill
                            qty -= fill
                            
            result_df = pd.DataFrame(plan_rows)
            st.success(f"✅ Loading Plan Successfully Ban Gaya! (~{target_per_line} bags per line)")
            st.dataframe(result_df, use_container_width=True)
            
            # Download Button
            csv = result_df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Loading Plan (CSV)", csv, "Loading_Plan.csv", "text/csv")
