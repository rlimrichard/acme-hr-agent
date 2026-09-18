# Vendor and Third-Party Management Policy

**Document ID:** POL-VND-019  
**Effective Date:** January 1, 2025  
**Last Reviewed:** September 1, 2025  
**Owner:** Finance / Legal / IT Security  
**Version:** 2.0

---

## 1. Purpose and Scope

This policy governs how Acme Corp engages, manages, and offboards third-party vendors, suppliers, service providers, and contractors who provide services to or on behalf of Acme Corp.

It applies to all employees who initiate, manage, or conclude vendor relationships, including procurement, IT, Finance, Legal, and business teams.

> **Scope boundaries:**
> - **Conflict of interest** rules for employees who have financial relationships with vendors are in POL-WPC-009 §5; this policy governs the vendor engagement process itself
> - **Contractor equipment provisioning** (company-issued or BYOD) follows POL-EQP-007 §9
> - **Contractor access revocation** timelines follow POL-SEC-004 §3.2
> - **Individual employee expense reimbursement** for vendor meals/gifts is governed by POL-EXP-001 §4 and POL-WPC-009 §7

---

## 2. Vendor Approval and Onboarding

### 2.1 Pre-Engagement Approval

No vendor engagement may begin — including issuing a Statement of Work, accepting services, or sharing company data — until the vendor has been approved through the vendor onboarding process. Emergency exceptions require the CFO and Legal sign-off.

New vendor requests are submitted via the **Procurement Portal** in Coupa and require:
- Business justification and proposed scope
- Estimated annual contract value
- Identification of any data the vendor will access or process

### 2.2 Approval Thresholds

Vendor approvals are tiered by estimated annual contract value (ACV):

| ACV | Approval Required |
|---|---|
| Under $10,000 | Manager + Finance |
| $10,000 – $50,000 | Director + Finance + Legal review |
| $50,000 – $250,000 | VP + Finance + Legal + IT Security (if data access) |
| Above $250,000 | CFO + Legal + IT Security + CISO |

### 2.3 Vendor Due Diligence

Before approval, vendors undergo due diligence appropriate to their risk profile:

| Vendor Category | Due Diligence Required |
|---|---|
| **High-risk** (access to Confidential/Restricted data, critical infrastructure) | Security assessment (questionnaire + evidence review), SOC 2 Type II report, financial stability check, references |
| **Medium-risk** (access to Internal data, non-critical services) | Security questionnaire, vendor references |
| **Low-risk** (no data access, non-critical, under $10K) | Standard procurement form only |

Risk categorization is performed by IT Security and Legal jointly.

### 2.4 Required Agreements

All vendors must execute applicable agreements before engagement begins:

| Agreement | Required For |
|---|---|
| **Non-Disclosure Agreement (NDA)** | All vendors; may be incorporated into the MSA |
| **Master Services Agreement (MSA)** | All recurring or multi-engagement vendors |
| **Statement of Work (SOW)** | Each discrete project or engagement phase |
| **Data Processing Agreement (DPA)** | Any vendor processing personal data on behalf of Acme Corp |
| **Business Associate Agreement (BAA)** | Vendors handling health information (HIPAA) |

Standard Acme Corp templates for each agreement are maintained by Legal. Vendors who insist on using their own paper must have their agreements reviewed by Legal before execution. Employees may not sign vendor agreements independently.

---

## 3. Recruiting and Staffing Agencies

### 3.1 Approved Agency List

All recruiting and staffing agencies must be on the Talent Acquisition-approved vendor list before being engaged. Using an unapproved agency is a policy violation and may expose Acme Corp to unsolicited placement fees.

### 3.2 Agency Fee Agreements

Placement fee terms must be agreed in writing before any candidate is presented. Standard terms for contingency search are negotiated by Talent Acquisition; retained search engagements require Finance approval.

### 3.3 Candidate Data

Candidate data provided by agencies is subject to the same candidate privacy protections as in POL-REC-016 §4.2 and must be stored only in Greenhouse.

---

## 4. Contractor Onboarding

### 4.1 Distinction: Vendor vs. Contractor

This policy uses "contractor" to refer to individuals engaged through a staffing agency or directly as independent contractors who work on Acme Corp premises (physical or virtual) and need access to Acme Corp systems. They are a subset of the vendor category.

### 4.2 Contractor System Access

Contractors receive system access scoped strictly to the needs of their engagement:
- Access is requested by the sponsoring manager through the IT Service Portal
- Access is time-bounded to the engagement period and automatically expires
- Contractors may not receive access to HR, financial, or executive systems unless explicitly required and approved by the relevant system owner

