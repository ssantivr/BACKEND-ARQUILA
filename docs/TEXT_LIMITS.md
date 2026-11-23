# Text limits (R07)

Every free text a user types has at most 200 characters. Shorter limits that already existed stay.

| Exception | Limit |
|---|---|
| Password | 8 to 128 |
| Email | 254 |
| Chat messages and AI-generated text | Set by each endpoint |
| Uploaded file contents | 20 MB |
| JSON settings, hashes, storage paths and asset references | Set by each column |

An older project text that is longer can be sent back unchanged, so the project stays editable.
The limit holds in the API. The database checks (migration 018) ship later, after the rows that
are already longer are counted (decision D-200).
