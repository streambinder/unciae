# IsPsec

This tool aims to give a quick status overview of IPsec tunnels: it checks the reachability of a tunnel representative IP and eventually, if unreachable, it tries to restore the whole tunnel.

## How to use

To get started, just run:

```bash
ispsec/runner.sh tunnel1_name:192.168.1.200 tunnel2_name:192.168.2.50
```

In order to attempt a connection reset (if detected as unreachable):

```bash
ispsec/runner.sh tunnel1_name:192.168.1.200 -r
```

If you want to use a custom timeout (in seconds) while checking tunnels, use `-t`/`--timeout` flag:

```bash
ispsec/runner.sh -t 5 tunnel1_name:192.168.1.200
```

Finally, if you just want a quick tunnels oveview, you can use the tool without giving the tunnel name parameter (suppressing `tunnel1_name:` part of the tunnel data). This way, the tunnel will be checked anyway, but the tool won't proceed, if needed, to its reset.

