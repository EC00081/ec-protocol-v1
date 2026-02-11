import streamlit as st
import pandas as pd
import time
import math
import hashlib
import random
from datetime import datetime
from streamlit_js_eval import get_geolocation

# ==========================================
# 1. CONFIGURATION
# ==========================================
st.set_page_config(page_title="EC Enterprise", page_icon="🛡️")

# SECURITY
USERS = {
    "1001": {"name": "Liam O'Neil", "role": "Respiratory Therapist", "rate": 85.00}
}
HOSPITAL_LAT = 42.0806
HOSPITAL_LON = -71.0264
GEOFENCE_RADIUS = 300  # 300 Meters (approx 984 ft) - The "Wiggle Room"

# INITIALIZE STATE
if 'pool' not in st.session_state: st.session_state.pool = 50000.0
if 'ledger' not in st.session_state: st.session_state.ledger = []
if 'user_state' not in st.session_state: 
    st.session_state.user_state = {'active': False, 'start_time': None, 'earnings': 0.0}

# ==========================================
# 2. ENCRYPTION ENGINE (The "Ghost" Layer)
# ==========================================
def encrypt_id(user_name):
    # Turns "Liam O'Neil" into "0x4f...2a" for privacy
    hash_object = hashlib.sha256(user_name.encode())
    hex_dig = hash_object.hexdigest()
    return f"0x{hex_dig[:8]}..."

def log_transaction(user, action, amount=None):
    # Logs to public ledger anonymously
    enc_id = encrypt_id(user)
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    if amount:
        note = f"TX: {enc_id} | {action} [ENCRYPTED AMT]"
    else:
        note = f"TX: {enc_id} | {action}"
        
    st.session_state.ledger.append(f"[{timestamp}] {note}")
    # Keep only last 10
    if len(st.session_state.ledger) > 10:
        st.session_state.ledger.pop(0)

# ==========================================
# 3. GPS MATH
# ==========================================
def get_distance(lat1, lon1, lat2, lon2):
    R = 6371000 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return c * R

# ==========================================
# 4. LOGIN SCREEN
# ==========================================
if 'logged_in_user' not in st.session_state:
    st.title("🛡️ EC Enterprise")
    st.caption("Secure Access Portal")
    
    pin_attempt = st.text_input("ENTER IDENTIFICATION PIN", type="password")
    
    if st.button("AUTHENTICATE"):
        if pin_attempt in USERS:
            st.session_state.logged_in_user = USERS[pin_attempt]
            st.success(f"WELCOME, {USERS[pin_attempt]['name'].upper()}")
            time.sleep(1)
            st.rerun()
        else:
            st.error("ACCESS DENIED: INVALID CREDENTIALS")
    st.stop() # Stop here if not logged in

# ==========================================
# 5. MAIN DASHBOARD (Logged In)
# ==========================================
user = st.session_state.logged_in_user
st.title(f"👤 {user['name']}")
st.caption(f"Role: {user['role']} | Status: {'🟢 ON SHIFT' if st.session_state.user_state['active'] else '⚪ OFF DUTY'}")

# --- LIVE EARNINGS TRACKER ---
current_earnings = st.session_state.user_state['earnings']
if st.session_state.user_state['active']:
    # Calculate real-time earnings since start
    elapsed_hours = (time.time() - st.session_state.user_state['start_time']) / 3600
    session_pay = elapsed_hours * user['rate']
    total_display = current_earnings + session_pay
    st.metric("PENDING WITHDRAWAL", f"${total_display:,.2f}", delta="Accruing Live...")
else:
    st.metric("AVAILABLE BALANCE", f"${current_earnings:,.2f}")

# --- GPS SENTINEL ---
st.markdown("---")
st.markdown("### 📡 SATELLITE LINK")

loc = get_geolocation()

if loc:
    lat = loc['coords']['latitude']
    lon = loc['coords']['longitude']
    dist = get_distance(lat, lon, HOSPITAL_LAT, HOSPITAL_LON)
    
    # GEOFENCE LOGIC
    is_inside = dist < GEOFENCE_RADIUS
    
    if is_inside:
        st.success(f"✅ INSIDE ZONE ({int(dist)}m from Core)")
    else:
        st.error(f"🚫 OUTSIDE ZONE ({int(dist)}m away)")

    # SMART ACTION BUTTON
    if st.button("🔄 SYNC STATUS & UPDATE"):
        
        # LOGIC 1: AUTO CLOCK IN
        if is_inside and not st.session_state.user_state['active']:
            st.session_state.user_state['active'] = True
            st.session_state.user_state['start_time'] = time.time()
            log_transaction(user['name'], "CLOCK IN")
            st.toast("✅ AUTO-CLOCK IN CONFIRMED")
            time.sleep(1)
            st.rerun()
            
        # LOGIC 2: AUTO CLOCK OUT (Barrier Breach)
        elif not is_inside and st.session_state.user_state['active']:
            # Calculate final pay
            elapsed = (time.time() - st.session_state.user_state['start_time']) / 3600
            pay = elapsed * user['rate']
            st.session_state.user_state['earnings'] += pay
            st.session_state.user_state['active'] = False
            log_transaction(user['name'], "AUTO-CLOCK OUT (GEOFENCE BREACH)")
            st.toast("⚠️ BARRIER BREACH: SHIFT ENDED")
            time.sleep(1)
            st.rerun()
            
        # LOGIC 3: JUST UPDATE
        else:
            st.toast("✅ STATUS SYNCED: NO CHANGE")

else:
    st.warning("WAITING FOR GPS... (Click Allow)")

# --- PRIVATE WITHDRAWAL ---
st.markdown("---")
if st.session_state.user_state['earnings'] > 0 and not st.session_state.user_state['active']:
    if st.button("💰 WITHDRAW FUNDS (PRIVATE)"):
        amount = st.session_state.user_state['earnings']
        st.session_state.user_state['earnings'] = 0.0
        log_transaction(user['name'], "WITHDRAWAL INITIATED", amount)
        st.success(f"TX CONFIRMED: ${amount:.2f} transferred to vault.")
        time.sleep(2)
        st.rerun()

# --- PUBLIC ENCRYPTED LEDGER ---
st.markdown("### 📜 PUBLIC CHAIN LEDGER")
st.caption("Transactions are encrypted for user privacy.")
for entry in reversed(st.session_state.ledger):
    st.code(entry, language="text")
