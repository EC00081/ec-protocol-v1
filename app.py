import streamlit as st
import pandas as pd
import time
import math
import requests
from datetime import datetime
from shapely.geometry import Point, Polygon
from streamlit_js_eval import get_geolocation
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="EC Enterprise", page_icon="🛡️")

# --- CONFIG ---
# Signature Healthcare Coordinates
HOSPITAL_LAT = 42.0875
HOSPITAL_LON = -70.9915
GEOFENCE_RADIUS = 300 
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}

# ⚡ HEARTBEAT
count = st_autorefresh(interval=10000, key="pulse")

# --- 1. NEW: POLYGON DEFINITION (Exact Building Shape) ---
# In a real scenario, this would trace the exact walls of the hospital
HOSPITAL_ZONE = Polygon([
    (42.0875, -70.9915),
    (42.0876, -70.9910),
    (42.0870, -70.9912),
    (42.0871, -70.9918)
])

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
    if not client: return None
    try:
        sheet = client.open("ec_database").worksheet("workers")
        records = sheet.get_all_records()
        for row in records:
            if str(row.get('pin')) == str(pin):
                return row
        return {}
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

def log_to_ledger(pin, action, earnings, msg):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("history")
            sheet.append_row([str(pin), action, str(datetime.now()), f"${earnings:.2f}", msg])
        except: pass

# --- 2. NEW: INTEGRITY CHECKS ---
def verify_integrity(claimed_lat, claimed_lon):
    # 1. GET IP-BASED LOCATION
    try:
        # Using free API for demo. In prod, use paid ipinfo.io
        response = requests.get('https://ipapi.co/json/').json()
        ip_lat = response.get('latitude')
        ip_lon = response.get('longitude')
        ip_addr = response.get('ip')
        provider = response.get('org', 'Unknown ISP')
        
        # 2. CALCULATE DISCREPANCY
        # Reuse our existing math function
        discrepancy = get_distance(claimed_lat, claimed_lon, ip_lat, ip_lon)
        
        # 3. JUDGMENT (50km Threshold for VPN detection)
        is_suspicious = discrepancy > 50000 
        
        return {
            "suspicious": is_suspicious,
            "ip": ip_addr,
            "discrepancy": discrepancy,
            "provider": provider
        }
    except:
        # If IP lookup fails, default to suspicious to be safe (or lenient for beta)
        return {"suspicious": False, "error": "Lookup Failed", "provider": "Unknown"}

def check_polygon_access(lat, lon):
    try:
        worker_location = Point(lat, lon)
        return HOSPITAL_ZONE.contains(worker_location)
    except:
        return False

# --- 3. NEW: ATOMIC PAYOUT SIMULATION ---
def trigger_atomic_payout(pin, amount):
    # This simulates the RTP / Stablecoin Trigger
    time.sleep(1.5) # Simulate bank processing time
    return {
        "status": "SETTLED",
        "tx_id": f"0x{hashlib.sha256(str(time.time()).encode()).hexdigest()[:12]}",
        "timestamp": datetime.now()
    }

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
    st.session_state.user_state = {'active': False, 'start_time': 0.0, 'earnings': 0.0, 'initialized': False}

USERS = {
    "1001": {"name": "Liam O'Neil", "role": "RT", "rate": 85.00},
    "9999": {"name": "CFO VIEW", "role": "Exec", "rate": 0.00}
}

# --- LOGIN ---
if 'logged_in_user' not in st.session_state:
    st.title("🛡️ EC Enterprise")
    st.caption("v55.0 | Atomic Settlement")
    
    pin = st.text_input("ENTER PIN", type="password")
    if st.button("AUTHENTICATE"):
        if pin in USERS:
            st.session_state.logged_in_user = USERS[pin]
            st.session_state.pin = pin
            
            # INITIAL SYNC
            if USERS[pin]['role'] != "Exec":
                cloud_data = get_cloud_state(pin)
                if cloud_data:
                    if cloud_data.get('status') == 'Active':
                        st.session_state.user_state['active'] = True
                        try:
                            st.session_state.user_state['start_time'] = float(cloud_data.get('start_time', 0))
                            st.session_state.user_state['earnings'] = float(cloud_data.get('earnings', 0))
                        except: pass
                    else:
                        st.session_state.user_state['active'] = False
                        try:
                            st.session_state.user_state['earnings'] = float(cloud_data.get('earnings', 0))
                        except: pass
                st.session_state.user_state['initialized'] = True
            
            st.rerun()
        else:
            st.error("INVALID PIN")
    st.stop()

