
import os
import csv
import tempfile
import pandas as pd

from sqlalchemy import create_engine, text
from time import perf_counter


# ============================================================
# 1. DATABASE CONNECTIONS
# ============================================================

source_engine = create_engine(
    "mysql+pymysql://root:123456@127.0.0.1:3306/nyc_taxi_source",
    connect_args={
        "connect_timeout": 30,
        "read_timeout": 600,
        "write_timeout": 600,
        "local_infile": True
    },
    pool_pre_ping=True
)

target_engine = create_engine(
    "mysql+pymysql://root:123456@127.0.0.1:3306/nyc_taxi_dw",
    connect_args={
        "connect_timeout": 30,
        "read_timeout": 600,
        "write_timeout": 600,
        "local_infile": True
    },
    pool_pre_ping=True
)


# ============================================================
# 2. ETL SETTINGS
# ============================================================

SOURCE_TABLE = "yellow_tripdata"
TARGET_TABLE = "fact_trip"

READ_CHUNK_SIZE = 25_000

# Only 2025 records are needed.
START_DATE = "2025-01-01 00:00:00"
END_DATE = "2026-01-01 00:00:00"


# ============================================================
# 3. SOURCE COLUMNS
# ============================================================

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


# ============================================================
# 4. DATA TYPE CONVERSION
# ============================================================

integer_like_cols = [
    "VendorID",
    "passenger_count",
    "RatecodeID",
    "PULocationID",
    "DOLocationID",
    "payment_type"
]

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


# ============================================================
# 5. DIMENSION KEY MAPPINGS
# ============================================================

vendor_map = {
    1: 1,
    2: 2,
    6: 3,
    7: 4
}

rate_code_map = {
    1: 1,
    2: 2,
    3: 3,
    4: 4,
    5: 5,
    6: 6
}

payment_type_map = {
    0: 0,
    1: 1,
    2: 2,
    3: 3,
    4: 4,
    5: 5,
    6: 6
}

store_fwd_map = {
    "Y": 1,
    "N": 2
}


# ============================================================
# 6. TARGET FACT TABLE COLUMNS
# ============================================================

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


# ============================================================
# 7. TRANSFORM
# ============================================================

def transform(df: pd.DataFrame) -> pd.DataFrame:
    """Clean source data and create fact_trip rows."""

    df = df.rename(
        columns={"Airport_fee": "airport_fee"}
    )

    # Convert datetime columns.
    df["tpep_pickup_datetime"] = pd.to_datetime(
        df["tpep_pickup_datetime"],
        errors="coerce"
    )

    df["tpep_dropoff_datetime"] = pd.to_datetime(
        df["tpep_dropoff_datetime"],
        errors="coerce"
    )

    # Convert numeric columns.
    for col in (
        integer_like_cols
        + ["trip_distance"]
        + financial_cols
    ):
        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    # Retain valid 2025 pickups and non-negative durations.
    df = df[
        df["tpep_pickup_datetime"].ge(START_DATE)
        & df["tpep_pickup_datetime"].lt(END_DATE)
        & df["tpep_dropoff_datetime"].notna()
        & (
            df["tpep_dropoff_datetime"]
            >= df["tpep_pickup_datetime"]
        )
    ].copy()

    if df.empty:
        return pd.DataFrame(columns=fact_columns)

    pickup = df["tpep_pickup_datetime"]
    dropoff = df["tpep_dropoff_datetime"]

    # Date keys: YYYYMMDD.
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

    # Time keys: HHMM.
    df["pickup_time_key"] = (
        pickup.dt.hour * 100
        + pickup.dt.minute
    ).astype("int16")

    df["dropoff_time_key"] = (
        dropoff.dt.hour * 100
        + dropoff.dt.minute
    ).astype("int16")

    # Trip duration in seconds.
    df["trip_duration_seconds"] = (
        (dropoff - pickup)
        .dt.total_seconds()
        .astype("int32")
    )

    # Vendor dimension key.
    df["vendor_key"] = (
        df["VendorID"]
        .map(vendor_map)
        .fillna(0)
        .astype("int16")
    )

    # Rate code dimension key.
    df["rate_code_key"] = (
        df["RatecodeID"]
        .map(rate_code_map)
        .fillna(99)
        .astype("int16")
    )

    # Payment type dimension key.
    df["payment_type_key"] = (
        df["payment_type"]
        .map(payment_type_map)
        .fillna(5)
        .astype("int16")
    )

    # Store-and-forward dimension key.
    df["store_and_fwd_key"] = (
        df["store_and_fwd_flag"]
        .astype("string")
        .str.strip()
        .str.upper()
        .map(store_fwd_map)
        .fillna(0)
        .astype("int16")
    )

    # Location keys.
    df["pickup_location_key"] = (
        df["PULocationID"]
        .fillna(-1)
        .astype("int32")
    )

    df["dropoff_location_key"] = (
        df["DOLocationID"]
        .fillna(-1)
        .astype("int32")
    )

    # Handle missing measures.
    df["passenger_count"] = (
        df["passenger_count"]
        .fillna(0)
        .astype("int16")
    )

    df["trip_distance"] = (
        df["trip_distance"].fillna(0.0)
    )

    df[financial_cols] = (
        df[financial_cols].fillna(0.0)
    )

    # Return the target columns in the required order.
    return df[fact_columns]


