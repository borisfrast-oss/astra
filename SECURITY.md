# Security Policy

Thank you for helping keep Astra and its community safe.

## Supported Versions

Only the latest **1.9.x** release line receives security fixes. Please upgrade
to the newest release to benefit from security updates.

| Version | Supported |
| ------- | --------- |
| >= 1.9.0 | ✅ Yes |
| < 1.9.0 | ❌ No |

## Reporting a Vulnerability

We take security vulnerabilities seriously. Please **do not** open a public
issue for security problems.

To report a vulnerability, use one of the following private channels:

- **GitHub Security Advisories** — use the "Report a vulnerability" button on
  the repository's Security tab (private, only visible to maintainers).
- **Email** — [borisfrast@gmail.com](mailto:borisfrast@gmail.com)

Please include:

- A description of the vulnerability and its impact.
- Steps to reproduce or a proof of concept (if available).
- The affected version(s).

You can expect an acknowledgment within a few days. We will keep you informed
as the issue is investigated and a fix is prepared.

## No Hardcoded Secrets

As part of the Astra privacy gate, the repository must not contain hardcoded
secrets or personal/device-specific paths. This includes API tokens,
passwords, and paths such as `C:/Users/<user>/...`. If you discover any
hardcoded secret in the code, docs, or configuration, report it immediately
using the private channels above.

Thank you for contributing to a safer Astra.
