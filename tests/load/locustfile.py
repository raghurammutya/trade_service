# tests/load/locustfile.py
"""
Load testing configuration using Locust.
Tests system behavior under various load scenarios.
"""

import random
import json
from locust import HttpUser, task, between, events
from locust.env import Environment
from locust.stats import stats_printer
from typing import Dict, Any

from tests.factories.test_data_factory import TestDataFactory

class TradeServiceUser(HttpUser):
    """Simulates a typical trade service user."""
    
    wait_time = between(1, 3)  # Wait 1-3 seconds between requests
    
    def on_start(self):
        """Initialize user session."""
        self.factory = TestDataFactory()
        self.user_id = self.factory.generate_user_id()
        self.organization_id = self.factory.generate_organization_id()
        
        # Authenticate user (if needed)
        self.headers = {
            "Content-Type": "application/json",
            "X-Organization-ID": self.organization_id,
            "X-User-ID": self.user_id
        }
    
    @task(5)
    def place_order(self):
        """Place a trading order (most common operation)."""
        order_data = self.factory.generate_order_data(
            pseudo_account=self.user_id,
            organization_id=self.organization_id
        )
        
        with self.client.post(
            "/trades/place-order",
            json=order_data,
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 400:
                # Validation errors are expected in load testing
                response.success()
            else:
                response.failure(f"Unexpected status code: {response.status_code}")
    
    @task(3)
    def fetch_positions(self):
        """Fetch user positions."""
        with self.client.get(
            f"/data/positions/{self.user_id}",
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code in [200, 404]:
                response.success()
            else:
                response.failure(f"Unexpected status code: {response.status_code}")
    
    @task(3)
    def fetch_holdings(self):
        """Fetch user holdings."""
        with self.client.get(
            f"/data/holdings/{self.user_id}",
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code in [200, 404]:
                response.success()
            else:
                response.failure(f"Unexpected status code: {response.status_code}")
    
    @task(2)
    def fetch_orders(self):
        """Fetch user orders."""
        with self.client.get(
            f"/data/orders/{self.user_id}",
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code in [200, 404]:
                response.success()
            else:
                response.failure(f"Unexpected status code: {response.status_code}")
    
    @task(2)
    def fetch_margins(self):
        """Fetch user margins."""
        with self.client.get(
            f"/data/margins/{self.user_id}",
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code in [200, 404]:
                response.success()
            else:
                response.failure(f"Unexpected status code: {response.status_code}")
    
    @task(1)
    def fetch_data_bulk(self):
        """Fetch all user data at once."""
        fetch_data = {
            "pseudo_account": self.user_id,
            "organization_id": self.organization_id
        }
        
        with self.client.post(
            "/trades/fetch-data",
            json=fetch_data,
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Unexpected status code: {response.status_code}")
    
    @task(1)
    def health_check(self):
        """Check service health."""
        with self.client.get("/health", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Health check failed: {response.status_code}")

class HighFrequencyUser(HttpUser):
    """Simulates high-frequency trading user."""
    
    wait_time = between(0.1, 0.5)  # Very fast operations
    weight = 2  # Higher weight for more aggressive testing
    
    def on_start(self):
        self.factory = TestDataFactory()
        self.user_id = self.factory.generate_user_id()
        self.organization_id = self.factory.generate_organization_id()
        
        self.headers = {
            "Content-Type": "application/json",
            "X-Organization-ID": self.organization_id,
            "X-User-ID": self.user_id
        }
    
    @task(10)
    def rapid_order_placement(self):
        """Rapid order placement to test rate limiting."""
        order_data = self.factory.generate_order_data(
            pseudo_account=self.user_id,
            organization_id=self.organization_id
        )
        
        with self.client.post(
            "/trades/place-order",
            json=order_data,
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 429:
                # Rate limiting is expected
                response.success()
            elif response.status_code == 400:
                # Validation errors are expected
                response.success()
            else:
                response.failure(f"Unexpected status code: {response.status_code}")
    
    @task(5)
    def rapid_position_checks(self):
        """Rapid position checking."""
        with self.client.get(
            f"/data/positions/{self.user_id}",
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code in [200, 404, 429]:
                response.success()
            else:
                response.failure(f"Unexpected status code: {response.status_code}")

class BulkDataUser(HttpUser):
    """Simulates users performing bulk data operations."""
    
    wait_time = between(5, 15)  # Slower, bulk operations
    weight = 1
    
    def on_start(self):
        self.factory = TestDataFactory()
        self.user_id = self.factory.generate_user_id()
        self.organization_id = self.factory.generate_organization_id()
        
        self.headers = {
            "Content-Type": "application/json",
            "X-Organization-ID": self.organization_id,
            "X-User-ID": self.user_id
        }
    
    @task(1)
    def bulk_data_fetch(self):
        """Fetch all user data."""
        fetch_data = {
            "pseudo_account": self.user_id,
            "organization_id": self.organization_id
        }
        
        with self.client.post(
            "/trades/fetch-data",
            json=fetch_data,
            headers=self.headers,
            catch_response=True,
            timeout=30  # Longer timeout for bulk operations
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Bulk fetch failed: {response.status_code}")
    
    @task(1)
    def strategy_operations(self):
        """Test strategy-related operations."""
        with self.client.get(
            f"/strategies/account/{self.organization_id}/{self.user_id}/selectable-data",
            params={"data_type": "positions"},
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code in [200, 404]:
                response.success()
            else:
                response.failure(f"Strategy operation failed: {response.status_code}")

# Load testing scenarios
class LoadTestScenarios:
    """Predefined load testing scenarios."""
    
    @staticmethod
    def light_load():
        """Light load scenario - normal business hours."""
        return {
            "users": 10,
            "spawn_rate": 2,
            "run_time": "5m"
        }
    
    @staticmethod
    def moderate_load():
        """Moderate load scenario - busy trading period."""
        return {
            "users": 50,
            "spawn_rate": 5,
            "run_time": "10m"
        }
    
    @staticmethod
    def heavy_load():
        """Heavy load scenario - peak trading hours."""
        return {
            "users": 100,
            "spawn_rate": 10,
            "run_time": "15m"
        }
    
    @staticmethod
    def stress_test():
        """Stress test scenario - beyond normal capacity."""
        return {
            "users": 200,
            "spawn_rate": 20,
            "run_time": "10m"
        }
    
    @staticmethod
    def spike_test():
        """Spike test scenario - sudden traffic increase."""
        return {
            "users": 150,
            "spawn_rate": 50,  # Very fast ramp-up
            "run_time": "5m"
        }

# Custom event handlers for detailed reporting
@events.request.add_listener
def request_handler(request_type, name, response_time, response_length, exception, context, **kwargs):
    """Handle individual request events for custom metrics."""
    if exception:
        print(f"Request failed: {request_type} {name} - {exception}")

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Handle test start event."""
    print(f"Load test starting with {environment.parsed_options.num_users} users")

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Handle test stop event and generate custom reports."""
    print("Load test completed")
    
    # Generate custom performance report
    stats = environment.stats
    
    report = {
        "summary": {
            "total_requests": stats.total.num_requests,
            "total_failures": stats.total.num_failures,
            "average_response_time": stats.total.avg_response_time,
            "min_response_time": stats.total.min_response_time,
            "max_response_time": stats.total.max_response_time,
            "requests_per_second": stats.total.current_rps,
            "failure_rate": stats.total.fail_ratio
        },
        "endpoints": {}
    }
    
    for name, entry in stats.entries.items():
        if entry.num_requests > 0:
            report["endpoints"][name] = {
                "requests": entry.num_requests,
                "failures": entry.num_failures,
                "avg_response_time": entry.avg_response_time,
                "min_response_time": entry.min_response_time,
                "max_response_time": entry.max_response_time,
                "rps": entry.current_rps,
                "failure_rate": entry.fail_ratio
            }
    
    # Save report
    with open("load_test_report.json", "w") as f:
        json.dump(report, f, indent=2)
    
    print("Performance report saved to load_test_report.json")

# Performance thresholds for automated testing
PERFORMANCE_THRESHOLDS = {
    "max_avg_response_time": 2000,  # 2 seconds
    "max_95th_percentile": 5000,    # 5 seconds
    "max_failure_rate": 0.05,       # 5%
    "min_rps": 10                   # 10 requests per second
}

def check_performance_thresholds(stats):
    """Check if performance meets defined thresholds."""
    failures = []
    
    if stats.total.avg_response_time > PERFORMANCE_THRESHOLDS["max_avg_response_time"]:
        failures.append(f"Average response time {stats.total.avg_response_time}ms exceeds threshold")
    
    if stats.total.fail_ratio > PERFORMANCE_THRESHOLDS["max_failure_rate"]:
        failures.append(f"Failure rate {stats.total.fail_ratio:.2%} exceeds threshold")
    
    if stats.total.current_rps < PERFORMANCE_THRESHOLDS["min_rps"]:
        failures.append(f"RPS {stats.total.current_rps} below threshold")
    
    return failures

# Example usage:
if __name__ == "__main__":
    # This can be used for programmatic load testing
    from locust.env import Environment
    from locust.stats import stats_printer
    import time
    
    # Setup environment
    env = Environment(user_classes=[TradeServiceUser])
    env.create_local_runner()
    
    # Start load test
    scenario = LoadTestScenarios.light_load()
    env.runner.start(scenario["users"], spawn_rate=scenario["spawn_rate"])
    
    # Run for specified time
    time.sleep(300)  # 5 minutes
    
    # Stop test
    env.runner.stop()
    
    # Check results
    failures = check_performance_thresholds(env.stats)
    if failures:
        print("Performance test failed:")
        for failure in failures:
            print(f"  - {failure}")
    else:
        print("Performance test passed!")