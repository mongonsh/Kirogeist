---
inclusion: fileMatch
fileMatchPattern: "Dockerfile,docker-compose*,deploy/*,*deploy*,*aws*"
---

# Deployment Guidelines for Kirogeist

## Docker Best Practices

### Multi-stage Builds
Use multi-stage builds to minimize image size and improve security:

```dockerfile
# Build stage
FROM python:3.11-slim as builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.11-slim
COPY --from=builder /root/.local /root/.local
# Add Chrome and dependencies
# Copy application code
```

### Security Considerations
```dockerfile
# Create non-root user
RUN groupadd -r kirogeist && useradd -r -g kirogeist kirogeist
USER kirogeist

# Use specific versions
FROM python:3.11.8-slim

# Minimize attack surface
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg unzip curl \
    && rm -rf /var/lib/apt/lists/*
```

### Environment Configuration
```yaml
# docker-compose.yml
services:
  kirogeist:
    environment:
      - FLASK_ENV=production
      - PYTHONUNBUFFERED=1
      - PYTHONDONTWRITEBYTECODE=1
    volumes:
      - ./data:/app/data:rw
      - ./logs:/app/logs:rw
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5051/ai/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

## AWS Infrastructure Patterns

### CloudFormation Best Practices
```yaml
# Use parameters for flexibility
Parameters:
  Environment:
    Type: String
    AllowedValues: [dev, staging, prod]
  
  InstanceType:
    Type: String
    Default: t3.medium
    AllowedValues: [t3.small, t3.medium, t3.large]

# Use conditions for environment-specific resources
Conditions:
  IsProduction: !Equals [!Ref Environment, prod]

Resources:
  # Use conditions
  ProductionOnlyResource:
    Type: AWS::S3::Bucket
    Condition: IsProduction
```

### Security Groups
```yaml
ApplicationSecurityGroup:
  Type: AWS::EC2::SecurityGroup
  Properties:
    GroupDescription: Kirogeist application security group
    SecurityGroupIngress:
      # SSH access (restrict to your IP in production)
      - IpProtocol: tcp
        FromPort: 22
        ToPort: 22
        CidrIp: 0.0.0.0/0  # Change to your IP range
      
      # HTTP/HTTPS
      - IpProtocol: tcp
        FromPort: 80
        ToPort: 80
        CidrIp: 0.0.0.0/0
      
      - IpProtocol: tcp
        FromPort: 443
        ToPort: 443
        CidrIp: 0.0.0.0/0
```

### IAM Roles and Policies
```yaml
EC2Role:
  Type: AWS::IAM::Role
  Properties:
    AssumeRolePolicyDocument:
      Version: '2012-10-17'
      Statement:
        - Effect: Allow
          Principal:
            Service: ec2.amazonaws.com
          Action: sts:AssumeRole
    Policies:
      - PolicyName: S3Access
        PolicyDocument:
          Version: '2012-10-17'
          Statement:
            - Effect: Allow
              Action:
                - s3:GetObject
                - s3:PutObject
                - s3:DeleteObject
              Resource: !Sub "${S3Bucket}/*"
```

## Deployment Automation

### Deployment Script Structure
```bash
#!/bin/bash
set -e  # Exit on any error

# Configuration validation
validate_config() {
    if [ -z "$OPENAI_API_KEY" ]; then
        echo "Error: OPENAI_API_KEY not set"
        exit 1
    fi
}

# Infrastructure deployment
deploy_infrastructure() {
    aws cloudformation deploy \
        --template-file infrastructure.yml \
        --stack-name $STACK_NAME \
        --capabilities CAPABILITY_IAM \
        --parameter-overrides \
            Environment=$ENVIRONMENT \
            KeyPairName=$KEY_PAIR_NAME
}

# Application deployment
deploy_application() {
    # Build and push Docker image
    docker build -t kirogeist:$VERSION .
    
    # Deploy to EC2
    ssh -i $KEY_PAIR ec2-user@$PUBLIC_IP << 'EOF'
        cd /opt/kirogeist
        docker-compose pull
        docker-compose up -d --remove-orphans
EOF
}
```

### Health Checks and Monitoring
```bash
# Health check function
check_health() {
    local url=$1
    local max_attempts=30
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        if curl -f -s "$url/ai/health" > /dev/null; then
            echo "✅ Application is healthy"
            return 0
        fi
        
        echo "⏳ Waiting for application... ($attempt/$max_attempts)"
        sleep 10
        ((attempt++))
    done
    
    echo "❌ Application health check failed"
    return 1
}
```

## Environment Management

### Configuration Hierarchy
1. **Default values** in code
2. **Environment files** (.env)
3. **Environment variables** (override .env)
4. **Command line arguments** (highest priority)

### Secrets Management
```bash
# Use AWS Systems Manager Parameter Store
aws ssm put-parameter \
    --name "/kirogeist/prod/openai-api-key" \
    --value "$OPENAI_API_KEY" \
    --type "SecureString"

