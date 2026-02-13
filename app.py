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

# --- CONFIGURATION (TARGET: LUNENBURG, MA) ---
HOSPITAL_LAT = 42.57381188522667
HOSPITAL_LON = -71.74726585573194
GEOFENCE_RADIUS = 300 
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

# --- STATE MANAGEMENT ---
if 'user_state' not in st.session_state: 
    st.session_state.user_state = {
        'active': False, 
        'start_time': 0.0, 
        'earnings': 0.0, 
        'locked': False,
        'payout_success': False,
        'debug_msg': "Initializing..."
    }

# --- BACKEND FUNCTIONS ---
def get_cloud_state(pin):
    client = get_db_connection()
    if not client: return {}
    try:
        sheet = client.open("ec_database").worksheet("workers")
        records = sheet.get_all_records()
        
        # AGGRESSIVE SEARCH
        # Convert search PIN to string and strip whitespace
        target_pin = str(pin).strip()
        
        for row in records:
            # Convert row PIN to string and strip whitespace
            row_pin = str(row.get('pin')).strip()
            
            if row_pin == target_pin:
                return row
        return {}
    except Exception as e: 
        st.session_state.user_state['debug_msg'] = f"Read Error: {e}"
        return {}

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

def log_transaction(pin, amount):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("transactions")
            tx_id = f"TX-{int(time.time())}"
            sheet.append_row([tx_id, str(pin), f"${amount:.2f}", str(datetime.now()), "INSTANT"])
            return tx_id
        except: return "ERR"

def log_history(pin, action, amount, note):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("history")
            sheet.append_row([str(pin), action, str(datetime.now()), f"${amount:.2f}", note])
        except: pass

# --- CALLBACKS (THE UI LOCK) ---
def cb_clock_in():
    st.session_state.user_state['active'] = True
    st.session_state.user_state['start_time'] = time.time()
    st.session_state.user_state['locked'] = True 
    
    pin = st.session_state.pin
    update_cloud_status(pin, "Active", time.time(), st.session_state.user_state['earnings'])
    log_history(pin, "CLOCK IN", st.session_state.user_state['earnings'], "User Action")

def cb_clock_out():
    st.session_state.user_state['active'] = False
    
    pin = st.session_state.pin
    earnings = st.session_state.user_state['earnings']
    update_cloud_status(pin, "Inactive", 0, earnings)
    log_history(pin, "CLOCK OUT", earnings, "User Action")

def cb_payout():
    pin = st.session_state.pin
    amount = st.session_state.user_state['earnings']
    taxed_amount = amount * (1 - sum(TAX_RATES.values()))
    
    log_transaction(pin, taxed_amount)
    update_cloud_status(pin, "Inactive", 0, 0)
    log_history(pin, "PAYOUT", taxed_amount, "Settled")
    
    st.session_state.user_state['earnings'] = 0.0
    st.session_state.user_state['payout_success'] = True

def cb_force_sync():
    # MANUAL SYNC BUTTON LOGIC
    pin = st.session_state.pin
    cloud = get_cloud_state(pin)
    if cloud:
        status = str(cloud.get('status')).strip()
        if status == 'Active':
            st.session_state.user_state['active'] = True
            try:
                st.session_state.user_state['start_time'] = float(cloud.get('start_time', 0))
                st.session_state.user_state['earnings'] = float(cloud.get('earnings', 0))
            except: pass
        else:
            st.session_state.user_state['active'] = False
            try: st.session_state.user_state['earnings'] = float(cloud.get('earnings', 0))
            except: pass
        st.toast("System Synced with HQ")

# --- MATH ---
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

USERS = {
    "1001": {"name": "Liam O'Neil", "role": "RT", "rate": 85.00},
    "9999": {"name": "CFO VIEW", "role": "Exec", "rate": 0.00}
}

# --- LOGIN SCREEN ---
if 'logged_in_user' not in st.session_state:
    st.title("🛡️ EC Enterprise")
    st.caption("v63.0 | Aggressive Sync")
    
    pin = st.text_input("ENTER PIN", type="password")
    if st.button("AUTHENTICATE"):
        if pin in USERS:
            st.session_state.logged_in_user = USERS[pin]
            st.session_state.pin = pin
            
            # AUTOMATIC INITIAL SYNC
            if USERS[pin]['role'] != "Exec":
                cb_force_sync()
            
            st.rerun()
        else:
            st.error("INVALID PIN")
    st.stop()

