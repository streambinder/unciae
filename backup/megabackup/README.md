# MEGABackup

This is a very simple backup system based on `tar.xz` compression, with automatic files retention and that's using MEGA as backup destination.

It backups common things such as databases (check `Databases dumper user setup` section), Apache virtual hosts, mail directories, filesystem ACLs and eventual arbitrary additional folders.
Keep in mind, it has been written for a ISPConfig-configured webserver and it assumes several directory locations by defaults (such as `/var/www/vhost` symlink for virtual hosts, or `/var/vmail` for mail directories, and so on).

The directory structure, inside the folder chosen as MEGA target directory, will be something like this:

```text
|- 2018
   |- 12
      |- 31
         |- acls.tar.xz
         |- backup.log
         |- databases.tar.xz
         |- mailserver.tar.xz
         |- webserver.tar.xz
         |- folder1.tar.xz
         |- folder2.tar.xz
|- 2019
   |- 01
      |- 01
         |- acls.tar.xz
         |- backup.log
         |- databases.tar.xz
         |- mailserver.tar.xz
         |- webserver.tar.xz
         |- folder1.tar.xz
         |- folder2.tar.xz
      |- 02
         |- acls.tar.xz
         |- backup.log
         |- databases.tar.xz
         |- mailserver.tar.xz
         |- webserver.tar.xz
         |- folder1.tar.xz
         |- folder2.tar.xz
      |- 03
         |- acls.tar.xz
         |- backup.log
         |- databases.tar.xz
         |- mailserver.tar.xz
         |- webserver.tar.xz
         |- folder1.tar.xz
         |- folder2.tar.xz
```

## How to use

First of all, it relies on [`MEGATools`](https://megatools.megous.com) project: the script uses `megacopy` subcommand to synchronize backup on MEGA storage.
Once installed, create a `~/.megarc` file (using the same user which will trigger the script run), with the following content:

```ini
[Login]
Username = email@addre.ss
Password = p4ssw0rd
```

In the first lines of the script you've the ability to tune few parameters, such as:

1. `CONTACT_EMAIL`: if you want a backup report via email
2. `BACKUP_VHOSTS`: to select which virtual hosts to backup
3. `BACKUP_EXT_FOLDERS`: to backup any other additional path
4. `BACKUP_RETENTION`: to set backup retention (months)
5. `BANDWIDTH_SHAPING`: to set the maximum bandwidth available for the backup synchronization to MEGA
6. `BACKUP_MEGADIR`: to set in which MEGA folder to save backups (it typically starts with `/Root/`)

### Databases dumper user setup

In order to backup databases, assure you have a user with these privileges: `USAGE`, `SELECT`, `LOCK TABLES`, `SHOW VIEW`, `EVENT`, `TRIGGER`, `SHOW DATABASES`. Creating a dedicated one is straightforward:

```sql
GRANT USAGE, SELECT, LOCK TABLES,
    SHOW VIEW, EVENT, TRIGGER, SHOW DATABASES
    ON *.*
    TO 'backup'@'localhost'
    IDENTIFIED BY 'b4ckup';
```
