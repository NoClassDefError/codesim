# Contributing to CodeSim

Thank you for helping improve CodeSim. Contributions can include bug reports,
documentation, tests, examples, device and system models, numerical fixes, and
frontend improvements.

## Before opening an issue

- Search existing issues to avoid duplicates.
- Use a current CodeSim release or the latest development version.
- Reduce bugs to the smallest reproducible system where possible.
- Remove customer, employer, personal, export-controlled, or otherwise
  confidential information before posting.
- For security-sensitive reports, follow `SECURITY.md` instead of opening a
  public issue.

A useful bug report includes the CodeSim version or commit, operating system,
Python and VS Code versions, the system and options used, expected behaviour,
actual behaviour, and a minimal reproducer.

## Development setup

The Python backend requires Python with NumPy, SciPy, and SymPy. The test suite
also uses pytest.

```powershell
python -m pip install numpy scipy sympy pytest
python -m pytest codesimpy/tests
```

The VS Code extension and webview are under `frontend`.

```powershell
cd frontend
npm ci
npm run build
npm run lint
```

Run the checks relevant to your change before submitting it. Changes that alter
numerical behaviour should include focused regression tests and should explain
any intentional change to reference results or tolerances.

## Design guidelines

- Keep equations, parameters, states, inputs, and units explicit and
  inspectable.
- Preserve established domain names where they carry modelling meaning. The
  Python implementation intentionally retains names such as `Vb`, `Sb`, `p`,
  `x`, `u`, `uref`, `f`, and `g` from the original model conventions.
- Include physical units in user-facing parameter names where practical.
- Prefer reproducible examples and deterministic tests.
- Avoid unrelated formatting, renaming, or generated-file changes in a focused
  contribution.
- Keep the Python API and frontend message schema backward compatible unless a
  breaking change is discussed first.
- Document modelling assumptions, validity limits, initialization requirements,
  and numerical tolerances for new models.

Generated snapshots, caches, build output, packaged extensions, and local
environment files should not be committed unless a maintainer explicitly asks
for them as a release artifact or test fixture.

## Pull requests

Keep each pull request focused. The description should state:

1. what problem it solves;
2. the approach taken;
3. how it was tested;
4. whether numerical results, public APIs, schemas, dependencies, or licensing
   information changed; and
5. any remaining limitations.

Maintainers may request changes to preserve model traceability, numerical
stability, compatibility, documentation quality, or legal provenance.

## Licensing of contributions

CodeSim is licensed under the Apache License, Version 2.0. Unless you explicitly
state otherwise in writing, any contribution intentionally submitted for
inclusion in CodeSim is provided under the same license, in accordance with
Section 5 of the Apache License, Version 2.0.

By submitting a contribution, you represent that you have the right to submit
it under those terms. Do not submit code, equations, model parameters, data,
figures, documentation, or other material copied from a third party unless its
license permits inclusion and you identify its source and license in the pull
request.

Submitting a contribution does not grant permission to use CodeSim trademarks
or imply that a derivative product is an official CodeSim release. See
`TRADEMARKS.md`.

## Third-party dependencies

Discuss new runtime dependencies before adding them. A dependency proposal
should explain why it is needed, its maintenance status, package size, security
impact, and license. Update `THIRD_PARTY_NOTICES` when a distributed dependency
or its license changes.
