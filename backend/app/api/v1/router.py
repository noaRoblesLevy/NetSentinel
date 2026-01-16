"""API v1 router - aggregates all endpoint routers."""

from fastapi import APIRouter

from app.api.v1.endpoints import health, flows, assets, alerts, dashboard, features, auth, sites, rules

api_router = APIRouter()

# Include all endpoint routers
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(sites.router, prefix="/sites", tags=["Sites"])
api_router.include_router(flows.router, prefix="/flows", tags=["Flows"])
api_router.include_router(assets.router, prefix="/assets", tags=["Assets"])
api_router.include_router(alerts.router, prefix="/alerts", tags=["Alerts"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
api_router.include_router(features.router, prefix="/features", tags=["Features"])
api_router.include_router(rules.router, prefix="/rules", tags=["Rules"])
