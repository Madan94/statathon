"""Prepare Dataset — convert PLFS labels to HuggingFace Dataset format.

Converts the JSONL from label_plfs.py into a HuggingFace Dataset suitable
for ColPali fine-tuning with LoRA.

Usage:
  python scripts/colpali_finetune/prepare_dataset.py \
    --labels ./data/colpali_labels/plfs_labels.jsonl \
    --output ./data/colpali_dataset/
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def prepare_dataset(labels_path: Path, output_dir: Path) -> None:
    """Convert JSONL labels to train/val splits in HuggingFace format."""
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = []
    with open(labels_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))

    if not samples:
        logger.warning("No samples found in %s", labels_path)
        return

    # 80/20 train/val split
    split_idx = int(len(samples) * 0.8)
    train_samples = samples[:split_idx]
    val_samples = samples[split_idx:]

    # Convert to ColPali fine-tuning format
    # Each sample: {"image_path": ..., "query": ..., "target": ...}
    def to_training_format(sample: dict) -> dict:
        return {
            "image_path": sample.get("image", ""),
            "query": f"What analytical question does this page answer?",
            "target": sample.get("question_intent", ""),
            "metadata": {
                "statement": sample.get("statement", ""),
                "archetype": sample.get("archetype", ""),
                "entities": sample.get("entities", []),
            },
        }

    train_data = [to_training_format(s) for s in train_samples]
    val_data = [to_training_format(s) for s in val_samples]

    # Write splits
    (output_dir / "train.jsonl").write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in train_data),
        encoding="utf-8",
    )
    (output_dir / "val.jsonl").write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in val_data),
        encoding="utf-8",
    )

    logger.info(
        "Dataset prepared: %d train, %d val → %s",
        len(train_data), len(val_data), output_dir,
    )


def main():
    parser = argparse.ArgumentParser(description="Prepare ColPali dataset from labels")
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    prepare_dataset(args.labels, args.output)


if __name__ == "__main__":
    main()