# ============================================================
# 8. BULK LOAD INTO MYSQL USING TSV + LOAD DATA
# ============================================================

def bulk_load_fact(df: pd.DataFrame) -> int:
    """
    Write transformed records to a temporary TSV file,
    then bulk-load them into fact_trip.

    Returns the number of rows accepted by LOAD DATA.
    """

    if df.empty:
        return 0

    temp_path = None

    try:
        # Write the chunk to a temporary TSV file.
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".tsv",
            encoding="utf-8",
            newline="",
            delete=False
        ) as temp:

            temp_path = temp.name

            df.to_csv(
                temp,
                sep="\t",
                index=False,
                header=False,
                na_rep=r"\N",
                quoting=csv.QUOTE_MINIMAL,
                quotechar='"',
                doublequote=True,
                lineterminator="\n"
            )

        # MySQL accepts forward slashes in Windows paths.
        sql_path = temp_path.replace("\\", "/")
        sql_path = sql_path.replace("'", "''")

        # Explicitly specify the target columns.
        columns_sql = ", ".join(
            f"`{col}`" for col in fact_columns
        )

        sql = f"""
            LOAD DATA LOCAL INFILE '{sql_path}'
            INTO TABLE `{TARGET_TABLE}`
            CHARACTER SET utf8mb4
            FIELDS TERMINATED BY '\\t'
            OPTIONALLY ENCLOSED BY '"'
            ESCAPED BY '\\\\'
            LINES TERMINATED BY '\\n'
            ({columns_sql})
        """

        # Commit each chunk separately.
        with target_engine.begin() as tgt_conn:
            result = tgt_conn.exec_driver_sql(sql)

            # MySQL reports the number of rows affected.
            inserted = result.rowcount

        return inserted

    finally:
        # Remove the temporary file after the load finishes.
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


# ============================================================
# 9. EXTRACT -> TRANSFORM -> LOAD
# ============================================================

query = text(f"""
    SELECT {", ".join(f"`{col}`" for col in columns)}
    FROM `{SOURCE_TABLE}`
    WHERE `tpep_pickup_datetime` >= :start_date
      AND `tpep_pickup_datetime` < :end_date
""")

start = perf_counter()

read_total = 0
loaded_total = 0
chunk_number = 0

print(
    f"Reading from nyc_taxi_source.{SOURCE_TABLE} ..."
)

try:
    # Stream source results instead of loading the entire
    # source table into memory.
    with source_engine.connect().execution_options(
        stream_results=True,
        yield_per=READ_CHUNK_SIZE
    ) as src_conn:

        chunks = pd.read_sql(
            query,
            src_conn,
            params={
                "start_date": START_DATE,
                "end_date": END_DATE
            },
            chunksize=READ_CHUNK_SIZE
        )

        for chunk in chunks:
            chunk_number += 1
            read_total += len(chunk)

            # Transform this source chunk.
            fact_df = transform(chunk)

            if fact_df.empty:
                elapsed = perf_counter() - start

                print(
                    f"Chunk {chunk_number}: "
                    f"no valid rows | "
                    f"Read {read_total:,} | "
                    f"Loaded {loaded_total:,} | "
                    f"{elapsed:.1f}s elapsed",
                    flush=True
                )

                del chunk, fact_df
                continue

            # Bulk-load transformed rows.
            inserted = bulk_load_fact(fact_df)

            loaded_total += inserted

            elapsed = perf_counter() - start
            rate = loaded_total / elapsed if elapsed else 0

            print(
                f"Chunk {chunk_number} | "
                f"Read {read_total:,} | "
                f"Loaded {loaded_total:,} | "
                f"{elapsed:.1f}s elapsed | "
                f"{rate:,.0f} rows/sec",
                flush=True
            )

            # Release memory before reading the next chunk.
            del chunk, fact_df

    elapsed = perf_counter() - start

    print("\nETL completed successfully.")
    print(f"Source rows read: {read_total:,}")
    print(f"Rows loaded: {loaded_total:,}")
    print(
        f"Rows filtered out: {read_total - loaded_total:,}"
    )
    print(f"Total time: {elapsed:.2f} seconds")

    if elapsed:
        print(
            f"Average load rate: "
            f"{loaded_total / elapsed:,.0f} rows/sec"
        )

except Exception as e:
    elapsed = perf_counter() - start

    print(f"\nETL failed: {e}")
    print(f"Source rows read: {read_total:,}")
    print(
        f"Rows reported loaded this run: {loaded_total:,}"
    )
    print(f"Elapsed time: {elapsed:.2f} seconds")
    print(
        "Previously committed chunks may remain in "
        "fact_trip. Check the actual table count before "
        "attempting another run."
    )

finally:
    source_engine.dispose()
    target_engine.dispose()
