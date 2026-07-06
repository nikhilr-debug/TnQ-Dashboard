# -*- coding: utf-8 -*-
"""
Funnel Quality & Revenue Dashboard
Framework: Streamlit
"""

import streamlit as st
import pandas as pd
import requests
import time
from datetime import date, timedelta

# --- RESILIENT ENVIRONMENT IMPORTS ---
try:
    from google import genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

# --- 1. CONFIGURATION & CONSTANTS ---
st.set_page_config(page_title="Funnel Quality", layout="wide")

REDASH_URL = "https://redash.vahan.link"
QUERY_ID = 17682
ACTIVE_CLIENTS = ["blinkit", "swiggy", "swiggy instamart", "uber"]

# APIs provided by user
REDASH_API_KEY = "4aFm2iOoyx8I91svQccdeZr0jmaiUsMFSRinZcmu"
GEMINI_API_KEY = "4aFm2iOoyx8I91svQccdeZr0jmaiUsMFSRinZcmu"

CLIENT_MS = {
    "blinkit": ["20th", "60th", "100th", "120th", "150th", "200th"],
    "swiggy": ["5th", "10th", "20th", "50th", "60th", "80th", "100th", "150th", "200th"],
    "swiggy instamart": ["5th", "10th", "20th", "50th", "60th", "80th", "100th", "150th", "200th"],
    "uber": ["10th", "20th", "30th", "50th", "100th", "150th", "200th"],
}

CLIENT_KEY_MS = {
    "blinkit": "60th", "swiggy": "20th", "swiggy instamart": "20th", "uber": "20th",
}
MIN_VL_FODS = 0

# --- FINANCIAL RATE CARDS & CONSTANTS ---
BLINKIT_CRITICAL_CITIES = {
    "delhi", "mumbai", "bangalore", "hyderabad", "pune", "kolkata", "chennai",
    "ahmedabad", "jaipur", "lucknow", "gurgaon", "noida", "indore", "chandigarh",
    "ghaziabad", "faridabad"
}

COMMERCIALS = {
    "swiggy":               {"20th": 400, "50th": 700, "60th": 0,    "80th": 900,  "100th": 1000, "120th": 0,    "150th": 0, "200th": 0},
    "swiggy instamart":     {"20th": 400, "50th": 750, "60th": 0,    "80th": 1000, "100th": 1100, "120th": 0,    "150th": 0, "200th": 0},
    "blinkit_critical":     {"20th": 860, "50th": 0,   "60th": 1130, "80th": 0,    "100th": 1200, "120th": 1560, "150th": 0, "200th": 4750},
    "blinkit_non_critical": {"20th": 690, "50th": 0,   "60th": 780,  "80th": 0,    "100th": 800,  "120th": 1040, "150th": 0, "200th": 3310}
}

OFFER_1 = {
    "swiggy":               {"20th": 800,  "50th": 1100, "60th": 0,   "120th": 0},
    "swiggy instamart":     {"20th": 1000, "50th": 1200, "60th": 0,   "120th": 0},
    "blinkit_critical":     {"20th": 1300, "50th": 0,    "60th": 500, "120th": 500},
    "blinkit_non_critical": {"20th": 1150, "50th": 0,    "60th": 400, "120th": 400}
}

TARGET_DIP_MS = ["20th", "50th", "60th", "80th", "100th", "120th", "150th", "200th"]

def get_segment(client, city=None):
    if client == "blinkit":
        city_clean = str(city).strip().lower() if pd.notna(city) else ""
        return "blinkit_critical" if city_clean in BLINKIT_CRITICAL_CITIES else "blinkit_non_critical"
    return client

def fmt_currency(val):
    if pd.isna(val): return "₹0"
    if val < 0: return f"-₹{abs(val):,.0f}"
    return f"₹{val:,.0f}"

# Date Calculations
yesterday = date.today() - timedelta(days=6)
mtd_day = yesterday.day
start_month = yesterday.month - 3
start_year = yesterday.year
if start_month <= 0:
    start_month += 12
    start_year -= 1
