# NetSentinel Monorepo Structure

```
netsentinel/
│
├── collector/                      # Go NetFlow/IPFIX collector
│   ├── cmd/
│   │   └── collector/
│   │       └── main.go            # Entry point
│   ├── internal/
│   │   ├── parser/
│   │   │   ├── parser.go          # Flow record parser
│   │   │   └── parser_test.go
│   │   └── sender/
│   │       ├── sender.go          # HTTP sender to backend
│   │       └── sender_test.go
│   ├── pkg/
│   │   ├── netflow/
│   │   │   ├── v5.go              # NetFlow v5 parsing
│   │   │   ├── v9.go              # NetFlow v9 parsing
│   │   │   └── types.go           # Shared types
│   │   └── ipfix/
│   │       ├── ipfix.go           # IPFIX parsing
│   │       └── templates.go       # IPFIX template handling
│   ├── go.mod
│   ├── go.sum
│   ├── Dockerfile
│   └── README.md
│
├── backend/                        # Python FastAPI backend
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                # FastAPI application entry
│   │   ├── config.py              # Configuration management
│   │   ├── database.py            # Database connection
│   │   │
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── deps.py            # Dependency injection
│   │   │   └── v1/
│   │   │       ├── __init__.py
│   │   │       ├── router.py      # API router aggregation
│   │   │       └── endpoints/
│   │   │           ├── __init__.py
│   │   │           ├── flows.py       # Flow ingestion endpoints
│   │   │           ├── assets.py      # Asset CRUD endpoints
│   │   │           ├── alerts.py      # Alert endpoints
│   │   │           ├── rules.py       # Rules CRUD endpoints
│   │   │           ├── dashboard.py   # Dashboard stats
│   │   │           └── auth.py        # Authentication
│   │   │
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── security.py        # JWT, password hashing
│   │   │   └── exceptions.py      # Custom exceptions
│   │   │
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── flow.py            # Flow SQLAlchemy model
│   │   │   ├── asset.py           # Asset model
│   │   │   ├── feature.py         # Feature vector model
│   │   │   ├── score.py           # Anomaly score model
│   │   │   ├── alert.py           # Alert model
│   │   │   ├── rule.py            # Rule model
│   │   │   ├── site.py            # Site/tenant model
│   │   │   └── user.py            # User model
│   │   │
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── flow.py            # Flow Pydantic schemas
│   │   │   ├── asset.py           # Asset schemas
│   │   │   ├── alert.py           # Alert schemas
│   │   │   ├── rule.py            # Rule schemas
│   │   │   └── common.py          # Shared schemas
│   │   │
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── flow_service.py    # Flow processing logic
│   │   │   ├── asset_service.py   # Asset discovery logic
│   │   │   ├── alert_service.py   # Alert generation logic
│   │   │   └── notification.py    # Email/Slack/webhook
│   │   │
│   │   └── workers/
│   │       ├── __init__.py
│   │       ├── celery_app.py      # Celery configuration
│   │       ├── flow_writer.py     # Flow batch insert task
│   │       ├── aggregation.py     # 5-min aggregation task
│   │       ├── scoring.py         # ML scoring task
│   │       └── alerting.py        # Alert generation task
│   │
│   ├── alembic/
│   │   ├── env.py                 # Alembic environment
│   │   ├── script.py.mako         # Migration template
│   │   └── versions/              # Migration files
│   │       └── 001_initial_schema.py
│   │
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── conftest.py            # Pytest fixtures
│   │   ├── test_flows.py
│   │   ├── test_assets.py
│   │   └── test_alerts.py
│   │
│   ├── alembic.ini
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── README.md
│
├── ml/                             # ML training and scoring
│   ├── src/
│   │   ├── __init__.py
│   │   ├── training/
│   │   │   ├── __init__.py
│   │   │   ├── trainer.py         # Model training pipeline
│   │   │   ├── feature_prep.py    # Feature preprocessing
│   │   │   └── isolation_forest.py # IF model wrapper
│   │   │
│   │   ├── scoring/
│   │   │   ├── __init__.py
│   │   │   ├── scorer.py          # Real-time scoring
│   │   │   └── batch_scorer.py    # Batch scoring
│   │   │
│   │   └── explainability/
│   │       ├── __init__.py
│   │       └── feature_contrib.py # Feature contribution calc
│   │
│   ├── models/                    # Trained model artifacts
│   │   └── .gitkeep
│   │
│   ├── tests/
│   │   ├── __init__.py
│   │   └── test_training.py
│   │
│   ├── requirements.txt
│   ├── Dockerfile
│   └── README.md
│
├── frontend/                       # React TypeScript frontend
│   ├── public/
│   │   ├── index.html
│   │   └── favicon.ico
│   │
│   ├── src/
│   │   ├── components/
│   │   │   ├── ui/                # shadcn/ui components
│   │   │   │   ├── button.tsx
│   │   │   │   ├── card.tsx
│   │   │   │   ├── table.tsx
│   │   │   │   └── ...
│   │   │   │
│   │   │   ├── dashboard/
│   │   │   │   ├── NetworkOverview.tsx
│   │   │   │   ├── TopAnomalies.tsx
│   │   │   │   ├── TrafficChart.tsx
│   │   │   │   └── StatsCards.tsx
│   │   │   │
│   │   │   ├── alerts/
│   │   │   │   ├── AlertList.tsx
│   │   │   │   ├── AlertDetail.tsx
│   │   │   │   ├── AlertTimeline.tsx
│   │   │   │   └── ExplanationCard.tsx
│   │   │   │
│   │   │   ├── devices/
│   │   │   │   ├── DeviceList.tsx
│   │   │   │   ├── DeviceProfile.tsx
│   │   │   │   ├── BehaviorTimeline.tsx
│   │   │   │   └── PeersList.tsx
│   │   │   │
│   │   │   └── layout/
│   │   │       ├── Header.tsx
│   │   │       ├── Sidebar.tsx
│   │   │       └── Layout.tsx
│   │   │
│   │   ├── hooks/
│   │   │   ├── useAlerts.ts
│   │   │   ├── useDevices.ts
│   │   │   └── useDashboard.ts
│   │   │
│   │   ├── lib/
│   │   │   ├── api.ts             # API client
│   │   │   ├── utils.ts           # Utility functions
│   │   │   └── constants.ts
│   │   │
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── Alerts.tsx
│   │   │   ├── AlertDetail.tsx
│   │   │   ├── Devices.tsx
│   │   │   ├── DeviceDetail.tsx
│   │   │   ├── Rules.tsx
│   │   │   ├── Settings.tsx
│   │   │   └── Login.tsx
│   │   │
│   │   ├── types/
│   │   │   ├── alert.ts
│   │   │   ├── device.ts
│   │   │   ├── flow.ts
│   │   │   └── api.ts
│   │   │
│   │   ├── App.tsx
│   │   ├── index.tsx
│   │   └── index.css
│   │
│   ├── package.json
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   ├── vite.config.ts
│   ├── Dockerfile
│   └── README.md
│
├── infra/                          # Infrastructure configs
│   ├── docker/
│   │   ├── collector.Dockerfile
│   │   ├── backend.Dockerfile
│   │   ├── frontend.Dockerfile
│   │   └── nginx.conf
│   │
│   └── scripts/
│       ├── init-db.sql            # Initial DB setup
│       ├── seed-data.sql          # Test data
│       └── backup.sh              # Backup script
│
├── shared/                         # Shared schemas/types
│   └── schemas/
│       └── flow_record.json       # JSON schema for flows
│
├── docs/                           # Documentation
│   ├── ARCHITECTURE.md
│   ├── FOLDER_STRUCTURE.md
│   ├── API.md
│   ├── DEPLOYMENT.md
│   └── ONBOARDING.md
│
├── docker-compose.yml              # Local development
├── docker-compose.prod.yml         # Production
├── .env.example                    # Environment template
├── .gitignore
├── Makefile                        # Common commands
└── README.md                       # Project overview
```

## Component Responsibilities Summary

| Directory | Language | Purpose |
|-----------|----------|---------|
| `collector/` | Go | High-performance UDP flow collection |
| `backend/` | Python | REST API, business logic, task workers |
| `ml/` | Python | Model training, scoring, explainability |
| `frontend/` | TypeScript | React dashboard UI |
| `infra/` | Various | Docker, scripts, deployment configs |
| `shared/` | JSON | Cross-component schemas |
| `docs/` | Markdown | Architecture and API documentation |
