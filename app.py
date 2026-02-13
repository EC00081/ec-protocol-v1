import streamlit as st
import pandas as pd
import time
import math
import hashlib
import requests
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
GRACE_PERIOD_SECONDS = 900  # 15 Minutes
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}

# ⚡ HEARTBEAT
count = st_autorefresh(interval=10000, key="pulse")

# --- DATABASE ENGINE ---
def get_db_connection():
    try:
        if "gcp_service_account" not in st.secrets: return None
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        client = gspread.authorize(creds)
        return client
    except: return None

def get_cloud_state(pin):
    client = get_db_connection()
    if not client: return {}
    try:
        sheet = client.open("ec_database").worksheet("workers")
        records = sheet.get_all_records()
        for row in records:
            if str(row.get('pin')) == str(pin):
                return row
        return {}
    except: return {}

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

def log_to_ledger(pin, action, earnings, msg):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("history")
            sheet.append_row([str(pin), action, str(datetime.now()), f"${earnings:.2f}", msg])
        except: pass

def log_transaction(pin, amount, method):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("transactions")
            tx_id = f"TX-{int(time.time())}"
            sheet.append_row([tx_id, str(pin), f"${amount:.2f}", str(datetime.now()), method])
            return tx_id
        except: return "ERR"

# --- NETWORK & MATH ---
def get_current_ip():
    try:
        return requests.get('https://api.ipify.org').text
    except:
        return "Unknown"

def get_distance(lat1, lon1, lat2, lon2):
    try:
        R = 6371000 
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return c * R
    except: return 0

def calculate_taxes(gross):
    return gross * (1 - sum(TAX_RATES.values()))

# --- CALLBACKS (THE BUG FIX) ---
# Executed INSTANTLY when button is clicked

def cb_clock_in():
    pin = st.session_state.pin
    
    # LOCK LOCAL STATE INSTANTLY
    st.session_state.user_state['active'] = True
    st.session_state.user_state['start_time'] = time.time()
    st.session_state.user_state['last_seen_inside'] = time.time()
    
    # Capture "Home Base" IP
    current_ip = get_current_ip()
    st.session_state.user_state['clock_in_ip'] = current_ip
    
    # Update Cloud
    update_cloud_status(pin, "Active", time.time(), st.session_state.user_state['earnings'])
    log_to_ledger(pin, "CLOCK IN", st.session_state.user_state['earnings'], f"IP: {current_ip}")

def cb_clock_out():
    pin = st.session_state.pin
    earnings = st.session_state.user_state['earnings']
    
    # LOCK LOCAL STATE INSTANTLY
    st.session_state.user_state['active'] = False
    
    # Update Cloud
    update_cloud_status(pin, "Inactive", 0, earnings)
    log_to_ledger(pin, "CLOCK OUT", earnings, "User Action")

def cb_payout():
    pin = st.session_state.pin
    amount = calculate_taxes(st.session_state.user_state['earnings'])
    
    log_transaction(pin, amount, "Instant_Rail")
    update_cloud_status(pin, "Inactive", 0, 0)
    log_to_ledger(pin, "PAYOUT", amount, "Settled")
    
    st.session_state.user_state['earnings'] = 0.0
    st.session_state.user_state['payout_success'] = True

# --- STATE INIT ---
if 'user_state' not in st.session_state: 
    st.session_state.user_state = {
        'active': False, 
        'start_time': 0.0, 
        'earnings': 0.0, 
        'last_seen_inside': time.time(),
        'clock_in_ip': None,
        'payout_success': False
    }

USERS = {
    "1001": {"name": "Liam O'Neil", "role": "RT", "rate": 85.00},
    "9999": {"name": "CFO VIEW", "role": "Exec", "rate": 0.00}
}

# --- LOGIN ---
if 'logged_in_user' not in st.session_state:
    st.title("🛡️ EC Enterprise")
    st.caption("v58.0 | Hybrid Sentinel (GPS + IP)")
    
    pin = st.text_input("ENTER PIN", type="password")
    if st.button("AUTHENTICATE"):
        if pin in USERS:
            st.session_state.logged_in_user = USERS[pin]
            st.session_state.pin = pin
            
            if USERS[pin]['role'] != "Exec":
                with st.spinner("Syncing Cloud State..."):
                    cloud = get_cloud_state(pin)
                    if cloud.get('status') == 'Active':
                        st.session_state.user_state['active'] = True
                        try:
                            st.session_state.user_state['start_time'] = float(cloud.get('start_time', 0))
                            st.session_state.user_state['earnings'] = float(cloud.get('earnings', 0))
                            st.session_state.user_state['last_seen_inside'] = time.time()
                        except: pass
                    else:
                        st.session_state.user_state['active'] = False
                        try: st.session_state.user_state['earnings'] = float(cloud.get('earnings', 0))
                        except: pass
            
            st.rerun()
        else:
            st.error("INVALID PIN")
    st.stop()

