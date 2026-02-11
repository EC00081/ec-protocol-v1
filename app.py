import streamlit as st
import pandas as pd
import time
import math
import hashlib
import random
from datetime import datetime
from streamlit_js_eval import get_geolocation

st.set_page_config(page_title="EC Enterprise", page_icon="🛡️")

# --- 1. TAX CONFIGURATION (2026 MA/FED) ---
TAX_RATES = {
    "FED": 0.22,   # Federal Supplemental Rate
    "MA": 0.05,    # Massachusetts Flat Tax
    "SS": 0.062,   # Social Security
    "MED": 0.0145  # Medicare
}

# --- 2. SECURITY & DATA ---
USERS = {
    "1001": {"name": "Liam O'Neil", "role": "Respiratory Therapist", "rate": 85.00}
}
HOSPITAL_LAT = 42.0806
HOSPITAL_LON = -71.0264
GEOFENCE_RADIUS = 300 

if 'ledger' not in st.session_state: st.session_state.ledger = []
if 'user_state' not in st.session_state: 
    st.session_state.user_state = {'active': False, 'start_time': None, 'earnings': 0.0}

# --- 3. HELPER FUNCTIONS ---
def get_distance(lat1, lon1, lat2, lon2):
    R = 6371000 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return c * R

def calculate_taxes(gross_amount):
    fed = gross_amount * TAX_RATES["FED"]
    ma = gross_amount * TAX_RATES["MA"]
    ss = gross_amount * TAX_RATES["SS"]
    med = gross_amount * TAX_RATES["MED"]
    total_tax = fed + ma + ss + med
    net = gross_amount - total_tax
    return net, fed, ma, ss, med

def log_transaction(user, action):
    enc_id = f"0x{hashlib.sha256(user.encode()).hexdigest()[:8]}..."
    timestamp = datetime.now().strftime("%H:%M")
    st.session_state.ledger.append(f"[{timestamp}] TX: {enc_id} | {action}")

# --- 4. LOGIN SCREEN ---
if 'logged_in_user' not in st.session_state:
    st.title("🛡️ EC Enterprise")
    st.caption("Secure Tax-Compliant Portal")
    pin = st.text_input("ENTER PIN", type="password")
    if st.button("AUTHENTICATE"):
        if pin in USERS:
            st.session_state.logged_in_user = USERS[pin]
            st.rerun()
        else:
            st.error("INVALID ACCESS")
    st.stop()

# --- 5. MAIN DASHBOARD ---
user = st.session_state.logged_in_user
st.title(f"👤 {user['name']}")
st.caption(f"Role: {user['role']} | Rate: ${user['rate']}/hr")

# --- REAL-TIME INCOME CALCULATOR ---
gross_pay = st.session_state.user_state['earnings']

# Add active time if clock is running
if st.session_state.user_state['active']:
    elapsed_hours = (time.time() - st.session_state.user_state['start_time']) / 3600
    current_session = elapsed_hours * user['rate']
    gross_pay += current_session

# CALCULATE TAXES
net_pay, fed, ma, ss, med = calculate_taxes(gross_pay)

# DISPLAY CARDS
col1, col2 = st.columns(2)
col1.metric("GROSS EARNINGS", f"${gross_pay:,.2f}", delta="Pre-Tax")
col2.metric("NET PAY (DEPOSIT)", f"${net_pay:,.2f}", delta="-34.65% Tax", delta_color="inverse")

# TAX BREAKDOWN DROPDOWN
with st.expander("SEE TAX BREAKDOWN (2026 ESTIMATE)"):
    t1, t2 = st.columns(2)
    t1.write(f"🇺🇸 **Federal (22%):** -${fed:.2f}")
    t1.write(f"🏛️ **MA State (5%):** -${ma:.2f}")
    t2.write(f"👴 **FICA (6.2%):** -${ss:.2f}")
    t2.write(f"🏥 **Medicare (1.45%):** -${med:.2f}")

st.markdown("---")

# --- GPS SENTINEL ---
st.markdown("### 📡 SATELLITE LINK")
loc = get_geolocation()
is_inside = False

# DEV OVERRIDE (Hidden in Sidebar)
with st.sidebar:
    st.header("DEV TOOLS")
    dev_override = st.checkbox("FORCE GPS: INSIDE (Simulate)")

if loc:
    dist = get_distance(loc['coords']['latitude'], loc['coords']['longitude'], HOSPITAL_LAT, HOSPITAL_LON)
    is_inside = dist < GEOFENCE_RADIUS
    
    if dev_override:
        is_inside = True
        st.warning("⚠️ DEV OVERRIDE ACTIVE")
    
    if is_inside:
        st.success(f"✅ VERIFIED: INSIDE GEOFENCE ({int(dist)}m)")
        
        # ACTIVE BUTTONS
        if not st.session_state.user_state['active']:
            if st.button("🟢 CLOCK IN"):
                st.session_state.user_state['active'] = True
                st.session_state.user_state['start_time'] = time.time()
                log_transaction(user['name'], "CLOCK IN")
                st.rerun()
        else:
            if st.button("🔴 CLOCK OUT & SETTLE"):
                st.session_state.user_state['earnings'] = gross_pay # Lock it in
                st.session_state.user_state['active'] = False
                log_transaction(user['name'], "CLOCK OUT")
                st.rerun()
    else:
        st.error(f"🚫 BLOCKED: OUTSIDE GEOFENCE ({int(dist)}m)")
        if st.session_state.user_state['active']:
            st.warning("⚠️ You left the zone! Please clock out.")
else:
    st.info("Waiting for GPS signal...")

# --- LEDGER ---
st.markdown("---")
st.caption("ENCRYPTED TRANSACTION LOG")
for l in reversed(st.session_state.ledger[-5:]):
    st.code(l)
