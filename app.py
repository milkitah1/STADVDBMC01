import time      # to measure how long the database query takes
import calendar  # used to find the last day of each month
import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text

# Sets page title and layout
st.set_page_config(page_title="NYC Taxi OLAP Dashboard", layout="wide")

# Database Connection
# @st.cache_resource = create the connection ONCE so we can reuse it
@st.cache_resource
def get_engine():
    # MySQL credentials
    return create_engine("mysql+pymysql://root:123456@127.0.0.1:3306/nyc_taxi_dw")

engine = get_engine()

# CACHING
# @st.cache_data remembers the result of each query for 10 minutes (ttl=600).
# If the exact same SQL Query runs again, the saved result is returned instantly.
@st.cache_data(ttl=600)
def run_query(sql, params=None):
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)

st.title("🚖 NYC Yellow Taxi OLAP Dashboard (2025)")
st.write("Perform multi-dimensional analysis with Roll-up, Drill-down, Slice, Dice, and Pivot.")

# SIDEBAR FILTERS (Slice & Dice Controls)
st.sidebar.header("🔍 OLAP Slice & Dice Filters")

# Fetch lookup data for filter dropdowns (cached, so it only runs once)
@st.cache_data
def get_filter_options():
    boroughs = run_query("SELECT DISTINCT borough FROM dim_location WHERE borough != 'Unknown' ORDER BY borough")['borough'].tolist()
    vendors = run_query("SELECT vendor_key, vendor_name FROM dim_vendor WHERE vendor_key != 0 ORDER BY vendor_key")
    payments = run_query("SELECT payment_type_key, payment_type_desc FROM dim_payment_type ORDER BY payment_type_key")
    return boroughs, vendors, payments

all_boroughs, df_vendors, df_payments = get_filter_options()
payment_options = dict(zip(df_payments['payment_type_desc'], df_payments['payment_type_key']))

# FILTER FORM
# Inside the form, nothing runs until you press "Apply filters".
with st.sidebar.form("filters"):
    # Borough selection
    selected_boroughs = st.multiselect(
        "Pickup Boroughs (Dice/Slice):",
        options=all_boroughs,
        default=all_boroughs[:2] if all_boroughs else []
    )

    # Month selection
    selected_months = st.multiselect(
        "Months (Dice/Slice):",
        options=list(range(1, 13)),
        default=[1, 2]
    )

    # Payment Type
    selected_payments = st.multiselect(
        "Payment Types (Dice/Slice):",
        options=list(payment_options.keys()),
        default=["Credit card", "Cash"]
    )

    st.form_submit_button("Apply filters")

conditions = ["1=1"]

if selected_boroughs:
    b_list = "', '".join(selected_boroughs)
    conditions.append(
        f"f.pickup_location_key IN "
        f"(SELECT location_key FROM dim_location WHERE borough IN ('{b_list}'))"
    )

if selected_months:
    month_ranges = []
    for m in selected_months:
        last_day = calendar.monthrange(2025, m)[1]
        month_ranges.append(
            f"f.pickup_date_key BETWEEN 2025{m:02d}01 AND 2025{m:02d}{last_day}"
        )
    conditions.append("(" + " OR ".join(month_ranges) + ")")

if selected_payments:
    p_ids = [str(payment_options[p]) for p in selected_payments]
    conditions.append(f"f.payment_type_key IN ({', '.join(p_ids)})")

where_clause = " AND ".join(conditions)

# ONE DATABASE SCAN FOR ALL THREE REPORTS
base_sql = f"""
    SELECT
        f.pickup_date_key,
        f.pickup_location_key,
        CASE
            WHEN f.pickup_time_key < 600  THEN 'Overnight'
            WHEN f.pickup_time_key < 1200 THEN 'Morning'
            WHEN f.pickup_time_key < 1700 THEN 'Midday'
            ELSE 'Evening'
        END AS day_part,
        COUNT(*)             AS trips,
        SUM(f.total_amount)  AS revenue,
        SUM(f.fare_amount)   AS fare_sum,
        SUM(f.trip_distance) AS dist_sum,
        SUM(f.tip_amount)    AS tip_sum
    FROM fact_trip f
    WHERE {where_clause}
    GROUP BY f.pickup_date_key, f.pickup_location_key, day_part
"""

# Run the one big query and time it
start = time.perf_counter()
with st.spinner("Loading data from the warehouse..."):
    base = run_query(base_sql)
elapsed = time.perf_counter() - start
st.caption(f"⏱️ Database query time: {elapsed:.2f} seconds (cached runs show ~0 seconds)")

# Stop early if the filters match nothing
if base.empty:
    st.warning("No trips match these filters. Try selecting more options.")
    st.stop()

# Database sums come back as Decimal objects- convert to normal numbers for pandas
sum_cols = ["trips", "revenue", "fare_sum", "dist_sum", "tip_sum"]
base[sum_cols] = base[sum_cols].astype(float)

