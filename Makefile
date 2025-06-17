# Trade Service Makefile
# Provides convenient commands for development and testing

.PHONY: help install test test-unit test-integration test-api test-performance test-smoke test-security test-quick lint format type-check clean coverage report setup-test-db

# Default target
help:
	@echo "Trade Service Development Commands"
	@echo "=================================="
	@echo ""
	@echo "Setup:"
	@echo "  install       Install dependencies"
	@echo "  setup-test-db Setup test database"
	@echo ""
	@echo "Testing:"
	@echo "  test          Run all tests"
	@echo "  test-quick    Run unit and smoke tests only"
	@echo "  test-unit     Run unit tests"
	@echo "  test-integration Run integration tests"
	@echo "  test-api      Run API tests"
	@echo "  test-performance Run performance tests"
	@echo "  test-smoke    Run smoke tests"
	@echo "  test-security Run security tests"
	@echo ""
	@echo "Code Quality:"
	@echo "  lint          Run all linting checks"
	@echo "  format        Format code with black and isort"
	@echo "  type-check    Run type checking with mypy"
	@echo ""
	@echo "Utilities:"
	@echo "  coverage      Generate coverage report"
	@echo "  report        Generate comprehensive test report"
	@echo "  clean         Clean build artifacts and cache"
	@echo ""

# Installation and setup
install:
	@echo "Installing dependencies..."
	pip install -r requirements.txt
	pip install -r test_requirements.txt

setup-test-db:
	@echo "Setting up test database..."
	python -c "from shared_architecture.db.database import Base, engine; Base.metadata.create_all(bind=engine); print('Test database setup complete')"

# Testing commands
test:
	@echo "Running all tests..."
	python scripts/run_tests.py --type all --verbose

test-quick:
	@echo "Running quick tests (unit + smoke)..."
	python scripts/run_tests.py --type quick --verbose

test-unit:
	@echo "Running unit tests..."
	python scripts/run_tests.py --type unit --verbose

test-integration:
	@echo "Running integration tests..."
	python scripts/run_tests.py --type integration --verbose

test-api:
	@echo "Running API tests..."
	python scripts/run_tests.py --type api --verbose

test-performance:
	@echo "Running performance tests..."
	python scripts/run_tests.py --type performance --verbose

test-smoke:
	@echo "Running smoke tests..."
	python scripts/run_tests.py --type smoke --verbose

test-security:
	@echo "Running security tests..."
	python scripts/run_tests.py --type security --verbose

# Code quality commands
lint:
	@echo "Running linting checks..."
	python -m black --check --diff .
	python -m isort --check-only --diff .
	python -m flake8 . --count --statistics
	python -m bandit -r app/ -f screen

format:
	@echo "Formatting code..."
	python -m black .
	python -m isort .
	@echo "Code formatting complete"

type-check:
	@echo "Running type checks..."
	python -m mypy app/ --ignore-missing-imports --show-error-codes

# Utility commands
coverage:
	@echo "Generating coverage report..."
	pytest tests/unit/ --cov=app --cov=shared_architecture --cov-report=html:htmlcov --cov-report=term-missing
	@echo "Coverage report generated in htmlcov/"

report:
	@echo "Generating comprehensive test report..."
	python scripts/run_tests.py --type all --report test-report.json
	@echo "Report saved to test-report.json"

clean:
	@echo "Cleaning build artifacts..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.coverage" -delete
	rm -rf htmlcov/
	rm -rf .coverage
	rm -rf dist/
	rm -rf build/
	rm -rf *.egg-info/
	rm -f test-results*.xml
	rm -f coverage*.xml
	rm -f benchmark-results.json
	rm -f test-report.json
	@echo "Clean complete"

# CI/CD commands
ci-test:
	@echo "Running CI test suite..."
	python scripts/run_tests.py --type all --report ci-report.json --skip-lint

ci-quick:
	@echo "Running CI quick tests..."
	python scripts/run_tests.py --type quick --report ci-quick-report.json

# Development helpers
dev-setup: install setup-test-db
	@echo "Development environment setup complete"

check:
	@echo "Running development checks..."
	python scripts/run_tests.py --check-env

# Docker commands (if using Docker)
docker-test:
	@echo "Running tests in Docker..."
	docker-compose -f docker/docker-compose.yml run --rm test

docker-build:
	@echo "Building Docker image..."
	docker build -f docker/Dockerfile -t trade-service:latest .

# Database helpers
db-reset:
	@echo "Resetting test database..."
	python -c "from shared_architecture.db.database import Base, engine; Base.metadata.drop_all(bind=engine); Base.metadata.create_all(bind=engine); print('Database reset complete')"

# Monitoring and profiling
profile:
	@echo "Running performance profiling..."
	python -m pytest tests/ -m performance --profile-svg

memory-profile:
	@echo "Running memory profiling..."
	python -m pytest tests/ -m performance --memray

# Documentation
docs:
	@echo "Generating documentation..."
	python -m pydoc -w app/
	@echo "Documentation generated"

# Version and release helpers
version:
	@python -c "import app; print(f'Trade Service version: {getattr(app, '__version__', 'unknown')}')"

# Safety and security
security-scan:
	@echo "Running security scans..."
	python -m bandit -r app/ -f json -o bandit-report.json
	python -m safety check --json --output safety-report.json
	@echo "Security reports generated"

dependency-check:
	@echo "Checking dependencies..."
	pip check
	python -m safety check

# Performance benchmarks
benchmark:
	@echo "Running performance benchmarks..."
	pytest tests/ -m performance --benchmark-only --benchmark-json=benchmark-results.json
	@echo "Benchmark results saved to benchmark-results.json"

# Load testing
load-test:
	@echo "Running load tests..."
	locust -f tests/load/locustfile.py --headless -u 10 -r 2 -t 60s --host http://localhost:8000

# Integration with external tools
sonar:
	@echo "Running SonarQube analysis..."
	sonar-scanner -Dsonar.projectKey=trade-service -Dsonar.sources=app/ -Dsonar.python.coverage.reportPaths=coverage.xml

# Pre-commit hooks
pre-commit:
	@echo "Running pre-commit checks..."
	python scripts/run_tests.py --type quick
	$(MAKE) lint
	$(MAKE) type-check
	@echo "Pre-commit checks passed"

# Git hooks setup
setup-hooks:
	@echo "Setting up git hooks..."
	echo "#!/bin/bash\nmake pre-commit" > .git/hooks/pre-commit
	chmod +x .git/hooks/pre-commit
	@echo "Git hooks setup complete"