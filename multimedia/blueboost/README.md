# Blueboost

In several distributions I'm experiencing very-low-volume Bluetooth issues.
As a long journey has taken me to solve this issue, I just need to drop a universal snippet to correct the behaviour.
Basically, it seems the absolute max volume parameter associated to the Bluetooth device is not set to its real maximum: this is why a simple `dbus-send` command does the trick, increasing the upperbound to the max allowed for each connected Bluetooth device's MAC.

## How to use

No space for tuning, just fire the command:

```bash
blueboost/runner.sh
```
