import os
import smtplib
import time
import requests
import pandas as pd
from datetime import date, timedelta, datetime, timezone
from email.message import EmailMessage

# ==========================================
# 1. CONFIGURATION & TEST MODE
# ==========================================
SENDER_EMAIL = "nikhil.r@vahan.co"
EMAIL_PASSWORD = os.environ.get("EMAIL_APP_PASS")

# TOGGLE THIS: Set to True to route all emails to yourself. Set to False for production.
TEST_MODE = True
TEST_EMAIL = "nikhil.r@vahan.co"

# The CC list that will be used when TEST_MODE = False
CC_EMAILS = "sajal@vahan.co, saurabh.dubey@vahan.co"

ZM_EMAILS = {
    "Piyush": "piyush.monga@vahan.co",
    "Rohit": "rohit@vahan.co",
    "Vishal": "vishalmittra@vahan.co",
    "Anil Kumar Singh": "anil@vahan.co"
}

# --- REDASH & DATA CONSTANTS ---
REDASH_URL = "https://redash.vahan.link"
QUERY_ID = 17682
REDASH_API_KEY = "4aFm2iOoyx8I91svQccdeZr0jmaiUsMFSRinZcmu"
ACTIVE_CLIENTS = ["blinkit", "swiggy", "swiggy instamart", "uber"]
CLIENT_FULL = {ck: ck.upper() for ck in ACTIVE_CLIENTS}

CLIENT_MS = {
    "blinkit": ["20th", "60th", "100th", "120th", "150th", "200th"],
    "swiggy": ["5th", "10th", "20th", "50th", "60th", "80th", "100th", "150th", "200th"],
    "swiggy instamart": ["5th", "10th", "20th", "50th", "60th", "80th", "100th", "150th", "200th"],
    "uber": ["10th", "20th", "30th", "50th", "100th", "150th", "200th"],
}

CLIENT_KEY_MS = {
    "blinkit": "60th", "swiggy": "20th", "swiggy instamart": "20th", "uber": "20th",
}

CLIENT_DECLINE_MS = {
    "blinkit":          ("20th", "60th"),
    "swiggy":           ("20th", "50th"),
    "swiggy instamart": ("20th", "50th"),
    "uber":             ("10th", "20th"),
}

MIN_VL_FODS = 0
MIN_CURRENT_MTD_FODS = 25
LT_CRITICAL = 5

# Date Calculations
yesterday = date.today() - timedelta(days=1)
mtd_day = yesterday.day
END_DATE = str(yesterday)
IST = timezone(timedelta(hours=5, minutes=30))

# ==========================================
# 2. EMAIL SENDER LOGIC
# ==========================================
def send_email(zm_name, html_body):
    month_name = yesterday.strftime('%B')
    end_day_str = yesterday.strftime('%d')
    subject = f"Quality Report | {month_name} MTD 01-{end_day_str} | {zm_name}"

    msg = EmailMessage()
    msg['From'] = SENDER_EMAIL
    
    if TEST_MODE:
        msg['To'] = TEST_EMAIL
        msg['Subject'] = f"[TEST] {subject}"
        print(f"TEST MODE ACTIVE: Diverting {zm_name}'s email to {TEST_EMAIL} (CC omitted)")
    else:
        recipient = ZM_EMAILS.get(zm_name)
        if not recipient: return
        msg['To'] = recipient
        msg['Cc'] = CC_EMAILS
        msg['Subject'] = subject

    msg.set_content(html_body, subtype='html')

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(SENDER_EMAIL, EMAIL_PASSWORD)
            smtp.send_message(msg)
        print(f"Success: Email sent for ZM {zm_name}")
    except Exception as e:
        print(f"Critical Error sending email for {zm_name}: {e}")

# ==========================================
# 3. DATA FETCHING & PROCESSING 
# ==========================================
def get_daily_refresh_key():
    now = datetime.now(IST)
    if now.hour < 13 or (now.hour == 13 and now.minute < 30):
        return str(now.date() - timedelta(days=1))
    return str(now.date())

