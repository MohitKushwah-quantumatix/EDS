# EDS Docker Guide - End to End

Complete guide for running the EDS Generator and EDS Loader using Docker.
Covers installation, images, volumes, configuration, running, and daily automation.

---

## Table of Contents

1. Prerequisites
2. Project Structure
3. Understanding the Two Images
4. Building the Images
5. Volume Mounts - What They Are and Why They Matter
6. Configuration - What to Change for Docker
7. Running EDS Generator
8. Running EDS Loader
9. Full Pipeline - Generator + Loader Together
10. Daily Automation with Windows Task Scheduler
11. docker-compose - One Command to Run Everything
12. Rebuilding After Code Changes
13. Useful Docker Commands Reference
14. Troubleshooting

---

## 1. Prerequisites

Install Docker Desktop from: https://www.docker.com/products/docker-desktop/

After installing, start Docker Desktop and verify:

    docker version      # shows Client and Server info
    docker ps           # shows empty table (no error)

If you see "cannot connect to Docker daemon" - Docker Desktop is not running.
Open it from the Start Menu and wait for the whale icon in taskbar to turn green (~30 seconds).

---

## 2. Project Structure

    EDS/                                  <- root folder
    +-- EDS/                              <- EDS Generator source code
    |   +-- eds/                          <- Python package
    |   +-- run_day.py                    <- main script to run one day
    |   +-- demo.py                       <- demo/batch script
    |   +-- pyproject.toml
    |
    +-- eds_loader/                       <- EDS Loader source code
    |   +-- eds_loader/                   <- Python package
    |   +-- pyproject.toml
    |
    +-- docker/                           <- ALL Docker files live here
        +-- DOCKER_GUIDE.md               <- this file
        +-- docker-compose.yml            <- orchestrates full pipeline
        +-- loader.yaml                   <- loader config for Docker
        +-- .env.example                  <- template for passwords
        +-- .env                          <- YOUR passwords (never commit!)
        +-- logs/                         <- loader logs land here
        +-- eds-generator/
        |   +-- Dockerfile
        |   +-- .dockerignore
        +-- eds-loader/
            +-- Dockerfile
            +-- .dockerignore

---

## 3. Understanding the Two Images

A Docker image is a self-contained, portable package with Python + your code + all dependencies.
Build it once, run it anywhere. No pip install, no virtual environments, no setup on each machine.

### eds-generator:latest

Contains: Python 3.12 + polars + pydantic + faker + typer + pyyaml + the eds package
Purpose:  Run EDS simulation for one day -> produce Parquet files + schema.json
Does NOT contain: project data, config files, or output folders (mounted at runtime)

### eds-loader:latest

Contains: Python 3.12 + polars + psycopg + pymysql + pymongo + boto3 + azure + gcs + paramiko + eds_loader
Purpose:  Read Parquet files from source -> write rows to a target database
Does NOT contain: loader.yaml config, passwords, or log files (all mounted at runtime)

KEY RULE: Images contain CODE only. Data, configs, and passwords are kept outside
the image and injected at runtime via volume mounts and environment variables.

---

## 4. Building the Images

Always run build commands from the EDS/ root folder:

    cd "C:\Users\Mohit Patel\Downloads\EDS"

    # Build EDS Loader image
    docker build -t eds-loader:latest -f docker/eds-loader/Dockerfile eds_loader/

    # Build EDS Generator image
    docker build -t eds-generator:latest -f docker/eds-generator/Dockerfile EDS/

Understanding the command:

    docker build   -t eds-loader:latest   -f docker/eds-loader/Dockerfile   eds_loader/
                   ^^^^^^^^^^^^^^^^^^^    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^   ^^^^^^^^^^^
                   name:tag               Dockerfile location                build context
                   (what to call it)      (instructions)                     (source files)

Build times:
  - First build ever:          3-8 minutes (downloads Python base image from internet)
  - Re-build after code change: 30-60 seconds (layers cached)
  - Re-build after dep change:  2-4 minutes (pip reinstall)

