"""
build_dataset.py

Aplana todos los directorios de ejecucion (metadata.json + result.json)
en un unico CSV tabular.

Estructura esperada de cada directorio de ejecucion:
    <timestamp>_<test_case>_<application>_<model>/
        metadata.json
        result.json
        agent.log
        screenshots/

Notas:
    - "repetition" se deriva del orden por timestamp de cada combinacion
      (application, model, test_case), ya que run_id no lleva un numero
      de repeticion explicito.
    - "likely_budget_exhausted" marca un ERROR con
      budget_utilization >= --budget-exhausted-threshold (0.85 por
      defecto) como probable agotamiento de presupuesto a mitad de
      tarea, distinto de un ERROR temprano (fallo tecnico).
    - Se compara metrics.screenshots contra el numero real de ficheros
      en screenshots/ como chequeo de consistencia.

Uso:
    python build_dataset.py --results-dir ~/cua-javafx-test/results --out dataset.csv
"""

import argparse
import csv
import json
import re
from pathlib import Path


RUN_DIR_PATTERN = re.compile(
    r"^(?P<timestamp>\d{8}_\d{6})_(?P<test_case>TC\d{2})_(?P<application>[A-Za-z0-9]+)_(?P<model>.+)$"
)


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_run_dir_name(name: str):
    m = RUN_DIR_PATTERN.match(name)
    if not m:
        return None
    return m.groupdict()


def count_screenshots(run_dir: Path) -> int:
    shots_dir = run_dir / "screenshots"
    if not shots_dir.is_dir():
        return -1
    return sum(1 for p in shots_dir.iterdir() if p.is_file())


def extract_row(run_dir: Path, budget_exhausted_threshold: float, warnings: list):
    name_info = parse_run_dir_name(run_dir.name)
    if name_info is None:
        warnings.append(f"[SKIP] nombre de carpeta no reconocido: {run_dir.name}")
        return None

    metadata_path = run_dir / "metadata.json"
    result_path = run_dir / "result.json"

    if not metadata_path.exists() or not result_path.exists():
        warnings.append(f"[SKIP] faltan metadata.json o result.json en: {run_dir.name}")
        return None

    try:
        metadata = load_json(metadata_path)
        result = load_json(result_path)
    except Exception as exc:
        warnings.append(f"[SKIP] error leyendo JSON en {run_dir.name}: {exc}")
        return None

    metrics = result.get("metrics", {})
    error = result.get("error") or {}

    trajectory_budget = metadata.get("trajectory_budget")
    response_cost = metrics.get("response_cost", 0.0)
    actions = metrics.get("actions", 0)
    total_tokens = metrics.get("total_tokens", 0)
    status = result.get("status")

    budget_utilization = (
        response_cost / trajectory_budget
        if trajectory_budget else None
    )
    likely_budget_exhausted = (
        status == "ERROR"
        and budget_utilization is not None
        and budget_utilization >= budget_exhausted_threshold
    )

    real_screenshot_count = count_screenshots(run_dir)
    if real_screenshot_count != -1 and real_screenshot_count != metrics.get("screenshots", -2):
        warnings.append(
            f"[CHECK] {run_dir.name}: metrics.screenshots={metrics.get('screenshots')} "
            f"pero hay {real_screenshot_count} ficheros en screenshots/"
        )

    return {
        "run_id": result.get("run_id", run_dir.name),
        "application": metadata.get("application", name_info["application"]),
        "model": metadata.get("model", name_info["model"]),
        "test_case": metadata.get("test_case", name_info["test_case"]),
        "timestamp": name_info["timestamp"],
        "trajectory_budget": trajectory_budget,
        "status": status,
        "error_type": error.get("type", ""),
        "error_message": error.get("message", ""),
        "input_tokens": metrics.get("input_tokens", 0),
        "output_tokens": metrics.get("output_tokens", 0),
        "total_tokens": total_tokens,
        "response_cost": response_cost,
        "actions": actions,
        "screenshots": metrics.get("screenshots", 0),
        "duration_seconds": result.get("duration_seconds", 0.0),
        "cost_per_action": (response_cost / actions) if actions else None,
        "tokens_per_action": (total_tokens / actions) if actions else None,
        "budget_utilization": budget_utilization,
        "likely_budget_exhausted": likely_budget_exhausted,
        "started_at": result.get("started_at", ""),
        "finished_at": result.get("finished_at", ""),
    }


def assign_repetitions(rows):
    """Deriva el numero de repeticion (1, 2, 3...) por (application, model, test_case), ordenando por timestamp."""
    rows_sorted = sorted(rows, key=lambda r: (r["application"], r["model"], r["test_case"], r["timestamp"]))

    counters = {}
    for row in rows_sorted:
        key = (row["application"], row["model"], row["test_case"])
        counters[key] = counters.get(key, 0) + 1
        row["repetition"] = counters[key]

    return rows_sorted


def main():
    parser = argparse.ArgumentParser(
        description="Aplana los directorios de resultados en un CSV tabular."
    )
    parser.add_argument("--results-dir", required=True, help="Directorio con las carpetas de ejecucion.")
    parser.add_argument("--out", default="dataset.csv", help="Ruta del CSV de salida.")
    parser.add_argument(
        "--budget-exhausted-threshold",
        type=float,
        default=0.85,
        help="Umbral de budget_utilization por encima del cual un ERROR se marca como likely_budget_exhausted (default: 0.85).",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir).expanduser()
    run_dirs = sorted(
        d for d in results_dir.iterdir()
        if d.is_dir() and (d / "result.json").exists()
    )

    if not run_dirs:
        print(f"No se encontraron carpetas de ejecucion validas bajo: {results_dir}")
        return

    warnings = []
    rows = []
    for run_dir in run_dirs:
        row = extract_row(run_dir, args.budget_exhausted_threshold, warnings)
        if row is not None:
            rows.append(row)

    rows = assign_repetitions(rows)

    fieldnames = [
        "run_id", "application", "model", "test_case", "repetition", "timestamp",
        "trajectory_budget", "status", "error_type", "error_message",
        "input_tokens", "output_tokens", "total_tokens", "response_cost",
        "actions", "screenshots", "duration_seconds",
        "cost_per_action", "tokens_per_action",
        "budget_utilization", "likely_budget_exhausted",
        "started_at", "finished_at",
    ]

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

    print(f"Procesadas {len(rows)} ejecuciones de {len(run_dirs)} carpetas encontradas.")
    print(f"CSV escrito en: {args.out}")

    if warnings:
        print(f"\n{len(warnings)} avisos:")
        for w in warnings:
            print(f"  {w}")

    from collections import Counter
    status_counts = Counter(r["status"] for r in rows)
    print("\nDistribucion de status:")
    for status, count in status_counts.items():
        print(f"  {status:10s}: {count}")

    budget_exhausted_count = sum(1 for r in rows if r["likely_budget_exhausted"])
    error_count = sum(1 for r in rows if r["status"] == "ERROR")
    print(f"\nDe los {error_count} ERROR, {budget_exhausted_count} parecen ser por presupuesto agotado "
          f"(budget_utilization >= {args.budget_exhausted_threshold}).")
    print(f"Los {error_count - budget_exhausted_count} restantes son ERROR tempranos (revisar error_type/message).")


if __name__ == "__main__":
    main()
