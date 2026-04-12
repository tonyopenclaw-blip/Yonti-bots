# HEARTBEAT.md

## Superbot Stats - Every 15 min

Every 15 minutes, run the stats script and send results to Discord.

```bash
python3 /home/ubuntu/.openclaw/workspace/workers/superbot/stats_report.py
```

The script handles everything: fetches balance, parses trades from log, calculates stats, posts to Discord webhook.