# --- MAIN APP ---
user = st.session_state.logged_in_user
pin = st.session_state.pin

if user['role'] != "Exec":
    st.title(f"👤 {user['name']}")
    
    # 1. HYBRID LOCATION LOGIC
    loc = get_geolocation()
    current_ip = get_current_ip()
    
    # Logic flags
    gps_inside = False
    ip_match = False
    status_msg = "Checking Signals..."
    
    # A. GPS CHECK
    with st.sidebar:
        dev_override = st.checkbox("FORCE GPS SIGNAL")
        if st.button("LOGOUT"):
            st.session_state.clear()
            st.rerun()

    if loc:
        dist = get_distance(loc['coords']['latitude'], loc['coords']['longitude'], HOSPITAL_LAT, HOSPITAL_LON)
        gps_inside = dist < GEOFENCE_RADIUS or dev_override
    
    # B. IP CHECK (The "Lifeline")
    # If the current IP matches the IP we used to Clock In, we assume we are still on the same Wifi
    if st.session_state.user_state.get('clock_in_ip') == current_ip:
        ip_match = True

    # C. FINAL JUDGMENT
    if gps_inside:
        status_msg = "✅ GPS VERIFIED (Optimal)"
        st.session_state.user_state['last_seen_inside'] = time.time() # Reset Timer
    elif ip_match and st.session_state.user_state['active']:
        # MRI MODE: GPS Failed, but IP is same. SAFE.
        status_msg = "⚠️ GPS LOST - IP MATCH (SAFE MODE)"
        st.session_state.user_state['last_seen_inside'] = time.time() # Reset Timer
    else:
        # DANGER ZONE
        time_gone = time.time() - st.session_state.user_state['last_seen_inside']
        if st.session_state.user_state['active']:
            if time_gone < GRACE_PERIOD_SECONDS:
                mins = int((GRACE_PERIOD_SECONDS - time_gone) / 60)
                status_msg = f"⏳ SIGNAL LOST - GRACE PERIOD ({mins}m Left)"
            else:
                status_msg = "❌ SIGNAL LOST - AUTO CLOCK OUT"
                cb_clock_out()
                st.rerun()
        else:
            status_msg = "🚫 OUTSIDE ZONE"

    # Display Status
    if "SAFE" in status_msg or "VERIFIED" in status_msg:
        st.success(f"📍 {status_msg}")
    elif "GRACE" in status_msg:
        st.warning(f"📍 {status_msg}")
    else:
        st.error(f"📍 {status_msg}")
        
    st.caption(f"Current IP: {current_ip}")

    # 2. EARNINGS
    is_active = st.session_state.user_state['active']
    current_earnings = st.session_state.user_state['earnings']
    if is_active:
        start = st.session_state.user_state['start_time']
        if start > 0:
            elapsed = (time.time() - start) / 3600
            current_earnings += elapsed * user['rate']
    
    net_pay = calculate_taxes(current_earnings)

    # 3. CONTROLS
    st.markdown("### ⏱️ Controls")
    c1, c2 = st.columns(2)
    c1.metric("GROSS", f"${current_earnings:,.2f}")
    c2.metric("NET", f"${net_pay:,.2f}")

    if is_active:
        st.button("🔴 CLOCK OUT", on_click=cb_clock_out)
    else:
        if gps_inside:
            st.button("🟢 CLOCK IN", on_click=cb_clock_in)
        else:
            st.error("Must be on-site to start.")

    # 4. WALLET
    st.markdown("---")
    if not is_active and net_pay > 0.01:
        st.info(f"💰 AVAILABLE: **${net_pay:,.2f}**")
        st.button("💸 PAYOUT", on_click=cb_payout)
    
    if st.session_state.user_state['payout_success']:
        st.balloons()
        st.success("FUNDS TRANSFERRED")
        st.session_state.user_state['payout_success'] = False

    # 5. LOGS
    with st.expander("Show Logs"):
        try:
            client = get_db_connection()
            if client:
                sheet = client.open("ec_database").worksheet("history")
                st.dataframe(pd.DataFrame(sheet.get_all_records()))
        except: st.write("No logs")

else:
    st.title("🛡️ COMMAND CENTER")
    # CFO Logic...
