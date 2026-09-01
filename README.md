# Fohboh-backend
Hotel Management system
https://staging.fohboh.ai/


# Fohboh Backend

A Python/FastAPI backend for hospitality and restaurant management, AI-assisted business analytics, document processing, data integration, and conversational access to operational data.

The project combines traditional backend functionality with modern AI capabilities including natural-language analytics, LLM integration, business-data interpretation, document processing, and external API integrations.

A major component of the repository is an AI assistant built around Adora POS data, allowing restaurant operators and managers to interact with business information using natural-language questions.

Project / staging environment:

https://staging.fohboh.ai/

## Overview

Fohboh Backend is designed as the server-side layer for a broader hospitality-management platform.

The codebase combines:

- FastAPI REST services
- restaurant / hospitality data management
- point-of-sale integration
- AI-powered analytics
- natural-language querying
- LLM integration
- historical business analysis
- document processing
- user authentication
- role-based access concepts
- external API integrations
- PostgreSQL database access
- Redis
- WebSockets
- cloud services
- payment services
- telephony integrations

One of the more developed AI components is the **Adora POS AI Assistant**, which retrieves restaurant operational data and converts it into structured context that can be analyzed through natural-language queries.

## AI-Powered Adora POS Assistant

The Adora POS integration allows business users to query restaurant data conversationally.

Instead of manually navigating multiple dashboards, a manager can ask questions such as:

```text
What are my top-selling items this week?

How did this week's revenue compare with last week?

What is my average order value?

Which menu items are performing poorly?

What are the busiest hours?

Which products have the strongest margins?

What business areas should I focus on today?
```

The system gathers relevant operational information and constructs context for the AI model before generating a response.

## Main Capabilities

### 1. Adora POS Data Integration

The repository contains dedicated modules for interacting with Adora POS.

The integration supports retrieval and processing of information such as:

- menu data
- orders
- sales
- customers
- employees
- operational information
- historical order data
- historical customer data

Dedicated components separate data fetching, database handling, AI analysis, and integration logic.

Important modules include:

```text
adora_pos_data_fetcher.py
adora_pos_database.py
adora_pos_integration.py
adora_pos_ai_chatbot.py
adora_prompt_executor.py
```

This modular design separates the underlying business data from the conversational AI layer.

### 2. Historical Business Analysis

The AI assistant works with both current and historical data.

The repository contains logic for maintaining a historical view of operations rather than answering questions using only the latest API response.

The system can calculate or prepare information such as:

- total orders
- total revenue
- average order value
- daily revenue
- daily order volume
- menu-item sales
- item profitability
- estimated costs
- profit margins
- peak ordering hours
- historical order patterns
- customer trends

This allows the AI assistant to answer analytical questions instead of functioning only as a database lookup interface.

### 3. Natural-Language Business Queries

The application converts operational data into structured context that can be given to an LLM.

Examples of supported question categories include:

#### Sales and Revenue

```text
What were my total sales this week?
```

```text
Compare this week with last week.
```

```text
What is my average order value?
```

#### Menu Analysis

```text
Which items sell the most?
```

```text
Which items have the highest margin?
```

```text
Which products are underperforming?
```

#### Operational Analysis

```text
What are the restaurant's busiest hours?
```

```text
What trends can you identify in recent orders?
```

#### Management Support

```text
Give me an overview of recent business performance.
```

```text
What areas should management investigate?
```

The goal is to make operational business data easier to access for users who may not want to manually construct database queries or analytical reports.

### 4. Conversational Context

The AI assistant supports conversation-oriented interactions.

Conversation information can include:

- conversation IDs
- user information
- chat history
- previous interaction context
- store information

This allows the application to support multi-turn interactions rather than treating every question as an unrelated request.

### 5. Data Refresh and Synchronization

The Adora POS component contains logic for retrieving current information and refreshing cached or stored data.

The chatbot tracks data freshness and can refresh operational data when required.

The repository contains endpoints and functions for:

- initializing an AI session
- refreshing business data
- synchronizing POS information
- retrieving quick insights
- checking service health
- testing AI queries

This separates data retrieval from the natural-language interaction layer.

## Example AI Data Flow

