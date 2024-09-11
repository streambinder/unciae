# Author change

As sometimes it happens to forget to replace the cached Git identity on the workstation with the one you want to make commits with, this little tool aims to rewrite the whole Git repository commit history, replacing a matched author with a new desired one while keeping all the other relevant information.

## How to use

```bash
author-change/runner.sh old@author.me new_name:new@author.me
```
