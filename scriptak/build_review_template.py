"""
build_review_template.py

Genera una plantilla CSV para revisar a mano (viendo el video de cada
ejecucion) las que terminaron en ERROR por probable agotamiento de
presupuesto (likely_budget_exhausted == True en dataset.csv), y marcar
si el objetivo se completo realmente aunque el agente no emitiera
TEST_RESULT. Los ERROR tempranos (likely_budget_exhausted == False) no
se revisan: son fallos tecnicos sin ambiguedad sobre si se completo
la tarea.

No modifica dataset.csv ni result.json: escribe un CSV nuevo, separado,
que luego se cruza con el dataset original en build_final_dataset.py.

Uso:
    python build_review_template.py \
        --dataset dataset.csv \
        --test-cases-dir ~/cua-javafx-test/test_cases \
        --out review_template.csv

Formato esperado de <TEST_ID>.json (mismo que usa run_test.py):
    {
        "id": "TC03",
        "name": "...",
        "success_criteria": ["...", "..."]
    }
"""

import argparse
import csv
import json
from pathlib import Path


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_success_criteria(test_cases_dir: Path, test_id: str, cache: dict):
    if test_id in cache:
        return cache[test_id]

    path = test_cases_dir / f"{test_id}.json"
    if not path.exists():
        cache[test_id] = []
        return []

    try:
        data = load_json(path)
    except Exception:
        cache[test_id] = []
        return []

    criteria = data.get("success_criteria", []) or []
    cache[test_id] = criteria
    return criteria


def main():
    parser = argparse.ArgumentParser(
        description="Genera plantilla CSV para revision manual de ERROR por budget agotado."
    )
    parser.add_argument("--dataset", required=True, help="Ruta a dataset.csv (de build_dataset.py).")
    parser.add_argument("--test-cases-dir", required=True, help="Directorio con los TC0X.json.")
    parser.add_argument("--out", default="review_template.csv", help="CSV de salida.")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    test_cases_dir = Path(args.test_cases_dir).expanduser()

    with open(dataset_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    to_review = [
        r for r in rows
        if r.get("status") == "ERROR" and r.get("likely_budget_exhausted") in ("True", "1", "true")
    ]

    if not to_review:
        print("No hay ejecuciones marcadas como likely_budget_exhausted en el dataset. Nada que revisar.")
        return

    criteria_cache = {}
    max_criteria = 0
    enriched = []

    for row in to_review:
        criteria = load_success_criteria(test_cases_dir, row["test_case"], criteria_cache)
        max_criteria = max(max_criteria, len(criteria))
        enriched.append((row, criteria))

    criterion_cols = [f"criterion_{i+1}_met" for i in range(max_criteria)]
    criterion_text_cols = [f"criterion_{i+1}_text" for i in range(max_criteria)]

    fieldnames = (
        ["run_id", "application", "model", "test_case", "repetition",
         "response_cost", "trajectory_budget", "budget_utilization"]
        + sum(([t, c] for t, c in zip(criterion_text_cols, criterion_cols)), [])
        + ["manual_status", "evidence_note", "reviewed_at"]
    )

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row, criteria in enriched:
            out_row = {
                "run_id": row["run_id"],
                "application": row["application"],
                "model": row["model"],
                "test_case": row["test_case"],
                "repetition": row["repetition"],
                "response_cost": row["response_cost"],
                "trajectory_budget": row["trajectory_budget"],
                "budget_utilization": row["budget_utilization"],
                "manual_status": "",       # PASS_MANUAL / PARTIAL_SUCCESS / PARTIAL_INCOMPLETE / FAIL_CONFIRMED
                "evidence_note": "",       # minuto del video / captura que lo evidencia
                "reviewed_at": "",         # fecha de revision
            }
            for i in range(max_criteria):
                if i < len(criteria):
                    out_row[f"criterion_{i+1}_text"] = criteria[i]
                    out_row[f"criterion_{i+1}_met"] = ""  # YES / NO / UNCLEAR
                else:
                    out_row[f"criterion_{i+1}_text"] = ""
                    out_row[f"criterion_{i+1}_met"] = ""
            writer.writerow(out_row)

    print(f"{len(to_review)} ejecuciones para revisar (de {len(rows)} totales en el dataset).")
    print(f"Plantilla escrita en: {args.out}")
    print(f"Numero maximo de criterios encontrados en un test case: {max_criteria}")
    print("\nRellena manualmente, viendo cada video:")
    print("  - criterion_N_met: YES / NO / UNCLEAR, para cada criterio de ese test case")
    print("  - manual_status: PASS_MANUAL / PARTIAL_SUCCESS / PARTIAL_INCOMPLETE / FAIL_CONFIRMED")
    print("  - evidence_note: minuto del video o captura que lo justifica")
    print("  - reviewed_at: fecha en que hiciste la revision")


if __name__ == "__main__":
    main()
