import streamlit as st
import pandas as pd
import time
import math
import hashlib
from datetime import datetime
from streamlit_js_eval import get_geolocation
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from streamlit_autorefresh import st_autorefresh

# --- CONFIGURATION ---
st.set_page_config(page_title="EC Enterprise", page_icon="🛡️")

# 1. HEARTBEAT (The "Running" Geolocator)
# This forces the app to refresh every 30 seconds (30000ms) to check GPS
count = st_autorefresh(interval=30000, key="fizzbuzzcounter")

# 2. CONSTANTS
HOSPITAL_LAT = 42.0875
HOSPITAL_LON = -70.9915
GEOFENCE_RADIUS = 300 
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}

# --- DATABASE ENGINE ---
def get_db_connection():
    """Connects to Google Sheets safely"""
    try:
        if "gcp_service_account" not in st.secrets:
            return None, "No Secrets Found"
        
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        client = gspread.authorize(creds)
        
        # Return the bot email so we can verify permissions
        return client, creds.service_account_email
    except Exception as e:
        return None, str(e)

def update_cloud_db(pin, status, start_time, earnings):
    client, email = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("workers")
            # Find row or append
            try:
                cell = sheet.find(str(pin))
                row = cell.row
                sheet.update_cell(row, 2, status)      # Status
                sheet.update_cell(row, 3, start_time)  # Start Time
                sheet.update_cell(row, 4, earnings)    # Earnings
                sheet.update_cell(row, 5, str(datetime.now())) # Last Update
            except gspread.exceptions.CellNotFound:
                # Create new user row if not found
                sheet.append_row([pin, status, start_time, earnings, str(datetime.now())])
            return True
        except Exception as e:
            st.error(f"Cloud Sync Error: {e}")
            return False
    return False

def get_cloud_data(pin):
    client, email = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("workers")
            cell = sheet.find(str(pin))
            row_values = sheet.row_values(cell.row)
            # Row Format: [PIN, Status, StartTime, Earnings, LastUpdate]
            return {
                'status': row_values[1],
                'start_time': float(row_values[2]),
                'earnings': float(row_values[3])
            }
        except:
            return None
    return None

# --- MATH & LOGIC ---
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

# --- STATE MANAGEMENT ---
if 'user_state' not in st.session_state: 
    st.session_state.user_state = {'active': False, 'start_time': None, 'earnings': 0.0}

USERS = {
    "1001": {"name": "Liam O'Neil", "role": "RT", "rate": 85.00},
    "9999": {"name": "CFO", "role": "Exec", "rate": 0.00}
}

# --- LOGIN SCREEN ---
if 'logged_in_user' not in st.session_state:
    st.title("🛡️ EC Enterprise")
    st.caption("v47.0 | Auto-Pilot Enabled")
    
    # DEBUG: Show the Bot Email so you can share the sheet
    client, bot_email = get_db_connection()
    if bot_email:
        with st.expander("ℹ️ Database Setup Info"):
            st.write("Share your Google Sheet with this email:")
            st.code(bot_email)
            st.write("Sheet Name must be: `ec_database`")
            st.write("Tab Name must be: `workers`")
    else:
        st.error("⚠️ Database Secrets Missing")

    pin = st.text_input("ENTER PIN", type="password")
    if st.button("AUTHENTICATE"):
        if pin in USERS:
            st.session_state.logged_in_user = USERS[pin]
            st.session_state.pin = pin
            
            # TRY TO RESTORE SESSION FROM CLOUD
            cloud_data = get_cloud_data(pin)
            if cloud_data:
                st.session_state.user_state['active'] = (cloud_data['status'] == 'Active')
                st.session_state.user_state['start_time'] = cloud_data['start_time']
                st.session_state.user_state['earnings'] = cloud_data['earnings']
                st.toast("☁️ Session Restored from Cloud")
            
            st.rerun()
        else:
            st.error("INVALID PIN")
    st.stop()

# --- MAIN DASHBOARD ---
user = st.session_state.logged_in_user
pin = st.session_state.pin

st.title(f"👤 {user['name']}")

# 1. GPS LOGIC
loc = get_geolocation()
dist_msg = "Waiting for GPS..."
is_inside = False

# Add DEV OVERRIDE
with st.sidebar:
    st.write(f"Auto-Refresh Count: {count}")
    dev_override = st.checkbox("FORCE INSIDE ZONE")

if loc:
    dist = get_distance(loc['coords']['latitude'], loc['coords']['longitude'], HOSPITAL_LAT, HOSPITAL_LON)
    is_inside = dist < GEOFENCE_RADIUS or dev_override
    
    if is_inside:
        dist_msg = f"✅ INSIDE ({int(dist)}m)"
        # AUTO CLOCK IN LOGIC COULD GO HERE
    else:
        dist_msg = f"🚫 OUTSIDE ({int(dist)}m)"
        
        # AUTO CLOCK OUT LOGIC (The "Running" Check)
        if st.session_state.user_state['active']:
            # They were active, now they are outside -> Clock Out
            st.session_state.user_state['active'] = False
            # Calculate final earnings
            elapsed = (time.time() - st.session_state.user_state['start_time']) / 3600
            final_pay = st.session_state.user_state['earnings'] + (elapsed * user['rate'])
            st.session_state.user_state['earnings'] = final_pay
            
            # Sync to Cloud
            update_cloud_db(pin, "Inactive", 0, final_pay)
            st.error("⚠️ GEOFENCE EXIT: AUTO-CLOCKED OUT")

st.info(f"📍 STATUS: {dist_msg}")

# 2. PAYROLL DISPLAY
current_earnings = st.session_state.user_state['earnings']
if st.session_state.user_state['active']:
    elapsed = (time.time() - st.session_state.user_state['start_time']) / 3600
    current_earnings += elapsed * user['rate']

net_pay = calculate_taxes(current_earnings)

c1, c2 = st.columns(2)
c1.metric("GROSS", f"${current_earnings:,.2f}")
c2.metric("NET", f"${net_pay:,.2f}")

# 3. CONTROLS
if not st.session_state.user_state['active']:
    if st.button("🟢 CLOCK IN"):
        if is_inside:
            st.session_state.user_state['active'] = True
            st.session_state.user_state['start_time'] = time.time()
            update_cloud_db(pin, "Active", time.time(), current_earnings)
            st.success("STARTED")
            st.rerun()
        else:
            st.error("Cannot Clock In: Outside Zone")
else:
    if st.button("🔴 CLOCK OUT"):
        st.session_state.user_state['active'] = False
        st.session_state.user_state['earnings'] = current_earnings
        update_cloud_db(pin, "Inactive", 0, current_earnings)
        st.success("ENDED")
        st.rerun()

st.caption("System refreshes every 30s to check location.")
