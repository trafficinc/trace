"""Synthetic aerospace red-team exercises; no real company assets or observations."""

CLIENT = "Asterion Aerospace & Defense (fictional)"
MARKING = "SYNTHETIC TRAINING DATA — NOT CLASSIFIED"
PEOPLE = {
    "kestrel_lead": ("demo.kestrel.lead", "Maya", "Chen"),
    "talon_lead": ("demo.talon.lead", "Jordan", "Ellis"),
    "operator": ("demo.redteam.operator", "Alex", "Rivera"),
    "analyst": ("demo.redteam.analyst", "Sam", "Okafor"),
    "reviewer": ("demo.redteam.reviewer", "Riley", "Patel"),
    "observer": ("demo.redteam.observer", "Casey", "Brooks"),
}

SCENARIOS = (
    {
        "key": "kestrel",
        "name": "[DEMO] Operation KESTREL — Engineering Enclave",
        "lead": "kestrel_lead",
        "completed": False,
        "start_offset": -7,
        "end_offset": 14,
        "description": "An authorized red-team exercise against a fictional aerospace contractor's isolated engineering environment. "
                       "All systems, observations and people in this exercise are synthetic. No Lockheed Martin assets or incidents are represented.",
        "objectives": "Validate separation between corporate IT and the engineering enclave.\n"
                      "Evaluate supplier identity controls, build-artifact permissions and SOC visibility.\n"
                      "Document findings with reproducible lab observations and linked evidence.",
        "scope": "ONLY the named training assets under asterion.example.test and documentation IP ranges.\n"
                 "No external connections, real credentials, payload deployment or production testing.\n"
                 "Flight hardware, weapons systems, classified programs and live factory controls are out of scope.",
        "assets": (
            {"key": "portal", "name": "Supplier collaboration portal", "asset_type": "application", "url": "https://suppliers.asterion.example.test", "ip_cidr": "192.0.2.20", "description": "Training portal containing synthetic supplier work packages. No real engineering drawings.", "environment": "Supplier lab", "scope_status": "in_scope"},
            {"key": "jump", "name": "Engineering privileged-access gateway", "asset_type": "host", "hostname": "jump01.eng.asterion.example.test", "ip_cidr": "192.0.2.30", "description": "Isolated jump host for evaluating privileged session controls.", "environment": "Engineering lab", "scope_status": "in_scope"},
            {"key": "build", "name": "Flight-software build pipeline simulator", "asset_type": "application", "url": "https://build.asterion.example.test", "description": "Build pipeline with dummy source code and unsigned training artifacts only.", "environment": "Engineering lab", "scope_status": "in_scope"},
            {"key": "registry", "name": "Engineering artifact registry", "asset_type": "service", "hostname": "registry.eng.asterion.example.test", "ip_cidr": "192.0.2.40", "description": "Synthetic release bundles used to evaluate read/write separation.", "environment": "Engineering lab", "scope_status": "in_scope"},
            {"key": "boundary", "name": "Engineering enclave boundary", "asset_type": "network", "ip_cidr": "198.51.100.0/24", "description": "Documentation-only address range standing in for an isolated engineering segment.", "environment": "Engineering lab", "scope_status": "in_scope"},
            {"key": "soc", "name": "SOC telemetry collector", "asset_type": "host", "hostname": "soc01.asterion.example.test", "ip_cidr": "203.0.113.10", "description": "Training event collector for purple-team validation.", "environment": "Security lab", "scope_status": "pending"},
            {"key": "hardware", "name": "Flight-hardware integration bench", "asset_type": "other", "description": "Scope exclusion only. No physical hardware or live control systems are represented or tested.", "environment": "Excluded systems", "scope_status": "out_of_scope"},
        ),
        "tests": (
            {"key": "boundary", "title": "Engineering-to-lab boundary enforcement", "category": "Network segmentation", "assets": ("boundary", "jump"), "status": "passed", "assigned": "operator", "objective": "Verify the approved management path is the only path into the engineering lab.", "procedure": "1. Review the synthetic allowlist with the exercise owner.\n2. Compare the provided lab policy export to the approved flow matrix.\n3. Record permitted and denied training flows without contacting any host.", "expected": "Only the approved gateway path is allowed; direct workstation-to-lab paths are denied.", "actual": "Synthetic policy review: approved gateway path ALLOW; direct workstation-to-lab path DENY. No real network traffic was generated."},
            {"key": "supplier", "title": "Supplier workspace authorization boundaries", "category": "Application authorization", "assets": ("portal",), "status": "failed", "assigned": "operator", "objective": "Verify suppliers can access only their own synthetic work packages.", "procedure": "1. Review two fabricated supplier personas.\n2. Compare access decisions in the provided authorization worksheet.\n3. Link the synthetic decision log to the finding.", "expected": "A supplier persona cannot view another supplier's work-package metadata.", "actual": "The synthetic worksheet permits Supplier Alpha to read Supplier Bravo's dummy package summary. No production portal was accessed."},
            {"key": "sessions", "title": "Privileged session approval and recording", "category": "Identity and access", "assets": ("jump",), "status": "in_progress", "assigned": "analyst", "objective": "Check that elevated sessions require approval and produce an attributable recording.", "procedure": "1. Review the lab approval record.\n2. Match a fabricated session ID to the training recording index.\n3. Confirm retention ownership with the lab custodian.", "expected": "Each training session has approval, an owner and a recording reference.", "actual": "Approval and ownership checks are complete; recording-index review is in progress."},
            {"key": "pipeline", "title": "Build artifact promotion authorization", "category": "Software supply chain", "assets": ("build", "registry"), "status": "blocked", "assigned": "operator", "objective": "Validate separation of build and release-approval duties.", "procedure": "1. Review the fictional release role matrix.\n2. Evaluate the provided training approval trace.\n3. Confirm independent approval before promotion.", "expected": "A build role cannot independently approve release promotion.", "actual": "Blocked: the synthetic release-owner approval worksheet has not yet been supplied."},
            {"key": "telemetry", "title": "SOC visibility for simulated boundary events", "category": "Detection and response", "assets": ("soc", "boundary"), "status": "not_started", "assigned": "analyst", "objective": "Determine whether approved training events appear in the SOC review queue.", "procedure": "1. Confirm SOC participation and the training-event window.\n2. Review offline event fixtures with the blue team.\n3. Document alert ownership and timestamps.", "expected": "Each synthetic boundary event has a corresponding attributed SOC record.", "actual": ""},
            {"key": "registry", "title": "Artifact registry read-only role separation", "category": "Software supply chain", "assets": ("registry",), "status": "passed", "assigned": "analyst", "objective": "Verify a read-only training identity cannot publish or delete release bundles.", "procedure": "1. Review the synthetic registry role matrix.\n2. Compare reader and publisher permissions.\n3. Retain the offline access-decision worksheet.", "expected": "Reader roles are limited to metadata and download permissions.", "actual": "The supplied lab matrix grants readers list/download only. Publish and delete permissions are absent."},
            {"key": "physical", "title": "Physical avionics bench access review", "category": "Scope validation", "assets": ("hardware",), "status": "not_applicable", "assigned": "operator", "objective": "Record the explicit exclusion of live hardware from this software-only exercise.", "procedure": "1. Compare the asset to the signed fictional scope.\n2. Record the exclusion. Do not test or contact hardware.", "expected": "Excluded assets receive no testing activity.", "actual": "Not applicable: physical integration benches and operational hardware are outside the approved training scope."},
            {"key": "retest", "title": "Supplier authorization remediation retest", "category": "Remediation validation", "assets": ("portal",), "status": "not_started", "assigned": "operator", "objective": "Retest the synthetic supplier boundary after the training application owner supplies a corrected policy.", "procedure": "1. Wait for the fictional remediation handoff.\n2. Review the replacement offline decision worksheet.\n3. Compare it to the original training observation.", "expected": "All cross-supplier metadata decisions are denied.", "actual": ""},
        ),
        "findings": (
            {"key": "supplier", "title": "Cross-supplier work-package metadata exposure", "severity": "high", "status": "confirmed", "asset": "portal", "test": "supplier", "description": "**Synthetic observation:** a training authorization worksheet allows one supplier persona to read another supplier's dummy work-package summary.", "impact": "In the fictional scenario, supplier separation could fail and expose project metadata. No real contractor data is involved.", "remediation": "Enforce supplier ownership on every work-package lookup and add cross-supplier regression checks."},
            {"key": "recording", "title": "Privileged session recording ownership is incomplete", "severity": "medium", "status": "under_review", "asset": "jump", "test": "sessions", "description": "The supplied training recording index does not consistently identify a retention owner. This observation is awaiting independent review.", "impact": "The fictional security team could have difficulty correlating an elevated session with retained review material.", "remediation": "Require recording ownership and retention references in the privileged-access review workflow."},
            {"key": "telemetry", "title": "SOC training-event ownership requires clarification", "severity": "low", "status": "draft", "asset": "soc", "test": "telemetry", "description": "Draft planning observation: the synthetic exercise handoff has no named owner for the boundary-event review queue. Detection testing has not started.", "impact": "Training events may lack a clear reviewer; this draft does not claim a demonstrated detection failure.", "remediation": "Assign the SOC exercise owner and confirm the review window before running the offline validation."},
        ),
        "milestones": (("Rules of engagement approved", -7, True), ("Scope and access validation", -4, True), ("Engineering enclave assessment", 7, False), ("Purple-team review and retest", 14, False)),
    },
    {
        "key": "talon",
        "name": "[DEMO] Operation TALON — Supplier Access Validation",
        "lead": "talon_lead",
        "completed": True,
        "start_offset": -42,
        "end_offset": -14,
        "description": "Completed fictional supplier-access exercise showing retained results and read-only content. All observations are fabricated training material, unrelated to any real defense contractor.",
        "objectives": "Validate expiration of supplier access and separation of training document repositories.\nRetain the remediation decision and independent review trail.",
        "scope": "Offline identity and document-access fixtures only, using asterion.example.test and documentation IP ranges.\nNo live suppliers, production systems, flight hardware or classified information.",
        "assets": (
            {"key": "identity", "name": "Supplier identity broker", "asset_type": "service", "hostname": "identity.asterion.example.test", "ip_cidr": "192.0.2.80", "description": "Fictional identity broker with synthetic supplier expiration records.", "environment": "Supplier training", "scope_status": "in_scope"},
            {"key": "documents", "name": "Supplier training document vault", "asset_type": "application", "url": "https://vault.asterion.example.test", "description": "Dummy document metadata only. Contains no real design or export-controlled material.", "environment": "Supplier training", "scope_status": "in_scope"},
            {"key": "boundary", "name": "Supplier training network", "asset_type": "network", "ip_cidr": "203.0.113.0/24", "description": "Documentation-only range representing the supplier training boundary.", "environment": "Supplier training", "scope_status": "in_scope"},
        ),
        "tests": (
            {"key": "expiry", "title": "Expired supplier access remediation validation", "category": "Identity and access", "assets": ("identity",), "status": "passed", "assigned": "operator", "objective": "Verify expired supplier personas lose access after the fictional control update.", "procedure": "1. Review the original fabricated expiration exception.\n2. Compare the corrected offline decision worksheet.\n3. Confirm denial for all expired training personas.", "expected": "Expired supplier personas receive a denied access decision.", "actual": "The synthetic retest worksheet denies access for all three expired supplier personas. Independent review accepted the remediation."},
            {"key": "documents", "title": "Supplier document-vault isolation", "category": "Application authorization", "assets": ("documents", "boundary"), "status": "passed", "assigned": "analyst", "objective": "Validate isolation between the training document repository and unrelated supplier workspaces.", "procedure": "1. Review the fabricated access matrix.\n2. Confirm each persona is limited to its own dummy records.\n3. Retain the reviewed worksheet.", "expected": "Supplier personas are isolated to their own training repository.", "actual": "All cross-supplier requests in the synthetic matrix are denied; own-workspace reads are allowed."},
            {"key": "hardware", "title": "Supplier factory-floor interface testing", "category": "Scope validation", "assets": ("boundary",), "status": "not_applicable", "assigned": "operator", "objective": "Document exclusion of supplier factory-floor systems.", "procedure": "1. Review the fictional signed scope.\n2. Record factory-floor exclusion without interacting with any device.", "expected": "No factory-floor testing takes place.", "actual": "Not applicable: the training engagement includes identity and document review only."},
        ),
        "findings": (
            {"key": "expiry", "title": "Expired supplier access was not consistently revoked", "severity": "medium", "status": "remediated", "asset": "identity", "test": "expiry", "description": "The original synthetic review identified an expiration-policy exception. A corrected offline policy worksheet and independent retest now demonstrate revoked access.", "impact": "Within the fictional scenario, expired supplier personas could retain unnecessary access until the policy correction.", "remediation": "Apply access expiration centrally, reconcile supplier lifecycle records and retain periodic access-review results."},
        ),
        "milestones": (("Supplier scope approved", -42, True), ("Access control review complete", -28, True), ("Remediation independently validated", -14, True)),
    },
)
