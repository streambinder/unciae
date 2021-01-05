# SalPass

This utility has been thought to act as a sort of stateless keychain which you ask your password to, giving it to you back without actually knowing it.

This is my answer to the need of keep in mind just one password for every service I'm subcribed to without effectively use that one.
The mechanism behind this script is self-explained by the concept of the _salted password_: in very poor words, it needs two arguments to generate a single password.
The first one is the payload, a discriminator that defines the service you're asking the password for and that's easy to remember/discover if needed, and the latter is the only password you need to remember, the key for the whole keychain, as it's the salt that's used to mix the discriminator payload.

That said, the resulting (mixed) payload gets hashed, cut and altered to increase password strength (with operations such as adding symbols as the hashtag, making the first letter uppercase, and so on).

## How to use

Straightforward, just run the script:

```bash
$ ./runner.py
Payload: websi.te
Salt: *****
Retype salt (verification): *****
Password (standard, v1) is: #869Cba47f4d7524
```

It eventually offers two options:
1. `-s`/`--short` flag: many websites impose a max length to the password. This flag make the resulting password shorter.
2. `-v`/`--version <int>` flag: many websites impose to periodically update passwords without the opportunity to re-use old passwords. This flag can be used to increase version of the password, without altering either the discriminator payload or the salt.