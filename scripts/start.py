#!/usr/bin/env python3
import json, asyncio
from typing import List, Dict, Any

import typer
from rich.progress import Progress, BarColumn, TimeRemainingColumn, SpinnerColumn

from redfish_batch import Host, RedfishBatch
from redfish_batch.utils import (
    load_hosts_csv, print_summary, DEFAULT_FORMATS,
    print_cpu_table, print_memory_table, print_raid_table, print_health_table, print_all_table,
    save_all_reports, save_all_csv, print_raid_disks_table, save_raid_disks_csv, save_raid_disks_xlsx,
    print_fans_table, print_accounts_table, print_roles_table, save_accounts_csv, save_accounts_xlsx
)

from scripts.accounts import (
    job_accounts_list, job_accounts_roles, job_account_create,
    job_account_password, job_account_role, job_account_enable, job_account_delete,
)

from scripts.parser_cpu import job_cpu
from scripts.parser_dimm import job_dimm
from scripts.parser_raid import job_raid
from scripts.parser_bios_sets import job_bios_dump
from scripts.parser_healts import job_health
from scripts.insert_fan_sets import job_fan_set
from scripts.bios_apply import apply_bios
from scripts.drop_bmc_sets import job_drop_bmc

app = typer.Typer(add_completion = False)
CHUNK_SIZE_DEFAULT = 48

def chunked(seq: List[Any], n: int) -> List[List[Any]]:
    return [seq[i: i+n] for i in range(0, len(seq), n)]

def load_bios_attrs(path: str) -> dict:
    import json
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    if isinstance(obj, dict) and "Attributes" in obj:
        return obj["Attributes"]
    if isinstance(obj, list) and len(obj) == 1 and isinstance(obj[0], dict) and "Attributes" in obj[0]:
        return obj[0]["Attributes"]
    if not isinstance(obj, dict):
        raise ValueError("Файл с атрибутами должен быть JSON-объектом: {\"Name\":\"Value\", ...}")
    return obj


async def run_with_progress(hosts: List[Host], job, concurrency: int, timeout: int, retries: int, chunk_size: int) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    total = len(hosts)
    with Progress(
        SpinnerColumn(),
        "[progress.description]{task.description}",
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
        "- {task.completed}/{task.total}",
        "-", TimeRemainingColumn(),
        transient=False
    ) as progress:
        overall = progress.add_task("Всего", total = total)
        for i, chunk in enumerate(chunked(hosts, chunk_size), start = 1):
            batch = RedfishBatch(chunk, concurrency = min(concurrency, chunk_size), timeout = timeout, retries = retries)
            t = progress.add_task(f"Чанк {i}", total=len(chunk))
            def on_progress(_):
                progress.advance(t, 1)
                progress.advance(overall, 1)
            part = await batch.run_job(job, on_progress = on_progress)
            results.extend(part)
            progress.remove_task(t)
            await asyncio.sleep(0.4)
    return results

common_opts = [
    typer.Option(..., "--csv", help = "Путь к .csv файлу с ip;hostname"),
    typer.Option(None, "--user", envvar = "BMC_USER", help = "Логин BMC(поддерживается envvar BMC_USER)", show_default = False),
    typer.Option(None, "--password", envvar = "BMC_PASS", help = "Пароль BMC(поддерживается envvar BMC_PASS)", show_default = False),
    typer.Option(False, "--verify", help = "Включить проверку TLS(по умолчанию выключена)"),
    typer.Option(8, "--concurrency", help = "Параллелизм внутри одного чанка (по умолчанию 8)"),
    typer.Option(20, "--timeout", help = "HTTP таймаут, в секундах"),
    typer.Option(3, "--retries", help = "Количество попыток подключения"),
    typer.Option(CHUNK_SIZE_DEFAULT, "--chunk-size", help = "Размер одного чанка (по умолчанию 48)"),
    typer.Option("out.json", "--out", help = "Файл с логами в .json"),
    typer.Option(None, "--format", help="Шаблон строки вывода"),
    typer.Option(False, "--quiet", "--no-summary", help="Не печатать краткую сводку"),
]

