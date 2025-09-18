from __future__ import annotations
from typing import List
import csv, io
from urllib.parse import urlparse
from ..models import Host

def _normalize_base_url(address: str) -> str:
    address = (address or "").strip()
    if not address:
        raise ValueError("Пустой base_url")
    if "://" not in address:
        address = f"https://{address}"
    parsed = urlparse(address)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Некорректный base_url: {address}")
    return f"{parsed.scheme}://{parsed.netloc}"

def load_hosts_csv(path: str, username: str, password: str, verify: bool=False) -> List[Host]:
    raw_content = open(path, "r", encoding="utf-8").read().lstrip("\ufeff")
    lines = [line.strip().rstrip("% \t") for line in raw_content.splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        raise ValueError(f"{path}: файл пуст")

    header = lines[0]
    delimiter = ";" if header.count(";") >= header.count(",") else ","

    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    headers = [header_item.strip().lower() for header_item in next(reader)]
    rows = [[cell.strip() for cell in row] for row in reader]

    base_url_keys = ("base_url", "address", "addr", "host", "ip", "url")
    name_keys = ("name", "hostname", "label")

    hosts: List[Host] = []
    for row_index, row in enumerate(rows, start=2):
        record = dict(zip(headers, row))
        raw_url = next((record[key] for key in base_url_keys if key in record and record[key]), None)
        raw_name = next((record[key] for key in name_keys if key in record and record[key]), None)
        if not raw_url:
            raise ValueError(f"{path}:{row_index}: не указан base_url/address/host/ip (найдены: {headers})")
        hosts.append(Host(
            base_url=_normalize_base_url(raw_url),
            username=username,
            password=password,
            verify=verify,
            name=raw_name or raw_url,
        ))
    return hosts
