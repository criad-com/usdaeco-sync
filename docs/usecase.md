# Edit in USD, let the host solve

A coordinator edits an axis, a size or a relationship in a sparse USD intent
layer. The integration submits those drivers to the authoring kernel. Sync
publishes the kernel's resolved drivers, bodies and findings into separate
layers; refused intent remains visible and retryable. An empty intent layer
means no pending requests, while convergence separately tests measured agreement.

The protocol is a library, without a facility-specific headline example or a
native solver. See the [host contract](host-contract.md), the historical
[protocol design](protocol.md), and the [minimal stage](../usdAecoSync/examples/minimal.usda).
IFC conversion, kind import and IFC transactions live in `usdaeco-ifc`; other
integrations own their host end to end.
