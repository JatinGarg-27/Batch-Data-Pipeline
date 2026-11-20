-- Upsert customers on the natural key (customer_id is UNIQUE in dim_customer).
-- New customers get a fresh surrogate customer_key; existing ones are updated
-- in place (SCD type 1) and keep their key, so facts never need re-pointing.
INSERT INTO dim_customer
    (customer_id, first_name, last_name, email, gender, city, state, signup_date,
     acquisition_channel)
SELECT customer_id, first_name, last_name, email, gender, city, state, signup_date,
       acquisition_channel
FROM stg_customers AS s
ON DUPLICATE KEY UPDATE
    first_name          = s.first_name,
    last_name           = s.last_name,
    email               = s.email,
    gender              = s.gender,
    city                = s.city,
    state               = s.state,
    signup_date         = s.signup_date,
    acquisition_channel = s.acquisition_channel;
