# Security reporting

Report vulnerabilities by opening an issue in this repository's **GitHub Issues** tab. Include the affected release, a concise description, impact and a minimal reproduction using synthetic data. Use a neutral title if details could expose an existing installation.

GitHub issues are public. **Do not include customer names, engagement records, credentials, session tokens, private URLs, databases, backups or uploaded evidence.** Describe sensitive details abstractly and tell maintainers additional restricted information exists; do not attach it to the issue. There is no published security email address or guaranteed private reporting channel. Notify your deployment owner separately when your own installation is affected.

Only the current reviewed release is a maintenance target. Version 0.1.0 remains development software; no security-support SLA is promised. Review the limitations below and validate your deployment before using sensitive data. Passing automated checks is not a security certification.

TRACE assumes a trusted server operator, protected local storage, authorized engagement membership and a trusted HTTPS reverse proxy. Uploaded files are never executed by the application; download recipients must still treat them as untrusted. Native image/document parsers need ongoing patching. Application authorization does not protect against an operator controlling the database, files, code or host. Same-database audit hashes detect some corruption but are neither independently immutable nor cryptographic non-repudiation.

Runtime works offline. Optional dependency-advisory checks require internet access and submit public package names/versions only. Follow [installation](docs/installation.md) and [operations/recovery](docs/operations.md); never publish private storage or the application directly to the internet by default.

## Security limitations

- Authentication has no MFA or emailed self-service recovery. Restrict network access and maintain operator procedures for password resets and offboarding.
- Uploads have no malware scanner. Native image, PDF and font parsers require ongoing patching; report-worker resource limits do not provide an OS security sandbox. Workers can access files available to their OS account, and macOS cannot reliably apply the Linux address-space limit.
- Application encryption of stored data and backups is not provided. Use protected encrypted disks/backups and independently retained audit checkpoints when required. File deletion does not guarantee forensic erasure.
- Evidence quotas do not bound reports, backups, unrelated writers or proxy buffering. Use host quotas, monitoring, retention and recovery procedures; see [storage controls](docs/storage-controls.md).
- SQLite permits one writer at a time; PostgreSQL also serializes application writes to preserve mutation ordering. Validate contention, maintenance exclusivity and recovery against the intended workload.
- Automated narrative redaction cannot recognize every secret. Review free text and exports before sharing them.
- Keep Python, bundled browser assets, native libraries and container packages patched. Scan final release dependencies and images, and pin reviewed image digests for controlled distribution.

Independent review should cover authorization, browser behavior, proxy configuration, upload/parser isolation, resource exhaustion, backup recovery and the deployed host/network. Automated checks do not replace that review.
