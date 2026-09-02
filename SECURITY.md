# Security Policy

## Supported versions

The `main` branch receives security fixes. Released tags receive critical fixes
for at least one year after release.

## Reporting a vulnerability

To report a security vulnerability, **do not open a public issue**. Instead,
open a private security advisory on GitHub:

1. Go to the [ Advisories tab](https://github.com/mahdisf/english_learning_software/security/advisories)
2. Click "New advisory"
3. Fill in the details and select "Publish privately"

Alternatively, you may email the maintainer at the address in the git commit
log. You should receive a response within 48 hours.

## Scope

This application stores data locally in SQLite and makes **no network calls**.
The main security considerations are:

- SQL injection via the import path (mitigated by SQLAlchemy parameterized queries)
- Path traversal in file handling (mitigated by `pathlib` boundary checks)
- Data leakage in exported Anki packages or reports (intended — these are your data)
