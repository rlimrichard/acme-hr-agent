# Data Security Policy

**Document ID:** POL-SEC-004  
**Effective Date:** January 1, 2025  
**Last Reviewed:** September 1, 2025  
**Owner:** Information Security  
**Version:** 5.2

---

## 1. Purpose and Scope

This policy establishes the requirements for protecting Acme Corp's information assets from unauthorized access, disclosure, modification, and destruction. It applies to **all employees, contractors, consultants, and third parties** who access Acme Corp systems, networks, or data in any capacity.

Compliance with this policy is mandatory. Violations may result in disciplinary action up to and including termination of employment or contract, and potential civil or criminal liability.

This policy should be read alongside the Remote Work Policy (POL-RW-001), which addresses physical workspace security obligations for remote employees.

---

## 2. Data Classification

### 2.1 Classification Levels

All Acme Corp data must be classified into one of four levels. Data owners are responsible for classifying data under their purview.

| Level          | Definition                                                              | Examples                                           |
|----------------|-------------------------------------------------------------------------|----------------------------------------------------|
| **Public**     | Approved for external distribution; no harm if disclosed               | Marketing materials, press releases, public docs   |
| **Internal**   | For employees only; limited harm if disclosed externally               | Internal announcements, non-sensitive process docs |
| **Confidential** | Sensitive business data; significant harm if disclosed               | Financial reports, roadmaps, employee records, PII |
| **Restricted** | Highest sensitivity; severe harm or legal consequence if disclosed     | PCI data, trade secrets, health records, credentials |

### 2.2 Data Handling by Classification

| Action                  | Public | Internal | Confidential | Restricted |
|-------------------------|--------|----------|--------------|------------|
| Store on personal device | Yes   | No       | No           | Never      |
| Email externally         | Yes   | No       | No           | Never      |
| Share via Slack          | Yes   | Yes      | Approved channels only | Never |
| Print                    | Yes   | Yes      | Secure printer required | Never |
| Cloud storage (approved) | Yes   | Yes      | Encrypted only | Prohibited |

### 2.3 Default Classification

Data that has not been explicitly classified must be treated as **Confidential** until classified by the data owner.

---

## 3. Access Control

### 3.1 Principle of Least Privilege

All system access must follow the principle of least privilege: employees are granted only the minimum permissions necessary to perform their job function. Access must be requested through the IT Service Portal, approved by both the employee's manager and the system owner, and reviewed quarterly.

### 3.2 Access Provisioning and De-provisioning

- **New hires:** Access is provisioned based on role-based access profiles. IT will complete provisioning within **2 business days** of an approved onboarding request.
- **Role changes:** Access must be updated within **5 business days** of a role change. Departing employees' access is revoked **within 4 hours** of HR notifying IT of a separation.
- **Contractors:** Access is time-boxed to the engagement period and automatically expires.

### 3.3 Privileged Access

Administrative and elevated privileges require additional approval from the CISO or designated deputy and are subject to enhanced monitoring and quarterly recertification.

### 3.4 Shared Accounts

Shared accounts and credentials are prohibited except for designated service accounts that cannot technically be assigned to individuals. All service accounts must be registered with IT Security.

---

## 4. Authentication and Passwords

### 4.1 Password Requirements

All passwords for Acme Corp systems must meet the following minimum standards:

- **Minimum length:** 14 characters
- **Complexity:** Must include at least one uppercase letter, one lowercase letter, one number, and one special character
- **History:** Cannot reuse the last 12 passwords
- **Maximum age:** 180 days (6 months) for standard accounts; 90 days for privileged accounts
- **Do not share** passwords with anyone, including IT staff or managers

### 4.2 Multi-Factor Authentication (MFA)

MFA is **mandatory** for:
- All remote access (VPN, cloud applications)
- Email and calendar (Microsoft 365 / Google Workspace)
- All HR and financial systems
- Any system storing Confidential or Restricted data
- GitHub and all code repositories

