# Agent Global Requirements

This file records user-level requirements for AI agents working in this workspace.

## Link Verification

- Before sharing a web link with the user, open and verify that the link is reachable.
- Do not present inaccessible, login-blocked, dynamically unavailable, or otherwise unverified pages as reliable sources.
- If a link is useful but unstable or requires authentication, clearly label that limitation instead of handing it to the user as a normal reference.
- For topics that may change over time, including policies, recruiting processes, pricing, software versions, and official documentation, check the latest available source before answering.
- Prefer official documentation and official sources when available.
- Clearly label non-official sources as reference material only.

## Communication and Code Changes

- If the user asks a question, answer the question directly.
- Use precise, standardized wording. Keep language accurate, logically coherent, and free of vague or poorly reasoned claims.
- Think through statements before presenting them. Do not make unsupported assertions or ambiguous conclusions.
- Distinguish between question-answering requests and execution requests.
- If the user has not explicitly asked to modify code, run commands, create files, or otherwise change the project, do not proactively change the project.
- If the user only asks for analysis, explanation, or a comparison of options, provide only the requested analysis output.
- Before writing or modifying code, ask the user clarifying questions first.
- Do not start code changes until the user's concrete requirements, details, and constraints are clear.
- After the requirements are clear, list the proposed modification plan and wait for the user's confirmation before writing code.

## Precision and Wording

- Use rigorous wording in technical explanations.
- Avoid vague qualifiers such as “可能”, “大概”, “一般”, or “应该” when the topology, configuration, observed evidence, or stated requirements already determine the conclusion.
- When uncertainty exists, explicitly state what is uncertain, what evidence is missing, and how to verify it.
- Do not use imprecise wording that could imply a different network path, behavior, or requirement than the actual configuration supports.

## Command Reliability and Static Analysis

- When running searches or scripts on Windows PowerShell, avoid complex one-line commands with nested quotes, regex metacharacters, pipes, or shell-sensitive characters unless the command has been tested.
- Prefer simple fixed-string searches such as `rg -F 'literal text' path` before using complex regular expressions.
- If a search requires complex parsing, use a small script or simpler repeated commands instead of relying on fragile PowerShell quoting.
- Do not pipe large PowerShell here-strings directly into `python -` for important analysis. PowerShell text encoding, BOM, or hidden characters can prevent Python from reading the script correctly.
- For Python analysis, prefer `python -c` for short snippets, an existing script file, or a clearly scoped temporary script that is removed after use.
- If a command fails because of shell quoting, encoding, or invocation syntax, treat it as a tooling issue, rerun with a corrected command, and do not present the failed attempt as a project problem.
- When identifying unused code, treat static import graphs as preliminary evidence only. Before declaring code unused or deleting it, also check name references, string-based references, router/CLI/config entry points, tests, and dynamic imports.
- Clearly distinguish confirmed project findings from analysis-tool limitations or failed commands when reporting results to the user.

## Linus/Torvalds-Style Code Changes

- Apply these principles to all code writing, code modification, feature implementation, bug fixing, and refactoring work.
- Prioritize data structures, ownership boundaries, and state transitions before extracting helpers, classes, files, or architectural layers.
- Do not change code by merely moving it into more files. A code change should reduce real complexity, remove duplication, clarify data flow, protect an invariant, or deliver required behavior.
- Prefer simple, direct, boring code over clever abstractions, framework-like indirection, wrapper layers, pass-through methods, and compatibility shims.
- Treat total code size as a meaningful signal. Splitting a large file is not enough if the total amount of code grows without a concrete payoff.
- Delete obsolete branches, duplicated normalization, redundant adapters, and unused compatibility paths when behavior and public contracts can be preserved.
- Keep one source of truth for IDs, status values, ownership, permission checks, and derived task/team/report state.
- Make invalid states hard to represent through clearer data shapes and centralized state transitions, instead of scattering defensive special cases across callers.
- Prefer explicit error handling and straightforward control flow. Avoid hidden side effects, broad catch-all behavior, and silent fallback paths.
- Before adding a new abstraction, state what code it removes, what duplication it eliminates, what invariant it protects, or what required behavior it enables. If it only moves code around, do not add it.
- For large legacy areas, change code in measurable cuts: list the expected files, the code to delete or collapse, the behavior that must remain unchanged, and the validation commands to run.

## Code Style Constraints

- Follow the existing style, structure, naming, and architecture of the current project.
- Do not introduce a new style, framework, abstraction, or formatting convention unless the user explicitly asks for it.
- Prefer clear, readable, self-explanatory code over clever or overly compact code.
- Use meaningful names. Avoid obscure abbreviations, pinyin names, and vague names such as `data`, `temp`, and `foo`, unless locally conventional.
- Comments should explain why something is done, not restate what the code already says.
- Keep code changes narrowly scoped to the user's request.
- Do not perform unrelated refactors, formatting-only rewrites, dependency upgrades, or file moves without explicit approval.
- Preserve public APIs, data formats, database schemas, and user-facing behavior unless the user confirms the change.
- Each file should have a clear, specific responsibility. Avoid catch-all files that collect unrelated functions, components, state, API calls, and business logic.
- Keep functions focused on one responsibility.
- Avoid large functions, deeply nested branches, duplicated logic, and hidden side effects.
- Extract helpers only when they reduce real complexity or match an existing project pattern.
- Handle errors explicitly. Do not silently swallow exceptions or return ambiguous failures.
- Validate inputs and handle empty, null, boundary, timeout, and failure cases.
- Release resources correctly, including files, network connections, locks, timers, and subscriptions.
- Do not hard-code secrets, tokens, passwords, private keys, or personal data.
- Do not introduce SQL injection, command injection, XSS, SSRF, unsafe deserialization, or arbitrary code execution risks.
- Treat external input as untrusted unless the codebase already guarantees validation.
- Use the repository's existing formatter, linter, type checker, and test commands.
- For Go, use `gofmt -s`, `goimports`, and the repository's `golangci-lint` configuration when present.
- For JavaScript and TypeScript, use the repository's ESLint, Prettier, TypeScript, and package manager conventions.
- For Python, use the repository's configured formatter, linter, type checker, and test runner.
- After code changes, report what was changed, which files were touched, and what verification was run.
- If tests or checks cannot be run, explain why clearly.
