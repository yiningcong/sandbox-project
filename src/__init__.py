"""DAU ETL interview prototype.

Local-mock mapping to production services:

    PostgreSQL accounts  ->  CSV export   (src/ingestion/postgres.py)
    Elasticsearch sessions -> NDJSON      (src/ingestion/elasticsearch.py)
    BigQuery warehouse    ->  DuckDB      (src/warehouse.py)

See README.md and docs/ for architecture, assumptions and how to run.
"""