# Small dimension tables cached so they load only once
df_loc = run_query("SELECT location_key, borough, zone FROM dim_location")
df_date = run_query(
    "SELECT date_key, quarter, month, month_name, day_of_week, day_name FROM dim_date"
)

# Attach borough/zone names and calendar info to our small result table
base = base.merge(df_loc, left_on="pickup_location_key", right_on="location_key")
base = base.merge(df_date, left_on="pickup_date_key", right_on="date_key")

# Report 1: Location Hierarchy (Roll-up & Drill-down)
st.header("1. Geographic Analysis (Roll-up / Drill-down)")
st.caption("Dimensional Hierarchy: All NYC ➔ Borough ➔ Zone")

geo_granularity = st.radio(
    "Select Granularity Level:",
    options=["Roll-up (Borough Level)", "Drill-down (Borough + Zone Level)"],
    horizontal=True
)

if "Roll-up" in geo_granularity:
    group_cols = ["borough"]             # Roll-up= less detail
else:
    group_cols = ["borough", "zone"]     # Drill-down=more detail

# Add up the numbers for each group, then calculate the averages
df_geo = base.groupby(group_cols, as_index=False)[sum_cols].sum()
df_geo["Avg Fare ($)"] = (df_geo["fare_sum"] / df_geo["trips"]).round(2)
df_geo["Avg Distance (mi)"] = (df_geo["dist_sum"] / df_geo["trips"]).round(2)
df_geo["Total Revenue ($)"] = df_geo["revenue"].round(2)
df_geo["Total Trips"] = df_geo["trips"].astype(int)

# Sort, rename, and keep only the columns we want to show
df_geo = df_geo.sort_values("Total Trips", ascending=False)
df_geo = df_geo.rename(columns={"borough": "Borough", "zone": "Pickup Zone"})
name_cols = ["Borough"] if len(group_cols) == 1 else ["Borough", "Pickup Zone"]
df_geo = df_geo[name_cols + ["Total Trips", "Total Revenue ($)", "Avg Fare ($)", "Avg Distance (mi)"]]

# Drill-down shows only the top 50 zones
st.dataframe(df_geo.head(50), use_container_width=True)

# REPORT 2: Time Hierarchy (Roll-up & Drill-down)
st.header("2. Temporal Performance (Roll-up / Drill-down)")
st.caption("Dimensional Hierarchy: Year ➔ Quarter ➔ Month ➔ Day of Week")

time_granularity = st.selectbox(
    "Drill / Roll Granularity:",
    ["Roll-up to Quarter", "Drill-down to Month", "Drill-down to Day Name"]
)

# Pick which calendar column to group by, depending on the chosen level
if time_granularity == "Roll-up to Quarter":
    group_cols = ["quarter"]
elif time_granularity == "Drill-down to Month":
    group_cols = ["month", "month_name"]
else:
    group_cols = ["day_of_week", "day_name"]

df_time = base.groupby(group_cols, as_index=False)[sum_cols].sum()
df_time = df_time.sort_values(group_cols[0])   # keep calendar order

# Build the "Period" label shown in the table and chart
if time_granularity == "Roll-up to Quarter":
    df_time["Period"] = "Q" + df_time["quarter"].astype(str)
elif time_granularity == "Drill-down to Month":
    df_time["Period"] = df_time["month_name"]
else:
    df_time["Period"] = df_time["day_name"]

df_time["Trip Count"] = df_time["trips"].astype(int)
df_time["Revenue ($)"] = df_time["revenue"].round(2)
df_time["Avg Tip ($)"] = (df_time["tip_sum"] / df_time["trips"]).round(2)
df_time = df_time[["Period", "Trip Count", "Revenue ($)", "Avg Tip ($)"]]

col1, col2 = st.columns([2, 1])
with col1:
    st.dataframe(df_time, use_container_width=True)
with col2:
    if not df_time.empty:
        st.bar_chart(data=df_time.set_index("Period")["Trip Count"])

# REPORT 3: Pivot / Cross-Tabulation
st.header("3. Multi-dimensional Pivot Table")
st.caption("Pivoting: Borough (Rows) vs Day Part (Columns) to analyze Trip Counts")

# Pivot: boroughs become rows, day parts become columns
df_pivot = base.pivot_table(
    index="borough",
    columns="day_part",
    values="trips",
    aggfunc="sum",
    fill_value=0
)

# Makes sure all four columns exist and are in a sensible order
df_pivot = df_pivot.reindex(columns=["Morning", "Midday", "Evening", "Overnight"], fill_value=0)
df_pivot["Total Trips"] = df_pivot.sum(axis=1)
df_pivot = df_pivot.sort_values("Total Trips", ascending=False).astype(int)

# Rename columns to match the original report, and turn the index back into a column
df_pivot = df_pivot.rename(columns={
    "Morning": "Morning Trips",
    "Midday": "Midday Trips",
    "Evening": "Evening Trips",
    "Overnight": "Overnight Trips"
})
df_pivot.index.name = "Borough"
df_pivot = df_pivot.reset_index()

st.dataframe(df_pivot, use_container_width=True)