@app.command("cpu")
def cmd_cpu(csv: str = common_opts[0], 
            user: str = common_opts[1],
            password: str = common_opts[2],
            verify: bool = common_opts[3],
            concurrency: int = common_opts[4],
            timeout: int = common_opts[5],
            retries: int = common_opts[6],
            chunk_size: int = common_opts[7],
            out: str = common_opts[8],
            form: str = common_opts[9],
            quiet: bool = common_opts[10],
            table_flag: bool = True):
    if not (user and password): 
        raise typer.Exit(code = 2)
    hosts = load_hosts_csv(csv, username = user, password = password, verify = verify)
    results = asyncio.run(run_with_progress(hosts, job_cpu, concurrency, timeout, retries, chunk_size))
    json.dump(results, open(out, "w", encoding = "utf-8"), ensure_ascii = False, indent = 2)
    if not quiet:
        print_cpu_table(results)
    typer.echo(f"Сохранено: {out}")

@app.command("drop-bmc")
def drop_bmc(csv: str = common_opts[0], 
            user: str = common_opts[1],
            password: str = common_opts[2],
            verify: bool = common_opts[3],
            concurrency: int = common_opts[4],
            timeout: int = common_opts[5],
            retries: int = common_opts[6],
            chunk_size: int = common_opts[7],
            out: str = common_opts[8],
            quiet: bool = common_opts[10]):
    if not (user and password): 
        raise typer.Exit(code = 2)
    hosts = load_hosts_csv(csv, username = user, password = password, verify = verify)
    results = asyncio.run(run_with_progress(hosts, job_drop_bmc, concurrency, timeout, retries, chunk_size))
    json.dump(results, open(out, "w", encoding = "utf-8"), ensure_ascii = False, indent = 2)
    typer.echo(f"Сохранено: {out}")

@app.command("dimm")
def cmd_dimm(csv: str = common_opts[0], 
            user: str = common_opts[1],
            password: str = common_opts[2],
            verify: bool = common_opts[3],
            concurrency: int = common_opts[4],
            timeout: int = common_opts[5],
            retries: int = common_opts[6],
            chunk_size: int = common_opts[7],
            out: str = common_opts[8],
            form: str = common_opts[9],
            quiet: bool = common_opts[10],
            table_flag: bool = True):
    if not (user and password): 
        raise typer.Exit(code = 2)
    hosts = load_hosts_csv(csv, username = user, password = password, verify = verify)
    results = asyncio.run(run_with_progress(hosts, job_dimm, concurrency, timeout, retries, chunk_size))
    json.dump(results, open(out, "w", encoding = "utf-8"), ensure_ascii = False, indent = 2)
    if not quiet:
        print_memory_table(results)
    typer.echo(f"Сохранено: {out}")

@app.command("raid")
def cmd_raid(csv: str = common_opts[0], 
            user: str = common_opts[1],
            password: str = common_opts[2],
            verify: bool = common_opts[3],
            concurrency: int = common_opts[4],
            timeout: int = common_opts[5],
            retries: int = common_opts[6],
            chunk_size: int = common_opts[7],
            out: str = common_opts[8],
            fmt: str = common_opts[9],
            quiet: bool = common_opts[10],
            list_disks: bool = typer.Option(False, "--list-disks", help="Показать таблицу всех физических дисков"),
            disks_csv_out: str  = typer.Option(None, "--disks-csv-out", help="Сохранить таблицу дисков в CSV"),
            disks_xlsx_out: str = typer.Option(None, "--disks-xlsx-out", help="Сохранить таблицу дисков в XLSX")):
    if not (user and password): 
        raise typer.Exit(code = 2)
    hosts = load_hosts_csv(csv, username = user, password = password, verify = verify)
    results = asyncio.run(run_with_progress(hosts, job_raid, concurrency, timeout, retries, chunk_size))
    json.dump(results, open(out, "w", encoding = "utf-8"), ensure_ascii = False, indent = 2)
    if not quiet:
        print_raid_table(results)
    if list_disks:
        print_raid_disks_table(results)
    if disks_csv_out:
        save_raid_disks_csv(results, disks_csv_out)
        typer.echo(f"Сохранено: {disks_csv_out}")
    if disks_xlsx_out:
        save_raid_disks_xlsx(results, disks_xlsx_out)
        typer.echo(f"Сохранено: {disks_xlsx_out}")
    typer.echo(f"Сохранено: {out}")

