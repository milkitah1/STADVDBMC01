# STADVDBMC01

here's what i ran in order:

- taxi_source.sql (inside mysqlworkbench)
- load_source.py
- taxi.sql (inside mysqlworkbench)
- load_dim_tables.ipynb
- load_warehouse.py

- RUN in MySQL before app.py:

[1] 
CREATE INDEX ix_fact_trip_loc_date_pay_time 
ON fact_trip (
    pickup_location_key, 
    pickup_date_key, 
    payment_type_key, 
    pickup_time_key, 
    total_amount, 
    fare_amount, 
    trip_distance, 
    tip_amount
);

[2] 
CREATE TABLE fact_trip_denorm AS
SELECT
    f.pickup_date_key,
    f.pickup_location_key,
    loc.borough,
    f.payment_type_key,
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
JOIN dim_location loc ON f.pickup_location_key = loc.location_key
GROUP BY f.pickup_date_key, f.pickup_location_key, loc.borough, f.payment_type_key, day_part;

- app.py


