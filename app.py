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
        'debug_log': []
    }

# --- BACKEND FUNCTIONS ---
def get_cloud_state(pin):
    client = get_db_connection()
    if not client: return {}
    try:
        sheet = client.open("ec_database").worksheet("workers")
        records = sheet.get_all_records()
        
        # AGGRESSIVE SEARCH (String Casting)
        target = str(pin).strip()
        
        for row in records:
            # We assume the PIN is in the first column or named 'pin'
            # Let's try to get 'pin' safely
            row_pin = str(row.get('pin', '')).strip()
            
            # Debug log to see what we are comparing
            # st.session_state.user_state['debug_log'].append(f"Comparing {target} vs {row_pin}")
            
            if row_pin == target:
                return row
        return {}
    except Exception as e: 
        return {}

def update_cloud_status(pin, status, start_time, earnings):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("workers")
            # Find cell by PIN string
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

# --- CALLBACKS ---
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

# --- SYNC LOGIC (The "Mirror") ---
def restore_session_from_cloud(pin):
    """
    Force the app to look like the database.
    This runs on Login and on 'Force Sync'.
    """
    cloud = get_cloud_state(pin)
    if cloud:
        status = str(cloud.get('status', '')).strip()
        
        if status == 'Active':
            st.session_state.user_state['active'] = True
            try:
                # CRITICAL: RESTORE TIME SO MONEY COUNTS CORRECTLY
                st.session_state.user_state['start_time'] = float(cloud.get('start_time', 0))
                # Restore previous earnings (if any)
                st.session_state.user_state['earnings'] = float(cloud.get('earnings', 0))
            except: 
                # Fallback if data is corrupt
                st.session_state.user_state['start_time'] = time.time()
        else:
            st.session_state.user_state['active'] = False
            try: st.session_state.user_state['earnings'] = float(cloud.get('earnings', 0))
            except: pass
            
        return True
    return False

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
    st.caption("v64.0 | The Mirror Protocol")
    
    pin = st.text_input("ENTER PIN", type="password")
    if st.button("AUTHENTICATE"):
        if pin in USERS:
            st.session_state.logged_in_user = USERS[pin]
            st.session_state.pin = pin
            
            # AUTOMATIC RESTORE
            if USERS[pin]['role'] != "Exec":
                restored = restore_session_from_cloud(pin)
                if restored:
                    st.toast("✅ Session Restored from HQ")
                else:
                    st.toast("⚠️ New Session (No Cloud Data Found)")
            
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
    
    # REAL-TIME CALCULATION
    # If active, we recalculate earnings based on NOW - START TIME
    if is_active:
        start = st.session_state.user_state['start_time']
        if start > 0:
            elapsed_hours = (time.time() - start) / 3600
            # Total = Previously Saved + Current Session
            # Note: simplified for this demo to just be Session based on start time
            current_earnings = elapsed_hours * user['rate']
            # We update session state so it displays correctly
            st.session_state.user_state['earnings'] = current_earnings
    
    net_pay = current_earnings * (1 - sum(TAX_RATES.values()))

    # Shift Controls
    st.markdown("### ⏱️ Shift Controls")
    c1, c2 = st.columns(2)
    c1.metric("GROSS", f"${current_earnings:,.2f}")
    c2.metric("NET", f"${net_pay:,.2f}")

    if is_active:
        st.success("🟢 ON SHIFT (Cloud Verified)")
        st.button("🔴 CLOCK OUT", on_click=cb_clock_out)
    else:
        st.warning("⚪ OFF DUTY")
        if is_inside:
            st.button("🟢 CLOCK IN", on_click=cb_clock_in)
        else:
            st.error("Cannot Clock In: Outside Geofence")
            
    # FORCE SYNC
    if st.button("🔄 Force Cloud Sync"):
        restore_session_from_cloud(pin)
        st.rerun()

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

    # THE TRUTH BOX (DEBUG)
    st.markdown("---")
    with st.expander("🛠️ System Diagnostics (The Truth Box)"):
        st.write("This panel shows exactly what the database sees.")
        
        # Fetch fresh raw data
        raw_cloud = get_cloud_state(pin)
        
        c1, c2 = st.columns(2)
        c1.write("**App State:**")
        c1.write(f"Active: {is_active}")
        c1.write(f"Start Time: {st.session_state.user_state['start_time']}")
        
        c2.write("**Cloud State:**")
        c2.write(f"Active: {raw_cloud.get('status', 'Not Found')}")
        c2.write(f"Start Time: {raw_cloud.get('start_time', 'N/A')}")
        
        if raw_cloud.get('status') == 'Active' and not is_active:
            st.error("MISMATCH DETECTED: Cloud says Active, App says Inactive.")
            st.write("👉 Click 'Force Cloud Sync' above to fix.")
        elif raw_cloud.get('status') != 'Active' and is_active:
             st.error("MISMATCH DETECTED: App says Active, Cloud says Inactive.")
        else:
            st.success("✅ SYNC OK: App and Cloud agree.")
            
        # History Log
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
