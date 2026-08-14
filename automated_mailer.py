import os
import smtplib
import time
import requests
import pandas as pd
import warnings
from datetime import date, timedelta, datetime, timezone
from email.message import EmailMessage

# Suppress expected Pandas/Numpy empty slice warnings during headless execution
warnings.filterwarnings('ignore', r'Mean of empty slice')

# ==========================================
# 1. CONFIGURATION & TEST MODE
# ==========================================
SENDER_EMAIL = "nikhil.r@vahan.co"
EMAIL_PASSWORD = os.environ.get("EMAIL_APP_PASS")
SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_TARGET_CHANNEL = "U0B75HAKDUK"  # User ID for DM Alerts

# TOGGLE THIS: Set to True to route all emails to yourself. Set to False for production.
TEST_MODE = False
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

# Clients scaled to include Rapido, Big Basket, Porter, and Loadshare
ACTIVE_CLIENTS = ["blinkit", "swiggy", "swiggy instamart", "uber", "rapido", "big basket", "porter", "loadshare"]
CLIENT_FULL = {ck: ck.upper() for ck in ACTIVE_CLIENTS}

CLIENT_MS = {
    "blinkit": ["20th", "60th", "100th", "120th", "150th", "200th"],
    "swiggy": ["5th", "10th", "20th", "50th", "60th", "80th", "100th", "150th", "200th"],
    "swiggy instamart": ["5th", "10th", "20th", "50th", "60th", "80th", "100th", "150th", "200th"],
    "uber": ["10th", "20th", "30th", "50th", "100th", "150th", "200th"],
    "rapido": ["5th", "10th", "20th", "50th", "60th", "80th", "100th", "150th", "200th"],
    "big basket": ["5th", "10th", "20th", "50th", "60th", "80th", "100th", "150th", "200th"],
    "porter": ["5th", "10th", "20th", "50th", "60th", "80th", "100th", "150th", "200th"],
    "loadshare": ["5th", "10th", "20th", "50th", "60th", "80th", "100th", "150th", "200th"],
}

CLIENT_KEY_MS = {
    "blinkit": "60th", "swiggy": "20th", "swiggy instamart": "20th", "uber": "20th",
    "rapido": "20th", "big basket": "20th", "porter": "20th", "loadshare": "20th"
}

