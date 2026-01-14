# NetSentinel Makefile
# Common commands for development and deployment

.PHONY: help install dev up down logs test lint clean build migrate

# Default target
help:
	@echo "NetSentinel Development Commands"
	@echo "================================"
	@echo ""
	@echo "Setup:"
	@echo "  make install      - Install all dependencies"
	@echo "  make setup        - Full setup (install + migrate + seed)"
	@echo ""
	@echo "Development:"
	@echo "  make dev          - Start all services in development mode"
	@echo "  make up           - Start services with docker-compose"
	@echo "  make down         - Stop all services"
	@echo "  make restart      - Restart all services"
	@echo "  make logs         - Tail all service logs"
	@echo "  make logs-<svc>   - Tail specific service logs (e.g., logs-backend)"
	@echo ""
	@echo "Database:"
	@echo "  make migrate      - Run database migrations"
	@echo "  make migrate-new  - Create new migration (NAME=migration_name)"
	@echo "  make seed         - Seed database with test data"
	@echo "  make db-shell     - Open PostgreSQL shell"
	@echo "  make db-reset     - Reset database (WARNING: destroys data)"
	@echo ""
	@echo "Testing:"
	@echo "  make test         - Run all tests"
	@echo "  make test-backend - Run backend tests"
	@echo "  make test-collector - Run collector tests"
	@echo "  make test-frontend - Run frontend tests"
	@echo "  make lint         - Run linters"
	@echo ""
	@echo "Build:"
	@echo "  make build        - Build all Docker images"
	@echo "  make build-<svc>  - Build specific service"
	@echo ""
	@echo "Production:"
	@echo "  make prod         - Start production stack"
	@echo "  make prod-build   - Build production images"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean        - Clean up containers, volumes, cache"
	@echo "  make shell-<svc>  - Open shell in service container"
	@echo "  make flow-gen     - Generate test flow data"

# ============================================================================
# SETUP
# ============================================================================

install:
	@echo "Installing dependencies..."
	cd backend && pip install -r requirements.txt -r requirements-dev.txt
	cd frontend && npm install
	cd collector && go mod download
	@echo "Done!"

setup: install
	@make up
	@sleep 5
	@make migrate
	@make seed
	@echo "Setup complete! Access the app at http://localhost:3000"

# ============================================================================
# DEVELOPMENT
# ============================================================================

dev: up logs

up:
	docker-compose up -d
	@echo "Services starting..."
	@echo "  - Frontend: http://localhost:3000"
	@echo "  - Backend API: http://localhost:8000"
	@echo "  - API Docs: http://localhost:8000/docs"
	@echo "  - Collector: UDP 2055"

down:
	docker-compose down

restart:
	docker-compose restart

logs:
	docker-compose logs -f

logs-backend:
	docker-compose logs -f backend

logs-collector:
	docker-compose logs -f collector

logs-worker:
	docker-compose logs -f celery-worker

logs-frontend:
	docker-compose logs -f frontend

# ============================================================================
# DATABASE
# ============================================================================

migrate:
	docker-compose exec backend alembic upgrade head

migrate-new:
ifndef NAME
	$(error NAME is required. Usage: make migrate-new NAME=add_new_table)
endif
	docker-compose exec backend alembic revision --autogenerate -m "$(NAME)"

seed:
	docker-compose exec backend python -m app.scripts.seed_data

db-shell:
	docker-compose exec postgres psql -U netsentinel -d netsentinel

db-reset:
	@echo "WARNING: This will destroy all data!"
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ]
	docker-compose down -v
	docker-compose up -d postgres
	@sleep 5
	docker-compose up -d

# ============================================================================
# TESTING
# ============================================================================

test: test-backend test-collector test-frontend

test-backend:
	docker-compose exec backend pytest -v

test-collector:
	cd collector && go test -v ./...

test-frontend:
	cd frontend && npm test

lint:
	@echo "Linting backend..."
	cd backend && ruff check . && mypy .
	@echo "Linting collector..."
	cd collector && golangci-lint run
	@echo "Linting frontend..."
	cd frontend && npm run lint

# ============================================================================
# BUILD
# ============================================================================

build:
	docker-compose build

build-backend:
	docker-compose build backend

build-collector:
	docker-compose build collector

build-frontend:
	docker-compose build frontend

# ============================================================================
# PRODUCTION
# ============================================================================

prod:
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

prod-build:
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml build

# ============================================================================
# UTILITIES
# ============================================================================

clean:
	@echo "Cleaning up..."
	docker-compose down -v --remove-orphans
	docker system prune -f
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "node_modules" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".next" -exec rm -rf {} + 2>/dev/null || true
	@echo "Done!"

shell-backend:
	docker-compose exec backend /bin/bash

shell-collector:
	docker-compose exec collector /bin/sh

shell-postgres:
	docker-compose exec postgres /bin/bash

# Generate test flow data (requires nflow-generator or similar)
flow-gen:
	@echo "Generating test NetFlow data..."
	@echo "Sending to localhost:2055..."
	docker run --rm --network host networkstatic/nflow-generator \
		-t localhost -p 2055 -c 1000 -s 5

# Watch mode for development
watch-backend:
	docker-compose logs -f backend celery-worker

watch-all:
	docker-compose logs -f
