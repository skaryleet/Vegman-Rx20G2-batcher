from typing import Dict, Any, List
import httpx
from redfish_batch import FetchMembers

async def job_health(client: httpx.AsyncClient, host) -> Dict[str, Any]:
    systems = await FetchMembers(client, "/redfish/v1/Systems")
    chassis = await FetchMembers(client, "/redfish/v1/Chassis")

    systems_health: List[Dict[str, Any]] = []
    for system in systems:
        system_path = system["@odata.id"]
        system_full_response = await client.get(system_path)
        system_full_response.raise_for_status()
        system_json = system_full_response.json()
        status = system_json.get("Status") or {}
        systems_health.append({
            "system_id": system_path,
            "health": status.get("Health"),
            "state": status.get("State"),
            "power_state": system_json.get("PowerState"),
            "bios_version": system_json.get("BiosVersion"),
            "model": system_json.get("Model"),
            "serial_number": system_json.get("SerialNumber"),
        })

    chassis_health: List[Dict[str, Any]] = []
    for chassis_item in chassis:
        chassis_path = chassis_item["@odata.id"]
        chassis_full_response = await client.get(chassis_path)
        chassis_full_response.raise_for_status()
        chassis_json = chassis_full_response.json()
        status = chassis_json.get("Status") or {}

        # Thermal (optional)
        fans_ok = temps_warn = temps_crit = None
        try:
            thermal_response = await client.get(f"{chassis_path}/Thermal")
            thermal_response.raise_for_status()
            thermal_json = thermal_response.json()
            fans = thermal_json.get("Fans") or []
            temps = thermal_json.get("Temperatures") or []
            fans_ok = sum(1 for fan in fans if (fan.get("Status") or {}).get("Health") in (None, "OK"))
            temps_warn = sum(1 for temp in temps if (temp.get("Status") or {}).get("Health") == "Warning")
            temps_crit = sum(1 for temp in temps if (temp.get("Status") or {}).get("Health") == "Critical")
        except httpx.HTTPStatusError as exception:
            if exception.response.status_code != 404:
                raise

        # Power (optional)
        psu_total = psu_ok = None
        try:
            power_response = await client.get(f"{chassis_path}/Power")
            power_response.raise_for_status()
            power_json = power_response.json()
            power_supplies = power_json.get("PowerSupplies") or []
            psu_total = len(power_supplies)
            psu_ok = sum(1 for supply in power_supplies if (supply.get("Status") or {}).get("Health") in (None, "OK"))
        except httpx.HTTPStatusError as exception:
            if exception.response.status_code != 404:
                raise

        chassis_health.append({
            "chassis_id": chassis_path,
            "health": status.get("Health"),
            "state": status.get("State"),
            "fans_ok": fans_ok,
            "temps_warn": temps_warn,
            "temps_crit": temps_crit,
            "psu_total": psu_total,
            "psu_ok": psu_ok,
        })

    return {"systems_health": systems_health, "chassis_health": chassis_health}