Approved MFA methods: hardware security keys (preferred), authenticator apps (Okta Verify, Google Authenticator), or SMS (last resort; discouraged due to SIM-swap risk).

### 4.3 Password Manager

Acme Corp provides a company-licensed password manager (1Password Teams) for all employees. Use of an approved password manager is strongly encouraged; storing passwords in browser auto-fill or unencrypted text files is prohibited.

---

## 5. Device Security

### 5.1 Endpoint Protection

All company-managed devices must have the following security controls active at all times:
- Approved antivirus and EDR software (CrowdStrike Falcon)
- Full-disk encryption (FileVault on macOS, BitLocker on Windows)
- Mobile Device Management (MDM) enrollment (Jamf for macOS, Intune for Windows)
- Automatic OS and security patch installation within **14 days** of release

### 5.2 Screen Lock

Devices must be configured to lock after **5 minutes** of inactivity. Employees must lock their screen manually when leaving a device unattended in any location.

### 5.3 Physical Security

- Laptops must never be left unattended in public spaces (coffee shops, airports, hotel lobbies).
- When traveling, devices must be kept in carry-on luggage and never checked.
- Devices must not be left visible in vehicles.

### 5.4 Personal Devices (BYOD)

Personal devices used to access Acme Corp systems must be enrolled in MDM. Accessing corporate email, Slack, or any internal system from an unenrolled personal device is prohibited. See Equipment & Asset Management Policy (POL-EQP-007) for BYOD enrollment procedures.

### 5.5 Lost or Stolen Devices

Report lost or stolen devices to IT Security **within 1 hour** of discovery via it-security@acmecorp.com or the IT emergency line. IT will initiate a remote wipe. Failure to report promptly is a policy violation.

---

## 6. Network Security

### 6.1 VPN Requirement

All remote access to internal Acme Corp systems, including internal applications, file shares, and databases, requires an active VPN connection. The approved VPN client is provided and configured by IT. Use of third-party or personal VPNs to access company resources is prohibited.

### 6.2 Public Wi-Fi

Employees must connect through VPN before using any public Wi-Fi network (airports, hotels, cafes). Sensitive work involving Confidential or Restricted data must not be conducted on public networks even with VPN active unless absolutely necessary.

### 6.3 Home Network Security

Remote employees should ensure their home router:
- Uses WPA2 or WPA3 encryption
- Has firmware updated to the latest available version
- Uses a non-default admin password

IT Security publishes a home network hardening guide on the IT Portal.

---

## 7. Data Handling and Storage

### 7.1 Approved Storage Locations

| Data Classification | Approved Storage                                   |
|---------------------|----------------------------------------------------|
| Public              | Any company-approved platform                      |
| Internal            | Microsoft SharePoint, OneDrive, Google Drive (company) |
| Confidential        | SharePoint (encrypted), company-managed cloud only |
| Restricted          | Dedicated secure vaults; no cloud without CISO approval |

### 7.2 Prohibited Storage

The following are never permitted for Confidential or Restricted data:
- Personal cloud storage (Dropbox personal, iCloud personal, Google Drive personal)
- USB drives or external hard drives not approved and encrypted by IT
- Email (sending Restricted data via email in any form)
- Messaging apps (WhatsApp, iMessage, personal SMS)

### 7.3 Data Retention and Disposal

Data must be retained according to the Data Retention Schedule maintained by Legal. When data has reached end-of-retention:
- Digital data must be securely deleted using approved deletion tools (not standard delete/empty trash).
- Physical documents must be shredded using cross-cut shredders or placed in locked shred bins.

### 7.4 Data Transfer and Sharing

Sharing Confidential or Restricted data with external parties requires a signed Non-Disclosure Agreement (NDA) and approval from the data owner and Legal. All external data transfers must use encrypted channels.

---

## 8. Acceptable Use of Company Systems

### 8.1 Permitted Use

