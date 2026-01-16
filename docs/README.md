# NetSentinel Documentation

Welcome to the NetSentinel documentation. This folder contains comprehensive guides for understanding, deploying, and testing the NetSentinel network anomaly detection platform.

## Documentation Index

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | System architecture, components, and data flow |
| [FOLDER_STRUCTURE.md](./FOLDER_STRUCTURE.md) | Project directory structure and file organization |
| [API.md](./API.md) | REST API reference and endpoint documentation |
| [TESTING_GUIDE.md](./TESTING_GUIDE.md) | Comprehensive guide for testing anomaly detection |

## Quick Links

### Getting Started
1. Review the [Architecture](./ARCHITECTURE.md) to understand system components
2. Check the [Folder Structure](./FOLDER_STRUCTURE.md) for code organization
3. Use the [API Reference](./API.md) for integration development

### Testing & Validation
- Follow the [Testing Guide](./TESTING_GUIDE.md) to validate detection capabilities
- Includes 10 safe anomaly test cases with exact commands
- Evaluation checklist for assessing detection quality

## Document Descriptions

### ARCHITECTURE.md
Covers the overall system design including:
- Component diagram and data flow
- Technology stack (Go collector, Python backend, React frontend)
- Database schema (TimescaleDB)
- ML pipeline architecture

### FOLDER_STRUCTURE.md
Explains the project organization:
- Directory layout and purpose of each folder
- Key files in each component
- Configuration file locations

### API.md
REST API documentation:
- Authentication endpoints
- Flow ingestion endpoints
- Alert management
- Dashboard statistics
- Asset and rule management

### TESTING_GUIDE.md
Comprehensive testing manual:
- Network topology setup
- Router configuration (pfSense, OpenWRT, MikroTik, Ubiquiti)
- Baseline learning phase guidelines
- 10 safe anomaly test cases with commands
- Alert verification procedures
- Evaluation checklist
- Troubleshooting guide

## Contributing to Documentation

When adding new documentation:
1. Use Markdown format (.md extension)
2. Include a table of contents for longer documents
3. Add the document to this index
4. Use consistent formatting and code blocks for commands
