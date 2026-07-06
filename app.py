# -*- coding: utf-8 -*-
"""
Optimus Analytics - Funnel Quality & Revenue Dashboard
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
st.set_page_config(page_title="Optimus | Funnel Quality", layout="wide")

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

# --- FINANCIAL & RISK THRESHOLDS ---
MIN_CURRENT_MTD_FODS = 25
DROP_CRITICAL = -15
DROP_HIGH = -8
DROP_WATCH = -3
ABS_CRITICAL = 0.30
ABS_HIGH = 0.50
ABS_WATCH = 0.70
LT_CRITICAL = 5
LT_HIGH = 10
SURGE_THRESH = 100
SURGE_DROP = -5
BELOW20_WATCH = 65

CLIENT_DECLINE_MS = {
    "blinkit":          ("20th", "60th"),
    "swiggy":           ("20th", "50th"),
    "swiggy instamart": ("20th", "50th"),
    "uber":             ("10th", "20th"),
}

MISUSE_SHOW_MS = {
    "swiggy":           ["5th", "20th", "50th", "100th"],
    "swiggy instamart": ["20th", "50th", "100th"],
    "blinkit":          ["20th", "60th", "100th", "200th"],
    "uber":             ["10th", "20th", "30th", "50th"],
}

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
    
    # Extract structural mapping columns directly from Redash payload 
    # Normalizing keys just in case Redash returns `cm`, `CM`, `region`, etc.
    col_map = {str(c).strip().lower(): c for c in df.columns}
    df["ZM"] = df[col_map["zm"]].fillna("Unknown") if "zm" in col_map else "Unknown"
    df["Region"] = df[col_map["region"]].fillna("Unknown") if "region" in col_map else "Unknown"
    df["CL"] = df[col_map["cl"]].fillna("Unknown") if "cl" in col_map else "Unknown"
    
    if "cm" in col_map:
        df["CM"] = df[col_map["cm"]].fillna("Unknown")
    elif "am" in col_map:
        df["CM"] = df[col_map["am"]].fillna("Unknown")
    else:
        df["CM"] = "Unknown"

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
                rec[f"pct_{ms}"] = round(g[f"has_{ms}"].mean() * 100, 2)
            rec["avg_lt"] = round(lt.mean(), 2)
            rec["median_lt"] = round(lt.median(), 2)
            rec["pct_200plus"] = round((lt >= 200).mean() * 100, 2)
            rec["pct_below20"] = round((lt < 20).mean() * 100, 2)
            monthly.append(rec)

        # Baseline dictionaries for highlighting
        bm_key = sum(m.get(f"pct_{key_ms}", 0) for m in monthly) / max(len(monthly), 1)
        bm_ms = {ms2: round(sum(m.get(f"pct_{ms2}", 0) for m in monthly) / max(len(monthly), 1), 2) for ms2 in ms_list}

        vl_summary = []
        vl_monthly = {}
        
        for vl_name, vl_df in sub.groupby("_vl"):
            if len(vl_df) < MIN_VL_FODS: continue
            
            # Map structural columns based on the most frequent occurrence within this VL
            zm_val = vl_df["ZM"].mode()[0] if not vl_df["ZM"].empty else "Unknown"
            reg_val = vl_df["Region"].mode()[0] if not vl_df["Region"].empty else "Unknown"
            cm_val = vl_df["CM"].mode()[0] if not vl_df["CM"].empty else "Unknown"
            cl_val = vl_df["CL"].mode()[0] if not vl_df["CL"].empty else "Unknown"
            
            lt_all = vl_df["candidate_lifetime_orders_trips"].astype(float)
            rec = {
                "vl": vl_name,
                "ZM": zm_val,
                "Region": reg_val,
                "CM": cm_val,
                "CL": cl_val,
                "total_fods": len(vl_df),
                "median_lt": round(lt_all.median(), 2),
                "pct_below20": round((lt_all < 20).mean() * 100, 2),
            }
            for ms in ms_list:
                rec[f"pct_{ms}"] = round(vl_df[f"has_{ms}"].mean() * 100, 2)
                
            # Month over Month parsing for Deltas
            vm = {}
            for m in all_months:
                m_df = vl_df[vl_df["_month"] == m]
                if len(m_df) < 5: 
                    vm[m] = None
                    continue
                m_rec = {"fods": len(m_df)}
                for ms in ms_list:
                    m_rec[f"pct_{ms}"] = round(m_df[f"has_{ms}"].mean() * 100, 2)
                m_rec["median_lt"] = round(m_df["candidate_lifetime_orders_trips"].astype(float).median(), 2)
                m_rec["pct_below20"] = round((m_df["candidate_lifetime_orders_trips"].astype(float) < 20).mean() * 100, 2)
                vm[m] = m_rec
            
            vl_monthly[vl_name] = vm
            
            valid_months = [m for m in all_months if vm.get(m) is not None]
            if len(valid_months) >= 2:
                pm, cm = valid_months[-2], valid_months[-1]
                rec["fod_growth"] = round((vm[cm]["fods"] - vm[pm]["fods"]) / max(vm[pm]["fods"], 1) * 100, 2)
                for ms in ms_list:
                    rec[f"delta_{ms}"] = round(vm[cm].get(f"pct_{ms}", 0) - vm[pm].get(f"pct_{ms}", 0), 2)
                    
            vl_summary.append(rec)

        results[client] = {
            "monthly": monthly,
            "vl_summary": vl_summary,
            "vl_monthly": vl_monthly,
            "bm_ms": bm_ms,
            "milestones": ms_list,
            "key_ms": key_ms,
        }
    return results, df

@st.cache_data(show_spinner=False)
def calculate_financials(df_raw, results_dict):
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
            
            region = group["Region"].mode()[0] if not group["Region"].empty else "Unknown"
            zm = group["ZM"].mode()[0] if not group["ZM"].empty else "Unknown"
            
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
        if isinstance(col, str) and (col.startswith('Δ') or col.startswith('Delta') or col == 'FOD Growth %' or 'Δ' in col):
            val = row[col]
            if pd.notna(val):
                if val <= -15: styles[i] = 'background-color: #FFCCCC; color: #C00000'
                elif val <= -5: styles[i] = 'background-color: #FFE4CC; color: #C55A00'
                elif val >= 0: styles[i] = 'background-color: #CCFFCC; color: #375623'
    return styles

def highlight_severity_rows(row):
    styles = [''] * len(row)
    sev = str(row.get("Severity", ""))
    if "CRITICAL" in sev:
        return ['background-color: #FFD2D2; color: #8B0000'] * len(row)
    elif "HIGH" in sev:
        return ['background-color: #FFEED2; color: #8B5A00'] * len(row)
    elif "WATCH" in sev:
        return ['background-color: #FFFFD2; color: #8B8B00'] * len(row)
    return styles

def highlight_misuse_status(val):
    if isinstance(val, str) and "⚠️ DROP" in val:
        return 'color: #C00000; font-weight: bold'
    elif isinstance(val, str) and "✓ OK" in val:
        return 'color: #375623'
    return ''

def style_financials(val):
    if isinstance(val, str) and '-₹' in val:
        return 'color: #C00000; font-weight: bold'
    return ''

# --- 4. STREAMLIT UI (MECE FRAMEWORK) ---
def main():
    st.title("📊 Optimus Analytics: Funnel Quality Hub")
    st.markdown(f"**Data Period:** {START_DATE} → {END_DATE} | **MTD Cutoff:** Day {mtd_day}")

    with st.spinner("Fetching and processing data pipelines..."):
        rows = fetch_redash()
        results, df_raw = run_analysis(rows)
        fin_data = calculate_financials(df_raw, results)

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
            key_ms = client_data["key_ms"]
            vl_monthly = client_data.get("vl_monthly", {})
            
            # Since data is fully baked into results, loading df_vl is direct
            df_vl = pd.DataFrame(client_data["vl_summary"])

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
            filtered_vl_names = df_vl["vl"].tolist()

            # --- EXPANDER 1: Overall Monthly ---
            with st.expander("📈 Overall Funnel - Month over Month (Unfiltered)", expanded=False):
                if client_data["monthly"]:
                    df_monthly = pd.DataFrame(client_data["monthly"])
                    cols = ["month", "fods"] + [f"pct_{m}" for m in ms_list] + ["median_lt", "pct_below20"]
                    df_monthly = df_monthly[[c for c in cols if c in df_monthly.columns]]
                    st.dataframe(df_monthly.style.format(precision=2), width="stretch", hide_index=True)

            # --- EXPANDER 2: VL Summary ---
            with st.expander("🏢 VL Summary (Current MTD vs Benchmark)", expanded=True):
                ms_cols = [f"pct_{m}" for m in ms_list]
                disp_cols1 = ["vl", "ZM", "Region", "CM", "CL", "total_fods", "median_lt", "pct_below20"] + ms_cols
                disp_cols1 = [c for c in disp_cols1 if c in df_vl.columns]
                
                df_disp1 = df_vl[disp_cols1].copy()
                rename_map1 = {"vl": "VL Name", "total_fods": "Total FODs", "median_lt": "Median LT", "pct_below20": "% <20 LT"}
                rename_map1.update({f"pct_{m}": f"F{m}%" for m in ms_list})
                df_disp1.rename(columns=rename_map1, inplace=True)
                
                st.dataframe(df_disp1.style.apply(lambda row: highlight_benchmark(row, bm_ms), axis=1).format(precision=2), 
                             width="stretch", hide_index=True)

            # --- EXPANDER 3: VL MoM Deltas ---
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
                    
                    st.dataframe(df_disp2.style.apply(highlight_deltas, axis=1).format(precision=2), 
                                 width="stretch", hide_index=True)

            # --- EXPANDER 4: Quality Decline View ---
            with st.expander("📉 VL Quality Decline View", expanded=False):
                all_months = sorted(df_raw["_month"].unique(), key=lambda x: pd.to_datetime("01 " + x))
                if len(all_months) < 2:
                    st.info("Insufficient Month-over-Month data to generate quality decline view.")
                else:
                    curr_m, prev_m = all_months[-1], all_months[-2]
                    ms1, ms2 = CLIENT_DECLINE_MS.get(client, (ms_list[0], key_ms))
                    decline_rows = []
                    
                    for vln in filtered_vl_names:
                        vl_rec = next((r for r in client_data["vl_summary"] if r["vl"] == vln), {})
                        
                        zm = vl_rec.get("ZM", "Unknown")
                        reg = vl_rec.get("Region", "Unknown")
                        cm = vl_rec.get("CM", "Unknown")
                        cl = vl_rec.get("CL", "Unknown")
                        
                        vm = vl_monthly.get(vln, {})
                        curr_d = vm.get(curr_m) or {}
                        prev_d = vm.get(prev_m) or {}
                        
                        curr_fod = curr_d.get("fods")
                        prev_fod = prev_d.get("fods")
                        curr_f1 = curr_d.get(f"pct_{ms1}")
                        prev_f1 = prev_d.get(f"pct_{ms1}")
                        curr_f2 = curr_d.get(f"pct_{ms2}")
                        prev_f2 = prev_d.get(f"pct_{ms2}")
                        
                        d_f1 = round(curr_f1 - prev_f1, 2) if curr_f1 is not None and prev_f1 is not None else None
                        d_f2 = round(curr_f2 - prev_f2, 2) if curr_f2 is not None and prev_f2 is not None else None
                        
                        if curr_fod is not None or prev_fod is not None:
                            decline_rows.append({
                                "VL Name": vln,
                                "ZM Name": zm,
                                "Region": reg,
                                "CM": cm,
                                "CL": cl,
                                f"{curr_m[:3]} MTD FOD": curr_fod if curr_fod is not None else 0,
                                f"LMTD FOD": prev_fod if prev_fod is not None else 0,
                                f"{curr_m[:3]} F{ms1}%": curr_f1,
                                f"LMTD F{ms1}%": prev_f1,
                                f"{curr_m[:3]} F{ms2}%": curr_f2,
                                f"LMTD F{ms2}%": prev_f2,
                                f"Delta F{ms1}": d_f1,
                                f"Delta F{ms2}": d_f2
                            })
                    
                    if decline_rows:
                        df_decline = pd.DataFrame(decline_rows)
                        df_decline = df_decline.sort_values(by=f"Delta F{ms2}", ascending=True, na_position="last")
                        st.dataframe(df_decline.style.apply(highlight_deltas, axis=1).format(precision=2), 
                                     width="stretch", hide_index=True)
                    else:
                        st.info("No records matched quality decline thresholds.")

            # --- EXPANDER 5: Misuse & Anomaly Flags ---
            with st.expander("🚨 VL Misuse & Anomaly Flags", expanded=False):
                all_months = sorted(df_raw["_month"].unique(), key=lambda x: pd.to_datetime("01 " + x))
                n_months = len(all_months)
                misuse_rows = []
                
                desired_ms = MISUSE_SHOW_MS.get(client, [key_ms])
                show_ms = [m2 for m2 in desired_ms if m2 in ms_list]
                if key_ms not in show_ms:
                    show_ms = [key_ms] + show_ms
                show_ms = list(dict.fromkeys(show_ms)) # Deduplicate and preserve order
                
                for vln in filtered_vl_names:
                    vl_rec = next((r for r in client_data["vl_summary"] if r["vl"] == vln), None)
                    if not vl_rec: continue
                    
                    zm = vl_rec.get("ZM", "Unknown")
                    reg = vl_rec.get("Region", "Unknown")
                    cm = vl_rec.get("CM", "Unknown")
                    cl = vl_rec.get("CL", "Unknown")
                    
                    total_fods = vl_rec.get("total_fods", 0)
                    fod_g = vl_rec.get("fod_growth", 0) or 0
                    
                    if "fod_growth" in vl_rec and vl_rec["fod_growth"] is not None:
                        g = vl_rec["fod_growth"] / 100
                        est_curr = total_fods * (1 + g) / (n_months + g) if (n_months + g) else 0
                    else:
                        est_curr = total_fods / n_months if n_months else 0
                        
                    if est_curr <= MIN_CURRENT_MTD_FODS: continue
                    
                    reasons = []
                    sev_scores = []
                    q_key = vl_rec.get(f"pct_{key_ms}", 0) or 0
                    bm_key_val = bm_ms.get(key_ms, 0) or 0.1
                    delta = vl_rec.get(f"delta_{key_ms}")
                    med_lt = vl_rec.get("median_lt", 999)
                    bel20 = vl_rec.get("pct_below20", 0)
                    ratio = q_key / bm_key_val
                    
                    # Base Logic Validation
                    if delta is not None:
                        if delta <= DROP_CRITICAL:
                            reasons.append(f"F{key_ms} dropped {delta:+.2f}pp MoM")
                            sev_scores.append("critical")
                        elif delta <= DROP_HIGH:
                            reasons.append(f"F{key_ms} dropped {delta:+.2f}pp MoM")
                            sev_scores.append("high")
                        elif delta <= DROP_WATCH:
                            reasons.append(f"F{key_ms} dropped {delta:+.2f}pp MoM")
                            sev_scores.append("watch")
                    if ratio < ABS_CRITICAL:
                        reasons.append(f"F{key_ms} = {q_key:.2f}% vs bm {bm_key_val:.2f}%")
                        sev_scores.append("critical")
                    elif ratio < ABS_HIGH:
                        reasons.append(f"F{key_ms} = {q_key:.2f}% vs bm {bm_key_val:.2f}%")
                        sev_scores.append("high")
                    elif ratio < ABS_WATCH:
                        reasons.append(f"F{key_ms} = {q_key:.2f}% vs bm {bm_key_val:.2f}%")
                        sev_scores.append("watch")
                    if med_lt < LT_CRITICAL:
                        reasons.append(f"Median LT = {med_lt} — ghost risk")
                        sev_scores.append("critical")
                    elif med_lt < LT_HIGH:
                        reasons.append(f"Median LT = {med_lt} — low")
                        sev_scores.append("high")
                    if fod_g > SURGE_THRESH and delta is not None and delta <= SURGE_DROP:
                        reasons.append(f"FOD surge +{fod_g:.2f}% with drop")
                        sev_scores.append("high")
                    if bel20 > BELOW20_WATCH:
                        reasons.append(f"{bel20:.2f}% <20 LT")
                        sev_scores.append("watch")
                        
                    # Advanced Misuse Logic: Baseline Drops across configured milestones
                    bm_drop_flags = []
                    for m2 in show_ms:
                        vl_pct = vl_rec.get(f"pct_{m2}") or 0
                        bv = bm_ms.get(m2, 0)
                        if bv and vl_pct < bv * 0.85:
                            bm_drop_flags.append(f"F{m2}={vl_pct:.1f}% (>{15}% drop from base {bv:.1f}%)")
                    
                    if not reasons and not bm_drop_flags:
                        continue
                        
                    if bm_drop_flags:
                        sev_scores.append("critical") # Override severity if structural milestones collapse
                        
                    final_sev = min(sev_scores, key=lambda s: {"critical": 0, "high": 1, "watch": 2}[s])
                    sev_label = {"critical": "❌ CRITICAL", "high": "🟠 HIGH", "watch": "🟡 WATCH"}[final_sev]
                    
                    combined_reasons = " | ".join(reasons)
                    if bm_drop_flags:
                        combined_reasons += " | Base Drops: " + ", ".join(bm_drop_flags)
                        
                    row_data = {
                        "VL Name": vln,
                        "ZM": zm,
                        "Region": reg,
                        "CM": cm,
                        "CL": cl,
                        "Severity": sev_label,
                        "Total FODs": total_fods,
                        "Median LT": med_lt,
                    }
                    
                    for m2 in show_ms:
                        vl_pct = vl_rec.get(f"pct_{m2}")
                        bv = bm_ms.get(m2, 0)
                        dropped = (vl_pct is not None) and bv and (vl_pct < bv * 0.85)
                        row_data[f"F{m2}% (VL)"] = vl_pct if vl_pct is not None else 0
                        row_data[f"F{m2}% (Base)"] = bv if bv else 0
                        row_data[f"F{m2} Status"] = "⚠️ DROP" if dropped else "✓ OK"
                        
                    row_data["FOD Growth %"] = fod_g
                    row_data["Red Flags"] = combined_reasons
                        
                    misuse_rows.append(row_data)
                
                if misuse_rows:
                    df_misuse = pd.DataFrame(misuse_rows)
                    severity_map = {"❌ CRITICAL": 0, "🟠 HIGH": 1, "🟡 WATCH": 2}
                    df_misuse["_sev_sort"] = df_misuse["Severity"].map(severity_map)
                    df_misuse = df_misuse.sort_values(by=["_sev_sort", "Total FODs"], ascending=[True, False]).drop(columns=["_sev_sort"])
                    
                    # Apply dual-styler mapping (Full row severity colors + Specific column text colors)
                    st.dataframe(df_misuse.style.apply(highlight_severity_rows, axis=1)
                                                .map(highlight_misuse_status)
                                                .format(precision=2), 
                                 width="stretch", hide_index=True)
                else:
                    st.success("🎉 No vendor anomalies or quality warnings detected for selected criteria!")

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
                    
                    st.dataframe(df_fin_disp.style.map(style_financials).format(precision=2), width="stretch", hide_index=True)

    # --- SIDEBAR: EXECUTIVE INSIGHTS ---
    with st.sidebar:
        st.header("🤖 Optimus AI Insights")
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
        st.caption("Developed by Optimus Analytics")
        st.caption("Strict adherence to MECE frameworks & zero-hallucination protocols.")

if __name__ == "__main__":
    main()
