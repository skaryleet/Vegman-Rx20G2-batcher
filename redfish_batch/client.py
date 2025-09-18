import asyncio
from typing import Any, Dict, List, Callable, Awaitable, Optional
import httpx
from .models import Host

async def FetchMembers(client: httpx.AsyncClient, collection_path: str) -> list:
    collection_response = await client.get(collection_path)
    collection_response.raise_for_status()
    members = collection_response.json().get("Members", [])
    output = []
    for member in members:
        member_response = await client.get(member["@odata.id"])
        member_response.raise_for_status()
        output.append(member_response.json())
    return output

async def FetchLinks(client: httpx.AsyncClient, links: list) -> list:
    output = []
    for link in links or []:
        link_response = await client.get(link.get("@odata.id"))
        if link_response.is_success:
            output.append(link_response.json())
    return output

async def FetchStorage(client: httpx.AsyncClient, system_path: str) -> list:
    controllers = await FetchMembers(client, f"{system_path}/Storage")
    disks = []
    for controller in controllers:
        drives = await FetchLinks(client, controller.get("Drives", []))
        for drive in drives:
            disks.append({
                "id": drive.get("Id"),
                "model": drive.get("Model"),
                "capacity": drive.get("CapacityBytes"),
                "media_type": drive.get("MediaType"),
                "conn_type": drive.get("Protocol"),
                "heatlh": drive.get("Health"),
                "slot": drive.get("PhysicalLocation")
            })
    return disks

class RedfishBatch:
    def __init__(self, hosts: List[Host], concurrency: int = 8, timeout: int = 20, retries: int = 3):
        # за дефолтные значения принял 8 потоков, таймаут в 20 секунд и 3 попытки
        self.hosts = hosts
        self.semaphore = asyncio.Semaphore(concurrency)
        self.timeout = timeout
        self.retries = retries

    async def _login(self, client: httpx.AsyncClient, user: str, pwd: str) -> Dict[str, str]:
        response = await client.post("/redfish/v1/SessionService/Sessions",
                                     json={"UserName": user, "Password": pwd},
                                     timeout=self.timeout)
        response.raise_for_status()
        return {"X-Auth-Token": response.headers.get("X-Auth-Token", ""),
                "Location": response.headers.get("Location", "")}
    
    async def _logout(self, client: httpx.AsyncClient, session_location: str) -> None:
        if session_location:
            try: 
                await client.delete(session_location, timeout=self.timeout)
            except Exception:
                pass

    async def _fetch_one(self, host: Host, job: Callable[[httpx.AsyncClient, Host], Awaitable[Dict[str, Any]]]) -> Dict[str, Any]:
        async with self.semaphore:
            backoff = 1.0
            for attempt in range(1, self.retries + 1):
                try:
                    async with httpx.AsyncClient(
                        base_url = host.base_url,
                        verify = host.verify,
                        headers = {"Accept": "application/json"},
                        timeout = self.timeout
                    ) as client:
                        username = host.username
                        password = host.password or ""
                        session = await self._login(client, username, password)
                        client.headers["X-Auth-Token"] = session["X-Auth-Token"]
                        payload = await job(client, host)
                        await self._logout(client, session["Location"])
                        return {"ok": True, "host": host.name or host.base_url, "base_url": host.base_url, **payload}
                except Exception as exception:
                    if attempt == self.retries:
                        return {"ok": False, "host": host.name or host.base_url, "base_url": host.base_url, "error": f"{type(exception).__name__}: {exception}"}
                    await asyncio.sleep(backoff)
                    backoff *=2

    async def run_job(self, job: Callable[[httpx.AsyncClient, Host], Awaitable[Dict[str, Any]]], 
                      on_progress: Optional[Callable[[Dict[str, Any]], None]] = None) -> List[Dict[str, Any]]:
        async def _wrap(host: Host):
            result = await self._fetch_one(host, job)
            if on_progress:
                on_progress(result)
            return result
        tasks = [asyncio.create_task(_wrap(host)) for host in self.hosts]
        results: List[Dict[str, Any]] = []
        for completed_task in asyncio.as_completed(tasks):
            result = await completed_task
            results.append(result)
        return results
