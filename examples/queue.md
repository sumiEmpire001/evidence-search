# Synthetic queue handbook
This document is fictional demonstration data.
Workers renew leases while they process durable queue jobs.
A failed job retries with exponential backoff before entering a dead-letter queue.
Expired leases allow another worker to reclaim abandoned jobs.
