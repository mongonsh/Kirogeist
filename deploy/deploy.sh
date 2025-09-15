#!/bin/bash

# Kirogeist AWS Deployment Script
set -e

# Configuration
ENVIRONMENT=${1:-production}
REGION=${2:-us-east-1}
STACK_NAME="kirogeist-${ENVIRONMENT}"
KEY_PAIR_NAME=${3:-""}
DOMAIN_NAME=${4:-""}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Starting Kirogeist deployment to AWS${NC}"
echo "Environment: ${ENVIRONMENT}"
echo "Region: ${REGION}"
echo "Stack Name: ${STACK_NAME}"

# Check prerequisites
check_prerequisites() {
    echo -e "${YELLOW}📋 Checking prerequisites...${NC}"
    
    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        echo -e "${RED}❌ AWS CLI not found. Please install it first.${NC}"
        exit 1
    fi
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}❌ Docker not found. Please install it first.${NC}"
        exit 1
    fi
    
    # Check if logged into AWS
    if ! aws sts get-caller-identity &> /dev/null; then
        echo -e "${RED}❌ Not logged into AWS. Please run 'aws configure' first.${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✅ Prerequisites check passed${NC}"
}

# Get OpenAI API Key
get_openai_key() {
    if [ -z "$OPENAI_API_KEY" ]; then
        echo -e "${YELLOW}🔑 OpenAI API Key not found in environment${NC}"
        read -s -p "Enter your OpenAI API Key: " OPENAI_API_KEY
        echo
    fi
    
    if [ -z "$OPENAI_API_KEY" ]; then
        echo -e "${RED}❌ OpenAI API Key is required${NC}"
        exit 1
    fi
}

# Get Key Pair Name
get_key_pair() {
    if [ -z "$KEY_PAIR_NAME" ]; then
        echo -e "${YELLOW}🔐 Available EC2 Key Pairs:${NC}"
        aws ec2 describe-key-pairs --region $REGION --query 'KeyPairs[].KeyName' --output table
        read -p "Enter the Key Pair name for EC2 access: " KEY_PAIR_NAME
    fi
    
    if [ -z "$KEY_PAIR_NAME" ]; then
        echo -e "${RED}❌ Key Pair name is required${NC}"
        exit 1
    fi
}

# Deploy CloudFormation stack
deploy_infrastructure() {
    echo -e "${YELLOW}☁️  Deploying infrastructure...${NC}"
    
    aws cloudformation deploy \
        --template-file deploy/aws-infrastructure.yml \
        --stack-name $STACK_NAME \
        --parameter-overrides \
            Environment=$ENVIRONMENT \
            KeyPairName=$KEY_PAIR_NAME \
            DomainName=$DOMAIN_NAME \
            OpenAIAPIKey=$OPENAI_API_KEY \
        --capabilities CAPABILITY_IAM \
        --region $REGION
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ Infrastructure deployed successfully${NC}"
    else
        echo -e "${RED}❌ Infrastructure deployment failed${NC}"
        exit 1
    fi
}

# Get stack outputs
get_stack_outputs() {
    echo -e "${YELLOW}📊 Getting stack outputs...${NC}"
    
    PUBLIC_IP=$(aws cloudformation describe-stacks \
        --stack-name $STACK_NAME \
        --region $REGION \
        --query 'Stacks[0].Outputs[?OutputKey==`PublicIP`].OutputValue' \
        --output text)
    
    S3_BUCKET=$(aws cloudformation describe-stacks \
        --stack-name $STACK_NAME \
        --region $REGION \
        --query 'Stacks[0].Outputs[?OutputKey==`S3BucketName`].OutputValue' \
        --output text)
    
    echo "Public IP: $PUBLIC_IP"
    echo "S3 Bucket: $S3_BUCKET"
}

# Generate SSL certificate
generate_ssl_cert() {
    echo -e "${YELLOW}🔒 Generating SSL certificate...${NC}"
    
    mkdir -p ssl
    
    # Generate self-signed certificate (replace with proper cert in production)
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout ssl/key.pem \
        -out ssl/cert.pem \
        -subj "/C=US/ST=State/L=City/O=Organization/CN=${PUBLIC_IP}"
    
    echo -e "${GREEN}✅ SSL certificate generated${NC}"
}

