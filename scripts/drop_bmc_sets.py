from typing import Dict, Any, Tuple, List
import httpx
from redfish_batch.client import FetchMembers

# helper: ожидается, что client - httpx.AsyncClient с base_url, auth/X-Auth-Token настроен
async def _resolve_openbmc_manager(client: httpx.AsyncClient) -> Tuple[str, Dict[str, Any]]:
    """
    Возвращает (manager_path, manager_json) для менеджера, где есть Oem.OpenBmc.
    Пробуем /redfish/v1/Managers/bmc сначала, иначе первый из /redfish/v1/Managers с Oem.OpenBmc,
    иначе первый менеджер.
    """
    # 1) Попробуем прямой менеджер /Managers/bmc
    
    resp = await client.get("/redfish/v1/Managers/bmc")
    if resp.status_code == 200:
        return "/redfish/v1/Managers/bmc", resp.json()
 

    # 2) Получим коллекцию Managers и просмотрим членов
    # Предполагаем, что у тебя есть утилита FetchMembers, которая возвращает уже список member JSON-объектов
    managers: List[Dict[str, Any]] = await FetchMembers(client, "/redfish/v1/Managers")
    # Найдём менеджер с Oem.OpenBmc
    for m in managers:
        oem = m.get("Oem", {})
        if oem and oem.get("OpenBmc") is not None:
            return m.get("@odata.id"), m
    # 3) fallback: первый менеджер
    if managers:
        return managers[0].get("@odata.id"), managers[0]
    raise RuntimeError("Managers collection is empty or недоступна")

async def job_drop_bmc(client: httpx.AsyncClient, host_label: str, reset_type: str = "ResetAll") -> Dict[str, Any]:
    """
    Выполняет ResetAll/ResetToDefaults для BMC. Возвращает словарь со статусом и ответом.
    - client: httpx.AsyncClient (обычно с base_url="https://<bmc_ip>" и auth/token)
    - reset_type: тип Reset, например "ResetAll" или "ResetToDefaults" в зависимости от реализации BMC
    """
    manager_path, manager_json = await _resolve_openbmc_manager(client)
    if not manager_path:
        raise RuntimeError("Не найден manager path")

    # Ищем target для action
    target = f"{manager_path}/Actions/Manager.ResetToDefaults"
    target_reboot = f"{manager_path}/Actions/Manager.Reset"

    payload = {"ResetType": reset_type}
    payload_reboot = {"ResetType": "GracefulRestart"}
    headers = {"Content-Type": "application/json"}

    # Выполняем POST
    resp = await client.post(target, json=payload, headers=headers)
    resp.raise_for_status()
    resp2 = await client.post(target_reboot, json=payload_reboot, headers=headers)
    resp2.raise_for_status()

    return {
        "bmc": {
            "out": resp.json(),
            "2out": resp2.json(),
        },
        "target_path": target,
        "target_reboot": target_reboot
    }
