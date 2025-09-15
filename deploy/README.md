# Kirogeist AWS Production Deployment Guide

This guide will help you deploy your kirogeist PHP testing system to AWS production environment.

## 🏗️ Architecture Overview

The production deployment includes:
- **EC2 Instance** - Runs the application in Docker containers
- **Application Load Balancer** - Handles traffic distribution and SSL termination
- **S3 Bucket** - Stores test reports and screenshots
- **CloudWatch** - Monitoring and logging
- **Nginx** - Reverse proxy with rate limiting and security headers
- **Docker** - Containerized application deployment

## 📋 Prerequisites

### 1. AWS Account Setup
- AWS CLI installed and configured
- Appropriate IAM permissions for EC2, S3, CloudFormation
- EC2 Key Pair created for SSH access

### 2. Local Requirements
- Docker and Docker Compose installed
- OpenAI API key for AI features
- Domain name (optional, but recommended)

### 3. Install AWS CLI
```bash
# macOS
brew install awscli

# Linux
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# Configure AWS CLI
aws configure
```

## 🚀 Quick Deployment

### Option 1: Automated Deployment Script
```bash
# Make deployment script executable
chmod +x deploy/deploy.sh

# Deploy to production
./deploy/deploy.sh production us-east-1 your-key-pair-name your-domain.com

# Deploy to staging
./deploy/deploy.sh staging us-east-1 your-key-pair-name
```

### Option 2: Manual Step-by-Step Deployment

#### Step 1: Deploy Infrastructure
```bash
# Deploy CloudFormation stack
aws cloudformation deploy \
  --template-file deploy/aws-infrastructure.yml \
  --stack-name kirogeist-production \
  --parameter-overrides \
    Environment=production \
    KeyPairName=your-key-pair-name \
    OpenAIAPIKey=your-openai-api-key \
  --capabilities CAPABILITY_IAM \
  --region us-east-1
```

#### Step 2: Get Stack Outputs
```bash
# Get public IP
PUBLIC_IP=$(aws cloudformation describe-stacks \
  --stack-name kirogeist-production \
  --query 'Stacks[0].Outputs[?OutputKey==`PublicIP`].OutputValue' \
  --output text)

echo "Public IP: $PUBLIC_IP"
```

#### Step 3: Deploy Application
```bash
# Create deployment package
tar -czf kirogeist-deploy.tar.gz \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  .

# Copy to EC2
scp -i ~/.ssh/your-key-pair.pem kirogeist-deploy.tar.gz ec2-user@$PUBLIC_IP:/tmp/

# SSH and deploy
ssh -i ~/.ssh/your-key-pair.pem ec2-user@$PUBLIC_IP
```

#### Step 4: Setup Application on EC2
```bash
# On EC2 instance
sudo mkdir -p /opt/kirogeist
cd /opt/kirogeist
sudo tar -xzf /tmp/kirogeist-deploy.tar.gz
sudo chown -R ec2-user:ec2-user /opt/kirogeist

# Create environment file
cp deploy/production.env .env
# Edit .env with your actual values

# Start application
docker-compose up -d --build
```

## 🔧 Configuration

### Environment Variables
Copy `deploy/production.env` to `.env` and update:

```bash
# Required
OPENAI_API_KEY=your-openai-api-key
AWS_REGION=us-east-1
S3_BUCKET=your-s3-bucket-name

# Optional but recommended
SECRET_KEY=your-secret-key
ALLOWED_HOSTS=your-domain.com
SMTP_HOST=smtp.gmail.com
SMTP_USER=your-email@gmail.com
```

### SSL Certificate
For production, replace the self-signed certificate:

```bash
# Using Let's Encrypt (recommended)
sudo certbot --nginx -d your-domain.com

# Or upload your own certificate
sudo cp your-cert.pem /opt/kirogeist/ssl/cert.pem
sudo cp your-key.pem /opt/kirogeist/ssl/key.pem
```

### Domain Setup
1. Point your domain to the Elastic IP
2. Update `ALLOWED_HOSTS` in `.env`
3. Update nginx configuration if needed

## 📊 Monitoring & Maintenance

### Health Checks
```bash
# Check application health
curl https://your-domain.com/ai/health

# Check Docker containers
docker-compose ps

# View logs
docker-compose logs -f
```

### CloudWatch Logs
- Application logs: `/aws/ec2/kirogeist-application`
- System metrics: Available in CloudWatch dashboard

### Backup Strategy
```bash
# Backup reports and data
aws s3 sync /opt/kirogeist/reports s3://your-backup-bucket/reports/
aws s3 sync /opt/kirogeist/uploads s3://your-backup-bucket/uploads/
```

## 🔒 Security Considerations

### Network Security
- Security groups restrict access to necessary ports only
- Nginx provides rate limiting and security headers
- SSL/TLS encryption for all traffic

### Application Security
- API key authentication for external access
- Input validation and sanitization
- Regular security updates

### Data Protection
- S3 bucket with private access only
- Encrypted data transmission
- Regular backups

## 🚨 Troubleshooting

### Common Issues

#### Application Won't Start
```bash
# Check Docker logs
docker-compose logs kirogeist

# Check system resources
df -h
free -m
```

#### Chrome/Selenium Issues
```bash
# Check Chrome installation
docker-compose exec kirogeist google-chrome --version

# Check display server
docker-compose exec kirogeist ps aux | grep Xvfb
```

#### SSL Certificate Issues
```bash
# Check certificate validity
openssl x509 -in ssl/cert.pem -text -noout

# Regenerate self-signed certificate
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ssl/key.pem -out ssl/cert.pem
```

### Performance Optimization

#### For High Load
```bash
# Scale horizontally with multiple instances
# Use Application Load Balancer
# Implement Redis for session storage
# Use RDS for database instead of SQLite
```

#### Memory Optimization
```bash
# Limit Chrome processes
# Implement test queue system
# Regular cleanup of old reports
```

## 📈 Scaling Considerations

### Horizontal Scaling
- Use Auto Scaling Groups
- Implement load balancing
- Shared storage for reports (EFS or S3)

### Database Scaling
- Migrate from SQLite to RDS PostgreSQL
- Implement connection pooling
- Add read replicas for analytics

### Monitoring at Scale
- Use CloudWatch dashboards
- Set up alerts for critical metrics
- Implement distributed tracing

## 💰 Cost Optimization

### EC2 Optimization
- Use Reserved Instances for predictable workloads
- Consider Spot Instances for development
- Right-size instances based on usage

### Storage Optimization
- Implement S3 lifecycle policies
- Use S3 Intelligent Tiering
- Regular cleanup of old reports

### Monitoring Costs
- Set up billing alerts
- Use AWS Cost Explorer
- Regular cost reviews

## 🔄 CI/CD Integration

### GitHub Actions Example
```yaml
name: Deploy to AWS
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Deploy to AWS
        run: ./deploy/deploy.sh production us-east-1 ${{ secrets.KEY_PAIR_NAME }}
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

## 📞 Support

For deployment issues:
1. Check CloudFormation stack events
2. Review EC2 instance logs
3. Verify security group settings
4. Check IAM permissions

Remember to regularly update your system and monitor security advisories!