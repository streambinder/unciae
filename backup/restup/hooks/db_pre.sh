#!/bin/bash

# shellcheck source=./db_common.sh
source "$(realpath "$(dirname "$0")")/db_common.sh"

mkdir -p "${DIR_DB}"
find "${DIR_DB}" -type f -delete
mysql -sN -u root -p'2dkNKCVT9AgFaV8g' -e "SHOW DATABASES;" | \
        grep -Ev "(Database|information_schema|performance_schema)" | \
        while read -r db; do
    mysqldump -u root -p'2dkNKCVT9AgFaV8g' "${db}" --add-drop-table > "${DIR_DB}/${db}.sql"
done
