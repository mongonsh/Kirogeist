# Kirogeist - Automated PHP Testing & Migration Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/)

Kirogeist is an automated smoke testing system specifically designed for PHP applications undergoing PHP 8+ migration. It combines Selenium browser automation, AI-powered error detection, and intelligent code fixing to help developers identify and resolve migration issues efficiently.

## 🚀 Features

### Core Testing Capabilities
- **Automated Smoke Testing** - Test multiple endpoints with browser automation
- **Screenshot Documentation** - Visual evidence for every test with full-page captures
- **Error Detection** - Advanced PHP error pattern matching and categorization
- **Excel Reports** - Comprehensive reports with embedded screenshots

### AI-Powered Error Fixing
- **Pattern-Based Fixes** - Configurable YAML patterns for common PHP migration issues
- **AI Fallback** - OpenAI integration for intelligent error resolution when patterns fail
- **Style Preservation** - Maintains existing code formatting and conventions
- **Safe Operations** - Always creates backups before applying fixes

### Advanced Features
- **Multi-Project Support** - Manage testing for multiple PHP applications
- **Scheduled Testing** - Automated test runs with cron-like scheduling
- **API Integration** - REST endpoints for CI/CD pipeline integration
- **Historical Analytics** - Track quality trends and error patterns over time

## 📋 Prerequisites

### System Requirements
- Python 3.11 or higher
- Chrome/Chromium browser
- Docker (for containerized deployment)
- 4GB+ RAM recommended

### API Keys
- OpenAI API key (for AI-powered error fixing)
- AWS credentials (for production deployment)

## 🛠️ Installation

### Quick Start with Docker
```bash
# Clone the repository
git clone https://github.com/yourusername/kirogeist.git
cd kirogeist

# Set up environment variables
cp deploy/production.env .env
# Edit .env with your configuration

# Start with Docker Compose
docker-compose up -d

# Access the application
open http://localhost:5051
```

### Local Development Setup
```bash
# Install Python dependencies
pip install -r requirements.txt

# Set up environment variables
export OPENAI_API_KEY="your-openai-api-key"
export FLASK_ENV=development

# Run the application
python app.py
```

### Chrome/Selenium Setup
The application automatically manages Chrome WebDriver through `webdriver-manager`. For headless operation in production, ensure Chrome is properly installed:

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y google-chrome-stable

# macOS
brew install --cask google-chrome
```

## 🎯 Usage

### Basic Smoke Testing

1. **Access the Web Interface**
   - Open http://localhost:5051 in your browser
   - Configure your target application's base URL

2. **Configure Test Parameters**
   - **Base URL**: Your PHP application's root URL
   - **Test Type**: Choose from smoke, e2e, or integration testing
   - **Endpoints**: Upload Excel file or manually enter URLs to test

3. **Optional Login Configuration**
   - Configure authentication if your application requires login
   - Supports custom field names for username, password, and submit buttons

4. **Run Tests**
   - Click "Run Test" to start automated testing
   - Monitor progress in real-time
   - Download Excel reports with screenshots and error analysis

### Error Fixing Workflow

1. **Automatic Error Detection**
   - Tests automatically detect PHP errors, warnings, and notices
   - Errors are categorized by severity (Critical, High, Medium, Low)

2. **Review Fix Candidates**
   - After test completion, review detected errors in the Fix Candidates panel
   - Select files and error lines you want to fix

3. **Apply Fixes**
   - Choose fix strategy (pattern-based or AI-powered)
   - Configure dynamic property handling for PHP 8.2+ compatibility
   - Apply fixes with automatic backup creation

### API Integration

```bash
# Trigger test via API
curl -X POST http://localhost:5051/run-test \
  -F "base_url=http://your-app.com" \
  -F "test_type=smoke" \
  -F "endpoints_text=/" \
  -F "project_root=/path/to/your/php/project"

# Check test status
curl http://localhost:5051/job/{job_id}/status

# Download report
curl -O http://localhost:5051/job/{job_id}/download
```

## ⚙️ Configuration

### Environment Variables
```bash
# Core Configuration
FLASK_ENV=production
PORT=5051
SECRET_KEY=your-secret-key

# AI Configuration
AI_MODEL=gpt-4o-mini
OPENAI_API_KEY=your-openai-api-key

# AWS Configuration (for production)
AWS_REGION=us-east-1
S3_BUCKET=your-s3-bucket-name

# Path Mapping (Docker container to host paths)
PATH_MAPS=[{"from": "/container/path", "to": "/host/path"}]

