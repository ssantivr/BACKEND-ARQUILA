# Reading PDF and images with AI (R08)

| Endpoint | What it does |
|---|---|
| `GET /extraction/status` | Whether a reader is configured, and if it is an external service |
| `POST /projects/{id}/extractions` | Reads an uploaded file: `{file_id, consent}` |
| `GET /projects/{id}/extractions` | The last 20 readings of a project |
| `POST /extractions/{id}/apply` | Applies what the user corrected in the review |
| `POST /extractions/{id}/undo` | Takes back what a reading changed |

- Only values the document states, each with its source and confidence. Unknown stays empty.
- Coordinates and polygon points are never extracted.
- A reading is applied on its own only when every field has a confidence of at least 0.85 and a
  quote with its page that holds the value and its unit, nothing was rejected, the required
  fields are present, the file was not applied before and no text of the user would be replaced.
  Otherwise it waits for review. The quote also comes from the model, so it can be fabricated: the
  threshold and this rule are provisional until decision D-AI-3 is taken.
- Deleting the file forgets what was read from it. Deleting the project keeps only who read and
  when, for the quota.
- Everything is applied in one transaction, with a snapshot for the undo. The undo refuses to
  delete work done afterwards.
- Limits: 4.3 MB, 10 pages (counted from the page tree with pypdf; an encrypted PDF, or one that cannot be read in
  5 seconds, is refused), 40 megapixels,
  10 readings per user and `AI_EXTRACTION_DAILY_LIMIT` in total (100) in 24 hours, one reading at
  a time per user and four at once in each process.

## Configuration

| Variable | Use |
|---|---|
| `AI_EXTRACTION_PROVIDER` | `gemini`, `ollama` or empty (document forms stay manual; text builds use the local fallback) |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Both are needed for `gemini`; it reads PDF, PNG and JPEG |
| `OLLAMA_VISION_MODEL`, `OLLAMA_URL` | For `ollama`; it reads PNG and JPEG on your own server |

PDF page trees are limited to ten pages and PNG/JPEG images to 40 megapixels; documents over
4.3 MB are refused for extraction. If local Ollama is unavailable, the text-based parametric
builder remains usable without sending the description elsewhere.

`gemini` sends the document to Google and stays off until the owner gives a key and a budget
(decision D-AI). `ollama` counts as external unless it is on this machine and its model is not
a cloud one. An external reader needs the user's consent on every reading.
Check the current price and data terms of the provider before setting a key.

## Passwords (R03)

Passwords travel over HTTPS and are stored as Argon2id hashes: 64 MiB, 4 passes, 4 lanes. They
cannot be decrypted. A hash made with weaker parameters is replaced the next time its owner signs
in. Until then, a wrong password for that account answers slightly faster than an unknown
email. The session cookie is HttpOnly, SameSite and, with `COOKIE_SECURE=1`, Secure, with HSTS.
