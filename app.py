import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text

# Set page title and layout
st.set_page_config(page_title="NYC Taxi OLAP Dashboard", layout="wide")

# 1. Database Connection
@st.cache_resource
def get_engine():
    # MySQL credentials
    return create_engine("mysql+pymysql://root:12345678@127.0.0.1:3306/nyc_taxi_dw")

engine = get_engine()

# Helper function to run queries safely
def run_query(sql, params=None):
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)

st.title("🚖 NYC Yellow Taxi OLAP Dashboard (2025)")
st.write("Perform multi-dimensional analysis with Roll-up, Drill-down, Slice, Dice, and Pivot.")

# ==============================================================================
# SIDEBAR FILTERS (Slice & Dice Controls)
# ==============================================================================
st.sidebar.header("🔍 OLAP Slice & Dice Filters")

# Fetch lookup data for filter dropdowns
@st.cache_data
def get_filter_options():
    boroughs = run_query("SELECT DISTINCT borough FROM dim_location WHERE borough != 'Unknown' ORDER BY borough")['borough'].tolist()
    vendors = run_query("SELECT vendor_key, vendor_name FROM dim_vendor WHERE vendor_key != 0 ORDER BY vendor_key")
    payments = run_query("SELECT payment_type_key, payment_type_desc FROM dim_payment_type ORDER BY payment_type_key")
    return boroughs, vendors, payments

all_boroughs, df_vendors, df_payments = get_filter_options()

# Slice / Dice 1: Borough selection
selected_boroughs = st.sidebar.multiselect(
    "Pickup Boroughs (Dice/Slice):",
    options=all_boroughs,
    default=all_boroughs[:2] if all_boroughs else []
)

# Slice / Dice 2: Month selection
selected_months = st.sidebar.multiselect(
    "Months (Dice/Slice):",
    options=list(range(1, 13)),
    default=[1, 2]
)

# Slice / Dice 3: Payment Type
payment_options = dict(zip(df_payments['payment_type_desc'], df_payments['payment_type_key']))
selected_payments = st.sidebar.multiselect(
    "Payment Types (Dice/Slice):",
    options=list(payment_options.keys()),
    default=["Credit card", "Cash"]
)

# Convert UI inputs to SQL filter clauses
conditions = ["1=1"]
if selected_boroughs:
    b_list = "', '".join(selected_boroughs)
    conditions.append(f"loc.borough IN ('{b_list}')")
if selected_months:
    m_list = ", ".join(map(str, selected_months))
    conditions.append(f"d.month IN ({m_list})")
if selected_payments:
    p_ids = [str(payment_options[p]) for p in selected_payments]
    conditions.append(f"f.payment_type_key IN ({', '.join(p_ids)})")

where_clause = " AND ".join(conditions)

# ==============================================================================
# REPORT 1: Location Hierarchy (Roll-up & Drill-down)
# ==============================================================================
st.header("1. Geographic Analysis (Roll-up / Drill-down)")
st.caption("Dimensional Hierarchy: All NYC ➔ Borough ➔ Zone")

geo_granularity = st.radio(
    "Select Granularity Level:",
    options=["Roll-up (Borough Level)", "Drill-down (Borough + Zone Level)"],
    horizontal=True
)

if "Roll-up" in geo_granularity:
    sql_geo = f"""
        SELECT 
            loc.borough AS `Borough`,
            COUNT(f.trip_key) AS `Total Trips`,
            ROUND(SUM(f.total_amount), 2) AS `Total Revenue ($)`,
            ROUND(AVG(f.fare_amount), 2) AS `Avg Fare ($)`,
            ROUND(AVG(f.trip_distance), 2) AS `Avg Distance (mi)`
        FROM fact_trip f
        JOIN dim_location loc ON f.pickup_location_key = loc.location_key
        JOIN dim_date d ON f.pickup_date_key = d.date_key
        WHERE {where_clause}
        GROUP BY loc.borough
        ORDER BY `Total Trips` DESC
    """