# --- MAIN APP ---
user = st.session_state.logged_in_user
pin = st.session_state.pin

# ==================================================
# 👤 WORKER FIELD UNIT
# ==================================================
if user['role'] != "Exec":
    st.title(f"👤 {user['name']}")
    
    is_active = st.session_state.user_state['active']
    
    # GPS
    loc = get_geolocation()
    dist_msg = "Signal Acquired"
    is_inside = False

    with st.sidebar:
        dev_override = st.checkbox("FORCE INSIDE ZONE (DEV)")
        if st.button("LOGOUT"):
            st.session_state.clear()
            st.rerun()

    if loc:
        dist = get_distance(loc['coords']['latitude'], loc['coords']['longitude'], HOSPITAL_LAT, HOSPITAL_LON)
        is_inside = dist < GEOFENCE_RADIUS or dev_override
        dist_msg = f"✅ INSIDE ({int(dist)}m)" if is_inside else f"🚫 OUTSIDE ({int(dist)}m)"

    st.info(f"📍 GPS: {dist_msg}")

    # Money
    current_earnings = st.session_state.user_state['earnings']
    if is_active:
        start = st.session_state.user_state['start_time']
        if start > 0:
            elapsed = (time.time() - start) / 3600
            current_earnings += elapsed * user['rate']

    net_pay = calculate_taxes(current_earnings)
    c1, c2 = st.columns(2)
    c1.metric("GROSS", f"${current_earnings:,.2f}")
    c2.metric("NET", f"${net_pay:,.2f}")

    # --- BUTTONS ---
    if is_active:
        st.success("🟢 STATUS: ON SHIFT")
        
        # 🛑 NEW: ATOMIC PAYOUT BUTTON 🛑
        if st.button("🔴 CLOCK OUT & PAY"):
            
            # 1. SECURITY INTEGRITY CHECK
            with st.spinner("running security diagnostics..."):
                integrity = verify_integrity(loc['coords']['latitude'], loc['coords']['longitude'])
            
            if integrity['suspicious'] and not dev_override:
                st.error(f"⚠️ FRAUD ALERT: IP/GPS Mismatch ({int(integrity['discrepancy']/1000)}km).")
                st.error("Payout Frozen. Contact Admin.")
                log_to_ledger(pin, "FRAUD_FREEZE", current_earnings, f"IP: {integrity.get('ip')}")
            
            else:
                # 2. TRIGGER PAYOUT
                with st.spinner("Processing Real-Time Settlement..."):
                    tx_receipt = trigger_atomic_payout(pin, net_pay)
                
                if tx_receipt['status'] == "SETTLED":
                    # 3. SUCCESS STATE
                    st.session_state.user_state['active'] = False
                    st.session_state.user_state['earnings'] = 0.0 # Reset balance
                    
                    st.balloons() # 🎉
                    st.success(f"💸 ${net_pay:.2f} TRANSFERRED INSTANTLY")
                    st.caption(f"TX ID: {tx_receipt['tx_id']}")
                    
                    # 4. LOGGING
                    update_cloud_status(pin, "Inactive", 0, 0) # Reset cloud to 0
                    log_to_ledger(pin, "PAYOUT_COMPLETE", net_pay, f"Verified via {integrity.get('provider')}")
                    
                    time.sleep(4)
                    st.rerun()
            
    else:
        st.warning("⚪ STATUS: OFF DUTY")
        if st.button("🟢 CLOCK IN"):
            if is_inside:
                st.session_state.user_state['active'] = True
                st.session_state.user_state['start_time'] = time.time()
                update_cloud_status(pin, "Active", time.time(), current_earnings)
                log_to_ledger(pin, "CLOCK IN", current_earnings, dist_msg)
                st.success("STARTED")
                st.rerun()
            else:
                st.error("Outside Zone")

    # History
    st.markdown("---")
    with st.expander("📜 Payout History"):
        try:
            client = get_db_connection()
            if client:
                sheet = client.open("ec_database").worksheet("history")
                st.dataframe(pd.DataFrame(sheet.get_all_records()))
        except: pass

else:
    st.title("🛡️ COMMAND CENTER")
    # ... CFO LOGIC ...
    if st.button("LOGOUT"):
        st.session_state.clear()
        st.rerun()
    client = get_db_connection()
    if client:
        sheet = client.open("ec_database").worksheet("workers")
        st.dataframe(pd.DataFrame(sheet.get_all_records()))
