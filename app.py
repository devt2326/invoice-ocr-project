import openai
import os
import json
import pdfplumber
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from datetime import datetime
# Load environment variables
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

# File paths
OUTPUT_DIR = "outputs"
LEDGER_FILE = os.path.join(OUTPUT_DIR, "ledger.xlsx")
INVENTORY_FILE = os.path.join(OUTPUT_DIR, "inventory.xlsx")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Hardcoded vendor-to-category map
VENDOR_CATEGORY_MAP = {
    "ABCD": "Office Supplies",
    "Google": "IT Services",
    "Staples": "Office Supplies"
}

# Streamlit page setup
st.set_page_config(page_title="LedgerScribe", layout="wide")
st.title("LedgerScribe: Invoice Parser & Journal Generator")

# Session state initialization
if "extracted_data" not in st.session_state:
    st.session_state["extracted_data"] = {}
if "invoice_text" not in st.session_state:
    st.session_state["invoice_text"] = ""
if "journal_entries" not in st.session_state:
    st.session_state["journal_entries"] = []

# Tabs
tabs = st.tabs(["Upload Invoice", "Invoice Details", "Journal Entries", "Ledger History", "Inventory"])

# Upload Invoice
with tabs[0]:
    uploaded_file = st.file_uploader("Upload your Invoice PDF", type=["pdf"])
    if uploaded_file:
        text = ""
        try:
            with pdfplumber.open(uploaded_file) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            st.session_state["invoice_text"] = text
            st.success("Invoice text extracted.")
        except Exception as e:
            st.error(f"PDF Read Error: {e}")

# Invoice Details
with tabs[1]:
    text = st.session_state.get("invoice_text", "")
    if text:
        st.subheader("Extracted Invoice Text")
        st.text_area("Text", text, height=300)

        if st.button("Extract Invoice Fields"):
            with st.spinner("Calling GPT to extract invoice fields..."):
                prompt = f"""
Extract the following fields from this invoice text:

- invoice_number
- invoice_date
- vendor_name
- line_items (list of description, quantity, and amount)
- subtotal
- taxes
- total_amount
- contact_info (address, phone_number)

Only return a valid JSON object with those fields.

Invoice:
{text}
"""
                try:
                    response = openai.ChatCompletion.create(
                        model="gpt-4",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0
                    )
                    result = response.choices[0].message["content"]
                    data = json.loads(result)

                    for item in data.get("line_items", []):
                        amt = item.get("amount", "$0").replace("$", "").replace(",", "")
                        item["amount"] = float(amt)
                        item["quantity"] = int(item.get("quantity", 1))
                        item["unit_cost"] = round(item["amount"] / item["quantity"], 2) if item["quantity"] != 0 else 0

                    st.session_state["extracted_data"] = data
                    st.success("Fields extracted.")

                except Exception as e:
                    st.error(f"GPT parsing error: {e}")

    data = st.session_state.get("extracted_data", {})

    if data:
        
        st.subheader("Invoice Details")

        # --- Line Items UI ---
        st.markdown("### Line Items")

        with st.form("add_item_form", clear_on_submit=True):
            col1, col2, col3, col4 = st.columns([4, 2, 2, 1])
            with col1:
                item_desc = st.text_input("Description", placeholder="Item description")
            with col2:
                item_qty = st.number_input("Quantity", min_value=1, step=1)
            with col3:
                item_amount = st.number_input("Amount", min_value=0.0, step=0.01)
            with col4:
                st.markdown(" ")
            add_item = st.form_submit_button("Add Item")

        if add_item:
            if item_desc and item_amount > 0:
                data.setdefault("line_items", []).append({
                    "description": item_desc,
                    "quantity": item_qty,
                    "amount": item_amount,
                    "unit_cost": round(item_amount / item_qty, 2) if item_qty > 0 else 0
                })
                st.session_state["extracted_data"] = data
                st.rerun()

        if data.get("line_items"):
            st.markdown("#### Current Items")
            for idx, item in enumerate(data["line_items"]):
                col1, col2, col3, col4, col5 = st.columns([4, 2, 2, 2, 1])
                col1.write(item["description"])
                col2.write(f"Qty: {item['quantity']}")
                col3.write(f"Amount: ${item['amount']:.2f}")
                col4.write(f"Unit: ${item['unit_cost']:.2f}")
                if col5.button("❌", key=f"delete_{idx}"):
                    data["line_items"].pop(idx)
                    st.session_state["extracted_data"] = data
                    st.rerun()

        total_amount = sum(item["amount"] for item in data.get("line_items", []))

        with st.form("invoice_form"):
            col1, col2 = st.columns(2)
            with col1:
                invoice_number = st.text_input("Invoice Number", value=data.get("invoice_number", ""))
            with col2:
                raw_date = data.get("invoice_date", "")
                parsed_date = pd.to_datetime(raw_date, errors="coerce")
                if pd.isna(parsed_date):
                    parsed_date = datetime.today()
                invoice_date = st.date_input("Date", value=parsed_date.date())

            col3, col4 = st.columns(2)
            with col3:
                vendor_name = st.text_input("Vendor", value=data.get("vendor_name", ""))
            with col4:
                st.number_input("Total Amount", value=total_amount, disabled=True)

            description = st.text_area("Description", value="Invoice description")

            submitted = st.form_submit_button("Process Invoice")
            if submitted:
                data["invoice_number"] = invoice_number
                data["invoice_date"] = invoice_date.strftime("%Y-%m-%d")
                data["vendor_name"] = vendor_name
                data["total_amount"] = total_amount
                st.session_state["extracted_data"] = data
                st.success("Invoice details processed.")
    else:
        st.info("Please upload and extract an invoice first.")
