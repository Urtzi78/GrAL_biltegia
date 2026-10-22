"""
run_test.py

Ejecuta un caso de prueba (TC01-TC06) sobre una aplicacion con un agente
Computer Use (cua-agent), y guarda metadata.json, result.json, agent.log
y las capturas de pantalla de la trayectoria en results/<run_id>/.

Uso:
    python run_test.py --app javafx --model claude-haiku-4-5 --test TC01
    python run_test.py --app avalonia --model claude-sonnet-4-5 --test TC03 --dry-run
"""

import argparse
import asyncio
import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CONFIG_DIR = PROJECT_ROOT / "config"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
TEST_CASES_DIR = PROJECT_ROOT / "test_cases"
RESULTS_DIR = PROJECT_ROOT / "results"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_test_case(test_id):
    path = TEST_CASES_DIR / f"{test_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Test case not found: {path}")
    return load_json(path)


def load_prompt_template():
    path = PROMPTS_DIR / "gui_agent.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


def format_list(values):
    if not values:
        return "None"
    return "\n".join(f"- {value}" for value in values)


def format_test_data(data):
    if not data:
        return "None"
    return json.dumps(data, indent=2, ensure_ascii=False)


def build_prompt(template, test_case):
    return template.format(
        test_case=f"{test_case['id']} — {test_case['name']}",
        description=test_case["description"],
        preconditions=format_list(test_case["preconditions"]),
        test_data=format_test_data(test_case["test_data"]),
        goal=test_case["goal"],
        success_criteria=format_list(test_case["success_criteria"]),
    )


def parse_args():
    parser = argparse.ArgumentParser(description="Run a GUI test case with Computer Use.")
    parser.add_argument("--app", required=True, help="Application identifier from config/apps.json.")
    parser.add_argument("--model", required=True, help="Model identifier from config/models.json.")
    parser.add_argument("--test", required=True, help="Test case identifier, e.g. TC01.")
    parser.add_argument("--dry-run", action="store_true", help="Build and display the prompt without executing the agent.")
    return parser.parse_args()


def create_run_directory(test_id, app_id, model_id):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"{timestamp}_{test_id}_{app_id}_{model_id}"
    run_dir = RESULTS_DIR / run_id
    screenshots_dir = run_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=False)
    return run_id, run_dir, screenshots_dir


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def extract_screenshot(result, screenshots_dir, screenshot_number):
    """Save a base64 PNG from a computer_call_output, if present, and point image_url to the local file."""
    try:
        outputs = result.get("output", [])
        for item in outputs:
            if item.get("type") != "computer_call_output":
                continue
            output = item.get("output", {})
            if output.get("type") != "input_image":
                continue

            image_url = output.get("image_url", "")
            prefix = "data:image/png;base64,"
            if not image_url.startswith(prefix):
                continue

            image_data = image_url[len(prefix):]
            image_path = screenshots_dir / f"{screenshot_number:03d}.png"
            with open(image_path, "wb") as f:
                f.write(base64.b64decode(image_data))

            output["image_url"] = str(Path("screenshots") / image_path.name)
            return True

    except Exception as exc:
        print(f"Warning: could not save screenshot: {exc}")

    return False


def extract_text(result):
    """Concatenate all assistant output_text blocks from a ComputerAgent result."""
    texts = []
    for item in result.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                text = content.get("text", "")
                if text:
                    texts.append(text)
    return "\n".join(texts)


def extract_final_status(text):
    if "TEST_RESULT: PASS" in text:
        return "PASS"
    if "TEST_RESULT: FAIL" in text:
        return "FAIL"
    return None


def sum_usage(usages):
    """
    Suma el usage de cada turno en los totales de la trayectoria. Cada
    `usage` refleja solo esa llamada individual, no un acumulado (ver
    cua-agent Usage Tracking docs: https://cua.ai/agent-sdk/usage-tracking).
    """
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "response_cost": 0.0}
    for usage in usages:
        totals["input_tokens"] += usage.get("input_tokens", 0)
        totals["output_tokens"] += usage.get("output_tokens", 0)
        totals["total_tokens"] += usage.get("total_tokens", 0)
        totals["response_cost"] += usage.get("response_cost", 0.0)
    return totals