# --- MAIN APP ---
user = st.session_state.logged_in_user
pin = st.session_state.pin

# ==================================================
# 👤 WORKER VIEW (PIN 1001)
# ==================================================
if user['role'] != "Exec":
    st.title(f"👤 {user['name']}")
    
    # GPS Logic
    loc = get_geolocation()
    dist_msg = "Triangulating..."
    is_inside = False
    
    if loc:
        dist = get_distance(loc['coords']['latitude'], loc['coords']['longitude'], HOSPITAL_LAT, HOSPITAL_LON)
        is_inside = dist < GEOFENCE_RADIUS
        dist_msg = f"✅ INSIDE ZONE ({int(dist)}m)" if is_inside else f"🚫 OUTSIDE ZONE ({int(dist)}m)"
    
    st.info(f"📍 GPS: {dist_msg}")

    # Earnings Calculation
    is_active = st.session_state.user_state['active']
    current_earnings = st.session_state.user_state['earnings']
    
    if is_active:
        start = st.session_state.user_state['start_time']
        if start > 0:
            elapsed = (time.time() - start) / 3600
            current_earnings += elapsed * user['rate']
    
    net_pay = current_earnings * (1 - sum(TAX_RATES.values()))

    # UI: Shift Controls
    st.markdown("### ⏱️ Shift Controls")
    c1, c2 = st.columns(2)
    c1.metric("GROSS", f"${current_earnings:,.2f}")
    c2.metric("NET", f"${net_pay:,.2f}")

    if is_active:
        st.success("🟢 ON SHIFT")
        st.button("🔴 CLOCK OUT", on_click=cb_clock_out)
    else:
        st.warning("⚪ OFF DUTY")
        if is_inside:
            st.button("🟢 CLOCK IN", on_click=cb_clock_in)
        else:
            st.error("Cannot Clock In: Outside Geofence")
            
    # FORCE SYNC BUTTON (THE FIX)
    st.button("🔄 Force Cloud Sync", on_click=cb_force_sync, help="Click if status is wrong")

    # UI: Wallet
    st.markdown("---")
    st.markdown("### 💳 Digital Wallet")
    
    if not is_active and current_earnings > 0.01:
        st.info(f"💰 PENDING BALANCE: **${net_pay:,.2f}**")
        if st.button("💸 INITIATE PAYOUT", on_click=cb_payout):
            pass 
    elif is_active:
        st.caption("🔒 Funds accumulate while on shift.")
    else:
        st.caption("Wallet Empty.")

    if st.session_state.user_state.get('payout_success'):
        st.balloons()
        st.success("FUNDS TRANSFERRED")
        st.session_state.user_state['payout_success'] = False

    # UI: History & Debug
    with st.expander("📜 System Logs"):
        # DEBUG VISION
        cloud_raw = get_cloud_state(pin)
        st.write(f"**Cloud Sees:** {cloud_raw.get('status', 'Unknown')}")
        st.write(f"**App Sees:** {'Active' if is_active else 'Inactive'}")
        
        try:
            client = get_db_connection()
            if client:
                sheet = client.open("ec_database").worksheet("history")
                st.dataframe(pd.DataFrame(sheet.get_all_records()))
        except: st.write("No Logs")
        
    if st.button("LOGOUT"):
        st.session_state.clear()
        st.rerun()

# ==================================================
# 🏛️ CFO VIEW (PIN 9999)
# ==================================================
else:
    st.title("🛡️ COMMAND CENTER")
    st.caption("Executive Oversight")
    
    client = get_db_connection()
    if client:
        sheet = client.open("ec_database").worksheet("workers")
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        
        total_liability = 0.0
        active_staff = 0
        for row in data:
            if str(row.get('status')).strip() == 'Active':
                active_staff += 1
                try:
                    start = float(row.get('start_time', 0))
                    saved = float(row.get('earnings', 0))
                    current_session = ((time.time() - start) / 3600) * 85.00
                    total_liability += (saved + current_session)
                except: pass
        
        c1, c2 = st.columns(2)
        c1.metric("ACTIVE STAFF", active_staff)
        c2.metric("CURRENT LIABILITY", f"${total_liability:,.2f}")
        
        st.dataframe(df)
    
    if st.button("LOGOUT"):
        st.session_state.clear()
        st.rerun()