# Journal Entries
with tabs[2]:
    st.header("Suggested Journal Entries")

    extracted_data = st.session_state.get("extracted_data", {})
    text = st.session_state.get("invoice_text", "")

    if st.button("Suggest Journal Entries"):
        if not extracted_data:
            st.warning("Please extract invoice data first.")
        else:
            amount_val = extracted_data.get("total_amount", 0)
            amount_str = str(amount_val).replace("$", "").replace(",", "").strip()
            
            try:
                amount = float(amount_str)
            except:
                amount = 0.0

            vendor = extracted_data.get("vendor_name", "").strip()
            category = VENDOR_CATEGORY_MAP.get(vendor)

            if not category:
                prompt = f"Suggest an accounting category like 'Office Supplies', 'IT Services', 'Inventory Purchases' for this invoice:\n{text}\nReturn just the category name."
                try:
                    response = openai.ChatCompletion.create(
                        model="gpt-4",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0
                    )
                    category = response.choices[0].message["content"].strip()
                    st.info(f"GPT Suggested Category: {category}")
                except Exception as e:
                    category = "Uncategorized"
                    st.warning("GPT failed. Defaulted to 'Uncategorized'.")

            journal_entries = [
                {"debit": category, "credit": "Accounts Payable", "amount": amount}
            ]
            st.session_state["journal_entries"] = journal_entries
            st.session_state["category"] = category
            st.success("Suggested journal entries loaded.")

    # Editable Table
    edited_entries = st.data_editor(
        st.session_state.get("journal_entries", [{"debit": "", "credit": "", "amount": 0.0}]),
        num_rows="dynamic",
        use_container_width=True,
        key="editable_journal_entries"
    )

    if st.button("Confirm and Save to Ledger"):
        if not edited_entries:
            st.warning("No journal entries to save.")
        else:
            data = extracted_data
            date = data.get("invoice_date", "Enter invoice date")
            ref = data.get("invoice_number", "unknown")

            if os.path.exists(LEDGER_FILE):
                existing = pd.read_excel(LEDGER_FILE)
                last_sr = existing["sr_no"].max() + 1
            else:
                existing = pd.DataFrame()
                last_sr = 1

            rows = []
            sr = last_sr
            for entry in edited_entries:
                rows.append({"sr_no": sr, "date": date, "reference": ref, "description": entry["debit"], "debit": entry["amount"], "credit": None})
                sr += 1
                rows.append({"sr_no": sr, "date": date, "reference": ref, "description": entry["credit"], "debit": None, "credit": entry["amount"]})
                sr += 1

            new_df = pd.DataFrame(rows)
            combined = pd.concat([existing, new_df], ignore_index=True)
            combined.to_excel(LEDGER_FILE, index=False)
            st.success("Ledger updated.")

            # --- Inventory Sync ---
            if st.session_state.get("category") == "Inventory Purchases":
                inv_df = pd.read_excel(INVENTORY_FILE) if os.path.exists(INVENTORY_FILE) else pd.DataFrame(columns=["description", "quantity", "amount", "invoice_number", "invoice_date"])
                for item in data.get("line_items", []):
                    row = {
                        "description": item.get("description"),
                        "quantity": item.get("quantity"),
                        "amount": item.get("amount"),
                        "invoice_number": ref,
                        "invoice_date": date
                    }
                    inv_df = pd.concat([inv_df, pd.DataFrame([row])], ignore_index=True)
                inv_df.to_excel(INVENTORY_FILE, index=False)

# Ledger History
with tabs[3]:
    st.subheader("Ledger Entries")
    if os.path.exists(LEDGER_FILE):
        df = pd.read_excel(LEDGER_FILE)
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No ledger entries found yet.")

# Inventory View
with tabs[4]:
    st.header("Inventory")
    if os.path.exists(INVENTORY_FILE):
        inv_df = pd.read_excel(INVENTORY_FILE)
        inv_df["amount"] = inv_df["amount"].astype(str).str.replace("$", "").str.replace(",", "").astype(float)
        inv_df["quantity"] = pd.to_numeric(inv_df["quantity"], errors="coerce").fillna(0)
        inv_df["unit_cost"] = inv_df.apply(lambda row: row["amount"] / row["quantity"] if row["quantity"] != 0 else 0, axis=1)

        grouped = inv_df.groupby("description", as_index=False).agg({
            "quantity": "sum",
            "amount": "sum",
            "unit_cost": "mean",
            "invoice_number": "last",
            "invoice_date": "last"
        })
        st.dataframe(grouped, use_container_width=True)
    else:
        st.info("No inventory records yet. Upload an invoice with Inventory Purchases to get started.")