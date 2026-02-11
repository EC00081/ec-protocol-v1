import streamlit as st
import pandas as pd
import time
import random
from datetime import datetime
from fpdf import FPDF

# ==========================================
# 1. CONFIGURATION
# ==========================================
st.set_page_config(page_title="EC Enterprise", page_icon="🛡️")

# Initialize Database
if 'pool' not in st.session_state: st.session_state.pool = 50000.0
if 'revenue' not in st.session_state: st.session_state.revenue = 0.0
if 'ledger' not in st.session_state: st.session_state.ledger = []
if 'history' not in st.session_state: st.session_state.history = [50000.0]
if 'worker_active' not in st.session_state: st.session_state.worker_active = False

# Security Config
VALID_PIN = "1111"

# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================
def generate_receipt(worker, amount):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="EC ENTERPRISE", ln=1, align='C')
    pdf.set_font("Arial", size=10)
    pdf.cell(200, 10, txt="Powered by Gilford Son & Co.", ln=1, align='C')
    pdf.line(10, 30, 200, 30)
    pdf.ln(20)
    
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=1)
    pdf.cell(200, 10, txt=f"Worker ID: {worker}", ln=1)
    pdf.ln(10)
    pdf.cell(200, 10, txt=f"Total Settlement: ${amount:.2f}", ln=1)
    pdf.cell(200, 10, txt="Status: VERIFIED ON-CHAIN", ln=1)
    
    return pdf.output(dest='S').encode('latin-1')

# ==========================================
# 3. UI LAYOUT
# ==========================================
st.title("🛡️ EC Enterprise")
st.caption("Protocol v40.0 | Live Beta")

# Metrics
col1, col2 = st.columns(2)
col1.metric("Network Liquidity", f"${st.session_state.pool:,.2f}")
col2.metric("Protocol Revenue", f"${st.session_state.revenue:,.2f}")

# Chart
st.line_chart(st.session_state.history)

# ==========================================
# 4. OPERATIONS DECK
# ==========================================
st.markdown("### 👤 Worker Interface")

# Mode Selection
mode = st.radio("Operation Mode", ["Live Field Unit", "Investor Demo"], horizontal=True)

if mode == "Live Field Unit":
    # Security Input
    pin_input = st.text_input("Enter Security PIN", type="password")
    
    col_a, col_b = st.columns(2)
    
    with col_a:
        if st.button("🟢 CLOCK IN"):
            # 1. FRAUD CHECK: Already Active?
            if st.session_state.worker_active:
                st.error("🚫 BLOCKED: You are already clocked in.")
            # 2. SECURITY CHECK: PIN Correct?
            elif pin_input != VALID_PIN:
                st.error("🚫 BLOCKED: Invalid PIN.")
            # 3. SUCCESS
            else:
                st.session_state.pool -= 0.50
                st.session_state.history.append(st.session_state.pool)
                st.session_state.ledger.append(f"IN: Verified User")
                st.session_state.worker_active = True
                st.success("✅ CLOCKED IN SUCCESSFUL")
                time.sleep(1)
                st.rerun()

    with col_b:
        if st.button("🔴 SETTLE SHIFT"):
            # 1. LOGIC CHECK: Are they working?
            if not st.session_state.worker_active:
                st.error("⚠️ ERROR: No active shift to settle.")
            # 2. SUCCESS
            else:
                payout = 100.00
                fee = payout * 0.02
                st.session_state.pool -= payout
                st.session_state.revenue += fee
                st.session_state.history.append(st.session_state.pool)
                st.session_state.ledger.append(f"OUT: Settlement (+${payout})")
                st.session_state.worker_active = False
                st.success(f"💰 SHIFT SETTLED: ${payout}")
                time.sleep(1)
                st.rerun()

else: 
    # INVESTOR DEMO (Auto-Pilot)
    if st.button("▶️ RUN FULL SCENARIO"):
        # Reset State for Demo
        st.session_state.pool = 50000.0
        st.session_state.history = [50000.0]
        st.session_state.ledger = []
        
        # Step 1: Verification
        with st.spinner("📍 Verifying Geofence (Brockton Signature)..."):
            time.sleep(1.5)
        st.toast("✅ Location Verified")
        
        # Step 2: Clock In
        st.session_state.pool -= 0.50
        st.session_state.history.append(st.session_state.pool)
        st.session_state.ledger.append("IN: Demo Worker")
        
        # Step 3: Work Simulation
        my_bar = st.progress(0)
        for i in range(100):
            time.sleep(0.01)
            if i % 10 == 0:
                st.session_state.pool -= random.uniform(20, 50)
                st.session_state.history.append(st.session_state.pool)
            my_bar.progress(i + 1)
            
        # Step 4: Settlement
        gross = 1020.00
        st.session_state.pool -= gross
        st.session_state.revenue += (gross * 0.02)
        st.session_state.history.append(st.session_state.pool)
        st.session_state.ledger.append("OUT: Demo Worker")
        
        st.success(f"💰 Payment Streamed: ${gross:,.2f}")
        
        # Step 5: Receipt
        pdf_data = generate_receipt("Liam_RT", gross)
        st.download_button("📄 Download Receipt", data=pdf_data, file_name="EC_Receipt.pdf", mime="application/pdf")

# Ledger
st.markdown("---")
st.caption("Immutable Ledger (Last 5 Actions)")
for log in reversed(st.session_state.ledger[-5:]):
    st.text(log)
