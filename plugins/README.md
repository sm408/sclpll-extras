# Plugins

Plugins extend SCLPL through its public plugin API. They are optional and are never activated merely because a workflow is opened in VS Code. The editor reads safe manifest metadata for callable completion; plugin code is not imported during background analysis.

## Available plugins

| Plugin | Provides | Version |
|---|---|---|
| [`azure_blob`](azure_blob/) | `azblob` Azure Blob Storage resource provider | `0.9.1` |

Install a plugin from its release asset or package directory, configure credentials outside source control, then restart the SCLPL language server.

Keep each plugin in its own directory with a `pyproject.toml`, `plugin.toml`, package code, tests, and its own README. New entries belong in the table above. Declare safe callable `signature` and `parameters` metadata in the manifest when applicable so editor help can work without executing plugin code.
