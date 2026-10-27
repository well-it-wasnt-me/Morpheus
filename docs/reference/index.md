# API reference

Generated straight from the docstrings, so it's exactly as accurate as the docstrings. Which is to say:
pretty accurate, written by someone who reads code for a living and doesn't trust it.

Only public names show up here. The private `_reply_*` methods and friends are documented in the source, and
the [protocol pages](../protocols/index.md) describe what they put on the wire.

| Page | What's in it |
| --- | --- |
| [Core](core.md) | `Simulator`, the request handler, chaos, transports, Unidesa framing, the factory |
| [Protocols](protocols.md) | One simulator class per protocol, plus their constants and helpers |
| [Models](models.md) | `MachineState` |
| [CLI](cli.md) | The `morpheus-vlt` entry point |
| [Pytest plugin](pytest-plugin.md) | The `morpheus_vlt_server` fixture and `SimHandle` |
