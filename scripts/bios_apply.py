# redfish_batch/bios_apply.py
from __future__ import annotations
from typing import Dict, Any, Optional, Tuple, List
import httpx, json

APPLY_TIME = "OnReset"  # фиксируем, как ты просил

def _extinfo_lines(obj: Any) -> List[str]:
    if not isinstance(obj, dict):
        try: obj = json.loads(str(obj))
        except Exception: return []
    out: List[str] = []
    for k, v in obj.items():
        if k.endswith("@Message.ExtendedInfo") and isinstance(v, list):
            for m in v:
                mid = (m or {}).get("MessageId") or ""
                msg = (m or {}).get("Message") or ""
                if mid or msg:
                    out.append(f"{k}: {mid} | {msg}")
    return out

async def _discover_paths(client: httpx.AsyncClient) -> Tuple[str, Optional[str]]:
    r = await client.get("/redfish/v1/Systems"); r.raise_for_status()
    members = (r.json().get("Members") or [])
    if not members:
        raise RuntimeError("Systems.Members is empty")
    sp = members[0]["@odata.id"]
    b = await client.get(f"{sp}/Bios"); b.raise_for_status()
    settings = (((b.json().get("@Redfish.Settings") or {}).get("SettingsObject") or {}).get("@odata.id"))
    if settings:
        try:
            s = await client.get(settings); s.raise_for_status()
        except httpx.HTTPError:
            settings = None
    return sp, settings

async def _patch_settings(client: httpx.AsyncClient, settings_path: str, attrs: Dict[str, Any]) -> httpx.Response:
    return await client.post(settings_path, json={"Attributes": attrs})

async def _patch_bios_flexible(client: httpx.AsyncClient, bios_path: str, attrs: Dict[str, Any]) -> tuple[httpx.Response, str]:
    """
    Для /Bios сначала пробуем без аннотаций. Если сервер просит @Redfish.Settings — повторяем с аннотациями.
    Если ругается на аннотацию — остаёмся на plain.
    """
    body_plain = {"Attributes": attrs}
    body_annot = {
        "Attributes": attrs,
        "@Redfish.Settings": {"ApplyTime": APPLY_TIME},
        "@Redfish.SettingsApplyTime": APPLY_TIME,
    }

    # 1) plain
    r = await client.post(bios_path, json=body_plain)
    if r.status_code in (200, 204):
        return r, "plain"
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        txt = e.response.text if e.response is not None else ""
        if "PropertyMissing" in txt and "@Redfish.Settings" in txt:
            r2 = await client.patch(bios_path, json=body_annot)
            r2.raise_for_status()
            return r2, "annot"
        if "PropertyUnknown" in txt and "@Redfish.SettingsApplyTime" in txt:
            r2 = await client.patch(bios_path, json=body_plain)
            r2.raise_for_status()
            return r2, "plain"
        raise

async def apply_bios(
    client: httpx.AsyncClient,
    wanted: Dict[str, Any],
    reboot: bool = False,
) -> Dict[str, Any]:
    """
    Без валидации. Пытаемся применить весь набор:
      - PATCH /Bios/Settings {"Attributes": wanted}
      - иначе PATCH /Bios (plain → при нужде с аннотациями)
    При 400 — расщепляем и шлём по одному ключу.
    """
    system_path, settings_path = await _discover_paths(client)
    bios_path = f"{system_path}/Bios"

    used_direct = False
    applied_keys: List[str] = []
    failed_keys: List[Dict[str, str]] = []

    # helpers для поатрибутного применения
    async def apply_one_settings(k: str, v: Any):
        return await _patch_settings(client, settings_path, {k: v})

    async def apply_one_bios(k: str, v: Any):
        # гибкий режим и для одиночных ключей
        resp, _mode = await _patch_bios_flexible(client, bios_path, {k: v})
        return resp

    # 1) пробуем SETTINGS целиком
    if settings_path:
        try:
            r = await _patch_settings(client, settings_path, wanted)
            r.raise_for_status()
            applied_keys = list(wanted.keys())
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 400:
                # пробуем по одному ключу, чтобы максимум применить
                for k, v in wanted.items():
                    try:
                        r1 = await apply_one_settings(k, v)
                        r1.raise_for_status()
                        applied_keys.append(k)
                    except httpx.HTTPStatusError as ee:
                        reason = "; ".join(_extinfo_lines(ee.response.text)) if ee.response is not None else str(ee)
                        failed_keys.append({"key": k, "reason": reason or "400 Bad Request"})
            elif e.response is not None and e.response.status_code in (404, 405):
                settings_path = None  # нет/не поддержан → BIOS
            else:
                txt = e.response.text if e.response is not None else ""
                raise httpx.HTTPStatusError(f"{e}. Body: {txt[:1200]}", request=e.request, response=e.response)

    # 2) если SETTINGS недоступен или не поддержан → BIOS
    if not settings_path:
        used_direct = True
        try:
            r2, _mode = await _patch_bios_flexible(client, bios_path, wanted)
            r2.raise_for_status()
            applied_keys = list(wanted.keys())
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 400:
                for k, v in wanted.items():
                    try:
                        r1 = await apply_one_bios(k, v)
                        r1.raise_for_status()
                        applied_keys.append(k)
                    except httpx.HTTPStatusError as ee:
                        reason = "; ".join(_extinfo_lines(ee.response.text)) if ee.response is not None else str(ee)
                        failed_keys.append({"key": k, "reason": reason or "400 Bad Request"})
            else:
                txt = e.response.text if e.response is not None else ""
                raise httpx.HTTPStatusError(f"{e}. Body: {txt[:1200]}", request=e.request, response=e.response)

    # 3) перезапуск (опционально)
    if reboot:
        try:
            sys_full = await client.get(system_path); sys_full.raise_for_status()
            actions = (sys_full.json() or {}).get("Actions") or {}
            reset = actions.get("#ComputerSystem.Reset")
            if reset and reset.get("target"):
                p = await client.post(reset["target"], json={"ResetType": "GracefulRestart"})
                p.raise_for_status()
        except Exception:
            pass

    return {
        "system_id": system_path,
        "used_direct_bios": used_direct,
        "apply_time": APPLY_TIME,
        "reboot": reboot,
        "status": "applied",
        "applied_keys": applied_keys or None,
        "failed_keys": failed_keys or None,
    }
