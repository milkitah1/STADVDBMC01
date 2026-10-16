
import pandas as pd
from sqlalchemy import create_engine
from time import perf_counter

# 1. DATABASE CONNECTION
engine = create_engine(
    "mysql+pymysql://root:123456@127.0.0.1:3306/nyc_taxi_dw",
    pool_pre_ping=True
)

parquet_file = "yellow_tripdata_2025-01.parquet"

# 2. READ ONLY THE REQUIRED SOURCE COLUMNS
columns = [
    "VendorID",
    "tpep_pickup_datetime",
    "tpep_dropoff_datetime",
    "passenger_count",
    "trip_distance",
    "RatecodeID",
    "store_and_fwd_flag",
    "PULocationID",
    "DOLocationID",
    "payment_type",
    "fare_amount",
    "extra",
    "mta_tax",
    "tip_amount",
    "tolls_amount",
    "improvement_surcharge",
    "congestion_surcharge",
    "Airport_fee",
    "cbd_congestion_fee",
    "total_amount"
]

start = perf_counter()

df = pd.read_parquet(
    parquet_file,
    columns=columns
)

print(f"Read {len(df):,} source records.")

# Standardize column names
df = df.rename(columns={
    "Airport_fee": "airport_fee"
})

# 3. FILTER INVALID RECORDS EARLY
df["tpep_pickup_datetime"] = pd.to_datetime(
    df["tpep_pickup_datetime"]
)
df["tpep_dropoff_datetime"] = pd.to_datetime(
    df["tpep_dropoff_datetime"]
)

df = df[
    df["tpep_pickup_datetime"].dt.year.eq(2025)
    & (
        df["tpep_dropoff_datetime"]
        >= df["tpep_pickup_datetime"]
    )
].copy()

print(f"Valid records: {len(df):,}")

# 4. DATE KEYS: YYYYMMDD
pickup = df["tpep_pickup_datetime"]
dropoff = df["tpep_dropoff_datetime"]

df["pickup_date_key"] = (
    pickup.dt.year * 10000
    + pickup.dt.month * 100
    + pickup.dt.day
).astype("int32")

df["dropoff_date_key"] = (
    dropoff.dt.year * 10000
    + dropoff.dt.month * 100
    + dropoff.dt.day
).astype("int32")

# 5. TIME KEYS: HHMM
df["pickup_time_key"] = (
    pickup.dt.hour * 100 + pickup.dt.minute
).astype("int16")

df["dropoff_time_key"] = (
    dropoff.dt.hour * 100 + dropoff.dt.minute
).astype("int16")

# Trip duration
df["trip_duration_seconds"] = (
    dropoff - pickup
).dt.total_seconds().astype("int32")

# 6. DIMENSION KEY MAPPINGS
vendor_map = {1: 1, 2: 2, 6: 3, 7: 4}

rate_code_map = {
    1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6
}

payment_type_map = {
    0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6
}

store_fwd_map = {"Y": 1, "N": 2}

df["vendor_key"] = (
    df["VendorID"].map(vendor_map).fillna(0).astype("int16")
)

df["rate_code_key"] = (
    df["RatecodeID"].map(rate_code_map).fillna(99).astype("int16")
)

df["payment_type_key"] = (
    df["payment_type"].map(payment_type_map).fillna(5).astype("int16")
)

df["store_and_fwd_key"] = (
    df["store_and_fwd_flag"]
    .str.strip()
    .map(store_fwd_map)
    .fillna(0)
    .astype("int16")
)

df["pickup_location_key"] = (
    df["PULocationID"].fillna(-1).astype("int32")
)

df["dropoff_location_key"] = (
    df["DOLocationID"].fillna(-1).astype("int32")
)

# 7. HANDLE NULL MEASURES
df["passenger_count"] = (
    df["passenger_count"].fillna(0).astype("int16")
)

financial_cols = [
    "fare_amount",
    "extra",
    "mta_tax",
    "tip_amount",
    "tolls_amount",
    "improvement_surcharge",
    "congestion_surcharge",
    "airport_fee",
    "cbd_congestion_fee",
    "total_amount"
]

df[financial_cols] = df[financial_cols].fillna(0.0)

# 8. PREPARE FACT TABLE
fact_columns = [
    "pickup_date_key",
    "pickup_time_key",
    "dropoff_date_key",
    "dropoff_time_key",
    "vendor_key",
    "rate_code_key",
    "payment_type_key",
    "store_and_fwd_key",
    "pickup_location_key",
    "dropoff_location_key",
    "tpep_pickup_datetime",
    "tpep_dropoff_datetime",
    "passenger_count",
    "trip_distance",
    "trip_duration_seconds",
    "fare_amount",
    "extra",
    "mta_tax",
    "tip_amount",
    "tolls_amount",
    "improvement_surcharge",
    "congestion_surcharge",
    "airport_fee",
    "cbd_congestion_fee",
    "total_amount"
]

fact_df = df[fact_columns]

print(f"Prepared {len(fact_df):,} records.")
print(f"Preparation time: {perf_counter() - start:.2f} seconds")

# 9. BATCHED LOAD INTO MYSQL

load_start = perf_counter()

batch_size = 5000
total_records = len(fact_df)
loaded_records = 0

print(f"Starting MySQL load: {total_records:,} records")

try:
    for start_row in range(0, total_records, batch_size):
        end_row = min(start_row + batch_size, total_records)
        batch = fact_df.iloc[start_row:end_row]

        with engine.begin() as connection:
            batch.to_sql(
                name="fact_trip",
                con=connection,
                if_exists="append",
                index=False,
                method=None
            )

        loaded_records += len(batch)

        elapsed = perf_counter() - load_start
        rate = loaded_records / elapsed

        print(
            f"Progress: {loaded_records:,}/{total_records:,} "
            f"({loaded_records / total_records:.1%}) | "
            f"{elapsed:.1f}s elapsed | "
            f"{rate:,.0f} rows/sec",
            flush=True
        )

    print(f"Loading completed in {perf_counter() - load_start:.2f}s")

except Exception as e:
    print(f"Load failed: {e}")
    print(f"Successfully committed in this run: {loaded_records:,}")

finally:
    engine.dispose()
