# ASK Reliability

This project wraps up the source code used to run Radio Frequency (RF) communication reliability experimentations between two Arduino Nano devices:

1. Transmitter: connected to the Amplitude Shift Key (ASK) `ANT/FS1000A` board (`VCC` to `5V`, `ATAD` to `D12`)
2. Receiver: connected to the `XY-MK-5V` board (`VCC` to `5V`, (one) `DATA` to `D11`)

## How to use

Connect the Arduino boards via USB.
Open up `ask_tx/ask_transmitter.ino` and `ask_rx/ask_receiver.ino` as separated projects on Arduino IDE and load them to each specific board.
Follow the flow by connecting to the USB/Serial ports (`ttyUSB` ports mapping could very likely be different):
```bash
# transmitter
screen -S tx /dev/ttyUSB0; screen -X -S tx quit
# receiver
screen -S rx /dev/ttyUSB1; screen -X -S rx quit
```
