
import os
import csv
import tempfile
import pandas as pd
import pyarrow.parquet as pq

from sqlalchemy import create_engine
from time import perf_counter

# 1. Connect to the local MySQL SOURCE database
source_engine = create_engine(
    "mysql+pymysql://root:123456@127.0.0.1:3306/nyc_taxi_source",
    connect_args={"local_infile": True},
    pool_pre_ping=True
)

start = perf_counter()
batch_size = 10000

total_loaded = 0
table_created = False

try:
    # 2. Process all 12 months of 2025
    for month in range(1, 13):

        parquet_file = f"yellow_tripdata_2025-{month:02d}.parquet"

        if not os.path.exists(parquet_file):
            print(f"File not found, skipping: {parquet_file}")
            continue

        parquet = pq.ParquetFile(parquet_file)
        file_rows = parquet.metadata.num_rows
        file_loaded = 0

        print(f"\nImporting {parquet_file}")
        print(f"Records in file: {file_rows:,}")

        # 3. Read the Parquet file in small batches
        for batch in parquet.iter_batches(batch_size=batch_size):
            df = batch.to_pandas()

            # Create the table once using the first batch's schema
            if not table_created:
                df.head(0).to_sql(
                    name="yellow_tripdata",
                    con=source_engine,
                    if_exists="replace",
                    index=False
                )
                table_created = True

            # 4. Write this batch to a temporary TSV file
            temp_path = None

            try:
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

                # MySQL accepts forward slashes in Windows paths
                sql_path = temp_path.replace("\\", "/")
                sql_path = sql_path.replace("'", "''")

                # 5. Bulk-load the temporary file into MySQL
                sql = f"""
                    LOAD DATA LOCAL INFILE '{sql_path}'
                    INTO TABLE yellow_tripdata
                    CHARACTER SET utf8mb4
                    FIELDS TERMINATED BY '\\t'
                    OPTIONALLY ENCLOSED BY '"'
                    ESCAPED BY '\\\\'
                    LINES TERMINATED BY '\\n'
                """

                with source_engine.begin() as conn:
                    conn.exec_driver_sql(sql)

            finally:
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)

            # 6. Track import progress
            file_loaded += len(df)
            total_loaded += len(df)

            elapsed = perf_counter() - start
            rate = total_loaded / elapsed if elapsed else 0

            print(
                f"\rFile: {file_loaded:,}/{file_rows:,} "
                f"| Total: {total_loaded:,} "
                f"| {rate:,.0f} rows/sec",
                end="",
                flush=True
            )

            # Release the current batch before reading the next one
            del df, batch

        print(f"\nFinished {parquet_file}: {file_loaded:,} rows")

    elapsed = perf_counter() - start

    print("\nImport finished.")
    print(f"Total records imported: {total_loaded:,}")
    print(f"Total time: {elapsed:.2f} seconds")
    print(
        f"Average speed: "
        f"{total_loaded / elapsed:,.0f} rows/sec"
        if elapsed else "No records imported."
    )

finally:
    source_engine.dispose()
