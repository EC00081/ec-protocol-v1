import streamlit as st
import pandas as pd
import time
import math
import hashlib
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

# ⚡ HEARTBEAT
count = st_autorefresh(interval=5000, key="system_pulse")

# --- DATABASE ENGINE ---
def get_db_connection():
    try:
        if "gcp_service_account" not in st.secrets: return None
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        client = gspread.authorize(creds)
        return client
    except: return None

# WORKER FUNCTIONS
def get_worker_status(pin):
    client = get_db_connection()
    if not client: return None, None
    try:
        sheet = client.open("ec_database").worksheet("workers")
        records = sheet.get_all_records()
        for i, row in enumerate(records):
            if str(row.get('pin')) == str(pin):
                return row, i + 2
        return None, None
    except: return None, None

def update_status_tab(pin, status, start_time, earnings):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("workers")
            try:
                cell = sheet.find(str(pin))
                row = cell.row
                sheet.update_cell(row, 2, status)
                sheet.update_cell(row, 3, start_time)
                sheet.update_cell(row, 4, earnings)
                sheet.update_cell(row, 5, str(datetime.now()))
            except:
                sheet.append_row([str(pin), status, start_time, earnings, str(datetime.now())])
        except: pass

def log_to_ledger(pin, action, earnings, gps_msg):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("history")
            sheet.append_row([str(pin), action, str(datetime.now()), f"${earnings:.2f}", gps_msg])
        except: pass

# CFO FUNCTIONS
def get_all_active_workers():
    client = get_db_connection()
    if not client: return []
    try:
        sheet = client.open("ec_database").worksheet("workers")
        data = sheet.get_all_records()
        # Filter for ONLY Active workers
        active = [d for d in data if d.get('status') == 'Active']
        return active
    except: return []

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
    st.session_state.user_state = {'active': False, 'start_time': None, 'earnings': 0.0}

USERS = {
    "1001": {"name": "Liam O'Neil", "role": "RT", "rate": 85.00},
    "9999": {"name": "CFO VIEW", "role": "Exec", "rate": 0.00}
}

# --- LOGIN ---
if 'logged_in_user' not in st.session_state:
    st.title("🛡️ EC Enterprise")
    st.caption("v50.0 | The Watchtower")
    
    pin = st.text_input("ENTER PIN", type="password")
    if st.button("AUTHENTICATE"):
        if pin in USERS:
            st.session_state.logged_in_user = USERS[pin]
            st.session_state.pin = pin
            
            # Sync Logic (Worker Only)
            if USERS[pin]['role'] != "Exec":
                row_data, _ = get_worker_status(pin)
                if row_data:
                    st.session_state.user_state['active'] = (row_data['status'] == 'Active')
                    st.session_state.user_state['start_time'] = float(row_data['start_time']) if row_data['start_time'] else 0.0
                    st.session_state.user_state['earnings'] = float(row_data['earnings']) if row_data['earnings'] else 0.0
            st.rerun()
        else:
            st.error("INVALID PIN")
    st.stop()

# --- ROUTING ---
user = st.session_state.logged_in_user
pin = st.session_state.pin

# ==================================================
# 🏛️ VIEW A: THE CFO WATCHTOWER (PIN 9999)
# ==================================================
if user['role'] == "Exec":
    st.title("🛡️ COMMAND CENTER")
    st.caption("Live Protocol Oversight")
    
    # 1. FETCH LIVE DATA
    active_workers = get_all_active_workers()
    
    # Calculate Real-Time Liability
    total_liability = 0.0
    active_count = len(active_workers)
    
    for w in active_workers:
        # Calculate their current earnings (Saved + Session)
        try:
            start = float(w['start_time'])
            saved = float(w['earnings'])
            # Since they are active, add current session time
            current_session = ((time.time() - start) / 3600) * 85.00 # Assuming base rate for now
            total_liability += (saved + current_session)
        except: pass

    # 2. METRICS
    c1, c2, c3 = st.columns(3)
    c1.metric("ACTIVE STAFF", f"{active_count}", delta="Live")
    c2.metric("CURRENT LIABILITY", f"${total_liability:,.2f}", delta="Pending Payout")
    c3.metric("PROTOCOL STATUS", "ONLINE", delta="Stable", delta_color="normal")
    
    # 3. LIVE MAP
    st.markdown("### 📍 LIVE ASSET MAP")
    if active_count > 0:
        # In a real app, we'd pull their lat/lon. For now, we plot them at hospital
        map_data = pd.DataFrame({
            'lat': [HOSPITAL_LAT],
            'lon': [HOSPITAL_LON]
        })
        st.map(map_data, zoom=15)
        st.dataframe(pd.DataFrame(active_workers))
    else:
        st.info("No Active Personnel on Site.")
        st.map(pd.DataFrame({'lat': [HOSPITAL_LAT], 'lon': [HOSPITAL_LON]}), zoom=15)

    if st.button("LOGOUT"):
        st.session_state.clear()
        st.rerun()

# ==================================================
# 👤 VIEW B: THE WORKER FIELD UNIT (PIN 1001)
# ==================================================
else:
    st.title(f"👤 {user['name']}")

    # GPS
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

    # Money Ticker
    current_earnings = st.session_state.user_state['earnings']
    if st.session_state.user_state['active']:
        elapsed = (time.time() - st.session_state.user_state['start_time']) / 3600
        current_earnings += elapsed * user['rate']

    net_pay = calculate_taxes(current_earnings)
    c1, c2 = st.columns(2)
    c1.metric("GROSS", f"${current_earnings:,.2f}")
    c2.metric("NET", f"${net_pay:,.2f}")

    # Actions
    if not st.session_state.user_state['active']:
        if st.button("🟢 CLOCK IN"):
            if is_inside:
                st.session_state.user_state['active'] = True
                st.session_state.user_state['start_time'] = time.time()
                update_status_tab(pin, "Active", time.time(), current_earnings)
                log_to_ledger(pin, "CLOCK IN", current_earnings, dist_msg)
                st.success("STARTED")
                st.rerun()
            else:
                st.error("Outside Zone")
    else:
        if st.button("🔴 CLOCK OUT"):
            st.session_state.user_state['active'] = False
            st.session_state.user_state['earnings'] = current_earnings
            update_status_tab(pin, "Inactive", 0, current_earnings)
            log_to_ledger(pin, "CLOCK OUT", current_earnings, dist_msg)
            st.success("ENDED & LOGGED")
            st.rerun()
            
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
