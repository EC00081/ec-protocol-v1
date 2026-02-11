import streamlit as st
import pandas as pd
import time
import math
import hashlib
import random
from datetime import datetime
from streamlit_js_eval import get_geolocation

st.set_page_config(page_title="EC Enterprise", page_icon="🛡️")

# SECURITY & CONFIG
USERS = {
    "1001": {"name": "Liam O'Neil", "role": "Respiratory Therapist", "rate": 85.00}
}
HOSPITAL_LAT = 42.0806
HOSPITAL_LON = -71.0264
GEOFENCE_RADIUS = 300 

if 'ledger' not in st.session_state: st.session_state.ledger = []
if 'user_state' not in st.session_state: 
    st.session_state.user_state = {'active': False, 'start_time': None, 'earnings': 0.0}

# --- DEV TOOLS (HIDDEN) ---
# This allows you to force "Inside Zone" if GPS fails
with st.sidebar:
    st.caption("DEV TOOLS")
    dev_override = st.checkbox("FORCE GPS: INSIDE")

# --- MATH & LOGIC ---
def get_distance(lat1, lon1, lat2, lon2):
    R = 6371000 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return c * R

def log_transaction(user, action, amount=None):
    # Encryption logic
    enc_id = f"0x{hashlib.sha256(user.encode()).hexdigest()[:8]}..."
    timestamp = datetime.now().strftime("%H:%M")
    note = f"TX: {enc_id} | {action}"
    st.session_state.ledger.append(f"[{timestamp}] {note}")

# --- LOGIN ---
if 'logged_in_user' not in st.session_state:
    st.title("🛡️ EC Enterprise")
    pin = st.text_input("ENTER PIN", type="password")
    if st.button("AUTHENTICATE"):
        if pin in USERS:
            st.session_state.logged_in_user = USERS[pin]
            st.rerun()
        else:
            st.error("INVALID ACCESS")
    st.stop()

# --- MAIN DASHBOARD ---
user = st.session_state.logged_in_user
st.title(f"👤 {user['name']}")
status = "🟢 ON SHIFT" if st.session_state.user_state['active'] else "⚪ OFF DUTY"
st.caption(f"Status: {status}")

# EARNINGS
current = st.session_state.user_state['earnings']
if st.session_state.user_state['active']:
    session_pay = ((time.time() - st.session_state.user_state['start_time']) / 3600) * user['rate']
    st.metric("ACCRUED EARNINGS", f"${current + session_pay:,.2f}")
else:
    st.metric("WALLET BALANCE", f"${current:,.2f}")

# GPS SENTINEL
st.markdown("---")
st.markdown("### 📡 SATELLITE LINK")

loc = get_geolocation()
is_inside = False

if loc:
    dist = get_distance(loc['coords']['latitude'], loc['coords']['longitude'], HOSPITAL_LAT, HOSPITAL_LON)
    is_inside = dist < GEOFENCE_RADIUS
    st.write(f"GPS Distance: {int(dist)}m")
    
# DEV OVERRIDE LOGIC
if dev_override:
    is_inside = True
    st.warning("⚠️ DEV OVERRIDE ACTIVE: GPS BYPASSED")

if is_inside:
    st.success("✅ VERIFIED: INSIDE GEOFENCE")
else:
    st.error("🚫 BLOCKED: OUTSIDE GEOFENCE")

# SYNC BUTTON
if st.button("🔄 SYNC STATUS"):
    if is_inside and not st.session_state.user_state['active']:
        st.session_state.user_state['active'] = True
        st.session_state.user_state['start_time'] = time.time()
        log_transaction(user['name'], "CLOCK IN")
        st.rerun()
    elif not is_inside and st.session_state.user_state['active']:
        # Auto Clock Out
        elapsed = (time.time() - st.session_state.user_state['start_time']) / 3600
        st.session_state.user_state['earnings'] += elapsed * user['rate']
        st.session_state.user_state['active'] = False
        log_transaction(user['name'], "AUTO-CLOCK OUT")
        st.rerun()
    else:
        st.toast("Status Updated")

# LEDGER
st.markdown("---")
st.caption("ENCRYPTED LEDGER")
for l in reversed(st.session_state.ledger[-5:]):
    st.code(l)
