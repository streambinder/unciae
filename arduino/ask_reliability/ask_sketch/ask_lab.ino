#include "ask_lab.h"
#include "ask_md5.h"

void stop_routine() {
  Serial.println("Exiting");
  while (1)
    ;
}

char *lab_md5(const char *message) {
  char *hash_msg =
      malloc((strlen(ASK_LAB_KEY) + strlen(message)) * sizeof(char));
  sprintf(hash_msg, "%s%s", ASK_LAB_KEY, message);

  unsigned char *hash = MD5::make_hash(hash_msg);
  free(hash_msg);

  char *md5 = MD5::make_digest(hash, 16);
  free(hash);

  return md5;
}

int lab_md5_verify(char *md5, const char *message) {
  char *md5_compare = lab_md5(message);
  int verify = 0;
  if (strcmp(md5, md5_compare) == 0) {
    verify = 1;
  }

  free(md5_compare);
  return verify;
}

int lab_auth(char *payload_content) {
  for (int i = 0; i < strlen(ASK_LAB_ID); i++) {
    if (payload_content[i] != ASK_LAB_ID[i]) {
      return 0;
    }
  }
  return 1;
}

void lab_payload_build(char *payload, const char *message) {
  char *hash_msg =
      malloc((strlen(ASK_LAB_ID) + strlen(message)) * sizeof(char));
  sprintf(hash_msg, "%s%s", ASK_LAB_ID, message);

  char *md5 = lab_md5(hash_msg);
  free(hash_msg);

  sprintf(payload, "%s%s%s", md5, ASK_LAB_ID, message);
  free(md5);
}

void lab_payload_chop_hash(char *hash, const char *payload) {
  strncpy(hash, payload, ASK_LAB_HASHLEN);
  hash[ASK_LAB_HASHLEN] = 0;
}

void lab_payload_chop_content(char *content, const char *payload,
                              const uint8_t payload_len) {
  for (int i = 0; i < payload_len - ASK_LAB_HASHLEN; i++) {
    content[i] = payload[ASK_LAB_HASHLEN + i];
  }
  content[payload_len - ASK_LAB_HASHLEN] = 0;
}

void lab_payload_chop_msg(char *msg, const char *payload,
                          const uint8_t payload_len) {
  for (int i = 0; i < payload_len - ASK_LAB_HASHLEN - strlen(ASK_LAB_ID); i++) {
    msg[i] = payload[ASK_LAB_HASHLEN + strlen(ASK_LAB_ID) + i];
  }
  msg[payload_len - ASK_LAB_HASHLEN - strlen(ASK_LAB_ID)] = 0;
}
