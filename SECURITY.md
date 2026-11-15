# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub: open the repository's **Security** tab and choose
**Report a vulnerability** (private vulnerability reporting). Do not open a public issue or pull request for a
security problem.

Do not include secrets, access tokens, or real personal data in a report. Describe how to reproduce the problem
with synthetic data, and redact anything sensitive from logs and screenshots.

## Supported versions

Prüfstand is pre-1.0. Only the `main` branch and the latest release receive security fixes.

## What to expect

- We acknowledge a report within 7 days.
- We send a fix or a mitigation plan within 30 days.
- We practise coordinated disclosure: please keep the details private until a fix or mitigation is available.
  We will credit you in the advisory if you wish.

## Scope

In scope: the gate (the `pruefstand` package and CLI), the GitHub Action, and the dashboard.

Out of scope: vulnerabilities in third-party dependencies, unless this repository uses them in an unsafe way.
Report those to the upstream project.
