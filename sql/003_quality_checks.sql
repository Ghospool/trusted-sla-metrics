-- Read-only PostgreSQL 14+ checks. Run after 001_schema.sql and 002_metrics.sql.
SET TIME ZONE 'UTC';

-- Expected: zero rows. Events before creation cannot contribute to metrics.
SELECT e.source_system, e.ticket_id, e.event_id, t.created_at, e.occurred_at
FROM staging.events AS e
JOIN staging.tickets AS t
  ON t.source_system = e.source_system AND t.ticket_id = e.ticket_id
WHERE e.occurred_at < t.created_at
ORDER BY e.source_system, e.ticket_id, e.occurred_at, e.event_id COLLATE "C";

-- Expected: zero rows. Validate transitions over the complete loaded history.
-- responded is deliberately absent: it never changes ticket state.
WITH RECURSIVE
ordered_events AS (
    SELECT e.source_system, e.ticket_id, e.event_id, e.occurred_at, e.event_type,
           row_number() OVER (
               PARTITION BY e.source_system, e.ticket_id
               ORDER BY e.occurred_at, e.event_id COLLATE "C"
           ) AS event_sequence
    FROM staging.events AS e
    JOIN staging.tickets AS t
      ON t.source_system = e.source_system AND t.ticket_id = e.ticket_id
    WHERE e.event_type <> 'responded' AND e.occurred_at >= t.created_at
),
walk (source_system, ticket_id, event_sequence, event_id, event_type,
      occurred_at, prior_status, ticket_status, valid_transition) AS (
    SELECT t.source_system, t.ticket_id, 0::bigint, NULL::text, NULL::text,
           t.created_at, 'open'::text, 'open'::text, true
    FROM staging.tickets AS t

    UNION ALL

    SELECT w.source_system, w.ticket_id, e.event_sequence, e.event_id, e.event_type,
           e.occurred_at, w.ticket_status,
           CASE
               WHEN w.ticket_status = 'open' AND e.event_type = 'waiting' THEN 'waiting'
               WHEN w.ticket_status = 'waiting' AND e.event_type = 'resumed' THEN 'open'
               WHEN w.ticket_status = 'open' AND e.event_type = 'resolved' THEN 'resolved'
               WHEN w.ticket_status = 'resolved' AND e.event_type = 'reopened' THEN 'open'
               ELSE w.ticket_status
           END,
           (w.ticket_status, e.event_type) IN (
               ('open', 'waiting'), ('waiting', 'resumed'),
               ('open', 'resolved'), ('resolved', 'reopened')
           )
    FROM walk AS w
    JOIN ordered_events AS e
      ON e.source_system = w.source_system
     AND e.ticket_id = w.ticket_id
     AND e.event_sequence = w.event_sequence + 1
)
SELECT source_system, ticket_id, event_id, occurred_at, event_type, prior_status
FROM walk
WHERE NOT valid_transition
ORDER BY source_system, ticket_id, event_sequence;

-- Expected: zero rows for completed successful runs. Counters cover all entities.
SELECT run_id, records_received, records_accepted, records_rejected,
       records_inserted, records_updated, records_unchanged
FROM raw.pipeline_runs
WHERE status = 'succeeded'
  AND (records_received IS NULL OR records_accepted IS NULL
       OR records_rejected IS NULL OR records_inserted IS NULL
       OR records_updated IS NULL OR records_unchanged IS NULL
       OR records_received < 0 OR records_accepted < 0 OR records_rejected < 0
       OR records_inserted < 0 OR records_updated < 0 OR records_unchanged < 0
       OR records_received::bigint <> records_accepted::bigint + records_rejected::bigint
       OR records_accepted::bigint <> records_inserted::bigint
           + records_updated::bigint + records_unchanged::bigint);

-- Expected: zero rows. Check metric invariants at a reproducible historical cutoff.
SELECT m.*
FROM analytics.ticket_metrics('2025-01-08T00:00:00Z'::timestamptz) AS m
WHERE m.resolution_minutes < 0
   OR m.first_response_minutes < 0
   OR m.backlog_age_minutes < 0
   OR m.reopened_count < 0
   OR (m.current_status = 'resolved' AND m.backlog_age_minutes IS NOT NULL)
   OR (m.current_status <> 'resolved' AND m.backlog_age_minutes IS NULL);

-- Sample metric result: current policies are static, not historical snapshots.
SELECT source_system, ticket_id, priority, team_id, current_status,
       first_response_minutes, resolution_minutes, response_breached,
       resolution_breached, backlog_age_minutes, reopened_count
FROM analytics.ticket_metrics('2025-01-08T00:00:00Z'::timestamptz)
ORDER BY source_system, ticket_id;

-- Pipeline audit, including the actual persisted raw and rejection row counts.
SELECT p.run_id, p.started_at, p.finished_at, p.status, p.as_of,
       p.records_received, p.records_accepted, p.records_rejected,
       p.records_inserted, p.records_updated, p.records_unchanged, p.error,
       (SELECT count(*) FROM raw.records AS r WHERE r.run_id = p.run_id)
           AS raw_row_count,
       (SELECT count(*) FROM raw.rejected_records AS r WHERE r.run_id = p.run_id)
           AS rejected_row_count
FROM raw.pipeline_runs AS p
ORDER BY p.started_at DESC, p.run_id;
