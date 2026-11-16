"""F22 output publication: the ``decoy-publication/v1`` descriptor and the publication types.

The descriptor codec (``_descriptor.py``), the request and receipt types and the typed errors
(``_types.py``), and the judge and bind under the destination lock (``_publish.py``:
``publish_unit``, ``publish_tables``). Vault ordering and the sink state table arrive in later
slices of the same package. Contract: ``docs/publication.md``.
"""

from decoy_engine.publication._descriptor import (
    ARTIFACT_FIELDS,
    DESCRIPTOR_NAME,
    MAX_DESCRIPTOR_BYTES,
    SCHEMA,
    Artifact,
    Descriptor,
    DescriptorVault,
    build_descriptor,
    compute_result_id,
    decode_descriptor,
    descriptor_digest,
    encode_descriptor,
)
from decoy_engine.publication._publish import publish_tables, publish_unit
from decoy_engine.publication._sink_state import (
    Act,
    Exit,
    SinkState,
    SinkStateMachine,
    recover,
)
from decoy_engine.publication._types import (
    MAX_COUNT,
    OPERATION_ID_PATTERN,
    UNIT_IMMUTABLE_DIRECTORY,
    ArtifactSummary,
    CommitReceipt,
    Outcome,
    PublicationFailed,
    PublicationRefused,
    PublicationRequest,
    VaultBinding,
    is_hex64,
    is_operation_id,
    raise_for_outcome,
)

__all__ = [
    "ARTIFACT_FIELDS",
    "DESCRIPTOR_NAME",
    "MAX_COUNT",
    "MAX_DESCRIPTOR_BYTES",
    "OPERATION_ID_PATTERN",
    "SCHEMA",
    "UNIT_IMMUTABLE_DIRECTORY",
    "Act",
    "Artifact",
    "ArtifactSummary",
    "CommitReceipt",
    "Descriptor",
    "DescriptorVault",
    "Exit",
    "Outcome",
    "PublicationFailed",
    "PublicationRefused",
    "PublicationRequest",
    "SinkState",
    "SinkStateMachine",
    "VaultBinding",
    "build_descriptor",
    "compute_result_id",
    "decode_descriptor",
    "descriptor_digest",
    "encode_descriptor",
    "is_hex64",
    "is_operation_id",
    "publish_tables",
    "publish_unit",
    "raise_for_outcome",
    "recover",
]