# Deploy application
deploy_application() {
    echo -e "${YELLOW}🐳 Deploying application...${NC}"
    
    # Create deployment package
    tar -czf kirogeist-deploy.tar.gz \
        --exclude='.git' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='node_modules' \
        --exclude='.env' \
        .
    
    # Copy to EC2 instance
    scp -i ~/.ssh/${KEY_PAIR_NAME}.pem \
        -o StrictHostKeyChecking=no \
        kirogeist-deploy.tar.gz \
        ec2-user@${PUBLIC_IP}:/tmp/
    
    # Deploy on EC2
    ssh -i ~/.ssh/${KEY_PAIR_NAME}.pem \
        -o StrictHostKeyChecking=no \
        ec2-user@${PUBLIC_IP} << EOF
        sudo mkdir -p /opt/kirogeist
        cd /opt/kirogeist
        sudo tar -xzf /tmp/kirogeist-deploy.tar.gz
        sudo chown -R ec2-user:ec2-user /opt/kirogeist
        
        # Create environment file
        cat > .env << EOL
FLASK_ENV=production
PORT=5051
AI_MODEL=gpt-4o-mini
OPENAI_API_KEY=${OPENAI_API_KEY}
S3_BUCKET=${S3_BUCKET}
AWS_REGION=${REGION}
EOL
        
        # Start application
        docker-compose down || true
        docker-compose up -d --build
EOF
    
    # Cleanup
    rm kirogeist-deploy.tar.gz
    
    echo -e "${GREEN}✅ Application deployed successfully${NC}"
}

# Setup monitoring
setup_monitoring() {
    echo -e "${YELLOW}📊 Setting up monitoring...${NC}"
    
    ssh -i ~/.ssh/${KEY_PAIR_NAME}.pem \
        -o StrictHostKeyChecking=no \
        ec2-user@${PUBLIC_IP} << 'EOF'
        # Create CloudWatch config
        sudo cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json << EOL
{
    "logs": {
        "logs_collected": {
            "files": {
                "collect_list": [
                    {
                        "file_path": "/opt/kirogeist/logs/*.log",
                        "log_group_name": "kirogeist-application",
                        "log_stream_name": "{instance_id}"
                    }
                ]
            }
        }
    },
    "metrics": {
        "namespace": "Kirogeist",
        "metrics_collected": {
            "cpu": {
                "measurement": ["cpu_usage_idle", "cpu_usage_iowait", "cpu_usage_user", "cpu_usage_system"],
                "metrics_collection_interval": 60
            },
            "disk": {
                "measurement": ["used_percent"],
                "metrics_collection_interval": 60,
                "resources": ["*"]
            },
            "mem": {
                "measurement": ["mem_used_percent"],
                "metrics_collection_interval": 60
            }
        }
    }
}
EOL
        
        # Start CloudWatch agent
        sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
            -a fetch-config \
            -m ec2 \
            -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json \
            -s
EOF
    
    echo -e "${GREEN}✅ Monitoring setup complete${NC}"
}

# Main deployment flow
main() {
    check_prerequisites
    get_openai_key
    get_key_pair
    deploy_infrastructure
    get_stack_outputs
    generate_ssl_cert
    
    # Wait for EC2 to be ready
    echo -e "${YELLOW}⏳ Waiting for EC2 instance to be ready...${NC}"
    sleep 60
    
    deploy_application
    setup_monitoring
    
    echo -e "${GREEN}🎉 Deployment completed successfully!${NC}"
    echo -e "${GREEN}🌐 Application URL: https://${PUBLIC_IP}${NC}"
    echo -e "${YELLOW}📝 SSH Access: ssh -i ~/.ssh/${KEY_PAIR_NAME}.pem ec2-user@${PUBLIC_IP}${NC}"
    echo -e "${YELLOW}📊 Logs: docker-compose logs -f${NC}"
}

# Run main function
main