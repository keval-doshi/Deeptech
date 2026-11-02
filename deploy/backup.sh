#!/bin/sh
# Nightly database and uploads backup into /backups, keeping RETENTION_DAYS days.
# Connection settings come from the PG* environment variables.
# Copy /backups off this server too: a backup on the same disk won't survive losing the server.
retention="${RETENTION_DAYS:-30}"
while true; do
  stamp=$(date -u +%Y%m%d-%H%M%S)
  if pg_dump -Fc -f "/backups/.db-$stamp.tmp" && pg_restore --list "/backups/.db-$stamp.tmp" > /dev/null; then
    mv "/backups/.db-$stamp.tmp" "/backups/db-$stamp.dump"
    echo "$stamp database backup written"
  else
    rm -f "/backups/.db-$stamp.tmp"
    echo "$stamp ERROR: database backup failed" >&2
  fi
  if tar -czf "/backups/.uploads-$stamp.tmp" -C /uploads .; then
    mv "/backups/.uploads-$stamp.tmp" "/backups/uploads-$stamp.tar.gz"
    echo "$stamp uploads backup written"
  else
    rm -f "/backups/.uploads-$stamp.tmp"
    echo "$stamp ERROR: uploads backup failed" >&2
  fi
  find /backups -type f \( -name 'db-*.dump' -o -name 'uploads-*.tar.gz' \) -mtime +"$retention" -delete
  sleep 86400
done
