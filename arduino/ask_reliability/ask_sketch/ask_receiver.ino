#include <RH_ASK.h>
#ifdef RH_HAVE_HARDWARE_SPI
#include <SPI.h>
#endif

#include "ask_lab.h"

RH_ASK driver;

int ctr;
char payload[RH_ASK_MAX_MESSAGE_LEN];
uint8_t payload_len = sizeof(payload);

void setup() {
  Serial.begin(9600);
  if (!driver.init()) {
    Serial.println("Unable to init!");
  }
}

void loop() {
  if (!driver.recv(payload, &payload_len)) {
    return;
  }
  // Serial.print("Received: ");
  // Serial.println(payload);

  char payload_hash[ASK_LAB_HASHLEN + 1];
  lab_payload_chop_hash(payload_hash, payload);

  char payload_content[payload_len + 1 - ASK_LAB_HASHLEN];
  lab_payload_chop_content(payload_content, payload, payload_len);

  if (!lab_md5_verify(payload_hash, payload_content)) {
    Serial.println("Message is corrupted!");
    return;
  }

  if (!lab_auth(payload_content)) {
    Serial.println("Message can't be authenticated!");
    return;
  }

  char payload_msg[payload_len + 1 - ASK_LAB_HASHLEN - strlen(ASK_LAB_ID)];
  lab_payload_chop_msg(payload_msg, payload, payload_len);
  if (strcmp(payload_msg, ASK_LAB_FIN_MSG) == 0) {
    return print_stats();
  }

  Serial.print("Message ");
  Serial.print(payload_msg);
  Serial.println(" OK");
  ctr++;
}

void print_stats() {
  int ctr_avg = ctr / ASK_LAB_EXP * 100;
  Serial.print("Reliability: ");
  Serial.print(ctr_avg);
  Serial.println("%");
  stop_routine();
}
