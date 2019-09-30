#!/bin/bash

source "$(realpath "$(dirname $0)")/db_common.sh"

mkdir -p "${DIR_DB}"
find "${DIR_DB}" -type f -delete
mysql --max_allowed_packet="${MAX_ALLOWED_PACKET}" -sN -u root -p'2dkNKCVT9AgFaV8g' -e "SHOW DATABASES;" | \
    grep -Ev "(Database|information_schema|performance_schema)" | \
    while read db ; do
        mysqldump -u dumper -p'dump3r!' "${db}" \
            --add-drop-table --max_allowed_packet="${MAX_ALLOWED_PACKET}" \
            --single-transaction="true" --lock-tables="false" > "${DIR_DB}/${db}.sql"
done
