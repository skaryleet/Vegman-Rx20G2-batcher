# scripts/fans_set.py
from typing import Dict, Any, Optional, Tuple
import httpx
from redfish_batch import FetchMembers

async def _resolve_openbmc_manager(client: httpx.AsyncClient) -> Tuple[str, dict]:
    """
    Возвращает (manager_path, manager_json) для менеджера, где есть Oem.OpenBmc.
    Пробуем /redfish/v1/Managers/bmc, иначе первый из /Managers с Oem.OpenBmc.
    """
    # прямой путь
    try:
        r = await client.get("/redfish/v1/Managers/bmc")
        if r.is_success:
            return "/redfish/v1/Managers/bmc", r.json()
    except httpx.HTTPStatusError:
        pass

    # поиск по коллекции
    managers = await FetchMembers(client, "/redfish/v1/Managers")
    for m in managers:
        if (m.get("Oem") or {}).get("OpenBmc"):
            return m["@odata.id"], m
    # если ни у кого нет OpenBmc — вернем первый менеджер (пусть упадём позже с понятной ошибкой)
    if managers:
        return managers[0]["@odata.id"], managers[0]
    raise RuntimeError("Managers не найдены")

async def job_fan_set(
    client: httpx.AsyncClient,
    host,
    min_output: float = 100.0,
    zone: str = "Main",
    set_failsafe: Optional[float] = None,
    require_if_match: bool = True,
) -> Dict[str, Any]:
    """
    Ставит Oem.OpenBmc.Fan.FanZones.<zone>.MinThermalOutput = min_output (0..100).
    Опционально меняет FailSafePercent. Патчим сам ресурс Manager (без '#').
    """

    if min_output < 0 or min_output > 100:
        raise ValueError("min_output должен быть в диапазоне 0..100")
    if set_failsafe is not None and (set_failsafe < 0 or set_failsafe > 100):
        raise ValueError("set_failsafe должен быть в диапазоне 0..100")

    mgr_path, mgr_json = await _resolve_openbmc_manager(client)

    # Проверяем, что зона существует (по текущему состоянию)
    oem = (mgr_json.get("Oem") or {}).get("OpenBmc") or {}
    fan = (oem.get("Fan") or {})
    zones = (fan.get("FanZones") or {})
    zone_obj = zones.get(zone)
    if not zone_obj:
        # Обновим json на всякий случай и проверим ещё раз (ETag мог смениться)
        res = await client.get(mgr_path); res.raise_for_status()
        mgr_json = res.json()
        oem = (mgr_json.get("Oem") or {}).get("OpenBmc") or {}
        fan = (oem.get("Fan") or {})
        zones = (fan.get("FanZones") or {})
        zone_obj = zones.get(zone)
        if not zone_obj:
            raise RuntimeError(f"Зона вентиляторов '{zone}' не найдена в Oem.OpenBmc.Fan.FanZones")

    old_min = zone_obj.get("MinThermalOutput")
    old_fs  = zone_obj.get("FailSafePercent")

    # Составляем минимальный PATCH на ресурс менеджера
    body: Dict[str, Any] = {
        "Oem": {
            "OpenBmc": {
                "Fan": {
                    "FanZones": {
                        zone: {
                            "MinThermalOutput": float(min_output)
                        }
                    }
                }
            }
        }
    }
    if set_failsafe is not None:
        body["Oem"]["OpenBmc"]["Fan"]["FanZones"][zone]["FailSafePercent"] = float(set_failsafe)

    # ETag/If-Match для безопасности
    headers = {}
    res = await client.get(mgr_path)
    res.raise_for_status()
    etag = res.headers.get("ETag")
    if require_if_match and etag:
        headers["If-Match"] = etag

    pres = await client.patch(mgr_path, json=body, headers=headers)
    pres.raise_for_status()

    # Прочитаем новое состояние
    final = await client.get(mgr_path); final.raise_for_status()
    fj = final.json()
    nz = (((fj.get("Oem") or {}).get("OpenBmc") or {}).get("Fan") or {}).get("FanZones", {}).get(zone, {})
    new_min = nz.get("MinThermalOutput")
    new_fs  = nz.get("FailSafePercent")

    return {
        "fan": {
            "zone": zone,
            "old": {"MinThermalOutput": old_min, "FailSafePercent": old_fs},
            "new": {"MinThermalOutput": new_min, "FailSafePercent": new_fs},
        },
        "manager_path": mgr_path,
    }
