---
inclusion: always
---

# Kirogeist Project Overview

## Project Purpose
Kirogeist is an automated smoke testing system specifically designed for PHP applications undergoing PHP 8+ migration. The system uses Selenium for browser automation, AI-powered error detection and fixing, and generates comprehensive Excel reports with screenshots.

## Core Architecture
- **Flask Web Application** (`app.py`) - Main web interface and job management
- **Selenium Testing Engine** (`agents.py`) - Browser automation and screenshot capture
- **Error Detection & Fixing** (`fixer.py`) - PHP error pattern matching and automated fixes
- **AI Integration** (`ai.py`) - OpenAI integration for intelligent error fixing
- **Pattern Configuration** (`patterns.yaml`) - Error detection rules and fix patterns

## Key Technologies
- **Backend**: Python Flask, Selenium WebDriver, OpenAI API
- **Frontend**: HTML/JavaScript with Tailwind CSS, Chart.js for visualizations
- **Testing**: Chrome/Chromium headless browser automation
- **Reports**: Excel generation with embedded screenshots using xlsxwriter
- **Deployment**: Docker containers, AWS infrastructure

## Important Design Principles
1. **Minimal Code Changes** - Automated fixes should be surgical and preserve application behavior
2. **Screenshot Documentation** - Every test includes visual evidence for manual review
3. **Pattern-Based Fixing** - Use configurable YAML patterns for common PHP migration issues
4. **AI Fallback** - When patterns fail, use LLM for intelligent error resolution
5. **Production Safety** - Always create backups before applying fixes

## File Structure Conventions
- `app.py` - Main Flask application with routes and job management
- `fixer.py` - Error detection, pattern matching, and automated fixing logic
- `agents.py` - Selenium automation and browser interaction
- `patterns.yaml` - Configurable error patterns and replacement rules
- `templates/` - HTML templates for web interface
- `uploads/` - Temporary file storage for Excel uploads
- `reports/` - Generated test reports and screenshots
- `shots/` - Screenshot storage organized by job ID

## Error Handling Philosophy
- **Categorize by Severity**: Critical, High, Medium, Low based on impact
- **Context-Aware Fixes**: Consider file type (.php, .tpl, .phtml) and coding style
- **Idempotent Operations**: Fixes should be safe to run multiple times
- **Preserve Style**: Maintain existing code formatting and conventions
- **Backup First**: Always create .bak files before modifications