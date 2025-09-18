from __future__ import annotations
from typing import List, Dict, Any

DEFAULT_FORMATS = {
    "memory": "({host}) SN: {serial_number} | Model: {model} | DIMM Model: {dimm_models} | RAM Size: {total_ram_gib} GiB",
    "raid":   "({host}) RAID Controllers: {raid_controllers} | Volumes: {raid_volumes} | Drives: {raid_drives}",
    "health": "({host}) Health: {system_health} | State: {system_state}",
    "cpu": "({host}) SN: {serial_number} | Model: {model} | CPU Model: {cpu_model} | Total Cores: {total_cores}",
    "all": "({host}) SN: {serial_number} | Model: {model} | CPU Model: {cpu_model} | "
           "Total Cores: {total_cores} | DIMM Model: {dimm_models} | RAM Size: {total_ram_gib} GiB",
}

class _Safe(dict):
    def __missing__(self, key):  # пустая строка для отсутствующих полей
        return ""

def _ctx_cpu(result: dict) -> dict:
    cpu_node = result["summary"]["cpu"] if "summary" in result else result

    cpu_models = cpu_node.get("cpu_models")  # может быть str, list или None
    first_cpu_model = None

    if isinstance(cpu_models, str) and cpu_models.strip():
        first_cpu_model = cpu_models.split(",")[0].strip()
    elif isinstance(cpu_models, list) and cpu_models:
        # если вдруг парсер вернул список — нормализуем
        first_cpu_model = str(cpu_models[0]).strip()
        cpu_models = ", ".join(str(model).strip() for model in cpu_models if str(model).strip())
    else:
        cpu_models = None

    return {
        "host": result.get("host"),
        "serial_number": cpu_node.get("serial_number"),
        "model": cpu_node.get("model"),
        "cpu_model": first_cpu_model,   # ← одиночная модель (первая)
        "cpu_models": cpu_models,       # ← все модели через запятую (как раньше)
        "total_cores": cpu_node.get("total_cores"),
    }


def _ctx_memory(result: dict) -> dict:
    memory_node = result["summary"]["memory"] if "summary" in result else result
    host = result.get("host")
    serial = memory_node.get("serial_number")
    model = memory_node.get("model")
    systems = memory_node.get("memory", [])
    dimm_models = set()
    total_mib = 0
    for memory_system in systems:
        if memory_system.get("total_physical_mb"):
            total_mib = memory_system["total_physical_mb"]  # summary точнее и перекрывает сумму
        for module in memory_system.get("modules", []):
            part_number = module.get("part_number") or module.get("name") or ""
            if part_number:
                dimm_models.add(part_number)
            if not memory_system.get("total_physical_mb"):
                total_mib += module.get("capacity_mib") or 0
    return {
        "host": host,
        "serial_number": serial,
        "model": model,
        "dimm_models": ", ".join(sorted(dimm_models)) if dimm_models else None,
        "total_ram_gib": round(total_mib / 1024, 1) if total_mib else None,
    }

def _ctx_raid(result: dict) -> dict:
    raid_node = result["summary"]["raid"] if "summary" in result else result
    systems = raid_node.get("systems", [])
    controller_count = volume_count = drive_count = 0
    for system in systems:
        for raid_controller in system.get("raid", []) or []:
            controller_count += 1
            volume_count += len(raid_controller.get("volumes", []) or [])
            drive_count += len(raid_controller.get("drives", []) or [])
    return {"host": result.get("host"), "raid_controllers": controller_count, "raid_volumes": volume_count, "raid_drives": drive_count}

def _ctx_health(result: dict) -> dict:
    health_node = result["summary"]["health"] if "summary" in result else result
    systems_health = health_node.get("systems_health", [])
    first_health = systems_health[0] if systems_health else {}
    return {"host": result.get("host"), "system_health": first_health.get("health"), "system_state": first_health.get("state")}

def _ctx_all(result: dict) -> dict:
    context = {}
    context.update(_ctx_cpu(result))
    context.update(_ctx_memory(result))
    return context

_CTX_BY_MODE = {"cpu": _ctx_cpu, "memory": _ctx_memory, "raid": _ctx_raid, "health": _ctx_health, "all": _ctx_all}

def print_summary(results: List[Dict[str, Any]], mode: str, fmt: str | None = None) -> None:
    successful_results = [result for result in results if result.get("ok")]
    failed_results = [result for result in results if not result.get("ok")]
    print(f"OK: {len(successful_results)} | FAIL: {len(failed_results)}")
    template = fmt or DEFAULT_FORMATS[mode]
    context_function = _CTX_BY_MODE[mode]
    for result in successful_results:
        print(template.format_map(_Safe(context_function(result))))
    for result in failed_results:
        print(f"({result.get('host')}) ERROR: {result.get('error')}")
