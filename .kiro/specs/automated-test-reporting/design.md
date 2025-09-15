# Design Document

## Overview

This design enhances the kirogeist automated smoke testing system by adding comprehensive reporting capabilities, automated scheduling, historical analytics, API integration, and multi-project management. The system will maintain its current Selenium-based testing approach while adding new layers for data persistence, analytics, and automation.

## Architecture

### Current System Components
- **Flask Web Application** (`app.py`) - Main web interface and job management
- **Selenium Testing Engine** (`agents.py`) - Browser automation and screenshot capture  
- **Error Detection & Fixing** (`fixer.py`) - PHP error pattern matching and automated fixes
- **AI Integration** (`ai.py`) - OpenAI integration for intelligent error fixing

### New Components

#### 1. Data Layer
- **Database Models** - SQLite/PostgreSQL for test history and configuration
- **Report Storage** - Enhanced Excel reports with historical comparison
- **Configuration Management** - Project-specific settings and templates

#### 2. Scheduling & Notification Layer  
- **Task Scheduler** - Cron-like scheduling for automated test runs
- **Notification Service** - Email, webhook, and Slack integrations
- **Alert Engine** - Threshold-based alerting for critical issues

#### 3. Analytics & Reporting Layer
- **Trend Analysis Engine** - Historical data processing and insights
- **Dashboard Service** - Real-time metrics and visualizations  
- **Report Generator** - Executive summaries and detailed technical reports

#### 4. API Layer
- **REST API** - Endpoints for CI/CD integration
- **Authentication Service** - API key management and security
- **Webhook Handler** - External system integrations

## Components and Interfaces

### Database Schema

```sql
-- Projects configuration
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    base_url VARCHAR(500) NOT NULL,
    project_root VARCHAR(500),
    login_config JSON,
    error_patterns JSON,
    notification_config JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Test runs history
CREATE TABLE test_runs (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    job_id VARCHAR(50) UNIQUE NOT NULL,
    status VARCHAR(20) NOT NULL, -- queued, running, completed, failed
    test_type VARCHAR(20) NOT NULL,
    total_endpoints INTEGER,
    passed_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    report_path VARCHAR(500),
    trigger_type VARCHAR(20) DEFAULT 'manual', -- manual, scheduled, api
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Individual test results
CREATE TABLE test_results (
    id INTEGER PRIMARY KEY,
    test_run_id INTEGER REFERENCES test_runs(id),
    url VARCHAR(1000) NOT NULL,
    title VARCHAR(500),
    status VARCHAR(20) NOT NULL, -- PASSED, FAILED
    error_note TEXT,
    http_status INTEGER,
    screenshot_path VARCHAR(500),
    response_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Error categorization
CREATE TABLE error_categories (
    id INTEGER PRIMARY KEY,
    test_result_id INTEGER REFERENCES test_results(id),
    category VARCHAR(50) NOT NULL, -- Critical, High, Medium, Low
    error_type VARCHAR(100), -- php_error, http_error, timeout, etc
    file_path VARCHAR(500),
    line_number INTEGER,
    error_pattern VARCHAR(200),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Scheduled jobs
CREATE TABLE scheduled_jobs (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    name VARCHAR(100) NOT NULL,
    cron_expression VARCHAR(100) NOT NULL,
    test_config JSON NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- API keys
CREATE TABLE api_keys (
    id INTEGER PRIMARY KEY,
    key_hash VARCHAR(64) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    project_id INTEGER REFERENCES projects(id),
    permissions JSON, -- ["read", "write", "schedule"]
    expires_at TIMESTAMP,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Enhanced Error Categorization System

```python
class ErrorCategorizer:
    SEVERITY_RULES = {
        'Critical': [
            r'fatal\s+error',
            r'500\s+internal\s+server\s+error',
            r'database\s+connection\s+failed',
            r'class\s+.*\s+not\s+found'
        ],
        'High': [
            r'undefined\s+function',
            r'call\s+to\s+undefined\s+method',
            r'404\s+not\s+found',
            r'parse\s+error'
        ],
        'Medium': [
            r'undefined\s+array\s+key',
            r'undefined\s+variable',
            r'deprecated',
            r'notice'
        ],
        'Low': [
            r'warning',
            r'strict\s+standards'
        ]
    }
    
    def categorize_error(self, error_text: str, http_status: int) -> Dict[str, str]:
        # Implementation for error severity classification
        pass
```

### Scheduling Service

```python
class SchedulingService:
    def __init__(self, db_connection):
        self.db = db_connection
        self.scheduler = BackgroundScheduler()
        
    def add_scheduled_job(self, project_id: int, cron_expr: str, test_config: Dict):
        # Add cron-based test scheduling
        pass
        
    def execute_scheduled_test(self, job_id: int):
        # Execute test run from schedule
        pass
        
    def check_and_send_alerts(self, test_run_id: int):
        # Evaluate alert conditions and send notifications
        pass
