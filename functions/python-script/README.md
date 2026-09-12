# Python script function example

`13-python-script.py` reads input rows from JSON stdin, multiplies amounts, and writes scored rows to JSON stdout. `sclpl.toml` registers it as `scorer`; the workflow [`../../workflows/13-python-script.sclpll`](../../workflows/13-python-script.sclpll) invokes that name.

Run the script itself normally:

```powershell
'[{"id": 1, "amount": 12.5}]' | py 13-python-script.py --multiplier 2
```

After changing the script, calculate a new SHA-256 and update `sclpl.toml`. Do not make editor features import or execute custom scripts.
