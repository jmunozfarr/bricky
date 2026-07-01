from __future__ import annotations

IDENTITY = "0 0 0 1 0 0 0 1 0 0 0 1"


def generated_large_repeated_model(physical_part_occurrences: int) -> bytes:
    if physical_part_occurrences < 1:
        raise ValueError("Physical part occurrence count must be positive")
    attachments = [
        f"1 4 {index * 20} 0 0 1 0 0 0 1 0 0 0 1 repeated.ldr"
        for index in range(physical_part_occurrences)
    ]
    return (
        "\n".join(
            [
                "0 FILE main.ldr",
                "0 Generated repeated-model diagnostic fixture",
                *attachments,
                "0 FILE repeated.ldr",
                f"1 16 {IDENTITY} 3001.dat",
                "0 NOFILE",
            ]
        )
        + "\n"
    ).encode()