Company-provided systems are primarily for business use. Incidental personal use is permitted provided it does not:
- Consume excessive bandwidth or storage
- Violate any provision of this policy
- Interfere with job responsibilities

### 8.2 Prohibited Activities

The following activities on company systems are strictly prohibited:
- Installing unauthorized software
- Accessing, downloading, or transmitting illegal content
- Bypassing security controls (disabling antivirus, using anonymizing proxies)
- Mining cryptocurrency
- Accessing peer-to-peer (P2P) file sharing networks
- Sending or storing material that is harassing, discriminatory, or offensive

### 8.3 Monitoring

Employees have no expectation of privacy when using company systems, networks, or devices. Acme Corp reserves the right to monitor, log, and audit all activity on company-owned systems for security and compliance purposes. Monitoring is conducted in accordance with applicable law and company HR policies.

---

## 9. Cloud and SaaS Application Security

### 9.1 Approved Applications

Only IT-vetted and approved SaaS applications may be used to process, store, or transmit Acme Corp data. The approved application catalog is maintained on the IT Portal.

### 9.2 Shadow IT

Employees must not use unapproved third-party applications, AI tools, browser extensions, or cloud services to process company data. Requests to evaluate new tools should be submitted to IT via the Software Request form. Unapproved tool use is a policy violation.

### 9.3 AI and Generative Tools

Using public-facing generative AI services (e.g., ChatGPT free tier, Claude.ai consumer) to process, paste, or describe Confidential or Restricted company data is **prohibited**. Company-approved AI tools (listed in the IT Portal) with enterprise data protection agreements are permitted. Questions about approved AI usage should be directed to IT Security.

---

## 10. Security Awareness and Training

### 10.1 Mandatory Training

All employees must complete the following training:
- **Annual Security Awareness Training:** Due within 30 days of hire and annually thereafter.
- **Phishing Simulation:** Periodic simulated phishing campaigns are conducted by IT Security.
- **Data Handling Training:** Required for roles with access to Restricted data.

Failure to complete mandatory training within the deadline will result in system access suspension until training is completed.

### 10.2 Phishing and Social Engineering

Do not click links or open attachments in unexpected emails, even if they appear to be from colleagues. If you suspect a phishing attempt, report it immediately using the "Report Phishing" button in Outlook/Gmail or by forwarding to phishing@acmecorp.com. Do not delete the email before reporting.

---

## 11. Security Incident Response

### 11.1 What Constitutes a Security Incident

The following must be reported as security incidents:
- Lost or stolen devices containing company data
- Unauthorized access to company accounts or systems
- Suspected or confirmed malware infection
- Accidental disclosure of Confidential or Restricted data
- Successful phishing or credential compromise
- Any anomalous activity suggesting unauthorized access

### 11.2 Reporting Procedure

Report all suspected security incidents **within 1 hour** of discovery:
- **Email:** it-security@acmecorp.com
- **Emergency line:** +1-800-555-SECU (available 24/7)
- **Slack:** #security-incidents channel (for non-urgent reports during business hours)

### 11.3 Employee Obligations During Incident Response

Employees must cooperate fully with IT Security during incident investigations, including providing device access, account credentials (to IT only, via secure channel), and detailed accounts of events. Do not attempt to investigate, remediate, or conceal an incident independently.

---

## 12. Policy Violations and Consequences

Violations of this policy are treated seriously and may result in:
- Mandatory additional security training
- Revocation of system privileges
- Disciplinary action up to and including termination
- Civil litigation or criminal referral for severe violations (e.g., intentional data theft)

Unintentional violations reported promptly and in good faith will be treated more leniently than deliberate or concealed violations.

---

## 13. Contact and Questions

- **IT Security Team:** it-security@acmecorp.com
- **IT Help Desk:** it-help@acmecorp.com
- **CISO Office:** ciso@acmecorp.com
- **Policy Questions:** Your manager or People Operations