@app.command("bios-dump")
def cmd_bios_dump(csv: str = common_opts[0], 
            user: str = common_opts[1],
            password: str = common_opts[2],
            verify: bool = common_opts[3],
            concurrency: int = common_opts[4],
            timeout: int = common_opts[5],
            retries: int = common_opts[6],
            chunk_size: int = common_opts[7],
            out: str = common_opts[8],
            fmt: str = common_opts[9],
            quiet: bool = common_opts[10]):
    if not (user and password): 
        raise typer.Exit(code = 2)
    hosts = load_hosts_csv(csv, username = user, password = password, verify = verify)
    results = asyncio.run(run_with_progress(hosts, job_bios_dump, concurrency, timeout, retries, chunk_size))
    json.dump(results, open(out, "w", encoding = "utf-8"), ensure_ascii = False, indent = 2)
    if not quiet:
        print("OK:", sum(1 for r in results if r.get("ok")), "| FAIL:", sum(1 for r in results if not r.get("ok")))
    typer.echo(f"Сохранено: {out}")
    
def _load_attrs(path: str) -> dict:
    import json
    obj = json.load(open(path, "r", encoding="utf-8"))
    # если вдруг принесли с обёрткой — снимаем
    if isinstance(obj, dict) and "Attributes" in obj and isinstance(obj["Attributes"], dict):
        obj = obj["Attributes"]
    if not isinstance(obj, dict):
        raise ValueError("--attrs должен быть JSON-объектом {\"Key\":\"Value\", ...}")
    if not obj:
        raise ValueError("--attrs пуст")
    return obj

@app.command("bios-apply")
def cmd_bios_apply(
    csv: str         = common_opts[0],
    user: str        = common_opts[1],
    password: str    = common_opts[2],
    verify: bool     = common_opts[3],
    concurrency: int = common_opts[4],
    timeout: int     = common_opts[5],
    retries: int     = common_opts[6],
    chunk_size: int  = common_opts[7],
    out: str         = common_opts[8],
    attrs_file: str  = typer.Option(..., "--attrs"),
    reboot: bool     = typer.Option(False, "--reboot"),
):
    import asyncio, json
    hosts = load_hosts_csv(csv, username=user, password=password, verify=verify)
    wanted = _load_attrs(attrs_file)

    async def job(client, host):
        return await apply_bios(client, wanted, reboot=reboot)

    results = asyncio.run(run_with_progress(hosts, job, concurrency, timeout, retries, chunk_size))
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    ok = [r for r in results if r.get("ok")]
    bad = [r for r in results if not r.get("ok")]
    for r in ok:
        d = r.get("result") or r
        via = "Settings" if not d.get("used_direct_bios") else "Bios"
        print(f"({r['host']}) applied via {via}, applyTime=OnReset, reboot={d.get('reboot')}")
        if d.get("failed_keys"):
            print("  failed_keys:")
            for fk in d["failed_keys"]:
                print(f"    - {fk['key']}: {fk['reason']}")
    for r in bad:
        print(f"({r['host']}) ERROR: {r.get('error')}")
    typer.echo(f"Сохранено: {out}")