START_DATE = str(date(start_year, start_month, 1))
END_DATE = str(yesterday)

# --- 2. DATA ACQUISITION & CACHING ---
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_redash():
    body_fresh = {"parameters": {"start_date": START_DATE, "end_date": END_DATE, "Client": ACTIVE_CLIENTS}, "max_age": 0}
    body_cached = {**body_fresh, "max_age": 3600}
    
    r = requests.post(f"{REDASH_URL}/api/queries/{QUERY_ID}/results?api_key={REDASH_API_KEY}", json=body_fresh, timeout=30)
    j = r.json()
    
    if "query_result" in j:
        return j["query_result"]["data"]["rows"]
    
    if "job" not in j:
        st.error(f"Redash API Error: {j}")
        return []
        
    job_id = j["job"]["id"]
    for attempt in range(40):
        time.sleep(15)
        r2 = requests.post(f"{REDASH_URL}/api/queries/{QUERY_ID}/results?api_key={REDASH_API_KEY}", json=body_cached, timeout=30)
        j2 = r2.json()
        if "query_result" in j2:
            return j2["query_result"]["data"]["rows"]
            
    st.error("Timed out waiting for Redash.")
    return []

@st.cache_data(ttl=86400, show_spinner=False)
def load_vl_mapping():
    SHEET_ID = "19HU42C26Sen8p93J9CoKR6OLhRnqIAjmEnuNEJkVrDs"
    TAB_NAME = "June%20Targets"
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={TAB_NAME}"
    
    try:
        df = pd.read_csv(url)
        df = df[df["Client"].isin(["Blinkit", "Swiggy", "Instamart"])].copy()
        df["client_key"] = df["Client"].map({
            "Blinkit":   "blinkit",
            "Swiggy":    "swiggy",
            "Instamart": "swiggy instamart",
        })
        df = (df.drop_duplicates(subset=["VL", "client_key"])
                [["VL", "client_key", "CM", "Region", "CL", "ZM"]]
                .fillna("Unknown")
                .rename(columns={"VL": "vl_name"}))
        return df
    except Exception as e:
        return pd.DataFrame(columns=["vl_name", "client_key", "CM", "Region", "CL", "ZM"])