CLIENT_DECLINE_MS = {
    "blinkit":          ("20th", "60th"),
    "swiggy":           ("20th", "50th"),
    "swiggy instamart": ("20th", "50th"),
    "uber":             ("10th", "20th"),
    "rapido":           ("20th", "50th"),
    "big basket":       ("20th", "50th"),
    "porter":           ("20th", "50th"),
    "loadshare":        ("20th", "50th"),
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
        print(f"EXECUTION: Sending [TEST] email for ZM '{zm_name}' to {TEST_EMAIL}")
    else:
        recipient = ZM_EMAILS.get(zm_name)
        if not recipient: 
            print(f"EXECUTION ERROR: Attempted to send to unregistered ZM name: '{zm_name}'")
            return
        msg['To'] = recipient
        msg['Cc'] = CC_EMAILS
        msg['Subject'] = subject
        print(f"EXECUTION: Sending live email for ZM '{zm_name}' to {recipient} (CC: {CC_EMAILS})")

    msg.set_content(html_body, subtype='html')

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(SENDER_EMAIL, EMAIL_PASSWORD)
            smtp.send_message(msg)
        print(f"Success: Email delivery confirmed for ZM {zm_name}")
    except Exception as e:
        print(f"Critical Error sending email for {zm_name}: {e}")

# ==========================================
# 3. DATA FETCHING 
# ==========================================
def get_daily_refresh_key():
    now = datetime.now(IST)
    if now.hour < 13 or (now.hour == 13 and now.minute < 30):
        return str(now.date() - timedelta(days=1))
    return str(now.date())

def fetch_redash(refresh_key):
    print("Sending execution trigger to Redash query pipeline...")
    body_fresh = {"parameters": {"Client": ACTIVE_CLIENTS}, "max_age": 7200}
    body_cached = {**body_fresh, "max_age": 7200}
    
    try:
        r = requests.post(f"{REDASH_URL}/api/queries/{QUERY_ID}/results?api_key={REDASH_API_KEY}", json=body_fresh, timeout=30)
        j = r.json()
        
        if "query_result" in j:
            rows = j["query_result"]["data"]["rows"]
            print(f"Data retrieved instantly from cache. Total rows: {len(rows)}")
            return rows
            
        if "job" not in j:
            print(f"Redash API Error: {j}")
            return []
            
        job_id = j["job"]["id"]
        print(f"Query executing asynchronously. Tracking Job ID: {job_id}")
        
        for attempt in range(1, 41):
            time.sleep(15)
            print(f" -> Polling Redash results endpoint [Attempt {attempt}/40]...")
            r2 = requests.post(f"{REDASH_URL}/api/queries/{QUERY_ID}/results?api_key={REDASH_API_KEY}", json=body_cached, timeout=30)
            j2 = r2.json()
            
            if "query_result" in j2:
                rows = j2["query_result"]["data"]["rows"]
                print(f"Download complete. Total rows parsed: {len(rows)}")
                return rows
                
        print("Timed out waiting for Redash after 10 minutes.")
        return []
    except Exception as e:
        print(f"Network error during Redash polling: {e}")
        return []

def run_analysis(rows):
    if not rows: 
        return {}, []
    df = pd.DataFrame(rows)
    
    if "company_name" in df.columns:
        df["company_name"] = df["company_name"].fillna("unknown").astype(str).str.strip().str.lower()
    else:
        df["company_name"] = "unknown"
        
    available_clients = df["company_name"].unique().tolist()
    
    df["_fod"] = pd.to_datetime(df["first_date_of_work"], format="%Y-%m-%d", errors="coerce")
    valid = df["_fod"].notna() & (df["_fod"].dt.day <= mtd_day) & (df["_fod"] <= pd.Timestamp(END_DATE))
    df = df[valid].copy()
    df["_month"] = df["_fod"].dt.strftime("%b-%Y")
    df = df.drop_duplicates(subset=["phone_number", "_month"])
    df["_vl"] = df["vl_name"].fillna("Unknown")
    col_map = {str(c).strip().lower(): c for c in df.columns}
    df["ZM"] = df[col_map["zm"]].fillna("Unknown") if "zm" in col_map else "Unknown"

    print(f"DEBUG: Unique ZM names found in the processed Redash data: {df['ZM'].unique().tolist()}")

    results = {}
    for client in ACTIVE_CLIENTS:
        if client not in available_clients:
            print(f"⚠️ PIPELINE ALERT: '{client.upper()}' is completely missing from the Redash query output. Bypassing email/Slack inclusion for this client.")
            continue
            
        sub = df[df["company_name"] == client].copy()
        ms_list = CLIENT_MS.get(client, [])
        key_ms = CLIENT_KEY_MS.get(client, ms_list[0])
        
        for ms in ms_list:
            col = f"{ms}_order_date"
            if col not in sub.columns: 
                sub[col] = None
            sub[col + "_dt"] = pd.to_datetime(sub[col], format="%Y-%m-%d", errors="coerce")
            sub[f"has_{ms}"] = ((sub[col + "_dt"].dt.year == sub["_fod"].dt.year) & 
                                (sub[col + "_dt"].dt.month == sub["_fod"].dt.month) & 
                                (sub[col + "_dt"].dt.day <= mtd_day)).astype(int)

        all_months = sorted(sub["_month"].unique(), key=lambda x: pd.to_datetime("01 " + x))
        monthly = []
        
        for m in all_months:
            g = sub[sub["_month"] == m]
            if len(g) == 0: 
                continue
            rec = {"month": m, "fods": len(g)}
            for ms in ms_list: 
                rec[f"pct_{ms}"] = round(g[f"has_{ms}"].mean() * 100, 2)
            monthly.append(rec)
            
        bm_ms = {ms2: round(sum(m.get(f"pct_{ms2}", 0) for m in monthly) / max(len(monthly), 1), 2) for ms2 in ms_list}

        vl_summary = []
        vl_monthly = {}
        for vl_name, vl_df in sub.groupby("_vl"):
            if len(vl_df) < MIN_VL_FODS: 
                continue
            lt_all = vl_df["candidate_lifetime_orders_trips"].astype(float)
            rec = {
                "vl": vl_name, 
                "ZM": vl_df["ZM"].mode()[0] if not vl_df["ZM"].empty else "Unknown", 
                "total_fods": len(vl_df), 
                "median_lt": round(lt_all.median(), 2)
            }
            for ms in ms_list: 
                rec[f"pct_{ms}"] = round(vl_df[f"has_{ms}"].mean() * 100, 2)
            
            vm = {}
            for m in all_months:
                m_df = vl_df[vl_df["_month"] == m]
                if len(m_df) == 0: 
                    vm[m] = None
                    continue
                m_rec = {"fods": len(m_df)}
                for ms in ms_list: 
                    m_rec[f"pct_{ms}"] = round(m_df[f"has_{ms}"].mean() * 100, 2)
                vm[m] = m_rec
                
            vl_monthly[vl_name] = vm
            curr_m = all_months[-1] if all_months else None
            rec["curr_m_fods"] = vm[curr_m]["fods"] if curr_m and vm.get(curr_m) else 0
            vl_summary.append(rec)

        vl_summary = sorted(vl_summary, key=lambda x: x.get("curr_m_fods", 0), reverse=True)
        results[client] = {"monthly": monthly, "vl_summary": vl_summary, "vl_monthly": vl_monthly, "bm_ms": bm_ms, "milestones": ms_list, "key_ms": key_ms}
        
    return results, available_clients

# ==========================================
# 4. HTML GENERATION ENGINE
# ==========================================
def _fmt_pct_word(val): 
    return "-" if pd.isna(val) or val is None else f"{val:.1f}%"

def generate_html_payloads(results):
    html_payloads = {}
    unique_zms = set()
    
    for ck in ACTIVE_CLIENTS:
        if ck in results:
            for vl in results[ck]["vl_summary"]:
                zm_raw_name = str(vl.get("ZM", "")).strip()
                for authorized_zm in ZM_EMAILS.keys():
                    if authorized_zm.lower() in zm_raw_name.lower() and zm_raw_name != "Unknown":
                        unique_zms.add(authorized_zm)
    
    print(f"DEBUG: Final filtered target ZMs matching delivery list: {list(unique_zms)}")
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
            if ck not in results: 
                continue
                
            data = results[ck]
            client_label = CLIENT_FULL.get(ck, ck.upper())
            mon = data["monthly"]
            if len(mon) < 2: 
                continue
                
            curr_m, prev_m = mon[-1]["month"], mon[-2]["month"]
            ms1, ms2 = CLIENT_DECLINE_MS.get(ck, (data["milestones"][0], data["key_ms"]))

            t1_rows = []
            for vl in data["vl_summary"]:
                if zm_name.lower() not in str(vl.get("ZM", "")).lower(): 
                    continue
                vln = vl["vl"]
                vm = data["vl_monthly"].get(vln, {})
                curr_d, prev_d = vm.get(curr_m) or {}, vm.get(prev_m) or {}
                
                curr_f1, prev_f1 = curr_d.get(f"pct_{ms1}"), prev_d.get(f"pct_{ms1}")
                curr_f2, prev_f2 = curr_d.get(f"pct_{ms2}"), prev_d.get(f"pct_{ms2}")
                
                d_f1 = round(curr_f1 - prev_f1, 1) if curr_f1 is not None and prev_f1 is not None else None
                d_f2 = round(curr_f2 - prev_f2, 1) if curr_f2 is not None and prev_f2 is not None else None

                if d_f2 is not None and d_f2 < 0:
                    t1_rows.append([str(vln), str(zm_name), f"{curr_d.get('fods', 0):,}", f"{prev_d.get('fods', 0):,}", _fmt_pct_word(curr_f1), _fmt_pct_word(prev_f1), _fmt_pct_word(curr_f2), _fmt_pct_word(prev_f2), f"{d_f1:+.1f}%" if d_f1 is not None else "-", f"{d_f2:+.1f}%" if d_f2 is not None else "-", d_f1, d_f2])

            t2_ms_list = ["20th", "60th", "100th", "200th"]
            t2_rows = []
            for vl_rec in data["vl_summary"]:
                if zm_name.lower() not in str(vl_rec.get("ZM", "")).lower(): 
                    continue
                total_fods = vl_rec.get("total_fods", 0)
                if total_fods <= MIN_CURRENT_MTD_FODS: 
                    continue
                
                med_lt = vl_rec.get("median_lt", 999)
                is_critical = False
                red_flags = []
                
                if med_lt < LT_CRITICAL:
                    red_flags.append(f"LT={med_lt:.1f}")
                    is_critical = True
                
                for m2 in t2_ms_list:
                    if m2 in data["milestones"]:
                        vl_pct = vl_rec.get(f"pct_{m2}", 0)
                        bv = data["bm_ms"].get(m2, 0)
                        if bv > 0:
                            drop_pct = (bv - vl_pct) / bv
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
                        else: 
                            row_data.extend(["-", "-"])
                    row_data.append(" | ".join(red_flags))
                    t2_rows.append(row_data)

            if t1_rows or t2_rows:
                has_content = True
                html_body += f"<h2>{client_label}</h2>"

                if t1_rows:
                    html_body += f"<h3>MTD VS LMD report</h3><table><tr>"
                    t1_headers = ["VL Name", "ZM Name", f"{curr_m[:3]} MTD", f"LMTD FOD", f"MTD F{ms1}%", f"LMTD F{ms1}%", f"MTD F{ms2}%", f"LMTD F{ms2}%", f"Delta F{ms1}", f"Delta F{ms2}"]
                    for h in t1_headers: 
                        html_body += f"<th>{h}</th>"
                    html_body += "</tr>"
                    
                    for row_data in t1_rows:
                        html_body += "<tr>"
                        d_f1_val = row_data[10]
                        d_f2_val = row_data[11]
                        for i, val in enumerate(row_data[:10]): 
                            css_class = ' class="right-align"' if i >= 2 else ''
                            css_style = ""
                            
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
                    for h in t2_headers: 
                        html_body += f"<th>{h.replace(chr(10), '<br>')}</th>"
                    html_body += "</tr>"

                    for row_data in t2_rows:
                        html_body += "<tr>"
                        for i, val in enumerate(row_data): 
                            css_class = ' class="right-align"' if 3 <= i <= 12 else ''
                            css_style = ""
                            
                            if i == 2:
                                css_style = ' style="background-color: #FFD2D2; color: #8B0000; font-weight: bold;"'
                            elif i == 4:
                                try:
                                    if float(val) < 5.0: css_style = ' style="background-color: #FFCCCC; color: #C00000; font-weight: bold;"'
                                except: pass
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
# 5. SLACK ALERT ENGINE
# ==========================================
def _fmt_num(val):
    """Formats numeric values: 2 decimals if decimal exists, 0 if whole number."""
    if pd.isna(val) or val is None:
        return "-"
    if isinstance(val, (int, float)):
        if val == int(val):
            return f"{int(val)}"
        return f"{val:.2f}"
    return val

def send_slack_alerts(results, available_clients):
    if not SLACK_TOKEN:
        print("SLACK ALERT: No Slack Bot Token found. Bypassing Slack integration.")
        return

    from slack_sdk import WebClient
    import dataframe_image as dfi
    client_slack = WebClient(token=SLACK_TOKEN)

    # Force Pandas to render entire DataFrame without truncation
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 2000)

    # --- DEFENSIVE API GATE: Resolve U... IDs to D... Channel Strings ---
    resolved_channel_id = SLACK_TARGET_CHANNEL
    if SLACK_TARGET_CHANNEL.startswith("U"):
        print(f"Resolving User ID '{SLACK_TARGET_CHANNEL}' to a DM Channel ID...")
        try:
            res = client_slack.conversations_open(users=SLACK_TARGET_CHANNEL)
            resolved_channel_id = res["channel"]["id"]
            print(f" -> Successfully mapped to Bot's DM Channel ID: {resolved_channel_id}")
        except Exception as e:
            print(f"Failed to open DM conversation with User ID: {e}")
            return

    print("Executing Headless Slack Engine for Top 10 Defaulters...")
    
    for ck in ACTIVE_CLIENTS:
        if ck not in available_clients or ck not in results: 
            continue
            
        data = results[ck]
        client_label = CLIENT_FULL.get(ck, ck.upper())
        mon = data["monthly"]
        
        if len(mon) < 2: 
            continue
            
        curr_m, prev_m = mon[-1]["month"], mon[-2]["month"]
        ms1, ms2 = CLIENT_DECLINE_MS.get(ck, (data["milestones"][0], data["key_ms"]))
        t2_ms_list = ["20th", "60th", "100th", "200th"]

        t1_list, t2_list = [], []

        for vl_rec in data["vl_summary"]:
            vln = vl_rec["vl"]
            zm_name = vl_rec.get("ZM", "Unknown")
            vm = data["vl_monthly"].get(vln, {})
            curr_d, prev_d = vm.get(curr_m) or {}, vm.get(prev_m) or {}
            
            curr_f1, prev_f1 = curr_d.get(f"pct_{ms1}"), prev_d.get(f"pct_{ms1}")
            curr_f2, prev_f2 = curr_d.get(f"pct_{ms2}"), prev_d.get(f"pct_{ms2}")
            d_f1 = round(curr_f1 - prev_f1, 1) if curr_f1 is not None and prev_f1 is not None else None
            d_f2 = round(curr_f2 - prev_f2, 1) if curr_f2 is not None and prev_f2 is not None else None

            # Gather T1 (Negative Delta)
            if d_f2 is not None and d_f2 < 0:
                t1_list.append({
                    "VL Name": vln, 
                    "ZM Name": zm_name, 
                    f"{curr_m[:3]} MTD FOD": curr_d.get('fods', 0),
                    "LMTD FOD": prev_d.get('fods', 0),
                    f"MTD F{ms1}%": curr_f1, 
                    f"LMTD F{ms1}%": prev_f1,
                    f"MTD F{ms2}%": curr_f2, 
                    f"LMTD F{ms2}%": prev_f2,
                    f"Delta F{ms1}": d_f1, 
                    f"Delta F{ms2}": d_f2
                })

            # Gather T2 (Critical Drop/Ghost Risk)
            total_fods = vl_rec.get("total_fods", 0)
            if total_fods > MIN_CURRENT_MTD_FODS:
                med_lt = vl_rec.get("median_lt", 999)
                is_critical = False
                red_flags = []
                
                if med_lt < LT_CRITICAL:
                    red_flags.append(f"LT={med_lt:.1f}")
                    is_critical = True
                
                if ms2 in data["milestones"]:
                    vl_pct = vl_rec.get(f"pct_{ms2}", 0)
                    bv = data["bm_ms"].get(ms2, 0)
                    if bv > 0 and (bv - vl_pct) / bv >= 0.50:
                        red_flags.append(f"Drop F{ms2}={vl_pct:.1f}%")
                        is_critical = True
                
                if is_critical:
                    t2_dict = {
                        "VL Name": vln, "ZM": zm_name, "Severity": "CRITICAL", 
                        "Total FODs": total_fods, "Median LT": med_lt
                    }
                    for m2 in t2_ms_list:
                        if m2 in data["milestones"]:
                            t2_dict[f"F{m2}% (MTD)"] = vl_rec.get(f"pct_{m2}", 0)
                            t2_dict[f"F{m2}% (Base)"] = data["bm_ms"].get(m2, 0)
                        else:
                            t2_dict[f"F{m2}% (MTD)"] = None
                            t2_dict[f"F{m2}% (Base)"] = None
                            
                    t2_dict["Red Flags"] = " | ".join(red_flags)
                    t2_list.append(t2_dict)

        # Render & Upload T1
        if t1_list:
            df_t1 = pd.DataFrame(t1_list).sort_values(by=f"{curr_m[:3]} MTD FOD", ascending=False).head(10)
            styled_t1 = df_t1.style.format(_fmt_num).hide(axis="index").set_properties(
                **{'background-color': '#FFCCCC', 'color': '#C00000'}, subset=[f"Delta F{ms1}", f"Delta F{ms2}"]
            )
            img_path_t1 = f"t1_{ck}_temp.png"
            dfi.export(styled_t1, img_path_t1, dpi=300, max_cols=-1)
            
            try:
                client_slack.files_upload_v2(
                    channel=resolved_channel_id,
                    file=img_path_t1,
                    title=f"{client_label} - Top 10 Negative MoM Delta",
                    initial_comment=f"📉 *{client_label}* - Top 10 VLs (Negative MTD Growth)"
                )
            except Exception as e: 
                print(f"Slack Upload Error (T1) {ck}: {e}")
            finally:
                if os.path.exists(img_path_t1): 
                    os.remove(img_path_t1)

        # Render & Upload T2
        if t2_list:
            df_t2 = pd.DataFrame(t2_list).sort_values(by="Total FODs", ascending=False).head(10)
            styled_t2 = df_t2.style.format(_fmt_num).hide(axis="index").set_properties(
                **{'background-color': '#FFD2D2', 'color': '#8B0000'}, subset=["Red Flags"]
            )
            img_path_t2 = f"t2_{ck}_temp.png"
            dfi.export(styled_t2, img_path_t2, dpi=300, max_cols=-1)
            
            try:
                client_slack.files_upload_v2(
                    channel=resolved_channel_id,
                    file=img_path_t2,
                    title=f"{client_label} - Top 10 Critical Risks",
                    initial_comment=f"🚨 *{client_label}* - Top 10 VLs (Critical Baseline Drops)"
                )
            except Exception as e: 
                print(f"Slack Upload Error (T2) {ck}: {e}")
            finally:
                if os.path.exists(img_path_t2): 
                    os.remove(img_path_t2)

# ==========================================
# 6. MAIN EXECUTION
# ==========================================
def run_automation():
    print("Starting Automated Mailer Job...")
    refresh_key = get_daily_refresh_key()
    rows = fetch_redash(refresh_key)
    
    if not rows:
        print("Aborting execution: No data rows returned from Redash endpoints.")
        return
        
    print("Beginning multi-client data analysis calculations...")
    results, available_clients = run_analysis(rows)
    
    # 1. Dispatch Emails
    print("Rendering HTML email layouts...")
    html_payloads = generate_html_payloads(results)
    
    if not html_payloads:
        print("Warning: Email generation process complete, but 0 matches were created. Check ZM naming variations.")
    else:
        print(f"Dispatching localized emails to execution queues... Found {len(html_payloads)} ZM outputs.")
        for target_zm, email_body_html in html_payloads.items():
            send_email(zm_name=target_zm, html_body=email_body_html)
            
    # 2. Dispatch Slack Alerts
    send_slack_alerts(results, available_clients)
    
    print("Automation Job Complete!")
            
if __name__ == "__main__":
    run_automation()
