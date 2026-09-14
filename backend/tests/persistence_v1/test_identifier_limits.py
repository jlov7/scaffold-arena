from __future__ import annotations

from persistence_v1.schema import metadata


POSTGRES_IDENTIFIER_LIMIT = 63


def test_all_canonical_database_identifiers_fit_postgres_limit() -> None:
    identifiers: list[tuple[str, str]] = []
    for table in metadata.sorted_tables:
        identifiers.append((f"table:{table.name}", table.name))
        for column in table.columns:
            identifiers.append((f"column:{table.name}.{column.name}", column.name))
        for constraint in table.constraints:
            if constraint.name is not None:
                identifiers.append(
                    (f"constraint:{table.name}.{constraint.name}", str(constraint.name))
                )
        for index in table.indexes:
            if index.name is not None:
                identifiers.append((f"index:{table.name}.{index.name}", str(index.name)))

    offenders = {
        label: identifier
        for label, identifier in identifiers
        if len(identifier.encode("utf-8")) > POSTGRES_IDENTIFIER_LIMIT
    }
    assert offenders == {}, (
        "canonical SQL identifiers exceed PostgreSQL's 63-byte limit: "
        f"{offenders}"
    )


def test_repository_generated_ids_are_protocol_safe() -> None:
    from persistence_v1.repository import _id

    observed = {_id() for _ in range(256)}
    assert len(observed) == 256
    assert all(identifier.startswith("x") for identifier in observed)
    assert all(len(identifier) == 33 for identifier in observed)
    assert all(
        identifier[0].islower()
        and identifier.replace("-", "").replace("_", "").isalnum()
        and identifier == identifier.lower()
        for identifier in observed
    )
