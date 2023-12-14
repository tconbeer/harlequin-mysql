from __future__ import annotations

import csv
import re
from pathlib import Path

from harlequin import HarlequinCompletion

WORD = re.compile(r"\w+")


def load_completions() -> list[HarlequinCompletion]:
    completions: list[HarlequinCompletion] = []

    keywords_path = Path(__file__).parent / "keywords.csv"
    with keywords_path.open("r") as f:
        reader = csv.reader(f, dialect="unix")
        for name, reserved, removed in reader:
            if removed == "False":
                completions.append(
                    HarlequinCompletion(
                        label=name.lower(),
                        type_label="kw",
                        value=name.lower(),
                        priority=100 if reserved else 1000,
                        context=None,
                    )
                )

    functions_path = Path(__file__).parent / "functions.tsv"
    with functions_path.open("r") as f:
        reader = csv.reader(f, dialect="unix", delimiter="\t")
        for name, _, _, deprecated in reader:
            if deprecated:
                continue
            for alias in name.split(", "):
                if WORD.match(alias):
                    completions.append(
                        HarlequinCompletion(
                            label=alias.split("...")[0].split("(")[0].lower(),
                            type_label="fn",
                            value=alias.split("...")[0].split("(")[0].lower(),
                            priority=1000,
                            context=None,
                        )
                    )

    return completions
