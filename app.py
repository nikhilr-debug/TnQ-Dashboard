<!-- ... existing code ... -->
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
yesterday = date.today() - timedelta(days=1) # Corrected from days=6 to days=1 for true yesterday MTD
mtd_day = yesterday.day
start_month = yesterday.month - 3
start_year = yesterday.year
if start_month <= 0:
    start_month += 12
    start_year -= 1
START_DATE = str(date(start_year, start_month, 1))
END_DATE = str(yesterday)

# --- 2. DATA ACQUISITION & CACHING ---
IST = timezone(timedelta(hours=5, minutes=30))

def get_daily_refresh_key():
<!-- ... existing code ... -->
