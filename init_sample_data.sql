-- Example: create a minimal forecast table (copy for each sheet_name)
CREATE TABLE IF NOT EXISTS farmers_registry_forecast (
    id SERIAL PRIMARY KEY,
    date DATE,
    metric TEXT,
    value NUMERIC
);

INSERT INTO farmers_registry_forecast (date, metric, value) VALUES ('2025-01-01', 'registered_farmers', 1200);
