-- PostgreSQL 14+. Requires 001_schema.sql.
SET TIME ZONE 'UTC';

CREATE OR REPLACE FUNCTION analytics.ticket_metrics(p_as_of timestamptz)
RETURNS TABLE (
    source_system text,
    ticket_id text,
    priority text,
    team_id text,
    current_status text,
    first_response_minutes numeric,
    resolution_minutes numeric,
    response_breached boolean,
    resolution_breached boolean,
    backlog_age_minutes numeric,
    reopened_count bigint
)
LANGUAGE sql
STABLE
STRICT
SET TimeZone = 'UTC'
AS $function$
WITH RECURSIVE
eligible_tickets AS (
    SELECT t.source_system, t.ticket_id, t.created_at, t.priority, t.team_id
    FROM staging.tickets AS t
    WHERE t.created_at <= p_as_of
),
eligible_events AS MATERIALIZED (
    SELECT e.source_system, e.ticket_id, e.event_id, e.occurred_at, e.event_type
    FROM staging.events AS e
    JOIN eligible_tickets AS t
      ON t.source_system = e.source_system AND t.ticket_id = e.ticket_id
    WHERE e.occurred_at >= t.created_at
      AND e.occurred_at <= p_as_of
),
-- Responses measure calendar time, never reset or otherwise change state.
responses AS (
    SELECT e.source_system, e.ticket_id, min(e.occurred_at) AS first_responded_at
    FROM eligible_events AS e
    WHERE e.event_type = 'responded'
    GROUP BY e.source_system, e.ticket_id
),
state_events AS MATERIALIZED (
    SELECT e.source_system, e.ticket_id, e.occurred_at, e.event_type,
           row_number() OVER (
               PARTITION BY e.source_system, e.ticket_id
               ORDER BY e.occurred_at, e.event_id COLLATE "C"
           ) AS event_sequence
    FROM eligible_events AS e
    WHERE e.event_type <> 'responded'
),
-- Walk each ticket once in deterministic order. Invalid transitions are no-ops;
-- 003_quality_checks.sql reports them instead of silently changing the state.
state_walk (source_system, ticket_id, event_sequence, interval_start,
            ticket_status, reopened_count) AS (
    SELECT t.source_system, t.ticket_id, 0::bigint, t.created_at,
           'open'::text, 0::bigint
    FROM eligible_tickets AS t

    UNION ALL

    SELECT w.source_system, w.ticket_id, e.event_sequence, e.occurred_at,
           CASE
               WHEN w.ticket_status = 'open' AND e.event_type = 'waiting' THEN 'waiting'
               WHEN w.ticket_status = 'waiting' AND e.event_type = 'resumed' THEN 'open'
               WHEN w.ticket_status = 'open' AND e.event_type = 'resolved' THEN 'resolved'
               WHEN w.ticket_status = 'resolved' AND e.event_type = 'reopened' THEN 'open'
               ELSE w.ticket_status
           END,
           w.reopened_count + CASE
               WHEN w.ticket_status = 'resolved' AND e.event_type = 'reopened'
               THEN 1::bigint ELSE 0::bigint
           END
    FROM state_walk AS w
    JOIN state_events AS e
      ON e.source_system = w.source_system
     AND e.ticket_id = w.ticket_id
     AND e.event_sequence = w.event_sequence + 1
),
intervals AS (
    SELECT w.*,
           lead(w.interval_start, 1, p_as_of) OVER (
               PARTITION BY w.source_system, w.ticket_id
               ORDER BY w.event_sequence
           ) AS interval_end
    FROM state_walk AS w
),
active_time AS (
    SELECT i.source_system, i.ticket_id,
           sum(CASE WHEN i.ticket_status = 'open'
               THEN extract(epoch FROM (i.interval_end - i.interval_start)) / 60::numeric
               ELSE 0::numeric
           END) AS resolution_minutes
    FROM intervals AS i
    GROUP BY i.source_system, i.ticket_id
),
latest_state AS (
    SELECT DISTINCT ON (w.source_system, w.ticket_id)
           w.source_system, w.ticket_id, w.ticket_status, w.reopened_count
    FROM state_walk AS w
    ORDER BY w.source_system, w.ticket_id, w.event_sequence DESC
)
SELECT t.source_system,
       t.ticket_id,
       t.priority,
       t.team_id,
       s.ticket_status AS current_status,
       extract(epoch FROM (r.first_responded_at - t.created_at)) / 60::numeric
           AS first_response_minutes,
       a.resolution_minutes,
       (extract(epoch FROM (coalesce(r.first_responded_at, p_as_of) - t.created_at))
           / 60::numeric > p.response_target_minutes) AS response_breached,
       (a.resolution_minutes > p.resolution_target_minutes) AS resolution_breached,
       CASE WHEN s.ticket_status <> 'resolved'
           THEN extract(epoch FROM (p_as_of - t.created_at)) / 60::numeric
           ELSE NULL::numeric
       END AS backlog_age_minutes,
       s.reopened_count
FROM eligible_tickets AS t
JOIN staging.policies AS p ON p.priority = t.priority
JOIN latest_state AS s
  ON s.source_system = t.source_system AND s.ticket_id = t.ticket_id
JOIN active_time AS a
  ON a.source_system = t.source_system AND a.ticket_id = t.ticket_id
LEFT JOIN responses AS r
  ON r.source_system = t.source_system AND r.ticket_id = t.ticket_id;
$function$;