@app.command("health")
def cmd_health(csv: str = common_opts[0], 
            user: str = common_opts[1],
            password: str = common_opts[2],
            verify: bool = common_opts[3],
            concurrency: int = common_opts[4],
            timeout: int = common_opts[5],
            retries: int = common_opts[6],
            chunk_size: int = common_opts[7],
            out: str = common_opts[8],
            fmt: str = common_opts[9],
            quiet: bool = common_opts[10],):
    if not (user and password): 
        raise typer.Exit(code = 2)
    hosts = load_hosts_csv(csv, username = user, password = password, verify = verify)
    results = asyncio.run(run_with_progress(hosts, job_health, concurrency, timeout, retries, chunk_size))
    json.dump(results, open(out, "w", encoding = "utf-8"), ensure_ascii = False, indent = 2)
    if not quiet:
        print_health_table(results)
    typer.echo(f"Сохранено: {out}")

@app.command("fans-set")
def cmd_fans_set(
    csv: str         = common_opts[0],
    user: str        = common_opts[1],
    password: str    = common_opts[2],
    verify: bool     = common_opts[3],
    concurrency: int = common_opts[4],
    timeout: int     = common_opts[5],
    retries: int     = common_opts[6],
    chunk_size: int  = common_opts[7],
    out: str         = common_opts[8],
    min_output: float = typer.Option(100.0, "--min-output", help="MinThermalOutput (0..100)"),
    zone: str         = typer.Option("Main", "--zone", help="Имя фан-зоны (например, Main)"),
    set_failsafe: float | None = typer.Option(None, "--failsafe", help="Опц.: FailSafePercent (0..100)"),
    fmt: str         = typer.Option(None, "--format", "--fmt", help="Шаблон строковой сводки"),
    quiet: bool      = typer.Option(False, "--quiet", "--no-summary", help="Не печатать строковую сводку"),
    table_flag: bool = typer.Option(True, "--table/--no-table", help="Показать таблицу результатов"),
):
    hosts = load_hosts_csv(csv, username=user, password=password, verify=verify)

    async def job(client, host):
        return await job_fan_set(client, host, min_output=min_output, zone=zone, set_failsafe=set_failsafe)

    results = asyncio.run(run_with_progress(hosts, job, concurrency, timeout, retries, chunk_size))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Опциональная строковая сводка
    if not quiet:
        # Простейший шаблон: можно вынести в printer при желании
        for r in [x for x in results if x.get("ok")]:
            host = r.get("host")
            fan = r.get("fan") or {}
            o, n = (fan.get("old") or {}), (fan.get("new") or {})
            print(f"({host}) {fan.get('zone')}: MinOut {o.get('MinThermalOutput')} -> {n.get('MinThermalOutput')}; "
                  f"FailSafe {o.get('FailSafePercent')} -> {n.get('FailSafePercent')}")

    if table_flag:
        print_fans_table(results)

    typer.echo(f"Сохранено: {out}")

@app.command("accounts-list")
def cmd_accounts_list(
    csv: str         = common_opts[0],
    user: str        = common_opts[1],
    password: str    = common_opts[2],
    verify: bool     = common_opts[3],
    concurrency: int = common_opts[4],
    timeout: int     = common_opts[5],
    retries: int     = common_opts[6],
    chunk_size: int  = common_opts[7],
    out: str         = common_opts[8],
    table_flag: bool = typer.Option(True, "--table/--no-table", help="Показать таблицу"),
    accounts_csv: str|None  = typer.Option(None, "--accounts-csv-out", help="Экспорт аккаунтов в CSV"),
    accounts_xlsx: str|None = typer.Option(None, "--accounts-xlsx-out", help="Экспорт аккаунтов в XLSX"),
):
    hosts = load_hosts_csv(csv, username=user, password=password, verify=verify)
    results = asyncio.run(run_with_progress(hosts, job_accounts_list, concurrency, timeout, retries, chunk_size))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    if table_flag:
        print_accounts_table(results)

    if accounts_csv:
        save_accounts_csv(results, accounts_csv)
        typer.echo(f"Сохранено: {accounts_csv}")
    if accounts_xlsx:
        save_accounts_xlsx(results, accounts_xlsx)
        typer.echo(f"Сохранено: {accounts_xlsx}")

    typer.echo(f"Сохранено: {out}")

