# -*- coding: utf-8 -*-
"""
Autonomous Headless Mailer for TnQ Quality Reports
Executes Redash queries, processes data, generates docs, and routes emails individually.
"""

import os
import pandas as pd
import requests
import smtplib
import mimetypes
from datetime import date, timedelta, datetime, timezone
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
from email.message import EmailMessage

# --- STREAMING_CHUNK:Configuring parameters and constraints ---
REDASH_URL = "https://redash.vahan.link"
QUERY_ID = 17682
REDASH_API_KEY = "4aFm2iOoyx8I91svQccdeZr0jmaiUsMFSRinZcmu"
EMAIL_APP_PASS = os.environ.get("EMAIL_APP_PASS") # Securely loaded from GitHub Secrets

SENDER_EMAIL = "nikhil.r@vahan.co"
ZM_EMAIL_MAP = {
    "Piyush": "piyush.monga@vahan.co",
    "Rohit": "rohit@vahan.co",
    "Vishal": "vishalmittra@vahan.co",
    "Anil Kumar Singh": "anil@vahan.co"
}

ACTIVE_CLIENTS = ["blinkit", "swiggy", "swiggy instamart", "uber"]
CLIENT_FULL = {ck: ck.upper() for ck in ACTIVE_CLIENTS}
CLIENT_ORDER = ACTIVE_CLIENTS

CLIENT_MS = {
    "blinkit": ["20th", "60th", "100th", "120th", "150th", "200th"],
    "swiggy": ["5th", "10th", "20th", "50th", "60th", "80th", "100th", "150th", "200th"],
    "swiggy instamart": ["5th", "10th", "20th", "50th", "60th", "80th", "100th", "150th", "200th"],
    "uber": ["10th", "20th", "30th", "50th", "100th", "150th", "200th"],
}

CLIENT_KEY_MS = {"blinkit": "60th", "swiggy": "20th", "swiggy instamart": "20th", "uber": "20th"}
CLIENT_DECLINE_MS = {"blinkit": ("20th", "60th"), "swiggy": ("20th", "50th"), "swiggy instamart": ("20th", "50th"), "uber": ("10th", "20th")}
TARGET_DIP_MS = ["20th", "50th", "60th", "80th", "100th", "120th", "150th", "200th"]

MIN_VL_FODS = 0
MIN_CURRENT_MTD_FODS = 25
LT_CRITICAL = 5

# --- STREAMING_CHUNK:Defining true MTD date boundaries ---
yesterday = date.today() - timedelta(days=1)
mtd_day = yesterday.day
start_month = yesterday.month - 3
start_year = yesterday.year
if start_month <= 0:
    start_month += 12
    start_year -= 1
START_DATE = str(date(start_year, start_month, 1))
END_DATE = str(yesterday)
IST = timezone(timedelta(hours=5, minutes=30))

# --- STREAMING_CHUNK:Fetching live dataset from Redash ---
def fetch_redash():
    print(f"Fetching data from Redash for period {START_DATE} to {END_DATE}...")
    body_fresh = {"parameters": {"Client": ACTIVE_CLIENTS}, "max_age": 7200}
    r = requests.post(f"{REDASH_URL}/api/queries/{QUERY_ID}/results?api_key={REDASH_API_KEY}", json=body_fresh, timeout=60)
    j = r.json()
    if "query_result" in j:
        return j["query_result"]["data"]["rows"]
    raise Exception(f"Redash API Error or Data missing: {j}")

