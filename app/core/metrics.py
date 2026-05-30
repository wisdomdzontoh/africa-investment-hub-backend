"""Prometheus metrics: a request-instrumenting middleware and /metrics route.

Built into the Coolify stack (PRD §8.7): API latency and request counts are
scraped by Prometheus and visualised in Grafana.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        # Use the route template (not the raw path) to keep cardinality bounded.
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        elapsed = time.perf_counter() - start
        REQUEST_LATENCY.labels(request.method, path).observe(elapsed)
        REQUEST_COUNT.labels(request.method, path, response.status_code).inc()
        return response


def metrics_endpoint() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def setup_metrics(app: FastAPI) -> None:
    app.add_middleware(PrometheusMiddleware)
    app.add_api_route("/metrics", lambda: metrics_endpoint(), include_in_schema=False)
