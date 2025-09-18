from typing import Dict, Any
import httpx
from redfish_batch import FetchMembers

async def job_dimm(client: httpx.AsyncClient, host) -> Dict[str, Any]:
    systems = await FetchMembers(client, "/redfish/v1/Systems")
    if not systems:
        raise RuntimeError("Не найдены системы")

    out = []
    for s in systems:
        sp = s["@odata.id"]

        # Берём ПОЛНЫЙ объект системы, чтобы точно увидеть MemorySummary
        sys_full = await client.get(sp)
        sys_full.raise_for_status()
        sys = sys_full.json()

        dimms = await FetchMembers(client, f"{sp}/Memory")
        dimms_norm = [{
            "id": d.get("Id"),
            "name": d.get("Name"),
            "manufacturer": d.get("Manufacturer"),
            "part_number": d.get("PartNumber"),
            "serial_number": d.get("SerialNumber"),
            "capacity_mib": d.get("CapacityMiB"),
            "speed_mhz": d.get("OperatingSpeedMhz"),
            "memory_device_type": d.get("MemoryDeviceType"),
            "slot": (d.get("PhysicalLocation") or {}).get("PartLocation", {}).get("LocationOrdinalValue"),
            "health": (d.get("Status") or {}).get("Health"),
        } for d in dimms]

        # Суммарная память — предпочитаем MemorySummary
        memsum = sys.get("MemorySummary") or {}
        if memsum.get("TotalSystemMemoryGiB") is not None:
            total_mb = int(memsum["TotalSystemMemoryGiB"] * 1024)
        else:
            total_mb = sum((m.get("CapacityMiB") or 0) for m in dimms_norm)

        out.append({
            "system_id": sp,
            "model": sys.get("Model"),
            "serial_number": sys.get("SerialNumber"),
            "total_physical_mb": total_mb,
            "modules": dimms_norm,
        })

    first = out[0]
    return {
        "system_id": first["system_id"],
        "model": first["model"],
        "serial_number": first["serial_number"],
        "memory": out,
    }
