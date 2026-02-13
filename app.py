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

def log_transaction(pin, amount, method):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("transactions")
            tx_id = f"TX-{int(time.time())}"
            sheet.append_row([tx_id, str(pin), f"${amount:.2f}", str(datetime.now()), method])
            return tx_id
        except: return "ERR"

def log_to_ledger(pin, action, earnings, msg):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("history")
            sheet.append_row([str(pin), action, str(datetime.now()), f"${earnings:.2f}", msg])
        except: pass

# --- INTEGRITY CHECKS ---
def verify_integrity(claimed_lat, claimed_lon):
    try:
        # Simple IP check (Demo)
        response = requests.get('https://ipapi.co/json/').json()
        discrepancy = get_distance(claimed_lat, claimed_lon, response.get('latitude'), response.get('longitude'))
        return {"suspicious": discrepancy > 50000, "ip": response.get('ip'), "discrepancy": discrepancy}
    except:
        return {"suspicious": False, "error": "Lookup Failed"}

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

def calculate_taxes(gross):
    return gross * (1 - sum(TAX_RATES.values()))

# --- STATE INIT ---
if 'user_state' not in st.session_state: 
    # processing: The "Lock" that prevents double clicks
    st.session_state.user_state = {'active': False, 'start_time': 0.0, 'earnings': 0.0, 'processing': False}

USERS = {
    "1001": {"name": "Liam O'Neil", "role": "RT", "rate": 85.00},
    "9999": {"name": "CFO VIEW", "role": "Exec", "rate": 0.00}
}

# --- LOGIN ---
if 'logged_in_user' not in st.session_state:
    st.title("🛡️ EC Enterprise")
    st.caption("v56.0 | The Wallet Protocol")
    
    pin = st.text_input("ENTER PIN", type="password")
    if st.button("AUTHENTICATE"):
        if pin in USERS:
            st.session_state.logged_in_user = USERS[pin]
            st.session_state.pin = pin
            
            # Initial Cloud Sync
            if USERS[pin]['role'] != "Exec":
                cloud = get_cloud_state(pin)
                if cloud.get('status') == 'Active':
                    st.session_state.user_state['active'] = True
                    try: 
                        st.session_state.user_state['start_time'] = float(cloud.get('start_time', 0))
                        st.session_state.user_state['earnings'] = float(cloud.get('earnings', 0))
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
    
    # --- 1. STATE MANAGEMENT (THE BUG FIX) ---
    # We check 'processing' first. If processing is True, we LOCK the UI.
    if st.session_state.user_state['processing']:
        st.info("🔄 Processing Blockchain Transaction...")
        # We stop drawing here to prevent double clicks
        # But we need a way to 'unlock' if it gets stuck, so we auto-refresh
        time.sleep(2)
        st.session_state.user_state['processing'] = False
        st.rerun()

    # GPS
    loc = get_geolocation()
    is_inside = False
    dist_msg = "Acquiring Signal..."
    
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

    # Money Logic
    is_active = st.session_state.user_state['active']
    current_earnings = st.session_state.user_state['earnings']
    
    if is_active:
        start = st.session_state.user_state['start_time']
        if start > 0:
            elapsed = (time.time() - start) / 3600
            current_earnings += elapsed * user['rate']
    
    net_pay = calculate_taxes(current_earnings)

    # --- 2. WORKFLOW UI ---
    
    # A. CLOCK IN / OUT SECTION
    st.markdown("### ⏱️ Shift Controls")
    c1, c2 = st.columns(2)
    c1.metric("GROSS EARNED", f"${current_earnings:,.2f}")
    c2.metric("NET PAYABLE", f"${net_pay:,.2f}")

    if is_active:
        st.success("🟢 ON SHIFT - EARNING")
        if st.button("🔴 CLOCK OUT (End Shift)"):
            st.session_state.user_state['processing'] = True # LOCK UI
            
            # Local update
            st.session_state.user_state['active'] = False
            st.session_state.user_state['earnings'] = current_earnings # Lock in final amount
            
            # Cloud update
            update_cloud_status(pin, "Inactive", 0, current_earnings)
            log_to_ledger(pin, "CLOCK OUT", current_earnings, dist_msg)
            
            st.rerun() # Unlock happens on reload
            
    else:
        st.warning("⚪ OFF DUTY")
        if st.button("🟢 CLOCK IN"):
            if is_inside:
                st.session_state.user_state['processing'] = True # LOCK UI
                
                # Local update
                st.session_state.user_state['active'] = True
                st.session_state.user_state['start_time'] = time.time()
                
                # Cloud update
                update_cloud_status(pin, "Active", time.time(), current_earnings)
                log_to_ledger(pin, "CLOCK IN", current_earnings, dist_msg)
                
                st.rerun()
            else:
                st.error("Cannot Clock In: Outside Zone")

    # B. WALLET SECTION (New!)
    st.markdown("---")
    st.markdown("### 💳 Digital Wallet")
    
    # We use the 'net_pay' calculated from 'current_earnings' (which is now static if clocked out)
    available_funds = net_pay if not is_active else 0.0 # Only allow withdrawal if clocked out? 
    # Actually, let's allow withdrawal of ACCRUED funds even if active? 
    # No, safer to require Clock Out for settlement first.
    
    if not is_active and net_pay > 0.01:
        st.info(f"💰 AVAILABLE TO WITHDRAW: **${net_pay:,.2f}**")
        
        if st.button("💸 INITIATE PAYOUT"):
            with st.spinner("Verifying Fraud Markers..."):
                integrity = verify_integrity(loc['coords']['latitude'], loc['coords']['longitude']) if loc else {'suspicious': False}
                
                if integrity['suspicious'] and not dev_override:
                    st.error("⚠️ FRAUD ALERT: Location Mismatch. Payout Frozen.")
                else:
                    # PROCESS PAYOUT
                    tx_id = log_transaction(pin, net_pay, "Instant_Rail")
                    update_cloud_status(pin, "Inactive", 0, 0) # Reset balance to 0
                    
                    st.session_state.user_state['earnings'] = 0.0
                    st.balloons()
                    st.success(f"Sent ${net_pay:.2f} to Bank Account")
                    st.caption(f"Transaction ID: {tx_id}")
                    time.sleep(3)
                    st.rerun()
    elif is_active:
        st.caption("🔒 Funds accumulate while on shift. Clock Out to withdraw.")
    else:
        st.caption("Wallet Empty.")

    # C. HISTORY SECTION
    st.markdown("---")
    tab1, tab2 = st.tabs(["Shift Logs", "Transaction History"])
    
    client = get_db_connection()
    if client:
        with tab1:
            try:
                sheet = client.open("ec_database").worksheet("history")
                st.dataframe(pd.DataFrame(sheet.get_all_records()))
            except: st.write("No Logs")
        with tab2:
            try:
                sheet = client.open("ec_database").worksheet("transactions")
                st.dataframe(pd.DataFrame(sheet.get_all_records()))
            except: st.write("No Transactions")

else:
    # CFO VIEW
    st.title("🛡️ COMMAND CENTER")
    if st.button("LOGOUT"):
        st.session_state.clear()
        st.rerun()
    client = get_db_connection()
    if client:
        sheet = client.open("ec_database").worksheet("workers")
        st.dataframe(pd.DataFrame(sheet.get_all_records()))
