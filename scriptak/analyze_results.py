"""
analyze_results.py

Genera tablas resumen (CSV) y graficos (PNG) a partir de
final_dataset.csv.

Decisiones metodologicas:
    - Se excluyen las filas con excluded_from_comparison == True
      (defectos confirmados de la aplicacion bajo prueba) de todos los
      analisis, incluidos coste y duracion: si la tarea era
      objetivamente irrealizable, tampoco es representativo medir
      cuanto gasto el agente intentandola.
    - "Exito" = is_success_strict (PASS, PASS_MANUAL, PARTIAL_SUCCESS).
    - cost_per_action (no response_cost bruto) se usa para comparar
      coste entre modelos, para no confundir presupuesto asignado
      (distinto entre Haiku y Sonnet) con coste real de operar el modelo.

Todo el texto de tablas/graficos de salida esta en TEXTS_EU, debajo de
este docstring; para corregir una traduccion solo hay que editar ese
diccionario.

Salidas (en --out-dir):
    summary_by_model.csv, summary_by_application.csv,
    summary_by_model_application.csv, summary_by_test_case.csv,
    summary_by_outcome.csv, final_status_distribution.csv,
    success_rate_by_model_app.png, success_rate_by_testcase.png,
    cost_per_action_boxplot_by_model.png,
    response_cost_boxplot_by_model.png, duration_boxplot_by_model.png,
    actions_vs_cost_by_outcome.png

Uso:
    python analyze_results.py --dataset final_dataset.csv --out-dir analysis_output
"""

import argparse
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # sin pantalla, solo generar ficheros
import matplotlib.pyplot as plt
import pandas as pd

TEXTS_EU = {
    "columns": {
        "application": "Aplikazioa",
        "model": "Eredua",
        "test_case": "Proba kasua",
        "final_status": "Azken egoera",
        "n": "N",
        "success_rate": "Arrakasta-tasa (%)",
        "median_response_cost": "Kostuaren mediana (USD)",
        "median_cost_per_action": "Ekintzako kostuaren mediana (USD)",
        "median_duration_seconds": "Iraupenaren mediana (s)",
        "mean_actions": "Ekintza kop. batez bestekoa",
        "median_actions": "Ekintza kop. mediana",
        "mean_cost_per_action": "Ekintzako kostuaren batez bestekoa (USD)",
        "mean_duration_seconds": "Iraupenaren batez bestekoa (s)",
        "n_redundant_retry": "Saiakera erredundante kop.",
        "n_budget_exhausted": "Aurrekontua agortutako kop.",
    },

    "status_values": {
        "PASS": "Arrakasta",
        "PASS_MANUAL": "Eskuz baieztatutako arrakasta",
        "PARTIAL_SUCCESS": "Arrakasta partziala",
        "PARTIAL_INCOMPLETE": "Osatu gabea",
        "FAIL_CONFIRMED": "Hutsegitea baieztatua",
        "FAIL": "Hutsegitea",
        "ERROR": "Errorea",
    },

    "plots": {
        "success_by_model_app_title": "Arrakasta-tasa aplikazio eta ereduaren arabera",
        "success_ylabel": "Arrakasta-tasa (%)",
        "application_xlabel": "Aplikazioa",
        "model_legend_title": "Eredua",

        "success_by_testcase_title": "Arrakasta-tasa proba kasuaren eta ereduaren arabera (javafx + avalonia batuta)",
        "test_case_xlabel": "Proba kasua",

        "cost_per_action_title": "Ekintzako kostua ereduaren arabera (konparazio normalizatua)",
        "cost_per_action_ylabel": "Ekintzako kostua (USD)",

        "response_cost_title": "Kostu osoa ereduaren arabera (aurrekontuaren arabera normalizatu gabe)",
        "response_cost_ylabel": "Trajektoriaren kostu osoa (USD)",

        "duration_title": "Exekuzioaren iraupena ereduaren arabera",
        "duration_ylabel": "Iraupena (segundo)",

        "scatter_title": "Ekintzak vs ekintzako kostua, emaitzaren arabera koloreztatuta",
        "actions_xlabel": "Trajektorian egindako ekintza kopurua",
        "scatter_cost_ylabel": "Ekintzako kostua (USD)",
        "legend_success": "arrakasta",
        "legend_no_success": "arrakastarik gabe",
    },
}


