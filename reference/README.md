## Reference Files

The runtime source of truth for Jenny's mutable prompt text lives in the database, not in this directory.

- Heartbeat instructions: use `st persona instructions`, `st persona instructions -e`, or `st persona instructions --export <file>`
- Personality and other persona fields: use the `st persona` CLI or the persona UI
- `st persona update --heartbeat-instructions <file>` is an import path into the DB, not a second source of truth

Do not store live prompt bodies in `reference/`. Any file here should be static research material or an explicitly generated export.