# --- STREAMING_CHUNK:Processing data and calculating MTD baselines ---
def run_analysis(rows):
    print("Processing Data & calculating MTD baselines...")
    df = pd.DataFrame(rows)
    df["_fod"] = pd.to_datetime(df["first_date_of_work"], format="%Y-%m-%d", errors="coerce")
    valid = df["_fod"].notna() & (df["_fod"].dt.day <= mtd_day) & (df["_fod"] <= pd.Timestamp(END_DATE))
    df = df[valid].copy()
    df["_month"] = df["_fod"].dt.strftime("%b-%Y")
    df = df.drop_duplicates(subset=["phone_number", "_month"])
    df["_vl"] = df["vl_name"].fillna("Unknown")
    
    col_map = {str(c).strip().lower(): c for c in df.columns}
    df["ZM"] = df[col_map["zm"]].fillna("Unknown") if "zm" in col_map else "Unknown"

    for ms in TARGET_DIP_MS:
        col = f"{ms}_order_date"
        if col in df.columns:
            df[col + "_dt"] = pd.to_datetime(df[col], format="%Y-%m-%d", errors="coerce")
            df[f"has_{ms}"] = ((df[col + "_dt"].dt.year == df["_fod"].dt.year) & (df[col + "_dt"].dt.month == df["_fod"].dt.month) & (df[col + "_dt"].dt.day <= mtd_day)).astype(int)

    results = {}
    for client in ACTIVE_CLIENTS:
        sub = df[df["company_name"].str.lower() == client].copy()
        ms_list = CLIENT_MS.get(client, [])
        key_ms = CLIENT_KEY_MS.get(client, ms_list[0])

        for ms in ms_list:
            col = f"{ms}_order_date"
            if col not in sub.columns: sub[col] = None
            sub[col + "_dt"] = pd.to_datetime(sub[col], format="%Y-%m-%d", errors="coerce")
            sub[f"has_{ms}"] = ((sub[col + "_dt"].dt.year == sub["_fod"].dt.year) & (sub[col + "_dt"].dt.month == sub["_fod"].dt.month) & (sub[col + "_dt"].dt.day <= mtd_day)).astype(int)

        all_months = sorted(sub["_month"].unique(), key=lambda x: pd.to_datetime("01 " + x))
        monthly = []
        for m in all_months:
            g = sub[sub["_month"] == m]
            if len(g) == 0: continue
            rec = {"month": m, "fods": len(g)}
            for ms in ms_list: rec[f"pct_{ms}"] = round(g[f"has_{ms}"].mean() * 100, 2)
            monthly.append(rec)

        bm_ms = {ms2: round(sum(m.get(f"pct_{ms2}", 0) for m in monthly) / max(len(monthly), 1), 2) for ms2 in ms_list}

        vl_summary = []
        vl_monthly = {}
        for vl_name, vl_df in sub.groupby("_vl"):
            zm_val = vl_df["ZM"].mode()[0] if not vl_df["ZM"].empty else "Unknown"
            rec = {"vl": vl_name, "ZM": zm_val, "total_fods": len(vl_df), "median_lt": vl_df["candidate_lifetime_orders_trips"].astype(float).median()}
            
            vm = {}
            for m in all_months:
                m_df = vl_df[vl_df["_month"] == m]
                if len(m_df) < 5: 
                    vm[m] = None
                    continue
                m_rec = {"fods": len(m_df)}
                for ms in ms_list: m_rec[f"pct_{ms}"] = round(m_df[f"has_{ms}"].mean() * 100, 2)
                vm[m] = m_rec
            
            vl_monthly[vl_name] = vm
            curr_m = all_months[-1] if all_months else None
            rec["curr_m_fods"] = vm[curr_m]["fods"] if curr_m and vm.get(curr_m) else 0
            vl_summary.append(rec)

        vl_summary = sorted(vl_summary, key=lambda x: x.get("curr_m_fods", 0), reverse=True)

        results[client] = {
            "monthly": monthly,
            "vl_summary": vl_summary,
            "vl_monthly": vl_monthly,
            "bm_ms": bm_ms,
            "milestones": ms_list,
            "key_ms": key_ms,
        }
    return results

# --- STREAMING_CHUNK:Initializing Docx style helpers ---
def set_thick_borders(table):
    tbl = table._tbl
    tblPr = tbl.tblPr if tbl.tblPr is not None else OxmlElement('w:tblPr')
    if tbl.tblPr is None: tbl.insert(0, tblPr)
    tblBorders = tblPr.first_child_found_in("w:tblBorders")
    if tblBorders is None:
        tblBorders = OxmlElement('w:tblBorders')
        tblPr.append(tblBorders)
    else:
        tblBorders.clear()
    for b_name in ['top', 'left', 'bottom', 'right', 'insideH', 'insideV']:
        b = OxmlElement(f'w:{b_name}')
        b.set(qn('w:val'), 'single'); b.set(qn('w:sz'), '12'); b.set(qn('w:space'), '0'); b.set(qn('w:color'), '000000')
        tblBorders.append(b)

def _fmt_pct_word(val):
    return "-" if pd.isna(val) or val is None else f"{val:.1f}%"