# Retrieve in application
OPENAI_API_KEY=$(aws ssm get-parameter \
    --name "/kirogeist/prod/openai-api-key" \
    --with-decryption \
    --query 'Parameter.Value' \
    --output text)
```

### Environment-Specific Configurations
```python
# config.py
import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key'
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
    
class DevelopmentConfig(Config):
    DEBUG = True
    DATABASE_URL = 'sqlite:///dev.db'

class ProductionConfig(Config):
    DEBUG = False
    DATABASE_URL = os.environ.get('DATABASE_URL')
    
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
```

## Monitoring and Logging

### CloudWatch Integration
```python
import boto3
import logging

# Configure CloudWatch logging
def setup_cloudwatch_logging():
    cloudwatch = boto3.client('logs')
    
    handler = CloudWatchLogsHandler(
        log_group='kirogeist-application',
        stream_name=f'{os.environ.get("HOSTNAME", "unknown")}'
    )
    
    logging.getLogger().addHandler(handler)
```

### Application Metrics
```python
# Custom metrics for monitoring
def record_test_metrics(test_run_id: str, results: Dict):
    cloudwatch = boto3.client('cloudwatch')
    
    cloudwatch.put_metric_data(
        Namespace='Kirogeist',
        MetricData=[
            {
                'MetricName': 'TestsExecuted',
                'Value': results['total'],
                'Unit': 'Count'
            },
            {
                'MetricName': 'TestFailureRate',
                'Value': results['failed'] / results['total'] * 100,
                'Unit': 'Percent'
            }
        ]
    )
```

## Backup and Recovery

### Data Backup Strategy
```bash
# Backup script
backup_data() {
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_bucket="kirogeist-backups"
    
    # Backup reports and screenshots
    aws s3 sync /opt/kirogeist/reports s3://$backup_bucket/reports/$timestamp/
    aws s3 sync /opt/kirogeist/shots s3://$backup_bucket/shots/$timestamp/
    
    # Backup database (if using file-based DB)
    if [ -f /opt/kirogeist/kirogeist.db ]; then
        aws s3 cp /opt/kirogeist/kirogeist.db s3://$backup_bucket/database/kirogeist_$timestamp.db
    fi
}
```

### Disaster Recovery
```bash
# Recovery script
restore_data() {
    local backup_timestamp=$1
    local backup_bucket="kirogeist-backups"
    
    # Stop application
    docker-compose down
    
    # Restore data
    aws s3 sync s3://$backup_bucket/reports/$backup_timestamp/ /opt/kirogeist/reports/
    aws s3 sync s3://$backup_bucket/shots/$backup_timestamp/ /opt/kirogeist/shots/
    
    # Restart application
    docker-compose up -d
}
```

## Performance Optimization

### Resource Limits
```yaml
# docker-compose.yml
services:
  kirogeist:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 4G
        reservations:
          cpus: '1.0'
          memory: 2G
```

### Caching Strategies
```python
# Redis caching for test results
import redis

cache = redis.Redis(host='redis', port=6379, db=0)

def get_cached_result(test_id: str):
    cached = cache.get(f"test_result:{test_id}")
    if cached:
        return json.loads(cached)
    return None

def cache_result(test_id: str, result: Dict, ttl: int = 3600):
    cache.setex(f"test_result:{test_id}", ttl, json.dumps(result))
```

## Security Hardening

### Network Security
```bash
# Firewall rules (iptables)
iptables -A INPUT -p tcp --dport 22 -s YOUR_IP_RANGE -j ACCEPT
iptables -A INPUT -p tcp --dport 80 -j ACCEPT
iptables -A INPUT -p tcp --dport 443 -j ACCEPT
iptables -A INPUT -j DROP
```

### Application Security
```python
# Input validation
from flask import request
from werkzeug.utils import secure_filename

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if not file.filename.endswith('.xlsx'):
        return jsonify({'error': 'Invalid file type'}), 400
    
    filename = secure_filename(file.filename)
    # Process file...
```