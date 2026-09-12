# Development guidance

Keep SCLPLL syntax, parsing, formatting, runtime behavior, and built-in function registration in `sm408/sclpl-api`. This repository may consume those public APIs but must not create a second parser or formatter.

Keep release assets versioned and downloadable: the Python language-server wheel, VS Code VSIX, and plugin wheels where applicable. Update the catalog tables in the root, `plugins`, and `functions` READMEs whenever a public item is added or removed.

Never add credentials, connection strings, SAS tokens, auth headers, or secret values. Editor features must remain passive: no workflow/script execution, HTTP calls, or plugin activation while a document is analyzed.
