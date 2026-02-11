import streamlit as st
import pandas as pd
import time
import math
import hashlib
import random
from datetime import datetime
from streamlit_js_eval import get_geolocation
import gspread
from oauth2client.service_account import ServiceAccountCredentials

st.set_page_config(page_title="EC Enterprise", page_icon="🛡️")

# --- CONFIG ---
HOSPITAL_LAT = 42.0875 # Signature Healthcare
HOSPITAL_LON = -70.9915
GEOFENCE_RADIUS = 300 
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}

# --- DATABASE CONNECTION ---
def get_db():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(creds)
    return client.open("ec_database").worksheet("workers")

# --- HELPER FUNCTIONS ---
def get_worker_status(pin):
    try:
        sheet = get_db()
        records = sheet.get_all_records()
        for i, row in enumerate(records):
            if str(row['pin']) == str(pin):
                return row, i + 2 # Return data and row number (1-based + header)
        return None, None
    except Exception as e:
        st.error(f"DB Error: {e}")
        return None, None

def update_worker_db(row_num, status, start_time, earnings):
    try:
        sheet = get_db()
        # Update Columns B, C, D (Status, Start, Earnings)
        sheet.update_cell(row_num, 2, status)
        sheet.update_cell(row_num, 3, start_time)
        sheet.update_cell(row_num, 4, earnings)
        sheet.update_cell(row_num, 5, str(datetime.now()))
    except:
        st.error("Failed to sync with Cloud DB")

def get_distance(lat1, lon1, lat2, lon2):
    R = 6371000 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return c * R

def calculate_taxes(gross):
    return gross * (1 - sum(TAX_RATES.values()))

# --- USER MAPPING ---
USERS = {
    "1001": {"name": "Liam O'Neil", "role": "Respiratory Therapist", "rate": 85.00},
    "9999": {"name": "CFO VIEW", "role": "CFO", "rate": 0.00}
}

# --- LOGIN ---
if 'logged_in_user' not in st.session_state:
    st.title("🛡️ EC Enterprise")
    st.caption("Cloud-Linked | v45.0")
    pin = st.text_input("ENTER PIN", type="password")
    
    if st.button("AUTHENTICATE"):
        if pin in USERS:
            st.session_state.logged_in_user = USERS[pin]
            st.session_state.pin = pin
            st.rerun()
        else:
            st.error("INVALID ACCESS")
    st.stop()

# --- MAIN APP ---
user = st.session_state.logged_in_user
pin = st.session_state.pin

# 1. SYNC WITH GOOGLE SHEETS
db_data, row_num = get_worker_status(pin)

# If user not in DB, create them (First time only)
if db_data is None and user['role'] != "CFO":
    try:
        sheet = get_db()
        sheet.append_row([pin, "Inactive", 0, 0.0, str(datetime.now())])
        st.rerun()
    except:
        st.error("DB Initialization Failed")

# Parse DB Data
if user['role'] != "CFO":
    is_active = db_data['status'] == "Active"
    start_time = float(db_data['start_time']) if db_data['start_time'] != 0 else 0
    saved_earnings = float(db_data['earnings'])
else:
    is_active = False

# --- UI: WORKER VIEW ---
if user['role'] != "CFO":
    st.title(f"👤 {user['name']}")
    
    # Live Earnings Calc
    current_earnings = saved_earnings
    if is_active:
        elapsed = (time.time() - start_time) / 3600
        current_earnings += elapsed * user['rate']
    
    net_pay = calculate_taxes(current_earnings)
    
    c1, c2 = st.columns(2)
    c1.metric("GROSS", f"${current_earnings:,.2f}")
    c2.metric("NET (EST)", f"${net_pay:,.2f}")
    
    # GPS Sentinel
    st.markdown("---")
    st.markdown("### 📡 SATELLITE LINK")
    
    with st.sidebar:
        dev_override = st.checkbox("FORCE GPS (DEV)")
        
    loc = get_geolocation()
    if loc:
        dist = get_distance(loc['coords']['latitude'], loc['coords']['longitude'], HOSPITAL_LAT, HOSPITAL_LON)
        is_inside = dist < GEOFENCE_RADIUS or dev_override
        
        if is_inside:
            st.success(f"✅ VERIFIED ({int(dist)}m)")
            
            if not is_active:
                if st.button("🟢 CLOCK IN"):
                    # WRITE TO GOOGLE SHEETS
                    update_worker_db(row_num, "Active", time.time(), saved_earnings)
                    st.success("SYNCED TO CLOUD")
                    time.sleep(1); st.rerun()
            else:
                if st.button("🔴 CLOCK OUT"):
                    # WRITE FINAL EARNINGS TO GOOGLE SHEETS
                    update_worker_db(row_num, "Inactive", 0, current_earnings)
                    st.success("SHIFT SAVED TO CLOUD")
                    time.sleep(1); st.rerun()
        else:
            st.error(f"🚫 BLOCKED ({int(dist)}m)")
    else:
        st.info("Waiting for GPS...")

# --- UI: CFO VIEW ---
else:
    st.title("🛡️ COMMAND CENTER")
    try:
        sheet = get_db()
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        st.dataframe(df)
        st.map(pd.DataFrame({'lat': [HOSPITAL_LAT], 'lon': [HOSPITAL_LON]}))
    except:
        st.error("Connection Error")
