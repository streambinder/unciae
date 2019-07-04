# Committer Changer

As sometimes it happens to forget to replace the cached Git identity on the workstation with the one you want to make commits with, this little tool aims to rewrite the whole Git repository commit history, replacing a matched author with a new desired one while keeping all the other relevant informations.

## How to use

```bash
committer-changer/runner.sh old@committ.er new_committer_name:new@committ.er
```
