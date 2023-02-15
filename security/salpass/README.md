# SalPass

This utility has been thought to act as a sort of stateless keychain which you ask your password to, giving it to you back without actually knowing it.

This is my answer to the need of keep in mind just one password for every service I'm subcribed to without effectively use that one.
The mechanism behind this script is self-explained by the concept of the _salted password_: in very poor words, it needs two arguments to generate a single password.
The first one is the payload, a discriminator that defines the service you're asking the password for and that's easy to remember/discover if needed, and the latter is the only password you need to remember, the key for the whole keychain, as it's the salt that's used to mix the discriminator payload.

That said, the resulting (mixed) payload gets hashed, cut and altered to increase password strength (with operations such as adding symbols as the hashtag, making the first letter uppercase, and so on).

## How to use

Fetch and install the requirements in a virtual environment (if desired):

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Then run the script:

```bash
salpass websi.te
Salt: *****
Verify: *****
Password (standard, v1) is: #869Cba47f4d7524
```

It offers two options:
1. `-s`/`--short` flag: many sites impose a max length to the password. This flag make the resulting password shorter.
2. `-v`/`--version <int>` flag: many sites impose to periodically update passwords without the opportunity to re-use old passwords. This flag can be used to increase version of the password, without altering either the discriminator payload or the salt.
3. `-c`/`--clip` flag: copies password to the clipboard instead of printing it.