else:
    sql_geo = f"""
        SELECT 
            loc.borough AS `Borough`,
            loc.zone AS `Pickup Zone`,
            COUNT(f.trip_key) AS `Total Trips`,
            ROUND(SUM(f.total_amount), 2) AS `Total Revenue ($)`,
            ROUND(AVG(f.fare_amount), 2) AS `Avg Fare ($)`,
            ROUND(AVG(f.trip_distance), 2) AS `Avg Distance (mi)`
        FROM fact_trip f
        JOIN dim_location loc ON f.pickup_location_key = loc.location_key
        JOIN dim_date d ON f.pickup_date_key = d.date_key
        WHERE {where_clause}
        GROUP BY loc.borough, loc.zone
        ORDER BY `Total Trips` DESC
        LIMIT 50
    """

df_geo = run_query(sql_geo)
st.dataframe(df_geo, use_container_width=True)

# ==============================================================================
# REPORT 2: Time Hierarchy (Roll-up & Drill-down)
# ==============================================================================
st.header("2. Temporal Performance (Roll-up / Drill-down)")
st.caption("Dimensional Hierarchy: Year ➔ Quarter ➔ Month ➔ Day of Week")

time_granularity = st.selectbox(
    "Drill / Roll Granularity:",
    ["Roll-up to Quarter", "Drill-down to Month", "Drill-down to Day Name"]
)

if time_granularity == "Roll-up to Quarter":
    group_col = "d.quarter"
    select_col = "CONCAT('Q', d.quarter) AS `Period`"
elif time_granularity == "Drill-down to Month":
    group_col = "d.month, d.month_name"
    select_col = "d.month_name AS `Period`"
else:
    group_col = "d.day_of_week, d.day_name"
    select_col = "d.day_name AS `Period`"

sql_time = f"""
    SELECT 
        {select_col},
        COUNT(f.trip_key) AS `Trip Count`,
        ROUND(SUM(f.total_amount), 2) AS `Revenue ($)`,
        ROUND(AVG(f.tip_amount), 2) AS `Avg Tip ($)`
    FROM fact_trip f
    JOIN dim_date d ON f.pickup_date_key = d.date_key
    JOIN dim_location loc ON f.pickup_location_key = loc.location_key
    WHERE {where_clause}
    GROUP BY {group_col}
    ORDER BY MIN(d.date_key)
"""

df_time = run_query(sql_time)
col1, col2 = st.columns([2, 1])
with col1:
    st.dataframe(df_time, use_container_width=True)
with col2:
    if not df_time.empty:
        st.bar_chart(data=df_time.set_index("Period")["Trip Count"])

# ==============================================================================
# REPORT 3: Pivot / Cross-Tabulation
# ==============================================================================
st.header("3. Multi-dimensional Pivot Table")
st.caption("Pivoting: Borough (Rows) vs Day Part (Columns) to analyze Trip Counts")

sql_pivot = f"""
    SELECT 
        loc.borough AS `Borough`,
        COUNT(CASE WHEN t.day_part = 'Morning' THEN 1 END) AS `Morning Trips`,
        COUNT(CASE WHEN t.day_part = 'Midday' THEN 1 END) AS `Midday Trips`,
        COUNT(CASE WHEN t.day_part = 'Evening' THEN 1 END) AS `Evening Trips`,
        COUNT(CASE WHEN t.day_part = 'Overnight' THEN 1 END) AS `Overnight Trips`,
        COUNT(f.trip_key) AS `Total Trips`
    FROM fact_trip f
    JOIN dim_location loc ON f.pickup_location_key = loc.location_key
    JOIN dim_time t ON f.pickup_time_key = t.time_key
    JOIN dim_date d ON f.pickup_date_key = d.date_key
    WHERE {where_clause}
    GROUP BY loc.borough
    ORDER BY `Total Trips` DESC
"""

df_pivot = run_query(sql_pivot)
st.dataframe(df_pivot, use_container_width=True)