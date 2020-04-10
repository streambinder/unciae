#ifndef ASK_LAB_H
#define ASK_LAB_H

#define ASK_LAB_ID "ask_lab"
#define ASK_LAB_KEY "supersecret"
#define ASK_LAB_FIN_MSG "fin"
#define ASK_LAB_HASHLEN 32
#define ASK_LAB_WAIT_SYN 5 // seconds
#define ASK_LAB_WAIT_FIN 10 // seconds
#define ASK_LAB_EXP 100

char *lab_md5(const char *message);
int lab_md5_verify(char *md5, const char *message);
void lab_payload_build(char *payload, const char *message);
void lab_payload_chop_hash(char *hash, const char *payload);
void lab_payload_chop_msg(char *msg, const char *payload,
                          const uint8_t payload_len);

#endif /* ASK_LAB_H */
