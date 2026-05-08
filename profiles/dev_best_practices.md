# Developer Best Practices

> Lightweight coding standards injected into all code-generation prompts.
> Follow these rules when writing or reviewing code.

## Naming

- **Python**: `snake_case` for variables/functions, `PascalCase` for classes, `UPPER_SNAKE` for constants.
- **JavaScript**: `camelCase` for variables/functions, `PascalCase` for classes/components.
- Use descriptive, intention-revealing names. Avoid abbreviations except well-known ones (`url`, `id`, `db`).
- Boolean variables: prefix with `is_`, `has_`, `can_`, `should_`.

## Code Structure

- **DRY** — Extract shared logic into helper functions. Never copy-paste blocks.
- **SRP** — Each function does one thing. Each file covers one concern.
- **Small units** — Functions ≤ 40 lines, files ≤ 300 lines. Split when larger.
- **Imports** — Group: stdlib → third-party → local. No wildcard imports.
- **Constants** — No magic numbers/strings. Extract to named constants at module top.

## Error Handling

- Always wrap external calls (network, file I/O, DB) in try/except.
- Use typed exceptions, never bare `except:`. Catch the narrowest type possible.
- Log errors with context (`logger.error("Failed to load %s: %s", name, e)`).
- Return meaningful error messages to the user; log stack traces for debugging.
- Fail fast on invalid input — validate early, at the boundary.

## Security (OWASP)

- **Never** hardcode secrets, API keys, or passwords. Use env vars or config.
- Parameterized queries only — no string-concatenated SQL.
- Sanitize and validate all user inputs (type, length, format).
- Escape output for the target context (HTML, SQL, shell).
- Use HTTPS for all external requests. Verify TLS certificates.
- Apply principle of least privilege for file/DB access.

## Documentation

- **Docstrings**: Every public function/class gets a one-line summary + Args/Returns if non-obvious.
- **Comments**: Explain *why*, not *what*. The code should be self-documenting for the *what*.
- **Type hints** (Python): All function signatures. Use `Optional`, `list[str]`, etc.
- **JSDoc** (JavaScript): Document params and return types for public functions.

## Testing

- Write unit tests for critical business logic and edge cases.
- Test error paths, not just happy paths.
- Use descriptive test names: `test_<function>_<scenario>_<expected>`.
- Mock external dependencies (network, DB, filesystem).

## Performance

- **Lazy loading** — Import heavy modules inside functions, not at module top.
- **Async I/O** — Use `async/await` for network and disk operations.
- **Avoid N+1** — Batch database queries. Prefetch related data.
- **Cache** expensive computations that don't change often.
- Profile before optimizing — don't prematurely optimize.

## Frontend

- **Semantic HTML** — Use `<nav>`, `<main>`, `<section>`, `<article>` appropriately.
- **CSS Variables** — Define colors, spacing, and fonts as `--var(...)` tokens.
- **Responsive** — Mobile-first, use Grid/Flexbox, test at 320px–1920px.
- **Accessibility** — `aria-label` on icons, keyboard navigation, sufficient contrast.
- **No inline styles** — All styling in external CSS files.

## Git & Workflow

- **Conventional commits**: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`.
- Small, focused commits — one logical change per commit.
- Always test before committing. Never commit broken code.
