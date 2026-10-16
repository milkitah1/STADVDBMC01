import pandas as pd
from sqlalchemy import create_engine, text
from time import perf_counter

# 1. DATABASE CONNECTIONS
source_engine = create_engine(
    "mysql+pymysql://root:123456@127.0.0.1:3306/nyc_taxi_source",
    pool_pre_ping=True
)

target_engine = create_engine(
    "mysql+pymysql://root:123456@127.0.0.1:3306/nyc_taxi_dw",
    pool_pre_ping=True
)

SOURCE_TABLE = "yellow_tripdata"
READ_CHUNK_SIZE = 100_000
INSERT_BATCH_SIZE = 20000

# 2. SOURCE COLUMNS
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

# Columns that arrive as text from the source table and need numeric casting
integer_like_cols = [
    "VendorID", "passenger_count", "RatecodeID",
    "PULocationID", "DOLocationID", "payment_type"
]

financial_cols = [
    "fare_amount", "extra", "mta_tax", "tip_amount", "tolls_amount",
    "improvement_surcharge", "congestion_surcharge", "airport_fee",
    "cbd_congestion_fee", "total_amount"
]

# 3. DIMENSION KEY MAPPINGS
vendor_map = {1: 1, 2: 2, 6: 3, 7: 4}
rate_code_map = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6}
payment_type_map = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6}
store_fwd_map = {"Y": 1, "N": 2}

fact_columns = [
    "pickup_date_key", "pickup_time_key",
    "dropoff_date_key", "dropoff_time_key",
    "vendor_key", "rate_code_key", "payment_type_key", "store_and_fwd_key",
    "pickup_location_key", "dropoff_location_key",
    "tpep_pickup_datetime", "tpep_dropoff_datetime",
    "passenger_count", "trip_distance", "trip_duration_seconds",
    "fare_amount", "extra", "mta_tax", "tip_amount", "tolls_amount",
    "improvement_surcharge", "congestion_surcharge", "airport_fee",
    "cbd_congestion_fee", "total_amount"
]


def transform(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and shape one chunk of source rows into fact_trip rows."""

    df = df.rename(columns={"Airport_fee": "airport_fee"})

    # Cast text columns to proper types
    df["tpep_pickup_datetime"] = pd.to_datetime(
        df["tpep_pickup_datetime"], errors="coerce"
    )
    df["tpep_dropoff_datetime"] = pd.to_datetime(
        df["tpep_dropoff_datetime"], errors="coerce"
    )

    for col in integer_like_cols + ["trip_distance"] + financial_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Filter invalid records early (NaT comparisons evaluate to False)
    df = df[
        df["tpep_pickup_datetime"].dt.year.eq(2025)
        & (df["tpep_dropoff_datetime"] >= df["tpep_pickup_datetime"])
    ].copy()

    if df.empty:
        return df

    pickup = df["tpep_pickup_datetime"]
    dropoff = df["tpep_dropoff_datetime"]

    # Date keys: YYYYMMDD
    df["pickup_date_key"] = (
        pickup.dt.year * 10000 + pickup.dt.month * 100 + pickup.dt.day
    ).astype("int32")
    df["dropoff_date_key"] = (
        dropoff.dt.year * 10000 + dropoff.dt.month * 100 + dropoff.dt.day
    ).astype("int32")

    # Time keys: HHMM
    df["pickup_time_key"] = (
        pickup.dt.hour * 100 + pickup.dt.minute
    ).astype("int16")
    df["dropoff_time_key"] = (
        dropoff.dt.hour * 100 + dropoff.dt.minute
    ).astype("int16")

    # Trip duration
    df["trip_duration_seconds"] = (
        (dropoff - pickup).dt.total_seconds().astype("int32")
    )

    # Dimension keys
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
        .astype("string")
        .str.strip()
        .str.upper()
        .map(store_fwd_map)
        .fillna(0)
        .astype("int16")
    )
    df["pickup_location_key"] = df["PULocationID"].fillna(-1).astype("int32")
    df["dropoff_location_key"] = df["DOLocationID"].fillna(-1).astype("int32")

    # Null measures
    df["passenger_count"] = df["passenger_count"].fillna(0).astype("int16")
    df["trip_distance"] = df["trip_distance"].fillna(0.0)
    df[financial_cols] = df[financial_cols].fillna(0.0)

    return df[fact_columns]


# 4. EXTRACT -> TRANSFORM -> LOAD, CHUNK BY CHUNK
query = text(f"SELECT {', '.join(columns)} FROM {SOURCE_TABLE}")

start = perf_counter()
read_total = 0
loaded_total = 0

print(f"Reading from nyc_taxi_source.{SOURCE_TABLE} ...")

try:
    # stream_results keeps rows server-side so the whole table isn't loaded at once
    with source_engine.connect().execution_options(stream_results=True) as src_conn:
        chunks = pd.read_sql(query, src_conn, chunksize=READ_CHUNK_SIZE)

        for chunk in chunks:
            read_total += len(chunk)
            fact_df = transform(chunk)

            if fact_df.empty:
                continue

            with target_engine.begin() as tgt_conn:
                fact_df.to_sql(
                    name="fact_trip",
                    con=tgt_conn,
                    if_exists="append",
                    index=False,
                    chunksize=INSERT_BATCH_SIZE,
                    method=None
                )

            loaded_total += len(fact_df)
            elapsed = perf_counter() - start
            print(
                f"Read {read_total:,} | Loaded {loaded_total:,} | "
                f"{elapsed:.1f}s elapsed | "
                f"{loaded_total / elapsed:,.0f} rows/sec",
                flush=True
            )

    print(f"Done. Read {read_total:,}, loaded {loaded_total:,}, "
          f"rejected {read_total - loaded_total:,}.")
    print(f"Total time: {perf_counter() - start:.2f}s")

except Exception as e:
    print(f"Load failed: {e}")
    print(f"Successfully committed in this run: {loaded_total:,}")

finally:
    source_engine.dispose()
    target_engine.dispose()