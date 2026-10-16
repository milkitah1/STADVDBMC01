CREATE DATABASE IF NOT EXISTS nyc_taxi_source;
SET GLOBAL local_infile = 1;

CREATE INDEX idx_pickup_datetime
ON nyc_taxi_source.yellow_tripdata (tpep_pickup_datetime);

SET GLOBAL net_read_timeout = 600;
SET GLOBAL net_write_timeout = 600;
