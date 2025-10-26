

Subtask Results
The directory Refactor-Oct2025 has been created (if needed) and the file Refactor-Oct2025/batch1_blueprint.md now contains the provided Markdown. The file content is exactly as specified:
Batch 1 – Data Ingestion & Scheduler Hardening Blueprint
1. Objective Summary
•	Productionize Finviz headline ingestion with resilient retries, deduplication, and persistence to unlock downstream analytics.
•	Harden the background scheduler so ingestion cadence can be controlled, monitored, and paused safely without redeployments.
•	Instrument ingestion and scheduler activity with metrics/logging, aligning with Batch 1 acceptance criteria and setting the foundation for Batches 2–5.
2. Scheduler Lifecycle Enhancements
2.1 Task orchestration
•	Extend TaskScheduler.start() to:
•	Load feature flags from configuration and skip registering new tasks when INGESTION_V2_ENABLED is disabled.
•	Register the ingestion loop via asyncio.create_task that delegates to the new ingestion service entry point (see §3).
•	Record task handles in self.tasks keyed by descriptive names ("headline_ingestion_v2", "cleanup_v2").
•	Replace the placeholder logic in TaskScheduler._fetch_headlines_task() with:
•	A guard to short-circuit when the feature flag is off.
•	Context acquisition from AsyncSessionLocal and invocation of FinvizClient.fetch_portfolio_headlines through the ingestion service API for each configured portfolio ID.
•	Structured logging (task, portfolio_id, duration_ms, headline_count).
•	Update TaskScheduler._cleanup_task() to call a cleanup helper in the ingestion service that prunes expired cache entries, stale headlines, and marks stale analytics aggregates.
2.2 Error handling & retries
•	Wrap each iteration of TaskScheduler._run_periodically() with exponential backoff (e.g., jittered sleep on failure capped at 5× interval) while preserving the base cadence.
•	Annotate ingestion calls with rate-limit awareness:
•	Surface 429/timeout responses from RateLimiter.acquire() as warnings and reschedule without crashing the loop.
•	Emit success/failure counters to Prometheus (see §5).
•	Ensure cancellations are graceful by awaiting outstanding ingestion tasks during TaskScheduler.stop().
2.3 Control surface & lifecycle
•	Store scheduler state (running, last_success_at, consecutive_failures) on the instance so the control API can query it.
•	Persist a lightweight heartbeat in Redis with cache_manager.set("scheduler:headline:last_heartbeat", ...), allowing external monitors to detect stalls.
•	Allow dynamic interval adjustment through feature-flag overrides (two environment variables or database-backed overrides).
3. Ingestion Service Module (backend/services/ingestion.py)
3.1 Responsibilities
•	Provide a cohesive API to fetch, normalize, deduplicate, and persist Finviz headline payloads while coordinating cache invalidation.
•	Abstract away direct Finviz client usage so routers and scheduler interact through a single facade.
•	Surface post-ingestion signals (counts, dedupe stats) for telemetry.
3.2 Public API
•	ingest_portfolios: async entry point invoked by the scheduler; accepts a list of portfolio IDs, optional explicit API key, and async session handle. Internally iterates portfolios, acquiring headlines concurrently (bounded semaphore) and consolidating results.
•	ingest_single_portfolio: helper returning a structured result (fetched, stored, deduped, errors) for one portfolio, leveraging FinvizClient.fetch_portfolio_headlines.
•	cleanup_expired_records: invoked by the hourly cleanup job to purge headlines older than configured retention and clear cache keys.
•	invalidate_downstream_caches: central cache invalidation hook shared by write paths (see §4).
3.3 Workflow
1.	Resolve runtime configuration (portfolio list, API key, dedupe thresholds) from Settings and persisted overrides (see backend/models.py).
2.	Acquire the Finviz rate limiter via the client and fetch raw headlines.
3.	Deduplicate using HeadlineDeduplicator before persistence.
4.	Upsert records into Headline/related tables inside a single transaction (reuse AsyncSessionLocal from database.py).
5.	Trigger cache invalidation once commits succeed.
6.	Emit telemetry payload to the scheduler control bus (structlog + metrics).
3.4 Data integrity & transactions
•	Use session-scoped transactions to write Headline, HeadlineSource, and any derived aggregates atomically.
•	Guard against concurrent ingestion by locking on Redis key ingestion:portfolio:{id}:lock with short TTL to avoid double-processing.
•	Capture dedupe hashes using the existing headline_hash column, preventing duplicates before hitting the database.
4. Cache Invalidation & Refresh Strategy
•	Generate cache keys with CacheManager.cache_key() to ensure consistent hashing for analytics/ticker responses.
•	After successful persistence, call invalidate_downstream_caches to:
•	Remove headline-related keys via CacheManager.delete_pattern() (e.g., headlines:, analytics:summary:, returns:ticker:*).
•	Optionally prewarm hot caches by reusing CacheManager.get_or_set() with fresh data loaders.
•	Expose cache hit/miss metrics to validate improvements (see §5).
5. Telemetry & Observability
•	Emit structured logs through structlog in:
•	Ingestion success/failure paths (status, portfolio_id, count, duration_ms).
•	Scheduler control events (action, actor, interval).
•	Register Prometheus metrics in backend/main.py:
•	Counter: braktrad_ingestion_fetch_total{status, source}.
•	Histogram: braktrad_ingestion_duration_seconds{portfolio_id}.
•	Gauge: braktrad_scheduler_last_success_timestamp.
•	Surface Redis heartbeat timestamp in a debug endpoint to assist operators.
6. Feature Flags
•	INGESTION_V2_ENABLED:
•	Declared in Settings with default False in production.
•	Persist overrides via a JSON column on the user settings record (see backend/models.py).
•	Checked inside TaskScheduler._fetch_headlines_task() and ingestion service entry points.
•	SCHEDULER_CONTROL_API:
•	Controls exposure of admin endpoints and UI toggles.
•	Evaluated during FastAPI router registration inside backend/main.py before including the control router.
•	Document expected propagation through environment variables (ENVIRONMENT, FEATURE_FLAGS).
7. Scheduler Control API Surface
•	Introduce backend/routers/system_scheduler.py with endpoints:
•	POST /api/system/scheduler/start – triggers TaskScheduler.start() when stopped.
•	POST /api/system/scheduler/stop – calls TaskScheduler.stop().
•	GET /api/system/scheduler/status – returns state (running, tasks, last_success_at, heartbeat value).
•	Authenticate using existing admin JWT middleware (reuse utilities from backend/routers/settings.py if present).
•	Inject the scheduler instance via Depends on request.app.state.task_scheduler to avoid circular imports.
•	Protect routes behind the SCHEDULER_CONTROL_API flag and return 404 when disabled.
8. Data Model & Migrations
•	No new migrations required. Existing headline tables and settings storage support the additional metadata.
9. Testing & Validation
•	Unit tests:
•	Scheduler: fake ingestion service to validate retry/backoff logic for TaskScheduler._run_periodically().
•	Ingestion service: mock FinvizClient.fetch_portfolio_headlines to ensure dedupe and persistence flows.
•	Cache utilities: verify invalidate_downstream_caches deletes expected keys via a fake Redis client.
•	Integration tests:
•	Spin up FastAPI app with in-memory Redis to validate control API start/stop paths.
•	Use seeded headlines to confirm cache invalidation updates analytics endpoints under INGESTION_V2_ENABLED.
•	Telemetry validation:
•	Assert Prometheus collectors emit expected samples after ingestion (scrape /metrics and parse).
•	Snapshot structlog JSON to ensure operational metadata is present.
10. External Dependency Risks & Mitigation
Risk	Impact	Mitigation
Finviz rate limiting/outage	High	Exponential backoff, dual-path fetch (export + scrape), manual toggle via INGESTION_V2_ENABLED, alert on consecutive failures.
Redis unavailable or degraded	Medium	Fallback to in-memory locks, skip cache invalidation with warnings, heartbeat stored in app memory, alert on cache errors.
Database contention during bulk ingest	Medium	Batch inserts, limit concurrency per portfolio, use short-lived locks.
Scheduler runaway tasks	Medium	Heartbeat watchdog, status endpoint, ability to pause via control API.
11. Implementation Sequence & Acceptance Criteria
1.	Implement ingestion service module with unit tests.
2.	Wire scheduler to new service and add control API (feature-flagged).
3.	Add telemetry/metrics and verify via integration tests.
4.	Document operator runbooks (scheduler start/stop, cache operations).
5.	Enable INGESTION_V2_ENABLED in staging; verify ingestion SLOs and cache invalidation.
6.	Promote to production after 24h of healthy metrics.
Acceptance Criteria:
•	Scheduler can be paused/resumed through the control API with feature flag on.
•	Ingestion runs every five minutes, retries gracefully, and deduplicates headlines before persistence.
•	Cache keys invalidated immediately after ingestion; analytics endpoints reflect fresh data.
•	Metrics and structured logs expose ingestion health for dashboards and alerts.
The file accurately reflects the specified blueprint.