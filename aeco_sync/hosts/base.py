"""Host contract and discovery. This module imports no authoring runtime."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib import import_module, metadata


class Operations(list):
    """Preflighted edits plus the engine's connected-element closure."""
    def __init__(self, edits, closure):
        super().__init__(edits)
        self.closure = closure


@dataclass(frozen=True)
class MutationReceipt:
    """Native handles changed atomically; readback resolves their final values."""
    touched: tuple[str, ...]
    version: str


class Host(ABC):
    """One open document per instance; the engine owns USD layer publication.

    A file host additionally implements save(path) and declares file_backed and
    file_suffix. An external transaction may implement acknowledge() to clear a
    durable recovery receipt only after USD publication succeeds.
    """
    name = ""
    file_backed = False
    file_suffix = ""

    @abstractmethod
    def capabilities(self):
        """Return supported operation families as an immutable set of strings."""

    @abstractmethod
    def open(self, session):
        """Open the configured document for a session and return self."""

    @abstractmethod
    def apply(self, operations):
        """Atomically apply Operations and return a MutationReceipt."""

    @abstractmethod
    def readback(self, ids):
        """Return result-layer data {touched, meshes, stamp}; None means all ids.

        touched records carry paths, native refs, normalized drivers and derived
        values. The engine's publisher serializes this into result.<host>.usda.
        """

    @abstractmethod
    def diagnostics(self):
        """Return normalized diagnostic dictionaries from this transaction."""

    @abstractmethod
    def close(self):
        """Release resources, including after a failed open or transaction."""

    @abstractmethod
    def version(self):
        """Opaque native change token, read without mutating the document."""

    @classmethod
    def initialize(cls, model, document, directory=None, policy="keepConnected", *, kind_import=False):
        if kind_import:
            raise ValueError("This host does not provide a kind importer")
        from ..stack import create
        return create(model, document, directory, policy, host=cls.name)

    def supports(self, edit):
        """Per-element refinement of capabilities; integrations may override."""
        return edit.operation in self.capabilities()

    def unsupported_reason(self, edit):
        return getattr(self, "_unsupported_reason", None) or f"Disallowed {edit.operation} {edit.name} for this native element"

    def validate(self):
        """Additional native validation rows, scoped by validation_refs."""
        return []


def discover():
    """Return installed entry points, rejecting ambiguous host names."""
    result = {}
    for entry in metadata.entry_points(group="aeco_sync.hosts"):
        if entry.name in result:
            raise ValueError(f"Multiple aeco_sync.hosts entry points named {entry.name}")
        result[entry.name] = entry
    return result


def host_class(name, host_module=None):
    """Resolve an installed name or explicit module:Class override."""
    if host_module:
        module, sep, symbol = host_module.partition(":")
        if not sep or not module or not symbol:
            raise ValueError("--host-module must be module:Class")
        cls = getattr(import_module(module), symbol)
    else:
        entry = discover().get(name)
        if entry is None:
            raise ValueError(f"No installed host {name!r}; install its integration or use --host-module module:Class")
        cls = entry.load()
    if not isinstance(cls, type) or not issubclass(cls, Host):
        raise TypeError("Host implementation must subclass aeco_sync.hosts.base.Host")
    if cls.name != name:
        raise ValueError(f"Host class name {cls.name!r} does not match {name!r}")
    return cls


def open_host(session, name, document=None, *, host_module=None, **options):
    cls = host_class(name, host_module)
    native = cls(document=document, **options)
    try:
        return native.open(session)
    except BaseException:
        native.close()
        raise
