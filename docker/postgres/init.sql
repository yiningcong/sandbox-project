-- Accounts table for the optional production Postgres service.
-- The local prototype instead reads data/sample/accounts.csv (the same shape).
CREATE TABLE IF NOT EXISTS accounts (
  user_id    TEXT PRIMARY KEY,
  country    TEXT,
  created_at TIMESTAMPTZ,   -- prototype addition (not in the assignment)
  updated_at TIMESTAMPTZ    -- prototype addition
);
