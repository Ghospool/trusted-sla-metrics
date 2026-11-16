-- PostgreSQL 14+. Run before 002_metrics.sql and before loading data.
SET TIME ZONE 'UTC';

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS raw.pipeline_runs (
    run_id uuid PRIMARY KEY,
    started_at timestamptz NOT NULL DEFAULT current_timestamp,
    finished_at timestamptz,
    status text CHECK (status IN ('running', 'succeeded', 'failed')),
    as_of timestamptz NOT NULL,
    records_received integer DEFAULT 0,
    records_accepted integer DEFAULT 0,
    records_rejected integer DEFAULT 0,
    records_inserted integer DEFAULT 0,
    records_updated integer DEFAULT 0,
    records_unchanged integer DEFAULT 0,
    error text
);

CREATE TABLE IF NOT EXISTS raw.records (
    run_id uuid REFERENCES raw.pipeline_runs (run_id),
    row_number integer,
    entity text,
    payload jsonb,
    PRIMARY KEY (run_id, entity, row_number)
);

CREATE TABLE IF NOT EXISTS raw.rejected_records (
    run_id uuid REFERENCES raw.pipeline_runs (run_id),
    row_number integer,
    entity text,
    payload jsonb,
    reason text
);

CREATE TABLE IF NOT EXISTS staging.teams (
    team_id text PRIMARY KEY,
    team_name text NOT NULL,
    staffing_count integer NOT NULL CHECK (staffing_count >= 0)
);

CREATE TABLE IF NOT EXISTS staging.policies (
    priority text PRIMARY KEY,
    response_target_minutes numeric NOT NULL CHECK (response_target_minutes > 0),
    resolution_target_minutes numeric NOT NULL CHECK (resolution_target_minutes > 0)
);

CREATE TABLE IF NOT EXISTS staging.tickets (
    source_system text NOT NULL,
    ticket_id text NOT NULL,
    created_at timestamptz NOT NULL,
    priority text NOT NULL REFERENCES staging.policies (priority),
    team_id text NOT NULL REFERENCES staging.teams (team_id),
    subject text NOT NULL,
    PRIMARY KEY (source_system, ticket_id)
);

CREATE TABLE IF NOT EXISTS staging.events (
    source_system text NOT NULL,
    event_id text NOT NULL,
    ticket_id text NOT NULL,
    occurred_at timestamptz NOT NULL,
    event_type text NOT NULL CHECK (
        event_type IN ('responded', 'waiting', 'resumed', 'resolved', 'reopened')
    ),
    PRIMARY KEY (source_system, event_id),
    FOREIGN KEY (source_system, ticket_id)
        REFERENCES staging.tickets (source_system, ticket_id)
);

CREATE INDEX IF NOT EXISTS events_ticket_timeline_idx
    ON staging.events (source_system, ticket_id, occurred_at, event_id COLLATE "C");
CREATE INDEX IF NOT EXISTS tickets_created_at_idx
    ON staging.tickets (created_at);
CREATE INDEX IF NOT EXISTS rejected_records_run_idx
    ON raw.rejected_records (run_id);
