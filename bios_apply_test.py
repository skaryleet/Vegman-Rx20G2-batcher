#!/usr/bin/env python3
import argparse, json, sys
import httpx

def extinfo_lines(j: dict) -> list[str]:
    if not isinstance(j, dict):
        return []
    out = []
    for k, v in j.items():
        if k.endswith("@Message.ExtendedInfo") and isinstance(v, list):
            for m in v:
                msg = (m or {}).get("Message") or ""
                mid = (m or {}).get("MessageId") or ""
                if msg or mid:
                    out.append(f"{k}: {mid} | {msg}")
    return out

def ensure_attrs_obj(obj):
    # Разрешаем "Attributes" обёртки или массивы — нормализуем в объект-словарь
    if isinstance(obj, dict) and "Attributes" in obj:
        obj = obj["Attributes"]
    if isinstance(obj, list):
        # если вдруг передали ["Key","Val"] — это неверно для Redfish. Сообщим явно.
        raise ValueError("Формат неверный: 'Attributes' в Redfish должен быть объектом {\"Key\":\"Value\"}, а не массивом.")
    if not isinstance(obj, dict):
        raise ValueError("Нужен JSON-объект {\"Key\":\"Value\"}.")
    return obj

def discover_system_and_settings(client: httpx.Client) -> tuple[str, str | None]:
    # Ищем первый system
    r = client.get("/redfish/v1/Systems"); r.raise_for_status()
    members = (r.json().get("Members") or [])
    if not members:
        raise RuntimeError("Systems: Members пуст.")
    sp = members[0]["@odata.id"]  # путь до системы
    # Читаем Bios и вытаскиваем SettingsObject, если есть
    b = client.get(f"{sp}/Bios"); b.raise_for_status()
    bj = b.json()
    settings_path = (((bj.get("@Redfish.Settings") or {}).get("SettingsObject") or {}).get("@odata.id"))
    if settings_path:
        # убедимся, что доступен
        try:
            s = client.get(settings_path); s.raise_for_status()
        except httpx.HTTPError:
            settings_path = None
    return sp, settings_path

def main():
    ap = argparse.ArgumentParser(description="BIOS apply test (PUT → POST → PATCH)")
    ap.add_argument("--host", required=True, help="BMC IP/hostname")
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--attrs", required=True, help="JSON файл c {\"Key\":\"Value\", ...}")
    ap.add_argument("--verify", action="store_true", help="Проверять TLS сертификат (по умолчанию — нет)")
    ap.add_argument("--apply-time", default="OnReset", help="Apply time для PATCH на /Bios (fallback)")
    args = ap.parse_args()

    base = f"https://{args.host}"
    with httpx.Client(base_url=base, verify=args.verify, headers={"Accept":"application/json"}) as client:
        # 1) Сессия
        r = client.post("/redfish/v1/SessionService/Sessions",
                        json={"UserName": args.user, "Password": args.password})
        r.raise_for_status()
        token = r.headers.get("X-Auth-Token")
        sess_loc = r.headers.get("Location")
        client.headers["X-Auth-Token"] = token or ""

        try:
            # 2) Системы/настройки
            system_path, settings_path = discover_system_and_settings(client)
            bios_path = f"{system_path}/Bios"
            print(f"System: {system_path}\nBios:   {bios_path}\nSettings: {settings_path or '(нет)'}")

            # 3) Загружаем целевые атрибуты и текущие значения
            wanted = ensure_attrs_obj(json.load(open(args.attrs, "r", encoding="utf-8")))
            cur = client.get(bios_path); cur.raise_for_status()
            cur_attrs = (cur.json().get("Attributes") or {})
            # «PUT-набор»: только те ключи, что ты собираешься менять — но их текущие значения
            put_attrs = {k: cur_attrs.get(k) for k in wanted.keys() if k in cur_attrs}

            # Утилиты печати результата
            def show_result(tag: str, resp: httpx.Response):
                print(f"{tag}: HTTP {resp.status_code}")
                try:
                    j = resp.json()
                except Exception:
                    j = None
                if isinstance(j, dict):
                    ei = extinfo_lines(j)
                    if ei:
                        print("\n".join(f"  {line}" for line in ei))

            # 4) Шаг 1: PUT /Bios/Settings (если доступен)
            if settings_path:
                try:
                    resp_put = client.put(settings_path, json={"Attributes": put_attrs})
                    if resp_put.status_code in (200, 201, 204):
                        show_result("PUT  Settings", resp_put)
                    else:
                        show_result("PUT  Settings", resp_put)
                        resp_put.raise_for_status()
                except httpx.HTTPStatusError as e:
                    print(f"PUT Settings → {e}")

            else:
                print("PUT пропущен: Settings недоступен на этом BMC.")

            # 6) Шаг 3: PATCH /Bios/Settings (основной способ)
            if settings_path:
                try:
                    resp_patch = client.patch(settings_path, json={"Attributes": wanted})
                    show_result("PATCH Settings", resp_patch)
                    resp_patch.raise_for_status()
                except httpx.HTTPStatusError as e:
                    print(f"PATCH Settings → {e}")
                
            else:
                print("Settings нет → PATCH /Bios c @Redfish.Settings.ApplyTime")
                resp2 = client.patch(bios_path, json={
                    "Attributes": wanted,
                    "@Redfish.Settings": {"ApplyTime": args.apply_time},
                    "@Redfish.SettingsApplyTime": args.apply_time
                })
                show_result("PATCH Bios", resp2)
                resp2.raise_for_status()

        finally:
            # 7) Логаут
            if sess_loc:
                try:
                    client.delete(sess_loc)
                except Exception:
                    pass

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FAILED: {e}")
        sys.exit(1)
