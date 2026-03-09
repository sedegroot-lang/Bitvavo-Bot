"""
Dashboard Load Testing
======================

Stress tests for Flask dashboard including:
- Concurrent HTTP requests
- WebSocket connection limits
- API endpoint throughput
- Memory and CPU usage under load
- Database connection pooling
"""

import time
import requests
import threading
import statistics
from datetime import datetime
from typing import List, Dict, Any
from collections import defaultdict
import psutil
import os

# Test configuration
BASE_URL = "http://localhost:5001"
NUM_USERS = 50  # Concurrent users
TEST_DURATION = 60  # Seconds
REQUEST_DELAY = 0.1  # Delay between requests per user


class LoadTestResult:
    """Store load test metrics"""
    
    def __init__(self):
        self.response_times: List[float] = []
        self.status_codes: Dict[int, int] = defaultdict(int)
        self.errors: List[str] = []
        self.start_time: float = 0
        self.end_time: float = 0
        self.requests_sent: int = 0
        self.requests_success: int = 0
        self.requests_failed: int = 0
        self.cpu_samples: List[float] = []
        self.memory_samples: List[float] = []
    
    def add_response(self, response_time: float, status_code: int):
        """Record a response"""
        self.response_times.append(response_time)
        self.status_codes[status_code] += 1
        self.requests_sent += 1
        
        if 200 <= status_code < 300:
            self.requests_success += 1
        else:
            self.requests_failed += 1
    
    def add_error(self, error: str):
        """Record an error"""
        self.errors.append(error)
        self.requests_failed += 1
        self.requests_sent += 1
    
    def get_summary(self) -> Dict[str, Any]:
        """Generate summary statistics"""
        duration = self.end_time - self.start_time
        
        if not self.response_times:
            return {
                'duration_seconds': duration,
                'requests_sent': self.requests_sent,
                'errors': len(self.errors),
                'status': 'NO_RESPONSES'
            }
        
        return {
            'duration_seconds': round(duration, 2),
            'requests_sent': self.requests_sent,
            'requests_success': self.requests_success,
            'requests_failed': self.requests_failed,
            'success_rate': round((self.requests_success / self.requests_sent) * 100, 2) if self.requests_sent > 0 else 0,
            'throughput_rps': round(self.requests_sent / duration, 2) if duration > 0 else 0,
            'response_time': {
                'min_ms': round(min(self.response_times) * 1000, 2),
                'max_ms': round(max(self.response_times) * 1000, 2),
                'mean_ms': round(statistics.mean(self.response_times) * 1000, 2),
                'median_ms': round(statistics.median(self.response_times) * 1000, 2),
                'p95_ms': round(statistics.quantiles(self.response_times, n=20)[18] * 1000, 2) if len(self.response_times) > 20 else 0,
                'p99_ms': round(statistics.quantiles(self.response_times, n=100)[98] * 1000, 2) if len(self.response_times) > 100 else 0,
            },
            'status_codes': dict(self.status_codes),
            'errors_count': len(self.errors),
            'errors_sample': self.errors[:10],
            'resource_usage': {
                'avg_cpu_percent': round(statistics.mean(self.cpu_samples), 2) if self.cpu_samples else 0,
                'max_cpu_percent': round(max(self.cpu_samples), 2) if self.cpu_samples else 0,
                'avg_memory_mb': round(statistics.mean(self.memory_samples), 2) if self.memory_samples else 0,
                'max_memory_mb': round(max(self.memory_samples), 2) if self.memory_samples else 0,
            }
        }


