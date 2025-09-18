from __future__ import annotations
from typing import List, Dict, Any
from urllib.parse import urlparse
from rich.table import Table
from rich.console import Console
import socket

def _ip_from_base_url(base_url: str | None) -> str | None:
    try:
        netloc = urlparse(base_url or "").netloc
        return netloc.split(":")[0] if netloc else None
    except Exception:
        return None

def _first_cpu_model(cpu_models):
    if isinstance(cpu_models, str) and cpu_models.strip():
        return cpu_models.split(",")[0].strip()
    if isinstance(cpu_models, list) and cpu_models:
        return str(cpu_models[0]).strip()
    return None


def _reverse_dns(ip: str | None) -> str | None:
    if not ip:
        return None
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return None
    
def _bytes_to_gib(n: int | None) -> str:
    if not n:
        return ""
    return f"{n / (1024**3):.1f}"

# ---------- summarize_* строят «плоские» строки данных из результата ----------
def summarize_cpu_row(r: Dict[str, Any]) -> Dict[str, Any]:
    node = (r.get("summary") or {}).get("cpu") if "summary" in r else r
    ip = _ip_from_base_url(r.get("base_url"))
    fqdn = node.get("fqdn") or node.get("host_name") or _reverse_dns(ip)  # ← NEW
    return {
        "host": r.get("host"),
        "ip": ip,
        "fqdn": fqdn,  # ← NEW
        "model": node.get("model"),
        "serial_number": node.get("serial_number"),
        "bios_version": node.get("bios_version"),
        "cpu_model": _first_cpu_model(node.get("cpu_models")) or node.get("cpu_model"),
        "total_cores": node.get("total_cores"),
    }

def summarize_memory_row(r: Dict[str, Any]) -> Dict[str, Any]:
    mem = (r.get("summary") or {}).get("memory") if "summary" in r else r
    host = r.get("host")
    ip = _ip_from_base_url(r.get("base_url"))
    model = mem.get("model")
    serial = mem.get("serial_number")
    systems = mem.get("memory", []) or []

    total_mb = 0
    dimm_models, dimm_count = set(), 0
    for sysn in systems:
        if sysn.get("total_physical_mb"):
            total_mb += sysn["total_physical_mb"]
        else:
            for m in sysn.get("modules", []) or []:
                total_mb += m.get("capacity_mib") or 0
        for m in sysn.get("modules", []) or []:
            pn = m.get("part_number") or m.get("name") or ""
            if pn:
                dimm_models.add(pn)
            dimm_count += 1

    return {
        "host": host, "ip": ip, "model": model, "serial_number": serial,
        "ram_gib": round(total_mb / 1024, 1) if total_mb else None,
        "dimm_count": dimm_count,
        "dimm_models": ", ".join(sorted(dimm_models)) if dimm_models else None,
    }

def summarize_raid_row(r: Dict[str, Any]) -> Dict[str, Any]:
    raid = (r.get("summary") or {}).get("raid") if "summary" in r else r
    ctrls = vols = drvs = 0
    for s in raid.get("systems", []) or []:
        for c in s.get("raid", []) or []:
            ctrls += 1
            vols += len(c.get("volumes") or [])
            drvs += len(c.get("drives") or [])
    return {
        "host": r.get("host"),
        "ip": _ip_from_base_url(r.get("base_url")),
        "raid_controllers": ctrls,
        "raid_volumes": vols,
        "raid_drives": drvs,
        "raid_present": ctrls > 0,
    }

def summarize_health_row(r: Dict[str, Any]) -> Dict[str, Any]:
    root = (r.get("summary") or {}).get("health") if "summary" in r else r
    sys_health = root.get("systems_health") or []
    h = sys_health[0] if sys_health else {}
    return {
        "host": r.get("host"),
        "ip": _ip_from_base_url(r.get("base_url")),
        "system_health": h.get("health"),
        "system_state": h.get("state"),
        "power_state": h.get("power_state"),
    }

