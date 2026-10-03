# Security

- Never commit `.env`, database URLs, bearer tokens, provider keys, or credentials. Load them from server-side environment variables or secure runtime configuration.
- Use a unique, high-entropy `SENSE_TOKEN`; protect it anywhere Reality and Hand clients are configured.
- Sensor, location, personal-place, device, and activity data are highly sensitive. Keep databases private; do not publish raw logs, database exports, or location history.
- Do not put secrets or personal location data in public issues. Use GitHub private vulnerability reporting when enabled, or contact the maintainer privately through GitHub.
