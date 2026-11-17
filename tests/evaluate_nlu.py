"""Evaluate the bundled Rasa artifact on a separate, authored English test set."""

import argparse
import asyncio
import hashlib
import json
import platform
from pathlib import Path
from time import perf_counter

from run import MODEL, ROOT, cpu_environment

import os
os.environ.update(cpu_environment())

import yaml
from rasa.core.agent import Agent
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix


def examples(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        (entry["intent"], line.strip()[2:])
        for entry in data["nlu"] if "intent" in entry
        for line in entry["examples"].splitlines() if line.strip().startswith("- ")
    ]


async def evaluate(output: Path):
    train = examples(ROOT / "rasa" / "data" / "nlu.yml")
    test = examples(ROOT / "rasa" / "heldout.yml")
    by_text = lambda pairs: {text.casefold() for _, text in pairs}
    assert not (by_text(train) & by_text(test)), "Exact utterance overlap"
    model = Agent.load(str(MODEL))
    await model.parse_message("hello")  # Exclude model load and the first inference.
    records = []
    for gold, text in test:
        start = perf_counter()
        result = await model.parse_message(text)
        time_ms = (perf_counter() - start) * 1000
        intent = result["intent"]
        raw = intent["name"]
        predicted = "out_of_scope" if raw == "nlu_fallback" else raw
        records.append({
            "text": text, "expected": gold, "predicted": predicted, "raw_intent": raw,
            "confidence": None if raw == "nlu_fallback" else intent["confidence"],
            "inference_ms": round(time_ms, 3),
        })

    gold = [row["expected"] for row in records]
    prediction = [row["predicted"] for row in records]
    labels = list(dict.fromkeys(gold))
    timings = sorted(row["inference_ms"] for row in records)
    report = {
        "model_sha256": hashlib.sha256(MODEL.read_bytes()).hexdigest(),
        "platform": platform.platform(), "python": platform.python_version(),
        "training_examples": len(train), "heldout_examples": len(test),
        "classes": labels, "correct": sum(a == b for a, b in zip(gold, prediction)),
        "accuracy": accuracy_score(gold, prediction),
        "scores": classification_report(gold, prediction, labels=labels,
                                        zero_division=0, output_dict=True),
        "confusion": confusion_matrix(gold, prediction, labels=labels).tolist(),
        "raw_fallbacks": sum(row["raw_intent"] == "nlu_fallback" for row in records),
        "latency_ms": {"p50": timings[len(timings) // 2],
                       "p95": timings[(95 * len(timings) + 99) // 100 - 1]},
        "predictions": records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Training utterances       {len(train)}")
    print(f"Held-out utterances       {len(test)} ({len(labels)} classes)")
    print(f"Correct predictions       {report['correct']}/{len(test)}")
    print(f"Intent accuracy           {report['accuracy']:.1%}")
    print(f"Macro F1                  {report['scores']['macro avg']['f1-score']:.3f}")
    print(f"Inference p50 / p95       {report['latency_ms']['p50']:.2f} / "
          f"{report['latency_ms']['p95']:.2f} ms")
    print(f"Raw fallback predictions  {report['raw_fallbacks']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" / "nlu_evaluation.json")
    asyncio.run(evaluate(parser.parse_args().output))