# ---------- Табличные принтеры ----------
def print_cpu_table(results: List[Dict[str, Any]]) -> None:
    ok = [x for x in results if x.get("ok")]
    table = Table(title="CPU Summary")
    table.add_column("Host", no_wrap=True)
    table.add_column("IP", no_wrap=True)
    table.add_column("FQDN", no_wrap=True)  # ← NEW
    table.add_column("Model")
    table.add_column("SN", no_wrap=True)
    table.add_column("CPU Model")
    table.add_column("Cores", justify="right")
    table.add_column("BIOS", no_wrap=True)
    for r in ok:
        row = summarize_cpu_row(r)
        table.add_row(
            str(row.get("host") or ""), str(row.get("ip") or ""), str(row.get("fqdn") or ""),
            str(row.get("model") or ""), str(row.get("serial_number") or ""),
            str(row.get("cpu_model") or ""), str(row.get("total_cores") or ""),
            str(row.get("bios_version") or ""),
        )
    Console().print(table)

def print_memory_table(results: List[Dict[str, Any]]) -> None:
    ok = [x for x in results if x.get("ok")]
    table = Table(title="Memory Summary")
    table.add_column("Host", no_wrap=True); table.add_column("IP", no_wrap=True)
    table.add_column("Model"); table.add_column("SN", no_wrap=True)
    table.add_column("RAM GiB", justify="right"); table.add_column("DIMMs", justify="right")
    table.add_column("DIMM Models")
    for r in ok:
        row = summarize_memory_row(r)
        table.add_row(
            str(row.get("host") or ""), str(row.get("ip") or ""),
            str(row.get("model") or ""), str(row.get("serial_number") or ""),
            str(row.get("ram_gib") or ""), str(row.get("dimm_count") or ""),
            str(row.get("dimm_models") or ""),
        )
    Console().print(table)

def print_raid_table(results: List[Dict[str, Any]]) -> None:
    ok = [x for x in results if x.get("ok")]
    table = Table(title="RAID Summary")
    table.add_column("Host", no_wrap=True); table.add_column("IP", no_wrap=True)
    table.add_column("Ctrls", justify="right"); table.add_column("Volumes", justify="right")
    table.add_column("Drives", justify="right"); table.add_column("Present", no_wrap=True)
    for r in ok:
        row = summarize_raid_row(r)
        table.add_row(
            str(row.get("host") or ""), str(row.get("ip") or ""),
            str(row.get("raid_controllers") or ""), str(row.get("raid_volumes") or ""),
            str(row.get("raid_drives") or ""), "yes" if row.get("raid_present") else "no",
        )
    Console().print(table)

def print_raid_disks_table(results: List[Dict[str, Any]]) -> None:
    """
    Печатает расширенную таблицу с *всеми* физическими дисками (для команды `raid`).
    """
    ok = [x for x in results if x.get("ok")]
    table = Table(title="RAID: Physical Drives")
    table.add_column("Host", no_wrap=True)
    table.add_column("IP", no_wrap=True)
    table.add_column("Controller", no_wrap=True)
    table.add_column("Slot", justify="right")
    table.add_column("Model")
    table.add_column("Capacity GiB", justify="right")
    table.add_column("Protocol", no_wrap=True)
    table.add_column("Media", no_wrap=True)
    table.add_column("Health", no_wrap=True)

    for r in ok:
        ip = _ip_from_base_url(r.get("base_url"))
        raid = (r.get("summary") or {}).get("raid") if "summary" in r else r
        for s in (raid.get("systems") or []):
            for c in (s.get("raid") or []):
                ctrl = (c.get("controller") or {})
                ctrl_id = ctrl.get("id") or ctrl.get("name") or ""
                for d in (c.get("drives") or []):
                    table.add_row(
                        str(r.get("host") or ""), str(ip or ""),
                        str(ctrl_id or ""),
                        str(d.get("slot") or ""),
                        str(d.get("model") or ""),
                        _bytes_to_gib(d.get("capacity_bytes")),
                        str(d.get("protocol") or ""),
                        str(d.get("media_type") or ""),
                        str((d.get("health") or "")),
                    )
    Console().print(table)

def print_health_table(results: List[Dict[str, Any]]) -> None:
    ok = [x for x in results if x.get("ok")]
    table = Table(title="Health Summary")
    table.add_column("Host", no_wrap=True); table.add_column("IP", no_wrap=True)
    table.add_column("Health", no_wrap=True); table.add_column("State", no_wrap=True)
    table.add_column("Power", no_wrap=True)
    for r in ok:
        row = summarize_health_row(r)
        table.add_row(
            str(row.get("host") or ""), str(row.get("ip") or ""),
            str(row.get("system_health") or ""), str(row.get("system_state") or ""),
            str(row.get("power_state") or ""),
        )
    Console().print(table)