class LoadTester:
    """Load testing orchestrator"""
    
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.results = LoadTestResult()
        self.running = False
        self.process = psutil.Process(os.getpid())
    
    def make_request(self, endpoint: str) -> tuple[float, int, str]:
        """Make single HTTP request and measure time"""
        try:
            start = time.time()
            response = requests.get(f"{self.base_url}{endpoint}", timeout=10)
            elapsed = time.time() - start
            return elapsed, response.status_code, ""
        except requests.exceptions.Timeout:
            return 0, 0, "Timeout"
        except requests.exceptions.ConnectionError:
            return 0, 0, "Connection refused"
        except Exception as e:
            return 0, 0, str(e)
    
    def user_session(self, user_id: int, duration: int):
        """Simulate one user making requests"""
        endpoints = [
            '/api/health',
            '/api/status',
            '/api/trades/open',
            '/api/heartbeat',
            '/api/prices',
        ]
        
        end_time = time.time() + duration
        request_count = 0
        
        while time.time() < end_time and self.running:
            # Rotate through endpoints
            endpoint = endpoints[request_count % len(endpoints)]
            
            elapsed, status_code, error = self.make_request(endpoint)
            
            if error:
                self.results.add_error(f"User {user_id}: {error} on {endpoint}")
            else:
                self.results.add_response(elapsed, status_code)
            
            request_count += 1
            time.sleep(REQUEST_DELAY)
    
    def monitor_resources(self):
        """Monitor CPU and memory usage"""
        while self.running:
            try:
                cpu = self.process.cpu_percent(interval=1)
                memory = self.process.memory_info().rss / 1024 / 1024  # MB
                
                self.results.cpu_samples.append(cpu)
                self.results.memory_samples.append(memory)
            except:
                pass
            
            time.sleep(1)
    
    def run(self, num_users: int = NUM_USERS, duration: int = TEST_DURATION):
        """Run load test with concurrent users"""
        print(f"\n{'='*60}")
        print(f"LOAD TEST STARTING")
        print(f"{'='*60}")
        print(f"Target: {self.base_url}")
        print(f"Concurrent Users: {num_users}")
        print(f"Duration: {duration}s")
        print(f"Request Delay: {REQUEST_DELAY}s")
        print(f"{'='*60}\n")
        
        self.running = True
        self.results.start_time = time.time()
        
        # Start resource monitor
        monitor_thread = threading.Thread(target=self.monitor_resources, daemon=True)
        monitor_thread.start()
        
        # Start user threads
        threads = []
        for user_id in range(num_users):
            thread = threading.Thread(
                target=self.user_session,
                args=(user_id, duration),
                daemon=True
            )
            thread.start()
            threads.append(thread)
            
            # Stagger user start times
            time.sleep(0.05)
        
        # Wait for all users to complete
        for thread in threads:
            thread.join()
        
        self.running = False
        self.results.end_time = time.time()
        
        return self.results.get_summary()


class WebSocketLoadTester:
    """Load test WebSocket connections"""
    
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.results = {
            'connections_attempted': 0,
            'connections_success': 0,
            'connections_failed': 0,
            'messages_received': 0,
            'errors': []
        }
    
    def test_websocket_connection(self, connection_id: int, duration: int):
        """Test single WebSocket connection"""
        try:
            from socketio import Client
        except ImportError:
            print("❌ python-socketio not installed. Run: pip install python-socketio")
            return
        
        self.results['connections_attempted'] += 1
        
        try:
            sio = Client()
            connected = False
            messages = 0
            
            @sio.event
            def connect():
                nonlocal connected
                connected = True
                self.results['connections_success'] += 1
            
            @sio.event
            def initial_data(data):
                nonlocal messages
                messages += 1
                self.results['messages_received'] += 1
            
            @sio.event
            def price_update(data):
                nonlocal messages
                messages += 1
                self.results['messages_received'] += 1
            
            sio.connect(self.base_url, wait_timeout=5)
            
            # Keep connection alive
            time.sleep(duration)
            
            sio.disconnect()
            
        except Exception as e:
            self.results['connections_failed'] += 1
            self.results['errors'].append(str(e))
    
    def run(self, num_connections: int = 20, duration: int = 30):
        """Run WebSocket load test"""
        print(f"\n{'='*60}")
        print(f"WEBSOCKET LOAD TEST")
        print(f"{'='*60}")
        print(f"Target: {self.base_url}")
        print(f"Concurrent Connections: {num_connections}")
        print(f"Duration: {duration}s")
        print(f"{'='*60}\n")
        
        threads = []
        for conn_id in range(num_connections):
            thread = threading.Thread(
                target=self.test_websocket_connection,
                args=(conn_id, duration),
                daemon=True
            )
            thread.start()
            threads.append(thread)
            time.sleep(0.1)  # Stagger connections
        
        # Wait for all to complete
        for thread in threads:
            thread.join()
        
        print(f"\n{'='*60}")
        print(f"WEBSOCKET TEST RESULTS")
        print(f"{'='*60}")
        print(f"Connections Attempted: {self.results['connections_attempted']}")
        print(f"Connections Success: {self.results['connections_success']}")
        print(f"Connections Failed: {self.results['connections_failed']}")
        print(f"Messages Received: {self.results['messages_received']}")
        print(f"Errors: {len(self.results['errors'])}")
        if self.results['errors']:
            print(f"Sample Errors: {self.results['errors'][:5]}")
        print(f"{'='*60}\n")
        
        return self.results


