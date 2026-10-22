"""
build_final_dataset.py

Fusiona dataset.csv (todas las ejecuciones) con review_template.csv
(revision manual de los ERROR por probable agotamiento de presupuesto)
en un dataset final, preservando la trazabilidad entre el status
original del agente y el resultado determinado al revisar el video.

Columnas nuevas por fila:
    manual_status        -> vacio si no se reviso; si no, el valor puesto
                             a mano (PASS_MANUAL / PARTIAL_SUCCESS /
                             PARTIAL_INCOMPLETE / FAIL_CONFIRMED)
    reviewed              -> True/False
    final_status          -> status original si no hubo revision manual,
                              o el valor mapeado via MANUAL_STATUS_MAP si la hubo
    is_success_strict     -> True si final_status es PASS, PASS_MANUAL o
                              PARTIAL_SUCCESS
    is_success_lenient    -> igual que is_success_strict (ver nota mas abajo)
    excluded_from_comparison -> True si final_status esta en
                                 EXCLUDED_FROM_COMPARISON_STATUSES (finalmente
                                 se ha dejado vacio en este TFG: ninguna categoria
                                 se ha excluido de la comparacion en la practica)
    redundant_retry_after_completion -> True si final_status == PARTIAL_SUCCESS

No modifica dataset.csv ni review_template.csv: escribe un fichero nuevo.

Uso:
    python build_final_dataset.py \
        --dataset dataset.csv \
        --review review_template.csv \
        --out final_dataset.csv
"""

import argparse
import csv


MANUAL_STATUS_MAP = {
    "PASS_MANUAL": "PASS_MANUAL",
    "PARTIAL_SUCCESS": "PARTIAL_SUCCESS",
    "PARTIAL_INCOMPLETE": "PARTIAL_INCOMPLETE",
    "FAIL_CONFIRMED": "FAIL_CONFIRMED",
}

# PARTIAL_SUCCESS cuenta como exito en ambos criterios: los
# success_criteria se cumplieron, pero el agente no lo detecto y siguio
# reintentando hasta agotar presupuesto. El objetivo SI se logro; lo que
# falla es la auto-verificacion del agente, no la completitud, y se deja
# como etiqueta separada para el analisis cualitativo de ese comportamiento.
STRICT_SUCCESS_STATUSES = {"PASS", "PASS_MANUAL", "PARTIAL_SUCCESS"}
LENIENT_SUCCESS_STATUSES = STRICT_SUCCESS_STATUSES

# Categorias de final_status que se excluirian de toda tasa de exito/fallo
# (p.ej. un defecto confirmado de la app que hace la tarea irrealizable).
# Vacio: en este TFG ninguna ejecucion ha caido en ese caso.
EXCLUDED_FROM_COMPARISON_STATUSES = set()


def read_csv(path):
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    parser = argparse.ArgumentParser(
        description="Fusiona dataset.csv con review_template.csv en un dataset final."
    )
    parser.add_argument("--dataset", required=True, help="Ruta a dataset.csv")
    parser.add_argument("--review", required=True, help="Ruta a review_template.csv (ya relleno)")
    parser.add_argument("--out", default="final_dataset.csv", help="CSV de salida")
    args = parser.parse_args()

    dataset_rows = read_csv(args.dataset)
    review_rows = read_csv(args.review)

    review_by_run_id = {r["run_id"]: r for r in review_rows}

    unfilled = []
    unknown_status = []
    final_rows = []

    # Cabeceras originales, capturadas antes de anadir columnas nuevas
    # (dataset_rows[0] es el mismo dict que se muta en el bucle).
    original_fieldnames = list(dataset_rows[0].keys()) if dataset_rows else []

    for row in dataset_rows:
        run_id = row["run_id"]
        review = review_by_run_id.get(run_id)

        if review is None:
            row["manual_status"] = ""
            row["reviewed"] = False
            row["final_status"] = row["status"]
        else:
            manual_status = (review.get("manual_status") or "").strip()

            if not manual_status:
                unfilled.append(run_id)
                row["manual_status"] = ""
                row["reviewed"] = False
                row["final_status"] = row["status"]  # de momento, sin resolver
            elif manual_status not in MANUAL_STATUS_MAP:
                unknown_status.append((run_id, manual_status))
                row["manual_status"] = manual_status
                row["reviewed"] = True
                row["final_status"] = row["status"]  # no se reconoce, no se sobreescribe
            else:
                row["manual_status"] = manual_status
                row["reviewed"] = True
                row["final_status"] = MANUAL_STATUS_MAP[manual_status]

        row["is_success_strict"] = row["final_status"] in STRICT_SUCCESS_STATUSES
        row["is_success_lenient"] = row["final_status"] in LENIENT_SUCCESS_STATUSES
        row["excluded_from_comparison"] = row["final_status"] in EXCLUDED_FROM_COMPARISON_STATUSES
        row["redundant_retry_after_completion"] = row["final_status"] == "PARTIAL_SUCCESS"

        final_rows.append(row)

    fieldnames = original_fieldnames + [
        "manual_status", "reviewed", "final_status",
        "is_success_strict", "is_success_lenient", "excluded_from_comparison",
        "redundant_retry_after_completion",
    ]

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in final_rows:
            writer.writerow(row)

    print(f"Dataset final escrito en: {args.out}")
    print(f"Total filas: {len(final_rows)}")
    print(f"Filas con revision manual aplicada: {sum(1 for r in final_rows if r['reviewed'])}")

    if unfilled:
        print(f"\n⚠ {len(unfilled)} filas en review_template.csv tienen manual_status VACIO todavia:")
        for run_id in unfilled:
            print(f"  - {run_id}")
        print("Estas se han dejado con su status original (ERROR) hasta que las rellenes.")

    if unknown_status:
        print(f"\n⚠ {len(unknown_status)} filas tienen un manual_status no reconocido "
              f"(revisa que no haya erratas, debe ser exactamente uno de: "
              f"{', '.join(MANUAL_STATUS_MAP.keys())}):")
        for run_id, value in unknown_status:
            print(f"  - {run_id}: '{value}'")

    n_total = len(final_rows)
    n_excluded = sum(1 for r in final_rows if r["excluded_from_comparison"])
    n_comparable = n_total - n_excluded

    strict = sum(1 for r in final_rows if r["is_success_strict"])
    lenient = sum(1 for r in final_rows if r["is_success_lenient"])

    print(f"\nTotal filas: {n_total}  |  excluidas por defecto de AUT: {n_excluded}  |  comparables: {n_comparable}")
    if n_comparable > 0:
        print(f"Tasa de exito (PASS / PASS_MANUAL / PARTIAL_SUCCESS):         {strict}/{n_comparable} = {strict/n_comparable:.1%}")
        if lenient != strict:
            print(f"Tasa de exito laxa (+ otras categorias):                      {lenient}/{n_comparable} = {lenient/n_comparable:.1%}")

    if n_excluded:
        print(f"\n⚠ {n_excluded} filas excluidas de las tasas de exito/fallo:")
        for r in final_rows:
            if r["excluded_from_comparison"]:
                print(f"  - {r['run_id']}")
        print("Estas ejecuciones se reportan aparte en la memoria (defecto de la app, no del agente),")
        print("no se cuentan ni como exito ni como fallo del modelo evaluado.")


if __name__ == "__main__":
    main()