@app.command("accounts-roles")
def cmd_accounts_roles(
    csv: str         = common_opts[0],
    user: str        = common_opts[1],
    password: str    = common_opts[2],
    verify: bool     = common_opts[3],
    concurrency: int = common_opts[4],
    timeout: int     = common_opts[5],
    retries: int     = common_opts[6],
    chunk_size: int  = common_opts[7],
    out: str         = common_opts[8],
    table_flag: bool = typer.Option(True, "--table/--no-table", help="Показать таблицу"),
):
    hosts = load_hosts_csv(csv, username=user, password=password, verify=verify)
    results = asyncio.run(run_with_progress(hosts, job_accounts_roles, concurrency, timeout, retries, chunk_size))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    if table_flag:
        print_roles_table(results)

    typer.echo(f"Сохранено: {out}")

@app.command("account-create")
def cmd_account_create(
    csv: str         = common_opts[0],
    user: str        = common_opts[1],
    password: str    = common_opts[2],
    verify: bool     = common_opts[3],
    concurrency: int = common_opts[4],
    timeout: int     = common_opts[5],
    retries: int     = common_opts[6],
    chunk_size: int  = common_opts[7],
    out: str         = common_opts[8],
    new_user: str = typer.Option(..., "--new-user", help="Логин для нового пользователя"),
    new_pass: str = typer.Option(..., "--new-pass", help="Пароль для нового пользователя"),
    role: str     = typer.Option("Operator", "--role", help="Указание роли для нового пользователя"),
    enabled: bool = typer.Option(True, "--enabled/--disabled", help="Флаг включен/выключен (по умолчанию включен)"),
):
    hosts = load_hosts_csv(csv, username=user, password=password, verify=verify)
    async def job(client, host):
        return await job_account_create(client, host, user=new_user, password=new_pass, role=role, enabled=enabled)
    results = asyncio.run(run_with_progress(hosts, job, concurrency, timeout, retries, chunk_size))
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    for r in [x for x in results if x.get("ok")]:
        print(f"({r['host']}) created at: {r.get('location') or (r.get('account') or {}).get('@odata.id')}")
    typer.echo(f"Сохранено: {out}")

@app.command("account-passwd")
def cmd_account_passwd(    
    csv: str         = common_opts[0],
    user: str        = common_opts[1],
    password: str    = common_opts[2],
    verify: bool     = common_opts[3],
    concurrency: int = common_opts[4],
    timeout: int     = common_opts[5],
    retries: int     = common_opts[6],
    chunk_size: int  = common_opts[7],
    account: str = typer.Option(..., "--account", help="Id или полный URI аккаунта"),
    new_pass: str = typer.Option(..., "--new-pass"),
    out: str = common_opts[8],
):
    hosts = load_hosts_csv(csv, username=user, password=password, verify=verify)
    async def job(client, host):
        return await job_account_password(client, host, account_id_or_uri=account, new_password=new_pass)
    results = asyncio.run(run_with_progress(hosts, job, concurrency, timeout, retries, chunk_size))
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    for r in [x for x in results if x.get("ok")]:
        print(f"({r['host']}) password updated for {r['account']}")
    typer.echo(f"Сохранено: {out}")

@app.command("account-role")
def cmd_account_role(    
    csv: str         = common_opts[0],
    user: str        = common_opts[1],
    password: str    = common_opts[2],
    verify: bool     = common_opts[3],
    concurrency: int = common_opts[4],
    timeout: int     = common_opts[5],
    retries: int     = common_opts[6],
    chunk_size: int  = common_opts[7],
    account: str = typer.Option(..., "--account", help="Имя аккаунта"),
    role: str    = typer.Option(..., "--role", help="Указание роли(Operator, Administator, etc)"),
    out: str = common_opts[8],
):
    hosts = load_hosts_csv(csv, username=user, password=password, verify=verify)
    async def job(client, host):
        return await job_account_role(client, host, account_id_or_uri=account, role=role)
    results = asyncio.run(run_with_progress(hosts, job, concurrency, timeout, retries, chunk_size))
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    for r in [x for x in results if x.get("ok")]:
        print(f"({r['host']}) role={role} set for {r['account']}")
    typer.echo(f"Сохранено: {out}")

