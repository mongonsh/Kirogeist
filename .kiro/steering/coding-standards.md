---
inclusion: always
---

# Kirogeist Coding Standards

## Python Code Style
- Follow PEP 8 with 4-space indentation
- Use type hints for function parameters and return values
- Prefer f-strings for string formatting
- Use descriptive variable names (e.g., `test_run_id` not `id`)
- Keep functions focused and under 50 lines when possible

## Error Handling Patterns
```python
# Always use try-except for external operations
try:
    result = external_operation()
    return result, True, "success"
except Exception as e:
    return None, False, f"error: {type(e).__name__}: {e}"

# Use tuple returns for operations that can fail
def process_file(path: str) -> Tuple[bool, str]:
    """Returns (success, message)"""
    pass
```

## Flask Route Conventions
- Use descriptive route names that match functionality
- Return consistent JSON structure: `{"ok": bool, "data": any, "error": str}`
- Include proper HTTP status codes
- Use request validation for all inputs

```python
@app.route("/api/v1/resource", methods=["POST"])
def create_resource():
    try:
        data = request.get_json()
        if not data or not data.get("required_field"):
            return jsonify({"ok": False, "error": "Missing required field"}), 400
        
        result = process_data(data)
        return jsonify({"ok": True, "data": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
```

## Database Patterns
- Use SQLAlchemy models with proper relationships
- Always use transactions for multi-table operations
- Include created_at and updated_at timestamps
- Use meaningful foreign key names

```python
class TestRun(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    job_id = db.Column(db.String(50), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

## Selenium Best Practices
- Always use explicit waits instead of time.sleep()
- Handle stale element exceptions gracefully
- Take screenshots on failures for debugging
- Use page object pattern for complex interactions

```python
# Good
wait = WebDriverWait(driver, 10)
element = wait.until(EC.presence_of_element_located((By.ID, "element-id")))

# Bad
time.sleep(5)
element = driver.find_element(By.ID, "element-id")
```

## Error Pattern Writing
- Use descriptive pattern IDs that indicate the fix type
- Include comprehensive notes explaining the pattern
- Test patterns against real-world examples
- Make patterns idempotent (safe to run multiple times)

```yaml
- id: undefined_array_key_superglobals
  match: 'undefined array key'
  search: |
    (\$_(GET|POST|REQUEST|COOKIE)\[['"]([A-Za-z0-9_]+)['"]\])(?!\s*\?\?)
  replace: '(\1 ?? null)'
  note: 'Guard superglobal access with ?? (idempotent).'
```

## Testing Standards
- Write unit tests for all utility functions
- Use pytest fixtures for common test data
- Mock external dependencies (OpenAI, Selenium)
- Include integration tests for critical workflows

## Documentation Requirements
- All public functions must have docstrings
- Include type hints and parameter descriptions
- Document complex algorithms and business logic
- Keep README files updated with setup instructions

## Security Considerations
- Validate all user inputs
- Use parameterized queries for database operations
- Sanitize file paths to prevent directory traversal
- Never log sensitive information (API keys, passwords)
- Use environment variables for configuration