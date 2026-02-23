# Scripts

Repository-level maintenance and verification utilities.

## Public release checks

```bash
./scripts/scan-secrets.sh
./scripts/verify-all.sh
```

## Script index

- `scan-secrets.sh` - scans tracked files for high-risk secret patterns.
- `verify-all.sh` - runs secret scan + backend tests + frontend lint/test/build.
