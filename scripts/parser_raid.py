from typing import Dict, Any, List
import httpx
from redfish_batch import FetchMembers, FetchLinks

async def job_raid(client: httpx.AsyncClient, host) -> Dict[str, Any]:
    systems = await FetchMembers(client, "/redfish/v1/Systems")
    if not systems:
        raise RuntimeError("Не найдены системы")

    systems_output: List[Dict[str, Any]] = []
    for system in systems:
        system_path = system["@odata.id"]
        controllers = await FetchMembers(client, f"{system_path}/Storage")
        controllers_output = []
        for controller in controllers:
            controller_id = controller.get("Id")
            # Логические тома (если поддерживаются)
            volumes: List[Dict[str, Any]] = []
            try:
                volumes = await FetchMembers(client, controller["@odata.id"] + "/Volumes")
            except httpx.HTTPStatusError as exception:
                if exception.response.status_code != 404:
                    raise

            # Физические диски под контроллером
            drives_objects = await FetchLinks(client, controller.get("Drives", []) or [])

            # Привязки: у volume → Links.Drives
            volumes_output = []
            for volume in volumes:
                volume_links = (volume.get("Links") or {}).get("Drives", []) or []
                volume_drives = await FetchLinks(client, volume_links)
                volumes_output.append({
                    "id": volume.get("Id"),
                    "name": volume.get("Name"),
                    "raid_type": volume.get("RAIDType"),
                    "capacity_bytes": volume.get("CapacityBytes"),
                    "health": (volume.get("Status") or {}).get("Health"),
                    "drives": [{
                        "id": drive.get("Id"),
                        "model": drive.get("Model"),
                        "capacity_bytes": drive.get("CapacityBytes"),
                        "protocol": drive.get("Protocol"),
                        "slot": (drive.get("PhysicalLocation") or {}).get("PartLocation", {}).get("LocationOrdinalValue"),
                        "health": (drive.get("Status") or {}).get("Health"),
                    } for drive in volume_drives],
                })

            controllers_output.append({
                "controller": {
                    "id": controller_id,
                    "name": controller.get("Name"),
                    "model": controller.get("Model"),
                    "firmware": (controller.get("FirmwareVersion") or controller.get("SoftwareVersion")),
                    "health": (controller.get("Status") or {}).get("Health"),
                },
                "drives": [{
                    "id": drive.get("Id"),
                    "model": drive.get("Model"),
                    "capacity_bytes": drive.get("CapacityBytes"),
                    "protocol": drive.get("Protocol"),
                    "media_type": drive.get("MediaType"),
                    "slot": (drive.get("PhysicalLocation") or {}).get("PartLocation", {}).get("LocationOrdinalValue"),
                    "health": (drive.get("Status") or {}).get("Health"),
                } for drive in drives_objects],
                "volumes": volumes_output,
            })

        systems_output.append({"system_id": system_path, "raid": controllers_output})

    return {"systems": systems_output}