def fetch_redash(refresh_key):
    body_fresh = {"parameters": {"Client": ACTIVE_CLIENTS}, "max_age": 7200}
    r = requests.post(f"{REDASH_URL}/api/queries/{QUERY_ID}/results?api_key={REDASH_API_KEY}", json=body_fresh, timeout=30)
    j = r.json()
    if "query_result" in j: return j["query_result"]["data"]["rows"]
    
    body_cached = {**body_fresh, "max_age": 7200}
    for _ in range(40):
        time.sleep(15)
        r2 = requests.post(f"{REDASH_URL}/api/queries/{QUERY_ID}/results?api_key={REDASH_API_KEY}", json=body_cached, timeout=30)
        j2 = r2.json()
        if "query_result" in j2: return j2["query_result"]["data"]["rows"]
    return []

def run_analysis(rows):
    if not rows: return {}
    df = pd.DataFrame(rows)
    df["_fod"] = pd.to_datetime(df["first_date_of_work"], format="%Y-%m-%d", errors="coerce")
    valid = df["_fod"].notna() & (df["_fod"].dt.day <= mtd_day) & (df["_fod"] <= pd.Timestamp(END_DATE))
    df = df[valid].copy()
    df["_month"] = df["_fod"].dt.strftime("%b-%Y")
    df = df.drop_duplicates(subset=["phone_number", "_month"])
    df["_vl"] = df["vl_name"].fillna("Unknown")
    col_map = {str(c).strip().lower(): c for c in df.columns}
    df["ZM"] = df[col_map["zm"]].fillna("Unknown") if "zm" in col_map else "Unknown"

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

        vl_summary = []; vl_monthly = {}
        for vl_name, vl_df in sub.groupby("_vl"):
            if len(vl_df) < MIN_VL_FODS: continue
            lt_all = vl_df["candidate_lifetime_orders_trips"].astype(float)
            rec = {"vl": vl_name, "ZM": vl_df["ZM"].mode()[0] if not vl_df["ZM"].empty else "Unknown", "total_fods": len(vl_df), "median_lt": round(lt_all.median(), 2)}
            for ms in ms_list: rec[f"pct_{ms}"] = round(vl_df[f"has_{ms}"].mean() * 100, 2)
            vm = {}
            for m in all_months:
                m_df = vl_df[vl_df["_month"] == m]
                if len(m_df) < 5: continue
                m_rec = {"fods": len(m_df)}
                for ms in ms_list: m_rec[f"pct_{ms}"] = round(m_df[f"has_{ms}"].mean() * 100, 2)
                vm[m] = m_rec
            vl_monthly[vl_name] = vm
            curr_m = all_months[-1] if all_months else None
            rec["curr_m_fods"] = vm[curr_m]["fods"] if curr_m and vm.get(curr_m) else 0
            vl_summary.append(rec)

        vl_summary = sorted(vl_summary, key=lambda x: x.get("curr_m_fods", 0), reverse=True)
        results[client] = {"monthly": monthly, "vl_summary": vl_summary, "vl_monthly": vl_monthly, "bm_ms": bm_ms, "milestones": ms_list, "key_ms": key_ms}
    return results

# ==========================================
# 4. HTML GENERATION ENGINE
# ==========================================
def _fmt_pct_word(val): return "-" if pd.isna(val) or val is None else f"{val:.1f}%"

