# Security policy

## Supported versions

Security fixes are applied to the latest released version and the current
development branch. Older releases may be affected even when a fix can be
backported.

| Version | Supported |
| --- | --- |
| Latest release | Yes |
| Current development branch | Yes |
| Older releases | Best effort |

## Reporting a vulnerability

Please do not disclose a suspected vulnerability in a public issue, discussion,
pull request, or social-media post before maintainers have had a reasonable
opportunity to investigate it.

Use GitHub's **Report a vulnerability** private reporting feature for the
official CodeSim repository. Include:

- the affected version or commit;
- the affected component and configuration;
- reproduction steps or a proof of concept;
- the impact you believe is possible;
- any known mitigations; and
- whether the report or its details have been shared elsewhere.

If private vulnerability reporting is unavailable, open a public issue that
only requests a private contact channel. Do not include vulnerability details
in that issue.

The maintainers aim to acknowledge a complete report within seven days and to
provide an initial assessment within fourteen days. Complex numerical,
dependency, or platform issues may require more time. A disclosure timeline
will be coordinated with the reporter where practical.

## Scope

Examples of security-relevant reports include:

- command or code execution through untrusted project data;
- path traversal or unintended file access;
- unsafe handling of external processes, files, or messages;
- exposure of secrets or sensitive local data;
- malicious model or snapshot content escaping its intended boundary;
- vulnerabilities in bundled frontend dependencies; and
- integrity defects that could silently substitute or tamper with analysis
  inputs or outputs.

Ordinary modelling disagreements, expected numerical approximation error,
unsupported operating conditions, and documentation questions should normally
be reported as regular issues. However, report an integrity problem privately
if it can be deliberately exploited to produce misleading results without a
reasonable opportunity for detection.

CodeSim is a research and engineering analysis tool. Unless accompanied by a
separate written agreement, it is not certified for protection, control,
safety-critical operation, or autonomous operational decisions.

## Safe-harbour intent

Good-faith research that avoids privacy violations, service disruption,
destruction of data, and access beyond what is necessary to demonstrate the
issue is welcomed. This policy does not create a bug-bounty program or promise
payment. It also does not authorize testing of third-party systems or data.