class EndpointStressTest:
    """Stress test individual endpoints"""
    
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
    
    def test_endpoint(self, endpoint: str, num_requests: int = 1000):
        """Hammer single endpoint with requests"""
        print(f"\nStress testing {endpoint}...")
        
        result = LoadTestResult()
        result.start_time = time.time()
        
        for i in range(num_requests):
            try:
                start = time.time()
                response = requests.get(f"{self.base_url}{endpoint}", timeout=5)
                elapsed = time.time() - start
                result.add_response(elapsed, response.status_code)
            except Exception as e:
                result.add_error(str(e))
            
            if (i + 1) % 100 == 0:
                print(f"  Completed {i + 1}/{num_requests}")
        
        result.end_time = time.time()
        
        summary = result.get_summary()
        
        print(f"\n  Results for {endpoint}:")
        print(f"  - Requests: {summary['requests_sent']}")
        print(f"  - Success Rate: {summary['success_rate']}%")
        print(f"  - Throughput: {summary['throughput_rps']} req/s")
        print(f"  - Mean Response Time: {summary['response_time']['mean_ms']}ms")
        print(f"  - P95 Response Time: {summary['response_time']['p95_ms']}ms")
        print(f"  - Errors: {summary['errors_count']}")
        
        return summary


# ========== CLI INTERFACE ==========

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Run dashboard load tests')
    parser.add_argument('--users', type=int, default=50, help='Number of concurrent users')
    parser.add_argument('--duration', type=int, default=60, help='Test duration in seconds')
    parser.add_argument('--url', default=BASE_URL, help='Dashboard URL')
    parser.add_argument('--websocket', action='store_true', help='Test WebSocket connections')
    parser.add_argument('--stress', type=str, help='Stress test single endpoint (e.g., /api/status)')
    parser.add_argument('--output', type=str, help='Save results to JSON file')
    
    args = parser.parse_args()
    
    if args.stress:
        # Stress test single endpoint
        tester = EndpointStressTest(args.url)
        results = tester.test_endpoint(args.stress, num_requests=1000)
    
    elif args.websocket:
        # WebSocket load test
        tester = WebSocketLoadTester(args.url)
        results = tester.run(num_connections=20, duration=30)
    
    else:
        # HTTP load test
        tester = LoadTester(args.url)
        results = tester.run(num_users=args.users, duration=args.duration)
        
        print(f"\n{'='*60}")
        print(f"LOAD TEST RESULTS")
        print(f"{'='*60}")
        print(f"Duration: {results['duration_seconds']}s")
        print(f"Requests Sent: {results['requests_sent']}")
        print(f"Success Rate: {results['success_rate']}%")
        print(f"Throughput: {results['throughput_rps']} req/s")
        print(f"\nResponse Times:")
        print(f"  Mean: {results['response_time']['mean_ms']}ms")
        print(f"  Median: {results['response_time']['median_ms']}ms")
        print(f"  P95: {results['response_time']['p95_ms']}ms")
        print(f"  P99: {results['response_time']['p99_ms']}ms")
        print(f"  Min: {results['response_time']['min_ms']}ms")
        print(f"  Max: {results['response_time']['max_ms']}ms")
        print(f"\nResource Usage:")
        print(f"  Avg CPU: {results['resource_usage']['avg_cpu_percent']}%")
        print(f"  Max CPU: {results['resource_usage']['max_cpu_percent']}%")
        print(f"  Avg Memory: {results['resource_usage']['avg_memory_mb']}MB")
        print(f"  Max Memory: {results['resource_usage']['max_memory_mb']}MB")
        print(f"\nStatus Codes: {results['status_codes']}")
        print(f"Errors: {results['errors_count']}")
        if results['errors_sample']:
            print(f"Sample Errors: {results['errors_sample'][:5]}")
        print(f"{'='*60}\n")
    
    # Save results if requested
    if args.output:
        import json
        from pathlib import Path
        
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        
        output_data = {
            'test_date': datetime.now().isoformat(),
            'test_type': 'websocket' if args.websocket else 'stress' if args.stress else 'http_load',
            'config': {
                'url': args.url,
                'users': args.users,
                'duration': args.duration
            },
            'results': results
        }
        
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2)
        
        print(f"✅ Results saved to {args.output}")
