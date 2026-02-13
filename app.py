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

# ⚡ HEARTBEAT
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

# --- WORKER FUNCTIONS ---
def get_worker_status_from_cloud(pin):
    client = get_db_connection()
    if not client: return None
    try:
        sheet = client.open("ec_database").worksheet("workers")
        records = sheet.get_all_records()
        for row in records:
            if str(row.get('pin')) == str(pin):
                return row # Returns the whole dictionary {status: Active, start: ...}
        return None
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

# --- CFO FUNCTIONS ---
def get_all_workers():
    client = get_db_connection()
    if not client: return []
    try:
        sheet = client.open("ec_database").worksheet("workers")
        return sheet.get_all_records()
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
    st.session_state.user_state = {'active': False, 'start_time': 0.0, 'earnings': 0.0}

USERS = {
    "1001": {"name": "Liam O'Neil", "role": "RT", "rate": 85.00},
    "9999": {"name": "CFO VIEW", "role": "Exec", "rate": 0.00}
}

# --- LOGIN SCREEN ---
if 'logged_in_user' not in st.session_state:
    st.title("🛡️ EC Enterprise")
    st.caption("v51.0 | Cloud State Restoration")
    
    pin = st.text_input("ENTER PIN", type="password")
    if st.button("AUTHENTICATE"):
        if pin in USERS:
            st.session_state.logged_in_user = USERS[pin]
            st.session_state.pin = pin
            
            # 🔴 THE FIX: CHECK CLOUD IMMEDIATELY ON LOGIN
            if USERS[pin]['role'] != "Exec":
                cloud_data = get_worker_status_from_cloud(pin)
                if cloud_data:
                    # If Cloud says Active, WE are Active.
                    if cloud_data.get('status') == 'Active':
                        st.session_state.user_state['active'] = True
                        # Parse Floats Safely
                        try:
                            st.session_state.user_state['start_time'] = float(cloud_data.get('start_time', 0))
                            st.session_state.user_state['earnings'] = float(cloud_data.get('earnings', 0))
                            st.toast("🔄 Session Restored from Cloud")
                        except:
                            st.session_state.user_state['start_time'] = time.time()
                    else:
                        st.session_state.user_state['active'] = False
                        try:
                            st.session_state.user_state['earnings'] = float(cloud_data.get('earnings', 0))
                        except: pass
            
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
    
    # 1. FETCH ALL DATA
    all_workers = get_all_workers()
    active_workers = [w for w in all_workers if w.get('status') == 'Active']
    
    # 2. CALCULATE LIABILITY
    total_liability = 0.0
    active_count = len(active_workers)
    
    for w in active_workers:
        try:
            # Get User Rate (In real app, fetch from DB. Here we assume 85.00 for demo)
            rate = 85.00 
            start = float(w.get('start_time', 0))
            saved = float(w.get('earnings', 0))
            
            if start > 0:
                current_session = ((time.time() - start) / 3600) * rate
                total_liability += (saved + current_session)
        except: pass

    # 3. METRICS
    c1, c2, c3 = st.columns(3)
    c1.metric("ACTIVE STAFF", f"{active_count}")
    c2.metric("CURRENT LIABILITY", f"${total_liability:,.2f}")
    c3.metric("SYSTEM", "ONLINE", delta_color="normal")
    
    # 4. MAP & ROSTER
    st.markdown("### 📍 LIVE ASSET MAP")
    if active_count > 0:
        map_data = pd.DataFrame({
            'lat': [HOSPITAL_LAT],
            'lon': [HOSPITAL_LON]
        })
        st.map(map_data, zoom=15)
        st.dataframe(pd.DataFrame(active_workers))
    else:
        st.info("No Active Personnel.")

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
                update_cloud_status(pin, "Active", time.time(), current_earnings)
                log_to_ledger(pin, "CLOCK IN", current_earnings, dist_msg)
                st.success("STARTED")
                time.sleep(1); st.rerun()
            else:
                st.error("Outside Zone")
    else:
        if st.button("🔴 CLOCK OUT"):
            st.session_state.user_state['active'] = False
            st.session_state.user_state['earnings'] = current_earnings
            update_cloud_status(pin, "Inactive", 0, current_earnings)
            log_to_ledger(pin, "CLOCK OUT", current_earnings, dist_msg)
            st.success("ENDED & LOGGED")
            time.sleep(1); st.rerun()
