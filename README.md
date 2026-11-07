# match-analyzer

Provisional code name. Web platform that analyzes replay files. Reference: `CLAUDE.md` and `docs/PLAN.md`.

## Development

Under WSL2, in the Linux file system. Requires Rust (`rustup`), `uv`, Node.js 22+, `pnpm`, `just` and Docker.

```bash
just install    # Python and TypeScript dependencies
just check      # everything CI runs
just dev-up     # PostgreSQL and S3 for development
just s3-check   # checks the S3 behavior uploads rely on
```

Copy `.env.example` to `.env` before starting the services. Replays are never versioned: `just corpus-check` verifies the local corpus against `tests/fixtures/manifest.toml`.