def translate_for_export(df: pd.DataFrame) -> pd.DataFrame:
    """Devuelve una copia del DataFrame con cabeceras y final_status traducidos segun TEXTS_EU."""
    out = df.copy()
    if "final_status" in out.columns:
        out["final_status"] = out["final_status"].map(TEXTS_EU["status_values"]).fillna(out["final_status"])
    return out.rename(columns=TEXTS_EU["columns"])


def load_dataset(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)

    bool_cols = [
        "likely_budget_exhausted", "reviewed", "is_success_strict",
        "is_success_lenient", "excluded_from_comparison",
        "redundant_retry_after_completion",
    ]
    for col in bool_cols:
        if col in df.columns and df[col].dtype != bool:
            df[col] = df[col].astype(str).str.strip().str.lower().isin(["true", "1"])

    return df


def summarize(df: pd.DataFrame, group_cols):
    grouped = df.groupby(group_cols)
    summary = grouped.agg(
        n=("run_id", "count"),
        success_rate=("is_success_strict", "mean"),
        median_response_cost=("response_cost", "median"),
        median_cost_per_action=("cost_per_action", "median"),
        median_duration_seconds=("duration_seconds", "median"),
        mean_actions=("actions", "mean"),
        n_redundant_retry=("redundant_retry_after_completion", "sum"),
        n_budget_exhausted=("likely_budget_exhausted", "sum"),
    ).reset_index()

    summary["success_rate"] = (summary["success_rate"] * 100).round(1)
    for col in ["median_response_cost", "median_cost_per_action"]:
        summary[col] = summary[col].round(5)
    summary["median_duration_seconds"] = summary["median_duration_seconds"].round(1)
    summary["mean_actions"] = summary["mean_actions"].round(1)

    return summary


def summarize_by_outcome(df: pd.DataFrame) -> pd.DataFrame:
    """Acciones/coste/duracion agregados por final_status, para ver si los fallos se quedan cortos de acciones o no."""
    grouped = df.groupby("final_status")
    summary = grouped.agg(
        n=("run_id", "count"),
        mean_actions=("actions", "mean"),
        median_actions=("actions", "median"),
        mean_cost_per_action=("cost_per_action", "mean"),
        mean_duration_seconds=("duration_seconds", "mean"),
    ).reset_index()

    summary["mean_actions"] = summary["mean_actions"].round(1)
    summary["median_actions"] = summary["median_actions"].round(1)
    summary["mean_cost_per_action"] = summary["mean_cost_per_action"].round(5)
    summary["mean_duration_seconds"] = summary["mean_duration_seconds"].round(1)

    return summary.sort_values("n", ascending=False)