```text
Adora POS
    |
    v
AdoraPOSDataFetcher
    |
    v
Current + Historical Data
    |
    +------------------+
    |                  |
    v                  v
Database           Local Data
    |                  |
    +--------+---------+
             |
             v
  Structured Business Context
             |
             v
       AI / LLM Analysis
             |
             v
     Natural-Language Answer
             |
             v
        FastAPI Client
```

The language model therefore receives business context generated from actual operational data rather than being asked to answer without supporting information.

## Business Metrics

The current implementation contains logic for calculating and organizing metrics such as:

### Order Metrics

- total number of orders
- daily order count
- average ticket / order value

### Revenue Metrics

- total revenue
- daily revenue
- revenue by item

### Menu Metrics

- item quantities sold
- item revenue
- item cost
- estimated item profit
- profit margin

### Temporal Metrics

- performance by date
- hourly order patterns
- peak-time behaviour

These structured metrics can then be included in the context supplied to the AI assistant.

## AI Fallback Analysis

The Adora POS AI integration contains fallback behaviour for situations where the external language-model service is unavailable.

This separates core analytics from complete dependence on an external AI provider.

The broader idea is that business-data processing should remain usable even when model access fails or is temporarily unavailable.

## API Layer

FastAPI is used as the primary application framework.

The Adora POS AI component exposes operations for functionality such as:

```text
POST /adora-pos/ai-chat
POST /adora-pos/start-chat-session
POST /adora-pos/sync-data
GET  /adora-pos/insights
GET  /adora-pos/health
POST /adora-pos/test-queries
```

These endpoints support conversational querying, synchronization, testing, monitoring, and analytics.

## Authentication and Access

The backend includes authentication and authorization components.

The wider dependency and code structure includes functionality related to:

- JWT
- password hashing
- role-based application access
- database-backed users
- protected API resources

The Adora POS AI functionality is designed primarily for operational users such as restaurant managers and administrators rather than unrestricted public access.

## Document and File Processing

The repository includes extensive file-processing functionality.

Supported libraries and modules indicate handling of formats including:

- PDF
- Microsoft Word
- Excel
- CSV
- general uploaded files

The application uses libraries including:

- PyPDF2
- pdfminer
- pdfplumber
- python-docx
- openpyxl
- pandas

This enables uploaded business documents to be extracted and processed for application or AI workflows.

## LLM and AI Integrations

The repository contains integration with multiple AI-related services and libraries.

These include:

- OpenAI
- Anthropic
- Voyage AI
- document-processing workflows
- conversational AI
- analytics
- embedding / retrieval components

This allows the backend to support different AI workflows rather than depending on only one provider.

## External Services and Integrations

The project contains dependencies and components associated with several external services.

These include:

- Adora POS
- OpenAI
- Anthropic
- AWS
- Stripe
- Twilio
- Redis
- PostgreSQL

The backend therefore acts as an integration layer between business services, databases, and AI functionality.

## Technology Stack

### Backend

- Python
- FastAPI
- Uvicorn
- Pydantic
- WebSockets
- HTTPX
- Requests

### Artificial Intelligence

- OpenAI
- Anthropic
- Voyage AI
- LLM-based conversational analytics

### Data Analysis

- pandas
- SciPy
- structured business metrics

### Database and Storage

- PostgreSQL
- psycopg2
- Redis
- AWS S3 / boto3 components

### Document Processing

- PyPDF2
- pdfminer.six
- pdfplumber
- python-docx
- openpyxl

### Authentication

- PyJWT
- bcrypt
- passlib

### External Integrations

- Adora POS
- Stripe
- Twilio

### Deployment

- Docker
- Docker Compose
- environment-variable configuration

## Repository Structure

A simplified representation of the repository:

```text
Fohboh-backend/
|
|-- routes.py
|-- requirements.txt
|-- Dockerfile
|-- docker-compose.yml
|
|-- src/
|   |
|   |-- adora_pos_ai_chatbot.py
|   |-- adora_pos_data_fetcher.py
|   |-- adora_pos_database.py
|   |-- adora_pos_integration.py
|   |-- adora_prompt_executor.py
|   |-- adora_db_helper.py
|   |
|   |-- chat_gpt.py
|   |-- File_upload.py
|   |-- csv_validation.py
|   |-- dashboard.py
|   |-- Audio_works.py
|   |-- config.py
|   |
|   `-- additional backend modules
|
|-- ADORA_POS_API_GUIDE.md
|-- README_ADORA_CHATBOT.md
`-- example_adora_chatbot_usage.py
```

