"""Stable identities; exporter-compatible port GUID recipe promoted from S3."""

import hashlib, uuid

T = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"


def to_ifc_guid(b):  # GUIDUtil.ConvertToIFCGuid over new Guid(md5).ToByteArray()
    num = [
        b[3],
        b[2] * 65536 + b[1] * 256 + b[0],
        b[5] * 65536 + b[4] * 256 + b[7],
        b[6] * 65536 + b[8] * 256 + b[9],
        b[10] * 65536 + b[11] * 256 + b[12],
        b[13] * 65536 + b[14] * 256 + b[15],
    ]
    out = ""
    for i, n in enumerate(num):
        ln = 2 if i == 0 else 4
        chars = ""
        for _ in range(ln):
            chars = T[n % 64] + chars
            n //= 64
        out += chars
    return out


def h(key):
    return to_ifc_guid(hashlib.md5(key.encode("utf-8")).digest())


def free_port(elem_guid, cid):
    return h(f"{elem_guid}Sub-element:IfcDistributionPort Connector: {cid}")


def in_port(cid, in_guid, out_guid):
    return h(f"InPort{cid}{in_guid}{out_guid}")  # on the element processed first


def out_port(cid, in_guid, out_guid):
    return h(
        f"OutPort{cid}{out_guid}{in_guid}"
    )  # on the other element (same cid = the first element's connector)


IDENTITY_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "urn:usdaeco:id:v1")


def guid_to_uuid(global_id):
    if len(global_id) != 22 or global_id[0] not in "0123" or any(c not in T for c in global_id):
        raise ValueError("Invalid compressed GUID")
    value = 0
    for char in global_id:
        value = value * 64 + T.index(char)
    return str(uuid.UUID(int=value))


def uuid_to_guid(value):
    number = uuid.UUID(str(value)).int
    chars = []
    for _ in range(22):
        chars.append(T[number % 64])
        number //= 64
    return "".join(reversed(chars))


def mint_id(source, native_id, *, document, kind="element"):
    """Core v0.7 recipe: published root -> document -> route:kind:key.

    Callers must supply a durable document id, never a session file path.
    Input strings are UTF-8 verbatim, without case or Unicode normalization.
    """
    namespace = uuid.uuid5(IDENTITY_NAMESPACE, document)
    return str(uuid.uuid5(namespace, f"{source}:{kind}:{native_id}"))


def connected_candidates(element_guid, connector_id, peer_guid, peer_connector_id):
    return (
        in_port(connector_id, element_guid, peer_guid),
        out_port(peer_connector_id, peer_guid, element_guid),
    )
