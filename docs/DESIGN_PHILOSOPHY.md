
# Design Philosophy

Loobric Core is built using AI tools and principles.  This document should be reviewed and incorporated by all AI agents working on Loobric.

## General AI Prompt

AI agents working on Loobric should incorporate the following prompts into their responses:

1. Review and incorporate the Loobric Design Philosophy document into all responses. Ask the user questions if the design philosophy is unclear. 
2. Favor a functional style of programming over an object-oriented style.
3. Docstrings will be included for every function, class, and module. Docstrings should accurately document the assumptions of the code. If those assumptions change, the docstring MUST be updated accordingly. Do NOT change the docstrings without confirming with the user that the change is intentional.
4. Unit testing is required for all code. Minimize the need for mocks and stubs. If mocks or stubs are required, document the assumptions in the docstring.
5. Unit testing should focus on testing the assumptions of the code. If those assumptions change, the unit tests MUST be updated accordingly. Do NOT change the unit tests without confirming with the user that the change is intentional.
6. Changes should be incremental and minimal. Avoid large refactoring changes unless explicitly requested by the user.
7. Favor TDD (Test Driven Development). Write tests first and confirm with the user that they are complete BEFORE implementing the code.
7. Keep README and other docs up to date.
8. All interactions and commit messages should be extremely brief and sacrifice grammer for conciseness.

# Infrastructure Strategy

## Core Design Assumptions

Loobric is built on five foundational infrastructure principles that inform all implementation decisions:

### 1. Backup and Restore First

**Assumption**: Backup and restore capabilities are not optional features to be added later—they are core infrastructure that must exist from day one.

**Rationale**:
- Manufacturing data is critical; tool data errors can lead to scrap or machine damage
- Backup/restore simplifies testing by allowing quick state snapshots and rollbacks
- Enables disaster recovery and data migration between environments
- Supports auditing and compliance requirements
- Builds community trust by avoiding lock-in to any particular database or storage solution

**Implementation Requirements**:
- All data must be serializable to a portable format (JSON, SQL dump)
- Database schema must support full export/import operations
- Backup operations must be atomic and consistent
- Restore operations must validate data integrity before applying
- Testing framework must leverage backup/restore for test fixtures

### 2. Versioning Built-In From the Beginning

**Assumption**: Every entity tracks its version/revision history. Versioning is not metadata—it's fundamental to the data model.

**Rationale**:
- Tool data changes frequently (wear, measurements, offsets)
- Clients need to detect and sync changes efficiently
- Conflicts require version information to resolve
- Audit trails depend on knowing what changed when
- Optimistic locking prevents concurrent update conflicts

**Implementation Requirements**:
- All entities include `created_at`, `updated_at`, `version` fields
- Version increments on every write operation
- Change detection APIs use versions/timestamps for queries
- Database supports version-based queries efficiently (indexed)
- Bulk operations handle version conflicts gracefully

### 3. Test-Driven Development (TDD)

**Assumption**: Tests are written before implementation code. The test suite defines the contract and validates assumptions.

**Rationale**:
- Complex domain (manufacturing, CAM, CNC) requires clear specifications
- Bulk-first API design needs thorough validation of edge cases
- Format translators (Fanuc, Haas, Mastercam) have subtle requirements
- Functional programming style benefits from property-based testing
- Tests serve as executable documentation

**Implementation Requirements**:
- Every function has tests before it has implementation
- Tests document assumptions in docstrings
- Property-based tests validate bulk operations
- Integration tests use backup/restore for state management
- CI/CD runs full test suite on every commit

### 4. Authentication and Authorization Built-In

**Assumption**: Authentication and authorization are infrastructure concerns that must be designed from the start, not bolted on later.

**Rationale**:
- Manufacturing data is valuable intellectual property
- Audit trails require knowing who made changes (user attribution)
- Different roles have different permissions (operators vs programmers vs admins)
- Multi-tenancy may be needed for service providers or large organizations
- API access needs to be controlled and rate-limited

**Implementation Requirements**:
- All write operations must identify the user account (`user_id`, `created_by`, `updated_by` fields)
- API endpoints require authentication by default (unless disabled)
- Authorization checks happen at the function level, not just routes
- Two authentication methods:
  - User account login (email/password) for web UI and management
  - API keys (created by users) for programmatic/machine access
- Configuration: `AUTH_ENABLED=true|false` environment variable
- Data isolation: All queries filtered by user account (multi-tenant by default)

### 5. Structured Logging Built-In

**Assumption**: Comprehensive, structured logging is essential infrastructure for production operations, debugging, and audit compliance.

**Rationale**:
- Manufacturing operations require audit trails for compliance and liability
- Debugging tool synchronization issues requires detailed operation logs
- Human operators need to review what happened (who changed what, when, why it failed)
- Performance monitoring requires structured metrics
- Security incidents require forensic investigation capabilities

**Implementation Requirements**:
- Structured logging from day one (JSON format, not plain text)
- All operations log: user_id, timestamp, operation, entity_type, entity_id, result
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Separate audit log for compliance (immutable, all data changes)
- Query interface for searching/filtering logs
- Log rotation and retention policies

## Development Workflow

### Test-Driven Development Process

1. **Write the test first** - Define expected behavior
2. **Run test (should fail)** - Verify test detects missing functionality
3. **Implement minimal code** - Make test pass with simplest solution
4. **Run test (should pass)** - Verify implementation works
5. **Refactor if needed** - Improve code while keeping tests passing
6. **Update docstrings** - Document assumptions and behavior
7. **Commit** - Small, incremental commits

### Code Style Guidelines

- **Functional style**: Prefer pure functions, avoid mutable state
- **Type hints**: All function signatures include type hints
- **Docstrings**: Google-style docstrings for all functions, classes, modules
- **Line length**: 100 characters maximum
- **Imports**: Organized (stdlib, third-party, local)
- **Error handling**: Explicit, with clear error messages