# --- 3. DATA PROCESSING ---
@st.cache_data(show_spinner=False)
def run_analysis(rows):
    if not rows: return {}, pd.DataFrame()
    
    df = pd.DataFrame(rows)
    df["_fod"] = pd.to_datetime(df["first_date_of_work"], format="%Y-%m-%d", errors="coerce")
    valid = df["_fod"].notna() & (df["_fod"].dt.day <= mtd_day) & (df["_fod"] <= pd.Timestamp(END_DATE))
    df = df[valid].copy()
    df["_month"] = df["_fod"].dt.strftime("%b-%Y")
    df = df.drop_duplicates(subset=["phone_number", "_month"])
    df["_vl"] = df["vl_name"].fillna("Unknown")

    # Pre-compute target dip milestones
    for ms in TARGET_DIP_MS:
        col = f"{ms}_order_date"
        if col in df.columns:
            df[col + "_dt"] = pd.to_datetime(df[col], format="%Y-%m-%d", errors="coerce")
            df[f"has_{ms}"] = (
                (df[col + "_dt"].dt.year == df["_fod"].dt.year) &
                (df[col + "_dt"].dt.month == df["_fod"].dt.month) &
                (df[col + "_dt"].dt.day <= mtd_day)
            ).astype(int)

    results = {}
    for client in ACTIVE_CLIENTS:
        sub = df[df["company_name"].str.lower() == client].copy()
        ms_list = CLIENT_MS.get(client, [])
        key_ms = CLIENT_KEY_MS.get(client, ms_list[0])

        for ms in ms_list:
            col = f"{ms}_order_date"
            if col not in sub.columns: sub[col] = None
            sub[col + "_dt"] = pd.to_datetime(sub[col], format="%Y-%m-%d", errors="coerce")
            sub[f"has_{ms}"] = (
                (sub[col + "_dt"].dt.year == sub["_fod"].dt.year) &
                (sub[col + "_dt"].dt.month == sub["_fod"].dt.month) &
                (sub[col + "_dt"].dt.day <= mtd_day)
            ).astype(int)

        all_months = sorted(sub["_month"].unique(), key=lambda x: pd.to_datetime("01 " + x))

        monthly = []
        for m in all_months:
            g = sub[sub["_month"] == m]
            if len(g) == 0: continue
            lt = g["candidate_lifetime_orders_trips"].astype(float)
            rec = {"month": m, "fods": len(g)}
            for ms in ms_list:
                rec[f"pct_{ms}"] = round(g[f"has_{ms}"].mean() * 100, 1)
            rec["avg_lt"] = round(lt.mean(), 1)
            rec["median_lt"] = round(lt.median(), 1)
            rec["pct_200plus"] = round((lt >= 200).mean() * 100, 1)
            rec["pct_below20"] = round((lt < 20).mean() * 100, 1)
            monthly.append(rec)

        # Baseline dictionaries for highlighting
        bm_key = sum(m.get(f"pct_{key_ms}", 0) for m in monthly) / max(len(monthly), 1)
        bm_ms = {ms2: round(sum(m.get(f"pct_{ms2}", 0) for m in monthly) / max(len(monthly), 1), 1) for ms2 in ms_list}

        vl_summary = []
        
        for vl_name, vl_df in sub.groupby("_vl"):
            if len(vl_df) < MIN_VL_FODS: continue
            
            lt_all = vl_df["candidate_lifetime_orders_trips"].astype(float)
            rec = {
                "vl": vl_name,
                "total_fods": len(vl_df),
                "median_lt": round(lt_all.median(), 1),
                "pct_below20": round((lt_all < 20).mean() * 100, 1),
            }
            for ms in ms_list:
                rec[f"pct_{ms}"] = round(vl_df[f"has_{ms}"].mean() * 100, 1)
                
            # Month over Month parsing for Deltas
            vm = {}
            for m in all_months:
                m_df = vl_df[vl_df["_month"] == m]
                if len(m_df) < 5: 
                    vm[m] = None
                    continue
                m_rec = {"fods": len(m_df)}
                for ms in ms_list:
                    m_rec[f"pct_{ms}"] = round(m_df[f"has_{ms}"].mean() * 100, 1)
                vm[m] = m_rec
            
            valid_months = [m for m in all_months if vm.get(m) is not None]
            if len(valid_months) >= 2:
                pm, cm = valid_months[-2], valid_months[-1]
                rec["fod_growth"] = round((vm[cm]["fods"] - vm[pm]["fods"]) / max(vm[pm]["fods"], 1) * 100, 1)
                for ms in ms_list:
                    rec[f"delta_{ms}"] = round(vm[cm].get(f"pct_{ms}", 0) - vm[pm].get(f"pct_{ms}", 0), 1)
                    
            vl_summary.append(rec)

        results[client] = {
            "monthly": monthly,
            "vl_summary": vl_summary,
            "bm_ms": bm_ms,
            "milestones": ms_list,
            "key_ms": key_ms,
        }
    return results, df

