# Synthetic sample data

The supported sample generator is `python manage.py seed_demo --admin ADMIN_USERNAME --settings=config.settings.development`; see [demo data](../docs/demo-data.md). First migrate an isolated development storage root and initialize your own administrator with `createsuperuser`. No default passwords are supplied; role-only demo users have unusable passwords.

All sample engagements, findings, test cases, evidence and organizations are fictional. Domains use `.test`, IPs use documentation ranges and records carry explicit synthetic handling markings. The generator makes no network calls and refuses production settings. Existing tests verify safe initialization and repeat runs.

Do not commit generated databases, evidence, backups or account exports. Use a disposable private storage root for training and review; never seed a customer instance or substitute actual penetration-test output into shareable samples.
