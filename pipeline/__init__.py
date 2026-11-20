"""Batch ETL pipeline: ingest -> clean -> load (MySQL star schema) -> transform (SQL marts)."""

import os

# Must be set before pyarrow is imported anywhere. Arrow's default allocator
# (jemalloc) keeps freed pages cached, so a chunked job's resident memory keeps
# growing even though each chunk is released. Measured on the clean stage
# (13.4M rows): 1,254 MB peak with jemalloc vs 620 MB with the system
# allocator + malloc_trim (see release_memory in pipeline/quality.py).
os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")
