"""HTTP API routers (M2).

Each router owns one resource family and is mounted under
`/api/v1` in `app/main.py`. The routers are thin: they parse
path / query params, call a service function that owns the DB
session, and return a pydantic response model. No DB session
leaks out of a router.
"""
