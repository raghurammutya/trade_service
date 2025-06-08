# Trade Service

This microservice handles trade order execution and management.

## Features

- Executes trade orders via the StocksDeveloper API.
- Stores order, position, holding, and margin data in TimescaleDB.
- Publishes order status updates to RabbitMQ.
- Provides API endpoints for order management and data retrieval.
- Implements rate limiting to comply with API restrictions.
- Caches frequently accessed data in Redis.
- Supports strategy-specific order tracking.
- Handles position-to-holding and holding-to-position transitions.

## Prerequisites

- Python 3.9
- Docker
- Docker Compose

## Installation

1.  Clone the repository.
2.  Create a `.env` file (see example below) and fill in the required environment variables.
3.  Build the Docker image: `docker-compose build`
4.  Run the service: `docker-compose up`

## Usage

Refer to the API documentation for details on available endpoints.

## Configuration

Environment variables are used to configure the service. You can set them in a `.env` file (for local development) or using environment variables directly (for production).

## Dependencies

- FastAPI
- Uvicorn
- SQLAlchemy
- ... (and others - see requirements.txt)

## Contributing

... (Your contribution guidelines)

## License

... (Your license information)
