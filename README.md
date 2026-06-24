# auto-check-in

集中管理当前使用的自动签到：

- GitHub Actions 云端运行：BMAPI、Ranmeng、aiapi1
- Windows 本地计划任务运行：AnyRouter

本地敏感文件不会提交到 GitHub：

- `accounts.json`
- `checkin.log`
- `launcher-error.log`
- `.venv/`

## Local AnyRouter

本地任务入口：

```powershell
C:\Users\tpf\auto-check-in\run.ps1
```

计划任务：

```powershell
Get-ScheduledTask -TaskName "AnyRouter Checkin"
Get-ScheduledTaskInfo -TaskName "AnyRouter Checkin"
```

本地账号文件格式：

```json
[
  {
    "name": "AnyRouter-xxxxx",
    "provider": "anyrouter",
    "cookies": {
      "session": "..."
    },
    "api_user": "xxxxx"
  }
]
```

AnyRouter 有浏览器/WAF 验证，本地脚本会使用 Playwright 先预热 WAF cookie，再执行签到。

## Cloud Check-Ins

云端 workflow：

```text
.github/workflows/cloud-checkin.yml
```

需要的 GitHub secrets：

- `API_SITES_ACCOUNTS`
- `BMAPI_ACCOUNTS`
- `GH_PAT`

`BMAPI_ACCOUNTS` 会在签到后写回更新后的 token。

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_anyrouter_local_checkin.py -q
.\.venv\Scripts\python.exe -m py_compile scripts\anyrouter_local_checkin.py scripts\api_sites_checkin.py scripts\bmapi_checkin.py
.\run.ps1
```
