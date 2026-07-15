import os
import smtplib
import zipfile
from email.message import EmailMessage

# Import your existing dashboard logic directly!
import app 

# ==========================================
# 1. CONFIGURATION & TEST MODE
# ==========================================
SENDER_EMAIL = "nikhil.r@vahan.co"
EMAIL_PASSWORD = os.environ.get("EMAIL_APP_PASS")

# TOGGLE THIS: Set to True to route all emails to yourself. Set to False for production.
TEST_MODE = True
TEST_EMAIL = "nikhil.r@vahan.co"

ZM_EMAILS = {
    "Piyush": "piyush.monga@vahan.co",
    "Rohit": "rohit@vahan.co",
    "Vishal": "vishalmittra@vahan.co",
    "Anil Kumar Singh": "anil@vahan.co"
}

# ==========================================
# 2. EMAIL SENDER LOGIC
# ==========================================
def send_email(zm_name, attachment_path, body_content):
    """Handles SMTP connection and dynamic test routing."""
    if TEST_MODE:
        recipient = TEST_EMAIL
        subject = f"[TEST] Automated Report for {zm_name}"
        print(f"TEST MODE ACTIVE: Diverting {zm_name}'s email to {recipient}")
    else:
        recipient = ZM_EMAILS.get(zm_name)
        subject = f"Automated ZM Report for {zm_name}"
        
    if not recipient:
        print(f"Error: No email mapped for {zm_name}. Skipping.")
        return

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    msg['To'] = recipient
    msg.set_content(body_content)

    if os.path.exists(attachment_path):
        with open(attachment_path, 'rb') as f:
            msg.add_attachment(
                f.read(),
                maintype='application',
                subtype='vnd.openxmlformats-officedocument.wordprocessingml.document',
                filename=os.path.basename(attachment_path)
            )

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(SENDER_EMAIL, EMAIL_PASSWORD)
            smtp.send_message(msg)
        print(f"Success: Email sent to {recipient} for ZM {zm_name}")
    except Exception as e:
        print(f"Critical Error sending email for {zm_name}: {e}")

# ==========================================
# 3. MAIN HEADLESS JOB 
# ==========================================
def run_automation():
    print("Starting Automated Mailer Job...")
    
    # 1. Fetch data seamlessly using app.py's Redash functions
    refresh_key = app.get_daily_refresh_key()
    print(f"Fetching Redash data with key: {refresh_key}...")
    rows = app.fetch_redash(refresh_key)
    
    if not rows:
        print("Aborting: No data returned from Redash.")
        return
        
    # 2. Run analysis using app.py's core logic
    print("Processing data metrics...")
    results, df_raw = app.run_analysis(rows)
    
    # 3. Generate Word Documents (app.py returns a zip folder in memory)
    print("Drafting Word Documents...")
    zip_buffer = app.generate_zm_email_drafts(results, df_raw, app.mtd_day, app.END_DATE)
    
    # Extract the generated drafts to a temporary local directory
    output_dir = "temp_zm_drafts"
    os.makedirs(output_dir, exist_ok=True)
    with zipfile.ZipFile(zip_buffer, "r") as zip_ref:
        zip_ref.extractall(output_dir)
        
    print("Documents extracted successfully. Preparing to dispatch emails...")
    
    # 4. Route and send emails based on the generated files
    for filename in os.listdir(output_dir):
        if not filename.endswith(".docx"): continue
        
        file_path = os.path.join(output_dir, filename)
        
        # Reverse-match the file name back to the exact ZM mapping
        target_zm = None
        for zm_key in ZM_EMAILS.keys():
            safe_key = "".join([c for c in zm_key if c.isalpha() or c.isdigit() or c==' ']).rstrip().replace(' ', '_')
            if safe_key in filename:
                target_zm = zm_key
                break
                
        if not target_zm:
            print(f"Skipping file {filename}: No matching ZM in email dictionary.")
            continue
            
        email_body = f"""Hi {target_zm},

Please find attached your automated MTD performance report and anomaly flags for your region up to {app.END_DATE}.

Please review the critical vendor drops and take necessary actions. (Tables sorted by highest MTD FOD volume).

Best regards,
Nikhil
"""
        send_email(
            zm_name=target_zm, 
            attachment_path=file_path, 
            body_content=email_body
        )
        
    print("Automation Job Complete!")

if __name__ == "__main__":
    run_automation()
