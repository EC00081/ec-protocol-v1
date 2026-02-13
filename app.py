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

st.set_page_config(page_title="EC Enterprise", page_icon="🛡️")

# --- 1. CONFIGURATION ---
HOSPITAL_LAT = 42.0875
HOSPITAL_LON = -70.9915
GEOFENCE_RADIUS = 300 
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}
# Auto-refresh every 30 seconds for GPS
count = st_autorefresh(interval=30000, key="gps_sync")

# --- 2. DATABASE CONNECTION (With Diagnostics) ---
def get_db_connection():
    """Attempts to connect and returns specific error messages if it fails."""
    if "gcp_service_account" not in st.secrets:
        return None, "MISSING_SECRETS"
    
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        client = gspread.authorize(creds)
        return client, creds.service_account_email
    except Exception as e:
        return None, str(e)

def get_worker_status(pin):
    client, email_or_error = get_db_connection()
    
    # CASE 1: CONNECTION FAILED
    if not client:
        return None, None, f"Connection Error: {email_or_error}"

    try:
        sheet = client.open("ec_database").worksheet("workers")
    except gspread.exceptions.SpreadsheetNotFound:
        return None, None, f"❌ I cannot find a sheet named 'ec_database'. Please check the name."
    except gspread.exceptions.WorksheetNotFound:
        return None, None, f"❌ I found 'ec_database', but I cannot find a tab named 'workers'. Please rename 'Sheet1'."
    except Exception as e:
        # This usually means PERMISSION DENIED
        return None, None, f"🔒 PERMISSION DENIED. Please share the sheet with: {email_or_error}"

    # CASE 2: CONNECTION SUCCESS - READ DATA
    try:
        records = sheet.get_all_records()
        for i, row in enumerate(records):
            # Convert both to string to be safe
            if str(row.get('pin')) == str(pin):
                return row, i + 2, None # Found user!
        return None, None, "User Not Found" # User not in DB yet
    except Exception as e:
        return None, None, f"Data Read Error: {e}"

def update_cloud_db(pin, status, start_time, earnings):
    client, _ = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("workers")
            # Try to find the cell with the PIN
            try:
                cell = sheet.find(str(pin))
                row = cell.row
                sheet.update_cell(row, 2, status)
                sheet.update_cell(row, 3, start_time)
                sheet.update_cell(row, 4, earnings)
                sheet.update_cell(row, 5, str(datetime.now()))
            except gspread.exceptions.CellNotFound:
                # If PIN not found, make a new row
                sheet.append_row([str(pin), status, start_time, earnings, str(datetime.now())])
            return True
        except:
            return False
    return False

# --- 3. MATH & LOGIC ---
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

# --- 4. APP LOGIC ---
if 'user_state' not in st.session_state: 
    st.session_state.user_state = {'active': False, 'start_time': None, 'earnings': 0.0}

USERS = {
    "1001": {"name": "Liam O'Neil", "role": "RT", "rate": 85.00},
    "9999": {"name": "CFO", "role": "Exec", "rate": 0.00}
}

# --- LOGIN SCREEN ---
if 'logged_in_user' not in st.session_state:
    st.title("🛡️ EC Enterprise")
    st.caption("v48.0 | Connection Doctor")
    
    # 🚨 DIAGNOSTICS PANEL 🚨
    client, msg = get_db_connection()
    if client:
        st.success(f"✅ SYSTEM ONLINE")
        with st.expander("Show Connection Details"):
             st.write("Bot Email (Share Sheet with this):")
             st.code(msg)
    else:
        st.error(f"⚠️ SYSTEM OFFLINE: {msg}")

    pin = st.text_input("ENTER PIN", type="password")
    
    if st.button("AUTHENTICATE"):
        if pin in USERS:
            st.session_state.logged_in_user = USERS[pin]
            st.session_state.pin = pin
            
            # ATTEMPT CLOUD SYNC
            row_data, row_num, error_msg = get_worker_status(pin)
            
            if row_data:
                # SUCCESS: We found data in the cloud!
                st.session_state.user_state['active'] = (row_data['status'] == 'Active')
                # Handle possible empty or string values
                try:
                    st.session_state.user_state['start_time'] = float(row_data['start_time'])
                except:
                    st.session_state.user_state['start_time'] = 0.0
                try:
                    st.session_state.user_state['earnings'] = float(row_data['earnings'])
                except:
                    st.session_state.user_state['earnings'] = 0.0
                st.toast("☁️ Cloud Sync Successful")
            
            elif "User Not Found" in str(error_msg):
                # New user, that's fine. We will create them on first clock in.
                pass
            
            elif error_msg:
                # REAL ERROR: Show it so we can fix it
                st.error(error_msg)
                st.stop()
                
            st.rerun()
        else:
            st.error("INVALID PIN")
    st.stop()

# --- MAIN DASHBOARD ---
user = st.session_state.logged_in_user
pin = st.session_state.pin

st.title(f"👤 {user['name']}")

# GPS Logic
loc = get_geolocation()
dist_msg = "Waiting for GPS..."
is_inside = False

# Sidebar Override
with st.sidebar:
    dev_override = st.checkbox("FORCE INSIDE ZONE")

if loc:
    dist = get_distance(loc['coords']['latitude'], loc['coords']['longitude'], HOSPITAL_LAT, HOSPITAL_LON)
    is_inside = dist < GEOFENCE_RADIUS or dev_override
    
    if is_inside:
        dist_msg = f"✅ INSIDE ({int(dist)}m)"
    else:
        dist_msg = f"🚫 OUTSIDE ({int(dist)}m)"
        
        # AUTO CLOCK OUT
        if st.session_state.user_state['active']:
            st.session_state.user_state['active'] = False
            elapsed = (time.time() - st.session_state.user_state['start_time']) / 3600
            final_pay = st.session_state.user_state['earnings'] + (elapsed * user['rate'])
            st.session_state.user_state['earnings'] = final_pay
            update_cloud_db(pin, "Inactive", 0, final_pay)
            st.error("⚠️ GEOFENCE EXIT: AUTO-CLOCKED OUT")

st.info(f"📍 STATUS: {dist_msg}")

# Payroll Logic
current_earnings = st.session_state.user_state['earnings']
if st.session_state.user_state['active']:
    elapsed = (time.time() - st.session_state.user_state['start_time']) / 3600
    current_earnings += elapsed * user['rate']

net_pay = calculate_taxes(current_earnings)

c1, c2 = st.columns(2)
c1.metric("GROSS", f"${current_earnings:,.2f}")
c2.metric("NET", f"${net_pay:,.2f}")

# Controls
if not st.session_state.user_state['active']:
    if st.button("🟢 CLOCK IN"):
        if is_inside:
            st.session_state.user_state['active'] = True
            st.session_state.user_state['start_time'] = time.time()
            # Try to write to cloud
            success = update_cloud_db(pin, "Active", time.time(), current_earnings)
            if success:
                st.success("STARTED & SYNCED")
            else:
                st.warning("STARTED (LOCAL ONLY - CLOUD ERROR)")
            time.sleep(1); st.rerun()
        else:
            st.error("Cannot Clock In: Outside Zone")
else:
    if st.button("🔴 CLOCK OUT"):
        st.session_state.user_state['active'] = False
        st.session_state.user_state['earnings'] = current_earnings
        update_cloud_db(pin, "Inactive", 0, current_earnings)
        st.success("ENDED & SAVED")
        time.sleep(1); st.rerun()
