# Dups

Dups simplifies the handling of detection and removal of image duplicates within a targer directory, relying on the [`imagededup`](https://github.com/idealo/imagededup) utility.

## How to use

Fetch and install the requirements in a virtual environment (if desired):

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Run the script against a target directory and check out the generated JSON files:

```bash
./runner.py /path/to/images/library
```

An optional `-t`/`--threshold` flag is offered to regulate the strictness of the algorithm in marking the images as different.