# --- STREAMING_CHUNK:Configuring individual email dispatcher ---
def send_email_attachment(zm_name, filepath, cohort_month):
    recipient = ZM_EMAIL_MAP.get(zm_name)
    if not recipient:
        print(f"Skipping email: No mapping found for ZM '{zm_name}'")
        return

    msg = EmailMessage()
    msg['Subject'] = f"TnQ Funnel Quality Report - {cohort_month} MTD ({zm_name})"
    msg['From'] = SENDER_EMAIL
    msg['To'] = recipient
    
    body = (f"Hi {zm_name},\n\n"
            f"Please find attached {cohort_month}'s TnQ quality Report for your cluster at the client level.\n"
            "Please work with the VLs listed to improve quality, and share your action plans and the estimated timeframe for improvement.\n\n"
            "Best regards,\nNikhil")
    msg.set_content(body)
    
    ctype, encoding = mimetypes.guess_type(filepath)
    if ctype is None or encoding is not None:
        ctype = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    maintype, subtype = ctype.split('/', 1)
    
    with open(filepath, 'rb') as f:
        msg.add_attachment(f.read(), maintype=maintype, subtype=subtype, filename=os.path.basename(filepath))
    
    print(f"Sending isolated email to {zm_name} at {recipient}...")
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(SENDER_EMAIL, EMAIL_APP_PASS)
        smtp.send_message(msg)
    print(f"Email successfully delivered to {recipient}.")

