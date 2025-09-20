# cron.sh
#!/bin/bash
set -e

# Call inactive sessions every 15 minutes
curl -H "X-API-KEY: $BACKEND_API_KEY" \
     -X GET "https://patrolio-patrol-sessions.onrender.com/inactive_sessions/15"