Verify images exist:

    docker images

    Expected output:
    REPOSITORY       TAG       SIZE
    eds-loader       latest    1.17 GB
    eds-generator    latest    1.81 GB

---

## 5. Volume Mounts

### What is a volume mount?

A volume mount (-v) connects a folder or file on your machine to a path inside the container.
Without mounts, anything written inside the container is LOST when it exits.

    Your machine:                       Container:
    C:\...\my-shop    <----------->    /app/my-shop
    C:\...\loader.yaml <---------->    /config/loader.yaml
    C:\...\logs\      <----------->    /app/logs

Syntax: -v "host_path:container_path"

### Volumes needed for Generator

    Host Path                         Container Path      Required
    -----------------------------------------------------------------------
    EDS\EDS\my-shop                   /app/my-shop        YES (retail)
    EDS\EDS\my-hospital               /app/my-hospital    YES (healthcare)

The generator WRITES output Parquet files and schema.json into this folder.
Without this mount, all generated data disappears when the container exits.

### Volumes needed for Loader

    Host Path                         Container Path        Required
    -----------------------------------------------------------------------
    your loader.yaml file             /config/loader.yaml   YES
    EDS\EDS\my-shop\output            /app/output           YES (source data)
    docker\logs\                      /app/logs             Recommended

loader.yaml is NEVER baked into the image. Always injected at runtime.
This lets you use the same image for PostgreSQL, MySQL, MongoDB - just swap the config.

---

## 6. Configuration - What to Change for Docker

### Source path in loader.yaml

    # On your machine (without Docker):
    source:
      path: C:\Users\Mohit Patel\Downloads\EDS\EDS\my-shop\output

    # Inside Docker - use the container path:
    source:
      path: /app/output

### Database host in loader.yaml

    # Without Docker - DB on your PC:
    target:
      host: localhost

    # With Docker - DB on your PC:
    target:
      host: host.docker.internal    <- special Docker name that reaches your machine

    # With Docker - DB in docker-compose:
    target:
      host: postgres                <- the service name from docker-compose.yml

IMPORTANT: This is the most common mistake. Inside a container, "localhost"
means the container itself - NOT your machine. Always use host.docker.internal
when your database is installed on your PC.

### Log paths in loader.yaml

    # Inside Docker:
    metrics_file: /app/logs/run_metrics.json
    run_log_file: /app/logs/run_history.jsonl

### Passwords - NEVER hardcode

    # WRONG - never do this:
    target:
      password: my_secret_password

    # CORRECT - use environment variable:
    target:
      password_env: DB_PASSWORD     # set via -e DB_PASSWORD=... at runtime

### Pre-configured docker/loader.yaml

The file at docker/loader.yaml is already configured correctly for Docker:
  - Source path: /app/output (the mounted volume)
  - DB host: postgres (docker-compose service name)
  - Password: via DB_PASSWORD environment variable
  - Load mode: append (DB grows day by day)
  - Logs: /app/logs/

For running against your local PostgreSQL: copy it, name it loader-local.yaml,
and change host to host.docker.internal.

---

## 7. Running EDS Generator

### Run one day - retail

    docker run --rm `
      -v "C:\Users\Mohit Patel\Downloads\EDS\EDS\my-shop:/app/my-shop" `
      eds-generator:latest `
      python run_day.py --domain retail --date 2026-01-01

### Run one day - healthcare

    docker run --rm `
      -v "C:\Users\Mohit Patel\Downloads\EDS\EDS\my-hospital:/app/my-hospital" `
      eds-generator:latest `
      python run_day.py --domain healthcare --date 2026-01-01

### Explaining the command

    docker run                    = start a new container
      --rm                        = delete container after it finishes (keeps things clean)
      -v "host:container"         = mount folder from your machine into the container
      eds-generator:latest        = which image to use
      python run_day.py ...       = command to run inside the container