### 4.3 Contractor Security Obligations

All contractors with system access must:
- Complete the Security Awareness Training module (abbreviated version) before access is granted
- Sign the Contractor Information Security Acknowledgment as part of onboarding
- Comply with all applicable Acme Corp security policies (POL-SEC-004) for the duration of their engagement

### 4.4 Contractor Identification

Contractors must not represent themselves as Acme Corp employees in external communications. In email signatures and meeting invitations, contractors should clearly identify their firm and role (e.g., "Jane Smith, Contractor via Apex Staffing, Software Engineer").

---

## 5. Ongoing Vendor Management

### 5.1 Vendor Owner

Each vendor relationship must have a designated **Vendor Owner** — the Acme Corp employee responsible for managing the relationship, performance, and compliance obligations. The Vendor Owner is typically the business stakeholder who initiated the engagement.

### 5.2 Vendor Performance Reviews

For strategic vendors (ACV above $100K or operationally critical), the Vendor Owner must conduct a formal **annual performance review** including:
- Delivery against SLAs and commitments
- Incident history (security, service outages, compliance issues)
- Relationship health and communication quality
- Decision to renew, renegotiate, or terminate

Performance review outcomes are documented in the Procurement Portal.

### 5.3 Contract Renewals

Vendor contracts with auto-renewal clauses must be flagged by Finance in the Procurement Portal. The Vendor Owner must review renewal decisions at least **60 days before** the auto-renewal date. Contracts that renew without review because the Vendor Owner did not act are still binding; prevention is the responsibility of the Vendor Owner.

### 5.4 Security Reassessment

Vendors with access to Confidential or Restricted data are subject to annual security reassessment. IT Security will request updated security documentation (SOC 2, penetration test results, security questionnaire) each year. Vendors who fail to provide documentation within 30 days of request are escalated to the CISO for decision on continued engagement.

---

## 6. Vendor Incident Management

### 6.1 Vendor Security Incidents

If a vendor experiences a security incident that may have affected Acme Corp data, the Vendor Owner must notify IT Security within **1 hour** of becoming aware. IT Security leads the response from Acme Corp's side.

Vendors are contractually required (via DPA or MSA security exhibit) to notify Acme Corp of any security incident affecting Acme Corp data within **24 hours** of discovery.

### 6.2 Vendor Disputes

Contract disputes are escalated to Legal. The Vendor Owner should document the dispute in writing before escalating. Acme Corp employees may not make verbal commitments to vendors to resolve disputes, modify contract terms, or accept liability without Legal involvement.

---

## 7. Vendor Offboarding

### 7.1 Planned Engagement End

When a vendor engagement ends (contract expiration, project completion, or termination), the Vendor Owner must initiate offboarding through the Procurement Portal at least **10 business days** before the end date.

### 7.2 Offboarding Checklist

Vendor offboarding involves:
- [ ] IT Security revokes all system access and deactivates accounts (per POL-SEC-004 §3.2, within 4 hours of engagement end)
- [ ] Vendor Owner confirms return or certified destruction of any Confidential or Restricted data held by the vendor (documented in writing)
- [ ] Finance confirms all invoices are settled and no open purchase orders remain
- [ ] Legal confirms any post-engagement obligations (NDA survival, IP assignment, non-solicitation) have been communicated to the vendor
- [ ] Procurement Portal updated to reflect engagement closure

### 7.3 Immediate Termination

If a vendor engagement must be terminated immediately for cause (security breach, breach of contract, misconduct), the Vendor Owner notifies IT Security and Legal simultaneously. IT Security revokes access immediately; Legal manages the formal termination notice.

---

## 8. Anti-Corruption and Vendor Gifts

### 8.1 Vendor Gifts to Acme Corp Employees

Vendor gifts to Acme Corp employees are subject to the limits and disclosure requirements in POL-WPC-009 §7. Vendors attempting to circumvent these limits — including providing gifts to family members of employees — must be reported to Legal and Procurement.

### 8.2 Acme Corp Gifts to Vendors

Business gifts to vendors on behalf of Acme Corp must be approved by the Vendor Owner's manager and comply with POL-EXP-001 §4. Cash or cash-equivalent gifts to vendors are prohibited.

---

## 9. Contact and Questions

- **Procurement / Vendor Onboarding:** procurement@acmecorp.com or Coupa Portal
- **Legal (contracts, NDAs, DPAs):** legal@acmecorp.com
- **IT Security (security assessments, access):** it-security@acmecorp.com
- **Finance (contract renewals, purchase orders):** finance@acmecorp.com