@app.command("account-enable")
def cmd_account_enable(    
    csv: str         = common_opts[0],
    user: str        = common_opts[1],
    password: str    = common_opts[2],
    verify: bool     = common_opts[3],
    concurrency: int = common_opts[4],
    timeout: int     = common_opts[5],
    retries: int     = common_opts[6],
    chunk_size: int  = common_opts[7],
    account: str = typer.Option(..., "--account", help="Имя аккаунта"),
    enable: bool = typer.Option(True, "--enable/--disable"),
    out: str = common_opts[8],
):
    hosts = load_hosts_csv(csv, username=user, password=password, verify=verify)
    async def job(client, host):
        return await job_account_enable(client, host, account_id_or_uri=account, enabled=enable)
    results = asyncio.run(run_with_progress(hosts, job, concurrency, timeout, retries, chunk_size))
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    for r in [x for x in results if x.get("ok")]:
        print(f"({r['host']}) {'enabled' if enable else 'disabled'} {r['account']}")
    typer.echo(f"Сохранено: {out}")

@app.command("account-delete")
def cmd_account_delete(    
    csv: str         = common_opts[0],
    user: str        = common_opts[1],
    password: str    = common_opts[2],
    verify: bool     = common_opts[3],
    concurrency: int = common_opts[4],
    timeout: int     = common_opts[5],
    retries: int     = common_opts[6],
    chunk_size: int  = common_opts[7],
    account: str = typer.Option(..., "--account", help="Имя аккаунта"),
    out: str = common_opts[8],
):
    hosts = load_hosts_csv(csv, username=user, password=password, verify=verify)
    async def job(client, host):
        return await job_account_delete(client, host, account_id_or_uri=account)
    results = asyncio.run(run_with_progress(hosts, job, concurrency, timeout, retries, chunk_size))
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    for r in [x for x in results if x.get("ok")]:
        print(f"({r['host']}) deleted {r['account']}")
    typer.echo(f"Сохранено: {out}")

@app.command("all")
def cmd_all(csv: str         = common_opts[0], 
            user: str        = common_opts[1],
            password: str    = common_opts[2],
            verify: bool     = common_opts[3],
            concurrency: int = common_opts[4],
            timeout: int     = common_opts[5],
            retries: int     = common_opts[6],
            chunk_size: int  = common_opts[7],
            out: str         = common_opts[8],
            fmt: str         = common_opts[9],
            quiet: bool      = common_opts[10],
            reports_dir: str = typer.Option("reports", "--reports-dir", help="Куда сохранять per-host JSON отчёты"),
            csv_out: str     = typer.Option(None, "--csv-out", help="Сводный CSV с кратким summary"),):
    if not (user and password): 
        raise typer.Exit(code = 2)
    hosts = load_hosts_csv(csv, username = user, password = password, verify = verify)
    async def job_all(client, host):
        from scripts.parser_cpu import job_cpu
        from scripts.parser_dimm import job_dimm
        from scripts.parser_raid import job_raid
        from scripts.parser_healts import job_health
        cpu = await job_cpu(client, host)
        mem = await job_dimm(client, host)
        raid = await job_raid(client, host)
        health = await job_health(client, host)
        return {"summary": {"cpu": cpu, "memory": mem, "raid": raid, "health": health}}
    results = asyncio.run(run_with_progress(hosts, job_all, concurrency, timeout, retries, chunk_size))
    json.dump(results, open(out, "w", encoding = "utf-8"), ensure_ascii = False, indent = 2)
    if not quiet:
        print_summary(results, mode="all", fmt=fmt)
    print_all_table(results)
    save_all_reports(results, reports_dir=reports_dir)
    if csv_out:
        save_all_csv(results, csv_path=csv_out)
    typer.echo(f"Сохранено: {out}; отчёты: {reports_dir}" + (f"; CSV: {csv_out}" if csv_out else ""))

if __name__ == "__main__":
    app()