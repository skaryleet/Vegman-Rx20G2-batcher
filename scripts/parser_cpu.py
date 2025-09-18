from typing import Dict, Any
import httpx
from redfish_batch import FetchMembers

async def job_cpu(client: httpx.AsyncClient, host) -> Dict[str, Any]:
    systems = await FetchMembers(client, "/redfish/v1/Systems")
    if not systems:
        raise RuntimeError("Не найдены системы")

    # --- NEW: попробуем получить FQDN BMC/Manager ---
    mgrs = []
    try:
        mgrs = await FetchMembers(client, "/redfish/v1/Managers")
    except httpx.HTTPStatusError:
        pass
    mgr_fqdn = None
    if mgrs:
        m0 = mgrs[0]
        mgr_fqdn = m0.get("FQDN") or m0.get("HostName")

    systems_out = []
    for s in systems:
        sp = s["@odata.id"]
        sys_full = await client.get(sp); sys_full.raise_for_status()
        sysj = sys_full.json()

        cpus = await FetchMembers(client, f"{sp}/Processors")
        cpus_norm = [{
            "id": c.get("Id"),
            "socket": c.get("Socket"),
            "model": c.get("Model"),
            "total_cores": c.get("TotalCores"),
            "total_threads": c.get("TotalThreads"),
            "max_speed_mhz": c.get("MaxSpeedMHz"),
            "health": (c.get("Status") or {}).get("Health"),
        } for c in cpus]

        systems_out.append({
            "system_id": sp,
            "model": sysj.get("Model"),
            "manufacturer": sysj.get("Manufacturer"),
            "serial_number": sysj.get("SerialNumber"),
            "bios_version": sysj.get("BiosVersion"),
            "host_name": sysj.get("HostName"),   # ← NEW
            "fqdn": mgr_fqdn,                    # ← NEW (от BMC)
            "cpus_list": cpus_norm,
            "cpu_models": ", ".join(sorted({x["model"] for x in cpus_norm if x.get("model")})) or None,
            "total_cores": sum((x.get("total_cores") or 0) for x in cpus_norm),
        })

    first = systems_out[0]
    return {
        "system_id": first["system_id"],
        "model": first["model"],
        "manufacturer": first.get("manufacturer"),
        "serial_number": first["serial_number"],
        "bios_version": first.get("bios_version"),
        "host_name": first.get("HostName"),  # ← NEW
        "fqdn": first.get("FQDN"),            # ← NEW
        "cpu_models": first.get("cpu_models"),
        "total_cores": first.get("total_cores"),
        "systems": systems_out,
    }
