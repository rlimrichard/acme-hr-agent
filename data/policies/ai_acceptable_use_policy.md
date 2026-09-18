# AI Tools Acceptable Use Policy

**Document ID:** POL-AIU-017  
**Effective Date:** January 1, 2025  
**Last Reviewed:** September 1, 2025  
**Owner:** IT Security / Legal  
**Version:** 1.2

---

## 1. Purpose and Scope

This policy governs the use of artificial intelligence (AI) and generative AI tools by Acme Corp employees in the course of their work. As AI tools become embedded in professional workflows, this policy ensures their use is safe, responsible, legally compliant, and consistent with Acme Corp's data protection obligations.

This policy applies to all employees, contractors, and interns who use AI tools in connection with Acme Corp work. It governs AI-specific requirements not addressed in the broader Data Security Policy (POL-SEC-004):
- POL-SEC-004 §9.2 defines **shadow IT** policy broadly; this policy provides the AI-specific detail, approved tool list, and use-case guidance.
- POL-SEC-004 §9.3 introduced the prohibition on public AI for Confidential/Restricted data; this policy expands on that with tiered use rules, prompt hygiene, and output governance.

---

## 2. AI Tool Categories

### 2.1 Classification of AI Tools

Acme Corp classifies AI tools into three tiers based on their data protection posture:

| Tier | Description | Default Status |
|---|---|---|
| **Tier 1 — Approved Enterprise** | Company-contracted tools with a signed Data Processing Agreement (DPA) guaranteeing data is not used for model training and is subject to enterprise data controls | Approved for use with Confidential data |
| **Tier 2 — Approved Standard** | Company-licensed tools with standard terms; data may be processed by the vendor but is not used for model training | Approved for Internal data; not for Confidential or Restricted |
| **Tier 3 — Prohibited** | Consumer-grade or unapproved tools with no enterprise agreement; data may be used to train models | Prohibited for any company data |

### 2.2 Approved Tools List

The current approved AI tool catalog is maintained in the IT Portal and updated as new tools are vetted. As of the effective date of this policy, approved tools include:

| Tool | Tier | Approved Use Cases |
|---|---|---|
| Microsoft Copilot (M365) | Tier 1 | Drafting, summarization, code assistance, data analysis |
| Claude for Enterprise | Tier 1 | Research, writing, coding, analysis, HR agent workflows |
| GitHub Copilot (Business) | Tier 1 | Code completion, code review assistance |
| Notion AI (Enterprise) | Tier 2 | Internal documentation drafting |
| Grammarly Business | Tier 2 | Writing assistance (Internal content only) |

Employees must not use Tier 3 tools (e.g., ChatGPT free, Claude.ai consumer, Gemini personal, Perplexity free) for any Acme Corp work. Requests to add tools to the approved list are submitted via the Software Request form in the IT Portal.

---

## 3. Data Input Rules

### 3.1 What You May and May Not Input

Data input rules follow the tool tier and the data classification (defined in POL-SEC-004 §2.1):

| Data Classification | Tier 1 Tools | Tier 2 Tools | Tier 3 Tools |
|---|---|---|---|
| Public | Permitted | Permitted | Permitted |
| Internal | Permitted | Permitted | Prohibited |
| Confidential | Permitted | Prohibited | Prohibited |
| Restricted | Prohibited (requires CISO approval) | Prohibited | Prohibited |

### 3.2 Specific Prohibitions

Regardless of tool tier, employees must **never** input the following into any AI tool:
- Full customer PII (names + contact info + account data in combination)
- Employee salary, performance rating, or medical information
- Unpublished financial results or projections
- Security credentials, API keys, or authentication tokens
- Pending M&A, fundraising, or strategic transaction details
- Legal matter details (litigation, regulatory investigations)

### 3.3 Anonymization and Redaction

When in doubt, anonymize or redact before inputting. Replace specific names with "[Employee A]", specific financials with "[AMOUNT]", and customer names with "[Customer]". This practice reduces risk while preserving the usefulness of the AI tool.

---

## 4. Prompt Hygiene

### 4.1 Principle of Minimum Necessary Context

Craft prompts using the **minimum amount of company information necessary** to get a useful output. Avoid pasting entire documents when a summary or excerpt would suffice.

