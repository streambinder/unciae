# IsPsec

This tool aims to give a quick status overview of IPsec tunnels: it check the reachability of an IP associated to the tunnel and eventually, if unreachable, it tries to restore the whole tunnel.

## How to use

To get started, just run:

```bash
ispsec/runner.sh tunnel1_name:192.168.1.200 tunnel2_name:192.168.2.50
```

In order to do attempt a connection reset (if found as unreachable):

```bash
ispsec/runner.sh tunnel1_name:192.168.1.200 -r
```

If you want to use a custom timeout (in seconds) while checking tunnels, use `-t`/`--timeout` flag:

```bash
ispsec/runner.sh -t 5 tunnel1_name:192.168.1.200
```

**NB**: you can also use the tool without giving the tunnel name parameter (suppressing `tunnel1_name:` part of the tunnel data), the tunnel will be checked anyway, but won't proceed, if needed, to its reset.