def plot_success_rate_by_model_app(df: pd.DataFrame, out_path: Path):
    texts = TEXTS_EU["plots"]
    pivot = df.groupby(["application", "model"])["is_success_strict"].mean().unstack() * 100

    fig, ax = plt.subplots(figsize=(7, 5))
    pivot.plot(kind="bar", ax=ax)
    ax.set_ylabel(texts["success_ylabel"])
    ax.set_xlabel(texts["application_xlabel"])
    ax.set_title(texts["success_by_model_app_title"])
    ax.set_ylim(0, 100)
    ax.legend(title=texts["model_legend_title"])
    ax.grid(axis="y", alpha=0.3)
    plt.xticks(rotation=0)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_success_rate_by_testcase(df: pd.DataFrame, out_path: Path):
    texts = TEXTS_EU["plots"]
    pivot = df.groupby(["test_case", "model"])["is_success_strict"].mean().unstack() * 100
    pivot = pivot.reindex(sorted(pivot.index))

    fig, ax = plt.subplots(figsize=(9, 5))
    pivot.plot(kind="bar", ax=ax)
    ax.set_ylabel(texts["success_ylabel"])
    ax.set_xlabel(texts["test_case_xlabel"])
    ax.set_title(texts["success_by_testcase_title"])
    ax.set_ylim(0, 100)
    ax.legend(title=texts["model_legend_title"])
    ax.grid(axis="y", alpha=0.3)
    plt.xticks(rotation=0)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_boxplot_by_model(df: pd.DataFrame, column: str, ylabel: str, title: str, out_path: Path):
    models = sorted(df["model"].unique())
    data = [df.loc[df["model"] == m, column].dropna().values for m in models]

    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.boxplot(data, tick_labels=models, showmeans=True)
    ax.set_ylabel(ylabel)
    ax.set_title(textwrap.fill(title, width=55))
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_actions_vs_cost_by_outcome(df: pd.DataFrame, out_path: Path):
    """Scatter por ejecucion: acciones vs coste/accion, color=exito, forma=modelo; muestra su relacion conjunta."""
    texts = TEXTS_EU["plots"]
    markers = {"claude-haiku-4-5": "o", "claude-sonnet-4-5": "^"}
    colors = {True: "#2ca02c", False: "#d62728"}  # berdea=arrakasta, gorria=arrakastarik ez

    fig, ax = plt.subplots(figsize=(8, 6))

    for model in sorted(df["model"].unique()):
        marker = markers.get(model, "o")
        for success in (True, False):
            sub = df[(df["model"] == model) & (df["is_success_strict"] == success)]
            if sub.empty:
                continue
            label_success = texts["legend_success"] if success else texts["legend_no_success"]
            ax.scatter(
                sub["actions"], sub["cost_per_action"],
                marker=marker, c=colors[success],
                alpha=0.75, edgecolors="black", linewidths=0.5,
                s=70,
                label=f"{model} - {label_success}",
            )

    ax.set_xlabel(texts["actions_xlabel"])
    ax.set_ylabel(texts["scatter_cost_ylabel"])
    ax.set_title(texts["scatter_title"])
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="best")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Agrega y visualiza final_dataset.csv (salida en euskera).")
    parser.add_argument("--dataset", required=True, help="Ruta a final_dataset.csv")
    parser.add_argument("--out-dir", default="analysis_output", help="Directorio de salida")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df_all = load_dataset(args.dataset)
    n_total = len(df_all)
    n_excluded = int(df_all["excluded_from_comparison"].sum())
    df = df_all[~df_all["excluded_from_comparison"]].copy()

    print(f"Filas totales: {n_total}  |  excluidas (defecto AUT): {n_excluded}  |  usadas en el analisis: {len(df)}")

    summary_model = summarize(df, ["model"])
    summary_app = summarize(df, ["application"])
    summary_model_app = summarize(df, ["application", "model"])
    summary_testcase = summarize(df, ["test_case", "application", "model"]).sort_values(["test_case", "application", "model"])
    summary_outcome = summarize_by_outcome(df)

    summary_model.pipe(translate_for_export).to_csv(out_dir / "summary_by_model.csv", index=False)
    summary_app.pipe(translate_for_export).to_csv(out_dir / "summary_by_application.csv", index=False)
    summary_model_app.pipe(translate_for_export).to_csv(out_dir / "summary_by_model_application.csv", index=False)
    summary_testcase.pipe(translate_for_export).to_csv(out_dir / "summary_by_test_case.csv", index=False)
    summary_outcome.pipe(translate_for_export).to_csv(out_dir / "summary_by_outcome.csv", index=False)

    dist = pd.crosstab([df["application"], df["model"]], df["final_status"])
    dist = dist.rename(columns=TEXTS_EU["status_values"])
    dist.index = dist.index.set_names([
        TEXTS_EU["columns"].get(name, name) for name in dist.index.names
    ])
    dist.to_csv(out_dir / "final_status_distribution.csv")

    plot_success_rate_by_model_app(df, out_dir / "success_rate_by_model_app.png")
    plot_success_rate_by_testcase(df, out_dir / "success_rate_by_testcase.png")
    plot_boxplot_by_model(
        df, "cost_per_action",
        TEXTS_EU["plots"]["cost_per_action_ylabel"],
        TEXTS_EU["plots"]["cost_per_action_title"],
        out_dir / "cost_per_action_boxplot_by_model.png",
    )
    plot_boxplot_by_model(
        df, "response_cost",
        TEXTS_EU["plots"]["response_cost_ylabel"],
        TEXTS_EU["plots"]["response_cost_title"],
        out_dir / "response_cost_boxplot_by_model.png",
    )
    plot_boxplot_by_model(
        df, "duration_seconds",
        TEXTS_EU["plots"]["duration_ylabel"],
        TEXTS_EU["plots"]["duration_title"],
        out_dir / "duration_boxplot_by_model.png",
    )
    plot_actions_vs_cost_by_outcome(df, out_dir / "actions_vs_cost_by_outcome.png")

    print("\n=== Resumen por modelo ===")
    print(summary_model.to_string(index=False))

    print("\n=== Resumen por aplicacion ===")
    print(summary_app.to_string(index=False))

    print("\n=== Resumen por aplicacion x modelo ===")
    print(summary_model_app.to_string(index=False))

    print("\n=== Resumen por resultado final (final_status) ===")
    print(summary_outcome.to_string(index=False))

    print(f"\nTablas y graficos (en euskera) escritos en: {out_dir}/")


if __name__ == "__main__":
    main()