def print_fans_table(results: List[Dict[str, Any]]) -> None:
    ok = [x for x in results if x.get("ok")]
    table = Table(title="Fans (MinThermalOutput / FailSafePercent)")
    table.add_column("Host", no_wrap=True)
    table.add_column("IP", no_wrap=True)
    table.add_column("Zone", no_wrap=True)
    table.add_column("MinOut old→new", no_wrap=True)
    table.add_column("FailSafe old→new", no_wrap=True)
    for r in ok:
        cpu = summarize_cpu_row(r)  # для host/ip
        fan = r.get("fan") or {}
        old = fan.get("old") or {}
        new = fan.get("new") or {}
        table.add_row(
            str(cpu.get("host") or ""), str(cpu.get("ip") or ""),
            str(fan.get("zone") or ""),
            f"{old.get('MinThermalOutput')} → {new.get('MinThermalOutput')}",
            f"{old.get('FailSafePercent')} → {new.get('FailSafePercent')}",
        )
    Console().print(table)


def print_all_table(results: List[Dict[str, Any]]) -> None:
    ok = [x for x in results if x.get("ok")]
    table = Table(title="All Summary")
    table.add_column("Host", no_wrap=True)
    table.add_column("IP", no_wrap=True)
    table.add_column("FQDN", no_wrap=True)  # ← NEW
    table.add_column("Model")
    table.add_column("SN", no_wrap=True)
    table.add_column("CPU Model")
    table.add_column("Cores", justify="right")
    table.add_column("RAM GiB", justify="right")
    table.add_column("RAID Ctrls", justify="right")
    table.add_column("Volumes", justify="right")
    table.add_column("Drives", justify="right")
    table.add_column("Health", no_wrap=True)
    for r in ok:
        cpu = summarize_cpu_row(r)
        mem = summarize_memory_row(r)
        raid = summarize_raid_row(r)
        health = summarize_health_row(r)
        table.add_row(
            str(cpu.get("host") or ""), str(cpu.get("ip") or ""), str(cpu.get("fqdn") or ""),
            str(cpu.get("model") or ""), str(cpu.get("serial_number") or ""),
            str(cpu.get("cpu_model") or ""), str(cpu.get("total_cores") or ""),
            str(mem.get("ram_gib") or ""), str(raid.get("raid_controllers") or ""),
            str(raid.get("raid_volumes") or ""), str(raid.get("raid_drives") or ""),
            str(health.get("system_health") or ""),
        )
    Console().print(table)

def print_accounts_table(results: List[Dict[str, Any]]) -> None:
    ok = [x for x in results if x.get("ok")]
    table = Table(title="Accounts")
    table.add_column("Host", no_wrap=True)
    table.add_column("IP", no_wrap=True)
    table.add_column("User", no_wrap=True)
    table.add_column("Role", no_wrap=True)
    table.add_column("Enabled", no_wrap=True)
    table.add_column("Locked", no_wrap=True)

    for r in ok:
        ip = _ip_from_base_url(r.get("base_url"))
        for a in (r.get("accounts") or []):
            table.add_row(
                str(r.get("host") or ""), str(ip or ""),
                str(a.get("user_name") or ""), str(a.get("role_id") or ""),
                "yes" if a.get("enabled") else "no",
                "yes" if a.get("locked") else "no",
            )
    Console().print(table)

def print_roles_table(results: List[Dict[str, Any]]) -> None:
    ok = [x for x in results if x.get("ok")]
    table = Table(title="Account Roles")
    table.add_column("Host", no_wrap=True)
    table.add_column("IP", no_wrap=True)
    table.add_column("RoleId", no_wrap=True)
    table.add_column("Predefined", no_wrap=True)
    table.add_column("Privileges")

    def _privs(rj: Dict[str, Any]) -> str:
        # разные вендоры: AssignedPrivileges / OemPrivileges / Privileges
        p = rj.get("AssignedPrivileges") or rj.get("Privileges") or rj.get("OemPrivileges") or []
        return ", ".join(p) if isinstance(p, list) else str(p)

    for r in ok:
        ip = _ip_from_base_url(r.get("base_url"))
        for role in (r.get("roles") or []):
            table.add_row(
                str(r.get("host") or ""), str(ip or ""),
                str(role.get("Id") or role.get("id") or ""),
                "yes" if role.get("IsPredefined") or role.get("is_predefined") else "no",
                _privs(role),
            )
    Console().print(table)