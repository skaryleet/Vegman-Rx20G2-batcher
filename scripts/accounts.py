# scripts/accounts.py
from typing import Dict, Any
import httpx
from redfish_batch import FetchMembers

ACCOUNTS = "/redfish/v1/AccountService/Accounts"
ROLES    = "/redfish/v1/AccountService/Roles"

async def job_accounts_list(client: httpx.AsyncClient, host) -> Dict[str, Any]:
    roles_list = []
    try:
        roles_list = await FetchMembers(client, ROLES)
    except Exception:
        pass
    accounts = await FetchMembers(client, ACCOUNTS)
    accounts_out = []
    for account in accounts:
        status = account.get("Status") or {}
        accounts_out.append({
            "id": account.get("Id"),
            "user_name": account.get("UserName"),
            "role_id": account.get("RoleId"),
            "enabled": account.get("Enabled"),
            "locked": account.get("Locked"),
            "health": status.get("Health"),
            "account_uri": account.get("@odata.id"),
        })
    return {"accounts": accounts_out, "roles": [{"id": role.get("Id"), "is_predefined": role.get("IsPredefined")} for role in roles_list]}

async def job_accounts_roles(client: httpx.AsyncClient, host) -> Dict[str, Any]:
    roles = await FetchMembers(client, ROLES)
    return {"roles": roles}

async def _create_via_post(client: httpx.AsyncClient, user: str, password: str, role: str, enabled: bool) -> Dict[str, Any]:
    response = await client.post(ACCOUNTS, json={
        "UserName": user, "Password": password, "RoleId": role, "Enabled": bool(enabled)
    })
    response.raise_for_status()
    location = response.headers.get("Location")
    account = None
    if location:
        account_response = await client.get(location)
        account_response.raise_for_status()
        account = account_response.json()
    return {"created": True, "location": location, "account": account}

async def _fallback_patch_fixed_slots(client: httpx.AsyncClient, user: str, password: str, role: str, enabled: bool) -> Dict[str, Any]:
    collection = await FetchMembers(client, ACCOUNTS)
    used_ids = {str((account.get("Id") or "")).strip() for account in collection}
    for slot_index in range(2, 33):
        slot_id = str(slot_index)
        if slot_id in used_ids:
            continue
        uri = f"{ACCOUNTS}/{slot_id}"
        try:
            response = await client.patch(uri, json={
                "UserName": user, "Password": password, "RoleId": role, "Enabled": bool(enabled)
            })
            if response.status_code in (200, 201, 204):
                return {"created": True, "location": uri, "account": {"Id": slot_id, "UserName": user, "RoleId": role, "Enabled": enabled}}
        except httpx.HTTPStatusError:
            pass
    raise RuntimeError("Не удалось создать пользователя через PATCH /Accounts/{slot}")

async def job_account_create(client: httpx.AsyncClient, host, user: str, password: str, role: str="Operator", enabled: bool=True) -> Dict[str, Any]:
    try:
        return await _create_via_post(client, user, password, role, enabled)
    except httpx.HTTPStatusError as exception:
        if exception.response.status_code in (405, 501):
            return await _fallback_patch_fixed_slots(client, user, password, role, enabled)
        raise

async def job_account_password(client: httpx.AsyncClient, host, account_id_or_uri: str, new_password: str) -> Dict[str, Any]:
    uri = account_id_or_uri if account_id_or_uri.startswith("/") else f"{ACCOUNTS}/{account_id_or_uri}"
    response = await client.patch(uri, json={"Password": new_password})
    response.raise_for_status()
    return {"password_set": True, "account": uri}

async def job_account_role(client: httpx.AsyncClient, host, account_id_or_uri: str, role: str) -> Dict[str, Any]:
    uri = account_id_or_uri if account_id_or_uri.startswith("/") else f"{ACCOUNTS}/{account_id_or_uri}"
    response = await client.patch(uri, json={"RoleId": role})
    response.raise_for_status()
    return {"role_set": role, "account": uri}

async def job_account_enable(client: httpx.AsyncClient, host, account_id_or_uri: str, enabled: bool) -> Dict[str, Any]:
    uri = account_id_or_uri if account_id_or_uri.startswith("/") else f"{ACCOUNTS}/{account_id_or_uri}"
    response = await client.patch(uri, json={"Enabled": bool(enabled)})
    response.raise_for_status()
    return {"enabled": enabled, "account": uri}

async def job_account_delete(client: httpx.AsyncClient, host, account_id_or_uri: str) -> Dict[str, Any]:
    uri = account_id_or_uri if account_id_or_uri.startswith("/") else f"{ACCOUNTS}/{account_id_or_uri}"
    response = await client.delete(uri)
    response.raise_for_status()
    return {"deleted": True, "account": uri}