```

### Analytics Engine

```python
class AnalyticsEngine:
    def generate_trend_report(self, project_id: int, days: int = 30) -> Dict:
        # Generate trend analysis for error rates, performance, etc.
        pass
        
    def compare_test_runs(self, run_id_1: int, run_id_2: int) -> Dict:
        # Compare two test runs for regression analysis
        pass
        
    def calculate_quality_score(self, project_id: int) -> float:
        # Calculate overall quality score based on recent test results
        pass
```

### REST API Endpoints

```python
# New API routes to add to app.py
@app.route('/api/v1/projects', methods=['GET', 'POST'])
@require_api_key
def api_projects():
    # Manage projects via API
    pass

@app.route('/api/v1/projects/<int:project_id>/test', methods=['POST'])
@require_api_key  
def api_trigger_test(project_id):
    # Trigger test run via API for CI/CD integration
    pass

@app.route('/api/v1/test-runs/<job_id>/status', methods=['GET'])
@require_api_key
def api_test_status(job_id):
    # Get test status for CI/CD pipeline decisions
    pass

@app.route('/api/v1/projects/<int:project_id>/analytics', methods=['GET'])
@require_api_key
def api_analytics(project_id):
    # Get analytics data for external dashboards
    pass
```

## Data Models

### Project Configuration Model
```python
@dataclass
class ProjectConfig:
    id: int
    name: str
    base_url: str
    project_root: str
    login_config: Dict[str, str]
    error_patterns: List[Dict]
    notification_config: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
```

### Enhanced Test Result Model
```python
@dataclass  
class TestResult:
    id: int
    test_run_id: int
    url: str
    title: str
    status: str
    error_note: str
    http_status: int
    screenshot_path: str
    response_time_ms: int
    error_category: str
    error_severity: str
    file_path: Optional[str]
    line_number: Optional[int]
    created_at: datetime
```

### Analytics Data Model
```python
@dataclass
class TrendData:
    project_id: int
    date_range: Tuple[datetime, datetime]
    total_tests: int
    pass_rate: float
    error_trends: Dict[str, List[int]]
    performance_trends: List[float]
    quality_score: float
    top_errors: List[Dict[str, Any]]
```

## Error Handling

### Enhanced Error Detection
- **Severity Classification** - Automatic categorization of errors by impact
- **Pattern Learning** - Machine learning to improve error detection over time
- **Context Awareness** - Consider error frequency and affected endpoints
- **False Positive Reduction** - Improved filtering of non-critical warnings

### Graceful Degradation
- **Database Failures** - Fall back to file-based storage for critical data
- **Notification Failures** - Queue notifications for retry with exponential backoff
- **Scheduler Failures** - Log missed jobs and attempt recovery on restart
- **API Timeouts** - Implement circuit breaker pattern for external services

### Error Recovery
```python
class ErrorRecoveryService:
    def handle_test_failure(self, job_id: str, error: Exception):
        # Log error, attempt recovery, notify if critical
        pass
        
    def handle_notification_failure(self, notification_id: int, error: Exception):
        # Queue for retry with exponential backoff
        pass
        
    def handle_database_failure(self, operation: str, data: Dict):
        # Fall back to file storage, queue for DB retry
        pass
```

## Testing Strategy

### Unit Testing
- **Database Models** - Test CRUD operations and relationships
- **Analytics Engine** - Test calculation accuracy and edge cases
- **Error Categorization** - Test pattern matching and severity assignment
- **API Endpoints** - Test authentication, validation, and responses

### Integration Testing  
- **End-to-End Workflows** - Test complete test run lifecycle
- **Notification Systems** - Test email, webhook, and Slack integrations
- **Scheduler Integration** - Test cron job execution and error handling
- **Database Migrations** - Test schema changes and data preservation

### Performance Testing
- **Large Test Suites** - Test system performance with 1000+ endpoints
- **Concurrent Test Runs** - Test multiple simultaneous test executions
- **Database Query Performance** - Test analytics queries on large datasets
- **Memory Usage** - Monitor memory consumption during long test runs

### Test Data Management
```python
class TestDataFactory:
    @staticmethod
    def create_test_project() -> ProjectConfig:
        # Create test project configuration
        pass
        
    @staticmethod  
    def create_test_run_data(project_id: int, endpoint_count: int) -> List[TestResult]:
        # Generate realistic test result data
        pass
        
    @staticmethod
    def create_error_scenarios() -> List[Dict[str, Any]]:
        # Create various error scenarios for testing
        pass
```

### Automated Testing Integration
- **CI/CD Pipeline Tests** - Automated testing of API endpoints
- **Regression Testing** - Ensure new features don't break existing functionality  
- **Load Testing** - Validate system performance under stress
- **Security Testing** - Test API authentication and data protection