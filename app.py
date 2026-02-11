import streamlit as st
import pandas as pd
import time
import math
import hashlib
import random
from datetime import datetime
from streamlit_js_eval import get_geolocation

# --- CONFIG ---
st.set_page_config(page_title="EC Enterprise", page_icon="🛡️")

# CORRECTED COORDINATES (Signature Healthcare)
HOSPITAL_LAT = 42.0875
HOSPITAL_LON = -70.9915
GEOFENCE_RADIUS = 300 
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}

# --- STATE INIT ---
if 'ledger' not in st.session_state: st.session_state.ledger = []
if 'user_state' not in st.session_state: 
    st.session_state.user_state = {'active': False, 'start_time': None, 'earnings': 0.0}

# --- HELPER FUNCTIONS ---
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
    st.caption("Field Unit | v46.0 (Standalone)")
    pin = st.text_input("ENTER PIN", type="password")
    
    if st.button("AUTHENTICATE"):
        if pin in USERS:
            st.session_state.logged_in_user = USERS[pin]
            st.rerun()
        else:
            st.error("INVALID ACCESS")
    st.stop()

# --- MAIN APP ---
user = st.session_state.logged_in_user

# ==========================================
# VIEW A: THE CFO COMMAND CENTER (PIN 9999)
# ==========================================
if user['role'] == "CFO":
    st.title("🛡️ COMMAND CENTER")
    st.caption("Executive Oversight | Global View")
    
    # 1. High Level Metrics
    c1, c2, c3 = st.columns(3)
    c1.metric("ACTIVE STAFF", "14", "+2")
    c2.metric("HOURLY BURN", "$1,250.00", "Normal")
    c3.metric("LIABILITY", "$4,520.00", "+$450")
    
    # 2. Live Map
    st.markdown("### 📍 GLOBAL ASSET TRACKING")
    map_data = pd.DataFrame({
        'lat': [HOSPITAL_LAT + random.uniform(-0.002, 0.002) for _ in range(14)],
        'lon': [HOSPITAL_LON + random.uniform(-0.002, 0.002) for _ in range(14)]
    })
    st.map(map_data, zoom=14)
    
    # 3. Roster
    st.markdown("### 📋 ON-DUTY ROSTER")
    roster = pd.DataFrame([
        {"ID": "1001", "Name": "Liam O'Neil", "Role": "RT", "Status": "🟢 ACTIVE", "GPS": "VERIFIED"},
        {"ID": "1002", "Name": "Sarah Connor", "Role": "RN", "Status": "🟢 ACTIVE", "GPS": "VERIFIED"},
    ])
    st.dataframe(roster, use_container_width=True)

# ==========================================
# VIEW B: THE WORKER FIELD UNIT (PIN 1001)
# ==========================================
else:
    st.title(f"👤 {user['name']}")
    
    # Earnings Logic
    gross_pay = st.session_state.user_state['earnings']
    if st.session_state.user_state['active']:
        gross_pay += ((time.time() - st.session_state.user_state['start_time']) / 3600) * user['rate']
    net_pay = calculate_taxes(gross_pay)
    
    col1, col2 = st.columns(2)
    col1.metric("GROSS", f"${gross_pay:,.2f}")
    col2.metric("NET (EST)", f"${net_pay:,.2f}")
    
    # GPS Sentinel
    st.markdown("---")
    st.markdown("### 📡 SATELLITE LINK")
    
    # DEV OVERRIDE (For Safety)
    with st.sidebar:
        dev_override = st.checkbox("FORCE GPS (DEV)")
        if st.button("LOGOUT"):
            del st.session_state.logged_in_user
            st.rerun()

    loc = get_geolocation()
    if loc:
        dist = get_distance(loc['coords']['latitude'], loc['coords']['longitude'], HOSPITAL_LAT, HOSPITAL_LON)
        is_inside = dist < GEOFENCE_RADIUS or dev_override
        
        if is_inside:
            st.success(f"✅ VERIFIED ({int(dist)}m)")
            
            if not st.session_state.user_state['active']:
                if st.button("🟢 CLOCK IN"):
                    st.session_state.user_state['active'] = True
                    st.session_state.user_state['start_time'] = time.time()
                    st.success("CLOCKED IN")
                    time.sleep(1); st.rerun()
            else:
                if st.button("🔴 CLOCK OUT"):
                    st.session_state.user_state['active'] = False
                    st.session_state.user_state['earnings'] = gross_pay
                    st.success("SHIFT ENDED")
                    time.sleep(1); st.rerun()
        else:
            st.error(f"🚫 BLOCKED ({int(dist)}m)")
    else:
        st.info("Waiting for GPS...")
