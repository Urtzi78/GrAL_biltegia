r"""
fix_metadata_budget.py

Corrige "trajectory_budget" en metadata.json segun modelo y test_case
(antes de la correccion en run_test.py, metadata.json escribia siempre
0.20 sin importar el budget real aplicado en la ejecucion). Solo toca
metadata.json; no modifica result.json, agent.log ni screenshots/.

Si el modelo no esta en BUDGET_TABLE, la carpeta se omite (no se
adivina un valor).

Requiere un backup previo de --results-dir (este script no lo hace):

    cd ~/cua-javafx-test/results
    mkdir -p old
    find . -maxdepth 1 -mindepth 1 -type d ! -name old -exec cp -r {} old/ \;

Uso:
    python fix_metadata_budget.py --results-dir ~/cua-javafx-test/results --dry-run
    python fix_metadata_budget.py --results-dir ~/cua-javafx-test/results --csv budget_fix_summary.csv
"""

import argparse
import csv
import json
from pathlib import Path


# Modelo -> (budget para TC03/TC06, budget para el resto)
BUDGET_TABLE = {
    "claude-haiku-4-5": (0.30, 0.20),
    "claude-sonnet-4-5": (0.50, 0.30),
}

HEAVY_TESTS = ("TC03", "TC06")


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def compute_correct_budget(model: str, test_case: str):
    if model not in BUDGET_TABLE:
        return None

    heavy_budget, normal_budget = BUDGET_TABLE[model]
    return heavy_budget if test_case in HEAVY_TESTS else normal_budget


def fix_one(metadata_path: Path, dry_run: bool):
    data = load_json(metadata_path)

    model = data.get("model")
    test_case = data.get("test_case")
    current_budget = data.get("trajectory_budget")

    correct_budget = compute_correct_budget(model, test_case)

    if correct_budget is None:
        return {
            "run_id": data.get("run_id", metadata_path.parent.name),
            "skipped": True,
            "reason": f"modelo desconocido en BUDGET_TABLE: '{model}'",
        }

    changed = current_budget != correct_budget

    if changed and not dry_run:
        data["trajectory_budget"] = correct_budget
        write_json(metadata_path, data)

    return {
        "run_id": data.get("run_id", metadata_path.parent.name),
        "skipped": False,
        "model": model,
        "test_case": test_case,
        "old_budget": current_budget,
        "new_budget": correct_budget,
        "changed": changed,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Corrige trajectory_budget en metadata.json segun modelo y test_case."
    )
    parser.add_argument("--results-dir", required=True, help="Directorio con las carpetas de ejecucion.")
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra los cambios, sin escribir.")
    parser.add_argument("--csv", default=None, help="Ruta opcional para guardar el resumen en CSV.")
    args = parser.parse_args()

    results_dir = Path(args.results_dir).expanduser()
    metadata_files = sorted(results_dir.glob("*/metadata.json"))

    if not metadata_files:
        print(f"No se encontraron metadata.json bajo: {results_dir}")
        return

    rows = []
    for path in metadata_files:
        try:
            row = fix_one(path, dry_run=args.dry_run)
        except Exception as exc:
            row = {
                "run_id": path.parent.name,
                "skipped": True,
                "reason": f"ERROR procesando: {type(exc).__name__}: {exc}",
            }
        rows.append(row)

    print("=" * 90)
    print(f"{'run_id':50s} {'modelo':20s} {'test':6s} {'budget_ant':>10s} {'budget_ok':>10s} {'cambia':>7s}")
    print("=" * 90)

    n_changed = 0
    n_skipped = 0

    for r in rows:
        if r.get("skipped"):
            n_skipped += 1
            print(f"{r['run_id']:50s} (omitido: {r.get('reason', '')})")
            continue

        if r["changed"]:
            n_changed += 1

        print(
            f"{r['run_id']:50s} {str(r['model']):20s} {str(r['test_case']):6s} "
            f"{str(r['old_budget']):>10s} {str(r['new_budget']):>10s} "
            f"{'SI' if r['changed'] else 'no':>7s}"
        )

    print("=" * 90)
    print(f"Total: {len(rows)}  |  corregidos: {n_changed}  |  ya correctos: {len(rows) - n_changed - n_skipped}  |  omitidos: {n_skipped}")

    if args.dry_run:
        print("\n(--dry-run activo: no se ha escrito nada en disco)")
    else:
        print("\nSe han corregido los metadata.json in-place.")

    if args.csv:
        fieldnames = ["run_id", "skipped", "reason", "model", "test_case", "old_budget", "new_budget", "changed"]
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in rows:
                writer.writerow({k: r.get(k, "") for k in fieldnames})
        print(f"\nResumen guardado en: {args.csv}")


if __name__ == "__main__":
    main()
