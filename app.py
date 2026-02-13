import streamlit as st
import pandas as pd
import time
import math
from datetime import datetime
from streamlit_js_eval import get_geolocation
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="EC Enterprise", page_icon="🛡️")

# --- CONFIG ---
HOSPITAL_LAT = 42.0875
HOSPITAL_LON = -70.9915
GEOFENCE_RADIUS = 300 
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}

# ⚡ HEARTBEAT (Refreshes every 5s to keep UI in sync)
count = st_autorefresh(interval=5000, key="pulse")

# --- DATABASE ENGINE ---
def get_db_connection():
    try:
        if "gcp_service_account" not in st.secrets: return None
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        client = gspread.authorize(creds)
        return client
    except: return None

# --- CRITICAL: FETCH CLOUD TRUTH ---
def get_cloud_state(pin):
    """
    Returns the EXACT state from the cloud.
    This is the Single Source of Truth.
    """
    client = get_db_connection()
    if not client: return None # Offline
    try:
        sheet = client.open("ec_database").worksheet("workers")
        records = sheet.get_all_records()
        for row in records:
            if str(row.get('pin')) == str(pin):
                return row # Returns {status: 'Active', ...}
        return {} # User not found
    except: return None

def update_cloud_status(pin, status, start_time, earnings):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("workers")
            try:
                cell = sheet.find(str(pin))
                row = cell.row
                sheet.update_cell(row, 2, status)
                sheet.update_cell(row, 3, str(start_time))
                sheet.update_cell(row, 4, str(earnings))
                sheet.update_cell(row, 5, str(datetime.now()))
            except:
                sheet.append_row([str(pin), status, str(start_time), str(earnings), str(datetime.now())])
        except: pass

def log_to_ledger(pin, action, earnings, gps_msg):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("history")
            sheet.append_row([str(pin), action, str(datetime.now()), f"${earnings:.2f}", gps_msg])
        except: pass

# --- MATH ---
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

# --- STATE ---
if 'user_state' not in st.session_state: 
    st.session_state.user_state = {'active': False, 'start_time': 0.0, 'earnings': 0.0}

USERS = {
    "1001": {"name": "Liam O'Neil", "role": "RT", "rate": 85.00},
    "9999": {"name": "CFO VIEW", "role": "Exec", "rate": 0.00}
}

# --- LOGIN ---
if 'logged_in_user' not in st.session_state:
    st.title("🛡️ EC Enterprise")
    st.caption("v53.0 | UI Lockout Protocol")
    
    pin = st.text_input("ENTER PIN", type="password")
    if st.button("AUTHENTICATE"):
        if pin in USERS:
            st.session_state.logged_in_user = USERS[pin]
            st.session_state.pin = pin
            st.rerun()
        else:
            st.error("INVALID PIN")
    st.stop()

# --- ROUTING ---
user = st.session_state.logged_in_user
pin = st.session_state.pin

# ==================================================
# 👤 WORKER FIELD UNIT
# ==================================================
if user['role'] != "Exec":
    st.title(f"👤 {user['name']}")

    # 1. 🛑 FORCE SYNC BEFORE DRAWING UI 🛑
    # We do NOT rely on session state alone. We check the cloud every time.
    cloud_data = get_cloud_state(pin)
    
    # Defaults
    is_active = False
    start_time = 0.0
    saved_earnings = 0.0
    
    if cloud_data:
        if cloud_data.get('status') == 'Active':
            is_active = True
            try:
                start_time = float(cloud_data.get('start_time', 0))
                saved_earnings = float(cloud_data.get('earnings', 0))
            except: pass
        else:
            is_active = False
            try:
                saved_earnings = float(cloud_data.get('earnings', 0))
            except: pass
    
    # 2. GPS LOGIC
    loc = get_geolocation()
    dist_msg = "Triangulating..."
    is_inside = False

    with st.sidebar:
        dev_override = st.checkbox("FORCE INSIDE ZONE")
        if st.button("LOGOUT"):
            st.session_state.clear()
            st.rerun()

    if loc:
        dist = get_distance(loc['coords']['latitude'], loc['coords']['longitude'], HOSPITAL_LAT, HOSPITAL_LON)
        is_inside = dist < GEOFENCE_RADIUS or dev_override
        dist_msg = f"✅ INSIDE ({int(dist)}m)" if is_inside else f"🚫 OUTSIDE ({int(dist)}m)"

    st.info(f"📍 GPS: {dist_msg}")

    # 3. MONEY LOGIC
    current_earnings = saved_earnings
    if is_active:
        elapsed = (time.time() - start_time) / 3600
        current_earnings += elapsed * user['rate']

    net_pay = calculate_taxes(current_earnings)
    c1, c2 = st.columns(2)
    c1.metric("GROSS", f"${current_earnings:,.2f}")
    c2.metric("NET", f"${net_pay:,.2f}")

    # 4. 🛑 THE LOCKED UI 🛑
    # We use the 'is_active' variable derived directly from the cloud above.
    
    if is_active:
        # USER IS WORKING -> ONLY SHOW CLOCK OUT
        st.success("🟢 STATUS: ON SHIFT (Cloud Verified)")
        if st.button("🔴 CLOCK OUT"):
            update_cloud_status(pin, "Inactive", 0, current_earnings)
            log_to_ledger(pin, "CLOCK OUT", current_earnings, dist_msg)
            st.success("ENDED & LOGGED")
            time.sleep(1); st.rerun()
            
    else:
        # USER IS NOT WORKING -> ONLY SHOW CLOCK IN
        st.warning("⚪ STATUS: OFF DUTY")
        if st.button("🟢 CLOCK IN"):
            if is_inside:
                update_cloud_status(pin, "Active", time.time(), current_earnings)
                log_to_ledger(pin, "CLOCK IN", current_earnings, dist_msg)
                st.success("STARTED")
                time.sleep(1); st.rerun()
            else:
                st.error("Outside Zone")

    # History
    st.markdown("---")
    with st.expander("📜 View Shift History"):
        try:
            client = get_db_connection()
            if client:
                sheet = client.open("ec_database").worksheet("history")
                data = sheet.get_all_records()
                df = pd.DataFrame(data)
                my_history = df[df['pin'].astype(str) == str(pin)]
                st.dataframe(my_history)
        except: st.caption("No history found.")

# ==================================================
# 🏛️ CFO WATCHTOWER (Standard View)
# ==================================================
else:
    st.title("🛡️ COMMAND CENTER")
    # ... (CFO Logic stays the same) ...
    client = get_db_connection()
    if client:
        sheet = client.open("ec_database").worksheet("workers")
        data = sheet.get_all_records()
        active_count = len([x for x in data if x.get('status') == 'Active'])
        st.metric("ACTIVE STAFF", active_count)
        st.dataframe(data)
        
    if st.button("LOGOUT"):
        st.session_state.clear()
        st.rerun()