### What gets written after running

    EDS\EDS\my-shop\
      output\
        customers.parquet         <- all table data
        orders.parquet
        products.parquet
        ... (all tables)
      schema.json                 <- table structure (loader needs this)
      daily_checkpoint.json       <- tracks last completed day

### Run multiple days in a loop

    $start = [datetime]"2026-01-01"
    $end   = [datetime]"2026-03-31"

    for ($d = $start; $d -le $end; $d = $d.AddDays(1)) {
        $dateStr = $d.ToString("yyyy-MM-dd")
        Write-Host "=== Generating: $dateStr ==="
        docker run --rm `
          -v "C:\Users\Mohit Patel\Downloads\EDS\EDS\my-shop:/app/my-shop" `
          eds-generator:latest `
          python run_day.py --domain retail --date $dateStr
    }

---

## 8. Running EDS Loader

### Against your local PostgreSQL (most common)

First create docker\loader-local.yaml:

    source:
      kind: local_fs
      path: /app/output
      format: parquet

    target:
      kind: postgres
      host: host.docker.internal   <- YOUR machine's PostgreSQL
      port: 5432
      database: eds_db
      user: eds
      password_env: DB_PASSWORD
      schema: public

    load_mode: append

    metrics_file: /app/logs/run_metrics.json
    run_log_file: /app/logs/run_history.jsonl

Then run:

    New-Item -ItemType Directory -Force -Path "C:\Users\Mohit Patel\Downloads\EDS\docker\logs"

    docker run --rm `
      -v "C:\Users\Mohit Patel\Downloads\EDS\EDS\my-shop\output:/app/output" `
      -v "C:\Users\Mohit Patel\Downloads\EDS\docker\loader-local.yaml:/config/loader.yaml" `
      -v "C:\Users\Mohit Patel\Downloads\EDS\docker\logs:/app/logs" `
      -e DB_PASSWORD=your_actual_password `
      eds-loader:latest `
      run -c /config/loader.yaml

### Against MySQL

    target:
      kind: mysql
      host: host.docker.internal
      port: 3306
      database: eds_db
      user: root
      password_env: DB_PASSWORD

### Against MongoDB

    target:
      kind: mongodb
      host: host.docker.internal
      port: 27017
      database: eds_db

### All available loader commands inside Docker

    # Run the load
    docker run --rm [volumes] eds-loader:latest run -c /config/loader.yaml

    # Preview - no data written
    docker run --rm [volumes] eds-loader:latest run -c /config/loader.yaml --dry-run

    # Validate config file
    docker run --rm -v ".\loader.yaml:/config/loader.yaml" eds-loader:latest validate -c /config/loader.yaml

    # Check status and last run
    docker run --rm [volumes] eds-loader:latest status -c /config/loader.yaml

    # View run history
    docker run --rm [volumes] eds-loader:latest history -c /config/loader.yaml

    # Show what would change (incremental mode)
    docker run --rm [volumes] eds-loader:latest diff -c /config/loader.yaml

    # Reset incremental state
    docker run --rm [volumes] eds-loader:latest reset -c /config/loader.yaml --force

    # Show installed connectors
    docker run --rm eds-loader:latest connectors

    # Version
    docker run --rm eds-loader:latest --version

---

## 9. Full Pipeline - Generator + Loader Together

Run these two commands to complete one full day:

    # Step 1: Generate data for a date
    docker run --rm `
      -v "C:\Users\Mohit Patel\Downloads\EDS\EDS\my-shop:/app/my-shop" `
      eds-generator:latest `
      python run_day.py --domain retail --date 2026-01-15

    # Step 2: Load into your database
    docker run --rm `
      -v "C:\Users\Mohit Patel\Downloads\EDS\EDS\my-shop\output:/app/output" `
      -v "C:\Users\Mohit Patel\Downloads\EDS\docker\loader-local.yaml:/config/loader.yaml" `
      -v "C:\Users\Mohit Patel\Downloads\EDS\docker\logs:/app/logs" `
      -e DB_PASSWORD=your_password `
      eds-loader:latest `
      run -c /config/loader.yaml

After running both:
  - my-shop\output\ has today's fresh Parquet files
  - Your database has the rows inserted (append mode = permanently accumulated)
  - docker\logs\run_metrics.json has load statistics
  - docker\logs\run_history.jsonl has the full run log

---

## 10. Daily Automation with Windows Task Scheduler

### Step 1: Create docker\run_pipeline.ps1

    param(
        [string]$Domain     = "retail",
        [string]$Date       = (Get-Date).ToString("yyyy-MM-dd"),
        [string]$DbPassword = $env:EDS_DB_PASSWORD
    )

    $Root = "C:\Users\Mohit Patel\Downloads\EDS"
    $Dir  = if ($Domain -eq "retail") { "my-shop" } else { "my-hospital" }
    $Log  = "$Root\docker\logs\pipeline-$Date.log"

    function Log($msg) {
        $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        "$ts  $msg" | Tee-Object -FilePath $Log -Append
    }

    Log "=== EDS Pipeline: $Domain / $Date ==="

    Log "Step 1: Generating..."
    docker run --rm `
      -v "${Root}\EDS\${Dir}:/app/${Dir}" `
      eds-generator:latest `
      python run_day.py --domain $Domain --date $Date

    if ($LASTEXITCODE -ne 0) { Log "ERROR: Generator failed"; exit 1 }

    Log "Step 2: Loading..."
    docker run --rm `
      -v "${Root}\EDS\${Dir}\output:/app/output" `
      -v "${Root}\docker\loader-local.yaml:/config/loader.yaml" `
      -v "${Root}\docker\logs:/app/logs" `
      -e "DB_PASSWORD=$DbPassword" `
      eds-loader:latest `
      run -c /config/loader.yaml

    if ($LASTEXITCODE -ne 0) { Log "ERROR: Loader failed"; exit 1 }
    Log "=== Pipeline done ==="

### Step 2: Register with Task Scheduler (run as Administrator)

    $action = New-ScheduledTaskAction `
      -Execute "powershell.exe" `
      -Argument "-NonInteractive -File C:\Users\Mohit Patel\Downloads\EDS\docker\run_pipeline.ps1"

    $trigger = New-ScheduledTaskTrigger -Daily -At "02:00AM"

    Register-ScheduledTask `
      -TaskName "EDS-Daily-Pipeline" `
      -Action $action `
      -Trigger $trigger `
      -RunLevel Highest `
      -Force

### Manage the task

    # Run now to test
    Start-ScheduledTask -TaskName "EDS-Daily-Pipeline"

    # Check status
    Get-ScheduledTask -TaskName "EDS-Daily-Pipeline" | Select TaskName, State

    # Remove
    Unregister-ScheduledTask -TaskName "EDS-Daily-Pipeline" -Confirm:$false

---

## 11. docker-compose - One Command to Run Everything

docker-compose defines all services (PostgreSQL, Generator, Loader) in one file.

### Setup

    cd "C:\Users\Mohit Patel\Downloads\EDS\docker"
    Copy-Item .env.example .env
    notepad .env       <- set your password here

.env file:

    POSTGRES_USER=eds
    POSTGRES_PASSWORD=change_me_please
    POSTGRES_DB=eds_db

### Start PostgreSQL

    docker compose up postgres -d
    docker compose ps    <- wait until Status = healthy (~10 seconds)

### Run one day of full pipeline

    docker compose run generator python run_day.py --domain retail --date 2026-01-01
    docker compose run loader run -c /config/loader.yaml

### Stop everything

    docker compose down        <- stop containers, keep data
    docker compose down -v     <- stop and delete volumes (LOSES DB data!)

---

## 12. Rebuilding After Code Changes

When you change source code in EDS/ or eds_loader/, rebuild the image:

    # Rebuild loader
    docker build -t eds-loader:latest -f docker/eds-loader/Dockerfile eds_loader/

    # Rebuild generator
    docker build -t eds-generator:latest -f docker/eds-generator/Dockerfile EDS/

    # Force rebuild (ignore all cache)
    docker build --no-cache -t eds-generator:latest -f docker/eds-generator/Dockerfile EDS/

### When to rebuild vs when not to

    Change made                                        Rebuild needed?
    -----------------------------------------------------------------------
    Changed Python code in eds/ or eds_loader/         YES
    Added a new Python dependency to pyproject.toml    YES
    Changed loader.yaml config                         NO  (just remount)
    Changed database password                          NO  (just update -e)
    Changed the date to simulate                       NO  (just pass new --date)

---

## 13. Useful Commands Reference

    # Images
    docker images                          # list all images
    docker rmi eds-loader:latest           # delete image
    docker image prune                     # delete unused images

    # Containers
    docker ps                              # running containers
    docker ps -a                           # all containers including stopped
    docker container prune                 # delete all stopped containers

    # Logs
    docker logs eds-loader                 # last logs of named container
    docker logs -f eds-loader              # follow live logs

    # Debug - enter a container
    docker run --rm -it eds-loader:latest bash
    # Inside: eds-loader --help, ls /app, cat /config/loader.yaml, exit

    docker run --rm -it eds-generator:latest bash
    # Inside: python run_day.py --help, ls /app, exit

    # Disk usage
    docker system df                       # show disk used by Docker
    docker system prune                    # clean up unused resources

---

## 14. Troubleshooting

### Cannot connect to Docker daemon

    error: open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file

Fix: Open Docker Desktop from Start Menu. Wait ~30 seconds for whale icon to turn green.

---

### Connection refused to database

    psycopg.OperationalError: connection refused

Cause: localhost inside container points to the container itself, not your PC.

Fix - change in loader.yaml:
    host: host.docker.internal    # when DB is on your PC
    host: postgres                # when DB is in docker-compose

---

### schema.json not found

Cause: Generator has not run yet, or wrong volume path.

Fix: Run generator first. Check:
    ls "C:\Users\Mohit Patel\Downloads\EDS\EDS\my-shop\"
    # Should show: schema.json, daily_checkpoint.json, output\

Note: schema.json is in my-shop/ NOT in my-shop/output/

---

### Output files missing after generator runs

Cause: Volume not mounted - data written inside container then lost on exit.

Fix: Always include -v "...\my-shop:/app/my-shop" in the generator command.

---

### Code changes not reflected in container

Cause: Docker cached the old image.

Fix:
    docker build --no-cache -t eds-generator:latest -f docker/eds-generator/Dockerfile EDS/

---

### Port 5432 already in use

Cause: PostgreSQL running on your machine AND docker-compose tries to expose port 5432.

Fix: In docker-compose.yml change:
    ports:
      - "5433:5432"     # use port 5433 on your host instead

---

## Quick Reference Card

BUILD (from EDS/ root):
  docker build -t eds-loader:latest    -f docker/eds-loader/Dockerfile    eds_loader/
  docker build -t eds-generator:latest -f docker/eds-generator/Dockerfile EDS/

GENERATE ONE DAY:
  docker run --rm -v ".\EDS\my-shop:/app/my-shop" eds-generator:latest python run_day.py --domain retail --date 2026-01-01

LOAD INTO DATABASE:
  docker run --rm -v ".\EDS\my-shop\output:/app/output" -v ".\docker\loader-local.yaml:/config/loader.yaml" -v ".\docker\logs:/app/logs" -e DB_PASSWORD=xxx eds-loader:latest run -c /config/loader.yaml

VALIDATE CONFIG:
  docker run --rm -v ".\docker\loader.yaml:/config/loader.yaml" eds-loader:latest validate -c /config/loader.yaml

ALL COMMANDS:
  docker run --rm eds-loader:latest --help
  docker run --rm eds-generator:latest python run_day.py --help