# PHP Fix Patterns
PHP_FIX_PATTERNS=./patterns.yaml
```

### Error Pattern Configuration
Customize error detection and fixing patterns in `patterns.yaml`:

```yaml
rules:
  - id: undefined_array_key_superglobals
    match: 'undefined array key'
    search: |
      (\$_(GET|POST|REQUEST|COOKIE)\[['"]([A-Za-z0-9_]+)['"]\])(?!\s*\?\?)
    replace: '(\1 ?? null)'
    note: 'Guard superglobal access with ?? (idempotent).'
```

## 🏗️ Architecture

### Core Components
- **Flask Web Application** (`app.py`) - Main web interface and job management
- **Selenium Testing Engine** (`agents.py`) - Browser automation and screenshot capture
- **Error Detection & Fixing** (`fixer.py`) - PHP error pattern matching and automated fixes
- **AI Integration** (`ai.py`) - OpenAI integration for intelligent error fixing
- **Pattern Configuration** (`patterns.yaml`) - Error detection rules and fix patterns

### File Structure
```
kirogeist/
├── app.py                 # Main Flask application
├── fixer.py              # Error detection and fixing logic
├── agents.py             # Selenium automation
├── ai.py                 # AI integration
├── patterns.yaml         # Error patterns configuration
├── templates/            # HTML templates
├── uploads/              # Temporary file storage
├── reports/              # Generated test reports
├── shots/                # Screenshot storage
├── deploy/               # Deployment configurations
└── .kiro/                # Kiro IDE configurations
    ├── specs/            # Feature specifications
    ├── steering/         # AI agent guidance
    └── hooks/            # Automation hooks
```

## 🚀 Production Deployment

### AWS Deployment
Use the provided deployment scripts for production AWS deployment:

```bash
# Make deployment script executable
chmod +x deploy/deploy.sh

# Deploy to AWS
./deploy/deploy.sh production us-east-1 your-key-pair-name your-domain.com
```

The deployment includes:
- EC2 instance with auto-scaling
- S3 bucket for report storage
- CloudWatch monitoring
- SSL/TLS encryption
- Security groups and IAM roles

### Docker Production
```bash
# Build production image
docker build -t kirogeist:latest .

# Run with production configuration
docker-compose -f docker-compose.yml up -d
```

## 🧪 Testing

### Running Tests
```bash
# Install test dependencies
pip install pytest pytest-cov

# Run unit tests
pytest tests/

# Run with coverage
pytest --cov=. tests/
```

### Test Categories
- **Unit Tests** - Individual component testing
- **Integration Tests** - End-to-end workflow testing
- **Selenium Tests** - Browser automation testing
- **API Tests** - REST endpoint testing

## 🤝 Contributing

### Development Setup
1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Follow the coding standards in `.kiro/steering/coding-standards.md`
4. Write tests for new functionality
5. Submit a pull request

### Coding Standards
- Follow PEP 8 for Python code
- Use type hints for function parameters and return values
- Write comprehensive docstrings
- Include unit tests for new features
- Maintain backward compatibility

## 📊 Monitoring & Analytics

### Built-in Monitoring
- Real-time test progress tracking
- Error categorization and trending
- Performance metrics collection
- Historical data analysis

### CloudWatch Integration (AWS)
- Application logs and metrics
- Custom dashboards
- Automated alerting
- Performance monitoring

## 🔒 Security

### Security Features
- Input validation and sanitization
- Secure file handling
- API authentication
- Environment variable configuration
- Regular security updates

### Best Practices
- Never commit API keys or secrets
- Use environment variables for configuration
- Regularly update dependencies
- Follow principle of least privilege for AWS IAM

## 📚 Documentation

### Additional Resources
- [Deployment Guide](deploy/README.md) - Comprehensive deployment instructions
- [API Documentation](docs/api.md) - REST API reference
- [Error Patterns Guide](docs/patterns.md) - Custom pattern creation
- [Troubleshooting Guide](docs/troubleshooting.md) - Common issues and solutions

## 🐛 Troubleshooting

### Common Issues

#### Chrome/Selenium Issues
```bash
# Check Chrome installation
google-chrome --version

# Verify WebDriver
python -c "from selenium import webdriver; print('WebDriver OK')"
```

#### Application Won't Start
```bash
# Check logs
docker-compose logs kirogeist

# Verify environment variables
env | grep OPENAI_API_KEY
```

#### Memory Issues
- Increase Docker memory allocation
- Limit concurrent test runs
- Regular cleanup of old reports

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [Selenium WebDriver](https://selenium.dev/) - Browser automation
- [OpenAI API](https://openai.com/) - AI-powered error fixing
- [Flask](https://flask.palletsprojects.com/) - Web framework
- [Tailwind CSS](https://tailwindcss.com/) - UI styling
- [Chart.js](https://www.chartjs.org/) - Data visualization

## 📞 Support

For support and questions:
- Create an issue on GitHub
- Check the troubleshooting guide
- Review the documentation

---

**Kirogeist** - Making PHP migration testing automated, intelligent, and reliable.