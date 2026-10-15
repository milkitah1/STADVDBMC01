
-- ---------------------------------------------------------------------
-- DIMENSIONS
-- ---------------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS nyc_taxi_dw;
USE nyc_taxi_dw;

CREATE TABLE dim_date (
    date_key        INT PRIMARY KEY,          -- yyyymmdd
    full_date       DATE NOT NULL,
    year            SMALLINT NOT NULL,
    quarter         SMALLINT NOT NULL,
    month           SMALLINT NOT NULL,
    month_name      VARCHAR(10) NOT NULL,
    day_of_month    SMALLINT NOT NULL,
    day_of_week     SMALLINT NOT NULL,        -- 1 = Monday
    day_name        VARCHAR(10) NOT NULL,
    is_weekend      BOOLEAN NOT NULL,
    is_holiday      BOOLEAN NOT NULL,
    holiday_name    VARCHAR(50) 
);

CREATE TABLE dim_time (
    time_key        INT PRIMARY KEY,          -- seconds since midnight (0-86399) or hhmm
    hour_24         SMALLINT NOT NULL,
    minute          SMALLINT NOT NULL,
    day_part        VARCHAR(12) NOT NULL      -- Overnight / Morning / Midday / Evening
);

CREATE TABLE dim_vendor (
    vendor_key      SMALLINT PRIMARY KEY,
    vendor_id       SMALLINT NOT NULL UNIQUE, -- VendorID from source
    vendor_name     VARCHAR(60) NOT NULL
);

CREATE TABLE dim_rate_code (
    rate_code_key   SMALLINT PRIMARY KEY,
    rate_code_id    SMALLINT NOT NULL UNIQUE, -- RatecodeID from source
    rate_code_desc  VARCHAR(40) NOT NULL
);

CREATE TABLE dim_payment_type (
    payment_type_key  SMALLINT PRIMARY KEY,
    payment_type_id   SMALLINT NOT NULL UNIQUE,  -- payment_type from source
    payment_type_desc VARCHAR(30) NOT NULL
);

CREATE TABLE dim_store_and_fwd (
    store_and_fwd_key  SMALLINT PRIMARY KEY,
    store_and_fwd_flag CHAR(1) NOT NULL UNIQUE,  -- Y / N
    description        VARCHAR(40) NOT NULL
);

-- Role-playing dimension: joined twice (pickup and dropoff)
-- Load from the TLC Taxi Zone Lookup table
CREATE TABLE dim_location (
    location_key    SMALLINT PRIMARY KEY,
    location_id     SMALLINT NOT NULL UNIQUE, -- PULocationID / DOLocationID
    borough         VARCHAR(30),
    zone            VARCHAR(80),
    service_zone    VARCHAR(30),
    is_airport      BOOLEAN                   -- LGA, JFK, EWR zones
);

-- ---------------------------------------------------------------------
-- FACT
-- ---------------------------------------------------------------------

CREATE TABLE fact_trip (
    trip_key               BIGINT PRIMARY KEY AUTO_INCREMENT,   -- surrogate key

    -- Foreign keys to dimensions
    pickup_date_key        INT      NOT NULL REFERENCES dim_date(date_key),
    pickup_time_key        INT      NOT NULL REFERENCES dim_time(time_key),
    dropoff_date_key       INT      NOT NULL REFERENCES dim_date(date_key),
    dropoff_time_key       INT      NOT NULL REFERENCES dim_time(time_key),
    vendor_key             SMALLINT NOT NULL REFERENCES dim_vendor(vendor_key),
    rate_code_key          SMALLINT NOT NULL REFERENCES dim_rate_code(rate_code_key),
    payment_type_key       SMALLINT NOT NULL REFERENCES dim_payment_type(payment_type_key),
    store_and_fwd_key      SMALLINT NOT NULL REFERENCES dim_store_and_fwd(store_and_fwd_key),
    pickup_location_key    SMALLINT NOT NULL REFERENCES dim_location(location_key),
    dropoff_location_key   SMALLINT NOT NULL REFERENCES dim_location(location_key),

    -- Exact timestamps kept for precision (dims hold only date/time-of-day)
    tpep_pickup_datetime   TIMESTAMP NOT NULL,
    tpep_dropoff_datetime  TIMESTAMP NOT NULL,

    -- Measures
    passenger_count        SMALLINT,
    trip_distance          DECIMAL(9,2),         -- miles
    trip_duration_seconds  INT,                  -- derived: dropoff - pickup
    fare_amount            DECIMAL(10,2),
    extra                  DECIMAL(10,2),
    mta_tax                DECIMAL(10,2),
    tip_amount             DECIMAL(10,2),        -- credit card tips only
    tolls_amount           DECIMAL(10,2),
    improvement_surcharge  DECIMAL(10,2),
    congestion_surcharge   DECIMAL(10,2),
    airport_fee            DECIMAL(10,2),
    cbd_congestion_fee     DECIMAL(10,2),        -- NULL/0 before 2025-01-05
    total_amount           DECIMAL(10,2)         -- excludes cash tips
);

CREATE INDEX ix_fact_trip_pickup_date ON fact_trip(pickup_date_key);
CREATE INDEX ix_fact_trip_pu_loc      ON fact_trip(pickup_location_key);
CREATE INDEX ix_fact_trip_do_loc      ON fact_trip(dropoff_location_key);

-- ---------------------------------------------------------------------
-- SEED DATA for the code-based dimensions (from the data dictionary)
-- ---------------------------------------------------------------------

INSERT INTO dim_vendor VALUES
    (1, 1, 'Creative Mobile Technologies, LLC'),
    (2, 2, 'Curb Mobility, LLC'),
    (3, 6, 'Myle Technologies Inc'),
    (4, 7, 'Helix'),
    (0, -1, 'Unknown');

INSERT INTO dim_rate_code VALUES
    (1, 1,  'Standard rate'),
    (2, 2,  'JFK'),
    (3, 3,  'Newark'),
    (4, 4,  'Nassau or Westchester'),
    (5, 5,  'Negotiated fare'),
    (6, 6,  'Group ride'),
    (99, 99, 'Null/unknown');

INSERT INTO dim_payment_type VALUES
    (0, 0, 'Flex Fare trip'),
    (1, 1, 'Credit card'),
    (2, 2, 'Cash'),
    (3, 3, 'No charge'),
    (4, 4, 'Dispute'),
    (5, 5, 'Unknown'),
    (6, 6, 'Voided trip');

INSERT INTO dim_store_and_fwd VALUES
    (1, 'Y', 'Store and forward trip'),
    (2, 'N', 'Not a store and forward trip'),
    (0, '?', 'Unknown');