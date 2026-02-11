# Dynamic Agent Marketplace Platform (Production)

**Production-ready intelligent agent platform with multi-source tool orchestration**

---

## 🎯 Overview

Enterprise-grade autonomous agent platform orchestrating tools from **three dynamic sources**:

- **🔌 MCP Servers** - Enterprise integrations (Confluence, GitHub)
- **📦 S3 Skills** - Dynamically loaded Python skills
- **🖥️ Computer Use** - Browser automation

**Key Feature:** Generic S3 skill executor supports ANY future skill without code changes.

---

## ✨ Features

- Claude Sonnet 4.5 orchestration
- Real-time streaming API (SSE)
- Generic S3 skill executor (zero-code extensibility)
- Docker containerization
- AWS ECS deployment ready

---

## 🚀 Quick Start

### 1. Setup Environment
\`\`\`bash
# Create .env file
cat > .env << EOF
ANTHROPIC_API_KEY=your-key-here
AWS_REGION=us-west-2
AWS_ACCESS_KEY_ID=your-aws-key
AWS_SECRET_ACCESS_KEY=your-aws-secret
S3_BUCKET=your-skills-bucket
EOF
\`\`\`

### 2. Start Services
\`\`\`bash
docker-compose up -d
\`\`\`

### 3. Test
\`\`\`bash
curl http://localhost:8003/health
\`\`\`

---

## 📊 API Endpoints

**POST /execute** - Standard execution
**POST /execute/stream** - Streaming (SSE)
**GET /health** - Health check

---

## 🏗️ Architecture

\`\`\`
FastAPI API (8003)
  ↓
Agent Runner
  ↓
┌─────────┬──────────┬────────────┐
│   MCP   │ S3 Skills│ Computer   │
│  Tools  │(Generic) │    Use     │
└─────────┴──────────┴────────────┘
\`\`\`

---

## 🔧 Production Deployment

See \`infrastructure/\` for:
- CloudFormation templates
- ECS task definitions
- Deployment scripts

---

## 📚 Documentation

- **QUICK_START.md** - Get started in 5 minutes
- **API Docs** - \`http://localhost:8003/docs\`

---

## 🛠️ Tech Stack

- **LLM:** Claude Sonnet 4.5
- **Framework:** FastAPI
- **Containers:** Docker
- **Cloud:** AWS (S3, ECS)
- **Protocols:** MCP, SSE

---

Built with Claude Sonnet 4.5
