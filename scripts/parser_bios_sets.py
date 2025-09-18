from typing import Dict, Any, List
import httpx
from redfish_batch import FetchMembers

async def job_bios_dump(client: httpx.AsyncClient, host) -> Dict[str, Any]:
    systems = await FetchMembers(client, "/redfish/v1/Systems")
    if not systems:
        raise RuntimeError("Не найдены системы")

    out: List[Dict[str, Any]] = []
    for s in systems:
        sp = s["@odata.id"]

        # Полный объект системы — для model/serial/bios_version
        sys_full = await client.get(sp); sys_full.raise_for_status()
        sysj = sys_full.json()

        # Текущие атрибуты BIOS
        b = await client.get(f"{sp}/Bios"); b.raise_for_status()
        bj = b.json()

        # Где лежат «настройки» для PATCH (и pending-атрибуты)
        settings_uri = (
            ((bj.get("@Redfish.Settings") or {}).get("SettingsObject") or {}).get("@odata.id")
            or f"{sp}/Bios/Settings"
        )
        pending = None
        etag = None
        try:
            sres = await client.get(settings_uri)
            sres.raise_for_status()
            pending = (sres.json() or {}).get("Attributes")
            etag = sres.headers.get("ETag")
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise

        out.append({
            "system_id": sp,
            "model": sysj.get("Model"),
            "manufacturer": sysj.get("Manufacturer"),
            "serial_number": sysj.get("SerialNumber"),
            "bios_version": sysj.get("BiosVersion"),
            "current": bj.get("Attributes"),
            "pending": pending,
            "settings_uri": settings_uri,
            "settings_etag": etag,
        })

    # Для сводок оставим «первую» систему на верхнем уровне
    first = out[0]
    return {
        "system_id": first["system_id"],
        "model": first["model"],
        "serial_number": first["serial_number"],
        "bios_version": first.get("bios_version"),
        "bios": out,
    }
