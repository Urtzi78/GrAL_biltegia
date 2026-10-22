r"""
fix_results_inplace.py

Corrige result.json sumando el usage de TODOS los turnos de la
trayectoria (en vez de quedarse solo con el ultimo), segun documenta
cua-agent en su pagina de Usage Tracking:
https://cua.ai/agent-sdk/usage-tracking

Corrige: metrics.input_tokens, metrics.output_tokens,
metrics.total_tokens, metrics.response_cost.
No toca: status, error, duration_seconds, results[], metadata.json,
agent.log, screenshots/.

Requiere un backup previo de --results-dir (este script no lo hace):

    cd ~/cua-javafx-test/results
    mkdir -p old
    find . -maxdepth 1 -mindepth 1 -type d ! -name old -exec cp -r {} old/ \;

Es idempotente: la correccion siempre se recalcula desde results[]
(que no se modifica), asi que ejecutarlo varias veces da el mismo
resultado.

Uso:
    python fix_results_inplace.py --results-dir ~/cua-javafx-test/results
    python fix_results_inplace.py --results-dir ~/cua-javafx-test/results --dry-run
    python fix_results_inplace.py --results-dir ~/cua-javafx-test/results --csv resumen.csv
"""

import argparse
import csv
import json
from pathlib import Path


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def extract_usages(result_entries):
    """Usage dicts validos (total_tokens > 0) de results[]; ignora turnos sin llamada al modelo."""
    usages = []
    for entry in result_entries:
        usage = entry.get("usage")
        if isinstance(usage, dict) and usage.get("total_tokens", 0) > 0:
            usages.append(usage)
    return usages


def sum_usages(usages):
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "response_cost": 0.0}
    for u in usages:
        totals["input_tokens"] += u.get("input_tokens", 0)
        totals["output_tokens"] += u.get("output_tokens", 0)
        totals["total_tokens"] += u.get("total_tokens", 0)
        totals["response_cost"] += u.get("response_cost", 0.0)
    return totals


def fix_one(result_path: Path, dry_run: bool):
    data = load_json(result_path)

    usages = extract_usages(data.get("results", []))
    corrected = sum_usages(usages)
    old_metrics = dict(data.get("metrics", {}))

    if not dry_run:
        data["metrics"]["input_tokens"] = corrected["input_tokens"]
        data["metrics"]["output_tokens"] = corrected["output_tokens"]
        data["metrics"]["total_tokens"] = corrected["total_tokens"]
        data["metrics"]["response_cost"] = corrected["response_cost"]

        write_json(result_path, data)

    old_cost = old_metrics.get("response_cost", 0.0) or 0.0
    new_cost = corrected["response_cost"]
    factor = (new_cost / old_cost) if old_cost else float("nan")

    return {
        "run_id": data.get("run_id", result_path.parent.name),
        "status": data.get("status"),
        "skipped": False,
        "n_turns_with_usage": len(usages),
        "old_cost": old_cost,
        "new_cost": new_cost,
        "factor": factor,
        "old_total_tokens": old_metrics.get("total_tokens", 0),
        "new_total_tokens": corrected["total_tokens"],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Corrige coste y tokens reales en result.json, in-place."
    )
    parser.add_argument(
        "--results-dir",
        required=True,
        help="Directorio con las carpetas de ejecucion (cada una con su result.json).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo muestra lo que cambiaria, sin escribir nada en disco.",
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="Ruta opcional donde guardar el resumen en CSV.",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    result_files = sorted(results_dir.glob("*/result.json"))

    if not result_files:
        print(f"No se encontraron result.json bajo: {results_dir}")
        return

    rows = []
    for path in result_files:
        try:
            row = fix_one(path, dry_run=args.dry_run)
        except Exception as exc:
            row = {
                "run_id": path.parent.name,
                "status": "N/A",
                "skipped": True,
                "reason": f"ERROR procesando: {type(exc).__name__}: {exc}",
            }
        rows.append(row)

    print("=" * 100)
    print(f"{'run_id':50s} {'status':7s} {'turnos':7s} {'coste_ant':>10s} {'coste_real':>10s} {'factor':>8s}")
    print("=" * 100)

    total_old_cost = 0.0
    total_new_cost = 0.0

    for r in rows:
        if r.get("skipped"):
            print(f"{r['run_id']:50s} {'-':7s} (omitido: {r.get('reason', '')})")
            continue

        total_old_cost += r["old_cost"]
        total_new_cost += r["new_cost"]

        factor_str = f"{r['factor']:.1f}x" if r["factor"] == r["factor"] else "n/a"  # NaN check
        print(
            f"{r['run_id']:50s} {str(r['status']):7s} {r['n_turns_with_usage']:>7d} "
            f"${r['old_cost']:>9.4f} ${r['new_cost']:>9.4f} {factor_str:>8s}"
        )

    print("=" * 100)
    print(f"Coste total (segun campos originales, solo ultimo turno): ${total_old_cost:.4f}")
    print(f"Coste total real (suma de todos los turnos):               ${total_new_cost:.4f}")
    if args.dry_run:
        print("\n(--dry-run activo: no se ha escrito nada en disco)")
    else:
        print("\nSe han corregido los result.json in-place.")
        print("Recuerda que el backup completo debe existir ya en otra carpeta (p.ej. results/old/).")

    if args.csv:
        fieldnames = [
            "run_id", "status", "skipped", "n_turns_with_usage",
            "old_cost", "new_cost", "factor", "old_total_tokens", "new_total_tokens",
        ]
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in rows:
                writer.writerow({k: r.get(k, "") for k in fieldnames})
        print(f"\nResumen guardado en: {args.csv}")


if __name__ == "__main__":
    main()
