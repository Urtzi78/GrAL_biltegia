"""
run_all.py

Ejecuta TC01-TC06 de forma interactiva para una app/modelo dados,
pausando antes de cada ejecucion para preparar la app segun las
precondiciones del caso de prueba, y delegando cada ejecucion en
run_test.py.

Uso:
    python run_all.py --app javafx --model claude-haiku-4-5
    python run_all.py --app avalonia --model claude-sonnet-4-5 --start-test TC03
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_CASES_DIR = PROJECT_ROOT / "test_cases"
RUN_TEST = PROJECT_ROOT / "runners" / "trycua" / "run_test.py"


def load_test_case(test_id):
    path = TEST_CASES_DIR / f"{test_id}.json"

    if not path.exists():
        raise FileNotFoundError(f"Test case not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def wait_for_user(test_case, model, repetition):
    """Pause so the application can be prepared according to the test case preconditions."""

    print()
    print("=" * 70)
    print(f"{test_case['id']} | {test_case['name']}")
    print(f"Model       : {model}")
    print(f"Repetition  : {repetition}")
    print("=" * 70)

    print("\nPreconditions:")

    for precondition in test_case.get("preconditions", []):
        print(f"  - {precondition}")

    print()
    print("Prepare the application according to these preconditions.")
    input("Press ENTER when the application is ready...")


def run_test(app, model, test_id):
    """Execute one test case using run_test.py."""

    command = [
        sys.executable,
        str(RUN_TEST),
        "--app",
        app,
        "--model",
        model,
        "--test",
        test_id,
    ]

    print()
    print("Starting test execution...")
    print()

    result = subprocess.run(command)

    return result.returncode


def main():
    parser = argparse.ArgumentParser(
        description="Run GUI test cases interactively."
    )

    parser.add_argument(
        "--app",
        required=True,
        help="Application ID, e.g. javafx",
    )

    parser.add_argument(
        "--model",
        required=True,
        help="Model ID, e.g. claude-haiku-4-5",
    )

    parser.add_argument(
        "--repetitions",
        type=int,
        default=3,
        help="Number of repetitions per test case (default: 3)",
    )

    parser.add_argument(
        "--start-test",
        default="TC01",
        help="Test case from which to start, e.g. TC03",
    )

    args = parser.parse_args()

    test_ids = [
        "TC01",
        "TC02",
        "TC03",
        "TC04",
        "TC05",
        "TC06",
    ]

    start_index = test_ids.index(args.start_test)
    test_ids = test_ids[start_index:]

    print("=" * 70)
    print("GUI TEST EXPERIMENT")
    print("=" * 70)
    print(f"Application : {args.app}")
    print(f"Model       : {args.model}")
    print(f"Test cases  : {len(test_ids)}")
    print(f"Repetitions : {args.repetitions}")
    print(f"Executions  : {len(test_ids) * args.repetitions}")
    print("=" * 70)

    for test_id in test_ids:

        test_case = load_test_case(test_id)

        for repetition in range(1, args.repetitions + 1):

            wait_for_user(
                test_case,
                args.model,
                repetition,
            )

            return_code = run_test(
                args.app,
                args.model,
                test_id,
            )

            if return_code != 0:
                print()
                print(
                    f"WARNING: {test_id} repetition "
                    f"{repetition} exited with code {return_code}."
                )

            print()
            print("=" * 70)
            print(
                f"Finished: {test_id} "
                f"| repetition {repetition}/{args.repetitions}"
            )
            print("=" * 70)

            print()
            choice = input(
                "Press ENTER to continue, or Q to stop the experiment: "
            ).strip().lower()

            if choice == "q":
                print("\nExperiment aborted by user.")
                return

    print()
    print("=" * 70)
    print("EXPERIMENT FINISHED")
    print("=" * 70)


if __name__ == "__main__":
    main()
