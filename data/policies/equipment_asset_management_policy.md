# Equipment and Asset Management Policy

**Document ID:** POL-EQP-007  
**Effective Date:** January 1, 2025  
**Last Reviewed:** September 1, 2025  
**Owner:** IT Operations  
**Version:** 3.0

---

## 1. Purpose and Scope

This policy governs the procurement, assignment, use, care, and return of hardware assets and technology equipment owned or leased by Acme Corp. It applies to all employees, contractors, and interns who are issued or use company equipment.

This policy works in conjunction with the Data Security Policy (POL-SEC-004) and the Remote Work Policy (POL-RW-001). For home office ergonomic equipment funded by the remote work stipend, see POL-RW-001, Section 5.2.

---

## 2. Equipment Provisioning

### 2.1 Standard Equipment Package

Upon hire, eligible employees are assigned the following standard equipment based on their role:

| Role Category              | Standard Package                                              |
|----------------------------|---------------------------------------------------------------|
| All office-based employees | Laptop, external monitor (27"), keyboard, mouse, headset      |
| All remote employees       | Laptop, external monitor (27"), keyboard, mouse, headset, webcam |
| Engineering / Data roles   | Laptop (high-performance), dual monitors, docking station     |
| Design / Creative roles    | MacBook Pro (M-series), calibrated display, drawing tablet    |
| Executive roles            | As above, plus mobile phone (see Section 2.4)                 |

Equipment is selected and approved by IT and is subject to hardware availability and budget constraints.

### 2.2 Provisioning Timeline

- **Office-based new hires:** Equipment is ready at the assigned workstation on Day 1.
- **Remote new hires:** Equipment is shipped to the employee's registered home address. IT targets delivery **3 business days before start date**. Employees must confirm their shipping address via the IT onboarding form at least 7 days before start.
- **Internal transfers:** New equipment needs must be requested via the IT Service Portal at least 10 business days before the transfer effective date.

### 2.3 Non-Standard Equipment Requests

Requests for equipment not included in the standard package (e.g., a second external monitor, ergonomic keyboard, or upgraded GPU) must be submitted via the IT Service Portal. Approval requires:
- Manager sign-off confirming business necessity
- IT review for compatibility and security compliance
- Finance approval for items exceeding $500

All approved non-standard equipment remains the property of Acme Corp.

### 2.4 Company Mobile Phones

Company-issued mobile phones are provided to roles with significant travel, on-call responsibilities, or where business communication requires a dedicated device (e.g., VP level and above, on-call engineering roles). Employees not in these categories are not eligible for a company phone; they may use their personal device enrolled in MDM for corporate email and messaging.

---

## 3. Asset Registration and Tracking

### 3.1 Asset Tagging

All hardware assets are tagged with a unique asset ID before issuance. Tags must not be removed or defaced. IT maintains an asset register in the Asset Management System (AMS).

### 3.2 Employee Acknowledgment

Before receiving equipment, employees must sign an **Equipment Acknowledgment Form** confirming they:
- Have received the listed assets in working condition
- Understand they are responsible for the equipment while it is assigned to them
- Agree to return the equipment upon separation or on demand

Signed forms are retained in the employee's personnel file.

### 3.3 Annual Asset Audit

IT conducts an annual asset audit each February. Employees will be asked to confirm possession of assigned equipment and to report any discrepancies. Failure to respond within 5 business days of the audit request will be escalated to the employee's manager.

---

## 4. Acceptable Use of Company Equipment

### 4.1 Permitted Use

Company equipment is provided for business use. Incidental personal use (e.g., personal browsing during off-hours) is permitted provided it:
- Does not violate the Data Security Policy (POL-SEC-004)
- Does not install unauthorized software
- Does not compromise device security

### 4.2 Prohibited Use

The following are strictly prohibited on company equipment:
- Installing software not approved in the company software catalog (IT Portal)
- Disabling or circumventing MDM, antivirus, or other security controls
- Storing personal media libraries (large video, music, or photo collections) that consume storage
- Using the device for commercial activities unrelated to Acme Corp business
- Mining cryptocurrency or running resource-intensive personal projects
- Sharing the device with non-employees (household members, friends) for extended use

### 4.3 Software Installation

Employees may install software from the approved catalog in the IT Portal without requesting approval. All other software must be requested via a Software Request form and is subject to IT security review before installation. Unapproved software installs may trigger an automatic security alert and will be removed.

---

## 5. Care and Maintenance

### 5.1 Employee Responsibilities

Employees are responsible for:
- Using equipment in a reasonable and careful manner
- Keeping liquids away from devices and using protective cases for laptops when traveling
- Not modifying, disassembling, or attempting to repair company hardware
- Keeping device OS and security software up to date per IT's automated patch schedule

### 5.2 IT-Managed Updates

IT pushes OS and security updates via MDM. Employees must not indefinitely defer or block updates. If an update causes a work-blocking issue, contact the IT Help Desk immediately rather than reverting or disabling update management.

### 5.3 Repairs

All hardware repairs must be performed by IT or an IT-approved third-party repair provider. Employees must not take company equipment to consumer repair shops (Apple Store, Best Buy Geek Squad) without IT authorization. Unauthorized repairs void the warranty and may create security vulnerabilities.

---

## 6. Lost, Stolen, or Damaged Equipment

### 6.1 Reporting Requirement

Lost or stolen equipment must be reported to **IT Security within 1 hour** of discovery (see POL-SEC-004, Section 5.5). IT will initiate a remote wipe.

Damaged equipment must be reported to the IT Help Desk within **1 business day**.

### 6.2 Accidental Damage

Acme Corp covers the cost of repair or replacement for equipment damaged due to ordinary accidents (e.g., a dropped laptop) **once per 12-month period** without cost to the employee. Repeated incidents may be investigated.

### 6.3 Negligence or Intentional Damage

Equipment damage resulting from negligence (e.g., liquid spilled due to obvious carelessness) or intentional misuse may result in the employee being charged for repair or replacement costs at fair market value. This determination is made by IT and the employee's manager jointly, with People Operations involvement.

### 6.4 Theft

For stolen equipment, employees must file a police report within 24 hours of discovery and provide the report number to IT. Acme Corp will cover replacement costs if a police report is filed; failure to file may result in the employee bearing replacement costs.

---

## 7. Bring Your Own Device (BYOD)

### 7.1 BYOD Eligibility

Employees who choose not to use company-issued equipment, or whose role requires access to corporate resources from a personal device, may enroll personal devices in the BYOD program.

### 7.2 MDM Enrollment Requirement

All personal devices used to access corporate email, Slack, or any internal system must be enrolled in the company MDM (Jamf for macOS/iOS; Intune for Windows/Android). MDM enrollment grants IT the ability to:
- Enforce screen lock and password policies
- Remotely wipe **corporate data only** (not personal data) in the event of a security incident
- View device compliance status (OS version, encryption status)

IT does not have access to personal files, applications, or browsing history on enrolled personal devices.

### 7.3 Personal Device Support

IT provides best-effort support for company applications on enrolled personal devices. IT does not provide support for personal applications, general device troubleshooting, or hardware issues on personal devices.

### 7.4 BYOD Separation

Upon separation, IT will remove the MDM profile from the employee's personal device, which removes corporate applications and data. The employee's personal data remains unaffected.

---

## 8. Equipment Return Upon Separation

### 8.1 Return Timeline

All Acme Corp-owned equipment must be returned within **5 business days** of the employee's last day of employment. Remote employees will receive a prepaid return shipping box from IT within 2 business days of separation notification.

### 8.2 Equipment Condition

Equipment must be returned in working condition with all original accessories (power adapters, cables, docking stations). Missing accessories will be deducted from the final paycheck at replacement cost, subject to applicable state law.

### 8.3 Data Wipe

Before returning equipment, employees must not attempt to wipe or reset devices themselves. IT will perform a certified data wipe after return to ensure compliance with data retention policies.

### 8.4 Failure to Return

If equipment is not returned within the required timeframe, Acme Corp reserves the right to pursue recovery of equipment value through:
- Deduction from final paycheck (where permitted by applicable state law)
- Civil legal action for recovery

---

## 9. Contractor and Vendor Equipment

Contractors and vendors using company equipment are subject to this policy for the duration of their engagement. Company equipment must be returned on the final day of the engagement. Contractors using personal devices must enroll in BYOD per Section 7.

---

## 10. Contact and Questions

- **IT Help Desk (equipment requests, repairs):** it-help@acmecorp.com or IT Service Portal
- **IT Security (lost/stolen devices):** it-security@acmecorp.com or +1-800-555-SECU
- **Asset Management questions:** it-assets@acmecorp.com
- **People Operations (separation equipment return):** people-ops@acmecorp.com