## Adora POS AI Components

### `AdoraPOSDataFetcher`

Responsible for communication with the Adora POS data source.

Its role includes retrieving operational information needed by the rest of the application.

### `AdoraPOSAIChatbot`

Coordinates the conversational AI workflow.

Responsibilities include:

- loading historical information
- refreshing current data
- preparing structured context
- handling user questions
- maintaining conversation-related information
- invoking the AI model
- returning analytical responses

### `AdoraPOSAIIntegration`

Connects the AI assistant with the wider backend and database logic.

### `AdoraPOSDatabase`

Handles persistence related to the Adora POS functionality.

### `AdoraPromptExecutor`

Supports prompt-oriented processing for restaurant analytics and AI interactions.

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/Nehalpk/Fohboh-backend.git
cd Fohboh-backend
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Windows:

```bash
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

## Environment Configuration

Application credentials and configuration should be supplied using environment variables.

Example structure:

```env
OPENAI_API_KEY=your_openai_key

DATABASE_URL=your_postgresql_database

AWS_ACCESS_KEY_ID=your_aws_key
AWS_SECRET_ACCESS_KEY=your_aws_secret

REDIS_URL=your_redis_url

STRIPE_SECRET_KEY=your_stripe_key

TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_token

ADORA_POS_API_URL=your_adora_api_url
ADORA_POS_CLIENT_ID=your_client_id
ADORA_POS_CLIENT_SECRET=your_client_secret
```

The exact variables depend on which application modules are being used.

**Do not commit real credentials, API keys, access tokens, or `.env` files to GitHub.**

## Running with Docker

A Dockerfile and Docker Compose configuration are included in the repository.

Typical usage:

```bash
docker compose up --build
```

## Running Locally

The exact FastAPI entry point should be selected according to the deployment configuration used by the project.

A typical FastAPI development command is:

```bash
uvicorn routes:app --reload
```

If the active deployment uses another application module, update the module path accordingly.

## Example Use Cases

The backend can support workflows such as:

### Hospitality Management

- operational data management
- management dashboards
- restaurant data integration
- document processing

### AI Business Assistant

- conversational sales analysis
- menu-performance questions
- revenue analysis
- operational trends
- management summaries

### Data Processing

- CSV processing
- spreadsheet processing
- PDF extraction
- Word-document processing

### AI and Analytics

- LLM-generated business analysis
- structured context generation
- historical trend analysis
- AI-assisted management insights

## Design Philosophy

The project combines standard backend engineering with AI functionality.

Instead of keeping AI as a separate demonstration, the repository integrates it with:

- authentication
- databases
- external APIs
- business data
- document-processing systems
- operational workflows

This makes the project an example of integrating AI capabilities into a broader production-style application architecture.

## Security

Before deploying the system publicly:

- keep all credentials in environment variables
- never commit API keys
- use a secret manager for production systems
- rotate any previously exposed credentials
- use strong database credentials
- restrict database network access
- validate uploaded files
- restrict allowed file types and file sizes
- validate all API inputs
- enforce authentication and authorization
- restrict CORS rules
- secure WebSocket endpoints
- apply rate limiting where appropriate
- maintain logs without exposing sensitive customer data

## Documentation

Additional repository documentation includes:

```text
README_ADORA_CHATBOT.md
ADORA_POS_API_GUIDE.md
example_adora_chatbot_usage.py
```

These files provide more information about the Adora POS AI integration and example interactions.

## Project Status

This repository contains development, integration, and experimental components from a larger hospitality-management and AI platform.

It is shared as a software and AI engineering portfolio demonstrating backend development, API integration, LLM-based analytics, data processing, and operational AI workflows.

## Author

**Syed Nehal Hassan Shah**

GitHub: https://github.com/Nehalpk