def generate_html_payloads(results):
    html_payloads = {}
    
    unique_zms = set()
    for ck in ACTIVE_CLIENTS:
        if ck in results:
            for vl in results[ck]["vl_summary"]:
                if vl.get("ZM") and vl["ZM"] != "Unknown" and vl["ZM"] in ZM_EMAILS.keys():
                    unique_zms.add(str(vl["ZM"]).strip())
    
    cohort_month = yesterday.strftime('%B')
    
    for zm_name in unique_zms:
        html_body = f"""
        <html>
        <head>
        <style>
            body {{ font-family: Arial, sans-serif; font-size: 14px; color: #333; }}
            table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; font-size: 12px; }}
            th, td {{ border: 1px solid #000; padding: 6px 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; font-weight: bold; }}
            .right-align {{ text-align: right; }}
            h2 {{ color: #C55A00; margin-top: 20px; margin-bottom: 10px; font-size: 18px; }}
            h3 {{ color: #333; margin-top: 15px; margin-bottom: 5px; font-size: 14px; text-decoration: underline; }}
        </style>
        </head>
        <body>
            <p><strong>Hi {zm_name},</strong></p>
            <p>Please find {cohort_month}'s TnQ quality Report for your cluster at the client level below. Please work with the VLs listed below to improve quality, and share your action plans and the estimated timeframe for improvement.</p>
        """
        
        has_content = False

        for ck in ACTIVE_CLIENTS:
            if ck not in results: continue
            data = results[ck]
            client_label = CLIENT_FULL.get(ck, ck.upper())
            mon = data["monthly"]
            if len(mon) < 2: continue
            curr_m, prev_m = mon[-1]["month"], mon[-2]["month"]
            ms1, ms2 = CLIENT_DECLINE_MS.get(ck, (data["milestones"][0], data["key_ms"]))

            t1_rows = []
            for vl in data["vl_summary"]:
                if vl.get("ZM") != zm_name: continue
                vln = vl["vl"]
                vm = data["vl_monthly"].get(vln, {})
                curr_d, prev_d = vm.get(curr_m) or {}, vm.get(prev_m) or {}
                curr_f1, prev_f1 = curr_d.get(f"pct_{ms1}"), prev_d.get(f"pct_{ms1}")
                curr_f2, prev_f2 = curr_d.get(f"pct_{ms2}"), prev_d.get(f"pct_{ms2}")
                d_f1 = round(curr_f1 - prev_f1, 1) if curr_f1 is not None and prev_f1 is not None else None
                d_f2 = round(curr_f2 - prev_f2, 1) if curr_f2 is not None and prev_f2 is not None else None

                # Keep row generation metrics matching original baseline rules
                if (d_f1 is not None and d_f1 < 0) or (d_f2 is not None and d_f2 < 0):
                    t1_rows.append([str(vln), str(zm_name), f"{curr_d.get('fods', 0):,}", f"{prev_d.get('fods', 0):,}", _fmt_pct_word(curr_f1), _fmt_pct_word(prev_f1), _fmt_pct_word(curr_f2), _fmt_pct_word(prev_f2), f"{d_f1:+.1f}%" if d_f1 is not None else "-", f"{d_f2:+.1f}%" if d_f2 is not None else "-", d_f1, d_f2])

            t2_ms_list = ["20th", "60th", "100th", "200th"]
            t2_rows = []
            for vl_rec in data["vl_summary"]:
                if vl_rec.get("ZM") != zm_name: continue
                total_fods = vl_rec.get("total_fods", 0)
                if total_fods <= MIN_CURRENT_MTD_FODS: continue
                
                med_lt = vl_rec.get("median_lt", 999)
                is_critical = False
                red_flags = []
                
                if med_lt < LT_CRITICAL:
                    red_flags.append(f"Median LT = {med_lt:.1f} risk")
                    is_critical = True
                
                for m2 in t2_ms_list:
                    if m2 in data["milestones"]:
                        vl_pct = vl_rec.get(f"pct_{m2}", 0)
                        bv = data["bm_ms"].get(m2, 0)
                        if bv > 0:
                            drop_pct = (bv - vl_pct) / bv
                            # RULE UPDATE: Only process conversion drops metrics for the critical destination milestone (F60th / F50th)
                            if m2 == ms2:
                                if drop_pct >= 0.50: 
                                    red_flags.insert(0, f"Critical Drop F{m2}={vl_pct:.1f}%")
                                    is_critical = True
                                elif drop_pct >= 0.15: 
                                    red_flags.append(f"Drop F{m2}={vl_pct:.1f}%")
                                    is_critical = True
                                
                if is_critical:
                    row_data = [str(vl_rec['vl']), str(zm_name), "CRITICAL", f"{total_fods:,}", str(round(med_lt, 1))]
                    for m2 in t2_ms_list:
                        if m2 in data["milestones"]:
                            row_data.append(_fmt_pct_word(vl_rec.get(f"pct_{m2}", 0)))
                            row_data.append(_fmt_pct_word(data["bm_ms"].get(m2, 0)))
                        else: row_data.extend(["-", "-"])
                    row_data.append(" | ".join(red_flags))
                    t2_rows.append(row_data)

            if t1_rows or t2_rows:
                has_content = True
                html_body += f"<h2>{client_label}</h2>"

                if t1_rows:
                    html_body += f"<h3>MTD VS LMD report</h3><table><tr>"
                    t1_headers = ["VL Name", "ZM Name", f"{curr_m[:3]} MTD", f"LMTD FOD", f"MTD F{ms1}%", f"LMTD F{ms1}%", f"MTD F{ms2}%", f"LMTD F{ms2}%", f"Delta F{ms1}", f"Delta F{ms2}"]
                    for h in t1_headers: html_body += f"<th>{h}</th>"
                    html_body += "</tr>"
                    
                    for row_data in t1_rows:
                        html_body += "<tr>"
                        d_f1_val = row_data[10]
                        d_f2_val = row_data[11]
                        # Render matching layout up to final string column configurations
                        for i, val in enumerate(row_data[:10]): 
                            css_class = ' class="right-align"' if i >= 2 else ''
                            css_style = ""
                            
                            # Heat-map formatting rules applied directly to cell background style properties
                            if i == 8 and d_f1_val is not None:
                                if d_f1_val < 0: css_style = ' style="background-color: #FFCCCC; color: #C00000; font-weight: bold;"'
                                elif d_f1_val > 0: css_style = ' style="background-color: #CCFFCC; color: #375623; font-weight: bold;"'
                            elif i == 9 and d_f2_val is not None:
                                if d_f2_val < 0: css_style = ' style="background-color: #FFCCCC; color: #C00000; font-weight: bold;"'
                                elif d_f2_val > 0: css_style = ' style="background-color: #CCFFCC; color: #375623; font-weight: bold;"'
                                
                            html_body += f"<td{css_class}{css_style}>{val}</td>"
                        html_body += "</tr>"
                    html_body += "</table>"

                if t2_rows:
                    html_body += f"<h3>Platform Avg(Baseline) vs VL Performance report (MTD)</h3>"
                    html_body += f"<p><em>Note: This table shows the list of VLs whose milestones achieved are critically below the platform average.</em></p><table><tr>"
                    
                    t2_headers = ["VL Name", "ZM", "Severity", "Total FODs", "Median LT", "F20th%\n(MTD Achieved)", "F20th%\n(MTD Baseline)", "F60th%\n(MTD Achieved)", "F60th%\n(MTD Baseline)", "F100th%\n(MTD Achieved)", "F100th%\n(MTD Baseline)", "F200th%\n(MTD Achieved)", "F200th%\n(MTD Baseline)", "Red Flags"]
                    for h in t2_headers: html_body += f"<th>{h.replace(chr(10), '<br>')}</th>"
                    html_body += "</tr>"

                    for row_data in t2_rows:
                        html_body += "<tr>"
                        for i, val in enumerate(row_data): 
                            css_class = ' class="right-align"' if 3 <= i <= 12 else ''
                            css_style = ""
                            
                            # Severity Row Styling
                            if i == 2:
                                css_style = ' style="background-color: #FFD2D2; color: #8B0000; font-weight: bold;"'
                            # Median LT Flagging
                            elif i == 4:
                                try:
                                    if float(val) < 5.0: css_style = ' style="background-color: #FFCCCC; color: #C00000; font-weight: bold;"'
                                except: pass
                            # Milestone Heat-mapping comparing overall Achieved vs Baseline values
                            elif i in [5, 7, 9, 11]:
                                try:
                                    achieved_val = float(str(val).replace('%', ''))
                                    baseline_val = float(str(row_data[i+1]).replace('%', ''))
                                    if baseline_val > 0:
                                        ratio = achieved_val / baseline_val
                                        if ratio >= 1.15: css_style = ' style="background-color: #CCFFCC; color: #375623;"'
                                        elif ratio < 0.50: css_style = ' style="background-color: #FFCCCC; color: #C00000;"'
                                        elif ratio < 0.80: css_style = ' style="background-color: #FFE4CC; color: #C55A00;"'
                                except: pass
                                
                            html_body += f"<td{css_class}{css_style}>{val}</td>"
                        html_body += "</tr>"
                    html_body += "</table>"

        if not has_content:
            html_body += "<p>No critical flags or negative quality decline metrics for your cluster this month.</p>"

        html_body += "<br><p>Regards,<br>Nikhil R</p></body></html>"
        html_payloads[zm_name] = html_body
        
    return html_payloads

# ==========================================
# 5. MAIN EXECUTION
# ==========================================
def run_automation():
    print("Starting Automated Mailer Job...")
    refresh_key = get_daily_refresh_key()
    rows = fetch_redash(refresh_key)
    if not rows:
        print("Aborting: No data returned from Redash.")
        return
        
    results = run_analysis(rows)
    html_payloads = generate_html_payloads(results)
    
    for target_zm, email_body_html in html_payloads.items():
        send_email(zm_name=target_zm, html_body=email_body_html)
            
if __name__ == "__main__":
    run_automation()