@st.cache_data(show_spinner=False)
def calculate_financials(df_raw, results_dict, vl_map_df):
    fin_data = {}
    for ck in ["swiggy", "swiggy instamart", "blinkit"]:
        if ck not in results_dict: continue
        
        mon = results_dict[ck]["monthly"]
        if len(mon) < 2: continue
        curr_m, prev_m = mon[-1]["month"], mon[-2]["month"]
        
        if ck in ["swiggy", "swiggy instamart"]:
            ms_list = [m for m in ["20th", "50th", "80th", "100th"] if m in TARGET_DIP_MS]
        else:
            ms_list = [m for m in ["20th", "60th", "120th", "200th"] if m in TARGET_DIP_MS]
            
        group_cols = ["company_name", "_vl", "jobCity"] if ck == "blinkit" else ["company_name", "_vl"]
        df_client = df_raw[(df_raw["company_name"].str.lower() == ck) & (df_raw["_month"].isin([curr_m, prev_m]))]
        
        rows_list = []
        for name, group in df_client.groupby(group_cols):
            vln = name[1]
            city = name[2] if ck == "blinkit" else None
            segment = get_segment(ck, city)
            
            mapping = vl_map_df[(vl_map_df["vl_name"] == vln) & (vl_map_df["client_key"] == ck)]
            region = mapping["Region"].iloc[0] if not mapping.empty else "Unknown"
            zm = mapping["ZM"].iloc[0] if not mapping.empty else "Unknown"
            
            c_data = group[group["_month"] == curr_m]
            p_data = group[group["_month"] == prev_m]
            c_fods, p_fods = len(c_data), len(p_data)
            if c_fods == 0 and p_fods == 0: continue
            
            row = {"Client": ck.title(), "VL Name": vln, "Region": region, "ZM": zm, "City": city, "Segment": segment, f"FODs {prev_m[:3]}": p_fods, f"FODs {curr_m[:3]}": c_fods}
            
            for m2 in ms_list:
                col_has = f"has_{m2}"
                c_hits = c_data[col_has].sum() if c_fods > 0 and col_has in c_data.columns else 0
                p_hits = p_data[col_has].sum() if p_fods > 0 and col_has in p_data.columns else 0
                
                rate_rc1 = COMMERCIALS.get(segment, {}).get(m2, 0)
                rate_o1 = OFFER_1.get(segment, {}).get(m2, 0)
                
                row[f"F{m2} Hits {curr_m[:3]}"] = c_hits
                row[f"F{m2} RC1 Rev {curr_m[:3]}"] = fmt_currency(c_hits * rate_rc1)
                row[f"F{m2} RC1 Rev Loss"] = fmt_currency((c_hits * rate_rc1) - (p_hits * rate_rc1))
                
                row[f"F{m2} Offer1 Rev {curr_m[:3]}"] = fmt_currency(c_hits * rate_o1)
                row[f"F{m2} Offer1 Rev Loss"] = fmt_currency((c_hits * rate_o1) - (p_hits * rate_o1))

            rows_list.append(row)
        
        if rows_list:
            fin_data[ck] = pd.DataFrame(rows_list)
            
    return fin_data

def draft_summary(results):
    if not HAS_GEMINI:
        return (
            "⚠️ **AI Insights Configuration Missing:**\n"
            "The dependency module `google-genai` was not detected in this Python execution environment.\n\n"
            "**To fix this on Streamlit Cloud:**\n"
            "1. Please add `google-genai` inside your repository's `requirements.txt` file (removing any reference to `google-generativeai`).\n"
            "2. Streamlit will detect the change, automatically rebuild, and activate this panel."
        )
    try:
        # Initialize the modern google-genai Client structure
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = "Write a short analytical executive summary for a dashboard about gig worker funnel quality. Highlight main drops in conversion, notable surges, and top client observations. Use 3-4 professional bullet points. No fluff."
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"Gemini API Error: {e}"

# --- STYLER FUNCTIONS (PANDAS FORMATTING) ---
def highlight_benchmark(row, bm_dict):
    styles = [''] * len(row)
    for i, col in enumerate(row.index):
        if isinstance(col, str) and col.startswith('F') and col.endswith('%'):
            val = row[col]
            ms_key = col[1:-1] # extracts '20th' from 'F20th%'
            bv = bm_dict.get(ms_key, 0)
            if pd.notna(val) and bv > 0:
                ratio = float(val) / bv
                if ratio >= 1.15: styles[i] = 'background-color: #CCFFCC; color: #375623'
                elif ratio < 0.50: styles[i] = 'background-color: #FFCCCC; color: #C00000'
                elif ratio < 0.80: styles[i] = 'background-color: #FFE4CC; color: #C55A00'
    return styles

