Redfish-Batcher v0.5b

Works only with .csv files (example included)

how-to use: 
python3 -m pip install -r requirements.txt
python3 -m script.start --csv hosts.csv --login admin --password ChangeMe 

To-do list:
-Parsers(CPU, DIMM, SATA/SAS/NVME, RAID, BIOS)
-Logging(apply --log start env)
-Saving in JSON with SN and timestamps (for system inventory, bios sets etc)
-Compile to macOS(x86_64&aarch64), Linux(x86_64), Win(x86_64)
-Unified launcher and API for netbox
-*not-needed* GUI to clever env