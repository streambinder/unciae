#!/bin/bash

set -e
export PATH=$PATH:/usr/local/bin

CONTACT_EMAIL="email@addre.ss"
BACKUP_VHOSTS="vhost1 vhost2"
BACKUP_EXT_FOLDERS="/path/to/folder1 /path/to/folder2"
BACKUP_RETENTION=2     # month(s)
BANDWIDTH_SHAPING=1024 # kbps

BACKUP_NAME="$(date +%Y-%m-%d)"
BACKUP_LOWERBOUND="$(date --date="${BACKUP_RETENTION} months ago" +%s)"
BACKUP_MEGADIR="/Root/server-backups/"
DIR_OFFLINE="/tmp/backup_${BACKUP_NAME}"
DIR_ONLINE="${BACKUP_MEGADIR}/${BACKUP_NAME//-//}"
LOG_FILE="${DIR_OFFLINE}/backup.log"

function mmkdir() {
	awk -F'/' '{ for(i = 1; i <= NF; i++) { print $i; } }' <<<"$1" | grep -v ^$ | while read -r col; do
		subpath="${subpath}/${col}"
		megamkdir "$subpath" &>/dev/null || echo -n
	done
}
function mmtopemptydir() {
	dir_child="$1"
	dir_parent="$(rev <<<"${dir_child}" | cut -d'/' -f 2- | rev)"
	if [ "$(megals -R "${dir_parent}" | grep -c "^${dir_child}")" -gt 1 ]; then
		echo "${dir_child}"
	else
		mmtopemptydir "${dir_parent}"
	fi
}

mkdir -p "${DIR_OFFLINE}"
exec &> >(tee -a "${LOG_FILE}")
exec 2>&1

# web sources
if [ ! -f "${DIR_OFFLINE}/webserver.tar.xz" ]; then
	echo "Backing up web sources"
	cd /var/www
	find -L "${BACKUP_VHOSTS}" -type f -not -path '*/.git/*' \( -path '*/web/*' -o -path '*/private/*' \) -print0 | tar cvfJ "${DIR_OFFLINE}/webserver.tar.xz" --null -T -
fi

# mail
if [ ! -f "${DIR_OFFLINE}/mailserver.tar.xz" ]; then
	echo "Backing up mail data"
	cd /var/vmail
	grep -v mailfilters <<<"$(ls)" | tar cvfJ "${DIR_OFFLINE}/mailserver.tar.xz" -T -
fi

# database
if [ ! -f "${DIR_OFFLINE}/databases.tar.xz" ]; then
	echo "Backing up databases"
	cd "${DIR_OFFLINE}"
	mysql -sN -u backup -p'b4ckup' -e "SHOW DATABASES;" |
		grep -Ev "(Database|information_schema|performance_schema)" |
		while read -r dbname; do
			mysqldump -u backup -p'b4ckup' "$dbname" --add-drop-table >"${DIR_OFFLINE}/${dbname}.sql"
		done
	tar cvfJ "${DIR_OFFLINE}/databases.tar.xz" ./*.sql
	rm -f ./*.sql
fi

# acls
if [ ! -f "${DIR_OFFLINE}/acls.tar.xz" ]; then
	echo "Backing up ACLs"
	cd "${DIR_OFFLINE}"
	set +e
	getfacl -pR / >"${DIR_OFFLINE}/acls.txt" 2>/dev/null
	set -e
	tar cvfJ "acls.tar.xz" "acls.txt"
	rm -f "acls.txt"
fi

# external folders
if [ -n "${BACKUP_EXT_FOLDERS}" ]; then
	for folder in ${BACKUP_EXT_FOLDERS}; do
		echo "Backing up folder ${folder}"
		folder_bkp="$(basename "${folder}").tar.xz"
		if [ -f "${DIR_OFFLINE}/${folder_bkp}" ]; then
			continue
		fi
		cd "${folder}"
		find . -maxdepth 1 -not -name '.' -not -name '..' | tar cvfJ "${DIR_OFFLINE}/${folder_bkp}" -T -
		cd -
	done
fi

# recycling
recycle_volumes=""
empty_volumes=""
while read -r backup_path; do
	backup="${backup_path//BACKUP_MEGADIR/}"
	backup="${backup:1}"
	backup="${backup//\//-}"
	if [ "$(date --date="${backup}" +%s)" -lt "${BACKUP_LOWERBOUND}" ] &&
		[ "${#backup_path}" -gt "$((${#BACKUP_MEGADIR} + 1))" ]; then
		echo "Removing ${backup_path}..."
		recycle_volumes="${recycle_volumes} ${backup_path}"
	else
		echo "Recycling detection completed: ignoring volumes from ${backup_path} and newer."
		break
	fi
done <<<"$(megals -R "${BACKUP_MEGADIR}" | grep -e -E "^${BACKUP_MEGADIR}/[0-9]{4}/[0-9]{2}/[0-9]{2}$" | sort -u)"
while read -r volume_path; do
	if [ "$(megals -R "${volume_path}" | wc -l)" -le "1" ]; then
		top_empty_volume_path="$(mmtopemptydir "${volume_path}")"
		if [ "$(grep -c " ${top_empty_volume_path} " <<<"${empty_volumes}")" -eq 0 ]; then
			echo "Removing (empty) ${top_empty_volume_path}..."
			empty_volumes="${empty_volumes} ${top_empty_volume_path}"
		fi
	fi
done <<<"$(megals -R "${BACKUP_MEGADIR}" | grep -E '/[0-9]+$')"
if [ "$((${#recycle_volumes} + ${#empty_volumes}))" -gt "$((${#BACKUP_MEGADIR} + 1))" ]; then
	echo "Starting effecting volumes recycling..."
	megarm "${recycle_volumes} ${empty_volumes}"
fi

# synchronizing
echo "Creating online directory ${DIR_ONLINE}"
mmkdir "${DIR_ONLINE}"
echo "Pushing data to MEGA"
megacopy --limit-speed="${BANDWIDTH_SHAPING}" --local "${DIR_OFFLINE}" --remote "${DIR_ONLINE}"

if [ -n "${CONTACT_EMAIL}" ]; then
	mail -s "MEGA backup outcome" "${CONTACT_EMAIL}" <"${LOG_FILE}"
fi

echo "Removing local backup"
rm -rf "${DIR_OFFLINE}"