# --- STREAMING_CHUNK:Generating specific Word docs and firing emails ---
def generate_and_dispatch(results):
    if not EMAIL_APP_PASS:
        raise ValueError("EMAIL_APP_PASS environment variable is missing. Setup your GitHub Secret.")

    unique_zms = sorted({str(vl["ZM"]).strip() for ck in ACTIVE_CLIENTS if ck in results for vl in results[ck]["vl_summary"] if vl.get("ZM") and vl["ZM"] != "Unknown"})
    cohort_month = pd.to_datetime(END_DATE).strftime('%B')

    for zm_name in unique_zms:
        if zm_name not in ZM_EMAIL_MAP:
            continue # Do not generate docs for unmapped ZMs
            
        doc = Document()
        for section in doc.sections:
            section.top_margin = Pt(36); section.bottom_margin = Pt(36); section.left_margin = Pt(36); section.right_margin = Pt(36)
            
        doc.add_paragraph().add_run(f"Hi {zm_name},").bold = True
        doc.add_paragraph(f"Please find {cohort_month}'s TnQ quality Report for your cluster at the client level below. Please work with the VLs listed below to improve quality, and share your action plans and the estimated timeframe for improvement.")
        
        has_content = False

        for ck in CLIENT_ORDER:
            if ck not in results: continue
            data = results[ck]
            
            mon = data["monthly"]
            if len(mon) < 2: continue
            curr_m, prev_m = mon[-1]["month"], mon[-2]["month"]
            ms1, ms2 = CLIENT_DECLINE_MS.get(ck, (data["milestones"][0], data["key_ms"]))

            t1_rows = []
            for vl in data["vl_summary"]:
                if vl.get("ZM") != zm_name: continue
                vm = data["vl_monthly"].get(vl["vl"], {})
                curr_d, prev_d = vm.get(curr_m) or {}, vm.get(prev_m) or {}
                d_f1 = round(curr_d.get(f"pct_{ms1}", 0) - prev_d.get(f"pct_{ms1}", 0), 1) if curr_d.get(f"pct_{ms1}") is not None and prev_d.get(f"pct_{ms1}") is not None else None
                d_f2 = round(curr_d.get(f"pct_{ms2}", 0) - prev_d.get(f"pct_{ms2}", 0), 1) if curr_d.get(f"pct_{ms2}") is not None and prev_d.get(f"pct_{ms2}") is not None else None

                if (d_f1 is not None and d_f1 < 0) or (d_f2 is not None and d_f2 < 0):
                    t1_rows.append([str(vl["vl"]), str(zm_name), f"{curr_d.get('fods', 0):,}", f"{prev_d.get('fods', 0):,}", _fmt_pct_word(curr_d.get(f"pct_{ms1}")), _fmt_pct_word(prev_d.get(f"pct_{ms1}")), _fmt_pct_word(curr_d.get(f"pct_{ms2}")), _fmt_pct_word(prev_d.get(f"pct_{ms2}")), f"{d_f1:+.1f}%" if d_f1 is not None else "-", f"{d_f2:+.1f}%" if d_f2 is not None else "-", vl.get("curr_m_fods", 0)])

            # Enforcing current MTD sort
            t1_rows = sorted(t1_rows, key=lambda x: x[-1], reverse=True)
            t1_rows = [r[:-1] for r in t1_rows]

            t2_ms_list = ["20th", "60th", "100th", "200th"]
            t2_rows = []
            
            for vl_rec in data["vl_summary"]:
                if vl_rec.get("ZM") != zm_name: continue
                total_fods = vl_rec.get("curr_m_fods", 0)
                if total_fods <= MIN_CURRENT_MTD_FODS: continue
                
                is_critical = False
                red_flags = []
                if vl_rec.get("median_lt", 999) < LT_CRITICAL:
                    red_flags.append(f"Median LT = {vl_rec.get('median_lt'):.1f} — ghost risk")
                    is_critical = True
                
                for m2 in t2_ms_list:
                    if m2 in data["milestones"]:
                        vl_pct = vl_rec.get(f"pct_{m2}", 0)
                        bv = data["bm_ms"].get(m2, 0)
                        if bv > 0:
                            drop_pct = (bv - vl_pct) / bv
                            if drop_pct >= 0.50:
                                red_flags.insert(0, f"Critical Base Drop F{m2}={vl_pct:.1f}% (≥50% drop)")
                                is_critical = True
                            elif drop_pct >= 0.15:
                                red_flags.append(f"Base Drop F{m2}={vl_pct:.1f}% (>{15}% drop)")
                                
                if is_critical:
                    row_data = [str(vl_rec['vl']), str(zm_name), "❌ CRITICAL", f"{total_fods:,}", str(round(vl_rec.get("median_lt", 0), 1))]
                    for m2 in t2_ms_list:
                        if m2 in data["milestones"]:
                            row_data.extend([_fmt_pct_word(vl_rec.get(f"pct_{m2}", 0)), _fmt_pct_word(data["bm_ms"].get(m2, 0))])
                        else:
                            row_data.extend(["-", "-"])
                    row_data.append(" | ".join(red_flags))
                    row_data.append(total_fods)
                    t2_rows.append(row_data)

            # Enforcing current MTD sort
            t2_rows = sorted(t2_rows, key=lambda x: x[-1], reverse=True)
            t2_rows = [r[:-1] for r in t2_rows]

            if not t1_rows and not t2_rows: continue
            has_content = True

            doc.add_heading(CLIENT_FULL.get(ck, ck.upper()), level=2).runs[0].font.color.rgb = RGBColor(197, 90, 0)

            if t1_rows:
                doc.add_heading("MTD VS LMD report", level=3)
                t1_headers = ["VL Name", "ZM Name", f"{curr_m[:3]} MTD FOD", "LMTD FOD", f"{curr_m[:3]} MTD F{ms1}%", f"LMTD F{ms1}%", f"{curr_m[:3]} F{ms2}%", f"LMTD F{ms2}%", f"Delta F{ms1}", f"Delta F{ms2}"]
                table = doc.add_table(rows=1, cols=len(t1_headers))
                set_thick_borders(table)
                for i, h in enumerate(t1_headers): 
                    table.rows[0].cells[i].text = h
                    table.rows[0].cells[i].paragraphs[0].runs[0].font.bold = True
                for row_data in t1_rows:
                    row_cells = table.add_row().cells
                    for i, val in enumerate(row_data): 
                        row_cells[i].text = str(val)
                        if i >= 2: row_cells[i].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
                doc.add_paragraph()

            if t2_rows:
                doc.add_heading("Platform Avg(Baseline) vs VL Performance report (MTD)", level=3)
                t2_note = doc.add_paragraph("Note: This table shows the list of VLs whose milestones achieved are critically below the platform average.")
                t2_note.runs[0].italic = True
                
                t2_headers = ["VL Name", "ZM", "Severity", "MTD FODs", "Median LT", "F20th%\n(MTD)", "F20th%\n(Base)", "F60th%\n(MTD)", "F60th%\n(Base)", "F100th%\n(MTD)", "F100th%\n(Base)", "F200th%\n(MTD)", "F200th%\n(Base)", "Red Flags"]
                table = doc.add_table(rows=1, cols=len(t2_headers))
                set_thick_borders(table)
                
                for cell in table.columns[-1].cells:
                    cell.width = Inches(2.5)
                    
                for i, h in enumerate(t2_headers): 
                    table.rows[0].cells[i].text = h
                    table.rows[0].cells[i].paragraphs[0].runs[0].font.bold = True
                for row_data in t2_rows:
                    row_cells = table.add_row().cells
                    for i, val in enumerate(row_data): 
                        row_cells[i].text = str(val)
                        if 3 <= i <= 12: row_cells[i].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
                doc.add_paragraph()

        if not has_content:
            doc.add_paragraph("No critical flags or negative quality decline metrics for your cluster this month.")

        filepath = f"Draft_{zm_name.replace(' ', '_')}.docx"
        doc.save(filepath)
        
        # Fire strictly isolated email
        send_email_attachment(zm_name, filepath, cohort_month)
        
        # Cleanup file after sending
        if os.path.exists(filepath):
            os.remove(filepath)

if __name__ == "__main__":
    print(f"--- Starting Autonomous Email Sequence at {datetime.now(IST)} IST ---")
    raw_data = fetch_redash()
    analysis_results = run_analysis(raw_data)
    generate_and_dispatch(analysis_results)
    print("--- Sequence Complete ---")
