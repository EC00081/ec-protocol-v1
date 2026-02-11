import streamlit as st
import pandas as pd
import time
import math
from streamlit_js_eval import get_geolocation

# ==========================================
# 1. CONFIGURATION
# ==========================================
st.set_page_config(page_title="EC Enterprise", page_icon="🛡️")

# TARGET: Signature Healthcare Brockton Hospital
TARGET_LAT = 42.0806
TARGET_LON = -71.0264
RADIUS_METERS = 300  # 300m Tolerance

# Initialize State
if 'pool' not in st.session_state: st.session_state.pool = 50000.0
if 'revenue' not in st.session_state: st.session_state.revenue = 0.0
if 'ledger' not in st.session_state: st.session_state.ledger = []
if 'worker_active' not in st.session_state: st.session_state.worker_active = False

# ==========================================
# 2. GPS MATH ENGINE
# ==========================================
def get_distance(lat1, lon1, lat2, lon2):
    R = 6371000 # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return c * R

# ==========================================
# 3. UI LAYOUT
# ==========================================
st.title("🛡️ EC Enterprise")
st.caption("Protocol v41.0 | GPS Linked")

# Metrics
col1, col2 = st.columns(2)
col1.metric("Network Liquidity", f"${st.session_state.pool:,.2f}")
col2.metric("Protocol Revenue", f"${st.session_state.revenue:,.2f}")

st.markdown("---")

# ==========================================
# 4. LOCATION VERIFICATION
# ==========================================
st.markdown("### 📍 Location Sentinel")

# This button triggers the browser popup "Allow Location?"
loc = get_geolocation()

is_in_zone = False
dist = 0

if loc:
    user_lat = loc['coords']['latitude']
    user_lon = loc['coords']['longitude']
    dist = get_distance(user_lat, user_lon, TARGET_LAT, TARGET_LON)
    
    if dist < RADIUS_METERS:
        st.success(f"✅ VERIFIED: Inside Geofence ({int(dist)}m from Core)")
        is_in_zone = True
    else:
        st.error(f"🚫 BLOCKED: You are {int(dist)}m away from Hospital.")
        st.caption(f"Your Coordinates: {user_lat:.4f}, {user_lon:.4f}")
        is_in_zone = False
else:
    st.warning("⚠️ WAITING FOR GPS SIGNAL... (Please Click 'Allow')")

# ==========================================
# 5. OPERATIONS
# ==========================================
st.markdown("### 👤 Operations")

pin = st.text_input("Enter PIN", type="password")
col_a, col_b = st.columns(2)

with col_a:
    if st.button("🟢 CLOCK IN"):
        # 1. GPS Check
        if not is_in_zone:
            st.error(f"❌ GPS LOCK: You are {int(dist)}m away.")
        # 2. Status Check
        elif st.session_state.worker_active:
            st.warning("⚠️ You are already clocked in.")
        # 3. PIN Check
        elif pin != "1111":
            st.error("❌ INVALID PIN")
        # 4. Success
        else:
            st.session_state.pool -= 0.50
            st.session_state.ledger.append(f"IN: Verified @ {int(dist)}m")
            st.session_state.worker_active = True
            st.success("CLOCK IN CONFIRMED")
            time.sleep(1)
            st.rerun()

with col_b:
    if st.button("🔴 SETTLE SHIFT"):
        if st.session_state.worker_active:
            amt = 100.00
            st.session_state.pool -= amt
            st.session_state.revenue += (amt * 0.02)
            st.session_state.worker_active = False
            st.session_state.ledger.append(f"OUT: Settled (+${amt})")
            st.success("SHIFT SETTLED")
            time.sleep(1)
            st.rerun()
        else:
            st.error("No active shift.")

# Ledger
st.markdown("---")
for log in reversed(st.session_state.ledger[-5:]):
    st.text(log)