### 4.2 Avoid Embedded Credentials

Never include passwords, API keys, database connection strings, or authentication tokens in prompts. Use placeholder text or environment variable names instead.

### 4.3 Prompt Injection Awareness

Be aware that when using AI tools to process external content (web pages, third-party documents, user inputs), that content may contain **prompt injection attacks** — instructions embedded in the content designed to manipulate the AI's behavior or extract information. Review AI outputs critically when the input included external content.

### 4.4 Conversation History

AI tool conversations may be logged and reviewable by IT Security for compliance purposes. Do not use AI chat interfaces as a substitute for secure internal communication channels when discussing sensitive matters.

---

## 5. Output Governance

### 5.1 Human Review Requirement

AI-generated outputs must be **reviewed and verified by a human employee** before use in any of the following contexts:
- Customer-facing communications or documentation
- Legal or compliance submissions
- Financial analysis or reporting
- Personnel decisions (hiring, performance, compensation)
- Code merged to a production branch

"AI generated this, I haven't checked it" is not an acceptable defense for errors, policy violations, or legal liability arising from AI output.

### 5.2 Accuracy Verification

AI tools may hallucinate facts, citations, statistics, and code. Employees are responsible for verifying material claims in AI-generated content against authoritative sources before relying on or distributing them.

### 5.3 Disclosure of AI Use

Employees must disclose AI assistance in the following contexts:
- **Research and analysis deliverables** sent to external parties: include a note such as "Prepared with AI assistance; verified by [Name]."
- **Code pull requests:** Note AI-assisted sections in the PR description.
- **Published content** (blog posts, whitepapers): Disclose per Marketing guidelines.

Internal use of AI for drafting, brainstorming, or iteration does not require disclosure.

---

## 6. Intellectual Property and Copyright

### 6.1 Ownership of AI-Assisted Work

Work product created by employees using approved AI tools in the course of their employment is owned by Acme Corp under the standard terms of employment, consistent with the IP Assignment Agreement signed at hire. AI assistance does not affect this ownership.

### 6.2 Copyright Risks in AI Outputs

AI-generated text, code, and images may incorporate content from training data in ways that could raise copyright concerns. Employees should:
- Not use AI to reproduce substantial portions of third-party copyrighted text verbatim
- Treat AI-generated code as subject to potential open-source license obligations and run it through the standard open-source review process before inclusion in proprietary products
- Consult Legal before publishing AI-generated content that may be substantially similar to known third-party works

### 6.3 AI in Patent Filings

AI tools may not be listed as an inventor in patent applications. Use of AI assistance in the inventive process must be disclosed to Legal when submitting invention disclosures.

---

## 7. AI in People Decisions

### 7.1 Prohibition on Automated HR Decisions

AI tools must not be used to make **automated, unreviewed decisions** about:
- Hiring or rejecting candidates
- Performance ratings or promotion decisions
- Compensation changes
- Disciplinary actions or terminations

AI may assist with drafting, summarizing interview notes, or flagging patterns for human review, but a qualified human must make all final personnel decisions with full accountability.

### 7.2 Bias Awareness in AI-Assisted Hiring

Employees using AI to screen resumes, draft job descriptions, or evaluate candidates must be aware that AI tools may reflect historical biases. Any AI-assisted screening tool used in hiring must be reviewed by the DEI Office before deployment (see POL-DEI-014 §4).

---

## 8. Training and Accountability

### 8.1 Mandatory AI Literacy Training

All employees are required to complete **AI Tools Acceptable Use Training** in Workday Learning within:
- **New hires:** Within 30 days of start date
- **Existing employees:** By March 31st, 2025 (initial rollout), and annually thereafter

### 8.2 Violations

Violations of this policy — including use of unapproved tools with company data or inputting Restricted data into any AI tool — are treated as data security violations under POL-SEC-004 §12 and may result in disciplinary action up to termination.

---

## 9. Contact and Questions

- **IT Security (tool approvals, incidents):** it-security@acmecorp.com
- **IT Help Desk (access to approved tools):** it-help@acmecorp.com
- **Legal (IP, copyright, patent questions):** legal@acmecorp.com
- **DEI Office (AI in hiring reviews):** dei@acmecorp.com