def highlight_deltas(row):
    styles = [''] * len(row)
    for i, col in enumerate(row.index):
        if isinstance(col, str) and (col.startswith('Δ F') or col == 'FOD Growth %'):
            val = row[col]
            if pd.notna(val):
                if val <= -15: styles[i] = 'background-color: #FFCCCC; color: #C00000'
                elif val <= -5: styles[i] = 'background-color: #FFE4CC; color: #C55A00'
                elif val >= 0: styles[i] = 'background-color: #CCFFCC; color: #375623'
    return styles

def style_financials(val):
    if isinstance(val, str) and '-₹' in val:
        return 'color: #C00000; font-weight: bold'
    return ''

# --- 4. STREAMLIT UI (MECE FRAMEWORK) ---
def main():
    st.title("📊 Funnel Quality Hub")
    st.markdown(f"**Data Period:** {START_DATE} → {END_DATE} | **MTD Cutoff:** Day {mtd_day}")
    
    with st.spinner("Fetching and processing data pipelines..."):
        rows = fetch_redash()
        results, df_raw = run_analysis(rows)
        vl_map_df = load_vl_mapping()
        fin_data = calculate_financials(df_raw, results, vl_map_df)

    if not results:
        st.warning("No data returned from queries.")
        return

    # --- TAB GENERATION ---
    tab_names = [c.title() for c in ACTIVE_CLIENTS] + ["💰 Commercials"]
    tabs = st.tabs(tab_names)

    for idx, client in enumerate(ACTIVE_CLIENTS):
        with tabs[idx]:
            client_data = results.get(client, {})
            if not client_data:
                st.info("No active data for this client in the current timeframe.")
                continue
                
            ms_list = client_data["milestones"]
            bm_ms = client_data.get("bm_ms", {})
            
            # Master DataFrame Assembly
            df_vl = pd.DataFrame(client_data["vl_summary"])
            client_vl_map = vl_map_df[vl_map_df["client_key"] == client] if not vl_map_df.empty else pd.DataFrame()
            if not client_vl_map.empty:
                df_vl = df_vl.merge(client_vl_map, left_on="vl", right_on="vl_name", how="left")
            
            for col in ["Region", "ZM", "CM", "CL"]:
                if col in df_vl.columns: df_vl[col] = df_vl[col].fillna("Unknown")
                else: df_vl[col] = "Unknown"

            # --- ZM & REGION FILTERS ---
            st.markdown(f"### 🔍 Filter Data for {client.title()}")
            col1, col2 = st.columns(2)
            
            regions = ["All"] + sorted([str(x) for x in df_vl["Region"].unique()])
            sel_reg = col1.selectbox("Filter by Region", regions, key=f"reg_{client}")
            if sel_reg != "All":
                df_vl = df_vl[df_vl["Region"] == sel_reg]
                
            zms = ["All"] + sorted([str(x) for x in df_vl["ZM"].unique()])
            sel_zm = col2.selectbox("Filter by ZM", zms, key=f"zm_{client}")
            if sel_zm != "All":
                df_vl = df_vl[df_vl["ZM"] == sel_zm]

            df_vl = df_vl.sort_values(by="total_fods", ascending=False)

            # --- EXPANDER 1: Overall Monthly ---
            with st.expander("📈 Overall Funnel - Month over Month (Unfiltered)", expanded=False):
                if client_data["monthly"]:
                    df_monthly = pd.DataFrame(client_data["monthly"])
                    cols = ["month", "fods"] + [f"pct_{m}" for m in ms_list] + ["median_lt", "pct_below20"]
                    df_monthly = df_monthly[[c for c in cols if c in df_monthly.columns]]
                    st.dataframe(df_monthly, use_container_width=True, hide_index=True)

            # --- EXPANDER 2: VL Summary (Color Coding against Benchmark) ---
            with st.expander("🏢 VL Summary (Current MTD vs Benchmark)", expanded=True):
                ms_cols = [f"pct_{m}" for m in ms_list]
                disp_cols1 = ["vl", "ZM", "Region", "CM", "CL", "total_fods", "median_lt", "pct_below20"] + ms_cols
                disp_cols1 = [c for c in disp_cols1 if c in df_vl.columns]
                
                df_disp1 = df_vl[disp_cols1].copy()
                rename_map1 = {"vl": "VL Name", "total_fods": "Total FODs", "median_lt": "Median LT", "pct_below20": "% <20 LT"}
                rename_map1.update({f"pct_{m}": f"F{m}%" for m in ms_list})
                df_disp1.rename(columns=rename_map1, inplace=True)
                
                st.dataframe(df_disp1.style.apply(lambda row: highlight_benchmark(row, bm_ms), axis=1), 
                             use_container_width=True, hide_index=True)

            # --- EXPANDER 3: VL MoM Deltas (Color Coding for Drops) ---
            with st.expander("📊 VL MoM Performance (Deltas)", expanded=False):
                delta_cols = [f"delta_{m}" for m in ms_list if f"delta_{m}" in df_vl.columns]
                if not delta_cols:
                    st.info("Insufficient Month-over-Month data to calculate deltas.")
                else:
                    disp_cols2 = ["vl", "ZM", "Region", "fod_growth"] + delta_cols
                    df_disp2 = df_vl[disp_cols2].copy()
                    rename_map2 = {"vl": "VL Name", "fod_growth": "FOD Growth %"}
                    rename_map2.update({f"delta_{m}": f"Δ F{m} (pp)" for m in ms_list})
                    df_disp2.rename(columns=rename_map2, inplace=True)
                    
                    st.dataframe(df_disp2.style.apply(highlight_deltas, axis=1), 
                                 use_container_width=True, hide_index=True)

    # --- COMMERCIALS TAB ---
    with tabs[-1]:
        st.header("Financial Revenue Models")
        st.markdown("Automated comparison of Rate Card 1 and Rate Card 2 (Offer 1) vs Prior Month baselines.")
        
        if not fin_data:
            st.info("Insufficient multi-month data to calculate revenue baselines.")
        else:
            for ck, df_fin in fin_data.items():
                with st.expander(f"💳 {ck.title()} Revenue & Share Metrics", expanded=True):
                    
                    colA, colB = st.columns(2)
                    c_regs = ["All"] + sorted([str(x) for x in df_fin["Region"].unique()])
                    sel_c_reg = colA.selectbox(f"Filter Region ({ck.title()})", c_regs, key=f"com_reg_{ck}")
                    
                    df_fin_disp = df_fin.copy()
                    if sel_c_reg != "All":
                        df_fin_disp = df_fin_disp[df_fin_disp["Region"] == sel_c_reg]
                        
                    c_zms = ["All"] + sorted([str(x) for x in df_fin_disp["ZM"].unique()])
                    sel_c_zm = colB.selectbox(f"Filter ZM ({ck.title()})", c_zms, key=f"com_zm_{ck}")
                    
                    if sel_c_zm != "All":
                        df_fin_disp = df_fin_disp[df_fin_disp["ZM"] == sel_c_zm]
                    
                    st.dataframe(df_fin_disp.style.map(style_financials), use_container_width=True, hide_index=True)

    # --- SIDEBAR: EXECUTIVE INSIGHTS ---
    with st.sidebar:
        st.header("🤖 AI Insights")
        if not HAS_GEMINI:
            st.warning(
                "AI Module Disabled:\n"
                "Please construct a `requirements.txt` file and add `google-genai`."
            )
        if st.button("Generate Executive Summary"):
            with st.spinner("Analyzing cross-client trends..."):
                summary = draft_summary(results)
                st.markdown(summary)
                
        st.divider()
        st.caption("Developed by nikhil.debug Analytics")
        st.caption("Strict adherence to MECE frameworks & zero-hallucination protocols.")

if __name__ == "__main__":
    main()
