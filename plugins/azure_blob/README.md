# Azure Blob plugin

This package provides the `azblob` SCLPL resource provider. It requires Azure SDK packages and an SCLPL installation compatible with the version declared in `pyproject.toml`.

Install from this directory:

```powershell
py -3.12 -m pip install .
```

Provide credentials through your environment or SCLPL project configuration; never place account keys, SAS tokens, or connection strings in this repository. Opening a workflow in VS Code does not contact Azure.
