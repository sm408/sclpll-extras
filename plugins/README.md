# Plugins

Plugins extend SCLPL through its public plugin API. They are optional and are never activated merely because a workflow is opened in VS Code. The editor reads safe manifest metadata for callable completion; plugin code is not imported during background analysis.

## Included example

[`azure_blob`](azure_blob/) is the existing Azure Blob resource-provider package. Install it from that folder with its declared dependencies, configure credentials outside source control, then restart the SCLPL language server.

Keep each plugin in its own directory with a `pyproject.toml`, `plugin.toml`, package code, tests, and its own README. Declare safe callable `signature` and `parameters` metadata in the manifest when applicable so editor help can work without executing plugin code.
