# Proditores

This script computes the list of Instagram accounts not following back (and some more).

## How to use

First, you need to obtain your current followers+following data from Instagram:

- head to <https://accountscenter.instagram.com>
- on the left menu, click on **Your information and permissions**
- select **Download your information**
- click on **Download or transfer information**
- select **Instagram profile**
- select **Some of your information**
- within **Connections**, enable **Followers and following** and hit **Next**
- select **Download to device**
- for **Date range**, select **All time**
- for **Format**, select **JSON**
- click **Create files**

At some point, in about half an hour top, you should receive an email that the data is ready for download: do it and run the script with the newly fetched file.

```bash
proditores/runner.sh instagram-nickname-1970-01-01-SoMeID.zip
```