async def main():
    args = parse_args()

    apps = load_json(CONFIG_DIR / "apps.json")
    models = load_json(CONFIG_DIR / "models.json")

    if args.app not in apps:
        raise ValueError(f"Unknown application '{args.app}'. Available: {', '.join(apps.keys())}")
    if args.model not in models:
        raise ValueError(f"Unknown model '{args.model}'. Available: {', '.join(models.keys())}")

    app_config = apps[args.app]
    model_config = models[args.model]

    test_case = load_test_case(args.test)
    prompt_template = load_prompt_template()
    prompt = build_prompt(prompt_template, test_case)

    print("=" * 70)
    print("GUI TEST RUN")
    print("=" * 70)
    print(f"Application : {app_config['name']}")
    print(f"App ID      : {args.app}")
    print(f"Model       : {model_config['name']}")
    print(f"Model ID    : {args.model}")
    print(f"Test case   : {test_case['id']}")
    print(f"Test name   : {test_case['name']}")
    print("=" * 70)

    print("\nPrompt:")
    print("-" * 70)
    print(prompt)
    print("-" * 70)

    if args.dry_run:
        print("\n✓ Dry run completed. No Computer Use execution performed.")
        return

    run_id, run_dir, screenshots_dir = create_run_directory(args.test, args.app, args.model)
    print(f"\nRun ID: {run_id}")
    print(f"Results: {run_dir}")

    # Presupuesto por trayectoria: segun modelo, con mayor margen en
    # TC03/TC06 (mas largos). Ver capitulo 7.4.2 de la memoria.
    if args.model == "claude-haiku-4-5":
        budget = 0.30 if args.test in ("TC03", "TC06") else 0.20
    elif args.model == "claude-sonnet-4-5":
        budget = 0.50 if args.test in ("TC03", "TC06") else 0.30
    else:
        raise ValueError(f"No budget configured for model '{args.model}'")

    start_time = datetime.now(timezone.utc)

    metadata = {
        "run_id": run_id,
        "timestamp": start_time.isoformat(),
        "test_case": args.test,
        "application": args.app,
        "application_name": app_config["name"],
        "model": args.model,
        "model_name": model_config["name"],
        "provider": model_config["provider"],
        "trajectory_budget": budget,
    }
    write_json(run_dir / "metadata.json", metadata)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set.")

    from computer import Computer
    from cua_agent import ComputerAgent

    results = []
    screenshot_number = 0
    all_agent_text = []
    all_usages = []  # usage de cada turno; se suma al final (ver sum_usage)
    action_count = 0
    error_info = None

    log_path = run_dir / "agent.log"

    with open(log_path, "w", encoding="utf-8") as log:
        async with Computer(
            os_type="linux",
            use_host_computer_server=True,
            api_port=8000,
            host="localhost",
        ) as computer:

            agent = ComputerAgent(
                model=model_config["model"],
                tools=[computer],
                api_key=api_key,
                max_trajectory_budget=budget,
            )

            print(f"Budget       : ${budget:.2f}")
            log.write(f"Budget: ${budget:.2f}\n")

            print("\n▶ Starting test...\n")
            log.write("Starting test...\n\n")

            try:
                async for result in agent.run(prompt):
                    print(result)

                    text = extract_text(result)
                    if text:
                        all_agent_text.append(text)

                    usage = result.get("usage")
                    if isinstance(usage, dict) and usage.get("total_tokens", 0) > 0:
                        all_usages.append(usage)

                    for item in result.get("output", []):
                        if item.get("type") == "computer_call":
                            action_count += 1

                    log.write(json.dumps(result, indent=2, ensure_ascii=False, default=str))
                    log.write("\n\n")

                    result_copy = json.loads(json.dumps(result, default=str))
                    if extract_screenshot(result_copy, screenshots_dir, screenshot_number + 1):
                        screenshot_number += 1

                    results.append(result_copy)

            except Exception as e:
                error_info = {"type": type(e).__name__, "message": str(e)}
                print(f"\nERROR: {type(e).__name__}: {e}")

    end_time = datetime.now(timezone.utc)

    final_text = "\n".join(all_agent_text)
    status = extract_final_status(final_text)
    if status is None:
        status = "ERROR"

    if status == "ERROR" and error_info is None:
        error_info = {
            "type": "missing_test_result",
            "message": "The agent finished without providing TEST_RESULT: PASS or TEST_RESULT: FAIL.",
        }

    usage_totals = sum_usage(all_usages)

    metrics = {
        "input_tokens": usage_totals["input_tokens"],
        "output_tokens": usage_totals["output_tokens"],
        "total_tokens": usage_totals["total_tokens"],
        "response_cost": usage_totals["response_cost"],
        "actions": action_count,
        "screenshots": screenshot_number,
    }

    duration_seconds = (end_time - start_time).total_seconds()

    result_data = {
        "run_id": run_id,
        "status": status,
        "error": error_info,
        "metrics": metrics,
        "duration_seconds": duration_seconds,
        "started_at": start_time.isoformat(),
        "finished_at": end_time.isoformat(),
        "results": results,
    }
    write_json(run_dir / "result.json", result_data)

    print(f"\n✓ Test execution finished: {status}")
    print(f"  Actions:    {action_count}")
    print(f"  Screenshots: {screenshot_number}")

    if all_usages:
        print(f"  Input tokens:  {usage_totals['input_tokens']}")
        print(f"  Output tokens: {usage_totals['output_tokens']}")
        print(f"  Total tokens:  {usage_totals['total_tokens']}")
        print(f"  Cost:          ${usage_totals['response_cost']:.5f}")

    print(f"\n✓ Results saved to: {run_dir}")


if __name__ == "__main__":
    asyncio.run(main())
