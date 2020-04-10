#include <RH_ASK.h>
#ifdef RH_HAVE_HARDWARE_SPI
#include <SPI.h>
#endif

#include "ask_lab.h"
#include "ask_md5.h"

RH_ASK driver;

int ctr;
int wait_syn;
int wait_fin;

char payload_msg[RH_ASK_MAX_MESSAGE_LEN - 32];
char payload[RH_ASK_MAX_MESSAGE_LEN];

void setup() {
  Serial.begin(9600);
  if (!driver.init()) {
    Serial.println("Unable to init!");
  }
}

void loop() {
  if (wait_syn++ < ASK_LAB_WAIT_SYN) {
    Serial.println("Waiting before starting sending...");
    delay(1000);
    return;
  }

  if (ctr == ASK_LAB_EXP) {
    if (wait_fin++ < ASK_LAB_WAIT_FIN) {
      return loop_fin();
    }
    return stop_routine();
  }

  sprintf(payload_msg, "%d", ctr++);
  lab_payload_build(payload, payload_msg);
  Serial.print("Sending packet (");
  Serial.print(strlen(payload));
  Serial.print("): ");
  Serial.println(payload);
  driver.send(payload, strlen(payload));
  driver.waitPacketSent();
}

void loop_fin() {
  Serial.println("Sending FIN packet...");
  sprintf(payload_msg, ASK_LAB_FIN_MSG);
  lab_payload_build(payload, payload_msg);
  driver.send((uint8_t *)payload, strlen(payload));
  driver.waitPacketSent();
  delay(1000);
}
