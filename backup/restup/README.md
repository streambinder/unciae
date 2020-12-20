# Restup

This is a simple Python script that behaves as wrapper for [Restic](https://github.com/restic) backup system.
It basically functions upons a script and a YAML-formatted configuration file.

## How to use

The only purpose of this script is to batch trigger `backup` command over several Restic repositories and eventually wrapping it with pre/post operations. It has been made to be inserted into `crontab` and do backup for you.

This means it won't setup the repositories for you, you'll need to do it by yourself.

### I — setup repositories

Assume you want to backup `/root` in `/var/restic/firstrepo` Restic repository and `/etc` in `/var/restic/latterone` one:

```bash
mkdir /var/restic
restic -r /var/restic/firstrepo init
restic -r /var/restic/latterone init
```

### II — populate config file

Now you need to inflate `restic backup` commands parameter in the `config.yml`.

In order to do that, assume `firstrepo` repository backup task to need some pre-backup operations and `latterone` one to need some paths to be excluded. The resulting `config.yml` would be:

```yaml
tasks:
  - repository: /var/restic/firstrepo
    password: "P4sSw0Rd1" # the one used during init stage
    path: /root
    retention: 1y2m
    prespawn: echo "content" > /root/sample.txt
    postspawn: /usr/local/sbin/post_backup.sh
  - repository: /var/restic/latterone
    password: "P4sSw0Rd2"
    path: /etc
    retention: 1m
    regexes:
      - "*.log"
      - "*.log*.gz"
      - "*/tmp/*"
```

The resulting commands spawned by the script would be:

- `firstrepo`:
  ```bash
  echo "content" > /root/sample.txt
  echo "P4sSw0Rd1" | restic -r /var/restic/firstrepo \
      backup /root --exclude-caches
  /usr/local/sbin/post_backup.sh
  echo "P4sSw0Rd1" | restic -r /var/restic/firstrepo \
      forget --keep-within 1y2m
  ```
- `latterone`:
  ```bash
  echo "P4sSw0Rd2" | restic -r /var/restic/latterone \
      backup /etc --exclude-caches \
      --iexclude "*.log" \
      --iexclude "*.log*.gz" \
      --iexclude "*/tmp/*"
  echo "P4sSw0Rd2" | restic -r /var/restic/latterone \
      forget --keep-within 1m
  ```

Also, all the tasks will be processed in dedicated threads.

### III — schedule backup

The whole script purpose was to be able to configure in a flexible and simple way different kind of backup, while keeping it simple to schedule them.

I personally use it as a scheduled command as a `crontab` entry:

```bash
0 2 * * * /path/to/restup/runner.py
```

By default, the script will be looking for the `config.yml` in the same directory as it is in (`/path/to/restup/` in the example). Otherwise you can give it yourself as first argument: `/path/to/restup/runner.py /path/to/config.yml`).
