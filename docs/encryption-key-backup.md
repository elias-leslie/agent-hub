# Encryption Key Backup

Agent Hub uses Fernet symmetric encryption for credential storage.

## Key Location

```
~/.env.local → AGENT_HUB_ENCRYPTION_KEY
```

## Backup Procedure

1. **Copy key to secure location:**
   ```bash
   grep AGENT_HUB_ENCRYPTION_KEY ~/.env.local >> ~/backup/agent-hub-keys.txt
   ```

2. **Verify backup:**
   ```bash
   grep AGENT_HUB_ENCRYPTION_KEY ~/backup/agent-hub-keys.txt
   ```

## Recovery

If key is lost, encrypted credentials become unrecoverable. Re-enter all API keys after generating a new key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Key Rotation

Not currently supported. Requires decrypting all credentials with old key, then re-encrypting with new key.
